/* リスト管理(純関数)。
 *
 * 1件 = { id, kind: 'trip'|'name', value, action: 'kick'|'spectate'|'allow', note, source, addedAt }
 *   kick     追放: 入室したら追放する
 *   spectate 観戦のみ: 観戦にいるのはよいが、参戦にはしない(参戦していたら観戦へ移す)
 *   allow    除外: 荒らし判定とリストによる自動処理の対象にしない(手動の操作は別)
 * 照合は、酉は完全一致(先頭の◆は無視)、名前は NFKC・小文字にしたうえでの部分一致。
 * 同じ人が複数に当たったときの優先は、除外 > 追放 > 観戦のみ。
 */
(function (root, factory) {
  const api = factory(typeof require === 'function' ? require('./text') : root.ZK.text);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else { root.ZK = root.ZK || {}; root.ZK.lists = api; }
})(typeof globalThis !== 'undefined' ? globalThis : this, function (text) {
  const ACTIONS = { kick: '追放', spectate: '観戦のみ', allow: '除外' };
  const ACTION_BY_LABEL = { 追放: 'kick', 観戦のみ: 'spectate', 観戦: 'spectate', 除外: 'allow' };
  const PRIORITY = ['allow', 'kick', 'spectate'];

  const TRIP_BODY = /^[A-Za-z0-9./+]{8,14}$/;

  function normTrip(s) {
    return String(s == null ? '' : s).trim().replace(/^[◆◇]/, '');
  }

  function normName(s) {
    return text.nfkc(s).toLowerCase().trim();
  }

  /** 重複判定のキー。 */
  function entryKey(e) {
    return `${e.kind}:${e.kind === 'trip' ? normTrip(e.value) : normName(e.value)}`;
  }

  /** 追加前の検査。問題があれば理由の文字列、なければ null。 */
  function validate(kind, value) {
    if (kind === 'trip') {
      return TRIP_BODY.test(normTrip(value)) ? null : '酉は英数字と . / + の8〜14文字で入力してください';
    }
    if (kind === 'name') {
      return Array.from(normName(value)).length >= 2 ? null : '名前は2文字以上で入力してください(短いと多くの人に当たります)';
    }
    return '種別が不正です';
  }

  let seq = 0;
  function newId(now) {
    seq = (seq + 1) % 1e6;
    return `${(now || Date.now()).toString(36)}${seq.toString(36)}`;
  }

  function makeEntry({ kind, value, action, note, source }, now) {
    const t = now == null ? Date.now() : now;
    return {
      id: newId(t),
      kind,
      value: kind === 'trip' ? normTrip(value) : String(value).trim(),
      action,
      note: String(note || '').replace(/\s+/g, ' ').trim(),
      source: source || 'manual',
      addedAt: t,
    };
  }

  /**
   * 既存のリストに足す。同じ種別・値が既にあれば、動作が同じなら重複、違えば競合として足さない。
   * @returns {{entries:object[], added:object[], duplicates:object[], conflicts:object[], invalid:{value:string,reason:string}[]}}
   */
  function addEntries(existing, candidates, now) {
    const entries = existing.slice();
    const index = new Map(entries.map((e) => [entryKey(e), e]));
    const added = [], duplicates = [], conflicts = [], invalid = [];
    for (const c of candidates) {
      const reason = validate(c.kind, c.value);
      if (reason) { invalid.push({ value: c.value, reason }); continue; }
      const entry = makeEntry(c, now);
      const key = entryKey(entry);
      const old = index.get(key);
      if (old) {
        (old.action === entry.action ? duplicates : conflicts).push({ entry, existing: old });
        continue;
      }
      entries.push(entry);
      index.set(key, entry);
      added.push(entry);
    }
    return { entries, added, duplicates, conflicts, invalid };
  }

  function matchEntry(e, player) {
    if (!player) return false;
    if (e.kind === 'trip') {
      const t = normTrip(player.trip);
      return t !== '' && t === normTrip(e.value);
    }
    const kw = normName(e.value);
    return kw !== '' && normName(player.name).includes(kw);
  }

  /** @returns {{action:string, entry:object}|null} 優先: 除外 > 追放 > 観戦のみ */
  function resolve(player, entries) {
    const hits = entries.filter((e) => matchEntry(e, player));
    if (!hits.length) return null;
    for (const a of PRIORITY) {
      const entry = hits.find((e) => e.action === a);
      if (entry) return { action: a, entry };
    }
    return null;
  }

  // ---- 取り込み(貼り付け)と書き出し ----
  const SECTION = /^[[［【]\s*(追放|観戦のみ|観戦|除外)\s*[\]］】]$/;
  const EXPLICIT = /^(trip|酉|トリップ|name|名前)\s*[:：=]\s*(.+)$/i;
  const PAREN_TRIP = /[(（]\s*([◆◇]?[A-Za-z0-9./+]{8,14})\s*[)）]\s*$/;
  const BARE_TRIP = /^[◆◇]?[A-Za-z0-9./+]{10,12}$/;

  /** ◆なしの英数字だけの語は、大文字・小文字・数字記号のうち2種類以上を含むときだけ酉と見なす。 */
  function looksLikeBareTrip(s) {
    if (/^[◆◇]/.test(s)) return BARE_TRIP.test(s);
    if (!BARE_TRIP.test(s)) return false;
    const kinds = [/[a-z]/, /[A-Z]/, /[0-9./+]/].filter((re) => re.test(s)).length;
    return kinds >= 2;
  }

  /**
   * 貼り付けた文章を読む。1行1件。
   *   ◆abcDEF1234              酉
   *   ミドリ (◆abcDEF1234)      サイトの表示のままでも、括弧の中の酉を拾う(名前はメモになる)
   *   trip:abcDEF1234 / name:荒らし   種別を指定
   *   荒らし太郎                名前(部分一致)
   *   末尾に「 # メモ」でメモ。[追放] [観戦のみ] [除外] の行で以降の動作を切り替える。
   *   空行、# か // で始まる行は無視。
   * @returns {{items:{kind:string,value:string,action:string,note:string}[], skipped:{line:number,text:string,reason:string}[]}}
   */
  function parseImport(input, defaultAction) {
    const items = [], skipped = [];
    let action = defaultAction || 'kick';
    const lines = String(input == null ? '' : input).replace(/\r\n?/g, '\n').split('\n');
    lines.forEach((raw, i) => {
      let line = raw.replace(/^﻿/, '').trim();
      if (!line || line.startsWith('//') || line.startsWith('#')) return;
      const sec = SECTION.exec(line);
      if (sec) { action = ACTION_BY_LABEL[sec[1]]; return; }

      let note = '';
      const hash = line.search(/\s#/);
      if (hash >= 0) {
        note = line.slice(hash).replace(/^\s*#\s?/, '').trim();
        line = line.slice(0, hash).trim();
      } else if (line.includes('\t')) {
        const [head, ...rest] = line.split('\t');
        line = head.trim();
        note = rest.join(' ').trim();
      }
      if (!line) return;

      let kind, value;
      const ex = EXPLICIT.exec(line);
      const paren = PAREN_TRIP.exec(line);
      if (ex) {
        kind = /^(trip|酉|トリップ)$/i.test(ex[1]) ? 'trip' : 'name';
        value = ex[2].trim();
      } else if (paren) {
        kind = 'trip';
        value = paren[1];
        if (!note) note = line.slice(0, paren.index).trim();
      } else if (looksLikeBareTrip(line)) {
        kind = 'trip';
        value = line;
      } else {
        kind = 'name';
        value = line;
      }
      const reason = validate(kind, value);
      if (reason) { skipped.push({ line: i + 1, text: raw.trim(), reason }); return; }
      items.push({ kind, value: kind === 'trip' ? normTrip(value) : value, action, note });
    });
    return { items, skipped };
  }

  /** parseImport で読み戻せる形の文章にする。 */
  function formatExport(entries) {
    const out = ['# zinro_ext リスト(貼り付けて取り込めます)'];
    for (const a of PRIORITY) {
      const rows = entries.filter((e) => e.action === a);
      if (!rows.length) continue;
      out.push(`[${ACTIONS[a]}]`);
      for (const e of rows) {
        const v = e.kind === 'trip' ? `◆${normTrip(e.value)}` : `name:${e.value}`;
        out.push(e.note ? `${v} # ${e.note}` : v);
      }
    }
    return out.join('\n') + '\n';
  }

  return {
    ACTIONS, normTrip, normName, entryKey, validate, makeEntry, addEntries,
    matchEntry, resolve, parseImport, formatExport,
  };
});
