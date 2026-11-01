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
from mathutils.bvhtree import BVHTree

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
    ap.add_argument('--step', type=int, default=1, help='N コマおきに描く（2 なら半分。間はあとで補う）')
    ap.add_argument('--resume', action='store_true', help='描き終えたコマ・カットは飛ばす（中断したところから）')
    ap.add_argument('--build-only', action='store_true', help='描かずに .blend だけ保存する（scene_check.py で点検する用）')
    ap.add_argument('--frames', default='', help='動くカットの、決めたコマだけを静止画で描く（first,mid,last か番号。本番前の確かめ用）')
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
    cams = [Vector(s['camera'][k]).xy for k in ('loc', 'loc2') if k in s['camera']]

    def near_cam(x, y, r):
        # カメラのすぐ近く（動くならその道すじ）に、幹や藪を置かない
        return any((Vector((x, y)) - c).length < r for c in cams)
    rng = stream(seed, 'coast', s['id'])
    ter = Terrain(seed, s.get('preset', 'volcanic_old'), village=s.get('village', True), reef=s.get('reef', False))
    flatten_paths(ter, s.get('extras', []))   # 草木を置く前に、歩く道を平らにしておく
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
    hut_occ = []
    for k, (x, y, face) in enumerate(huts):
        src = types[k % len(types)]
        ob = bpy.data.objects.new('家', src.data)
        # 4隅の地面の高さを見て、いちばん低い隅に床を合わせる（下り側が浮かないように）。
        # 上り側は地面に埋まる＝斜面に建つ家の土台。その深さは embed_ok として点検に伝える
        # 型の大きさは頂点から測る（場面に置いていない型の bound_box は 0 のことがある）
        vco = np.empty(len(src.data.vertices) * 3, np.float32)
        src.data.vertices.foreach_get('co', vco)
        vco = vco.reshape(-1, 3)
        xs, ys = [float(vco[:, 0].min()), float(vco[:, 0].max())], [float(vco[:, 1].min()), float(vco[:, 1].max())]
        ca, sa = math.cos(face), math.sin(face)
        hs = [ter.height_at(x + cx * ca - cy * sa, y + cx * sa + cy * ca) for cx in (min(xs), max(xs)) for cy in (min(ys), max(ys))]
        ob.location = (x, y, min(hs) - 0.03)
        ob.rotation_euler = (0, 0, face)
        ob['embed_ok'] = round(max(hs) - min(hs) + 0.08, 3)   # 地形ができた後に seat_on_lowest で測り直す
        # 足もとの円：囲む箱の中心（回した後）と、半分の対角
        cxl, cyl = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        hut_occ.append((x + cxl * ca - cyl * sa, y + cxl * sa + cyl * ca, 0.5 * math.hypot(max(xs) - min(xs), max(ys) - min(ys))))
        ob['grounded'] = True
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
            if h < 2.6 or ter.slope_at(x, y) > 58:
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
    cleared = []
    for acc, x, y, h, u in cand:
        if thr is not None and u < 1 / (1 + math.exp((acc - thr) / 60.0)):
            cleared.append((x, y, h))
            continue
        if near_cam(x, y, 9):
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
            if near_cam(x, y, 9):
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
        if h < 1.9 or ter.slope_at(x, y) > 50:
            continue
        if any((x - hx) ** 2 + (y - hy) ** 2 < 5 ** 2 for hx, hy, _ in huts):
            continue
        if near_cam(x, y, 7):
            continue
        if f < 160 and rng.random() < 0.35:
            shrubs.append((x, y, h - 0.1, rng.randrange(3), rng.uniform(0.6, 1.4), rng.uniform(0, 6.3)))
    # 草はカメラに近いほど多く（遠くは見えないので置かない）
    for _ in range(60000):
        a = rng.uniform(0, 2 * math.pi)
        d = 6 + 160 * rng.random() ** 2
        x, y = cam.x + math.cos(a) * d, cam.y + math.sin(a) * d
        f = ter.field_at(x, y)
        h = ter.height_at(x, y)
        if f < 12 or h < 1.5 or ter.slope_at(x, y) > 35:
            continue
        if any((x - hx) ** 2 + (y - hy) ** 2 < 4 ** 2 for hx, hy, _ in huts):
            continue
        grass.append((x, y, h - 0.03, rng.randrange(3), rng.uniform(0.7, 1.3), rng.uniform(0, 6.3)))
    # 木を切った跡は、裸の土ではなく低い藪と草地になる
    for x, y, h in cleared:
        if rng.random() < 0.6 and not near_cam(x, y, 7):
            shrubs.append((x + rng.uniform(-1.5, 1.5), y + rng.uniform(-1.5, 1.5), h - 0.1, rng.randrange(3), rng.uniform(0.9, 1.9), rng.uniform(0, 6.3)))
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
    if ter.use_reef:   # 潮の引いた岩場：低い岩をたくさん
        rx, ry = Terrain.REEF
        for _ in range(260):
            q, rr = rng.uniform(0, 2 * math.pi), 13 * math.sqrt(rng.random())
            x, y = rx + math.cos(q) * rr * 1.2, ry + math.sin(q) * rr
            sz = rng.uniform(0.25, 1.1)
            rocks.append((x, y, ter.height_at(x, y) - sz * 0.35, rng.randrange(6), sz, rng.uniform(0, 6.3)))
    scatter.instances('岩', rocks_c, rocks)
    # 浜の舟・干し棚・土器・焚き火・人
    beach_y = {}

    def beach_at(x, h0=0.9):
        if x not in beach_y:
            beach_y[x] = next((yy for yy in np.arange(30, 260, 0.4) if ter.height_at(x, yy) > h0), None)
        return beach_y[x]
    # 置いた物の足もと（円）を覚えておき、重ならない所にだけ置く（人どうし・人と舟などのめり込みを防ぐ）
    occ = list(hut_occ)
    EX_R = dict(figure=0.5, fire=1.3, pots=0.9, rack=1.9, woodpile=1.0, log=4.0, raft=2.6, dugout=3.6, outrigger=4.6, sail=4.6,
                lightstone=0.6, shelter=3.0, hut=3.4)
    for e in s.get('extras', []):
        occ.append((e['loc'][0], e['loc'][1], EX_R.get(e['type'], 1.0)))

    def free(x, y, r):
        return all((x - ox) ** 2 + (y - oy) ** 2 >= (r + orr) ** 2 for ox, oy, orr in occ)

    k = 0
    for b in s.get('boats', []):
        for _ in range(b.get('count', 1)):
            x = vx - 70 + k * 13 + rng.uniform(-3, 3)
            k += 1
            yb = beach_at(round(x, 1))
            if yb is None:
                continue
            afloat0 = b.get('afloat', False)
            rb = 2.6 if b['type'] == 'raft' else (3.6 if b['type'] == 'dugout' else 4.6)
            yy = yb - (14 if afloat0 else -2.5)
            if not free(x, yy, rb):
                continue
            occ.append((x, yy, rb))
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
            if not afloat:
                ob['grounded'] = True
                ob['rest'] = True
            ob.rotation_euler = (0, 0, rng.uniform(-0.35, 0.35) + (math.pi / 2 if afloat else 0))
    for k in range(vil.get('racks', 0)):
        if not huts:
            break
        hx, hy, _ = huts[(k * 3) % len(huts)]
        for _ in range(30):
            x, y = hx + rng.uniform(-6, 6), hy - 7 - rng.uniform(0, 3)
            if free(x, y, 1.9):
                break
        else:
            continue
        occ.append((x, y, 1.9))
        o = Pr.drying_rack('干し棚%d' % k, seed + k)
        o.location = (x, y, ter.height_at(x, y))
        o['grounded'] = True
        o.rotation_euler = (0, 0, rng.uniform(-0.4, 0.4))
    for k in range(vil.get('pots', 0)):
        if not huts:
            break
        hx, hy, _ = huts[(k * 5 + 1) % len(huts)]
        for _ in range(30):
            px, py = hx + rng.uniform(1.5, 5), hy - rng.uniform(4, 6)
            if free(px, py, 0.9):
                break
        else:
            continue
        occ.append((px, py, 0.9))
        o = Pr.pots('土器%d' % k, seed + k)
        o.location = (px, py, ter.height_at(px, py))
        o['grounded'] = True
    fires = []
    for k in range(vil.get('fires', 0)):
        if not huts:
            break
        # 焚き火は家の前の浜寄り（画面から見える所）
        hx, hy, _ = huts[(k * 4 + 2) % len(huts)]
        for _ in range(30):
            x = hx + rng.uniform(-4, 4)
            yb = beach_at(round(x, 1), 1.6) or hy - 6
            y = min(hy - 6, yb + 6) + rng.uniform(-1, 1)
            if free(x, y, 1.3 + 1.2):     # 火のまわりに座る人の場所も空けておく
                break
        else:
            continue
        occ.append((x, y, 1.3))
        o = Pr.fire('焚き火%d' % k, seed + k, smoke=k < vil.get('smoke', 2), strength=s.get('fire_strength', 60.0))
        o.location = (x, y, ter.height_at(x, y))
        o['grounded'] = True
        fires.append((x, y))
    poses = ['stand', 'carry', 'bend', 'sit', 'look', 'stand']   # 止まっている人は、歩く途中の形にしない
    for k in range(vil.get('people', 0)):
        ok = False
        for tries in range(40):
            if fires and k % 3 == 0:
                fx, fy = fires[k % len(fires)]
                a = rng.uniform(0, 2 * math.pi)
                x, y, pose = fx + math.cos(a) * 1.9, fy + math.sin(a) * 1.9, 'sit'
                face = math.atan2(fy - y, fx - x) - math.pi / 2
                r_ = 0.75
                occ_ok = all((x - ox) ** 2 + (y - oy) ** 2 >= (r_ + orr) ** 2 for ox, oy, orr in occ if (ox, oy) != (fx, fy))
            elif huts:
                hx, hy, _ = huts[rng.randrange(len(huts))]
                x, y = hx + rng.uniform(-8, 8), hy + rng.uniform(-10, -3)
                pose = poses[k % len(poses)]
                face = rng.uniform(0, 2 * math.pi)
                r_ = 0.9 if pose == 'bend' else 0.55
                occ_ok = free(x, y, r_)
            else:
                break
            if occ_ok:
                ok = True
                break
        if not ok:
            continue
        occ.append((x, y, r_))
        o = P.figure('人%d' % k, seed * 7 + k, pose=pose, child=rng.random() < 0.2, phase=rng.random())
        o.location = (x, y, ter.height_at(x, y))
        o['grounded'] = True
        o.rotation_euler = (0, 0, face)
    # 潮麦の浅瀬（追加検証の世界）：水深0.5〜1.5mの所に群生
    tw = s.get('tidewheat')
    if tw:
        tcoll = scatter.library('潮麦の型')
        for k in range(3):
            V.tidewheat('潮麦%d' % k, seed * 70 + k, coll=tcoll)
        items = []
        for _ in range(int(40000 * tw.get('density', 1.0))):
            x, y = rng.uniform(-300, 300), rng.uniform(-30, 160)
            h = ter.height_at(x, y)
            if -1.5 < h < -0.5 and noise.fractal(Vector((x / 30, y / 30, 9.0)), 0.6, 2.0, 3) > -0.15:
                items.append((x, y, h, rng.randrange(3), rng.uniform(0.8, 1.15), rng.uniform(0, 6.3)))
        scatter.instances('潮麦', tcoll, items)
    place_extras(s.get('extras', []), ter, seed)
    # 地面に置く物は、実際の地面の面（三角形）にぴったり乗せる（高さの計算値と面の間には数cmの差がある）
    tree = ground_tree()
    for ob in list(bpy.data.objects):
        if ob.get('grounded') and 'embed_ok' in ob.keys():
            seat_on_lowest(ob, tree)       # 家：下り側が浮かないように（上り側は土台として埋まる）
            continue
        if ob.get('grounded') and ob.parent is None and 'move' not in ob.keys():
            if ob.get('rest'):
                rest_on_ground(ob, tree)    # 舟・いかだ：いくつかの支え（船体と浮き木など）が地面につく向き
            else:
                # 斜面では、地面の傾きに合わせて少し傾けてから乗せる（人は 6°まで：両足が地面につく）
                tilt_to_ground(ob, tree, 6.0 if 'sole_L' in ob.keys() else 15.0)
            settle(ob, tree)
    for k, isl in enumerate(s.get('islands', [])):
        island_silhouette('島影%d' % k, seed + k, isl['radius'], isl['height'], isl['loc'])
    water.sea_box(s.get('algae', 1.0))
    water.foam(ter)
    return ter


