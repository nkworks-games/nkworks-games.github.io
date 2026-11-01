"""並行地球：カット表の3Dのカットを、カットの設定（JSON）から組み立てて描く（Blender 5.x / Cycles）

使い方（Mac の例。リポジトリの一番上で）：
  /Applications/Blender.app/Contents/MacOS/Blender -b -P heikou-chikyu/_blender/shots.py -- \
      --shots heikou-chikyu/_blender/shots/ep1.json --out ~/heikou-renders --gpu
  --only 001,003   一部のカットだけ
  --still          動くカットも、真ん中の1コマだけ描く（構図の確認用）
  --preview        960×540・少ない試行で速く描く
  --blend          編集できる .blend も保存する

カットの種類（kind）：
  coast   入り江の海岸（地形・森・集落・舟・人・焚き火・海）
  opensea 沖の海（波・帆の舟・遠くの島影）
  planet  惑星の全景（計算の地形から作った地図を貼る）
外部の素材は使わない。同じ設定なら同じ絵になる。
"""
import argparse
import json
import math
import os
import sys
import time

import bpy  # bpy を先に読み込む（Python のパッケージ版では bmesh・mathutils が bpy の後でないと使えない）
import bmesh
import numpy as np
from mathutils import Matrix, Vector, noise

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '_sim'))

from kit import boats as Bo  # noqa: E402
from kit import materials as M  # noqa: E402
from kit import people as P  # noqa: E402
from kit import props as Pr  # noqa: E402
from kit import scatter, sky, water  # noqa: E402
from kit import vegetation as V  # noqa: E402
from kit.terrain import Terrain  # noqa: E402
from kit.util import link_object, mesh_object, stream  # noqa: E402


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument('--shots', default=os.path.join(HERE, 'shots', 'ep1.json'))
    ap.add_argument('--only', default='')
    ap.add_argument('--out', default='heikou-renders')
    ap.add_argument('--res', default='1920x1080')
    ap.add_argument('--samples', type=int, default=64)
    ap.add_argument('--preview', action='store_true')
    ap.add_argument('--still', action='store_true')
    ap.add_argument('--blend', action='store_true')
    ap.add_argument('--gpu', action='store_true')
    ap.add_argument('--threads', type=int, default=0)
    return ap.parse_args(argv)


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


# ---------------------------------------------------------------- 植物の型（気候ごと）

def vegetation_library(climate, seed):
    lib = {}
    trees = scatter.library('木の型')
    palms = scatter.library('ヤシの型')
    shrubs = scatter.library('低木の型')
    grass = scatter.library('草の型')
    r = stream(seed, 'veglib', climate)
    if climate == 'tropical':
        for k in range(3):
            V.tree('熱帯の木%d' % k, seed * 10 + k, r.uniform(15, 22), species='tropical', umbrella=k == 0, buttress=k < 2, coll=trees)
        for k in range(2):
            V.tree('照葉樹%d' % k, seed * 10 + 5 + k, r.uniform(10, 14), species='evergreen', coll=trees)
        n_palm = 4
        gkinds = ['meadow', 'beach', 'meadow']
    elif climate == 'subtropical':
        for k in range(4):
            V.tree('照葉樹%d' % k, seed * 10 + k, r.uniform(9, 14), species='evergreen', coll=trees)
        V.tree('熱帯の木', seed * 10 + 7, 14, species='tropical', coll=trees)
        n_palm = 2
        gkinds = ['dry', 'beach', 'meadow']
    else:
        for k in range(2):
            V.tree('照葉樹%d' % k, seed * 10 + k, r.uniform(10, 14), species='evergreen', coll=trees)
        for k in range(2):
            V.tree('落葉樹%d' % k, seed * 10 + 3 + k, r.uniform(10, 15), species='deciduous', coll=trees)
        for k in range(2):
            V.conifer('針葉樹%d' % k, seed * 10 + 6 + k, r.uniform(13, 19), coll=trees)
        n_palm = 0
        gkinds = ['meadow', 'meadow', 'dry']
    for k in range(n_palm):
        V.palm('ヤシ%d' % k, seed * 20 + k, r.uniform(9, 14), coll=palms)
    for k in range(3):
        V.shrub('低木%d' % k, seed * 30 + k, r.uniform(1.0, 1.8), coll=shrubs)
    for k, g in enumerate(gkinds):
        V.grass_clump('草%d' % k, seed * 40 + k, r.uniform(0.4, 0.8), blades=36, kind=g, coll=grass)
    lib.update(trees=trees, palms=palms, shrubs=shrubs, grass=grass)
    return lib


