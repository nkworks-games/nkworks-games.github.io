"""並行地球：全ショットを組み立てて、scene_check.py で全フレームを点検する（本番レンダーの前に毎回）

    python3 heikou-chikyu/_blender/check_shots.py [--only 022,047] [--step 4] [--out check]
    Mac：python3 の代わりに /Applications/Blender.app/Contents/MacOS/Blender -b --python-expr は使わず、
         下の BLENDER を Blender 本体にして実行する（BLENDER=/Applications/Blender.app/Contents/MacOS/Blender python3 check_shots.py）

ショットごとに shots.py --build-only で .blend を作り、scene_check.py で点検して check/cutNNN/report.json と sheet.png を出す。
最後に check/summary.json（ショットごとの ok と問題の一覧）。点検が済んだ .blend は消す（大きいので）。
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BLENDER = os.environ.get('BLENDER', '')


def run_blender(args):
    """GPU の無い所（BLENDER が未設定＝Python の bpy）では、確認画像を Cycles で描く（scene_check.py の CHECK_ENGINE）"""
    if not BLENDER:
        os.environ.setdefault('CHECK_ENGINE', 'CYCLES')
    if BLENDER:
        cmd = [BLENDER, '-b', '--factory-startup'] + args
    else:   # Python の bpy パッケージ
        script = args[args.index('-P') + 1]
        rest = args[args.index('-P') + 2:]
        pre = args[:args.index('-P')]
        cmd = [sys.executable, script] + rest + [a for a in pre if a.endswith('.blend')]
    return subprocess.run(cmd, capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='')
    ap.add_argument('--step', default='4')
    ap.add_argument('--shots', default='4')
    ap.add_argument('--out', default=os.path.join(HERE, '..', '_sim', 'out', 'check'))
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    ids = [s['id'] for s in json.load(open(os.path.join(HERE, 'shots', 'ep1.json'), encoding='utf-8'))['shots']]
    if a.only:
        ids = [i for i in ids if i in a.only.split(',')]
    summary = {}
    sp = os.path.join(out, 'summary.json')
    if os.path.exists(sp):
        summary = json.load(open(sp, encoding='utf-8'))
    for cid in ids:
        r = run_blender(['-P', os.path.join(HERE, 'shots.py'), '--', '--build-only', '--only', cid, '--out', out])
        blend = os.path.join(out, 'cut%s.blend' % cid)
        if not os.path.exists(blend):
            summary[cid] = dict(ok=False, error='組み立てに失敗', log=r.stdout[-2000:] + r.stderr[-2000:])
            print(cid, '組み立てに失敗', flush=True)
            continue
        d = os.path.join(out, 'cut%s' % cid)
        r = run_blender([blend, '-P', os.path.join(HERE, 'scene_check.py'), '--', blend, '--step', a.step, '--shots', a.shots, '--out', d])
        rep = os.path.join(d, 'report.json')
        if os.path.exists(rep):
            R = json.load(open(rep, encoding='utf-8'))
            summary[cid] = dict(ok=R['ok'], problems=[(p['kind'], p['msg'], p['frame'], p.get('in_camera')) for p in R['problems']],
                                warnings=len(R['warnings']))
        else:
            summary[cid] = dict(ok=False, error='点検に失敗', log=r.stdout[-2000:] + r.stderr[-2000:])
        os.remove(blend)
        for ext in ('.blend1',):
            if os.path.exists(blend + ext[6:]):
                os.remove(blend + ext[6:])
        print(cid, 'OK' if summary[cid].get('ok') else '問題あり %s' % summary[cid].get('problems', summary[cid].get('error')), flush=True)
        json.dump(summary, open(sp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    bad = [k for k, v in summary.items() if not v.get('ok')]
    print('全 %d ショット、問題あり %d：%s' % (len(summary), len(bad), ' '.join(bad)))


if __name__ == '__main__':
    main()
