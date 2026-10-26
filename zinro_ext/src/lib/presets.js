/* 配役プリセット。
 *
 * jobs は [役職番号, 人数] の並び。サイトの job_N パラメータにそのまま渡す(並び順も同じ)。
 * allsu に満たない分は村人になる。27種、4〜19人。
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else { root.ZK = root.ZK || {}; root.ZK.presets = api; }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  // 役職番号 → 役職名(zinro.net の job_N)
  const JOB_NAMES = {
    1: '人狼', 2: '予言者', 3: '狩人', 4: '占い師', 5: '霊能者',
    6: '狂人', 7: '狂信者', 8: '妖狐', 9: '背徳者', 10: '猫又',
    11: '共有者', 12: '役人', 13: '怪盗', 14: '狼憑き',
    15: 'ものまね', 16: 'てるてる', 17: '恋人', 18: 'パン屋', 19: '黒猫',
  };

  const PRESETS = [
    { label: '4A', allsu: 4, jobs: [[1, 1]] },
    { label: '夏至(4人)', allsu: 4, jobs: [[1, 1], [6, 1]] },
    { label: 'ルアー(4人)', allsu: 4, jobs: [[1, 1], [16, 1]] },
    { label: '4A占', allsu: 4, jobs: [[1, 1], [4, 1]] },
    { label: '6A', allsu: 6, jobs: [[1, 1], [4, 1]] },
    { label: '6B', allsu: 6, jobs: [[1, 1], [4, 1], [8, 1]] },
    { label: '6C', allsu: 6, jobs: [[1, 1], [6, 3], [4, 1], [3, 1]] },
    { label: 'メチ(6人)', allsu: 6, jobs: [[1, 1], [3, 2], [10, 1], [4, 1], [11, 1]] },
    { label: '8CFO', allsu: 8, jobs: [[1, 2], [6, 1], [4, 1], [5, 1], [11, 2]] },
    { label: '8CNO', allsu: 8, jobs: [[1, 2], [6, 2], [4, 2], [5, 2]] },
    { label: '9D', allsu: 9, jobs: [[1, 1], [4, 1], [8, 1], [15, 2]] },
    { label: '10A狩', allsu: 10, jobs: [[1, 2], [6, 1], [4, 1], [3, 1], [5, 1]] },
    { label: '10C猫', allsu: 10, jobs: [[1, 3], [6, 1], [4, 2], [3, 1], [5, 1], [8, 1], [10, 1]] },
    { label: '11C猫', allsu: 11, jobs: [[1, 3], [6, 1], [4, 2], [3, 1], [5, 1], [8, 1], [10, 1]] },
    { label: '11A', allsu: 11, jobs: [[1, 2], [6, 1], [4, 1], [3, 1], [5, 1]] },
    { label: '12A猫', allsu: 12, jobs: [[1, 3], [6, 1], [4, 1], [3, 1], [5, 1], [10, 1]] },
    { label: '12B', allsu: 12, jobs: [[1, 2], [6, 1], [4, 1], [3, 1], [5, 1], [8, 1]] },
    { label: '12B背徳猫', allsu: 12, jobs: [[1, 3], [6, 1], [4, 1], [3, 1], [5, 1], [8, 1], [9, 1], [10, 1]] },
    { label: '12W', allsu: 12, jobs: [[1, 3], [4, 1], [5, 1], [3, 1], [6, 1], [10, 1], [8, 2], [7, 1], [9, 1]] },
    { label: '12R猫FO', allsu: 12, jobs: [[1, 2], [4, 1], [5, 1], [3, 1], [6, 1], [10, 1], [8, 2], [7, 1], [9, 1]] },
    { label: '13Z', allsu: 13, jobs: [[1, 2], [6, 1], [4, 1], [3, 1], [5, 1], [16, 1]] },
    { label: '14D猫', allsu: 14, jobs: [[1, 3], [4, 1], [5, 1], [3, 1], [6, 1], [10, 1], [8, 2], [7, 1], [9, 1]] },
    { label: '16A', allsu: 16, jobs: [[1, 3], [6, 1], [4, 1], [3, 1], [5, 1], [8, 2], [7, 1]] },
    { label: '16D猫', allsu: 16, jobs: [[1, 4], [4, 1], [5, 1], [3, 1], [6, 1], [10, 1], [8, 2], [7, 1], [9, 1]] },
    { label: '17A', allsu: 17, jobs: [[1, 3], [6, 1], [4, 1], [3, 1], [5, 1], [8, 2], [7, 1]] },
    { label: '18A猫', allsu: 18, jobs: [[1, 4], [6, 1], [4, 1], [3, 1], [5, 1], [10, 1], [8, 2], [7, 1]] },
    { label: '19D猫', allsu: 19, jobs: [[1, 4], [4, 1], [5, 1], [3, 1], [6, 1], [10, 1], [8, 2], [7, 1], [9, 1]] },
  ];

  /** サイトに送る相対パス(同一オリジンの fetch 用)。 */
  function presetPath(p) {
    const q = p.jobs.map(([j, c]) => `&job_${j}=${c}`).join('');
    return `/m/player.php?mode=updateJobset${q}&yakukakenashi=0`;
  }

  /** 例: 「人狼2 / 狂人1 / 占い師1 / 村人6」 */
  function describePreset(p) {
    const parts = p.jobs.map(([j, c]) => `${JOB_NAMES[j] || `役職${j}`}${c}`);
    const used = p.jobs.reduce((s, [, c]) => s + c, 0);
    if (p.allsu > used) parts.push(`村人${p.allsu - used}`);
    return parts.join(' / ');
  }

  function findPreset(label) {
    return PRESETS.find((p) => p.label === label) || null;
  }

  return { JOB_NAMES, PRESETS, presetPath, describePreset, findPreset };
});
