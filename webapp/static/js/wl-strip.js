(function () {
  const strip = document.getElementById("wlTickerStrip");
  const inner = document.getElementById("wlTickerStripInner");
  if (!strip || !inner) return;

  function fmtPct(n) {
    if (n == null || !isFinite(Number(n))) return "—";
    const x = Number(n);
    return (x > 0 ? "+" : "") + x.toFixed(2) + "%";
  }
  function fmtPrice(n) {
    if (n == null || !isFinite(Number(n))) return "—";
    return Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  async function refresh() {
    try {
      const resp = await fetch("/api/watchlist/prices");
      const data = await resp.json();
      const prices = data.prices || {};
      const tickers = Object.keys(prices);
      if (!tickers.length) {
        strip.hidden = true;
        return;
      }
      strip.hidden = false;
      inner.innerHTML = tickers.map(function (t) {
        const p = prices[t];
        if (!p) {
          return '<a class="wl-chip" href="/stock/' + encodeURIComponent(t) + '"><span class="wl-chip-sym">' +
            t + '</span><span class="wl-chip-pct muted">—</span></a>';
        }
        const pct = p.change_pct;
        const cls = pct == null ? "muted" : pct >= 0 ? "pos" : "neg";
        const arrow = pct == null ? "" : pct >= 0 ? "▲ " : "▼ ";
        return '<a class="wl-chip" href="/stock/' + encodeURIComponent(t) + '" title="' +
          t + " " + fmtPrice(p.price) + '">' +
          '<span class="wl-chip-sym">' + t + "</span>" +
          '<span class="wl-chip-pct ' + cls + '">' + arrow + fmtPct(pct) + "</span></a>";
      }).join("");
    } catch (e) {
      /* silent */
    }
  }

  refresh();
  setInterval(refresh, 60000);
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) refresh();
  });
})();
