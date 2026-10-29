"""並行地球：入り江の海岸・浅瀬・岩・森・木造の集落を、計算データから組み立てて描画する（Blender 5.x / Cycles）

外部の素材は使わず、地形・水・植物・建物をすべてこのスクリプトで作る。同じ引数なら同じ景色になる。

使い方（Blender 本体）:
  blender -b -P scene.py -- --data blender.json --planet reference --year 0 --island D --out d-y0.png
使い方（Python の bpy モジュール）:
  python scene.py -- --data blender.json --planet reference --year 24 --island D --out d-y24.png --preview

--data はスタジオの「Blender用 JSON」（または _dev/export-blender.js の出力）。
--preview は 960×540・少ない試行で速く描く。--blend を付けると編集できる .blend も保存する。
"""
import argparse
import json
import math
import os
import random
import sys
import time

import bpy  # bpy を先に読み込む（Python のパッケージ版では bmesh・mathutils が bpy の後でないと使えない）
import bmesh
import numpy as np
from mathutils import Euler, Matrix, Vector, noise

# ---------------------------------------------------------------- 引数

def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', help='Blender用 JSON')
    ap.add_argument('--planet', default='reference')
    ap.add_argument('--year', type=int, default=0)
    ap.add_argument('--island', default='D')
    ap.add_argument('--out', default='heikou-scene.png')
    ap.add_argument('--blend', default='')
    ap.add_argument('--res', default='1920x1080')
    ap.add_argument('--samples', type=int, default=256)
    ap.add_argument('--preview', action='store_true')
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--sun-elevation', type=float, default=16.0)
    ap.add_argument('--sun-azimuth', type=float, default=-130.0, help='北を0、東回りを正とした度（-130 は南西）')
    ap.add_argument('--camera', default='drone', choices=['drone', 'boat'])
    ap.add_argument('--anim', action='store_true', help='カメラが入り江に近づく動画を描く（--out は連番画像の頭）')
    ap.add_argument('--seconds', type=float, default=12.0)
    ap.add_argument('--fps', type=int, default=24)
    ap.add_argument('--threads', type=int, default=0)
    ap.add_argument('--border', default='', help='画面の一部だけ描く。左,下,右,上（0〜1）')
    ap.add_argument('--gpu', action='store_true', help='GPU で描く（Mac は Metal、ほかは OptiX・CUDA・HIP の順に探す）')
    ap.add_argument('--dry', action='store_true', help='組み立てだけして描かない（家や木の数の確認用）')
    return ap.parse_args(argv)


def load_state(args):
    """計算データから、景色に使う値を取り出す。データがなければ手つかずの状態にする"""
    st = dict(forest=1.0, algae=1.0, tide=0.0, population=200, ships_wood=0, ships_shell=0, storm=0.0,
              tidal_crop=False, label='データなし（手つかずの状態）')
    if not args.data:
        return st
    with open(args.data, encoding='utf-8') as f:
        data = json.load(f)
    planet = next(p for p in data['planets'] if p['id'] == args.planet)
    rec = planet['years'][min(args.year, len(planet['years']) - 1)]
    isl = rec['islands'][args.island]
    ix = isl['index']
    st.update(
        forest=(ix.get('forest') if ix.get('forest') is not None else 100) / 100.0,
        algae=(ix.get('algae') if ix.get('algae') is not None else 100) / 100.0,
        tide=(ix.get('tide') or 0) / 100.0 if planet.get('tidal_crop') else 0.0,
        population=isl['population'], ships_wood=isl['ships']['wood'], ships_shell=isl['ships']['shell'],
        storm=rec.get('storm') or 0.0, tidal_crop=planet.get('tidal_crop', False),
        label='%s・%s年目・%s島' % (planet['name'], rec['year'], args.island))
    return st


# ---------------------------------------------------------------- 共通の道具

def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def new_material(name):
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    return m, nt


def node(nt, kind, loc=(0, 0), **inputs):
    n = nt.nodes.new(kind)
    n.location = loc
    for k, v in inputs.items():
        if k in n.inputs:
            n.inputs[k].default_value = v
        else:
            setattr(n, k, v)
    return n


def link(nt, a, b):
    nt.links.new(a, b)


def link_object(obj, coll=None):
    (coll or bpy.context.scene.collection).objects.link(obj)
    return obj


def mesh_object(name, bm, coll=None):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    if coll is not False:
        link_object(obj, coll)
    return obj


def shade_smooth(obj):
    for p in obj.data.polygons:
        p.use_smooth = True


# ---------------------------------------------------------------- 空気遠近（遠くほど空の色に溶ける）

def haze_group():
    g = bpy.data.node_groups.get('Haze')
    if g:
        return g
    g = bpy.data.node_groups.new('Haze', 'ShaderNodeTree')
    g.interface.new_socket('Shader', in_out='INPUT', socket_type='NodeSocketShader')
    g.interface.new_socket('Shader', in_out='OUTPUT', socket_type='NodeSocketShader')
    gi = node(g, 'NodeGroupInput', (-600, 0))
    go = node(g, 'NodeGroupOutput', (400, 0))
    cam = node(g, 'ShaderNodeCameraData', (-600, -200))
    # 霞の濃さ：1 - exp(-距離/3500) を 0.55 までに抑える
    div = node(g, 'ShaderNodeMath', (-400, -200), operation='DIVIDE')
    div.inputs[1].default_value = -7000.0
    link(g, cam.outputs['View Distance'], div.inputs[0])
    ex = node(g, 'ShaderNodeMath', (-250, -200), operation='EXPONENT')
    link(g, div.outputs[0], ex.inputs[0])
    inv = node(g, 'ShaderNodeMath', (-100, -200), operation='SUBTRACT')
    inv.inputs[0].default_value = 1.0
    link(g, ex.outputs[0], inv.inputs[1])
    lim = node(g, 'ShaderNodeMath', (50, -200), operation='MULTIPLY')
    lim.inputs[1].default_value = 0.5
    link(g, inv.outputs[0], lim.inputs[0])
    em = node(g, 'ShaderNodeEmission', (50, -380))
    em.inputs['Color'].default_value = (0.70, 0.76, 0.86, 1)
    em.inputs['Strength'].default_value = 0.3
    g['haze_emission'] = em.name
    mix = node(g, 'ShaderNodeMixShader', (220, 0))
    link(g, lim.outputs[0], mix.inputs[0])
    link(g, gi.outputs[0], mix.inputs[1])
    link(g, em.outputs[0], mix.inputs[2])
    link(g, mix.outputs[0], go.inputs[0])
    return g


def finish(nt, shader_socket, loc=(600, 0)):
    """霞を通して出力につなぐ"""
    hz = node(nt, 'ShaderNodeGroup', (loc[0] - 200, loc[1]))
    hz.node_tree = haze_group()
    link(nt, shader_socket, hz.inputs[0])
    out = node(nt, 'ShaderNodeOutputMaterial', loc)
    link(nt, hz.outputs[0], out.inputs['Surface'])
    return out


# ---------------------------------------------------------------- 材質

