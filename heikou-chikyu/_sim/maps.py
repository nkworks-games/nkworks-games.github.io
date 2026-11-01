"""並行地球：地図の画像（正距円筒図法）。確認用と、動画の地図の下地に使う"""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import world as W

OCEAN_DEEP = np.array([10, 28, 52])
OCEAN_MID = np.array([16, 52, 88])
SHALLOW = np.array([40, 120, 140])


def land_color(T, P, h, kind):
    if T < -2:
        return np.array([225, 230, 236])
    if T < 4:
        base = np.array([120, 124, 112])
    elif P < 600:
        base = np.array([168, 146, 100])
    elif T > 20:
        base = np.array([46, 96, 44])
    else:
        base = np.array([70, 110, 58])
    if kind == 'coral':
        base = np.array([200, 190, 150])
    return np.clip(base + min(60, h / 40), 0, 255)


def render(world, width=1440, halo_km=35.0, window=None):
    """地図（正距円筒図法）。window=(西経度, 東経度, 南緯度, 北緯度) で一部だけ拡大できる"""
    lon_a, lon_b, lat_a, lat_b = window or (-180.0, 180.0, -90.0, 90.0)
    res = (lon_b - lon_a) / width
    H = int(round((lat_b - lat_a) / res))
    img = np.zeros((H, width, 3), np.float32)
    lat_c = lat_b - (np.arange(H) + 0.5) * res
    shade = (np.abs(lat_c)[:, None, None] / 90.0)
    img[:] = OCEAN_MID * (1 - shade) + OCEAN_DEEP * shade
    lay, props = world['lay'], world['props']
    full = window is None
    for k in range(len(lay['area'])):
        lat0, lon0, rho = lay['lat'][k], lay['lon'][k], lay['rho'][k]
        rmax = rho.max() + halo_km
        dlat = rmax / 111.2 + res
        coslat = max(0.02, math.cos(math.radians(min(89, abs(lat0) + dlat))))
        dlon = min(180, rmax / (111.2 * coslat) + res)
        # 窓の中の経度にそろえる
        lc = lon0
        if not full:
            mid = (lon_a + lon_b) / 2
            lc = (lon0 - mid + 180) % 360 - 180 + mid
            if lc + dlon < lon_a or lc - dlon > lon_b or lat0 + dlat < lat_a or lat0 - dlat > lat_b:
                continue
        r0 = int(max(0, (lat_b - (lat0 + dlat)) / res))
        r1 = int(min(H, (lat_b - (lat0 - dlat)) / res + 1))
        c0 = int(math.floor((lc - dlon - lon_a) / res))
        c1 = int(math.ceil((lc + dlon - lon_a) / res)) + 1
        if not full:
            c0, c1 = max(0, c0), min(width, c1)
        if r1 <= r0 or c1 <= c0:
            continue
        rows = np.arange(r0, r1)
        cols = np.arange(c0, c1)
        LA = lat_b - (rows + 0.5) * res
        LO = (cols + 0.5) * res + lon_a
        GLA, GLO = np.meshgrid(LA, LO, indexing='ij')
        d = W.gc_dist(lat0, lon0, GLA, GLO)
        th = W.bearing(lat0, lon0, GLA, GLO)
        edge = W.interp_rho(rho, th)
        cc = np.mod(cols, width)
        RR, CC = np.meshgrid(rows, cc, indexing='ij')
        halo = (d < edge + halo_km) & (d >= edge)
        img[RR[halo], CC[halo]] = img[RR[halo], CC[halo]] * 0.45 + SHALLOW * 0.55
        inside = d < edge
        col = land_color(props['T'][k], props['P'][k], props['hmax'][k], props['kind'][k])
        if not inside.any():
            # 1画素より小さい島も、点として見えるようにする
            rr = int((lat_b - lat0) / res)
            cl = int((lc - lon_a) / res)
            if 0 <= rr < H and 0 <= cl < width:
                img[rr, cl] = col
        else:
            f = np.clip(1 - d / np.maximum(edge, 1e-6), 0, 1)
            shade_l = (0.8 + 0.35 * f)[..., None]
            img[RR[inside], CC[inside]] = np.clip(col * shade_l[inside], 0, 255)
    return Image.fromarray(img.astype(np.uint8))