def flatten_paths(ter, extras, half=1.4, blend=1.6):
    """歩く人の通り道を、横方向に平らな踏み分け道にする（両足が同じ高さの地面に乗る）。
    道の中心の高さは元の地形のまま（道に沿った上り下りは残る）"""
    for e in extras:
        if e.get('type') != 'figure' or 'move' not in e or e.get('pose') not in ('walk', 'carrywalk'):
            continue
        a = np.array(e['loc'][:2], float)
        d = np.array(e['move'][:2], float)
        L = np.linalg.norm(d)
        if L < 0.1:
            continue
        u = d / L
        nrm = np.array([-u[1], u[0]])
        P0 = np.stack([ter.X - a[0], ter.Y - a[1]], -1)
        t = np.clip(P0 @ u, -2.0, L + 2.0)
        lat = np.abs(P0 @ nrm)
        # 中心線の高さ（格子の上で、道に沿った距離 t ごとに）
        ts = np.linspace(-2.0, L + 2.0, 60)
        hs = np.array([ter.height_at(a[0] + u[0] * q, a[1] + u[1] * q) for q in ts])
        hc = np.interp(t, ts, hs)
        w = np.clip(1 - (lat - half) / blend, 0, 1)
        w[(P0 @ u < -3.0) | (P0 @ u > L + 3.0)] = 0
        ter.H[:] = ter.H * (1 - w) + hc * w


