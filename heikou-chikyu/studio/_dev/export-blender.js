// スタジオの「Blender用 JSON」と同じものを、コマンドで作る
// 使い方：node heikou-chikyu/studio/_dev/export-blender.js <出力ファイル> [条件の JSON]
// 例：node heikou-chikyu/studio/_dev/export-blender.js out.json '{"policy":"demand","storm":true}'
'use strict';
const fs = require('fs');
const M = require('../model.js');

const out = process.argv[2];
if (!out) { console.error('出力ファイルを指定してください'); process.exit(1); }
const options = M.normalizeOptions(JSON.parse(process.argv[3] || '{}'));
const runs = M.simulateAll(M.WORLDS, options);
fs.writeFileSync(out, JSON.stringify(M.blenderExport(runs, M.WORLDS, options)));
console.log('書き出し：' + out + '（' + M.WORLDS.length + 'つの星・' + (options.years + 1) + '年分）');
