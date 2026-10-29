"""地球の基礎キット：材質

どの関数も、同じ名前の材質がすでにあればそれを返す（何度呼んでも1つだけ作る）。
色は線形の値（画面で見える色より暗い）。AgX の表示変換を前提に決めている。
"""
import bpy

from .util import finish, link, map_range, math_op, mix_color, mix_float, new_material, node


def _reuse(name):
    return bpy.data.materials.get(name)


# ---------------------------------------------------------------- 地面

# 地面の色の組（気候や星ごとに差し替える）
GROUND = {
    'temperate': dict(
        sand=((0.40, 0.35, 0.26, 1), (0.52, 0.46, 0.35, 1)),
        grass=((0.05, 0.085, 0.02, 1), (0.11, 0.13, 0.04, 1)),
        dry=(0.20, 0.17, 0.08, 1),
        floor=((0.035, 0.032, 0.02, 1), (0.08, 0.07, 0.04, 1)),
        soil=((0.16, 0.12, 0.08, 1), (0.25, 0.20, 0.13, 1)),
        rock=((0.07, 0.065, 0.06, 1), (0.17, 0.155, 0.13, 1)),
        strata=(0.13, 0.10, 0.075, 1),
        beach_top=(2.6, 3.6),
    ),
    # 火山の黒い砂浜と、乾いた草
    'volcanic': dict(
        sand=((0.035, 0.033, 0.032, 1), (0.07, 0.065, 0.06, 1)),
        grass=((0.07, 0.085, 0.025, 1), (0.15, 0.14, 0.05, 1)),
        dry=(0.24, 0.19, 0.09, 1),
        floor=((0.03, 0.027, 0.02, 1), (0.06, 0.05, 0.035, 1)),
        soil=((0.09, 0.06, 0.045, 1), (0.15, 0.10, 0.07, 1)),
        rock=((0.025, 0.024, 0.024, 1), (0.07, 0.065, 0.06, 1)),
        strata=(0.10, 0.06, 0.04, 1),
        beach_top=(2.2, 3.2),
    ),
}