def ground_tree():
    """地形の面の判定（BVH）"""
    ob = bpy.data.objects.get('地形')
    if ob is None:
        return None
    bpy.context.view_layer.update()
    return BVHTree.FromObject(ob, bpy.context.evaluated_depsgraph_get())


def _world_points(objs):
    dg = bpy.context.evaluated_depsgraph_get()
    out = []
    for o in objs:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        n = len(me.vertices)
        if n:
            co = np.empty(n * 3, np.float32)
            me.vertices.foreach_get('co', co)
            co = co.reshape(-1, 3)
            mw = np.array(ev.matrix_world)
            out.append(co @ mw[:3, :3].T + mw[:3, 3])
        ev.to_mesh_clear()
    return np.concatenate(out) if out else np.zeros((0, 3))


def tilt_to_ground(obj, tree, max_deg, band=0.2):
    """物の下の方の頂点の真下の地面に平面を当てはめ、その傾きに合わせて物を傾ける（max_deg まで）"""
    if tree is None:
        return
    bpy.context.view_layer.update()
    parts = [obj] + [c for c in obj.children_recursive if c.type == 'MESH' and not c.get('nocheck')
                     and not any(k in c.name for k in NOCHECK_NAMES)]
    P_ = _world_points(parts)
    if len(P_) < 3:
        return
    sel = P_[P_[:, 2] < P_[:, 2].min() + band]
    if len(sel) > 600:
        sel = sel[np.linspace(0, len(sel) - 1, 600).astype(int)]
    g = []
    for x, y, z in sel:
        h = tree.ray_cast(Vector((float(x), float(y), float(z) + 100.0)), Vector((0, 0, -1)), 400.0)
        if h[0] is not None:
            g.append((x, y, h[0].z))
    g = np.array(g)
    if len(g) < 3 or np.ptp(g[:, 0]) + np.ptp(g[:, 1]) < 0.05:
        return
    A = np.c_[g[:, 0] - g[:, 0].mean(), g[:, 1] - g[:, 1].mean(), np.ones(len(g))]
    a, b, _ = np.linalg.lstsq(A, g[:, 2], rcond=None)[0]
    n = Vector((-a, -b, 1.0)).normalized()
    ang = math.degrees(math.acos(max(-1.0, min(1.0, n.z))))
    if ang < 0.3:
        return
    if ang > max_deg:
        n = Vector((0, 0, 1)).slerp(n, max_deg / ang).normalized()
    tilt = Vector((0, 0, 1)).rotation_difference(n).to_matrix()
    obj.rotation_euler = (tilt @ obj.rotation_euler.to_matrix()).to_euler()


def _ground_gaps(obj, tree, band, cap=2500):
    bpy.context.view_layer.update()
    parts = [obj] + [c for c in obj.children_recursive if c.type == 'MESH' and not c.get('nocheck')
                     and not any(k in c.name for k in NOCHECK_NAMES)]
    P_ = _world_points(parts)
    if not len(P_):
        return None
    sel = P_[P_[:, 2] < P_[:, 2].min() + band]
    if len(sel) > cap:
        sel = sel[np.linspace(0, len(sel) - 1, cap).astype(int)]
    gaps = []
    for x, y, z in sel:
        h = tree.ray_cast(Vector((float(x), float(y), float(z) + 100.0)), Vector((0, 0, -1)), 400.0)
        if h[0] is not None:
            gaps.append(z - h[0].z)
    return np.array(gaps) if gaps else None


