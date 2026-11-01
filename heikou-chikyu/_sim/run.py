"""並行地球：試行をまとめて実行する

  python3 run.py pilot          # 予備計算：各系統から1地形（C1・A1・S1・R1）×1回×300年
  python3 run.py main           # 本番：8地形×5回×3,000年（40試行）
  python3 run.py verify        # 追加検証：潮麦・軽殻石・両方・初期人口2,000人・潮麦を1500年から（各40試行）
  python3 run.py one C1 0 3000  # 1つだけ

結果は out/<名前>/ に、試行ごとの記録（.pkl.gz）と、まとめ（summary.json）を書く。
同じ版・同じ地形・同じ試行番号なら、何度実行しても同じ結果になる。
"""
import gzip
import json
import multiprocessing as mp
import os
import pickle
import sys
import time

import numpy as np

import metrics
import model as M
import world as W

HERE = os.path.dirname(os.path.abspath(__file__))
TIDS = ['C1', 'C2', 'A1', 'A2', 'S1', 'S2', 'R1', 'R2']
_worlds = {}


def get_world(tid):
    if tid not in _worlds:
        _worlds[tid] = W.build_world(tid)
    return _worlds[tid]


def run_one(args):
    tid, trial, years, outdir, opts = args
    t0 = time.time()
    w = get_world(tid)
    s = M.Sim(w, trial, years=years, **opts)
    s.run()
    rec = dict(version=M.VERSION, tid=tid, trial=trial, years=years, family=w['family'], name=w['name'], opts=opts,
               series=s.series, events=s.events, snaps=s.snaps,
               deaths_age=np.array(s.deaths_age, np.float32), pop_age=np.array(s.pop_age, np.float32),
               checks=s.checks, tech_first={str(k): v for k, v in s.tech_first.items()},
               start_regions=s.start_regions, isl_settled=s.isl_settled.tolist(), seconds=time.time() - t0)
    rec['tech_first_raw'] = {k: v for k, v in s.tech_first.items() if isinstance(k, str)}
    path = os.path.join(outdir, '%s-%d.pkl.gz' % (tid, trial))
    with gzip.open(path, 'wb') as f:
        pickle.dump(rec, f)
    rec['tech_first'] = rec['tech_first_raw']
    summ = metrics.summarize(rec)
    return dict(tid=tid, trial=trial, seconds=round(time.time() - t0, 1), summary=summ)


def batch(name, jobs, procs=4, opts=None):
    opts = opts or {}
    outdir = os.path.join(HERE, 'out', name)
    os.makedirs(outdir, exist_ok=True)
    meta = dict(version=M.VERSION, jobs=[list(j) for j in jobs], opts=opts, started=time.strftime('%Y-%m-%d %H:%M:%S'))
    # 地形の記録（仕様書3章の項目）
    terr = {}
    for tid in sorted(set(j[0] for j in jobs)):
        terr[tid] = W.summary(get_world(tid))
    with open(os.path.join(outdir, 'terrains.json'), 'w') as f:
        json.dump(terr, f, ensure_ascii=False, indent=1, default=float)
    args = [(tid, trial, years, outdir, opts) for tid, trial, years in jobs]
    res = []
    with mp.get_context('fork').Pool(procs) as pool:
        for r in pool.imap_unordered(run_one, args):
            s = r['summary']
            print('%s-%d %5.1fs 人口 %8.0f（最大 %8.0f） 島 %3d 技術 %4.1f 海を渡った年 %s 舟の距離 %4.0fkm 検査 %s' % (
                r['tid'], r['trial'], r['seconds'], s['人口']['最後'], s['人口']['最大'], s['存続']['住んでいる島（最後）'],
                s['豊かさ']['使える技術の数（最後）'], s['海']['最初に海を渡って住んだ年'], s['海']['舟が届く距離km（最後）'],
                'OK' if not any(s['検査'].values()) else s['検査']), flush=True)
            res.append(r)
    res.sort(key=lambda r: (TIDS.index(r['tid']), r['trial']))
    meta['finished'] = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(os.path.join(outdir, 'summary.json'), 'w') as f:
        json.dump(dict(meta=meta, runs=res), f, ensure_ascii=False, indent=1, default=float)
    return res


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'pilot'
    if cmd == 'pilot':
        batch('pilot', [(t, 0, 300) for t in ('C1', 'A1', 'S1', 'R1')])
    elif cmd == 'main':
        batch('main', [(t, k, 3000) for t in TIDS for k in range(5)])
    elif cmd == 'verify':
        arms = {'tide': dict(extras=('tidewheat',)), 'stone': dict(extras=('lightstone',)),
                'both': dict(extras=('tidewheat', 'lightstone')), 'pop2000': dict(start_pop=2000),
                'tide1500': dict(extras=('tidewheat',), extras_year=1500)}
        for name in (sys.argv[2:] or arms):
            print('==', name, flush=True)
            batch('verify-' + name, [(t, k, 3000) for t in TIDS for k in range(5)], opts=arms[name])
    elif cmd == 'one':
        batch('one-%s-%s' % (sys.argv[2], sys.argv[3]), [(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))], procs=1)
