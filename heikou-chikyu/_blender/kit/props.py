"""地球の基礎キット：暮らしの道具と建物（住まい・干し棚・火と煙・土器・薪）

時代に合わないものは置かない（金属の道具や高度な船は、その技術を得るまで出さない）。
原点は地面、y が正面。長さは m。
"""
import math

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import materials as M
from .util import add_box, link_object, new_material, node, link, map_range, math_op, stream
from .vegetation import Builder


def _mats():
    return dict(
        thatch=M.simple('茅', (0.17, 0.13, 0.07, 1), (0.33, 0.26, 0.15, 1), 0.95, 9.0, 0.8, (1, 6, 1)),
        pole=M.simple('柱', (0.12, 0.08, 0.05, 1), (0.25, 0.18, 0.11, 1), 0.85, 4.0, 0.5, (1, 1, 6), kind='wave'),
        mat=M.simple('編んだ葉', (0.28, 0.22, 0.12, 1), (0.42, 0.34, 0.19, 1), 0.9, 25.0, 0.4, (1, 4, 1), kind='wave'),
        dark=M.simple('戸口', (0.02, 0.015, 0.01, 1), (0.05, 0.04, 0.03, 1), 0.9, 3.0, 0.1),
        clay=M.simple('土器', (0.22, 0.12, 0.07, 1), (0.36, 0.22, 0.13, 1), 0.85, 6.0, 0.3),
        fish=M.simple('干した魚', (0.20, 0.17, 0.12, 1), (0.40, 0.35, 0.26, 1), 0.5, 12.0, 0.2),
        ash=M.simple('灰と炭', (0.02, 0.02, 0.02, 1), (0.10, 0.09, 0.08, 1), 0.95, 8.0, 0.3),
    )


def shelter(name, seed, coll=None):
    """最初期の住まい：枝を立てかけ、葉でふいた差しかけ小屋"""
    rng = stream(seed, 'shelter', name)
    m = _mats()
    B = Builder()
    w, d, h = rng.uniform(2.4, 3.2), rng.uniform(2.0, 2.6), rng.uniform(1.4, 1.8)
    B.tube([Vector((-w / 2, 0, 0)), Vector((-w / 2, 0, h))], [0.05, 0.04], segs=5, mat=0)
    B.tube([Vector((w / 2, 0, 0)), Vector((w / 2, 0, h))], [0.05, 0.04], segs=5, mat=0)
    B.tube([Vector((-w / 2 - 0.2, 0, h)), Vector((w / 2 + 0.2, 0, h))], [0.04, 0.04], segs=5, mat=0)
    n = int(w / 0.25)
    for k in range(n + 1):
        x = -w / 2 + k * w / n
        B.tube([Vector((x, 0, h)), Vector((x + rng.uniform(-.1, .1), -d, 0))], [0.025, 0.02], segs=4, mat=0)
    # 葉でふいた面
    for row in range(6):
        t0, t1 = row / 6, (row + 1.15) / 6
        a = [B.bm.verts.new(Vector((-w / 2 - 0.15, -d * t, h * (1 - t) + 0.05))) for t in (t0, t1)]
        b = [B.bm.verts.new(Vector((w / 2 + 0.15, -d * t, h * (1 - t) + 0.05))) for t in (t0, t1)]
        B.face([a[0], b[0], b[1], a[1]], [(0, t0), (1, t0), (1, t1), (0, t1)], 1)
    return B.finish(name, [m['pole'], m['thatch']], coll, smooth=False)


