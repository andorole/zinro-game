# 引継ぎ(zinro_ext)

2026-10-26 に、クラウドのセッションで作ったものを、手元(ローカル)の環境で続けるための資料。次の担当(ローカルの Claude Code や、あとで読む自分)が、これだけで再開できるようにしてある。

## いまの状態

- ブランチ `claude/quirky-euler-71id09`。コミットは、`d486b6e`(判定ロジックと単体テスト)→ `ee142ea`(拡張本体・E2E・README)→ この資料。PR はまだない。`main` には入っていない。
- テストはすべて通っている: `node --test zinro_ext/tests/*.test.js` が69件、E2E(Playwright)が29件、`python -m unittest` が100件(拡張の単体テストも含む)。
- **実サイト(zinro.net)では、一度も動かしていない**。クラウドの環境から zinro.net に届かないため。確かめたのは、旧拡張の実装から読み取ったサイトの形を再現した模擬サイトの上だけ。これが最大の未確認で、次の仕事の中心。

## 引継ぎに必要なもの

| もの | どこにある | 手元でやること |
|---|---|---|
| コード・テスト・README | GitHub `andorole/zinro-game` の `claude/quirky-euler-71id09` の `zinro_ext/` | `git clone` して checkout |
| この資料 | `zinro_ext/HANDOVER.md` | 同上 |
| 設計の理由・既定値・確かめた範囲 | `zinro_ext/README.md` とコミットメッセージ | 読む |
| サイトの形の前提(旧拡張から読み取った) | この資料の「実サイトで確かめる前提」、`src/lib/zinro.js` の冒頭、`tests/e2e/mock_site.js` | 実サイトと突き合わせる |
| 旧拡張のソース zip | リポジトリには入っていない。あなたがクラウドのセッションにアップロードしたもの(手元に残っているはず) | 参照したいときだけ、リポジトリの**外**に展開。読むだけで、実行しない |
| 荒らしの実例2件(生ログ) | あなたのチャット履歴・ログ。リポジトリには入れていない(他人の発言を含むため) | 判定テストに貼る。リポジトリには入れない |
| 確認する場所 | あなたの Chrome、zinro.net のアカウント、身内の村、(追放・観戦移動を試すための)捨てアカウント | — |
| Node.js | 手元 | v20 以上(クラウドでは22) |
| Playwright と Chromium(E2E だけ) | 手元 | `npm i -g playwright` と `npx playwright install chromium`。グローバルに入れたときは、`NODE_PATH` に `npm root -g` の場所を設定する。リポジトリに package.json はない(`node_modules/` は .gitignore 済み)。E2E は拡張を入れた Chromium(`channel: 'chromium'`)を動かす。単体テストだけなら、入れなくてよい |

## 実サイトで確かめる前提

上から順に確かめる。「危険」は、違ったときに別の人を追放しうるもの。違っていたら、直す前に、模擬サイト(`tests/e2e/mock_site.js`)を実サイトの形に合わせて、失敗するテストを先に足す。確認用のスニペットは、後ろの「確認用スニペット」(1〜7)。

