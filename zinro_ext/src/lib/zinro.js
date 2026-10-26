/* zinro.net の画面・API の読み取り(サイト依存はここに集める)。
 *
 * 参加者API(/m/api/?mode=players)の形、チャット欄のDOM、KICK の URL は、公開されていた
 * 旧拡張の実装を手がかりにしている。サイトが変わったらここを直す。
 *   players: { room:{gm,name,scene|status}, player:{name}, players:{ id: {id,name,trip,trip_open,is_spectator,job,...} } }
 *   チャット: #message > #message_text > div(新しい発言が先頭)。行は .from-normal/.from-system(発言者) と
 *             .text-normal/.text-system(本文)。システム通知の発言者は「鯖」。
 */
(function (root, factory) {
  const api = factory(typeof require === 'function' ? require('./text') : root.ZK.text);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else { root.ZK = root.ZK || {}; root.ZK.zinro = api; }
})(typeof globalThis !== 'undefined' ? globalThis : this, function (text) {
  const SYSTEM_SPEAKER = '鯖';
  const DAY1_VICTIM = '初日犠牲者';

  // ---- 参加者API ----
  function isSpectator(p) {
    if (!p) return false;
    if (p.job === '観戦者' || p.job === '見学者') return true;
    const spec = p.is_spectator ?? p.spectator ?? p.watch ?? p.is_watch ?? 0;
    return spec === 1 || spec === '1' || spec === true;
  }

  /** 初日犠牲者(ダミー)を除いた参加者・観戦者。 */
  function playersOf(data) {
    return Object.values((data && data.players) || {}).filter((p) => p && p.name && p.name !== DAY1_VICTIM);
  }

  function amIGm(data) {
    const gm = data && data.room && data.room.gm;
    const me = data && data.player && data.player.name;
    return !!(gm && me && gm === me);
  }

  function sceneOf(data) {
    const r = (data && data.room) || {};
    return String(r.scene ?? r.status ?? '');
  }

  /** ゲーム開始前(配役変更や観戦移動ができる状態)か。 */
  function isPregame(data) {
    return ['', '開始前', 'waiting', '0'].includes(sceneOf(data));
  }

  /** 公開されている酉だけを返す(trip_open が "1")。 */
  function publicTrip(p) {
    return p && p.trip && String(p.trip_open) === '1' ? String(p.trip) : '';
  }

  function findByName(players, name) {
    if (!name) return null;
    const exact = players.find((p) => p.name === name);
    if (exact) return exact;
    const n = text.nfkc(name);
    return players.find((p) => text.nfkc(p.name) === n) || null;
  }

  function roomKey(data) {
    return String((data && data.room && data.room.name) || 'room');
  }

  function kickPath(id, name) {
    return `/m/player.php?kick=${encodeURIComponent(id)}&name=${encodeURIComponent(name)}`;
  }

  /** player.php の HTML から、フォーム送信用の token を取る(属性の並びは問わない)。 */
  function extractToken(html) {
    const tag = /<input\b[^>]*\bname\s*=\s*["']token["'][^>]*>/i.exec(String(html == null ? '' : html));
    const value = tag && /\bvalue\s*=\s*["']([^"']+)["']/i.exec(tag[0]);
    return value ? value[1] : null;
  }

  // ---- チャットの読み取り ----
  function cleanSpeaker(s) {
    return String(s == null ? '' : s).replace(/[()（）[\]◆◇]/g, '').trim();
  }

  /** DOM の構造から取れないときの予備。「名前: 本文」を、既知の名前を先頭から探して分ける。 */
  function splitChatLine(raw, knownNames) {
    const t = String(raw == null ? '' : raw).trim().replace(/\s+/g, ' ').replace(/^[()（）[\]◆◇]+/, '');
    const names = [...new Set((knownNames || []).concat([SYSTEM_SPEAKER]))].sort((a, b) => b.length - a.length);
    for (const n of names) {
      if (!n || !t.startsWith(n)) continue;
      const m = /^[)）\]]?\s*(?:→\s*[^:：]+?)?\s*[:：]\s*(.*)$/.exec(t.slice(n.length));
      if (m) return { speaker: n, body: m[1].trim() };
    }
    return null;
  }

  /**
   * チャット欄の行から発言者と本文を取る。
   * @param {Element} el
   * @param {string[]} names 参加者名(予備の分割に使う)
   */
  function parseChatItem(el, names) {
    const nameEl = el.querySelector(':scope > .from-normal, :scope > .from-system, :scope > .name, :scope > .speaker');
    const bodyEl = el.querySelector(':scope > .text-normal, :scope > .text-system, :scope > .body, :scope > .msg');
    let speaker = cleanSpeaker(nameEl && nameEl.textContent);
    let body = ((bodyEl && bodyEl.textContent) || '').trim().replace(/^\s*[:：]\s*/, '');
    if (!speaker || !body) {
      const alt = splitChatLine(el.textContent, names);
      if (alt) { speaker = alt.speaker; body = alt.body; }
    }
    return { speaker, body };
  }

  function chatContainer(doc) {
    return doc.getElementById('message') || doc.getElementById('message_text') ||
      doc.getElementById('talk_list') || doc.getElementById('talks') || null;
  }

  /** チャット欄の発言の行(DOM の並び順のまま)。 */
  function chatItems(doc) {
    const items = [];
    const seen = new Set();
    const push = (el) => { if (el && !seen.has(el)) { seen.add(el); items.push(el); } };
    const message = doc.getElementById('message');
    const messageText = doc.getElementById('message_text');
    if (message) {
      for (const el of Array.from(message.children)) {
        if (el.id === 'message_text') Array.from(el.children).filter((c) => c.tagName === 'DIV').forEach(push);
        else if (el.tagName === 'DIV') push(el);
      }
      return items;
    }
    if (messageText) {
      Array.from(messageText.children).filter((c) => c.tagName === 'DIV').forEach(push);
      return items;
    }
    const box = doc.getElementById('talk_list') || doc.getElementById('talks');
    return box ? Array.from(box.querySelectorAll('li, .talk_item')) : [];
  }

  /** 参加者表の行から名前を取る(旧拡張と同じ読み方)。 */
  function playerRowName(row) {
    const span = row.querySelector('td span[onclick*="confirmDialog"]');
    return span ? span.textContent.split('(')[0].trim() : '';
  }

  // ---- 新しい発言だけを取り出す ----
  /**
   * 前回までに処理した分との差から、新しい発言だけを返す。
   * サイトが一覧を作り直しても二重に数えず、同じ内容の連投は回数ぶん数える。
   * @param {{key:string}[]} items 現在の発言(DOM の並び)
   * @param {Object<string,number>} processed キーごとの処理済みの数
   * @param {{newestFirst?:boolean}} [opt] 新しい発言が先頭か(既定 true)
   * @returns {{fresh:object[], next:Object<string,number>}} fresh は古い順
   */
  function diffNew(items, processed, opt) {
    const newestFirst = !opt || opt.newestFirst !== false;
    const cur = new Map();
    for (const it of items) cur.set(it.key, (cur.get(it.key) || 0) + 1);
    const taken = new Map();
    const fresh = [];
    for (const it of items) {
      const newCount = Math.max(0, cur.get(it.key) - (processed[it.key] || 0));
      const idx = taken.get(it.key) || 0;
      taken.set(it.key, idx + 1);
      if (idx < newCount) fresh.push(it);
    }
    if (newestFirst) fresh.reverse();
    return { fresh, next: Object.fromEntries(cur) };
  }

  return {
    SYSTEM_SPEAKER, DAY1_VICTIM, isSpectator, playersOf, amIGm, sceneOf, isPregame, publicTrip,
    findByName, roomKey, kickPath, extractToken, cleanSpeaker, splitChatLine, parseChatItem, chatContainer,
    chatItems, playerRowName, diffNew,
  };
});
