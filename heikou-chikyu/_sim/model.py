"""並行地球 第1回：文明の計算（1週間版・A案：住民の判断は決めた規則と確率）

1年ずつ進める。集団（同じ場所で暮らす人々）ごとに、年齢別の人数・知識・道具・備蓄を持つ。
地域ごとに、植物・獲物・貝・魚・森・大木・畑・土の量を持つ。

1年の順番：
  気候と災害 → 労働の割り振り（水・燃料・食べ物・住まい・道具・舟・残りが余暇）
  → 収穫と備蓄 → 生死 → 知識（発見・開発・上達・忘れる・伝わる）→ 探索と移住 → 記録

単位：食べ物は「1人が1年に食べる量」（FU）。労働は人日。距離は km。
値の根拠と仮定は README.md の表にまとめる。
"""
import hashlib
import math
import pickle

import numpy as np

import world as W

VERSION = 'heikou-sim-1.1'
MAXAGE = 90

# ---------------------------------------------------------------- 人口（年齢別の死亡と出生）

# 狩猟採集民の年齢別死亡率（Siler モデル）。Gurven & Kaplan (2007) の狩猟採集民の値を仮置き
SILER = dict(a1=0.422, b1=1.131, a2=0.013, a3=0.000147, b3=0.086)
AGES = np.arange(MAXAGE)


def siler_hazard(x):
    s = SILER
    return s['a1'] * np.exp(-s['b1'] * x) + s['a2'] + s['a3'] * np.exp(s['b3'] * x)


Q0 = 1 - np.exp(-siler_hazard(AGES + 0.5))      # 1年で亡くなる確率（困りごとがないとき）
Q0[-1] = 1.0
FERT_SHAPE = np.where((AGES >= 15) & (AGES < 50), np.exp(-((AGES - 27.0) / 7.5) ** 2), 0.0)
FERT_SHAPE /= FERT_SHAPE.sum()
FEMALE_BIRTHS = 0.488
R0 = 0.002   # 食べ物・水・住まいが足りているときの、人口の伸び（年0.2％）に合わせる


def _survival(q):
    return np.concatenate([[1.0], np.cumprod(1 - q)[:-1]])


def _tfr_for(r):
    """オイラー＝ロトカの式で、伸び r になる合計特殊出生率"""
    l = _survival(Q0)
    return 1.0 / np.sum(np.exp(-r * (AGES + 0.5)) * l * FEMALE_BIRTHS * FERT_SHAPE)


TFR = _tfr_for(R0)
FERT = FERT_SHAPE * TFR                          # 女性1人あたりの年齢別出生数
E0_BASE = float(np.sum(_survival(Q0) * (1 - Q0 / 2)))  # 困りごとがないときの平均寿命


def stable_ages(n, r=0.002):
    w = np.exp(-r * (AGES + 0.5)) * _survival(Q0)
    w /= w.sum()
    return w * n


NEED = np.where(AGES < 5, 0.45, np.where(AGES < 15, 0.75, np.where(AGES < 60, 1.0, 0.85)))  # 食べる量（大人=1）
LABOR = np.where((AGES >= 15) & (AGES < 60), 250.0, np.where((AGES >= 10) & (AGES < 15), 100.0, np.where(AGES >= 60, 80.0, 0.0)))
VULN = np.where((AGES < 5) | (AGES >= 60), 1.5, 1.0)

# ---------------------------------------------------------------- 技術

TECHS = [
    # 記号, 名前, 前提の技術, 必要な資源, 開発に要る人日, 難しさ
    ('nets', '網とわな', (), 'fiber', 1500, 1.0),
    ('hooks', '釣り針', (), None, 800, 0.8),
    ('drying', '干物・燻製', (), None, 600, 0.7),
    ('containers', '水をためる器', (), 'fiber', 800, 0.8),
    ('pottery', '土器', (), 'clay', 3000, 2.0),
    ('wells', '井戸', ('containers',), None, 2000, 1.5),
    ('adze', '磨いた石の斧', (), 'adze_stone', 2500, 1.3),
    ('dugout', '丸木舟', (), 'bigtree', 4000, 1.8),
    ('outrigger', '浮き木つきの舟', ('dugout', 'nets'), 'bigtree', 6000, 3.0),
    ('sail', '帆', ('outrigger',), 'fiber', 8000, 4.0),
    ('wayfinding', '星と波の航法', ('sail',), None, 10000, 4.0),
    ('horticulture', '芋や果樹の栽培', (), 'crop', 8000, 3.0),
    ('agriculture', '穀物の農耕', ('adze',), 'grain', 15000, 4.0),
    ('fishpond', '養魚池', ('horticulture',), None, 6000, 2.5),
    ('salt', '塩づくり', ('pottery',), None, 1500, 1.2),
    ('storehouse', '高床の倉', ('adze',), 'bigtree', 4000, 1.8),
    ('copper', '銅の精錬', ('pottery',), 'copper', 20000, 6.0),
    ('tally', '数の記録', (), None, 3000, 4.0),
]
TK = [t[0] for t in TECHS]
TI = {k: i for i, k in enumerate(TK)}
NT = len(TECHS)
TECH_JA = {t[0]: t[1] for t in TECHS}
PREREQ = np.zeros((NT, NT), bool)
for i, t in enumerate(TECHS):
    for p in t[2]:
        PREREQ[i, TI[p]] = True
COST = np.array([t[4] for t in TECHS], float)
DIFF = np.array([t[5] for t in TECHS], float)

# 資源：存在する → 見つける → 性質を理解する →（技術で）加工できる → 使う
RES = ['fiber', 'clay', 'adze_stone', 'bigtree', 'crop', 'grain', 'copper']
RES_JA = {'fiber': '繊維になる植物', 'clay': '粘土', 'adze_stone': '斧に向く硬い石（サンゴ島では大きな貝）', 'bigtree': '舟を作れる大木',
          'crop': '育てられる芋や果樹', 'grain': '育てられる穀物', 'copper': '銅の鉱石'}
RI = {k: i for i, k in enumerate(RES)}
NR = len(RES)
P_FIND = np.array([0.6, 0.15, 0.15, 0.8, 0.08, 0.06, 0.004])   # その地域にあれば、1年に見つける確率（余暇で増える）
P_UNDERSTAND = np.array([0.3, 0.05, 0.05, 0.3, 0.02, 0.015, 0.003])
TECH_RES = np.array([RI[t[3]] if t[3] in RI else -1 for t in TECHS])

# 舟が届く距離（km）。技術の上達で 6〜10割
RANGE = {'raft': 30.0, 'dugout': 40.0, 'outrigger': 160.0, 'sail': 500.0, 'wayfinding': 1500.0}

# ---------------------------------------------------------------- 食べ物の取り方

ACTS = ['plant', 'game', 'shell', 'fish', 'offshore', 'garden', 'field', 'pond']
ACT_JA = {'plant': '採集', 'game': '狩り', 'shell': '貝とり', 'fish': '岸の漁', 'offshore': '沖の漁',
          'garden': '芋や果樹の畑', 'field': '穀物の畑', 'pond': '養魚池'}