| # | 前提 | 確かめ方 | 違ったとき直す所 |
|---|---|---|---|
| 1 | 村のページは `/m/player.php`。拡張は `https://zinro.net/m/*` で動く | 村を開いて、右下に「RM補助」が出るか | `manifest.json` の `matches`、`src/content/main.js` 冒頭の `player.php` の判定 |
| 2 | 参加者API `GET /m/api/?mode=players` が `{ room:{gm,name,scene または status}, player:{name}, players:{…} }` を返し、各人が `id, name, trip, trip_open("1"), is_spectator, job` を持つ。ダミーの参加者名は「初日犠牲者」 | スニペット1 | `src/lib/zinro.js`(`isSpectator` `playersOf` `amIGm` `sceneOf` `isPregame` `publicTrip`)。確かめたい点: 開始前の `scene` の値(「開始前」「waiting」「0」「空」のどれか)、観戦者の表し方、`trip_open` の意味、RM から見て非公開の酉が `trip` に入っているか |
| 3 | サイトが参加者APIを fetch か XHR で取り、interceptor が応答を拾える(拾えなくても、2.5秒後に拡張が自分で取りに行くので動くが、サイトの通信に相乗りできていない) | スニペット7 | `src/interceptor.js` の `isPlayersUrl`(URL や `mode=players` の判定) |
| 4 | **(危険)** チャット欄は `#message > #message_text > div`、新しい発言が先頭。発言者は `.from-normal` / `.from-system`、本文は `.text-normal` / `.text-system`(先頭に「:」)。システム通知の発言者は「鯖」 | スニペット2、スニペット6。試運転のログの名前が、実際の発言者と一致するか | `src/lib/zinro.js`(`chatContainer` `chatItems` `parseChatItem` `splitChatLine`)。新しい発言が末尾なら、`src/content/main.js` の `scanChat` で `diffNew` に `{ newestFirst: false }` を渡す |
| 5 | 1発言の上限は255字(貼り付けた2件が253字・255字で途切れていたことからの推定) | スニペット3(入力欄の `maxLength`)。実際に長文を送って、切れる字数を見る | `src/lib/rules.js` の `DEFAULTS.chatCap`(設定画面でも変えられる) |
| 6 | 参加者表は `#all_players table`。名前は `td span[onclick*="confirmDialog"]` の、`(` より前 | スニペット4 | `src/lib/zinro.js` の `playerRowName`、`src/content/main.js` の `injectRowButtons` |
| 7 | **(危険)** 追放は `GET /m/player.php?kick=<id>&name=<名前>`(RM のみ)。`<id>` は参加者APIの各人の `id` | 試運転のまま、手動の「追放」ボタンで、捨てアカウントを追放する | `src/lib/zinro.js` の `kickPath` |
| 8 | 配役は `GET /m/player.php?mode=updateJobset&job_N=…&yakukakenashi=0`。27種の内訳が実サイトの配役と同じ | プリセットを押して、サイトの配役表示が変わるか。内訳(特に人数)が合うか | `src/lib/presets.js` |
| 9 | 観戦への移動は、4手順で成り立つ(`GET /m/player.php` の `input[name=token]` → POST `setWord is_word=on` → POST `updateJobset job_1=1 job_8=0 word_gm=<名前>` → POST `setWord`(OFF) → 配役を GET で戻す)。token は毎回取り直す | スニペット5(token の入力欄)。身内の村で、捨てアカウントを移して、DevTools の Network で各手順の結果を見る。最後に、観戦になっているか・配役が戻っているか | `src/content/actions.js` の `moveToSpectator`、`src/lib/zinro.js` の `extractToken` |
| 10 | 酉は「◆+10桁または12桁」、または◆なしの素トリップ。拡張は英数字と `. / +` の8〜14桁を酉と見る | 実際の酉を、リストの追加欄に入れてみる | `src/lib/lists.js` の `TRIP_BODY` |
| 11 | 通信の間隔(参加者API 1.2秒、player.php 2秒)で、サイトから拒否されない | 通常の使用で、エラーが出ないか | `src/content/actions.js` の `gaps` |
| 12 | 実際の荒らしの2件が、どちらも1発言で2点になる | 「荒らし」タブの「判定テスト」に貼る(定義文・AI文章の貼り付け+上限ぴったり、ログの貼り付け+上限ぴったり) | `src/lib/rules.js` |

### 確かめ方の順番(安全のため)

1. 拡張は試運転のまま(初期状態)。自動の追放・観戦移動は起きない。
2. 場所は、自分が RM の身内の村だけ。荒らし役は、自分の別アカウントか、事情を知っている人。
3. #1〜#6 と #12 は、試運転のまま確かめられる。
4. #7(追放)と #9(観戦移動)は、実際に実行するので、対象は自分の捨てアカウントだけにする。
5. 本番への切り替えは、#1〜#9 が確かめられてから。そのあとも、最初は身内の村だけで使う。

## 決めたこと(理由は README とコミットメッセージ)