# ---------------------------------------------------------------- 入り江の海岸

def build_coast(s):
    seed = s.get('seed', 7)
    rng = stream(seed, 'coast', s['id'])
    ter = Terrain(seed, s.get('preset', 'volcanic_old'), village=s.get('village', True), reef=s.get('reef', False))
    lib = vegetation_library(s.get('climate', 'tropical'), seed)
    vx, vy = Terrain.VILLAGE
    # 集落：家（数は計算の人口から決めて、カットの設定に入れてある）
    vil = s.get('settlement', {})
    huts = []
    tries = 0
    n_huts = vil.get('huts', 0)
    while len(huts) < n_huts and tries < 8000:
        tries += 1
        rad = 14 + 70 * math.sqrt(rng.random())
        a = rng.uniform(0, 2 * math.pi)
        x, y = vx + math.cos(a) * rad * 1.8, vy + math.sin(a) * rad * 0.7
        if ter.field_at(x, y) < 26 or ter.slope_at(x, y, 3) > 13:
            continue
        if any((x - hx) ** 2 + (y - hy) ** 2 < 9.5 ** 2 for hx, hy, _ in huts):
            continue
        face = math.atan2(-(y - 40), -(x - 5)) + math.pi / 2 + rng.uniform(-.35, .35)
        huts.append((x, y, face))
    style = vil.get('style', 'hut')
    types = []
    for k in range(5):
        if style == 'shelter':
            types.append(Pr.shelter('住まい%d' % k, seed * 100 + k, coll=False))
        else:
            types.append(Pr.hut('家%d' % k, seed * 100 + k, coll=False, stilts=(k == 4 and vil.get('storehouse', False))))
    for k, (x, y, face) in enumerate(huts):
        src = types[k % len(types)]
        ob = bpy.data.objects.new('家', src.data)
        ob.location = (x, y, ter.height_at(x, y) - 0.12)
        ob.rotation_euler = (0, 0, face)
        link_object(ob)
    # 畑（芋や果樹）：集落の奥の平らな所
    garden = []
    if vil.get('gardens', 0):
        gcoll = scatter.library('芋の型')
        for k in range(3):
            V.taro('芋%d' % k, seed * 50 + k, rng.uniform(0.8, 1.2), coll=gcoll)
        for p in range(vil['gardens']):
            gx, gy = vx + rng.uniform(-120, 120), vy + rng.uniform(45, 110)
            if ter.slope_at(gx, gy, 4) > 12:
                continue
            garden.append((gx, gy))
            items = []
            for i in range(14):
                for j in range(9):
                    x, y = gx + i * 1.3 + rng.uniform(-.2, .2), gy + j * 1.4 + rng.uniform(-.2, .2)
                    items.append((x, y, ter.height_at(x, y) - 0.05, rng.randrange(3), rng.uniform(0.8, 1.2), rng.uniform(0, 6.3)))
            scatter.instances('畑%d' % p, gcoll, items)
    # 森・ヤシ・低木・草
    cover = s.get('forest', 1.0)
    cand = []
    for gy in np.arange(ter.Y0 + 5, ter.Y1 - 5, 3.6):
        for gx in np.arange(ter.X0 + 5, ter.X1 - 5, 3.6):
            x, y = gx + rng.uniform(-1.7, 1.7), gy + rng.uniform(-1.7, 1.7)
            f = ter.field_at(x, y)
            if f < 30:
                continue
            h = ter.height_at(x, y)
            if h < 2.6 or ter.slope_at(x, y) > 46:
                continue
            if noise.fractal(Vector((x / 70, y / 70, 5.0 + seed)), 0.6, 2.0, 3) < -0.5:
                continue
            near = min(((x - hx) ** 2 + (y - hy) ** 2 for hx, hy, _ in huts), default=1e9)
            if near < 9 ** 2 or (near < 18 ** 2 and rng.random() < 0.6):
                continue
            if any(abs(x - gx - 9) < 13 and abs(y - gy - 6) < 10 for gx, gy in garden):
                continue
            access = math.hypot((x - vx) / 1.15, (y - vy) / 0.8) + 0.8 * h
            cand.append((access, x, y, h, rng.random()))
    # 森が減った分は、集落から行きやすい所ほど切られている（境目はぼかす）
    cand.sort()
    n_cut = int(round(len(cand) * (1 - cover)))
    thr = cand[n_cut][0] if 0 < n_cut < len(cand) else None
    trees = []
    n_tree_types = len(lib['trees'].objects)
    for acc, x, y, h, u in cand:
        if thr is not None and u < 1 / (1 + math.exp((acc - thr) / 60.0)):
            continue
        trees.append((x, y, h - 0.2, rng.randrange(n_tree_types), rng.uniform(0.75, 1.15), rng.uniform(0, 6.3)))
    scatter.instances('森', lib['trees'], trees)
    palms = []
    if len(lib['palms'].objects):
        for _ in range(int(9000 * s.get('palm_density', 1.0))):
            x, y = rng.uniform(-430, 430), rng.uniform(-40, 330)
            f = ter.field_at(x, y)
            wb = ter.Wb[int((y - ter.Y0) / ter.STEP), int((x - ter.X0) / ter.STEP)]
            if not (wb - 6 < f < wb + 45):
                continue
            h = ter.height_at(x, y)
            if h < 1.6 or ter.slope_at(x, y) > 25:
                continue
            if any((x - hx) ** 2 + (y - hy) ** 2 < 6 ** 2 for hx, hy, _ in huts):
                continue
            palms.append((x, y, h - 0.15, rng.randrange(len(lib['palms'].objects)), rng.uniform(0.8, 1.2), rng.uniform(0, 6.3)))
        scatter.instances('ヤシ', lib['palms'], palms)
    shrubs, grass = [], []
    cam = Vector(s['camera']['loc'])
    for _ in range(30000):
        x, y = rng.uniform(-430, 430), rng.uniform(-30, 420)
        f = ter.field_at(x, y)
        if f < 18:
            continue
        h = ter.height_at(x, y)
        if h < 1.9 or ter.slope_at(x, y) > 35:
            continue
        if any((x - hx) ** 2 + (y - hy) ** 2 < 5 ** 2 for hx, hy, _ in huts):
            continue
        if f < 160 and rng.random() < 0.35:
            shrubs.append((x, y, h - 0.1, rng.randrange(3), rng.uniform(0.6, 1.4), rng.uniform(0, 6.3)))
    # 草はカメラに近いほど多く（遠くは見えないので置かない）
    for _ in range(60000):
        a = rng.uniform(0, 2 * math.pi)
        d = 3 + 160 * rng.random() ** 2
        x, y = cam.x + math.cos(a) * d, cam.y + math.sin(a) * d
        f = ter.field_at(x, y)
        h = ter.height_at(x, y)
        if f < 12 or h < 1.5 or ter.slope_at(x, y) > 35:
            continue
        if any((x - hx) ** 2 + (y - hy) ** 2 < 4 ** 2 for hx, hy, _ in huts):
            continue
        grass.append((x, y, h - 0.03, rng.randrange(3), rng.uniform(0.7, 1.3), rng.uniform(0, 6.3)))
    scatter.instances('低木', lib['shrubs'], shrubs)
    scatter.instances('草', lib['grass'], grass)
    # 地面（森の床と集落の土を書き込む）
    canopy = np.zeros_like(ter.H)
    for x, y, *_ in trees:
        i, j = int((x - ter.X0) / ter.STEP), int((y - ter.Y0) / ter.STEP)
        canopy[max(0, j - 2):j + 3, max(0, i - 2):i + 3] += 0.35
    village = np.zeros_like(ter.H)
    for x, y, _ in huts:
        village = np.maximum(village, np.exp(-((ter.X - x) ** 2 + (ter.Y - y) ** 2) / (2 * 7.5 ** 2)))
    for gx, gy in garden:
        village = np.maximum(village, ((abs(ter.X - gx - 9) < 10) & (abs(ter.Y - gy - 6) < 7.5)).astype(float) * 0.9)
    village *= ter.H > 2.0
    ter.build(M.terrain(s.get('ground', 'temperate')), dict(canopy=np.clip(canopy, 0, 1), village=village))
    # 岩（岬と浜の両端）
    rocks_c = scatter.library('岩の型')
    for k in range(6):
        _rock(seed * 60 + k, rocks_c)
    rocks = []
    for _ in range(1500):
        x, y = rng.uniform(-420, 420), rng.uniform(-60, 260)
        f = ter.field_at(x, y)
        hm = ter.headmask[int((y - ter.Y0) / ter.STEP), int((x - ter.X0) / ter.STEP)]
        if not (-14 < f < 10) or (abs(x - vx) < 160 and hm < 0.3):
            continue
        sz = rng.uniform(0.6, 2.4) * (1.6 if hm > 0.3 else 1.0)
        rocks.append((x, y, ter.height_at(x, y) - sz * 0.25, rng.randrange(6), sz, rng.uniform(0, 6.3)))
    scatter.instances('岩', rocks_c, rocks)
    # 浜の舟・干し棚・土器・焚き火・人
    beach_y = {}

    def beach_at(x, h0=0.9):
        if x not in beach_y:
            beach_y[x] = next((yy for yy in np.arange(30, 260, 0.4) if ter.height_at(x, yy) > h0), None)
        return beach_y[x]
    k = 0
    for b in s.get('boats', []):
        for _ in range(b.get('count', 1)):
            x = vx - 70 + k * 13 + rng.uniform(-3, 3)
            k += 1
            yb = beach_at(round(x, 1))
            if yb is None:
                continue
            afloat = b.get('afloat', False)
            if b['type'] == 'raft':
                ob = Bo.raft('いかだ%d' % k, seed + k)
            elif b['type'] == 'dugout':
                ob = Bo.dugout('丸木舟%d' % k, seed + k, rng.uniform(5.5, 7.0))
            else:
                ob = Bo.outrigger('舟%d' % k, seed + k, rng.uniform(7, 9), sail=b['type'] == 'sail')
            y = yb - (14 + rng.uniform(0, 12) if afloat else -rng.uniform(1, 4))
            z = 0.05 if afloat else ter.height_at(x, y) + 0.15
            ob.location = (x, y, z)
            ob.rotation_euler = (0, 0, rng.uniform(-0.35, 0.35) + (math.pi / 2 if afloat else 0))
    for k in range(vil.get('racks', 0)):
        if not huts:
            break
        hx, hy, _ = huts[(k * 3) % len(huts)]
        x, y = hx + rng.uniform(-6, 6), hy - 7
        o = Pr.drying_rack('干し棚%d' % k, seed + k)
        o.location = (x, y, ter.height_at(x, y))
        o.rotation_euler = (0, 0, rng.uniform(-0.4, 0.4))
    for k in range(vil.get('pots', 0)):
        if not huts:
            break
        hx, hy, _ = huts[(k * 5 + 1) % len(huts)]
        o = Pr.pots('土器%d' % k, seed + k)
        o.location = (hx + 3, hy - 4, ter.height_at(hx + 3, hy - 4))
    fires = []
    for k in range(vil.get('fires', 0)):
        if not huts:
            break
        # 焚き火は家の前の浜寄り（画面から見える所）
        hx, hy, _ = huts[(k * 4 + 2) % len(huts)]
        x = hx + rng.uniform(-4, 4)
        yb = beach_at(round(x, 1), 1.6) or hy - 6
        y = min(hy - 6, yb + 6)
        o = Pr.fire('焚き火%d' % k, seed + k, smoke=k < vil.get('smoke', 2), strength=s.get('fire_strength', 60.0))
        o.location = (x, y, ter.height_at(x, y))
        fires.append((x, y))
    poses = ['stand', 'walk', 'carry', 'bend', 'sit', 'look', 'walk']
    for k in range(vil.get('people', 0)):
        if fires and k % 3 == 0:
            fx, fy = fires[k % len(fires)]
            a = rng.uniform(0, 2 * math.pi)
            x, y, pose = fx + math.cos(a) * 1.6, fy + math.sin(a) * 1.6, 'sit'
            face = math.atan2(fy - y, fx - x) - math.pi / 2
        elif huts:
            hx, hy, _ = huts[rng.randrange(len(huts))]
            x, y = hx + rng.uniform(-8, 8), hy + rng.uniform(-10, -3)
            pose = poses[k % len(poses)]
            face = rng.uniform(0, 2 * math.pi)
        else:
            continue
        o = P.figure('人%d' % k, seed * 7 + k, pose=pose, child=rng.random() < 0.2, phase=rng.random())
        o.location = (x, y, ter.height_at(x, y))
        o.rotation_euler = (0, 0, face)
    water.sea_box(s.get('algae', 1.0))
    water.foam(ter)
    return ter


