"""地球の基礎キット：空と光（時刻・雲・嵐・夜の星）

time：dawn（夜明け）、day（昼）、dusk（夕暮れ）、night（夜）
太陽の方位は北0・東回り（度）。空の太陽と、太陽の光（ランプ）の向きをそろえる。
"""
import math

import bpy
from mathutils import Vector

from .util import link, link_object, map_range, math_op, node

PRESET = {
    # 時刻: (太陽の高さ, 空の明るさ, 太陽の強さ, 太陽の色, 雲の色, 雲の明るさ)
    'dawn': (4.0, 0.16, 3.0, (1.0, 0.70, 0.48), (1.0, 0.72, 0.55), 2.2),
    'day': (42.0, 0.20, 5.5, (1.0, 0.96, 0.90), (1.0, 1.0, 1.0), 2.6),
    'dusk': (6.0, 0.17, 3.6, (1.0, 0.66, 0.40), (1.0, 0.68, 0.50), 2.4),
    'night': (-25.0, 0.0, 0.0, (0.6, 0.7, 1.0), (0.10, 0.12, 0.16), 0.15),
}


def setup(time='dusk', azimuth=-120.0, elevation=None, cloud=0.5, storm=0.0, seed=7, stars=None):
    sc = bpy.context.scene
    w = bpy.data.worlds.new('空')
    sc.world = w
    if bpy.app.version < (5, 0, 0):  # 5.0 からは最初からノードを使う（use_nodes は 6.0 で消える）
        w.use_nodes = True
    nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    el0, sky_str, sun_e, sun_c, cl_c, cl_s = PRESET[time]
    el = el0 if elevation is None else elevation
    stars = (time == 'night') if stars is None else stars
    out = node(nt, 'ShaderNodeOutputWorld', (900, 0))
    lp = node(nt, 'ShaderNodeLightPath', (-200, 400))
    seen = math_op(nt, 'MAXIMUM', lp.outputs['Is Camera Ray'], lp.outputs['Is Glossy Ray'], (0, 400))
    tc = node(nt, 'ShaderNodeTexCoord', (-1400, -300))
    sep = node(nt, 'ShaderNodeSeparateXYZ', (-1200, -300))
    link(nt, tc.outputs['Generated'], sep.inputs[0])
    if time != 'night':
        sky = node(nt, 'ShaderNodeTexSky', (-600, 100))
        sky.sky_type = 'MULTIPLE_SCATTERING'
        sky.sun_disc = False
        sky.sun_elevation = math.radians(max(el, 0.5))
        sky.sun_rotation = math.radians(azimuth)
        sky.altitude = 20.0
        # 昼はかすみを少なく（白っぽくならないように）。朝夕は少し多めで色が出る
        sky.aerosol_density = (0.7 if time == 'day' else 1.6) + 2.5 * storm
        bg = node(nt, 'ShaderNodeBackground', (-300, 100), Strength=sky_str * (1 - 0.4 * storm))
        if time == 'day' and storm < 0.5:
            # 昼の空は地平線ほど白くなりすぎるので、色を少し濃くする（海に映る空も青くなる）
            hs = node(nt, 'ShaderNodeHueSaturation', (-450, 100))
            hs.inputs['Saturation'].default_value = 1.55
            hs.inputs['Value'].default_value = 0.9
            link(nt, sky.outputs[0], hs.inputs['Color'])
            tint = node(nt, 'ShaderNodeMix', (-380, 100), data_type='RGBA', blend_type='MULTIPLY')
            tint.inputs['Factor'].default_value = 1.0
            link(nt, hs.outputs[0], tint.inputs[6])
            tint.inputs[7].default_value = (0.80, 0.90, 1.06, 1)   # 地平線の白を、うすい青に
            link(nt, tint.outputs[2], bg.inputs['Color'])
        else:
            link(nt, sky.outputs[0], bg.inputs['Color'])
        base = bg.outputs[0]
    else:
        # 夜：暗い青の空。地平線ほど少し明るい
        grad = map_range(nt, sep.outputs['Z'], 0.0, 0.6)
        col = node(nt, 'ShaderNodeMix', (-500, 100), data_type='RGBA')
        link(nt, grad, col.inputs['Factor'])
        col.inputs[6].default_value = (0.010, 0.014, 0.028, 1)
        col.inputs[7].default_value = (0.002, 0.003, 0.008, 1)
        bg = node(nt, 'ShaderNodeBackground', (-300, 100), Strength=1.0)
        link(nt, col.outputs[2], bg.inputs['Color'])
        base = bg.outputs[0]
    # 雲（方向から上空の面へ写した2次元のむら）。目に見える分だけ
    zc = math_op(nt, 'MAXIMUM', sep.outputs['Z'], 0.02, (-1050, -450))
    px = math_op(nt, 'DIVIDE', sep.outputs['X'], zc, (-900, -250))
    py = math_op(nt, 'DIVIDE', sep.outputs['Y'], zc, (-900, -400))
    cxy = node(nt, 'ShaderNodeCombineXYZ', (-750, -300))
    link(nt, px, cxy.inputs['X'])
    link(nt, py, cxy.inputs['Y'])
    mp = node(nt, 'ShaderNodeMapping', (-600, -300))
    mp.inputs['Scale'].default_value = (0.9, 0.55, 1.0)
    mp.inputs['Location'].default_value = (seed * 0.37, seed * 0.11, 0)
    link(nt, cxy.outputs[0], mp.inputs[0])
    cn = node(nt, 'ShaderNodeTexNoise', (-450, -300), Scale=1.1, Detail=9.0, Roughness=0.62)
    link(nt, mp.outputs[0], cn.inputs['Vector'])
    thr = 0.62 - 0.22 * cloud - 0.15 * storm
    cm = map_range(nt, cn.outputs['Fac'], thr, thr + 0.16)
    hz = map_range(nt, sep.outputs['Z'], 0.03, 0.22)
    cmask = math_op(nt, 'MULTIPLY', math_op(nt, 'MULTIPLY', cm, hz), 0.9)
    cloud_bg = node(nt, 'ShaderNodeBackground', (-300, -100))
    c = tuple(v * (1 - 0.55 * storm) for v in cl_c)
    cloud_bg.inputs['Color'].default_value = c + (1,)
    cloud_bg.inputs['Strength'].default_value = cl_s
    mix = node(nt, 'ShaderNodeMixShader', (350, 0))
    link(nt, math_op(nt, 'MULTIPLY', cmask, seen), mix.inputs[0])
    link(nt, base, mix.inputs[1])
    link(nt, cloud_bg.outputs[0], mix.inputs[2])
    final = mix.outputs[0]
    if stars:
        # 星：細かい点（カメラに見える分だけ）
        st = node(nt, 'ShaderNodeTexVoronoi', (-450, -650), Scale=420.0, feature='F1')
        link(nt, tc.outputs['Generated'], st.inputs['Vector'])
        dot = map_range(nt, st.outputs['Distance'], 0.0, 0.06, 1.0, 0.0)
        bright = map_range(nt, st.outputs['Color'], 0.9, 1.0)
        sm = math_op(nt, 'MULTIPLY', math_op(nt, 'MULTIPLY', dot, bright), map_range(nt, sep.outputs['Z'], 0.05, 0.3))
        sm = math_op(nt, 'MULTIPLY', math_op(nt, 'MULTIPLY', sm, seen), math_op(nt, 'SUBTRACT', 1.0, cmask))
        star_bg = node(nt, 'ShaderNodeBackground', (300, -300), Strength=3.0)
        star_bg.inputs['Color'].default_value = (0.9, 0.95, 1.0, 1)
        add = node(nt, 'ShaderNodeAddShader', (650, 0))
        sbg = node(nt, 'ShaderNodeMixShader', (500, -200))
        link(nt, sm, sbg.inputs[0])
        tr = node(nt, 'ShaderNodeBackground', (300, -450), Strength=0.0)
        link(nt, tr.outputs[0], sbg.inputs[1])
        link(nt, star_bg.outputs[0], sbg.inputs[2])
        link(nt, final, add.inputs[0])
        link(nt, sbg.outputs[0], add.inputs[1])
        final = add.outputs[0]
    link(nt, final, out.inputs['Surface'])
    # 太陽（夜は月の淡い光）
    if time == 'night':
        light = bpy.data.lights.new('月', 'SUN')
        light.energy = 0.22
        light.color = (0.65, 0.75, 1.0)
        light.angle = math.radians(0.5)
        el_l, az_l = 35.0, azimuth + 160
    else:
        light = bpy.data.lights.new('太陽', 'SUN')
        light.energy = sun_e * (1 - 0.7 * storm)
        light.color = sun_c
        light.angle = math.radians(0.6 + 3 * storm)
        el_l, az_l = el, azimuth
    lo = bpy.data.objects.new(light.name, light)
    link_object(lo)
    e, a = math.radians(el_l), math.radians(az_l)
    d = Vector((math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e)))
    lo.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
    return lo