- 初期状態は試運転。点数制で、追放ラインは2点、点の有効期間は30分。マヨビーム12字・ジャワ文字8字は各1点で、同じ発言の中では合わせて1点まで(=2回の投稿で追放)。
- 同一文字の連続と、短い語句の繰り返しは検知しない。旧拡張にあった「文字の重なりで測る類似連投」も入れていない。
- 「ログの貼り付け」は既定1点(単独では警告まで)。
- 自動追放した人の酉は、既定ではリストに自動登録しない(追放ログから1クリックで登録できる)。
- 要望になかったが、「除外」リストを足した(常連が荒らし判定に巻き込まれないようにするため)。
- 入れていない: 戦績などサーバーのデータが要るもの、情報パネルの使用時間・フレンド・サーバー状態、点呼・人数の警告・接続切れの警告・他村パネル。

## 未決

- 点呼・人数の警告・接続切れの警告・他村パネルを入れるか。
- 「ログの貼り付け」を、単独で追放ライン(2点)にするか。
- この拡張を zinro-game に置いたままにするか、別リポジトリに移すか(`zinro_ext/` は自己完結していて、そのまま移せる)。
- サイトの規約で、RM による自動の追放・観戦移動が許されるか(旧拡張は公開されていた。確かめるのは使う人)。

## 守ること

- 外部のサーバーと通信しない(`tests/invariants.test.js` が検査している)。HTML として文字列を入れない(同じテスト)。チャットへの自動投稿をしない。
- 初期状態を試運転にしている設定を変えない。
- 他人の発言・名前・酉を含む生ログや、DevTools の生の出力を、リポジトリに入れない(リポジトリ全体の方針)。テストには合成データを使う。
- 実際に人を追放する・観戦に移す操作の前と、本番への切り替えの前は、使う人に確認する。
- PR は、頼まれたときだけ作る。

## 確認用スニペット

zinro.net の村のページで、DevTools のコンソールに貼って実行する。他人の名前・酉・発言は、字数だけに伏せて出す。貼る前に、出力に名前や酉が混ざっていないか、目で確かめること。

### スニペット1: 参加者API

```js
fetch('/m/api/?mode=players').then((r) => r.json()).then((j) => {
  const len = (v) => (v ? `<${String(v).length}字>` : v);
  const redact = (o) => Object.fromEntries(Object.entries(o || {}).map(([k, v]) =>
    /pass|token|secret|mail|addr|^ip$/i.test(k) ? [k, '<伏せ>']
      : /^(name|trip|gm|from_user|to_user)$/.test(k) ? [k, len(v)] : [k, v]));
  console.log(JSON.stringify({
    top_keys: Object.keys(j),
    room: redact(j.room),
    room_gm_is_me: !!(j.room && j.player && j.room.gm === j.player.name),
    player: redact(j.player),
    players_keys: Object.keys(j.players || {}).slice(0, 3),
    players_sample: Object.values(j.players || {}).slice(0, 3).map(redact),
  }, null, 2));
});
```

### スニペット2: チャット欄の構造

```js
(() => {
  const mask = (html) => html.replace(/>([^<]+)</g, (_, t) => `>…(${t.trim().length}字)<`);
  const box = document.querySelector('#message_text') || document.querySelector('#message');
  const items = box ? Array.from(box.children).filter((e) => e.tagName === 'DIV') : [];
  console.log('container:', box ? `${box.tagName}#${box.id}` : 'なし', ' items:', items.length);
  console.log('先頭の行:', items[0] ? mask(items[0].outerHTML) : 'なし');
  console.log('末尾の行:', items.length ? mask(items[items.length - 1].outerHTML) : 'なし');
})();
```

### スニペット3: 入力欄の上限

```js
console.log(JSON.stringify(Array.from(document.querySelectorAll('textarea, input[type=text]'))
  .map((e) => ({ tag: e.tagName, id: e.id, name: e.name, maxLength: e.maxLength })), null, 2));
```

### スニペット4: 参加者表の行

拡張を入れていると、拡張が足した `td.zk-cell`(追放・観戦のボタンの欄)も混ざって出る。

```js
(() => {
  const row = document.querySelector('#all_players table tr:nth-child(2)');
  console.log(row
    ? row.outerHTML.replace(/>([^<]+)</g, (_, t) => `>…(${t.trim().length}字)<`).replace(/confirmDialog\([^)]*\)/g, 'confirmDialog(…)')
    : '行なし');
})();
```

### スニペット5: フォームの token

```js
console.log(JSON.stringify(Array.from(document.querySelectorAll('input[name="token"]'))
  .map((e) => ({ type: e.type, hasValue: !!e.value, form: e.form && (e.form.id || e.form.action) })), null, 2));
