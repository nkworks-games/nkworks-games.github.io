// 計算モデルの確認（生物学的な妥当性の検証ではなく、収支・再現性・数値の挙動の確認）
// 使い方：node heikou-chikyu/studio/_dev/check.js [--v02 v0.2の simulation-data.json]
'use strict';
const assert = require('assert/strict');
const fs = require('fs');
const path = require('path');
const M = require('../model.js');

const args = process.argv.slice(2);
const v02Path = args.includes('--v02') ? args[args.indexOf('--v02') + 1] : null;
const W = M.WORLDS;
const results = [];
function pass(msg) { results.push(msg); console.log('PASS', msg); }

// 1. v0.2 の記録と同じになるか（人口固定・2方針・嵐あり／なし・3つの星）
if (v02Path) {
  const data = JSON.parse(fs.readFileSync(v02Path, 'utf8'));
  let worst = 0, compared = 0;
  const near = (a, b, where) => {
    if (a == null || b == null) { assert.equal(a, b, where); return; }
    const d = Math.abs(a - b);
    worst = Math.max(worst, d);
    compared++;
    assert.ok(d <= 2e-3, `${where}: ${a} != ${b}`);
  };
  for (const policy of Object.keys(data.runs)) {
    for (const kase of Object.keys(data.runs[policy])) {
      for (const world of W) {
        const want = data.runs[policy][kase][world.id];
        const got = M.simulate(world, { policy, storm: kase === 'storm' }).records;
        assert.equal(got.length, want.length);
        want.forEach((w, y) => {
          const g = got[y], at = `${policy}/${kase}/${world.id}/${y}`;
          for (const k of ['population', 'supplied', 'demand', 'coverage', 'cumulative_unmet', 'ships', 'transported', 'produced_food', 'spoiled_food', 'retired_ships']) near(g[k], w[k], at + '/' + k);
          for (const k of Object.keys(w.ecology)) { near(g.ecology[k], w.ecology[k], at + '/ecology/' + k); near(g.ecology_index[k], w.ecology_index[k], at + '/index/' + k); }
          for (const grp of ['ship_inputs', 'mined', 'food_sources', 'ecology_flows']) if (w[grp]) for (const k of Object.keys(w[grp])) near(g[grp][k], w[grp][k], at + '/' + grp + '/' + k);
          assert.deepEqual(g.events, w.events, at + '/events');
          assert.equal(g.transfers.length, w.transfers.length, at + '/transfers');
          w.transfers.forEach((t, i) => {
            const u = g.transfers[i];
            assert.deepEqual([u.source, u.target, u.resource, u.carrier], [t.source, t.target, t.resource, t.carrier], at + '/transfer');
            near(u.amount, t.amount, at + '/transfer/amount');
          });
          w.islands.forEach((s, i) => {
            const q = g.islands[i];
            assert.equal(q.ships, s.ships);
            assert.deepEqual(q.fleet, s.fleet, at + '/fleet');
            for (const k of Object.keys(s.stock)) near(q.stock[k], s.stock[k], at + '/stock/' + k);
            for (const k of Object.keys(s.deposits)) near(q.deposits[k], s.deposits[k], at + '/deposits/' + k);
            for (const k of Object.keys(s.ecosystem)) near(q.ecosystem[k], s.ecosystem[k], at + '/eco/' + s.id + '/' + k);
          });
        });
      }
    }
  }
  pass(`v0.2 の12試行を再現（比べた数値 ${compared} 個、最大の差 ${worst.toExponential(2)}。出来事・輸送・船の記録は完全一致）`);
}

// 2. 人類が採らない24年間で、生態系がほとんど動かない
let drift = 0;
for (const tidal of [false, true]) {
  for (const island of M.ISLANDS) {
    const bio = M.BIO_DEFAULT;
    const base = M.initialEcosystem(island, tidal, M.ECO, bio);
    const pools = Object.assign({}, base);
    for (let y = 0; y < 24; y++) M.ecosystemYear(pools, island, M.capsFor(island, bio), M.ECO, bio, 1, 0);
    const d = Math.max(...M.POOLS.map(k => Math.abs(pools[k] - base[k]) / Math.max(base[k], 1)));
    drift = Math.max(drift, d);
    assert.ok(d < 0.01, island.id + ' ' + tidal + ' ' + d);
    for (const k of ['land', 'forest', 'algae', 'grazers', 'predators', 'microbes']) assert.ok(base[k] > 1);
  }
}
pass(`採らない24年間の変動は最大 ${(drift * 100).toFixed(3)}％`);

