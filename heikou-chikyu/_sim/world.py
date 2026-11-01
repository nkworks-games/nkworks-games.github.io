"""並行地球 第1回「地球の99％が海だったら」：惑星と8つの地形

- 惑星は地球と同じ大きさの球（半径 6,371km）。海面は標高 0m。
- 陸地は全球の表面積のちょうど 1％（約 510万km²）。島の面積は球面上で正確に計算し、
  格子で数え直して確かめる（許容誤差は陸地面積の ±1％）。
- 4つの系統 × 2つの地図 = 8地形。どの地形も陸地の総面積は同じ。
- 島の中は、約 4,000km² ごとの「地域」に分ける（小さな島は島全体で1地域）。
  計算は地域ごとに資源・水・土地を持つ。

座標：緯度・経度（度）。島の形は、中心から見た方位（北から時計回り）ごとの半径（km）で持つ。
"""
import hashlib
import math

import numpy as np

R_KM = 6371.0
SPHERE_KM2 = 4 * math.pi * R_KM ** 2
LAND_FRACTION = 0.01
LAND_KM2 = SPHERE_KM2 * LAND_FRACTION
AREA_TOLERANCE = 0.01          # 格子で数え直したときの許容誤差（陸地面積に対する割合）
NTH = 360                      # 島の形を持つ方位の数
REGION_KM2 = 4000.0            # 地域の大きさの目安
SPLIT_KM2 = 6000.0             # これより大きい島は地域に分ける

TERRAINS = {
    'C1': ('大きな陸地へ集中', 'ひとつの大きな島'),
    'C2': ('大きな陸地へ集中', 'ふたつの大きな島'),
    'A1': ('近接した群島', 'ひとつの大きな群島'),
    'A2': ('近接した群島', '三つの群島'),
    'S1': ('飛び石状の島々', 'ひと続きの飛び石'),
    'S2': ('飛び石状の島々', '枝分かれする飛び石'),
    'R1': ('遠く離れた小島', '一様に散らばる小島'),
    'R2': ('遠く離れた小島', '小さな島の集まりが遠く散らばる'),
}

KINDS = ('continental', 'volcanic_high', 'volcanic_old', 'coral')
KIND_JA = {'continental': '大陸性の島', 'volcanic_high': '高い火山島', 'volcanic_old': '古い火山島', 'coral': '低いサンゴ島'}


def rng_for(*parts):
    key = ':'.join(str(p) for p in ('heikou-world-v1',) + parts)
    return np.random.default_rng(int(hashlib.sha256(key.encode()).hexdigest()[:16], 16))


# ---------------------------------------------------------------- 球面の道具

def xyz(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=-1)


def gc_dist(lat1, lon1, lat2, lon2):
    """大円距離（km）"""
    a, b = xyz(lat1, lon1), xyz(lat2, lon2)
    cr = np.linalg.norm(np.cross(a, b), axis=-1)
    return R_KM * np.arctan2(cr, np.sum(a * b, axis=-1))


def bearing(lat1, lon1, lat2, lon2):
    """1 から 2 への方位（ラジアン、北0・時計回り、0〜2π）"""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    y = np.sin(dl) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return np.mod(np.arctan2(y, x), 2 * math.pi)


def destination(lat, lon, brg, dist_km):
    p1, l1 = np.radians(lat), np.radians(lon)
    d = np.asarray(dist_km) / R_KM
    p2 = np.arcsin(np.sin(p1) * np.cos(d) + np.cos(p1) * np.sin(d) * np.cos(brg))
    l2 = l1 + np.arctan2(np.sin(brg) * np.sin(d) * np.cos(p1), np.cos(d) - np.sin(p1) * np.sin(p2))
    return np.degrees(p2), (np.degrees(l2) + 540) % 360 - 180


def random_on_sphere(rng, n, max_lat=90.0):
    """球面上に一様（|緯度| <= max_lat）"""
    s = math.sin(math.radians(max_lat))
    z = rng.uniform(-s, s, n)
    return np.degrees(np.arcsin(z)), rng.uniform(-180, 180, n)


def random_in_cap(rng, lat0, lon0, radius_km, n):
    """中心から radius_km 以内の円の中に一様"""
    d = radius_km / R_KM
    u = rng.uniform(0, 1, n)
    dist = np.arccos(1 - u * (1 - math.cos(d))) * R_KM
    return destination(lat0, lon0, rng.uniform(0, 2 * math.pi, n), dist)


