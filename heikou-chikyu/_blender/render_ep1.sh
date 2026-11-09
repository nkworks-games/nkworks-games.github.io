#!/bin/bash
# 並行地球 第1回：本番の 3D を Mac で描く（第4版のカット表で使う 35 ショットだけ）
#
#   bash heikou-chikyu/_blender/render_ep1.sh            # 描く（途中で止めても、同じコマンドで続きから）
#   bash heikou-chikyu/_blender/render_ep1.sh 013 221    # 一部のショットだけ
#
# 1. Blender で描く（1920×1080・64回・GPU・動くショットは1コマおき）→ ~/heikou-renders
# 2. 連番画像を mp4 に（1コマおきの間は動きから補う）
# 3. mp4・静止画・矢印の先の点の記録（anchors_cutNNN.json）を heikou-chikyu/_sim/out/renders/final/ にまとめる
#    → make_roughcut.py がそれを使う
#
# 目安：M5 の MacBook Air で全部 約26時間（1コマ約22秒）。夜に流し、朝に同じコマンドで続きを流す。
# 先に静止画のショット（013 031 063 070 104）で色と構図を確かめるとよい。
set -e
cd "$(dirname "$0")/../.."
BLENDER=${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}
OUT=${OUT:-$HOME/heikou-renders}
FINAL=heikou-chikyu/_sim/out/renders/final
# 第4版で使うショット（export_shots.py の fit_to_cuts と同じカット表から。使わない 019 023 044 069 074 079 081 092 は描かない）
ALL=001,002,003,004,006,013,020,021,022,031,033,035,036,038,047,048,049,051,055,056,057,063,064,070,076,090,097,104,105,111,112,113,212,213,221
if [ $# -gt 0 ]; then ONLY=$(IFS=,; echo "$*"); else ONLY=$ALL; fi

mkdir -p "$OUT" "$FINAL"
"$BLENDER" -b -P heikou-chikyu/_blender/shots.py -- --gpu --step 2 --resume --only "$ONLY" --out "$OUT"
python3 heikou-chikyu/_sim/frames_to_mp4.py "$OUT"
for f in "$OUT"/cut*.mp4 "$OUT"/cut*.png "$OUT"/anchors_cut*.json; do
  [ -e "$f" ] && cp "$f" "$FINAL"/
done
echo "できた：$FINAL（$(ls "$FINAL" | wc -l | tr -d ' ') ファイル）"
