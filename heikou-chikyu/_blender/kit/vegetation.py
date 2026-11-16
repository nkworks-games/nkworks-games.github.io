"""地球の基礎キット：植物（木・ヤシ・低木・草・芋・潮麦）

どの関数も、型となるオブジェクト（原点が根元、z が上、長さは m）を1つ作って返す。
場面では、これを散らばらせる（scatter）か、そのまま置く。
葉と樹皮には UV を付けてあり、材質（materials.leaf / bark / grass）が葉脈や樹皮の向きに使う。
"""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

from . import materials as M
from .util import link_object, stream


class Builder:
    """面ごとに材質の番号と UV を持たせながら、メッシュを組み立てる"""

    def __init__(self):
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new('UVMap')

    def face(self, verts, uvs, mat=0):
        f = self.bm.faces.new(verts)
        f.material_index = mat
        for loop, uv in zip(f.loops, uvs):
            loop[self.uv].uv = uv
        return f

    def tube(self, path, radii, segs=7, mat=0, cap=False):
        """道すじに沿った先細りの筒。UV の u は周り、v は長さ（周の長さで割って、模様の縦横をそろえる）"""
        rings = []
        prev_u = None
        vs = [0.0]
        for k in range(1, len(path)):
            vs.append(vs[-1] + (path[k] - path[k - 1]).length)
        circ = 2 * math.pi * max(radii[0], 0.01)
        for k, p in enumerate(path):
            d = path[min(k + 1, len(path) - 1)] - path[max(k - 1, 0)]
            if d.length < 1e-9:
                d = Vector((0, 0, 1))
            d.normalize()
            if prev_u is None:
                u = d.orthogonal().normalized()
            else:
                u = prev_u - d * prev_u.dot(d)
                u = u.normalized() if u.length > 1e-6 else d.orthogonal().normalized()
            prev_u = u
            v = d.cross(u).normalized()
            rings.append([self.bm.verts.new(p + (u * math.cos(a) + v * math.sin(a)) * radii[k])
                          for a in np.linspace(0, 2 * math.pi, segs, endpoint=False)])
        for k in range(len(rings) - 1):
            v0, v1 = vs[k] / circ, vs[k + 1] / circ
            for s in range(segs):
                u0, u1 = s / segs, (s + 1) / segs
                self.face([rings[k][s], rings[k][(s + 1) % segs], rings[k + 1][(s + 1) % segs], rings[k + 1][s]],
                          [(u0, v0), (u1, v0), (u1, v1), (u0, v1)], mat)
        if cap and radii[-1] > 0.01:
            self.face(rings[-1], [(0.5 + 0.5 * math.cos(a), 0.5 + 0.5 * math.sin(a))
                                  for a in np.linspace(0, 2 * math.pi, segs, endpoint=False)], mat)
        return rings

    def leaf(self, base, axis, normal, length, width, mat=0, fold=0.12, droop=0.15, shape='oval'):
        """1枚の葉。base が付け根、axis が葉先の向き、normal が表の向き。
        shape：oval（卵形）、lance（細長い）、heart（芋の葉のようなハート形）"""
        a = axis.normalized()
        n = (normal - a * normal.dot(a)).normalized()
        s = a.cross(n).normalized()
        if shape == 'heart':
            prof = [(0.0, 0.0), (0.12, -0.38), (0.45, -0.50), (0.78, -0.32), (1.0, 0.0), (0.78, 0.32), (0.45, 0.50), (0.12, 0.38)]
        elif shape == 'lance':
            prof = [(0.0, 0.0), (0.25, -0.42), (0.6, -0.36), (1.0, 0.0), (0.6, 0.36), (0.25, 0.42)]
        else:
            prof = [(0.0, 0.0), (0.3, -0.5), (0.7, -0.38), (1.0, 0.0), (0.7, 0.38), (0.3, 0.5)]
        pts = []
        for t, w in prof:
            p = base + a * (t * length) + s * (w * width) + n * (fold * abs(w) * width - droop * (t ** 2) * length)
            pts.append(p)
        mid = base + a * (0.5 * length) + n * (-droop * 0.25 * length)
        vm = self.bm.verts.new(mid)
        vv = [self.bm.verts.new(p) for p in pts]
        uvs = [(0.5 + w, t) for t, w in prof]
        for k in range(len(vv)):
            k2 = (k + 1) % len(vv)
            self.face([vm, vv[k], vv[k2]], [(0.5, 0.5), uvs[k], uvs[k2]], mat)

    def blade(self, base, direction, length, width, segs=4, bend=0.4, twist=0.0, mat=0, side=None, taper=1.0):
        """細長い葉（草・ヤシの小葉・稲のような葉）。先へ行くほど下へしなる。UV の v は根元0→先1"""
        d = direction.normalized()
        side = (side if side is not None else d.orthogonal()).normalized()
        side = (side - d * side.dot(d)).normalized()
        prev = None
        down = Vector((0, 0, -1))
        p = base.copy()
        step = length / segs
        for k in range(segs + 1):
            t = k / segs
            w = width * (1 - taper * t ** 1.5) * 0.5 + 0.0005
            sd = side.copy()
            if twist:
                sd.rotate(Quaternion(d, twist * t))
            l, r = self.bm.verts.new(p - sd * w), self.bm.verts.new(p + sd * w)
            if prev is not None:
                self.face([prev[0], prev[1], r, l], [(0, (k - 1) / segs), (1, (k - 1) / segs), (1, t), (0, t)], mat)
            prev = (l, r)
            d = (d + down * bend / segs).normalized()
            p = p + d * step

    def finish(self, name, mats, coll=None, smooth=True):
        me = bpy.data.meshes.new(name)
        self.bm.to_mesh(me)
        self.bm.free()
        for m in mats:
            me.materials.append(m)
        if smooth:
            me.polygons.foreach_set('use_smooth', np.ones(len(me.polygons), bool))
        obj = bpy.data.objects.new(name, me)
        if coll is not False:
            link_object(obj, coll)
        return obj


