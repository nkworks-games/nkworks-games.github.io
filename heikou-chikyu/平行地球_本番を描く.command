#!/bin/bash
# ダブルクリックで：最新を取ってきて、第1回の本番の 3D を続きから描く。
# 途中で窓を閉じても、描き終わった絵は残る。もう一度ダブルクリックすると続きから描く。
cd "$(dirname "$0")/.."
# 最新を取ってきて、このファイル自身が新しくなっていたら、新しいほうで始め直す
if [ -z "$HEIKOU_PULLED" ]; then
  echo "===== 最新を取ってきます ====="
  git pull --ff-only || echo "（最新を取れませんでした。いまの手もとのまま続けます）"
  export HEIKOU_PULLED=1
  exec bash "$0" "$@"
fi
echo
echo "===== 描きます（試行 32 回・止めても続きから）====="
bash heikou-chikyu/_blender/render_ep1.sh
echo
echo "===== 終わりました（または止まりました）。もう一度ダブルクリックすると、続きから描きます ====="