def _rock(seed, coll):
    rng = stream(seed, 'rock')
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=4, radius=1.0)
    off = Vector((seed * 3.1, seed * 1.7, seed * 0.9))
    sx, sy, sz = rng.uniform(.8, 1.5), rng.uniform(.7, 1.3), rng.uniform(.45, .85)
    for v in bm.verts:
        p = v.co.copy()
        p = p * (1 + noise.fractal(p * 1.3 + off, 0.6, 2.0, 6) * 0.36 - noise.cell(p * 2.2 + off) * 0.28)
        if p.z > 0.75:
            p.z = 0.75 + (p.z - 0.75) * 0.55
        v.co = Vector((p.x * sx, p.y * sy, p.z * sz))
    o = mesh_object('岩%d' % seed, bm, coll)
    o.data.materials.append(M.rock('shore'))
    o.data.polygons.foreach_set('use_smooth', np.ones(len(o.data.polygons), bool))
    return o


# ---------------------------------------------------------------- 沖の海

def island_silhouette(name, seed, radius, height, loc):
    """遠くの島影（森におおわれた低い山）"""
    rng = stream(seed, 'silhouette', name)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=64, y_segments=64, size=radius * 1.3)
    off = Vector((seed * 2.3, seed * 1.1, 0))
    for v in bm.verts:
        r = v.co.length / radius
        n = noise.fractal(v.co / radius * 2 + off, 0.55, 2.0, 5)
        h = height * max(0.0, 1 - r ** 2) ** 0.8 * (1 + 0.35 * n) - 3 * max(0, r - 0.95)
        v.co.z = h
    o = mesh_object(name, bm)
    o.location = loc
    o.data.materials.append(M.simple('遠くの森', (0.012, 0.022, 0.010, 1), (0.03, 0.05, 0.02, 1), 0.9, 0.05, 0.1))
    o.data.polygons.foreach_set('use_smooth', np.ones(len(o.data.polygons), bool))
    return o


