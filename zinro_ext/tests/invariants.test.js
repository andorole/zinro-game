/* 守りたい前提を、静的に検査する(今後の編集で破るとここで落ちる)。
 *   1. 外部のサーバーと通信しない(権限・通信先・通信の手段)
 *   2. 他人の名前・発言を、HTML として解釈される形で画面に入れない
 *   3. manifest が指すファイルがすべてある */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');
const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, 'manifest.json'), 'utf8'));

function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    (e.isDirectory() ? walk(path.join(dir, e.name)) : [path.join(dir, e.name)]));
}
const sources = walk(path.join(ROOT, 'src')).filter((f) => f.endsWith('.js'));
const rel = (f) => path.relative(ROOT, f);
/** コメントを除いたコード(説明文の中の語に反応しないため)。 */
const code = (f) => fs.readFileSync(f, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

test('manifest: 権限は storage だけ。ホスト権限・バックグラウンド処理・外部との接続設定を持たない', () => {
  assert.equal(manifest.manifest_version, 3);
  assert.deepEqual(manifest.permissions, ['storage']);
  for (const key of ['host_permissions', 'optional_host_permissions', 'background', 'externally_connectable',
    'web_accessible_resources', 'update_url', 'content_security_policy', 'declarative_net_request']) {
    assert.equal(manifest[key], undefined, `${key} を足すときは、外部と通信しない前提を見直すこと`);
  }
});

test('manifest: 動作対象は zinro.net の /m/ 以下だけ。MAIN world で動かすのは interceptor だけ', () => {
  for (const cs of manifest.content_scripts) {
    assert.deepEqual(cs.matches, ['https://zinro.net/m/*']);
    if (cs.world === 'MAIN') assert.deepEqual(cs.js, ['src/interceptor.js']);
  }
  assert.equal(manifest.content_scripts.filter((c) => c.world === 'MAIN').length, 1);
});

test('manifest が指すファイルがすべてある。src の js はすべて manifest に載っている', () => {
  const listed = manifest.content_scripts.flatMap((c) => c.js);
  for (const f of listed) assert.ok(fs.existsSync(path.join(ROOT, f)), `${f} がない`);
  const onDisk = sources.map(rel).sort();
  assert.deepEqual([...listed].sort(), onDisk, 'manifest に載っていない(または余分な)ファイルがある');
});

test('ソースに外部の URL がない(通信先は同一オリジンの相対パスだけ)', () => {
  for (const f of sources) {
    const hits = code(f).match(/https?:\/\/[^\s'"`)]+/g) || [];
    assert.deepEqual(hits, [], `${rel(f)} に URL がある`);
  }
});

test('外部送信につながる API を使わない(interceptor が読むだけの XMLHttpRequest は除く)', () => {
  const banned = /\b(sendBeacon|WebSocket|EventSource|importScripts|chrome\.runtime\.sendMessage|chrome\.tabs|chrome\.webRequest|chrome\.cookies|window\.open)\b/;
  for (const f of sources) assert.doesNotMatch(code(f), banned, rel(f));
  for (const f of sources.filter((x) => !x.endsWith('interceptor.js'))) assert.doesNotMatch(code(f), /XMLHttpRequest/, rel(f));
});

test('fetch は同一オリジンの相対パス(/m/...)だけに出す', () => {
  for (const f of sources) {
    for (const m of code(f).matchAll(/\bfetch\(\s*([^,)]+)/g)) {
      const arg = m[1].trim();
      // interceptor の fetch は、サイト自身の fetch を包む元の関数(origFetch)
      if (/origFetch|window\.fetch/.test(arg) || arg === 'job.url') continue;
      assert.match(arg, /^['"`]\/m\//, `${rel(f)}: fetch(${arg})`);
    }
  }
});

test('HTML として解釈される形で文字列を入れない(他人の名前・発言を表示するため)', () => {
  for (const f of sources) {
    assert.doesNotMatch(code(f), /\b(innerHTML|outerHTML|insertAdjacentHTML|document\.write|srcdoc)\b|\beval\s*\(|new Function/, rel(f));
  }
});
