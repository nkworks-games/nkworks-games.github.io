"""並行地球 第1回：字幕（数字は算用数字）と「いまどの歴史の、何年目か」の表示を作る

  python3 make_overlays.py

作るもの
  out/script/subtitles_ep1.csv   カットごとの字幕（ナレーションの漢数字を算用数字に。読み上げ用の原稿はそのまま）
  out/script/ep1_subtitles.srt   編集ソフトに読み込める字幕（カット表の時間で）
  out/overlay/hudNNN.png         左上に重ねる表示（透明な 1920×1080）。どの歴史・どの世界・何年目（3,000年の帯）・人口・住む島
                                 3D のカットのうち、特定の歴史を映すものに付ける（図・地図は画面の中に書いてあるので付けない）

数字（人口・住む島）は計算の記録から読む。年は、ナレーションで言っている年（カット表の「出どころ」）に合わせる。
"""
import csv
import gzip
import json
import os
import pickle
import re

from PIL import Image, ImageDraw

import world as W
from motion import BG, ENTITY, ENTITY_JA, FAMILY, H, MUTED, TEXT, TEXT2, W as WW, Layer, blend, font

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_HUD = os.path.join(HERE, 'out', 'overlay')
ARM_JA = {'main': '', 'verify-tide': '潮麦あり（追加検証）', 'verify-stone': '軽殻石あり（追加検証）', 'verify-pop2000': '2,000人で始める（追加検証）'}

# ---------------------------------------------------------------- 漢数字 → 算用数字（字幕用）

