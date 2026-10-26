/* 実際の拡張を Chromium に読み込み、模擬の zinro.net 上で動かして確かめる。
 * 実行: node --test zinro_ext/tests/e2e/zinro_e2e.test.js   (要 Playwright と Chromium。数分かかる)
 * 実サイトではないので、「模擬サイトの形のとおりに動く」ことの確認であり、実サイトでの動作の証明ではない。 */
const test = require('node:test');
const assert = require('node:assert/strict');
const { createMock } = require('./mock_site');
const H = require('./harness');
const F = require('../fixtures');

const TROLL_TRIP = '◆Xy7Zk9QwEr';
const OPTS = { timeout: 90_000 };

function baseMock(opts) {
  const mock = createMock(opts);
  mock.addPlayer({ name: 'RM', trip: '◆rmTrip12345' });
  mock.addPlayer({ name: 'アオイ' });
  mock.addPlayer({ name: 'ミナト', trip: '◆aBcDeFgHiJ' });
  return mock;
}

async function session(opts, fn) {
  const mock = (opts && opts.mock) || baseMock();
  const env = await H.launch(mock, opts && opts.gaps);
  try {
    await fn(env, mock);
    assert.deepEqual(env.errors, [], '拡張が例外を出した');
    assert.deepEqual(mock.state.external, [], 'zinro.net 以外へ通信した');
  } finally {
    await env.close();
  }
}

const toast = (page, text) => page.locator('.zk-toast', { hasText: text });
const playerGets = (mock) => mock.state.requests.filter((r) => r === 'GET /m/player.php').length;
const waitKick = (mock, n = 1) => H.waitFor(() => mock.state.kicks.length >= n, 12000, `追放が${n}件`);

/** リロードが終わり、拡張が参加者表にボタンを出すまで待つ。 */
async function waitReloaded(env, before) {
  await H.waitFor(() => playerGets(env.mock) > before, 10000, 'ページの再読み込み');
  await env.page.waitForSelector('.zk-launch', { state: 'attached' });
  await H.sleep(200);
}

async function pickPreset(env, label) {
  const before = playerGets(env.mock);
  await H.openPanel(env.page, '配役');
  await env.page.locator('.zk-preset', { hasText: new RegExp(`^${label}$`) }).click();
  await waitReloaded(env, before);
}

test('RMには参加者表に追放・観戦ボタンが出る。RMでなければ出ない', OPTS, async () => {
  await session({}, async (env, mock) => {
    await env.open();
    await H.waitFor(async () => (await env.page.locator('.zk-cell button').count()) === 4, 8000, '2人ぶんの追放・観戦ボタン');
    assert.deepEqual(await env.page.locator('.zk-cell button').allTextContents(), ['追放', '観戦', '追放', '観戦']);
    await H.openPanel(env.page);
    assert.match(await env.page.locator('.zk-banner').textContent(), /試運転中/);

    mock.state.me = 'アオイ';                          // RMではない人として開き直す
    await env.page.reload();
    await env.page.waitForSelector('.zk-launch');
    await H.waitFor(async () => /RMではありません/.test(await env.page.locator('.zk-launch').getAttribute('title') || ''), 8000, '非RM表示');
    assert.equal(await env.page.locator('.zk-cell').count(), 0);
  });
});

test('配役プリセット: updateJobset を送ってリロードし、選択が残ってパネルも開き直る', OPTS, async () => {
  await session({}, async (env, mock) => {
    await env.open();
    await pickPreset(env, '10A狩');
    assert.deepEqual(mock.state.jobsetGets, ['?mode=updateJobset&job_1=2&job_6=1&job_4=1&job_3=1&job_5=1&yakukakenashi=0']);
    // リロード後: パネルが同じタブで開き直され、選んだ配役が強調されている
    await env.page.locator('.zk-preset.zk-active').waitFor();
    assert.equal((await env.page.locator('.zk-preset.zk-active').textContent()).trim(), '10A狩');
  });
});