def mat_terrain():
    m, nt = new_material('地形')
    geo = node(nt, 'ShaderNodeNewGeometry', (-1600, 0))
    sep = node(nt, 'ShaderNodeSeparateXYZ', (-1400, 100))
    link(nt, geo.outputs['Position'], sep.inputs[0])
    sepn = node(nt, 'ShaderNodeSeparateXYZ', (-1400, -150))
    link(nt, geo.outputs['Normal'], sepn.inputs[0])
    tc = node(nt, 'ShaderNodeTexCoord', (-1600, -400))
    n1 = node(nt, 'ShaderNodeTexNoise', (-1400, -400), Scale=0.08, Detail=8.0, Roughness=0.6)
    link(nt, tc.outputs['Object'], n1.inputs['Vector'])
    n2 = node(nt, 'ShaderNodeTexNoise', (-1400, -650), Scale=1.6, Detail=10.0, Roughness=0.65)
    link(nt, tc.outputs['Object'], n2.inputs['Vector'])
    n3 = node(nt, 'ShaderNodeTexNoise', (-1400, -1250), Scale=0.018, Detail=4.0, Roughness=0.55)
    link(nt, tc.outputs['Object'], n3.inputs['Vector'])
    warp = node(nt, 'ShaderNodeTexNoise', (-1600, -1450), Scale=0.25, Detail=4.0)
    wv = node(nt, 'ShaderNodeVectorMath', (-1500, -1450), operation='MULTIPLY_ADD')
    link(nt, warp.outputs['Color'], wv.inputs[0]); wv.inputs[1].default_value = (6.0, 6.0, 6.0); link(nt, tc.outputs['Object'], wv.inputs[2])
    link(nt, tc.outputs['Object'], warp.inputs['Vector'])
    vor = node(nt, 'ShaderNodeTexVoronoi', (-1400, -1450), Scale=0.12, feature='DISTANCE_TO_EDGE')
    link(nt, wv.outputs[0], vor.inputs['Vector'])
    strata = node(nt, 'ShaderNodeTexWave', (-1400, -1650), Scale=0.06, Distortion=6.0, Detail=4.0, wave_type='BANDS', bands_direction='Z')
    link(nt, tc.outputs['Object'], strata.inputs['Vector'])
    attr_c = node(nt, 'ShaderNodeAttribute', (-1400, -900), attribute_name='canopy')
    attr_v = node(nt, 'ShaderNodeAttribute', (-1400, -1050), attribute_name='village')

    def rng(src, a, b, lo=0.0, hi=1.0, loc=(0, 0)):
        r = node(nt, 'ShaderNodeMapRange', loc)
        r.inputs['From Min'].default_value = a
        r.inputs['From Max'].default_value = b
        r.inputs['To Min'].default_value = lo
        r.inputs['To Max'].default_value = hi
        r.clamp = True
        link(nt, src, r.inputs['Value'])
        return r.outputs['Result']

    def mixc(fac, c1, c2, loc):
        mx = node(nt, 'ShaderNodeMix', loc, data_type='RGBA')
        link(nt, fac, mx.inputs['Factor'])
        for i, c in ((6, c1), (7, c2)):
            if isinstance(c, tuple):
                mx.inputs[i].default_value = c
            else:
                link(nt, c, mx.inputs[i])
        return mx.outputs[2]

    def mixf(fac, a, b, loc):
        mx = node(nt, 'ShaderNodeMix', loc, data_type='FLOAT')
        link(nt, fac, mx.inputs['Factor'])
        for i, v in ((2, a), (3, b)):
            if isinstance(v, float):
                mx.inputs[i].default_value = v
            else:
                link(nt, v, mx.inputs[i])
        return mx.outputs[0]

    z = sep.outputs['Z']
    # 砂：明るい砂に細かいむら
    sand = mixc(n2.outputs['Fac'], (0.40, 0.35, 0.26, 1), (0.52, 0.46, 0.35, 1), (-1000, 400))
    # 草地と土と森の床
    grass = mixc(n1.outputs['Fac'], (0.05, 0.085, 0.02, 1), (0.11, 0.13, 0.04, 1), (-1100, 200))
    dry = rng(n3.outputs['Fac'], 0.5, 0.68)
    grass = mixc(dry, grass, (0.20, 0.17, 0.08, 1), (-1000, 200))
    floor = mixc(n2.outputs['Fac'], (0.035, 0.032, 0.02, 1), (0.08, 0.07, 0.04, 1), (-1000, 0))
    soil = mixc(n2.outputs['Fac'], (0.16, 0.12, 0.08, 1), (0.25, 0.20, 0.13, 1), (-1000, -200))
    rock = mixc(n1.outputs['Fac'], (0.07, 0.065, 0.06, 1), (0.17, 0.155, 0.13, 1), (-1100, -400))
    rock = mixc(strata.outputs['Fac'], rock, (0.13, 0.10, 0.075, 1), (-1000, -500))
    crack = rng(vor.outputs['Distance'], 0.0, 0.025, 0.0, 0.0)
    land = mixc(attr_c.outputs['Fac'], grass, floor, (-800, 100))
    land = mixc(rng(attr_v.outputs['Fac'], 0.25, 0.75), land, soil, (-650, 100))
    # 浜から草地へ（高さ 1.8〜3.2m で移る。むらで境目を崩す）
    zj = node(nt, 'ShaderNodeMath', (-1100, 600), operation='MULTIPLY_ADD')
    link(nt, n1.outputs['Fac'], zj.inputs[0])
    zj.inputs[1].default_value = 1.6
    link(nt, z, zj.inputs[2])
    col = mixc(rng(zj.outputs[0], 2.6, 3.6), sand, land, (-500, 300))
    # 急な斜面は岩
    steep = rng(sepn.outputs['Z'], 0.82, 0.68)
    col = mixc(steep, col, rock, (-350, 300))
    # 波打ち際の濡れた砂（暗く、つやがある）
    wet = rng(z, 0.9, 0.15)
    wetcol = node(nt, 'ShaderNodeMix', (-200, 450), data_type='RGBA', blend_type='MULTIPLY')
    wetcol.inputs['Factor'].default_value = 1.0
    link(nt, col, wetcol.inputs[6])
    wetcol.inputs[7].default_value = (0.55, 0.52, 0.48, 1)
    col = mixc(wet, col, wetcol.outputs[2], (-50, 300))
    # 打ち上げられた海藻や流木の線（満潮線、高さ 1.1〜1.35m）
    wrack_n = node(nt, 'ShaderNodeMath', (-300, 600), operation='MULTIPLY_ADD')
    link(nt, n2.outputs['Fac'], wrack_n.inputs[0])
    wrack_n.inputs[1].default_value = 0.35
    link(nt, z, wrack_n.inputs[2])
    wr1 = rng(wrack_n.outputs[0], 1.15, 1.28)
    wr2 = rng(wrack_n.outputs[0], 1.38, 1.30)
    wr = node(nt, 'ShaderNodeMath', (-150, 600), operation='MINIMUM')
    link(nt, wr1, wr.inputs[0]); link(nt, wr2, wr.inputs[1])
    wrm = node(nt, 'ShaderNodeMath', (0, 600), operation='MULTIPLY')
    link(nt, wr.outputs[0], wrm.inputs[0]); link(nt, rng(n1.outputs['Fac'], 0.45, 0.6), wrm.inputs[1])
    col = mixc(wrm.outputs[0], col, (0.07, 0.06, 0.035, 1), (50, 450))
    # 水中の砂は少し緑がかる（藻）
    under = rng(z, -0.1, -1.5)
    col = mixc(under, col, (0.50, 0.47, 0.36, 1), (100, 300))
    grass_bed = node(nt, 'ShaderNodeMath', (100, 500), operation='MULTIPLY')
    link(nt, rng(n3.outputs['Fac'], 0.5, 0.6), grass_bed.inputs[0]); link(nt, rng(z, -3.0, -4.5), grass_bed.inputs[1])
    col = mixc(grass_bed.outputs[0], col, (0.035, 0.05, 0.02, 1), (250, 300))
    rough = mixf(wet, 1.0, 0.3, (100, 0))
    bump_n = node(nt, 'ShaderNodeTexNoise', (-400, -500), Scale=6.0, Detail=12.0, Roughness=0.7)
    link(nt, tc.outputs['Object'], bump_n.inputs['Vector'])
    crack_rock = node(nt, 'ShaderNodeMath', (-250, -500), operation='MULTIPLY')
    link(nt, crack, crack_rock.inputs[0]); link(nt, steep, crack_rock.inputs[1])
    bmix = node(nt, 'ShaderNodeMath', (-100, -500), operation='MULTIPLY_ADD')
    link(nt, crack_rock.outputs[0], bmix.inputs[0])
    bmix.inputs[1].default_value = -0.6
    link(nt, bump_n.outputs['Fac'], bmix.inputs[2])
    bump = node(nt, 'ShaderNodeBump', (100, -300), Strength=0.45, Distance=0.2)
    link(nt, bmix.outputs[0], bump.inputs['Height'])
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled', (300, 200))
    link(nt, col, bsdf.inputs['Base Color'])
    link(nt, rough, bsdf.inputs['Roughness'])
    spec = mixf(wet, 0.12, 0.5, (100, -100))
    link(nt, spec, bsdf.inputs['Specular IOR Level'])
    link(nt, bump.outputs['Normal'], bsdf.inputs['Normal'])
    finish(nt, bsdf.outputs[0], (800, 200))
    return m


def mat_water(st):
    m, nt = new_material('海')
    tc = node(nt, 'ShaderNodeTexCoord', (-1200, 0))
    mp = node(nt, 'ShaderNodeMapping', (-1000, 0))
    mp.inputs['Scale'].default_value = (1.0, 2.6, 1.0)
    link(nt, tc.outputs['Object'], mp.inputs['Vector'])
    mps = node(nt, 'ShaderNodeMapping', (-1000, 300))
    mps.inputs['Scale'].default_value = (0.35, 1.0, 1.0)
    link(nt, tc.outputs['Object'], mps.inputs['Vector'])
    swell = node(nt, 'ShaderNodeTexNoise', (-800, 300), Scale=0.06, Detail=3.0, Roughness=0.5)
    link(nt, mps.outputs[0], swell.inputs['Vector'])
    rip = node(nt, 'ShaderNodeTexNoise', (-800, 500), Scale=6.0, Detail=8.0, Roughness=0.62)
    link(nt, mp.outputs[0], rip.inputs['Vector'])
    w1 = node(nt, 'ShaderNodeTexNoise', (-800, 100), Scale=0.35, Detail=6.0, Roughness=0.55)
    w2 = node(nt, 'ShaderNodeTexNoise', (-800, -150), Scale=3.2, Detail=8.0, Roughness=0.62)
    link(nt, mp.outputs[0], w1.inputs['Vector'])
    link(nt, mp.outputs[0], w2.inputs['Vector'])
    add = node(nt, 'ShaderNodeMath', (-600, 0), operation='MULTIPLY_ADD')
    link(nt, w2.outputs['Fac'], add.inputs[0])
    add.inputs[1].default_value = 0.3
    link(nt, w1.outputs['Fac'], add.inputs[2])
    add2 = node(nt, 'ShaderNodeMath', (-500, 150), operation='MULTIPLY_ADD')
    link(nt, swell.outputs['Fac'], add2.inputs[0])
    add2.inputs[1].default_value = 1.6
    link(nt, add.outputs[0], add2.inputs[2])
    add3 = node(nt, 'ShaderNodeMath', (-450, 300), operation='MULTIPLY_ADD')
    link(nt, rip.outputs['Fac'], add3.inputs[0])
    add3.inputs[1].default_value = 0.16
    link(nt, add2.outputs[0], add3.inputs[2])
    fine = node(nt, 'ShaderNodeTexNoise', (-800, 700), Scale=28.0, Detail=4.0, Roughness=0.5)
    link(nt, mp.outputs[0], fine.inputs['Vector'])
    add4 = node(nt, 'ShaderNodeMath', (-450, 450), operation='MULTIPLY_ADD')
    link(nt, fine.outputs['Fac'], add4.inputs[0])
    add4.inputs[1].default_value = 0.025
    link(nt, add3.outputs[0], add4.inputs[2])
    add = add4
    bump = node(nt, 'ShaderNodeBump', (-400, 0), Strength=0.45, Distance=0.8)
    link(nt, add.outputs[0], bump.inputs['Height'])
    bsdf = node(nt, 'ShaderNodeBsdfGlass', (-150, 150))
    bsdf.inputs['Color'].default_value = (1, 1, 1, 1)
    bsdf.inputs['Roughness'].default_value = 0.03
    bsdf.inputs['IOR'].default_value = 1.333
    link(nt, bump.outputs['Normal'], bsdf.inputs['Normal'])
    # 影を落とさない（海底に日が届くように）。水の中を通る光は下の吸収で弱まる
    lp = node(nt, 'ShaderNodeLightPath', (-150, 400))
    tr = node(nt, 'ShaderNodeBsdfTransparent', (-150, -150))
    mix = node(nt, 'ShaderNodeMixShader', (100, 150))
    link(nt, lp.outputs['Is Shadow Ray'], mix.inputs[0])
    link(nt, bsdf.outputs[0], mix.inputs[1])
    link(nt, tr.outputs[0], mix.inputs[2])
    # 海水の色：赤が先に吸われ、深いほど青緑から紺へ。藻が多いと少し緑寄り
    # 吸収と散乱を1つの部品で扱う（別々の部品を足すとシェーダーの上限を超える）
    # 散乱の強さ = 密度×Color、吸収の強さ ≒ 密度×(1-Color)×(1-Absorption Color)
    g = min(1.6, max(0.6, st['algae']))
    vol = node(nt, 'ShaderNodeVolumePrincipled', (-150, -400))
    vol.inputs['Color'].default_value = (0.008, 0.03, 0.028, 1)
    vol.inputs['Density'].default_value = 0.14
    vol.inputs['Absorption Color'].default_value = (0.03, 0.55 + 0.06 * (g - 1), 0.62, 1)
    out = node(nt, 'ShaderNodeOutputMaterial', (350, 0))
    link(nt, mix.outputs[0], out.inputs['Surface'])
    link(nt, vol.outputs[0], out.inputs['Volume'])
    return m