def interp_rho(rho, th):
    """方位 th（ラジアン）での島の半径。rho は (NTH,) か (n, NTH)"""
    f = np.mod(th, 2 * math.pi) / (2 * math.pi) * NTH
    i0 = np.floor(f).astype(int) % NTH
    i1 = (i0 + 1) % NTH
    t = f - np.floor(f)
    if rho.ndim == 1:
        return rho[i0] * (1 - t) + rho[i1] * t
    idx = np.arange(rho.shape[0])[:, None] if np.ndim(th) == 2 else np.arange(rho.shape[0])
    return rho[idx, i0] * (1 - t) + rho[idx, i1] * t


# ---------------------------------------------------------------- 島の形と面積

THETA = np.linspace(0, 2 * math.pi, NTH, endpoint=False)


def shapes(rng, n, aspect=(0.45, 1.0), rough=1.0):
    """形だけ（大きさ1）を n 個。細長さ・向き・海岸の凹凸を乱数で"""
    eps = rng.uniform(*aspect, n)
    alpha = rng.uniform(0, math.pi, n)
    d = THETA[None, :] - alpha[:, None]
    base = 1 / np.sqrt(np.cos(d) ** 2 + (np.sin(d) / eps[:, None]) ** 2)
    noise = np.zeros((n, NTH))
    for k in range(2, 17):
        amp = (0.22 / k ** 0.9 if k <= 7 else 0.05 / k ** 0.5) * rough
        a = rng.normal(0, amp, n)
        ph = rng.uniform(0, 2 * math.pi, n)
        noise += a[:, None] * np.cos(k * THETA[None, :] - ph[:, None])
    return base * np.exp(noise)


def sphere_area(rho):
    """方位ごとの半径（km）から、球面上の面積（km²）"""
    return R_KM ** 2 * np.sum(1 - np.cos(rho / R_KM), axis=-1) * (2 * math.pi / NTH)


def scale_to_area(u, area):
    """形 u を、球面上の面積が area になる大きさにする"""
    lo = np.zeros(len(area))
    hi = np.full(len(area), math.pi * R_KM * 0.45) / u.max(axis=1)
    for _ in range(60):
        mid = (lo + hi) / 2
        big = sphere_area(u * mid[:, None]) > area
        hi = np.where(big, mid, hi)
        lo = np.where(big, lo, mid)
    return u * ((lo + hi) / 2)[:, None]


def perimeter(rho):
    x, y = rho * np.sin(THETA), rho * np.cos(THETA)
    dx = np.roll(x, -1, axis=-1) - x
    dy = np.roll(y, -1, axis=-1) - y
    return np.sum(np.hypot(dx, dy), axis=-1)


# ---------------------------------------------------------------- 置き場所（重ならないように）

class Placer:
    """置いた島を覚えておき、新しい島が重ならないか調べる。
    まず外接円で大まかに調べ、近いときは島の輪郭（36方位）で確かめる"""

    def __init__(self, cell_deg=4.0):
        self.cell = cell_deg
        self.big = []
        self.buckets = {}

    def _key(self, lat, lon):
        return (int(math.floor((lat + 90) / self.cell)), int(math.floor((lon + 180) / self.cell)))

    def _near(self, lat, lon, r, gap):
        out = list(self.big)
        span = (r + 400 + gap) / 111.2
        nlat = int(span / self.cell) + 1
        coslat = max(0.05, math.cos(math.radians(lat)))
        nlon = min(int(span / coslat / self.cell) + 1, int(360 / self.cell))
        ki, kj = self._key(lat, lon)
        ncol = int(360 / self.cell)
        for di in range(-nlat, nlat + 1):
            for dj in range(-nlon, nlon + 1):
                out.extend(self.buckets.get((ki + di, (kj + dj) % ncol), ()))
        return out

    def fits(self, lat, lon, rho, gap):
        r = float(rho.max())
        for (la, lo, rb, rho_b) in self._near(lat, lon, r, gap):
            d = float(gc_dist(lat, lon, la, lo))
            if d >= r + rb + gap:
                continue
            if d < 1e-6:
                return False
            # 輪郭どうし：片方の輪郭の点が、もう片方（gap の分ふくらませた）の内側にないか
            for (a_la, a_lo, a_rho, b_la, b_lo, b_rho) in ((lat, lon, rho, la, lo, rho_b), (la, lo, rho_b, lat, lon, rho)):
                th = THETA[::10]
                pla, plo = destination(a_la, a_lo, th, a_rho[::10])
                dd = gc_dist(b_la, b_lo, pla, plo)
                bb = bearing(b_la, b_lo, pla, plo)
                if np.any(dd < interp_rho(b_rho, bb) + gap):
                    return False
            if interp_rho(rho, bearing(lat, lon, la, lo)) + interp_rho(rho_b, bearing(la, lo, lat, lon)) + gap > d:
                return False
        return True

    def add(self, lat, lon, rho):
        r = float(rho.max())
        if r > 400:
            self.big.append((lat, lon, r, rho))
        else:
            self.buckets.setdefault(self._key(lat, lon), []).append((lat, lon, r, rho))