test('リスト(追放): 試運転では追放せず記録だけ。本番にすると追放し、再読み込み後は増えない', OPTS, async () => {
  await session({}, async (env, mock) => {
    await env.open();
    await H.importList(env.page, `${TROLL_TRIP} # 荒らし`, 'kick');
    await env.page.locator('.zk-msg.zk-good', { hasText: '追加 1件' }).waitFor();
    mock.addPlayer({ name: '荒らし', trip: TROLL_TRIP });
    await H.openPanel(env.page, '荒らし');
    await env.page.locator('.zk-log div', { hasText: '【試運転】荒らし を追放するところでした' }).waitFor({ timeout: 8000 });
    await H.sleep(1200);
    assert.equal(mock.state.kicks.length, 0, '試運転では追放しない');

    await H.goLive(env.page);
    await waitKick(mock, 1);
    assert.deepEqual(mock.state.kicks.map((k) => k.name), ['荒らし']);
    await H.sleep(2500);                                // リロードを挟んでも、もう追放は起きない
    assert.equal(mock.state.kicks.length, 1);
  });
});

test('リスト(追放): 酉は◆の有無によらず一致し、名前は部分一致する', OPTS, async () => {
  await session({}, async (env, mock) => {
    await env.open();
    await H.importList(env.page, 'Xy7Zk9QwEr\nname:迷惑', 'kick');   // ◆なしの酉 / 名前の一部
    await env.page.locator('.zk-msg.zk-good', { hasText: '追加 2件' }).waitFor();
    await H.goLive(env.page);
    mock.addPlayer({ name: '別名の人', trip: TROLL_TRIP });
    await waitKick(mock, 1);
    assert.equal(mock.state.kicks[0].name, '別名の人');
    mock.addPlayer({ name: 'とても迷惑な人' });
    await waitKick(mock, 2);
    assert.equal(mock.state.kicks[1].name, 'とても迷惑な人');
  });
});

test('荒らし: マヨビームは1回目は警告だけ、2回目で追放。リロードをまたいでも点が残り、履歴の再描画で二重に数えない', OPTS, async () => {
  const mock = baseMock({ chatDelayMs: 1500 });            // リロード後、チャット履歴が遅れて描画される
  await session({ mock, gaps: { grace: 0 } }, async (env) => {
    await env.open();
    await H.goLive(env.page);
    await H.sleep(500);
    mock.say('ミナト', F.zalgo('あ', 30));
    await toast(env.page, '1/2点').first().waitFor({ timeout: 8000 });
    assert.equal(mock.state.kicks.length, 0, '1回目は警告まで');

    const before = playerGets(mock);
    await env.page.reload();
    await waitReloaded(env, before);
    await H.sleep(3500);                                    // 遅れて描画された履歴の中の同じ発言は、数え直さない
    assert.equal(mock.state.kicks.length, 0, '履歴の再描画で点が二重に付いてはいけない');

    mock.say('ミナト', F.java(10));                         // 2回目(別の種類でも合算)
    await waitKick(mock, 1);
    assert.deepEqual(mock.state.kicks.map((k) => k.name), ['ミナト']);
  });
});

test('荒らし: 同一文字・ジャワ文字1文字・絵文字・濁点・短い繰り返しは何も起こさない', OPTS, async () => {
  await session({}, async (env, mock) => {
    await env.open();
    await H.goLive(env.page);
    await H.sleep(600);
    const bodies = ['あ'.repeat(100), 'w'.repeat(200), `こんにちは${F.java(1)}`, '❤️'.repeat(40),
      'がぎぐげご'.normalize('NFD').repeat(20), 'ワロタワロタワロタ', 'うんうんうんうんうん'];
    for (const b of bodies) { mock.say('ミナト', b); await H.sleep(150); }
    await H.sleep(2500);
    assert.equal(mock.state.kicks.length, 0);
    assert.equal(await env.page.locator('.zk-toast').count(), 0, '警告も出ない');
  });
});

