#!/bin/bash
# ダブルクリックで：Mac で描いた 3D と、クラウドで作った材料（図の動画・字幕・字体）をつないで、
# 第1回の通し動画（約12分）を作る → heikou-chikyu/_sim/out/roughcut/ep1.mp4
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
SIM=heikou-chikyu/_sim
pause() { echo; read -n 1 -s -r -p "何かキーを押すと閉じます"; echo; }

# 最新を取ってきて、このファイル自身が新しくなっていたら、新しいほうで始め直す
if [ -z "$HEIKOU_PULLED" ]; then
  echo "===== 最新を取ってきます ====="
  git pull --ff-only || echo "（最新を取れませんでした。いまの手もとのまま続けます）"
  export HEIKOU_PULLED=1
  exec bash "$0" "$@"
fi

# 1. 描いた 3D：描いた所（~/heikou-renders）から集める（どのコピーのリポジトリで描いても、描いた物はそこにある）
R="$HOME/heikou-renders"
mkdir -p $SIM/out/renders/final
for f in "$R"/cut*.mp4 "$R"/cut*.png "$R"/anchors_cut*.json; do
  [ -e "$f" ] && cp -p "$f" $SIM/out/renders/final/
done
n=$(ls $SIM/out/renders/final/cut*.mp4 2>/dev/null | wc -l | tr -d ' ')
if [ "$n" -lt 30 ]; then
  echo "描いた 3D の動画が ${n} 本しかありません（30 本のはず。$R を見ました）。"
  echo "先に「平行地球_本番を描く.command」を流してください。"
  pause; exit 1
fi
echo "描いた 3D の動画：${n} 本"

# 2. 材料一式（図の動画・字幕・字体など）。はじめの1回だけ、zip か、前に展開したフォルダから入れる
if [ ! -f $SIM/out/script/cuts_v4.csv ]; then
  HERE_OUT="$(cd $SIM && pwd)/out"
  Z=$( (ls -t "$HOME/Downloads"/heikou-ep1-pack*.zip "$HOME/Desktop"/heikou-ep1-pack*.zip 2>/dev/null; \
        mdfind -name "heikou-ep1-pack" 2>/dev/null | grep -i '\.zip$') | head -1)
  if [ -n "$Z" ]; then
    echo "===== 材料一式を展開します：$Z ====="
    ditto -x -k "$Z" $SIM || { echo "展開できませんでした。この画面を Claude に送ってください。"; pause; exit 1; }
  else
    # zip が見つからないときは、前に展開した場所（別のコピーのリポジトリなど）を探して写す
    SRC=""
    while IFS= read -r p; do
      o="$(dirname "$(dirname "$p")")"
      if [ "$o" != "$HERE_OUT" ] && [ -f "$o/video/cut007.mp4" ] && [ -f "$o/fonts/ipag.ttf" ]; then SRC="$o"; break; fi
    done < <(mdfind -name "cuts_v4.csv" 2>/dev/null)
    if [ -z "$SRC" ]; then
      echo "材料一式（heikou-ep1-pack.zip）が見つかりません。"
      echo "Claude の会話にある zip を「ダウンロード」フォルダに保存してから、もう一度ダブルクリックしてください。"
      pause; exit 1
    fi
    echo "===== 材料一式を写します：$SRC ====="
    for d in script overlay video main verify-tide fonts; do
      [ -d "$SRC/$d" ] && mkdir -p "$HERE_OUT/$d" && cp -Rp "$SRC/$d/." "$HERE_OUT/$d/"
    done
  fi
  [ -f $SIM/out/script/cuts_v4.csv ] || { echo "材料一式を入れられませんでした。この画面を Claude に送ってください。"; pause; exit 1; }
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
