# 低画質で失礼します：6面の地図データを作り、teigashitsu/index.html の STAGES の行を書きかえる。
#   python3 .github/scripts/teigashitsu_stages.py          … 作って書きこむ（作者の最少回数も計算）
#   python3 .github/scripts/teigashitsu_stages.py --check  … 書きこまずに、各面の最少回数だけ表示
# 地図は smartnews-smri/japan-topography（国土数値情報 行政区域データを1%に簡素化）の県別GeoJSON。
# 初回は ~/.cache/teigashitsu に取ってくる。必要なもの：Python3, numpy, Pillow
import json, math, os, sys, base64, collections, urllib.request
import numpy as np
from PIL import Image, ImageDraw

W, H, FS = 144, 96, (1, 4, 8)   # くっきりのマス数と、段階ごとのマスの大きさ（index.html の CONFIG と同じにする）
CACHE = os.path.expanduser('~/.cache/teigashitsu')
URL = 'https://raw.githubusercontent.com/smartnews-smri/japan-topography/main/data/municipality/geojson/s0010/N03-21_{}_210101.json'
HTML = os.path.join(os.path.dirname(__file__), '..', '..', 'teigashitsu', 'index.html')

def sh(lon0, lat0, w, dx, dy):  # 範囲をマス単位でずらす（ずらすと、粗い段階の形が変わる）
    cell = w / W; kx = 111.32 * math.cos(math.radians(lat0)); ky = 110.57
    return lon0 + dx * cell / kx, lat0 + dy * cell / ky

# 面：中心（経度・緯度）、横幅km、スタート・旗・出口は (行, 列) のマス。並び順＝面の順
ST = [
 dict(id='kanmon', name='関門海峡', sub='本州と九州のあいだ', prefs=['35', '40'], c=(130.95, 33.93), w=60, start=(38, 68), flags=[(55, 74), (72, 28), (84, 74)], exit=(88, 44)),
 dict(id='matsushima', name='松島湾', sub='湾に浮かぶ島々', prefs=['04'], c=(141.12, 38.36), w=30, start=(28, 104), flags=[(57, 15), (26, 59), (59, 73)], exit=(7, 45)),
 dict(id='kujuku', name='九十九島', sub='入り組んだ海岸', prefs=['42'], c=sh(129.67, 33.2, 25, -3, -3), w=25, start=(25, 132), flags=[(44, 66), (71, 132), (41, 36)], exit=(48, 126)),
 dict(id='amakusa', name='天草', sub='島から島へ', prefs=['43', '42'], c=sh(130.25, 32.45, 60, -1, -1), w=60, start=(39, 92), flags=[(66, 34), (66, 65), (26, 20)], exit=(57, 92)),
 dict(id='omura', name='大村湾', sub='細い瀬戸の先へ', prefs=['42'], c=(129.8, 33.0), w=40, start=(63, 64), flags=[(51, 42), (73, 9), (21, 100)], exit=(15, 42)),
 dict(id='shimanami', name='しまなみ', sub='芸予の島めぐり', prefs=['34', '38', '37', '33'], c=sh(133.05, 34.28, 30, 0, 4), w=30, start=(44, 107), flags=[(62, 82), (15, 98), (34, 85)], exit=(65, 110)),
]

_polys = {}
def polys(pref):
    if pref not in _polys:
        os.makedirs(CACHE, exist_ok=True); f = os.path.join(CACHE, f'N03_{pref}.json')
        if not os.path.exists(f): urllib.request.urlretrieve(URL.format(pref), f)
        L = []
        for ft in json.load(open(f))['features']:
            g = ft['geometry']; L += g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
        _polys[pref] = L
    return _polys[pref]

def raster(prefs, lon0, lat0, wkm, SS=8):  # マスごとの陸の割合（0〜1）
    hkm = wkm * H / W; kx = 111.32 * math.cos(math.radians(lat0)); ky = 110.57
    img = Image.new('L', (W * SS, H * SS), 0); dr = ImageDraw.Draw(img)
    tf = lambda c: (((c[0] - lon0) * kx / wkm + 0.5) * W * SS, (0.5 - (c[1] - lat0) * ky / hkm) * H * SS)
    for p in prefs:
        for P in polys(p):
            ext = [tf(c) for c in P[0]]; xs = [q[0] for q in ext]; ys = [q[1] for q in ext]
            if max(xs) < 0 or min(xs) > W * SS or max(ys) < 0 or min(ys) > H * SS: continue
            dr.polygon(ext, fill=255)
            for hole in P[1:]: dr.polygon([tf(c) for c in hole], fill=0)
    return (np.asarray(img, dtype=np.float32) / 255).reshape(H, SS, W, SS).mean(axis=(1, 3))