# ---------------------------------------------------------------- 8つの地形の島の並べ方

def lognormal_areas(rng, n, median, sigma, lo=3.0, hi=None):
    a = np.exp(rng.normal(math.log(median), sigma, n))
    a = np.maximum(a, lo)
    if hi:
        a = np.minimum(a, hi)
    return a


def place_scatter(rng, placer, rho, sampler, gap, tries=400):
    """rho の大きい順に、sampler() の場所へ重ならないように置く"""
    n = len(rho)
    rmax = rho.max(axis=1)
    lat = np.full(n, np.nan)
    lon = np.full(n, np.nan)
    for i in np.argsort(-rmax):
        for _ in range(tries):
            la, lo = sampler()
            if placer.fits(la, lo, rho[i], gap):
                placer.add(la, lo, rho[i])
                lat[i], lon[i] = la, lo
                break
    return lat, lon


def place_chain(rng, placer, rho, start, heading, long_gaps, gap_median, turn=0.08, lateral=0.0):
    """飛び石：start から heading の向きへ、島を順に並べる。long_gaps は {何番目の後: 長い海の幅km}"""
    n = len(rho)
    lat = np.full(n, np.nan)
    lon = np.full(n, np.nan)
    la, lo = start
    h = heading
    prev = None
    for i in range(n):
        for attempt in range(60):
            hh = h + rng.normal(0, turn)
            if prev is None:
                cla, clo = la, lo
            else:
                g = long_gaps.get(i, gap_median * math.exp(rng.normal(0, 0.6)))
                rp = interp_rho(rho[prev], hh)
                rn = interp_rho(rho[i], hh + math.pi)
                cla, clo = destination(lat[prev], lon[prev], hh, rp + g + rn)
                if lateral:
                    off = rng.normal(0, lateral)
                    cla, clo = destination(cla, clo, hh + math.pi / 2, off)
            if abs(cla) < 72 and placer.fits(cla, clo, rho[i], 4.0 if prev is None else 2.0):
                placer.add(cla, clo, rho[i])
                lat[i], lon[i] = cla, clo
                if prev is not None:
                    h = float(bearing(lat[prev], lon[prev], cla, clo))
                prev = i
                break
    return lat, lon