def mat_simple(name, c1, c2, rough=0.8, scale=3.0, bump=0.3, stretch=(1, 1, 1), sss=0.0, kind='noise'):
    m, nt = new_material(name)
    tc = node(nt, 'ShaderNodeTexCoord', (-900, 0))
    mp = node(nt, 'ShaderNodeMapping', (-700, 0))
    mp.inputs['Scale'].default_value = stretch
    link(nt, tc.outputs['Object'], mp.inputs['Vector'])
    if kind == 'wave':
        tx = node(nt, 'ShaderNodeTexWave', (-500, 0), Scale=scale, Distortion=4.0, Detail=6.0)
    else:
        tx = node(nt, 'ShaderNodeTexNoise', (-500, 0), Scale=scale, Detail=10.0, Roughness=0.65)
    link(nt, mp.outputs[0], tx.inputs['Vector'])
    oi = node(nt, 'ShaderNodeObjectInfo', (-500, 250))
    jit = node(nt, 'ShaderNodeMath', (-300, 250), operation='MULTIPLY_ADD')
    link(nt, oi.outputs['Random'], jit.inputs[0])
    jit.inputs[1].default_value = 0.35
    link(nt, tx.outputs['Fac'], jit.inputs[2])
    mx = node(nt, 'ShaderNodeMix', (-100, 100), data_type='RGBA')
    link(nt, jit.outputs[0], mx.inputs['Factor'])
    mx.inputs[6].default_value = c1
    mx.inputs[7].default_value = c2
    bp = node(nt, 'ShaderNodeBump', (-100, -200), Strength=bump, Distance=0.05)
    link(nt, tx.outputs['Fac'], bp.inputs['Height'])
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled', (150, 100))
    link(nt, mx.outputs[2], bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = rough
    bsdf.inputs['Specular IOR Level'].default_value = 0.25 if rough > 0.5 else 0.5
    link(nt, bp.outputs['Normal'], bsdf.inputs['Normal'])
    if sss:
        bsdf.inputs['Subsurface Weight'].default_value = sss
    finish(nt, bsdf.outputs[0], (600, 100))
    return m


def mat_rock():
    """岩：割れ目、色むら、水際の濡れて暗い帯と海藻の帯"""
    m, nt = new_material('岩')
    tc = node(nt, 'ShaderNodeTexCoord', (-1200, 0))
    geo = node(nt, 'ShaderNodeNewGeometry', (-1200, 300))
    sep = node(nt, 'ShaderNodeSeparateXYZ', (-1000, 300))
    link(nt, geo.outputs['Position'], sep.inputs[0])
    n1 = node(nt, 'ShaderNodeTexNoise', (-900, 0), Scale=1.1, Detail=10.0, Roughness=0.65)
    link(nt, tc.outputs['Object'], n1.inputs['Vector'])
    wn = node(nt, 'ShaderNodeTexNoise', (-1100, -250), Scale=1.5, Detail=4.0)
    link(nt, tc.outputs['Object'], wn.inputs['Vector'])
    wv = node(nt, 'ShaderNodeVectorMath', (-1000, -250), operation='MULTIPLY_ADD')
    link(nt, wn.outputs['Color'], wv.inputs[0]); wv.inputs[1].default_value = (0.8, 0.8, 0.8); link(nt, tc.outputs['Object'], wv.inputs[2])
    vo = node(nt, 'ShaderNodeTexVoronoi', (-900, -250), Scale=1.6, feature='DISTANCE_TO_EDGE')
    link(nt, wv.outputs[0], vo.inputs['Vector'])
    oi = node(nt, 'ShaderNodeObjectInfo', (-900, 250))
    f = node(nt, 'ShaderNodeMath', (-700, 100), operation='MULTIPLY_ADD')
    link(nt, oi.outputs['Random'], f.inputs[0]); f.inputs[1].default_value = 0.3; link(nt, n1.outputs['Fac'], f.inputs[2])
    base = node(nt, 'ShaderNodeMix', (-500, 100), data_type='RGBA')
    link(nt, f.outputs[0], base.inputs['Factor'])
    base.inputs[6].default_value = (0.045, 0.042, 0.038, 1)
    base.inputs[7].default_value = (0.16, 0.145, 0.12, 1)
    cr = node(nt, 'ShaderNodeMapRange', (-700, -250))
    cr.inputs['From Min'].default_value = 0.0; cr.inputs['From Max'].default_value = 0.03
    cr.inputs['To Min'].default_value = 0.75; cr.inputs['To Max'].default_value = 0.0
    link(nt, vo.outputs['Distance'], cr.inputs['Value'])
    dark = node(nt, 'ShaderNodeMix', (-300, 100), data_type='RGBA')
    link(nt, cr.outputs['Result'], dark.inputs['Factor'])
    link(nt, base.outputs[2], dark.inputs[6]); dark.inputs[7].default_value = (0.012, 0.012, 0.01, 1)
    wet = node(nt, 'ShaderNodeMapRange', (-700, 450))
    wet.inputs['From Min'].default_value = 0.7; wet.inputs['From Max'].default_value = 0.1
    link(nt, sep.outputs['Z'], wet.inputs['Value'])
    weed = node(nt, 'ShaderNodeMix', (-100, 100), data_type='RGBA')
    link(nt, wet.outputs['Result'], weed.inputs['Factor'])
    link(nt, dark.outputs[2], weed.inputs[6]); weed.inputs[7].default_value = (0.025, 0.03, 0.015, 1)
    rough = node(nt, 'ShaderNodeMapRange', (-100, -150))
    rough.inputs['To Min'].default_value = 0.9; rough.inputs['To Max'].default_value = 0.35
    link(nt, wet.outputs['Result'], rough.inputs['Value'])
    hb = node(nt, 'ShaderNodeMath', (-300, -400), operation='MULTIPLY_ADD')
    link(nt, cr.outputs['Result'], hb.inputs[0]); hb.inputs[1].default_value = -0.5; link(nt, n1.outputs['Fac'], hb.inputs[2])
    bp = node(nt, 'ShaderNodeBump', (-100, -400), Strength=0.8, Distance=0.08)
    link(nt, hb.outputs[0], bp.inputs['Height'])
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled', (150, 100))
    link(nt, weed.outputs[2], bsdf.inputs['Base Color'])
    link(nt, rough.outputs['Result'], bsdf.inputs['Roughness'])
    bsdf.inputs['Specular IOR Level'].default_value = 0.3
    link(nt, bp.outputs['Normal'], bsdf.inputs['Normal'])
    finish(nt, bsdf.outputs[0], (600, 100))
    return m


def mat_foam():
    """波打ち際の泡。depth（その場所の海底の高さ）が 0 に近いほど、むらのある白い泡が出る"""
    m, nt = new_material('泡')
    tc = node(nt, 'ShaderNodeTexCoord', (-900, 0))
    mp = node(nt, 'ShaderNodeMapping', (-700, 0))
    mp.inputs['Scale'].default_value = (1.0, 3.0, 1.0)
    link(nt, tc.outputs['Object'], mp.inputs['Vector'])
    n = node(nt, 'ShaderNodeTexNoise', (-500, 0), Scale=0.9, Detail=10.0, Roughness=0.7)
    link(nt, mp.outputs[0], n.inputs['Vector'])
    vo = node(nt, 'ShaderNodeTexVoronoi', (-500, -250), Scale=1.8, feature='DISTANCE_TO_EDGE')
    link(nt, tc.outputs['Object'], vo.inputs['Vector'])
    at = node(nt, 'ShaderNodeAttribute', (-500, 250), attribute_name='depth')
    band = node(nt, 'ShaderNodeMapRange', (-300, 250))
    band.inputs['From Min'].default_value = -0.4
    band.inputs['From Max'].default_value = -0.04
    band.clamp = True
    link(nt, at.outputs['Fac'], band.inputs['Value'])
    lace = node(nt, 'ShaderNodeMapRange', (-300, -250))
    lace.inputs['From Min'].default_value = 0.0
    lace.inputs['From Max'].default_value = 0.09
    lace.inputs['To Min'].default_value = 1.0
    lace.inputs['To Max'].default_value = 0.0
    lace.clamp = True
    link(nt, vo.outputs['Distance'], lace.inputs['Value'])
    patchy = node(nt, 'ShaderNodeMapRange', (-300, 0))
    patchy.inputs['From Min'].default_value = 0.42
    patchy.inputs['From Max'].default_value = 0.62
    patchy.clamp = True
    link(nt, n.outputs['Fac'], patchy.inputs['Value'])
    m1 = node(nt, 'ShaderNodeMath', (-100, 100), operation='MAXIMUM')
    link(nt, patchy.outputs['Result'], m1.inputs[0]); link(nt, lace.outputs['Result'], m1.inputs[1])
    m2 = node(nt, 'ShaderNodeMath', (50, 100), operation='MULTIPLY')
    link(nt, m1.outputs[0], m2.inputs[0]); link(nt, band.outputs['Result'], m2.inputs[1])
    m3 = node(nt, 'ShaderNodeMath', (200, 100), operation='MULTIPLY')
    m3.inputs[1].default_value = 0.7
    link(nt, m2.outputs[0], m3.inputs[0])
    white = node(nt, 'ShaderNodeBsdfPrincipled', (200, -100))
    white.inputs['Base Color'].default_value = (0.82, 0.84, 0.84, 1)
    white.inputs['Roughness'].default_value = 0.6
    tr = node(nt, 'ShaderNodeBsdfTransparent', (200, -300))
    mix = node(nt, 'ShaderNodeMixShader', (400, 0))
    link(nt, m3.outputs[0], mix.inputs[0])
    link(nt, tr.outputs[0], mix.inputs[1])
    link(nt, white.outputs[0], mix.inputs[2])
    out = node(nt, 'ShaderNodeOutputMaterial', (600, 0))
    link(nt, mix.outputs[0], out.inputs['Surface'])
    return m


def mat_leaf(name, c1, c2):
    """葉：一枚ずつ色を変え、日に透ける"""
    m, nt = new_material(name)
    geo = node(nt, 'ShaderNodeNewGeometry', (-900, 0))
    oi = node(nt, 'ShaderNodeObjectInfo', (-900, 250))
    add = node(nt, 'ShaderNodeMath', (-700, 100), operation='MULTIPLY_ADD')
    link(nt, oi.outputs['Random'], add.inputs[0])
    add.inputs[1].default_value = 0.5
    link(nt, geo.outputs['Random Per Island'], add.inputs[2])
    fr = node(nt, 'ShaderNodeMath', (-550, 100), operation='FRACT')
    link(nt, add.outputs[0], fr.inputs[0])
    ramp = node(nt, 'ShaderNodeValToRGB', (-400, 100))
    ramp.color_ramp.elements[0].color = c1
    ramp.color_ramp.elements[1].color = c2
    e = ramp.color_ramp.elements.new(0.85)
    e.color = (c2[0] * 1.35 + 0.03, c2[1] * 1.15, c2[2] * 0.7, 1)
    link(nt, fr.outputs[0], ramp.inputs['Fac'])
    tree_tint = node(nt, 'ShaderNodeValToRGB', (-400, 350))
    tt = tree_tint.color_ramp.elements
    tt[0].color = (0.82, 0.92, 0.78, 1)
    tt[1].color = (1.10, 1.06, 0.80, 1)
    mid = tt.new(0.55)
    mid.color = (1.0, 1.0, 1.0, 1)
    red = tt.new(0.97)
    red.color = (1.25, 0.95, 0.70, 1)
    link(nt, oi.outputs['Random'], tree_tint.inputs['Fac'])
    tinted = node(nt, 'ShaderNodeMix', (-200, 250), data_type='RGBA', blend_type='MULTIPLY')
    tinted.inputs['Factor'].default_value = 1.0
    link(nt, ramp.outputs['Color'], tinted.inputs[6])
    link(nt, tree_tint.outputs['Color'], tinted.inputs[7])
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled', (-100, 200))
    link(nt, tinted.outputs[2], bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = 0.55
    bsdf.inputs['Specular IOR Level'].default_value = 0.35
    tl = node(nt, 'ShaderNodeBsdfTranslucent', (-100, -150))
    tint = node(nt, 'ShaderNodeMix', (-300, -150), data_type='RGBA', blend_type='MULTIPLY')
    tint.inputs['Factor'].default_value = 1.0
    link(nt, tinted.outputs[2], tint.inputs[6])
    tint.inputs[7].default_value = (1.4, 1.5, 0.6, 1)
    link(nt, tint.outputs[2], tl.inputs['Color'])
    mix = node(nt, 'ShaderNodeMixShader', (150, 50))
    mix.inputs[0].default_value = 0.3
    link(nt, bsdf.outputs[0], mix.inputs[1])
    link(nt, tl.outputs[0], mix.inputs[2])
    finish(nt, mix.outputs[0], (600, 50))
    return m


# ---------------------------------------------------------------- 地形

class Terrain:
    """入り江のある島。x は東、y は北、z は高さ（m）。海面は z=0"""
    X0, X1, Y0, Y1 = -620.0, 620.0, -380.0, 900.0
    STEP = 2.5
    CENTER = (0.0, 340.0)
    VILLAGE = (5.0, 160.0)
    REEF = (57.0, 36.0)

    def __init__(self, seed):
        self.seed = seed
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

    def _heights(self):
        cx, cy = self.CENTER
        X, Y = self.X, self.Y
        dx, dy = X - cx, Y - cy
        r = np.hypot(dx, dy)
        th = np.arctan2(dy, dx)
        R = np.vectorize(self.coast_radius)(th)
        # 島の中心の近くでは角度ごとの差を消す（中心から入り江へ向かう不自然な溝を作らない）
        w = smoothstep(60, 160, r)
        R = R * w + 345.0 * (1 - w)
        flat_x, flat_y = X.ravel(), Y.ravel()
        n_low = np.array([self._n(a, b, 1 / 160, 3) for a, b in zip(flat_x, flat_y)]).reshape(X.shape)
        n_mid = np.array([self._n(a, b, 1 / 45, 4, 3.3) for a, b in zip(flat_x, flat_y)]).reshape(X.shape)
        n_hi = np.array([self._n(a, b, 1 / 9, 3, 9.1) for a, b in zip(flat_x, flat_y)]).reshape(X.shape)
        F = R - r + 16 * n_low + 4 * n_mid
        south = -math.pi / 2
        headmask = np.exp(-((th - (south + 0.78)) / 0.2) ** 2) + np.exp(-((th - (south - 0.82)) / 0.18) ** 2)
        headmask = np.clip(headmask, 0, 1)
        Wb = (24 + 7 * n_mid) * (1 - 0.85 * headmask)
        H = np.zeros_like(F)
        land = F >= 0
        # 浜：ゆるやかに 2.2m まで
        fb = np.clip(F / np.maximum(Wb, 1.0), 0, 1)
        beach = 2.2 * fb ** 1.5
        g = np.maximum(F - Wb, 0)
        hill_h = 72 * (0.72 + 0.28 * n_low)
        ridge = np.array([noise.ridged_multi_fractal(Vector((a / 95, b / 95, 2.0 + self.seed)), 1.0, 2.0, 4, 1.0, 2.0)
                          for a, b in zip(flat_x, flat_y)]).reshape(X.shape)
        hill = (hill_h * (1 - np.exp(-g / 120)) + 7 * n_mid * (1 - np.exp(-g / 50)) + 1.2 * n_hi * (1 - np.exp(-g / 20))
                + 5 * np.clip(ridge - 0.8, -0.8, 0.9) * smoothstep(20, 120, g))
        # 浜の後ろに低くなだらかな平地の帯を作る（海岸から 15〜170m で山の高さへ移る）
        hill = hill * (0.15 + 0.85 * smoothstep(15, 170, g))
        # 岬は崖っぽく
        cliff = headmask * 9 * (1 - np.exp(-np.maximum(F, 0) / 6))
        hl = beach + hill + cliff
        # 陸地の高さを少しぼかして、鋭い谷の角を丸める（海岸の近くはそのまま）
        k = np.array([1, 4, 6, 4, 1], float)
        k /= k.sum()
        hs = hl.copy()
        for _ in range(2):
            hs = np.apply_along_axis(lambda v: np.convolve(np.pad(v, 2, mode='edge'), k, 'valid'), 1, hs)
            hs = np.apply_along_axis(lambda v: np.convolve(np.pad(v, 2, mode='edge'), k, 'valid'), 0, hs)
        blend = smoothstep(25, 60, F)
        hl = hl * (1 - blend) + hs * blend
        # 崩れ落ち（熱侵食）：36°より急な所から、土を少しずつ低い側へ移す。不自然な壁を残さない
        hl = self._settle(hl, F > 12, 36.0, 80)
        # 集落の段丘：ぼかした後に、なだらかにならす（先にならすと、ぼかしで斜面に戻ってしまう）
        vx, vy = self.VILLAGE
        # 浜に沿って東西に長い、なだらかな段丘（海沿いに家が並ぶ集落）
        # 平地の帯があるので、ならすのは家の並ぶ所だけ・弱めに（強くすると奥に段差ができる）
        vm = np.exp(-(((X - vx) / 1.7) ** 2 + ((Y - vy) / 0.45) ** 2) / (2 * 52 ** 2))
        vm = vm * smoothstep(Wb * 0.8, Wb + 10, F)
        terrace = 4.6 + 1.2 * n_mid + 0.05 * np.clip(Y - vy, 0, None)
        hl = hl * (1 - 0.6 * vm) + terrace * 0.6 * vm
        H[land] = hl[land]
        # 海底：浅瀬の棚から、沖へ深くなる
        d = np.maximum(-F, 0)
        shelf = 0.35 + 2.6 * (1 - np.exp(-d / 55)) + np.maximum(d - 85, 0) * 0.17
        depth = np.minimum(shelf, 38) + 0.25 * n_mid + 0.06 * n_hi
        H[~land] = -depth[~land]
        # 手前の小さな岩礁（カメラの右前）。岩が水面から出るように海底を持ち上げる
        rx, ry = self.REEF
        reef = -7.5 + 7.9 * np.exp(-((X - rx) ** 2 + (Y - ry) ** 2) / (2 * 9.0 ** 2))
        H = np.maximum(H, reef)
        self.headmask = headmask
        self.Wb = Wb
        self.village_mask = vm
        return H, F

    def _settle(self, h, movable, angle, iters):
        """急すぎる斜面を、土を低い側へ移して angle 度まで落ち着かせる（全体の土の量は変えない）"""
        h = h.copy()
        talus = math.tan(math.radians(angle)) * self.STEP
        mv = movable.astype(float)
        for _ in range(iters):
            for axis, step in ((0, 1), (0, -1), (1, 1), (1, -1)):
                nb = np.roll(h, step, axis)
                d = h - nb
                move = np.where(d > talus, (d - talus) * 0.2, 0.0) * mv * np.roll(mv, step, axis)
                # 端は回り込ませない
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
        return (h[j, i] * (1 - tx) * (1 - ty) + h[j, i + 1] * tx * (1 - ty) + h[j + 1, i] * (1 - tx) * ty + h[j + 1, i + 1] * tx * ty)

    def field_at(self, x, y):
        fx = (x - self.X0) / self.STEP
        fy = (y - self.Y0) / self.STEP
        i = int(np.clip(round(fx), 0, self.nx - 1))
        j = int(np.clip(round(fy), 0, self.ny - 1))
        return self.F[j, i]

    def slope_at(self, x, y, e=1.5):
        hx = self.height_at(x + e, y) - self.height_at(x - e, y)
        hy = self.height_at(x, y + e) - self.height_at(x, y - e)
        return math.degrees(math.atan(math.hypot(hx, hy) / (2 * e)))

    def build(self, mat, canopy=None, village=None):
        nx, ny = self.nx, self.ny
        verts = np.stack([self.X.ravel(), self.Y.ravel(), self.H.ravel()], axis=1)
        ii, jj = np.meshgrid(np.arange(nx - 1), np.arange(ny - 1))
        a = (jj * nx + ii).ravel()
        quads = np.stack([a, a + 1, a + nx + 1, a + nx], axis=1)
        me = bpy.data.meshes.new('地形')
        me.vertices.add(len(verts))
        me.vertices.foreach_set('co', verts.astype(np.float32).ravel())
        me.loops.add(len(quads) * 4)
        me.loops.foreach_set('vertex_index', quads.astype(np.int32).ravel())
        me.polygons.add(len(quads))
        me.polygons.foreach_set('loop_start', (np.arange(len(quads)) * 4).astype(np.int32))
        me.polygons.foreach_set('loop_total', np.full(len(quads), 4, np.int32))
        me.update(calc_edges=True)
        me.polygons.foreach_set('use_smooth', np.ones(len(quads), bool))
        for name, val in (('canopy', canopy), ('village', village)):
            if val is None:
                continue
            at = me.attributes.new(name, 'FLOAT', 'POINT')
            at.data.foreach_set('value', val.astype(np.float32).ravel())
        obj = bpy.data.objects.new('地形', me)
        link_object(obj)
        me.materials.append(mat)
        return obj


# ---------------------------------------------------------------- 植物

def add_leaf(bm, center, size, normal_hint, rng, stretch=1.0):
    """1枚の葉（ひし形の四角形）"""
    n = (normal_hint + Vector((rng.uniform(-.8, .8), rng.uniform(-.8, .8), rng.uniform(-.4, .9)))).normalized()
    t = n.orthogonal().normalized()
    t.rotate(Matrix.Rotation(rng.uniform(0, math.pi), 3, n))
    b = n.cross(t).normalized()
    L, W = size * stretch, size * 0.45
    pts = [center + t * L * 0.5, center + b * W * 0.5, center - t * L * 0.5, center - b * W * 0.5]
    vs = [bm.verts.new(p) for p in pts]
    bm.faces.new(vs)


def add_tube(bm, path, radii, segs=7):
    """道すじに沿った先細りの筒（幹や枝）"""
    rings = []
    for k, p in enumerate(path):
        d = (path[min(k + 1, len(path) - 1)] - path[max(k - 1, 0)]).normalized()
        u = d.orthogonal().normalized()
        v = d.cross(u).normalized()
        ring = [bm.verts.new(p + (u * math.cos(a) + v * math.sin(a)) * radii[k]) for a in np.linspace(0, 2 * math.pi, segs, endpoint=False)]
        rings.append(ring)
    for k in range(len(rings) - 1):
        for s in range(segs):
            bm.faces.new([rings[k][s], rings[k][(s + 1) % segs], rings[k + 1][(s + 1) % segs], rings[k + 1][s]])


def make_broadleaf(name, seed, height, crown, mats, coll):
    rng = random.Random(seed)
    bm = bmesh.new()
    lean = Vector((rng.uniform(-.6, .6), rng.uniform(-.6, .6), 0))
    trunk_top = Vector((0, 0, height * 0.62)) + lean
    path = [Vector((0, 0, -0.3)).lerp(trunk_top, t) + Vector((0.25 * math.sin(t * 3 + seed), 0.2 * math.cos(t * 2 + seed), 0)) * t for t in np.linspace(0, 1, 7)]
    r0 = 0.16 + height * 0.018
    add_tube(bm, path, [r0 * (1.35 - 0.75 * t) for t in np.linspace(0, 1, 7)])
    crown_c = Vector((0, 0, height * 0.66)) + lean
    n_cl = rng.randint(16, 22)
    clusters = []
    for _ in range(n_cl):
        d = Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0.15, 0.75))).normalized()
        c = crown_c + Vector((d.x * crown, d.y * crown, d.z * crown * 0.7)) * rng.uniform(0.35, 0.95)
        clusters.append(c)
        bpath = [trunk_top.lerp(c, t) + Vector((0, 0, 0.6 * math.sin(t * math.pi))) for t in np.linspace(0, 1, 4)]
        add_tube(bm, bpath, [r0 * 0.55 * (1 - 0.7 * t) for t in np.linspace(0, 1, 4)], segs=5)
    trunk_faces = len(bm.faces)
    for c in clusters:
        rc = crown * rng.uniform(0.48, 0.62)
        for _ in range(rng.randint(150, 200)):
            p = Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 0.75)))
            if p.length > 2.2:
                continue
            p = c + p * rc * 0.55
            add_leaf(bm, p, rng.uniform(0.5, 0.85), (p - crown_c).normalized(), rng)
    obj = mesh_object(name, bm, coll)
    obj.data.materials.append(mats['bark'])
    obj.data.materials.append(mats['leaf'])
    for i, f in enumerate(obj.data.polygons):
        f.material_index = 0 if i < trunk_faces else 1
    shade_smooth(obj)
    return obj


