const test = require('node:test');
const assert = require('node:assert/strict');
const z = require('../src/lib/zinro');

test('観戦者の判定', () => {
  assert.ok(z.isSpectator({ job: '観戦者' }));
  assert.ok(z.isSpectator({ job: '見学者' }));
  for (const v of [1, '1', true]) assert.ok(z.isSpectator({ is_spectator: v }));
  for (const v of [0, '0', false, undefined]) assert.ok(!z.isSpectator({ is_spectator: v, job: '村人' }));
  assert.ok(z.isSpectator({ watch: '1' }));
  assert.ok(!z.isSpectator(null));
});

test('初日犠牲者(ダミー)は参加者から除く', () => {
  const data = { players: { 1: { id: 1, name: 'A' }, 2: { id: 2, name: '初日犠牲者' }, 3: { id: 3, name: 'B' } } };
  assert.deepEqual(z.playersOf(data).map((p) => p.name), ['A', 'B']);
  assert.deepEqual(z.playersOf(null), []);
});

test('RMかどうか・開始前かどうか', () => {
  assert.ok(z.amIGm({ room: { gm: 'A' }, player: { name: 'A' } }));
  assert.ok(!z.amIGm({ room: { gm: 'A' }, player: { name: 'B' } }));
  assert.ok(!z.amIGm({ room: {}, player: {} }));
  assert.ok(!z.amIGm(null));
  for (const scene of ['開始前', 'waiting', '0', '']) assert.ok(z.isPregame({ room: { scene } }), scene);
  assert.ok(z.isPregame({ room: { status: '開始前' } }));
  assert.ok(z.isPregame({ room: {} }));
  for (const scene of ['昼', '夜', '終了', '1']) assert.ok(!z.isPregame({ room: { scene } }), scene);
});

test('公開されている酉だけを返す', () => {
  assert.equal(z.publicTrip({ trip: '◆abc', trip_open: '1' }), '◆abc');
  assert.equal(z.publicTrip({ trip: '◆abc', trip_open: '0' }), '');
  assert.equal(z.publicTrip({ trip: '', trip_open: '1' }), '');
  assert.equal(z.publicTrip(null), '');
});

test('名前で参加者を探す(全角半角の違いは吸収するが、大文字小文字は区別する)', () => {
  const ps = [{ name: 'ＡＢＣ' }, { name: 'ミドリ' }];
  assert.equal(z.findByName(ps, 'ミドリ').name, 'ミドリ');
  assert.equal(z.findByName(ps, 'ABC').name, 'ＡＢＣ');         // 全角半角は同じ名前として扱う
  assert.equal(z.findByName(ps, 'abc'), null);                  // 別人かもしれないので、追放の対象にしない
  assert.equal(z.findByName(ps, '不在'), null);
  assert.equal(z.findByName(ps, ''), null);
  // 全角と半角の両方がいるときは、完全一致を先にとる
  assert.equal(z.findByName([{ name: 'ＡＢＣ', id: 1 }, { name: 'ABC', id: 2 }], 'ABC').id, 2);
});

test('KICK の URL は名前を符号化する', () => {
  assert.equal(z.kickPath(12, 'さ くら&'), '/m/player.php?kick=12&name=%E3%81%95%20%E3%81%8F%E3%82%89%26');
});

test('フォームの token を、属性の並びによらず取る', () => {
  assert.equal(z.extractToken('<form><input type="hidden" name="token" value="abc123"></form>'), 'abc123');
  assert.equal(z.extractToken("<input value='f00d' name='token' type=hidden>"), 'f00d');
  assert.equal(z.extractToken('<input name="other" value="x"><input name="token" value="t0k">'), 't0k');
  assert.equal(z.extractToken('<input name="token">'), null);
  assert.equal(z.extractToken('<p>token</p>'), null);
  assert.equal(z.extractToken(null), null);
});

test('発言者名の飾りを外す', () => {
  assert.equal(z.cleanSpeaker('(ミドリ)'), 'ミドリ');
  assert.equal(z.cleanSpeaker('◆ソラ'), 'ソラ');
  assert.equal(z.cleanSpeaker(null), '');
});

test('構造から取れない行は、既知の名前を先頭から探して分ける', () => {
  const names = ['A', 'ABC', 'RE：山田'];
  assert.deepEqual(z.splitChatLine('ABC: こんにちは', names), { speaker: 'ABC', body: 'こんにちは' });      // 長い名前を優先
  assert.deepEqual(z.splitChatLine('A → B : 内緒話', names), { speaker: 'A', body: '内緒話' });
  assert.deepEqual(z.splitChatLine('RE：山田: やあ', names), { speaker: 'RE：山田', body: 'やあ' });         // 名前にコロンを含む
  assert.deepEqual(z.splitChatLine('鯖: Aさんが入室しました', names), { speaker: '鯖', body: 'Aさんが入室しました' });
  assert.equal(z.splitChatLine('知らない人: やあ', names), null);
  assert.equal(z.splitChatLine('', names), null);
});

// ---- 新しい発言の差分 ----
const item = (speaker, body) => ({ key: `${speaker}\u0001${body}`, speaker, body });

test('最初の取り込みで基準を作り、同じ一覧からは新しい発言が出ない', () => {
  const list = [item('B', 'b2'), item('A', 'a1')];
  const first = z.diffNew(list, {});
  assert.equal(first.fresh.length, 2);                       // 基準づくりでは呼び出し側が捨てる
  assert.equal(z.diffNew(list, first.next).fresh.length, 0);  // サイトが一覧を作り直しても増えない
});

test('新しい発言(先頭に足される)だけが古い順で返る', () => {
  const base = z.diffNew([item('B', 'b'), item('A', 'a')], {}).next;
  const r = z.diffNew([item('C', 'c2'), item('C', 'c1'), item('B', 'b'), item('A', 'a')], base);
  assert.deepEqual(r.fresh.map((x) => x.body), ['c1', 'c2']);
});

test('同じ内容の連投も、回数ぶん数える', () => {
  let state = z.diffNew([item('X', 'やあ')], {}).next;
  const spam = (n) => Array.from({ length: n }, () => item('X', 'やあ'));
  for (let n = 2; n <= 5; n++) {
    const r = z.diffNew(spam(n), state);
    assert.equal(r.fresh.length, 1, `n=${n}`);
    state = r.next;
  }
  // 一度にまとめて3件増えたとき
  assert.equal(z.diffNew(spam(8), state).fresh.length, 3);
});

test('古い発言が一覧から消えたあと、同じ内容がまた来たら新しい発言として数える', () => {
  const s1 = z.diffNew([item('X', 'やあ'), item('Y', 'y')], {}).next;
  const s2 = z.diffNew([item('Y', 'y')], s1);                // 「やあ」が一覧から消えた
  assert.equal(s2.fresh.length, 0);
  assert.equal(z.diffNew([item('X', 'やあ'), item('Y', 'y')], s2.next).fresh.length, 1);
});

test('古い順に並ぶ画面にも使える', () => {
  const base = z.diffNew([item('A', 'a'), item('B', 'b')], {}, { newestFirst: false }).next;
  const r = z.diffNew([item('A', 'a'), item('B', 'b'), item('C', 'c1'), item('C', 'c2')], base, { newestFirst: false });
  assert.deepEqual(r.fresh.map((x) => x.body), ['c1', 'c2']);
});
