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

SKIN = [((0.11, 0.055, 0.032, 1), (0.17, 0.09, 0.055, 1)), ((0.075, 0.038, 0.022, 1), (0.12, 0.062, 0.038, 1)),
        ((0.15, 0.08, 0.048, 1), (0.22, 0.125, 0.075, 1))]
CLOTH = [((0.35, 0.28, 0.18, 1), (0.48, 0.40, 0.27, 1)), ((0.22, 0.14, 0.08, 1), (0.33, 0.22, 0.13, 1)),
         ((0.40, 0.36, 0.30, 1), (0.55, 0.50, 0.42, 1))]


def _mats(rng):
    k = rng.randrange(len(SKIN))
    c = rng.randrange(len(CLOTH))
    skin = M.simple('肌%d' % k, SKIN[k][0], SKIN[k][1], 0.6, 8.0, 0.05, sss=0.08)
    cloth = M.simple('樹皮の布%d' % c, CLOTH[c][0], CLOTH[c][1], 0.95, 30.0, 0.3, (1, 1, 4), kind='wave')
    hair = M.simple('髪', (0.010, 0.008, 0.007, 1), (0.024, 0.02, 0.016, 1), 0.8, 40.0, 0.4)
    return skin, cloth, hair


def figure(name, seed, pose='stand', height=1.65, coll=None, child=False, phase=0.0, cycle=0):
    """人。MakeHuman の体（assets/human.npz）があればそれで作る（kit/human.py）。なければ下の簡単な形"""
    from . import human
    if human.available():
        return human.figure(name, seed, pose=pose, coll=coll, child=child, phase=phase, cycle=cycle)
    return simple_figure(name, seed, 'carry' if pose == 'carrywalk' else pose, height, coll, child, phase)


def simple_figure(name, seed, pose='stand', height=1.65, coll=None, child=False, phase=0.0):
    """簡単な人の形（MakeHuman の素材がないときの代わり）。phase は歩く・こぐ動きの位相（0〜1）"""
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
    # 腰・くびれ・胸・肩・首（輪を多めにして、なめらかに）
    B.tube([hip + Vector((0, 0, -0.05 * s)), hip, hip + up * 0.15 * s, chest, hip + up * 0.47 * s, neck, neck + up * 0.03 * s],
           [0.13 * s, 0.15 * s, 0.128 * s, 0.158 * s, 0.15 * s, 0.062 * s, 0.056 * s], segs=16, mat=0)
    # 頭と髪（頭は球に近い形、髪は後ろ寄りにかぶせる）
    head = neck + up * 0.13 * s
    hb = neck + up * 0.02 * s
    B.tube([hb, hb + up * 0.05 * s, hb + up * 0.1 * s, hb + up * 0.16 * s, hb + up * 0.21 * s, hb + up * 0.245 * s],
           [0.052 * s, 0.072 * s, 0.092 * s, 0.098 * s, 0.08 * s, 0.03 * s], segs=16, mat=0)
    back = Vector((0, -0.008 * s, 0))
    B.tube([hb + back + up * 0.07 * s, hb + back + up * 0.12 * s, hb + back + up * 0.165 * s, hb + back + up * 0.215 * s, hb + back + up * 0.25 * s, hb + back + up * 0.268 * s],
           [0.093 * s, 0.103 * s, 0.106 * s, 0.088 * s, 0.05 * s, 0.01 * s], segs=16, mat=2)
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
        calf = knee.lerp(foot, 0.3)
        B.tube([hipj, hipj.lerp(knee, 0.5), knee, calf, foot], [0.082 * s, 0.07 * s, 0.05 * s, 0.054 * s, 0.037 * s], segs=10, mat=0)
        B.tube([foot - V(0, 0.04, 0.03), foot + V(0, 0.06, -0.035), foot + V(0, 0.14, -0.045)], [0.036 * s, 0.038 * s, 0.026 * s], segs=8, mat=0)
    # 腕
    sh_w = 0.175 * s
    for sgn in (-1, 1):
        sh = chest + up * 0.09 * s + Vector((sgn * sh_w, 0, 0))
        # 肩：胴の中から腕の付け根へ（腕が胴から離れて見えないように）
        B.tube([chest + up * 0.08 * s + Vector((sgn * 0.06 * s, 0, 0)), chest + up * 0.1 * s + Vector((sgn * 0.13 * s, 0, 0)), sh],
               [0.07 * s, 0.07 * s, 0.056 * s], segs=12, mat=0)
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
        B.tube([sh, sh.lerp(elbow, 0.5), elbow, elbow.lerp(hand, 0.85), hand], [0.052 * s, 0.045 * s, 0.037 * s, 0.03 * s, 0.022 * s], segs=10, mat=0)
    if pose == 'carry':
        bpy_basket = head + up * 0.25 * s
        B.tube([bpy_basket - V(0, 0, 0.08), bpy_basket + V(0, 0, 0.1)], [0.2 * s, 0.24 * s], segs=12, mat=1, cap=True)
    ob = B.finish(name, [skin, cloth, hair], coll)
    sub = ob.modifiers.new('なめらか', 'SUBSURF')
    sub.levels, sub.render_levels = 1, 1
    return ob


def paddle_tool(name, coll=None):
    m = M.simple('木材', (0.18, 0.12, 0.07, 1), (0.32, 0.23, 0.14, 1), 0.85, 4.0, 0.4, (1, 1, 6), kind='wave')
    B = Builder()
    B.tube([Vector((0, 0, 0)), Vector((0, 0, 1.3))], [0.02, 0.02], segs=5, mat=0)
    B.blade(Vector((0, 0, -0.45)), Vector((0, 0, 1)), 0.45, 0.16, segs=2, bend=0.0, mat=0, side=Vector((1, 0, 0)), taper=0.3)
    return B.finish(name, [m], coll)
