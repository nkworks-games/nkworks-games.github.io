"""地球の基礎キット：たくさん置く（ジオメトリーノードで、型のオブジェクトを点ごとに置く）"""
import bpy
import numpy as np

from .util import link, link_object, node


def instances(name, coll, items):
    """items：(x, y, z, 型の番号, 大きさ, z軸まわりの回転) の並び。coll の中のオブジェクトを型として使う"""
    if not items:
        return None
    arr = np.array(items, dtype=np.float64)
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(arr))
    me.vertices.foreach_set('co', arr[:, :3].astype(np.float32).ravel())
    for aname, col, kind in (('variant', 3, 'INT'), ('scale', 4, 'FLOAT'), ('rot', 5, 'FLOAT')):
        at = me.attributes.new(aname, kind, 'POINT')
        at.data.foreach_set('value', arr[:, col].astype(np.int32 if kind == 'INT' else np.float32))
    obj = bpy.data.objects.new(name, me)
    obj['nocheck'] = True   # 草木・岩は根元を地面に埋めて置く（めり込みの検査からは外す）
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
    e2r = node(ng, 'FunctionNodeEulerToRotation', (-200, -700))
    link(ng, cxyz.outputs[0], e2r.inputs[0])
    link(ng, e2r.outputs[0], iop.inputs['Rotation'])
    link(ng, iop.outputs[0], go.inputs[0])
    obj.modifiers.new('配置', 'NODES').node_group = ng
    return obj


def library(name):
    """場面には出さず、型を入れておく入れ物"""
    return bpy.data.collections.new(name)