def build_layout(tid):
    """地形 tid の島の一覧（面積・形・中心）"""
    rng = rng_for(tid, 'layout')
    placer = Placer()
    groups = []  # (areas, aspect, sampler/chain)

    def finish(areas_list):
        areas = np.concatenate(areas_list)
        return areas * (LAND_KM2 / areas.sum())

    if tid in ('C1', 'C2'):
        if tid == 'C1':
            big = np.array([3.55e6])
            mids = rng.dirichlet(np.ones(5)) * 0.95e6
            smalls = lognormal_areas(rng, 90, 2500, 1.2)
            centers = [(12.0, 20.0)]
        else:
            big = np.array([1.95e6, 1.85e6])
            mids = rng.dirichlet(np.ones(4)) * 0.8e6
            smalls = lognormal_areas(rng, 70, 2500, 1.2)
            centers = [(28.0, -40.0), (-18.0, 112.0)]
        smalls = smalls * ((LAND_KM2 - big.sum() - mids.sum()) / smalls.sum())
        areas = np.concatenate([big, mids, smalls])
        u = shapes(rng, len(areas), aspect=(0.55, 0.9))
        rho = scale_to_area(u, areas)
        lat = np.full(len(areas), np.nan)
        lon = np.full(len(areas), np.nan)
        for k, (la, lo) in enumerate(centers):
            lat[k], lon[k] = la, lo
            placer.add(la, lo, rho[k])
        nb = len(big)
        # 中くらいの島：大きな島から 600〜3,500km 離れた所
        for k in range(nb, nb + len(mids)):
            c = centers[k % nb]
            for _ in range(500):
                brg = rng.uniform(0, 2 * math.pi)
                dist = rho[k % nb].max() + rng.uniform(600, 3500)
                la, lo = destination(c[0], c[1], brg, dist)
                if abs(la) < 65 and placer.fits(la, lo, rho[k], 150):
                    placer.add(la, lo, rho[k])
                    lat[k], lon[k] = la, lo
                    break
        # 小さな島：地球のあちこち
        rest = np.arange(nb + len(mids), len(areas))
        la2, lo2 = place_scatter(rng, placer, rho[rest], lambda: tuple(np.ravel(random_on_sphere(rng, 1, 65))), 60)
        lat[rest], lon[rest] = la2, lo2
    elif tid in ('A1', 'A2'):
        if tid == 'A1':
            clusters = [((-4.0, 150.0), 3200.0, 520)]
        else:
            clusters = [((18.0, -150.0), 1850.0, 175), ((-14.0, -55.0), 1850.0, 175), ((6.0, 62.0), 1850.0, 175)]
        areas = finish([lognormal_areas(rng, n, 3500, 1.25, lo=10) for _, _, n in clusters])
        u = shapes(rng, len(areas), aspect=(0.6, 0.95), rough=0.7)
        rho = scale_to_area(u, areas)
        lat = np.full(len(areas), np.nan)
        lon = np.full(len(areas), np.nan)
        start = 0
        for (c, rad, n) in clusters:
            idx = np.arange(start, start + n)
            la2, lo2 = place_scatter(rng, placer, rho[idx],
                                     lambda c=c, rad=rad: tuple(np.ravel(random_in_cap(rng, c[0], c[1], rad, 1))), 6, tries=3000)
            lat[idx], lon[idx] = la2, lo2
            start += n
    elif tid in ('S1', 'S2'):
        if tid == 'S1':
            chains = [((-28.0, -175.0), math.radians(62), 90, {21: 320.0, 46: 560.0, 70: 900.0})]
        else:
            hub = (2.0, 10.0)
            chains = [(hub, math.radians(25), 34, {12: 420.0}),
                      (hub, math.radians(145), 34, {18: 650.0}),
                      (hub, math.radians(265), 34, {8: 300.0})]
        areas = finish([lognormal_areas(rng, n, 30000, 0.9, lo=50) for _, _, n, _ in chains])
        u = shapes(rng, len(areas), aspect=(0.4, 0.9))
        rho = scale_to_area(u, areas)
        lat = np.full(len(areas), np.nan)
        lon = np.full(len(areas), np.nan)
        start = 0
        for k, (st, hd, n, gaps) in enumerate(chains):
            idx = np.arange(start, start + n)
            if tid == 'S2' and k > 0:
                # 枝は、真ん中の島から少し離れて始める
                st = destination(hub[0], hub[1], hd, rho[0].max() + 60.0)
                st = (float(st[0]), float(st[1]))
            la2, lo2 = place_chain(rng, placer, rho[idx], st, hd, gaps, 45.0, turn=0.10, lateral=25.0)
            lat[idx], lon[idx] = la2, lo2
            start += n
    else:
        if tid == 'R1':
            areas = finish([lognormal_areas(rng, 2600, 900, 1.2, lo=3)])
            u = shapes(rng, len(areas), aspect=(0.4, 1.0))
            rho = scale_to_area(u, areas)
            lat, lon = place_scatter(rng, placer, rho, lambda: tuple(np.ravel(random_on_sphere(rng, 1, 65))), 60)
        else:
            nclu = 320
            sizes = rng.integers(3, 9, nclu)
            areas = finish([lognormal_areas(rng, int(sizes.sum()), 1300, 1.1, lo=3)])
            u = shapes(rng, len(areas), aspect=(0.4, 1.0))
            rho = scale_to_area(u, areas)
            lat = np.full(len(areas), np.nan)
            lon = np.full(len(areas), np.nan)
            cl_lat, cl_lon = [], []
            # 集まりの中心どうしは 700km 以上離す
            while len(cl_lat) < nclu:
                la, lo = random_on_sphere(rng, 1, 62)
                la, lo = float(la[0]), float(lo[0])
                if not cl_lat or np.min(gc_dist(la, lo, np.array(cl_lat), np.array(cl_lon))) > 700:
                    cl_lat.append(la)
                    cl_lon.append(lo)
            start = 0
            for c in range(nclu):
                idx = np.arange(start, start + sizes[c])
                la2, lo2 = place_scatter(rng, placer, rho[idx],
                                         lambda c=c: tuple(np.ravel(random_in_cap(rng, cl_lat[c], cl_lon[c], 140.0, 1))), 8, tries=600)
                lat[idx], lon[idx] = la2, lo2
                start += sizes[c]
    # 決めた場所に置けなかった島は、面積を保つために、地球のどこかへ離して置く
    miss = np.nonzero(np.isnan(lat))[0]
    if len(miss):
        la2, lo2 = place_scatter(rng, placer, rho[miss], lambda: tuple(np.ravel(random_on_sphere(rng, 1, 65))), 60)
        lat[miss], lon[miss] = la2, lo2
    ok = ~np.isnan(lat)
    return dict(area=np.asarray(areas)[ok], rho=rho[ok], lat=lat[ok], lon=lon[ok],
                relocated=int(len(miss)), dropped=int((~ok).sum()))


