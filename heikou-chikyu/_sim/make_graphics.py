"""並行地球 第1回：地図・グラフ・文字のカットを、計算の記録から動画にする（out/video/cutNNN.mp4）

  python3 make_graphics.py            # すべて
  python3 make_graphics.py 027 053    # 一部だけ
  python3 make_graphics.py --still    # 各カットの最後のコマだけ PNG（確認用）
  python3 make_graphics.py --skip     # もう mp4 があるカットは飛ばす（続きから）

数字はすべて計算の記録（out/main・out/verify-*）から読む。手で書いた数字は、設定（企画の前提）だけ。
"""
import csv
import gzip
import math
import os
import pickle
import sys

import numpy as np
from PIL import Image, ImageDraw

import maps
import metrics
import model as Mo
import world as W
from motion import (BG, ENTITY, ENTITY_JA, FAMILY, GRID, H, MUTED, TEXT, TEXT2, W as WW, Axes, Layer, appear, blend,
                    canvas, ease, fmt_int, font, label_chip, series_pts, spread_1d, spread_labels, tag, text, write_video)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'out', 'video')
TIDS = ['C1', 'C2', 'A1', 'A2', 'S1', 'S2', 'R1', 'R2']
FEAT = {'R1-1': ('R1', 1), 'R1-4': ('R1', 4), 'A1-2': ('A1', 2), 'C1-3': ('C1', 3)}
_runs, _worlds, _maps = {}, {}, {}


def run(tid, k, arm='main'):
    key = (arm, tid, k)
    if key not in _runs:
        with gzip.open(os.path.join(HERE, 'out', arm, '%s-%d.pkl.gz' % (tid, k))) as f:
            r = pickle.load(f)
        r['tech_first'] = r.get('tech_first_raw', r['tech_first'])
        _runs[key] = r
    return _runs[key]


def world(tid):
    if tid not in _worlds:
        _worlds[tid] = W.build_world(tid)
    return _worlds[tid]


def cut_table():
    """いまのカット表（新しい版から）"""
    for name in ('cuts_v4.csv', 'cuts_v3.csv', 'cuts_v2.csv'):
        p = os.path.join(HERE, 'out', 'script', name)
        if os.path.exists(p):
            return p
    raise FileNotFoundError('カット表がない')


def seconds_of():
    rows = list(csv.DictReader(open(cut_table(), encoding='utf-8')))
    return {r['no']: int(r['sec']) for r in rows}


# ---------------------------------------------------------------- 文字のカード

def title_card(lines, sub=None, tagk=None):
    def draw(t):
        img = canvas()
        d = ImageDraw.Draw(img)
        a = appear(t, 0.3, 1.0)
        y = H / 2 - (len(lines) - 1) * 50 - (30 if sub else 0)
        for i, s in enumerate(lines):
            text(d, (WW / 2, y + i * 100), s, 72 if i == 0 else 56, TEXT, appear(t, 0.3 + 0.5 * i, 1.0), bold=i == 0, anchor='mm')
        if sub:
            text(d, (WW / 2, y + len(lines) * 100 + 10), sub, 34, TEXT2, appear(t, 1.2, 1.0), anchor='mm')
        tag(img, tagk, a)
        return img
    return draw


def bullets(title, items, tagk='設定', note=None, start=0.4, gap=1.2):
    """見出しと、順に現れる項目。items は文字列か (文字列, 色)"""
    def draw(t):
        img = canvas()
        d = ImageDraw.Draw(img)
        text(d, (150, 150), title, 56, TEXT, appear(t, 0.1), bold=True)
        lay = Layer()
        for i, it in enumerate(items):
            s, col = (it, None) if isinstance(it, str) else it
            a = appear(t, start + gap * i)
            y = 300 + i * 96
            if col:
                lay.circle((172, y + 4), 12, col, a)
            else:
                lay.rect((160, y - 6, 184, y + 14), TEXT2, a * 0.8, radius=4)
            text(d, (214, y + 4), s, 42, TEXT, a, anchor='lm')
        lay.onto(img)
        if note:
            text(d, (150, H - 120), note, 30, TEXT2, appear(t, start + gap * len(items)))
        tag(img, tagk, appear(t, 0.1))
        return img
    return draw


