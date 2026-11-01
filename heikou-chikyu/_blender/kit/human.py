"""地球の基礎キット：人（MakeHuman の体・骨格・重み〈CC0〉から作る）

assets/human.npz（kit/human_data.py で作る）を読んで、
  1. 体つきを決める（性別・年齢・人種の混ざり方・筋肉・体重・身長）
  2. 骨ごとの回転で姿勢をつける（重みで皮膚を動かす。Blender の骨は使わず、ここで計算して形を固める）
  3. 肌・髪（毛の粒子）・目・腰布（巻きスカート）・胸の布をつける
を行う。座標は Blender の z が上、y が前、原点は足もと（座る姿勢ではお尻の下）、単位は m。

pose：stand（立つ）、walk（歩く。phase で足の位置）、carry（頭に荷を載せる）、bend（かがんで拾う）、
      sit（膝を立てて座る）、paddle（舟に座ってこぐ）、look（遠くを見る・片手を額に）
"""
import math
import os

import bpy
import numpy as np
from mathutils import Matrix, Vector

from . import materials as M
from .util import link, link_object, map_range, math_op, mix_color, new_material, node, stream

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'assets', 'human.npz')
_D = {}

# 肌の色（線形の色）。暗い褐色〜明るい褐色
SKIN = [(0.105, 0.052, 0.030), (0.075, 0.037, 0.021), (0.140, 0.072, 0.042), (0.090, 0.046, 0.028)]
HAIR_MELANIN = (0.92, 0.97)


def available():
    return os.path.exists(DATA)


def data():
    if not _D:
        d = np.load(DATA)
        for k in d.files:
            _D[k] = d[k]
        off = np.concatenate([[0], np.cumsum(_D['f_len'])])
        _D['f_off'] = off
        _D['groups_l'] = list(_D['groups'])
        _D['bones_l'] = list(_D['bones'])
        _D['tnames'] = list(_D['target_names'])
        # 骨を親から順に
        par = _D['parent']
        order, seen = [], set()

        def visit(b):
            if b in seen:
                return
            if par[b] >= 0:
                visit(par[b])
            seen.add(b)
            order.append(b)
        for b in range(len(par)):
            visit(b)
        _D['order'] = order
    return _D


def to_bl(v):
    """MakeHuman（y が上・単位 dm・前が +z）→ Blender（z が上・m・前が +y）"""
    return np.stack([-v[..., 0], v[..., 2], v[..., 1]], -1) * 0.1


def shape(sex=1.0, age='young', race=(0.5, 0.5, 0.0), muscle=0.55, weight=0.45, height=0.5):
    """体つき。sex：1＝男・0＝女（間も可）。race：アフリカ・アジア・ヨーロッパの混ざり方"""
    d = data()
    v = d['verts'].astype(np.float32).copy()
    T = d['targets']
    names = d['tnames']

    def add(name, w):
        if abs(w) > 1e-6:
            v[:] += w * T[names.index(name)].astype(np.float32)
    rs = np.asarray(race, float)
    rs = rs / rs.sum()
    for sx, sw in (('male', sex), ('female', 1 - sex)):
        if sw <= 0:
            continue
        for r, rw in zip(('african', 'asian', 'caucasian'), rs):
            add('%s-%s-%s' % (r, sx, age), sw * rw)
        if muscle > 0.5:
            add('universal-%s-%s-maxmuscle-averageweight' % (sx, age), sw * (muscle - 0.5) * 2)
        else:
            add('universal-%s-%s-minmuscle-averageweight' % (sx, age), sw * (0.5 - muscle) * 2)
        if weight > 0.5:
            add('universal-%s-%s-averagemuscle-maxweight' % (sx, age), sw * (weight - 0.5) * 2)
        else:
            add('universal-%s-%s-averagemuscle-minweight' % (sx, age), sw * (0.5 - weight) * 2)
        if height > 0.5:
            add('height/%s-%s-averagemuscle-averageweight-maxheight' % (sx, age), sw * (height - 0.5) * 2)
        else:
            add('height/%s-%s-averagemuscle-averageweight-minheight' % (sx, age), sw * (0.5 - height) * 2)
    return to_bl(v)