test('荒らし: 実物と同じ形の貼り付け(定義文+上限、ログ+上限)は1発言で追放', OPTS, async () => {
  const mock = baseMock();
  mock.addPlayer({ name: 'ユズ' });
  mock.addPlayer({ name: 'ハル' });
  await session({ mock }, async (env) => {
    await env.open();
    await H.goLive(env.page);
    await H.sleep(600);
    const wall = (F.WALL_BULLETS + F.WALL_BULLETS).slice(0, 253);
    mock.say('ミナト', wall);
    await waitKick(mock, 1);
    assert.equal(mock.state.kicks[0].name, 'ミナト');
    await env.page.waitForSelector('.zk-launch');
    await H.sleep(2200);                                    // リロードを待つ
    const log = (F.LOG_PASTE + ' ' + F.LOG_PASTE + ' ' + F.LOG_PASTE).slice(0, 255);
    mock.say('アオイ', log);
    await waitKick(mock, 2);
    assert.equal(mock.state.kicks[1].name, 'アオイ');
  });
});

test('荒らし: 上限に届かない貼り付けは警告だけで、追放しない', OPTS, async () => {
  const mock = baseMock();
  mock.addPlayer({ name: 'ユズ' });
  mock.addPlayer({ name: 'ハル' });
  await session({ mock }, async (env) => {
    await env.open();
    await H.goLive(env.page);
    await H.sleep(600);
    mock.say('アオイ', F.LOG_PASTE);                        // 97字: ログの貼り付け(1点)だけ
    await toast(env.page, 'ログの貼り付け').first().waitFor({ timeout: 8000 });
    await H.sleep(1500);
    assert.equal(mock.state.kicks.length, 0);
  });
});

test('荒らし: 除外リストの人は、荒らし判定でも追放されない', OPTS, async () => {
  await session({}, async (env, mock) => {
    await env.open();
    await H.importList(env.page, 'name:ミナト # 常連', 'allow');
    await env.page.locator('.zk-msg.zk-good', { hasText: '追加 1件' }).waitFor();
    await H.goLive(env.page);
    await H.sleep(600);
    mock.say('ミナト', F.zalgo('あ', 40));
    mock.say('ミナト', F.java(20));
    await H.sleep(2500);
    assert.equal(mock.state.kicks.length, 0);
    assert.equal(await env.page.locator('.zk-toast').count(), 0);
  });
});

test('荒らし: 試運転では、追放ラインに届いても追放せず、記録と通知だけ', OPTS, async () => {
  await session({}, async (env, mock) => {
    await env.open();
    await H.sleep(600);
    mock.say('ミナト', F.zalgo('あ', 40));
    mock.say('ミナト', F.java(20));
    await toast(env.page, '試運転').first().waitFor({ timeout: 8000 });
    await H.sleep(1200);
    assert.equal(mock.state.kicks.length, 0);
    await H.openPanel(env.page, '荒らし');
    await env.page.locator('.zk-log div', { hasText: '追放するところでした' }).first().waitFor();
  });
});

test('荒らし: 判定テストで、貼り付けた文章の点数が見られる', OPTS, async () => {
  await session({}, async (env) => {
    await env.open();
    await H.openPanel(env.page, '荒らし');
    const area = env.page.locator('textarea[placeholder^="荒らしの発言"]');
    await area.fill((F.WALL_BULLETS + F.WALL_BULLETS).slice(0, 253));
    await env.page.locator('button', { hasText: '判定する' }).click();
    const out = env.page.locator('.zk-msg', { hasText: '追放ライン' }).first();
    await out.waitFor();
    const txt = await out.textContent();
    assert.match(txt, /2点/);
    assert.match(txt, /定義文・AI文章の貼り付け/);
    assert.match(txt, /上限ぴったり/);
    await area.fill('今日はよろしくお願いします');
    await env.page.locator('button', { hasText: '判定する' }).click();
    await env.page.locator('.zk-msg', { hasText: '当たらない' }).waitFor();
  });
});

