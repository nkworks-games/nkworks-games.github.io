// 試行のまとめを、画面とは別のスレッドで計算する
importScripts('model.js');
self.onmessage = function (e) {
  var d = e.data;
  try {
    for (var i = 0; i < d.trials; i++) {
      var opts = Object.assign({}, d.options, { seed: d.seedFrom + i });
      var digests = d.worlds.map(function (w) { return HeikouModel.digest(HeikouModel.simulate(w, opts)); });
      self.postMessage({ type: 'trial', i: i, digests: digests });
    }
    self.postMessage({ type: 'done' });
  } catch (err) {
    self.postMessage({ type: 'error', message: String(err && err.message || err) });
  }
};
