"""地球の基礎キット：入り江のある海岸の地形（scene.py の地形を、島の種類で変えられるようにしたもの）

x は東、y は北、z は高さ（m）。海面は z=0。範囲は 1.24km × 1.28km（2.5m 間隔）。
島の中心は (0, 340)。入り江は南向き。集落の段丘は VILLAGE のまわり。

preset（計算の島の種類に合わせる）：
  volcanic_high：高い火山島（山が高く、崖の岬）
  volcanic_old ：古い火山島（なだらかな丘）
  coral        ：低いサンゴ島（ほとんど平ら、浜が広い）
  continental  ：大陸性の島の海岸（広い平地の奥に丘）
"""
import math

import bpy
import numpy as np
from mathutils import Vector, noise

from .util import link_object, mesh_from_arrays, smoothstep

PRESETS = {
    'volcanic_high': dict(hill=110.0, ridge=9.0, cliff=14.0, flat_from=10.0, flat_to=140.0, beach_w=20.0),
    'volcanic_old': dict(hill=70.0, ridge=5.0, cliff=9.0, flat_from=15.0, flat_to=170.0, beach_w=24.0),
    'coral': dict(hill=5.0, ridge=0.0, cliff=0.0, flat_from=5.0, flat_to=60.0, beach_w=45.0),
    'continental': dict(hill=45.0, ridge=4.0, cliff=4.0, flat_from=30.0, flat_to=260.0, beach_w=28.0),
}


