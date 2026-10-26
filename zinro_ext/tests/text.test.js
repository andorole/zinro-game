const test = require('node:test');
const assert = require('node:assert/strict');
const text = require('../src/lib/text');
const { zalgo, java } = require('./fixtures');

test('積み重なった結合記号を数える(4つ以上の連なりだけ)', () => {
  assert.equal(text.countMayo(zalgo('あ', 12)).total, 12);
  assert.equal(text.countMayo(zalgo('あ', 4)).total, 4);
  // 3つ以下の連なりは数えない(タイ語・ヒンディー語などの母音記号と同じ)
  assert.equal(text.countMayo(zalgo('あ', 3)).total, 0);
  assert.equal(text.countMayo(zalgo('あ', 3).repeat(20)).total, 0);
});

test('複数の文字に分けて積んでも、連なりごとに数える', () => {
  const s = zalgo('a', 5) + zalgo('b', 6) + zalgo('c', 2);
  const r = text.countMayo(s);
  assert.equal(r.stacked, 11);
  assert.equal(r.maxRun, 6);
});

test('不可視の制御文字を数える(ZWJ・タグ文字は数えない)', () => {
  assert.equal(text.countMayo('​'.repeat(12)).invisible, 12);
  assert.equal(text.countMayo('‮'.repeat(3)).invisible, 3);     // 方向上書き
  assert.equal(text.countMayo('‍'.repeat(30)).total, 0);        // ZWJ
  assert.equal(text.countMayo('\u{e0067}\u{e0062}\u{e007f}'.repeat(5)).total, 0); // 旗のタグ
});

test('絵文字・濁点・外国語の通常の記号は巻き込まない', () => {
  assert.equal(text.countMayo('❤️'.repeat(40)).total, 0);               // 異体字選択子 FE0F
  assert.equal(text.countMayo('1️⃣'.repeat(20)).total, 0);               // キーキャップ
  assert.equal(text.countMayo('👨‍👩‍👧‍👦'.repeat(10)).total, 0);           // ZWJ で連結した絵文字
  assert.equal(text.countMayo('がぎぐげござじずぜぞ'.normalize('NFD').repeat(10)).total, 0); // NFD の濁点
  const thai = 'สวัสดีครับ ผมชื่อสมชาย ยินดีที่ได้รู้จักครับ ผู้ใหญ่ใจดี'.repeat(3);
  assert.equal(text.countMayo(thai).total, 0);
  const arabic = 'السَّلَامُ عَلَيْكُمْ وَرَحْمَةُ اللَّهِ'.repeat(3);
  assert.equal(text.countMayo(arabic).total, 0);
});

test('同じ文字の連続は数えない(あああ…)', () => {
  for (const s of ['あ'.repeat(60), 'w'.repeat(100), 'ー'.repeat(80), 'うんうんうんうんうん', 'ワロタワロタワロタ']) {
    assert.equal(text.countMayo(s).total, 0, s);
    assert.equal(text.countJava(s), 0, s);
  }
});

test('ジャワ文字を数える', () => {
  assert.equal(text.countJava(java(1)), 1);
  assert.equal(text.countJava('こんにちは' + java(8) + 'です'), 8);
  assert.equal(text.countJava('日本語だけ'), 0);
  assert.equal(text.countJava(String.fromCodePoint(0xa97f, 0xa9e0)), 0); // ブロックの外
});

test('比較用の正規化と抜粋', () => {
  assert.equal(text.normalizeMessage('  ＡＢＣ　 d\n e '), 'abc d e');
  assert.equal(text.excerpt('あいうえおかきくけこ', 5), 'あいうえお…');
  assert.equal(text.excerpt(zalgo('あ', 20)), 'あ');           // 結合記号は抜粋から落とす
  assert.equal(text.excerpt(null), '');
});

test('null や空でも落ちない', () => {
  assert.deepEqual(text.countMayo(null), { stacked: 0, invisible: 0, total: 0, maxRun: 0 });
  assert.equal(text.countJava(undefined), 0);
});