# ---------------------------------------------------------------- 島の性質

def climate(lat, rng=None, n=None):
    """年平均気温（℃）と年降水量（mm）。海の多い星なので、気温の差は地球より穏やか"""
    a = np.abs(lat)
    T = 27.5 - 0.0058 * a ** 2
    P = 900 + 1500 * np.exp(-(a / 11) ** 2) + 750 * np.exp(-((a - 50) / 12) ** 2) - 350 * np.exp(-((a - 25) / 7) ** 2)
    P = np.maximum(P, 250)
    if rng is not None:
        T = T + rng.normal(0, 0.8, n)
        P = P * np.exp(rng.normal(0, 0.18, n))
    return T, P


def productivity(T, P):
    """陸の生産力の目安（0〜1.2）"""
    fT = np.clip(T / 22.0, 0, 1.1)
    fP = np.clip(P / 1800.0, 0, 1.25)
    return fT * fP ** 0.8


def marine_productivity(lat):
    a = np.abs(lat)
    return np.where(a < 22, 0.9, np.where(a < 40, 1.0, np.where(a < 62, 1.4, 1.0)))


def island_props(tid, lay):
    rng = rng_for(tid, 'props')
    n = len(lay['area'])
    area, lat = lay['area'], lay['lat']
    r = rng.uniform(0, 1, n)
    trop = np.abs(lat) < 30
    kind = np.empty(n, dtype=object)
    for i in range(n):
        a = area[i]
        if a >= 150e3:
            kind[i] = 'continental' if r[i] < 0.85 else 'volcanic_high'
        elif a >= 5e3:
            kind[i] = 'volcanic_high' if r[i] < 0.5 else ('volcanic_old' if r[i] < 0.85 else 'continental')
        elif a >= 300:
            pc = 0.30 if trop[i] else 0.04
            kind[i] = 'coral' if r[i] < pc else ('volcanic_high' if r[i] < pc + 0.35 else 'volcanic_old')
        else:
            kind[i] = 'coral' if (trop[i] and r[i] < 0.6) else 'volcanic_old'
    r2 = rng.uniform(0, 1, n)
    hmax = np.where(kind == 'continental', np.clip(600 + 2600 * r2 * (area / 1e6) ** 0.2, 300, 4500),
           np.where(kind == 'volcanic_high', np.clip(350 + 1800 * r2 ** 0.7 * (area / 1e4) ** 0.25, 300, 4000),
           np.where(kind == 'volcanic_old', 80 + 520 * r2, 3 + 5 * r2)))
    T, P = climate(lat, rng, n)
    P = P * np.where(hmax > 600, 1.25, np.where(kind == 'coral', 0.85, 1.0))
    coast = perimeter(lay['rho']) * 1.6
    shelf_w = np.select([kind == 'coral', kind == 'volcanic_high', kind == 'volcanic_old'], [8.0, 2.0, 4.0], 15.0)
    r3 = rng.uniform(0, 1, (n, 6))
    res = dict(
        flake_stone=kind != 'coral',
        # 斧の材料：火山島の玄武岩など。サンゴ島では大きな貝の殻で斧を作れる
        adze_stone=(kind == 'volcanic_high') | (kind == 'volcanic_old') | (kind == 'coral') | ((kind == 'continental') & (r3[:, 0] < 0.7)),
        clay=((kind == 'continental') & (r3[:, 1] < 0.9)) | (((kind == 'volcanic_high') | (kind == 'volcanic_old')) & (r3[:, 1] < 0.55)),
        copper=(kind == 'continental') & (area > 50e3) & (r3[:, 2] < 0.4),
        root_crop=(T > 18) & (P > 1000) & (((kind != 'coral') & (area > 150) & (r3[:, 3] < 0.7)) | ((kind == 'coral') & (r3[:, 3] < 0.35))),
        grain=(T > 8) & (T < 25) & (P > 400) & (P < 1800) & (area > 20e3) & (r3[:, 4] < 0.6),
    )
    return dict(kind=kind, hmax=hmax, T=T, P=P, coast_km=coast, shelf_w=shelf_w, res=res)


# ---------------------------------------------------------------- 地域に分ける

