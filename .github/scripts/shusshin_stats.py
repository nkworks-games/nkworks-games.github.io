# 出身地、当てます：Firestore のみんなの答え（shusshinShards の箱）を足し合わせて、
# ゲームが読む「まとめファイル」（shusshin-ken/stats.json）を作る。
# GitHub Actions で30分ごとに動く。ゲームはこのファイルを読むので、Firebase を読む料金がかからない。
#   python3 shusshin_stats.py shusshin-ken/stats.json
import json, os, re, sys, time, urllib.request

OUT = sys.argv[1]
URL = os.environ.get('SK_URL') or 'https://firestore.googleapis.com/v1/projects/nkworks-games/databases/(default)/documents/shusshinShards?pageSize=100'
N = 47

docs, token = [], None
while True:
    u = URL + ('&pageToken=' + token if token else '')
    with urllib.request.urlopen(u, timeout=60) as r:
        d = json.load(r)
    docs += d.get('documents', [])
    token = d.get('nextPageToken')
    if not token:
        break
names = sorted(x['name'].rsplit('/', 1)[1] for x in docs)
print('箱：', len(docs), names)
if len(docs) < 8:
    sys.exit('箱が少なすぎるので、作り直さない')

st = {}
for doc in docs:
    for k, v in doc.get('fields', {}).items():
        if 'integerValue' in v:
            n = int(v['integerValue'])
        elif 'doubleValue' in v:
            n = int(round(float(v['doubleValue'])))
        else:
            continue
        st[k] = st.get(k, 0) + n

q = {}
for k, v in st.items():
    m = re.match(r'^q(\d+)_(\d+)([abc])$', k)
    if not m or not 1 <= int(m.group(2)) <= N:
        continue
    a = q.setdefault(m.group(1), [0] * (3 * N))
    a[3 * (int(m.group(2)) - 1) + 'abc'.index(m.group(3))] = v
out = {
    'v': 1, 'at': int(time.time() * 1000), 't': st.get('t', 0),
    'n': [st.get('n%d' % (i + 1), 0) for i in range(N)],
    'h': [st.get('h%d' % (i + 1), 0) for i in range(N)],
    'q': dict(sorted(q.items(), key=lambda x: int(x[0]))),
}

old_t = -1
if os.path.exists(OUT):
    try:
        old_t = json.load(open(OUT, encoding='utf-8')).get('t', -1)
    except Exception:
        pass
print('遊んだ人：', old_t, '→', out['t'], '／ 問題', len(q))
if out['t'] <= old_t:
    print('前より増えていないので、そのまま')
    sys.exit(0)
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
print('書きました：', OUT, os.path.getsize(OUT), 'バイト')