def flow(title, steps, tagk='設定', sub=None):
    """箱と矢印（計算の流れ・労働の割り振り）。5つ以上は2段に折り返す"""
    n = len(steps)
    rows = 1 if n <= 4 else 2
    per = int(math.ceil(n / rows))
    bw = (WW - 300 - (per - 1) * 60) / per
    bh = 200 if rows == 1 else 170
    ys = [440] if rows == 1 else [330, 620]
    boxes = [(150 + (i % per) * (bw + 60), ys[i // per]) for i in range(n)]

    def draw(t):
        img = canvas()
        d = ImageDraw.Draw(img)
        text(d, (150, 150), title, 56, TEXT, appear(t, 0.1), bold=True)
        lay = Layer()
        for i, (x0, y0) in enumerate(boxes):
            a = appear(t, 0.5 + 0.9 * i)
            lay.rect((x0, y0, x0 + bw, y0 + bh), (40, 58, 78), a, radius=14)
            if i < n - 1:
                aa = appear(t, 0.9 + 0.9 * i)
                x1, y1 = boxes[i + 1]
                if y1 == y0:
                    ym = y0 + bh / 2
                    lay.line([(x0 + bw + 10, ym), (x0 + bw + 50, ym)], TEXT2, 4, aa)
                    lay.line([(x0 + bw + 36, ym - 12), (x0 + bw + 50, ym), (x0 + bw + 36, ym + 12)], TEXT2, 4, aa)
                else:   # 段の終わりから次の段の始めへ
                    yg = (y0 + bh + y1) / 2
                    cx0, cx1 = x0 + bw / 2, x1 + bw / 2
                    lay.line([(cx0, y0 + bh + 8), (cx0, yg), (cx1, yg), (cx1, y1 - 8)], TEXT2, 4, aa)
                    lay.line([(cx1 - 12, y1 - 22), (cx1, y1 - 8), (cx1 + 12, y1 - 22)], TEXT2, 4, aa)
        lay.onto(img)
        for i, s in enumerate(steps):
            a = appear(t, 0.5 + 0.9 * i)
            x0, y0 = boxes[i]
            parts = s.split('\n')
            for j, p in enumerate(parts):
                text(d, (x0 + bw / 2, y0 + bh / 2 + (j - (len(parts) - 1) / 2) * 50), p, 36 if j == 0 else 28, TEXT if j == 0 else TEXT2, a, anchor='mm')
        if sub:
            text(d, (150, ys[-1] + bh + 110), sub, 34, TEXT2, appear(t, 0.5 + 0.9 * n))
        tag(img, tagk, appear(t, 0.1))
        return img
    return draw


def big_numbers(title, cells, tagk='計算', sub=None):
    """大きな数字を並べる。cells：(上の小さな文字, 数字の文字列, 下の説明, 色)"""
    def draw(t):
        img = canvas()
        d = ImageDraw.Draw(img)
        text(d, (150, 150), title, 56, TEXT, appear(t, 0.1), bold=True)
        n = len(cells)
        cw = (WW - 300) / n
        lay = Layer()
        for i, (top, num, bot, col) in enumerate(cells):
            a = appear(t, 0.6 + 1.2 * i)
            cx = 150 + cw * (i + 0.5)
            if col:
                lay.circle((cx - d.textlength(top, font=font(36)) / 2 - 26, 420), 12, col, a)
        lay.onto(img)
        for i, (top, num, bot, col) in enumerate(cells):
            a = appear(t, 0.6 + 1.2 * i)
            cx = 150 + cw * (i + 0.5)
            text(d, (cx, 420), top, 36, TEXT2, a, anchor='mm')
            text(d, (cx, 560), num, 120, TEXT, a, bold=True, anchor='mm')
            text(d, (cx, 690), bot, 34, TEXT2, a, anchor='mm')
        if sub:
            text(d, (WW / 2, 860), sub, 34, TEXT2, appear(t, 0.6 + 1.2 * n), anchor='mm')
        tag(img, tagk, appear(t, 0.1))
        return img
    return draw


# ---------------------------------------------------------------- 折れ線

def lines_chart(title, series, xlim, ylim, log=False, xticks=None, yticks=None, yfmt=fmt_int, xlabel='年', ylabel='',
                tagk='計算', grow=0.7, notes=(), hlines=()):
    """series：(値の並び, 色, 名前 or None, 太さ, 透明度)。名前のある線には、線の終わりに名前を付ける"""
    ax = Axes((230, 300, 1600, 900), xlim, ylim, log)

    def draw(t):
        img = canvas()
        d = ImageDraw.Draw(img)
        text(d, (150, 130), title, 52, TEXT, appear(t, 0.1), bold=True)
        ax.draw(img, xticks or [], yticks or [], xfmt=lambda v: fmt_int(v), yfmt=yfmt, xlabel=xlabel, ylabel=ylabel, a=appear(t, 0.2))
        frac = ease(t / (grow * T_cur[0]))
        upto = xlim[0] + frac * (xlim[1] - xlim[0])
        lay = Layer()
        for v, c, a, s in hlines:
            y = ax.Y(v)
            lay.line([(ax.x0, y), (ax.x1, y)], c, 2, a * appear(t, 0.5))
        for ys, col, name, wdt, alpha in series:
            ys = np.asarray(ys, float)
            n = int(min(len(ys), upto + 1))
            pts = [(ax.X(i), ax.Y(ys[i])) for i in range(int(xlim[0]), n, max(1, (n - int(xlim[0])) // 600 or 1))]
            if n - 1 > int(xlim[0]):
                pts.append((ax.X(n - 1), ax.Y(ys[n - 1])))
            lay.line(pts, col, wdt, alpha)
            if name and pts:
                lay.circle(pts[-1], 6, col, alpha)
        lay.onto(img)
        named = []
        for ys, col, name, wdt, alpha in series:
            if name:
                ys = np.asarray(ys, float)
                n = int(min(len(ys), upto + 1))
                named.append((ax.X(n - 1), ax.Y(ys[n - 1]), name, alpha))
        ly = spread_labels([y for _, y, _, _ in named], 36, ax.y0, ax.y1 + 20)
        for (x, y, name, alpha), yy in zip(named, ly):
            text(d, (x + 16, yy), name, 28, TEXT, alpha * appear(t, 0.4), anchor='lm')
        for v, c, a, s in hlines:
            text(d, (ax.x1 + 12, ax.Y(v)), s, 26, TEXT2, a * appear(t, 0.5), anchor='lm')
        for k, (tt, s) in enumerate(notes):
            text(d, (230, 1000), s, 32, TEXT2, appear(t, tt))
        tag(img, tagk, appear(t, 0.1))
        return img
    return draw


T_cur = [10.0]


# ---------------------------------------------------------------- 年表

def timeline(title, events, span, tagk='計算', color=ENTITY['A1-2'], sub=None):
    """events：(年, 文字, 種類 'new'|'lost')。左から右へ年が進む。
    名前は上と下に交互に置き、近い年どうしは横にずらして引き出し線でつなぐ（位置は最初に全部決める）"""
    x0, x1, y = 200, 1720, 600
    ev = sorted(events)
    f30, f24 = font(30), font(24)
    probe = ImageDraw.Draw(Image.new('RGB', (8, 8)))

    def X(v):
        return x0 + (v - span[0]) / (span[1] - span[0]) * (x1 - x0)

    side = [i % 2 for i in range(len(ev))]          # 0＝上、1＝下
    lx = [0.0] * len(ev)
    for sd in (0, 1):
        idx = [i for i in range(len(ev)) if side[i] == sd]
        xs = [X(ev[i][0]) for i in idx]
        ws = [max(probe.textlength(ev[i][1], font=f30), probe.textlength('%s年' % fmt_int(ev[i][0]), font=f24)) for i in idx]
        for i, v in zip(idx, spread_1d(xs, ws, 120, WW - 120, pad=30)):
            lx[i] = v

    def draw(t):
        img = canvas()
        d = ImageDraw.Draw(img)
        text(d, (150, 150), title, 52, TEXT, appear(t, 0.1), bold=True)
        frac = ease(t / (0.75 * T_cur[0]))
        now = span[0] + frac * (span[1] - span[0])
        lay = Layer()
        lay.line([(x0, y), (x1, y)], MUTED, 3, appear(t, 0.2))
        lay.line([(x0, y), (X(now), y)], color, 6, 1.0)
        for i, (yr, s, kind) in enumerate(ev):
            if yr > now:
                continue
            a = min(1.0, (now - yr) / ((span[1] - span[0]) * 0.03 + 1e-6))
            up = side[i] == 0
            ty = y - 130 if up else y + 130
            px = X(yr)
            # 引き出し線：点から少し離れて、名前の真下（上）まで
            yk = y - 60 if up else y + 60
            lay.line([(px, y + (-14 if up else 14)), (px, yk), (lx[i], ty + (24 if up else -24))], MUTED, 2, a)
            col = color if kind == 'new' else (120, 120, 120)
            lay.circle((px, y), 11, col, 1.0, outline=BG, ow=3)
        lay.onto(img)
        for i, (yr, s, kind) in enumerate(ev):
            if yr > now:
                continue
            a = min(1.0, (now - yr) / ((span[1] - span[0]) * 0.03 + 1e-6))
            up = side[i] == 0
            ty = y - 130 if up else y + 130
            text(d, (lx[i], ty), s, 30, TEXT if kind == 'new' else MUTED, a, anchor='md' if up else 'ma')
            text(d, (lx[i], ty + (-40 if up else 40)), '%s年' % fmt_int(yr), 24, TEXT2, a, anchor='md' if up else 'ma')
        text(d, (x1, y + 300), '%s年' % fmt_int(now), 40, TEXT2, 1.0, anchor='rm')
        if sub:
            text(d, (150, H - 110), sub, 32, TEXT2, appear(t, 0.75 * T_cur[0]))
        tag(img, tagk, appear(t, 0.1))
        return img
    return draw


def presence_strip(title, ent, tech, span=(0, 3000), sub=None, tagk='計算'):
    """ある技術を知っている集団の数を、10年ごとの記録から帯で描く。失われた年に印"""
    tid, k = FEAT[ent]
    r = run(tid, k)
    yrs = np.array([s_['year'] for s_ in r['snaps']])
    cnt = np.array([sum(1 for g in s_['groups'] if tech in g.get('techs', ())) for s_ in r['snaps']])
    tot = np.array([len(s_['groups']) for s_ in r['snaps']])
    ev = [e for e in r['events'] if e.get('tech') == tech and e['kind'] in ('tech', 'tech_spread', 'tech_lost')]
    first = min((e['year'] for e in ev if e['kind'] == 'tech'), default=None)
    lost = [e['year'] for e in ev if e['kind'] == 'tech_lost']
    x0, x1, yb, hh = 200, 1720, 640, 260
    gmax = max(4, int(tot.max()))
    X = lambda v: x0 + (v - span[0]) / (span[1] - span[0]) * (x1 - x0)
    col = ENTITY[ent]

    def draw(t):
        img = canvas()
        d = ImageDraw.Draw(img)
        text(d, (150, 130), title, 52, TEXT, appear(t, 0.1), bold=True)
        frac = ease(t / (0.7 * T_cur[0]))
        now = span[0] + frac * (span[1] - span[0])
        lay = Layer()
        for gg in range(1, gmax + 1):
            lay.line([(x0, yb - gg / gmax * hh), (x1, yb - gg / gmax * hh)], GRID, 1, appear(t, 0.2))
        for j in range(len(yrs)):
            if yrs[j] > now or cnt[j] == 0:
                continue
            xa, xb = X(yrs[j]), X(min(yrs[j] + 10, span[1]))
            lay.rect((xa, yb - cnt[j] / gmax * hh, xb + 0.6, yb), col, 0.9, radius=0)
        lay.line([(x0, yb), (x1, yb)], MUTED, 2, appear(t, 0.2))
        for v in lost:
            if v <= now:
                lay.line([(X(v), yb + 14), (X(v), yb + 44)], TEXT2, 3, 0.9)
        lay.onto(img)
        a = appear(t, 0.2)
        for v in range(span[0], span[1] + 1, 500):
            text(d, (X(v), yb + 60), fmt_int(v), 26, TEXT2, a, anchor='ma')
        text(d, (x0 - 20, yb - hh), '%d集団' % gmax, 24, TEXT2, a, anchor='rm')
        text(d, (x0 - 20, yb), '0', 24, TEXT2, a, anchor='rm')
        text(d, (x0, yb - hh - 40), '斧を知っている集団の数（10年ごとの記録）', 28, MUTED, a, anchor='ls')
        text(d, ((x0 + x1) / 2, yb + 104), '年（縦の短い線＝集団が斧を失った年）', 26, MUTED, a, anchor='ma')
        lines = []
        if first is not None and now >= first:
            lines.append('%s年　初めて生まれる' % fmt_int(first))
        nl = sum(1 for v in lost if v <= now)
        if nl:
            lines.append('集団の中で失われた　%d回' % nl)
        if lost and cnt[-1] == 0 and now >= max(lost):
            lines.append('%s年　最後の集団が失い、斧は消える' % fmt_int(max(lost)))
        for i, s_ in enumerate(lines):
            text(d, (x1, yb + 150 + i * 50), s_, 34, TEXT, 1.0, anchor='ra')   # 右寄せ・上の方に（下は字幕の場所）
        if sub:
            text(d, (150, H - 40), sub, 30, TEXT2, appear(t, 0.75 * T_cur[0]), anchor='ls')
        tag(img, tagk, appear(t, 0.1))
        return img
    return draw


# ---------------------------------------------------------------- 地図

def map_image(tid, width, window=None, halo=25.0):
    key = (tid, width, window, halo)
    if key not in _maps:
        arr = maps.render_array(world(tid), width, halo_km=halo, window=window)
        im = Image.fromarray(arr)
        h = int(round(width * (window[3] - window[2]) / (window[1] - window[0]))) if window else width // 2
        _maps[key] = im.resize((width, h), Image.LANCZOS)
    return _maps[key]


def snap_at(r, year):
    return max((s for s in r['snaps'] if s['year'] <= year), key=lambda s: s['year'])


def project(window, w_px, h_px, lat, lon):
    lon_a, lon_b, lat_a, lat_b = window
    mid = (lon_a + lon_b) / 2
    lc = (np.asarray(lon) - mid + 180) % 360 - 180 + mid
    return (lc - lon_a) / (lon_b - lon_a) * w_px, (lat_b - np.asarray(lat)) / (lat_b - lat_a) * h_px


def window_for(tid, k, years=(2990,), margin=500, arm='main'):
    r = run(tid, k, arm)
    w = world(tid)
    reg = w['reg']
    lats, lons = [], []
    for y in years:
        for g in snap_at(r, y)['groups']:
            lats.append(reg['lat'][g['region']])
            lons.append(reg['lon'][g['region']])
    return tuple(float(v) for v in maps.window_around(lats, lons, margin_km=margin))


def groups_layer(lay, ent, tid, snap, window, ox, oy, w_px, h_px, a=1.0, scale=1.0):
    """集団を点で。大きさは人数。同じ地域にいる集団は、重ならないよう小さな輪に並べる"""
    reg = world(tid)['reg']
    by = {}
    for g in snap['groups']:
        by.setdefault(g['region'], []).append(g)
    for rg, gs in by.items():
        x, y = project(window, w_px, h_px, reg['lat'][rg], reg['lon'][rg])
        x, y = ox + float(x), oy + float(y)
        rads = [max(5.0, 1.1 * math.sqrt(g['pop']) / 3) * scale for g in gs]
        if len(gs) == 1:
            lay.circle((x, y), rads[0], ENTITY[ent], a * 0.9, outline=BG, ow=1.5)
            continue
        n = len(gs)
        ring = max(rads) * (1.25 / math.sin(math.pi / n) if n > 1 else 0)
        for j, (g, rd) in enumerate(zip(gs, rads)):
            q = -math.pi / 2 + 2 * math.pi * j / n
            lay.circle((x + ring * math.cos(q), y + ring * math.sin(q)), rd, ENTITY[ent], a * 0.9, outline=BG, ow=1.5)


_shade = {}


def shade_bottom(img, y0=840):
    """地図の下の方を暗くして、文字を読みやすくする"""
    if y0 not in _shade:
        m = np.zeros((H, WW), np.float32)
        m[y0:] = np.linspace(0, 0.82, H - y0)[:, None] ** 0.8
        _shade[y0] = Image.fromarray((m * 255).astype(np.uint8))
    return Image.composite(Image.new('RGB', (WW, H), BG), img, _shade[y0])


def map_timelapse(ent, title, y0, y1, margin=500, arm='main', tagk='計算', hold=0.15, extra=None):
    tid, k = FEAT[ent]
    r = run(tid, k, arm)
    win = window_for(tid, k, years=(y1 - 10,), margin=margin, arm=arm)
    base = map_image(tid, WW, win)
    pop = np.asarray(r['series']['pop'])
    isl = np.asarray(r['series']['islands'])

    def draw(t):
        img = canvas()
        img.paste(base, (0, (H - base.height) // 2))
        frac = ease(t / ((1 - hold) * T_cur[0]))
        year = int(y0 + frac * (y1 - 1 - y0))
        snap = snap_at(r, year)
        lay = Layer()
        groups_layer(lay, ent, tid, snap, win, 0, (H - base.height) // 2, WW, base.height)
        if extra:
            extra(lay, win, t)
        lay.onto(img)
        img = shade_bottom(img)
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, WW, 130], fill=BG)
        text(d, (80, 66), title, 44, TEXT, 1.0, bold=True, anchor='lm')
        label_chip(img, (80, 1010), ENTITY_JA[ent] + '（' + ent + '）', ENTITY[ent])
        text(d, (WW - 80, 950), '%s年' % fmt_int(year), 56, TEXT, 1.0, bold=True, anchor='rm')
        text(d, (WW - 80, 1022), '人口 %s人・住む島 %d' % (fmt_int(pop[year]), isl[year]), 34, TEXT, 1.0, anchor='rm')
        tag(img, tagk, 1.0)
        return img
    return draw


def terrain_pair(a, b, title):
    def draw(t):
        img = canvas()
        d = ImageDraw.Draw(img)
        text(d, (150, 140), title, 52, TEXT, appear(t, 0.1), bold=True)
        for i, tid in enumerate((a, b)):
            m = map_image(tid, 860)
            x0 = 80 + i * 900
            al = appear(t, 0.4 + 0.8 * i)
            m2 = Image.blend(Image.new('RGB', m.size, BG), m, al)
            img.paste(m2, (x0, 300))
            s = W.summary(world(tid))
            text(d, (x0, 270), '%s %s' % (tid, W.TERRAINS[tid][1]), 36, TEXT, al)
            text(d, (x0, 300 + m.height + 24), '島 %s・いちばん近い島まで（中央値） %dkm' % (fmt_int(s['島の数']),
                 s['いちばん近い島までの海の幅km（10・50・90％点）'][1]), 28, TEXT2, al)
        tag(img, '設定', appear(t, 0.1))
        return img
    return draw


# ---------------------------------------------------------------- 点と幅のグラフ（地形ごと）

def dots_by_terrain(title, values, fmt, xlim, xticks, note=None, tagk='計算', none_label='渡らない', xlabel=''):
    """地形ごとに5試行の値を点で、中央値を縦線で。None は右端に「渡らない」としてまとめる"""
    x0, x1 = 520, 1600

    def X(v):
        return x0 + (v - xlim[0]) / (xlim[1] - xlim[0]) * (x1 - x0)

    def draw(t):
        img = canvas()
        d = ImageDraw.Draw(img)
        text(d, (150, 130), title, 50, TEXT, appear(t, 0.1), bold=True)
        lay = Layer()
        for v in xticks:
            lay.line([(X(v), 250), (X(v), 960)], GRID, 1, appear(t, 0.2))
        for i, tid in enumerate(TIDS):
            y = 280 + i * 84
            a = appear(t, 0.4 + 0.35 * i)
            col = FAMILY[tid[0]]
            vals = values[tid]
            got = [v for v in vals if v is not None]
            for j, v in enumerate(vals):
                if v is None:
                    lay.circle((x1 + 90 + j * 22, y), 9, MUTED, a)
                else:
                    lay.circle((X(v), y + (j - 2) * 3), 10, col, a, outline=BG, ow=2)
            if got:
                m = float(np.median(got))
                lay.line([(X(m), y - 24), (X(m), y + 24)], TEXT, 3, a)
        lay.onto(img)
        for v in xticks:
            text(d, (X(v), 990), fmt(v), 26, TEXT2, appear(t, 0.2), anchor='ma')
        text(d, (x1 + 90, 240), none_label, 26, TEXT2, appear(t, 0.2), anchor='ls')
        if xlabel:
            text(d, ((x0 + x1) / 2, 1030), xlabel, 26, MUTED, appear(t, 0.2), anchor='ma')
        for i, tid in enumerate(TIDS):
            y = 280 + i * 84
            text(d, (150, y), '%s %s' % (tid, W.TERRAINS[tid][1]), 30, TEXT, appear(t, 0.4 + 0.35 * i), anchor='lm')
        if note:
            text(d, (150, H - 40), note, 28, TEXT2, appear(t, 3.5), anchor='ls')
        tag(img, tagk, appear(t, 0.1))
        return img
    return draw


# ---------------------------------------------------------------- 個々のカット

def build_cuts():
    C = {}
    main = {(t, k): run(t, k) for t in TIDS for k in range(5)}
    pop = lambda e: np.asarray(run(*FEAT[e])['series']['pop'])
    ser = lambda e, key, arm='main': np.asarray(run(*FEAT[e], arm=arm)['series'][key])

    C['005'] = title_card(['並行地球', '地球の99％が海だったら'])
    C['066'] = title_card(['三千年後'])
    C['088'] = title_card(['もし、この星に', '〇〇があったら'], tagk='架空')
    C['007'] = big_numbers('陸地の割合', [('現実の地球', '29%', '陸は約1億4,900万km²', None),
                                         ('この星', '1%', '約510万km²（オーストラリアの約3分の2）', None)], tagk='事実',
                           sub='この星の数字は企画の設定、現実の地球の数字は事実')
    C['018'] = big_numbers('計算した歴史の数', [('世界', '8', '陸の並び方の違い', None), ('各', '5回', '始まりの場所と偶然を変えて', None),
                                              ('それぞれ', '3,000年', '1年ずつ', None), ('あわせて', '40', 'の歴史', None)], tagk='設定')
    C['014'] = bullets('出発するときの人々', ['1,000人 ＝ 200人 × 5集団', '言葉・火', '打ち欠いた石の道具', '採集と、岸での漁',
                                               '簡単な住まい', 'いかだ（約30kmまで）'], gap=0.9)
    C['015'] = bullets('知らないこと', ['島の外の地図', 'ほかの集団の居場所', 'まだ見つけていない資源'], gap=1.1)
    C['016'] = flow('1年の計算の流れ', ['気候と災害', '労働の割り振り', '食べ物と水', '生まれる・亡くなる', '知識', '探索と移住'])
    C['017'] = title_card(['住民の判断は、', '決めた規則と確率で計算'], sub='AI は使っていない。嵐・病気・発見には偶然が入る', tagk='設定')
    C['024'] = flow('大人1人の1年（250日）の使い方', ['水・薪・道具\n先に引く', '食べ物\n必要な分まで', '住まい・舟・畑\n残りから', '余暇\n残った時間'])
    C['025'] = flow('余暇から生まれるもの', ['休む', '子に教える', '新しいことを試す', '技術の芽'])
    C['039'] = bullets('技術が失われるとき', ['人が少ない（大人25人未満で急に失われやすい）', '材料が手に入らない', '教える余暇がない'], gap=1.2)
    C['041'] = bullets('世界を比べる4つの物差し', ['人口', '平均寿命（年齢別の死亡率から）', '貧困（食べ物・水・住まいが足りない人の割合）',
                                              '暮らしの余裕（大人1人の余暇の日数）'], gap=1.0)
    C['078'] = title_card(['余裕が、', '海を越える舟を生んだ'], tagk='計算')
    C['085'] = title_card(['参考：計算を延ばすと', '4,108年に初めて海の向こうへ移り住む'], sub='本編の比較には含めない', tagk='参考')
    C['087'] = bullets('分かれ目になったもの', ['海の距離と、舟の届く距離', '育てられる植物があるか', '暮らしの余裕（余暇）'], tagk='計算')
    C['089'] = bullets('行き詰まりの3つの原因', ['育てられる植物がない', '舟の材料（大木）がない', '余暇がない（年に数日）'], tagk='計算')
    C['091'] = bullets('潮麦（架空の植物）', ['暖かい海の浅瀬に育つ穀物', '浅瀬の最大5割まで広げられる', '1km²で、1年に40人分',
                                           '代償：岸の魚が減る', '代償：嵐の高潮に弱い'], tagk='架空', gap=1.0)
    C['093'] = bullets('軽殻石（架空の素材）', ['水に浮く軽い石', '大木がなくても舟を作れる（届く距離 約100km）', '割れやすい（年22％傷む）', '量に限りがある'], tagk='架空', gap=1.0)
    C['094'] = big_numbers('もう一つの条件', [('最初の人数', '2,000人', '400人 × 5集団', None)], tagk='設定')
    C['095'] = bullets('比べ方', ['地形・始まりの場所・偶然は同じ', '違うのは、足したもの（または人数）だけ', '8つの世界 × 5回ずつ'], tagk='設定')
    C['103'] = title_card(['足すだけでは、抜け出せない'], sub='必要だったのは、余裕と届く舟の両方', tagk='計算')
    C['106'] = bullets('結論1', ['島どうしが近い世界では、多くの場合', '3,000年で数十の島へ', '人口は数万〜十万人あまり'], tagk='計算')
    C['107'] = bullets('結論2', ['ひとつの大きな島の世界では', '暮らしが島の中で足りていた', '海の向こうへは、5回とも移り住まなかった'], tagk='計算')
    C['108'] = bullets('結論3', ['遠く離れた小島の世界では', 'どこから始まったかが、行く末を大きく分けた', '5回中3回は最初の島から出られなかった'], tagk='計算')
    C['109'] = bullets('結論', ['海を越える舟も、新しい道具も', 'それを生んだのは、暮らしの余裕だった'], tagk='計算')
    C['110'] = title_card(['数字は、仮定と規則しだいで変わる'], sub='出生率・技術を思いつく速さ・住民の判断の規則', tagk='設定')
    C['114'] = title_card(['並行地球 第1回', '地球の99％が海だったら'],
                          sub='計算：heikou-sim 1.1（追加検証 1.2）・3DCG：Blender / Cycles・人の体：MakeHuman（CC0）・音声：VOICEVOX', tagk=None)
    # 地形
    C['009'] = terrain_pair('C1', 'C2', '大きな陸地へ集中')
    C['010'] = terrain_pair('A1', 'A2', '近接した群島')
    C['011'] = terrain_pair('S1', 'S2', '飛び石状の島々')
    C['012'] = terrain_pair('R1', 'R2', '遠く離れた小島')

    def four_maps(t):
        img = canvas()
        d = ImageDraw.Draw(img)
        text(d, (150, 120), '惑星の大きさと陸の面積は同じ。並び方だけが違う', 46, TEXT, appear(t, 0.1), bold=True)
        for i, tid in enumerate(['C1', 'A1', 'S1', 'R1']):
            m = map_image(tid, 780)
            x0, y0 = 150 + (i % 2) * 840, 220 + (i // 2) * 420
            al = appear(t, 0.4 + 0.5 * i)
            img.paste(Image.blend(Image.new('RGB', m.size, BG), m, al), (x0, y0))
            text(d, (x0, y0 + m.height + 14), '%s・陸 510万km²' % W.TERRAINS[tid][0], 26, TEXT2, al)
        tag(img, '設定', appear(t, 0.1))
        return img
    C['008'] = four_maps
    # 人口の始まり
    series = []
    for t_ in TIDS:
        for k in range(5):
            series.append((np.asarray(main[(t_, k)]['series']['pop'][:301]), (95, 110, 125), None, 2, 0.8))
    for e in ('A1-2', 'R1-4'):
        series.append((pop(e)[:301], ENTITY[e], ENTITY_JA[e], 4, 1.0))
    C['027'] = lines_chart('40の歴史の人口（最初の300年）', series, (0, 300), (300, 4000), log=True, xticks=[0, 100, 200, 300],
                           yticks=[300, 1000, 3000], ylabel='人口（目盛りは10倍ごと）')
    p4 = pop('R1-4')
    C['029'] = big_numbers('小さな火山島（771km²）', [('採集と漁で養える人数', '約550人', '計算の自然の量から', ENTITY['R1-4']),
                                                   ('置かれた人数', '1,000人', '200人 × 5集団', ENTITY['R1-4'])])
    C['030'] = lines_chart('小さな火山島の歴史：最初の100年', [(p4[:101], ENTITY['R1-4'], ENTITY_JA['R1-4'], 4, 1.0)], (0, 100), (0, 1100),
                           xticks=[0, 25, 50, 75, 100], yticks=[0, 250, 500, 750, 1000], ylabel='人口',
                           hlines=[(550, MUTED, 0.9, '養える人数 約550人')], notes=[(5.0, '50年で %s人' % fmt_int(p4[50]))])
    le4 = ser('R1-4', 'leisure')
    leA = ser('A1-2', 'leisure')
    sm = lambda v, k=25: np.convolve(np.pad(v, (k, k), mode='edge'), np.ones(2 * k + 1) / (2 * k + 1), 'valid')
    C['032'] = lines_chart('余暇（大人1人が1年に休んだり試したりできる日数）', [(sm(le4), ENTITY['R1-4'], ENTITY_JA['R1-4'], 4, 1.0)],
                           (0, 2999), (0, 200), xticks=[0, 1000, 2000, 3000], yticks=[0, 50, 100, 150, 200], ylabel='日（25年の平均）')
    C['043'] = lines_chart('暮らしの余裕：余暇の日数', [(sm(leA), ENTITY['A1-2'], ENTITY_JA['A1-2'], 4, 1.0), (sm(le4), ENTITY['R1-4'], ENTITY_JA['R1-4'], 4, 1.0)],
                           (0, 2999), (0, 200), xticks=[0, 1000, 2000, 3000], yticks=[0, 50, 100, 150, 200], ylabel='日（25年の平均）')
    # 平均寿命
    e0 = {}
    for t_ in TIDS:
        vals = [metrics.life_expectancy(main[(t_, k)]['deaths_age'], main[(t_, k)]['pop_age'], 2500, 3000) for k in range(5)]
        e0[t_] = [v for v in vals]
    C['042'] = dots_by_terrain('平均寿命（最後の500年・年齢別の死亡率から計算）', e0, lambda v: '%d歳' % v, (20, 40), [20, 25, 30, 35, 40],
                               note='どの世界もおよそ30歳。狩猟採集の暮らしに近い値', none_label='未算出')
    # 初めて海を渡った年
    cross = {}
    isl_n = {}
    for t_ in TIDS:
        cross[t_] = []
        isl_n[t_] = []
        for k in range(5):
            ev = [e['year'] for e in main[(t_, k)]['events'] if e['kind'] in ('settle', 'relocate') and e.get('first')]
            cross[t_].append(ev[0] if ev else None)
            isl_n[t_].append(main[(t_, k)]['series']['islands'][-1])
    C['059'] = dots_by_terrain('初めて海の向こうへ移り住んだ年（5回ずつ・縦線は中央値）', cross, lambda v: '%s年' % fmt_int(v), (0, 3000),
                               [0, 500, 1000, 1500, 2000, 2500, 3000], none_label='移り住まない')
    C['060'] = C['059']
    C['061'] = dots_by_terrain('3,000年後に人が住む島の数（5回ずつ）', isl_n, lambda v: fmt_int(v), (0, 80), [0, 20, 40, 60, 80], none_label='')
    # 距離と広がり
    def scatter_gap(t):
        img = canvas()
        d = ImageDraw.Draw(img)
        text(d, (150, 130), '島どうしの距離と、住む島の数', 50, TEXT, appear(t, 0.1), bold=True)
        ax = Axes((300, 300, 1640, 880), (0, 1200), (1, 100), log=True)
        ax.draw(img, [0, 300, 600, 900, 1200], [1, 3, 10, 30, 100], xfmt=lambda v: '%dkm' % v, yfmt=fmt_int,
                xlabel='いちばん近い島までの海の幅（地形の中央値）', ylabel='3,000年後に住む島の数', a=appear(t, 0.2))
        lay = Layer()
        for i, t_ in enumerate(TIDS):
            g = W.summary(world(t_))['いちばん近い島までの海の幅km（10・50・90％点）'][1]
            for k, v in enumerate(isl_n[t_]):
                lay.circle((ax.X(g) + (k - 2) * 7, ax.Y(max(v, 1))), 10, FAMILY[t_[0]], appear(t, 0.5 + 0.4 * i), outline=BG)
        lay.onto(img)
        for i, t_ in enumerate(TIDS):
            g = W.summary(world(t_))['いちばん近い島までの海の幅km（10・50・90％点）'][1]
            text(d, (ax.X(g) + 24, ax.Y(max(np.median(isl_n[t_]), 1)) - 26), t_, 26, TEXT, appear(t, 0.5 + 0.4 * i))
        text(d, (150, H - 40), '近い島が多い世界ほど、多くの島へ広がる傾向（5回ずつの結果）', 28, TEXT2, appear(t, 4.0), anchor='ls')
        tag(img, '計算', appear(t, 0.1))
        return img
    C['062'] = scatter_gap
    # R1 の5回
    r1 = [(np.asarray(main[('R1', k)]['series']['pop']), ENTITY['R1-1'] if k == 1 else (ENTITY['R1-4'] if k == 4 else (110, 120, 132)),
           ENTITY_JA['R1-1'] if k == 1 else (ENTITY_JA['R1-4'] if k == 4 else None), 4 if k in (1, 4) else 2, 1.0 if k in (1, 4) else 0.8) for k in range(5)]
    C['067'] = lines_chart('遠く離れた小島の世界：5回の人口', r1, (0, 2999), (200, 200000), log=True, xticks=[0, 1000, 2000, 3000],
                           yticks=[300, 1000, 10000, 100000], ylabel='人口（目盛りは10倍ごと）')
    # 年表
    def tech_events(e, techs):
        r = run(*FEAT[e])
        out = []
        first = {}
        for ev in r['events']:
            if ev['kind'] in ('tech', 'tech_spread') and ev.get('tech') in techs and ev['tech'] not in first:
                first[ev['tech']] = ev['year']
        for tch, y in first.items():
            out.append((y, Mo.TECH_JA[tch], 'new'))
        return sorted(out)
    C['034'] = timeline('群島の歴史：技術が生まれた年', tech_events('A1-2', ['hooks', 'nets', 'drying', 'dugout', 'outrigger', 'pottery', 'sail', 'horticulture', 'wayfinding']),
                        (0, 1250), color=ENTITY['A1-2'])
    C['040'] = presence_strip('小さな火山島の歴史：磨いた石の斧', 'R1-4', 'adze')
    C['071'] = timeline('大木の島の歴史', tech_events('R1-1', ['dugout', 'outrigger', 'sail', 'wayfinding']) + [(531, '96kmの海を渡る', 'new')], (0, 900), color=ENTITY['R1-1'])
    C['072'] = C['071']
    C['082'] = timeline('大きな島の歴史：技術が生まれた年', tech_events('C1-3', ['pottery', 'dugout', 'horticulture', 'outrigger', 'sail', 'wayfinding', 'copper']),
                        (0, 2000), color=ENTITY['C1-3'])
    # 数字のカット
    r11 = run(*FEAT['R1-1'])
    C['052'] = big_numbers('戻らなかった探検の舟', [('群島の歴史', fmt_int(sum(1 for e in run(*FEAT['A1-2'])['events'] if e['kind'] == 'voyage_lost')) + '回',
                                                 '3,000年のあいだ', ENTITY['A1-2'])])
    pv = lambda e: float(np.mean(ser(e, 'poor')[-100:]))
    lv = lambda e: float(np.mean(ser(e, 'leisure')[-100:]))
    C['077'] = big_numbers('最後の100年：暮らしに困る人の割合', [(ENTITY_JA['R1-1'], '%d%%' % round(pv('R1-1') * 100), '余暇 年%d日' % round(lv('R1-1')), ENTITY['R1-1']),
                                                               (ENTITY_JA['R1-4'], '%d%%' % round(pv('R1-4') * 100), '余暇 年%d日' % round(lv('R1-4')), ENTITY['R1-4'])])
    c3 = run(*FEAT['C1-3'])
    C['084'] = big_numbers('大きな島の歴史：3,000年後', [('人口', '約%s万人' % ('%.1f' % (c3['series']['pop'][-1] / 1e4)), '住む島は1つ', ENTITY['C1-3']),
                                                      ('余暇', '%d日' % round(lv('C1-3')), '大人1人・1年', ENTITY['C1-3']),
                                                      ('見つけた島', '%d' % sum(1 for e in c3['events'] if e['kind'] == 'island_found'), '移り住んだ島 0', ENTITY['C1-3'])])
    C['083'] = dots_by_terrain('3,000年後に人が住む島の数（5回ずつ）', isl_n, lambda v: fmt_int(v), (0, 80), [0, 20, 40, 60, 80], none_label='')
    # 追加検証
    def med_final(arm, tid):
        return float(np.median([run(tid, k, arm)['series']['pop'][-1] for k in range(5)]))
    C['096'] = big_numbers('遠く離れた小島の世界：3,000年後の人口（5回の中央値）', [('潮麦なし', fmt_int(med_final('main', 'R1')) + '人', '', None),
                                                                         ('潮麦あり', fmt_int(med_final('verify-tide', 'R1')) + '人', '', None)])
    rt4 = run('R1', 4, 'verify-tide')
    C['098'] = big_numbers('小さな火山島の歴史（潮麦あり）', [('人口', fmt_int(rt4['series']['pop'][-1]) + '人', 'なし：%s人' % fmt_int(p4[-1]), ENTITY['R1-4']),
                                                          ('住む島', '%d' % rt4['series']['islands'][-1], '出られないまま', ENTITY['R1-4']),
                                                          ('余暇', '%d日' % round(float(np.mean(rt4['series']['leisure'][-100:]))), 'なし：%d日' % round(lv('R1-4')), ENTITY['R1-4'])])
    # 岸の魚：浅瀬で潮麦を育てた歴史ごとに、育てなかった同じ歴史と比べる（最後の100年の平均）
    fd = []
    for t_ in TIDS:
        for k in range(5):
            a_ = run(t_, k, 'verify-tide')['series']
            if max(a_.get('tide_km2', [0])) <= 0:
                continue
            fd.append(float(np.mean(a_['fish'][-100:]) - np.mean(run(t_, k)['series']['fish'][-100:])))
    fd = np.asarray(fd)
    C['099'] = big_numbers('岸の魚の量：浅瀬で潮麦を育てた歴史', [('潮麦を育てた歴史', '%d' % len(fd), '40のうち', None),
                                                         ('岸の魚が減った', '%d' % int((fd <= -0.01).sum()), '変わらない %d・増えた %d' % (int((abs(fd) < 0.01).sum()), int((fd >= 0.01).sum())), None)],
                           sub='最後の100年の平均を、育てなかった同じ歴史と比べた（減り方の中央値 約%d％）' % round(-np.median(fd) * 100))
    C['100'] = bullets('軽殻石では、ほとんど変わらなかった', ['行き詰まった島に、軽殻石がない', '試す余暇がない', '隣の島が、舟の届く距離（約100km）より遠い'], tagk='計算')
    ratios = {}
    for t_ in TIDS:
        ratios[t_] = float(np.median([run(t_, k, 'verify-pop2000')['series']['pop'][-1] / max(run(t_, k)['series']['pop'][-1], 1) for k in range(5)]))

    def ratio_bars(t):
        img = canvas()
        d = ImageDraw.Draw(img)
        text(d, (150, 130), '最初の人数を2,000人にすると：3,000年後の人口の比（5回の中央値）', 44, TEXT, appear(t, 0.1), bold=True)
        x0, x1 = 780, 1640
        X = lambda v: x0 + v / 1.8 * (x1 - x0)
        lay = Layer()
        lay.line([(X(1.0), 240), (X(1.0), 960)], MUTED, 2, appear(t, 0.2))
        for i, t_ in enumerate(TIDS):
            y = 280 + i * 84
            a = appear(t, 0.4 + 0.35 * i)
            lay.rect((x0, y - 18, X(ratios[t_]), y + 18), FAMILY[t_[0]], a, radius=4)
        lay.onto(img)
        text(d, (X(1.0), 990), '1倍（変わらない）', 26, TEXT2, appear(t, 0.2), anchor='ma')
        for i, t_ in enumerate(TIDS):
            y = 280 + i * 84
            a = appear(t, 0.4 + 0.35 * i)
            text(d, (150, y), '%s %s' % (t_, W.TERRAINS[t_][1]), 30, TEXT, a, anchor='lm')
            text(d, (X(ratios[t_]) + 14, y), '%.2f倍' % ratios[t_], 30, TEXT, a, anchor='lm')
        tag(img, '計算', appear(t, 0.1))
        return img
    C['101'] = ratio_bars
    # 地図
    C['053'] = map_timelapse('A1-2', '群島の歴史：住む島が広がる', 0, 3000, margin=400)
    C['073'] = map_timelapse('R1-1', '大木の島の歴史：住む島が広がる', 500, 3000, margin=500)

    def still_map(ent, year, title, margin=500, arm='main', note=None, extra=None):
        tid, k = FEAT[ent]
        r = run(tid, k, arm)
        win = window_for(tid, k, years=(year,), margin=margin, arm=arm)
        base = map_image(tid, WW, win)

        def draw(t):
            img = canvas()
            img.paste(Image.blend(Image.new('RGB', base.size, BG), base, appear(t, 0.0, 0.8)), (0, (H - base.height) // 2))
            lay = Layer()
            groups_layer(lay, ent, tid, snap_at(r, year), win, 0, (H - base.height) // 2, WW, base.height, appear(t, 0.8))
            if extra:
                extra(lay, win, t, base.height)
            lay.onto(img)
            d = ImageDraw.Draw(img)
            d.rectangle([0, 0, WW, 130], fill=BG)
            text(d, (80, 66), title, 44, TEXT, 1.0, bold=True, anchor='lm')
            img = shade_bottom(img)
            d = ImageDraw.Draw(img)
            label_chip(img, (80, 1010), ENTITY_JA[ent] + '（' + ent + '）', ENTITY[ent])
            s = r['series']
            yy = min(year, len(s['pop']) - 1)
            text(d, (WW - 80, 1010), '%s年・人口 %s人・住む島 %d' % (fmt_int(year), fmt_int(s['pop'][yy]), s['islands'][yy]), 34, TEXT, 1.0, anchor='rm')
            if note:
                text(d, (WW / 2, 960), note, 32, TEXT, appear(t, 1.5), anchor='mm')
            tag(img, '計算', 1.0)
            return img
        return draw
    C['058'] = still_map('A1-2', 2990, '群島の歴史：3,000年後')
    C['028'] = still_map('R1-4', 0, '小さな火山島の歴史：最初の島（771km²）に5集団', margin=90)
    C['080'] = map_timelapse('C1-3', '大きな島の歴史：海岸に沿って広がる', 0, 3000, margin=600)
    C['050'] = still_map('A1-2', 320, '群島の歴史：314年、50kmの海を渡る', margin=300)
    C['203b'] = still_map('A1-2', 0, '群島の歴史：最初の島と、まわりの近い島々', margin=170)
    C['054'] = map_timelapse('A1-2', '群島の歴史：人と技術が島から島へ', 300, 1500, margin=400)

    def r14_extra(lay, win, t, hpx):
        tid, k = FEAT['R1-4']
        w = world(tid)
        r = run(tid, k)
        i0 = int(w['reg']['island'][r['start_regions'][0]])
        lat0, lon0 = w['lay']['lat'][i0], w['lay']['lon'][i0]
        cx, cy = project(win, WW, hpx, lat0, lon0)
        oy = (H - hpx) // 2
        km = WW / ((win[1] - win[0]) * 111.2 * math.cos(math.radians(lat0)))
        rr = (w['lay']['rho'][i0].mean() + 30) * km
        a = appear(t, 2.0)
        pts = [(float(cx) + rr * math.cos(q), float(cy) + oy + rr * math.sin(q)) for q in np.linspace(0, 2 * math.pi, 120)]
        lay.line(pts, (240, 239, 236), 3, a)
    C['075'] = still_map('R1-4', 1500, '小さな火山島の歴史：いかだの届く距離（約30km）', margin=250, extra=r14_extra,
                         note='いちばん近い島まで104km')

    def side_by_side(ents, years, title, arms=('main', 'main'), notes=('', '')):
        def draw(t):
            img = canvas()
            d = ImageDraw.Draw(img)
            text(d, (80, 90), title, 48, TEXT, appear(t, 0.1), bold=True)
            for i, (ent, yr, arm) in enumerate(zip(ents, years, arms)):
                tid, k = FEAT[ent]
                r = run(tid, k, arm)
                win = window_for(tid, k, years=(yr,), margin=120 if yr == 0 else 350, arm=arm)
                m = map_image(tid, 900, win)
                x0, y0 = 50 + i * 960, 200
                al = appear(t, 0.4 + 0.8 * i)
                img.paste(Image.blend(Image.new('RGB', m.size, BG), m, al), (x0, y0))
                lay = Layer()
                groups_layer(lay, ent, tid, snap_at(r, yr), win, x0, y0, 900, m.height, al, scale=1.3 if yr == 0 else 0.8)
                lay.onto(img)
                label_chip(img, (x0 + 10, y0 + m.height + 40), ENTITY_JA[ent], ENTITY[ent], al)
                s = r['series']
                yy = min(yr, len(s['pop']) - 1)
                text(d, (x0 + 10, y0 + m.height + 90), (notes[i] + '　' if notes[i] else '') + '人口 %s人・住む島 %d' % (fmt_int(s['pop'][yy]), s['islands'][yy]), 30, TEXT2, al)
            tag(img, '計算', appear(t, 0.1))
            return img
        return draw
    C['068'] = side_by_side(['R1-1', 'R1-4'], [0, 0], '同じ世界の、二つの歴史：始まりの場所')
    C['102'] = side_by_side(['R1-1', 'R1-1'], [2990, 2990], '大木の島の歴史：最初の人数を変えると（3,000年後）', arms=('main', 'verify-pop2000'),
                            notes=('1,000人で始める', '2,000人で始める'))

    def globe_view(t):
        img = canvas()
        r = run(*FEAT['A1-2'])
        c = window_for('A1', 2, years=(2990,), margin=0)
        lc = (c[0] + c[1]) / 2
        win = (lc - 180.0, lc + 180.0, -90.0, 90.0)
        m = map_image('A1', WW, win)
        img.paste(Image.blend(Image.new('RGB', m.size, BG), m, appear(t, 0.0, 1.0)), (0, (H - m.height) // 2))
        lay = Layer()
        groups_layer(lay, 'A1-2', 'A1', snap_at(r, 2990), win, 0, (H - m.height) // 2, WW, m.height, appear(t, 1.0), scale=0.5)
        lay.onto(img)
        d = ImageDraw.Draw(img)
        text(d, (80, 80), '地球全体で見た、群島の歴史（3,000年後）', 44, TEXT, 1.0, bold=True)
        text(d, (WW / 2, 1010), '人が住むのは、星のほんの一角', 36, TEXT, appear(t, 2.0), anchor='mm')
        tag(img, '計算', 1.0)
        return img
    C['065'] = globe_view
    # 舟の届く距離
    def ladder(t):
        img = canvas()
        d = ImageDraw.Draw(img)
        text(d, (150, 130), '舟の段階と届く距離（目盛りは10倍ごと）', 50, TEXT, appear(t, 0.1), bold=True)
        tiers = [('いかだ', 30), ('丸木舟', 40), ('浮き木つきの舟', 160), ('帆', 500), ('星と波の航法', 1500)]
        x0, x1 = 560, 1700
        X = lambda v: x0 + (math.log10(v) - 1) / (math.log10(2000) - 1) * (x1 - x0)
        lay = Layer()
        for v in (10, 100, 1000):
            lay.line([(X(v), 260), (X(v), 900)], GRID, 1, appear(t, 0.2))
        for i, (n, v) in enumerate(tiers):
            y = 320 + i * 120
            lay.rect((x0, y - 22, X(v), y + 22), ENTITY['A1-2'], appear(t, 0.5 + 1.0 * i), radius=4)
        lay.onto(img)
        for v in (10, 100, 1000):
            text(d, (X(v), 930), '%skm' % fmt_int(v), 26, TEXT2, appear(t, 0.2), anchor='ma')
        for i, (n, v) in enumerate(tiers):
            y = 320 + i * 120
            a = appear(t, 0.5 + 1.0 * i)
            text(d, (150, y), n, 38, TEXT, a, anchor='lm')
            text(d, (X(v) + 16, y), '%skm' % fmt_int(v), 34, TEXT, a, anchor='lm')
        tag(img, '設定', appear(t, 0.1))
        return img
    C['045'] = ladder
    C['046'] = bullets('島が見える距離', ['水平線までの距離は、目の高さと島の高さで決まる', '高さ500mの島なら、約96km先まで見える', '高い島は雲をかぶり、さらに遠くから分かる'],
                       tagk='事実', note='見通し距離 ＝ 3.57 ×（√目の高さ ＋ √島の高さ）km')
    # 40試行の一覧（小さな図を8つ）
    def overview(t):
        img = canvas()
        d = ImageDraw.Draw(img)
        text(d, (80, 70), '40の歴史：人口の推移（地形ごとに5回）', 44, TEXT, appear(t, 0.1), bold=True)
        for i, t_ in enumerate(TIDS):
            x0, y0 = 90 + (i % 4) * 450, 170 + (i // 4) * 440
            ax = Axes((x0 + 60, y0 + 50, x0 + 410, y0 + 340), (0, 2999), (200, 200000), log=True)
            ax.draw(img, [0, 3000], [1000, 100000], xfmt=lambda v: '%d年' % v, yfmt=lambda v: fmt_int(v), a=appear(t, 0.2 + 0.2 * i))
            text(d, (x0 + 60, y0 + 18), '%s %s' % (t_, W.TERRAINS[t_][1]), 26, TEXT, appear(t, 0.2 + 0.2 * i))
            lay = Layer()
            for k in range(5):
                ent = next((e for e, v in FEAT.items() if v == (t_, k)), None)
                ys = np.asarray(main[(t_, k)]['series']['pop'])
                pts = [(ax.X(j), ax.Y(max(ys[j], 1))) for j in range(0, 3000, 15)]
                lay.line(pts, ENTITY[ent] if ent else FAMILY[t_[0]], 4 if ent else 2, appear(t, 0.4 + 0.2 * i) * (1.0 if ent else 0.6))
            lay.onto(img)
        tag(img, '計算', appear(t, 0.1))
        return img
    C['086'] = overview

    def events_chart(t):
        img = canvas()
        d = ImageDraw.Draw(img)
        r = run(*FEAT['A1-2'])
        text(d, (150, 130), '群島の歴史：嵐（▲）とはやり病（●）と人口', 48, TEXT, appear(t, 0.1), bold=True)
        ax = Axes((230, 300, 1640, 900), (0, 1500), (500, 20000), log=True)
        ax.draw(img, [0, 500, 1000, 1500], [1000, 3000, 10000], xfmt=lambda v: '%s年' % fmt_int(v), yfmt=fmt_int, a=appear(t, 0.2))
        frac = ease(t / (0.7 * T_cur[0]))
        upto = int(frac * 1500)
        ys = np.asarray(r['series']['pop'])
        lay = Layer()
        lay.line([(ax.X(j), ax.Y(ys[j])) for j in range(0, max(2, upto), 3)], ENTITY['A1-2'], 4, 1.0)
        for e in r['events']:
            if e['year'] > upto:
                continue
            if e['kind'] == 'storm':
                x = ax.X(e['year'])
                lay.line([(x - 7, 280), (x, 266), (x + 7, 280), (x - 7, 280)], TEXT2, 3, 0.8)
            elif e['kind'] == 'epidemic' and e.get('deaths', 0) >= 20:
                lay.circle((ax.X(e['year']), 950), 6, TEXT2, 0.8)
        lay.onto(img)
        tag(img, '計算', appear(t, 0.1))
        return img
    C['037'] = events_chart

    def regrow(t):
        img = canvas()
        d = ImageDraw.Draw(img)
        text(d, (150, 150), '自然の量：とりすぎると減り、休めると戻る', 50, TEXT, appear(t, 0.1), bold=True)
        ax = Axes((230, 300, 1640, 880), (0, 100), (0, 1.1))
        ax.draw(img, [0, 50, 100], [0, 0.5, 1.0], xfmt=lambda v: '%d年' % v, yfmt=lambda v: '%.1f' % v, ylabel='量（手つかずを1）', a=appear(t, 0.2))
        S, ys = 1.0, []
        for y in range(101):
            h = 0.45 if 20 <= y < 50 else 0.05
            S = max(0.0, S + 0.35 * S * (1 - S) - h * S)
            ys.append(S)
        frac = ease(t / (0.75 * T_cur[0]))
        lay = Layer()
        lay.rect((ax.X(20), ax.y0, ax.X(50), ax.y1), (60, 40, 30), 0.35 * appear(t, 0.5), radius=0)
        lay.line([(ax.X(j), ax.Y(ys[j])) for j in range(0, max(2, int(frac * 100)))], ENTITY['A1-2'], 4, 1.0)
        lay.onto(img)
        text(d, (ax.X(35), ax.y0 + 30), 'とりすぎた30年', 30, TEXT2, appear(t, 0.5), anchor='mm')
        tag(img, '設定', appear(t, 0.1))
        return img
    C['026'] = regrow
    two_histories(C)
    return C


# ---------------------------------------------------------------- 第3版：二つの歴史（群島の歴史 A1-2 と 小さな火山島の歴史 R1-4）

A_, R_ = 'A1-2', 'R1-4'


def composite_scores():
    """40の歴史の「変わり方」：6つの物差し（人口の増え方・住む島・技術・舟の届く距離・余暇の変化・貧しさの減り方）の標準得点の合計"""
    rows = []
    for t_ in TIDS:
        for k in range(5):
            s = run(t_, k)['series']
            pop = np.asarray(s['pop'])
            rows.append(('%s-%d' % (t_, k), [math.log10(max(pop[-1], 1) / pop[0]), math.log10(max(s['islands'][-1], 1)),
                                             float(np.mean(s['techs'][-100:]) - np.mean(s['techs'][:10])),
                                             math.log10(max(float(np.mean(s['range_km'][-100:])), 1)),
                                             float(np.mean(s['leisure'][-100:]) - np.mean(s['leisure'][:100])),
                                             float(np.mean(s['poor'][:100]) - np.mean(s['poor'][-100:]))]))
    F = np.array([r[1] for r in rows])
    Z = ((F - F.mean(0)) / np.where(F.std(0) > 0, F.std(0), 1)).sum(1)
    return {r[0]: float(z) for r, z in zip(rows, Z)}


def score_strip(title, emphasis='ends'):
    """40の歴史を変わり方で並べ、二つの歴史に名前を付ける。emphasis='between' では、あいだの38を囲む"""
    sc = composite_scores()
    ids = sorted(sc, key=sc.get)
    x0, x1, y = 200, 1720, 600
    lo, hi = sc[ids[0]], sc[ids[-1]]
    X = lambda v: x0 + (v - lo) / (hi - lo) * (x1 - x0)
    items = ['人口の増え方', '住む島の数', '技術の数', '舟の届く距離', '暮らしの余裕', '貧しさの減り方']

    def draw(t):
        img = canvas()
        d = ImageDraw.Draw(img)
        text(d, (150, 130), title, 50, TEXT, appear(t, 0.1), bold=True)
        for i, it in enumerate(items):
            a = appear(t, 0.4 + 0.25 * i)
            text(d, (150 + i * 270, 250), it, 30, TEXT2, a)
        lay = Layer()
        lay.line([(x0, y), (x1, y)], MUTED, 2, appear(t, 1.8))
        for k, hid in enumerate(ids):
            a = appear(t, 2.0 + 0.04 * k)
            special = hid in (A_, R_)
            col = ENTITY[hid] if special else (110, 120, 132)
            lay.circle((X(sc[hid]), y), 16 if special else 10, col, a, outline=BG, ow=2)
        if emphasis == 'between':
            a = appear(t, 1.0)
            xa, xb = X(sc[ids[1]]) - 14, X(sc[ids[-2]]) + 14
            lay.line([(xa, y + 110), (xa, y + 126), (xb, y + 126), (xb, y + 110)], TEXT2, 3, a)
        lay.onto(img)
        a = appear(t, 2.0 + 0.04 * len(ids) + 0.3)
        text(d, (x0, y + 60), '変わらなかった', 28, MUTED, appear(t, 1.8), anchor='la')
        text(d, (x1, y + 60), '大きく変わった', 28, MUTED, appear(t, 1.8), anchor='ra')
        for hid, anc in ((A_, 'rd'), (R_, 'ld')):
            xx = X(sc[hid])
            text(d, (xx, y - 40), ENTITY_JA[hid], 36, TEXT, a, bold=True, anchor=anc)
            text(d, (xx, y - 84), '40の歴史のうち %s' % ('1番目' if hid == A_ else '40番目'), 26, TEXT2, a, anchor=anc)
        if emphasis == 'between':
            text(d, ((x0 + x1) / 2, y + 146), 'ほかの38の歴史は、このあいだ', 34, TEXT, appear(t, 1.2), anchor='ma')
        text(d, (150, H - 60), '6つの物差しそれぞれで40の歴史の中の位置（標準得点）を出し、足し合わせた', 26, MUTED, appear(t, 1.0), anchor='ls')
        tag(img, '計算', appear(t, 0.1))
        return img
    return draw


def two_islands(title):
    """二つの歴史の始まりの島を、同じ縮尺で並べる"""
    half_km = 170.0
    wins = {}
    for ent in (A_, R_):
        tid, k = FEAT[ent]
        r = run(tid, k)
        w = world(tid)
        isl = int(w['reg']['island'][r['start_regions'][0]])
        lat0, lon0 = w['lay']['lat'][isl], w['lay']['lon'][isl]
        dlat = half_km * 0.6 / 111.2
        dlon = half_km / (111.2 * math.cos(math.radians(lat0)))
        wins[ent] = (lon0 - dlon, lon0 + dlon, lat0 - dlat, lat0 + dlat)
    info = {A_: ('近接した群島の世界', '最初の島 12,121km²・いちばん近い島 26km'), R_: ('遠く離れた小島の世界', '最初の島 771km²・いちばん近い島 104km')}

    def draw(t):
        img = canvas()
        d = ImageDraw.Draw(img)
        text(d, (80, 90), title, 46, TEXT, appear(t, 0.1), bold=True)
        for i, ent in enumerate((A_, R_)):
            tid, k = FEAT[ent]
            win = wins[ent]
            m = map_image(tid, 900, win)
            x0, y0 = 50 + i * 960, 210
            al = appear(t, 0.4 + 1.2 * i)
            img.paste(Image.blend(Image.new('RGB', m.size, BG), m, al), (x0, y0))
            lay = Layer()
            groups_layer(lay, ent, tid, snap_at(run(tid, k), 0), win, x0, y0, 900, m.height, al, scale=1.0)
            # 100km の物差し
            px = 900 * 100 / (2 * half_km)
            lay.line([(x0 + 30, y0 + m.height - 30), (x0 + 30 + px, y0 + m.height - 30)], TEXT, 4, al)
            lay.onto(img)
            text(d, (x0 + 30 + px / 2, y0 + m.height - 44), '100km', 24, TEXT, al, anchor='md')
            label_chip(img, (x0 + 14, y0 + m.height + 44), ENTITY_JA[ent], ENTITY[ent], al, size=36)
            text(d, (x0 + 14, y0 + m.height + 96), info[ent][0], 28, TEXT2, al)
            text(d, (x0 + 14, y0 + m.height + 140), info[ent][1], 28, TEXT2, al)
        tag(img, '計算', appear(t, 0.1))
        return img
    return draw


def compare_table(title, rows_, tagk='計算', note=None):
    """二つの歴史を表で並べる。rows_：(項目, 群島の値, 小さな火山島の値)"""
    def draw(t):
        img = canvas()
        d = ImageDraw.Draw(img)
        text(d, (150, 120), title, 48, TEXT, appear(t, 0.1), bold=True)
        cx = {A_: 1000, R_: 1480}
        for ent in (A_, R_):
            label_chip(img, (cx[ent] - 170, 250), ENTITY_JA[ent], ENTITY[ent], appear(t, 0.3), size=32)
        lay = Layer()
        step = 92 if len(rows_) <= 5 else 78     # 下の方は字幕の場所なので、行が多い表は詰める
        for i in range(len(rows_)):
            yy = 320 + i * step
            lay.line([(150, yy + step - 18), (1770, yy + step - 18)], GRID, 1, appear(t, 0.6 + 0.6 * i))
        lay.onto(img)
        for i, (lab, va, vr) in enumerate(rows_):
            yy = 320 + i * step
            a = appear(t, 0.6 + 0.6 * i)
            text(d, (150, yy + 34), lab, 34, TEXT2, a, anchor='lm')
            for ent, v in ((A_, va), (R_, vr)):
                main_, sub_ = (v, None) if isinstance(v, str) else v   # （大きい数字, 小さい添え書き）
                if sub_:
                    text(d, (cx[ent], yy + 22), main_, 40, TEXT, a, bold=True, anchor='mm')
                    text(d, (cx[ent], yy + 58), sub_, 24, TEXT2, a, anchor='mm')
                else:
                    text(d, (cx[ent], yy + 34), main_, 42, TEXT, a, bold=True, anchor='mm')
        if note:
            text(d, (150, H - 50), note, 26, MUTED, appear(t, 0.6 + 0.6 * len(rows_)), anchor='ls')
        tag(img, tagk, appear(t, 0.1))
        return img
    return draw


def two_histories(C):
    ra, rr = run(*FEAT[A_]), run(*FEAT[R_])
    sa, sr = ra['series'], rr['series']
    last = lambda s, k: float(np.mean(s[k][-100:]))
    e0 = lambda r: metrics.life_expectancy(r['deaths_age'], r['pop_age'], 2500, 3000)
    C['202'] = score_strip('40の歴史を「どれだけ変わったか」で並べる')
    C['206'] = score_strip('40の歴史の変わり方', emphasis='between')
    C['203'] = two_islands('二つの歴史の始まりの島（同じ縮尺）')
    C['204'] = compare_table('3,000年後', [
        ('人口', '%s人' % fmt_int(sa['pop'][-1]), '%s人' % fmt_int(sr['pop'][-1])),
        ('住む島', '%d' % sa['islands'][-1], '%d' % sr['islands'][-1]),
        ('使える技術', '%d' % round(last(sa, 'techs')), '%d' % round(last(sr, 'techs'))),
        ('舟の届く距離', '%skm' % fmt_int(round(last(sa, 'range_km'), -1)), 'いかだ %dkm' % round(last(sr, 'range_km'))),
        ('余暇（大人1人・1年）', '%d日' % round(last(sa, 'leisure')), '%d日' % round(last(sr, 'leisure'))),
        ('暮らしに困る人', '%d%%' % round(100 * last(sa, 'poor')), '%d%%' % round(100 * last(sr, 'poor'))),
        ('平均寿命', '%d歳' % round(e0(ra)), '%d歳' % round(e0(rr))),
    ], note='余暇・暮らしに困る人は最後の100年の平均、平均寿命は最後の500年の年齢別の死亡率から')
    C['205'] = compare_table('分かれ目になったもの', [
        ('いちばん近い島', '26km（50km先にも）', '104km'),
        ('届く舟', '浮き木の舟 160km（284年〜）', 'いかだ 30km'),
        ('育てられる植物', '芋・果樹（4年目に見つける）', 'なし'),
        ('舟にする大木', 'たくさん', '群島の100分の1以下'),
        ('余暇（大人1人・1年）', '100日以上', 'ほとんどなし'),
    ], note='舟の届く距離は、この計算で決めた値（いかだ30km・丸木舟40km・浮き木の舟160km・帆500km）')
    pa, pr = np.asarray(sa['pop'], float), np.asarray(sr['pop'], float)
    C['207'] = lines_chart('二つの歴史の人口（目盛りは10倍ごと）', [(pa, ENTITY[A_], ENTITY_JA[A_], 4, 1.0), (pr, ENTITY[R_], ENTITY_JA[R_], 4, 1.0)],
                           (0, 2999), (200, 200000), log=True, xticks=[0, 1000, 2000, 3000], yticks=[300, 1000, 10000, 100000], ylabel='人口')
    sm = lambda v, k=25: np.convolve(np.pad(np.asarray(v, float), (k, k), mode='edge'), np.ones(2 * k + 1) / (2 * k + 1), 'valid')
    rt = run('R1', 4, 'verify-tide')['series']
    C['209'] = lines_chart('小さな火山島の歴史：岸の魚の量（手つかずを1）', [(sm(sr['fish']), (110, 120, 132), '潮麦なし', 3, 1.0), (sm(rt['fish']), ENTITY[R_], '潮麦あり', 4, 1.0)],
                           (0, 2999), (0.4, 1.05), xticks=[0, 1000, 2000, 3000], yticks=[0.4, 0.6, 0.8, 1.0], yfmt=lambda v: '%.1f' % v, ylabel='25年の平均',
                           notes=[(4.0, '潮麦あり＝はじめから潮麦がある世界（ほかの規則・地形・始まりの場所は同じ）')])
    ta, tr = run('A1', 2, 'verify-tide')['series'], rt
    C['211'] = compare_table('はじめから潮麦があったら：3,000年後', [
        ('人口', ('%s人' % fmt_int(ta['pop'][-1]), '潮麦なし %s人' % fmt_int(sa['pop'][-1])), ('%s人' % fmt_int(tr['pop'][-1]), '潮麦なし %s人' % fmt_int(sr['pop'][-1]))),
        ('住む島', ('%d' % ta['islands'][-1], '潮麦なし %d' % sa['islands'][-1]), ('%d' % tr['islands'][-1], '潮麦なし %d' % sr['islands'][-1])),
        ('余暇（大人1人・1年）', '%d日' % round(last(ta, 'leisure')), '%d日' % round(last(tr, 'leisure'))),
        ('暮らしに困る人', '%d%%' % round(100 * last(ta, 'poor')), '%d%%' % round(100 * last(tr, 'poor'))),
    ], tagk='架空', note='潮麦は架空の植物（はじめからある世界）。ほかの規則・地形・始まりの場所は同じ')
    pa2, pr2 = run('A1', 2, 'verify-pop2000')['series'], run('R1', 4, 'verify-pop2000')['series']
    C['210'] = compare_table('2,000人で始めると：3,000年後', [
        ('人口', ('%s人' % fmt_int(pa2['pop'][-1]), '1,000人だと %s人' % fmt_int(sa['pop'][-1])), ('%s人' % fmt_int(pr2['pop'][-1]), '1,000人だと %s人' % fmt_int(sr['pop'][-1]))),
        ('住む島', ('%d' % pa2['islands'][-1], '1,000人だと %d' % sa['islands'][-1]), ('%d' % pr2['islands'][-1], '1,000人だと %d' % sr['islands'][-1])),
        ('余暇（大人1人・1年）', ('%d日' % round(last(pa2, 'leisure')), '1,000人だと %d日' % round(last(sa, 'leisure'))), ('%d日' % round(last(pr2, 'leisure')), '1,000人だと %d日' % round(last(sr, 'leisure')))),
    ], tagk='設定', note='最初の人数だけを変えた（地形・始まりの場所・規則は同じ）')


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    still = '--still' in sys.argv
    os.makedirs(OUT, exist_ok=True)
    secs = seconds_of()
    C = build_cuts()
    ids = args or sorted(C)
    for cid in ids:
        if cid not in C:
            print('なし', cid)
            continue
        if '--skip' in sys.argv and not still and os.path.exists(os.path.join(OUT, 'cut%s.mp4' % cid)):
            continue
        T = secs.get(cid, 10)
        T_cur[0] = T
        if still:
            img = C[cid](T - 0.01)
            img.save(os.path.join(OUT, 'cut%s.png' % cid))
        else:
            write_video(os.path.join(OUT, 'cut%s.mp4' % cid), T, C[cid])
        print('cut', cid, T, 's', flush=True)


if __name__ == '__main__':
    main()