def local_points(rho, lat0, lon0, spacing):
    """島の中の点（島の中心を原点とする平面、km）と、海岸の帯かどうか"""
    rmax = rho.max()
    xs = np.arange(-rmax, rmax + spacing, spacing)
    X, Y = np.meshgrid(xs, xs)
    X, Y = X.ravel(), Y.ravel()
    d = np.hypot(X, Y)
    th = np.mod(np.arctan2(X, Y), 2 * math.pi)
    edge = interp_rho(rho, th)
    inside = d < edge
    return X[inside], Y[inside], d[inside] / np.maximum(edge[inside], 1e-6), (edge[inside] - d[inside])


def to_latlon(lat0, lon0, x, y):
    return destination(lat0, lon0, np.mod(np.arctan2(x, y), 2 * math.pi), np.hypot(x, y))


def regions_for_island(i, lay, props, rng):
    area = lay['area'][i]
    rho = lay['rho'][i]
    lat0, lon0 = lay['lat'][i], lay['lon'][i]
    kind = props['kind'][i]
    hmax = props['hmax'][i]
    out = []
    if area <= SPLIT_KM2:
        low = {'coral': 1.0, 'volcanic_high': 0.3, 'volcanic_old': 0.6, 'continental': 0.5}[kind]
        out.append(dict(lat=lat0, lon=lon0, area=area, coast_km=props['coast_km'][i], coastal=True,
                        lowland=low, elev=hmax * 0.35, cells=[]))
        return out
    spacing = max(3.0, math.sqrt(area / 40000))
    X, Y, frac, inset = local_points(rho, lat0, lon0, spacing)
    h = math.sqrt(2 * REGION_KM2 / math.sqrt(3))
    rmax = rho.max()
    cs = []
    for row, y in enumerate(np.arange(-rmax, rmax + h, h * math.sqrt(3) / 2)):
        off = (h / 2) if row % 2 else 0.0
        for x in np.arange(-rmax + off, rmax + h, h):
            cs.append((x, y))
    C = np.array(cs)
    for it in range(5):
        lab = np.empty(len(X), int)
        for s in range(0, len(X), 4000):
            d2 = (X[s:s + 4000, None] - C[None, :, 0]) ** 2 + (Y[s:s + 4000, None] - C[None, :, 1]) ** 2
            lab[s:s + 4000] = np.argmin(d2, axis=1)
        cnt = np.bincount(lab, minlength=len(C))
        keep = cnt >= 0.3 * (REGION_KM2 / spacing ** 2)
        if keep.all() or it == 4:
            break
        C = C[keep]
    coastal_pt = inset < 12.0
    n_coast_all = max(1, coastal_pt.sum())
    elev_pt = hmax * (1 - frac) ** 1.2
    for c in range(len(C)):
        m = lab == c
        if not m.any():
            continue
        cx, cy = X[m].mean(), Y[m].mean()
        la, lo = to_latlon(lat0, lon0, np.array([cx]), np.array([cy]))
        nc = coastal_pt[m].sum()
        out.append(dict(lat=float(la[0]), lon=float(lo[0]), area=area * cnt[c] / len(X),
                        coast_km=props['coast_km'][i] * nc / n_coast_all, coastal=bool(nc > 0),
                        lowland=float(np.mean(elev_pt[m] < 200)), elev=float(np.mean(elev_pt[m])),
                        cells=[cx, cy]))
    return out


# ---------------------------------------------------------------- 世界をまとめて作る

