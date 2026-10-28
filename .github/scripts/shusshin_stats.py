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
# 箱ごとの項目の数（Firestore は1つの箱の索引が40,000まで。数の項目は1つで索引2つなので、約20,000項目をこえると書きこめなくなる）
fields = {x['name'].rsplit('/', 1)[1]: len(x.get('fields', {})) for x in docs}
print('箱ごとの項目の数：', fields, '／ 最大', max(fields.values()))
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

# ---- 書きかえ対策 ----
# Firestore のルールでは、+1 以外の数や、ゲームにない項目も書きこめてしまう（2026-10-28 に、試験の書きこみで北海道の人数などが水増しされた）。
# そこで、前回のまとめ（OUT）を正しい値として、そこからの増え方がありえる範囲かを、項目ごとに確かめる。
# ありえない増え方の項目は、今回の増えを使わず、その分を adj に覚えて、次からも Firestore の値から引く。
html = open(os.path.join(os.path.dirname(OUT) or '.', 'index.html'), encoding='utf-8').read()
REAL = set(re.findall(r'\{"s":(\d+),"id"', html))   # ゲームにある問題の番号
KEY = re.compile(r'^(?:t|[nh](\d+)|q(\d+)_(\d+)[abc]|zx\d+_(\d+)_(\d+)|z[cl]\d+_\d+_[01]|ze\d+_[01][01])$')
def ok(k):
    m = KEY.match(k)
    return bool(m) and all(1 <= int(x) <= N for x in (m.group(1), m.group(3), m.group(4), m.group(5)) if x) and (not m.group(2) or m.group(2) in REAL)
def flat(d):   # まとめの形 → 項目ごとの数
    f = {'t': d.get('t', 0)}
    for c in 'nh':
        f.update({'%s%d' % (c, i + 1): v for i, v in enumerate(d.get(c, [])) if v})
    for s, arr in d.get('q', {}).items():
        f.update({'q%s_%d%s' % (s, i // 3 + 1, 'abc'[i % 3]): v for i, v in enumerate(arr) if v})
    f.update(d.get('z', {}))
    return f

prev = {}
if os.path.exists(OUT):
    try:
        prev = json.load(open(OUT, encoding='utf-8'))
    except Exception:
        pass
adj = dict(prev.get('adj', {}))
cur = {k: st.get(k, 0) - adj.get(k, 0) for k in set(st) | set(adj) if ok(k)}
if prev:
    B = {k: v for k, v in flat(prev).items() if ok(k)}
    d = {k: cur.get(k, 0) - B.get(k, 0) for k in set(cur) | set(B)}
    tol = lambda x: max(20, abs(x) // 100)   # 箱を読む時刻のずれで、数人ぶんは合わないことがある
    fixed = {}
    def use(k, v):   # 項目 k の今回の増えを v にする（ちがう分は adj へ）
        if v != d.get(k, 0):
            fixed[k] = d.get(k, 0) - v
            adj[k] = adj.get(k, 0) + d.get(k, 0) - v
        d[k] = v
    # 1回遊ぶと、t・n（本当の県）・zx（本当の県×予想）が1つずつ増える。県ごとの遊んだ回数は、zx からも数えられる
    zx, zh = [0] * N, [0] * N
    for k, v in d.items():
        m = re.match(r'^zx\d+_(\d+)_(\d+)$', k)
        if m and v > 0:
            zx[int(m.group(1)) - 1] += v
            if m.group(1) == m.group(2):
                zh[int(m.group(1)) - 1] += v
    dt, dn = d.get('t', 0), [d.get('n%d' % (i + 1), 0) for i in range(N)]
    zx_ok = abs(sum(zx) - dt) <= tol(dt)   # zx の増えが t の増えと合っていれば、zx を信じる
    if not zx_ok:
        print('注意：zx の増え', sum(zx), 'と t の増え', dt, 'が合わない')
    for i in range(N):
        n, h, want = 'n%d' % (i + 1), 'h%d' % (i + 1), zx[i] if zx_ok else max(0, min(dn[i], zx[i]))
        d.setdefault(n, 0); d.setdefault(h, 0)
        if abs(d[n] - want) > tol(want):
            use(n, want)
        if abs(d[h] - zh[i]) > tol(zh[i]) or not 0 <= d[h] <= d[n] + tol(d[n]):
            use(h, min(zh[i], d[n]))
    if abs(d.get('t', 0) - sum(d['n%d' % (i + 1)] for i in range(N))) > tol(dt):
        use('t', sum(d['n%d' % (i + 1)] for i in range(N)))
    for k in list(d):   # 答え・記録は、へることはなく、遊んだ回数より多くは増えない
        m = re.match(r'^(?:q\d+_(\d+)[abc]|zx\d+_(\d+)_\d+)$', k)
        if m:
            top = d['n%s' % (m.group(1) or m.group(2))] + tol(0)
        elif k[0] == 'z':
            top = d.get('t', 0) + tol(d.get('t', 0))
        else:
            continue
        if not 0 <= d[k] <= top:
            use(k, 0)
    if fixed:
        print('ありえない増え方を直した項目：', len(fixed), dict(sorted(fixed.items(), key=lambda x: -abs(x[1]))[:20]))
    cur = {k: B.get(k, 0) + v for k, v in d.items()}

q = {}
for k, v in cur.items():
    m = re.match(r'^q(\d+)_(\d+)([abc])$', k)
    if not m:
        continue
    a = q.setdefault(m.group(1), [0] * (3 * N))
    a[3 * (int(m.group(2)) - 1) + 'abc'.index(m.group(3))] = v
out = {
    'v': 1, 'at': int(time.time() * 1000), 't': cur.get('t', 0),
    'n': [cur.get('n%d' % (i + 1), 0) for i in range(N)],
    'h': [cur.get('h%d' % (i + 1), 0) for i in range(N)],
    'q': dict(sorted(q.items(), key=lambda x: int(x[0]))),
    # まちがいの記録（zx=本当の県×予想、zc=確率×当たり、zl=問題数×当たり、ze=10問時点×最後）
    'z': dict(sorted((k, v) for k, v in cur.items() if k[0] == 'z' and v)),
    'f': fields,   # 箱ごとの項目の数（20,000に近づいたら、箱の分け方を見直す）
    'adj': dict(sorted((k, v) for k, v in adj.items() if v)),   # Firestore の値から引いている数（書きかえの分）
}

old_t = prev.get('t', -1)
print('遊んだ人：', old_t, '→', out['t'], '／ 問題', len(q))
if out['t'] <= old_t:
    print('前より増えていないので、そのまま')
    sys.exit(0)
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
print('書きました：', OUT, os.path.getsize(OUT), 'バイト')