```

### スニペット6: 新しい発言が先頭か

自分で「ZK-ORDER-TEST」と発言した直後に実行する。先頭が最新なら `true`。

```js
console.log(!!(document.querySelector('#message_text > div') || {}).textContent?.includes('ZK-ORDER-TEST'));
```

### スニペット7: interceptor がサイトの通信を拾えているか

村のページを開き直さずに、コンソールで実行して、数秒待つ。「zk_players を受信」が出れば、サイトの参加者APIの応答を拾えている。

```js
(() => {
  console.log('interceptor:', window.__zkInterceptor === true ? '入っている' : '入っていない');
  window.addEventListener('zk_players', () => console.log('zk_players を受信'), { once: true });
  console.log('数秒待って「zk_players を受信」が出るか見る');
})();
```

## ローカルの Claude Code に貼るプロンプト

```
このリポジトリ(zinro-game)の `zinro_ext/`(zinro.net の RM 補助の Chrome 拡張)の続きをお願いします。クラウドのセッションで作ったもので、実サイト(zinro.net)ではまだ一度も動かしていません。手元のこの環境で、実サイトに合わせて確かめて、違うところを直すのが今回の仕事です。日本語で、簡潔にお願いします。

## 最初にやること
1. ブランチ `claude/quirky-euler-71id09`(コミット ee142ea 以降)にいることを確認する。
2. `zinro_ext/HANDOVER.md` と `zinro_ext/README.md` を読む。
3. テストが通ることを確認する: `python -m unittest` と `node --test zinro_ext/tests/*.test.js`。E2E(`zinro_ext/tests/e2e/zinro_e2e.test.js`)は Playwright が要る。入っていなければ、入れる前に私に聞く。

## 今回の仕事: 実サイトとの突き合わせ
この拡張は、旧拡張(提供終了)の実装から読み取ったサイトの形(参加者API、チャット欄のDOM、KICK、配役、フォームの token)を前提にしています。HANDOVER.md の「実サイトで確かめる前提」を、上から順に確かめて、違うところを `zinro_ext/src/` で直してください。
- 確かめ方: ブラウザを操作できるツールがあれば、それで。なければ、HANDOVER.md の「確認用スニペット」を私が実行して、出力を貼ります(他人の名前・酉は伏せてあります)。手順は一つずつ、私に頼んでください。
- 違いが見つかったら、まず模擬サイト(`zinro_ext/tests/e2e/mock_site.js`)を実サイトの形に合わせ、失敗するテストを足してから直す。
- 直したら、`zinro_ext/README.md` の「確かめたこと / 確かめていないこと」を、実際に確かめた範囲に合わせて更新し、HANDOVER.md の表も更新する。

## 守ること
- 実サイトでの確認は、拡張を試運転のままにして、私が RM の身内の村でだけ行う。実際に人を追放する・観戦に移す操作の前と、本番への切り替えの前には、必ず私に確認する。対象は私の捨てアカウントだけ。
- チャットへの自動投稿はしない。外部サーバーへの通信は足さない(`zinro_ext/tests/invariants.test.js` が守っている。外さない)。初期状態の試運転は変えない。
- 他人の発言・名前・酉を含む生ログや、DevTools の生の出力を、リポジトリに入れない。テストには合成データを使う。
- 旧拡張の zip を参照する必要があれば、リポジトリの外に展開して、読むだけ。実行しない。
- コミットは同じブランチに。プッシュと PR は、私に確認してから。

## 荒らしの実例での確認
荒らしの実例2件(辞書のような解説文の貼り付けと、チャットログの貼り付け)を、私が貼ります。拡張の「荒らし」タブの「判定テスト」に貼って、どちらも2点(追放ライン)になることを確かめてください。ならなければ、原因を調べてください。

## 私に聞いてほしいこと(未決)
- 点呼・人数の警告・接続切れの警告・他村パネルを入れるか。
- 「ログの貼り付け」を、単独で追放ライン(2点)にするか(今は1点=警告まで)。
- この拡張を zinro-game に置いたままにするか、別リポジトリに移すか。
```
