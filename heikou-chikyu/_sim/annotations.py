"""並行地球 第1回：3DCG の場面に重ねる解説（矢印・名前・数字・輪の図）

make_roughcut.py が、カットごとに1コマずつ透明な画像を作って 3D の映像に重ねる。
  NOTES[カット番号]  ：重ねる物の一覧
  SPLITS[カット番号] ：左右に2つの 3D を並べるカット（左右それぞれの名前と数字）

矢印・名前が指す点（anchor）は、Blender が書き出した anchors_cutNNN.json（コマごとの画面の位置）から読む。
  → カメラが動いても、矢印は島や人についていく
時刻 t は秒か、ナレーションの言葉（その言葉を読むころに出る）。数字は計算の記録から読む。

物の種類
  label   ：点に印をつけ、線を引いて名前（＋小さい説明）
  route   ：2つの点を点線でつなぎ、真ん中に距離など（終わりに矢じり）
  panel   ：画面の決まった場所に、見出しと「名前　数字」の行（行ごとに出る。数字が動くもの・小さい折れ線も）
  daybar  ：1年（250日）の帯を、働く日と余暇に分けて塗る
  steps   ：年と技術の名前を、順に並べる
  cycle   ：輪の図（余裕→技術→舟→新しい島と食べ物→余裕）
"""
import gzip
import math
import os
import pickle
import json

import numpy as np
from PIL import Image, ImageDraw

from motion import BG, ENTITY, ENTITY_JA, H, MUTED, TEXT, TEXT2, W, ease, font

HERE = os.path.dirname(os.path.abspath(__file__))
S = 2                       # 2倍で描いて縮める（線をなめらかに）
CPS = 4.6                   # ナレーションの速さ（1秒に読む字数の目安）
A_, R_ = 'A1-2', 'R1-4'
GREEN, ORANGE = ENTITY[A_], ENTITY[R_]
WHITE = (250, 249, 246)
SHADOW = (8, 12, 18)


# ---------------------------------------------------------------- 計算の記録

_REC = {}


def rec(ent, arm='main'):
    key = (ent, arm)
    if key not in _REC:
        tid, k = ent.split('-')
        with gzip.open(os.path.join(HERE, 'out', arm, '%s-%s.pkl.gz' % (tid, k))) as f:
            _REC[key] = pickle.load(f)
    return _REC[key]


def series(ent, key, arm='main'):
    return np.asarray(rec(ent, arm)['series'][key], float)


def mean(ent, key, y0, y1, arm='main'):
    return float(np.mean(series(ent, key, arm)[y0:y1]))


def techs_until(ent, year):
    """その年までに生まれた技術（年, 名前）"""
    out = []
    for e in rec(ent)['events']:
        if e['kind'] == 'tech' and e['year'] <= year:
            out.append((e['year'], e['text'].split('を作り出した')[0]))
    return out


def lost_voyages(ent):
    s = rec(ent)['series']
    return int(sum(s['lost_voyages'])), int(sum(s['voyages']))


def e0(ent):
    import metrics
    r = rec(ent)
    return metrics.life_expectancy(r['deaths_age'], r['pop_age'], 2500, 3000)


def n(v):
    return format(int(round(v)), ',')


# ---------------------------------------------------------------- 解説の中身（カットごと）