def level(cov, f):  # 粗い段階：ブロックの半分以上が陸なら陸
    out = np.zeros((H, W), bool)
    for by in range(0, H, f):
        for bx in range(0, W, f): out[by:by + f, bx:bx + f] = cov[by:by + f, bx:bx + f].mean() >= 0.5
    return out

def comps(m):  # 上下左右でつながった陸に番号
    lab = -np.ones((H, W), int); n = 0
    for y in range(H):
        for x in range(W):
            if m[y, x] and lab[y, x] < 0:
                q = [(y, x)]; lab[y, x] = n
                while q:
                    cy, cx = q.pop()
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < H and 0 <= nx < W and m[ny, nx] and lab[ny, nx] < 0: lab[ny, nx] = n; q.append((ny, nx))
                n += 1
    return lab

class Stage:
    def __init__(s, cov):
        s.M = [cov >= 0.5 if f == 1 else level(cov, f) for f in FS]; s.L = [comps(m) for m in s.M]
        s.trans = {}
        for a in range(3):
            for b in range(3):
                if a == b: continue
                ok = (s.L[a] >= 0) & (s.L[b] >= 0); d = collections.defaultdict(set)
                for p, q in set(zip(s.L[a][ok].tolist(), s.L[b][ok].tolist())): d[p].add(q)
                s.trans[(a, b)] = d
    def solve(s, start, flags, exit, allowed=(0, 1, 2)):
        """最少の切替回数（旗は くっきり の時だけ取れる。切替は足もとが陸の時だけ）。解けなければ None"""
        full = (1 << len(flags)) - 1
        def grab(lv, c, mask):
            if lv == 0:
                for i, f in enumerate(flags):
                    if s.L[0][f] == c: mask |= 1 << i
            return mask
        c0 = s.L[0][start]; st = (0, c0, grab(0, c0, 0)); dist = {st: 0}; dq = collections.deque([st])
        while dq:
            cur = dq.popleft(); lv, c, mask = cur
            if mask == full and s.L[lv][exit] == c: return dist[cur]
            for nl in allowed:
                if nl == lv: continue
                for nc in s.trans[(lv, nl)].get(c, ()):
                    ns = (nl, nc, grab(nl, nc, mask))
                    if ns not in dist: dist[ns] = dist[cur] + 1; dq.append(ns)
        return None

def b64(m): return base64.b64encode(np.packbits(m.astype(np.uint8).ravel()).tobytes()).decode()

if __name__ == '__main__':
    out = []
    for s in ST:
        g = Stage(raster(s['prefs'], s['c'][0], s['c'][1], s['w']))
        o = g.solve(s['start'], s['flags'], s['exit'])
        o01 = g.solve(s['start'], s['flags'], s['exit'], allowed=(0, 1)); o02 = g.solve(s['start'], s['flags'], s['exit'], allowed=(0, 2))
        print(f"{s['id']:11s} 最少 {o}  ざっくりなし {o01}  カクカクなし {o02}")
        assert o is not None, s['id'] + ' が解けない'
        out.append(dict(id=s['id'], name=s['name'], sub=s['sub'], km=s['w'], best=o, start=s['start'][::-1],
                        flags=[f[::-1] for f in s['flags']], exit=s['exit'][::-1], m=[b64(m[::f, ::f]) for m, f in zip(g.M, FS)]))
    if '--check' in sys.argv: sys.exit()
    lines = open(HTML, encoding='utf-8').read().split('\n'); k = [i for i, l in enumerate(lines) if l.startswith('const STAGES = ')]
    assert len(k) == 1
    lines[k[0]] = 'const STAGES = ' + json.dumps(out, ensure_ascii=False, separators=(',', ':')) + ';'
    open(HTML, 'w', encoding='utf-8').write('\n'.join(lines)); print('書きこみました：', HTML)