def make_conifer(name, seed, height, mats, coll):
    rng = random.Random(seed)
    bm = bmesh.new()
    path = [Vector((0, 0, -0.3 + t * (height + 0.3))) for t in np.linspace(0, 1, 6)]
    add_tube(bm, path, [0.22 * (1 - 0.9 * t) + 0.02 for t in np.linspace(0, 1, 6)])
    trunk_faces = len(bm.faces)
    layers = int(height / 0.55)
    for li in range(layers):
        t = li / layers
        z = height * (0.18 + 0.82 * t)
        rad = (1 - t) * height * 0.24 + 0.25
        for k in range(int(14 + rad * 16)):
            a = rng.uniform(0, 2 * math.pi)
            rr = rad * math.sqrt(rng.uniform(0.15, 1))
            p = Vector((math.cos(a) * rr, math.sin(a) * rr, z - rr * 0.35 + rng.uniform(-.2, .2)))
            add_leaf(bm, p, rng.uniform(0.55, 0.85), Vector((math.cos(a), math.sin(a), 0.6)), rng, stretch=1.8)
    obj = mesh_object(name, bm, coll)
    obj.data.materials.append(mats['bark'])
    obj.data.materials.append(mats['needle'])
    for i, f in enumerate(obj.data.polygons):
        f.material_index = 0 if i < trunk_faces else 1
    return obj