def terrain(palette='temperate'):
    """地形：浜・濡れた砂・満潮線・草地・森の床・集落の土・岩肌・水の通り道

    地形のメッシュの点の値（無ければ 0 として働く）：
      canopy  森の床（木の下）0〜1
      village 踏み固めた土 0〜1
      flow    水の集まりやすさ 0〜1（谷筋が湿って暗くなる）
    """
    name = '地面・' + palette
    m = _reuse(name)
    if m:
        return m
    P = GROUND[palette]
    m, nt = new_material(name)
    geo = node(nt, 'ShaderNodeNewGeometry', (-1600, 0))
    sep = node(nt, 'ShaderNodeSeparateXYZ', (-1400, 100))
    link(nt, geo.outputs['Position'], sep.inputs[0])
    sepn = node(nt, 'ShaderNodeSeparateXYZ', (-1400, -150))
    link(nt, geo.outputs['Normal'], sepn.inputs[0])
    tc = node(nt, 'ShaderNodeTexCoord', (-1600, -400))
    obj = tc.outputs['Object']
    n1 = node(nt, 'ShaderNodeTexNoise', (-1400, -400), Scale=0.08, Detail=8.0, Roughness=0.6)
    n2 = node(nt, 'ShaderNodeTexNoise', (-1400, -650), Scale=1.6, Detail=10.0, Roughness=0.65)
    n3 = node(nt, 'ShaderNodeTexNoise', (-1400, -1250), Scale=0.018, Detail=4.0, Roughness=0.55)
    for n in (n1, n2, n3):
        link(nt, obj, n.inputs['Vector'])
    strata = node(nt, 'ShaderNodeTexWave', (-1400, -1650), Scale=0.06, Distortion=6.0, Detail=4.0,
                  wave_type='BANDS', bands_direction='Z')
    link(nt, obj, strata.inputs['Vector'])
    a_can = node(nt, 'ShaderNodeAttribute', (-1400, -900), attribute_name='canopy').outputs['Fac']
    a_vil = node(nt, 'ShaderNodeAttribute', (-1400, -1050), attribute_name='village').outputs['Fac']
    a_flow = node(nt, 'ShaderNodeAttribute', (-1400, -1150), attribute_name='flow').outputs['Fac']
    z = sep.outputs['Z']

    sand = mix_color(nt, n2.outputs['Fac'], *P['sand'], (-1000, 400))
    grass = mix_color(nt, n1.outputs['Fac'], *P['grass'], (-1100, 200))
    grass = mix_color(nt, map_range(nt, n3.outputs['Fac'], 0.5, 0.68), grass, P['dry'], (-1000, 200))
    floor = mix_color(nt, n2.outputs['Fac'], *P['floor'], (-1000, 0))
    soil = mix_color(nt, n2.outputs['Fac'], *P['soil'], (-1000, -200))
    rock = mix_color(nt, n1.outputs['Fac'], *P['rock'], (-1100, -400))
    rock = mix_color(nt, strata.outputs['Fac'], rock, P['strata'], (-1000, -500))
    land = mix_color(nt, a_can, grass, floor, (-800, 100))
    land = mix_color(nt, map_range(nt, a_vil, 0.25, 0.75), land, soil, (-650, 100))
    # 谷筋は湿って暗い
    damp = math_op(nt, 'MULTIPLY', map_range(nt, a_flow, 0.15, 0.8), 0.45, (-700, -50))
    land = mix_color(nt, damp, land, P['floor'][0], (-550, 100))
    # 浜から草地へ（境目はむらで崩す）
    zj = node(nt, 'ShaderNodeMath', (-1100, 600), operation='MULTIPLY_ADD')
    link(nt, n1.outputs['Fac'], zj.inputs[0])
    zj.inputs[1].default_value = 1.6
    link(nt, z, zj.inputs[2])
    col = mix_color(nt, map_range(nt, zj.outputs[0], *P['beach_top']), sand, land, (-500, 300))
    steep = map_range(nt, sepn.outputs['Z'], 0.82, 0.68)
    col = mix_color(nt, steep, col, rock, (-350, 300))
    # 波打ち際の濡れた砂
    wet = map_range(nt, z, 0.9, 0.15)
    wetcol = mix_color(nt, 1.0, col, (0.55, 0.52, 0.48, 1), (-200, 450), blend='MULTIPLY')
    col = mix_color(nt, wet, col, wetcol, (-50, 300))
    # 満潮線の打ち上げ（海藻や流木のかけら）
    wn = node(nt, 'ShaderNodeMath', (-300, 600), operation='MULTIPLY_ADD')
    link(nt, n2.outputs['Fac'], wn.inputs[0])
    wn.inputs[1].default_value = 0.35
    link(nt, z, wn.inputs[2])
    wr = math_op(nt, 'MINIMUM', map_range(nt, wn.outputs[0], 1.15, 1.28), map_range(nt, wn.outputs[0], 1.38, 1.30))
    wr = math_op(nt, 'MULTIPLY', wr, map_range(nt, n1.outputs['Fac'], 0.45, 0.6))
    col = mix_color(nt, wr, col, (0.07, 0.06, 0.035, 1), (50, 450))
    # 水の中の砂、深い所の海草の群れ
    col = mix_color(nt, map_range(nt, z, -0.1, -1.5), col, (0.50, 0.47, 0.36, 1), (100, 300))
    bed = math_op(nt, 'MULTIPLY', map_range(nt, n3.outputs['Fac'], 0.5, 0.6), map_range(nt, z, -3.0, -4.5))
    col = mix_color(nt, bed, col, (0.035, 0.05, 0.02, 1), (250, 300))
    rough = mix_float(nt, wet, 1.0, 0.3, (100, 0))
    bn = node(nt, 'ShaderNodeTexNoise', (-400, -500), Scale=6.0, Detail=12.0, Roughness=0.7)
    link(nt, obj, bn.inputs['Vector'])
    bump = node(nt, 'ShaderNodeBump', (100, -300), Strength=0.45, Distance=0.2)
    link(nt, bn.outputs['Fac'], bump.inputs['Height'])
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled', (300, 200))
    link(nt, col, bsdf.inputs['Base Color'])
    link(nt, rough, bsdf.inputs['Roughness'])
    link(nt, mix_float(nt, wet, 0.12, 0.5, (100, -100)), bsdf.inputs['Specular IOR Level'])
    link(nt, bump.outputs['Normal'], bsdf.inputs['Normal'])
    finish(nt, bsdf.outputs[0], (800, 200))
    return m