# ---------------------------------------------------------------- 種類ごとの色

SPECIES = {
    # 名前: (樹皮の色2つ, 樹皮の模様, 葉の色2つ, つや, 透け, 紅葉)
    'tropical': (((0.05, 0.045, 0.035, 1), (0.12, 0.11, 0.085, 1)), 'smooth', ((0.018, 0.045, 0.010, 1), (0.055, 0.11, 0.020, 1)), 0.55, 0.25, 0.0),
    'evergreen': (((0.035, 0.03, 0.025, 1), (0.09, 0.08, 0.06, 1)), 'fissured', ((0.015, 0.040, 0.010, 1), (0.045, 0.095, 0.018, 1)), 0.6, 0.2, 0.0),
    'deciduous': (((0.06, 0.055, 0.05, 1), (0.14, 0.13, 0.11, 1)), 'smooth', ((0.035, 0.075, 0.015, 1), (0.09, 0.16, 0.03, 1)), 0.35, 0.35, 0.15),
    'pine': (((0.07, 0.045, 0.03, 1), (0.17, 0.11, 0.07, 1)), 'plates', ((0.012, 0.035, 0.015, 1), (0.035, 0.075, 0.03, 1)), 0.4, 0.2, 0.0),
    'palm': (((0.12, 0.10, 0.08, 1), (0.26, 0.23, 0.19, 1)), 'rings', ((0.03, 0.07, 0.015, 1), (0.11, 0.16, 0.035, 1)), 0.5, 0.3, 0.0),
    'shrub': (((0.06, 0.05, 0.04, 1), (0.13, 0.11, 0.08, 1)), 'smooth', ((0.02, 0.05, 0.012, 1), (0.07, 0.12, 0.025, 1)), 0.45, 0.3, 0.05),
}


def species_mats(sp):
    bark_c, bark_k, leaf_c, gloss, trans, autumn = SPECIES[sp]
    return M.bark(sp, *bark_c, kind=bark_k), M.leaf(sp, *leaf_c, gloss=gloss, translucency=trans, autumn=autumn)


