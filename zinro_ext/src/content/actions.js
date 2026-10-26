/* zinro.net への操作。すべて同一オリジンの fetch(外部には出ない)。
 *
 * サイトに負荷をかけないよう、通信は1本のキューで順に行う(参加者API: 1.2秒おき、player.php: 2秒おき)。
 * 待ち時間は sessionStorage の zk_test_gaps(テスト用。JSON で api/player/step/grace を ms で指定)で縮められる。
 */
(function (root) {
  const ZK = (root.ZK = root.ZK || {});
  const { zinro, presets } = ZK;

  function gaps() {
    // grace: 読み込み直後にチャットを判定しない時間(履歴が遅れて描画されるため)
    const g = { api: 1200, player: 2000, step: 1000, grace: 4000 };
    try {
      const o = JSON.parse(sessionStorage.getItem('zk_test_gaps') || 'null');
      if (o && typeof o === 'object') for (const k of Object.keys(g)) if (Number.isFinite(o[k])) g[k] = o[k];
    } catch (e) { /* 既定 */ }
    return g;
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const queue = [];
  const lastAt = { api: 0, player: 0 };
  let running = false;

  const laneOf = (url) => (/\/m\/api\//.test(url) ? 'api' : 'player');

  async function drain() {
    if (running) return;
    running = true;
    try {
      while (queue.length) {
        const job = queue.shift();
        const lane = laneOf(job.url);
        const wait = Math.max(0, gaps()[lane] - (Date.now() - lastAt[lane]));
        if (wait > 0) await sleep(wait);
        try {
          const res = await fetch(job.url, job.init);
          lastAt[lane] = Date.now();
          job.resolve(res);
        } catch (e) {
          lastAt[lane] = Date.now();
          job.reject(e);
        }
      }
    } finally {
      running = false;
    }
  }

  /** キューに積んで順番に fetch する。 */
  function zfetch(url, init) {
    return new Promise((resolve, reject) => {
      if (queue.length >= 30) { reject(new Error('通信待ちが多すぎます')); return; }
      queue.push({ url, init, resolve, reject });
      drain();
    });
  }

  async function ok(res, what) {
    if (!res.ok) throw new Error(`${what}: HTTP ${res.status}`);
    return res;
  }

  async function fetchPlayers() {
    const res = await ok(await zfetch('/m/api/?mode=players', { credentials: 'include' }), '参加者の取得');
    return res.json();
  }

  async function kick(id, name) {
    await ok(await zfetch(zinro.kickPath(id, name), { credentials: 'include' }), '追放');
  }

  async function applyPreset(preset) {
    await ok(await zfetch(presets.presetPath(preset), { method: 'GET', credentials: 'include' }), '配役の変更');
  }

  /**
   * 参加者を観戦に移す。サイトのワードウルフ機能の「お題役」に指定してから解除し、配役を戻す。
   *   1. ワードウルフ ON  2. お題役を対象に指定  3. ワードウルフ OFF  4. 配役を元に戻す
   * 途中で失敗してワードウルフが ON のまま残らないよう、後始末(OFF と配役の復元)を試みる。
   * @param {string} name 対象の名前
   * @param {string|null} restorePath 戻す配役の updateJobset パス
   * @param {(msg:string)=>void} [log]
   */
  async function moveToSpectator(name, restorePath, log) {
    const say = log || (() => {});
    const step = () => sleep(gaps().step);
    const token = async () => {
      const html = await (await ok(await zfetch('/m/player.php', { credentials: 'include' }), 'トークンの取得')).text();
      const t = zinro.extractToken(html);
      if (!t) throw new Error('フォームの token が見つかりません(サイトの作りが変わった可能性)');
      return t;
    };
    const post = async (params, what) => ok(await zfetch('/m/player.php', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams(params).toString(),
    }), what);

    let wordOn = false;
    try {
      say('[1/4] ワードウルフ ON…');
      await post({ token: await token(), mode: 'setWord', is_word: 'on' }, 'ワードウルフ ON');
      wordOn = true;
      await step();
      say(`[2/4] お題役を「${name}」に指定…`);
      await post({ token: await token(), mode: 'updateJobset', job_1: '1', job_8: '0', word_gm: name }, 'お題役の指定');
      await step();
      say('[3/4] ワードウルフ OFF…');
      await post({ token: await token(), mode: 'setWord' }, 'ワードウルフ OFF');
      wordOn = false;
      await step();
      if (restorePath) {
        say('[4/4] 配役を元に戻す…');
        await ok(await zfetch(restorePath, { method: 'GET', credentials: 'include' }), '配役の復元');
      } else {
        say('[4/4] 配役が不明のため、復元はしていません');
      }
    } catch (e) {
      // 後始末: ワードウルフを切り、配役を戻す(失敗しても元のエラーを返す)
      try {
        if (wordOn) await post({ token: await token(), mode: 'setWord' }, 'ワードウルフ OFF(後始末)');
        if (restorePath) await zfetch(restorePath, { method: 'GET', credentials: 'include' });
      } catch (e2) { /* 後始末の失敗は握りつぶす */ }
      throw e;
    }
  }

  ZK.actions = { zfetch, fetchPlayers, kick, applyPreset, moveToSpectator, gaps };
})(globalThis);