def notes():
    lA, lR = (round(mean(A_, 'leisure', 0, 100)), round(mean(R_, 'leisure', 0, 100)))
    l3A, l3R = (round(mean(A_, 'leisure', 0, 300)), round(mean(R_, 'leisure', 0, 300)))
    lostA, voyA = lost_voyages(A_)
    lostR, voyR = lost_voyages(R_)
    popR = series(R_, 'pop')
    popT = series(R_, 'pop', 'verify-tide')
    lastA = lambda k: mean(A_, k, 2900, 3000)
    lastR = lambda k: mean(R_, k, 2900, 3000)
    N = {
        '013': [
            dict(type='label', at='people', text='200人 × 5集団', sub='あわせて1,000人', t='二百人', dx=-150, dy=-300),
            dict(type='label', at='fire', text='火', t='火', dx=-260, dy=-200),
            dict(type='label', at='wood', text='石の道具・薪', t='石の道具', dx=90, dy=-250),
            dict(type='label', at='raft', text='いかだ', sub='海を30kmまで渡れる', t='いかだ', dx=40, dy=-190),
        ],
        '221': [
            dict(type='label', at='start', text='火山島 12,121km²', sub='4つの集団（800人）', t='四つ', dx=330, dy=160, color=GREEN),
            dict(type='route', a='start', b='near', text='26km', t='二十六キロ', trim=(0.45, 0.22), color=GREEN, ldx=-10, ldy=75),
            dict(type='label', at='near', text='低いサンゴの島', sub='1つの集団（200人）', t='一つは', dx=40, dy=-210, color=GREEN),
            dict(type='route', a='start', b='first', text='50km', t='五十キロ', trim=(0.42, 0.25), color=GREEN, ldx=80, ldy=55),
            dict(type='label', at='first', text='まだ誰もいない島', t='五十キロ', dx=130, dy=-150, color=GREEN),
        ],
        '022': [
            dict(type='daybar', title='大人1人の1年（250日）', sub='群島の歴史・最初の100年の平均',
                 parts=[('食べ物・水・住まい', 250 - lA, MUTED), ('余暇 %d日' % lA, lA, GREEN)], t='働く日', pos=(1150, 190)),
        ],
        '070': [
            dict(type='label', at='start', text='始まりの島 771km²', sub='1,000人', t='七百七十一', dx=360, dy=-30, color=ORANGE),
            dict(type='label', at='ring', text='いかだで渡れる海', sub='海岸から30km', t='三十キロ', dx=-300, dy=-90, color=ORANGE),
            dict(type='route', a='start', b='near', text='104km', sub='いちばん近い島まで', t='百四キロ', trim=(0.30, 0.10), color=ORANGE),
        ],
        '212': [
            dict(type='panel', pos=(710, 40), w=580, title='小さな火山島の歴史（始まりの50年）', color=ORANGE, rows=[
                dict(t='五百五十人', label='島の恵みで暮らせる人数', value='約550人'),
                dict(t='千人', label='はじめに置いた人数', value='1,000人'),
                dict(t='最初の五十年', label='50年後の人口', count=(popR[0], popR[50]), fmt=lambda v: '%s人' % n(v), dur=3.0),
            ]),
        ],
        '031': [
            dict(type='daybar', title='大人1人の1年（250日）', sub='小さな火山島の歴史・最初の100年の平均',
                 parts=[('食べ物・水・住まい', 250 - lR, MUTED), ('余暇 %d日' % lR, lR, ORANGE)], t='食べ物', pos=(1150, 190)),
        ],
        '035': [
            dict(type='steps', pos=(1330, 170), title='群島の歴史で生まれた技術', color=GREEN,
                 items=[(y, s, ('百九十九年' if y == 199 else '網とわな' if y == 201 else None)) for y, s in techs_until(A_, 300)],
                 t0=1.0, gap=1.6),
        ],
        '049': [
            dict(type='label', at='island', text='50km先の島', sub='まだ誰も住んでいない', t='五十キロ', dx=300, dy=-170, color=GREEN),
            dict(type='label', at='boat', text='浮き木つきの舟', sub='284年に生まれた舟', t='舟は', dx=-380, dy=60, color=GREEN),
        ],
        '051': [
            dict(type='panel', pos=(1290, 150), w=580, title='314年', color=GREEN, rows=[
                dict(t='百六十六人', label='海を渡った人', value='166人'),
                dict(t='まだ誰も', label='行き先', value='まだ誰もいない島（50km先）'),
            ]),
        ],
        '052': [
            dict(type='panel', pos=(1290, 150), w=580, title='群島の歴史・3,000年の探検', color=GREEN, rows=[
                dict(t='すべての舟', label='探検に出た舟', value='%s回' % n(voyA)),
                dict(t='百二十回', label='戻らなかった舟', value='%d回' % lostA),
            ]),
        ],
        '075': [
            dict(type='panel', pos=(710, 40), w=580, title='小さな火山島の歴史・いかだの探検（3,000年）', color=ORANGE, rows=[
                dict(t='七十二回', label='探検に出たいかだ', value='%d回' % voyR),
                dict(t='三十キロの先', label='見つかった島', value='0'),
                dict(t='六回は', label='戻らなかったいかだ', value='%d回' % lostR),
            ]),
        ],
        '076': [
            dict(type='label', at='island', text='104km先の島', sub='島は水平線の下', t='百四キロ', dx=-360, dy=-150, color=ORANGE),
            dict(type='label', at='cloud', text='島の上にかかる雲', sub='これで島のありかが分かる', t='雲で', dx=300, dy=-200, color=ORANGE),
            dict(type='label', at='raft', text='いかだ', sub='30kmまでしか渡れない', t='渡る舟', dx=-200, dy=-170, color=ORANGE),
        ],
        '213': [
            dict(type='panel', pos=(1290, 150), w=580, title='小さな火山島の歴史・人口（3,000年）', color=ORANGE, rows=[
                dict(t='三百五十人', label='200年目からの人口', value='%s〜%s人' % (n(popR[200:].min()), n(popR[200:].max()))),
                dict(t='行ったり来たり', label='', spark=popR, ylim=(0, 1100), mark=(1000, 'はじめ 1,000人')),
            ]),
        ],
        '063': [
            dict(type='cycle', center=(1250, 450), r=230, color=GREEN,
                 items=[('暮らしの余裕', '余裕が'), ('新しい技術', '技術を'), ('海を越える舟', '舟が'), ('新しい島と食べ物', '新しい島'), ('さらに余裕', 'さらに')]),
        ],
        '097': [
            dict(type='panel', pos=(1290, 150), w=580, title='小さな火山島の人口（3,000年後）', color=ORANGE, rows=[
                dict(t='四百三十六人', label='潮麦なし', value='%s人' % n(popR[-1])),
                dict(t='二千五百七十三人', label='潮麦あり（架空）', count=(popR[-1], popT[-1]), fmt=lambda v: '%s人' % n(v), dur=2.5),
            ]),
        ],
        '211': [
            dict(type='panel', pos=(1290, 150), w=580, title='潮麦あり（架空）：3,000年後', color=ORANGE, rows=[
                dict(t='住む島', label='住む島', value='%d のまま' % series(R_, 'islands', 'verify-tide')[-1]),
                dict(t='余暇は', label='余暇（大人1人・1年）', value='%d日' % round(mean(R_, 'leisure', 2900, 3000, 'verify-tide'))),
                dict(t='増えた食べ物', label='人口', value='%s人' % n(popT[-1])),
            ]),
        ],
    }
    SP = {
        '203': dict(shots=('221', '070'), crop=(0.3, 0.5), sides=[
            dict(ent=A_, t='群島', rows=[dict(t='いちばん大きく', label='', value='いちばん大きく変わった')]),
            dict(ent=R_, t='小さな火山島', rows=[dict(t='いちばん変わらなかった', label='', value='いちばん変わらなかった')]),
        ]),
        '043': dict(shots=('033', '212'), crop=(0.5, 0.5), sides=[
            dict(ent=A_, t='群島は', rows=[dict(t='群島は', label='余暇（最初の300年の平均）', value='1年に%d日' % l3A)]),
            dict(ent=R_, t='小さな火山島は', rows=[dict(t='小さな火山島は', label='余暇（最初の300年の平均）', value='1年に%d日' % l3R)]),
        ]),
        '204': dict(shots=('063', '003'), crop=(0.5, 0.5), sides=[
            dict(ent=A_, t=0.2, rows=[
                dict(t='余暇は', label='余暇（大人1人・1年）', value='%d日' % round(lastA('leisure'))),
                dict(t='暮らしに困る人', label='暮らしに困る人', value='%d％' % round(100 * lastA('poor'))),
                dict(t='平均寿命', label='平均寿命', value='%d歳' % round(e0(A_)))]),
            dict(ent=R_, t=0.2, rows=[
                dict(t='余暇は', label='余暇（大人1人・1年）', value='%d日' % round(lastR('leisure'))),
                dict(t='暮らしに困る人', label='暮らしに困る人', value='%d％' % round(100 * lastR('poor'))),
                dict(t='平均寿命', label='平均寿命', value='%d歳' % round(e0(R_)))]),
        ], note='3,000年後（余暇・困る人は最後の100年の平均）'),
        '205a': dict(shots=('221', '070'), crop=(0.2, 0.5), header='分かれ目 1　舟で渡れる距離に、島があったか', sides=[
            dict(ent=A_, t='一つ目', rows=[dict(t='一つ目', label='いちばん近い島', value='26km')],
                 notes=[dict(type='route', a='start', b='near', text='26km', t='一つ目', trim=(0.45, 0.22), color=GREEN, ldx=-10, ldy=75)]),
            dict(ent=R_, t='一つ目', rows=[dict(t='一つ目', label='いちばん近い島', value='104km')],
                 notes=[dict(type='route', a='start', b='near', text='104km', t='一つ目', trim=(0.30, 0.10), color=ORANGE)]),
        ], note='いかだで渡れるのは30km（この計算の値）'),
        '205b': dict(shots=('057', '212'), crop=(0.5, 0.5), header='分かれ目 2　育てられる植物があったか', sides=[
            dict(ent=A_, t='二つ目', rows=[dict(t='育てられる', label='育てられる植物', value='芋・果樹（4年目に見つける）')]),
            dict(ent=R_, t='二つ目', rows=[dict(t='育てられる', label='育てられる植物', value='なし')]),
        ]),
        '205c': dict(shots=('047', '213'), crop=(0.5, 0.5), header='舟にする大木', sides=[
            dict(ent=A_, t='群島には', rows=[dict(t='群島には', label='舟にする大木', value='たくさん')]),
            dict(ent=R_, t='小さな火山島には', rows=[dict(t='百分の一', label='舟にする大木', value='群島の100分の1以下')]),
        ]),
        '205d': dict(shots=('022', '212'), crop=(0.5, 0.5), header='分かれ目 3　暮らしに余裕があったか', sides=[
            dict(ent=A_, t='三つ目', rows=[dict(t='余裕', label='余暇（最初の300年の平均）', value='1年に%d日' % l3A)]),
            dict(ent=R_, t='三つ目', rows=[dict(t='余裕', label='余暇（最初の300年の平均）', value='1年に%d日' % l3R)]),
        ]),
    }
    return N, SP