test('観戦のみリスト: 配役を選んでいれば、開始前に参戦していると自動で観戦へ移し、配役を戻す', OPTS, async () => {
  await session({}, async (env, mock) => {
    await env.open();
    await pickPreset(env, '6A');
    await H.importList(env.page, `${TROLL_TRIP} # 参戦不可`, 'spectate');
    await env.page.locator('.zk-msg.zk-good', { hasText: '追加 1件' }).waitFor();
    await H.goLive(env.page);
    mock.addPlayer({ name: '見学希望', trip: TROLL_TRIP });
    await H.waitFor(() => mock.byName('見学希望').is_spectator === true, 15000, '観戦への移動');
    await H.waitFor(() => mock.state.jobsetGets.length >= 2, 8000, '配役の復元(4つ目の手順)');

    const modes = mock.state.posts.map((p) => `${p.mode}${p.is_word ? ':' + p.is_word : ''}${p.word_gm ? ':' + p.word_gm : ''}`);
    assert.deepEqual(modes, ['setWord:on', 'updateJobset:見学希望', 'setWord']);
    const pre = mock.state.posts.find((p) => p.mode === 'updateJobset');
    assert.equal(pre.job_1, '1'); assert.equal(pre.job_8, '0');
    assert.equal(mock.state.jobsetGets.length, 2, '選択時と、観戦移動後の復元');
    assert.equal(mock.state.jobsetGets[1], mock.state.jobsetGets[0], '配役を元に戻している');
    assert.equal(mock.state.wordOn, false, 'ワードウルフは切れている');
    await H.sleep(2500);                                    // リロード後に、もう一度移そうとしない
    assert.equal(mock.state.posts.length, 3);
  });
});

test('観戦のみリスト: 配役が未選択なら、自動では移さず警告する', OPTS, async () => {
  await session({}, async (env, mock) => {
    await env.open();
    await H.importList(env.page, TROLL_TRIP, 'spectate');
    await env.page.locator('.zk-msg.zk-good', { hasText: '追加 1件' }).waitFor();
    await H.goLive(env.page);
    mock.addPlayer({ name: '見学希望', trip: TROLL_TRIP });
    await toast(env.page, 'タブで配役を選ぶと').first().waitFor({ timeout: 8000 });
    await H.sleep(1500);
    assert.equal(mock.state.posts.length, 0);
    assert.equal(mock.byName('見学希望').is_spectator, false);
  });
});

test('観戦のみリスト: 試運転では移さない(記録だけ)', OPTS, async () => {
  await session({}, async (env, mock) => {
    await env.open();
    await pickPreset(env, '6A');
    await H.importList(env.page, TROLL_TRIP, 'spectate');
    await env.page.locator('.zk-msg.zk-good', { hasText: '追加 1件' }).waitFor();
    mock.addPlayer({ name: '見学希望', trip: TROLL_TRIP });
    await H.openPanel(env.page, '荒らし');
    await env.page.locator('.zk-log div', { hasText: '観戦に移すところでした' }).waitFor({ timeout: 8000 });
    await H.sleep(1200);
    assert.equal(mock.state.posts.length, 0);
  });
});

test('手動の観戦移動(参加者表のボタン): 確認 → 4ステップ → 「観戦のみ」に登録できる', OPTS, async () => {
  await session({}, async (env, mock) => {
    await env.open();
    await pickPreset(env, '6A');
    await H.waitFor(async () => (await env.page.locator('.zk-cell button').count()) === 4, 8000, 'ボタン');
    const before = playerGets(mock);
    await env.page.locator('tr', { hasText: 'ミナト' }).locator('.zk-cell button', { hasText: '観戦' }).click();
    await env.page.locator('.zk-dialog button', { hasText: '移して「観戦のみ」に登録' }).click();
    await H.waitFor(() => mock.byName('ミナト').is_spectator === true, 15000, '観戦への移動');
    await waitReloaded(env, before);
    await H.openPanel(env.page, 'リスト');
    const row = env.page.locator('.zk-panel tbody tr', { hasText: 'aBcDeFgHiJ' });
    await row.waitFor();
    assert.equal(await row.locator('select').inputValue(), 'spectate');
  });
});