D = {'〇': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
U = {'十': 10, '百': 100, '千': 1000}
KAN = '〇一二三四五六七八九十百千万'



def cut_table():
    """いまのカット表（第3版があればそれ）"""
    for name in ('cuts_v3.csv', 'cuts_v2.csv'):
        p = os.path.join(HERE, 'out', 'script', name)
        if os.path.exists(p):
            return p
    raise FileNotFoundError('カット表がない')


def kan2int(s):
    total, sect, num = 0, 0, 0
    for ch in s:
        if ch in D:
            num = D[ch]
        elif ch in U:
            sect += (num or 1) * U[ch]
            num = 0
        elif ch == '万':
            total += (sect + num) * 10000
            sect, num = 0, 0
    return total + sect + num


def fmt(n, unit_next):
    if unit_next.startswith('年'):
        return format(n, ',')
    if n >= 10000 and n % 10000 == 0:
        return '%d万' % (n // 10000)
    return format(n, ',')


KEEP_AFTER_ONE = '方段気角度緒つ'   # 一方・一段・一気・一角・一度・一緒・一つ は言葉のまま


def to_display(s):
    """ナレーションの漢数字を、字幕用の算用数字にする（言葉として使う「一」などはそのまま）"""
    s = s.replace('一年、また一年', '\x00')
    # 小数（〇・一、一・五）
    s = re.sub(r'([〇一二三四五六七八九])・([〇一二三四五六七八九])', lambda m: '%d.%d' % (D[m.group(1)], D[m.group(2)]), s)
    out, i = [], 0
    while i < len(s):
        if s[i] in KAN:
            j = i
            while j < len(s) and s[j] in KAN:
                j += 1
            seq, nxt, prev = s[i:j], s[j:j + 2], s[i - 1] if i else ''
            word_juubun = seq == '十' and nxt[:1] == '分' and s[j + 1:j + 2] != 'の'   # 「十分（じゅうぶん）」は言葉のまま（三分の二などは数）
            if prev == '数' or (seq == '一' and nxt[:1] in KEEP_AFTER_ONE) or seq == '万' or word_juubun:
                out.append(seq)
            else:
                out.append(fmt(kan2int(seq), nxt))
            i = j
        else:
            out.append(s[i])
            i += 1
    s = ''.join(out).replace('\x00', '一年、また一年')
    s = re.sub(r'(\d)\s*平方キロメートル', r'\1km²', s)
    s = re.sub(r'(\d|万)\s*平方キロメートル', r'\1km²', s)
    s = re.sub(r'(\d)キロ', r'\1km', s)
    s = re.sub(r'(\d)パーセント', r'\1％', s)
    return s


# ---------------------------------------------------------------- どの歴史・何年目

def run(tid, k, arm='main'):
    with gzip.open(os.path.join(HERE, 'out', arm, '%s-%d.pkl.gz' % (tid, k))) as f:
        return pickle.load(f)


def parse_year(src):
    m = re.search(r'([\d,]+)年', src)
    return int(m.group(1).replace(',', '')) if m else None


def hud_spec(row, shot):
    """カットに付ける表示の中身。付けないカットは None"""
    if not row['kind'].startswith('3D'):
        return None
    src = row['source']
    rec = (shot or {}).get('record', '')
    ents = re.findall(r'([CASR][12])-(\d)', src) or re.findall(r'([CASR][12])-(\d)', rec)
    if not ents:
        m = re.match(r'([CASR][12])・全球', src)
        if m:   # その世界の星の全景
            tid = m.group(1)
            return dict(name='%sの世界' % W.TERRAINS[tid][0], sub='%s（%s）・惑星の全体' % (W.TERRAINS[tid][1], tid), color=FAMILY[tid[0]])
        return None
    tid, k = ents[0][0], int(ents[0][1])     # 「R1-4」の 4 は 0 から数えた番号（R1-4 ＝ R1 の5回目）
    arm = 'main'
    m = re.search(r'（(verify-[a-z0-9]+|main)）', rec)
    if m:
        arm = m.group(1)
    if '潮麦あり' in src:
        arm = 'verify-tide'
    year = parse_year(src)
    approx = 'ごろ' in src or '〜' in src
    if year is None:
        year = parse_year(rec)
    ent = '%s-%d' % (tid, k)
    name = ENTITY_JA.get(ent, '%sの世界・%d回目の歴史' % (W.TERRAINS[tid][0], k + 1))
    sub = '%sの世界（%s）・5回のうち%d回目' % (W.TERRAINS[tid][0], tid, k + 1)
    if ARM_JA.get(arm):
        sub += '・' + ARM_JA[arm]
    spec = dict(name=name, sub=sub, color=ENTITY.get(ent, FAMILY[tid[0]]), year=year, approx=approx)
    if year is not None:
        r = run(tid, k, arm)
        y = min(max(year, 0), len(r['series']['pop']) - 1)
        spec['pop'] = int(r['series']['pop'][y])
        spec['islands'] = int(r['series']['islands'][y])
    return spec


def draw_hud(spec):
    img = Image.new('RGBA', (WW, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0, y0 = 44, 40
    w = max(640, int(d.textlength(spec['sub'], font=font(22))) + 56)
    h = 100 if spec.get('year') is None else 222
    pane = Image.new('RGBA', (w, h), BG + (170,))
    img.paste(pane, (x0, y0), pane)
    lay = Layer()
    lay.circle((x0 + 30, y0 + 34), 11, spec['color'], 1.0)
    if spec.get('year') is not None:
        bx0, bx1, by = x0 + 24, x0 + w - 24, y0 + 152
        lay.rect((bx0, by - 3, bx1, by + 3), MUTED, 0.6, radius=3)
        fx = bx0 + (bx1 - bx0) * min(spec['year'], 3000) / 3000
        lay.rect((bx0, by - 3, fx, by + 3), spec['color'], 1.0, radius=3)
        lay.circle((fx, by), 8, spec['color'], 1.0, outline=TEXT, ow=2)
    small = Image.new('RGBA', (WW * 2, H * 2), (0, 0, 0, 0))
    small.paste(lay.img, (0, 0))
    ov = small.reduce(2)
    img.alpha_composite(ov)
    d = ImageDraw.Draw(img)
    d.text((x0 + 52, y0 + 34), spec['name'], font=font(34, True), fill=TEXT + (255,), anchor='lm')
    d.text((x0 + 24, y0 + 66), spec['sub'], font=font(22), fill=TEXT2 + (255,), anchor='lt')
    if spec.get('year') is not None:
        yr = '%s年%s' % (format(spec['year'], ','), 'ごろ' if spec.get('approx') else '')
        d.text((x0 + 24, y0 + 136), yr + '　（始まりから）', font=font(30, True), fill=TEXT + (255,), anchor='ls')
        d.text((x0 + w - 24, y0 + 136), '3,000年', font=font(20), fill=MUTED + (255,), anchor='rs')
        if 'pop' in spec:
            d.text((x0 + 24, y0 + 200), '人口 %s人　住む島 %d' % (format(spec['pop'], ','), spec['islands']),
                   font=font(26), fill=TEXT2 + (255,), anchor='ls')
    return img


def srt_time(t):
    ms = int(round(t * 1000))
    return '%02d:%02d:%02d,%03d' % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def main():
    rows = list(csv.DictReader(open(cut_table(), encoding='utf-8')))
    shots = {s['id']: s for s in json.load(open(os.path.join(HERE, '..', '_blender', 'shots', 'ep1.json'), encoding='utf-8'))['shots']}
    os.makedirs(OUT_HUD, exist_ok=True)
    subs, srt, t, n = [], [], 0.0, 0
    huds = 0
    for r in rows:
        sec = int(r['sec'])
        disp = to_display(r['narration'].strip())
        subs.append(dict(no=r['no'], start=round(t, 2), end=round(t + sec, 2), narration=r['narration'].strip(), subtitle=disp))
        if disp:
            n += 1
            srt.append('%d\n%s --> %s\n%s\n' % (n, srt_time(t + 0.3), srt_time(t + sec - 0.2), disp))
        spec = hud_spec(r, shots.get(r['no']))
        p = os.path.join(OUT_HUD, 'hud%s.png' % r['no'])
        if spec:
            draw_hud(spec).save(p)
            huds += 1
        elif os.path.exists(p):
            os.remove(p)
        t += sec
    with open(os.path.join(HERE, 'out', 'script', 'subtitles_ep1.csv'), 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['no', 'start', 'end', 'narration', 'subtitle'])
        w.writeheader()
        w.writerows(subs)
    open(os.path.join(HERE, 'out', 'script', 'ep1_subtitles.srt'), 'w', encoding='utf-8').write('\n'.join(srt))
    print('字幕 %d・表示 %d カット' % (n, huds))


if __name__ == '__main__':
    main()