def rest_on_ground(obj, tree, max_deg=10.0, step=2.0, band=0.5, n=500):
    """かたい物（舟・いかだ）：少しずつ傾けてみて、下の方の頂点と地面のすき間のばらつきが一番小さい向きにする
    （支えが何か所も地面につく＝置かれた物らしい向き）。そのあと settle で高さを合わせる"""
    if tree is None:
        return
    from mathutils import Euler
    bpy.context.view_layer.update()
    parts = [obj] + [c for c in obj.children_recursive if c.type == 'MESH' and not c.get('nocheck')
                     and not any(k in c.name for k in NOCHECK_NAMES)]
    P_ = _world_points(parts)
    if not len(P_):
        return
    low = P_   # 全体（何も沈まない高さを決めるため）
    if len(low) > n:
        low = low[np.linspace(0, len(low) - 1, n).astype(int)]
    o = np.array(obj.location)
    best = None
    angs = np.arange(-max_deg, max_deg + 1e-6, step)
    for ax in angs:
        for ay in angs:
            Rd = np.array(Euler((math.radians(ax), math.radians(ay), 0.0)).to_matrix())
            pts = (low - o) @ Rd.T + o
            gaps, zs_ = [], []
            for x, y, z in pts:
                h = tree.ray_cast(Vector((float(x), float(y), float(z) + 100.0)), Vector((0, 0, -1)), 400.0)
                if h[0] is not None:
                    gaps.append(z - h[0].z)
                    zs_.append(z)
            if len(gaps) < 3:
                continue
            g = np.array(gaps)
            # 何も地面に沈まない高さまで上げたとき（全体を -min だけ上げる）、一番低い所（下から20cm）が地面からどれだけ浮くか
            zl = np.array(zs_)
            lift = -g.min()
            low_gap = float((g[zl < zl.min() + 0.2] + lift).min()) if (zl < zl.min() + 0.2).any() else 1e9
            key = (round(low_gap, 3), abs(ax) + abs(ay))
            if best is None or key < best[0]:
                best = (key, ax, ay)
    if best is None:
        return
    Rd = Euler((math.radians(best[1]), math.radians(best[2]), 0.0)).to_matrix()
    obj.rotation_euler = (Rd @ obj.rotation_euler.to_matrix()).to_euler()


def seat_on_lowest(obj, tree, band=0.3):
    """家など：下の方の頂点のうち一番浮いている所が地面に触れる高さまで下げる。
    上り側が地面に埋まる深さは embed_ok として点検に伝える（斜面に建つ家の土台）"""
    if tree is None:
        return
    g = _ground_gaps(obj, tree, band)
    if g is None:
        return
    obj.location.z -= float(g.max())
    obj['embed_ok'] = round(float(g.max() - g.min()) + 0.02, 3)


def settle(obj, tree, gap=0.0, band=100.0, cap=4000):
    """物の下の方の頂点を真上から地面へ打ち、どれも地面より下にならず、少なくとも1点が地面に触れる高さへ動かす
    （めり込みも浮きも消す。blender-video-physics-guard の settle を、下の方の頂点ごとに調べる形にしたもの）"""
    if tree is None:
        return False
    bpy.context.view_layer.update()
    parts = [obj] + [c for c in obj.children_recursive if c.type == 'MESH' and not c.get('nocheck')
                     and not any(k in c.name for k in NOCHECK_NAMES)]
    P_ = _world_points([o for o in parts if o.type == 'MESH'])
    if not len(P_):
        return False
    lo = P_[:, 2].min()
    sel = P_[P_[:, 2] < lo + band]
    if len(sel) > cap:
        sel = sel[np.linspace(0, len(sel) - 1, cap).astype(int)]
    best = None
    for x, y, z in sel:
        h = tree.ray_cast(Vector((float(x), float(y), float(z) + 100.0)), Vector((0, 0, -1)), 400.0)
        if h[0] is not None:
            d = h[0].z - z
            best = d if best is None else max(best, d)
    if best is None:
        return False
    obj.location.z += best + gap
    return True