def make_shrub(name, seed, size, mats, coll):
    rng = random.Random(seed)
    bm = bmesh.new()
    for _ in range(rng.randint(3, 6)):
        c = Vector((rng.uniform(-.5, .5) * size, rng.uniform(-.5, .5) * size, rng.uniform(0.3, 0.7) * size))
        for _ in range(70):
            p = c + Vector((rng.gauss(0, .35), rng.gauss(0, .35), rng.gauss(0, .25))) * size
            if p.z < 0.02:
                continue
            add_leaf(bm, p, rng.uniform(0.18, 0.3) * size ** 0.5, Vector((0, 0, 1)), rng)
    obj = mesh_object(name, bm, coll)
    obj.data.materials.append(mats['leaf'])
    return obj


def make_rock(name, seed, mats, coll, size=1.0):
    rng = random.Random(seed)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=4, radius=1.0)
    off = Vector((seed * 3.1, seed * 1.7, seed * 0.9))
    sx, sy, sz = rng.uniform(.8, 1.5), rng.uniform(.7, 1.3), rng.uniform(.45, .85)
    for v in bm.verts:
        p = v.co.copy()
        d = noise.fractal(p * 1.3 + off, 0.6, 2.0, 6) * 0.36
        cell = noise.cell(p * 2.2 + off) * 0.28
        p = p * (1 + d - cell)
        if p.z > 0.75:
            p.z = 0.75 + (p.z - 0.75) * 0.55
        v.co = Vector((p.x * sx, p.y * sy, p.z * sz)) * size
    obj = mesh_object(name, bm, coll)
    obj.data.materials.append(mats['rock'])
    shade_smooth(obj)
    return obj


# ---------------------------------------------------------------- 建物と舟

def add_box(bm, center, size, rot_z=0.0, tilt=None):
    m = Matrix.Translation(center) @ Matrix.Rotation(rot_z, 4, 'Z')
    if tilt is not None:
        m = m @ tilt
    m = m @ Matrix.Diagonal(Vector((size[0], size[1], size[2], 1.0)))
    res = bmesh.ops.create_cube(bm, size=1.0, matrix=m)
    return res['verts']


def make_hut(name, seed, mats, coll):
    """木の柱と板壁（または土壁）の小屋に、茅葺きの切妻屋根"""
    rng = random.Random(seed)
    w, d, h = rng.uniform(4.0, 5.6), rng.uniform(5.0, 7.5), rng.uniform(2.2, 2.7)
    pitch = math.radians(rng.uniform(38, 46))
    over = 0.55
    bm_wall, bm_roof, bm_wood, bm_dark = bmesh.new(), bmesh.new(), bmesh.new(), bmesh.new()
    add_box(bm_wall, Vector((0, 0, h / 2 + 0.25)), (w, d, h))
    add_box(bm_dark, Vector((0, -d / 2 - 0.03, 1.15 + 0.25)), (1.0, 0.08, 1.9))
    for sx in (-1, 1):
        add_box(bm_dark, Vector((sx * w * 0.28, -d / 2 - 0.03, 1.6 + 0.25)), (0.6, 0.06, 0.5))
    add_box(bm_wood, Vector((0, 0, 0.12)), (w + 0.4, d + 0.4, 0.3))
    for sx in (-1, 1):
        for sy in (-1, 1):
            add_box(bm_wood, Vector((sx * w / 2, sy * d / 2, h / 2 + 0.25)), (0.22, 0.22, h + 0.05))
    # 切妻の三角の壁（妻面）
    top = h + 0.25 + (w / 2) * math.tan(pitch)
    for sy in (-1, 1):
        y = sy * d / 2
        vs = [bm_wall.verts.new(p) for p in ((-w / 2, y, h + 0.25), (w / 2, y, h + 0.25), (0, y, top))]
        bm_wall.faces.new(vs if sy > 0 else vs[::-1])
    # 屋根：厚みのある2枚の板
    slope_len = (w / 2 + over) / math.cos(pitch)
    for sx in (-1, 1):
        tilt = Matrix.Rotation(sx * pitch, 4, 'Y')
        c = Vector((sx * (w / 4 + over / 2), 0, h + 0.25 + (w / 4 - over / 2) * math.tan(pitch) + 0.18))
        add_box(bm_roof, c, (slope_len + 0.1, d + 2 * over, 0.32), 0.0, tilt)
    add_box(bm_wood, Vector((0, 0, top + 0.12)), (0.35, d + 2 * over + 0.1, 0.25))
    parts = []
    for bm, mname in ((bm_wall, 'wall_wood' if rng.random() < 0.55 else 'wall_daub'), (bm_roof, 'thatch'), (bm_wood, 'wood'), (bm_dark, 'dark')):
        me = bpy.data.meshes.new(name + mname)
        bm.to_mesh(me)
        bm.free()
        me.materials.append(mats[mname])
        parts.append(me)
    obj = join_meshes(name, parts, coll)
    return obj, (w, d)


def join_meshes(name, meshes, coll):
    bm = bmesh.new()
    mats = []
    for me in meshes:
        offset = len(mats)
        mats.extend(me.materials)
        tmp = bmesh.new()
        tmp.from_mesh(me)
        for f in tmp.faces:
            f.material_index += offset
        tmp_me = bpy.data.meshes.new('tmp')
        tmp.to_mesh(tmp_me)
        tmp.free()
        bm.from_mesh(tmp_me)
        bpy.data.meshes.remove(tmp_me)
        bpy.data.meshes.remove(me)
    obj = mesh_object(name, bm, coll)
    for m in mats:
        obj.data.materials.append(m)
    return obj


