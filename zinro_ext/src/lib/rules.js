/* 荒らし判定ルール(純関数)。
 *
 * 1つの発言を調べて、当たったルールと点数を返す。人ごとの点数を合計して、しきい値(既定2点)に
 * 届いたら追放する。1点だけなら警告にとどめる。
 *
 *   glyph(字): マヨビーム(1点)、ジャワ文字(1点)。同じ発言の中では合わせて1点まで。
 *              → 「2回以上投稿したら追放」になる。
 *   paste(貼り付け): ログの貼り付け、定義文・AI文章の貼り付け、入室直後の長文(各1点)。
 *              これらのどれかが当たった発言が、1発言の上限字数に届いていれば、さらに1点(cap)。
 *              貼り付けは上限で途切れるので、貼り付けの根拠が別にあるときだけ強い印として使う。
 *   rate(連投): 同一内容の連投(2点)。
 *
 * 同一文字の連続(「あああああ」)と、短い語句の繰り返しは検知しない。人の発言でも出るため。
 */
(function (root, factory) {
  const api = factory(typeof require === 'function' ? require('./text') : root.ZK.text);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else { root.ZK = root.ZK || {}; root.ZK.rules = api; }
})(typeof globalThis !== 'undefined' ? globalThis : this, function (text) {
  // ---- ルールの定義(設定画面もこれから作る) ----
  const RULES = [
    { id: 'mayo', group: 'glyph', label: 'マヨビーム',
      help: '積み重なった結合記号と、不可視の制御文字の合計',
      params: [{ key: 'threshold', label: '字数', unit: '字以上', min: 3, max: 500 }] },
    { id: 'java', group: 'glyph', label: 'ジャワ文字',
      help: 'ジャワ文字(U+A980〜A9DF)の数',
      params: [{ key: 'threshold', label: '字数', unit: '字以上', min: 1, max: 500 }] },
    { id: 'logpaste', group: 'paste', label: 'ログの貼り付け',
      help: '「名前: 発言」の形が並ぶ(3人以上、または「鯖:」入り)。他人の発言の偽装になる',
      params: [{ key: 'threshold', label: '個数', unit: '個以上', min: 2, max: 50 }] },
    { id: 'wall', group: 'paste', label: '定義文・AI文章の貼り付け',
      help: '長文で、箇条書き・見出し語・定義文・「項目: 説明」が揃い、ゲームの話題ではない',
      params: [
        { key: 'threshold', label: '長さ', unit: '字以上', min: 50, max: 1000 },
        { key: 'structure', label: '構造点', unit: '点以上(4点満点)', min: 1, max: 4 },
      ] },
    { id: 'newcomer', group: 'paste', label: '入室直後の長文',
      help: '入室を見てからの時間に対して、打てない速さの長文',
      params: [
        { key: 'threshold', label: '長さ', unit: '字以上', min: 30, max: 1000 },
        { key: 'maxAgeSec', label: '入室から', unit: '秒以内', min: 10, max: 3600 },
        { key: 'minCps', label: '速さ', unit: '字/秒以上', min: 1, max: 100 },
      ] },
    { id: 'flood', group: 'rate', label: '同一内容の連投',
      help: '同じ発言(3字以上)が短時間に繰り返される',
      params: [
        { key: 'threshold', label: '回数', unit: '回以上', min: 2, max: 50 },
        { key: 'windowSec', label: '期間', unit: '秒以内', min: 3, max: 300 },
      ] },
    { id: 'cap', group: 'bonus', label: '上限ぴったり(加点)',
      help: '貼り付け系が当たった発言が、1発言の上限字数に届いている',
      params: [{ key: 'margin', label: '上限との差', unit: '字以内', min: 0, max: 100 }] },
  ];

  const DEFAULTS = {
    kickPoints: 2,   // 追放する合計点
    windowMin: 30,   // 点の有効期間(分)
    chatCap: 255,    // 1発言の上限字数(貼り付けた2件が253・255字で途切れていた値)
    rules: {
      mayo: { enabled: true, points: 1, threshold: 12 },
      java: { enabled: true, points: 1, threshold: 8 },
      logpaste: { enabled: true, points: 1, threshold: 4 },
      wall: { enabled: true, points: 1, threshold: 200, structure: 3 },
      newcomer: { enabled: true, points: 1, threshold: 120, maxAgeSec: 180, minCps: 5 },
      flood: { enabled: true, points: 2, threshold: 5, windowSec: 15 },
      cap: { enabled: true, points: 1, margin: 10 },
    },
  };

  function num(v, min, max, def) {
    const n = Math.round(Number(v));
    if (!Number.isFinite(n)) return def;
    return Math.min(max, Math.max(min, n));
  }

  /** 保存された設定を、既定値とマージして範囲内に直す。 */
  function normalizeConfig(raw) {
    const src = raw && typeof raw === 'object' ? raw : {};
    const out = {
      kickPoints: num(src.kickPoints, 1, 20, DEFAULTS.kickPoints),
      windowMin: num(src.windowMin, 1, 1440, DEFAULTS.windowMin),
      chatCap: num(src.chatCap, 20, 5000, DEFAULTS.chatCap),
      rules: {},
    };
    for (const meta of RULES) {
      const d = DEFAULTS.rules[meta.id];
      const s = (src.rules && src.rules[meta.id]) || {};
      const r = {
        enabled: typeof s.enabled === 'boolean' ? s.enabled : d.enabled,
        points: num(s.points, 0, 10, d.points),
      };
      for (const p of meta.params) r[p.key] = num(s[p.key], p.min, p.max, d[p.key]);
      out.rules[meta.id] = r;
    }
    return out;
  }

  // ---- 材料の測定 ----
  const GAME_WORDS = ['人狼', '占い', '霊能', '狩人', '狂人', '妖狐', '村人', '共有者', '猫又', '背徳者',
    '吊り', '噛み', '投票', '護衛', '襲撃', '処刑', '役職', 'グレー', '確白', '確黒', 'CO'];
  const HEADINGS = ['特徴', '由来', '概要', '定義', 'まとめ', 'ポイント', '背景', '種類', 'メリット',
    'デメリット', '具体例', '注意点', '歴史', '分類', '原因'];
  const DEFINITION = /^.{1,50}?(?:とは|というのは)[、,]?.{4,120}?(?:のこと|を指|を意味|行為|現象|状態|もの)/s;
  const LABEL = /(?:^|\s)([^\s:：•‣◦▪➤➢]{2,14})[:：]\s*\S/g;

  function charLength(s) {
    return Array.from(String(s == null ? '' : s)).length;
  }

  /** 「名前: 」の形がいくつ並ぶか。参加者名と「鯖」だけを数える(NFKC 後の文字列で)。 */
  function logTokens(nf, names) {
    const set = new Set((names || []).map(text.nfkc).filter((n) => n && n !== '初日犠牲者'));
    set.add('鯖');
    const alt = [...set].sort((a, b) => b.length - a.length).map(text.escapeRegExp).join('|');
    const re = new RegExp(`(?<!\\S)(${alt})\\s*[:：]`, 'gu');
    let tokens = 0, system = false;
    const distinct = new Set();
    for (const m of nf.matchAll(re)) {
      tokens++;
      if (m[1] === '鯖') system = true; else distinct.add(m[1]);
    }
    return { tokens, distinct: distinct.size, system };
  }

  /** 辞書・AI文章らしい構造がいくつ揃うか(0〜4)。 */
  function structureScore(nf, names) {
    const bullets = (nf.match(/[•‣◦▪➤➢]/g) || []).length;
    const numbered = (nf.match(/(?:^|\s)\d{1,2}[.)]\s*\S/g) || []).length;
    const nameSet = new Set((names || []).map(text.nfkc));
    nameSet.add('鯖');
    let labels = 0;
    for (const m of nf.matchAll(LABEL)) {
      if (/^\d+$/.test(m[1]) || nameSet.has(m[1])) continue;
      labels++;
    }
    const heads = HEADINGS.filter((h) => nf.includes(h)).length;
    const signals = {
      bullets: bullets >= 2 || numbered >= 3,
      definition: DEFINITION.test(nf),
      labels: labels >= 3,
      headings: heads >= 2,
    };
    return { score: Object.values(signals).filter(Boolean).length, signals };
  }

  function mentionsName(nf, name) {
    const n = text.nfkc(name);
    if (n.length >= 3) return nf.includes(n);
    if (n.length === 2) return new RegExp(`${text.escapeRegExp(n)}(?:さん|くん|君|ちゃん|>|:)`).test(nf);
    return false;
  }

  /** ゲームの話題か(参加者の名前を呼んでいる、またはゲーム用語が2語以上)。 */
  function topicInfo(nf, names, speaker) {
    const me = text.nfkc(speaker || '');
    const mention = (names || []).some((n) => text.nfkc(n) !== me && mentionsName(nf, n));
    const words = GAME_WORDS.filter((w) => nf.includes(w)).length;
    return { onTopic: mention || words >= 2, mention, words };
  }

  /**
   * @param {string} body
   * @param {{names?:string[], speaker?:string}} [ctx]
   */
  function measure(body, ctx) {
    const c = ctx || {};
    const names = c.names || [];
    const nf = text.nfkc(body);
    return {
      len: charLength(body),
      mayo: text.countMayo(body),
      java: text.countJava(body),
      log: logTokens(nf, names),
      structure: structureScore(nf, names),
      topic: topicInfo(nf, names, c.speaker),
    };
  }

  // ---- 判定 ----
  function hit(id, label, points, detail) {
    return { id, label, points, detail };
  }

  /**
   * 1つの発言を判定する。
   * @param {string} body
   * @param {{names?:string[], speaker?:string, now?:number, firstSeenAt?:number,
   *          recent?:{ts:number,norm:string}[]}} [ctx]
   *   recent: 同じ人の直前までの発言(今回の発言は含めない)。firstSeenAt: 入室を見た時刻(不明なら 0)。
   * @param {object} [cfgIn] 設定(normalizeConfig に通す)
   * @returns {{points:number, hits:{id:string,label:string,points:number,detail:string}[], metrics:object}}
   */
  function evaluate(body, ctx, cfgIn) {
    const cfg = normalizeConfig(cfgIn);
    const c = ctx || {};
    const R = cfg.rules;
    const now = c.now == null ? Date.now() : c.now;
    const m = measure(body, c);
    const hits = [];

    if (R.mayo.enabled && m.mayo.total >= R.mayo.threshold) {
      hits.push(hit('mayo', 'マヨビーム', R.mayo.points,
        `結合記号${m.mayo.stacked}字+不可視${m.mayo.invisible}字`));
    }
    if (R.java.enabled && m.java >= R.java.threshold) {
      hits.push(hit('java', 'ジャワ文字', R.java.points, `${m.java}字`));
    }
    if (R.logpaste.enabled && m.log.tokens >= R.logpaste.threshold && (m.log.distinct >= 3 || m.log.system)) {
      hits.push(hit('logpaste', 'ログの貼り付け', R.logpaste.points,
        `「名前:」${m.log.tokens}個(${m.log.distinct}人${m.log.system ? '+鯖' : ''})`));
    }
    const wallNeed = m.topic.onTopic ? R.wall.structure + 1 : R.wall.structure;
    if (R.wall.enabled && m.len >= R.wall.threshold && m.structure.score >= wallNeed) {
      hits.push(hit('wall', '定義文・AI文章の貼り付け', R.wall.points,
        `${m.len}字・構造${m.structure.score}/4${m.topic.onTopic ? '・話題内' : '・話題外'}`));
    }
    if (R.newcomer.enabled && c.firstSeenAt > 0) {
      const ageMs = Math.max(1000, now - c.firstSeenAt);
      const cps = m.len / (ageMs / 1000);
      if (m.len >= R.newcomer.threshold && ageMs <= R.newcomer.maxAgeSec * 1000 && cps >= R.newcomer.minCps) {
        hits.push(hit('newcomer', '入室直後の長文', R.newcomer.points,
          `入室${Math.round(ageMs / 1000)}秒後に${m.len}字(${cps.toFixed(1)}字/秒)`));
      }
    }
    if (R.flood.enabled && c.recent) {
      const norm = text.normalizeMessage(body);
      if (charLength(norm) >= 3) {
        const since = now - R.flood.windowSec * 1000;
        const same = c.recent.filter((r) => r.ts >= since && r.norm === norm).length + 1;
        if (same >= R.flood.threshold) {
          hits.push(hit('flood', '同一内容の連投', R.flood.points, `${R.flood.windowSec}秒以内に${same}回`));
        }
      }
    }
    const pasted = hits.some((h) => h.id === 'logpaste' || h.id === 'wall' || h.id === 'newcomer');
    if (R.cap.enabled && pasted && m.len >= cfg.chatCap - R.cap.margin) {
      hits.push(hit('cap', '上限ぴったり', R.cap.points, `${m.len}/${cfg.chatCap}字`));
    }

    return { points: totalPoints(hits), hits, metrics: m };
  }

  /** glyph グループは同じ発言の中で1回分(いちばん高い点)だけ数える。 */
  function totalPoints(hits) {
    let sum = 0, glyph = 0;
    for (const h of hits) {
      if (h.id === 'mayo' || h.id === 'java') glyph = Math.max(glyph, h.points);
      else sum += h.points;
    }
    return sum + glyph;
  }

  // ---- 人ごとの点(追放までの積み上げ) ----
  function pruneStrikes(list, now, windowMin) {
    const span = windowMin * 60000;
    return (list || []).filter((s) => now - s.ts <= span);
  }

  function sumStrikes(list) {
    return (list || []).reduce((s, x) => s + (x.points || 0), 0);
  }

  /** 連投判定用の直近発言リストに1件足し、古いものを落とす(新しい配列を返す)。 */
  function pushRecent(recent, now, norm, spanMs) {
    const keep = (recent || []).filter((r) => now - r.ts <= spanMs);
    keep.push({ ts: now, norm });
    return keep;
  }

  function describeHits(hits) {
    return hits.map((h) => `${h.label}(${h.detail})`).join(' + ');
  }

  return {
    RULES, DEFAULTS, normalizeConfig, measure, evaluate, totalPoints,
    pruneStrikes, sumStrikes, pushRecent, describeHits, logTokens, structureScore, topicInfo,
  };
});