def place_extras(extras, ter, seed):
    """カットごとに、決まった場所へ置くもの（近くで見せる道具・舟・人など）"""
    placed = []
    for k, e in enumerate(extras):
        t = e['type']
        x, y = e['loc'][0], e['loc'][1]
        ground = ter.height_at(x, y) if ter is not None else 0.0
        if t == 'figure' and ter is not None and not e.get('float') and len(e['loc']) < 3 and not e.get('noshift'):
            for _ in range(60):
                if ground >= -0.45:
                    break
                y += 0.5
                ground = ter.height_at(x, y)
        z = e['loc'][2] if len(e['loc']) > 2 else (max(ground, 0.0) + (0.05 if ground < 0 else 0.0) if e.get('float') else ground)
        name = '%s_%d' % (t, k)
        sd = seed * 1000 + k
        if t == 'fire':
            o = Pr.fire(name, sd, smoke=e.get('smoke', True), strength=e.get('strength', 80.0))
        elif t == 'pots':
            o = Pr.pots(name, sd, n=e.get('n', 5))
        elif t == 'rack':
            o = Pr.drying_rack(name, sd)
        elif t == 'woodpile':
            o = Pr.woodpile(name, sd)
        elif t == 'log':
            o = Pr.log_carving(name, sd)
        elif t == 'raft':
            o = Bo.raft(name, sd)
        elif t == 'dugout':
            o = Bo.dugout(name, sd, e.get('length', 6.5))
        elif t in ('outrigger', 'sail'):
            o = Bo.outrigger(name, sd, e.get('length', 8.5), sail=t == 'sail')
        elif t == 'figure':
            pose = e.get('pose', 'stand')
            cyc = 16 if pose in ('walk', 'carrywalk') else (8 if pose == 'paddle' else 0)   # 歩く足は細かく（間をつなぐと足が下がるので）
            o = P.figure(name, sd, pose=pose, child=e.get('child', False), phase=e.get('phase', 0.0), cycle=cyc)
        elif t == 'lightstone':
            o = Pr.lightstone(name, sd, e.get('size', 0.5))
        elif t == 'shelter':
            o = Pr.shelter(name, sd)
        elif t == 'hut':
            o = Pr.hut(name, sd)
        else:
            continue
        o.location = (x, y, z + e.get('dz', 0.0))
        o.rotation_euler = (math.radians(e.get('tilt', 0.0)), 0, math.radians(e.get('rot', 0.0)))
        if e.get('scale'):
            o.scale = (e['scale'],) * 3
        placed.append(o)
        if 'parent' in e:
            # parent の名前の物の子にする。loc・rot はその物から見た位置と向き（舟の上の位置をそのまま書ける）
            o.parent = bpy.data.objects[e['parent']]
            o.matrix_parent_inverse.identity()
            o.location = tuple(e['loc'][:3])
            o['in_boat'] = True
        elif 'boat' in e:
            # 舟に乗る人は舟の子にする（一緒に動き、ずれない）
            boat = placed[e['boat']]
            bpy.context.view_layer.update()
            mw = o.matrix_world.copy()
            o.parent = boat
            o.matrix_parent_inverse = boat.matrix_world.inverted()
            o.matrix_world = mw
            o['in_boat'] = True
        elif 'move' in e:
            o['move'] = e['move']
        if t in ('figure', 'fire', 'pots', 'rack', 'woodpile', 'log', 'shelter', 'hut', 'raft', 'dugout', 'outrigger', 'sail', 'lightstone') \
                and ter is not None and not e.get('float') \
                and len(e['loc']) < 3 and 'boat' not in e and 'parent' not in e:
            o['grounded'] = True   # 浅い水の中に立つ人も、海の底に立つ
            if t in ('raft', 'dugout', 'outrigger', 'sail') and not e.get('tilt'):
                o['rest'] = True


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
            f = P.figure('乗り手%d_%d' % (k, j), seed * 3 + k * 10 + j, pose='paddle' if j else 'sit', phase=j * 0.3, cycle=8 if j else 0)
            f.parent = ob
            f.location = (0.0, -1.6 + j * 1.3, -0.1)
        boats.append((ob, b))
    for k, isl in enumerate(s.get('islands', [])):
        island_silhouette('島影%d' % k, seed + k, isl['radius'], isl['height'], isl['loc'])
    return oc, md, boats


# ---------------------------------------------------------------- 島々の空撮（計算の島の形から）