def make_canoe(name, seed, length, mats, coll, big=False):
    rng = random.Random(seed)
    bm = bmesh.new()
    stations = 14
    prof = [(-1.0, 1.0), (-0.92, 0.55), (-0.62, 0.2), (0.0, 0.0), (0.62, 0.2), (0.92, 0.55), (1.0, 1.0)]
    rings = []
    width = length * (0.13 if not big else 0.20)
    depth = length * (0.075 if not big else 0.11)
    for k in range(stations):
        t = k / (stations - 1)
        y = (t - 0.5) * length
        taper = math.sin(math.pi * t) ** (0.75 if big else 0.6)
        sheer = depth * (1 + 0.45 * (2 * abs(t - 0.5)) ** 3)
        keel = depth * 0.25 * (2 * abs(t - 0.5)) ** 2  # 両端は底が持ち上がる
        ring = [bm.verts.new(Vector((px * width * 0.5 * max(taper, 0.03), y, keel + pz * (sheer - keel)))) for px, pz in prof]
        rings.append(ring)
    for k in range(stations - 1):
        for s in range(len(prof) - 1):
            bm.faces.new([rings[k][s], rings[k][s + 1], rings[k + 1][s + 1], rings[k + 1][s]])
    obj = mesh_object(name, bm, coll)
    sol = obj.modifiers.new('厚み', 'SOLIDIFY')
    sol.thickness = 0.06 if not big else 0.12
    obj.data.materials.append(mats['hull_shell' if big == 'shell' else 'hull'])
    shade_smooth(obj)
    parts = [obj]
    if big:
        bmd = bmesh.new()
        add_box(bmd, Vector((0, 0, depth * 0.78)), (width * 0.82, length * 0.72, 0.08))
        deck = mesh_object(name + '甲板', bmd, coll)
        deck.data.materials.append(mats['wood'])
        deck.parent = obj
        bm2 = bmesh.new()
        add_tube(bm2, [Vector((0, length * 0.05, depth * 0.5)), Vector((0, length * 0.05, depth + length * 0.75))], [0.12, 0.07], segs=8)
        add_box(bm2, Vector((0, length * 0.05, depth + length * 0.32)), (0.18, length * 0.42, 0.18))
        mast = mesh_object(name + '帆柱', bm2, coll)
        mast.data.materials.append(mats['wood'])
        mast.parent = obj
        bm3 = bmesh.new()
        add_box(bm3, Vector((0, length * 0.05, depth + length * 0.36)), (0.35, length * 0.40, 0.32))
        sail = mesh_object(name + '帆', bm3, coll)
        sail.data.materials.append(mats['sail'])
        sail.parent = obj
        parts += [mast, sail]
    return obj


def make_jetty(mats, terrain, start, end):
    bm = bmesh.new()
    a, b = Vector((start[0], start[1], 0)), Vector((end[0], end[1], 0))
    dirv = (b - a)
    L = dirv.length
    ang = math.atan2(dirv.y, dirv.x) - math.pi / 2
    deck_z = 1.35
    n = int(L / 2.4)
    for k in range(n + 1):
        p = a.lerp(b, k / n)
        g = terrain.height_at(p.x, p.y)
        for s in (-1, 1):
            off = Vector((math.cos(ang), math.sin(ang), 0)) * 1.0 * s
            q = p + off
            add_box(bm, Vector((q.x, q.y, (g + deck_z) / 2 - 0.2)), (0.22, 0.22, deck_z - g + 0.6), ang)
    for k in range(int(L / 0.42)):
        p = a.lerp(b, k / (L / 0.42))
        add_box(bm, Vector((p.x, p.y, deck_z)), (2.5, 0.36, 0.08), ang + random.uniform(-0.03, 0.03))
    obj = mesh_object('桟橋', bm)
    obj.data.materials.append(mats['wood'])
    return obj


def make_foam(ter, mats):
    H = ter.H
    lo = np.minimum(np.minimum(H[:-1, :-1], H[1:, :-1]), np.minimum(H[:-1, 1:], H[1:, 1:]))
    hi = np.maximum(np.maximum(H[:-1, :-1], H[1:, :-1]), np.maximum(H[:-1, 1:], H[1:, 1:]))
    cells = np.argwhere((lo < 0.25) & (hi > -1.2))
    if not len(cells):
        return None
    nx = ter.nx
    used = np.unique(np.concatenate([cells[:, 0] * nx + cells[:, 1], cells[:, 0] * nx + cells[:, 1] + 1,
                                     (cells[:, 0] + 1) * nx + cells[:, 1], (cells[:, 0] + 1) * nx + cells[:, 1] + 1]))
    remap = -np.ones(H.size, np.int64)
    remap[used] = np.arange(len(used))
    xs, ys = ter.X.ravel()[used], ter.Y.ravel()[used]
    verts = np.stack([xs, ys, np.full(len(used), 0.025)], axis=1)
    a = cells[:, 0] * nx + cells[:, 1]
    quads = np.stack([remap[a], remap[a + 1], remap[a + nx + 1], remap[a + nx]], axis=1)
    me = bpy.data.meshes.new('泡')
    me.vertices.add(len(verts))
    me.vertices.foreach_set('co', verts.astype(np.float32).ravel())
    me.loops.add(len(quads) * 4)
    me.loops.foreach_set('vertex_index', quads.astype(np.int32).ravel())
    me.polygons.add(len(quads))
    me.polygons.foreach_set('loop_start', (np.arange(len(quads)) * 4).astype(np.int32))
    me.polygons.foreach_set('loop_total', np.full(len(quads), 4, np.int32))
    me.update(calc_edges=True)
    at = me.attributes.new('depth', 'FLOAT', 'POINT')
    at.data.foreach_set('value', H.ravel()[used].astype(np.float32))
    me.materials.append(mats['foam'])
    obj = bpy.data.objects.new('泡', me)
    link_object(obj)
    obj.visible_shadow = False
    return obj


# ---------------------------------------------------------------- 散らばらせる（ジオメトリーノードで大量に置く）

def scatter(name, coll, items):
    """items: (x, y, z, variant, scale, rot) のリスト"""
    if not items:
        return None
    arr = np.array(items, dtype=np.float64)
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(arr))
    me.vertices.foreach_set('co', arr[:, :3].astype(np.float32).ravel())
    for aname, col, kind in (('variant', 3, 'INT'), ('scale', 4, 'FLOAT'), ('rot', 5, 'FLOAT')):
        at = me.attributes.new(aname, kind, 'POINT')
        vals = arr[:, col].astype(np.int32 if kind == 'INT' else np.float32)
        at.data.foreach_set('value', vals)
    obj = bpy.data.objects.new(name, me)
    link_object(obj)
    ng = bpy.data.node_groups.new(name + '配置', 'GeometryNodeTree')
    ng.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    gi = node(ng, 'NodeGroupInput', (-800, 0))
    go = node(ng, 'NodeGroupOutput', (400, 0))
    m2p = node(ng, 'GeometryNodeMeshToPoints', (-600, 0))
    link(ng, gi.outputs[0], m2p.inputs['Mesh'])
    ci = node(ng, 'GeometryNodeCollectionInfo', (-600, -250))
    ci.inputs['Collection'].default_value = coll
    ci.inputs['Separate Children'].default_value = True
    ci.inputs['Reset Children'].default_value = True
    iop = node(ng, 'GeometryNodeInstanceOnPoints', (0, 0))
    link(ng, m2p.outputs[0], iop.inputs['Points'])
    link(ng, ci.outputs[0], iop.inputs['Instance'])
    iop.inputs['Pick Instance'].default_value = True
    av = node(ng, 'GeometryNodeInputNamedAttribute', (-400, -400), data_type='INT')
    av.inputs['Name'].default_value = 'variant'
    link(ng, av.outputs['Attribute'], iop.inputs['Instance Index'])
    asz = node(ng, 'GeometryNodeInputNamedAttribute', (-400, -550), data_type='FLOAT')
    asz.inputs['Name'].default_value = 'scale'
    link(ng, asz.outputs['Attribute'], iop.inputs['Scale'])
    ar = node(ng, 'GeometryNodeInputNamedAttribute', (-600, -700), data_type='FLOAT')
    ar.inputs['Name'].default_value = 'rot'
    cxyz = node(ng, 'ShaderNodeCombineXYZ', (-400, -700))
    link(ng, ar.outputs['Attribute'], cxyz.inputs['Z'])
    try:
        e2r = node(ng, 'FunctionNodeEulerToRotation', (-200, -700))
        link(ng, cxyz.outputs[0], e2r.inputs[0])
        link(ng, e2r.outputs[0], iop.inputs['Rotation'])
    except Exception:
        link(ng, cxyz.outputs[0], iop.inputs['Rotation'])
    link(ng, iop.outputs[0], go.inputs[0])
    mod = obj.modifiers.new('配置', 'NODES')
    mod.node_group = ng
    return obj


def hidden_collection(name):
    c = bpy.data.collections.new(name)
    return c


# ---------------------------------------------------------------- 空と光

def setup_world(args, st):
    sc = bpy.context.scene
    w = bpy.data.worlds.new('空')
    sc.world = w
    try:
        w.use_nodes = True
    except Exception:
        pass
    nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    sky = node(nt, 'ShaderNodeTexSky', (-600, 0))
    sky.sky_type = 'MULTIPLE_SCATTERING'
    sky.sun_disc = False
    sky.sun_elevation = math.radians(args.sun_elevation)
    sky.sun_rotation = math.radians(args.sun_azimuth)
    sky.altitude = 20.0
    sky.air_density = 1.0
    sky.aerosol_density = 1.6 + 2.0 * min(1.0, st['storm'])
    # 雲：方向から上空の面へ写した2次元のむら
    tc = node(nt, 'ShaderNodeTexCoord', (-1400, -300))
    sep = node(nt, 'ShaderNodeSeparateXYZ', (-1200, -300))
    link(nt, tc.outputs['Generated'], sep.inputs[0])
    zc = node(nt, 'ShaderNodeMath', (-1050, -450), operation='MAXIMUM')
    zc.inputs[1].default_value = 0.02
    link(nt, sep.outputs['Z'], zc.inputs[0])
    px = node(nt, 'ShaderNodeMath', (-900, -250), operation='DIVIDE')
    py = node(nt, 'ShaderNodeMath', (-900, -400), operation='DIVIDE')
    link(nt, sep.outputs['X'], px.inputs[0]); link(nt, zc.outputs[0], px.inputs[1])
    link(nt, sep.outputs['Y'], py.inputs[0]); link(nt, zc.outputs[0], py.inputs[1])
    cxy = node(nt, 'ShaderNodeCombineXYZ', (-750, -300))
    link(nt, px.outputs[0], cxy.inputs['X']); link(nt, py.outputs[0], cxy.inputs['Y'])
    mp = node(nt, 'ShaderNodeMapping', (-600, -300))
    mp.inputs['Scale'].default_value = (0.9, 0.55, 1.0)
    mp.inputs['Location'].default_value = (args.seed * 0.37, args.seed * 0.11, 0)
    link(nt, cxy.outputs[0], mp.inputs[0])
    cn = node(nt, 'ShaderNodeTexNoise', (-450, -300), Scale=1.1, Detail=9.0, Roughness=0.62)
    link(nt, mp.outputs[0], cn.inputs['Vector'])
    cover = 0.56 - 0.12 * min(1.0, st['storm'])
    cr = node(nt, 'ShaderNodeMapRange', (-250, -300))
    cr.inputs['From Min'].default_value = cover
    cr.inputs['From Max'].default_value = cover + 0.16
    link(nt, cn.outputs['Fac'], cr.inputs['Value'])
    # 地平線の近くと地平線の下には雲を出さない
    hz = node(nt, 'ShaderNodeMapRange', (-250, -500))
    hz.inputs['From Min'].default_value = 0.03
    hz.inputs['From Max'].default_value = 0.22
    link(nt, sep.outputs['Z'], hz.inputs['Value'])
    cm = node(nt, 'ShaderNodeMath', (-80, -350), operation='MULTIPLY')
    link(nt, cr.outputs['Result'], cm.inputs[0]); link(nt, hz.outputs['Result'], cm.inputs[1])
    cm2 = node(nt, 'ShaderNodeMath', (60, -350), operation='MULTIPLY')
    cm2.inputs[1].default_value = 0.85
    link(nt, cm.outputs[0], cm2.inputs[0])
    sky_bg = node(nt, 'ShaderNodeBackground', (-300, 100), Strength=0.18)
    link(nt, sky.outputs[0], sky_bg.inputs['Color'])
    cloud_bg = node(nt, 'ShaderNodeBackground', (-300, -100))
    cloud_bg.inputs['Color'].default_value = (1.0, 0.86, 0.72, 1)
    cloud_bg.inputs['Strength'].default_value = 2.6
    lp = node(nt, 'ShaderNodeLightPath', (-100, 300))
    # 雲は目に見える部分だけ（照明には空だけを使う）
    seen = node(nt, 'ShaderNodeMath', (60, -150), operation='MAXIMUM')
    link(nt, lp.outputs['Is Camera Ray'], seen.inputs[0]); link(nt, lp.outputs['Is Glossy Ray'], seen.inputs[1])
    camcloud = node(nt, 'ShaderNodeMath', (200, -300), operation='MULTIPLY')
    link(nt, cm2.outputs[0], camcloud.inputs[0]); link(nt, seen.outputs[0], camcloud.inputs[1])
    mix = node(nt, 'ShaderNodeMixShader', (350, 0))
    link(nt, camcloud.outputs[0], mix.inputs[0])
    link(nt, sky_bg.outputs[0], mix.inputs[1])
    link(nt, cloud_bg.outputs[0], mix.inputs[2])
    out = node(nt, 'ShaderNodeOutputWorld', (550, 0))
    link(nt, mix.outputs[0], out.inputs['Surface'])
    # 太陽：空の太陽と同じ向き。夕方の色
    sun = bpy.data.lights.new('太陽', 'SUN')
    sun.energy = 5.0 * (1 - 0.6 * min(1.0, st['storm']))
    sun.angle = math.radians(0.6)
    sun.color = (1.0, 0.82, 0.62)
    so = bpy.data.objects.new('太陽', sun)
    link_object(so)
    el = math.radians(args.sun_elevation)
    az = math.radians(args.sun_azimuth)
    d = Vector((math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)))  # 太陽の方向
    so.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
    return sky