test('手動の観戦移動: 配役が未選択だと警告つきの確認になる', OPTS, async () => {
  await session({}, async (env, mock) => {
    await env.open();
    await H.waitFor(async () => (await env.page.locator('.zk-cell button').count()) === 4, 8000, 'ボタン');
    await env.page.locator('tr', { hasText: 'アオイ' }).locator('.zk-cell button', { hasText: '観戦' }).click();
    const dlg = env.page.locator('.zk-dialog');
    await dlg.waitFor();
    assert.match(await dlg.textContent(), /配役が未選択/);
    await dlg.locator('button', { hasText: 'キャンセル' }).click();
    await H.sleep(600);
    assert.equal(mock.state.posts.length, 0);
  });
});

test('手動追放(参加者表のボタン): 追放と同時に酉をリストへ登録できる', OPTS, async () => {
  await session({}, async (env, mock) => {
    await env.open();
    await H.waitFor(async () => (await env.page.locator('.zk-cell button').count()) === 4, 8000, 'ボタン');
    const before = playerGets(mock);
    await env.page.locator('tr', { hasText: 'ミナト' }).locator('.zk-cell button', { hasText: '追放' }).click();
    await env.page.locator('.zk-dialog button', { hasText: '追放して酉をリストへ' }).click();
    await waitKick(mock, 1);
    assert.equal(mock.state.kicks[0].name, 'ミナト');
    await waitReloaded(env, before);
    await H.openPanel(env.page, 'リスト');
    const row = env.page.locator('.zk-panel tbody tr', { hasText: 'aBcDeFgHiJ' });
    await row.waitFor();
    assert.equal(await row.locator('select').inputValue(), 'kick');
    // 酉が公開されていない人は、名前での登録しか選べない
    await env.page.locator('tr', { hasText: 'アオイ' }).locator('.zk-cell button', { hasText: '追放' }).click();
    const dlg = env.page.locator('.zk-dialog');
    await dlg.waitFor();
    assert.equal(await dlg.locator('button', { hasText: '追放して酉をリストへ' }).count(), 0);
    assert.equal(await dlg.locator('button', { hasText: '追放して名前をリストへ' }).count(), 1);
    await dlg.locator('button', { hasText: 'キャンセル' }).click();
  });
});

test('履歴タブ: 入室した人が記録され、そこからリストへ登録できる', OPTS, async () => {
  await session({}, async (env, mock) => {
    await env.open();
    await H.sleep(800);
    mock.addPlayer({ name: '新入り', trip: '◆nEwPlAyEr12' });
    mock.addPlayer({ name: '酉なしさん' });
    await H.openPanel(env.page, '履歴');
    const row = env.page.locator('.zk-panel tbody tr', { hasText: '新入り' });
    await row.waitFor({ timeout: 8000 });
    await row.locator('button', { hasText: '観戦のみ' }).click();
    await toast(env.page, '観戦のみリストに登録しました(酉)').waitFor();
    const row2 = env.page.locator('.zk-panel tbody tr', { hasText: '酉なしさん' });
    await row2.locator('button', { hasText: '追放' }).click();
    await toast(env.page, '名前・部分一致').waitFor();
    await H.openPanel(env.page, 'リスト');
    assert.equal(await env.page.locator('.zk-panel tbody tr', { hasText: 'nEwPlAyEr12' }).locator('select').inputValue(), 'spectate');
    assert.equal(await env.page.locator('.zk-panel tbody tr', { hasText: '酉なしさん' }).locator('select').inputValue(), 'kick');
  });
});

test('リスト(本番): 今いる人に当たる追加は、実行の前に確認が出る(名前は部分一致のため)', OPTS, async () => {
  await session({}, async (env, mock) => {
    await env.open();
    await H.goLive(env.page);
    await H.openPanel(env.page, 'リスト');
    const sec = env.page.locator('.zk-sec', { hasText: '追加' }).first();
    await sec.locator('select').nth(0).selectOption('name');
    await sec.locator('input[type=text]').first().fill('ミナ');
    await sec.locator('button', { hasText: '追加' }).click();
    const dlg = env.page.locator('.zk-dialog');
    await dlg.waitFor();
    assert.match(await dlg.textContent(), /ミナト → 追放/);
    await dlg.locator('button', { hasText: 'キャンセル' }).click();
    await H.sleep(1500);
    assert.equal(mock.state.kicks.length, 0, 'キャンセルすれば追放されない');
    assert.match(await env.page.locator('.zk-panel tbody tr').first().textContent(), /なし/, '登録もされない');

    await sec.locator('button', { hasText: '追加' }).click();
    await dlg.locator('button', { hasText: '追加して実行' }).click();
    await waitKick(mock, 1);
    assert.equal(mock.state.kicks[0].name, 'ミナト');
  });
});

