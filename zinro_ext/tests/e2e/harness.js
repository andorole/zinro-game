/* 実際の拡張を Chromium に読み込み、https://zinro.net/ へのすべての通信を模擬サイトに差し替えて動かす。 */
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { chromium } = require('playwright');

const EXT = path.resolve(__dirname, '..', '..');     // zinro_ext/(manifest.json のある所)

/** テスト用の待ち時間(ms)。猶予(grace)は、チャットの履歴が遅れて描画される場合を確かめるため 0 にもできる。 */
const FAST = { api: 5, player: 5, step: 5, grace: 300 };

async function launch(mock, gaps) {
  const userDir = fs.mkdtempSync(path.join(os.tmpdir(), 'zk-e2e-'));
  const ctx = await chromium.launchPersistentContext(userDir, {
    channel: 'chromium',
    headless: true,
    args: [`--disable-extensions-except=${EXT}`, `--load-extension=${EXT}`],
  });
  await ctx.route(/^https?:\/\//, (route) => mock.handle(route));
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error' && /\[zk\]/.test(m.text())) errors.push(`console: ${m.text()}`); });
  const g = Object.assign({}, FAST, gaps || {});
  await page.addInitScript((v) => { try { sessionStorage.setItem('zk_test_gaps', JSON.stringify(v)); } catch (e) { /* 無視 */ } }, g);

  const env = {
    ctx, page, errors, mock,
    async open() {
      await page.goto('https://zinro.net/m/player.php');
      await page.waitForSelector('#zk-host', { state: 'attached', timeout: 10000 });
      await page.waitForSelector('.zk-launch');
    },
    async close() {
      await ctx.close();
      fs.rmSync(userDir, { recursive: true, force: true });
    },
  };
  return env;
}

// ---- 画面操作の補助 ----
const launcher = (page) => page.locator('.zk-launch');
async function openPanel(page, tabName) {
  if (!(await page.locator('.zk-panel').isVisible())) await launcher(page).click();
  if (tabName) await page.locator('.zk-tab', { hasText: tabName }).click();
}
async function importList(page, text, action) {
  await openPanel(page, 'リスト');
  const det = page.locator('details', { hasText: '一括取り込み' });
  if (!(await det.evaluate((d) => d.open))) await det.locator('summary').click();
  await det.locator('textarea').fill(text);
  if (action) await det.locator('select').selectOption(action);
  await det.locator('button', { hasText: '取り込む' }).click();
}
async function goLive(page) {
  await openPanel(page);
  await page.locator('.zk-banner .zk-btn', { hasText: '本番にする' }).click();
  await page.locator('.zk-modal .zk-btn.zk-danger', { hasText: '本番にする' }).click();
  await page.locator('.zk-banner.zk-b-live').waitFor();
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, timeout = 8000, what = '条件') {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    if (await fn()) return;
    await sleep(60);
  }
  throw new Error(`時間内に満たされませんでした: ${what}`);
}

module.exports = { launch, openPanel, importList, goLive, launcher, sleep, waitFor, FAST, EXT };
