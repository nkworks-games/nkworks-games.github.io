# 素材

## human.npz（人の体）

- 出どころ：MakeHuman（https://github.com/makehumancommunity/makehuman）の `makehuman/data` のうち
  基本の体（3dobjs/base.obj）、体つきの差分（targets/macrodetails）、骨格（rigs/default.mhskel）、骨ごとの重み（rigs/default_weights.mhw）
- 利用条件：CC0 1.0（MakeHuman の LICENSE.md「C. The license for the bundled assets」。各ファイルの頭にも「explicitly released as CC0」とある）。
  クレジットの表記は義務ではないが、動画の概要欄に「人の体：MakeHuman（CC0）」と書いておくとよい
- 作り方：`python3 heikou-chikyu/_blender/kit/human_data.py <makehuman/data のフォルダ>`
- MakeHuman のプログラム（AGPL）は使っていない。ファイルの形式を読んで、姿勢づけ・髪・布・材質はこのキット（kit/human.py）で作っている
- 髪の形・肌の模様・服の素材（MakeHuman の別の素材集）は使っていない