def hut(name, seed, size=1.0, coll=None, stilts=False):
    """柱と編んだ葉の壁、茅ぶきの切妻屋根の家。stilts=True で高床（倉にも使う）"""
    rng = stream(seed, 'hut', name)
    m = _mats()
    w, d, h = rng.uniform(3.6, 5.0) * size, rng.uniform(4.5, 6.5) * size, rng.uniform(1.9, 2.4)
    base = 1.2 if stilts else 0.15
    pitch = math.radians(rng.uniform(40, 50))
    bm_wall, bm_roof, bm_pole, bm_dark = bmesh.new(), bmesh.new(), bmesh.new(), bmesh.new()
    add_box(bm_wall, Vector((0, 0, base + h / 2)), (w, d, h))
    add_box(bm_dark, Vector((0, -d / 2 - 0.03, base + 0.8)), (0.9, 0.08, 1.6))
    if stilts:
        add_box(bm_pole, Vector((0, 0, base - 0.05)), (w + 0.5, d + 0.5, 0.12))
        for sx in (-1, 0, 1):
            for sy in (-1, 0, 1):
                add_box(bm_pole, Vector((sx * w * 0.45, sy * d * 0.45, base / 2)), (0.18, 0.18, base))
        for k in range(6):
            add_box(bm_pole, Vector((0, -d / 2 - 0.4 - k * 0.12, base * (1 - k / 6) - 0.05)), (0.7, 0.12, 0.06))
    for sx in (-1, 1):
        for sy in (-1, 1):
            add_box(bm_pole, Vector((sx * w / 2, sy * d / 2, base + h / 2)), (0.18, 0.18, h + 0.05))
    top = base + h + (w / 2) * math.tan(pitch)
    for sy in (-1, 1):
        y = sy * d / 2
        vs = [bm_wall.verts.new(p) for p in ((-w / 2, y, base + h), (w / 2, y, base + h), (0, y, top))]
        bm_wall.faces.new(vs if sy > 0 else vs[::-1])
    over = 0.6
    slope_len = (w / 2 + over) / math.cos(pitch)
    for sx in (-1, 1):
        tilt = Matrix.Rotation(sx * pitch, 4, 'Y')
        c = Vector((sx * (w / 4 + over / 2), 0, base + h + (w / 4 - over / 2) * math.tan(pitch) + 0.2))
        add_box(bm_roof, c, (slope_len + 0.15, d + 2 * over, 0.35), 0.0, tilt)
    add_box(bm_pole, Vector((0, 0, top + 0.14)), (0.35, d + 2 * over + 0.1, 0.25))
    me_list = []
    for bm, mm in ((bm_wall, m['mat']), (bm_roof, m['thatch']), (bm_pole, m['pole']), (bm_dark, m['dark'])):
        me = bpy.data.meshes.new(name + mm.name)
        bm.to_mesh(me)
        bm.free()
        me.materials.append(mm)
        me_list.append(me)
    return _join(name, me_list, coll)


def _join(name, meshes, coll):
    bm = bmesh.new()
    mats = []
    for me in meshes:
        off = len(mats)
        mats.extend(me.materials)
        tmp = bmesh.new()
        tmp.from_mesh(me)
        for f in tmp.faces:
            f.material_index += off
        t = bpy.data.meshes.new('tmp')
        tmp.to_mesh(t)
        tmp.free()
        bm.from_mesh(t)
        bpy.data.meshes.remove(t)
        bpy.data.meshes.remove(me)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for mm in mats:
        me.materials.append(mm)
    obj = bpy.data.objects.new(name, me)
    if coll is not False:
        link_object(obj, coll)
    return obj


def drying_rack(name, seed, length=3.0, coll=None):
    """魚を干す棚（干物・燻製の技術から）"""
    rng = stream(seed, 'rack', name)
    m = _mats()
    B = Builder()
    for x in (-length / 2, length / 2):
        for y in (-0.3, 0.3):
            B.tube([Vector((x, y, 0)), Vector((x, y * 0.3, 1.6))], [0.035, 0.03], segs=5, mat=0)
    for z in (1.1, 1.5):
        B.tube([Vector((-length / 2 - 0.1, 0, z)), Vector((length / 2 + 0.1, 0, z))], [0.025, 0.025], segs=5, mat=0)
        for k in range(int(length / 0.18)):
            x = -length / 2 + 0.1 + k * 0.18
            c = Vector((x, 0, z - 0.2))
            B.leaf(c + Vector((0, 0, 0.2)), Vector((0, 0, -1)), Vector((0, 1, 0)), rng.uniform(0.3, 0.42), 0.12, mat=1, fold=0.05, droop=0.0)
    return B.finish(name, [m['pole'], m['fish']], coll)


def pots(name, seed, n=5, coll=None):
    """土器（土器の技術から）"""
    rng = stream(seed, 'pots', name)
    m = _mats()
    B = Builder()
    for k in range(n):
        c = Vector((rng.uniform(-0.6, 0.6), rng.uniform(-0.5, 0.5), 0))
        r = rng.uniform(0.15, 0.25)
        prof = [0.4, 0.8, 1.0, 0.95, 0.7, 0.55, 0.6]
        path = [c + Vector((0, 0, r * 1.4 * t)) for t in [0, 0.12, 0.35, 0.6, 0.82, 0.95, 1.0]]
        B.tube(path, [r * p for p in prof], segs=12, mat=0)
    return B.finish(name, [m['clay']], coll)


