"""並行地球：地図・グラフ・文字の動画を作る小さな道具（PIL で1コマずつ描き、ffmpeg で動画にする）

- 1920×1080・24コマ/秒。線は2倍の大きさで描いて縮め、なめらかにする
- 色は役割ごとに決める（docs：dataviz の暗い面の配色を、この動画の背景で確かめた）
    R1-1（大木の島の歴史）＝青、R1-4（小さな火山島の歴史）＝橙、A1-2（群島の歴史）＝青緑、C1-3（大きな島の歴史）＝黄
    橙と黄は見分けにくいので、同時に出すときは必ず名前を添える
- 文字は役割の色（主・副・控えめ）。系列の色は印にだけ使う
- 書体は HEIKOU_FONT（なければ IPA ゴシック）
"""
import math
import os
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
FPS = 24
SS = 2   # 線を描くときの倍率

BG = (14, 22, 32)
BG2 = (20, 32, 46)
TEXT = (240, 239, 236)
TEXT2 = (195, 194, 183)
MUTED = (139, 138, 131)
GRID = (52, 64, 78)
ENTITY = {'R1-1': (57, 135, 229), 'R1-4': (217, 89, 38), 'A1-2': (25, 158, 112), 'C1-3': (201, 133, 0)}
ENTITY_JA = {'R1-1': '大木の島の歴史', 'R1-4': '小さな火山島の歴史', 'A1-2': '群島の歴史', 'C1-3': '大きな島の歴史'}
FAMILY = {'C': (201, 133, 0), 'A': (25, 158, 112), 'S': (144, 133, 233), 'R': (217, 89, 38)}
TAGS = {'計算': '計算結果', '設定': '設定', '事実': '事実', '架空': '架空（設定）', '参考': '参考（本編の比較外）'}

FONT_PATHS = [os.environ.get('HEIKOU_FONT', ''), '/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc',
              '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', '/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf']
FONT_BOLD = [os.environ.get('HEIKOU_FONT_BOLD', ''), '/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc',
             '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc', '/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf']
_fonts = {}


def font(size, bold=False):
    key = (size, bold)
    if key not in _fonts:
        for p in (FONT_BOLD if bold else FONT_PATHS):
            if p and os.path.exists(p):
                _fonts[key] = ImageFont.truetype(p, size)
                break
        else:
            _fonts[key] = ImageFont.load_default()
    return _fonts[key]


def ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def appear(t, start, dur=0.5):
    """t 秒の時点で、start 秒から dur 秒かけて現れる割合"""
    return ease((t - start) / dur)


def blend(c, a, bg=BG):
    return tuple(int(round(bg[i] + (c[i] - bg[i]) * a)) for i in range(3))


def background():
    img = Image.new('RGB', (W, H), BG)
    y = np.linspace(0, 1, H)[:, None]
    x = np.linspace(-1, 1, W)[None, :]
    v = np.clip(1 - 0.35 * (x ** 2 + (y - 0.4) ** 2), 0, 1)
    arr = (np.array(BG2)[None, None, :] * v[..., None] + np.array(BG)[None, None, :] * (1 - v[..., None]))
    return Image.fromarray(arr.astype(np.uint8))


_BG = None


def canvas():
    global _BG
    if _BG is None:
        _BG = background()
    return _BG.copy()


def text(d, xy, s, size=40, color=TEXT, a=1.0, bold=False, anchor='la'):
    d.text(xy, s, font=font(size, bold), fill=blend(color, a), anchor=anchor)


def tag(img, kind, a=1.0):
    """右上の区別の表示（計算結果・設定・事実・架空・参考）"""
    if not kind:
        return
    d = ImageDraw.Draw(img)
    s = TAGS.get(kind, kind)
    f = font(26)
    w = d.textlength(s, font=f)
    x1, y0 = W - 70, 52
    d.rounded_rectangle([x1 - w - 32, y0, x1, y0 + 46], radius=8, outline=blend(TEXT2, a * 0.7), width=2)
    d.text((x1 - 16, y0 + 23), s, font=f, fill=blend(TEXT2, a), anchor='rm')


def label_chip(img, xy, name, color, a=1.0, size=30):
    """系列の名前：色の印（丸）＋文字（文字は文字の色）"""
    d = ImageDraw.Draw(img)
    x, y = xy
    r = 9
    d.ellipse([x - r, y - r, x + r, y + r], fill=blend(color, a))
    d.text((x + 20, y), name, font=font(size), fill=blend(TEXT, a), anchor='lm')


