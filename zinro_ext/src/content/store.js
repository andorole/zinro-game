/* 保存。
 *   chrome.storage.local: 設定・リスト・選択中の配役・追放ログ(ブラウザを閉じても残る。このPCの中だけ)
 *   sessionStorage:       点数・入室履歴・検知ログなど(タブを閉じると消える)
 * どこにも送信しない。
 */
(function (root) {
  const ZK = (root.ZK = root.ZK || {});
  const { rules, lists } = ZK;

  const KEY = {
    settings: 'zk_settings_v1',
    entries: 'zk_entries_v1',
    preset: 'zk_preset_v1',
    kicklog: 'zk_kicklog_v1',
  };
  const KICKLOG_MAX = 100;

  /** 試運転(dryRun)は既定ON: 初めて使うときは、判定と記録だけして、実際には追放や観戦移動をしない。 */
  function normalizeSettings(raw) {
    const s = raw && typeof raw === 'object' ? raw : {};
    return {
      dryRun: s.dryRun !== false,
      listKick: s.listKick !== false,
      listSpectate: s.listSpectate !== false,
      spamEnabled: s.spamEnabled !== false,
      autoRegister: s.autoRegister === true,
      spam: rules.normalizeConfig(s.spam),
    };
  }

  function validEntry(e) {
    return e && (e.kind === 'trip' || e.kind === 'name') && typeof e.value === 'string' && e.value !== '' &&
      (e.action === 'kick' || e.action === 'spectate' || e.action === 'allow');
  }

  let settings = normalizeSettings();
  let entries = [];
  let preset = null;
  let kicklog = [];
  const listeners = new Set();
  const emit = () => listeners.forEach((fn) => { try { fn(); } catch (e) { console.error('[zk]', e); } });

  function read(got) {
    settings = normalizeSettings(got[KEY.settings]);
    entries = Array.isArray(got[KEY.entries]) ? got[KEY.entries].filter(validEntry) : [];
    preset = got[KEY.preset] && got[KEY.preset].label ? got[KEY.preset] : null;
    kicklog = Array.isArray(got[KEY.kicklog]) ? got[KEY.kicklog] : [];
  }

  async function init() {
    read(await chrome.storage.local.get(Object.values(KEY)));
    // 別のタブでの変更も反映する
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area !== 'local') return;
      const next = {
        [KEY.settings]: settings, [KEY.entries]: entries, [KEY.preset]: preset, [KEY.kicklog]: kicklog,
      };
      let touched = false;
      for (const k of Object.values(KEY)) if (changes[k]) { next[k] = changes[k].newValue; touched = true; }
      if (touched) { read(next); emit(); }
    });
  }

  const save = (obj) => chrome.storage.local.set(obj);

  async function setSettings(next) {
    settings = normalizeSettings(next);
    await save({ [KEY.settings]: settings });
    emit();
  }

  async function setEntries(list) {
    entries = list.filter(validEntry);
    await save({ [KEY.entries]: entries });
    emit();
  }

  /** @returns {Promise<ReturnType<typeof lists.addEntries>>} */
  async function addEntries(candidates) {
    const r = lists.addEntries(entries, candidates);
    if (r.added.length) await setEntries(r.entries);
    return r;
  }

  async function updateEntry(id, patch) {
    await setEntries(entries.map((e) => (e.id === id ? Object.assign({}, e, patch) : e)));
  }

  async function removeEntries(pred) {
    await setEntries(entries.filter((e) => !pred(e)));
  }

  async function setPreset(p) {
    preset = p ? { label: p.label, allsu: p.allsu } : null;
    await save({ [KEY.preset]: preset });
    emit();
  }

  async function pushKickLog(item) {
    kicklog = [item].concat(kicklog).slice(0, KICKLOG_MAX);
    await save({ [KEY.kicklog]: kicklog });
    emit();
  }

  async function clearKickLog() {
    kicklog = [];
    await save({ [KEY.kicklog]: kicklog });
    emit();
  }

  const session = {
    get(key, fallback) {
      try {
        const v = sessionStorage.getItem(key);
        return v == null ? fallback : JSON.parse(v);
      } catch (e) { return fallback; }
    },
    set(key, value) {
      try { sessionStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* 容量超過など */ }
    },
  };

  ZK.store = {
    init, normalizeSettings, session,
    settings: () => settings,
    entries: () => entries,
    preset: () => preset,
    kickLog: () => kicklog,
    setSettings, setEntries, addEntries, updateEntry, removeEntries, setPreset, pushKickLog, clearKickLog,
    onChange: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
  };
})(globalThis);
