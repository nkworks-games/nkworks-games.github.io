"""並行地球：本番40試行の結果をまとめ、動画の候補になる経過を探す

  python3 report.py out/main

書き出すもの（out/main/report/）
  overview.png       8地形×5試行の人口・住む島・技術の推移
  table.md           地形ごとの結果の表（5試行の中央値と幅）
  candidates.md      動画で詳しく見せる候補（理由つき）と、各試行の転換点
"""
import gzip
import json
import os
import pickle
import sys

import numpy as np

import metrics
import world as W

TIDS = ['C1', 'C2', 'A1', 'A2', 'S1', 'S2', 'R1', 'R2']
FAMILY_COLOR = {'C': '#b5651d', 'A': '#2a7ab0', 'S': '#3a9a5b', 'R': '#8a5cb8'}


def load_runs(d):
    runs = []
    for tid in TIDS:
        for k in range(10):
            p = os.path.join(d, '%s-%d.pkl.gz' % (tid, k))
            if os.path.exists(p):
                with gzip.open(p) as f:
                    r = pickle.load(f)
                r['tech_first'] = r.get('tech_first_raw', r['tech_first'])
                runs.append(r)
    return runs


KEY_TECH = ['dugout', 'outrigger', 'sail', 'wayfinding', 'horticulture', 'agriculture', 'pottery', 'copper']


def turning_points(r):
    """その試行の転換点（年と短い説明）"""
    import model as M
    s = r['series']
    pop = np.asarray(s['pop'])
    isl = np.asarray(s['islands'])
    out = []
    for t in KEY_TECH:
        y = r['tech_first'].get(t)
        if y is not None:
            out.append((y, '%sを作り出す' % M.TECH_JA[t]))
    firsts = [e for e in r['events'] if e['kind'] in ('settle', 'relocate') and e.get('first')]
    if firsts:
        out.append((firsts[0]['year'], '初めて海を渡って別の島に住む（海の幅%dkm）' % round(firsts[0].get('gap', 0))))
    for n in (5, 10, 25, 50):
        y = np.nonzero(isl >= n)[0]
        if len(y):
            out.append((int(y[0]), '住む島が%dになる' % n))
    for f in (2, 10, 100):
        y = np.nonzero(pop >= 1000 * f)[0]
        if len(y):
            out.append((int(y[0]), '人口が%s人を超える' % format(1000 * f, ',')))
    summ = metrics.summarize(r)
    for a, b, d in summ['回復力']['大きな落ち込み']:
        out.append((a, '人口が%d年で%d％減る' % (b - a, round(d * 100))))
    lost_boat = [e for e in r['events'] if e['kind'] == 'tech_lost' and e.get('tech') in ('dugout', 'outrigger', 'sail', 'wayfinding')]
    if lost_boat:
        out.append((lost_boat[0]['year'], '舟の技術を失った集団が出る（%s）' % lost_boat[0]['text']))
    # 長い足止め：舟の届く距離が伸びないまま、住む島が1のままの期間
    stuck = np.nonzero(isl > 1)[0]
    if len(stuck) and stuck[0] > 600:
        out.append((0, '%d年間、最初の島から出られない' % stuck[0]))
    elif not len(stuck):
        out.append((0, '3,000年間、最初の島から出られない'))
    return sorted(out), summ


def interest_score(r, summ):
    """動画で詳しく見せる面白さの目安（転換点の多さ・落差・ほかの試行との違い）"""
    s = r['series']
    pop = np.asarray(s['pop'])
    isl = np.asarray(s['islands'])
    sc = 0.0
    sc += min(len(summ['回復力']['大きな落ち込み']), 3) * 1.0
    sc += 1.5 if summ['海']['最初に海を渡って住んだ年'] and summ['海']['最初に海を渡って住んだ年'] > 500 else 0
    sc += min(isl.max() / 10, 3)
    sc += 1.0 if any(e['kind'] == 'tech_lost' and e.get('tech') in ('dugout', 'outrigger', 'sail') for e in r['events']) else 0
    sc += 0.5 * min(summ['出来事の数'].get('famine', 0) / 10, 2)
    sc += 1.0 if pop[-1] < pop.max() * 0.6 else 0
    return sc


