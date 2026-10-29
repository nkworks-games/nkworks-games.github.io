// 並行地球の計算モデル v0.3
// 人口を固定すると、v0.2（simulation-source.py）と同じ規則・同じ順番で計算し、同じ結果になる。
// 「人口・移住・技術あり」は v0.3 で足した拡張。係数はすべて仮置きで、実在の生態系や文明の予測ではない。
var HeikouModel = (function () {
  'use strict';

  var VERSION = '0.3';

  // ---- 乱数：v0.2 と同じく「種:用途:…」の SHA-256 の先頭48ビットを使う ----
  var K256 = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  ];
  var W = new Int32Array(64);
  function sha256Head(str) {
    var bytes = [];
    for (var i = 0; i < str.length; i++) {
      var c = str.charCodeAt(i);
      if (c < 0x80) bytes.push(c);
      else if (c < 0x800) bytes.push(0xc0 | (c >> 6), 0x80 | (c & 63));
      else bytes.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    }
    var len = bytes.length, total = ((len + 9 + 63) >> 6) << 6;
    var m = new Uint8Array(total);
    m.set(bytes);
    m[len] = 0x80;
    var bits = len * 8;
    m[total - 4] = (bits >>> 24) & 255; m[total - 3] = (bits >>> 16) & 255; m[total - 2] = (bits >>> 8) & 255; m[total - 1] = bits & 255;
    var h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a, h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19;
    for (var off = 0; off < total; off += 64) {
      for (var t = 0; t < 16; t++) W[t] = (m[off + 4 * t] << 24) | (m[off + 4 * t + 1] << 16) | (m[off + 4 * t + 2] << 8) | m[off + 4 * t + 3];
      for (t = 16; t < 64; t++) {
        var x = W[t - 15], y = W[t - 2];
        var s0 = ((x >>> 7) | (x << 25)) ^ ((x >>> 18) | (x << 14)) ^ (x >>> 3);
        var s1 = ((y >>> 17) | (y << 15)) ^ ((y >>> 19) | (y << 13)) ^ (y >>> 10);
        W[t] = (W[t - 16] + s0 + W[t - 7] + s1) | 0;
      }
      var a = h0, b = h1, c2 = h2, d = h3, e = h4, f = h5, g = h6, h = h7;
      for (t = 0; t < 64; t++) {
        var S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
        var ch = (e & f) ^ (~e & g);
        var t1 = (h + S1 + ch + K256[t] + W[t]) | 0;
        var S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
        var mj = (a & b) ^ (a & c2) ^ (b & c2);
        var t2 = (S0 + mj) | 0;
        h = g; g = f; f = e; e = (d + t1) | 0; d = c2; c2 = b; b = a; a = (t1 + t2) | 0;
      }
      h0 = (h0 + a) | 0; h1 = (h1 + b) | 0; h2 = (h2 + c2) | 0; h3 = (h3 + d) | 0;
      h4 = (h4 + e) | 0; h5 = (h5 + f) | 0; h6 = (h6 + g) | 0; h7 = (h7 + h) | 0;
    }
    return [h0 >>> 0, h1 >>> 0];
  }
  function uniform(seed, parts) {
    var h = sha256Head([seed].concat(parts).join(':'));
    return (h[0] * 65536 + (h[1] >>> 16)) / 281474976710656;
  }
  function sha256Hex(str) { var h = sha256Head(str); return ('00000000' + h[0].toString(16)).slice(-8) + ('00000000' + h[1].toString(16)).slice(-8); }

  // ---- v0.2 と同じ係数（すべて仮置き） ----
  var ECO = {
    warmup_years: 160, substeps: 96, food_per_biomass: 12, waste_return: 0.7,
    nutrient_inflow: 9, nutrient_export: 0.035, detritus_export: 0.008,
    decomposer_efficiency: 0.2, decompose_rate: 8, grazing_rate: 1.6, grazer_assimilation: 0.35,
    predation_rate: 1.2, predator_assimilation: 0.3,
    mortality: { land: 0.18, forest: 0.035, algae: 0.3, grazers: 0.18, predators: 0.13, microbes: 0.45 },
    crowding: { grazers: 0.002, predators: 0.012, microbes: 0.001 },
    growth: { land: 1.6, forest: 0.2, algae: 3.0 }
  };
  var POOLS = ['nutrients', 'detritus', 'microbes', 'grazers', 'predators', 'land', 'forest', 'algae', 'tide'];
  var POOL_NAMES = {
    nutrients: '栄養', detritus: '枯死物', microbes: '分解者', grazers: '小魚など', predators: '捕食者',
    land: '陸上の食用植物', forest: '森', algae: '藻類', tide: '潮麦'
  };

  var POLICIES = {
    demand: { name: '今の需要を優先', food_fraction: 0.55, wood_fraction: 0.10 },
    limited: { name: '採取量を抑える', food_fraction: 0.22, wood_fraction: 0.035 }
  };

  // water は v0.3 の拡張でだけ使う淡水の上限（人）。v0.2 は「初期人口分を確保済み」とだけ仮定していた。
  var ISLANDS = [
    { id: 'A', name: '森の島', x: 55, y: 65, food: 260, wood: 25, ore: 2, shallow: false, exposed: false, water: 300, note: '食料と木材が比較的多い' },
    { id: 'B', name: '浅瀬の島', x: 175, y: 55, food: 175, wood: 12, ore: 4, shallow: true, exposed: false, water: 240, note: '浅瀬がある。食料は不足しやすい' },
    { id: 'C', name: '鉱山の島', x: 110, y: 145, food: 150, wood: 9, ore: 18, shallow: false, exposed: false, water: 230, note: '鉱石が多い。食料と木材が少ない' },
    { id: 'D', name: '湾の島', x: 250, y: 145, food: 200, wood: 18, ore: 4, shallow: true, exposed: true, water: 280, note: '中程度の資源と浅瀬。嵐にさらされる' },
    { id: 'E', name: '外洋の島', x: 190, y: 235, food: 180, wood: 10, ore: 5, shallow: true, exposed: true, water: 220, note: '浅瀬がある。食料が少なく、嵐にさらされる' }
  ];

  var WOOD_SHIP = { cost: { wood: 50, ore: 10, shell: 0 }, capacity: 120, life: 8 };
  var BIO_DEFAULT = { start: 25, growth: 2.4, mortality: 0.3, cap: 180, palatability: 0.25, competition: 0.35, stormLoss: 0.55 };
  var MAT_DEFAULT = { deposit: 2000, mining: 12, capacity: 180, life: 12, costWood: 26, costOre: 5, costShell: 8 };

  var WORLDS = [
    { id: 'reference', name: '基準の星', subtitle: '共通の生態系と小集落', tidal_crop: false, special_material: false, params: {} },
    { id: 'biology', name: '生物の星', subtitle: '浅瀬に架空植物「潮麦」', tidal_crop: true, special_material: false, params: clone(BIO_DEFAULT) },
    { id: 'material', name: '素材の星', subtitle: '船材になる架空鉱物「軽殻石」', tidal_crop: false, special_material: true, params: clone(MAT_DEFAULT) }
  ];

  // 拡張（人口・移住・技術）の仮置き係数
  var DEMOGRAPHY = { birth: 0.035, death: 0.025, starvation: 0.5, overcrowd: 0.25, migration: 0.05, personCost: 2, ideaRate: 0.05 };
  var TECHS = [
    { id: 'preserve', name: '干物と塩漬け', know: 10, exp: { food: 6000 }, effect: '保存中に傷む食料が年10％から5％に減る' },
    { id: 'cistern', name: '貯水池', know: 30, exp: {}, effect: '各島の淡水の上限が1.3倍になる' },
    { id: 'sail', name: '帆の改良', know: 45, exp: { ships: 40 }, effect: '航路の上限が145から200に延び、船の輸送枠が1.25倍になる' },
    { id: 'field', name: '畑の拡大', know: 60, exp: { land: 4000 }, effect: '陸上の食用植物の生育場所が1.3倍、森の生育場所が0.85倍になる' }
  ];

  var DEFAULT_OPTIONS = {
    years: 24, seed: 29, policy: 'demand', storm: true, stormYear: 12, stormPower: 1,
    population: 'fixed', randomStorms: false,
    eco: clone(ECO), demography: clone(DEMOGRAPHY)
  };

  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function rnd(v, n) { var p = Math.pow(10, n); return Math.round(v * p) / p; }
  function sumPools(p) { var s = 0; for (var i = 0; i < POOLS.length; i++) s += p[POOLS[i]]; return s; }
  function dist(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }

  function normalizeOptions(o) {
    var d = clone(DEFAULT_OPTIONS);
    o = o || {};
    ['years', 'seed', 'stormYear', 'stormPower'].forEach(function (k) { if (o[k] != null && isFinite(+o[k])) d[k] = +o[k]; });
    ['storm', 'randomStorms'].forEach(function (k) { if (o[k] != null) d[k] = !!o[k]; });
    if (POLICIES[o.policy]) d.policy = o.policy;
    if (o.population === 'dynamic') d.population = 'dynamic';
    ['eco', 'demography'].forEach(function (g) {
      if (!o[g]) return;
      for (var k in d[g]) {
        if (typeof d[g][k] === 'object') { if (o[g][k]) for (var k2 in d[g][k]) if (isFinite(+o[g][k][k2])) d[g][k][k2] = +o[g][k][k2]; }
        else if (o[g][k] != null && isFinite(+o[g][k])) d[g][k] = +o[g][k];
      }
    });
    d.years = Math.max(1, Math.min(1000, Math.round(d.years)));
    d.seed = Math.round(d.seed);
    d.stormYear = Math.max(1, Math.round(d.stormYear));
    d.stormPower = Math.max(0, Math.min(2, d.stormPower));
    d.eco.substeps = Math.max(1, Math.round(d.eco.substeps));
    d.eco.warmup_years = Math.max(0, Math.round(d.eco.warmup_years));
    return d;
  }

  function worldParams(world) {
    return {
      bio: Object.assign(clone(BIO_DEFAULT), world.tidal_crop ? world.params : {}),
      mat: Object.assign(clone(MAT_DEFAULT), world.special_material ? world.params : {})
    };
  }

  // ---- 生態系 ----
  function capsFor(island, bio, mods) {
    mods = mods || {};
    return {
      land: island.food * 0.8 * (mods.land || 1), forest: island.wood * 18 * (mods.forest || 1),
      algae: island.shallow ? 240 : 160, tide: island.shallow ? bio.cap : 0
    };
  }

  function ecosystemYear(pools, island, caps, eco, bio, weather, stormPower, decompositionFactor) {
    if (decompositionFactor == null) decompositionFactor = 1;
    var before = sumPools(pools);
    var extIn = 0, extOut = 0;
    var n = eco.substeps, dt = 1 / n;
    // 量を手元の変数に移して計算する。足し引きの順番は v0.2 と同じ
    var N = pools.nutrients, Dt = pools.detritus, Mi = pools.microbes, G = pools.grazers, P = pools.predators;
    var L = pools.land, F = pools.forest, A = pools.algae, T = pools.tide;
    var cL = caps.land, cF = caps.forest, cA = caps.algae, cT = caps.tide;
    var gL = eco.growth.land, gF = eco.growth.forest, gA = eco.growth.algae, gT = bio.growth;
    var comp = bio.competition, pal = bio.palatability;
    var mo = eco.mortality, cr = eco.crowding;
    // 量によらない減り方は、刻みごとに同じ値になるので先に計算しておく（結果は変わらない）
    var expN = 1 - Math.exp(-eco.nutrient_export * dt), expD = 1 - Math.exp(-eco.detritus_export * dt);
    function fixed(rate, crowd) { return crowd ? null : 1 - Math.exp(-rate * dt); }
    var kL = fixed(mo.land, cr.land), kF = fixed(mo.forest, cr.forest), kA = fixed(mo.algae, cr.algae), kT = fixed(bio.mortality, cr.tide);
    var kG = fixed(mo.grazers, cr.grazers), kP = fixed(mo.predators, cr.predators), kM = fixed(mo.microbes, cr.microbes);
    var crG = cr.grazers || 0, crP = cr.predators || 0, crM = cr.microbes || 0;
    var inflow = eco.nutrient_inflow * dt;
    var ga = eco.grazer_assimilation, pa = eco.predator_assimilation, de = eco.decomposer_efficiency;
    var grazeK = eco.grazing_rate, predK = eco.predation_rate, decK = decompositionFactor * eco.decompose_rate;
    for (var step = 0; step < n; step++) {
      N += inflow;
      extIn += inflow;
      var flow = N * expN;
      N -= flow; extOut += flow;
      flow = Dt * expD;
      Dt -= flow; extOut += flow;
      // 生産者は、ひとつの栄養プールを同時に取り合う
      var nf = N / (N + 50);
      var dL = cL <= 0 ? 0 : gL * L * Math.max(0, 1 - L / cL) * nf * weather * dt;
      var dF = cF <= 0 ? 0 : gF * F * Math.max(0, 1 - F / cF) * nf * weather * dt;
      var dA = cA <= 0 ? 0 : gA * A * Math.max(0, 1 - (A + comp * T) / cA) * nf * weather * dt;
      var dT = cT <= 0 ? 0 : gT * T * Math.max(0, 1 - (T + comp * A) / cT) * nf * weather * dt;
      var total = 0 + dL + dF + dA + dT;
      var frac = total ? Math.min(1, N / total) : 1;
      var amt = dL * frac; N -= amt; L += amt;
      amt = dF * frac; N -= amt; F += amt;
      amt = dA * frac; N -= amt; A += amt;
      amt = dT * frac; N -= amt; T += amt;
      // 小魚などは藻類と潮麦を食べる（潮麦は食べにくい）
      var edible = A + pal * T;
      var desired = grazeK * G * edible / (edible + 60) * dt;
      var partA = edible ? Math.min(A, desired * 1 * A / edible) : 0;
      A -= partA;
      var grazed = 0 + partA;
      var partT = edible ? Math.min(T, desired * pal * T / edible) : 0;
      T -= partT;
      grazed += partT;
      G += grazed * ga;
      Dt += grazed * (1 - ga);
      var eaten = Math.min(G, predK * P * G / (G + 35) * dt);
      G -= eaten;
      P += eaten * pa;
      Dt += eaten * (1 - pa);
      var dead;
      dead = kL != null ? L * kL : L * (1 - Math.exp(-(mo.land + cr.land * L) * dt)); L -= dead; Dt += dead;
      dead = kF != null ? F * kF : F * (1 - Math.exp(-(mo.forest + cr.forest * F) * dt)); F -= dead; Dt += dead;
      dead = kA != null ? A * kA : A * (1 - Math.exp(-(mo.algae + cr.algae * A) * dt)); A -= dead; Dt += dead;
      dead = kT != null ? T * kT : T * (1 - Math.exp(-(bio.mortality + cr.tide * T) * dt)); T -= dead; Dt += dead;
      dead = kG != null ? G * kG : G * (1 - Math.exp(-(mo.grazers + crG * G) * dt)); G -= dead; Dt += dead;
      dead = kP != null ? P * kP : P * (1 - Math.exp(-(mo.predators + crP * P) * dt)); P -= dead; Dt += dead;
      dead = kM != null ? Mi * kM : Mi * (1 - Math.exp(-(mo.microbes + crM * Mi) * dt)); Mi -= dead; Dt += dead;
      var dec = Math.min(Dt, decK * Mi * Dt / (Dt + 80) * dt);
      Dt -= dec;
      Mi += dec * de;
      N += dec * (1 - de);
    }
    pools.nutrients = N; pools.detritus = Dt; pools.microbes = Mi; pools.grazers = G; pools.predators = P;
    pools.land = L; pools.forest = F; pools.algae = A; pools.tide = T;
    if (stormPower > 0) {
      var losses = [['tide', bio.stormLoss]];
      if (island.exposed) losses.push(['land', 0.2], ['forest', 0.08], ['algae', 0.25]);
      for (var j = 0; j < losses.length; j++) {
        var f = Math.min(1, losses[j][1] * stormPower);
        var d = pools[losses[j][0]] * f;
        pools[losses[j][0]] -= d;
        pools.detritus += d;
      }
    }
    for (var q = 0; q < POOLS.length; q++) {
      var v = pools[POOLS[q]];
      if (!(v >= -1e-9) || !isFinite(v)) throw new Error('生態系の量が負または非数になった：' + POOLS[q]);
    }
    if (Math.abs(sumPools(pools) - before - extIn + extOut) > 1e-7 * Math.max(1, before / 1000)) throw new Error('生態系の収支が合わない');
    return { nutrient_input: extIn, nutrient_export: extOut };
  }

  var warmCache = {};
  function initialEcosystem(island, tidal, eco, bio) {
    var key = JSON.stringify([island.id, island.food, island.wood, island.shallow, island.exposed, tidal, eco, tidal ? bio : null]);
    if (!warmCache[key]) {
      var c = capsFor(island, bio);
      var pools = { nutrients: 100, detritus: 150, microbes: 22, grazers: 65, predators: 12, land: c.land * 0.6, forest: c.forest * 0.8, algae: c.algae * 0.6, tide: 0 };
      // 自生する潮麦は、同じ初期の栄養の一部を占める
      if (tidal && island.shallow) { pools.tide = bio.start; pools.nutrients -= bio.start; }
      for (var y = 0; y < eco.warmup_years; y++) ecosystemYear(pools, island, c, eco, bio, 1, 0);
      warmCache[key] = pools;
    }
    return Object.assign({}, warmCache[key]);
  }

  function harvestFood(pools, desired, policy, eco) {
    var remaining = Math.max(0, desired) / eco.food_per_biomass;
    var g = { tide: 0, grazers: 0, land: 0 };
    ['tide', 'grazers', 'land'].forEach(function (k) {
      var amount = Math.min(remaining, pools[k] * policy.food_fraction);
      pools[k] -= amount;
      g[k] = amount;
      remaining -= amount;
    });
    return { food: (g.tide + g.grazers + g.land) * eco.food_per_biomass, gathered: g };
  }
  function harvestWood(pools, desired, cap, policy) {
    var amount = Math.min(Math.max(0, desired), cap, pools.forest * policy.wood_fraction);
    pools.forest -= amount;
    return amount;
  }
  function ecoTotals(states) {
    var t = {};
    POOLS.forEach(function (k) { var s = 0; for (var i = 0; i < states.length; i++) s += states[i].ecosystem[k]; t[k] = s; });
    return t;
  }

  // ---- 1つの星を計算する ----
  // 戻り値の records は v0.2 の simulation-data.json と同じ形（追加の項目あり）。
  function simulate(world, options) {
    var o = normalizeOptions(options);
    var eco = o.eco, policy = POLICIES[o.policy], dem = o.demography;
    var wp = worldParams(world), bio = wp.bio, mat = wp.mat;
    var dynamic = o.population === 'dynamic';
    var seed = o.seed;
    var U = function () { return uniform(seed, Array.prototype.slice.call(arguments)); };
    var ships = { wood: WOOD_SHIP, shell: { cost: { wood: mat.costWood, ore: mat.costOre, shell: mat.costShell }, capacity: mat.capacity, life: mat.life } };
    var techs = {}, know = 0, xp = { food: 0, ships: 0, land: 0 };
    var mods = {};

    var states = ISLANDS.map(function (island) {
      var s = clone(island);
      s.population = 200;
      s.stock = { food: 200, wood: 45, ore: 8, shell: 0 };
      s.deposits = { ore: 500, shell: world.special_material && island.id === 'C' ? mat.deposit : 0 };
      s.ships = []; s.next_ship = 0;
      s.ecosystem = initialEcosystem(island, world.tidal_crop, eco, bio);
      s.initEco = Object.assign({}, s.ecosystem);
      s.lastCov = 1; s.coverage = null;
      return s;
    });
    var initialEco = ecoTotals(states);
    var records = [];
    var notes = [];
    var cumulativeUnmet = 0;
    var flags = {};

    function need(s) { return dynamic ? s.population : 200; }
    function water(s) { return s.water * (techs.cistern != null ? 1.3 : 1); }
    function maxRoute() { return techs.sail != null ? 200 : 145; }
    function capMult() { return techs.sail != null ? 1.25 : 1; }
    function note(year, type, text, extra) {
      var n = { year: year, type: type, text: text };
      if (extra) for (var k in extra) n[k] = extra[k];
      notes.push(n);
    }

    function record(year, transfers, events, supplied, produced, spoilage, spent, retired, mined, demand, storm) {
      var totals = ecoTotals(states);
      var pop = 0;
      states.forEach(function (s) { pop += s.population; });
      var r = {
        year: year, population: dynamic ? rnd(pop, 2) : 1000, supplied: rnd(supplied, 3), demand: year ? (dynamic ? rnd(demand, 3) : 1000) : 0,
        coverage: year ? rnd(supplied / (dynamic ? demand : 1000) * 100, 1) : null,
        cumulative_unmet: rnd(cumulativeUnmet, 3), ships: states.reduce(function (a, s) { return a + s.ships.length; }, 0),
        transported: rnd(transfers.reduce(function (a, t) { return t.resource === 'people' ? a : a + t.amount; }, 0), 3),
        produced_food: rnd(produced, 3), spoiled_food: rnd(spoilage, 3),
        ecology: {}, ecology_index: {},
        ship_inputs: spent, retired_ships: retired, mined: mined,
        islands: states.map(function (s) {
          var e = {}, idx = {};
          POOLS.forEach(function (k) {
            e[k] = rnd(s.ecosystem[k], 4);
            idx[k] = s.initEco[k] ? rnd(100 * s.ecosystem[k] / s.initEco[k], 2) : null;
          });
          return {
            id: s.id, population: dynamic ? rnd(s.population, 2) : s.population, ships: s.ships.length,
            stock: { food: rnd(s.stock.food, 4), wood: rnd(s.stock.wood, 4), ore: rnd(s.stock.ore, 4), shell: rnd(s.stock.shell, 4) },
            fleet: s.ships.map(function (x) { return { type: x.type, built: x.built, number: x.number }; }),
            deposits: { ore: s.deposits.ore, shell: s.deposits.shell },
            ecosystem: e, ecology_index: idx, coverage: s.coverage, water: rnd(water(s), 1)
          };
        }),
        transfers: transfers, events: events,
        knowledge: rnd(know, 3), techs: Object.keys(techs), storm: storm
      };
      POOLS.forEach(function (k) {
        r.ecology[k] = rnd(totals[k], 4);
        r.ecology_index[k] = initialEco[k] ? rnd(100 * totals[k] / initialEco[k], 2) : null;
      });
      return r;
    }

    records.push(record(0, [], ['生態系がある5つの島に200人ずつ。船は未建造。'], 0, 0, 0, {}, 0, {}, 0, 0));
    note(0, 'start', '生態系がある5つの島に200人ずつが暮らしている。船はまだない');

    for (var year = 1; year <= o.years; year++) {
      var before = {};
      ['food', 'wood', 'ore', 'shell'].forEach(function (k) { before[k] = states.reduce(function (a, s) { return a + s.stock[k]; }, 0); });
      var events = [], transfers = [];
      var spent = { wood: 0, ore: 0, shell: 0 }, harvested = { wood: 0, ore: 0, shell: 0 };
      var produced = 0, spoilage = 0, retired = 0;
      var bal = { input: 0, export: 0, human_return: 0, food_taken: 0, wood_taken: 0 };
      var ecoBefore = sumPools(ecoTotals(states));
      var foodSources = { tide: 0, grazers: 0, land: 0 };
      var mainStorm = o.storm && year === o.stormYear && o.stormPower > 0;
      var stormPower = mainStorm ? o.stormPower : 0;
      if (!mainStorm && o.randomStorms && U('storm', year) < 0.05) stormPower = 0.4 + 0.5 * U('stormPower', year);
      var spoil = techs.preserve != null ? 0.05 : 0.1;
      var built = { wood: [], shell: [] }, lostShips = [];

      for (var si = 0; si < states.length; si++) {
        var s = states[si];
        var active = [];
        for (var k = 0; k < s.ships.length; k++) {
          var ship = s.ships[k];
          var expired = year - ship.built >= ships[ship.type].life;
          var wrecked = false;
          if (stormPower > 0 && s.exposed) {
            var u = mainStorm ? U('wreck', s.id, ship.number) : U('wreck', s.id, ship.number, year);
            wrecked = u < 0.35 * stormPower;
          }
          if (expired || wrecked) {
            retired++;
            events.push(s.id + '：船1隻が' + (wrecked ? '嵐で失われた。' : '使用期限に達した。'));
            if (wrecked) lostShips.push(s.id);
          } else active.push(ship);
        }
        s.ships = active;
        var loss = s.stock.food * spoil;
        s.stock.food -= loss;
        spoilage += loss;
        var rec = loss / eco.food_per_biomass * eco.waste_return;
        s.ecosystem.detritus += rec;
        bal.human_return += rec;
        var weather = 0.94 + 0.12 * U('weather', year, s.id);
        var flows = ecosystemYear(s.ecosystem, s, capsFor(s, bio, mods), eco, bio, weather, stormPower);
        bal.input += flows.nutrient_input;
        bal.export += flows.nutrient_export;
        var hv = harvestFood(s.ecosystem, 1.25 * need(s) - s.stock.food, policy, eco);
        bal.food_taken += hv.gathered.tide + hv.gathered.grazers + hv.gathered.land;
        foodSources.tide += hv.gathered.tide * eco.food_per_biomass;
        foodSources.grazers += hv.gathered.grazers * eco.food_per_biomass;
        foodSources.land += hv.gathered.land * eco.food_per_biomass;
        xp.food += hv.food; xp.land += hv.gathered.land * eco.food_per_biomass;
        s.stock.food += hv.food;
        produced += hv.food;
        var wood = harvestWood(s.ecosystem, 0.5 * need(s) - s.stock.wood, dynamic ? s.wood * s.population / 200 : s.wood, policy);
        bal.wood_taken += wood;
        var res = [['wood', wood], ['ore', s.ore], ['shell', world.special_material && s.id === 'C' ? mat.mining : 0]];
        for (k = 0; k < 3; k++) {
          var amount = res[k][1];
          if (res[k][0] !== 'wood') { amount = Math.min(amount, s.deposits[res[k][0]]); s.deposits[res[k][0]] -= amount; }
          s.stock[res[k][0]] += amount;
          harvested[res[k][0]] += amount;
        }
        // すべての星で同じ計画：1つの島で1年に1隻まで造る
        var options2 = world.special_material ? ['shell', 'wood'] : ['wood'];
        for (k = 0; k < options2.length; k++) {
          var kind = options2[k], cost = ships[kind].cost;
          if (s.stock.wood >= cost.wood && s.stock.ore >= cost.ore && s.stock.shell >= cost.shell) {
            ['wood', 'ore', 'shell'].forEach(function (r) { s.stock[r] -= cost[r]; spent[r] += cost[r]; });
            s.ships.push({ type: kind, built: year, number: s.next_ship });
            s.next_ship++;
            xp.ships++;
            events.push(s.id + '：' + (kind === 'shell' ? '軽殻石の船' : '木の船') + 'を1隻建造。');
            built[kind].push(s.id);
            break;
          }
        }
      }
      if (mainStorm) events.unshift('共通の嵐：D・Eの植生が一部失われ、枯死物になる。潮麦は全生育地で減少。');
      else if (stormPower > 0) events.unshift('嵐（強さ' + Math.round(stormPower * 100) + '）：D・Eの植生が一部失われ、枯死物になる。潮麦は全生育地で減少。');

      var budgets = states.map(function (s) { return s.ships.reduce(function (a, x) { return a + ships[x.type].capacity; }, 0) * capMult(); });
      var limit = maxRoute();

      // 拡張：混み合うか食料が足りなかった島から、余裕のある島へ船で移る
      var moved = [];
      if (dynamic) {
        var order = states.map(function (s, i) { return i; }).sort(function (a, b) {
          return states[b].population / water(states[b]) - states[a].population / water(states[a]) || a - b;
        });
        order.forEach(function (srcI) {
          var src = states[srcI];
          if (!(src.population > 0.92 * water(src) || src.lastCov < 0.97)) return;
          var best = -1, bestRoom = 1, bestD = 0;
          states.forEach(function (dst, di) {
            if (di === srcI) return;
            var d = dist(src, dst);
            if (d > limit || dst.lastCov < 0.999) return;
            var room = 0.85 * water(dst) - dst.population;
            if (room > bestRoom) { bestRoom = room; best = di; bestD = d; }
          });
          if (best < 0) return;
          var carrier = budgets[srcI] >= budgets[best] ? srcI : best;
          var cpu = (1 + bestD / 100) * dem.personCost;
          var people = Math.min(dem.migration * src.population, bestRoom, budgets[carrier] / cpu);
          if (people < 1) return;
          src.population -= people; states[best].population += people;
          budgets[carrier] -= people * cpu;
          transfers.push({ source: src.id, target: states[best].id, resource: 'people', amount: rnd(people, 4), carrier: states[carrier].id });
          moved.push(src.id + '→' + states[best].id + ' ' + Math.round(people) + '人');
        });
        if (moved.length) note(year, 'migrate', '移住：' + moved.join('、'), { count: moved.length });
      }

      var transferPass = function (resource, target, floor) {
        // 最も足りない島から先に、近い島から運ぶ。価格や対立はなく、協力して分け合う
        var dests = [0, 1, 2, 3, 4].sort(function (a, b) { return states[a].stock[resource] - states[b].stock[resource] || a - b; });
        dests.forEach(function (dest) {
          var missing = Math.max(0, target(states[dest]) - states[dest].stock[resource]);
          var srcs = [0, 1, 2, 3, 4].filter(function (i) { return i !== dest; }).sort(function (a, b) {
            return dist(states[a], states[dest]) - dist(states[b], states[dest]) || a - b;
          });
          srcs.forEach(function (src) {
            var d = dist(states[src], states[dest]);
            if (d > limit || missing <= 1e-9) return;
            var surplus = Math.max(0, states[src].stock[resource] - floor(states[src]));
            var cpu = 1 + d / 100;
            var carrier = budgets[src] >= budgets[dest] ? src : dest;
            var amount = Math.min(surplus, missing, budgets[carrier] / cpu);
            if (amount <= 1e-9) return;
            states[src].stock[resource] -= amount;
            states[dest].stock[resource] += amount;
            budgets[carrier] -= amount * cpu;
            missing -= amount;
            transfers.push({ source: states[src].id, target: states[dest].id, resource: resource, amount: rnd(amount, 4), carrier: states[carrier].id });
            if (budgets[carrier] < -1e-8) throw new Error('輸送枠が負になった');
          });
        });
      };
      var needF = function (s) { return need(s); };
      var reserveF = function (s) { return 1.25 * need(s); };
      // 今の食料を先に、次に備蓄、最後に船の材料を運ぶ
      transferPass('food', needF, needF);
      transferPass('food', reserveF, reserveF);
      transferPass('wood', function (s) { return 0.25 * need(s); }, function (s) { return 0.25 * need(s); });
      transferPass('ore', function () { return 10; }, function () { return 10; });
      if (world.special_material) transferPass('shell', function () { return 8; }, function () { return 8; });

      var supplied = 0, demand = 0, short = [];
      states.forEach(function (s) {
        var nd = need(s);
        demand += nd;
        var eaten = Math.min(s.stock.food, nd);
        s.stock.food -= eaten;
        supplied += eaten;
        var r2 = eaten / eco.food_per_biomass * eco.waste_return;
        s.ecosystem.detritus += r2;
        bal.human_return += r2;
        s.coverage = nd > 0 ? rnd(eaten / nd * 100, 1) : 100;
        s.lastCov = nd > 0 ? eaten / nd : 1;
        if (eaten < nd - 0.001) {
          events.push(s.id + '：食料需要の' + (eaten / nd * 100).toFixed(0) + '％を供給。');
          short.push(s.id + '（' + (eaten / nd * 100).toFixed(0) + '％）');
        }
        ['food', 'wood', 'ore', 'shell'].forEach(function (r) { if (s.stock[r] < -1e-8) throw new Error('在庫が負になった'); });
      });
      cumulativeUnmet += demand - supplied;
      var after = {};
      ['food', 'wood', 'ore', 'shell'].forEach(function (k) { after[k] = states.reduce(function (a, s) { return a + s.stock[k]; }, 0); });
      if (Math.abs(after.food - (before.food - spoilage + produced - supplied)) > 1e-6) throw new Error('食料の収支が合わない');
      ['wood', 'ore', 'shell'].forEach(function (r) { if (Math.abs(after[r] - (before[r] + harvested[r] - spent[r])) > 1e-6) throw new Error('資源の収支が合わない：' + r); });
      var expected = ecoBefore + bal.input - bal.export + bal.human_return - bal.food_taken - bal.wood_taken;
      if (Math.abs(sumPools(ecoTotals(states)) - expected) > 1e-6 * Math.max(1, expected / 10000)) throw new Error('生態系全体の収支が合わない');

      // 拡張：人口の増減と、知識・技術
      if (dynamic) {
        var gone = [];
        states.forEach(function (s) {
          var cov = s.lastCov;
          var births = dem.birth * s.population * Math.min(1, cov);
          var deaths = dem.death * s.population + dem.starvation * s.population * Math.max(0, 1 - cov);
          var over = Math.max(0, s.population - water(s)) * dem.overcrowd;
          s.population = Math.max(0, s.population + births - deaths - over);
          if (s.population < 1 && s.population > 0) s.population = 0;
          if (s.population === 0 && !s.goneNoted) { s.goneNoted = 1; gone.push(s.name); }
        });
        if (gone.length) note(year, 'crisis', gone.join('・') + 'に住む人がいなくなった');
        var popAll = states.reduce(function (a, s) { return a + s.population; }, 0);
        var routes = {};
        transfers.forEach(function (t) { routes[[t.source, t.target].sort().join('')] = 1; });
        know += dem.ideaRate * Math.sqrt(popAll) * (1 + 0.05 * Object.keys(routes).length) * (0.6 + 0.8 * U('idea', year));
        TECHS.forEach(function (t) {
          if (techs[t.id] != null || know < t.know) return;
          for (var ek in t.exp) if ((xp[ek] || 0) < t.exp[ek]) return;
          techs[t.id] = year;
          if (t.id === 'field') mods = { land: 1.3, forest: 0.85 };
          note(year, 'tech', t.name + '：' + t.effect, { tech: t.id });
        });
      }

      // 記録用の出来事（v0.2 の events とは別に、種類つきで残す）
      if (mainStorm || stormPower > 0) {
        note(year, 'storm', (mainStorm ? '共通の嵐' : '嵐') + '（強さ' + Math.round(stormPower * 100) + '）' + (lostShips.length ? '：船' + lostShips.length + '隻が沈んだ（' + lostShips.join('・') + '）' : '：沈んだ船はない'), { big: mainStorm, ships: lostShips.length });
      }
      if (built.wood.length) note(year, 'build', '木の船を' + built.wood.length + '隻建造（' + built.wood.join('・') + '）', { count: built.wood.length });
      if (built.shell.length) note(year, 'build', '軽殻石の船を' + built.shell.length + '隻建造（' + built.shell.join('・') + '）', { count: built.shell.length });
      if (retired - lostShips.length > 0) note(year, 'build', '船' + (retired - lostShips.length) + '隻が使用期限に達した', { retired: retired - lostShips.length });
      // 食料不足は、始まった年・終わった年・深刻な年（どこかの島で8割未満）だけを残す
      var severe = states.some(function (s) { return s.lastCov < 0.8; });
      if (short.length && !flags.shortSince) {
        flags.shortSince = year;
        note(year, 'shortage', '食料不足が始まった：' + short.join('・'), { start: true });
      } else if (short.length && severe && year - (flags.severeNoted || -99) >= 5) {
        note(year, 'shortage', '深刻な食料不足：' + short.join('・'));
      } else if (!short.length && flags.shortSince) {
        note(year, 'shortage', '食料不足が解消（' + (year - flags.shortSince) + '年続いた）', { end: true });
        flags.shortSince = 0;
      }
      if (short.length && severe) flags.severeNoted = year;

      var r = record(year, transfers, events, supplied, produced, spoilage, spent, retired, harvested, demand, stormPower);
      r.ecology_flows = {};
      for (var bk in bal) r.ecology_flows[bk] = rnd(bal[bk], 6);
      r.food_sources = { tide: rnd(foodSources.tide, 4), grazers: rnd(foodSources.grazers, 4), land: rnd(foodSources.land, 4) };
      records.push(r);
      watch(year, r);
    }

    // 量の大きな変化と、資源の枯渇を記録する
    function watch(year, r) {
      var ix = r.ecology_index;
      [['grazers', 10, 50], ['predators', 10, 50], ['forest', 50, 80], ['algae', 50, 80], ['land', 50, 80], ['tide', 30, 70]].forEach(function (w) {
        var v = ix[w[0]];
        if (v == null) return;
        var key = 'low:' + w[0];
        if (!flags[key] && v < w[1]) { flags[key] = 1; note(year, 'eco', POOL_NAMES[w[0]] + 'が開始時の' + w[1] + '％を下回った', { pool: w[0], threshold: w[1] }); }
        else if (flags[key] && v > w[2]) { flags[key] = 0; note(year, 'eco', POOL_NAMES[w[0]] + 'が開始時の' + w[2] + '％まで戻った', { pool: w[0], recovered: w[2] }); }
      });
      var c = states[2];
      if (!flags.oreC && c.deposits.ore <= 1e-9) { flags.oreC = 1; note(year, 'resource', '鉱山の島の鉱石を掘り尽くした', { key: 'oreC' }); }
      if (world.special_material && !flags.shell && c.deposits.shell <= 1e-9) {
        flags.shell = 1;
        note(year, 'turn', '軽殻石を掘り尽くした（ここから先は木の船だけ）', { key: 'shellOut' });
      }
      // 潮麦に頼っていたところへ嵐が来て、食料が足りなくなった
      if (world.tidal_crop && r.storm > 0 && r.produced_food > 0 && r.coverage < 100) {
        var prev = records[records.length - 2];
        var share = prev && prev.food_sources ? prev.food_sources.tide / Math.max(1e-9, prev.produced_food) : 0;
        if (share >= 0.4) note(year, 'turn', '食料の' + Math.round(share * 100) + '％を潮麦に頼っていたところへ嵐。食料の充足が' + r.coverage + '％に下がった', { key: 'tideStorm' });
      }
    }

    return {
      version: VERSION, world: { id: world.id, name: world.name, tidal_crop: world.tidal_crop, special_material: world.special_material },
      options: o, records: records, notes: notes, techs: techs
    };
  }

  function simulateAll(worlds, options) {
    return worlds.map(function (w) { return simulate(w, options); });
  }

  // ---- 試行のまとめ ----
  var SERIES = [
    ['coverage', function (r) { return r.coverage; }],
    ['population', function (r) { return r.population; }],
    ['ships', function (r) { return r.ships; }],
    ['transported', function (r) { return r.transported; }],
    ['produced_food', function (r) { return r.produced_food; }],
    ['stock_food', function (r) { return r.islands.reduce(function (a, s) { return a + s.stock.food; }, 0); }],
    ['knowledge', function (r) { return r.knowledge; }]
  ].concat(POOLS.map(function (k) { return ['eco:' + k, function (r) { return r.ecology_index[k]; }]; }));
  var SERIES_KEYS = SERIES.map(function (s) { return s[0]; });

  function digest(run) {
    var out = { series: {}, milestones: {} };
    var recs = run.records;
    SERIES.forEach(function (s) {
      out.series[s[0]] = Float64Array.from(recs, function (r) { var v = s[1](r); return v == null ? NaN : v; });
    });
    var m = out.milestones;
    var minCov = Infinity, shortYears = 0;
    recs.forEach(function (r) {
      if (r.year && r.coverage != null) {
        if (r.coverage < minCov) minCov = r.coverage;
        if (r.coverage < 100) { shortYears++; if (m.firstShortage == null) m.firstShortage = r.year; }
      }
    });
    m.minCoverage = minCov === Infinity ? 100 : minCov;
    m.shortageYears = shortYears;
    run.notes.forEach(function (n) {
      if (n.type === 'eco' && n.threshold != null) { var k = 'low:' + n.pool; if (m[k] == null) m[k] = n.year; }
      if (n.type === 'resource' || n.type === 'turn') { if (m['ev:' + n.key] == null) m['ev:' + n.key] = n.year; }
      if (n.type === 'tech') m['tech:' + n.tech] = n.year;
      if (n.type === 'migrate' && m.firstMigration == null) m.firstMigration = n.year;
      if (n.type === 'storm' && n.big) m.stormShips = n.ships;
    });
    var last = recs[recs.length - 1];
    m.finalShips = last.ships;
    m.finalPopulation = last.population;
    m.finalForest = last.ecology_index.forest;
    m.finalGrazers = last.ecology_index.grazers;
    return out;
  }

  function quantile(sorted, q) {
    if (!sorted.length) return NaN;
    var pos = (sorted.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
  }
  function aggregate(digests) {
    var len = digests[0].series.coverage.length;
    var series = {};
    SERIES_KEYS.forEach(function (k) {
      var p10 = new Float64Array(len), p50 = new Float64Array(len), p90 = new Float64Array(len);
      for (var y = 0; y < len; y++) {
        var col = [];
        for (var i = 0; i < digests.length; i++) { var v = digests[i].series[k][y]; if (!isNaN(v)) col.push(v); }
        col.sort(function (a, b) { return a - b; });
        p10[y] = quantile(col, 0.1); p50[y] = quantile(col, 0.5); p90[y] = quantile(col, 0.9);
      }
      series[k] = { p10: p10, p50: p50, p90: p90 };
    });
    var keys = {};
    digests.forEach(function (d) { for (var k in d.milestones) keys[k] = 1; });
    var milestones = {};
    Object.keys(keys).forEach(function (k) {
      var vals = digests.map(function (d) { return d.milestones[k]; }).filter(function (v) { return v != null; }).sort(function (a, b) { return a - b; });
      milestones[k] = { n: vals.length, share: vals.length / digests.length, p10: quantile(vals, 0.1), p50: quantile(vals, 0.5), p90: quantile(vals, 0.9) };
    });
    return { trials: digests.length, series: series, milestones: milestones };
  }

  return {
    VERSION: VERSION, ECO: ECO, POOLS: POOLS, POOL_NAMES: POOL_NAMES, POLICIES: POLICIES, ISLANDS: ISLANDS,
    WORLDS: WORLDS, WOOD_SHIP: WOOD_SHIP, BIO_DEFAULT: BIO_DEFAULT, MAT_DEFAULT: MAT_DEFAULT,
    DEMOGRAPHY: DEMOGRAPHY, TECHS: TECHS, DEFAULT_OPTIONS: DEFAULT_OPTIONS, SERIES_KEYS: SERIES_KEYS,
    uniform: uniform, sha256Hex: sha256Hex, clone: clone, normalizeOptions: normalizeOptions,
    capsFor: capsFor, ecosystemYear: ecosystemYear, initialEcosystem: initialEcosystem, worldParams: worldParams,
    simulate: simulate, simulateAll: simulateAll, digest: digest, aggregate: aggregate, dist: dist
  };
})();
if (typeof module !== 'undefined') module.exports = HeikouModel;
