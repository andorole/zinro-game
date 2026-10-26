/* パネルとダイアログ(Shadow DOM。サイトのCSSと混ざらない)。
 *
 * 他人の名前・発言を表示するので、動的な文字列はすべて textContent で入れる(innerHTML は使わない)。
 * 状態の読み書きは ZK.store、操作は main.js が渡す api.handlers を呼ぶ。
 */
(function (root) {
  const ZK = (root.ZK = root.ZK || {});
  const { rules, lists, presets } = ZK;

  const CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; }
    .zk-root { font: 12px/1.5 system-ui, -apple-system, "Segoe UI", "Hiragino Sans", "Yu Gothic UI", sans-serif; color: #eee; }
    button, input, select, textarea { font: inherit; color: inherit; }
    .zk-launch { position: fixed; right: 16px; bottom: 16px; z-index: 2147483000; padding: 9px 13px; border: 0; border-radius: 8px;
      background: rgba(60,90,160,.9); color: #fff; font-weight: 700; cursor: pointer; box-shadow: 0 4px 10px rgba(0,0,0,.35); }
    .zk-launch.zk-dry { background: rgba(196,120,16,.95); }
    .zk-launch.zk-live { background: rgba(30,130,70,.95); }
    .zk-launch.zk-off { background: rgba(100,100,100,.9); }
    .zk-panel { position: fixed; right: 16px; bottom: 62px; width: 460px; max-width: calc(100vw - 24px); max-height: 76vh;
      display: flex; flex-direction: column; background: rgba(22,22,26,.985); border: 1px solid rgba(255,255,255,.14);
      border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,.6); z-index: 2147483001; overflow: hidden; }
    .zk-panel[hidden], .zk-modal[hidden] { display: none; }
    .zk-head { display: flex; align-items: center; gap: 8px; padding: 9px 12px; border-bottom: 1px solid rgba(255,255,255,.1); }
    .zk-head b { font-size: 13px; }
    .zk-grow { flex: 1; }
    .zk-x { background: none; border: 0; color: rgba(255,255,255,.6); font-size: 16px; cursor: pointer; line-height: 1; }
    .zk-banner { margin: 8px 10px 0; padding: 6px 9px; border-radius: 7px; font-size: 11px; display: flex; gap: 8px; align-items: center; }
    .zk-banner.zk-b-dry { background: rgba(196,120,16,.2); border: 1px solid rgba(230,150,40,.5); color: #ffd9a0; }
    .zk-banner.zk-b-live { background: rgba(30,130,70,.18); border: 1px solid rgba(60,180,100,.45); color: #bff0cf; }
    .zk-banner.zk-b-off { background: rgba(120,120,120,.18); border: 1px solid rgba(160,160,160,.35); color: #ccc; }
    .zk-tabs { display: flex; gap: 2px; padding: 8px 10px 0; border-bottom: 1px solid rgba(255,255,255,.1); }
    .zk-tab { padding: 5px 11px; border: 0; border-radius: 7px 7px 0 0; background: transparent; color: rgba(255,255,255,.62); cursor: pointer; }
    .zk-tab[aria-selected="true"] { background: rgba(255,255,255,.1); color: #fff; font-weight: 700; }
    .zk-body { padding: 10px; overflow: auto; min-height: 120px; }
    .zk-sec { margin-bottom: 14px; }
    .zk-sec > h4 { margin: 0 0 6px; font-size: 11px; letter-spacing: .04em; color: rgba(255,255,255,.55); font-weight: 600; }
    .zk-sub { color: rgba(255,255,255,.5); font-size: 11px; font-weight: 400; }
    .zk-row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-bottom: 6px; }
    .zk-btn { padding: 4px 10px; border: 1px solid rgba(255,255,255,.2); border-radius: 6px; background: rgba(255,255,255,.08); cursor: pointer; }
    .zk-btn:hover { background: rgba(255,255,255,.16); }
    .zk-btn:disabled { opacity: .4; cursor: not-allowed; }
    .zk-btn.zk-primary { background: rgba(70,110,200,.85); border-color: rgba(120,160,240,.6); }
    .zk-btn.zk-danger { background: rgba(190,50,50,.8); border-color: rgba(240,110,110,.6); }
    .zk-btn.zk-sm { padding: 1px 7px; font-size: 11px; }
    input[type=text], input[type=number], select, textarea { background: rgba(0,0,0,.35); border: 1px solid rgba(255,255,255,.2);
      border-radius: 6px; padding: 4px 7px; min-width: 0; }
    input[type=number] { width: 64px; }
    textarea { width: 100%; resize: vertical; font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 11px; }
    .zk-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 4px; }
    .zk-preset { padding: 7px 2px; font-size: 11px; text-align: center; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .zk-preset.zk-active { background: rgba(120,80,220,.45); border-color: rgba(180,140,255,.7); }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 3px 4px; border-bottom: 1px solid rgba(255,255,255,.07); text-align: left; vertical-align: middle; }
    th { color: rgba(255,255,255,.5); font-weight: 600; font-size: 11px; }
    td.zk-mono, .zk-mono { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 11px; word-break: break-all; }
    .zk-tag { display: inline-block; padding: 0 6px; border-radius: 4px; font-size: 10px; background: rgba(255,255,255,.14); }
    .zk-tag.zk-k-kick { background: rgba(200,60,60,.6); }
    .zk-tag.zk-k-spectate { background: rgba(60,130,200,.6); }
    .zk-tag.zk-k-allow { background: rgba(60,160,90,.6); }
    .zk-tag.zk-auto { background: rgba(180,140,40,.6); }
    .zk-msg { font-size: 11px; margin: 4px 0; white-space: pre-wrap; }
    .zk-bad { color: #ff9a9a; }
    .zk-good { color: #9fe6b4; }
    .zk-check { display: flex; gap: 6px; align-items: flex-start; margin: 0 0 6px; cursor: pointer; }
    .zk-check input { margin-top: 2px; flex: none; }
    .zk-rule { padding: 6px 8px; margin-bottom: 6px; border: 1px solid rgba(255,255,255,.1); border-radius: 8px; }
    .zk-rule.zk-dim { opacity: .55; }
    .zk-rule-head { display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; cursor: pointer; }
    .zk-rule-params { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 5px; padding-left: 22px; align-items: center; }
    .zk-log { max-height: 150px; overflow: auto; font-size: 11px; }
    .zk-log div { padding: 2px 0; border-bottom: 1px solid rgba(255,255,255,.06); }
    .zk-time { color: rgba(255,255,255,.45); margin-right: 6px; }
    details > summary { cursor: pointer; margin-bottom: 6px; color: rgba(255,255,255,.75); }
    .zk-toasts { position: fixed; top: 14px; right: 14px; z-index: 2147483002; display: flex; flex-direction: column; gap: 8px; width: 330px; max-width: calc(100vw - 28px); }
    .zk-toast { padding: 9px 11px; border-radius: 9px; background: rgba(30,30,36,.98); border: 1px solid rgba(255,255,255,.2);
      box-shadow: 0 6px 20px rgba(0,0,0,.5); font-size: 12px; }
    .zk-toast.zk-t-warn { border-color: rgba(240,180,60,.7); }
    .zk-toast.zk-t-kick { border-color: rgba(240,90,90,.8); }
    .zk-toast.zk-t-error { border-color: rgba(255,90,90,.9); background: rgba(60,20,20,.98); }
    .zk-toast .zk-row { margin: 6px 0 0; }
    .zk-modal { position: fixed; inset: 0; z-index: 2147483003; background: rgba(0,0,0,.55); display: flex; align-items: center; justify-content: center; padding: 16px; }
    .zk-dialog { width: min(440px, 100%); max-height: 86vh; overflow: auto; background: #1b1b22; border: 1px solid rgba(255,255,255,.22);
      border-radius: 12px; padding: 14px 16px; box-shadow: 0 14px 40px rgba(0,0,0,.65); }
    .zk-dialog h3 { margin: 0 0 8px; font-size: 14px; }
    .zk-dialog p { margin: 4px 0; }
    .zk-dialog .zk-row { justify-content: flex-end; margin-top: 12px; }
  `;

  /** DOM を組み立てる小さな補助(テキストは必ず textContent 相当で入る)。 */
  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    let value;
    for (const [k, v] of Object.entries(props || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'value') value = v;
      else if (k === 'checked') el.checked = !!v;
      else if (k === 'disabled') el.disabled = true;
      else if (k === 'open') el.open = true;
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : String(v));
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid == null || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    if (value !== undefined) el.value = value;
    return el;
  }

  const hhmm = (ts) => {
    const d = new Date(ts);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
  };
  const tripLabel = (e) => (e.kind === 'trip' ? `◆${e.value}` : e.value);

  function create(api) {
    const store = ZK.store;
    const H = api.handlers;
    let shadow, launch, panel, banner, tabsEl, bodyEl, toastsEl, modalEl;
    let tab = 'preset';
    let opened = false;
    let lastSig = '';
    // 画面の外に持つ状態。再描画(状態の変化で起こる)のたびに、入力途中の内容や結果を復元するために使う。
    const ui = {
      filter: { action: 'all', q: '', autoOnly: false },
      addMsg: null, importMsg: null, testRun: false, spectateLog: '', busyPreset: false,
      draft: {
        addKind: 'trip', addValue: '', addAction: 'kick', addNote: '',
        impText: '', impAct: 'kick', openImport: false, openExport: false,
        testText: '', testSpeaker: '', specName: '',
      },
    };
    const D = ui.draft;
    // <details> の開閉は、toggle イベント(非同期)ではなく summary のクリックの時点で記録する。
    // toggle を待つと、その前に再描画が起きたとき、閉じた状態で作り直されて勝手に閉じてしまう。
    /** 入力欄の値を D[key] に保つ。 */
    const keep = (key) => (e) => { D[key] = e.target.value; };

    const TABS = [['preset', '配役'], ['list', 'リスト'], ['spam', '荒らし'], ['spectate', '観戦'], ['history', '履歴']];

    function patch(fn) {
      const s = JSON.parse(JSON.stringify(store.settings()));
      fn(s);
      return store.setSettings(s);
    }

    function check(checked, onChange, label) {
      return h('label', { class: 'zk-check' }, h('input', { type: 'checkbox', checked, onchange: onChange }), h('span', null, label));
    }

    function numInput(value, meta, onChange) {
      return h('input', {
        type: 'number', value, min: meta.min, max: meta.max, step: 1,
        onchange: (e) => onChange(e.target.value),
      });
    }

    // ---------------------------------------------------------------- 配役
    function renderPreset() {
      const st = api.getState();
      const active = store.preset();
      const grid = h('div', { class: 'zk-grid' }, presets.PRESETS.map((p) => h('button', {
        class: 'zk-btn zk-preset' + (active && active.label === p.label ? ' zk-active' : ''),
        title: `${p.label}(${p.allsu}人): ${presets.describePreset(p)}`,
        disabled: !st.isRm || ui.busyPreset,
        onclick: async () => {
          ui.busyPreset = true; render();
          const ok = await H.applyPreset(p);
          ui.busyPreset = false;
          if (!ok) render();
        },
      }, p.label)));
      const cur = active ? presets.findPreset(active.label) : null;
      return h('div', null,
        h('div', { class: 'zk-sec' },
          h('h4', null, '現在の配役(観戦移動のあとに戻す先)'),
          h('div', null, cur ? h('span', null, h('b', null, `${cur.label}(${cur.allsu}人)`), ' ', h('span', { class: 'zk-sub' }, presets.describePreset(cur)))
            : h('span', { class: 'zk-sub' }, '未選択(このツールで配役を選ぶと記録されます)'))),
        h('div', { class: 'zk-sec' }, h('h4', null, '配役プリセット'), grid,
          h('div', { class: 'zk-msg zk-sub' }, st.isRm
            ? '押すとサイトの配役を変更して、ページを再読み込みします。ボタンに合わせると内訳が出ます。'
            : 'RMではないため使えません。')));
    }

    // ---------------------------------------------------------------- リスト
    function renderList() {
      const st = store.settings();
      const all = store.entries();
      const counts = { all: all.length, kick: 0, spectate: 0, allow: 0 };
      all.forEach((e) => { counts[e.action]++; });
      const f = ui.filter;
      let rows = all.filter((e) => (f.action === 'all' || e.action === f.action) && (!f.autoOnly || e.source === 'auto'));
      if (f.q.trim()) {
        const q = lists.normName(f.q);
        rows = rows.filter((e) => lists.normName(`${e.value} ${e.note}`).includes(q));
      }
      const shown = rows.slice().reverse().slice(0, 200);

      const kindSel = h('select', { value: D.addKind, onchange: keep('addKind') }, h('option', { value: 'trip' }, '酉'), h('option', { value: 'name' }, '名前(部分一致)'));
      const valIn = h('input', { type: 'text', value: D.addValue, oninput: keep('addValue'), placeholder: '◆abc... または 名前', style: 'flex:1;min-width:120px' });
      const actSel = h('select', { value: D.addAction, onchange: keep('addAction') }, Object.entries(lists.ACTIONS).map(([k, v]) => h('option', { value: k }, v)));
      const noteIn = h('input', { type: 'text', value: D.addNote, oninput: keep('addNote'), placeholder: 'メモ(任意)', style: 'width:110px' });
      const addBtn = h('button', {
        class: 'zk-btn zk-primary',
        onclick: async () => {
          const cand = { kind: kindSel.value, value: valIn.value, action: actSel.value, note: noteIn.value, source: 'manual' };
          if (!(await H.confirmAdd([cand]))) return;
          const r = await store.addEntries([cand]);
          ui.addMsg = r.added.length ? { ok: true, text: '追加しました' }
            : r.invalid.length ? { ok: false, text: r.invalid[0].reason }
              : { ok: false, text: r.conflicts.length ? '同じ値が別の動作で登録済みです(表で動作を変えてください)' : 'すでに登録済みです' };
          if (r.added.length) { D.addValue = ''; D.addNote = ''; }
          render();
        },
      }, '追加');
      valIn.addEventListener('keydown', (e) => { if (e.key === 'Enter') addBtn.click(); });

      const impText = h('textarea', { rows: 5, value: D.impText, oninput: keep('impText'), placeholder: '1行に1件。例:\n◆abcDEF1234 # 荒らし\nミドリ (◆Zx9/Qw+k1LmN)\nname:連投の人\n[観戦のみ]\n◆Pq7Rs8Tu9V # 参戦不可' });
      const impAct = h('select', { value: D.impAct, onchange: keep('impAct') }, Object.entries(lists.ACTIONS).map(([k, v]) => h('option', { value: k }, v)));
      const impBtn = h('button', {
        class: 'zk-btn zk-primary',
        onclick: async () => {
          const parsed = lists.parseImport(impText.value, impAct.value);
          const cands = parsed.items.map((i) => Object.assign({}, i, { source: 'import' }));
          if (!(await H.confirmAdd(cands))) return;
          const r = await store.addEntries(cands);
          const lines = [`追加 ${r.added.length}件(酉 ${r.added.filter((e) => e.kind === 'trip').length}・名前 ${r.added.filter((e) => e.kind === 'name').length})`];
          if (r.duplicates.length) lines.push(`重複 ${r.duplicates.length}件(登録済み)`);
          if (r.conflicts.length) lines.push(`競合 ${r.conflicts.length}件(同じ値が別の動作で登録済み。表で動作を変えてください): ${r.conflicts.slice(0, 5).map((c) => tripLabel(c.entry)).join(', ')}`);
          const bad = parsed.skipped.concat(r.invalid.map((x) => ({ line: '-', text: x.value, reason: x.reason })));
          if (bad.length) lines.push(`読めなかった行 ${bad.length}件:\n` + bad.slice(0, 8).map((b) => `  ${b.line}行目 ${b.text} … ${b.reason}`).join('\n'));
          ui.importMsg = { ok: !bad.length && !r.conflicts.length, text: lines.join('\n') };
          if (!bad.length && !r.conflicts.length) D.impText = '';     // 全部入ったら欄を空にする。残りがあれば直せるよう残す
          D.openImport = true;
          render();
        },
      }, '取り込む');

      const exp = h('textarea', { rows: 5, readonly: true });
      exp.value = lists.formatExport(all);
      const copyBtn = h('button', {
        class: 'zk-btn', onclick: async () => {
          try { await navigator.clipboard.writeText(exp.value); copyBtn.textContent = 'コピーしました'; } catch (e) { exp.select(); copyBtn.textContent = '選択しました(Ctrl+C)'; }
        },
      }, 'コピー');

      const tabBtn = (key, label) => h('button', {
        class: 'zk-btn zk-sm' + (f.action === key ? ' zk-primary' : ''),
        onclick: () => { f.action = key; render(); },
      }, `${label} ${counts[key]}`);

      const table = h('table', null,
        h('thead', null, h('tr', null, ['種別', '値', '動作', 'メモ', ''].map((t) => h('th', null, t)))),
        h('tbody', null, shown.map((e) => h('tr', null,
          h('td', null, h('span', { class: 'zk-tag' }, e.kind === 'trip' ? '酉' : '名前'), e.source === 'auto' ? h('span', { class: 'zk-tag zk-auto', title: '自動追放の結果として登録' }, '自動') : null),
          h('td', { class: 'zk-mono' }, tripLabel(e)),
          h('td', null, h('select', {
            value: e.action, onchange: (ev) => store.updateEntry(e.id, { action: ev.target.value }),
          }, Object.entries(lists.ACTIONS).map(([k, v]) => h('option', { value: k }, v)))),
          h('td', null, h('input', { type: 'text', value: e.note, style: 'width:100px', onchange: (ev) => store.updateEntry(e.id, { note: ev.target.value.trim() }) })),
          h('td', null, h('button', { class: 'zk-btn zk-sm', title: '削除', onclick: () => store.removeEntries((x) => x.id === e.id) }, '×')))),
          shown.length ? null : h('tr', null, h('td', { colspan: 5, class: 'zk-sub' }, 'なし'))));

      const autoCount = all.filter((e) => e.source === 'auto').length;
      return h('div', null,
        h('div', { class: 'zk-sec' }, h('h4', null, '自動処理'),
          check(st.listKick, (e) => patch((s) => { s.listKick = e.target.checked; }), '追放リストの人が入室したら、自動で追放する'),
          check(st.listSpectate, (e) => patch((s) => { s.listSpectate = e.target.checked; }), '観戦のみリストの人が参戦していたら、開始前に自動で観戦へ移す(配役の復元先が必要)'),
          h('div', { class: 'zk-sub' }, '除外リストの人は、荒らし判定とこの自動処理の対象外です。同じ人が複数に当たるときの優先は 除外 > 追放 > 観戦のみ。')),
        h('div', { class: 'zk-sec' }, h('h4', null, '追加'),
          h('div', { class: 'zk-row' }, kindSel, valIn), h('div', { class: 'zk-row' }, actSel, noteIn, addBtn),
          ui.addMsg ? h('div', { class: 'zk-msg ' + (ui.addMsg.ok ? 'zk-good' : 'zk-bad') }, ui.addMsg.text) : null),
        h('details', { class: 'zk-sec', open: D.openImport }, h('summary', { onclick: (e) => { D.openImport = !e.currentTarget.parentElement.open; } }, '一括取り込み(貼り付け)'),
          impText, h('div', { class: 'zk-row', style: 'margin-top:6px' }, '動作の既定:', impAct, impBtn),
          ui.importMsg ? h('div', { class: 'zk-msg ' + (ui.importMsg.ok ? 'zk-good' : 'zk-bad') }, ui.importMsg.text) : null),
        h('details', { class: 'zk-sec', open: D.openExport }, h('summary', { onclick: (e) => { D.openExport = !e.currentTarget.parentElement.open; } }, '書き出し(バックアップ・他のPCへ)'), exp, h('div', { class: 'zk-row', style: 'margin-top:6px' }, copyBtn)),
        h('div', { class: 'zk-sec' }, h('h4', null, `登録一覧(${all.length}件)`),
          h('div', { class: 'zk-row' }, tabBtn('all', 'すべて'), tabBtn('kick', '追放'), tabBtn('spectate', '観戦のみ'), tabBtn('allow', '除外')),
          h('div', { class: 'zk-row' },
            h('input', { type: 'text', placeholder: '検索', value: f.q, style: 'flex:1', oninput: (e) => { f.q = e.target.value; } , onchange: () => render() }),
            h('label', null, h('input', { type: 'checkbox', checked: f.autoOnly, onchange: (e) => { f.autoOnly = e.target.checked; render(); } }), ' 自動登録のみ'),
            autoCount ? h('button', { class: 'zk-btn zk-sm', onclick: async () => { if (await H.confirmSimple(`自動登録の${autoCount}件をすべて削除しますか?`)) store.removeEntries((e) => e.source === 'auto'); } }, '自動登録を全削除') : null),
          table, rows.length > shown.length ? h('div', { class: 'zk-sub' }, `新しい順に${shown.length}件を表示(全${rows.length}件)`) : null));
    }

    // ---------------------------------------------------------------- 荒らし
    function renderSpam() {
      const st = store.settings();
      const cfg = st.spam;
      const state = api.getState();

      const ruleRows = rules.RULES.map((meta) => {
        const r = cfg.rules[meta.id];
        return h('div', { class: 'zk-rule' + (r.enabled ? '' : ' zk-dim') },
          h('label', { class: 'zk-rule-head' },
            h('input', { type: 'checkbox', checked: r.enabled, onchange: (e) => patch((s) => { s.spam.rules[meta.id].enabled = e.target.checked; }) }),
            h('b', null, meta.label), h('span', { class: 'zk-sub' }, meta.help)),
          h('div', { class: 'zk-rule-params' },
            meta.params.map((p) => h('label', null, `${p.label} `, numInput(r[p.key], p, (v) => patch((s) => { s.spam.rules[meta.id][p.key] = v; })), ` ${p.unit}`)),
            h('label', null, '当たると ', numInput(r.points, { min: 0, max: 10 }, (v) => patch((s) => { s.spam.rules[meta.id].points = v; })), ' 点')));
      });

      const spk = h('input', { type: 'text', value: D.testSpeaker, oninput: keep('testSpeaker'), placeholder: '発言者名(任意)', style: 'width:130px' });
      const area = h('textarea', { rows: 4, value: D.testText, oninput: keep('testText'), placeholder: '荒らしの発言を貼り付けて、どのルールに何点当たるかを調べます(送信も保存もしません)' });
      const out = h('div', { class: 'zk-msg' });
      const showOut = (res) => {
        out.replaceChildren();
        const m = res.metrics;
        out.append(
          h('div', { class: res.points >= cfg.kickPoints ? 'zk-bad' : res.points ? '' : 'zk-good' },
            `${res.points}点 / 追放ライン${cfg.kickPoints}点` + (res.points >= cfg.kickPoints ? ' → この1発言で追放' : res.points ? ' → 警告(あと' + (cfg.kickPoints - res.points) + '点)' : ' → 当たらない')),
          ...res.hits.map((x) => h('div', null, `・${x.label} +${x.points}点 … ${x.detail}`)),
          h('div', { class: 'zk-sub' }, `${m.len}字 / 結合記号+不可視 ${m.mayo.total}字 / ジャワ文字 ${m.java}字 / 「名前:」${m.log.tokens}個 / 構造 ${m.structure.score}/4 / ${m.topic.onTopic ? '話題内' : '話題外'}`));
      };
      // 結果は入力と今の設定から毎回計算し直す(再描画しても残り、しきい値を変えるとその場で更新される)
      if (ui.testRun) showOut(H.evaluateText(D.testText, D.testSpeaker.trim()));
      const testBtn = h('button', { class: 'zk-btn', onclick: () => { D.testText = area.value; D.testSpeaker = spk.value; ui.testRun = true; render(); } }, '判定する');

      const logRows = state.log.slice().reverse().slice(0, 60);
      const kl = store.kickLog().slice(0, 30);

      return h('div', null,
        h('div', { class: 'zk-sec' }, h('h4', null, '動作'),
          check(st.spamEnabled, (e) => patch((s) => { s.spamEnabled = e.target.checked; }), '荒らしの自動追放を使う'),
          check(st.dryRun, (e) => H.setDryRun(e.target.checked), '試運転(判定と記録だけ行い、自動の追放・観戦移動はしない)'),
          h('div', { class: 'zk-row' },
            h('label', null, '追放する合計点 ', numInput(cfg.kickPoints, { min: 1, max: 20 }, (v) => patch((s) => { s.spam.kickPoints = v; }))),
            h('label', null, '点の有効期間 ', numInput(cfg.windowMin, { min: 1, max: 1440 }, (v) => patch((s) => { s.spam.windowMin = v; })), ' 分'),
            h('label', null, '1発言の上限 ', numInput(cfg.chatCap, { min: 20, max: 5000 }, (v) => patch((s) => { s.spam.chatCap = v; })), ' 字')),
          check(st.autoRegister, (e) => patch((s) => { s.autoRegister = e.target.checked; }), '自動追放した人の酉(公開されているもの)をリストへ自動登録する'),
          h('div', { class: 'zk-sub' }, '各ルールに当たった発言は点が付き、同じ人の点が合計に届くと追放します。1点だけなら警告にとどめます。マヨビームとジャワ文字は、同じ発言の中では合わせて1点までです(=「2回以上投稿したら追放」)。同一文字の連続(「あああ」)は検知しません。')),
        h('div', { class: 'zk-sec' }, h('h4', null, 'ルール'), ruleRows),
        h('div', { class: 'zk-sec' }, h('h4', null, '判定テスト'), h('div', { class: 'zk-row' }, spk), area, h('div', { class: 'zk-row', style: 'margin-top:6px' }, testBtn), out),
        h('div', { class: 'zk-sec' }, h('h4', null, `最近の検知・処理(このタブ)`),
          h('div', { class: 'zk-log' }, logRows.length ? logRows.map((l) => h('div', null, h('span', { class: 'zk-time' }, hhmm(l.ts)), l.text)) : h('div', { class: 'zk-sub' }, 'まだありません'))),
        h('div', { class: 'zk-sec' }, h('h4', null, `追放ログ(保存・最新${kl.length}件)`),
          h('div', { class: 'zk-log', style: 'max-height:200px' }, kl.length ? kl.map((k) => h('div', null,
            h('span', { class: 'zk-time' }, `${new Date(k.ts).getMonth() + 1}/${new Date(k.ts).getDate()} ${hhmm(k.ts)}`),
            h('b', null, k.name), k.trip ? h('span', { class: 'zk-mono zk-sub' }, ` ◆${k.trip}`) : null, ` — ${k.reason}`, ' ',
            h('button', { class: 'zk-btn zk-sm', onclick: () => H.registerLogEntry(k, 'kick') }, 'リストへ登録'))) : h('div', { class: 'zk-sub' }, 'まだありません')),
          kl.length ? h('div', { class: 'zk-row', style: 'margin-top:6px' }, h('button', { class: 'zk-btn zk-sm', onclick: () => store.clearKickLog() }, 'ログを消す')) : null));
    }

    // ---------------------------------------------------------------- 観戦
    function renderSpectate() {
      const st = api.getState();
      const active = store.preset();
      const cands = st.players.filter((p) => !ZK.zinro.isSpectator(p) && p.name !== st.me);
      const sel = h('select', { style: 'flex:1', disabled: !cands.length, onchange: keep('specName') }, cands.length
        ? cands.map((p) => h('option', { value: p.name }, p.name)) : [h('option', { value: '' }, '移せる参戦者がいません')]);
      if (cands.some((p) => p.name === D.specName)) sel.value = D.specName;
      const go = h('button', {
        class: 'zk-btn zk-primary', disabled: !st.isRm || !cands.length || !st.pregame,
        onclick: async () => { if (sel.value) { ui.spectateLog = ''; await H.moveSpectator(sel.value, { manual: true }); } },
      }, '観戦に移動');
      return h('div', null,
        h('div', { class: 'zk-sec' }, h('h4', null, '参戦者を観戦へ移す'),
          h('div', { class: 'zk-sub', style: 'margin-bottom:6px' }, 'サイトのワードウルフ機能の「お題役」に指定して外し、配役を元に戻します。約20秒かかり、終わるとページを再読み込みします。ゲーム開始前だけ使えます。'),
          h('div', { class: 'zk-row' }, sel, go),
          !st.isRm ? h('div', { class: 'zk-msg zk-bad' }, 'RMではないため使えません。') : null,
          st.isRm && !st.pregame ? h('div', { class: 'zk-msg zk-bad' }, 'ゲーム開始前ではないため使えません。') : null,
          h('div', { class: 'zk-msg zk-sub', id: 'zk-spec-log' }, ui.spectateLog)),
        h('div', { class: 'zk-sec' }, h('h4', null, '配役の復元先'),
          active ? h('div', null, h('b', null, active.label), h('span', { class: 'zk-sub' }, ` (${active.allsu}人)`))
            : h('div', { class: 'zk-msg zk-bad' }, '未選択です。このまま移すと、配役が「人狼1」だけの状態で残ります。先に「配役」タブで選んでください(自動の観戦移動は、配役が未選択だと行いません)。'),
          h('div', { class: 'zk-sub' }, 'サイトの画面で配役を手で変えた場合は、ここの記録と食い違うので、「配役」タブでもう一度選び直してください。')));
    }

    // ---------------------------------------------------------------- 履歴
    function renderHistory() {
      const st = api.getState();
      const entries = store.entries();
      const rows = st.history.slice().reverse().slice(0, 60);
      return h('div', null,
        h('div', { class: 'zk-sub', style: 'margin-bottom:6px' }, 'このタブを開いてから入室した人です(タブを閉じると消えます)。荒らしが出て退出・追放されたあとでも、ここから登録できます。公開されていない酉は登録せず、名前で登録します(名前は部分一致なので、短い名前は他の人にも当たります)。'),
        h('table', null,
          h('thead', null, h('tr', null, ['時刻', '名前 / 酉', 'リスト', '登録'].map((t) => h('th', null, t)))),
          h('tbody', null, rows.length ? rows.map((r) => {
            const hit = lists.resolve({ name: r.name, trip: r.trip }, entries);
            const btn = (action) => h('button', { class: 'zk-btn zk-sm', onclick: () => H.registerHistory(r, action) }, lists.ACTIONS[action]);
            return h('tr', null,
              h('td', { class: 'zk-time' }, hhmm(r.ts)),
              h('td', null, h('div', null, r.name), r.trip ? h('div', { class: 'zk-mono zk-sub' }, r.trip.startsWith('◆') ? r.trip : `◆${r.trip}`, r.tripOpen ? '' : '(非公開)') : null),
              h('td', null, hit ? h('span', { class: `zk-tag zk-k-${hit.action}` }, lists.ACTIONS[hit.action]) : h('span', { class: 'zk-sub' }, '-')),
              h('td', null, h('div', { class: 'zk-row', style: 'margin:0;flex-wrap:nowrap' }, btn('kick'), btn('spectate'), btn('allow'))));
          }) : [h('tr', null, h('td', { colspan: 4, class: 'zk-sub' }, 'まだ入室がありません'))])));
    }

    // ---------------------------------------------------------------- 全体
    const RENDERERS = { preset: renderPreset, list: renderList, spam: renderSpam, spectate: renderSpectate, history: renderHistory };

    function renderBanner() {
      const st = api.getState();
      const s = store.settings();
      banner.replaceChildren();
      banner.className = 'zk-banner';
      if (!st.ready) {
        banner.classList.add('zk-b-off');
        banner.append('村の情報を読み込み中です…');
      } else if (!st.isRm) {
        banner.classList.add('zk-b-off');
        banner.append('RMではないため、追放・配役変更・観戦移動は使えません(リストと設定の編集はできます)');
      } else if (s.dryRun) {
        banner.classList.add('zk-b-dry');
        banner.append(h('span', { class: 'zk-grow' }, '🧪 試運転中: 判定と記録だけ行い、自動の追放・観戦移動はしません(手動の操作は実行されます)'),
          h('button', { class: 'zk-btn zk-sm', onclick: () => H.setDryRun(false) }, '本番にする'));
      } else {
        banner.classList.add('zk-b-live');
        banner.append(h('span', { class: 'zk-grow' }, '● 本番: 条件に当たった人を自動で追放・観戦移動します'),
          h('button', { class: 'zk-btn zk-sm', onclick: () => H.setDryRun(true) }, '試運転に戻す'));
      }
    }

    function renderLauncher() {
      const st = api.getState();
      const s = store.settings();
      launch.className = 'zk-launch ' + (!st.isRm ? 'zk-off' : s.dryRun ? 'zk-dry' : 'zk-live');
      launch.textContent = !st.isRm ? 'RM補助' : s.dryRun ? 'RM補助 🧪' : 'RM補助 ●';
      launch.title = !st.ready ? '村の情報を読み込み中です' : !st.isRm ? 'RMではありません'
        : s.dryRun ? '試運転中(自動の追放はしません)' : '本番(自動で追放・観戦移動します)';
    }

    function render() {
      renderLauncher();
      if (!opened) return;
      renderBanner();
      tabsEl.replaceChildren(...TABS.map(([key, label]) => h('button', {
        class: 'zk-tab', role: 'tab', 'aria-selected': String(key === tab),
        onclick: () => { tab = key; render(); },
      }, label)));
      const scroll = bodyEl.scrollTop;
      bodyEl.replaceChildren(RENDERERS[tab]());
      bodyEl.scrollTop = scroll;
    }

    /** 状態が変わったとき。入力中は壊さない。 */
    function refresh() {
      renderLauncher();
      if (!opened) return;
      // 文字を打っている最中は再描画しない(入力が途切れるため)。チェックボックスやボタンにフォーカスが
      // 残っているだけなら、画面を最新にする。
      const active = shadow.activeElement;
      if (active && (active.tagName === 'TEXTAREA' ||
        (active.tagName === 'INPUT' && !/^(checkbox|radio|button|submit)$/.test(active.type)))) return;
      if (!modalEl.hidden) return;
      const st = api.getState();
      const sig = JSON.stringify([tab, st.ready, st.isRm, st.pregame, st.players.map((p) => p.name + (p.is_spectator || '')),
        st.history.length, st.log.length, store.settings(), store.entries().length, store.preset(), store.kickLog().length]);
      if (sig === lastSig) return;
      lastSig = sig;
      render();
    }

    function toast(text, opt) {
      const o = opt || {};
      const el = h('div', { class: `zk-toast zk-t-${o.kind || 'info'}` }, h('div', null, text));
      if (o.actions && o.actions.length) {
        el.append(h('div', { class: 'zk-row' }, o.actions.map((a) => h('button', {
          class: 'zk-btn zk-sm', onclick: () => { a.onClick(); el.remove(); },
        }, a.label))));
      }
      toastsEl.append(el);
      const ttl = o.ttl == null ? 9000 : o.ttl;
      if (ttl > 0) setTimeout(() => el.remove(), ttl);
      while (toastsEl.children.length > 5) toastsEl.firstChild.remove();
      return el;
    }

    /** @returns {Promise<any>} 押したボタンの value。閉じたら null。 */
    function dialog({ title, lines, buttons }) {
      return new Promise((resolve) => {
        const done = (v) => { modalEl.hidden = true; modalEl.replaceChildren(); document.removeEventListener('keydown', onKey, true); resolve(v); };
        const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); done(null); } };
        document.addEventListener('keydown', onKey, true);
        modalEl.replaceChildren(h('div', { class: 'zk-dialog', role: 'dialog', 'aria-modal': 'true' },
          h('h3', null, title),
          (lines || []).map((l) => h('p', null, l)),
          h('div', { class: 'zk-row' }, (buttons || []).map((b) => h('button', {
            class: 'zk-btn' + (b.kind ? ` zk-${b.kind}` : ''), onclick: () => done(b.value),
          }, b.label)))));
        modalEl.onclick = (e) => { if (e.target === modalEl) done(null); };
        modalEl.hidden = false;
        const first = modalEl.querySelector('.zk-btn.zk-primary, .zk-btn.zk-danger') || modalEl.querySelector('.zk-btn');
        if (first) first.focus();
      });
    }

    function mount() {
      const host = document.createElement('div');
      host.id = 'zk-host';
      shadow = host.attachShadow({ mode: 'open' });
      launch = h('button', { class: 'zk-launch', onclick: (e) => { e.stopPropagation(); toggle(); } }, 'RM補助');
      banner = h('div', { class: 'zk-banner' });
      tabsEl = h('div', { class: 'zk-tabs', role: 'tablist' });
      bodyEl = h('div', { class: 'zk-body' });
      panel = h('div', { class: 'zk-panel', hidden: true },
        h('div', { class: 'zk-head' }, h('b', null, 'RM補助'), h('span', { class: 'zk-grow' }), h('button', { class: 'zk-x', title: '閉じる', onclick: () => toggle(false) }, '×')),
        banner, tabsEl, bodyEl);
      toastsEl = h('div', { class: 'zk-toasts' });
      modalEl = h('div', { class: 'zk-modal', hidden: true });
      shadow.append(h('style', null, CSS), h('div', { class: 'zk-root' }, launch, panel, toastsEl, modalEl));
      // パネルの入力欄で打ったキーに、サイト側のショートカット等が反応しないようにする
      for (const ev of ['keydown', 'keyup', 'keypress']) host.addEventListener(ev, (e) => e.stopPropagation());
      document.documentElement.append(host);
      store.onChange(() => refresh());
      renderLauncher();
    }

    function toggle(force) {
      opened = force == null ? !opened : !!force;
      panel.hidden = !opened;
      if (opened) { lastSig = ''; render(); }
    }

    function setSpectateLog(msg) {
      ui.spectateLog = msg;
      const el = shadow && shadow.getElementById('zk-spec-log');
      if (el) el.textContent = msg;
    }

    function openTab(name) {
      if (RENDERERS[name]) tab = name;
      toggle(true);
    }

    return {
      mount, refresh, render, toast, dialog, toggle, openTab, setSpectateLog,
      getTab: () => tab, isOpen: () => opened,
    };
  }

  ZK.ui = { create, h };
})(globalThis);
