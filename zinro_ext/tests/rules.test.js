const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const rules = require('../src/lib/rules');
const F = require('./fixtures');

const NOW = 1_700_000_000_000;
const ctx = (extra) => Object.assign({ names: F.NAMES, speaker: 'アオイ', now: NOW }, extra || {});
const ids = (r) => r.hits.map((h) => h.id).sort();
const evalMsg = (body, extra, cfg) => rules.evaluate(body, ctx(extra), cfg);

// ---- 依頼どおりに「検知しない」もの ----
test('同一文字・短い語句の繰り返しは検知しない', () => {
  for (const s of ['あ'.repeat(60), 'w'.repeat(120), 'ー'.repeat(80), 'うんうんうんうんうん', 'ワロタワロタワロタワロタ', '！！！！！！！！！！！！']) {
    assert.equal(evalMsg(s).points, 0, s);
  }
});

test('ジャワ文字が1文字あるだけでは追放に向かわない(しきい値未満)', () => {
  assert.equal(evalMsg('こんにちは' + F.java(1)).points, 0);
  assert.equal(evalMsg('꧁' + 'みなさん' + '꧂').points, 0);   // 飾り括弧(U+A9C1/A9C2)
  assert.equal(evalMsg(F.java(7)).points, 0);
});

test('結合記号が1〜数個では検知しない(しきい値未満)', () => {
  assert.equal(evalMsg(F.zalgo('あ', 3)).points, 0);
  assert.equal(evalMsg(F.zalgo('あ', 11)).points, 0);
});

// ---- マヨビーム・ジャワ文字: 字数しきい値と「2回で追放」 ----
test('マヨビームは12字から1点、ジャワ文字は8字から1点', () => {
  const m = evalMsg(F.zalgo('あ', 12));
  assert.deepEqual(ids(m), ['mayo']);
  assert.equal(m.points, 1);
  const j = evalMsg(F.java(8));
  assert.deepEqual(ids(j), ['java']);
  assert.equal(j.points, 1);
});

test('マヨビームとジャワ文字が同じ発言に両方あっても、その発言では1点まで', () => {
  const r = evalMsg(F.zalgo('あ', 30) + F.java(20));
  assert.deepEqual(ids(r), ['java', 'mayo']);
  assert.equal(r.points, 1);
});

test('しきい値は設定で変えられる', () => {
  const cfg = { rules: { java: { threshold: 3 }, mayo: { threshold: 20 } } };
  assert.equal(evalMsg(F.java(3), {}, cfg).points, 1);
  assert.equal(evalMsg(F.zalgo('あ', 19), {}, cfg).points, 0);
  assert.equal(evalMsg(F.zalgo('あ', 20), {}, cfg).points, 1);
});

test('2回目で追放ラインに届く(合計2点)', () => {
  const cfg = rules.normalizeConfig({});
  const strikes = [];
  const post = (body, t) => {
    const r = evalMsg(body, { now: t });
    if (r.points > 0) strikes.push({ ts: t, points: r.points });
    return rules.sumStrikes(rules.pruneStrikes(strikes, t, cfg.windowMin));
  };
  assert.equal(post(F.zalgo('あ', 15), NOW), 1);            // 1回目: 警告まで
  assert.equal(post('普通の発言です', NOW + 5000), 1);        // 普通の発言は増えない
  const total = post(F.java(10), NOW + 60_000);               // 2回目: 別の種類でも合算される
  assert.ok(total >= cfg.kickPoints);
});

test('点の有効期間(既定30分)を過ぎると消える', () => {
  const list = [{ ts: NOW, points: 1 }, { ts: NOW + 29 * 60000, points: 1 }];
  assert.equal(rules.sumStrikes(rules.pruneStrikes(list, NOW + 31 * 60000, 30)), 1);
  assert.equal(rules.sumStrikes(rules.pruneStrikes(list, NOW + 61 * 60000, 30)), 0);
});

// ---- 絵文字などを巻き込まない ----
test('絵文字・濁点(NFD)・タイ語の発言は検知しない', () => {
  assert.equal(evalMsg('❤️'.repeat(40)).points, 0);
  assert.equal(evalMsg('1️⃣2️⃣3️⃣'.repeat(10)).points, 0);
  assert.equal(evalMsg('がぎぐげご'.normalize('NFD').repeat(20)).points, 0);
  assert.equal(evalMsg('สวัสดีครับ ผมชื่อสมชาย ยินดีที่ได้รู้จักครับ'.repeat(4)).points, 0);
});

