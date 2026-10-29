"""地球の基礎キット：共通の道具（乱数、ノード、メッシュ、空気遠近）"""
import hashlib
import math
import random

import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector


# ---------------------------------------------------------------- 乱数
# 部品ごとに名前つきの乱数を使う。木の本数が変わっても、岩や地形の乱数はずれない。

def stream(seed, *names):
    """種と名前から、独立した乱数を作る"""
    key = ':'.join(str(v) for v in (seed,) + names)
    return random.Random(int(hashlib.sha256(key.encode()).hexdigest()[:15], 16))


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------- ノード

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


def map_range(nt, src, a, b, lo=0.0, hi=1.0, loc=(0, 0)):
    r = node(nt, 'ShaderNodeMapRange', loc)
    r.inputs['From Min'].default_value = a
    r.inputs['From Max'].default_value = b
    r.inputs['To Min'].default_value = lo
    r.inputs['To Max'].default_value = hi
    r.clamp = True
    link(nt, src, r.inputs['Value'])
    return r.outputs['Result']


def mix_color(nt, fac, c1, c2, loc=(0, 0), blend='MIX'):
    mx = node(nt, 'ShaderNodeMix', loc, data_type='RGBA', blend_type=blend)
    if isinstance(fac, float):
        mx.inputs['Factor'].default_value = fac
    else:
        link(nt, fac, mx.inputs['Factor'])
    for i, c in ((6, c1), (7, c2)):
        if isinstance(c, tuple):
            mx.inputs[i].default_value = c
        else:
            link(nt, c, mx.inputs[i])
    return mx.outputs[2]


def mix_float(nt, fac, a, b, loc=(0, 0)):
    mx = node(nt, 'ShaderNodeMix', loc, data_type='FLOAT')
    link(nt, fac, mx.inputs['Factor'])
    for i, v in ((2, a), (3, b)):
        if isinstance(v, (float, int)):
            mx.inputs[i].default_value = float(v)
        else:
            link(nt, v, mx.inputs[i])
    return mx.outputs[0]


def math_op(nt, op, a, b=None, loc=(0, 0)):
    n = node(nt, 'ShaderNodeMath', loc, operation=op)
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (float, int)):
            n.inputs[i].default_value = float(v)
        else:
            link(nt, v, n.inputs[i])
    return n.outputs[0]


# ---------------------------------------------------------------- 空気遠近（遠くほど空の色に溶ける）

def haze_group(strength=0.3, distance=7000.0, limit=0.5, color=(0.70, 0.76, 0.86)):
    g = bpy.data.node_groups.get('Haze')
    if g:
        return g
    g = bpy.data.node_groups.new('Haze', 'ShaderNodeTree')
    g.interface.new_socket('Shader', in_out='INPUT', socket_type='NodeSocketShader')
    g.interface.new_socket('Shader', in_out='OUTPUT', socket_type='NodeSocketShader')
    gi = node(g, 'NodeGroupInput', (-600, 0))
    go = node(g, 'NodeGroupOutput', (400, 0))
    cam = node(g, 'ShaderNodeCameraData', (-600, -200))
    f = math_op(g, 'DIVIDE', cam.outputs['View Distance'], -distance, (-400, -200))
    f = math_op(g, 'EXPONENT', f, None, (-250, -200))
    f = math_op(g, 'SUBTRACT', 1.0, f, (-100, -200))
    f = math_op(g, 'MULTIPLY', f, limit, (50, -200))
    em = node(g, 'ShaderNodeEmission', (50, -380))
    em.inputs['Color'].default_value = color + (1,)
    em.inputs['Strength'].default_value = strength
    mix = node(g, 'ShaderNodeMixShader', (220, 0))
    link(g, f, mix.inputs[0])
    link(g, gi.outputs[0], mix.inputs[1])
    link(g, em.outputs[0], mix.inputs[2])
    link(g, mix.outputs[0], go.inputs[0])
    return g


def finish(nt, shader_socket, loc=(600, 0), haze=True):
    """霞を通して出力につなぐ"""
    out = node(nt, 'ShaderNodeOutputMaterial', loc)
    if haze:
        hz = node(nt, 'ShaderNodeGroup', (loc[0] - 200, loc[1]))
        hz.node_tree = haze_group()
        link(nt, shader_socket, hz.inputs[0])
        link(nt, hz.outputs[0], out.inputs['Surface'])
    else:
        link(nt, shader_socket, out.inputs['Surface'])
    return out


# ---------------------------------------------------------------- メッシュ

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


def mesh_from_arrays(name, verts, faces_flat, face_sizes):
    """頂点と面の配列から、速くメッシュを作る（大きな地形向け）"""
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(verts))
    me.vertices.foreach_set('co', np.asarray(verts, np.float32).ravel())
    me.loops.add(len(faces_flat))
    me.loops.foreach_set('vertex_index', np.asarray(faces_flat, np.int32))
    me.polygons.add(len(face_sizes))
    starts = np.concatenate([[0], np.cumsum(face_sizes)[:-1]]).astype(np.int32)
    me.polygons.foreach_set('loop_start', starts)
    me.polygons.foreach_set('loop_total', np.asarray(face_sizes, np.int32))
    me.update(calc_edges=True)
    return me


def shade_smooth(obj):
    obj.data.polygons.foreach_set('use_smooth', np.ones(len(obj.data.polygons), bool))


def hidden_collection(name):
    """場面には置かず、型として使う部品の入れ物"""
    return bpy.data.collections.new(name)


def add_box(bm, center, size, rot_z=0.0, tilt=None):
    m = Matrix.Translation(center) @ Matrix.Rotation(rot_z, 4, 'Z')
    if tilt is not None:
        m = m @ tilt
    m = m @ Matrix.Diagonal(Vector((size[0], size[1], size[2], 1.0)))
    return bmesh.ops.create_cube(bm, size=1.0, matrix=m)['verts']


def add_tube(bm, path, radii, segs=7, cap=False):
    """道すじに沿った先細りの筒（幹や枝）。向きは前後の点から決めて、ねじれを抑える"""
    rings = []
    prev_u = None
    for k, p in enumerate(path):
        d = (path[min(k + 1, len(path) - 1)] - path[max(k - 1, 0)])
        if d.length < 1e-9:
            d = Vector((0, 0, 1))
        d.normalize()
        if prev_u is None:
            u = d.orthogonal().normalized()
        else:
            u = (prev_u - d * prev_u.dot(d))
            u = u.normalized() if u.length > 1e-6 else d.orthogonal().normalized()
        prev_u = u
        v = d.cross(u).normalized()
        ring = [bm.verts.new(p + (u * math.cos(a) + v * math.sin(a)) * radii[k])
                for a in np.linspace(0, 2 * math.pi, segs, endpoint=False)]
        rings.append(ring)
    for k in range(len(rings) - 1):
        for s in range(segs):
            bm.faces.new([rings[k][s], rings[k][(s + 1) % segs], rings[k + 1][(s + 1) % segs], rings[k + 1][s]])
    if cap and radii[-1] > 0.02:
        bm.faces.new(rings[-1])
    return rings