test('荒らしで追放した人の酉は、既定ではリストに自動登録しない。追放ログから登録できる', OPTS, async () => {
  await session({}, async (env, mock) => {
    await env.open();
    await H.goLive(env.page);
    await H.sleep(500);
    const before = playerGets(mock);
    mock.say('ミナト', F.zalgo('あ', 30));
    mock.say('ミナト', F.java(10));
    await waitKick(mock, 1);
    await waitReloaded(env, before);
    await H.openPanel(env.page, 'リスト');
    assert.match(await env.page.locator('.zk-panel tbody tr').first().textContent(), /なし/, '自動では登録されない');

    await H.openPanel(env.page, '荒らし');
    // 「最近の検知・処理」(タブを閉じると消える)ではなく、「追放ログ」(保存される)の行
    const logRow = env.page.locator('.zk-sec', { hasText: '追放ログ' }).locator('.zk-log div', { hasText: 'ミナト' });
    await logRow.waitFor();
    assert.match(await logRow.textContent(), /aBcDeFgHiJ/, '公開されている酉が追放ログに残る');
    await logRow.locator('button', { hasText: 'リストへ登録' }).click();
    await toast(env.page, '追放リストに登録しました(酉)').waitFor();
    await H.openPanel(env.page, 'リスト');
    assert.equal(await env.page.locator('.zk-panel tbody tr', { hasText: 'aBcDeFgHiJ' }).locator('select').inputValue(), 'kick');
  });
});

test('自動登録をONにすると、追放と同時に酉が「自動」の印つきで登録され、まとめて消せる', OPTS, async () => {
  await session({}, async (env, mock) => {
    await env.open();
    await H.openPanel(env.page, '荒らし');
    await env.page.locator('label.zk-check', { hasText: '自動追放した人の酉' }).locator('input').click();   // 押すと再描画される
    await env.page.locator('label.zk-check', { hasText: '自動追放した人の酉' }).locator('input:checked').waitFor();
    await H.goLive(env.page);
    await H.sleep(500);
    const before = playerGets(mock);
    mock.say('ミナト', F.zalgo('あ', 30));
    mock.say('ミナト', F.java(10));
    await waitKick(mock, 1);
    await waitReloaded(env, before);
    await H.openPanel(env.page, 'リスト');
    const row = env.page.locator('.zk-panel tbody tr', { hasText: 'aBcDeFgHiJ' });
    await row.waitFor();
    await row.locator('.zk-tag.zk-auto').waitFor();
    assert.equal(await row.locator('select').inputValue(), 'kick');
    await env.page.locator('button', { hasText: '自動登録を全削除' }).click();
    await env.page.locator('.zk-dialog button', { hasText: 'OK' }).click();
    await env.page.locator('.zk-panel tbody tr', { hasText: 'なし' }).waitFor();
  });
});

test('パネルの入力欄で打ったキーが、サイト側のキー操作に漏れない', OPTS, async () => {
  await session({}, async (env) => {
    await env.open();
    await env.page.evaluate(() => { window.__keys = []; document.addEventListener('keydown', (e) => window.__keys.push(e.key)); });
    await H.openPanel(env.page, 'リスト');
    await env.page.locator('.zk-panel input[placeholder^="◆abc"]').click();
    await env.page.keyboard.type('abc');
    assert.deepEqual(await env.page.evaluate(() => window.__keys), [], 'パネルの中のキーはサイトに届かない');
    await env.page.locator('h1#title').click();
    await env.page.keyboard.press('x');
    assert.deepEqual(await env.page.evaluate(() => window.__keys), ['x'], '対照: パネルの外のキーは届く');
  });
});

