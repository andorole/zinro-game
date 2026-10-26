const test = require('node:test');
const assert = require('node:assert/strict');
const presets = require('../src/lib/presets');

test('配役プリセットは27種、4〜19人', () => {
  assert.equal(presets.PRESETS.length, 27);
  const sizes = presets.PRESETS.map((p) => p.allsu);
  assert.equal(Math.min(...sizes), 4);
  assert.equal(Math.max(...sizes), 19);
  assert.equal(new Set(presets.PRESETS.map((p) => p.label)).size, 27, 'ラベルは重複しない');
});

test('役職の合計は人数以内で、役職番号はすべて名前がある(残りは村人)', () => {
  for (const p of presets.PRESETS) {
    const used = p.jobs.reduce((s, [, c]) => s + c, 0);
    assert.ok(used <= p.allsu, `${p.label}: ${used} > ${p.allsu}`);
    assert.ok(p.jobs.some(([j]) => j === 1), `${p.label}: 人狼がいない`);
    for (const [j, c] of p.jobs) {
      assert.ok(presets.JOB_NAMES[j], `${p.label}: job_${j}`);
      assert.ok(Number.isInteger(c) && c >= 1);
    }
    assert.equal(new Set(p.jobs.map(([j]) => j)).size, p.jobs.length, `${p.label}: 役職番号の重複`);
  }
});

test('サイトに送るパスは、役職の並びのままの updateJobset', () => {
  assert.equal(presets.presetPath(presets.findPreset('4A')),
    '/m/player.php?mode=updateJobset&job_1=1&yakukakenashi=0');
  assert.equal(presets.presetPath(presets.findPreset('10A狩')),
    '/m/player.php?mode=updateJobset&job_1=2&job_6=1&job_4=1&job_3=1&job_5=1&yakukakenashi=0');
  assert.equal(presets.presetPath(presets.findPreset('19D猫')),
    '/m/player.php?mode=updateJobset&job_1=4&job_4=1&job_5=1&job_3=1&job_6=1&job_10=1&job_8=2&job_7=1&job_9=1&yakukakenashi=0');
});

test('内訳の表示(残りは村人)', () => {
  assert.equal(presets.describePreset(presets.findPreset('8CFO')), '人狼2 / 狂人1 / 占い師1 / 霊能者1 / 共有者2 / 村人1');
  assert.equal(presets.describePreset(presets.findPreset('6C')), '人狼1 / 狂人3 / 占い師1 / 狩人1');   // 村人0は出さない
  assert.equal(presets.findPreset('存在しない'), null);
});
