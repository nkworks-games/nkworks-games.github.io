"""地球の基礎キット：人（遠景・後ろ姿・手元用の、簡単な人の形）

顔の大写しには使わない。原点は足もと、y が前、身長は m。
pose：stand（立つ）、walk（歩く）、carry（頭に荷を載せて運ぶ）、bend（かがんで拾う）、
      paddle（舟をこぐ・座る）、sit（座る）、look（遠くを見る・片手を額に）
"""
import math

import bpy
from mathutils import Vector

from . import materials as M
from .util import link_object, stream
from .vegetation import Builder

SKIN = [((0.20, 0.11, 0.07, 1), (0.30, 0.17, 0.11, 1)), ((0.13, 0.07, 0.045, 1), (0.21, 0.12, 0.08, 1)),
        ((0.26, 0.15, 0.10, 1), (0.38, 0.23, 0.15, 1))]
CLOTH = [((0.35, 0.28, 0.18, 1), (0.48, 0.40, 0.27, 1)), ((0.22, 0.14, 0.08, 1), (0.33, 0.22, 0.13, 1)),
         ((0.40, 0.36, 0.30, 1), (0.55, 0.50, 0.42, 1))]


def _mats(rng):
    k = rng.randrange(len(SKIN))
    c = rng.randrange(len(CLOTH))
    skin = M.simple('肌%d' % k, SKIN[k][0], SKIN[k][1], 0.55, 8.0, 0.05, sss=0.25)
    cloth = M.simple('樹皮の布%d' % c, CLOTH[c][0], CLOTH[c][1], 0.95, 30.0, 0.3, (1, 1, 4), kind='wave')
    hair = M.simple('髪', (0.012, 0.01, 0.008, 1), (0.03, 0.025, 0.02, 1), 0.5, 40.0, 0.4)
    return skin, cloth, hair


def figure(name, seed, pose='stand', height=1.65, coll=None, child=False, phase=0.0):
    """簡単な人の形。phase は歩く・こぐ動きの位相（0〜1）"""
    rng = stream(seed, 'person', name)
    skin, cloth, hair = _mats(rng)
    h = height * (0.62 if child else 1.0)
    s = h / 1.65
    B = Builder()
    V = lambda x, y, z: Vector((x * s, y * s, z * s))
    hip = V(0, 0, 0.92)
    lean = 0.0
    if pose == 'bend':
        lean = 0.9
    elif pose == 'carry':
        lean = 0.05
    elif pose in ('paddle', 'sit'):
        hip = V(0, 0, 0.42)
        lean = 0.25 if pose == 'paddle' else 0.1
    # 胴（腰から首）
    up = Vector((0, math.sin(lean), math.cos(lean)))
    neck = hip + up * 0.55 * s
    chest = hip + up * 0.38 * s
    B.tube([hip + Vector((0, 0, -0.04 * s)), hip + up * 0.12 * s, chest, neck], [0.15 * s, 0.14 * s, 0.17 * s, 0.07 * s], segs=10, mat=0)
    # 頭と髪
    head = neck + up * 0.13 * s
    B.tube([neck, neck + up * 0.05 * s, head + up * 0.06 * s, head + up * 0.12 * s], [0.05 * s, 0.09 * s, 0.1 * s, 0.02 * s], segs=10, mat=0)
    B.tube([head - Vector((0, 0.03 * s, 0)) + up * 0.02 * s, head - Vector((0, 0.035 * s, 0)) + up * 0.1 * s, head + up * 0.135 * s],
           [0.105 * s, 0.1 * s, 0.03 * s], segs=10, mat=2)
    # 腰布
    B.tube([hip + Vector((0, 0, 0.08 * s)), hip + Vector((0, 0, -0.12 * s)), hip + Vector((0, 0, -0.38 * s))],
           [0.165 * s, 0.18 * s, 0.17 * s], segs=12, mat=1)
    # 脚
    ph = 2 * math.pi * phase
    for sgn in (-1, 1):
        hipj = hip + Vector((sgn * 0.09 * s, 0, -0.05 * s))
        if pose in ('paddle', 'sit'):
            knee = hipj + V(sgn * 0.05, 0.42, 0.02)
            foot = knee + V(0, 0.08, -0.38)
        else:
            sw = 0.35 * math.sin(ph + (0 if sgn > 0 else math.pi)) if pose == 'walk' else 0.0
            bend_k = 0.25 if pose == 'bend' else 0.0
            knee = hipj + Vector((0, math.sin(sw) * 0.45 * s + bend_k * 0.1 * s, -math.cos(sw) * 0.45 * s))
            foot = knee + Vector((0, math.sin(sw - 0.2 - bend_k) * 0.44 * s, -0.44 * s))
            foot.z = max(foot.z, 0.06 * s)
        B.tube([hipj, knee, foot], [0.075 * s, 0.05 * s, 0.04 * s], segs=7, mat=0)
        B.tube([foot - V(0, 0.04, 0.03), foot + V(0, 0.14, -0.04)], [0.035 * s, 0.03 * s], segs=6, mat=0)
    # 腕
    sh_w = 0.19 * s
    for sgn in (-1, 1):
        sh = chest + up * 0.1 * s + Vector((sgn * sh_w, 0, 0))
        if pose == 'carry' and sgn > 0:
            elbow = sh + V(sgn * 0.12, 0.0, 0.22)
            hand = head + up * 0.16 * s + V(sgn * 0.08, 0, 0)
        elif pose == 'look' and sgn > 0:
            elbow = sh + V(sgn * 0.12, 0.2, 0.05)
            hand = head + V(0.02, 0.12, 0.05)
        elif pose == 'bend':
            elbow = sh + Vector((0, 0.2 * s, -0.22 * s))
            hand = elbow + Vector((0, 0.1 * s, -0.25 * s))
        elif pose == 'paddle':
            a = math.sin(ph)
            elbow = sh + V(sgn * 0.08, 0.25 + 0.05 * a, -0.05)
            hand = elbow + V(-sgn * 0.08, 0.2 + 0.1 * a, 0.05 * sgn)
        else:
            sw = -0.3 * math.sin(ph + (math.pi if sgn > 0 else 0)) if pose == 'walk' else 0.05
            elbow = sh + Vector((sgn * 0.03 * s, math.sin(sw) * 0.28 * s, -0.28 * s))
            hand = elbow + Vector((0, math.sin(sw + 0.15) * 0.26 * s, -0.25 * s))
        B.tube([sh, elbow, hand], [0.05 * s, 0.04 * s, 0.03 * s], segs=7, mat=0)
    if pose == 'carry':
        bpy_basket = head + up * 0.25 * s
        B.tube([bpy_basket - V(0, 0, 0.08), bpy_basket + V(0, 0, 0.1)], [0.2 * s, 0.24 * s], segs=12, mat=1, cap=True)
    return B.finish(name, [skin, cloth, hair], coll)


def paddle_tool(name, coll=None):
    m = M.simple('木材', (0.18, 0.12, 0.07, 1), (0.32, 0.23, 0.14, 1), 0.85, 4.0, 0.4, (1, 1, 6), kind='wave')
    B = Builder()
    B.tube([Vector((0, 0, 0)), Vector((0, 0, 1.3))], [0.02, 0.02], segs=5, mat=0)
    B.blade(Vector((0, 0, -0.45)), Vector((0, 0, 1)), 0.45, 0.16, segs=2, bend=0.0, mat=0, side=Vector((1, 0, 0)), taper=0.3)
    return B.finish(name, [m], coll)