def island_material():
    from kit.util import new_material, node, link, map_range
    m = bpy.data.materials.get('島の地表')
    if m:
        return m
    m, nt = new_material('島の地表')
    geo = node(nt, 'ShaderNodeNewGeometry', (-900, 0))
    sep = node(nt, 'ShaderNodeSeparateXYZ', (-700, 0))
    link(nt, geo.outputs['Position'], sep.inputs[0])
    sn = node(nt, 'ShaderNodeSeparateXYZ', (-700, -250))
    link(nt, geo.outputs['Normal'], sn.inputs[0])
    tc = node(nt, 'ShaderNodeTexCoord', (-900, 300))
    nz = node(nt, 'ShaderNodeTexNoise', (-700, 300), Scale=0.004, Detail=8.0)
    link(nt, tc.outputs['Object'], nz.inputs['Vector'])
    nz2 = node(nt, 'ShaderNodeTexNoise', (-700, 500), Scale=0.05, Detail=6.0)
    link(nt, tc.outputs['Object'], nz2.inputs['Vector'])
    sand = (0.42, 0.37, 0.27, 1)
    forest = M.mix_color(nt, nz2.outputs['Fac'], (0.012, 0.03, 0.008, 1), (0.03, 0.06, 0.015, 1), (-400, 300))
    rock = M.mix_color(nt, nz.outputs['Fac'], (0.06, 0.055, 0.05, 1), (0.14, 0.12, 0.10, 1), (-400, 100))
    col = M.mix_color(nt, map_range(nt, sep.outputs['Z'], 2.5, 6.0), sand, forest, (-200, 300))
    steep = map_range(nt, sn.outputs['Z'], 0.75, 0.55)
    col = M.mix_color(nt, steep, col, rock, (0, 300))
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled', (200, 200))
    link(nt, col, bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = 0.9
    from kit.util import finish
    finish(nt, bsdf.outputs[0], (600, 200))
    return m


def shallow_material():
    from kit.util import new_material, node, link, map_range
    m = bpy.data.materials.get('浅瀬の色')
    if m:
        return m
    m, nt = new_material('浅瀬の色')
    at = node(nt, 'ShaderNodeAttribute', (-600, 0), attribute_name='f')
    a = map_range(nt, at.outputs['Fac'], 0.0, 1.0, 0.75, 0.0)
    em = node(nt, 'ShaderNodeBsdfPrincipled', (-200, 100))
    em.inputs['Base Color'].default_value = (0.05, 0.32, 0.30, 1)
    em.inputs['Roughness'].default_value = 0.05
    tr = node(nt, 'ShaderNodeBsdfTransparent', (-200, -100))
    mix = node(nt, 'ShaderNodeMixShader', (100, 0))
    link(nt, a, mix.inputs[0])
    link(nt, tr.outputs[0], mix.inputs[1])
    link(nt, em.outputs[0], mix.inputs[2])
    out = node(nt, 'ShaderNodeOutputMaterial', (300, 0))
    link(nt, mix.outputs[0], out.inputs['Surface'])
    return m


def island_from_world(name, rho_km, hmax, seed, loc, shelf_km=2.0):
    """計算の島の形（方位ごとの半径 km）から、島の地形（m）を作る"""
    rho = np.asarray(rho_km)[::2] * 1000.0
    nth = len(rho)
    rings = np.concatenate([np.linspace(0, 0.9, 30) ** 0.8, np.linspace(0.91, 1.0, 10), [1.03]])
    th = np.linspace(0, 2 * math.pi, nth, endpoint=False)
    verts = []
    off = Vector((seed * 1.3, seed * 0.7, 0))
    for f in rings:
        for k in range(nth):
            r = rho[k] * f
            x, y = r * math.sin(th[k]), r * math.cos(th[k])
            n = noise.fractal(Vector((x / 4000, y / 4000, 0)) + off, 0.55, 2.0, 6)
            if f <= 1.0:
                z = hmax * max(0.0, 1 - f) ** 1.25 * (0.8 + 0.4 * n) + 1.6 * min(1.0, (1 - f) / 0.02)
            else:
                z = -30.0
            verts.append((x, y, z))
    faces = []
    for i in range(len(rings) - 1):
        for k in range(nth):
            a, b2 = i * nth + k, i * nth + (k + 1) % nth
            faces.append([a, b2, b2 + nth, a + nth])
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    me.polygons.foreach_set('use_smooth', np.ones(len(me.polygons), bool))
    me.materials.append(island_material())
    o = bpy.data.objects.new(name, me)
    link_object(o)
    o.location = loc
    # 浅瀬の色の輪
    verts2, faces2, fval = [], [], []
    for j, f in enumerate(np.linspace(0, 1, 6)):
        for k in range(nth):
            r = rho[k] * 0.995 + f * shelf_km * 1000
            verts2.append((r * math.sin(th[k]), r * math.cos(th[k]), 0.15))
            fval.append(f)
    for j in range(5):
        for k in range(nth):
            a, b2 = j * nth + k, j * nth + (k + 1) % nth
            faces2.append([a, b2, b2 + nth, a + nth])
    me2 = bpy.data.meshes.new(name + '浅瀬')
    me2.from_pydata(verts2, [], faces2)
    at = me2.attributes.new('f', 'FLOAT', 'POINT')
    at.data.foreach_set('value', np.array(fval, np.float32))
    me2.materials.append(shallow_material())
    o2 = bpy.data.objects.new(name + '浅瀬', me2)
    link_object(o2)
    o2.location = loc
    o2.visible_shadow = False
    return o


def build_islands(s):
    """計算の世界の島々を、実際の位置と形で並べる（空撮用）"""
    import world as W
    w = W.build_world(s['terrain'])
    lay, props = w['lay'], w['props']
    c = s['center_island']
    lat0, lon0 = lay['lat'][c], lay['lon'][c]
    d = W.gc_dist(lat0, lon0, lay['lat'], lay['lon'])
    near = np.nonzero(d < s.get('radius_km', 150))[0]
    for i in near:
        brg = W.bearing(lat0, lon0, lay['lat'][i], lay['lon'][i])
        x, y = d[i] * math.sin(brg) * 1000, d[i] * math.cos(brg) * 1000
        island_from_world('島%d' % i, lay['rho'][i], float(props['hmax'][i]) * s.get('relief', 1.0), int(i),
                          (x, y, 0), shelf_km=float(props['shelf_w'][i]) * 0.5)
    oc, md = water.ocean(size=600, wave_scale=s.get('wave', 0.6), seed=s.get('seed', 7), repeat=3)
    # 波のある海は、カメラの下に置く（島から遠い所から撮るカットがある）
    cx, cy = s['camera']['loc'][0], s['camera']['loc'][1]
    oc.location = (cx - 900 + 500, cy - 900 + 500 + 400, 0) if abs(cx) > 3000 or abs(cy) > 3000 else oc.location
    # 空撮は数十〜数百 km 先まで見えるので、遠くの海を広げ、霞を薄く、カメラの描く距離を延ばす
    far = bpy.data.objects.get('遠くの海')
    if far is not None:
        far.scale = (2000.0, 2000.0, 1.0)   # 高い所からでも、海の果てが地平線のすぐ下まで届くように
    from kit.util import set_haze
    set_haze(90000.0, 0.35)
    s['camera'].setdefault('clip', 3.0e6)
    boats = []
    for k, b in enumerate(s.get('boats', [])):
        ob = Bo.outrigger('舟%d' % k, s.get('seed', 7) + k, b.get('length', 9.0), sail=b.get('sail', True))
        ob.location = Vector(b['loc'])
        ob.rotation_euler = (0, 0, math.radians(b.get('heading', 0)))
        boats.append((ob, b))
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

def ground_relative(c, ter):
    """海岸のカットでは、カメラと注視点の高さを「その場所の地面（海なら海面）からの高さ」とみなす。
    地形は種ごとに少しずつ違うので、絶対の高さで書くと地面に埋まることがある"""
    if ter is None or c.get('absolute'):
        return c
    c = dict(c)
    for k in ('loc', 'target', 'loc2', 'target2'):
        if k in c:
            x, y, z = c[k]
            c[k] = [x, y, max(ter.height_at(x, y), 0.0) + z]
    return c


def setup_camera(s, frames, ter=None):
    cam = bpy.data.objects.new('カメラ', bpy.data.cameras.new('カメラ'))
    link_object(cam)
    c = ground_relative(s['camera'], ter)
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


def linear_keys(ob):
    """位置のキーを直線でつなぐ（ベジェの行き過ぎで地面にめり込まないように）"""
    ad = ob.animation_data
    if not (ad and ad.action):
        return
    act = ad.action
    curves = list(getattr(act, 'fcurves', []) or [])
    for layer in getattr(act, 'layers', []):          # Blender 4.4 以降の重ねられるアクション
        for strip in layer.strips:
            for cb in getattr(strip, 'channelbags', []):
                curves += list(cb.fcurves)
    for fc in curves:
        for kp in fc.keyframe_points:
            kp.interpolation = 'LINEAR'


def cycle_weights(f, n, period):
    """フレーム f での形のキーの重み（1〜n-1 番。0 番は元の形）"""
    ph = ((f - 1) / period) % 1.0 * n
    i0 = int(ph) % n
    i1 = (i0 + 1) % n
    t = ph - int(ph)
    return [(1 - t if k == i0 else 0.0) + (t if k == i1 else 0.0) for k in range(n)]


def cycle_period(ob, seconds, fps=24):
    if 'move' in ob.keys() and not ob.get('in_boat'):
        speed = Vector(ob['move']).length / max(seconds, 1e-6)
        return fps * float(ob.get('stride', 1.45)) / max(speed, 0.05)
    return fps * 1.7   # こぐ：1.7秒で1回


def follow_ground(ob, mv, frames, seconds, tree):
    """地面を歩く人：フレームごとに、地面についている方の足の下の地面へ高さを合わせてキーを打つ
    （坂を下っても浮かない・上っても埋まらない）。足の形は形のキーから計算する（フレームを進めずに済む）"""
    start = ob.location.copy()
    kbs = ob.data.shape_keys.key_blocks if ob.data.shape_keys else None
    n = int(ob.get('cycle', 0))
    soles = {sd: list(ob.get('sole_' + sd, [])) for sd in ('L', 'R')}
    keyco = {}
    if kbs and n:
        for sd, ids in soles.items():
            for k in range(n):
                co = np.empty(len(kbs[k].data) * 3, np.float32)
                kbs[k].data.foreach_get('co', co)
                keyco[(sd, k)] = co.reshape(-1, 3)[ids]
    period = cycle_period(ob, seconds)
    R = ob.rotation_euler.to_matrix()
    for f in range(1, frames + 1):
        t = (f - 1) / max(1, frames - 1)
        pos = start + mv * t
        best = None
        if keyco:
            w = cycle_weights(f, n, period)
            feet = {}
            for sd in ('L', 'R'):
                base = keyco[(sd, 0)]
                loc = base + sum(w[k] * (keyco[(sd, k)] - base) for k in range(1, n))
                feet[sd] = loc
            sd = min(feet, key=lambda q: feet[q][:, 2].min())   # 地面についている方の足
            low = feet[sd]
            other = 'R' if sd == 'L' else 'L'
            if feet[other][:, 2].min() < low[:, 2].min() + 0.03:      # 両足が地面近く（着地の瞬間）：どちらも地面に沈まないように
                low = np.concatenate([low, feet[other]])
            for p_ in low:
                wp = Vector((pos.x, pos.y, 0.0)) + R @ Vector(p_)
                h = tree.ray_cast(Vector((wp.x, wp.y, wp.z + 100.0)), Vector((0, 0, -1)), 400.0)
                if h[0] is not None:
                    d = h[0].z - wp.z
                    best = d if best is None else max(best, d)
        else:
            h = tree.ray_cast(Vector((pos.x, pos.y, pos.z + 100.0)), Vector((0, 0, -1)), 400.0)
            best = (h[0].z) if h[0] is not None else pos.z
        ob.location = (pos.x, pos.y, best if best is not None else pos.z)
        ob.keyframe_insert('location', frame=f)
    linear_keys(ob)


def _key_points(ob, ids):
    """形のキーごとの、決めた頂点の位置（キーの番号 → 点の並び）"""
    kbs = ob.data.shape_keys.key_blocks if ob.data.shape_keys else None
    if not kbs:
        co = np.empty(len(ob.data.vertices) * 3, np.float32)
        ob.data.vertices.foreach_get('co', co)
        return [co.reshape(-1, 3)[ids]]
    out = []
    for k in range(len(kbs)):
        co = np.empty(len(kbs[k].data) * 3, np.float32)
        kbs[k].data.foreach_get('co', co)
        out.append(co.reshape(-1, 3)[ids])
    return out


def add_paddles(frames, seconds):
    """こぐ人に櫂（かい）を持たせる。両手を通る向きに柄を合わせ、こぐ動き（形のキー）に合わせてフレームごとにキーを打つ"""
    for ob in list(bpy.data.objects):
        if ob.get('pose') != 'paddle' or 'hand_L' not in ob.keys():
            continue
        hl = _key_points(ob, list(ob['hand_L']))
        hr = _key_points(ob, list(ob['hand_R']))
        n = len(hl)
        period = cycle_period(ob, seconds)
        pd = P.paddle_tool(ob.name + '櫂')
        pd.parent = ob
        pd.matrix_parent_inverse.identity()
        pd.rotation_mode = 'QUATERNION'
        for f in range(1, max(1, frames) + 1):
            if n > 1:
                w = cycle_weights(f, n, period)
                L = hl[0] + sum(w[k] * (hl[k] - hl[0]) for k in range(1, n))
                R = hr[0] + sum(w[k] * (hr[k] - hr[0]) for k in range(1, n))
            else:
                L, R = hl[0], hr[0]
            a, b = Vector(L.mean(0)), Vector(R.mean(0))
            up, lo = (a, b) if a.z > b.z else (b, a)
            d = (up - lo).normalized() if (up - lo).length > 1e-4 else Vector((0, 0, 1))
            pd.location = lo - d * 0.45          # 下の手が柄の 0.45m の所を握る（刃は水の中へ）
            pd.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(d)
            if frames > 1:
                pd.keyframe_insert('location', frame=f)
                pd.keyframe_insert('rotation_quaternion', frame=f)


def animate_cycles(frames, seconds, fps=24):
    """歩く・こぐ人の形のキーを、時間に合わせて切り替える。
    歩く人は、進む速さ÷1周期の歩幅で周期を決める（足が地面をすべらないように）"""
    for ob in list(bpy.data.objects):
        if 'cycle' not in ob.keys():
            continue
        n = int(ob['cycle'])
        period = cycle_period(ob, seconds, fps)
        for pname in ob['cycle_parts']:
            part = bpy.data.objects.get(pname)
            if part is None or part.data.shape_keys is None:
                continue
            kbs = part.data.shape_keys.key_blocks
            for f in range(1, frames + 1):
                w = cycle_weights(f, n, period)
                for k in range(1, n):
                    kbs[k].value = w[k]
                    kbs[k].keyframe_insert('value', frame=f)


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
    # 新しく打つキーは直線でつなぐ（ベジェの行き過ぎで、接地している物が地面にめり込まないように）
    bpy.context.preferences.edit.keyframe_new_interpolation_type = 'LINEAR'
    kind = s['kind']
    fps = 24
    frames = int(round(s.get('seconds', 0) * fps)) if s.get('anim') and not args.still else 1
    ocean_md = None
    boats = []
    ter = None
    if kind == 'coast':
        ter = build_coast(s)
    elif kind == 'opensea':
        _, ocean_md, boats = build_opensea(s)
    elif kind == 'islands':
        _, ocean_md, boats = build_islands(s)
    elif kind == 'planet':
        build_planet(s)
    if kind in ('opensea', 'islands') and s.get('extras'):
        place_extras(s['extras'], None, s.get('seed', 7))
    sk = s.get('sky')
    if sk:
        sky.setup(sk.get('time', 'dusk'), sk.get('azimuth', -120), sk.get('elevation'), sk.get('cloud', 0.5),
                  sk.get('storm', 0.0), s.get('seed', 7))
    setup_camera(s, frames, ter)
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, max(1, frames)
    if frames > 1:
        sc.render.use_persistent_data = kind != 'opensea'
        if ocean_md is not None:
            ocean_md.time = 0.0
            ocean_md.keyframe_insert('time', frame=1)
            ocean_md.time = s['seconds']
            ocean_md.keyframe_insert('time', frame=frames)
        tree = ground_tree() if kind == 'coast' else None
        for ob in bpy.data.objects:
            if 'move' in ob.keys():
                mv = Vector(ob['move'])
                if tree is not None and ob.get('grounded'):
                    follow_ground(ob, mv, frames, s['seconds'], tree)
                    continue
                ob.keyframe_insert('location', frame=1)
                ob.location = ob.location + mv
                ob.keyframe_insert('location', frame=frames)
                linear_keys(ob)
        animate_cycles(frames, s['seconds'])
        for ob, b in boats:
            v = b.get('speed', 2.0)
            hd = math.radians(b.get('heading', 0))
            d = Vector((-math.sin(hd), math.cos(hd), 0)) * v * s['seconds']
            ob.keyframe_insert('location', frame=1)
            ob.location = ob.location + d
            ob.keyframe_insert('location', frame=frames)
    elif s.get('anim') and args.still and ocean_md is not None:
        ocean_md.time = s['seconds'] / 2
    add_paddles(frames, s.get('seconds', 1))
    render_settings(args, s)
    mark_for_check(kind)
    return frames


NOCHECK_NAMES = ('海', '泡', '煙', '炎', '島影', '浅瀬', '雲', '大気', '星', '空')


def mark_for_check(kind):
    """scene_check.py のための印：地面（floor）・調べない物（nocheck：水・煙・炎・遠景・空）"""
    for ob in bpy.data.objects:
        if ob.type != 'MESH':
            continue
        if ob.name == '地形' or (kind == 'islands' and ob.name.startswith('島') and not ob.name.endswith('浅瀬') and '影' not in ob.name):
            ob['floor'] = True
        elif any(k in ob.name for k in NOCHECK_NAMES):
            ob['nocheck'] = True
        elif kind == 'planet' and ob.name != '惑星':
            ob['nocheck'] = True


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
        if args.resume and os.path.exists(os.path.join(out, 'cut%s.png' % s['id'])):
            continue
        t0 = time.time()
        frames = build(s, args)
        sc = bpy.context.scene
        print('カット %s（%s）組み立て %.1fs・%d コマ' % (s['id'], s.get('title', ''), time.time() - t0, frames), flush=True)
        if args.blend or args.build_only:
            bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, 'cut%s.blend' % s['id']))
        if args.build_only:
            continue
        t1 = time.time()
        if args.frames and frames > 1:
            want = []
            for w in args.frames.split(','):
                w = w.strip()
                want.append({'first': 1, 'mid': (frames + 1) // 2, 'last': frames}.get(w) or int(w))
            for f in want:
                sc.frame_set(f)
                sc.render.filepath = os.path.join(out, 'cut%s_f%04d.png' % (s['id'], f))
                bpy.ops.render.render(write_still=True)
            print('  確かめのコマ %s・%.1fs' % (want, time.time() - t1), flush=True)
            continue
        if frames > 1:
            d = os.path.join(out, 'cut%s' % s['id'])
            os.makedirs(d, exist_ok=True)
            sc.render.filepath = os.path.join(d, 'f_')
            sc.frame_step = max(1, args.step)
            sc.render.use_overwrite = not args.resume
            sc.render.use_placeholder = args.resume
            bpy.ops.render.render(animation=True)
            done = len(range(1, frames + 1, max(1, args.step)))
            print('  動画 %d コマ（%d コマおき）・%.1fs（1コマ %.1fs）→ %s' % (done, max(1, args.step), time.time() - t1, (time.time() - t1) / done, d), flush=True)
        else:
            sc.render.filepath = os.path.join(out, 'cut%s.png' % s['id'])
            bpy.ops.render.render(write_still=True)
            print('  静止画 %.1fs → %s' % (time.time() - t1, sc.render.filepath), flush=True)


if __name__ == '__main__':
    main()
