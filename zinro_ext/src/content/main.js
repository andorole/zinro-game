/* 起動と配線。
 *
 * 流れ:
 *   interceptor が参加者APIの応答を渡す → onPlayers で状態を更新(入室履歴・表のボタン・リスト照合)
 *   チャット欄の変化を監視 → 新しい発言だけを判定 → 点を積む → 届いたら追放(試運転なら記録だけ)
 *
 * 安全のために:
 *   - 試運転(既定ON)では、自動の追放・観戦移動をせず、記録だけ残す。手動の操作は実行する。
 *   - 同じ人への追放・観戦移動は、効かなくても繰り返さない(試行回数に上限)。無限リロードを防ぐ。
 *   - 読み込み直後の数秒は、チャットの履歴が遅れて描画されても判定しない。点が付いた発言はリロードをまたいで覚える。
 *   - RM(村主)でなければ、何も自動では行わない。
 */
(function (root) {
  'use strict';
  if (root.__zkLoaded) return;
  if (!/player\.php/.test(location.pathname)) return;
  root.__zkLoaded = true;

  const ZK = root.ZK;
  const { text, rules, lists, presets, zinro, store, actions } = ZK;

  const SS = {
    strikes: 'zk_strikes_v1', scored: 'zk_scored_v1', history: 'zk_history_v1', firstSeen: 'zk_firstseen_v1',
    log: 'zk_log_v1', attempts: 'zk_attempts_v1', reopen: 'zk_reopen_v1',
  };
  const MAX_ATTEMPTS = 3;         // 同じ人への自動の追放の試行回数
  const MAX_SPECTATE_ATTEMPTS = 2;
  const RECENT_SPAN_MS = 60_000;

  const S = {
    data: null, dataAt: 0, me: '', isRm: false, pregame: true, room: 'room',
    prevNames: new Set(), baselineDone: false,
    firstSeen: store.session.get(SS.firstSeen, {}),
    history: store.session.get(SS.history, []),
    log: store.session.get(SS.log, []),
    strikes: store.session.get(SS.strikes, {}),
    scored: store.session.get(SS.scored, {}),
    attempts: store.session.get(SS.attempts, {}),
    scoredSeen: {},
    processed: {}, chatBaseline: false, scanning: false, scanAgain: false, chatBox: null, chatObserver: null,
    recent: new Map(),
    loadedAt: Date.now(),
    once: new Set(), inflight: new Set(),
    chain: Promise.resolve(), pending: 0, reloadTimer: null, reloadWanted: false,
  };
  let panel = null;
  const ui = () => panel;

  // ---------------------------------------------------------------- 記録・通知
  function log(kind, msg) {
    S.log.push({ ts: Date.now(), kind, text: msg });
    if (S.log.length > 100) S.log.shift();
    store.session.set(SS.log, S.log);
    console.log('[zk]', msg);
    if (panel) panel.refresh();
  }

  function logOnce(key, kind, msg) {
    if (S.once.has(key)) return;
    S.once.add(key);
    log(kind, msg);
  }

  function toast(msg, opt) {
    if (panel) panel.toast(msg, opt);
  }

  /** 同じ人への自動の追放・観戦移動を、実際に実行した回数(照合が走った回数ではない)。 */
  function attemptsOf(key) {
    return S.attempts[`${S.room}|${key}`] || 0;
  }

  function bumpAttempt(key) {
    const k = `${S.room}|${key}`;
    S.attempts[k] = (S.attempts[k] || 0) + 1;
    store.session.set(SS.attempts, S.attempts);
    return S.attempts[k];
  }

  // ---------------------------------------------------------------- 実行キュー・リロード
  /** 追放・配役変更・観戦移動を1つずつ順に行う。 */
  function enqueue(task) {
    S.pending++;
    const run = S.chain.then(task, task);
    S.chain = run.then(() => {}, () => {}).then(() => { S.pending--; maybeReload(); });
    return run;
  }

  function scheduleReload(ms) {
    S.reloadWanted = true;
    S.reloadMs = ms;
    maybeReload();
  }

  function maybeReload() {
    if (!S.reloadWanted || S.reloadTimer) return;
    S.reloadTimer = setTimeout(() => {
      S.reloadTimer = null;
      if (S.pending > 0) { maybeReload(); return; }   // まだ処理が残っていれば待つ
      store.session.set(SS.reopen, panel && panel.isOpen() ? panel.getTab() : null);
      location.reload();
    }, S.reloadMs || 1200);
  }

  // ---------------------------------------------------------------- 参加者の状態
  function onPlayers(data) {
    if (!data || !data.players) return;
    S.data = data;
    S.dataAt = Date.now();
    S.me = (data.player && data.player.name) || '';
    S.isRm = zinro.amIGm(data);
    S.pregame = zinro.isPregame(data);
    S.room = zinro.roomKey(data);
    trackNames(data);
    injectRowButtons();
    ensureChatObserver();
    scheduleListCheck();
    if (panel) panel.refresh();
  }

  async function ensurePlayers(maxAgeMs) {
    if (S.data && Date.now() - S.dataAt < (maxAgeMs == null ? 15000 : maxAgeMs)) return S.data;
    try { onPlayers(await actions.fetchPlayers()); } catch (e) { log('error', `参加者の取得に失敗: ${e.message}`); }
    return S.data;
  }

  /** 入室を見分ける(最初の取得は「もともといた人」として基準にする)。 */
  function trackNames(data) {
    const now = Date.now();
    const players = zinro.playersOf(data);
    const names = new Set(players.map((p) => p.name));
    for (const p of players) {
      if (!S.baselineDone) {
        if (!(p.name in S.firstSeen)) S.firstSeen[p.name] = 0;      // 入室時刻は不明
      } else if (!S.prevNames.has(p.name)) {
        S.firstSeen[p.name] = now;
        S.history.push({ name: p.name, trip: p.trip ? String(p.trip) : '', tripOpen: String(p.trip_open) === '1', ts: now });
        if (S.history.length > 200) S.history.shift();
      }
    }
    S.baselineDone = true;
    S.prevNames = names;
    const keys = Object.keys(S.firstSeen);
    if (keys.length > 400) for (const k of keys.slice(0, keys.length - 400)) delete S.firstSeen[k];
    store.session.set(SS.firstSeen, S.firstSeen);
    store.session.set(SS.history, S.history);
  }

  // ---------------------------------------------------------------- 追放・観戦移動
  async function register(cand, why) {
    const r = await store.addEntries([Object.assign({ note: why || '', source: 'manual' }, cand)]);
    return r;
  }

  /**
   * 追放を実行する。成功したらログ・通知・(希望があれば)リスト登録をして、ページを再読み込みする。
   * @param {object} p 参加者
   * @param {{reason:string, mode:'manual'|'list'|'spam', register?:'trip'|'name'|null}} o
   */
  function doKick(p, o) {
    const key = `kick:${p.name}`;
    if (S.inflight.has(key)) return Promise.resolve(false);
    S.inflight.add(key);
    if (o.mode !== 'manual') bumpAttempt(key);            // 実際に追放を試す回数を数える
    return enqueue(async () => {
      try {
        await actions.kick(p.id, p.name);
        const trip = zinro.publicTrip(p).replace(/^[◆◇]/, '');
        await store.pushKickLog({ ts: Date.now(), name: p.name, trip, reason: o.reason, mode: o.mode });
        log('kick', `${p.name} を追放しました — ${o.reason}`);
        let registered = '';
        if (o.register === 'trip' && trip) {
          const r = await register({ kind: 'trip', value: trip, action: 'kick', source: o.mode === 'manual' ? 'manual' : 'auto' }, o.reason);
          registered = r.added.length ? '酉をリストに登録しました' : '';
        } else if (o.register === 'name') {
          const r = await register({ kind: 'name', value: p.name, action: 'kick', source: o.mode === 'manual' ? 'manual' : 'auto' }, o.reason);
          registered = r.added.length ? '名前をリストに登録しました' : '';
        }
        toast(`${p.name} を追放しました。${registered}`, { kind: 'kick' });
        scheduleReload(1200);
        return true;
      } catch (e) {
        S.inflight.delete(key);
        log('error', `${p.name} の追放に失敗: ${e.message}`);
        toast(`${p.name} の追放に失敗しました: ${e.message}`, { kind: 'error' });
        return false;
      }
    });
  }

  /** 参加者を観戦に移す。manual のときは確認を出す。 */
  async function moveSpectator(name, opts) {
    const o = Object.assign({}, opts);
    await ensurePlayers(5000);
    const p = zinro.findByName(zinro.playersOf(S.data || {}), name);
    if (!p) { toast(`${name} が見つかりません`, { kind: 'error' }); return false; }
    if (!S.isRm) { toast('RMではないため観戦に移せません', { kind: 'error' }); return false; }
    if (!S.pregame) { toast('ゲーム開始前ではないため観戦に移せません', { kind: 'error' }); return false; }
    if (zinro.isSpectator(p)) { toast(`${p.name} はすでに観戦です`, { kind: 'info' }); return false; }
    const preset = store.preset();
    const restore = preset ? presets.findPreset(preset.label) : null;

    if (o.manual) {
      const v = await panel.dialog({
        title: '観戦に移す',
        lines: [
          `${p.name} を観戦に移します。約20秒かかり、終わるとページを再読み込みします。`,
          restore ? `配役は「${restore.label}」に戻します。`
            : '⚠ 配役が未選択のため、移したあと配役が「人狼1」だけの状態で残ります。先に「配役」タブで選ぶことをおすすめします。',
        ],
        buttons: [
          { label: restore ? '観戦に移す' : 'それでも移す', value: 'move', kind: 'primary' },
          { label: '移して「観戦のみ」に登録', value: 'reg' },
          { label: 'キャンセル', value: null },
        ],
      });
      if (!v) return false;
      if (v === 'reg') o.register = true;
    }

    const key = `spec:${p.name}`;
    if (S.inflight.has(key)) return false;
    S.inflight.add(key);
    if (!o.manual) bumpAttempt(key);                      // 実際に移そうとする回数を数える
    return enqueue(async () => {
      try {
        toast(`${p.name} を観戦に移しています…(約20秒)`, { kind: 'info', ttl: 30000 });
        await actions.moveToSpectator(p.name, restore ? presets.presetPath(restore) : null, (m) => panel.setSpectateLog(m));
        log('info', `${p.name} を観戦に移しました${o.reason ? ` — ${o.reason}` : ''}`);
        if (o.register) {
          const pub = zinro.publicTrip(p).replace(/^[◆◇]/, '');
          await register(pub ? { kind: 'trip', value: pub, action: 'spectate' } : { kind: 'name', value: p.name, action: 'spectate' }, '観戦のみ(移動時に登録)');
        }
        panel.setSpectateLog(`✅ ${p.name} を観戦に移しました。ページを更新します…`);
        scheduleReload(800);
        return true;
      } catch (e) {
        S.inflight.delete(key);
        log('error', `${p.name} の観戦移動に失敗: ${e.message}`);
        panel.setSpectateLog(`❌ ${e.message}`);
        toast(`${p.name} の観戦移動に失敗しました: ${e.message}`, { kind: 'error', ttl: 15000 });
        return false;
      }
    });
  }

  // ---------------------------------------------------------------- 参加者表のボタン
  function mkBtn(label, bg, onClick) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = label;
    b.style.cssText = `background:${bg};color:#fff;border:none;border-radius:4px;padding:2px 6px;cursor:pointer;font-size:11px;font-weight:bold;white-space:nowrap;margin-right:2px;`;
    b.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); onClick(); });
    return b;
  }

  async function onKickClick(p) {
    const pub = zinro.publicTrip(p);
    const buttons = [];
    if (pub) buttons.push({ label: '追放して酉をリストへ', value: 'trip', kind: 'danger' });
    buttons.push({ label: pub ? '追放のみ' : '追放', value: 'only', kind: pub ? '' : 'danger' });
    if (!pub) buttons.push({ label: '追放して名前をリストへ', value: 'name' });
    buttons.push({ label: 'キャンセル', value: null });
    const lines = [`${p.name}${pub ? ` (${pub})` : ''} を追放します。`];
    if (!pub) lines.push('酉が公開されていないので、リストには名前でしか登録できません(名前は部分一致のため、短い名前は他の人にも当たります)。');
    const v = await panel.dialog({ title: '追放', lines, buttons });
    if (!v) return;
    await doKick(p, { reason: '手動', mode: 'manual', register: v === 'trip' ? 'trip' : v === 'name' ? 'name' : null });
  }

  function injectRowButtons() {
    const container = document.getElementById('all_players');
    const table = container && container.querySelector('table');
    if (!table) return;
    if (!S.isRm || !S.data) {
      table.querySelectorAll('.zk-head, .zk-cell').forEach((el) => el.remove());
      return;
    }
    const headerRow = table.querySelector('tr');
    if (headerRow && headerRow.querySelector('th') && !headerRow.querySelector('.zk-head')) {
      const th = document.createElement('th');
      th.className = 'zk-head';
      th.style.cssText = 'min-width:96px;text-align:center;font-size:11px;padding:2px;';
      th.textContent = '操作';
      headerRow.appendChild(th);
    }
    const players = zinro.playersOf(S.data);
    for (const row of table.querySelectorAll('tr')) {
      if (row.querySelector('th') || row.querySelector('.zk-cell')) continue;
      const name = zinro.playerRowName(row);
      if (!name) continue;
      const td = document.createElement('td');
      td.className = 'zk-cell';
      td.style.cssText = 'text-align:center;padding:2px;white-space:nowrap;';
      td.addEventListener('click', (e) => e.stopPropagation());
      const p = zinro.findByName(players, name);
      if (p && p.name !== S.me) {
        td.append(mkBtn('追放', 'rgba(190,40,40,.75)', () => onKickClick(p)));
        if (!zinro.isSpectator(p) && S.pregame) td.append(mkBtn('観戦', 'rgba(50,120,190,.8)', () => moveSpectator(p.name, { manual: true })));
      }
      row.appendChild(td);
    }
  }

  // ---------------------------------------------------------------- リストによる自動処理
  let listTimer = null;
  function scheduleListCheck() {
    if (listTimer) return;
    listTimer = setTimeout(() => { listTimer = null; runListEnforcement(); }, 300);
  }

  function describeEntry(e) {
    return `${lists.ACTIONS[e.action]}リスト ${e.kind === 'trip' ? `◆${e.value}` : e.value}${e.note ? `(${e.note})` : ''}`;
  }

  async function runListEnforcement() {
    if (!S.isRm || !S.data || S.pending > 0) return;
    const st = store.settings();
    const entries = store.entries();
    if (!entries.length) return;
    const candidates = zinro.playersOf(S.data).filter((p) => p.name !== S.me)
      .map((p) => ({ p, res: lists.resolve(p, entries) })).filter((x) => x.res && x.res.action !== 'allow');

    const toKick = st.listKick ? candidates.find((x) => x.res.action === 'kick') : null;
    if (toKick) { await autoKick(toKick.p, toKick.res.entry, st); return; }
    const toSpec = st.listSpectate && S.pregame ? candidates.find((x) => x.res.action === 'spectate' && !zinro.isSpectator(x.p)) : null;
    if (toSpec) await autoSpectate(toSpec.p, toSpec.res.entry, st);
  }

  /** 追放を何度試しても在室している。無限に繰り返さず、一度だけ知らせて止める。 */
  function giveUpKick(name) {
    if (S.once.has(`giveup-kick:${name}`)) return;
    S.once.add(`giveup-kick:${name}`);
    log('error', `${name} の追放を${MAX_ATTEMPTS}回試しましたが、まだ在室しています。手動で確認してください`);
    toast(`${name} を追放できません(${MAX_ATTEMPTS}回試行)。手動で確認してください`, { kind: 'error', ttl: 0 });
  }

  async function autoKick(p, entry, st) {
    const why = `${describeEntry(entry)}に該当`;
    if (st.dryRun) { logOnce(`dry-kick:${p.name}`, 'dry', `【試運転】${p.name} を追放するところでした — ${why}`); return; }
    if (attemptsOf(`kick:${p.name}`) >= MAX_ATTEMPTS) { giveUpKick(p.name); return; }
    await doKick(p, { reason: why, mode: 'list', register: null });
  }

  async function autoSpectate(p, entry, st) {
    const why = `${describeEntry(entry)}に該当`;
    if (!store.preset()) {
      logOnce(`nopreset:${p.name}`, 'error', `${p.name} は観戦のみリストの人ですが参戦中です。配役が未選択のため、自動では移しません`);
      toast(`${p.name} は観戦のみリストの人ですが参戦中です。「配役」タブで配役を選ぶと、自動で観戦に移せます`, { kind: 'warn', ttl: 15000 });
      return;
    }
    if (st.dryRun) { logOnce(`dry-spec:${p.name}`, 'dry', `【試運転】${p.name} を観戦に移すところでした — ${why}`); return; }
    if (attemptsOf(`spec:${p.name}`) >= MAX_SPECTATE_ATTEMPTS) {
      const msg = `${p.name} の観戦移動を${MAX_SPECTATE_ATTEMPTS}回試しましたが、まだ参戦中です。手動で確認してください`;
      if (!S.once.has(`giveup-spec:${p.name}`)) {
        S.once.add(`giveup-spec:${p.name}`);
        log('error', msg);
        toast(`${p.name} を観戦に移せません(${MAX_SPECTATE_ATTEMPTS}回試行)。手動で確認してください`, { kind: 'error', ttl: 0 });
      }
      return;
    }
    await moveSpectator(p.name, { manual: false, reason: why });
  }

  // ---------------------------------------------------------------- チャット監視と荒らし判定
  function ensureChatObserver() {
    const box = zinro.chatContainer(document) || document.body;
    if (S.chatBox === box) return;
    if (S.chatObserver) S.chatObserver.disconnect();
    S.chatBox = box;
    let timer = null;
    S.chatObserver = new MutationObserver(() => {
      if (timer) return;
      timer = setTimeout(() => { timer = null; scanChat(); }, 120);
    });
    S.chatObserver.observe(box, { childList: true, subtree: true });
    S.processed = {};
    S.chatBaseline = false;
    scanChat();
  }

  async function scanChat() {
    if (S.scanning) { S.scanAgain = true; return; }
    S.scanning = true;
    try {
      do {
        S.scanAgain = false;
        const names = S.data ? zinro.playersOf(S.data).map((p) => p.name) : [];
        const items = zinro.chatItems(document).map((el) => {
          const { speaker, body } = zinro.parseChatItem(el, names);
          return { key: `${speaker}\u0001${body}`, speaker, body };
        }).filter((it) => it.speaker || it.body);
        const { fresh, next } = zinro.diffNew(items, S.processed);
        S.processed = next;
        // 最初の取り込み、および読み込み直後の猶予の間は、履歴として覚えるだけで判定しない
        if (!S.chatBaseline || Date.now() - S.loadedAt < actions.gaps().grace) { S.chatBaseline = true; continue; }
        for (const it of fresh) await judge(it);
      } while (S.scanAgain);
    } catch (e) {
      console.error('[zk] scanChat', e);
    } finally {
      S.scanning = false;
    }
  }

  /** 点が付いた発言を、リロードをまたいで一度しか数えない。 */
  function alreadyScored(key) {
    const room = (S.scored[S.room] = S.scored[S.room] || {});
    S.scoredSeen[key] = (S.scoredSeen[key] || 0) + 1;
    if (S.scoredSeen[key] <= (room[key] || 0)) return true;
    room[key] = S.scoredSeen[key];
    const keys = Object.keys(room);
    if (keys.length > 200) for (const k of keys.slice(0, keys.length - 200)) delete room[k];
    store.session.set(SS.scored, S.scored);
    return false;
  }

  async function judge(it) {
    const st = store.settings();
    const { speaker, body } = it;
    if (!S.isRm || !st.spamEnabled || !speaker || !body) return;
    if (speaker === zinro.SYSTEM_SPEAKER || speaker === S.me) return;
    await ensurePlayers(20000);
    const players = zinro.playersOf(S.data || {});
    const target = zinro.findByName(players, speaker);
    if (!target) return;                                   // すでに退出した人の発言(履歴の描画など)
    const listed = lists.resolve(target, store.entries());
    if (listed && listed.action === 'allow') return;       // 除外リスト

    const now = Date.now();
    const recent = S.recent.get(target.name) || [];
    const res = rules.evaluate(body, {
      names: players.map((p) => p.name), speaker: target.name, now,
      firstSeenAt: S.firstSeen[target.name] || 0, recent,
    }, st.spam);
    S.recent.set(target.name, rules.pushRecent(recent, now, text.normalizeMessage(body), RECENT_SPAN_MS));
    if (res.points <= 0) return;
    if (alreadyScored(it.key)) return;

    const room = (S.strikes[S.room] = S.strikes[S.room] || {});
    const kept = rules.pruneStrikes(room[target.name], now, st.spam.windowMin);
    kept.push({ ts: now, points: res.points, rules: res.hits.map((h) => h.id), excerpt: text.excerpt(body, 24) });
    room[target.name] = kept;
    store.session.set(SS.strikes, S.strikes);
    const total = rules.sumStrikes(kept);
    const what = rules.describeHits(res.hits);

    if (total >= st.spam.kickPoints) {
      const why = `荒らし判定 ${total}点: ${what}`;
      if (st.dryRun) {
        log('dry', `【試運転】${target.name} を追放するところでした — ${why}「${text.excerpt(body, 30)}」`);
        toast(`🧪 試運転: ${target.name} は追放ライン(${total}/${st.spam.kickPoints}点)です — ${what}`, { kind: 'kick', ttl: 12000 });
        return;
      }
      if (attemptsOf(`kick:${target.name}`) >= MAX_ATTEMPTS) { giveUpKick(target.name); return; }
      delete room[target.name];
      store.session.set(SS.strikes, S.strikes);
      await doKick(target, { reason: why, mode: 'spam', register: st.autoRegister ? 'trip' : null });
    } else {
      log('warn', `${target.name}: ${what} → ${total}/${st.spam.kickPoints}点「${text.excerpt(body, 30)}」`);
      toast(`⚠ ${target.name}: ${what}(${total}/${st.spam.kickPoints}点)`, { kind: 'warn' });
    }
  }

  // ---------------------------------------------------------------- UI から呼ばれる操作
  /** 判定テスト用: 貼り付けた文章の中の「名前:」も参加者として扱う。 */
  function guessNames(body) {
    const counts = new Map();
    for (const m of text.nfkc(body).matchAll(/(?<!\S)([^\s:：]{1,12})\s*[:：]/g)) counts.set(m[1], (counts.get(m[1]) || 0) + 1);
    return [...counts].filter(([, n]) => n >= 2).map(([name]) => name);
  }

  function evaluateText(body, speaker) {
    const names = (S.data ? zinro.playersOf(S.data).map((p) => p.name) : []).concat(guessNames(body));
    const sp = speaker || '(テスト)';
    return rules.evaluate(body, { names, speaker: sp, now: Date.now(), firstSeenAt: S.firstSeen[sp] || 0, recent: [] }, store.settings().spam);
  }

  async function setDryRun(on) {
    if (!on) {
      const v = await panel.dialog({
        title: '本番にしますか?',
        lines: ['条件に当たった人を、自動で追放・観戦移動します(リストの人が入室したときと、荒らし判定が追放ラインに届いたとき)。',
          '先に「荒らし」タブの判定テストと、試運転中のログで、誤検知がないか確かめることをおすすめします。'],
        buttons: [{ label: '本番にする', value: true, kind: 'danger' }, { label: 'キャンセル', value: null }],
      });
      if (!v) { panel.render(); return; }
    }
    const s = JSON.parse(JSON.stringify(store.settings()));
    s.dryRun = on;
    await store.setSettings(s);
    log('info', on ? '試運転にしました(自動の追放・観戦移動はしません)' : '本番にしました(自動の追放・観戦移動を行います)');
  }

  async function registerIdentity(id, action, note) {
    const pub = id.trip && id.tripOpen !== false ? String(id.trip).replace(/^[◆◇]/, '') : '';
    const cand = pub ? { kind: 'trip', value: pub } : { kind: 'name', value: id.name };
    const r = await register(Object.assign({ action, source: 'manual' }, cand), note || '');
    const label = lists.ACTIONS[action];
    if (r.added.length) {
      toast(`${id.name} を${label}リストに登録しました(${pub ? '酉' : '名前・部分一致'})`, { kind: 'info' });
    } else if (r.conflicts.length) {
      toast(`${id.name} は別の動作で登録済みです。リストタブで動作を変えてください`, { kind: 'warn' });
    } else if (r.duplicates.length) {
      toast(`${id.name} は${label}リストに登録済みです`, { kind: 'info' });
    } else {
      toast(r.invalid.length ? r.invalid[0].reason : '登録できませんでした', { kind: 'error' });
    }
  }

  const handlers = {
    async applyPreset(p) {
      if (!S.isRm) { toast('RMではないため配役を変えられません', { kind: 'error' }); return false; }
      try {
        await enqueue(() => actions.applyPreset(p));
        await store.setPreset(p);
        log('info', `配役を「${p.label}」に変更しました`);
        scheduleReload(500);
        return true;
      } catch (e) {
        log('error', `配役の変更に失敗: ${e.message}`);
        toast(`配役の変更に失敗しました: ${e.message}`, { kind: 'error' });
        return false;
      }
    },
    moveSpectator,
    setDryRun,
    evaluateText,
    registerHistory: (row, action) => registerIdentity({ name: row.name, trip: row.trip, tripOpen: row.tripOpen }, action, '履歴から'),
    registerLogEntry: (k, action) => registerIdentity({ name: k.name, trip: k.trip, tripOpen: true }, action, `追放ログから(${k.reason})`),
    /**
     * 本番のとき、これから足す追放・観戦のみの項目が、今この村にいる人に当たるなら、実行前に確認する
     * (名前は部分一致なので、短い語を足すと複数人に当たることがある)。
     */
    async confirmAdd(cands) {
      const st = store.settings();
      if (st.dryRun || !S.isRm || !S.data) return true;
      const hits = new Map();
      for (const c of cands) {
        if ((c.action !== 'kick' && c.action !== 'spectate') || lists.validate(c.kind, c.value)) continue;
        if (c.action === 'spectate' && !S.pregame) continue;
        const entry = lists.makeEntry(c);
        for (const p of zinro.playersOf(S.data)) {
          if (p.name === S.me || !lists.matchEntry(entry, p)) continue;
          if (c.action === 'spectate' && zinro.isSpectator(p)) continue;
          const cur = lists.resolve(p, store.entries());
          if (cur && cur.action === 'allow') continue;          // 除外リストの人には当たらない
          hits.set(p.name, c.action);
        }
      }
      if (!hits.size) return true;
      const v = await panel.dialog({
        title: '今いる人に当たります',
        lines: ['本番のため、追加するとすぐに実行されます:']
          .concat([...hits].map(([n, a]) => `・${n} → ${a === 'kick' ? '追放' : '観戦へ移動'}`)),
        buttons: [{ label: '追加して実行', value: true, kind: 'danger' }, { label: 'キャンセル', value: null }],
      });
      return !!v;
    },
    async confirmSimple(msg) {
      return !!(await panel.dialog({ title: '確認', lines: [msg], buttons: [{ label: 'OK', value: true, kind: 'primary' }, { label: 'キャンセル', value: null }] }));
    },
  };

  function getState() {
    return {
      ready: !!S.data, isRm: S.isRm, me: S.me, pregame: S.pregame, room: S.room,
      players: S.data ? zinro.playersOf(S.data) : [],
      history: S.history, log: S.log,
    };
  }

  // ---------------------------------------------------------------- 起動
  async function start() {
    await store.init();
    panel = ZK.ui.create({ getState, handlers });
    panel.mount();
    const reopen = store.session.get(SS.reopen, null);
    if (reopen) { store.session.set(SS.reopen, null); panel.openTab(reopen); }
    root.addEventListener('zk_players', (e) => onPlayers(e.detail));
    store.onChange(() => scheduleListCheck());
    const table = document.getElementById('all_players');
    if (table) {
      new MutationObserver((muts) => { if (muts.some((m) => m.addedNodes.length)) injectRowButtons(); })
        .observe(table, { childList: true, subtree: true });
    }
    ensureChatObserver();
    setTimeout(() => ensurePlayers(), 2500);       // interceptor からの通知が来なければ、自分で一度取る
    log('info', `起動しました(${store.settings().dryRun ? '試運転' : '本番'})`);
  }

  start().catch((e) => console.error('[zk] 起動に失敗', e));
})(globalThis);