def fire(name, seed, smoke=True, coll=None, strength=60.0):
    """焚き火：石の輪、薪、炎の明かり（光）と、上がる煙（体積）"""
    rng = stream(seed, 'fire', name)
    m = _mats()
    B = Builder()
    for k in range(9):
        a = k / 9 * 2 * math.pi
        c = Vector((math.cos(a) * 0.45, math.sin(a) * 0.45, 0.06))
        bmesh.ops.create_icosphere(B.bm, subdivisions=1, radius=rng.uniform(0.08, 0.12), matrix=Matrix.Translation(c))
    for k in range(6):
        a = rng.uniform(0, 2 * math.pi)
        d = Vector((math.cos(a), math.sin(a), 0))
        B.tube([d * 0.35 + Vector((0, 0, 0.05)), Vector((0, 0, 0.35))], [0.04, 0.03], segs=5, mat=1)
    obj = B.finish(name, [m['ash'], m['pole']], coll)
    # 炎の明かり
    light = bpy.data.lights.new(name + '火', 'POINT')
    light.energy = strength
    light.color = (1.0, 0.45, 0.15)
    light.shadow_soft_size = 0.3
    lo = bpy.data.objects.new(name + '火', light)
    lo.location = (0, 0, 0.4)
    lo.parent = obj
    link_object(lo, coll if coll is not False else None)
    # 炎（光る小さな形）
    fm, nt = new_material('炎')
    em = node(nt, 'ShaderNodeEmission', (0, 0))
    em.inputs['Color'].default_value = (1.0, 0.42, 0.10, 1)
    em.inputs['Strength'].default_value = 25.0
    out = node(nt, 'ShaderNodeOutputMaterial', (200, 0))
    link(nt, em.outputs[0], out.inputs['Surface'])
    Bf = Builder()
    for k in range(5):
        a = rng.uniform(0, 2 * math.pi)
        base = Vector((math.cos(a) * 0.08, math.sin(a) * 0.08, 0.15))
        Bf.blade(base, Vector((rng.uniform(-.2, .2), rng.uniform(-.2, .2), 1)), rng.uniform(0.35, 0.55), 0.14, segs=3, bend=0.0, mat=0, taper=1.0)
    fl = Bf.finish(name + '炎', [fm], coll)
    fl.parent = obj
    fl.visible_shadow = False
    if smoke:
        sm, nt = new_material('煙')
        tc = node(nt, 'ShaderNodeTexCoord', (-800, 0))
        mp = node(nt, 'ShaderNodeMapping', (-600, 0))
        mp.inputs['Scale'].default_value = (1.2, 1.2, 0.5)
        link(nt, tc.outputs['Object'], mp.inputs['Vector'])
        nz = node(nt, 'ShaderNodeTexNoise', (-400, 0), Scale=2.5, Detail=6.0, Roughness=0.6)
        link(nt, mp.outputs[0], nz.inputs['Vector'])
        sep = node(nt, 'ShaderNodeSeparateXYZ', (-600, -250))
        link(nt, tc.outputs['Generated'], sep.inputs[0])
        # 上へ行くほど広がって薄くなる柱
        lean = math_op(nt, 'ADD', math_op(nt, 'MULTIPLY', sep.outputs['Z'], 0.28), 0.36)
        dx = node(nt, 'ShaderNodeMath', (-400, -250), operation='SUBTRACT')
        link(nt, sep.outputs['X'], dx.inputs[0])
        link(nt, lean, dx.inputs[1])
        dy = node(nt, 'ShaderNodeMath', (-400, -400), operation='SUBTRACT')
        link(nt, sep.outputs['Y'], dy.inputs[0])
        dy.inputs[1].default_value = 0.5
        r2 = node(nt, 'ShaderNodeVectorMath', (-250, -300), operation='LENGTH')
        cxy = node(nt, 'ShaderNodeCombineXYZ', (-320, -300))
        link(nt, dx.outputs[0], cxy.inputs['X'])
        link(nt, dy.outputs[0], cxy.inputs['Y'])
        link(nt, cxy.outputs[0], r2.inputs[0])
        wid = map_range(nt, sep.outputs['Z'], 0.0, 1.0, 0.05, 0.42)
        col_ = node(nt, 'ShaderNodeMath', (-100, -300), operation='DIVIDE')
        link(nt, r2.outputs['Value'], col_.inputs[0])
        link(nt, wid, col_.inputs[1])
        core = map_range(nt, col_.outputs[0], 1.0, 0.3)
        fade = map_range(nt, sep.outputs['Z'], 0.85, 0.05)
        d1 = node(nt, 'ShaderNodeMath', (50, -200), operation='MULTIPLY')
        link(nt, core, d1.inputs[0])
        link(nt, fade, d1.inputs[1])
        d2 = node(nt, 'ShaderNodeMath', (200, -100), operation='MULTIPLY')
        link(nt, d1.outputs[0], d2.inputs[0])
        link(nt, map_range(nt, nz.outputs['Fac'], 0.45, 0.75), d2.inputs[1])
        d3 = node(nt, 'ShaderNodeMath', (350, -100), operation='MULTIPLY')
        link(nt, d2.outputs[0], d3.inputs[0])
        d3.inputs[1].default_value = 0.9
        vol = node(nt, 'ShaderNodeVolumePrincipled', (500, 0))
        vol.inputs['Color'].default_value = (0.40, 0.41, 0.43, 1)
        vol.inputs['Absorption Color'].default_value = (0.25, 0.25, 0.26, 1)
        link(nt, d3.outputs[0], vol.inputs['Density'])
        out = node(nt, 'ShaderNodeOutputMaterial', (750, 0))
        link(nt, vol.outputs[0], out.inputs['Volume'])
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Translation((0.5, 1.2, 4.5)) @ Matrix.Diagonal(Vector((5, 5, 9, 1))))
        me = bpy.data.meshes.new(name + '煙')
        bm.to_mesh(me)
        bm.free()
        me.materials.append(sm)
        so = bpy.data.objects.new(name + '煙', me)
        so.parent = obj
        link_object(so, coll if coll is not False else None)
    return obj


