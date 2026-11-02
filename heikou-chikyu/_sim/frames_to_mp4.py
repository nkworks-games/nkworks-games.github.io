"""3D の連番画像（shots.py の出力 cutNNN/f_0001.png …）を、カットごとの mp4 にする

  python3 frames_to_mp4.py ~/heikou-renders            # その中の cutNNN フォルダをすべて
  python3 frames_to_mp4.py ~/heikou-renders 019 053    # 一部だけ

--step 2 で1コマおきに描いた場合は、間のコマを動きから補って 24コマ/秒にする（ffmpeg の minterpolate）。
できた mp4 は、同じ場所に cutNNN.mp4 として置く（make_roughcut.py は out/renders/final を見る）。
"""
import glob
import os
import re
import subprocess
import sys


def frames(d):
    fs = sorted(glob.glob(os.path.join(d, 'f_*.png')))
    nums = [int(re.findall(r'(\d+)\.png$', f)[0]) for f in fs]
    return fs, nums


def encode(d, out):
    fs, nums = frames(d)
    if len(fs) < 2:
        print('コマが足りない', d)
        return
    step = min(b - a for a, b in zip(nums, nums[1:]))
    if any(b - a != step for a, b in zip(nums, nums[1:])):
        print('抜けたコマがある（描き終わっていない？）', d)
        return
    rate = 24 / step
    vf = 'minterpolate=fps=24:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1' if step > 1 else 'null'
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-framerate', '%g' % rate, '-pattern_type', 'glob', '-i', os.path.join(d, 'f_*.png'),
                    '-vf', vf, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '16', '-preset', 'slow', '-r', '24', out], check=True)
    print('できた', out, '（%d コマ・%d コマおき）' % (len(fs), step))


def main():
    root = os.path.expanduser(sys.argv[1]) if len(sys.argv) > 1 else 'out/renders/final'
    only = set(sys.argv[2:])
    for d in sorted(glob.glob(os.path.join(root, 'cut*'))):
        no = os.path.basename(d)[3:]
        if not os.path.isdir(d) or (only and no not in only):
            continue
        encode(d, os.path.join(root, 'cut%s.mp4' % no))


if __name__ == '__main__':
    main()
