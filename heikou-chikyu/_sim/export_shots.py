"""並行地球：カット表の3Dのカットの設定（_blender/shots/ep1.json）を、計算の記録から作る

  python3 export_shots.py

各カットの「記録」（試行・年）から、その時点の集落の大きさ・持っている技術・森の残り具合・気候・島の種類を読み、
家・舟・干し棚・土器・畑などを決める。時代に合わないもの（まだ作り出していない舟など）は置かない。
人の顔の大写しはしない（遠景・後ろ姿・手元）。
"""
import gzip
import json
import os
import pickle

import numpy as np

import world as W

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', '_blender', 'shots', 'ep1.json')
_cache = {}


def run(tid, trial, arm='main'):
    key = (arm, tid, trial)
    if key not in _cache:
        with gzip.open(os.path.join(HERE, 'out', arm, '%s-%d.pkl.gz' % (tid, trial))) as f:
            _cache[key] = pickle.load(f)
    return _cache[key]


_worlds = {}


def world(tid):
    if tid not in _worlds:
        _worlds[tid] = W.build_world(tid)
    return _worlds[tid]


def state(tid, trial, year, arm='main'):
    """その年の、出発の地域の集落の様子"""
    r = run(tid, trial, arm)
    w = world(tid)
    snaps = r['snaps']
    snap = max((s for s in snaps if s['year'] <= year), key=lambda s: s['year'])
    r0 = r['start_regions'][0]
    isl = int(w['reg']['island'][r0])
    gs = [g for g in snap['groups'] if g['region'] == r0] or [g for g in snap['groups'] if g['island'] == isl]
    pop = sum(g['pop'] for g in gs)
    techs = set(t for g in gs for t in g['techs'])
    reg = snap['regions'].get(r0) or snap['regions'].get(str(r0)) or {}
    T = float(w['reg']['T'][r0])
    climate = 'tropical' if T >= 24 else ('subtropical' if T >= 17 else 'temperate')
    kind = w['props']['kind'][isl]
    return dict(pop=pop, techs=techs, forest=float(reg.get('forest', 1.0)), farmed=float(reg.get('farmed_km2', 0.0)),
                climate=climate, preset=kind, island=isl, year=snap['year'])


def village(st, scale=1.0):
    t = st['techs']
    huts = int(np.clip(round(st['pop'] / 6 * 0.3 * scale), 3, 26))
    boats = []
    if 'sail' in t:
        boats = [{'type': 'outrigger', 'count': 3}, {'type': 'sail', 'count': 2, 'afloat': True}]
    elif 'outrigger' in t:
        boats = [{'type': 'outrigger', 'count': 3}, {'type': 'dugout', 'count': 2}]
    elif 'dugout' in t or 'lightboat' in t:
        boats = [{'type': 'dugout', 'count': 4}]
    else:
        boats = [{'type': 'raft', 'count': 5}]
    return dict(settlement=dict(huts=huts, style='hut' if 'adze' in t else 'shelter', racks=3 if 'drying' in t else 0,
                                pots=2 if 'pottery' in t else 0, gardens=4 if ('horticulture' in t or 'agriculture' in t) else 0,
                                storehouse='storehouse' in t, fires=3, smoke=2, people=int(np.clip(st['pop'] / 30, 5, 16))),
                boats=boats)


def coast(cid, title, tid, trial, year, camera, time='day', arm='main', anim=True, seconds=8, **kw):
    st = state(tid, trial, year, arm)
    s = dict(id=cid, title=title, kind='coast', seed={'R1': 4, 'A1': 2, 'C1': 3}[tid] * 10 + trial,
             preset=st['preset'], climate=st['climate'], ground='volcanic' if st['preset'] == 'volcanic_high' else 'temperate',
             forest=round(min(1.0, max(0.55, st['forest'])) * 0.97, 3), palm_density=0.35 if st['climate'] != 'tropical' else 0.7,
             sky=dict(time=time, azimuth=-150 if time in ('dusk', 'dawn') else -140, elevation=4.0 if time in ('dusk', 'dawn') else None,
                      cloud=0.5), camera=camera, anim=anim, seconds=seconds,
             record='%s-%d・%d年（%s）' % (tid, trial, st['year'], arm), techs=sorted(st['techs']), pop=st['pop'])
    if time in ('dusk', 'dawn'):
        s['exposure'] = 0.4
    s.update(village(st, kw.pop('village_scale', 1.0)))
    for k, v in kw.items():
        if k in ('settlement', 'sky') and isinstance(v, dict):
            s[k].update(v)
        else:
            s[k] = v
    return s