class Layer:
    """2倍の大きさで線や点を描き、縮めて重ねる"""

    def __init__(self):
        self.img = Image.new('RGBA', (W * SS, H * SS), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    def line(self, pts, color, width=4, a=1.0):
        if len(pts) < 2:
            return
        p = [(x * SS, y * SS) for x, y in pts]
        self.d.line(p, fill=tuple(color) + (int(255 * a),), width=int(width * SS), joint='curve')

    def circle(self, xy, r, color, a=1.0, outline=None, ow=2):
        x, y = xy[0] * SS, xy[1] * SS
        R = r * SS
        self.d.ellipse([x - R, y - R, x + R, y + R], fill=tuple(color) + (int(255 * a),),
                       outline=(tuple(outline) + (int(255 * a),)) if outline else None, width=int(ow * SS))

    def rect(self, box, color, a=1.0, radius=6):
        b = [v * SS for v in box]
        self.d.rounded_rectangle(b, radius=radius * SS, fill=tuple(color) + (int(255 * a),))

    def onto(self, img):
        small = self.img.resize((W, H), Image.LANCZOS)
        img.paste(small, (0, 0), small)
        return img


class Axes:
    """折れ線グラフの軸（横は年、縦は値。対数も可）"""

    def __init__(self, box, xlim, ylim, log=False):
        self.x0, self.y0, self.x1, self.y1 = box
        self.xlim, self.ylim, self.log = xlim, ylim, log

    def X(self, v):
        return self.x0 + (v - self.xlim[0]) / (self.xlim[1] - self.xlim[0]) * (self.x1 - self.x0)

    def Y(self, v):
        lo, hi = self.ylim
        if self.log:
            v, lo, hi = math.log10(max(v, 1e-9)), math.log10(lo), math.log10(hi)
        return self.y1 - (v - lo) / (hi - lo) * (self.y1 - self.y0)

    def draw(self, img, xticks, yticks, xfmt=str, yfmt=str, xlabel='', ylabel='', a=1.0):
        d = ImageDraw.Draw(img)
        for v in yticks:
            y = self.Y(v)
            d.line([(self.x0, y), (self.x1, y)], fill=blend(GRID, a), width=1)
            d.text((self.x0 - 16, y), yfmt(v), font=font(26), fill=blend(TEXT2, a), anchor='rm')
        for v in xticks:
            x = self.X(v)
            d.text((x, self.y1 + 18), xfmt(v), font=font(26), fill=blend(TEXT2, a), anchor='ma')
        d.line([(self.x0, self.y1), (self.x1, self.y1)], fill=blend(MUTED, a), width=2)
        if xlabel:
            d.text(((self.x0 + self.x1) / 2, self.y1 + 62), xlabel, font=font(28), fill=blend(MUTED, a), anchor='ma')
        if ylabel:
            d.text((self.x0 - 70, self.y0 - 26), ylabel, font=font(28), fill=blend(MUTED, a), anchor='ls')


def spread_labels(ys, gap, lo=-1e9, hi=1e9):
    """縦に並ぶ文字が重ならないように位置をずらす（順番は保つ）"""
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    out = list(ys)
    for _ in range(50):
        moved = False
        for a, b in zip(order, order[1:]):
            if out[b] - out[a] < gap:
                m = (out[a] + out[b]) / 2
                out[a], out[b] = m - gap / 2, m + gap / 2
                moved = True
        for i in order:
            out[i] = min(hi, max(lo, out[i]))
        if not moved:
            break
    return out


def spread_1d(xs, widths, lo, hi, pad=24):
    """横に並ぶ文字（中央 xs・幅 widths）が重ならないように、なるべく元の位置の近くへ"""
    n = len(xs)
    order = sorted(range(n), key=lambda i: xs[i])
    pos = [float(xs[i]) for i in order]
    w = [widths[i] + pad for i in order]
    for _ in range(200):
        moved = False
        for k in range(1, n):
            need = (w[k - 1] + w[k]) / 2
            if pos[k] - pos[k - 1] < need - 1e-6:
                over = need - (pos[k] - pos[k - 1])
                pos[k - 1] -= over / 2
                pos[k] += over / 2
                moved = True
        if n:
            pos[0] = max(pos[0], lo + w[0] / 2)
            pos[-1] = min(pos[-1], hi - w[-1] / 2)
        if not moved:
            break
    out = [0.0] * n
    for k, i in enumerate(order):
        out[i] = pos[k]
    return out


def series_pts(ax, ys, upto=None, step=1):
    n = len(ys) if upto is None else max(2, int(upto))
    return [(ax.X(i), ax.Y(ys[i])) for i in range(0, min(n, len(ys)), step)]


def fmt_int(v):
    return format(int(round(v)), ',')


def write_video(path, seconds, draw):
    """draw(t) が返す画像を、seconds 秒分つないで mp4 にする"""
    n = int(round(seconds * FPS))
    p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H),
                          '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', '-preset', 'medium', path],
                         stdin=subprocess.PIPE)
    last = None
    for k in range(n):
        img = draw(k / FPS)
        last = img
        p.stdin.write(img.convert('RGB').tobytes())
    p.stdin.close()
    p.wait()
    return last