class Terrain:
    X0, X1, Y0, Y1 = -620.0, 620.0, -380.0, 900.0
    STEP = 2.5
    CENTER = (0.0, 340.0)
    VILLAGE = (5.0, 160.0)
    REEF = (57.0, 36.0)

    def __init__(self, seed, preset='volcanic_old', village=True, reef=True, **over):
        self.seed = seed
        self.p = dict(PRESETS[preset])
        self.p.update(over)
        self.preset = preset
        self.use_village = village
        self.use_reef = reef
        self.nx = int((self.X1 - self.X0) / self.STEP) + 1
        self.ny = int((self.Y1 - self.Y0) / self.STEP) + 1
        xs = np.linspace(self.X0, self.X1, self.nx)
        ys = np.linspace(self.Y0, self.Y1, self.ny)
        self.X, self.Y = np.meshgrid(xs, ys)
        self.H, self.F = self._heights()

    def _n(self, x, y, s, oct=4, off=0.0):
        o = Vector((self.seed * 13.1 + off, self.seed * 7.7 + off, 0))
        return noise.fractal(Vector((x * s, y * s, 0)) + o, 0.55, 2.0, oct)

    def coast_radius(self, th):
        R0 = 345.0
        south = -math.pi / 2
        bay = 1 - 0.40 * math.exp(-((th - south) / 0.5) ** 2)
        head = 0.15 * math.exp(-((th - (south + 0.78)) / 0.17) ** 2) + 0.12 * math.exp(-((th - (south - 0.82)) / 0.15) ** 2)
        wob = 0.07 * noise.noise(Vector((math.cos(th) * 1.7 + self.seed, math.sin(th) * 1.7, 0.3)))
        return R0 * (bay + head + wob)

    def _grid_noise(self, fn):
        fx, fy = self.X.ravel(), self.Y.ravel()
        return np.array([fn(a, b) for a, b in zip(fx, fy)]).reshape(self.X.shape)

    def _heights(self):
        P = self.p
        cx, cy = self.CENTER
        X, Y = self.X, self.Y
        dx, dy = X - cx, Y - cy
        r = np.hypot(dx, dy)
        th = np.arctan2(dy, dx)
        R = np.vectorize(self.coast_radius)(th)
        w = smoothstep(60, 160, r)
        R = R * w + 345.0 * (1 - w)
        n_low = self._grid_noise(lambda a, b: self._n(a, b, 1 / 160, 3))
        n_mid = self._grid_noise(lambda a, b: self._n(a, b, 1 / 45, 4, 3.3))
        n_hi = self._grid_noise(lambda a, b: self._n(a, b, 1 / 9, 3, 9.1))
        F = R - r + 16 * n_low + 4 * n_mid
        south = -math.pi / 2
        headmask = np.clip(np.exp(-((th - (south + 0.78)) / 0.2) ** 2) + np.exp(-((th - (south - 0.82)) / 0.18) ** 2), 0, 1)
        Wb = (P['beach_w'] + 7 * n_mid) * (1 - 0.85 * headmask * (P['cliff'] > 0))
        H = np.zeros_like(F)
        land = F >= 0
        fb = np.clip(F / np.maximum(Wb, 1.0), 0, 1)
        beach = (2.2 if self.preset != 'coral' else 1.6) * fb ** 1.5
        g = np.maximum(F - Wb, 0)
        hill_h = P['hill'] * (0.72 + 0.28 * n_low)
        hill = hill_h * (1 - np.exp(-g / 120)) + 7 * n_mid * (1 - np.exp(-g / 50)) * min(1, P['hill'] / 40) \
            + 1.2 * n_hi * (1 - np.exp(-g / 20))
        if P['ridge'] > 0:
            ridge = self._grid_noise(lambda a, b: noise.ridged_multi_fractal(Vector((a / 95, b / 95, 2.0 + self.seed)), 1.0, 2.0, 4, 1.0, 2.0))
            hill = hill + P['ridge'] * np.clip(ridge - 0.8, -0.8, 0.9) * smoothstep(20, 120, g)
        hill = hill * (0.15 + 0.85 * smoothstep(P['flat_from'], P['flat_to'], g))
        cliff = headmask * P['cliff'] * (1 - np.exp(-np.maximum(F, 0) / 6))
        hl = beach + hill + cliff
        k = np.array([1, 4, 6, 4, 1], float)
        k /= k.sum()
        hs = hl.copy()
        for _ in range(2):
            hs = np.apply_along_axis(lambda v: np.convolve(np.pad(v, 2, mode='edge'), k, 'valid'), 1, hs)
            hs = np.apply_along_axis(lambda v: np.convolve(np.pad(v, 2, mode='edge'), k, 'valid'), 0, hs)
        blend = smoothstep(25, 60, F)
        hl = hl * (1 - blend) + hs * blend
        hl = self._settle(hl, F > 12, 36.0, 60)
        vx, vy = self.VILLAGE
        vm = np.exp(-(((X - vx) / 1.7) ** 2 + ((Y - vy) / 0.45) ** 2) / (2 * 52 ** 2))
        vm = vm * smoothstep(Wb * 0.8, Wb + 10, F)
        if self.use_village:
            terrace = 4.6 + 1.2 * n_mid + 0.05 * np.clip(Y - vy, 0, None)
            if self.preset == 'coral':
                terrace = 2.6 + 0.3 * n_mid
            hl = hl * (1 - 0.6 * vm) + terrace * 0.6 * vm
        H[land] = hl[land]
        d = np.maximum(-F, 0)
        shelf_k = 1.6 if self.preset == 'coral' else 2.6
        shelf = 0.35 + shelf_k * (1 - np.exp(-d / 55)) + np.maximum(d - 85, 0) * 0.17
        depth = np.minimum(shelf, 38) + 0.25 * n_mid + 0.06 * n_hi
        H[~land] = -depth[~land]
        if self.use_reef:
            rx, ry = self.REEF
            g_ = np.exp(-((X - rx) ** 2 + (Y - ry) ** 2) / (2 * 9.0 ** 2))
            reef = -7.5 + 7.9 * g_ + 0.45 * n_hi * smoothstep(0.3, 0.8, g_)   # 岩場らしいでこぼこ
            H = np.maximum(H, reef)
        self.headmask = headmask
        self.Wb = Wb
        self.village_mask = vm
        return H, F

    def _settle(self, h, movable, angle, iters):
        h = h.copy()
        talus = math.tan(math.radians(angle)) * self.STEP
        mv = movable.astype(float)
        for _ in range(iters):
            for axis, step in ((0, 1), (0, -1), (1, 1), (1, -1)):
                nb = np.roll(h, step, axis)
                d = h - nb
                move = np.where(d > talus, (d - talus) * 0.2, 0.0) * mv * np.roll(mv, step, axis)
                if axis == 0:
                    move[0 if step > 0 else -1, :] = 0
                else:
                    move[:, 0 if step > 0 else -1] = 0
                h -= move
                h += np.roll(move, -step, axis)
        return h

    def height_at(self, x, y):
        fx = (x - self.X0) / self.STEP
        fy = (y - self.Y0) / self.STEP
        i = int(np.clip(math.floor(fx), 0, self.nx - 2))
        j = int(np.clip(math.floor(fy), 0, self.ny - 2))
        tx, ty = fx - i, fy - j
        h = self.H
        return h[j, i] * (1 - tx) * (1 - ty) + h[j, i + 1] * tx * (1 - ty) + h[j + 1, i] * (1 - tx) * ty + h[j + 1, i + 1] * tx * ty

    def field_at(self, x, y):
        i = int(np.clip(round((x - self.X0) / self.STEP), 0, self.nx - 1))
        j = int(np.clip(round((y - self.Y0) / self.STEP), 0, self.ny - 1))
        return self.F[j, i]

    def slope_at(self, x, y, e=1.5):
        hx = self.height_at(x + e, y) - self.height_at(x - e, y)
        hy = self.height_at(x, y + e) - self.height_at(x, y - e)
        return math.degrees(math.atan(math.hypot(hx, hy) / (2 * e)))

    def build(self, mat, attrs=None):
        nx, ny = self.nx, self.ny
        verts = np.stack([self.X.ravel(), self.Y.ravel(), self.H.ravel()], axis=1)
        ii, jj = np.meshgrid(np.arange(nx - 1), np.arange(ny - 1))
        a = (jj * nx + ii).ravel()
        quads = np.stack([a, a + 1, a + nx + 1, a + nx], axis=1)
        me = mesh_from_arrays('地形', verts, quads.ravel(), np.full(len(quads), 4))
        me.polygons.foreach_set('use_smooth', np.ones(len(quads), bool))
        for name, val in (attrs or {}).items():
            at = me.attributes.new(name, 'FLOAT', 'POINT')
            at.data.foreach_set('value', np.asarray(val, np.float32).ravel())
        obj = bpy.data.objects.new('地形', me)
        link_object(obj)
        me.materials.append(mat)
        return obj
