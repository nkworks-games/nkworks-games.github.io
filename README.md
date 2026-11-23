# nkworks-games.github.io
N.K. Works site root (app-ads.txt)

## 人数の計測（Cloudflare Web Analytics）
新しいページ（ゲーム・説明ページなど）を作ったら、`</body>` の直前に次の1行を入れる。入れないページは人数が数えられない（nkworks-games.com は DNS only なので、Cloudflare が自動では入れてくれない）。

```html
<!-- Cloudflare Web Analytics --><script type='module' src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "747b6a03970a41c9aae7804501eb411a"}'></script><!-- End Cloudflare Web Analytics -->
```