def build_opensea(s):
    seed = s.get('seed', 7)
    rng = stream(seed, 'opensea', s['id'])
    wave = s.get('wave', 0.8)
    oc, md = water.ocean(size=300, wave_scale=wave, choppy=1.2, wind=8 + 6 * wave, seed=seed, repeat=3)
    boats = []
    for k, b in enumerate(s.get('boats', [])):
        ob = Bo.outrigger('舟%d' % k, seed + k, b.get('length', 9.0), sail=b.get('sail', True), side=1)
        ob.location = Vector(b['loc'])
        ob.rotation_euler = (math.radians(rng.uniform(-2, 2)), math.radians(rng.uniform(-3, 3)), math.radians(b.get('heading', 0)))
        for j in range(b.get('crew', 3)):
            f = P.figure('乗り手%d_%d' % (k, j), seed * 3 + k * 10 + j, pose='paddle' if j else 'sit', phase=j * 0.3)
            f.parent = ob
            f.location = (0.0, -1.6 + j * 1.3, -0.1)
        boats.append((ob, b))
    for k, isl in enumerate(s.get('islands', [])):
        island_silhouette('島影%d' % k, seed + k, isl['radius'], isl['height'], isl['loc'])
    return oc, md, boats


# ---------------------------------------------------------------- 惑星

