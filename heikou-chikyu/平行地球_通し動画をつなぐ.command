#!/bin/bash
# ダブルクリックで：Mac で描いた 3D と、クラウドで作った材料（図の動画・字幕・字体）をつないで、
# 第1回の通し動画（約12分）を作る → heikou-chikyu/_sim/out/roughcut/ep1.mp4
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
SIM=heikou-chikyu/_sim
pause() { echo; read -n 1 -s -r -p "何かキーを押すと閉じます"; echo; }

echo "===== 最新を取ってきます ====="
git pull --ff-only || echo "（最新を取れませんでした。いまの手もとのまま続けます）"

# 1. 描いた 3D（平行地球_本番を描く.command が out/renders/final に集めたもの）
n=$(ls $SIM/out/renders/final/cut*.mp4 2>/dev/null | wc -l | tr -d ' ')
if [ "$n" -lt 30 ]; then
  echo "描いた 3D の動画が ${n} 本しかありません（30 本のはず）。先に「平行地球_本番を描く.command」を流してください。"
  pause; exit 1
fi
echo "描いた 3D の動画：${n} 本"

# 2. 材料一式（はじめの1回だけ、ダウンロードフォルダの heikou-ep1-pack.zip を展開する）
if [ ! -f $SIM/out/script/cuts_v4.csv ]; then
  Z=$(ls -t "$HOME/Downloads"/heikou-ep1-pack*.zip 2>/dev/null | head -1)
  if [ -z "$Z" ]; then
    echo "材料一式（heikou-ep1-pack.zip）が「ダウンロード」フォルダにありません。"
    echo "Claude の会話にある zip を保存してから、もう一度ダブルクリックしてください。"
    pause; exit 1
  fi
  echo "===== 材料一式を展開します：$Z ====="
  ditto -x -k "$Z" $SIM || { echo "展開できませんでした。この画面を Claude に送ってください。"; pause; exit 1; }
fi

# 3. Python の道具（numpy・pillow）。はじめの1回だけ、専用の場所（~/heikou-venv）に入れる
VENV="$HOME/heikou-venv"
if [ ! -x "$VENV/bin/python" ] || ! "$VENV/bin/python" -c "import numpy, PIL" 2>/dev/null; then
  echo "===== はじめの1回だけ：Python の道具を入れます（1〜2分）====="
  python3 -m venv "$VENV" && "$VENV/bin/pip" install -q numpy pillow || {
    echo "Python の道具を入れられませんでした。この画面を Claude に送ってください。"; pause; exit 1; }
fi

# 4. ナレーションの声（out/voice に VOICEVOX の wav があれば入れる。なければ声なしで作る）
nv=$(ls $SIM/out/voice/*.wav 2>/dev/null | wc -l | tr -d ' ')
echo "ナレーションの声：${nv} 個（0 なら声なしで作ります。声はあとから入れて、もう一度ダブルクリックすれば入ります）"

echo "===== つなぎます（10〜30分ほど）====="
"$VENV/bin/python" $SIM/make_roughcut.py --final || { echo "途中で止まりました。この画面を Claude に送ってください。"; pause; exit 1; }
open $SIM/out/roughcut
echo "===== できました：$SIM/out/roughcut/ep1.mp4 ====="
pause