test('パネル: 入力途中の内容と判定テストの結果は、状態が変わって再描画されても消えない', OPTS, async () => {
  await session({}, async (env, mock) => {
    await env.open();
    await H.openPanel(env.page, 'リスト');
    const val = env.page.locator('.zk-panel input[placeholder^="◆abc"]');
    await val.fill('途中まで打った名前');
    await val.evaluate((el) => { el.dataset.marker = 'old'; });
    mock.addPlayer({ name: '誰か', trip: '◆sOmEoNe1234' });          // 状態の変化(入力中なので再描画は保留される)
    await env.page.locator('.zk-head b').click();                     // 入力から離れる
    await H.waitFor(async () => (await val.getAttribute('data-marker')) !== 'old', 6000, '再描画');
    assert.equal(await val.inputValue(), '途中まで打った名前', '再描画のあとも入力が残る');

    await H.openPanel(env.page, '荒らし');
    const area = env.page.locator('textarea[placeholder^="荒らしの発言"]');
    await area.fill((F.WALL_BULLETS + F.WALL_BULLETS).slice(0, 253));
    await env.page.locator('button', { hasText: '判定する' }).click();
    const result = env.page.locator('.zk-msg', { hasText: '追放ライン' });
    await result.first().waitFor();
    mock.addPlayer({ name: 'もう一人' });                              // 再び状態が変わる
    await H.sleep(1500);
    assert.match(await result.first().textContent(), /2点/, '判定結果が消えない');
    assert.equal(await area.inputValue(), (F.WALL_BULLETS + F.WALL_BULLETS).slice(0, 253));
  });
});

test('パネル: 開いた折りたたみ(一括取り込み)は、再描画されても開いたまま', OPTS, async () => {
  await session({}, async (env, mock) => {
    await env.open();
    await H.openPanel(env.page, 'リスト');
    const det = env.page.locator('details', { hasText: '一括取り込み' });
    await det.locator('summary').click();
    assert.equal(await det.evaluate((d) => d.open), true);
    await det.evaluate((d) => { d.dataset.marker = 'old'; });
    for (let i = 0; i < 3; i++) {                             // 状態の変化を何度か起こして、再描画させる
      mock.addPlayer({ name: `入室${i}`, trip: `◆nEwPlAyEr${i}00` });
      await H.sleep(500);
    }
    await H.waitFor(async () => (await det.getAttribute('data-marker')) !== 'old', 6000, '再描画');
    assert.equal(await det.evaluate((d) => d.open), true, '再描画で閉じない');
    await det.locator('summary').click();                       // 閉じる操作も、再描画をまたいで保たれる
    assert.equal(await det.evaluate((d) => d.open), false);
    mock.addPlayer({ name: '入室9', trip: '◆nEwPlAyEr900' });
    await H.sleep(900);
    assert.equal(await det.evaluate((d) => d.open), false);
  });
});

test('追放が効かなくても、同じ人への自動の追放は3回で止まる(無限リロードしない)', OPTS, async () => {
  await session({}, async (env, mock) => {
    await env.open();
    await H.importList(env.page, TROLL_TRIP, 'kick');
    await env.page.locator('.zk-msg.zk-good', { hasText: '追加 1件' }).waitFor();
    await H.goLive(env.page);
    mock.state.failKick = true;                             // サーバーが追放を受け付けない状況
    mock.addPlayer({ name: '居座り', trip: TROLL_TRIP });
    await waitKick(mock, 3);
    await H.sleep(5000);
    assert.equal(mock.state.kicks.length, 3, '3回で諦める');
    await toast(env.page, '追放できません').first().waitFor();
  });
});

test('サイトが参加者表を毎回作り直しても、ボタンが残って押せる', OPTS, async () => {
  await session({ mock: baseMock({ rerender: 'always' }) }, async (env) => {
    await env.open();
    await H.waitFor(async () => (await env.page.locator('.zk-cell button').count()) === 4, 8000, 'ボタン');
    await H.sleep(1500);                                    // 何度か作り直されたあとも
    assert.equal(await env.page.locator('.zk-cell button').count(), 4, 'ボタンが二重に増えない');
    await env.page.locator('tr', { hasText: 'ミナト' }).locator('.zk-cell button', { hasText: '追放' }).click();
    await env.page.locator('.zk-dialog').waitFor();
    await env.page.locator('.zk-dialog button', { hasText: 'キャンセル' }).click();
  });
});