STOCKS = ['plant', 'game', 'shell', 'fish', 'offshore']
GROW = {'plant': 0.8, 'game': 0.25, 'shell': 0.35, 'fish': 0.45, 'offshore': 0.45}   # 自然に増える速さ（年）
HARV = {'plant': 0.35, 'game': 0.25, 'shell': 0.30, 'fish': 0.30, 'offshore': 0.25}  # 1年にとれる上限（量に対して）
E1 = {'plant': 0.010, 'game': 0.014, 'shell': 0.011, 'fish': 0.009, 'offshore': 0.012,
      'garden': 0.008, 'field': 0.009, 'pond': 0.010}                                  # 1人日でとれる量（とり始め）
GARDEN_YIELD = 30.0   # 芋や果樹の畑 1km² で、1年に何人分
FIELD_YIELD = 75.0    # 穀物の畑
CLEAR_DAYS = 3000.0   # 森を 1km² 切り開く人日（石の斧なし）
INSIGHT = 0.0006      # 余暇1万人日あたり、難しさ1の技術を思いつく確率（1年）


def seed_for(*parts):
    key = ':'.join(str(p) for p in (VERSION,) + parts)
    return int(hashlib.sha256(key.encode()).hexdigest()[:16], 16)


class Sim:
    def __init__(self, world, trial, start_pop=1000, n_groups=5, years=3000, snapshot_every=10):
        self.w = world
        self.tid = world['tid']
        self.trial = trial
        self.years = years
        self.year = 0
        self.snap_every = snapshot_every
        ss = np.random.SeedSequence(seed_for(self.tid, trial))
        self.r_demo, self.r_event, self.r_know, self.r_move = [np.random.default_rng(s) for s in ss.spawn(4)]
        reg = world['reg']
        self.reg = reg
        self.NRg = len(reg['area'])
        lay = world['lay']
        self.n_isl = len(lay['area'])
        self.isl_req = np.sqrt(lay['area'] / math.pi)
        self.isl_kind = world['props']['kind']
        self.isl_hmax = world['props']['hmax']
        # 地域の自然の量（最初は手つかず）
        self.K = {s: 4 * reg['msy_' + s] / GROW[s] for s in STOCKS}
        self.S = {s: self.K[s].copy() for s in STOCKS}
        self.forest0 = reg['forest_km2'].copy()
        self.forest = reg['forest_km2'].copy()
        self.bigtree0 = reg['bigtree'].copy()
        self.bigtree = reg['bigtree'].copy()
        self.farmed = np.zeros(self.NRg)
        self.soil = reg['soil'].copy()
        self.region_res = np.stack([
            (reg['P'] > 500) & (reg['T'] > 5),
            reg['res_clay'], reg['res_adze_stone'], reg['bigtree'] >= 1,
            reg['res_root_crop'], reg['res_grain'], reg['res_copper']], axis=1)
        self.anom = np.zeros(self.n_isl)            # 雨の多さのずれ（島ごと）
        self.rainf = np.ones(self.n_isl)
        # 島のつながり（海の幅）
        L = world['links']
        self.nbr = [[] for _ in range(self.n_isl)]
        for a, b, g, vij, vji in zip(L['i'], L['j'], L['gap'], L['vis_ij'], L['vis_ji']):
            self.nbr[a].append((g, b, g <= vij))
            self.nbr[b].append((g, a, g <= vji))
        for lst in self.nbr:
            lst.sort()
        self.isl_regions = world['island_regions']
        self.adj = world['adj']
        self.region_center = np.stack([reg['lat'], reg['lon']], axis=1)
        # 集団
        self.cap = 64
        self._alloc(self.cap)
        self.G = 0
        self.events = []
        self.series = {k: [] for k in ('pop', 'groups', 'islands', 'food', 'water', 'shelter', 'poor', 'leisure', 'store',
                                       'techs', 'forest', 'bigtree', 'fish', 'shell', 'contacts', 'voyages', 'lost_voyages',
                                       'births', 'deaths', 'range_km', 'farmed_km2', 'max_tech')}
        self.deaths_age = []
        self.pop_age = []
        self.snaps = []
        self.isl_settled = np.full(self.n_isl, -1)
        self.checks = {'negative_stock': 0, 'negative_pop': 0, 'food_balance': 0, 'labor_over': 0}
        self.tech_first = {}
        self._place_start(start_pop, n_groups)

    # ------------------------------------------------------------ 集団の入れ物
    def _alloc(self, cap):
        z = lambda *s, dt=float: np.zeros(s, dt)
        self.ages = z(cap, MAXAGE)
        self.alive = z(cap, dt=bool)
        self.region = z(cap, dt=int)
        self.skill = z(cap, NT)
        self.dev = z(cap, NT)
        self.res = z(cap, NR, dt=np.int8)      # 0=知らない 1=見つけた 2=性質を理解した
        self.store = z(cap)
        self.houses = z(cap)
        self.boats = z(cap)
        self.years_here = z(cap)
        self.stress = z(cap)
        self.voyages = z(cap)
        self.immune = z(cap)
        self.fruitless = z(cap)
        self.range_seen = z(cap)
        self.crops = z(cap, 2, dt=bool)        # 持ち運んでいる作物（芋や果樹・穀物）
        self.parent = np.full(cap, -1)
        self.born = z(cap, dt=int)
        self.known = [set() for _ in range(cap)]
        self.last = {}
        self.conn_pop = {}

    def _grow(self):
        old = self.cap
        self.cap *= 2
        keep = {k: getattr(self, k) for k in ('ages', 'alive', 'region', 'skill', 'dev', 'res', 'store', 'houses', 'boats',
                                               'years_here', 'stress', 'voyages', 'immune', 'fruitless', 'range_seen',
                                               'crops', 'parent', 'born')}
        known = self.known
        self._alloc(self.cap)
        for k, v in keep.items():
            getattr(self, k)[:old] = v
        self.known[:old] = known

    def _new_group(self, ages, region, parent=-1, **kw):
        if self.G >= self.cap:
            self._grow()
        g = self.G
        self.G += 1
        self.ages[g] = ages
        self.alive[g] = True
        self.region[g] = region
        self.parent[g] = parent
        self.born[g] = self.year
        for k, v in kw.items():
            getattr(self, k)[g] = v
        return g

    def island_of(self, region):
        return self.reg['island'][region]

    def _learn_island(self, g, isl):
        """島を知る（その島から見える島も、見えたものとして知る）"""
        if isl in self.known[g]:
            return
        self.known[g].add(isl)

    def _seen_from(self, isl):
        return [b for (gap, b, vis) in self.nbr[isl] if vis]

    # ------------------------------------------------------------ 最初の配置（どの地形でも同じ規則）
    def forage_cap(self, regions):
        r = self.reg
        return r['msy_plant'][regions] + r['msy_game'][regions] + r['msy_shell'][regions] + r['msy_fish'][regions]

    def water_cap0(self, regions):
        r = self.reg
        return r['water_surface'][regions] + r['water_plant'][regions]

    def _place_start(self, n, k):
        """出発の中心の地域を、暮らしやすさ（採集と漁で養える人数と、道具なしで得られる水の少ない方）に
        比例した確率で選ぶ（陸地の多い所ほど選ばれやすく、試行ごとに変わる）。
        そこから歩くかいかだで行ける範囲の、暮らしやすい地域へ 200人ずつ置く。足りなければ同じ地域に重ねる"""
        allr = np.arange(self.NRg)
        score = np.minimum(self.forage_cap(allr), self.water_cap0(allr))
        r0 = int(self.r_move.choice(self.NRg, p=score / score.sum()))
        isl0 = self.island_of(r0)
        reach = set(self.isl_regions[isl0])
        for gap, b, vis in self.nbr[isl0]:
            if gap <= RANGE['raft']:
                reach.update(self.isl_regions[b])
        cand = sorted(reach, key=lambda r: -score[r])
        cand = [r0] + [r for r in cand if r != r0]
        chosen = [cand[i % len(cand)] for i in range(k)]
        self.start_regions = chosen
        for r in chosen:
            ages = np.round(stable_ages(n / k)).astype(float)
            ages[20] += n / k - ages.sum()
            pop = ages.sum()
            need = float(np.sum(ages * NEED))
            g = self._new_group(ages, r, store=need * 0.25, houses=pop / 6, boats=4)
            isl = self.island_of(r)
            self._learn_island(g, isl)
            for b in self._seen_from(isl):
                self.known[g].add(b)
            # 開始時点で、周りの資源のうち目につくもの（繊維の植物・大木）は知っている
            for res in ('fiber', 'bigtree'):
                if self.region_res[r, RI[res]]:
                    self.res[g, RI[res]] = 2
            self.isl_settled[isl] = 0
        self._event('start', -1, '開始：%d人（%d集団）。最初の島は%s（%s km²）' % (
            n, k, W.KIND_JA[self.isl_kind[isl0]], format(round(self.w['lay']['area'][isl0]), ',')), island=int(isl0))

    def _event(self, kind, g, text, **kw):
        e = dict(year=self.year, kind=kind, group=int(g), text=text)
        if g >= 0:
            e['region'] = int(self.region[g])
            e['island'] = int(self.island_of(self.region[g]))
        e.update(kw)
        self.events.append(e)

    # ------------------------------------------------------------ 1年
    def step(self):
        G = self.G
        al = self.alive[:G]
        idx = np.nonzero(al)[0]
        reg = self.reg
        y = self.year
        if len(idx) == 0:
            self._record(idx, {}, empty=True)
            self.year += 1
            return
        # ---- 気候と災害
        self.anom = 0.7 * self.anom + self.r_event.normal(0, 0.15, self.n_isl)
        self.rainf = np.clip(np.exp(self.anom), 0.3, 1.6)
        rg = self.region[idx]
        isl = reg['island'][rg]
        rf = self.rainf[isl]
        ages = self.ages[idx]
        pop = ages.sum(axis=1)
        adults = ages[:, 15:60].sum(axis=1)
        need = ages @ NEED
        labor = ages @ LABOR
        sk = self.skill[idx]
        has = lambda t: sk[:, TI[t]] > 0.25
        # 嵐（人の住む島ごと）。熱帯の外側（8〜30度）で多い
        isl_u = np.unique(isl)
        storm_sev = np.zeros(self.n_isl)
        for i_ in isl_u:
            la = abs(self.w['lay']['lat'][i_])
            p = 0.2 if 8 < la < 30 else (0.08 if la < 50 else 0.05)
            if self.r_event.uniform() < p:
                storm_sev[i_] = min(1.0, self.r_event.exponential(0.3)) * (1.5 if self.isl_kind[i_] == 'coral' else 1.0)
        sev = np.minimum(storm_sev[isl], 1.0)
        self.houses[idx] *= 1 - 0.5 * sev
        self.boats[idx] *= 1 - 0.6 * sev
        self.store[idx] *= 1 - 0.3 * sev
        reg_sev = np.minimum(storm_sev[reg['island']], 1.0)
        for s in ('plant', 'shell'):
            self.S[s] *= 1 - 0.2 * reg_sev
        # ---- 水
        coral = self.isl_kind[isl] == 'coral'
        share = self._shares(rg, pop)
        w_surface = reg['water_surface'][rg] * rf
        w_lens = reg['water_lens'][rg] * np.minimum(1.0, rf + 0.3) * sk[:, TI['wells']]
        w_rain = np.where(reg['P'][rg] * rf > 500, 1.0, reg['P'][rg] * rf / 500) * pop * np.minimum(1, sk[:, TI['containers']] + sk[:, TI['pottery']])
        w_plant = reg['water_plant'][rg] * np.minimum(1.0, rf + 0.2)
        wcap = (w_surface + w_lens + w_plant) * share + w_rain
        ws = np.minimum(1.0, wcap / np.maximum(pop, 1))
        lab_water = pop * np.where(w_surface > pop, 3.0, 6.0)
        # ---- 燃料（薪）
        T = reg['T'][rg]
        cold = np.clip((15 - T) / 15, 0, 1.5)
        fuel_need = pop * (1 + cold)
        fdens = np.clip(self.forest[rg] * share / np.maximum(fuel_need / 300, 1e-6), 0, 1)
        fuel_ok = np.minimum(1.0, self.forest[rg] * share * 300 / np.maximum(fuel_need, 1e-6))
        lab_fuel = pop * 4 / np.maximum(0.25, fdens)
        lab_tools = adults * 2
        base_lab = np.minimum(labor, lab_water + lab_fuel + lab_tools)
        L_food = np.maximum(0, labor - base_lab)
        # ---- 食べ物：限界の取れ高がそろうように労働を割り振る
        A = len(ACTS)
        n = len(idx)
        e1 = np.zeros((n, A))
        C = np.zeros((n, A))
        mult_fish = (1 + 0.5 * sk[:, TI['nets']]) * (1 + 0.3 * sk[:, TI['hooks']])
        for a, s in enumerate(STOCKS):
            dens = self.S[s][rg] / np.maximum(self.K[s][rg], 1e-9)
            e1[:, a] = E1[s] * (0.3 + 0.7 * dens)
            C[:, a] = self.S[s][rg] * HARV[s] * share
        e1[:, 1] *= 1 + 0.2 * sk[:, TI['nets']]
        e1[:, 3] *= mult_fish
        e1[:, 4] *= mult_fish
        boat_ok = (self.boats[idx] >= 1) & has('dugout')
        C[:, 4] *= boat_ok * (1 + 0.5 * sk[:, TI['outrigger']])
        crop_here = self.region_res[rg, RI['crop']] | self.crops[idx, 0]
        grain_here = self.region_res[rg, RI['grain']] | self.crops[idx, 1]
        farmed_share = self.farmed[rg] * share
        soil = self.soil[rg]
        gard = has('horticulture') & crop_here
        field = has('agriculture') & grain_here
        C[:, 5] = np.where(gard & ~field, farmed_share * GARDEN_YIELD * soil * rf ** 0.8, 0)
        e1[:, 5] = E1['garden'] * soil
        C[:, 6] = np.where(field, farmed_share * FIELD_YIELD * soil * rf ** 0.8, 0)
        e1[:, 6] = E1['field'] * soil
        C[:, 7] = np.where(has('fishpond'), reg['shelf_km2'][rg] * 2.0 * sk[:, TI['fishpond']] * share, 0)
        e1[:, 7] = E1['pond']
        keep = np.minimum(0.8, 0.15 + 0.2 * sk[:, TI['drying']] + 0.15 * sk[:, TI['salt']] + 0.15 * sk[:, TI['pottery']]
                          + 0.15 * sk[:, TI['storehouse']])
        store_prev = self.store[idx]
        store_cap = need * (0.25 + 0.75 * keep)
        kept = store_prev * keep
        target = np.maximum(0, need * 1.05 - kept + np.maximum(0, store_cap - kept) * 0.5)
        H, E = solve_effort(e1, C, target, L_food)
        produced = H.sum(axis=1)
        avail = kept + produced
        eat = np.minimum(need, avail)
        fs = np.where(need > 0, avail / np.maximum(need, 1e-9), 1.0)
        fs = np.minimum(fs, 1.0)
        new_store = np.minimum(avail - eat, store_cap)
        if np.any(new_store < -1e-9) or np.any(eat > avail + 1e-9):
            self.checks['food_balance'] += 1
        self.store[idx] = new_store
        lab_used_food = E.sum(axis=1)
        if np.any(lab_used_food > L_food * (1 + 1e-6) + 1e-6):
            self.checks['labor_over'] += 1
        # 自然の量を減らす（同じ地域の集団の分を合計）
        for a, s in enumerate(STOCKS):
            take = np.bincount(rg, weights=H[:, a], minlength=self.NRg)
            self.S[s] = np.maximum(0.0, self.S[s] - take)
        # ---- 住まい・舟・道具。残りが余暇
        rest = np.maximum(0, labor - base_lab - lab_used_food)
        house_need = pop / 6
        dur = 0.08 * (1 - 0.4 * sk[:, TI['storehouse']])
        self.houses[idx] *= 1 - dur
        build_h = np.minimum(np.maximum(0, house_need - self.houses[idx]), rest / 30)
        build_h = np.minimum(build_h, self.forest[rg] * share * 50)
        self.houses[idx] += build_h
        rest -= build_h * 30 + self.houses[idx] * 3
        rest = np.maximum(rest, 0)
        shelter = np.minimum(1.0, self.houses[idx] / np.maximum(house_need, 1e-9))
        # 舟：いちばん進んだ舟の技術で、大人8人に1艘を目安に作る
        boat_tier = np.where(has('dugout'), 1, 0)
        self.boats[idx] *= 0.88
        want = np.maximum(1, adults / 8) * (adults > 3)
        # 丸木舟は火でくりぬけば石の斧なしでも作れるが、斧があれば半分の手間
        days_per = np.where(boat_tier > 0, (90 + 40 * has('outrigger') + 30 * has('sail')) * (1 - 0.5 * has('adze')), 12)
        trees = self.bigtree[rg] * share
        can = np.where(boat_tier > 0, np.minimum(trees, np.maximum(0, want - self.boats[idx])), np.maximum(0, want - self.boats[idx]))
        can = np.where((boat_tier == 0) & (self.forest[rg] * share < 0.5), 0, can)
        build_b = np.minimum(can, rest * 0.5 / days_per)
        self.boats[idx] += build_b
        rest -= build_b * days_per
        tree_use = build_b * (boat_tier > 0) + build_h * 0.02 * has('storehouse')
        self.bigtree -= np.minimum(self.bigtree, np.bincount(rg, weights=tree_use, minlength=self.NRg))
        # 畑を広げる（栽培を知っていて、作物がある所。食べ物が足りないほど急ぐ）
        farming = gard | field
        farm_need = np.where(field, need / (FIELD_YIELD * np.maximum(soil, 0.1) * 0.8),
                             need / (GARDEN_YIELD * np.maximum(soil, 0.1) * 0.8)) * 1.2
        arable_left = np.maximum(0, reg['arable_km2'][rg] * share - farmed_share)
        clear_days = CLEAR_DAYS / (1 + sk[:, TI['adze']] + 0.5 * sk[:, TI['copper']])
        add_km2 = np.where(farming, np.minimum(np.minimum(arable_left, np.maximum(0, farm_need - farmed_share)),
                                               rest * 0.35 / clear_days), 0)
        rest -= add_km2 * clear_days
        add_reg = np.bincount(rg, weights=add_km2, minlength=self.NRg)
        self.farmed += add_reg
        self.forest = np.maximum(0, self.forest - add_reg)
        leisure = np.maximum(0, rest)
        # ---- 自然の回復（雨の多さで変わる）
        rf_reg = self.rainf[reg['island']]
        for s in STOCKS:
            r_ = GROW[s] * (rf_reg if s in ('plant', 'game') else 1.0)
            S, K = self.S[s], self.K[s]
            self.S[s] = np.minimum(K, S + r_ * S * (1 - S / np.maximum(K, 1e-9)) + 1e-4 * K)
        regrow_f = 0.02 * self.forest * (1 - self.forest / np.maximum(self.forest0, 1e-9))
        self.forest = np.minimum(self.forest0 - self.farmed * 0.999, self.forest + regrow_f + 0.001 * np.maximum(0, self.forest0 - self.farmed - self.forest))
        self.forest = np.maximum(self.forest, 0)
        self.bigtree = np.minimum(self.bigtree0, self.bigtree + 0.012 * self.bigtree * (1 - self.bigtree / np.maximum(self.bigtree0, 1e-9)) + 0.0005 * self.bigtree0 * (self.forest / np.maximum(self.forest0, 1e-9)))
        intense = np.bincount(rg, weights=field.astype(float) * farmed_share, minlength=self.NRg)
        f_field = np.clip(intense / np.maximum(self.farmed, 1e-9), 0, 1)
        self.soil = np.clip(self.soil - 0.004 * f_field * self.soil + 0.01 * (reg['soil'] - self.soil), 0.2, reg['soil'])
        self.region_res[:, RI['bigtree']] = self.bigtree >= 1
        if any(np.any(self.S[s] < 0) for s in STOCKS) or np.any(self.forest < 0):
            self.checks['negative_stock'] += 1
        # ---- 生死
        d_f = 1 - fs
        d_w = 1 - ws
        d_s = 1 - shelter
        stress = 8 * d_f ** 1.5 + 10 * d_w ** 1.5 + 0.6 * d_s * (0.3 + cold) + 1.5 * (1 - fuel_ok) * cold + 0.3 * sev
        hz = -np.log(1 - np.minimum(Q0, 0.999999))
        q = 1 - np.exp(-hz[None, :] * (1 + stress[:, None] * VULN[None, :]))
        # はやり病
        epi = np.zeros(n)
        # はやり病は、行き来のある人の数（自分＋付き合いのある集団）と、人の密度で起こりやすくなる
        conn = np.array([self.conn_pop.get(int(g), 0.0) for g in idx]) + pop
        dens = pop / np.maximum(reg['area'][rg], 1)
        p_epi = 0.002 + 0.012 * np.minimum(conn / 20000, 1) + 0.008 * np.minimum(dens / 20, 1)
        p_epi = np.where(self.immune[idx] > y, 0, p_epi)
        hit_e = self.r_event.uniform(0, 1, n) < p_epi
        if hit_e.any():
            epi[hit_e] = self.r_event.uniform(0.04, 0.18, hit_e.sum())
            self.immune[idx[hit_e]] = y + 30
        q = 1 - (1 - q) * (1 - epi[:, None] * np.where((AGES < 5) | (AGES >= 55), 1.6, 0.8)[None, :])
        # 津波（高い火山島、まれ）
        tsu = np.zeros(n)
        for i_ in isl_u:
            if self.isl_kind[i_] == 'volcanic_high' and self.r_event.uniform() < 0.0004:
                m = isl == i_
                tsu[m] = self.r_event.uniform(0.03, 0.15)
                self.houses[idx[m]] *= 0.4
                self.boats[idx[m]] *= 0.2
                self._event('tsunami', -1, '津波が島を襲った', island=int(i_), deaths=int(np.sum(pop[m] * tsu[m])))
        q = 1 - (1 - q) * (1 - tsu[:, None])
        q = np.clip(q, 0, 1)
        q[:, -1] = 1.0
        deaths = self.r_demo.binomial(ages.astype(np.int64), q).astype(float)
        women = ages * 0.5
        fert = FERT[None, :] * (fs ** 2 * (1 - 0.6 * d_w) * (1 - 0.3 * sev))[:, None]
        births = self.r_demo.poisson(np.sum(women * fert, axis=1)).astype(float)
        survivors = ages - deaths
        new = np.zeros_like(ages)
        new[:, 1:] = survivors[:, :-1]
        new[:, 0] = births
        self.ages[idx] = new
        if np.any(new < 0):
            self.checks['negative_pop'] += 1
        big_storm = [i_ for i_ in isl_u if storm_sev[i_] >= 0.6]
        for i_ in big_storm:
            m = isl == i_
            self._event('storm', -1, '大きな嵐', island=int(i_), severity=float(storm_sev[i_]),
                        deaths=int(deaths[m].sum()))
        for k_ in np.nonzero(hit_e)[0]:
            if pop[k_] * epi[k_] >= 5:
                self._event('epidemic', int(idx[k_]), 'はやり病', deaths=int(round(pop[k_] * epi[k_])))
        # ---- 知識
        self._knowledge(idx, leisure, adults, fs, ws, pop)
        # ---- 探索・分かれる・移る
        self.stress[idx] = 0.8 * self.stress[idx] + 0.2 * np.clip(d_f + d_w, 0, 1)
        self.years_here[idx] += 1
        famine = np.nonzero((fs < 0.7) & (pop > 20))[0]
        for k_ in famine:
            if self.r_event.uniform() < 0.2:
                self._event('famine', int(idx[k_]), '食べ物が大きく足りない年', food=float(fs[k_]))
        self._move(idx)
        self._tidy()
        # ---- 記録
        ctx = dict(fs=fs, ws=ws, shelter=shelter, leisure=leisure, adults=adults, pop=pop, need=need,
                   deaths=deaths, births=births, ages_before=ages)
        self._record(idx, ctx)
        self.year += 1

    def _shares(self, rg, pop):
        tot = np.bincount(rg, weights=pop, minlength=self.NRg)
        return np.where(tot[rg] > 0, pop / np.maximum(tot[rg], 1e-9), 1.0)

    # ------------------------------------------------------------ 知識：見つける・理解する・作り出す・上達・忘れる・伝わる
    def _knowledge(self, idx, leisure, adults, fs, ws, pop):
        rk = self.r_know
        n = len(idx)
        rg = self.region[idx]
        lpa = leisure / np.maximum(adults, 1)
        curious = np.clip(leisure / 20000, 0, 2)
        here = self.region_res[rg] | np.concatenate([np.zeros((n, 4), bool), self.crops[idx], np.zeros((n, 1), bool)], axis=1)
        here[:, RI['crop']] = self.region_res[rg, RI['crop']] | self.crops[idx, 0]
        here[:, RI['grain']] = self.region_res[rg, RI['grain']] | self.crops[idx, 1]
        st = self.res[idx]
        u = rk.uniform(0, 1, (n, NR))
        pf = 1 - (1 - P_FIND[None, :]) ** (1 + curious[:, None])
        found = here & (st == 0) & (u < pf)
        u2 = rk.uniform(0, 1, (n, NR))
        und = (st == 1) & here & (u2 < P_UNDERSTAND[None, :] * (0.5 + curious[:, None]))
        st = st + found + und
        self.res[idx] = st
        for k, r in zip(*np.nonzero(found | und)):
            stage = '見つけた' if st[k, r] == 1 else '性質を理解した'
            if r in (RI['copper'], RI['grain'], RI['crop'], RI['clay']):
                self._event('resource', int(idx[k]), '%sを%s' % (RES_JA[RES[r]], stage), res=RES[r], stage=int(st[k, r]))
        sk = self.skill[idx]
        dev = self.dev[idx]
        known = sk > 0
        prereq_ok = np.all((sk[:, None, :] > 0.3) | ~PREREQ[None, :, :], axis=2)
        res_ok = np.ones((n, NT), bool)
        for t in range(NT):
            r = TECH_RES[t]
            if r >= 0:
                res_ok[:, t] = (st[:, r] >= 2) & here[:, r]
        res_ok[:, TI['horticulture']] = ((st[:, RI['crop']] >= 2) & here[:, RI['crop']]) | ((st[:, RI['grain']] >= 2) & here[:, RI['grain']])
        extra = np.ones((n, NT), bool)
        extra[:, TI['wayfinding']] = self.voyages[idx] >= 15
        extra[:, TI['horticulture']] &= self.years_here[idx] >= 15
        extra[:, TI['agriculture']] &= self.years_here[idx] >= 20
        extra[:, TI['fishpond']] = self.reg['shelf_km2'][rg] > 5
        extra[:, TI['tally']] = pop > 150
        # 必要に迫られると思いつきやすい
        needf = np.ones((n, NT))
        needf[:, TI['wells']] += 3 * (1 - ws)
        needf[:, TI['containers']] += 3 * (1 - ws)
        needf[:, [TI['horticulture'], TI['agriculture'], TI['fishpond']]] += 2 * np.clip(self.stress[idx], 0, 1)[:, None]
        needf[:, [TI['drying'], TI['salt'], TI['storehouse']]] += 1.0 * (1 - fs)[:, None]
        cand = ~known & (dev == 0) & prereq_ok & res_ok & extra
        p_ins = 1 - np.exp(-(leisure[:, None] / 10000.0) * INSIGHT * needf / DIFF[None, :])
        ins = cand & (rk.uniform(0, 1, (n, NT)) < p_ins)
        dev[ins] = 1e-6
        # 開発：余暇の15％を、取りかかっている開発に分ける
        active = (dev > 0) & ~known
        na = active.sum(axis=1)
        per = np.where(na > 0, leisure * 0.15 / np.maximum(na, 1), 0)
        dev = np.where(active & prereq_ok & res_ok, dev + per[:, None], dev)
        done = active & (dev >= COST[None, :])
        sk = np.where(done, 0.4, sk)
        dev = np.where(done, 0, dev)
        known = sk > 0
        for k, t in zip(*np.nonzero(done)):
            g = int(idx[k])
            first = TK[t] not in self.tech_first
            if first:
                self.tech_first[TK[t]] = self.year
            self._event('tech', g, '%sを作り出した' % TECH_JA[TK[t]] + ('（この世界で初めて）' if first else ''), tech=TK[t], first=first)
        # 上達と、忘れること（人が少ない・材料がない・使わないと失われる）
        practiced = res_ok | (TECH_RES[None, :] < 0)
        teach = np.clip(lpa / 30, 0, 1)
        record = np.clip(sk[:, TI['tally']], 0, 1)
        decay = (0.004 + 0.04 * np.clip(1 - adults / 25, 0, 1))[:, None] + 0.03 * ~practiced
        decay = decay * (1 - 0.5 * record[:, None])
        sk2 = np.where(known, sk + 0.08 * teach[:, None] * practiced * (1 - sk) - decay, 0)
        lost = known & (sk2 < 0.08)
        sk2 = np.where(lost, 0, np.clip(sk2, 0, 1))
        for k, t in zip(*np.nonzero(lost)):
            self._event('tech_lost', int(idx[k]), '%sが失われた' % TECH_JA[TK[t]], tech=TK[t])
        self.skill[idx] = sk2
        self.dev[idx] = dev
        # 作物を持ち運べるようになる
        self.crops[idx, 0] |= (sk2[:, TI['horticulture']] > 0.3) & self.region_res[rg, RI['crop']]
        self.crops[idx, 1] |= (sk2[:, TI['agriculture']] > 0.3) & self.region_res[rg, RI['grain']]
        # 伝わる：付き合いのある集団どうし
        self._contacts(idx)

    def _range(self, g):
        s = self.skill[g]
        r = RANGE['raft']
        for t in ('dugout', 'outrigger', 'sail', 'wayfinding'):
            if s[TI[t]] > 0.25:
                r = RANGE[t] * (0.6 + 0.4 * s[TI[t]])
        if self.boats[g] < 1 and r > RANGE['raft']:
            r = RANGE['raft']
        return r

    def _contacts(self, idx):
        """付き合いのある集団の組を決め、技術・資源の知識・作物が伝わる"""
        rk = self.r_know
        by_reg = {}
        by_isl = {}
        regs = self.region
        isl_of = self.reg['island']
        for g in idx:
            r = int(regs[g])
            by_reg.setdefault(r, []).append(int(g))
            by_isl.setdefault(int(isl_of[r]), []).append(int(g))
        pa, pb = [], []
        for g in idx:
            g = int(g)
            r = int(regs[g])
            near = set(by_reg.get(r, ()))
            for r2 in self.adj[r]:
                near.update(by_reg.get(r2, ()))
            isl = int(isl_of[r])
            if self.boats[g] >= 1:
                R = self._range(g)
                kn = self.known[g]
                for gap, b, vis in self.nbr[isl]:
                    if gap > R:
                        break
                    if b in by_isl and b in kn and rk.uniform() < 0.3:
                        near.update(by_isl[b])
            for h in near:
                if h > g:
                    pa.append(g)
                    pb.append(h)
                elif h < g:
                    pa.append(h)
                    pb.append(g)
        self.last = {}
        self.conn_pop = {}
        self._voyages_trade = 0
        if not pa:
            return
        P = np.unique(np.array([pa, pb]).T, axis=0)
        A, B = P[:, 0], P[:, 1]
        popg = self.ages.sum(axis=1)
        for a, b in zip(A.tolist(), B.tolist()):
            self.last.setdefault(a, set()).add(b)
            self.last.setdefault(b, set()).add(a)
            self.conn_pop[a] = self.conn_pop.get(a, 0.0) + popg[b]
            self.conn_pop[b] = self.conn_pop.get(b, 0.0) + popg[a]
        ia, ib = isl_of[regs[A]], isl_of[regs[B]]
        cross = np.nonzero(ia != ib)[0]
        self._voyages_trade = int(len(cross))
        for k in cross:
            a, b, xa, xb = int(A[k]), int(B[k]), int(ia[k]), int(ib[k])
            key = ('contact', min(xa, xb), max(xa, xb))
            if key not in self.tech_first:
                self.tech_first[key] = self.year
                self._event('contact', a, '別の島の人々と行き来が始まった', other=b, islands=[xa, xb])
            self.known[a].add(xb)
            self.known[b].add(xa)
        # 技術が伝わる（よく身についた技術を、知らない側へ。1年に15％）。受け取る側で材料が手に入る技術だけ
        avail = np.ones((self.cap, NT), bool)
        for t in range(NT):
            r = TECH_RES[t]
            if r >= 0:
                avail[:, t] = self.region_res[self.region[:self.cap], r]
        avail[:, TI['horticulture']] = (self.region_res[self.region[:self.cap], RI['crop']] | self.crops[:, 0]
                                        | self.region_res[self.region[:self.cap], RI['grain']] | self.crops[:, 1])
        avail[:, TI['agriculture']] = self.region_res[self.region[:self.cap], RI['grain']] | self.crops[:, 1]
        for src, dst in ((A, B), (B, A)):
            ss, sd = self.skill[src], self.skill[dst]
            m = (ss > 0.4) & (sd == 0) & avail[dst] & (rk.uniform(0, 1, ss.shape) < 0.15)
            for k, t in zip(*np.nonzero(m)):
                d = int(dst[k])
                if self.skill[d, t] == 0:
                    self.skill[d, t] = 0.25
                    self._event('tech_spread', d, '%sが伝わった' % TECH_JA[TK[t]], tech=TK[t], source=int(src[k]))
            und = np.where(self.res[src] >= 2, 2, 0).astype(np.int8)
            np.maximum.at(self.res, dst, und)
            carry = self.crops[src] & (self.skill[dst][:, [TI['horticulture'], TI['agriculture']]] > 0.25)
            np.logical_or.at(self.crops, dst, carry)

    # ------------------------------------------------------------ 探索・分かれる・移る（決めた規則と確率）
    def split_size(self, g):
        s = self.skill[g]
        if s[TI['agriculture']] > 0.3:
            return 3000
        if s[TI['horticulture']] > 0.3 or s[TI['fishpond']] > 0.3:
            return 1000
        return 400

    def capacity(self, g, rs):
        """集団 g の技術で、地域 rs が養える人数の目安（いまの自然の量で）"""
        reg = self.reg
        rs = np.atleast_1d(rs)
        c = np.zeros(len(rs))
        for s_ in ('plant', 'game', 'shell', 'fish'):
            c += reg['msy_' + s_][rs] * (self.S[s_][rs] / np.maximum(self.K[s_][rs], 1e-9))
        s = self.skill[g]
        if s[TI['dugout']] > 0.3:
            c += reg['msy_offshore'][rs] * 0.5
        crop = self.region_res[rs, RI['crop']] | self.crops[g, 0]
        grain = self.region_res[rs, RI['grain']] | self.crops[g, 1]
        if s[TI['agriculture']] > 0.3:
            c += np.where(grain, reg['arable_km2'][rs] * FIELD_YIELD * self.soil[rs] * 0.6, 0)
        elif s[TI['horticulture']] > 0.3:
            c += np.where(crop | grain, reg['arable_km2'][rs] * GARDEN_YIELD * self.soil[rs] * 0.6, 0)
        water = reg['water_surface'][rs] + reg['water_plant'][rs]
        if s[TI['wells']] > 0.3:
            water = water + reg['water_lens'][rs]
        if s[TI['containers']] > 0.3 or s[TI['pottery']] > 0.3:
            water = np.where(reg['P'][rs] > 500, 1e7, water)
        return np.minimum(c, water)

    def _move(self, idx):
        rm = self.r_move
        pop_reg = np.bincount(self.region[idx], weights=self.ages[idx].sum(axis=1), minlength=self.NRg)
        voyages, lost = 0, 0
        for g in idx:
            g = int(g)
            if not self.alive[g]:
                continue
            pop = self.ages[g].sum()
            if pop < 1:
                continue
            r = int(self.region[g])
            isl = int(self.reg['island'][r])
            R = self._range(g)
            cap_here = float(self.capacity(g, r)[0])
            crowd = pop_reg[r] / max(cap_here, 1)
            pressure = max(self.stress[g], min(1.0, max(0.0, crowd - 0.7)), max(0.0, pop / self.split_size(g) - 0.9))
            # 海の探検（舟があり、困っているほど出やすい）
            # 何度出ても見つからないと、探検に出なくなる（舟の届く距離が伸びると、また出る）
            if self.range_seen[g] < R:
                self.range_seen[g] = R
                self.fruitless[g] = 0
            if self.boats[g] >= 1 and rm.uniform() < (0.01 + 0.25 * pressure) * math.exp(-self.fruitless[g] / 4):
                voyages += 1
                self.voyages[g] += 1
                found = []
                far = 0.0
                gapd = {}
                for gap, b, vis in self.nbr[isl]:
                    if gap > R:
                        break
                    if b in self.known[g]:
                        continue
                    cue = 40.0 if self.isl_hmax[b] > 500 else 10.0
                    p = min(1.0, 3 * 2 * (self.isl_req[b] + cue) / (2 * math.pi * max(gap, 1)))
                    if rm.uniform() < p:
                        found.append(b)
                        gapd[b] = gap
                        far = max(far, gap)
                p_loss = min(0.5, 0.03 + 0.25 * (max(far, R * 0.5) / R) ** 2) * (1 - 0.5 * self.skill[g, TI['wayfinding']])
                if rm.uniform() < p_loss:
                    lost += 1
                    self._kill_crew(g, 6)
                    self._event('voyage_lost', g, '探検の舟が戻らなかった')
                else:
                    self.fruitless[g] = 0 if found else self.fruitless[g] + 1
                    for b in found:
                        self.known[g].add(b)
                        for b2 in self._seen_from(b):
                            self.known[g].add(b2)
                        self._event('island_found', g, '新しい島を見つけた（海の幅 %dkm）' % round(gapd[b]), found=int(b), gap=float(gapd[b]))
            # 分かれる（大きくなりすぎた・混んできた）
            if pop > self.split_size(g) * rm.uniform(0.9, 1.25) or (self.stress[g] > 0.12 and pop > 60 and rm.uniform() < 0.2):
                # 大きくなって分かれるときは、今の場所の6割くらいの暮らしやすさでも移る
                dest = self._best_dest(g, r, isl, R, pop_reg, pop * 0.4, need_better=0.6)
                if dest is not None:
                    d_r, gap = dest
                    self._split(g, d_r, gap, R, pop_reg)
            elif self.stress[g] > 0.3 and pop > 10 and rm.uniform() < 0.15:
                dest = self._best_dest(g, r, isl, R, pop_reg, pop, need_better=1.3)
                if dest is not None:
                    d_r, gap = dest
                    self._relocate(g, d_r, gap, R, pop_reg)
        self._voyages = voyages
        self._lost = lost

    def _dest_candidates(self, g, r, isl, R):
        out = []
        for r2 in self.isl_regions[isl]:
            if r2 != r:
                out.append((r2, 0.0))
        for gap, b, vis in self.nbr[isl]:
            if gap > R:
                break
            if b in self.known[g]:
                for r2 in self.isl_regions[b]:
                    out.append((r2, gap))
        return out

    def _best_dest(self, g, r, isl, R, pop_reg, movers, need_better=1.0):
        cands = self._dest_candidates(g, r, isl, R)
        if not cands:
            return None
        if len(cands) > 120:
            cands = [cands[i] for i in self.r_move.choice(len(cands), 120, replace=False)]
        rs = np.array([c[0] for c in cands])
        gaps = np.array([c[1] for c in cands])
        here = float(self.capacity(g, r)[0]) / (pop_reg[r] + 1)
        lat0, lon0 = self.region_center[r]
        d = W.gc_dist(lat0, lon0, self.region_center[rs, 0], self.region_center[rs, 1])
        # 遠い所ほど不利（同じ島の中は歩く距離、島をまたぐときは海の幅）
        sc = self.capacity(g, rs) / (pop_reg[rs] + movers + 1) / (1 + d / 400 + gaps / max(R, 1))
        k = int(np.argmax(sc))
        if sc[k] <= here * need_better:
            return None
        return int(rs[k]), float(gaps[k])

    def _split(self, g, d_r, gap, R, pop_reg):
        frac = 0.4
        movers = self.r_move.binomial(self.ages[g].astype(np.int64), frac).astype(float)
        if movers.sum() < 8:
            return
        self.ages[g] -= movers
        p_loss = (0.01 + 0.2 * (gap / max(R, 1)) ** 2) if gap > 0 else 0.0
        src_isl = int(self.reg['island'][self.region[g]])
        dst_isl = int(self.reg['island'][d_r])
        if self.r_move.uniform() < p_loss:
            self._event('migration_lost', g, '移住の舟が戻らなかった（%d人）' % movers.sum(), people=int(movers.sum()), gap=float(gap))
            return
        h = self._new_group(movers, d_r, parent=g, store=self.store[g] * frac, houses=0.0, boats=self.boats[g] * frac)
        self.store[g] *= 1 - frac
        self.boats[g] *= 1 - frac
        self.skill[h] = self.skill[g] * 0.9
        self.res[h] = self.res[g]
        self.crops[h] = self.crops[g]
        self.known[h] = set(self.known[g])
        self.voyages[h] = self.voyages[g]
        self.known[h].add(dst_isl)
        for b in self._seen_from(dst_isl):
            self.known[h].add(b)
        pop_reg[d_r] += movers.sum()
        pop_reg[self.region[g]] -= movers.sum()
        if dst_isl != src_isl:
            first = self.isl_settled[dst_isl] < 0
            if first:
                self.isl_settled[dst_isl] = self.year
            self._event('settle', h, '%d人が海を渡って移り住んだ（海の幅 %dkm）' % (movers.sum(), round(gap)) + ('。初めて人が住む島' if first else ''),
                        people=int(movers.sum()), gap=float(gap), first=bool(first), from_island=src_isl)
        else:
            self._event('split', h, '%d人が分かれて新しい土地へ' % movers.sum(), people=int(movers.sum()))

    def _relocate(self, g, d_r, gap, R, pop_reg):
        pop = self.ages[g].sum()
        p_loss = (0.01 + 0.2 * (gap / max(R, 1)) ** 2) if gap > 0 else 0.0
        if self.r_move.uniform() < p_loss:
            self._kill_crew(g, int(pop * 0.3))
            self._event('migration_lost', g, '移住の途中で舟の一部が戻らなかった')
        src = int(self.region[g])
        pop_reg[src] -= self.ages[g].sum()
        self.region[g] = d_r
        pop_reg[d_r] += self.ages[g].sum()
        self.years_here[g] = 0
        self.houses[g] *= 0.2
        dst_isl = int(self.reg['island'][d_r])
        self.known[g].add(dst_isl)
        if dst_isl != int(self.reg['island'][src]):
            first = self.isl_settled[dst_isl] < 0
            if first:
                self.isl_settled[dst_isl] = self.year
            self._event('relocate', g, '集団ごと海を渡って移った（海の幅 %dkm）' % round(gap) + ('。初めて人が住む島' if first else ''),
                        gap=float(gap), first=bool(first))
        else:
            self._event('relocate_land', g, '集団ごと新しい土地へ移った')

    def _kill_crew(self, g, k):
        """若い大人から k 人を失う"""
        a = self.ages[g]
        for age in range(18, 45):
            if k <= 0:
                break
            take = min(a[age], math.ceil(k / 4))
            a[age] -= take
            k -= take

    def _tidy(self):
        live = np.nonzero(self.alive[:self.G])[0]
        by_reg = {}
        for g in live:
            by_reg.setdefault(int(self.region[g]), []).append(int(g))
        for g in live:
            g = int(g)
            p = self.ages[g].sum()
            if p < 1:
                self.alive[g] = False
                self._event('extinct', g, '集団が途絶えた')
                continue
            if p < 15:
                others = [h for h in by_reg.get(int(self.region[g]), ()) if h != g and self.alive[h]]
                if others:
                    h = others[0]
                    self.ages[h] += self.ages[g]
                    self.skill[h] = np.maximum(self.skill[h], self.skill[g])
                    self.res[h] = np.maximum(self.res[h], self.res[g])
                    self.known[h] |= self.known[g]
                    self.alive[g] = False
                    self.ages[g] = 0
                    self._event('merge', g, '小さくなった集団が近くの集団に加わった', into=h)

    # ------------------------------------------------------------ 記録
    def _record(self, idx, c, empty=False):
        s = self.series
        if empty:
            for k in s:
                s[k].append(0.0)
            self.deaths_age.append(np.zeros(MAXAGE))
            self.pop_age.append(np.zeros(MAXAGE))
            return
        pop = c['pop']
        P = max(pop.sum(), 1e-9)
        alive_now = self.alive[idx]
        s['pop'].append(float(self.ages[idx].sum()))
        s['groups'].append(int(alive_now.sum()))
        s['islands'].append(int(len(set(self.reg['island'][self.region[idx[alive_now]]]))) if alive_now.any() else 0)
        s['food'].append(float(np.sum(c['fs'] * pop) / P))
        s['water'].append(float(np.sum(c['ws'] * pop) / P))
        s['shelter'].append(float(np.sum(c['shelter'] * pop) / P))
        poor = (c['fs'] < 0.95) | (c['ws'] < 0.95) | (c['shelter'] < 0.8)
        s['poor'].append(float(np.sum(pop * poor) / P))
        s['leisure'].append(float(np.sum(c['leisure']) / max(c['adults'].sum(), 1)))
        s['store'].append(float(np.sum(self.store[idx]) / max(c['need'].sum(), 1e-9) * 12))
        sk = self.skill[idx]
        s['techs'].append(float(np.sum((sk > 0).sum(axis=1) * pop) / P))
        s['max_tech'].append(int((sk > 0).any(axis=0).sum()))
        used = np.unique(self.region[idx])
        s['forest'].append(float(self.forest[used].sum() / max(self.forest0[used].sum(), 1e-9)))
        s['bigtree'].append(float(self.bigtree[used].sum() / max(self.bigtree0[used].sum(), 1e-9)))
        s['fish'].append(float(self.S['fish'][used].sum() / max(self.K['fish'][used].sum(), 1e-9)))
        s['shell'].append(float(self.S['shell'][used].sum() / max(self.K['shell'][used].sum(), 1e-9)))
        s['contacts'].append(int(sum(len(v) for v in self.last.values()) // 2))
        s['voyages'].append(int(getattr(self, '_voyages', 0)))
        s['lost_voyages'].append(int(getattr(self, '_lost', 0)))
        s['births'].append(float(c['births'].sum()))
        s['deaths'].append(float(c['deaths'].sum()))
        s['range_km'].append(float(max(self._range(int(g)) for g in idx)))
        s['farmed_km2'].append(float(self.farmed.sum()))
        self.deaths_age.append(c['deaths'].sum(axis=0))
        self.pop_age.append(c['ages_before'].sum(axis=0))
        if self.year % self.snap_every == 0:
            live = idx[self.alive[idx]]
            self.snaps.append(dict(year=self.year, groups=[dict(
                id=int(g), region=int(self.region[g]), island=int(self.reg['island'][self.region[g]]),
                pop=int(self.ages[g].sum()), techs=[TK[t] for t in np.nonzero(self.skill[g] > 0)[0]],
                boats=round(float(self.boats[g]), 1), houses=round(float(self.houses[g]), 1),
                parent=int(self.parent[g])) for g in live],
                regions={int(r): dict(forest=round(float(self.forest[r] / max(self.forest0[r], 1e-9)), 3),
                                      bigtree=round(float(self.bigtree[r] / max(self.bigtree0[r], 1e-9)), 3),
                                      farmed_km2=round(float(self.farmed[r]), 2),
                                      fish=round(float(self.S['fish'][r] / max(self.K['fish'][r], 1e-9)), 3))
                         for r in np.unique(self.region[live])}))

    # ------------------------------------------------------------ 保存と再開
    def save(self, path):
        st = {k: v for k, v in self.__dict__.items() if k != 'w'}
        with open(path, 'wb') as f:
            pickle.dump(st, f)

    @classmethod
    def load(cls, path, world):
        obj = cls.__new__(cls)
        with open(path, 'rb') as f:
            obj.__dict__.update(pickle.load(f))
        obj.w = world
        return obj

    def run(self, until=None):
        until = self.years if until is None else until
        while self.year < until:
            self.step()
        return self


def solve_effort(e1, C, target, L):
    """取れ高の限界がそろうように、取り方ごとの労働を決める。
    取り方 a の取れ高は C(1-exp(-E e1/C))。必要量 target を満たすか、労働 L を使い切るまで"""
    eps = 1e-12
    act = (C > eps) & (e1 > eps)
    e1s = np.where(act, e1, eps)
    Cs = np.where(act, C, 0)

    def F(lam):
        return np.sum(np.where(act & (e1s > lam[:, None]), Cs * (1 - lam[:, None] / e1s), 0), axis=1)

    def Eff(lam):
        return np.sum(np.where(act & (e1s > lam[:, None]), Cs / e1s * np.log(e1s / lam[:, None]), 0), axis=1)

    n = len(target)
    hi = np.log(np.maximum(e1s.max(axis=1), 1e-9))
    lo = np.full(n, math.log(1e-9))
    a, b = lo.copy(), hi.copy()
    for _ in range(40):
        m = (a + b) / 2
        too_much = F(np.exp(m)) > target
        a = np.where(too_much, m, a)
        b = np.where(too_much, b, m)
    lam1 = np.exp(a)          # 必要量に届く側
    a, b = lo.copy(), hi.copy()
    for _ in range(40):
        m = (a + b) / 2
        over = Eff(np.exp(m)) > L
        a = np.where(over, m, a)
        b = np.where(over, b, m)
    lam2 = np.exp(b)          # 労働を使いすぎない側
    lam = np.maximum(lam1, lam2)
    lam = np.where(target <= 0, np.exp(hi) * 1.01, lam)
    on = act & (e1s > lam[:, None])
    H = np.where(on, Cs * (1 - lam[:, None] / e1s), 0)
    E = np.where(on, Cs / e1s * np.log(e1s / lam[:, None]), 0)
    return H, E