# ---------------------------------------------------------------- 姿勢

def _rot_between(a, b):
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    c = np.cross(a, b)
    s = np.linalg.norm(c)
    dot = float(np.clip(a @ b, -1, 1))
    if s < 1e-8:
        return np.eye(3) if dot > 0 else -np.eye(3)
    k = c / s
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    ang = math.atan2(s, dot)
    return np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * K @ K


def _rot_axis(axis, deg):
    return np.array(Matrix.Rotation(math.radians(deg), 3, Vector(axis)))


def _n(*v):
    v = np.array(v, float)
    return v / np.linalg.norm(v)


def joints(v):
    d = data()
    jo, jv = d['joint_off'], d['joint_verts']
    return np.array([v[jv[jo[k]:jo[k + 1]]].mean(0) for k in range(len(jo) - 1)])


def pose_ops(pose, phase=0.0, side=1):
    """姿勢ごとの骨の向き。('aim', 終わりの骨, 向き)＝骨の付け根から終わりの骨の付け根へ向かう向き（世界の向き）、
    ('rot', 軸, 角度)＝世界の軸まわりの回転。L は体の左（−x）、R は右（+x）"""
    ops = {}

    def aim(b, end, *v):
        ops.setdefault(b, []).append(('aim', end, _n(*v)))

    def rot(b, axis, deg):
        ops.setdefault(b, []).append(('rot', np.array(axis, float), deg))

    def arms_down(spread=7, fore=12):
        for sd, s in (('L', -1), ('R', 1)):
            a = math.radians(spread)
            aim('upperarm01.' + sd, 'lowerarm01.' + sd, s * math.sin(a), -0.04, -math.cos(a))
            f = math.radians(fore)
            aim('lowerarm01.' + sd, 'wrist.' + sd, s * 0.05, math.sin(f), -math.cos(f))

    if pose in ('stand', 'look', 'carry'):
        arms_down()
    if pose in ('walk', 'carrywalk'):
        # 太ももの振れは三角波：地面についている間、足が一定の速さで後ろへ動く（体は一定の速さで進むので、足がすべらない）
        sw = 2 / math.pi * math.asin(math.sin(2 * math.pi * phase))
        for sd, s, sg in (('L', -1, 1), ('R', 1, -1)):
            a = math.radians(24) * sw * sg
            aim('upperleg01.' + sd, 'lowerleg01.' + sd, s * 0.05, math.sin(a), -math.cos(a))
            # 膝は、足が地面を離れている間（脚の位相 0.75〜1.25）だけ大きく曲げる
            pl = (phase + (0.0 if sg > 0 else 0.5)) % 1.0
            u = ((pl - 0.75) % 1.0) / 0.5
            flex = math.radians(5 + (62 * math.sin(math.pi * u) if u < 1.0 else 0.0))
            aim('lowerleg01.' + sd, 'foot.' + sd, s * 0.04, math.sin(a - flex), -math.cos(a - flex))
            b = -math.radians(18) * sw * sg
            aim('upperarm01.' + sd, 'lowerarm01.' + sd, s * 0.1, math.sin(b) - 0.03, -math.cos(b))
            f = math.radians(18) + max(0.0, b)
            aim('lowerarm01.' + sd, 'wrist.' + sd, s * 0.05, math.sin(f), -math.cos(f))
        rot('spine05', (1, 0, 0), 3)
    if pose in ('carry', 'carrywalk'):
        # 右手を頭の上の荷へ
        aim('upperarm01.R', 'lowerarm01.R', 0.45, 0.08, 0.89)
        aim('lowerarm01.R', 'wrist.R', -0.72, 0.05, 0.69)
        rot('spine05', (1, 0, 0), -2)
    if pose == 'look':
        aim('upperarm01.R', 'lowerarm01.R', 0.55, 0.55, 0.15)
        aim('lowerarm01.R', 'wrist.R', -0.75, 0.25, 0.62)
        rot('neck01', (0, 0, 1), 8)
    if pose == 'bend':
        for b, a in (('spine05', 30), ('spine04', 18), ('spine03', 12), ('spine02', 8)):
            rot(b, (1, 0, 0), -a)
        rot('neck01', (1, 0, 0), 25)
        for sd, s in (('L', -1), ('R', 1)):
            aim('upperleg01.' + sd, 'lowerleg01.' + sd, s * 0.08, 0.30, -0.95)
            aim('lowerleg01.' + sd, 'foot.' + sd, s * 0.05, -0.12, -0.99)
            aim('upperarm01.' + sd, 'lowerarm01.' + sd, s * 0.12, 0.25, -0.96)
            aim('lowerarm01.' + sd, 'wrist.' + sd, s * 0.05, 0.35, -0.94)
    if pose in ('sit', 'paddle'):
        lean = 14 if pose == 'sit' else 8 + 10 * math.sin(2 * math.pi * phase)
        rot('spine05', (1, 0, 0), -lean)
        for sd, s in (('L', -1), ('R', 1)):
            if pose == 'sit':
                aim('upperleg01.' + sd, 'lowerleg01.' + sd, s * 0.07, 0.84, 0.54)
                aim('lowerleg01.' + sd, 'foot.' + sd, s * 0.02, 0.22, -0.97)
                aim('upperarm01.' + sd, 'lowerarm01.' + sd, s * 0.12, 0.5, -0.86)
                aim('lowerarm01.' + sd, 'wrist.' + sd, -s * 0.15, 0.95, 0.1)
            else:
                aim('upperleg01.' + sd, 'lowerleg01.' + sd, s * 0.12, 0.97, 0.18)
                aim('lowerleg01.' + sd, 'foot.' + sd, s * 0.05, 0.35, -0.94)
                a = math.sin(2 * math.pi * phase)
                aim('upperarm01.' + sd, 'lowerarm01.' + sd, s * 0.25, 0.6 + 0.15 * a, -0.75)
                aim('lowerarm01.' + sd, 'wrist.' + sd, -s * 0.3, 0.9, -0.1 + 0.25 * a)
    return ops