def build_planet(s):
    import world as W
    import maps
    tid = s.get('terrain', 'R1')
    w = W.build_world(tid)
    width = s.get('texture', 4096)
    arr = maps.render_array(w, width, halo_km=25.0)
    h = arr.shape[0]
    img = bpy.data.images.new('地図_' + tid, width, h, alpha=False)
    px = np.ones((h, width, 4), np.float32)
    px[:, :, :3] = (arr[::-1].astype(np.float32) / 255.0) ** 2.2
    img.pixels.foreach_set(px.ravel())
    img.pack()
    R = 6.371
    bpy.ops.mesh.primitive_uv_sphere_add(segments=256, ring_count=128, radius=R)
    pl = bpy.context.active_object
    pl.name = '惑星'
    bpy.ops.object.shade_smooth()
    from kit.util import new_material, node, link, map_range
    m, nt = new_material('惑星の地表')
    tc = node(nt, 'ShaderNodeTexCoord', (-900, 0))
    tex = node(nt, 'ShaderNodeTexImage', (-600, 0))
    tex.image = img
    tex.interpolation = 'Cubic'
    link(nt, tc.outputs['UV'], tex.inputs['Vector'])
    sep = node(nt, 'ShaderNodeSeparateColor', (-350, -200))
    link(nt, tex.outputs['Color'], sep.inputs[0])
    land = map_range(nt, sep.outputs['Red'], 0.012, 0.02)
    # 海は地図の色より明るい青に（宇宙から見た海の色）。陸は地図の色
    seacol = node(nt, 'ShaderNodeMix', (-150, 150), data_type='RGBA')
    link(nt, land, seacol.inputs['Factor'])
    seacol.inputs[6].default_value = (0.012, 0.045, 0.13, 1)
    link(nt, tex.outputs['Color'], seacol.inputs[7])
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled', (0, 0))
    link(nt, seacol.outputs[2], bsdf.inputs['Base Color'])
    rough = node(nt, 'ShaderNodeMapRange', (-150, -250))
    link(nt, land, rough.inputs['Value'])
    rough.inputs['To Min'].default_value = 0.32
    rough.inputs['To Max'].default_value = 0.85
    link(nt, rough.outputs['Result'], bsdf.inputs['Roughness'])
    out = node(nt, 'ShaderNodeOutputMaterial', (300, 0))
    link(nt, bsdf.outputs[0], out.inputs['Surface'])
    pl.data.materials.append(m)
    # 雲
    bpy.ops.mesh.primitive_uv_sphere_add(segments=192, ring_count=96, radius=R * 1.006)
    cl = bpy.context.active_object
    cl.name = '雲'
    bpy.ops.object.shade_smooth()
    cm, nt = new_material('雲')
    tc = node(nt, 'ShaderNodeTexCoord', (-900, 0))
    warp = node(nt, 'ShaderNodeTexNoise', (-800, -200), Scale=0.8, Detail=3.0)
    link(nt, tc.outputs['Object'], warp.inputs['Vector'])
    wv = node(nt, 'ShaderNodeVectorMath', (-700, -100), operation='MULTIPLY_ADD')
    link(nt, warp.outputs['Color'], wv.inputs[0])
    wv.inputs[1].default_value = (2.5, 2.5, 2.5)
    link(nt, tc.outputs['Object'], wv.inputs[2])
    nz = node(nt, 'ShaderNodeTexNoise', (-600, 0), Scale=0.35, Detail=14.0, Roughness=0.6)
    link(nt, wv.outputs[0], nz.inputs['Vector'])
    mask = map_range(nt, nz.outputs['Fac'], 0.56, 0.72)
    white = node(nt, 'ShaderNodeBsdfPrincipled', (-200, 100))
    white.inputs['Base Color'].default_value = (0.85, 0.86, 0.88, 1)
    white.inputs['Roughness'].default_value = 0.9
    tr = node(nt, 'ShaderNodeBsdfTransparent', (-200, -100))
    mix = node(nt, 'ShaderNodeMixShader', (100, 0))
    link(nt, mask, mix.inputs[0])
    link(nt, tr.outputs[0], mix.inputs[1])
    link(nt, white.outputs[0], mix.inputs[2])
    out = node(nt, 'ShaderNodeOutputMaterial', (300, 0))
    link(nt, mix.outputs[0], out.inputs['Surface'])
    cl.data.materials.append(cm)
    # 大気のふち（縁が青く光る）
    bpy.ops.mesh.primitive_uv_sphere_add(segments=128, ring_count=64, radius=R * 1.03)
    at = bpy.context.active_object
    at.name = '大気'
    bpy.ops.object.shade_smooth()
    am, nt = new_material('大気')
    lw = node(nt, 'ShaderNodeLayerWeight', (-600, 0))
    lw.inputs['Blend'].default_value = 0.35
    rim = map_range(nt, lw.outputs['Facing'], 0.25, 1.0, 0.06, 1.0)
    em = node(nt, 'ShaderNodeEmission', (-200, 100))
    em.inputs['Color'].default_value = (0.25, 0.5, 1.0, 1)
    em.inputs['Strength'].default_value = 1.2
    tr = node(nt, 'ShaderNodeBsdfTransparent', (-200, -100))
    mix = node(nt, 'ShaderNodeMixShader', (100, 0))
    link(nt, rim, mix.inputs[0])
    link(nt, tr.outputs[0], mix.inputs[1])
    link(nt, em.outputs[0], mix.inputs[2])
    out = node(nt, 'ShaderNodeOutputMaterial', (300, 0))
    link(nt, mix.outputs[0], out.inputs['Surface'])
    at.data.materials.append(am)
    at.visible_shadow = False
    # 宇宙と太陽
    world = bpy.data.worlds.new('宇宙')
    bpy.context.scene.world = world
    wnt = world.node_tree
    for n in list(wnt.nodes):
        wnt.nodes.remove(n)
    from kit.util import node as nd
    bg = nd(wnt, 'ShaderNodeBackground', (0, 0), Strength=0.0)
    st = nd(wnt, 'ShaderNodeTexVoronoi', (-400, 0), Scale=900.0)
    tcw = nd(wnt, 'ShaderNodeTexCoord', (-600, 0))
    link(wnt, tcw.outputs['Generated'], st.inputs['Vector'])
    dot = map_range(wnt, st.outputs['Distance'], 0.0, 0.05, 1.0, 0.0)
    br = map_range(wnt, st.outputs['Color'], 0.93, 1.0)
    mul = nd(wnt, 'ShaderNodeMath', (-100, -150), operation='MULTIPLY')
    link(wnt, dot, mul.inputs[0])
    link(wnt, br, mul.inputs[1])
    starbg = nd(wnt, 'ShaderNodeBackground', (0, -200), Strength=2.0)
    mixw = nd(wnt, 'ShaderNodeMixShader', (200, 0))
    link(wnt, mul.outputs[0], mixw.inputs[0])
    link(wnt, bg.outputs[0], mixw.inputs[1])
    link(wnt, starbg.outputs[0], mixw.inputs[2])
    outw = nd(wnt, 'ShaderNodeOutputWorld', (400, 0))
    link(wnt, mixw.outputs[0], outw.inputs['Surface'])
    sun = bpy.data.lights.new('太陽', 'SUN')
    sun.energy = 4.0
    so = bpy.data.objects.new('太陽', sun)
    link_object(so)
    so.rotation_euler = (math.radians(70), 0, math.radians(s.get('sun_az', 60)))
    pl.rotation_euler = (0, 0, math.radians(s.get('spin', 0)))
    cl.rotation_euler = pl.rotation_euler
    return pl