def main(d):
    runs = load_runs(d)
    outd = os.path.join(d, 'report')
    os.makedirs(outd, exist_ok=True)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for fp in ('/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf',):
        if os.path.exists(fp):
            font_manager.fontManager.addfont(fp)
            plt.rcParams['font.family'] = font_manager.FontProperties(fname=fp).get_name()
    fig, axes = plt.subplots(3, 8, figsize=(24, 9), sharex=True)
    for c, tid in enumerate(TIDS):
        rs = [r for r in runs if r['tid'] == tid]
        col = FAMILY_COLOR[tid[0]]
        for r in rs:
            s = r['series']
            axes[0, c].plot(s['pop'], color=col, lw=1, alpha=0.8)
            axes[1, c].plot(s['islands'], color=col, lw=1, alpha=0.8)
            axes[2, c].plot(s['techs'], color=col, lw=1, alpha=0.8)
        axes[0, c].set_yscale('log')
        axes[0, c].set_title('%s %s' % (tid, W.TERRAINS[tid][1]), fontsize=10)
    axes[0, 0].set_ylabel('人口')
    axes[1, 0].set_ylabel('住む島の数')
    axes[2, 0].set_ylabel('使える技術の数（平均）')
    for ax in axes[2]:
        ax.set_xlabel('年')
    fig.tight_layout()
    fig.savefig(os.path.join(outd, 'overview.png'), dpi=110)
    plt.close(fig)

    # 地形ごとの表
    lines = ['| 地形 | 人口（3,000年後・中央値と幅） | 住む島 | 初めて海を渡った年 | 技術の数 | 平均寿命（最後の500年） | 貧困度 | 余暇（人日/大人） |',
             '|---|---|---|---|---|---|---|---|']
    allpts = {}
    scores = []
    for tid in TIDS:
        rs = [r for r in runs if r['tid'] == tid]
        if not rs:
            continue
        sums = []
        for r in rs:
            tp, summ = turning_points(r)
            allpts[(tid, r['trial'])] = (tp, summ)
            scores.append((interest_score(r, summ), tid, r['trial']))
            sums.append(summ)
        P = [s['人口']['最後'] for s in sums]
        I = [s['存続']['住んでいる島（最後）'] for s in sums]
        X = [s['海']['最初に海を渡って住んだ年'] for s in sums]
        T = [s['豊かさ']['使える技術の数（最後）'] for s in sums]
        E = [s['平均寿命（500年ごと）'][-1][2] for s in sums]
        Pv = [s['貧困度（最後の500年の平均）'] for s in sums]
        L = [s['暮らしの余裕'] for s in sums]
        fmt = lambda v, f='%.0f': (f % np.median(v)) + '（' + (f % min(v)) + '〜' + (f % max(v)) + '）'
        xs = [x for x in X if x is not None]
        lines.append('| %s %s | %s | %s | %s | %s | %s | %s | %s |' % (
            tid, W.TERRAINS[tid][1], fmt(P), fmt(I), (fmt(xs) + ('、渡らない %d回' % (len(X) - len(xs)) if len(xs) < len(X) else '')) if xs else '5回とも渡らない',
            fmt(T, '%.1f'), fmt([e for e in E if e is not None], '%.1f') if any(e is not None for e in E) else '未算出',
            fmt(Pv, '%.2f'), fmt(L)))
    with open(os.path.join(outd, 'table.md'), 'w') as f:
        f.write('\n'.join(lines) + '\n')
    scores.sort(reverse=True)
    out = ['# 動画で詳しく見せる候補', '', '面白さの目安（転換点の多さ・落差・足止めの長さ）が高い順。典型か珍しいかは、同じ地形の5試行と比べて判断する。', '']
    for sc, tid, k in scores[:10]:
        tp, summ = allpts[(tid, k)]
        out.append('## %s-%d（%s / %s）目安 %.1f' % (tid, k, W.TERRAINS[tid][0], W.TERRAINS[tid][1], sc))
        out.append('人口 %s → 最大 %s（%d年）・住む島 %d・技術 %.1f' % (
            format(round(summ['人口']['500年ごと'][0]), ','), format(round(summ['人口']['最大']), ','), summ['人口']['最大の年'],
            summ['存続']['住んでいる島（最後）'], summ['豊かさ']['使える技術の数（最後）']))
        out.append('')
        for y, t in tp:
            out.append('- %d年：%s' % (y, t))
        out.append('')
    out.append('# すべての試行の転換点')
    for (tid, k), (tp, summ) in allpts.items():
        out.append('')
        out.append('## %s-%d' % (tid, k))
        for y, t in tp:
            out.append('- %d年：%s' % (y, t))
    with open(os.path.join(outd, 'candidates.md'), 'w') as f:
        f.write('\n'.join(out) + '\n')
    print('\n'.join(lines))
    print()
    print('候補の上位:', ['%s-%d(%.1f)' % (t, k, s) for s, t, k in scores[:8]])


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'out/main')