def skin(v, ops):
    """骨の回転を、重みで皮膚に移す（線形の混ぜ合わせ）"""
    d = data()
    J = joints(v)
    bones = d['bones_l']
    bh, bt, par = d['bone_head'], d['bone_tail'], d['parent']
    nb = len(bones)
    G = np.tile(np.eye(4), (nb, 1, 1))
    Rw = np.tile(np.eye(3), (nb, 1, 1))
    for b in d['order']:
        p = par[b]
        Gp = G[p] if p >= 0 else np.eye(4)
        Rp = Rw[p] if p >= 0 else np.eye(3)
        R = np.eye(3)
        for op in ops.get(bones[b], []):
            if op[0] == 'aim':
                end = bones.index(op[1])
                d0 = J[bh[end]] - J[bh[b]]
                cur = R @ d0
                R = _rot_between(cur, Rp.T @ op[2]) @ R
            else:
                R = (Rp.T @ _rot_axis(op[1], op[2]) @ Rp) @ R
        h = J[bh[b]]
        L = np.eye(4)
        L[:3, :3] = R
        L[:3, 3] = h - R @ h
        G[b] = Gp @ L
        Rw[b] = Rp @ R
    wb, wv, ww = d['w_bone'], d['w_vert'], d['w_val'].astype(np.float64)
    tot = np.bincount(wv, ww, minlength=len(v))
    hv = np.concatenate([v, np.ones((len(v), 1))], 1)
    moved = np.einsum('kij,kj->ki', G[wb], hv[wv])[:, :3]
    out = np.zeros_like(v, dtype=np.float64)
    np.add.at(out, wv, moved * ww[:, None])
    has = tot > 1e-6
    res = v.astype(np.float64).copy()
    res[has] = out[has] / tot[has, None]
    head_top = (G[bones.index('head')] @ np.append(J[bt[bones.index('head')]], 1))[:3]
    return res, head_top