# ---------------------------------------------------------------- 広葉樹・針葉樹（枝分かれで作る）

def _envelope_len(start, d, center, rad, max_len):
    """start から d の向きに進んで、楕円体（樹冠）の外へ出るまでの長さ"""
    L = 0.0
    step = max_len / 40
    while L < max_len:
        p = start + d * (L + step)
        q = p - center
        if (q.x / rad.x) ** 2 + (q.y / rad.y) ** 2 + (q.z / rad.z) ** 2 > 1.0:
            break
        L += step
    return max(L, step)


def tree(name, seed, height=12.0, crown_r=None, crown_base=0.35, species='evergreen', n_main=None,
         leaf_size=None, density=1.0, lean=0.3, buttress=False, coll=None, umbrella=False):
    """広葉樹。幹 → 太い枝 → 小枝 → 葉の房、と枝分かれさせる。
    crown_base：樹冠の下の高さ（全体の高さに対する割合）。umbrella：上の平たい傘形（熱帯の高木）"""
    rng = stream(seed, 'tree', name)
    bark_m, leaf_m = species_mats(species)
    B = Builder()
    H = height
    crown_r = crown_r or H * rng.uniform(0.32, 0.42)
    leaf_size = leaf_size or {'tropical': 0.42, 'deciduous': 0.28}.get(species, 0.30)
    zb = H * crown_base
    zc = (zb + H) / 2 if not umbrella else H * 0.78
    rad = Vector((crown_r, crown_r * rng.uniform(0.85, 1.1), (H - zb) / 2 if not umbrella else (H - zb) * 0.32))
    center = Vector((0, 0, zc))
    lean_v = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), 0)).normalized() * lean
    top = Vector((0, 0, H * (0.72 if not umbrella else 0.8))) + lean_v
    r0 = 0.10 + H * 0.016
    # 幹（根元は少し広がる）
    n = 9
    path, radii = [], []
    for k in range(n):
        t = k / (n - 1)
        p = Vector((0, 0, -0.4)).lerp(top, t) + Vector((0.18 * math.sin(3 * t + seed), 0.15 * math.cos(2.3 * t + seed), 0)) * t
        path.append(p)
        flare = (1 + (1.6 if buttress else 0.5) * math.exp(-t * 14))
        radii.append(r0 * (1.0 - 0.55 * t) * flare)
    B.tube(path, radii, segs=10, mat=0)
    if buttress:
        for k in range(rng.randint(4, 6)):
            a = k / 5 * 2 * math.pi + rng.uniform(-0.3, 0.3)
            d = Vector((math.cos(a), math.sin(a), 0))
            B.tube([Vector((0, 0, 1.8)), d * r0 * 1.6 + Vector((0, 0, 0.6)), d * r0 * 3.2 + Vector((0, 0, -0.2))],
                   [r0 * 0.35, r0 * 0.3, r0 * 0.15], segs=5, mat=0)
    # 太い枝
    n_main = n_main or rng.randint(7, 11)
    golden = math.pi * (3 - math.sqrt(5))
    clusters = []
    for i in range(n_main):
        t = (i + 0.5) / n_main
        z = zb + (top.z - zb) * (0.15 + 0.8 * t)
        base = Vector((0, 0, z)) + lean_v * (z / top.z)
        az = i * golden + rng.uniform(-0.3, 0.3)
        el = math.radians((25 if umbrella else 35) + 40 * t + rng.uniform(-8, 8))
        d = Vector((math.cos(az) * math.cos(el), math.sin(az) * math.cos(el), math.sin(el)))
        L = _envelope_len(base, d, center, rad, H) * rng.uniform(0.8, 0.95)
        pts = [base]
        dd = d.copy()
        for k in range(4):
            dd = (dd + Vector((0, 0, 0.12 if not umbrella else -0.05))).normalized()
            pts.append(pts[-1] + dd * (L / 4))
        rb = r0 * (0.55 - 0.25 * t)
        B.tube(pts, [rb * (1 - 0.8 * k / 4) for k in range(5)], segs=6, mat=0)
        clusters.append((pts[-1], dd))
        # 小枝
        for j in range(rng.randint(3, 5)):
            f = rng.uniform(0.35, 0.9)
            k0 = int(f * 3.99)
            p0 = pts[k0].lerp(pts[k0 + 1], f * 4 - k0)
            side = d.cross(Vector((0, 0, 1)))
            if side.length < 1e-6:
                side = Vector((1, 0, 0))
            side.normalize()
            sd = (dd + side * rng.uniform(-1.1, 1.1) + Vector((0, 0, rng.uniform(0.1, 0.6)))).normalized()
            L2 = min(_envelope_len(p0, sd, center, rad, L), L * (1 - f) * rng.uniform(0.6, 0.9) + 0.6)
            p1 = p0 + sd * L2 * 0.55 + Vector((0, 0, 0.1))
            p2 = p0 + sd * L2
            B.tube([p0, p1, p2], [rb * 0.45, rb * 0.25, rb * 0.08], segs=4, mat=0)
            clusters.append((p2, sd))
            clusters.append((p1, sd))
    # 葉の房：樹冠の外側（殻）に房を散らし、近い枝先から細い小枝でつなぐ。本物の樹冠と同じく、葉は外側に集まる
    tips = [c for c, _ in clusters]
    n_cl = int(220 * density * (crown_r / 4.5) ** 2 * (0.8 if umbrella else 1.0))
    for _ in range(n_cl):
        d = Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1))).normalized()
        if umbrella and d.z < -0.25:
            d.z = -d.z * 0.5
        f = rng.uniform(0.72, 1.0)
        p = center + Vector((d.x * rad.x, d.y * rad.y, d.z * rad.z)) * f
        near = min(tips, key=lambda t: (t - p).length)
        if 0.25 < (near - p).length < 1.6:
            mid = near.lerp(p, 0.5) + Vector((0, 0, 0.1))
            B.tube([near, mid, p], [0.014, 0.01, 0.005], segs=3, mat=0)
        out = (p - Vector((0, 0, p.z * 0.6))).normalized()
        nl = int(rng.uniform(40, 60) * (1.0 if species != 'tropical' else 0.8))
        for _ in range(nl):
            q = p + Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 0.7))) * crown_r * 0.09
            axis = (out + Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-.4, .4)))).normalized()
            nrm = (Vector((0, 0, 1)) * 1.0 + out * 0.8 + Vector((rng.gauss(0, .5), rng.gauss(0, .5), 0))).normalized()
            B.leaf(q, axis, nrm, leaf_size * rng.uniform(0.75, 1.25), leaf_size * 0.5 * rng.uniform(0.8, 1.2), mat=1,
                   shape='lance' if species in ('deciduous',) and rng.random() < 0.3 else 'oval')
    return B.finish(name, [bark_m, leaf_m], coll)