# ---------------------------------------------------------------- 岩

ROCKS = {
    # 名前: (暗い色, 明るい色, 苔の量)
    'basalt': ((0.030, 0.029, 0.028, 1), (0.10, 0.095, 0.085, 1), 0.35),
    'granite': ((0.13, 0.12, 0.11, 1), (0.36, 0.34, 0.31, 1), 0.25),
    'sandstone': ((0.17, 0.11, 0.065, 1), (0.40, 0.29, 0.18, 1), 0.2),
    'shore': ((0.045, 0.042, 0.038, 1), (0.16, 0.145, 0.12, 1), 0.15),
}


def rock(kind='shore'):
    """岩：割れ目、色むら、上向きの面の苔、水際の濡れて暗い帯と海藻（世界の高さ z=0 が海面）"""
    name = '岩・' + kind
    m = _reuse(name)
    if m:
        return m
    c1, c2, moss_amount = ROCKS[kind]
    m, nt = new_material(name)
    tc = node(nt, 'ShaderNodeTexCoord', (-1200, 0))
    obj = tc.outputs['Object']
    geo = node(nt, 'ShaderNodeNewGeometry', (-1200, 300))
    sep = node(nt, 'ShaderNodeSeparateXYZ', (-1000, 300))
    link(nt, geo.outputs['Position'], sep.inputs[0])
    sn = node(nt, 'ShaderNodeSeparateXYZ', (-1000, 500))
    link(nt, geo.outputs['Normal'], sn.inputs[0])
    n1 = node(nt, 'ShaderNodeTexNoise', (-900, 0), Scale=1.1, Detail=10.0, Roughness=0.65)
    link(nt, obj, n1.inputs['Vector'])
    wn = node(nt, 'ShaderNodeTexNoise', (-1100, -250), Scale=1.5, Detail=4.0)
    link(nt, obj, wn.inputs['Vector'])
    wv = node(nt, 'ShaderNodeVectorMath', (-1000, -250), operation='MULTIPLY_ADD')
    link(nt, wn.outputs['Color'], wv.inputs[0])
    wv.inputs[1].default_value = (0.8, 0.8, 0.8)
    link(nt, obj, wv.inputs[2])
    vo = node(nt, 'ShaderNodeTexVoronoi', (-900, -250), Scale=1.6, feature='DISTANCE_TO_EDGE')
    link(nt, wv.outputs[0], vo.inputs['Vector'])
    oi = node(nt, 'ShaderNodeObjectInfo', (-900, 250))
    f = node(nt, 'ShaderNodeMath', (-700, 100), operation='MULTIPLY_ADD')
    link(nt, oi.outputs['Random'], f.inputs[0])
    f.inputs[1].default_value = 0.3
    link(nt, n1.outputs['Fac'], f.inputs[2])
    base = mix_color(nt, f.outputs[0], c1, c2, (-500, 100))
    crack = map_range(nt, vo.outputs['Distance'], 0.0, 0.03, 0.75, 0.0)
    col = mix_color(nt, crack, base, (0.012, 0.012, 0.01, 1), (-300, 100))
    # 苔と地衣類：上を向いた面に、むらをつけて
    mn = node(nt, 'ShaderNodeTexNoise', (-900, 650), Scale=2.5, Detail=8.0, Roughness=0.7)
    link(nt, obj, mn.inputs['Vector'])
    up = map_range(nt, sn.outputs['Z'], 0.35, 0.85)
    patch = map_range(nt, mn.outputs['Fac'], 0.62 - 0.25 * moss_amount, 0.70 - 0.25 * moss_amount)
    moss = math_op(nt, 'MULTIPLY', up, patch)
    dry_land = map_range(nt, sep.outputs['Z'], 1.2, 2.2)
    moss = math_op(nt, 'MULTIPLY', moss, dry_land)
    mcol = mix_color(nt, mn.outputs['Fac'], (0.03, 0.05, 0.012, 1), (0.08, 0.10, 0.03, 1), (-300, 500))
    col = mix_color(nt, moss, col, mcol, (-150, 200))
    # 水際：濡れて暗く、海藻がつく
    wet = map_range(nt, sep.outputs['Z'], 0.7, 0.1)
    col = mix_color(nt, wet, col, (0.025, 0.03, 0.015, 1), (-50, 100))
    rough = mix_float(nt, wet, 0.9, 0.35, (-100, -150))
    hb = node(nt, 'ShaderNodeMath', (-300, -400), operation='MULTIPLY_ADD')
    link(nt, crack, hb.inputs[0])
    hb.inputs[1].default_value = -0.5
    link(nt, n1.outputs['Fac'], hb.inputs[2])
    bp = node(nt, 'ShaderNodeBump', (-100, -400), Strength=0.8, Distance=0.08)
    link(nt, hb.outputs[0], bp.inputs['Height'])
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled', (150, 100))
    link(nt, col, bsdf.inputs['Base Color'])
    link(nt, rough, bsdf.inputs['Roughness'])
    bsdf.inputs['Specular IOR Level'].default_value = 0.3
    link(nt, bp.outputs['Normal'], bsdf.inputs['Normal'])
    finish(nt, bsdf.outputs[0], (600, 100))
    return m