# ---------------------------------------------------------------- 形と材質

def _faces(groups, keep=None):
    d = data()
    gi = [d['groups_l'].index(g) for g in groups]
    sel = np.where(np.isin(d['fgroup'], gi))[0]
    off, fi, fu = d['f_off'], d['f_idx'], d['f_uv']
    faces, uvs = [], []
    for f in sel:
        ids = fi[off[f]:off[f + 1]]
        if keep is not None and not keep[ids].all():
            continue
        faces.append(ids)
        uvs.append(fu[off[f]:off[f + 1]])
    return faces, uvs


def _mesh(name, v, faces, uvs=None, mat_idx=None):
    used = np.unique(np.concatenate(faces))
    remap = -np.ones(len(v), np.int64)
    remap[used] = np.arange(len(used))
    me = bpy.data.meshes.new(name)
    me.from_pydata(v[used].tolist(), [], [remap[f].tolist() for f in faces])
    if uvs is not None:
        uvl = me.uv_layers.new(name='UVMap')
        allu = data()['uvs']
        loop_uv = np.concatenate([allu[u] for u in uvs])
        uvl.data.foreach_set('uv', loop_uv.ravel())
    if mat_idx is not None:
        me.polygons.foreach_set('material_index', np.asarray(mat_idx, np.int32))
    me.polygons.foreach_set('use_smooth', np.ones(len(me.polygons), bool))
    me.update()
    return me, used


def skin_material(k):
    name = '人の肌%d' % k
    m = bpy.data.materials.get(name)
    if m:
        return m
    m, nt = new_material(name)
    tc = node(nt, 'ShaderNodeTexCoord', (-900, 0))
    n1 = node(nt, 'ShaderNodeTexNoise', (-700, 100), Scale=40.0, Detail=6.0, Roughness=0.6)
    link(nt, tc.outputs['Object'], n1.inputs['Vector'])
    c = SKIN[k % len(SKIN)]
    col = mix_color(nt, map_range(nt, n1.outputs['Fac'], 0.35, 0.65), c + (1,), tuple(x * 1.18 for x in c) + (1,), (-450, 100))
    # 眉・唇（頂点の色 tone：R＝眉、G＝唇）
    attr = node(nt, 'ShaderNodeAttribute', (-700, -200), attribute_name='tone')
    sep = node(nt, 'ShaderNodeSeparateColor', (-500, -200))
    link(nt, attr.outputs['Color'], sep.inputs[0])
    col = mix_color(nt, sep.outputs[0], col, (0.012, 0.009, 0.007, 1), (-250, 50))
    col = mix_color(nt, sep.outputs[1], col, tuple(x * 0.75 for x in (c[0] * 1.15, c[1] * 0.8, c[2] * 0.8)) + (1,), (-100, 50))
    b = node(nt, 'ShaderNodeBsdfPrincipled', (150, 0))
    link(nt, col, b.inputs['Base Color'])
    b.inputs['Roughness'].default_value = 0.5
    b.inputs['Subsurface Weight'].default_value = 0.35
    b.inputs['Subsurface Radius'].default_value = (1.0, 0.4, 0.22)
    b.inputs['Subsurface Scale'].default_value = 0.008
    b.inputs['Specular IOR Level'].default_value = 0.45
    bn = node(nt, 'ShaderNodeTexNoise', (-450, -400), Scale=600.0, Detail=4.0)
    link(nt, tc.outputs['Object'], bn.inputs['Vector'])
    bump = node(nt, 'ShaderNodeBump', (-100, -300), Strength=0.08, Distance=0.002)
    link(nt, bn.outputs['Fac'], bump.inputs['Height'])
    link(nt, bump.outputs['Normal'], b.inputs['Normal'])
    out = node(nt, 'ShaderNodeOutputMaterial', (400, 0))
    link(nt, b.outputs[0], out.inputs['Surface'])
    return m