def conifer(name, seed, height=14.0, coll=None, species='pine'):
    """針葉樹（円すい形）。輪生する枝に、細い針葉の房を付ける"""
    rng = stream(seed, 'conifer', name)
    bark_m, leaf_m = species_mats(species)
    B = Builder()
    H = height
    r0 = 0.12 + H * 0.014
    path = [Vector((rng.uniform(-.1, .1) * t, rng.uniform(-.1, .1) * t, -0.4 + t * (H + 0.4))) for t in np.linspace(0, 1, 8)]
    B.tube(path, [r0 * (1 - 0.92 * t) + 0.01 for t in np.linspace(0, 1, 8)], segs=8, mat=0)
    golden = math.pi * (3 - math.sqrt(5))
    whorls = int(H / 0.7)
    for w in range(whorls):
        t = w / whorls
        z = H * (0.15 + 0.83 * t)
        R = (1 - t) ** 1.1 * H * 0.24 + 0.3
        for k in range(rng.randint(4, 6)):
            az = w * golden + k * 2 * math.pi / 5 + rng.uniform(-0.3, 0.3)
            d = Vector((math.cos(az), math.sin(az), rng.uniform(-0.25, 0.05))).normalized()
            p0 = Vector((0, 0, z))
            p1 = p0 + d * R * 0.5 + Vector((0, 0, -0.1 * R))
            p2 = p0 + d * R + Vector((0, 0, -0.05 * R))
            B.tube([p0, p1, p2], [r0 * 0.25 * (1 - t), r0 * 0.12, 0.01], segs=4, mat=0)
            # 針葉の房
            for j in range(int(12 + R * 14)):
                f = rng.uniform(0.15, 1.0)
                c = p0.lerp(p2, f) + Vector((rng.gauss(0, .14), rng.gauss(0, .14), rng.gauss(0, .08))) * R
                for _ in range(16):
                    dn = (d * 0.4 + Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0.6, 0.5)))).normalized()
                    B.blade(c, dn, rng.uniform(0.22, 0.36), 0.02, segs=1, bend=0.0, mat=1, taper=0.6)
    return B.finish(name, [bark_m, leaf_m], coll, smooth=False)