_CACHE = None


def tables():
    global _CACHE
    if _CACHE is None:
        _CACHE = notes()
    return _CACHE


def has_notes(no):
    N, SP = tables()
    return no in N or no in SP


def split_of(no):
    return tables()[1].get(no)


def needs_anchor(no):
    N, SP = tables()
    if no in N:
        return any(e['type'] in ('label', 'route') for e in N[no])
    if no in SP:
        return any(e['type'] in ('label', 'route') for sd in SP[no]['sides'] for e in sd.get('notes', []))
    return False


# ---------------------------------------------------------------- 時刻

def when(t, narration):
    """秒、またはナレーションの言葉（その言葉を読むころ）"""
    if t is None:
        return 0.3
    if isinstance(t, (int, float)):
        return float(t)
    i = narration.find(t)
    if i < 0:
        print('注意：ナレーションに「%s」がない' % t)
        return 0.5
    return max(0.2, 0.3 + i / CPS - 0.15)


def prog(t, t0, dur):
    return ease((t - t0) / dur) if dur > 0 else float(t >= t0)


# ---------------------------------------------------------------- 描く道具（1倍の座標で渡す）

class Canvas:
    def __init__(self):
        self.img = Image.new('RGBA', (W * S, H * S), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    def rgba(self, c, a):
        return tuple(int(v) for v in c[:3]) + (int(255 * max(0.0, min(1.0, a))),)

    def line(self, pts, color, width, a=1.0):
        if len(pts) >= 2:
            self.d.line([(x * S, y * S) for x, y in pts], fill=self.rgba(color, a), width=int(width * S), joint='curve')

    def shadowed_line(self, pts, width=3, a=1.0, color=WHITE):
        self.line(pts, SHADOW, width + 3, 0.55 * a)
        self.line(pts, color, width, a)

    def circle(self, xy, r, fill=None, outline=None, ow=2, a=1.0):
        x, y = xy[0] * S, xy[1] * S
        R = r * S
        self.d.ellipse([x - R, y - R, x + R, y + R], fill=self.rgba(fill, a) if fill else None,
                       outline=self.rgba(outline, a) if outline else None, width=int(ow * S))

    def box(self, b, a=1.0, alpha=0.78, radius=10, accent=None):
        x0, y0, x1, y1 = [v * S for v in b]
        self.d.rounded_rectangle([x0, y0, x1, y1], radius=radius * S, fill=self.rgba(BG, alpha * a))
        if accent:
            self.d.rounded_rectangle([x0, y0, x0 + 7 * S, y1], radius=3 * S, fill=self.rgba(accent, a))

    def text(self, xy, s, size, color=TEXT, a=1.0, bold=False, anchor='la'):
        self.d.text((xy[0] * S, xy[1] * S), s, font=font(size * S, bold), fill=self.rgba(color, a), anchor=anchor)

    def tlen(self, s, size, bold=False):
        return self.d.textlength(s, font=font(size * S, bold)) / S

    def polygon(self, pts, color, a=1.0):
        self.d.polygon([(x * S, y * S) for x, y in pts], fill=self.rgba(color, a))

    def result(self):
        return self.img.reduce(S)


def arrowhead(cv, tip, frm, color=WHITE, a=1.0, size=18):
    dx, dy = tip[0] - frm[0], tip[1] - frm[1]
    L = math.hypot(dx, dy) or 1
    ux, uy = dx / L, dy / L
    px, py = -uy, ux
    pts = [tip, (tip[0] - ux * size + px * size * 0.55, tip[1] - uy * size + py * size * 0.55),
           (tip[0] - ux * size - px * size * 0.55, tip[1] - uy * size - py * size * 0.55)]
    cv.polygon([(x + 1.5, y + 1.5) for x, y in pts], SHADOW, 0.5 * a)
    cv.polygon(pts, color, a)


def label_box(cv, cx, cy, text, sub, color, a, slide=0.0):
    """名前の箱（中心 cx, cy）。返り値は箱の四隅"""
    tw = cv.tlen(text, 34, True)
    sw = cv.tlen(sub, 24) if sub else 0
    w = max(tw, sw) + 48
    h = 62 if not sub else 98
    x0, y0 = cx - w / 2, cy - h / 2 + slide
    cv.box((x0, y0, x0 + w, y0 + h), a, accent=color)
    cv.text((x0 + 26, y0 + 31 if not sub else y0 + 30), text, 34, TEXT, a, True, 'lm')
    if sub:
        cv.text((x0 + 26, y0 + 72), sub, 24, TEXT2, a, False, 'lm')
    return (x0, y0, x0 + w, y0 + h)


def edge_point(b, p):
    """箱 b の、点 p に向かう辺の上の点"""
    x0, y0, x1, y1 = b
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = p[0] - cx, p[1] - cy
    if dx == 0 and dy == 0:
        return cx, cy
    sx = (x1 - x0) / 2 / abs(dx) if dx else 1e9
    sy = (y1 - y0) / 2 / abs(dy) if dy else 1e9
    s = min(sx, sy)
    return cx + dx * s, cy + dy * s


# ---------------------------------------------------------------- 物ごとの描き方

def clamp_point(p, box):
    """画面（や左右の半分）の外の点は、ふちに寄せる。返り値（点, 外か）"""
    x0, y0, x1, y1 = box
    m = 50
    q = (min(max(p[0], x0 + m), x1 - m), min(max(p[1], y0 + m), y1 - m))
    return q, (q != tuple(p))


def draw_label(cv, e, t, P, view):
    t0 = e['_t']
    if t < t0 or e['at'] not in P:
        return
    p, out = clamp_point(P[e['at']], view)
    c = e.get('color', WHITE)
    pm = prog(t, t0, 0.35)
    pl = prog(t, t0 + 0.12, 0.4)
    pb = prog(t, t0 + 0.3, 0.4)
    # 印：白い輪＋色の点（出るときに輪が広がる）
    if not out:
        if pm < 1:
            cv.circle(p, 11 + 26 * pm, outline=WHITE, ow=2, a=(1 - pm) * 0.8)
        cv.circle(p, 12, outline=SHADOW, ow=5, a=0.45 * pm)
        cv.circle(p, 11, outline=WHITE, ow=2.5, a=pm)
        cv.circle(p, 5, fill=c, a=pm)
    cx = min(max(p[0] + e.get('dx', 0), view[0] + 170), view[2] - 170)
    cy = min(max(p[1] + e.get('dy', -160), view[1] + 70), view[3] - 70)
    # 箱の位置を先に測る（線を箱のふちまで引く）
    w = max(cv.tlen(e['text'], 34, True), cv.tlen(e.get('sub', ''), 24) if e.get('sub') else 0) + 48
    h = 62 if not e.get('sub') else 98
    b = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    q = edge_point(b, p)
    start = p
    if not out:
        L = math.hypot(q[0] - p[0], q[1] - p[1]) or 1
        start = (p[0] + (q[0] - p[0]) * 13 / L, p[1] + (q[1] - p[1]) * 13 / L)
    end = (start[0] + (q[0] - start[0]) * pl, start[1] + (q[1] - start[1]) * pl)
    cv.shadowed_line([start, end], 3, min(1.0, pl * 3))
    if out:
        arrowhead(cv, p, q, WHITE, pm)
    if pb > 0:
        label_box(cv, cx, cy, e['text'], e.get('sub'), c, pb, slide=(1 - pb) * 10)


def bezier(a, b, bend, k=60):
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    dx, dy = b[0] - a[0], b[1] - a[1]
    c = (mx - dy * bend, my + dx * bend)
    pts = []
    for i in range(k + 1):
        u = i / k
        pts.append(((1 - u) ** 2 * a[0] + 2 * (1 - u) * u * c[0] + u * u * b[0], (1 - u) ** 2 * a[1] + 2 * (1 - u) * u * c[1] + u * u * b[1]))
    return pts


def draw_route(cv, e, t, P, view):
    t0 = e['_t']
    if t < t0 or e['a'] not in P or e['b'] not in P:
        return
    a, _ = clamp_point(P[e['a']], view)
    b, out = clamp_point(P[e['b']], view)
    ta, tb = e.get('trim', (0.2, 0.2))
    a2 = (a[0] + (b[0] - a[0]) * ta, a[1] + (b[1] - a[1]) * ta)
    b2 = (b[0] + (a[0] - b[0]) * tb, b[1] + (a[1] - b[1]) * tb) if not out else b
    pts = bezier(a2, b2, e.get('bend', 0.12))
    pd = prog(t, t0, 1.0)
    upto = max(2, int(len(pts) * pd))
    # 点線
    seg = []
    acc = 0.0
    for i in range(1, upto):
        x0, y0 = pts[i - 1]
        x1, y1 = pts[i]
        acc += math.hypot(x1 - x0, y1 - y0)
        if int(acc / 16) % 2 == 0:
            seg.append(((x0, y0), (x1, y1)))
    for s0, s1 in seg:
        cv.line([s0, s1], SHADOW, 7, 0.5)
    for s0, s1 in seg:
        cv.line([s0, s1], WHITE, 4, 1.0)
    if pd >= 1:
        arrowhead(cv, pts[-1], pts[-4], WHITE, 1.0, 22)
    pt = prog(t, t0 + 0.6, 0.4)
    if pt > 0:
        m = pts[len(pts) // 2]
        c = e.get('color', WHITE)
        tw = cv.tlen(e['text'], 40, True)
        sw = cv.tlen(e.get('sub', ''), 22) if e.get('sub') else 0
        w = max(tw, sw) + 40
        h = 64 if not e.get('sub') else 96
        cx, cy = m[0] + e.get('ldx', 0), m[1] + e.get('ldy', 0)
        x0, y0 = cx - w / 2, cy - h / 2
        cv.box((x0, y0, x0 + w, y0 + h), pt, accent=c)
        if e.get('sub'):
            cv.text((cx + 4, y0 + 26), e['sub'], 22, TEXT2, pt, False, 'mm')
            cv.text((cx + 4, y0 + 64), e['text'], 40, TEXT, pt, True, 'mm')
        else:
            cv.text((cx + 4, cy), e['text'], 40, TEXT, pt, True, 'mm')


def sparkline(cv, box, ys, ylim, a, color, mark=None):
    x0, y0, x1, y1 = box
    ys = np.asarray(ys, float)
    k = 20
    ys = np.convolve(np.pad(ys, (k, k), mode='edge'), np.ones(2 * k + 1) / (2 * k + 1), 'valid')
    xs = np.linspace(x0, x1, len(ys))
    Y = lambda v: y1 - (v - ylim[0]) / (ylim[1] - ylim[0]) * (y1 - y0)
    cv.line([(x0, y1), (x1, y1)], MUTED, 1.5, 0.6 * a)
    if mark:
        cv.line([(x0, Y(mark[0])), (x1, Y(mark[0]))], MUTED, 1.5, 0.5 * a)
        cv.text((x1, Y(mark[0]) - 6), mark[1], 20, MUTED, a, False, 'rb')
    step = max(1, len(ys) // 300)
    cv.line([(xs[i], Y(ys[i])) for i in range(0, len(ys), step)], color, 3, a)
    cv.text((x0, y1 + 8), '0年', 18, MUTED, a, False, 'lt')
    cv.text((x1, y1 + 8), '3,000年', 18, MUTED, a, False, 'rt')


def draw_panel(cv, e, t, narr, pos=None, w=None):
    x0, y0 = pos or e['pos']
    w = w or e.get('w', 560)
    rows = e['rows']
    times = [when(r.get('t'), narr) for r in rows]
    tp = min(times) - 0.2 if 'title_t' not in e else when(e['title_t'], narr)
    pa = prog(t, tp, 0.4)
    if pa <= 0:
        return
    hgt = 62 + sum(130 if r.get('spark') is not None else (94 if r.get('label') else 62) for r in rows) + 12
    cv.box((x0, y0, x0 + w, y0 + hgt), pa, accent=e.get('color'))
    cv.text((x0 + 28, y0 + 34), e['title'], 24, TEXT2, pa, False, 'lm')
    y = y0 + 62
    for r, tr in zip(rows, times):
        a = prog(t, tr, 0.45)
        if r.get('spark') is not None:
            if a > 0:
                sparkline(cv, (x0 + 30, y + 14, x0 + w - 30, y + 100), r['spark'], r['ylim'], a, e.get('color', WHITE), r.get('mark'))
            y += 130
            continue
        if a > 0:
            if r.get('label'):
                cv.text((x0 + 28, y + 18), r['label'], 24, TEXT2, a, False, 'lm')
            if 'count' in r:
                v0, v1 = r['count']
                v = v0 + (v1 - v0) * prog(t, tr, r.get('dur', 2.5))
                val = r['fmt'](v)
            else:
                val = r['value']
            cv.text((x0 + 28, y + (58 if r.get('label') else 30) + (1 - a) * 8), val, 42, TEXT, a, True, 'lm')
        y += 94 if r.get('label') else 62


def draw_daybar(cv, e, t, narr):
    x0, y0 = e['pos']
    w = e.get('w', 700)
    t0 = e['_t']
    pa = prog(t, t0, 0.4)
    if pa <= 0:
        return
    cv.box((x0, y0, x0 + w, y0 + 196), pa)
    cv.text((x0 + 28, y0 + 34), e['title'], 30, TEXT, pa, True, 'lm')
    cv.text((x0 + 28, y0 + 70), e['sub'], 22, TEXT2, pa, False, 'lm')
    bx0, bx1, by0, by1 = x0 + 28, x0 + w - 28, y0 + 96, y0 + 132
    total = sum(p[1] for p in e['parts'])
    cv.d.rounded_rectangle([bx0 * S, by0 * S, bx1 * S, by1 * S], radius=6 * S, fill=cv.rgba((40, 50, 62), pa))
    x = bx0
    tt = t0 + 0.4
    for i, (name, v, c) in enumerate(e['parts']):
        seg = (bx1 - bx0) * v / total
        p = prog(t, tt, 1.0)
        if p > 0 and seg * p > 1:
            cv.d.rounded_rectangle([x * S, by0 * S, (x + seg * p) * S, by1 * S], radius=6 * S, fill=cv.rgba(c, pa))
        if p > 0.6:
            al = (p - 0.6) / 0.4
            last = i == len(e['parts']) - 1
            if last:
                cv.text((bx1, by1 + 30), name, 30 if last else 22, TEXT, al, True, 'rm')
            else:
                cv.text((x, by1 + 30), name, 22, TEXT2, al, False, 'lm')
        x += seg
        tt += 1.0


def step_times(e, narr):
    """年表の行が出る時刻：言葉があればそのころ、なければ前の行から gap 秒あと"""
    tt = e.get('t0', 0.5) + 0.3
    times = []
    for y, s, word in e['items']:
        tt = when(word, narr) if word else tt + e.get('gap', 1.5)
        times.append(tt)
    return sorted(times)


def draw_steps(cv, e, t, narr):
    x0, y0 = e['pos']
    items = e['items']
    w = e.get('w', 520)
    pa = prog(t, e.get('t0', 0.5), 0.4)
    if pa <= 0:
        return
    hgt = 70 + 58 * len(items) + 10
    cv.box((x0, y0, x0 + w, y0 + hgt), pa, accent=e.get('color'))
    cv.text((x0 + 28, y0 + 36), e['title'], 26, TEXT2, pa, False, 'lm')
    times = step_times(e, narr)
    for i, ((yr, s, _), ti) in enumerate(zip(items, times)):
        a = prog(t, ti, 0.4)
        if a <= 0:
            continue
        yy = y0 + 70 + 58 * i + 26 + (1 - a) * 8
        cv.circle((x0 + 38, yy), 6, fill=e.get('color', WHITE), a=a)
        cv.text((x0 + 60, yy), '%d年' % yr, 28, TEXT2, a, False, 'lm')
        cv.text((x0 + 180, yy), s, 32, TEXT, a, True, 'lm')


def draw_cycle(cv, e, t, narr):
    cx, cy = e['center']
    R = e['r']
    items = e['items']
    k = len(items) - 1 if items[-1][0].startswith('さらに') else len(items)
    times = [when(w, narr) for _, w in items]
    pa = prog(t, times[0] - 0.4, 0.5)
    if pa <= 0:
        return
    RX, RY = R * 1.42, R
    cv.d.ellipse([(cx - RX - 190) * S, (cy - RY - 95) * S, (cx + RX + 190) * S, (cy + RY + 95) * S], fill=cv.rgba(BG, 0.62 * pa))
    ang = [-math.pi / 2 + 2 * math.pi * i / k for i in range(k)]
    pos = [(cx + RX * math.cos(a), cy + RY * math.sin(a)) for a in ang]
    col = e.get('color', WHITE)
    # 矢印（次の物が出るときに引く）
    for i in range(k):
        j = (i + 1) % k
        tj = times[j] if j else times[-1] if len(items) > k else times[0] + 99
        p = prog(t, tj - 0.3, 0.6)
        if p <= 0:
            continue
        a0 = ang[i] + 0.36
        a1 = ang[i] + (2 * math.pi / k) - 0.36
        steps = 24
        upto = max(2, int(steps * p))
        pts = [(cx + RX * math.cos(a0 + (a1 - a0) * u / steps), cy + RY * math.sin(a0 + (a1 - a0) * u / steps)) for u in range(upto + 1)]
        cv.line(pts, col, 6, 1.0)
        if p >= 1:
            arrowhead(cv, pts[-1], pts[-3], col, 1.0, 24)
    for i in range(k):
        a = prog(t, times[i] - 0.15, 0.4)
        if a <= 0:
            continue
        s = items[i][0]
        tw = cv.tlen(s, 32, True) + 40
        x, y = pos[i]
        cv.box((x - tw / 2, y - 32, x + tw / 2, y + 32), a, alpha=0.9, radius=30)
        cv.d.rounded_rectangle([(x - tw / 2) * S, (y - 32) * S, (x + tw / 2) * S, (y + 32) * S], radius=30 * S, outline=cv.rgba(col, a), width=3 * S)
        cv.text((x, y), s, 32, TEXT, a, True, 'mm')
    if len(items) > k:
        a = prog(t, times[-1], 0.5)
        if a > 0:
            cv.text((cx, cy), items[-1][0], 40, TEXT, a, True, 'mm')
            cv.text((cx, cy + 46), 'くり返す', 24, TEXT2, a, False, 'mm')


def draw_side(cv, sd, side, t, narr, header):
    """左右に並べたときの、その側の名前と数字"""
    x0 = side * W / 2 + 36
    y0 = 40 if not header else 128
    c = ENTITY[sd['ent']]
    a = prog(t, when(sd.get('t', 0.2), narr), 0.4)
    if a <= 0:
        return
    rows = sd.get('rows', [])
    # 幅は中身に合わせる（3D をなるべく隠さない）
    tw = [cv.tlen(ENTITY_JA[sd['ent']], 34, True) + 30]
    for r in rows:
        tw.append(cv.tlen(r['value'], 40 if r.get('label') else 36, True))
        if r.get('label'):
            tw.append(cv.tlen(r['label'], 24))
    w = min(W / 2 - 72, max(tw) + 70)
    hgt = 70 + sum(94 if r.get('label') else 60 for r in rows) + (8 if rows else 0)
    cv.box((x0, y0, x0 + w, y0 + hgt), a, accent=c)
    cv.circle((x0 + 36, y0 + 36), 10, fill=c, a=a)
    cv.text((x0 + 56, y0 + 36), ENTITY_JA[sd['ent']], 34, TEXT, a, True, 'lm')
    y = y0 + 70
    for r in rows:
        ar = prog(t, when(r.get('t'), narr), 0.45)
        if ar > 0:
            if r.get('label'):
                cv.text((x0 + 28, y + 18), r['label'], 24, TEXT2, ar, False, 'lm')
                cv.text((x0 + 28, y + 58), r['value'], 40, TEXT, ar, True, 'lm')
            else:
                cv.text((x0 + 28, y + 28), r['value'], 36, TEXT, ar, True, 'lm')
        y += 94 if r.get('label') else 60


DRAW = {'label': draw_label, 'route': draw_route}


# ---------------------------------------------------------------- 1コマずつ作る

def anchor_points(data, t, view, crop=None):
    """anchors_cutNNN.json の中身から、時刻 t の点（画面の座標）。crop＝左右に並べるときの切り出し（x0, 幅, 置く x）"""
    if not data:
        return {}
    fr = max(1, data.get('frames', 1))
    i = min(fr - 1, int(t * data.get('fps', 24)))
    out = {}
    for k, v in data['anchors'].items():
        if not v or i >= len(v) or v[i] is None:
            continue
        x, y, vis = v[i]
        if not vis:
            continue
        px, py = x * W, y * H
        if crop:
            cx0, cw, dx = crop
            px = dx + (px - cx0) * (W / 2) / cw
        out[k] = (px, py)
    return out


def frames(row, sec, base, anchors, fps=24):
    """カットの全コマの重ね絵（RGBA の bytes）を順に返す。base＝字幕などの重ね絵（RGBA）
    anchors：1つ（または左右の2つ）の anchors_cutNNN.json の中身"""
    no = row['no']
    narr = row['narration']
    N, SP = tables()
    sp = SP.get(no)
    elems = []
    if sp:
        for side, sd in enumerate(sp['sides']):
            for e in sd.get('notes', []):
                e = dict(e)
                e['_side'] = side
                elems.append(e)
    else:
        elems = [dict(e) for e in N.get(no, [])]
    for e in elems:
        e['_t'] = when(e.get('t'), narr)
    nfr = int(sec * fps)
    last_key, last_bytes = None, None
    for f in range(nfr):
        t = f / fps
        # 変化がないコマは、前のコマをそのまま使う
        idx = tuple(min(max(1, (a or {}).get('frames', 1)) - 1, int(t * 24)) for a in anchors)
        key = (idx, round(t, 2) if any(t < e['_t'] + 3.2 for e in elems) or _animating(no, t, narr) else None)
        if key == last_key and last_bytes is not None:
            yield last_bytes
            continue
        cv = Canvas()
        if sp:
            cw = W / 2
            for side in (0, 1):
                v = (side * cw, 0, (side + 1) * cw, H)
                cxf = sp.get('crop', (0.5, 0.5))[side]
                crop = ((W - cw) * cxf, cw, side * cw)
                P = anchor_points(anchors[side] if side < len(anchors) else None, t, v, crop)
                for e in elems:
                    if e['_side'] == side:
                        DRAW[e['type']](cv, e, t, P, v)
                draw_side(cv, sp['sides'][side], side, t, narr, sp.get('header'))
            cv.line([(W / 2, 0), (W / 2, H)], SHADOW, 6, 1.0)
            if sp.get('header'):
                a = prog(t, 0.1, 0.4)
                tw = cv.tlen(sp['header'], 38, True) + 64
                cv.box((W / 2 - tw / 2, 36, W / 2 + tw / 2, 108), a, alpha=0.86)
                cv.text((W / 2, 72), sp['header'], 38, TEXT, a, True, 'mm')
            if sp.get('note'):
                a = prog(t, 1.0, 0.4)
                tw = cv.tlen(sp['note'], 22) + 36
                cv.box((W / 2 - tw / 2, 820, W / 2 + tw / 2, 858), a, alpha=0.7, radius=8)
                cv.text((W / 2, 839), sp['note'], 22, TEXT2, a, False, 'mm')
        else:
            v = (0, 0, W, H)
            P = anchor_points(anchors[0] if anchors else None, t, v)
            for e in elems:
                if e['type'] in DRAW:
                    DRAW[e['type']](cv, e, t, P, v)
                elif e['type'] == 'panel':
                    draw_panel(cv, e, t, narr)
                elif e['type'] == 'daybar':
                    draw_daybar(cv, e, t, narr)
                elif e['type'] == 'steps':
                    draw_steps(cv, e, t, narr)
                elif e['type'] == 'cycle':
                    draw_cycle(cv, e, t, narr)
        img = base.copy()
        img.alpha_composite(cv.result())
        last_key, last_bytes = key, img.tobytes()
        yield last_bytes


def _animating(no, t, narr):
    """パネルの行・数字・輪の図など、時刻で変わる物がまだ動いているか"""
    N, SP = tables()
    ts = []
    for e in N.get(no, []):
        for r in e.get('rows', []):
            ts.append(when(r.get('t'), narr) + r.get('dur', 0.5))
        if e['type'] == 'steps':
            ts.append(max(step_times(e, narr)) + 0.5)
        if e['type'] == 'cycle':
            ts += [when(w, narr) + 1.0 for _, w in e['items']]
        if e['type'] == 'daybar':
            ts.append(when(e.get('t'), narr) + 0.4 + len(e['parts']) * 1.0 + 0.5)
    sp = SP.get(no)
    if sp:
        ts.append(1.6)
        for sd in sp['sides']:
            ts.append(when(sd.get('t', 0.2), narr) + 0.5)
            for r in sd.get('rows', []):
                ts.append(when(r.get('t'), narr) + 0.5)
    return any(t < x for x in ts)


def load_anchors(path):
    if path and os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    return None