def eye_material():
    m = bpy.data.materials.get('人の目')
    if m:
        return m
    m, nt = new_material('人の目')
    attr = node(nt, 'ShaderNodeAttribute', (-600, 0), attribute_name='tone')
    sep = node(nt, 'ShaderNodeSeparateColor', (-400, 0))
    link(nt, attr.outputs['Color'], sep.inputs[0])
    col = mix_color(nt, sep.outputs[2], (0.55, 0.50, 0.46, 1), (0.02, 0.012, 0.008, 1), (-200, 0))
    b = node(nt, 'ShaderNodeBsdfPrincipled', (0, 0))
    link(nt, col, b.inputs['Base Color'])
    b.inputs['Roughness'].default_value = 0.08
    b.inputs['Coat Weight'].default_value = 1.0
    out = node(nt, 'ShaderNodeOutputMaterial', (250, 0))
    link(nt, b.outputs[0], out.inputs['Surface'])
    return m


def hair_material(melanin):
    name = '人の髪%.2f' % melanin
    m = bpy.data.materials.get(name)
    if m:
        return m
    m, nt = new_material(name)
    h = node(nt, 'ShaderNodeBsdfHairPrincipled', (0, 0))
    try:
        h.parametrization = 'MELANIN'
    except (AttributeError, TypeError):
        pass
    for k, v in (('Melanin', melanin), ('Melanin Redness', 0.4), ('Roughness', 0.45), ('Radial Roughness', 0.6), ('Coat', 0.1)):
        if k in h.inputs:
            h.inputs[k].default_value = v
    out = node(nt, 'ShaderNodeOutputMaterial', (250, 0))
    link(nt, h.outputs[0], out.inputs['Surface'])
    return m


def _tone(vb, rest_v):
    """眉（R）・唇（G）・目の黒目（B）の塗り分けを、頭の形（休めの姿勢）から決める"""
    d = data()
    g = d['groups_l']
    tone = np.zeros((len(rest_v), 4), np.float32)
    tone[:, 3] = 1
    eyes = []
    for side in ('l', 'r'):
        f, _ = _faces(['helper-%s-eye' % side])
        ids = np.unique(np.concatenate(f))
        c = rest_v[ids].mean(0)
        r = np.linalg.norm(rest_v[ids] - c, axis=1).mean()
        n = (rest_v[ids] - c) / np.maximum(np.linalg.norm(rest_v[ids] - c, axis=1, keepdims=True), 1e-9)
        tone[ids, 2] = np.clip((n[:, 1] - 0.72) / 0.1, 0, 1)
        eyes.append((c, r))
        # 眉：目の上 1.6〜2.4cm、横 ±2.2cm、前を向いた面
        dx = (rest_v[:, 0] - c[0]) / 0.024
        dz = (rest_v[:, 2] - (c[2] + 0.02)) / 0.0045
        front = rest_v[:, 1] > c[1] - 0.004
        br = np.clip(1.2 - (dx ** 2 + dz ** 2), 0, 1) * front
        tone[:, 0] = np.maximum(tone[:, 0], br)
    # 唇：両目の中心から下へ約 6.6cm、横 ±2.4cm
    ce = (eyes[0][0] + eyes[1][0]) / 2
    dx = (rest_v[:, 0] - ce[0]) / 0.024
    dz = (rest_v[:, 2] - (ce[2] - 0.066)) / 0.008
    front = rest_v[:, 1] > ce[1] - 0.005
    tone[:, 1] = np.clip(1.3 - (dx ** 2 + dz ** 2), 0, 1) * front * 0.6
    return tone


def _set_tone(me, used, tone):
    a = me.color_attributes.new('tone', 'FLOAT_COLOR', 'POINT')
    a.data.foreach_set('color', tone[used].ravel())


