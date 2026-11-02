"""並行地球 第1回：粗いつなぎ（通し確認用の動画）を作る

カット表（out/script/cuts_v2.csv）の順と秒数で、手元にある素材をつなぐ。
  図・地図・文字：out/video/cutNNN.mp4（make_graphics.py で作ったもの）
  3D           ：out/renders/final/cutNNN.mp4（frames_to_mp4.py で作る）か cutNNN.png。なければ動きの確かめ用の小さい動画（motion）、
                 それもなければ確認用の静止画
                 （out/renders/preview2 → preview の順に探す）をゆっくり寄せて使う
  どちらもない ：カットの内容を書いた仮の画面

  python3 make_roughcut.py            # 字幕（ナレーション）とカット番号を焼き込む
  python3 make_roughcut.py --clean    # 何も焼き込まない（編集ソフトに持っていく用）

ナレーション：out/voice/ に VOICEVOX で書き出した音声（001_….wav のように番号で始まるもの）があれば、
  out/script/voicevox_ep1.txt の行の順＝ナレーションのあるカットの順に、各カットの頭（0.3秒後）へ置く。
  音声がカットより長いときは、その一覧を最後に出す（カットの秒数を直す目安）。

出力：out/roughcut/roughcut.mp4（音声がなければ無音）
"""
import csv
import glob
import os
import re
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw

from motion import BG, H, MUTED, TEXT, TEXT2, W, font

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'out', 'roughcut')
SEG = os.path.join(OUT, 'seg')
FPS = 24
ENC = ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', '-preset', 'veryfast', '-r', str(FPS)]


def ff(args):
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error'] + args, check=True)


def wrap(s, n=30):
    """日本語を、句読点の後ろを優先して n 文字前後で折り返す"""
    lines, cur = [], ''
    for ch in s:
        cur += ch
        if len(cur) >= n or (len(cur) >= n * 0.6 and ch in '。、'):
            lines.append(cur)
            cur = ''
    if cur:
        lines.append(cur)
    return lines


_SUBS = None


def subtitle_of(row):
    """字幕の文（make_overlays.py が作った、数字を算用数字にしたもの）。なければナレーションのまま"""
    global _SUBS
    if _SUBS is None:
        p = os.path.join(HERE, 'out', 'script', 'subtitles_ep1.csv')
        _SUBS = {r['no']: r['subtitle'] for r in csv.DictReader(open(p, encoding='utf-8'))} if os.path.exists(p) else {}
    return _SUBS.get(row['no'], row['narration']).strip()


def overlay_png(row, path, clean):
    """重ねる透明な画像：左上の「どの歴史・何年目」（out/overlay/hudNNN.png）＋字幕とカット番号（確認用）"""
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    hud = os.path.join(HERE, 'out', 'overlay', 'hud%s.png' % row['no'])
    if not clean and os.path.exists(hud):
        img.alpha_composite(Image.open(hud).convert('RGBA'))
    if not clean:
        d = ImageDraw.Draw(img)
        lines = wrap(subtitle_of(row))[-3:]
        y = H - 70 - 58 * len(lines)
        for s in lines:
            w = d.textlength(s, font=font(40))
            d.rounded_rectangle([W / 2 - w / 2 - 18, y - 6, W / 2 + w / 2 + 18, y + 52], radius=8, fill=(0, 0, 0, 150))
            d.text((W / 2, y + 23), s, font=font(40), fill=TEXT + (255,), anchor='mm')
            y += 58
        tag = '%s　%s　%s' % (row['no'], row['kind'], row['label'])
        tw = d.textlength(tag, font=font(22))
        d.rounded_rectangle([W - 60 - tw, 112, W - 44, 146], radius=6, fill=(0, 0, 0, 120))
        d.text((W - 52, 129), tag, font=font(22), fill=TEXT2 + (255,), anchor='rm')
    img.save(path)


def placeholder(row, path):
    img = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((W / 2, H / 2 - 60), '（素材まだ）%s' % row['kind'], font=font(40), fill=MUTED, anchor='mm')
    for i, s in enumerate(wrap(row['visual'], 34)):
        d.text((W / 2, H / 2 + 10 + i * 56), s, font=font(40), fill=TEXT, anchor='mm')
    img.save(path)


def find_3d(no):
    for p in ('final/cut%s.mp4' % no, 'final/cut%s.png' % no, 'motion/cut%s.mp4' % no, 'preview5/cut%s.png' % no, 'preview4/cut%s.png' % no, 'preview3/cut%s.png' % no, 'preview2/cut%s.png' % no, 'preview/cut%s.png' % no):
        f = os.path.join(HERE, 'out', 'renders', p)
        if os.path.exists(f):
            return f
    return None