# ---------------------------------------------------------------- カメラと描画

def setup_camera(s, frames):
    cam = bpy.data.objects.new('カメラ', bpy.data.cameras.new('カメラ'))
    link_object(cam)
    c = s['camera']
    cam.data.lens = c.get('lens', 30)
    cam.data.sensor_width = 36
    cam.data.clip_end = c.get('clip', 40000)
    cam.data.clip_start = c.get('clip_start', 0.1)

    def aim(loc, tgt):
        cam.location = loc
        cam.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    aim(c['loc'], c['target'])
    bpy.context.scene.camera = cam
    if frames > 1 and 'loc2' in c:
        for k in range(frames):
            t = k / (frames - 1)
            e = t * t * (3 - 2 * t) if c.get('ease', True) else t
            aim(Vector(c['loc']).lerp(Vector(c['loc2']), e), Vector(c['target']).lerp(Vector(c['target2']), e))
            cam.keyframe_insert('location', frame=k + 1)
            cam.keyframe_insert('rotation_euler', frame=k + 1)
    return cam


def use_gpu():
    prefs = bpy.context.preferences.addons['cycles'].preferences
    for kind in ('METAL', 'OPTIX', 'CUDA', 'HIP', 'ONEAPI'):
        try:
            prefs.compute_device_type = kind
        except TypeError:
            continue
        prefs.get_devices()
        if any(d.type == kind for d in prefs.devices):
            for d in prefs.devices:
                d.use = d.type == kind
            bpy.context.scene.cycles.device = 'GPU'
            return kind
    return None


