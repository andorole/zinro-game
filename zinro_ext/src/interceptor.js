/* MAIN world(zinro.net 自身と同じスコープ)で動く。
 *
 * サイトが自分で行っている参加者一覧の取得(/m/api/?mode=players)の応答を横から読み、
 * CustomEvent「zk_players」で拡張側(content script)に渡す。拡張が自前でポーリングしなくて済む。
 * 外部には何も送らない。サイトの通信の結果は変えない(clone した複製を読むだけ)。
 */
(function () {
  if (window.__zkInterceptor) return;
  window.__zkInterceptor = true;

  const isPlayersUrl = (url) => /\/m\/api\//.test(url) && /[?&]mode=players(?:&|$)/.test(url);
  const emit = (json) => {
    if (json && json.players) window.dispatchEvent(new CustomEvent('zk_players', { detail: json }));
  };

  const origFetch = window.fetch;
  window.fetch = async function (input) {
    const res = await origFetch.apply(this, arguments);
    try {
      const url = typeof input === 'string' ? input : (input && (input.url || input.href)) || String(input);
      if (isPlayersUrl(url)) res.clone().json().then(emit).catch(() => {});
    } catch (e) { /* サイトの通信は妨げない */ }
    return res;
  };

  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__zkUrl = String(url);
    return origOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function () {
    this.addEventListener('load', function () {
      try { if (isPlayersUrl(this.__zkUrl || '')) emit(JSON.parse(this.responseText)); } catch (e) { /* 無視 */ }
    });
    return origSend.apply(this, arguments);
  };
})();