// ---- ログの貼り付け ----
test('「名前: 発言」が並ぶ貼り付けを検知する(3人以上、または鯖入り)', () => {
  const r = evalMsg(F.LOG_PASTE);
  assert.ok(ids(r).includes('logpaste'), JSON.stringify(r.hits));
  assert.equal(r.metrics.log.system, true);
  assert.ok(r.metrics.log.tokens >= 4);
});

test('少数の引用ではログの貼り付けにならない', () => {
  assert.equal(evalMsg(F.LEGIT_QUOTE).points, 0);
  // 同じ2人だけの4行は、鯖がなければ貼り付けとは見ない
  assert.equal(evalMsg('アオイ: こんにちは ミナト: やあ アオイ: 元気 ミナト: 元気です、ありがとう').points, 0);
  // 参加者でない名前の「X: 」は数えない
  assert.equal(evalMsg('他人: a 別人: b 誰か: c もう一人: d 最後: e').points, 0);
});

test('参加者名が取れていないとログの貼り付けは判定しない', () => {
  const r = rules.evaluate(F.LOG_PASTE, { names: [], speaker: 'アオイ', now: NOW }, {});
  assert.ok(!ids(r).includes('logpaste') || r.metrics.log.distinct < 3);
});

// ---- 定義文・AI文章の貼り付け ----
test('辞書・AI文章の貼り付けを検知する(話題外)', () => {
  for (const body of [F.WALL_BULLETS, F.WALL_NUMBERED]) {
    assert.ok(Array.from(body).length >= 200, `fixture length ${Array.from(body).length}`);
    const r = evalMsg(body);
    assert.ok(ids(r).includes('wall'), JSON.stringify({ hits: r.hits, s: r.metrics.structure }));
    assert.equal(r.metrics.topic.onTopic, false);
  }
});

test('構造が3つでも、ゲームの話題なら貼り付けと見ない(4つ必要)', () => {
  const off = evalMsg(F.WALL_THREE_SIGNALS);
  assert.equal(off.metrics.structure.score, 3);
  assert.ok(ids(off).includes('wall'));
  const on = evalMsg(F.WALL_THREE_SIGNALS + ' 占い師と霊能者の結果も気になります。');
  assert.equal(on.metrics.topic.onTopic, true);
  assert.ok(!ids(on).includes('wall'));
});

test('普通の長い発言(推理・雑談)は検知しない', () => {
  for (const body of [F.LEGIT_ANALYSIS, F.LEGIT_CHAT]) {
    assert.ok(Array.from(body).length >= 200);
    assert.equal(evalMsg(body).points, 0, body.slice(0, 20));
  }
});

test('長さが足りなければ構造が揃っていても検知しない', () => {
  assert.equal(evalMsg(F.WALL_BULLETS.slice(0, 120)).points, 0);
});

// ---- 上限ぴったり(加点)と、実際に出た2つの形 ----
test('貼り付けが上限(255字)で途切れていれば、1発言で2点(追放ライン)に届く', () => {
  const wall = (F.WALL_BULLETS + F.WALL_BULLETS).slice(0, 253);        // 実際の貼り付けも253字だった
  const w = evalMsg(wall);
  assert.deepEqual(ids(w), ['cap', 'wall']);
  assert.equal(w.points, 2);

  const log = (F.LOG_PASTE + ' ' + F.LOG_PASTE + ' ' + F.LOG_PASTE).slice(0, 255);
  const l = evalMsg(log);
  assert.deepEqual(ids(l), ['cap', 'logpaste']);
  assert.equal(l.points, 2);
});

test('貼り付けの根拠がなければ、上限の長さだけでは加点しない', () => {
  const long = (F.LEGIT_CHAT + F.LEGIT_CHAT).slice(0, 255);
  assert.equal(evalMsg(long).points, 0);
});

test('上限に届かない貼り付けは1点(警告まで)', () => {
  const r = evalMsg(F.LOG_PASTE);
  assert.ok(Array.from(F.LOG_PASTE).length < 245);
  assert.equal(r.points, 1);
});

test('上限の字数は設定で変えられる', () => {
  const body = (F.LOG_PASTE + ' ' + F.LOG_PASTE).slice(0, 180);
  assert.equal(evalMsg(body).points, 1);
  assert.equal(evalMsg(body, {}, { chatCap: 185 }).points, 2);
});

