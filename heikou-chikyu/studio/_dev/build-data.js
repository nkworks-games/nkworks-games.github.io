// 計算データと設定の記録を作る（引き継ぎ資料の outputs/ に入れる用）
// 使い方：node heikou-chikyu/studio/_dev/build-data.js <出力先フォルダ>
'use strict';
const fs = require('fs');
const path = require('path');
const M = require('../model.js');

const outDir = process.argv[2];
if (!outDir) { console.error('出力先フォルダを指定してください'); process.exit(1); }
fs.mkdirSync(outDir, { recursive: true });

const policies = Object.keys(M.POLICIES);
const status = '生態系から開始する未校正のルールモデル。AI判断・進化予測ではありません。';

// v0.2 と同じ形：人口固定・24年・種29・2方針×嵐あり／なし×3つの星
const data = {
  version: M.VERSION, status, years: 24, seed: 29,
  islands: M.ISLANDS, worlds: M.WORLDS, policies: M.POLICIES,
  runs: {}, notes: {},
  dynamic: { years: 24, seed: 29, note: '人口・移住・技術ありの拡張（v0.3 の仮置き）。records の形は runs と同じ。', runs: {}, notes: {} }
};
for (const p of policies) {
  data.runs[p] = { storm: {}, calm: {} }; data.notes[p] = { storm: {}, calm: {} };
  data.dynamic.runs[p] = { storm: {}, calm: {} }; data.dynamic.notes[p] = { storm: {}, calm: {} };
  for (const kase of ['storm', 'calm']) {
    for (const w of M.WORLDS) {
      const fixed = M.simulate(w, { policy: p, storm: kase === 'storm' });
      data.runs[p][kase][w.id] = fixed.records;
      data.notes[p][kase][w.id] = fixed.notes;
      const dyn = M.simulate(w, { policy: p, storm: kase === 'storm', population: 'dynamic' });
      data.dynamic.runs[p][kase][w.id] = dyn.records;
      data.dynamic.notes[p][kase][w.id] = dyn.notes;
    }
  }
}
fs.writeFileSync(path.join(outDir, 'simulation-data.json'), JSON.stringify(data));

const settings = {
  version: M.VERSION, provisional: true, mode: '成立した生態系＋人類の小集団',
  population_modes: { fixed: 'v0.2 と同じ。各島200人で固定', dynamic: '出生・死亡・淡水の上限・移住・技術を加えた拡張（仮置き）' },
  canonical_code: 'nkworks-games.github.io リポジトリの heikou-chikyu/studio/model.js',
  defaults: M.DEFAULT_OPTIONS, islands: M.ISLANDS, worlds: M.WORLDS, wood_ship: M.WOOD_SHIP,
  ecology: M.ECO, harvest_policies: M.POLICIES, demography: M.DEMOGRAPHY, techs: M.TECHS,
  initial: { population_per_island: 200, food: 200, wood: 45, ore: 8, shell: 0, ships: 0, ore_deposit: 500 },
  assumptions: {
    food_unit: '人年分（食料需要の単位）', other_units: '仮の資源単位', distance_unit: '模式図上の仮想km',
    max_route_distance: '145（拡張の「帆の改良」の後は200）',
    note: 'world-settings.json は読み込まれる設定ではなく、model.js の値を書き出した参照記録。変更は model.js かスタジオの画面で行う。'
  }
};
fs.writeFileSync(path.join(outDir, 'world-settings.json'), JSON.stringify(settings, null, 2));

// 資料用のまとめ：人口固定と拡張を、30の種（29〜58）で比べる
function summarize(opts, trials) {
  const out = {};
  for (const w of M.WORLDS) {
    const ds = [];
    for (let i = 0; i < trials; i++) ds.push(M.digest(M.simulate(w, Object.assign({}, opts, { seed: 29 + i }))));
    const ag = M.aggregate(ds);
    const last = ds[0].series.coverage.length - 1;
    const s = k => ({ p10: ag.series[k].p10[last], p50: ag.series[k].p50[last], p90: ag.series[k].p90[last] });
    let peak = { v: 0, y: 0 };
    ag.series.population.p50.forEach((v, y) => { if (v > peak.v) peak = { v, y }; });
    out[w.id] = {
      final: { population: s('population'), forest: s('eco:forest'), grazers: s('eco:grazers'), predators: s('eco:predators'), ships: s('ships'), coverage: s('coverage') },
      peakPopulationMedian: peak, milestones: ag.milestones
    };
  }
  return out;
}
const summary = { version: M.VERSION, trials: 30, seeds: '29〜58', cases: {} };
for (const p of policies) {
  summary.cases[`fixed-24-${p}`] = summarize({ policy: p }, 30);
  summary.cases[`dynamic-24-${p}`] = summarize({ policy: p, population: 'dynamic' }, 30);
  summary.cases[`dynamic-300-${p}`] = summarize({ policy: p, population: 'dynamic', years: 300 }, 30);
}
fs.writeFileSync(path.join(outDir, 'trial-summary.json'), JSON.stringify(summary, null, 2));

for (const p of policies) for (const w of M.WORLDS) {
  const r = data.runs[p].storm[w.id][24], d = data.dynamic.runs[p].storm[w.id][24];
  console.log(p, w.id, '固定24年', r.coverage, '船', r.ships, '森', r.ecology_index.forest, '小魚', r.ecology_index.grazers,
    '｜拡張24年 人口', Math.round(d.population), '充足', d.coverage, '船', d.ships, '森', d.ecology_index.forest, '小魚', d.ecology_index.grazers);
}
console.log('書き出し：', ['simulation-data.json', 'world-settings.json', 'trial-summary.json'].map(f => path.join(outDir, f)).join('、'));
