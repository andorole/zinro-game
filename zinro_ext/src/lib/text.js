/* 文字種の数え上げ(純関数)。荒らし判定の材料になる。
 *
 * 数えるのは次の2つ。
 *   - マヨビーム: 4つ以上積み重なった結合記号の合計 + 不可視の制御文字の数
 *   - ジャワ文字: ジャワ文字のブロック(U+A980〜U+A9DF)の文字数
 *
 * 誤検知を避けるため、普通の文章や絵文字に出る次のものは数えない。
 *   - 絵文字の異体字選択子(U+FE0F など)、ZWJ(U+200D)、キーキャップ(U+20E3)、旗のタグ文字
 *   - 日本語の濁点・半濁点の結合記号(U+3099, U+309A。NFD の文章に出る)
 *   - 1〜3個の結合記号(タイ語・ヒンディー語・アラビア語の母音記号など)
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else { root.ZK = root.ZK || {}; root.ZK.text = api; }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const MIN_STACK_RUN = 4;
  const RE_MARK = /^[\p{Mn}\p{Me}]$/u;
  const RE_FORMAT = /^\p{Cf}$/u;

  function isExcludedMark(cp) {
    return (cp >= 0x3099 && cp <= 0x309a) ||      // 日本語の濁点・半濁点(結合)
      (cp >= 0xfe00 && cp <= 0xfe0f) ||           // 異体字選択子(絵文字表示など)
      (cp >= 0xe0100 && cp <= 0xe01ef) ||         // 異体字選択子の補助
      cp === 0x20e3;                              // 囲みキーキャップ
  }

  function isCountedInvisible(cp) {
    if (cp === 0x200d) return false;                    // ZWJ(絵文字の連結に使う)
    if (cp >= 0xe0000 && cp <= 0xe007f) return false;   // タグ文字(旗の絵文字)
    return true;
  }

  /** @returns {{stacked:number, invisible:number, total:number, maxRun:number}} */
  function countMayo(text) {
    let run = 0, maxRun = 0, stacked = 0, invisible = 0;
    for (const ch of String(text == null ? '' : text)) {
      const cp = ch.codePointAt(0);
      if (RE_MARK.test(ch) && !isExcludedMark(cp)) {
        run++;
        if (run > maxRun) maxRun = run;
        continue;
      }
      if (run >= MIN_STACK_RUN) stacked += run;
      run = 0;
      if (RE_FORMAT.test(ch) && isCountedInvisible(cp)) invisible++;
    }
    if (run >= MIN_STACK_RUN) stacked += run;
    return { stacked, invisible, total: stacked + invisible, maxRun };
  }

  /** ジャワ文字(U+A980〜U+A9DF)の文字数。 */
  function countJava(text) {
    let n = 0;
    for (const ch of String(text == null ? '' : text)) {
      const cp = ch.codePointAt(0);
      if (cp >= 0xa980 && cp <= 0xa9df) n++;
    }
    return n;
  }

  function nfkc(s) {
    return String(s == null ? '' : s).normalize('NFKC');
  }

  /** 同一内容の比較用: NFKC・小文字・空白をひとつに。 */
  function normalizeMessage(s) {
    return nfkc(s).toLowerCase().replace(/\s+/g, ' ').trim();
  }

  function escapeRegExp(s) {
    return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  /** ログ表示用の短い抜粋。制御文字は落とす。 */
  function excerpt(s, n = 24) {
    const t = String(s == null ? '' : s).replace(/[\p{Cc}\p{Cf}\p{Mn}\p{Me}]/gu, '').replace(/\s+/g, ' ').trim();
    const chars = Array.from(t);
    return chars.length > n ? chars.slice(0, n).join('') + '…' : t;
  }

  return { MIN_STACK_RUN, countMayo, countJava, nfkc, normalizeMessage, escapeRegExp, excerpt };
});
