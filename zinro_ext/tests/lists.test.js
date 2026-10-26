const test = require('node:test');
const assert = require('node:assert/strict');
const lists = require('../src/lib/lists');

const T1 = 'abcDEF1234';       // 10桁の酉
const T2 = 'Zx9/Qw+k1LmN';     // 12桁の酉
const T3 = 'Pq7Rs8Tu9V';       // 別の10桁の酉
const add = (existing, ...cands) => lists.addEntries(existing, cands, 1000);
const trip = (value, action = 'kick', extra) => Object.assign({ kind: 'trip', value, action }, extra);
const name = (value, action = 'kick', extra) => Object.assign({ kind: 'name', value, action }, extra);

test('酉は先頭の◆の有無を無視して完全一致で照合する', () => {
  const { entries } = add([], trip(`◆${T1}`));
  assert.equal(entries[0].value, T1);
  assert.ok(lists.matchEntry(entries[0], { name: 'x', trip: `◆${T1}` }));
  assert.ok(lists.matchEntry(entries[0], { name: 'x', trip: T1 }));
  assert.ok(!lists.matchEntry(entries[0], { name: 'x', trip: `◆${T1}x` }));     // 部分一致はしない
  assert.ok(!lists.matchEntry(entries[0], { name: 'x', trip: `◆${T1.toLowerCase()}` })); // 大文字小文字は区別
  assert.ok(!lists.matchEntry(entries[0], { name: 'x', trip: '' }));
  assert.ok(!lists.matchEntry(entries[0], { name: 'x' }));
});

test('名前は NFKC・小文字にしたうえでの部分一致', () => {
  const { entries } = add([], name('ＡＢＣ'));
  assert.ok(lists.matchEntry(entries[0], { name: 'abc太郎' }));
  assert.ok(lists.matchEntry(entries[0], { name: 'ｘＡｂＣｙ' }));
  assert.ok(!lists.matchEntry(entries[0], { name: 'あいう' }));
});

test('1文字の名前や酉でない文字列は登録できない', () => {
  const r = add([], name('あ'), trip('abc'), trip('日本語の酉ではない'), name('  '));
  assert.equal(r.added.length, 0);
  assert.equal(r.invalid.length, 4);
});

test('同じ種別・値の再登録は重複、動作が違えば競合として足さない', () => {
  const first = add([], trip(T1, 'kick'));
  const again = add(first.entries, trip(`◆${T1}`, 'kick'), trip(T1, 'spectate'), name('荒らし', 'kick'));
  assert.equal(again.duplicates.length, 1);
  assert.equal(again.conflicts.length, 1);
  assert.equal(again.added.length, 1);
  assert.equal(again.entries.length, 2);
  assert.equal(again.entries.find((e) => e.kind === 'trip').action, 'kick');   // 既存は変わらない
});

test('優先は 除外 > 追放 > 観戦のみ', () => {
  let { entries } = add([], name('ミドリ', 'spectate'));
  const p = { name: 'ミドリ太郎', trip: T1 };
  assert.equal(lists.resolve(p, entries).action, 'spectate');
  entries = add(entries, trip(T1, 'kick')).entries;
  assert.equal(lists.resolve(p, entries).action, 'kick');
  entries = add(entries, name('太郎', 'allow')).entries;
  assert.equal(lists.resolve(p, entries).action, 'allow');
  assert.equal(lists.resolve({ name: '別人', trip: '' }, entries), null);
});

test('取り込み: 酉・サイト表示のままの行・種別指定・名前・メモ・見出し', () => {
  const input = [
    '# コメント',
    '',
    `◆${T1}`,
    `ミドリ (◆${T2})`,
    `trip:${T1.toLowerCase()}xyz`,                 // 酉として読む(形式は正しい)
    'name:荒らし太郎 # 何度も来る',
    '連投の人',
    '[観戦のみ]',
    `${T3}\t荒らしではないが参戦不可`,
    '[除外]',
    '常連さん # 信頼',
  ].join('\n');
  const r = lists.parseImport(input, 'kick');
  assert.deepEqual(r.skipped, []);
  const byValue = Object.fromEntries(r.items.map((i) => [i.value, i]));
  assert.equal(byValue[T1].kind, 'trip');
  assert.equal(byValue[T1].action, 'kick');
  // サイトの表示「名前 (◆酉)」: 酉を取り、名前はメモにする
  assert.equal(byValue[T2].kind, 'trip');
  assert.equal(byValue[T2].note, 'ミドリ');
  assert.equal(byValue['荒らし太郎'].kind, 'name');
  assert.equal(byValue['荒らし太郎'].note, '何度も来る');
  assert.equal(byValue['連投の人'].kind, 'name');
  assert.equal(r.items.filter((i) => i.action === 'spectate').length, 1);
  assert.equal(byValue[T3].action, 'spectate');
  assert.equal(byValue[T3].note, '荒らしではないが参戦不可');
  assert.equal(byValue['常連さん'].action, 'allow');
  assert.equal(byValue['常連さん'].note, '信頼');
});

test('取り込み: ◆なしの英数字は、大文字小文字や数字が混ざるときだけ酉と見なす', () => {
  const r = lists.parseImport(['yamadataro', 'Yamadataro1', '◆yamadataro', 'name:Abcdef1234'].join('\n'), 'kick');
  const kinds = Object.fromEntries(r.items.map((i) => [i.value, i.kind]));
  assert.equal(kinds['yamadataro'] || kinds['yamadataro'], 'trip'); // ◆付きの方
  const plain = r.items.find((i) => i.value === 'yamadataro' && i.kind === 'name');
  assert.ok(plain, '◆なしで小文字だけの語は名前として読む');
  assert.equal(kinds['Yamadataro1'], 'trip');
  assert.equal(kinds['Abcdef1234'], 'name');                         // name: で明示
});

test('取り込み: 解釈できない行は理由つきで返す', () => {
  const r = lists.parseImport('name:あ\ntrip:短い\n', 'kick');
  assert.equal(r.items.length, 0);
  assert.equal(r.skipped.length, 2);
  assert.equal(r.skipped[0].line, 1);
});

test('書き出した文章は、そのまま取り込める', () => {
  const base = add([], trip(T1, 'kick', { note: '荒らし' }), name('連投', 'kick'),
    trip(T2, 'spectate', { note: '参戦不可' }), name('常連', 'allow', { note: '信頼' })).entries;
  const out = lists.formatExport(base);
  assert.ok(out.includes('[追放]') && out.includes('[観戦のみ]') && out.includes('[除外]'));
  assert.ok(out.includes(`◆${T1} # 荒らし`));
  const back = lists.parseImport(out, 'kick');
  assert.deepEqual(back.skipped, []);
  const norm = (xs) => xs.map((x) => `${x.kind}|${x.value}|${x.action}|${x.note}`).sort();
  assert.deepEqual(norm(back.items), norm(base));
});

test('空のリストを書き出しても読める', () => {
  assert.equal(lists.parseImport(lists.formatExport([]), 'kick').items.length, 0);
});