def to_px(lat, lon, window, width):
    lon_a, lon_b, lat_a, lat_b = window
    res = (lon_b - lon_a) / width
    mid = (lon_a + lon_b) / 2
    lc = (np.asarray(lon) - mid + 180) % 360 - 180 + mid
    return (lc - lon_a) / res, (lat_b - np.asarray(lat)) / res


def overlay_state(img, world, snap, window, width, max_pop=None):
    """その年の集団（点の大きさは人口）を重ねる。色は舟の技術（白：いかだ、黄：丸木舟、橙：浮き木つき、赤：帆、桃：航法）"""
    d = ImageDraw.Draw(img, 'RGBA')
    reg = world['reg']
    col_of = lambda techs: ((255, 120, 200) if 'wayfinding' in techs else (240, 70, 60) if 'sail' in techs else
                            (255, 160, 40) if 'outrigger' in techs else (250, 230, 80) if 'dugout' in techs else (240, 240, 240))
    for g in snap['groups']:
        r = g['region']
        x, y = to_px(reg['lat'][r], reg['lon'][r], window, width)
        rad = max(2.0, 1.2 * math.sqrt(g['pop']) / 3)
        c = col_of(g['techs'])
        d.ellipse([x - rad, y - rad, x + rad, y + rad], fill=c + (210,), outline=(20, 20, 20, 200))
    return img


def window_around(lats, lons, margin_km=600, aspect=16 / 9):
    """点の集まりを囲む窓（経度の幅が緯度の幅の aspect 倍）"""
    lats = np.asarray(lats)
    lons = np.asarray(lons)
    mid_lon = math.degrees(math.atan2(np.mean(np.sin(np.radians(lons))), np.mean(np.cos(np.radians(lons)))))
    rel = (lons - mid_lon + 180) % 360 - 180
    m = margin_km / 111.2
    la0, la1 = lats.min() - m, lats.max() + m
    lo0, lo1 = rel.min() - m, rel.max() + m
    h = la1 - la0
    w = lo1 - lo0
    if w < h * aspect:
        c = (lo0 + lo1) / 2
        lo0, lo1 = c - h * aspect / 2, c + h * aspect / 2
    else:
        c = (la0 + la1) / 2
        la0, la1 = c - w / aspect / 2, c + w / aspect / 2
    return (lo0 + mid_lon, lo1 + mid_lon, max(-90, la0), min(90, la1))


def font(size):
    for p in ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', '/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf',
              '/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc'):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def contact_sheet(worlds, path, width=1200):
    """8つの地形を並べた一覧"""
    tiles = []
    for w in worlds:
        im = render(w, width)
        d = ImageDraw.Draw(im)
        s = W.summary(w)
        label = '%s  %s / %s   島 %d・最大の島 %s万km²・近い島まで（中央値）%dkm' % (
            w['tid'], w['family'], w['name'], s['島の数'], format(s['最大の島km2'] / 1e4, '.0f'),
            s['いちばん近い島までの海の幅km（10・50・90％点）'][1])
        d.rectangle([0, 0, width, 34], fill=(0, 0, 0))
        d.text((10, 5), label, fill=(255, 255, 255), font=font(20))
        tiles.append(im)
    cols = 2
    rows = math.ceil(len(tiles) / cols)
    sheet = Image.new('RGB', (cols * width + (cols - 1) * 8, rows * (width // 2) + (rows - 1) * 8), (255, 255, 255))
    for k, im in enumerate(tiles):
        sheet.paste(im, ((k % cols) * (width + 8), (k // cols) * (width // 2 + 8)))
    sheet.save(path, quality=88)
    return path