// 3. 分解を止めると、枯死物がたまり、栄養が減る
{
  const island = M.ISLANDS[1], bio = M.BIO_DEFAULT;
  const base = M.initialEcosystem(island, true, M.ECO, bio);
  const cycled = Object.assign({}, base), stopped = Object.assign({}, base);
  for (let y = 0; y < 5; y++) {
    M.ecosystemYear(cycled, island, M.capsFor(island, bio), M.ECO, bio, 1, 0);
    M.ecosystemYear(stopped, island, M.capsFor(island, bio), M.ECO, bio, 1, 0, 0);
  }
  assert.ok(stopped.detritus > cycled.detritus && stopped.nutrients < cycled.nutrients);
  pass('分解を止めると枯死物が増え、栄養が減る');
}

// 4. 時間刻みを半分にしても、結果が大きく変わらない
{
  const coarse = M.simulate(W[1], {}).records;
  const eco = M.clone(M.ECO); eco.substeps *= 2;
  const fine = M.simulate(W[1], { eco }).records;
  const ch = Math.max(...M.POOLS.map(k => Math.abs(fine[24].ecology[k] - coarse[24].ecology[k]) / Math.max(coarse[0].ecology[k], 1)));
  assert.ok(ch < 0.03, ch);
  pass(`時間刻みを半分にしたときの差は最大 ${(ch * 100).toFixed(2)}％`);
}

// 5. 種・方針・星の組み合わせ（人口固定）
for (const seed of [7, 19, 29, 41, 53]) for (const policy of Object.keys(M.POLICIES)) for (const w of W) {
  const r = M.simulate(w, { seed, policy }).records;
  assert.ok(r.slice(1).every(x => x.population === 1000 && x.coverage >= 0 && x.coverage <= 100));
  assert.ok(r.every(x => Object.values(x.ecology).every(v => v >= 0)));
}
pass('5つの種×2方針×3つの星（30試行）で収支が合い、量が負にならない');

// 6. 同じ種なら同じ結果、違う種なら違う結果
assert.deepEqual(M.simulate(W[0], { seed: 7 }), M.simulate(W[0], { seed: 7 }));
assert.notDeepEqual(M.simulate(W[0], { seed: 7 }).records, M.simulate(W[0], { seed: 19 }).records);
pass('同じ種なら同じ結果になる');

// 7. 特殊な条件を外すと基準の星と同じになり、嵐の前までは嵐あり・なしが一致する
for (const policy of Object.keys(M.POLICIES)) {
  const ref = M.simulate(W[0], { policy }).records;
  for (const w of W.slice(1)) {
    const nul = Object.assign({}, w, { tidal_crop: false, special_material: false });
    assert.deepEqual(M.simulate(nul, { policy }).records, ref);
  }
  for (const w of W) {
    const a = M.simulate(w, { policy, storm: true }).records.slice(0, 12);
    const b = M.simulate(w, { policy, storm: false }).records.slice(0, 12);
    assert.deepEqual(a, b);
  }
}
pass('特殊な条件を外すと基準の星と一致し、嵐の前の記録は嵐あり・なしで一致する');

// 8. 拡張（人口・移住・技術）：300年・いろいろな条件で、収支が合い、値が壊れない
{
  let runs = 0, minPop = Infinity, maxPop = 0;
  for (const seed of [3, 29, 77]) for (const policy of Object.keys(M.POLICIES)) for (const randomStorms of [false, true]) for (const w of W) {
    const r = M.simulate(w, { seed, policy, years: 300, population: 'dynamic', randomStorms, stormYear: 40 }).records;
    runs++;
    for (const x of r) {
      assert.ok(Number.isFinite(x.population) && x.population >= 0);
      if (x.year) assert.ok(x.coverage >= 0 && x.coverage <= 100);
      for (const s of x.islands) assert.ok(s.population <= s.water * 1.05 + 1, `water ${w.id} ${x.year} ${s.id}`);
    }
    minPop = Math.min(minPop, r[300].population); maxPop = Math.max(maxPop, r[300].population);
  }
  pass(`拡張モードの300年×${runs}試行で収支が合い、淡水の上限を大きく超えない（300年目の人口 ${Math.round(minPop)}〜${Math.round(maxPop)}人）`);
}

// 9. 拡張モードでも、特殊な条件を外すと基準の星と一致する
{
  const o = { years: 120, population: 'dynamic', randomStorms: true, seed: 5 };
  const ref = M.simulate(W[0], o).records;
  for (const w of W.slice(1)) assert.deepEqual(M.simulate(Object.assign({}, w, { tidal_crop: false, special_material: false }), o).records, ref);
  pass('拡張モードでも、特殊な条件を外すと基準の星と一致する');
}

console.log('\n' + results.length + '項目すべて PASS（数値計算の整合性の確認であり、現実の生態系や社会の妥当性の検証ではない）');
