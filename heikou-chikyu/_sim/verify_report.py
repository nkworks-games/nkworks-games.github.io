"""並行地球：追加検証の比較（追加なし ↔ 追加あり）

  python3 verify_report.py

out/main（追加なし）と out/verify-*（追加あり）を、同じ地形・同じ試行番号どうしで比べる。
書き出すもの（out/verify-report/）
  compare.md    地形ごと・条件ごとの比較表と、主役候補の比較
  compare.png   地形ごとの人口の推移（5試行の中央値）
"""
import gzip
import os
import pickle

import numpy as np

import metrics
import world as W

HERE = os.path.dirname(os.path.abspath(__file__))
TIDS = ['C1', 'C2', 'A1', 'A2', 'S1', 'S2', 'R1', 'R2']
ARMS = [('main', '追加なし'), ('verify-tide', '潮麦'), ('verify-stone', '軽殻石'), ('verify-both', '潮麦＋軽殻石'),
        ('verify-pop2000', '初期人口2,000人'), ('verify-tide1500', '潮麦（1500年から）')]
FEATURED = [('R1', 1), ('R1', 4), ('A1', 2), ('C1', 3)]


def load(arm, tid, k):
    p = os.path.join(HERE, 'out', arm, '%s-%d.pkl.gz' % (tid, k))
    if not os.path.exists(p):
        return None
    with gzip.open(p) as f:
        r = pickle.load(f)
    r['tech_first'] = r.get('tech_first_raw', r['tech_first'])
    return r


def stats(r):
    s = {k: np.asarray(v, float) for k, v in r['series'].items()}
    last = slice(-500, None)
    ev = r['events']
    left = [e['year'] for e in ev if e['kind'] in ('settle', 'relocate') and e.get('first')]
    eat = [e['year'] for e in ev if e['kind'] == 'resource' and e.get('res') == 'tidewheat' and e.get('stage') == 2]
    e0 = metrics.life_expectancy(r['deaths_age'], r['pop_age'], 2500, 3000)
    return dict(
        pop=s['pop'][-1], islands=s['islands'][-1], stuck=not left, cross=left[0] if left else None,
        poor=s['poor'][last].mean(), leisure=s['leisure'][last].mean(), fish=s['fish'].min(),
        tide=s['tide_km2'][-1] if 'tide_km2' in s else 0.0,
        stone=(s['stone_boats'][-1] if 'stone_boats' in s else 0.0),
        tidefarm=r['tech_first'].get('tidefarm'), lightboat=r['tech_first'].get('lightboat'),
        eat=eat[0] if eat else None, e0=e0, famine=sum(1 for e in ev if e['kind'] == 'famine'),
        series=s['pop'])


def med(v):
    v = [x for x in v if x is not None]
    return float(np.median(v)) if v else None


def main():
    outd = os.path.join(HERE, 'out', 'verify-report')
    os.makedirs(outd, exist_ok=True)
    data = {}
    for arm, _ in ARMS:
        for tid in TIDS:
            for k in range(5):
                r = load(arm, tid, k)
                if r is not None:
                    data[(arm, tid, k)] = stats(r)
    lines = ['# 追加検証：人口を増やすには何が足りないか', '',
             '同じ地形・同じ試行番号（同じ出発地点・同じ偶然）で、追加なしと追加ありを比べる。値は5試行の中央値。', '']
    for tid in TIDS:
        lines.append('## %s %s / %s' % (tid, W.TERRAINS[tid][0], W.TERRAINS[tid][1]))
        lines.append('')
        lines.append('| 条件 | 人口（3,000年後） | 追加なしとの比（試行ごとの比の中央値・幅） | 住む島 | 最初の島から出られない回数 | 余暇（人日/大人） | 貧困度 | 岸の魚（最も減った時） | 平均寿命 |')
        lines.append('|---|---|---|---|---|---|---|---|---|')
        for arm, label in ARMS:
            ds = [data.get((arm, tid, k)) for k in range(5)]
            if any(d is None for d in ds):
                continue
            base = [data.get(('main', tid, k)) for k in range(5)]
            ratio = [d['pop'] / max(b['pop'], 1) for d, b in zip(ds, base)]
            e0 = med([d['e0'] for d in ds])
            lines.append('| %s | %s | %s（%s〜%s） | %.0f | %d/5 | %.0f | %.2f | %.2f | %s |' % (
                label, format(round(med([d['pop'] for d in ds])), ','),
                '%.2f倍' % np.median(ratio), '%.2f' % min(ratio), '%.2f' % max(ratio),
                med([d['islands'] for d in ds]), sum(d['stuck'] for d in ds), med([d['leisure'] for d in ds]),
                med([d['poor'] for d in ds]), med([d['fish'] for d in ds]), '%.1f' % e0 if e0 else '未算出'))
        lines.append('')
    lines.append('## 主役候補の比較')
    lines.append('')
    lines.append('| 試行 | ' + ' | '.join(l for _, l in ARMS) + ' |')
    lines.append('|---|' + '---|' * len(ARMS))
    for tid, k in FEATURED:
        cells = []
        for arm, _ in ARMS:
            d = data.get((arm, tid, k))
            cells.append('—' if d is None else '%s人・%d島' % (format(round(d['pop']), ','), d['islands']))
        lines.append('| %s-%d | %s |' % (tid, k, ' | '.join(cells)))
    lines.append('')
    lines.append('## 架空の資源が使われた時期（中央値）')
    lines.append('')
    for arm, label in ARMS[1:4] + ARMS[5:]:
        ds = [d for (a, t, k), d in data.items() if a == arm]
        if not ds:
            continue
        lines.append('- %s：潮麦を食べられると知った年 %s、潮麦の栽培 %s 年（%d/40試行で開発）、軽殻石の浮き舟 %s 年（%d/40）、3,000年後の潮麦の浅瀬 %s km²、軽殻石の舟 %s 艘' % (
            label, med([d['eat'] for d in ds]), med([d['tidefarm'] for d in ds]), sum(d['tidefarm'] is not None for d in ds),
            med([d['lightboat'] for d in ds]), sum(d['lightboat'] is not None for d in ds),
            format(round(med([d['tide'] for d in ds]) or 0), ','), format(round(med([d['stone'] for d in ds]) or 0), ',')))
    with open(os.path.join(outd, 'compare.md'), 'w') as f:
        f.write('\n'.join(lines) + '\n')
    # 図
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    fp = '/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf'
    if os.path.exists(fp):
        font_manager.fontManager.addfont(fp)
        plt.rcParams['font.family'] = font_manager.FontProperties(fname=fp).get_name()
    colors = ['#333333', '#2a9d8f', '#b07d3a', '#7a4fb0', '#d0453a', '#7fb3d5']
    fig, axes = plt.subplots(2, 4, figsize=(20, 8.5))
    for ax, tid in zip(axes.ravel(), TIDS):
        for (arm, label), c in zip(ARMS, colors):
            ss = [data.get((arm, tid, k)) for k in range(5)]
            if any(d is None for d in ss):
                continue
            m = np.median(np.stack([d['series'] for d in ss]), axis=0)
            ax.plot(m, color=c, lw=1.6 if arm == 'main' else 1.2, label=label, ls='-' if arm != 'verify-tide1500' else '--')
        ax.set_yscale('log')
        ax.set_title('%s %s' % (tid, W.TERRAINS[tid][1]), fontsize=11)
        ax.set_xlabel('年')
    axes[0, 0].set_ylabel('人口（5試行の中央値）')
    axes[1, 0].set_ylabel('人口（5試行の中央値）')
    axes[0, 0].legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(outd, 'compare.png'), dpi=110)
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
