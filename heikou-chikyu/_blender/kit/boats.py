"""地球の基礎キット：舟（いかだ・丸木舟・浮き木つきの舟・帆）

原点は舟の真ん中の水面の高さ。y が舳先（へさき）の向き。長さは m。
計算の舟の段階（いかだ → 丸木舟 → 浮き木つきの舟 → 帆 → 星と波の航法）に合わせて使い分ける。
"""
import math

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import materials as M
from .util import add_box, link_object, stream
from .vegetation import Builder


def _mats():
    return dict(wood=M.simple('丸太', (0.10, 0.07, 0.045, 1), (0.22, 0.16, 0.10, 1), 0.8, 4.0, 0.5, (1, 1, 6), kind='wave'),
                hull=M.simple('舟の木', (0.11, 0.075, 0.045, 1), (0.24, 0.16, 0.09, 1), 0.55, 3.0, 0.3, (1, 8, 1), kind='wave'),
                rope=M.simple('縄', (0.16, 0.12, 0.07, 1), (0.30, 0.24, 0.14, 1), 0.9, 30.0, 0.6),
                sail=M.simple('帆（編んだ葉）', (0.42, 0.34, 0.20, 1), (0.60, 0.50, 0.32, 1), 0.85, 18.0, 0.25, (1, 6, 1), sss=0.15, kind='wave'))


def raft(name, seed, length=4.2, width=2.0, coll=None):
    """丸太を並べて縄で縛ったいかだ"""
    rng = stream(seed, 'raft', name)
    m = _mats()
    B = Builder()
    n = max(5, int(width / 0.3))
    for k in range(n):
        x = (k - (n - 1) / 2) * width / n
        L = length * rng.uniform(0.9, 1.05)
        r = rng.uniform(0.11, 0.15)
        y0 = -L / 2 + rng.uniform(-0.1, 0.1)
        B.tube([Vector((x, y0, 0.02)), Vector((x, y0 + L, 0.02))], [r, r * 0.9], segs=8, mat=0, cap=True)
    for y in (-length * 0.35, 0, length * 0.35):
        B.tube([Vector((-width / 2 - 0.1, y, 0.16)), Vector((width / 2 + 0.1, y, 0.16))], [0.06, 0.06], segs=6, mat=0)
    obj = B.finish(name, [m['wood']], coll)
    return obj


def _hull(B, length, beam, depth, mat=0, stations=16):
    """丸木をくりぬいた船体（外側だけ。厚みは Solidify で付ける）"""
    prof = [(-1.0, 1.0), (-0.95, 0.6), (-0.75, 0.25), (-0.4, 0.05), (0.0, 0.0), (0.4, 0.05), (0.75, 0.25), (0.95, 0.6), (1.0, 1.0)]
    rings = []
    for k in range(stations):
        t = k / (stations - 1)
        y = (t - 0.5) * length
        taper = math.sin(math.pi * t) ** 0.55
        rise = depth * 0.35 * (2 * abs(t - 0.5)) ** 3          # 舳先と艫（とも）は少し上がる
        rings.append([B.bm.verts.new(Vector((px * beam * 0.5 * max(taper, 0.04), y, -depth * 0.55 + rise + pz * depth * (1 + 0.3 * (2 * abs(t - 0.5)) ** 2))))
                      for px, pz in prof])
    for k in range(stations - 1):
        for s in range(len(prof) - 1):
            B.face([rings[k][s], rings[k][s + 1], rings[k + 1][s + 1], rings[k + 1][s]],
                   [(s / 8, k / stations), ((s + 1) / 8, k / stations), ((s + 1) / 8, (k + 1) / stations), (s / 8, (k + 1) / stations)], mat)


def dugout(name, seed, length=6.0, coll=None):
    """丸木舟"""
    m = _mats()
    B = Builder()
    _hull(B, length, length * 0.11, length * 0.07)
    obj = B.finish(name, [m['hull']], coll)
    sol = obj.modifiers.new('厚み', 'SOLIDIFY')
    sol.thickness = 0.05
    sol.offset = -1
    return obj


