/* 模擬の zinro.net(実サイトではない)。
 *
 * 旧拡張の実装から読み取ったサイトの形を再現する: 参加者API(/m/api/?mode=players)、チャット欄のDOM
 * (#message > #message_text > div に新しい発言が先頭)、参加者表(#all_players の table)、KICK(player.php?kick=)、
 * 配役(player.php?mode=updateJobset)、フォームの token(ページを取得するたびに更新され、使うと失効する)。
 * 拡張がこの形のサイトでどう動くかを確かめるためのもので、実サイトで動くことの証明にはならない。
 */

function createMock(opts) {
  const o = Object.assign({ rerender: 'onChange', chatDelayMs: 0 }, opts);
  const state = {
    room: { gm: 'RM', name: 'テスト村', scene: '開始前' },
    me: 'RM',
    players: [],
    chat: [],            // 古い順(画面には新しい順で出す)
    nextId: 1,
    kicks: [],           // { id, name }
    posts: [],           // POST の本文(オブジェクト)
    jobsetGets: [],      // GET の updateJobset(クエリ文字列)
    requests: [],        // すべてのリクエスト "METHOD path?query"
    external: [],        // zinro.net 以外への通信(あってはならない)
    wordGm: null, wordOn: false,
    failKick: false,
    token: null, tokenSeq: 0,
  };

  function addPlayer(p) {
    const pl = Object.assign({ id: String(state.nextId++), trip: '', trip_open: undefined, is_spectator: false, job: '' }, p);
    state.players.push(pl);
    return pl;
  }
  const byName = (n) => state.players.find((p) => p.name === n);
  function say(speaker, body, system) { state.chat.push({ speaker, body, system: !!system }); }

  function playersPayload() {
    const players = {};
    for (const p of state.players) {
      players[p.id] = {
        id: p.id, name: p.name, trip: p.trip || '',
        trip_open: p.trip_open !== undefined ? p.trip_open : (p.trip ? '1' : '0'),
        is_spectator: p.is_spectator ? '1' : '0', job: p.job || '',
      };
    }
    return { room: Object.assign({}, state.room), player: { name: state.me }, players };
  }

  const chatPayload = () => state.chat.slice().reverse().map((m) => ({ from_user: m.speaker, message: m.body, system: m.system }));

  function pageHtml() {
    state.tokenSeq++;
    state.token = `tok${state.tokenSeq}`;
    return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>模擬 zinro</title></head><body>
<h1 id="title">${state.room.name}</h1>
<div id="all_players"></div>
<form id="messageForm" action="player.php" onsubmit="return false">
  <input type="hidden" name="token" value="${state.token}">
  <textarea name="message" maxlength="255"></textarea><input type="submit" value="送信">
</form>
<div id="message"><div id="message_text"></div></div>
<script>
const MODE = ${JSON.stringify(o.rerender)};
const CHAT_DELAY = ${Number(o.chatDelayMs) || 0};
const T0 = Date.now();
let lastP = '', lastM = '';
function confirmDialog() {}
function esc(s) { return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function renderPlayers(p) {
  const key = JSON.stringify(p);
  if (MODE !== 'always' && key === lastP) return;
  lastP = key;
  const rows = Object.values(p.players).map(x =>
    '<tr><td><span onclick="confirmDialog(\\'' + esc(x.name) + '\\')">' + esc(x.name) + (x.trip ? ' (' + esc(x.trip) + ')' : '') +
    '</span></td><td>' + (x.is_spectator == '1' ? '観戦' : '参戦') + '</td></tr>').join('');
  document.getElementById('all_players').innerHTML = '<table><tr><th>名前</th><th>状態</th></tr>' + rows + '</table>';
}
function renderChat(msgs) {
  if (Date.now() - T0 < CHAT_DELAY) return;
  const key = JSON.stringify(msgs);
  if (key === lastM) return;
  lastM = key;
  document.getElementById('message_text').innerHTML = msgs.map(m =>
    '<div><span class="' + (m.system ? 'from-system' : 'from-normal') + '">' + esc(m.from_user) + '</span>' +
    '<span class="' + (m.system ? 'text-system' : 'text-normal') + '">: ' + esc(m.message) + '</span></div>').join('');
}
async function poll() {
  try {
    renderPlayers(await (await fetch('/m/api/?mode=players')).json());
    renderChat((await (await fetch('/m/api/?mode=message')).json()).messages);
  } catch (e) {}
}
setInterval(poll, 400); poll();
</script></body></html>`;
  }

  const fulfill = (route, status, type, body) => route.fulfill({ status, contentType: type, body });

  async function handle(route) {
    const req = route.request();
    const url = new URL(req.url());
    if (url.hostname !== 'zinro.net') {
      state.external.push(req.url());
      return route.abort();
    }
    state.requests.push(`${req.method()} ${url.pathname}${url.search}`);

    if (url.pathname === '/m/api/') {
      const mode = url.searchParams.get('mode');
      if (mode === 'players') return fulfill(route, 200, 'application/json', JSON.stringify(playersPayload()));
      if (mode === 'message') return fulfill(route, 200, 'application/json', JSON.stringify({ messages: chatPayload() }));
    }

    if (url.pathname === '/m/player.php') {
      if (req.method() === 'POST') {
        const body = Object.fromEntries(new URLSearchParams(req.postData() || ''));
        state.posts.push(body);
        if (!body.token || body.token !== state.token) return fulfill(route, 403, 'text/plain', 'bad token');
        state.token = null;                                  // 使い切り
        if (body.mode === 'setWord') {
          if (body.is_word === 'on') state.wordOn = true;
          else {
            state.wordOn = false;
            if (state.wordGm) { const p = byName(state.wordGm); if (p) p.is_spectator = true; state.wordGm = null; }
          }
        } else if (body.mode === 'updateJobset' && body.word_gm) {
          state.wordGm = body.word_gm;
        }
        return fulfill(route, 200, 'text/plain', 'ok');
      }
      if (url.searchParams.has('kick')) {
        const id = url.searchParams.get('kick');
        state.kicks.push({ id, name: url.searchParams.get('name') });
        if (!state.failKick) state.players = state.players.filter((p) => p.id !== id);
        return fulfill(route, 200, 'text/plain', 'ok');
      }
      if (url.searchParams.get('mode') === 'updateJobset') {
        state.jobsetGets.push(url.search);
        return fulfill(route, 200, 'text/plain', 'ok');
      }
      return fulfill(route, 200, 'text/html; charset=utf-8', pageHtml());
    }
    return fulfill(route, 404, 'text/plain', 'not found');
  }

  return { state, addPlayer, byName, say, handle };
}

module.exports = { createMock };