CAM_BEACH = dict(loc=[34, 98, 2.6], target=[-14, 170, 7], lens=30, loc2=[27, 104, 2.6], target2=[-16, 172, 7])
CAM_DRONE = dict(loc=[60, 30, 14], target=[0, 175, 12], lens=28, loc2=[50, 45, 13], target2=[0, 178, 12])


def opensea(cid, title, time='dusk', boats=None, islands=None, camera=None, seconds=8, **kw):
    s = dict(id=cid, title=title, kind='opensea', seed=11, wave=0.6, boats=boats or [], islands=islands or [],
             sky=dict(time=time, azimuth=20, cloud=0.5), camera=camera, anim=True, seconds=seconds)
    s.update(kw)
    return s


def planet(cid, title, camera, seconds=9, **kw):
    s = dict(id=cid, title=title, kind='planet', terrain='R1', spin=200, sun_az=50, camera=camera, anim=True, seconds=seconds)
    s.update(kw)
    return s


def islands_shot(cid, title, tid, trial, camera, time='dusk', radius_km=150, boats=None, seconds=10, anim=True, relief=1.0):
    r = run(tid, trial)
    w = world(tid)
    isl = int(w['reg']['island'][r['start_regions'][0]])
    return dict(id=cid, title=title, kind='islands', terrain=tid, center_island=isl, radius_km=radius_km, seed=5, relief=relief,
                boats=boats or [], sky=dict(time=time, azimuth=-150 if time == 'dusk' else -140, elevation=5.0 if time == 'dusk' else None, cloud=0.45),
                camera=camera, anim=anim, seconds=seconds, record='%s-%d の島（計算の形）' % (tid, trial), exposure=0.3 if time == 'dusk' else 0.0)