def build_world(tid):
    lay = build_layout(tid)
    props = island_props(tid, lay)
    rng = rng_for(tid, 'regions')
    n = len(lay['area'])
    regs = []
    island_regions = []
    for i in range(n):
        rs = regions_for_island(i, lay, props, rng)
        ids = []
        for r in rs:
            r['island'] = i
            ids.append(len(regs))
            regs.append(r)
        island_regions.append(ids)
    # 地域の性質を配列に
    R = len(regs)
    g = lambda k: np.array([r[k] for r in regs], dtype=float)
    isl = np.array([r['island'] for r in regs])
    reg = dict(island=isl, lat=g('lat'), lon=g('lon'), area=g('area'), coast_km=g('coast_km'),
               coastal=np.array([r['coastal'] for r in regs]), lowland=g('lowland'), elev=g('elev'))
    T, P = climate(reg['lat'])
    # 島ごとのむらを地域にも
    T = T + (props['T'][isl] - climate(lay['lat'])[0][isl])
    P = P * (props['P'][isl] / climate(lay['lat'])[1][isl])
    reg['T'], reg['P'] = T, P
    kind = props['kind'][isl]
    prod = productivity(T, P)
    coral = kind == 'coral'
    reg['prod'] = prod
    reg['shelf_km2'] = reg['coast_km'] * props['shelf_w'][isl] * 0.5
    mp = marine_productivity(reg['lat']) * np.where(coral, 1.2, 1.0)
    reg['marine'] = mp
    # 持続的にとれる食べ物の量（1年に何人分か：FU/年）
    reg['msy_plant'] = reg['area'] * 0.35 * prod * np.where(coral, 0.5, 1.0)
    reg['msy_game'] = reg['area'] * 0.12 * prod * np.where(coral, 0.15, 1.0)
    reg['msy_shell'] = reg['coast_km'] * 0.8 * mp
    reg['msy_fish'] = reg['shelf_km2'] * 0.6 * mp
    reg['msy_offshore'] = reg['coast_km'] * 3.0 * mp
    # 森（km²）と、舟や大きな家に使える大木（本）
    forest_frac = np.clip(prod, 0, 1) * np.where(coral, 0.6, 0.9) * (T > 2)
    reg['forest_km2'] = reg['area'] * forest_frac
    reg['bigtree'] = reg['forest_km2'] * 20 * np.clip(prod - 0.25, 0, 1) * np.where(coral, 0.1, 1.0) * (T > 10)
    # 畑にできる土地（km²）と土の良さ
    soil = np.select([kind == 'volcanic_high', kind == 'volcanic_old', kind == 'continental'], [1.0, 0.75, 0.8], 0.35)
    reg['soil'] = soil
    reg['arable_km2'] = reg['area'] * reg['lowland'] * 0.5 * soil * (T > 6) * (P > 400)
    # 淡水（何人分か）。高い島は川や泉、低い島は地下の淡水レンズ（井戸が要る）と雨水（器が要る）
    hm = props['hmax'][isl]
    reg['water_surface'] = np.where(hm > 150, reg['area'] * reg['P'] * 0.4 * 0.01 * 1e3 / 1.8 * np.clip((hm - 150) / 600, 0.1, 1), 0)
    reg['water_lens'] = np.where(hm <= 150, reg['area'] * reg['P'] * 0.3 * 0.002 * 1e3 / 1.8, 0)
    reg['water_plant'] = np.where(coral, reg['area'] * 8.0, reg['area'] * 2.0)
    for k, v in props['res'].items():
        reg['res_' + k] = v[isl].copy()
    # 銅の鉱石は、大きな島の一部の地域にだけ
    rr = rng.uniform(0, 1, R)
    reg['res_copper'] = reg['res_copper'] & (rr < 0.08)
    # 地域どうしのつながり（同じ島の隣どうし）
    adj = [[] for _ in range(R)]
    for i, ids in enumerate(island_regions):
        if len(ids) < 2:
            continue
        la, lo = reg['lat'][ids], reg['lon'][ids]
        for a_k, a in enumerate(ids):
            d = gc_dist(la[a_k], lo[a_k], la, lo)
            for b_k in np.nonzero((d > 0) & (d < 1.5 * math.sqrt(2 * REGION_KM2 / math.sqrt(3)) * 1.15))[0]:
                adj[a].append(ids[b_k])
    links = sea_links(lay, props)
    world = dict(tid=tid, family=TERRAINS[tid][0], name=TERRAINS[tid][1], lay=lay, props=props,
                 reg=reg, island_regions=island_regions, adj=adj, links=links)
    return world


def sea_links(lay, props, max_gap=2500.0):
    """島どうしの海の幅（海岸から海岸、km）。近い組だけ"""
    lat, lon, rho = lay['lat'], lay['lon'], lay['rho']
    n = len(lat)
    rmax = rho.max(axis=1)
    V = xyz(lat, lon)
    out_i, out_j, out_g = [], [], []
    for s in range(0, n, 500):
        dot = np.clip(V[s:s + 500] @ V.T, -1, 1)
        D = np.arccos(dot) * R_KM
        cand = np.argwhere(D < rmax[s:s + 500, None] + rmax[None, :] + max_gap)
        cand = cand[cand[:, 0] + s < cand[:, 1]]
        if not len(cand):
            continue
        a = cand[:, 0] + s
        b = cand[:, 1]
        bab = bearing(lat[a], lon[a], lat[b], lon[b])
        bba = bearing(lat[b], lon[b], lat[a], lon[a])
        gap = D[cand[:, 0], cand[:, 1]] - interp_rho(rho[a], bab) - interp_rho(rho[b], bba)
        ok = gap < max_gap
        out_i.append(a[ok])
        out_j.append(b[ok])
        out_g.append(np.maximum(gap[ok], 0.5))
    i = np.concatenate(out_i) if out_i else np.zeros(0, int)
    j = np.concatenate(out_j) if out_j else np.zeros(0, int)
    g = np.concatenate(out_g) if out_g else np.zeros(0)
    # 見える距離：見る人の目の高さ 20m と、相手の島の高さ。高い島は雲の帽子でさらに遠くから分かる
    hm = props['hmax']
    vis = lambda h: 3.57 * (math.sqrt(20) + np.sqrt(h)) + np.where(h > 500, 40.0, 0.0)
    return dict(i=i, j=j, gap=g, vis_ij=vis(hm[j]), vis_ji=vis(hm[i]))


