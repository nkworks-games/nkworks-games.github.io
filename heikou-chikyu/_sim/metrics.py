"""並行地球：評価（E1.0 の簡易版）

視聴者に見せる4項目：人口・平均寿命・貧困度・豊かさ
シリーズ共通の7軸：存続・生活の安定・暮らしの余裕・技術と知識・社会のつながり・環境と資源の持続性・回復力
総合点や順位は作らない。
"""
import numpy as np


def life_expectancy(deaths_age, pop_age, y0, y1, min_deaths=200):
    """y0〜y1年の、年齢別の死亡率から計算した出生時の平均寿命（期間生命表）。死亡が少なすぎれば None（未算出）"""
    D = np.asarray(deaths_age[y0:y1]).sum(axis=0)
    P = np.asarray(pop_age[y0:y1]).sum(axis=0)
    if D.sum() < min_deaths:
        return None
    expo = np.maximum(P - D / 2, 1e-9)
    m = np.where(P > 0, D / expo, 0.0)
    q = np.clip(m / (1 + m / 2), 0, 1)
    q[-1] = 1.0
    l = np.concatenate([[1.0], np.cumprod(1 - q)[:-1]])
    L = l * (1 - q / 2)
    return float(L.sum())


def windows(n_years, step=250):
    return [(a, min(a + step, n_years)) for a in range(0, n_years, step)]


def summarize(run):
    s = {k: np.asarray(v, float) for k, v in run['series'].items()}
    n = len(s['pop'])
    pop = s['pop']
    ev = run['events']
    kinds = {}
    for e in ev:
        kinds[e['kind']] = kinds.get(e['kind'], 0) + 1
    e0 = [(a, b, life_expectancy(run['deaths_age'], run['pop_age'], a, b)) for a, b in windows(n, 500)]
    last = slice(max(0, n - 500), n)
    # 大きな落ち込み：50年で2割以上減った時期
    drops = []
    for y in range(50, n):
        if pop[y - 50] > 100 and pop[y] < 0.8 * pop[y - 50]:
            if not drops or y - drops[-1][1] > 100:
                drops.append([y - 50, y, float(1 - pop[y] / pop[y - 50])])
            else:
                drops[-1][1] = y
                drops[-1][2] = max(drops[-1][2], float(1 - pop[y] / pop[y - 50]))
    # 回復：落ち込みの後、元の人口に戻るまでの年数
    recov = []
    for a, b, d in drops:
        target = pop[a]
        after = np.nonzero(pop[b:] >= target)[0]
        recov.append(int(after[0] + b - a) if len(after) else None)
    settled = [e for e in ev if e['kind'] in ('settle', 'relocate') and e.get('first')]
    techs_first = {k: v for k, v in run['tech_first'].items() if isinstance(k, str)}
    out = {
        '人口': {'最後': float(pop[-1]), '最大': float(pop.max()), '最大の年': int(pop.argmax()),
                '500年ごと': [float(pop[min(y, n - 1)]) for y in range(0, n + 1, 500)]},
        '平均寿命（500年ごと）': [[a, b, None if v is None else round(v, 1)] for a, b, v in e0],
        '貧困度（最後の500年の平均）': float(s['poor'][last].mean()),
        '豊かさ': {'余暇 人日/大人（最後の500年）': float(s['leisure'][last].mean()),
                 '備蓄 か月分（最後の500年）': float(s['store'][last].mean()),
                 '使える技術の数（最後）': float(s['techs'][-1])},
        '存続': {'住んでいる島（最後）': int(s['islands'][-1]), '集団（最後）': int(s['groups'][-1]),
               '途絶えた集団': kinds.get('extinct', 0), '全滅': bool(pop[-1] < 1)},
        '生活の安定': {'食べ物が大きく足りない年の記録': kinds.get('famine', 0),
                   '食べ物の充足（最後の500年）': float(s['food'][last].mean()),
                   '水の充足（最後の500年）': float(s['water'][last].mean())},
        '暮らしの余裕': float(s['leisure'][last].mean()),
        '技術と知識': {'最初に作り出した年': techs_first, '失われた回数': kinds.get('tech_lost', 0),
                   '伝わった回数': kinds.get('tech_spread', 0)},
        '社会のつながり': {'付き合いのある組（最後）': int(s['contacts'][-1]),
                     '島をまたぐ行き来が始まった組': kinds.get('contact', 0)},
        '環境と資源': {'森（最小）': float(s['forest'].min()), '大木（最小）': float(s['bigtree'].min()),
                   '岸の魚（最小）': float(s['fish'].min()), '貝（最小）': float(s['shell'].min()),
                   '畑km²（最後）': float(s['farmed_km2'][-1])},
        '回復力': {'大きな落ち込み': [[a, b, round(d, 2)] for a, b, d in drops], '元に戻るまでの年数': recov},
        '海': {'初めて人が住んだ島': len(settled), '最初に海を渡って住んだ年': settled[0]['year'] if settled else None,
              '舟が届く距離km（最後）': float(s['range_km'][-1]), '戻らなかった探検': kinds.get('voyage_lost', 0),
              '戻らなかった移住': kinds.get('migration_lost', 0)},
        '出来事の数': kinds,
        '検査': run['checks'],
    }
    return out