# ---------------------------------------------------------------- 植物

def bark(name, c1, c2, kind='fissured'):
    """樹皮。UV（u は幹のまわり、v は幹に沿った長さ）で模様を幹の向きにそろえる

    kind: fissured（縦の割れ目）, smooth（なめらか・まだら）, plates（松の亀甲）, rings（ヤシの輪）
    """
    mname = '樹皮・' + name
    m = _reuse(mname)
    if m:
        return m
    m, nt = new_material(mname)
    uv = node(nt, 'ShaderNodeUVMap', (-1200, 0)).outputs['UV']
    mp = node(nt, 'ShaderNodeMapping', (-1000, 0))
    link(nt, uv, mp.inputs['Vector'])
    oi = node(nt, 'ShaderNodeObjectInfo', (-1000, 300))
    link(nt, oi.outputs['Random'], mp.inputs['Location'])
    vec = mp.outputs[0]
    n = node(nt, 'ShaderNodeTexNoise', (-800, 200), Scale=6.0, Detail=10.0, Roughness=0.65)
    link(nt, vec, n.inputs['Vector'])
    if kind == 'rings':
        tx = node(nt, 'ShaderNodeTexWave', (-800, -100), Scale=2.2, Distortion=1.5, Detail=3.0,
                  wave_type='BANDS', bands_direction='Y', wave_profile='SAW')
        link(nt, vec, tx.inputs['Vector'])
        h = tx.outputs['Fac']
    elif kind == 'plates':
        sc = node(nt, 'ShaderNodeMapping', (-900, -100))
        sc.inputs['Scale'].default_value = (5.0, 1.6, 1.0)
        link(nt, vec, sc.inputs['Vector'])
        tx = node(nt, 'ShaderNodeTexVoronoi', (-800, -100), Scale=1.0, feature='DISTANCE_TO_EDGE')
        link(nt, sc.outputs[0], tx.inputs['Vector'])
        h = map_range(nt, tx.outputs['Distance'], 0.0, 0.12)
    elif kind == 'smooth':
        h = n.outputs['Fac']
    else:
        sc = node(nt, 'ShaderNodeMapping', (-900, -100))
        sc.inputs['Scale'].default_value = (9.0, 0.9, 1.0)
        link(nt, vec, sc.inputs['Vector'])
        warp = node(nt, 'ShaderNodeTexNoise', (-900, -300), Scale=3.0, Detail=3.0)
        link(nt, vec, warp.inputs['Vector'])
        wv = node(nt, 'ShaderNodeVectorMath', (-850, -200), operation='MULTIPLY_ADD')
        link(nt, warp.outputs['Color'], wv.inputs[0])
        wv.inputs[1].default_value = (0.5, 0.5, 0.0)
        link(nt, sc.outputs[0], wv.inputs[2])
        tx = node(nt, 'ShaderNodeTexVoronoi', (-800, -100), Scale=1.0, feature='DISTANCE_TO_EDGE')
        link(nt, wv.outputs[0], tx.inputs['Vector'])
        h = map_range(nt, tx.outputs['Distance'], 0.0, 0.18)
    col = mix_color(nt, n.outputs['Fac'], c1, c2, (-500, 200))
    col = mix_color(nt, map_range(nt, h, 0.35, 0.0), col, (c1[0] * 0.4, c1[1] * 0.4, c1[2] * 0.4, 1), (-350, 200))
    # 地衣類のまだら
    ln = node(nt, 'ShaderNodeTexNoise', (-800, 500), Scale=14.0, Detail=6.0, Roughness=0.6)
    link(nt, vec, ln.inputs['Vector'])
    lich = map_range(nt, ln.outputs['Fac'], 0.64, 0.70)
    col = mix_color(nt, math_op(nt, 'MULTIPLY', lich, 0.6), col, (0.20, 0.22, 0.17, 1), (-200, 200))
    bp = node(nt, 'ShaderNodeBump', (-200, -200), Strength=0.9, Distance=0.04)
    link(nt, h, bp.inputs['Height'])
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled', (50, 100))
    link(nt, col, bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = 0.92
    bsdf.inputs['Specular IOR Level'].default_value = 0.2
    link(nt, bp.outputs['Normal'], bsdf.inputs['Normal'])
    finish(nt, bsdf.outputs[0], (500, 100))
    return m


def leaf(name, c1, c2, gloss=0.45, translucency=0.3, autumn=0.0):
    """葉：1枚ずつ色を変え、裏は白っぽく、日に透ける。葉脈と縁は UV（u は葉の幅、v は葉の長さ）から作る

    autumn: 0〜1。黄や赤の葉の割合
    """
    mname = '葉・' + name
    m = _reuse(mname)
    if m:
        return m
    m, nt = new_material(mname)
    geo = node(nt, 'ShaderNodeNewGeometry', (-1100, 0))
    oi = node(nt, 'ShaderNodeObjectInfo', (-1100, 250))
    uv = node(nt, 'ShaderNodeUVMap', (-1100, -300)).outputs['UV']
    suv = node(nt, 'ShaderNodeSeparateXYZ', (-950, -300))
    link(nt, uv, suv.inputs[0])
    r = node(nt, 'ShaderNodeMath', (-850, 100), operation='MULTIPLY_ADD')
    link(nt, oi.outputs['Random'], r.inputs[0])
    r.inputs[1].default_value = 0.5
    link(nt, geo.outputs['Random Per Island'], r.inputs[2])
    rr = math_op(nt, 'FRACT', r.outputs[0])
    ramp = node(nt, 'ShaderNodeValToRGB', (-700, 100))
    el = ramp.color_ramp.elements
    el[0].color = c1
    if autumn > 0:
        # 緑 → 黄 → 橙 → 赤（autumn が大きいほど、色づいた葉が多い）
        el[1].color = (0.32, 0.06, 0.02, 1)
        el.new(1 - 0.25 * autumn).color = (0.40, 0.20, 0.02, 1)
        el.new(1 - 0.45 * autumn).color = (0.38, 0.30, 0.04, 1)
        el.new(1 - 0.6 * autumn).color = c2
    else:
        el[1].color = c2
        el.new(0.88).color = (c2[0] * 1.35 + 0.03, c2[1] * 1.15, c2[2] * 0.7, 1)
    link(nt, rr, ramp.inputs['Fac'])
    # 木ごとの色合い
    tint = node(nt, 'ShaderNodeValToRGB', (-700, 350))
    tt = tint.color_ramp.elements
    tt[0].color = (0.85, 0.94, 0.82, 1)
    tt[1].color = (1.08, 1.05, 0.82, 1)
    tt.new(0.55).color = (1.0, 1.0, 1.0, 1)
    link(nt, oi.outputs['Random'], tint.inputs['Fac'])
    col = mix_color(nt, 1.0, ramp.outputs['Color'], tint.outputs['Color'], (-500, 200), blend='MULTIPLY')
    # 中央の葉脈は明るく、縁は少し暗い
    du = math_op(nt, 'ABSOLUTE', math_op(nt, 'SUBTRACT', suv.outputs['X'], 0.5))
    rib = map_range(nt, du, 0.03, 0.0)
    rib = math_op(nt, 'MULTIPLY', rib, 0.5)
    col = mix_color(nt, rib, col, (c2[0] * 1.8 + 0.02, c2[1] * 1.6 + 0.02, c2[2] * 1.3, 1), (-350, 200))
    edge = math_op(nt, 'MULTIPLY', map_range(nt, du, 0.3, 0.5), 0.35)
    col = mix_color(nt, edge, col, (c1[0] * 0.6, c1[1] * 0.6, c1[2] * 0.6, 1), (-250, 200))
    # 裏面は白っぽく、つやが少ない
    back = geo.outputs['Backfacing']
    under = mix_color(nt, 1.0, col, (0.16, 0.18, 0.10, 1), (-150, 350), blend='SCREEN')
    col = mix_color(nt, back, col, under, (-50, 200))
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled', (150, 200))
    link(nt, col, bsdf.inputs['Base Color'])
    link(nt, mix_float(nt, back, 1.0 - gloss, 0.75), bsdf.inputs['Roughness'])
    bsdf.inputs['Specular IOR Level'].default_value = 0.35 + 0.2 * gloss
    tl = node(nt, 'ShaderNodeBsdfTranslucent', (150, -150))
    tcol = mix_color(nt, 1.0, col, (1.4, 1.5, 0.6, 1), (0, -150), blend='MULTIPLY')
    link(nt, tcol, tl.inputs['Color'])
    mix = node(nt, 'ShaderNodeMixShader', (350, 50))
    mix.inputs[0].default_value = translucency
    link(nt, bsdf.outputs[0], mix.inputs[1])
    link(nt, tl.outputs[0], mix.inputs[2])
    finish(nt, mix.outputs[0], (700, 50))
    return m


def grass(name, base, mid, tip, dry=0.3, translucency=0.35):
    """草の葉：根元は暗く、先は明るく乾いた色。株ごと・葉ごとに色を変える（UV の v が根元0→先1）"""
    mname = '草・' + name
    m = _reuse(mname)
    if m:
        return m
    m, nt = new_material(mname)
    geo = node(nt, 'ShaderNodeNewGeometry', (-1100, 0))
    oi = node(nt, 'ShaderNodeObjectInfo', (-1100, 250))
    uv = node(nt, 'ShaderNodeUVMap', (-1100, -300)).outputs['UV']
    suv = node(nt, 'ShaderNodeSeparateXYZ', (-950, -300))
    link(nt, uv, suv.inputs[0])
    v = suv.outputs['Y']
    ramp = node(nt, 'ShaderNodeValToRGB', (-700, 0))
    el = ramp.color_ramp.elements
    el[0].color = (base[0] * 0.35, base[1] * 0.35, base[2] * 0.35, 1)
    el[1].color = tip
    el.new(0.25).color = base
    el.new(0.65).color = mid
    link(nt, v, ramp.inputs['Fac'])
    # 葉ごとの乾き具合
    r = node(nt, 'ShaderNodeMath', (-850, 300), operation='MULTIPLY_ADD')
    link(nt, oi.outputs['Random'], r.inputs[0])
    r.inputs[1].default_value = 0.37
    link(nt, geo.outputs['Random Per Island'], r.inputs[2])
    rr = math_op(nt, 'FRACT', r.outputs[0])
    dryf = map_range(nt, rr, 1.0 - dry, 1.0)
    col = mix_color(nt, math_op(nt, 'MULTIPLY', dryf, 0.8), ramp.outputs['Color'], (0.26, 0.21, 0.10, 1), (-450, 100))
    hue = mix_color(nt, rr, (0.9, 1.0, 0.85, 1), (1.1, 1.0, 0.9, 1), (-450, 300))
    col = mix_color(nt, 1.0, col, hue, (-300, 100), blend='MULTIPLY')
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled', (-50, 150))
    link(nt, col, bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = 0.6
    bsdf.inputs['Specular IOR Level'].default_value = 0.35
    tl = node(nt, 'ShaderNodeBsdfTranslucent', (-50, -150))
    tcol = mix_color(nt, 1.0, col, (1.3, 1.4, 0.6, 1), (-200, -150), blend='MULTIPLY')
    link(nt, tcol, tl.inputs['Color'])
    mix = node(nt, 'ShaderNodeMixShader', (200, 50))
    mix.inputs[0].default_value = translucency
    link(nt, bsdf.outputs[0], mix.inputs[1])
    link(nt, tl.outputs[0], mix.inputs[2])
    finish(nt, mix.outputs[0], (600, 50))
    return m


# ---------------------------------------------------------------- 水

def sea(algae=1.0, name='海'):
    """海：屈折する水面（細かい波は凹凸で）と、赤い光から先に吸う水の体積

    algae: 藻の指数（1が基準）。多いほど少し緑寄り。
    水面は影を落とさない（海底に日が届くように）。水の中を通る光は体積の吸収で弱まる。
    """
    m = _reuse(name)
    if m:
        return m
    m, nt = new_material(name)
    tc = node(nt, 'ShaderNodeTexCoord', (-1200, 0))
    mp = node(nt, 'ShaderNodeMapping', (-1000, 0))
    mp.inputs['Scale'].default_value = (1.0, 2.6, 1.0)
    link(nt, tc.outputs['Object'], mp.inputs['Vector'])
    mps = node(nt, 'ShaderNodeMapping', (-1000, 300))
    mps.inputs['Scale'].default_value = (0.35, 1.0, 1.0)
    link(nt, tc.outputs['Object'], mps.inputs['Vector'])

    def tex(vec, scale, detail, rough, loc):
        t = node(nt, 'ShaderNodeTexNoise', loc, Scale=scale, Detail=detail, Roughness=rough)
        link(nt, vec, t.inputs['Vector'])
        return t.outputs['Fac']

    h = tex(mp.outputs[0], 0.35, 6.0, 0.55, (-800, 100))
    for vec, scale, detail, rough, amp, y in ((mp.outputs[0], 3.2, 8.0, 0.62, 0.3, -150),
                                               (mps.outputs[0], 0.06, 3.0, 0.5, 1.6, 300),
                                               (mp.outputs[0], 6.0, 8.0, 0.62, 0.16, 500),
                                               (mp.outputs[0], 28.0, 4.0, 0.5, 0.025, 700)):
        a = node(nt, 'ShaderNodeMath', (-500, y), operation='MULTIPLY_ADD')
        link(nt, tex(vec, scale, detail, rough, (-800, y)), a.inputs[0])
        a.inputs[1].default_value = amp
        link(nt, h, a.inputs[2])
        h = a.outputs[0]
    bump = node(nt, 'ShaderNodeBump', (-400, 0), Strength=0.45, Distance=0.8)
    link(nt, h, bump.inputs['Height'])
    glass = node(nt, 'ShaderNodeBsdfGlass', (-150, 150))
    glass.inputs['Color'].default_value = (1, 1, 1, 1)
    glass.inputs['Roughness'].default_value = 0.03
    glass.inputs['IOR'].default_value = 1.333
    link(nt, bump.outputs['Normal'], glass.inputs['Normal'])
    lp = node(nt, 'ShaderNodeLightPath', (-150, 400))
    tr = node(nt, 'ShaderNodeBsdfTransparent', (-150, -150))
    mix = node(nt, 'ShaderNodeMixShader', (100, 150))
    link(nt, lp.outputs['Is Shadow Ray'], mix.inputs[0])
    link(nt, glass.outputs[0], mix.inputs[1])
    link(nt, tr.outputs[0], mix.inputs[2])
    # 吸収と散乱を1つの部品で扱う（別々の部品を足すとシェーダーの上限を超える）
    g = min(1.6, max(0.6, algae))
    vol = node(nt, 'ShaderNodeVolumePrincipled', (-150, -400))
    vol.inputs['Color'].default_value = (0.008, 0.03, 0.028, 1)
    vol.inputs['Density'].default_value = 0.14
    vol.inputs['Absorption Color'].default_value = (0.03, 0.55 + 0.06 * (g - 1), 0.62, 1)
    out = node(nt, 'ShaderNodeOutputMaterial', (350, 0))
    link(nt, mix.outputs[0], out.inputs['Surface'])
    link(nt, vol.outputs[0], out.inputs['Volume'])
    return m


def foam():
    """波打ち際の泡。depth（その場所の海底の高さ）が 0 に近いほど、むらのある白い泡が出る"""
    m = _reuse('泡')
    if m:
        return m
    m, nt = new_material('泡')
    tc = node(nt, 'ShaderNodeTexCoord', (-900, 0))
    mp = node(nt, 'ShaderNodeMapping', (-700, 0))
    mp.inputs['Scale'].default_value = (1.0, 3.0, 1.0)
    link(nt, tc.outputs['Object'], mp.inputs['Vector'])
    n = node(nt, 'ShaderNodeTexNoise', (-500, 0), Scale=0.9, Detail=10.0, Roughness=0.7)
    link(nt, mp.outputs[0], n.inputs['Vector'])
    vo = node(nt, 'ShaderNodeTexVoronoi', (-500, -250), Scale=1.8, feature='DISTANCE_TO_EDGE')
    link(nt, tc.outputs['Object'], vo.inputs['Vector'])
    depth = node(nt, 'ShaderNodeAttribute', (-500, 250), attribute_name='depth').outputs['Fac']
    band = map_range(nt, depth, -0.4, -0.04)
    lace = map_range(nt, vo.outputs['Distance'], 0.0, 0.09, 1.0, 0.0)
    patchy = map_range(nt, n.outputs['Fac'], 0.42, 0.62)
    f = math_op(nt, 'MULTIPLY', math_op(nt, 'MULTIPLY', math_op(nt, 'MAXIMUM', patchy, lace), band), 0.7)
    white = node(nt, 'ShaderNodeBsdfPrincipled', (200, -100))
    white.inputs['Base Color'].default_value = (0.82, 0.84, 0.84, 1)
    white.inputs['Roughness'].default_value = 0.6
    tr = node(nt, 'ShaderNodeBsdfTransparent', (200, -300))
    mix = node(nt, 'ShaderNodeMixShader', (400, 0))
    link(nt, f, mix.inputs[0])
    link(nt, tr.outputs[0], mix.inputs[1])
    link(nt, white.outputs[0], mix.inputs[2])
    out = node(nt, 'ShaderNodeOutputMaterial', (600, 0))
    link(nt, mix.outputs[0], out.inputs['Surface'])
    return m


# ---------------------------------------------------------------- 人の作ったもの・その他

def simple(name, c1, c2, rough=0.8, scale=3.0, bump=0.3, stretch=(1, 1, 1), sss=0.0, kind='noise'):
    """むらと凹凸のある、単純な材質（木材・壁・茅・船体・帆など）"""
    m = _reuse(name)
    if m:
        return m
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
    col = mix_color(nt, jit.outputs[0], c1, c2, (-100, 100))
    bp = node(nt, 'ShaderNodeBump', (-100, -200), Strength=bump, Distance=0.05)
    link(nt, tx.outputs['Fac'], bp.inputs['Height'])
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled', (150, 100))
    link(nt, col, bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = rough
    bsdf.inputs['Specular IOR Level'].default_value = 0.25 if rough > 0.5 else 0.5
    link(nt, bp.outputs['Normal'], bsdf.inputs['Normal'])
    if sss:
        bsdf.inputs['Subsurface Weight'].default_value = sss
    finish(nt, bsdf.outputs[0], (600, 100))
    return m


def builtin():
    """集落や舟で使う材質の一式"""
    return {
        'wall_wood': simple('板壁', (0.13, 0.09, 0.055, 1), (0.26, 0.18, 0.11, 1), 0.8, 2.5, 0.5, (1, 1, 8), kind='wave'),
        'wall_daub': simple('土壁', (0.27, 0.21, 0.15, 1), (0.40, 0.33, 0.24, 1), 0.95, 2.0, 0.4),
        'thatch': simple('茅', (0.17, 0.13, 0.07, 1), (0.33, 0.26, 0.15, 1), 0.95, 9.0, 0.8, (1, 6, 1)),
        'wood': simple('木材', (0.18, 0.12, 0.07, 1), (0.32, 0.23, 0.14, 1), 0.85, 4.0, 0.4, (1, 1, 6), kind='wave'),
        'dark': simple('戸口', (0.02, 0.015, 0.01, 1), (0.05, 0.04, 0.03, 1), 0.9, 3.0, 0.1),
        'hull': simple('船体', (0.12, 0.08, 0.05, 1), (0.25, 0.17, 0.10, 1), 0.6, 3.0, 0.3, (1, 8, 1), kind='wave'),
        'hull_shell': simple('軽殻石の船体', (0.70, 0.72, 0.68, 1), (0.86, 0.87, 0.82, 1), 0.35, 2.0, 0.2),
        'sail': simple('帆', (0.55, 0.50, 0.42, 1), (0.70, 0.65, 0.55, 1), 0.9, 5.0, 0.2, sss=0.1),
    }