def outrigger(name, seed, length=8.0, sail=False, coll=None, side=1):
    """浮き木つきの舟。舟の片側に、腕木2本で浮き木（細い丸太）を付ける。sail=True で帆柱と蟹のはさみ形の帆"""
    rng = stream(seed, 'outrigger', name)
    m = _mats()
    B = Builder()
    beam, depth = length * 0.1, length * 0.065
    _hull(B, length, beam, depth)
    hull_faces = len(B.bm.faces)
    # 腕木と浮き木
    off = side * (beam * 0.5 + 2.2 + length * 0.08)
    for y in (-length * 0.18, length * 0.18):
        B.tube([Vector((-side * beam * 0.6, y, depth * 0.45)), Vector((off * 0.5, y, depth * 0.55)), Vector((off, y, depth * 0.25))],
               [0.05, 0.05, 0.045], segs=6, mat=1)
    fl = length * 0.62
    B.tube([Vector((off, -fl / 2, 0.05)), Vector((off, -fl * 0.3, -0.02)), Vector((off, fl * 0.3, -0.02)), Vector((off, fl / 2, 0.06))],
           [0.04, 0.12, 0.12, 0.04], segs=8, mat=1, cap=True)
    # 腕木の上の台
    for k in range(6):
        y = (k - 2.5) * 0.28
        B.tube([Vector((beam * 0.2 * side, y, depth * 0.6)), Vector((off * 0.45, y, depth * 0.62))], [0.025, 0.025], segs=4, mat=1)
    if sail:
        mast_base = Vector((0, length * 0.05, -depth * 0.2))
        mast_top = mast_base + Vector((side * 0.3, -0.3, length * 0.75))
        B.tube([mast_base, mast_top], [0.07, 0.045], segs=6, mat=1)
        # 蟹のはさみ形の帆：下の端を舳先に付け、2本の帆桁のあいだに張る
        foot = Vector((0, length * 0.42, depth * 0.6))
        y1 = mast_top + Vector((0, -length * 0.15, length * 0.12))
        y2 = Vector((side * 0.2, -length * 0.42, length * 0.42))
        B.tube([foot, foot.lerp(y1, 0.5) + Vector((-side * 0.1, 0, 0)), y1], [0.04, 0.035, 0.025], segs=5, mat=1)
        B.tube([foot, foot.lerp(y2, 0.5) + Vector((side * 0.3, 0, -0.3)), y2], [0.04, 0.035, 0.025], segs=5, mat=1)
        n = 10
        prev = None
        billow = Vector((side * 0.9, 0, 0))
        for k in range(n + 1):
            t = k / n
            a = foot.lerp(y1, t)
            b = foot.lerp(y2, t)
            row = []
            for j in range(7):
                u = j / 6
                p = a.lerp(b, u) + billow * math.sin(math.pi * u) * math.sin(math.pi * t * 0.9) * 0.6
                row.append(B.bm.verts.new(p))
            if prev:
                for j in range(6):
                    B.face([prev[j], prev[j + 1], row[j + 1], row[j]], [(j / 6, (k - 1) / n), ((j + 1) / 6, (k - 1) / n), ((j + 1) / 6, t), (j / 6, t)], 2)
            prev = row
    obj = B.finish(name, [m['hull'], m['wood'], m['sail']], coll)
    # 船体にだけ厚み（頂点グループで指定）
    vg = obj.vertex_groups.new(name='hull')
    hull_verts = set()
    for f in obj.data.polygons[:hull_faces]:
        hull_verts.update(f.vertices)
    vg.add(list(hull_verts), 1.0, 'REPLACE')
    sol = obj.modifiers.new('厚み', 'SOLIDIFY')
    sol.thickness = 0.06
    sol.offset = -1
    sol.vertex_group = 'hull'
    return obj
