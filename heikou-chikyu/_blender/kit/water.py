"""地球の基礎キット：水（入り江の海の水の塊、波打ち際の泡、沖の波のある海）"""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

from . import materials as M
from .util import link, link_object, map_range, math_op, mesh_from_arrays, mesh_object, new_material, node


def sea_box(algae=1.0, center=(0, 2000), size=24000.0, depth=60.0):
    """入り江用の海：大きな水の塊（表面 z=0）。浅瀬は砂が透け、深いほど紺になる"""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Translation((center[0], center[1], -depth / 2)) @ Matrix.Diagonal(Vector((size, size, depth, 1))))
    sea = mesh_object('海', bm)
    sea.data.materials.append(M.sea(algae))
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size / 2, matrix=Matrix.Translation((center[0], center[1], -depth * 0.75)))
    fl = mesh_object('沖の海底', bm)
    fl.data.materials.append(M.rock('basalt'))
    return sea


def foam(ter):
    """波打ち際の泡（地形の高さから、浅い所だけの薄い面を作る）"""
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
    verts = np.stack([ter.X.ravel()[used], ter.Y.ravel()[used], np.full(len(used), 0.025)], axis=1)
    a = cells[:, 0] * nx + cells[:, 1]
    quads = np.stack([remap[a], remap[a + 1], remap[a + nx + 1], remap[a + nx]], axis=1)
    me = mesh_from_arrays('泡', verts, quads.ravel(), np.full(len(quads), 4))
    at = me.attributes.new('depth', 'FLOAT', 'POINT')
    at.data.foreach_set('value', H.ravel()[used].astype(np.float32))
    me.materials.append(M.foam())
    obj = bpy.data.objects.new('泡', me)
    link_object(obj)
    obj.visible_shadow = False
    return obj


def open_sea_material(name='沖の海'):
    """沖の深い海の水面：空を映す水面と、深い紺の水。白波は波の先（Ocean の泡の値）に出す"""
    m = bpy.data.materials.get(name)
    if m:
        return m
    m, nt = new_material(name)
    attr = node(nt, 'ShaderNodeAttribute', (-800, 200), attribute_name='foam')
    fm = map_range(nt, attr.outputs['Fac'], 0.75, 1.0)
    nz = node(nt, 'ShaderNodeTexNoise', (-800, -100), Scale=1.5, Detail=8.0)
    tc = node(nt, 'ShaderNodeTexCoord', (-1000, -100))
    link(nt, tc.outputs['Object'], nz.inputs['Vector'])
    fm = math_op(nt, 'MULTIPLY', fm, map_range(nt, nz.outputs['Fac'], 0.4, 0.6))
    water = node(nt, 'ShaderNodeBsdfPrincipled', (-300, 100))
    water.inputs['Base Color'].default_value = (0.002, 0.012, 0.022, 1)
    water.inputs['Roughness'].default_value = 0.04
    water.inputs['IOR'].default_value = 1.333
    water.inputs['Specular IOR Level'].default_value = 0.5
    water.inputs['Subsurface Weight'].default_value = 0.0
    # 細かいさざ波（世界の位置で。遠くの平らな面も鏡のようにならないように）
    geo = node(nt, 'ShaderNodeNewGeometry', (-1000, -400))
    rp = node(nt, 'ShaderNodeTexNoise', (-800, -400), Scale=0.08, Detail=10.0, Roughness=0.6)
    link(nt, geo.outputs['Position'], rp.inputs['Vector'])
    bump = node(nt, 'ShaderNodeBump', (-550, -400), Strength=0.35, Distance=1.0)
    link(nt, rp.outputs['Fac'], bump.inputs['Height'])
    link(nt, bump.outputs['Normal'], water.inputs['Normal'])
    water.inputs['Roughness'].default_value = 0.07
    white = node(nt, 'ShaderNodeBsdfPrincipled', (-300, -250))
    white.inputs['Base Color'].default_value = (0.75, 0.78, 0.78, 1)
    white.inputs['Roughness'].default_value = 0.7
    mix = node(nt, 'ShaderNodeMixShader', (0, 0))
    link(nt, fm, mix.inputs[0])
    link(nt, water.outputs[0], mix.inputs[1])
    link(nt, white.outputs[0], mix.inputs[2])
    out = node(nt, 'ShaderNodeOutputMaterial', (200, 0))
    link(nt, mix.outputs[0], out.inputs['Surface'])
    return m


def ocean(size=400.0, wave_scale=1.0, choppy=1.0, wind=10.0, resolution=14, seed=1, repeat=3, time=0.0):
    """沖の波のある海（Blender の Ocean。うねりと白波）。repeat 枚並べて広げる。遠くは平らな面でつなぐ"""
    me = bpy.data.meshes.new('沖の海')
    obj = bpy.data.objects.new('沖の海', me)
    link_object(obj)
    md = obj.modifiers.new('波', 'OCEAN')
    md.geometry_mode = 'GENERATE'
    md.resolution = resolution
    md.spatial_size = int(size)
    md.repeat_x = repeat
    md.repeat_y = repeat
    md.wave_scale = wave_scale
    md.choppiness = choppy
    md.wind_velocity = wind
    md.random_seed = seed
    md.use_foam = True
    md.foam_layer_name = 'foam'
    md.foam_coverage = -0.35
    md.time = time
    obj.location = (-size * repeat / 2, -size * repeat / 2, 0)
    obj.data.materials.append(open_sea_material())
    # 遠くの平らな海（同じ材質）
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=40000)
    far = mesh_object('遠くの海', bm)
    far.location = (0, 0, -2.0)
    far.data.materials.append(open_sea_material())
    return obj, md