def use_gpu():
    """使える GPU を探して、Cycles の描画装置にする。見つからなければ None"""
    prefs = bpy.context.preferences.addons['cycles'].preferences
    for kind in ('METAL', 'OPTIX', 'CUDA', 'HIP', 'ONEAPI'):
        try:
            prefs.compute_device_type = kind
        except TypeError:
            continue
        prefs.get_devices()
        devs = [d for d in prefs.devices if d.type == kind]
        if devs:
            for d in prefs.devices:
                d.use = d.type == kind
            bpy.context.scene.cycles.device = 'GPU'
            return kind
    return None


# ---------------------------------------------------------------- 組み立て

def build(args):
    t0 = time.time()
    st = load_state(args)
    print('状態:', st)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    random.seed(args.seed)
    rng = random.Random(args.seed)
    sc = bpy.context.scene

    mats = {
        'terrain': mat_terrain(),
        'water': mat_water(st),
        'bark': mat_simple('樹皮', (0.07, 0.055, 0.04, 1), (0.16, 0.13, 0.10, 1), 0.9, 6.0, 0.6, (1, 1, 0.15)),
        'leaf': mat_leaf('葉', (0.025, 0.055, 0.012, 1), (0.075, 0.13, 0.025, 1)),
        'needle': mat_leaf('針葉', (0.02, 0.05, 0.02, 1), (0.05, 0.10, 0.04, 1)),
        'rock': mat_rock(),
        'wall_wood': mat_simple('板壁', (0.13, 0.09, 0.055, 1), (0.26, 0.18, 0.11, 1), 0.8, 2.5, 0.5, (1, 1, 8), kind='wave'),
        'wall_daub': mat_simple('土壁', (0.27, 0.21, 0.15, 1), (0.40, 0.33, 0.24, 1), 0.95, 2.0, 0.4),
        'thatch': mat_simple('茅', (0.17, 0.13, 0.07, 1), (0.33, 0.26, 0.15, 1), 0.95, 9.0, 0.8, (1, 6, 1)),
        'foam': mat_foam(),
        'wood': mat_simple('木材', (0.18, 0.12, 0.07, 1), (0.32, 0.23, 0.14, 1), 0.85, 4.0, 0.4, (1, 1, 6), kind='wave'),
        'dark': mat_simple('戸口', (0.02, 0.015, 0.01, 1), (0.05, 0.04, 0.03, 1), 0.9, 3.0, 0.1),
        'hull': mat_simple('船体', (0.12, 0.08, 0.05, 1), (0.25, 0.17, 0.10, 1), 0.6, 3.0, 0.3, (1, 8, 1), kind='wave'),
        'hull_shell': mat_simple('軽殻石の船体', (0.70, 0.72, 0.68, 1), (0.86, 0.87, 0.82, 1), 0.35, 2.0, 0.2),
        'sail': mat_simple('帆', (0.55, 0.50, 0.42, 1), (0.70, 0.65, 0.55, 1), 0.9, 5.0, 0.2, sss=0.1),
        'tide': mat_leaf('潮麦', (0.32, 0.30, 0.08, 1), (0.55, 0.47, 0.13, 1)),
    }

    # 地形（いったん高さだけ作り、植物の位置を決めてから、森の床と集落の地面を書き込む）
    ter = Terrain(args.seed)
    print('地形 %.1fs' % (time.time() - t0))

    # 集落の家：人口6.5人あたり1軒
    n_huts = int(max(3, min(60, round(st['population'] / 6.5))))
    vx, vy = Terrain.VILLAGE
    huts = []
    tries = 0
    while len(huts) < n_huts and tries < 6000:
        tries += 1
        rad = 14 + 66 * math.sqrt(rng.random())
        a = rng.uniform(0, 2 * math.pi)
        x, y = vx + math.cos(a) * rad * 1.8, vy + math.sin(a) * rad * 0.7
        f = ter.field_at(x, y)
        if f < 26 or ter.slope_at(x, y, 3) > 13:
            continue
        if any((x - hx) ** 2 + (y - hy) ** 2 < 9.5 ** 2 for hx, hy, *_ in huts):
            continue
        face = math.atan2(-(y - 40), -(x - 5)) + math.pi / 2 + rng.uniform(-.35, .35)
        huts.append((x, y, face))
    hut_coll = hidden_collection('家の型')
    hut_types = [make_hut('家%02d' % k, args.seed * 100 + k, mats, hut_coll) for k in range(6)]
    for k, (x, y, face) in enumerate(huts):
        src, _ = hut_types[k % len(hut_types)]
        ob = bpy.data.objects.new('家', src.data)
        ob.location = (x, y, ter.height_at(x, y) - 0.15)
        ob.rotation_euler = (0, 0, face)
        link_object(ob)

    # 木の候補：島の陸地全体に、4.2m 間隔をずらして置く
    # 森の生物量の指数を、木の本数（被覆）と大きさに分けて対応させる。
    # 生物量が減ると、本数は 生物量^0.75 の割合に、残る木も若く小さくなる
    cover = max(0.0, min(1.0, st['forest'])) ** 0.75
    tree_coll = hidden_collection('木の型')
    variants = []
    for k in range(5):
        variants.append(make_broadleaf('木%02d' % k, args.seed * 10 + k, rng.uniform(9, 14), rng.uniform(4.2, 5.6), mats, tree_coll))
    for k in range(3):
        variants.append(make_conifer('木%02d' % (5 + k), args.seed * 20 + k, rng.uniform(11, 16), mats, tree_coll))
    cand = []
    sp = 3.4
    for gy in np.arange(ter.Y0 + 5, ter.Y1 - 5, sp):
        for gx in np.arange(ter.X0 + 5, ter.X1 - 5, sp):
            x, y = gx + rng.uniform(-1.6, 1.6), gy + rng.uniform(-1.6, 1.6)
            f = ter.field_at(x, y)
            if f < 30:
                continue
            h = ter.height_at(x, y)
            if h < 2.6 or ter.slope_at(x, y) > 46:
                continue
            # 林のむら（ところどころ空き地）
            patch = noise.fractal(Vector((x / 70, y / 70, 5.0)), 0.6, 2.0, 3)
            if patch < -0.5:
                continue
            dv = math.hypot((x - vx) / 1.15, (y - vy) / 0.8)
            near = min(((x - hx) ** 2 + (y - hy) ** 2 for hx, hy, _ in huts), default=1e9)
            if near < 8 ** 2 or (near < 16 ** 2 and rng.random() < 0.6):
                continue
            access = dv + 0.8 * h + 25 * noise.noise(Vector((x / 40, y / 40, 1.0)))
            cand.append((x, y, h, access))
    # 森が減った分は、集落から行きやすい所ほど切られやすい（境目はぼかす）
    cand.sort(key=lambda c: c[3])
    n_cut = int(round(len(cand) * (1 - cover)))
    if 0 < n_cut < len(cand):
        thr = cand[n_cut][3]
        soft = 60.0
        cut, keep = [], []
        for c in cand:
            p_cut = 1 / (1 + math.exp((c[3] - thr) / soft))
            (cut if rng.random() < p_cut else keep).append(c)
    else:
        cut, keep = cand[:n_cut], cand[n_cut:]
    young = 0.72 + 0.28 * cover
    trees = []
    for x, y, h, _ in keep:
        conifer_share = min(0.85, max(0.0, (h - 25) / 60))
        v = rng.randrange(5, 8) if rng.random() < conifer_share else rng.randrange(0, 5)
        trees.append((x, y, h - 0.2, v, rng.uniform(0.75, 1.2) * young, rng.uniform(0, 2 * math.pi)))
    # 切り跡の一部では若木が育ち始めている
    regrow = [c for c in cut if rng.random() < 0.14]
    regrow_set = set(regrow)
    cut = [c for c in cut if c not in regrow_set]
    for x, y, h, _ in regrow:
        trees.append((x, y, h - 0.2, rng.randrange(0, 5), rng.uniform(0.3, 0.55), rng.uniform(0, 2 * math.pi)))
    scatter('森', tree_coll, trees)
    # 切り株（切られた所の一部）
    stump_coll = hidden_collection('切り株の型')
    bm = bmesh.new()
    add_tube(bm, [Vector((0, 0, -0.2)), Vector((0, 0, 0.55))], [0.32, 0.27], segs=9)
    stump = mesh_object('切り株', bm, stump_coll)
    stump.data.materials.append(mats['bark'])
    stumps = [(x, y, h, 0, rng.uniform(0.7, 1.3), rng.uniform(0, 6.3)) for x, y, h, _ in cut if rng.random() < 0.35]
    scatter('切り株', stump_coll, stumps)
    print('木 %d 本・切り株 %d・家 %d 軒  %.1fs' % (len(trees), len(stumps), len(huts), time.time() - t0))
    if len(huts) < n_huts:
        print('注意：段丘に収まらず、家は %d 軒のうち %d 軒だけ置いた' % (n_huts, len(huts)))

    # 低木：林のふち、集落のまわり、浜の上
    shrub_coll = hidden_collection('低木の型')
    for k in range(4):
        make_shrub('低木%02d' % k, args.seed * 30 + k, rng.uniform(0.9, 1.6), mats, shrub_coll)
    shrubs = []
    for _ in range(26000):
        x, y = rng.uniform(-420, 420), rng.uniform(40, 420)
        f = ter.field_at(x, y)
        if f < 22 or f > 160:
            continue
        if f > 70 and rng.random() < 0.6:
            continue
        h = ter.height_at(x, y)
        if h < 2.3 or ter.slope_at(x, y) > 35:
            continue
        if any((x - hx) ** 2 + (y - hy) ** 2 < 6 ** 2 for hx, hy, _ in huts):
            continue
        shrubs.append((x, y, h - 0.1, rng.randrange(4), rng.uniform(0.6, 1.4), rng.uniform(0, 6.3)))
    scatter('低木', shrub_coll, shrubs)

    # 森の床と集落の地面を地形に書き込む
    canopy = np.zeros_like(ter.H)
    for x, y, *_ in trees:
        i = int((x - ter.X0) / ter.STEP)
        j = int((y - ter.Y0) / ter.STEP)
        canopy[max(0, j - 2):j + 3, max(0, i - 2):i + 3] += 0.35
    canopy = np.clip(canopy, 0, 1)
    village = np.zeros_like(ter.H)
    for x, y, _ in huts:
        d2 = (ter.X - x) ** 2 + (ter.Y - y) ** 2
        village = np.maximum(village, np.exp(-d2 / (2 * 7.5 ** 2)))
    village *= (ter.H > 2.4)
    ter.build(mats['terrain'], canopy, village)

    # 岩：岬のふもと、浜の両端、浅瀬の手前
    rock_coll = hidden_collection('岩の型')
    for k in range(7):
        make_rock('岩%02d' % k, args.seed * 40 + k, mats, rock_coll)
    rocks = []
    for _ in range(4000):
        x, y = rng.uniform(-420, 420), rng.uniform(-60, 260)
        f = ter.field_at(x, y)
        hm = ter.headmask[int((y - ter.Y0) / ter.STEP), int((x - ter.X0) / ter.STEP)]
        near_coast = -14 < f < 10
        ends = abs(x - vx) > 85
        if not near_coast or (not ends and hm < 0.3):
            continue
        s = rng.uniform(0.6, 2.4) * (1.6 if hm > 0.3 else 1.0)
        rocks.append((x, y, ter.height_at(x, y) - s * 0.25, rng.randrange(7), s, rng.uniform(0, 6.3)))
    # 手前の岩礁の岩（画面右下に入る）
    rx, ry = Terrain.REEF
    for k in range(11):
        x, y = rx + rng.uniform(-7, 7), ry + rng.uniform(-6, 6)
        s = 3.2 if k == 0 else rng.uniform(0.6, 2.0)
        rocks.append((x, y, ter.height_at(x, y) - s * 0.15, rng.randrange(7), s, rng.uniform(0, 6.3)))
    scatter('岩', rock_coll, rocks)

    # 潮麦（生物の星）：浅瀬の 0.3〜2.5m に群生
    if st['tidal_crop'] and st['tide'] > 0.01:
        tide_coll = hidden_collection('潮麦の型')
        for k in range(3):
            r2 = random.Random(args.seed * 50 + k)
            bm = bmesh.new()
            for _ in range(60):
                base = Vector((r2.gauss(0, .35), r2.gauss(0, .35), 0))
                tip = base + Vector((r2.gauss(0, .15), r2.gauss(0, .15), r2.uniform(0.7, 1.3)))
                add_leaf(bm, base.lerp(tip, 0.5), 1.2, Vector((1, 0, 0)), r2, stretch=1.0)
            ob = mesh_object('潮麦%02d' % k, bm, tide_coll)
            ob.data.materials.append(mats['tide'])
        tides = []
        for _ in range(int(25000 * min(1.5, st['tide']))):
            x, y = rng.uniform(-300, 300), rng.uniform(-40, 140)
            h = ter.height_at(x, y)
            if -2.5 < h < -0.3 and noise.fractal(Vector((x / 25, y / 25, 9.0)), 0.6, 2.0, 3) > -0.1:
                tides.append((x, y, h, rng.randrange(3), rng.uniform(0.6, 1.2), rng.uniform(0, 6.3)))
        scatter('潮麦', tide_coll, tides)

    make_foam(ter, mats)

    # 海：大きな水の塊（表面 z=0、深さ 60m）
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Translation((0, 2000, -30)) @ Matrix.Diagonal(Vector((24000, 24000, 60, 1))))
    sea = mesh_object('海', bm)
    sea.data.materials.append(mats['water'])
    # 遠くの海底（地形の外側）
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=12000, matrix=Matrix.Translation((0, 2000, -45)))
    fl = mesh_object('沖の海底', bm)
    fl.data.materials.append(mats['rock'])

    # 桟橋と舟
    jy0 = None
    for yy in np.arange(60, 200, 0.5):
        if ter.height_at(28, yy) > 0.6:
            jy0 = yy
            break
    if jy0:
        make_jetty(mats, ter, (28, jy0 + 2), (24, jy0 - 34))
    boat_coll = bpy.data.collections.new('舟')
    sc.collection.children.link(boat_coll)
    for k in range(5):
        x = -60 + k * 17 + rng.uniform(-4, 4)
        y = None
        for yy in np.arange(40, 220, 0.4):
            if ter.height_at(x, yy) > 0.9:
                y = yy
                break
        if y is None:
            continue
        b = make_canoe('丸木舟%d' % k, args.seed + k, rng.uniform(5.5, 7.5), mats, boat_coll)
        b.location = (x, y + rng.uniform(1, 4), ter.height_at(x, y + 2) + 0.05)
        b.rotation_euler = (math.radians(rng.uniform(-3, 3)), math.radians(rng.uniform(-6, 6)), rng.uniform(-0.4, 0.4))
    # 島どうしを結ぶ船（計算データの船の数）
    for k in range(st['ships_wood'] + st['ships_shell']):
        kind = 'shell' if k < st['ships_shell'] else True
        b = make_canoe('船%d' % k, args.seed * 3 + k, 13.0, mats, boat_coll, big=kind)
        b.location = (14 - k * 16, (jy0 or 120) - 40 - k * 8, -0.25)
        b.rotation_euler = (0, 0, math.radians(75 + 20 * k))

    # カメラ：入り江の中、水面から 2.4m
    cam = bpy.data.objects.new('カメラ', bpy.data.cameras.new('カメラ'))
    link_object(cam)
    cam.data.sensor_width = 36
    cam.data.clip_end = 30000
    if args.camera == 'boat':
        cam.data.lens = 30
        poses = [((42, 6, 2.4), (-2, 175, 15))]
    else:
        cam.data.lens = 30
        poses = [((48, -30, 16), (0, 175, 18))]
    if args.anim:
        # 沖から入り江へ12秒で近づき、少し右へ回り込む
        poses = [((78, -95, 26), (-5, 175, 0)), ((40, 15, 10), (-2, 175, 1))]
    def aim(loc, tgt):
        cam.location = loc
        cam.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    aim(*poses[0])
    sc.camera = cam
    if args.anim:
        sc.render.use_persistent_data = True  # カメラしか動かないので、場面の準備をコマごとにやり直さない
        n_frames = int(round(args.seconds * args.fps))
        sc.frame_start, sc.frame_end = 1, n_frames
        sc.render.fps = args.fps
        for k in range(n_frames):
            t = k / max(1, n_frames - 1)
            e = t * t * (3 - 2 * t)  # ゆっくり動き出し、ゆっくり止まる
            loc = Vector(poses[0][0]).lerp(Vector(poses[1][0]), e)
            tgt = Vector(poses[0][1]).lerp(Vector(poses[1][1]), e)
            aim(loc, tgt)
            cam.keyframe_insert('location', frame=k + 1)
            cam.keyframe_insert('rotation_euler', frame=k + 1)

    setup_world(args, st)

    # 描画の設定
    sc.render.engine = 'CYCLES'
    cy = sc.cycles
    cy.device = 'CPU'
    if args.gpu:
        kind = use_gpu()
        print('GPU:', kind or '見つからないので CPU で描く')
    rx, ry = (960, 540) if args.preview else map(int, args.res.lower().split('x'))
    sc.render.resolution_x, sc.render.resolution_y = rx, ry
    sc.render.resolution_percentage = 100
    cy.samples = 48 if args.preview else args.samples
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = 0.03 if args.preview else 0.015
    cy.use_denoising = True
    cy.denoiser = 'OPENIMAGEDENOISE'
    cy.max_bounces = 8
    cy.diffuse_bounces = 3
    cy.glossy_bounces = 3
    cy.transmission_bounces = 8
    cy.volume_bounces = 0
    cy.transparent_max_bounces = 8
    cy.caustics_reflective = False
    cy.caustics_refractive = False
    cy.blur_glossy = 1.0
    cy.sample_clamp_indirect = 8.0
    if hasattr(cy, 'use_light_tree'):
        cy.use_light_tree = True
    if args.threads:
        sc.render.threads_mode = 'FIXED'
        sc.render.threads = args.threads
    sc.view_settings.view_transform = 'AgX'
    try:
        sc.view_settings.look = 'AgX - Medium High Contrast'
    except TypeError:
        pass
    sc.view_settings.exposure = 0.0
    sc.render.image_settings.file_format = 'PNG'
    if args.border:
        b = [float(v) for v in args.border.split(',')]
        sc.render.use_border = True
        sc.render.use_crop_to_border = True
        sc.render.border_min_x, sc.render.border_min_y, sc.render.border_max_x, sc.render.border_max_y = b
    sc.render.filepath = os.path.abspath(args.out)
    print('組み立て完了 %.1fs（%s）' % (time.time() - t0, st['label']))
    if args.blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.blend))
    if args.dry:
        return
    t1 = time.time()
    if args.anim:
        sc.render.filepath = os.path.abspath(args.out)
        bpy.ops.render.render(animation=True)
        n = sc.frame_end - sc.frame_start + 1
        print('動画 %d コマ・%.1fs（1コマ %.1fs）→ %s####.png' % (n, time.time() - t1, (time.time() - t1) / n, sc.render.filepath))
    else:
        bpy.ops.render.render(write_still=True)
        print('描画 %.1fs → %s' % (time.time() - t1, sc.render.filepath))


if __name__ == '__main__':
    build(parse_args())
