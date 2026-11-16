"""MakeHuman の素材（CC0）から、人を作るのに要る分だけを1つのファイル（assets/human.npz）にまとめる

    python3 heikou-chikyu/_blender/kit/human_data.py <MakeHuman の data フォルダ>

data フォルダは https://github.com/makehumancommunity/makehuman の makehuman/data。
使うもの：基本の体（3dobjs/base.obj）、体つきの差分（targets/macrodetails）、骨格（rigs/default.mhskel）と
骨ごとの重み（rigs/default_weights.mhw）。どれも CC0（MakeHuman の LICENSE.md「C. The license for the bundled assets」）。
MakeHuman のプログラム（AGPL）は使っていない。ファイルの形式を読んでいるだけ。
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'assets', 'human.npz')

RACES = ('african', 'asian', 'caucasian')
SEXES = ('male', 'female')
AGES = ('child', 'young', 'old')


def read_obj(path):
    vs, vts, faces, fuv, fgroup, groups = [], [], [], [], [], []
    g = None
    for line in open(path):
        if line.startswith('v '):
            vs.append([float(x) for x in line.split()[1:4]])
        elif line.startswith('vt '):
            vts.append([float(x) for x in line.split()[1:3]])
        elif line.startswith('g '):
            g = line.split()[1]
            if g not in groups:
                groups.append(g)
        elif line.startswith('f '):
            ids = [p.split('/') for p in line.split()[1:]]
            faces.append([int(p[0]) - 1 for p in ids])
            fuv.append([int(p[1]) - 1 if len(p) > 1 and p[1] else -1 for p in ids])
            fgroup.append(groups.index(g))
    return np.array(vs, np.float32), np.array(vts, np.float32), faces, fuv, np.array(fgroup, np.int16), groups


def read_target(path, nv):
    d = np.zeros((nv, 3), np.float32)
    for line in open(path):
        if line.startswith('#') or not line.strip():
            continue
        p = line.split()
        d[int(p[0])] = [float(p[1]), float(p[2]), float(p[3])]
    return d


def main():
    data = sys.argv[1]
    v, vt, faces, fuv, fgroup, groups = read_obj(os.path.join(data, '3dobjs', 'base.obj'))
    nv = len(v)
    out = dict(verts=v, uvs=vt, fgroup=fgroup, groups=np.array(groups))
    # 面（四角と三角がまざる）→ 長さの並び＋ひとつながりの並び
    out['f_len'] = np.array([len(f) for f in faces], np.int8)
    out['f_idx'] = np.array([i for f in faces for i in f], np.int32)
    out['f_uv'] = np.array([i for f in fuv for i in f], np.int32)
    # 体つきの差分（人種×性別×年齢、筋肉・体重、身長）
    names = []
    for r in RACES:
        for s in SEXES:
            for a in AGES:
                names.append('%s-%s-%s' % (r, s, a))
    for s in SEXES:
        for a in ('child', 'young', 'old'):
            for m in ('minmuscle-averageweight', 'maxmuscle-averageweight', 'averagemuscle-minweight', 'averagemuscle-maxweight'):
                names.append('universal-%s-%s-%s' % (s, a, m))
            for h in ('minheight', 'maxheight'):
                names.append('height/%s-%s-averagemuscle-averageweight-%s' % (s, a, h))
    tg = np.zeros((len(names), nv, 3), np.float16)
    for k, n in enumerate(names):
        tg[k] = read_target(os.path.join(data, 'targets', 'macrodetails', n + '.target'), nv)
    out['targets'] = tg
    out['target_names'] = np.array(names)
    # 骨格：関節（頂点の重心）、親、重み
    sk = json.load(open(os.path.join(data, 'rigs', 'default.mhskel')))
    bones = list(sk['bones'])
    out['bones'] = np.array(bones)
    out['parent'] = np.array([bones.index(sk['bones'][b]['parent']) if sk['bones'][b]['parent'] else -1 for b in bones], np.int16)
    jl, jo, jh, jt = [], [0], [], []
    joints = sk['joints']
    jn = list(joints)
    for n in jn:
        jl.extend(joints[n])
        jo.append(len(jl))
    out['joint_names'] = np.array(jn)
    out['joint_verts'] = np.array(jl, np.int32)
    out['joint_off'] = np.array(jo, np.int32)
    out['bone_head'] = np.array([jn.index(sk['bones'][b]['head']) for b in bones], np.int16)
    out['bone_tail'] = np.array([jn.index(sk['bones'][b]['tail']) for b in bones], np.int16)
    w = json.load(open(os.path.join(data, 'rigs', 'default_weights.mhw')))['weights']
    wb, wv, ww = [], [], []
    for b, lst in w.items():
        for vi, x in lst:
            wb.append(bones.index(b))
            wv.append(vi)
            ww.append(x)
    out['w_bone'] = np.array(wb, np.int16)
    out['w_vert'] = np.array(wv, np.int32)
    out['w_val'] = np.array(ww, np.float32)
    np.savez_compressed(OUT, **out)
    print('できた', OUT, '%.1f MB' % (os.path.getsize(OUT) / 1e6), '頂点', nv, '面', len(faces), '差分', len(names), '骨', len(bones))


if __name__ == '__main__':
    main()