test('本番への切り替えは確認が出て、試運転に戻せる', OPTS, async () => {
  await session({}, async (env) => {
    await env.open();
    await H.openPanel(env.page);
    await env.page.locator('.zk-banner .zk-btn', { hasText: '本番にする' }).click();
    await env.page.locator('.zk-dialog button', { hasText: 'キャンセル' }).click();
    assert.match(await env.page.locator('.zk-banner').textContent(), /試運転中/);
    await H.goLive(env.page);
    assert.match(await env.page.locator('.zk-banner').textContent(), /本番/);
    await env.page.locator('.zk-banner .zk-btn', { hasText: '試運転に戻す' }).click();
    await env.page.locator('.zk-banner.zk-b-dry').waitFor();
  });
});

test('RMでなければ、本番にしてあっても自動では何もしない', OPTS, async () => {
  await session({}, async (env, mock) => {
    await env.open();
    await H.importList(env.page, TROLL_TRIP, 'kick');
    await env.page.locator('.zk-msg.zk-good', { hasText: '追加 1件' }).waitFor();
    await H.goLive(env.page);
    mock.state.me = 'アオイ';                               // 別のタブ・別の村でRMではない立場になった
    mock.addPlayer({ name: '荒らし', trip: TROLL_TRIP });
    await env.page.reload();
    await env.page.waitForSelector('.zk-launch');
    await H.sleep(600);
    mock.say('ミナト', F.zalgo('あ', 40));
    mock.say('ミナト', F.java(20));
    await H.sleep(3000);
    assert.equal(mock.state.kicks.length, 0);
    assert.equal(mock.state.posts.length, 0);
  });
});

test('リスト: 追加・重複・競合・取り込み・書き出しが画面から使える', OPTS, async () => {
  await session({}, async (env) => {
    await env.open();
    await H.openPanel(env.page, 'リスト');
    const add = async (kind, value, action) => {
      const sec = env.page.locator('.zk-sec', { hasText: '追加' }).first();
      await sec.locator('select').nth(0).selectOption(kind);
      await sec.locator('input[type=text]').first().fill(value);
      await sec.locator('select').nth(1).selectOption(action);
      await sec.locator('button', { hasText: '追加' }).click();
    };
    await add('name', 'あ', 'kick');
    await env.page.locator('.zk-msg.zk-bad', { hasText: '2文字以上' }).waitFor();
    await add('trip', '◆aBcDeFgHiJ', 'kick');
    await env.page.locator('.zk-msg.zk-good', { hasText: '追加しました' }).waitFor();
    await add('trip', 'aBcDeFgHiJ', 'kick');
    await env.page.locator('.zk-msg.zk-bad', { hasText: '登録済み' }).waitFor();
    await add('trip', 'aBcDeFgHiJ', 'spectate');
    await env.page.locator('.zk-msg.zk-bad', { hasText: '別の動作で登録済み' }).waitFor();

    await H.importList(env.page, `[観戦のみ]\n◆Pq7Rs8Tu9V # 参戦不可\n\ntrip:短い\n[除外]\nname:常連さん`, 'kick');
    const msg = env.page.locator('.zk-msg', { hasText: '追加 2件' });
    await msg.waitFor();
    assert.match(await msg.textContent(), /読めなかった行 1件/);

    const exp = env.page.locator('details', { hasText: '書き出し' });
    await exp.locator('summary').click();
    const out = await exp.locator('textarea').inputValue();
    assert.match(out, /\[追放\]\n◆aBcDeFgHiJ/);
    assert.match(out, /\[観戦のみ\]\n◆Pq7Rs8Tu9V # 参戦不可/);
    assert.match(out, /\[除外\]\nname:常連さん/);
  });
});