# ---------------------------------------------------------------- 面積の確認（格子で数え直す）

def raster_area(lay, res_deg=0.05):
    """各島の範囲の格子（res_deg 度）で陸のセルを数え、球面上の面積を足す"""
    total = 0.0
    for k in range(len(lay['area'])):
        lat0, lon0, rho = lay['lat'][k], lay['lon'][k], lay['rho'][k]
        rmax = rho.max()
        dlat = rmax / 111.2 + 2 * res_deg
        la0, la1 = max(-90, lat0 - dlat), min(90, lat0 + dlat)
        coslat = math.cos(math.radians(min(89.0, max(abs(la0), abs(la1)))))
        dlon = min(180.0, rmax / (111.2 * max(coslat, 0.02)) + 2 * res_deg)
        lats = np.arange(math.floor(la0 / res_deg) * res_deg, la1 + res_deg, res_deg) + res_deg / 2
        lats = lats[(lats > -90) & (lats < 90)]
        lons = np.arange(math.floor((lon0 - dlon) / res_deg) * res_deg, lon0 + dlon + res_deg, res_deg) + res_deg / 2
        if dlon >= 180:
            lons = np.arange(-180, 180, res_deg) + res_deg / 2
        LA, LO = np.meshgrid(lats, lons, indexing='ij')
        d = gc_dist(lat0, lon0, LA, LO)
        th = bearing(lat0, lon0, LA, LO)
        inside = d < interp_rho(rho, th)
        cell = R_KM ** 2 * math.radians(res_deg) * (np.sin(np.radians(LA + res_deg / 2)) - np.sin(np.radians(LA - res_deg / 2)))
        total += float(np.sum(cell * inside))
    return total


def summary(world):
    """地形ごとの特徴の記録（仕様書3章の項目）"""
    lay, props, reg, links = world['lay'], world['props'], world['reg'], world['links']
    area = lay['area']
    n = len(area)
    # 島ごとの、いちばん近い島までの海の幅
    near = np.full(n, np.inf)
    np.minimum.at(near, links['i'], links['gap'])
    np.minimum.at(near, links['j'], links['gap'])
    q = lambda v, p=(10, 50, 90): [float(np.percentile(v[np.isfinite(v)], x)) if np.isfinite(v).any() else None for x in p]
    kinds = {KIND_JA[k]: int(np.sum(props['kind'] == k)) for k in KINDS}
    hab = (reg['msy_plant'] + reg['msy_game'] + reg['msy_shell'] + reg['msy_fish'])
    return {
        '地形': world['tid'], '系統': world['family'], '名前': world['name'],
        '島の数': int(n), '地域の数': int(len(reg['area'])),
        '決めた場所に置けず離して置いた島': int(lay['relocated']), '置けなかった島': int(lay['dropped']),
        '陸地の面積km2（球面で計算）': float(area.sum()),
        '陸地の割合％': float(area.sum() / SPHERE_KM2 * 100),
        '島の面積km2（10・50・90％点）': q(area),
        '最大の島km2': float(area.max()), '上位5島の割合％': float(np.sort(area)[-5:].sum() / area.sum() * 100),
        'いちばん近い島までの海の幅km（10・50・90％点）': q(near),
        '15km以内に島がある島の割合％': float(np.mean(near <= 15) * 100),
        '150km以内に島がある島の割合％': float(np.mean(near <= 150) * 100),
        '島の種類': kinds,
        '最高標高m（10・50・90％点）': q(props['hmax']),
        '平地の割合（面積で重み）': float(np.sum(reg['lowland'] * reg['area']) / reg['area'].sum()),
        '海岸線km': float(props['coast_km'].sum()),
        '浅い海km2': float(reg['shelf_km2'].sum()),
        '川や泉のある地域の割合％': float(np.mean(reg['water_surface'] > 0) * 100),
        '畑にできる土地km2': float(reg['arable_km2'].sum()),
        '森km2': float(reg['forest_km2'].sum()),
        '資源のある島の数': {k: int(v.sum()) for k, v in props['res'].items()},
        '採集と漁で暮らせる人数の目安（地域の合計）': float(hab.sum()),
    }