def _cloth_band(v_posed, v_rest, z0, z1, offset, arms_mask):
    """体の面のうち、高さ z0〜z1（休めの姿勢）で、腕でない所を、法線の向きに少しふくらませた布"""
    keep = (v_rest[:, 2] > z0) & (v_rest[:, 2] < z1) & ~arms_mask
    f, _ = _faces(['body'], keep)
    return f


CYCLIC = ('walk', 'carrywalk', 'paddle')
STRIDE = 1.45   # 歩く1周期（2歩）で進む距離 m（太ももの振れ ±24° と脚の長さから）


def _add_cycle_keys(ob, phases, used, offset=None):
    """歩く・こぐ動きの各位相を、形のキー（シェイプキー）として足す。0 番目は元の形"""
    ob.shape_key_add(name='位相0', from_mix=False)
    for k, vk in enumerate(phases[1:], 1):
        kb = ob.shape_key_add(name='位相%d' % k, from_mix=False)
        co = vk[used].astype(np.float32)
        if offset is not None:
            co = co + offset
        kb.data.foreach_set('co', co.ravel())
        kb.value = 0.0


def figure(name, seed, pose='stand', coll=None, child=False, phase=0.0, sex=None, height=None, cycle=0):
    """MakeHuman の体から作る人。返すのは体のオブジェクト（髪・目・布は子として付く）。
    cycle>0 で、歩く・こぐ姿勢の1周期を cycle 個の形のキーとして持つ（shots.py が時間に合わせて切り替える）"""
    rng = stream(seed, 'human', name)
    d = data()
    if sex is None:
        sex = 1.0 if rng.random() < 0.55 else 0.0
    age = 'child' if child else 'young'
    race = (rng.uniform(0.35, 0.65), rng.uniform(0.35, 0.65), rng.uniform(0.0, 0.1))
    v_rest = shape(sex, age, race, muscle=rng.uniform(0.5, 0.75), weight=rng.uniform(0.3, 0.5),
                   height=rng.uniform(0.3, 0.7) if height is None else height)
    v, head_top = skin(v_rest, pose_ops(pose, phase))
    # 足もと（いちばん低い所）を z=0 に、腰の真下を原点に
    bodyf, bodyuv = _faces(['body'])
    body_ids = np.unique(np.concatenate(bodyf))
    J = joints(v_rest)
    ox, oy = J[d['bone_head'][d['bones_l'].index('root')]][:2]
    oz = v[body_ids, 2].min()
    shift = np.array([ox, oy, oz])
    v = v - shift
    head_top = head_top - shift
    phases = None
    if cycle and pose in CYCLIC:
        phases = [v]
        for k in range(1, cycle):
            vk, _ = skin(v_rest, pose_ops(pose, (phase + k / cycle) % 1.0))
            vk = vk - shift
            vk[:, 2] -= vk[body_ids, 2].min() - v[body_ids, 2].min()   # 位相ごとに足もとを地面へ（体が少し上下する）
            phases.append(vk)
    tone = _tone(v, v_rest)
    k_skin = rng.randrange(len(SKIN))
    # 体と目（1つのメッシュ）
    eyef, eyeuv = _faces(['helper-l-eye', 'helper-r-eye'])
    faces = bodyf + eyef
    uvs = bodyuv + eyeuv
    mi = [0] * len(bodyf) + [1] * len(eyef)
    me, used = _mesh(name, v.astype(np.float32), faces, uvs, mi)
    me.materials.append(skin_material(k_skin))
    me.materials.append(eye_material())
    _set_tone(me, used, tone)
    ob = bpy.data.objects.new(name, me)
    parts = [ob]
    if phases:
        _add_cycle_keys(ob, phases, used)
    if coll is not False:
        link_object(ob, coll)
    sub = ob.modifiers.new('なめらか', 'SUBSURF')
    sub.levels, sub.render_levels = 0, 1
    # 腕の頂点（腕・手の骨に重みが大きい所）
    bones = d['bones_l']
    arm_b = [i for i, b in enumerate(bones) if b.startswith(('upperarm', 'lowerarm', 'wrist', 'finger', 'metacarpal', 'shoulder'))]
    arm_w = np.bincount(d['w_vert'][np.isin(d['w_bone'], arm_b)], d['w_val'][np.isin(d['w_bone'], arm_b)], minlength=len(v))
    arms = arm_w > 0.35
    # 布：腰から膝までの巻きスカート（helper-skirt の上の方）＋女性は胸の布
    z_knee = J[d['bone_head'][bones.index('lowerleg01.L')]][2]
    keep = v_rest[:, 2] > z_knee - (0.02 if pose not in ('sit', 'paddle') else -0.24)
    if pose in ('sit', 'paddle'):
        # 座ると巻きスカートは脚に沿う：体の面から、腰と太ももの上だけの布を作る
        z_hip = J[d['bone_head'][bones.index('upperleg01.L')]][2]
        cloth_faces = _cloth_band(v, v_rest, z_hip - 0.17, z_hip + 0.09, 0.006, arms)
    else:
        sk_f, sk_uv = _faces(['helper-skirt'], keep)
        cloth_faces = list(sk_f)
    if sex < 0.5:
        zc = J[d['bone_head'][bones.index('spine01')]][2]
        cloth_faces += _cloth_band(v, v_rest, zc - 0.10, zc + 0.07, 0.006, arms)
    if cloth_faces:
        cv = v.astype(np.float32).copy()
        # 体の面から作った布は、法線の向きへ 6mm 浮かせる
        me_tmp, used_tmp = _mesh(name + '_tmp', cv, cloth_faces)
        nrm = np.zeros((len(me_tmp.vertices), 3), np.float32)
        me_tmp.vertices.foreach_get('normal', nrm.ravel())
        co = np.zeros((len(me_tmp.vertices), 3), np.float32)
        me_tmp.vertices.foreach_get('co', co.ravel())
        co += nrm * 0.007
        me_tmp.vertices.foreach_set('co', co.ravel())
        cloth_used = used_tmp
        me_tmp.update()
        me_tmp.name = name + '布'
        k = rng.randrange(3)
        me_tmp.materials.append(M.simple('樹皮の布%d' % k, ((0.30, 0.24, 0.15, 1), (0.20, 0.13, 0.07, 1), (0.36, 0.33, 0.27, 1))[k],
                                         ((0.42, 0.35, 0.23, 1), (0.30, 0.20, 0.11, 1), (0.50, 0.46, 0.38, 1))[k], 0.95, 30.0, 0.3, (1, 1, 4), kind='wave'))
        cl = bpy.data.objects.new(name + '布', me_tmp)
        if coll is not False:
            link_object(cl, coll)
        sol = cl.modifiers.new('厚み', 'SOLIDIFY')
        sol.thickness = 0.004
        s2 = cl.modifiers.new('なめらか', 'SUBSURF')
        s2.levels, s2.render_levels = 0, 1
        cl.parent = ob
        parts.append(cl)
        if phases:
            _add_cycle_keys(cl, phases, cloth_used, nrm * 0.007)
    # 髪：頭皮（生え際より上・後ろ、耳を除く）の面から毛を生やす
    eye_c = []
    for side in ('l', 'r'):
        f_, _ = _faces(['helper-%s-eye' % side])
        eye_c.append(v_rest[np.unique(np.concatenate(f_))].mean(0))
    ec = (eye_c[0] + eye_c[1]) / 2
    back = ec[1] - v_rest[:, 1]                      # 目から後ろへの距離
    scalp = v_rest[:, 2] > ec[2] + 0.058 - 0.62 * np.clip(back, 0, 0.2)
    scalp &= ~((np.abs(v_rest[:, 0] - ec[0]) > 0.062) & (v_rest[:, 2] < ec[2] + 0.035))
    scalp &= v_rest[:, 2] > ec[2] - 0.075
    hf, _ = _faces(['body'], scalp)
    hme, hused = _mesh(name + '髪の根', v.astype(np.float32), hf)
    hob = bpy.data.objects.new(name + '髪', hme)
    hob['nocheck'] = True      # 毛の根の面（描かない）
    parts.append(hob)
    if phases:
        _add_cycle_keys(hob, phases, hused)
    if coll is not False:
        link_object(hob, coll)
    hob.parent = ob
    hob.modifiers.new('毛', 'PARTICLE_SYSTEM')
    ps = hob.particle_systems[0]
    ps.seed = seed % 1000
    st = ps.settings
    st.type = 'HAIR'
    long_hair = sex < 0.5 and rng.random() < 0.7
    st.count = 1600
    if long_hair:
        # 長い髪：外へ少し出てから、後ろと下へ流れる（前の毛が顔にかからない）
        st.use_advanced_hair = True
        st.normal_factor = 0.012
        st.object_align_factor = (0.0, -0.008, -0.075)   # 長さはおよそ 35〜40cm
        st.hair_step = 6
    else:
        st.use_advanced_hair = False
        st.hair_length = 0.03 * (0.75 if child else 1.0)
    st.emit_from = 'FACE'
    st.use_emit_random = True
    st.child_type = 'INTERPOLATED'
    st.child_percent = 20
    st.rendered_child_count = 30
    st.clump_factor = 0.2
    st.roughness_1 = 0.003
    st.roughness_endpoint = 0.003
    st.kink = 'CURL'
    st.kink_amplitude = 0.004
    st.kink_frequency = 20.0
    st.display_step = 3
    st.render_step = 4
    st.root_radius = 0.5
    st.tip_radius = 0.25
    st.radius_scale = 0.001
    hme.materials.append(hair_material(rng.uniform(*HAIR_MELANIN)))
    st.material = 1
    hob.show_instancer_for_render = False
    hob.show_instancer_for_viewport = False
    ob['head_top'] = list(map(float, head_top))
    ob['pose'] = pose
    # 足の裏の頂点（休めの姿勢で左右それぞれ一番低い 40 点。体のメッシュの番号で）。足すべりの検査に使う
    pos_in_body = -np.ones(len(v_rest), np.int64)
    pos_in_body[used] = np.arange(len(used))
    for sd, m in (('L', v_rest[body_ids, 0] < 0), ('R', v_rest[body_ids, 0] > 0)):
        ids = body_ids[m]
        ob['sole_' + sd] = [int(i) for i in pos_in_body[ids[np.argsort(v_rest[ids, 2])[:40]]]]
    if phases:
        ob['cycle'] = cycle
        ob['cycle_parts'] = [p.name for p in parts]
        ob['cycle_phase'] = float(phase)
        # 1周期で進む距離＝足の前後の振れ幅の2倍（この体と姿勢から測る。足がすべらないように）
        # 左足が地面につく瞬間（位相 0.25）と離れる瞬間（0.75）の、足の前後の位置の差が1歩
        sl_full = used[np.array(ob['sole_L'])]
        ya = float(np.mean(skin(v_rest, pose_ops(pose, 0.25))[0][sl_full, 1]))
        yb = float(np.mean(skin(v_rest, pose_ops(pose, 0.75))[0][sl_full, 1]))
        step = abs(ya - yb)
        ob['stride'] = round(2 * step, 3) if step > 0.2 else STRIDE * (0.65 if child else 1.0)
    if pose in ('carry', 'carrywalk'):
        # 頭に載せた籠（編み目のある浅い筒）
        from .vegetation import Builder
        B = Builder()
        c = Vector(head_top) + Vector((0, 0, 0.035))
        B.tube([c - Vector((0, 0, 0.02)), c + Vector((0, 0, 0.05)), c + Vector((0, 0, 0.16))], [0.13, 0.19, 0.22], segs=18, mat=0, cap=True)
        bk = B.finish(name + '籠', [M.simple('籠', (0.20, 0.14, 0.07, 1), (0.34, 0.25, 0.13, 1), 0.9, 60.0, 0.5, (1, 1, 1), kind='wave')], coll)
        bk.parent = ob
    return ob