def palm(name, seed, height=11.0, lean=None, n_fronds=None, coll=None, dead=2):
    """ヤシ。曲がった幹、輪の模様、羽の形の葉（小葉が両側に並ぶ）。先の枯れ葉もつける"""
    rng = stream(seed, 'palm', name)
    bark_m, leaf_m = species_mats('palm')
    dead_m = M.leaf('palm_dead', (0.18, 0.12, 0.05, 1), (0.30, 0.22, 0.10, 1), gloss=0.2, translucency=0.15)
    B = Builder()
    H = height
    lean = rng.uniform(0.08, 0.28) if lean is None else lean
    az = rng.uniform(0, 2 * math.pi)
    dirh = Vector((math.cos(az), math.sin(az), 0))
    path = []
    for t in np.linspace(0, 1, 12):
        bend = lean * H * (t ** 1.6)
        path.append(Vector((0, 0, -0.3 + t * (H + 0.3))) + dirh * bend + Vector((0, 0, 0)))
    radii = [0.21 * (1 + 0.6 * math.exp(-t * 12)) * (1 - 0.25 * t) for t in np.linspace(0, 1, 12)]
    B.tube(path, radii, segs=10, mat=0)
    top = path[-1]
    up_dir = (path[-1] - path[-2]).normalized()
    n_fronds = n_fronds or rng.randint(14, 19)
    golden = math.pi * (3 - math.sqrt(5))
    for i in range(n_fronds + dead):
        is_dead = i >= n_fronds
        a = i * golden + rng.uniform(-0.2, 0.2)
        age = rng.uniform(0, 1) if not is_dead else 1.3
        el = math.radians(65 - 85 * age)            # 若い葉は上向き、古い葉は垂れる
        d = Vector((math.cos(a) * math.cos(el), math.sin(a) * math.cos(el), math.sin(el)))
        L = rng.uniform(3.8, 5.0) * (0.85 if is_dead else 1.0)
        pts = [top + up_dir * 0.2]
        dd = d.copy()
        for k in range(6):
            dd = (dd + Vector((0, 0, -0.22 - 0.25 * age))).normalized()
            pts.append(pts[-1] + dd * L / 6)
        B.tube(pts, [0.05, 0.04, 0.032, 0.025, 0.018, 0.012, 0.006], segs=4, mat=2 if is_dead else 1)
        if is_dead:
            # 枯れ葉は幹に沿って垂れ下がる
            for k in range(1, 6):
                p = pts[k]
                for sgn in (-1, 1):
                    side = dd.cross(Vector((0, 0, 1))).normalized() * sgn
                    B.blade(p, (side * 0.3 + Vector((0, 0, -1))).normalized(), 0.6, 0.05, segs=2, bend=0.1, mat=2)
            continue
        # 小葉：葉軸の両側に、根元と先は短く
        npair = 42
        for k in range(npair):
            t = 0.08 + 0.9 * k / npair
            seg = t * 6
            k0 = min(int(seg), 5)
            p = pts[k0].lerp(pts[k0 + 1], seg - k0)
            tang = (pts[k0 + 1] - pts[k0]).normalized()
            side = tang.cross(Vector((0, 0, 1)))
            if side.length < 1e-6:
                side = Vector((1, 0, 0))
            side.normalize()
            ll = 0.95 * math.sin(math.pi * min(1, 0.15 + t)) * rng.uniform(0.85, 1.1)
            for sgn in (-1, 1):
                dl = (side * sgn * 0.85 + tang * 0.45 + Vector((0, 0, -0.35 - 0.3 * age))).normalized()
                B.blade(p, dl, ll, 0.055, segs=3, bend=0.55 + 0.3 * age, mat=1, twist=0.4 * sgn, side=tang)
    # 実
    for k in range(rng.randint(3, 8)):
        a = rng.uniform(0, 2 * math.pi)
        c = top + Vector((math.cos(a) * 0.3, math.sin(a) * 0.3, -0.4 - rng.uniform(0, 0.3)))
        bmesh.ops.create_icosphere(B.bm, subdivisions=2, radius=0.13, matrix=Matrix.Translation(c))
    return B.finish(name, [bark_m, leaf_m, dead_m], coll)