def segment(row, clean):
    no, sec = row['no'], int(row['sec'])
    out = os.path.join(SEG, 'cut%s.mp4' % no)
    ov = os.path.join(SEG, 'ov%s.png' % no)
    overlay_png(row, ov, clean)
    n = sec * FPS
    src = None
    if row['kind'].startswith('3D'):
        src = find_3d(no)
    else:
        f = os.path.join(HERE, 'out', 'video', 'cut%s.mp4' % no)
        src = f if os.path.exists(f) else None
    if src is None:
        ph = os.path.join(SEG, 'ph%s.png' % no)
        placeholder(row, ph)
        src = ph
    if src.endswith('.mp4'):
        # 長さをカット表にそろえる（足りなければ最後のコマで延ばす）
        ff(['-i', src, '-i', ov, '-filter_complex',
            '[0:v]fps=%d,scale=%d:%d,tpad=stop_mode=clone:stop_duration=%d[v];[v][1:v]overlay=0:0' % (FPS, W, H, sec),
            '-frames:v', str(n)] + ENC + ['-an', out])
    else:
        # 静止画：ゆっくり寄せる（4% だけ）
        ff(['-loop', '1', '-i', src, '-i', ov, '-filter_complex',
            '[0:v]scale=%d:%d,zoompan=z=\'1+0.04*on/%d\':x=\'iw/2-(iw/zoom/2)\':y=\'ih/2-(ih/zoom/2)\':d=%d:s=%dx%d:fps=%d[v];[v][1:v]overlay=0:0'
            % (W * 2, H * 2, n, n, W, H, FPS),
            '-frames:v', str(n)] + ENC + ['-an', out])
    return out


SR = 48000


def load_wav(path):
    """どんな形式の音声も 48kHz・ステレオ・float にそろえて読む"""
    raw = subprocess.run(['ffmpeg', '-loglevel', 'error', '-i', path, '-f', 's16le', '-ac', '2', '-ar', str(SR), '-'],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.int16).reshape(-1, 2).astype(np.float32) / 32768.0


def voice_track(rows, path):
    """ナレーションを並べた1本の音声。なければ None"""
    files = sorted(glob.glob(os.path.join(HERE, 'out', 'voice', '*.wav')))
    files = [f for f in files if re.match(r'^\d+', os.path.basename(f))]
    if not files:
        return None
    files.sort(key=lambda f: int(re.match(r'^(\d+)', os.path.basename(f)).group(1)))
    narrated = [r for r in rows if r['narration'].strip()]
    if len(files) != len(narrated):
        print('注意：音声 %d 個、ナレーションのあるカット %d 個（順に対応させる）' % (len(files), len(narrated)))
    start, t = {}, 0.0
    for r in rows:
        start[r['no']] = t
        t += int(r['sec'])
    buf = np.zeros((int(t * SR) + SR, 2), np.float32)
    over = []
    for f, r in zip(files, narrated):
        a = load_wav(f)
        i0 = int((start[r['no']] + 0.3) * SR)
        n = min(len(a), len(buf) - i0)
        buf[i0:i0 + n] += a[:n]
        dur = len(a) / SR
        if dur + 0.3 > int(r['sec']):
            over.append((r['no'], dur, int(r['sec'])))
    for no, dur, sec in over:
        print('長い：カット %s の音声 %.1f秒（カット %d秒）' % (no, dur, sec))
    pcm = (np.clip(buf, -1, 1) * 32767).astype(np.int16)
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 's16le', '-ac', '2', '-ar', str(SR), '-i', '-', path],
                   input=pcm.tobytes(), check=True)
    return path


def main():
    clean = '--clean' in sys.argv
    os.makedirs(SEG, exist_ok=True)
    rows = list(csv.DictReader(open(os.path.join(HERE, 'out', 'script', 'cuts_v2.csv'), encoding='utf-8')))
    segs = []
    for r in rows:
        segs.append(segment(r, clean))
        print('cut', r['no'], r['sec'], 's', flush=True)
    lst = os.path.join(SEG, 'list.txt')
    with open(lst, 'w') as f:
        for p in segs:
            f.write("file '%s'\n" % p)
    name = 'roughcut_clean.mp4' if clean else 'roughcut.mp4'
    # 音声：ナレーションがあれば並べたもの、なければ無音（編集ソフトで扱いやすいように）
    vt = voice_track(rows, os.path.join(OUT, 'voice.wav'))
    audio = ['-i', vt] if vt else ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
    ff(['-f', 'concat', '-safe', '0', '-i', lst] + audio + ['-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', os.path.join(OUT, name)])
    total = sum(int(r['sec']) for r in rows)
    print('できた', os.path.join(OUT, name), '%d分%02d秒' % (total // 60, total % 60))


if __name__ == '__main__':
    main()