// ---- 入室直後の長文 ----
test('入室から短時間で、打てない速さの長文を検知する', () => {
  const body = F.LEGIT_CHAT.slice(0, 150);
  const fast = evalMsg(body, { firstSeenAt: NOW - 10_000 });          // 15字/秒
  assert.deepEqual(ids(fast), ['newcomer']);
  assert.equal(evalMsg(body, { firstSeenAt: NOW - 100_000 }).points, 0);  // 1.5字/秒: 打てる速さ
  assert.equal(evalMsg(body, { firstSeenAt: NOW - 400_000 }).points, 0);  // 入室から時間が経っている
  assert.equal(evalMsg(body, { firstSeenAt: 0 }).points, 0);              // 入室を見ていない
  assert.equal(evalMsg(body.slice(0, 60), { firstSeenAt: NOW - 3_000 }).points, 0); // 短い
});

// ---- 同一内容の連投 ----
test('同じ発言が15秒以内に5回続くと検知する(2点)', () => {
  const norm = 'こんにちは';
  const recent = (n) => Array.from({ length: n }, (_, i) => ({ ts: NOW - i * 2000, norm }));
  assert.equal(evalMsg(norm, { recent: recent(3) }).points, 0);       // 今回で4回目
  const r = evalMsg(norm, { recent: recent(4) });                      // 今回で5回目
  assert.deepEqual(ids(r), ['flood']);
  assert.equal(r.points, 2);
  const old = Array.from({ length: 4 }, (_, i) => ({ ts: NOW - 60_000 - i, norm }));
  assert.equal(evalMsg(norm, { recent: old }).points, 0);              // 期間外
  assert.equal(evalMsg('はい', { recent: Array.from({ length: 9 }, () => ({ ts: NOW - 1000, norm: 'はい' })) }).points, 0); // 2字は対象外
});

test('pushRecent は古いものを落とす', () => {
  let rec = [];
  rec = rules.pushRecent(rec, NOW, 'a', 15000);
  rec = rules.pushRecent(rec, NOW + 10_000, 'b', 15000);
  rec = rules.pushRecent(rec, NOW + 20_000, 'c', 15000);
  assert.deepEqual(rec.map((r) => r.norm), ['b', 'c']);
});

// ---- 設定の正規化 ----
test('設定は既定値とマージされ、範囲内に直される', () => {
  const d = rules.normalizeConfig(undefined);
  assert.equal(d.kickPoints, 2);
  assert.equal(d.rules.mayo.threshold, 12);
  assert.equal(d.rules.java.threshold, 8);
  const c = rules.normalizeConfig({ kickPoints: 999, windowMin: -5, rules: { mayo: { threshold: 'x', enabled: false }, wall: { structure: 99 } } });
  assert.equal(c.kickPoints, 20);
  assert.equal(c.windowMin, 1);
  assert.equal(c.rules.mayo.threshold, 12);       // 数値でなければ既定値
  assert.equal(c.rules.mayo.enabled, false);
  assert.equal(c.rules.wall.structure, 4);
});

test('無効にしたルールは当たらない', () => {
  const cfg = { rules: { mayo: { enabled: false }, java: { enabled: false } } };
  assert.equal(evalMsg(F.zalgo('あ', 50) + F.java(50), {}, cfg).points, 0);
});

// ---- リポジトリの発言例で誤検知がないこと ----
test('匿名化された発言例(444件)に、既定の設定では1件も当たらない', (t) => {
  const file = path.join(__dirname, '..', '..', 'knowledge', 'examples.jsonl');
  if (!fs.existsSync(file)) return t.skip('knowledge/examples.jsonl がない');
  const utterances = fs.readFileSync(file, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l).utterance);
  assert.ok(utterances.length > 400);
  const names = ['A', 'B', 'C', 'O1', 'O2', 'O3'];
  for (const u of utterances) {
    const r = rules.evaluate(u, { names, speaker: 'B', now: NOW }, {});
    assert.equal(r.points, 0, `${u} => ${rules.describeHits(r.hits)}`);
  }
  // 連続する発言をつないで上限(255字)近い長さにした合成の長文でも当たらない
  let buf = '', joined = 0;
  for (const u of utterances) {
    buf += (buf ? ' ' : '') + u;
    if (Array.from(buf).length >= 245) {
      const r = rules.evaluate(buf.slice(0, 255), { names, speaker: 'B', now: NOW }, {});
      assert.equal(r.points, 0, `${buf.slice(0, 40)} => ${rules.describeHits(r.hits)}`);
      joined++;
      buf = '';
    }
  }
  assert.ok(joined > 20, `joined=${joined}`);
});