def main():
    S = []
    sail_boat = lambda loc, hd, crew=3: dict(loc=loc, heading=hd, sail=True, length=9.5, crew=crew, speed=3.0)
    far = [dict(radius=900, height=180, loc=[-2600, 7000, -5]), dict(radius=500, height=90, loc=[2200, 9500, -5])]
    S.append(opensea('001', '夕暮れの海を渡る帆の舟（R1-1・2,900年ごろ）', boats=[sail_boat([0, 0, 0.35], -20)], islands=far,
                     camera=dict(loc=[-24, -12, 3.5], target=[0, 10, 3], lens=35, loc2=[-20, 6, 3.2], target2=[2, 28, 3]), seconds=7))
    S.append(opensea('002', '舟の上から：帆と波、遠くに島影（R1-1）', boats=[sail_boat([0, 0, 0.35], 0)], islands=far,
                     camera=dict(loc=[1.3, 3.4, 1.5], target=[-7, 40, 2.0], lens=24, loc2=[1.3, 21.4, 1.5], target2=[-7, 58, 2.0], ease=False), seconds=6))
    S.append(coast('003', '小さな火山島の夕方の浜（R1-4・2,990年）', 'R1', 4, 2990, CAM_BEACH, time='dusk'))
    S.append(planet('004', '雲の上から惑星の全景へ', dict(loc=[0, -7.5, 2.4], target=[0, 0, 6.4], lens=35, loc2=[0, -24, 5], target2=[0, 0, 0])))
    S.append(planet('006', '惑星がゆっくり回る', dict(loc=[-8, -18, 4], target=[0, 0, 0], lens=50, loc2=[8, -18, 4], target2=[0, 0, 0], ease=False), seconds=8))
    S.append(coast('013', '浜の火と石の道具、数人の後ろ姿（開始時点）', 'A1', 2, 0, dict(loc=[8, 133, 1.6], target=[4, 148, 0.8], lens=35),
                   time='dusk', anim=False, extras=[dict(type='fire', loc=[4, 146], strength=120), dict(type='woodpile', loc=[7, 149]),
                                                   dict(type='figure', loc=[2.6, 144.6], pose='sit', rot=-60), dict(type='figure', loc=[5.6, 144.4], pose='sit', rot=60),
                                                   dict(type='figure', loc=[4.2, 143.9], pose='sit', rot=0)]))
    S.append(coast('019', '朝の浜の集落（R1-1・0年ごろ）', 'R1', 1, 0, CAM_DRONE, time='dawn', anim=False))
    S.append(coast('020', '潮の引いた岩場で貝をとる（A1-2・100年ごろ）', 'A1', 2, 100, dict(loc=[68, 22, 1.8], target=[56, 38, 0.3], lens=40, loc2=[66, 24, 1.7], target2=[56, 38, 0.3]),
                   reef=True, extras=[dict(type='figure', loc=[54, 38], pose='bend', rot=200), dict(type='figure', loc=[59, 35], pose='bend', rot=150, phase=0.3)]))
    S.append(coast('021', '岸で魚を突く（A1-2・100年ごろ）', 'A1', 2, 100, dict(loc=[14, 144, 1.5], target=[-2, 134.5, 0.7], lens=50, loc2=[13, 143.4, 1.5], target2=[-2.5, 134.5, 0.7]),
                   extras=[dict(type='figure', loc=[-4, 134], pose='bend', rot=200), dict(type='figure', loc=[2, 136.5], pose='look', rot=150)], seconds=6))
    S.append(coast('022', '水を運ぶ（A1-2・100年ごろ）', 'A1', 2, 100, dict(loc=[-14, 132, 1.6], target=[-30, 140.5, 1.0], lens=45),
                   extras=[dict(type='figure', loc=[-37, 140.5], pose='carry', rot=-90, move=[9, 0, 0])], seconds=6))
    S.append(coast('023', '薪を運び、火を焚く（A1-2・100年ごろ）', 'A1', 2, 100, dict(loc=[16, 138, 1.7], target=[8, 150, 0.8], lens=35, loc2=[15, 139, 1.7], target2=[8, 150, 0.8]),
                   extras=[dict(type='fire', loc=[8, 150], strength=100), dict(type='woodpile', loc=[11, 153]), dict(type='figure', loc=[5, 152], pose='carry', rot=40)], seconds=6))
    S.append(coast('031', '小さな火山島の浜。家は少ない（R1-4・100年）', 'R1', 4, 100, CAM_DRONE, time='day', anim=False))
    S.append(coast('033', '落ち着いた集落の暮らし（A1-2・200年）', 'A1', 2, 200, dict(loc=[42, 148, 6.5], target=[-30, 165, 3], lens=32, loc2=[38, 146, 6.3], target2=[-30, 165, 3])))
    S.append(coast('035', '干物を干す棚と煙（A1-2・300年）', 'A1', 2, 300, dict(loc=[22, 138, 1.7], target=[10, 150, 1.3], lens=35, loc2=[21, 139, 1.7], target2=[10, 150, 1.3]),
                   extras=[dict(type='rack', loc=[10, 149], rot=20), dict(type='rack', loc=[16, 152], rot=-10), dict(type='fire', loc=[13, 146], strength=60)]))
    S.append(coast('036', '土器を焼く（A1-2・333年）', 'A1', 2, 333, dict(loc=[7, 140, 1.0], target=[2, 147, 0.5], lens=40, loc2=[6.5, 140.5, 1.0], target2=[2, 147, 0.5]), time='dusk',
                   extras=[dict(type='fire', loc=[2, 147], strength=150), dict(type='pots', loc=[3.2, 148.5], n=4), dict(type='figure', loc=[0, 149.5], pose='sit', rot=-140)]))
    S.append(coast('038', '嵐の浜。家と舟が傷む（A1-2・629年）', 'A1', 2, 629, CAM_BEACH, time='day', sky=dict(storm=1.0, cloud=0.95), exposure=-0.2,
                   extras=[dict(type='dugout', loc=[-10, 150], rot=30, tilt=25)]))
    S.append(coast('044', '浜から海を見る人（後ろ姿）、水平線に島影（A1-2・250年）', 'A1', 2, 250, dict(loc=[1.5, 160, 2.3], target=[0, 0, 4], lens=35, loc2=[1.2, 157, 2.2], target2=[0, 0, 4]),
                   extras=[dict(type='figure', loc=[0, 146], pose='look', rot=180)], islands=[dict(radius=1800, height=260, loc=[-6000, -45000, -5])]))
    S.append(coast('047', '大木を倒し、丸木舟を彫る（A1-2・264年）', 'A1', 2, 264, dict(loc=[-22, 158, 1.8], target=[-36, 171, 0.8], lens=35, loc2=[-23, 159, 1.8], target2=[-36, 171, 0.8]),
                   extras=[dict(type='log', loc=[-36, 171], rot=70), dict(type='figure', loc=[-34.5, 169.5], pose='bend', rot=150)]))
    S.append(coast('048', '舟に浮き木を取り付ける（A1-2・284年）', 'A1', 2, 284, dict(loc=[20, 128, 1.6], target=[10, 140, 0.5], lens=35, loc2=[19, 129, 1.6], target2=[10, 140, 0.5]),
                   extras=[dict(type='outrigger', loc=[10, 140], rot=80), dict(type='figure', loc=[8.5, 137.5], pose='bend', rot=40), dict(type='figure', loc=[12, 143], pose='stand', rot=200)]))
    S.append(coast('049', '浜から沖へ漕ぎ出す舟（A1-2・314年）', 'A1', 2, 314, dict(loc=[6, 142, 1.8], target=[0, 100, 0.5], lens=35), time='dawn', seconds=10,
                   extras=[dict(type='outrigger', loc=[0, 122], rot=180, float=True, move=[0, -40, 0])]))
    S.append(coast('051', '新しい島の浜に舟が着く（A1-2・314年）', 'A1', 2, 0, dict(loc=[-6, 152, 2.5], target=[0, 100, 1], lens=35), seconds=12,
                   settlement=dict(huts=0, fires=0, people=0, racks=0, pots=0, gardens=0), boats=[], forest=1.0,
                   extras=[dict(type='outrigger', loc=[0, 95], rot=0, float=True, move=[0, 18, 0])]))
    S.append(coast('055', '帆をあげる舟（A1-2・380年〜）', 'A1', 2, 400, dict(loc=[16, 126, 1.5], target=[0, 112, 3], lens=35, loc2=[15, 124, 1.5], target2=[0, 112, 3]),
                   extras=[dict(type='sail', loc=[0, 112], rot=90, float=True)], seconds=10))
    S.append(coast('057', '芋や果樹の畑（A1-2・772年〜）', 'A1', 2, 800, dict(loc=[40, 196, 7], target=[0, 245, 0], lens=30, loc2=[36, 200, 6.5], target2=[0, 245, 0]),
                   settlement=dict(gardens=6), seconds=10))
    S.append(opensea('056', '夜の航海。星を見上げる（A1-2・1,163年）', time='night', boats=[sail_boat([0, 0, 0.35], 10, crew=3)],
                     camera=dict(loc=[-9, -8, 2.2], target=[0, 4, 4.5], lens=28, loc2=[-8, -4, 2.2], target2=[0, 8, 4.5]), seconds=10, wave=0.4,
                     extras=[dict(type='figure', loc=[0.2, 1.0, 0.3], pose='look', rot=10)]))
    S.append(islands_shot('063', '群島の空撮（夕方・A1の実際の島々）', 'A1', 2, dict(loc=[0, -38000, 6000], target=[0, 15000, 0], lens=35), anim=False, relief=2.5))
    S.append(islands_shot('064', '島々の間を行き交う舟（A1-2・2,500年）', 'A1', 2, dict(loc=[-60, -260, 45], target=[0, 400, 0], lens=35, loc2=[-40, -200, 42], target2=[0, 460, 0]), time='day',
                          boats=[sail_boat([0, 0, 0.35], -5), sail_boat([40, 120, 0.35], 8), sail_boat([-50, 260, 0.35], -12)], seconds=12, relief=2.0))
    S.append(islands_shot('069', 'R1-1の島：大木の森のある、大きな火山島（計算の形）', 'R1', 1, dict(loc=[0, -90000, 26000], target=[0, 0, 0], lens=35), time='day', radius_km=60, anim=False, relief=4.0))
    S.append(islands_shot('070', 'R1-4の島：小さな古い火山島（計算の形）', 'R1', 4, dict(loc=[0, -42000, 12000], target=[0, 0, 0], lens=35), time='day', radius_km=60, anim=False, relief=4.0))
    S.append(opensea('074', '遠くの島へ向かう帆の船団（R1-1・2,000年ごろ）', time='day',
                     boats=[sail_boat([0, 0, 0.35], -10), sail_boat([-25, -30, 0.35], -10), sail_boat([20, -45, 0.35], -10), sail_boat([-8, -70, 0.35], -10)],
                     islands=[dict(radius=1600, height=300, loc=[-4000, 16000, -5])],
                     camera=dict(loc=[45, -95, 9], target=[-5, 10, 2], lens=40, loc2=[40, -70, 8], target2=[-8, 40, 2]), seconds=12))
    S.append(coast('076', '浜で沖を見る人（後ろ姿）と、いかだ（R1-4・1,500年）', 'R1', 4, 1500, dict(loc=[2, 160, 2.2], target=[0, 0, 3.5], lens=35, loc2=[1.6, 157, 2.2], target2=[0, 0, 3.5]),
                   time='dusk', extras=[dict(type='figure', loc=[0, 145], pose='look', rot=180), dict(type='raft', loc=[6, 138], rot=10)], seconds=12))
    S.append(coast('079', '大きな島の空撮（C1-3）', 'C1', 3, 2500, dict(loc=[0, -500, 260], target=[0, 450, 0], lens=28, loc2=[0, -380, 230], target2=[0, 500, 0])))
    S.append(coast('081', '海岸の集落と畑、背後に手つかずの内陸の森（C1-3・2,500年）', 'C1', 3, 2500, dict(loc=[70, 40, 32], target=[0, 200, 8], lens=28, loc2=[58, 55, 30], target2=[0, 205, 8]),
                   village_scale=2.0, settlement=dict(gardens=6), seconds=12))
    S.append(coast('090', '潮の引いた浅瀬に揺れる潮麦の穂（追加検証・R1-4）', 'R1', 4, 2500, dict(loc=[10, 70, 1.2], target=[-5, 100, 0.9], lens=40, loc2=[8, 74, 1.2], target2=[-5, 100, 0.9]),
                   arm='verify-tide', tidewheat=dict(density=1.0), seconds=12))
    # 軽殻石のある島（R1-2 の出発の島）で見せる。R1-4 の島には軽殻石がない（計算の設定）
    S.append(coast('092', '浜に打ち上げられた白い軽殻石。水に浮く（追加検証・R1-2）', 'R1', 2, 2500, dict(loc=[4, 121, 0.7], target=[0, 132, 0.2], lens=35, loc2=[3.5, 122, 0.7], target2=[0, 132, 0.2]),
                   arm='verify-stone', seconds=10,
                   extras=[dict(type='lightstone', loc=[x, y], size=sz, float=fl) for x, y, sz, fl in
                           [(-1, 131, 0.5, False), (1.5, 133, 0.35, False), (-3, 134, 0.6, False), (2.5, 130, 0.3, False), (0.5, 136, 0.45, False),
                            (-2, 124, 0.4, True), (1, 122, 0.3, True), (3, 125, 0.5, True), (-4, 121, 0.35, True)]]))
    S.append(coast('097', '浅瀬で潮麦を刈る人々（遠景）（R1-4・潮麦あり・2,500年）', 'R1', 4, 2500, dict(loc=[18, 78, 1.6], target=[-5, 102, 1.0], lens=45, loc2=[16, 80, 1.6], target2=[-5, 102, 1.0]),
                   arm='verify-tide', tidewheat=dict(density=1.0), seconds=12,
                   extras=[dict(type='figure', loc=[-6, 101], pose='bend', rot=200), dict(type='figure', loc=[-1, 104], pose='bend', rot=160, phase=0.4),
                           dict(type='figure', loc=[-10, 106], pose='carry', rot=90)]))
    S.append(coast('104', '（予備）夕暮れの潮麦の浅瀬', 'R1', 4, 2500, dict(loc=[10, 70, 1.4], target=[-5, 100, 1.0], lens=35), time='dusk', anim=False,
                   arm='verify-tide', tidewheat=dict(density=1.0)))
    S.append(planet('105', '惑星の全景', dict(loc=[0, -22, 4], target=[0, 0, 0], lens=50, loc2=[-3, -21.5, 4], target2=[0, 0, 0]), seconds=10))
    S.append(opensea('111', '冒頭の帆の舟へ戻る（R1-1・2,900年）', boats=[sail_boat([0, 0, 0.35], 30)], islands=far,
                     camera=dict(loc=[22, -16, 5], target=[0, 6, 3], lens=35, loc2=[16, 2, 4.5], target2=[-4, 24, 3]), seconds=14))
    S.append(coast('112', '小さな火山島の浜の夕暮れ。火を囲む人影（R1-4・2,990年）', 'R1', 4, 2990, dict(loc=[20, 112, 2.0], target=[0, 160, 3], lens=32, loc2=[16, 118, 2.0], target2=[-2, 162, 3]),
                   time='dusk', seconds=14, sky=dict(elevation=2.0)))
    S.append(planet('113', 'カメラが空へ上がり、惑星の全景へ', dict(loc=[0, -7.0, 0.9], target=[0, 0, 0.9], lens=35, loc2=[0, -26, 6], target2=[0, 0, 0]), seconds=16))
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(dict(episode='並行地球 第1回', note='export_shots.py が計算の記録から作る。手で直すときは export_shots.py を直す', shots=S),
                  f, ensure_ascii=False, indent=1, default=lambda o: sorted(o) if isinstance(o, set) else str(o))
    print(len(S), 'shots →', OUT)
    for s in S:
        if s['kind'] == 'coast':
            print(s['id'], s.get('record'), s['preset'], s['climate'], 'pop', s.get('pop'), 'huts', s['settlement']['huts'], s['settlement']['style'],
                  'boats', [b['type'] for b in s['boats']], 'techs', len(s.get('techs', [])))


if __name__ == '__main__':
    main()