def shrub(name, seed, size=1.4, species='shrub', coll=None):
    """低木：根元から何本も枝が出て、丸く茂る"""
    rng = stream(seed, 'shrub', name)
    bark_m, leaf_m = species_mats(species)
    B = Builder()
    for _ in range(rng.randint(4, 7)):
        d = Vector((rng.gauss(0, .5), rng.gauss(0, .5), 1.0)).normalized()
        tip = d * size * rng.uniform(0.7, 1.0)
        B.tube([Vector((0, 0, -0.05)), tip * 0.5, tip], [0.025 * size, 0.015 * size, 0.005], segs=4, mat=0)
        for _ in range(int(55 * size)):
            p = tip * rng.uniform(0.35, 1.0) + Vector((rng.gauss(0, .32), rng.gauss(0, .32), rng.gauss(0, .2))) * size
            if p.z < 0.05:
                continue
            ax = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-.2, .6))).normalized()
            B.leaf(p, ax, Vector((rng.gauss(0, .4), rng.gauss(0, .4), 1)), 0.09 * size ** 0.5 * rng.uniform(0.8, 1.3),
                   0.045 * size ** 0.5, mat=1)
    return B.finish(name, [bark_m, leaf_m], coll)


def grass_clump(name, seed, height=0.6, blades=30, kind='meadow', coll=None):
    """草の株。kind：meadow（草地）、dry（乾いた草）、beach（浜の硬い草）"""
    rng = stream(seed, 'grass', name)
    cols = {'meadow': ((0.035, 0.07, 0.015, 1), (0.07, 0.12, 0.03, 1), (0.20, 0.20, 0.07, 1), 0.25),
            'dry': ((0.09, 0.08, 0.03, 1), (0.20, 0.16, 0.07, 1), (0.36, 0.30, 0.15, 1), 0.6),
            'beach': ((0.05, 0.07, 0.025, 1), (0.10, 0.13, 0.05, 1), (0.26, 0.24, 0.12, 1), 0.4)}[kind]
    mat = M.grass(kind, *cols[:3], dry=cols[3])
    B = Builder()
    for _ in range(blades):
        a = rng.uniform(0, 2 * math.pi)
        r = abs(rng.gauss(0, 0.04))
        base = Vector((math.cos(a) * r, math.sin(a) * r, -0.02))
        d = Vector((math.cos(a) * rng.uniform(0.1, 0.5), math.sin(a) * rng.uniform(0.1, 0.5), 1)).normalized()
        B.blade(base, d, height * rng.uniform(0.55, 1.1), rng.uniform(0.006, 0.012) * (1.6 if kind == 'beach' else 1),
                segs=4, bend=rng.uniform(0.3, 0.9), twist=rng.uniform(-0.6, 0.6), mat=0)
    return B.finish(name, [mat], coll)