def render_settings(args, s):
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    cy = sc.cycles
    cy.device = 'CPU'
    if args.gpu:
        print('GPU:', use_gpu() or '見つからないので CPU で描く')
    rx, ry = (960, 540) if args.preview else map(int, args.res.lower().split('x'))
    sc.render.resolution_x, sc.render.resolution_y = rx, ry
    sc.render.resolution_percentage = 100
    cy.samples = 24 if args.preview else s.get('samples', args.samples)
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = 0.03 if args.preview else 0.015
    cy.use_denoising = True
    cy.denoiser = 'OPENIMAGEDENOISE'
    cy.max_bounces = 8
    cy.diffuse_bounces = 3
    cy.glossy_bounces = 3
    cy.transmission_bounces = 8
    cy.volume_bounces = 0
    cy.transparent_max_bounces = 16
    cy.caustics_reflective = False
    cy.caustics_refractive = False
    cy.blur_glossy = 1.0
    cy.sample_clamp_indirect = 8.0
    if args.threads:
        sc.render.threads_mode = 'FIXED'
        sc.render.threads = args.threads
    sc.view_settings.view_transform = 'AgX'
    try:
        sc.view_settings.look = 'AgX - Medium High Contrast'
    except TypeError:
        pass
    sc.view_settings.exposure = s.get('exposure', 0.0)
    sc.render.image_settings.file_format = 'PNG'
    sc.render.fps = 24