def woodpile(name, seed, coll=None):
    rng = stream(seed, 'woodpile', name)
    m = _mats()
    B = Builder()
    for k in range(14):
        y = rng.uniform(-0.4, 0.4)
        z = 0.06 + (k // 5) * 0.1
        x0 = rng.uniform(-0.1, 0.1)
        B.tube([Vector((x0 - 0.6, y, z)), Vector((x0 + 0.6, y + rng.uniform(-.1, .1), z))], [0.05, 0.045], segs=5, mat=0, cap=True)
    return B.finish(name, [m['pole']], coll)


def lightstone(name, seed, size=0.5, coll=None):
    """軽殻石（架空）：白っぽい、穴の多い軽い石。浜に打ち上がり、水に浮く"""
    rng = stream(seed, 'lightstone', name)
    from mathutils import noise
    m = M.simple('軽殻石', (0.55, 0.55, 0.52, 1), (0.80, 0.80, 0.76, 1), 0.85, 18.0, 1.2)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=3, radius=1.0)
    off = Vector((seed * 1.7, seed * 2.3, seed * 0.7))
    sx, sy, sz = rng.uniform(.8, 1.3), rng.uniform(.7, 1.1), rng.uniform(.5, .8)
    for v in bm.verts:
        p = v.co.copy()
        p = p * (1 + 0.25 * noise.fractal(p * 1.5 + off, 0.6, 2.0, 4) - 0.35 * noise.cell(p * 3.0 + off))
        v.co = Vector((p.x * sx, p.y * sy, p.z * sz)) * size
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(m)
    obj = bpy.data.objects.new(name, me)
    if coll is not False:
        link_object(obj, coll)
    return obj


def log_carving(name, seed, length=7.0, coll=None):
    """くりぬき途中の丸木（台の上）と、削りくず"""
    rng = stream(seed, 'log', name)
    m = _mats()
    wood_in = M.simple('削った木', (0.30, 0.20, 0.11, 1), (0.48, 0.34, 0.20, 1), 0.8, 6.0, 0.4, (1, 1, 5), kind='wave')
    B = Builder()
    r = 0.42
    # 外側：太い丸太（上を少し平らに）
    B.tube([Vector((0, -length / 2, 0.9)), Vector((0, length / 2, 0.9))], [r, r * 0.92], segs=14, mat=0, cap=True)
    # くりぬいた内側（明るい木肌の溝）
    for k in range(12):
        y = (k / 11 - 0.5) * length * 0.75
        B.leaf(Vector((-0.3, y, 1.28)), Vector((1, 0, 0)), Vector((0, 0, 1)), 0.6, length * 0.08, mat=1, fold=-0.4, droop=0.0)
    # 台
    for y in (-length * 0.3, length * 0.3):
        for x in (-0.5, 0.5):
            B.tube([Vector((x, y, 0)), Vector((x * 0.3, y, 0.6))], [0.06, 0.05], segs=5, mat=2)
    # 削りくず
    for _ in range(80):
        p = Vector((rng.uniform(-1.5, 1.5), rng.uniform(-length / 2, length / 2), 0.02))
        B.leaf(p, Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), 0)), Vector((0, 0, 1)), rng.uniform(0.06, 0.14), 0.04, mat=1, fold=0.2, droop=0.0)
    return B.finish(name, [m['pole'], wood_in, m['pole']], coll)