def taro(name, seed, size=1.0, coll=None):
    """芋（タロイモのような）：長い葉柄の先に、大きなハート形の葉"""
    rng = stream(seed, 'taro', name)
    stem_m = M.simple('芋の葉柄', (0.06, 0.10, 0.03, 1), (0.12, 0.17, 0.06, 1), 0.6, 4.0, 0.1)
    leaf_m = M.leaf('taro', (0.03, 0.07, 0.02, 1), (0.08, 0.15, 0.04, 1), gloss=0.5, translucency=0.25)
    B = Builder()
    for k in range(rng.randint(3, 6)):
        a = rng.uniform(0, 2 * math.pi)
        h = size * rng.uniform(0.6, 1.0)
        d = Vector((math.cos(a) * 0.35, math.sin(a) * 0.35, 1)).normalized()
        tip = d * h
        B.tube([Vector((0, 0, -0.05)), tip * 0.6 + Vector((0, 0, 0.05)), tip], [0.02, 0.014, 0.01], segs=5, mat=0)
        out = Vector((math.cos(a), math.sin(a), 0))
        B.leaf(tip, (out + Vector((0, 0, -0.5))).normalized(), (Vector((0, 0, 1)) + out * 0.5).normalized(),
               0.55 * size * rng.uniform(0.8, 1.1), 0.75 * size, mat=1, fold=0.1, droop=0.1, shape='heart')
    return B.finish(name, [stem_m, leaf_m], coll)


def tidewheat(name, seed, coll=None):
    """潮麦（架空）：浅瀬に立つ茎と細い葉、先に麦のような穂。原点は水底。高さ1.6〜2.4mなので、水深0.5〜1.5mの浅瀬で穂が水面から出る"""
    rng = stream(seed, 'tidewheat', name)
    stem_m = M.grass('tidewheat', (0.05, 0.07, 0.02, 1), (0.14, 0.15, 0.05, 1), (0.40, 0.33, 0.12, 1), dry=0.4)
    ear_m = M.simple('潮麦の穂', (0.32, 0.24, 0.08, 1), (0.52, 0.42, 0.17, 1), 0.7, 25.0, 0.4)
    B = Builder()
    for k in range(rng.randint(10, 16)):
        a = rng.uniform(0, 2 * math.pi)
        base = Vector((math.cos(a), math.sin(a), 0)) * abs(rng.gauss(0, 0.06))
        h = rng.uniform(1.6, 2.4)
        lean = Vector((math.cos(a), math.sin(a), 0)) * rng.uniform(0.05, 0.25)
        tip = base + Vector((0, 0, h)) + lean
        mid = base.lerp(tip, 0.55) + lean * 0.3
        B.tube([base, mid, tip], [0.012, 0.009, 0.005], segs=4, mat=0)
        # 穂（小さな粒を並べた房と、細いのぎ）
        ear_dir = (tip - mid).normalized()
        ear_dir = (ear_dir + Vector((0, 0, -0.6)) * rng.uniform(0.3, 0.9)).normalized()
        for j in range(14):
            p = tip + ear_dir * (j * 0.012)
            for sgn in (-1, 1):
                side = ear_dir.cross(Vector((0, 0, 1))).normalized() * sgn
                B.leaf(p, (ear_dir + side * 0.6).normalized(), (side.cross(ear_dir)).normalized(), 0.022, 0.012, mat=1, fold=0.3, droop=0.0)
                B.blade(p + side * 0.008, (ear_dir + side * 0.3).normalized(), 0.05, 0.002, segs=1, bend=0.0, mat=1)
        # 葉
        for j in range(2):
            p = base.lerp(tip, rng.uniform(0.45, 0.8))
            d = (Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), 0.8))).normalized()
            B.blade(p, d, rng.uniform(0.3, 0.5), 0.02, segs=3, bend=0.6, mat=0)
    return B.finish(name, [stem_m, ear_m], coll)