def build(s, args):
    reset()
    kind = s['kind']
    fps = 24
    frames = int(round(s.get('seconds', 0) * fps)) if s.get('anim') and not args.still else 1
    ocean_md = None
    boats = []
    if kind == 'coast':
        build_coast(s)
    elif kind == 'opensea':
        _, ocean_md, boats = build_opensea(s)
    elif kind == 'planet':
        build_planet(s)
    sk = s.get('sky')
    if sk:
        sky.setup(sk.get('time', 'dusk'), sk.get('azimuth', -120), sk.get('elevation'), sk.get('cloud', 0.5),
                  sk.get('storm', 0.0), s.get('seed', 7))
    setup_camera(s, frames)
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, max(1, frames)
    if frames > 1:
        sc.render.use_persistent_data = kind != 'opensea'
        if ocean_md is not None:
            ocean_md.time = 0.0
            ocean_md.keyframe_insert('time', frame=1)
            ocean_md.time = s['seconds']
            ocean_md.keyframe_insert('time', frame=frames)
        for ob, b in boats:
            v = b.get('speed', 2.0)
            hd = math.radians(b.get('heading', 0))
            d = Vector((-math.sin(hd), math.cos(hd), 0)) * v * s['seconds']
            ob.keyframe_insert('location', frame=1)
            ob.location = ob.location + d
            ob.keyframe_insert('location', frame=frames)
    elif s.get('anim') and args.still and ocean_md is not None:
        ocean_md.time = s['seconds'] / 2
    render_settings(args, s)
    return frames


def main():
    args = parse_args()
    with open(args.shots, encoding='utf-8') as f:
        shots = json.load(f)['shots']
    only = set(x.strip() for x in args.only.split(',') if x.strip())
    out = os.path.abspath(os.path.expanduser(args.out))
    os.makedirs(out, exist_ok=True)
    for s in shots:
        if only and s['id'] not in only:
            continue
        t0 = time.time()
        frames = build(s, args)
        sc = bpy.context.scene
        print('カット %s（%s）組み立て %.1fs・%d コマ' % (s['id'], s.get('title', ''), time.time() - t0, frames), flush=True)
        if args.blend:
            bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, 'cut%s.blend' % s['id']))
        t1 = time.time()
        if frames > 1:
            d = os.path.join(out, 'cut%s' % s['id'])
            os.makedirs(d, exist_ok=True)
            sc.render.filepath = os.path.join(d, 'f_')
            bpy.ops.render.render(animation=True)
            print('  動画 %d コマ・%.1fs（1コマ %.1fs）→ %s' % (frames, time.time() - t1, (time.time() - t1) / frames, d), flush=True)
        else:
            sc.render.filepath = os.path.join(out, 'cut%s.png' % s['id'])
            bpy.ops.render.render(write_still=True)
            print('  静止画 %.1fs → %s' % (time.time() - t1, sc.render.filepath), flush=True)


if __name__ == '__main__':
    main()
