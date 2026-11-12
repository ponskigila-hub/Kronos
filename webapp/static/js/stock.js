(function () {
  const form = document.getElementById("stkForm");
  const input = document.getElementById("stkTicker");
  const statusEl = document.getElementById("stkStatus");
  const view = document.getElementById("stkView");
  const chartSvg = document.getElementById("stkChartSvg");
  const chartStatus = document.getElementById("stkChartStatus");
  let currentTicker = "";
  let currentRange = "1M";
  let chartToken = 0;

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function fmtMoney(n) {
    if (n == null || !isFinite(Number(n))) return "—";
    n = Number(n);
    const sign = n < 0 ? "-" : "";
    n = Math.abs(n);
    if (n >= 1e12) return sign + (n / 1e12).toFixed(2) + "T";
    if (n >= 1e9) return sign + (n / 1e9).toFixed(2) + "B";
    if (n >= 1e6) return sign + (n / 1e6).toFixed(2) + "M";
    return sign + n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  function fmtPct(n) {
    if (n == null || !isFinite(Number(n))) return "—";
    const x = Number(n);
    return (x > 0 ? "+" : "") + x.toFixed(2) + "%";
  }
  function fmtPrice(n) {
    if (n == null || !isFinite(Number(n))) return "—";
    return Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function clsPct(n) {
    if (n == null || !isFinite(Number(n))) return "";
    return Number(n) >= 0 ? "pos" : "neg";
  }

  function setActions(ticker) {
    const f = document.getElementById("stkLinkForecast");
    const n = document.getElementById("stkLinkNews");
    const ins = document.getElementById("stkLinkInsights");
    const chat = document.getElementById("stkLinkChat");
    if (f) f.href = "/forecast?ticker=" + encodeURIComponent(ticker);
    if (n) n.href = "/news?ticker=" + encodeURIComponent(ticker);
    if (ins) ins.href = "/insights";
    if (chat) chat.href = "/chat?prefill=" + encodeURIComponent("full wall street breakdown on " + ticker);
  }

  function drawChart(points, rangeChangePct) {
    chartSvg.innerHTML = "";
    if (!points || points.length < 2) {
      chartStatus.hidden = false;
      chartStatus.textContent = "Not enough points for this range.";
      return;
    }
    chartStatus.hidden = true;
    const closes = points.map((p) => p.c);
    const min = Math.min(...closes);
    const max = Math.max(...closes);
    const w = 640, h = 220;
    const padL = 44, padR = 12, padT = 12, padB = 24;
    const range = max - min || 1;
    const stepX = (w - padL - padR) / (points.length - 1);
    const yOf = (v) => padT + (1 - (v - min) / range) * (h - padT - padB);
    const coords = points.map((p, i) => [padL + i * stepX, yOf(p.c)]);
    const poly = coords.map(([x, y]) => x.toFixed(1) + "," + y.toFixed(1)).join(" ");
    const up = rangeChangePct == null ? closes[closes.length - 1] >= closes[0] : rangeChangePct >= 0;
    const stroke = up ? "#2ee6a8" : "#f85149";
    const area =
      poly + " " + (padL + (points.length - 1) * stepX).toFixed(1) + "," + (h - padB) +
      " " + padL + "," + (h - padB);

    const mid = (min + max) / 2;
    const gridYs = [max, mid, min];
    let grid = "";
    gridYs.forEach(function (gv) {
      const gy = yOf(gv);
      grid +=
        '<line x1="' + padL + '" y1="' + gy.toFixed(1) + '" x2="' + (w - padR) +
        '" y2="' + gy.toFixed(1) + '" class="stk-grid-line"/>' +
        '<text x="' + (padL - 6) + '" y="' + (gy + 3).toFixed(1) +
        '" class="stk-axis-label" text-anchor="end">' + fmtPrice(gv) + "</text>";
    });
    grid +=
      '<text x="' + padL + '" y="' + (h - 6) + '" class="stk-axis-label">' + esc(points[0].t) + "</text>" +
      '<text x="' + (w - padR) + '" y="' + (h - 6) + '" class="stk-axis-label" text-anchor="end">' +
      esc(points[points.length - 1].t) + "</text>";

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 " + w + " " + h);
    svg.setAttribute("class", "stk-svg");
    svg.innerHTML =
      '<defs><linearGradient id="stkGrad" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0%" stop-color="' + stroke + '" stop-opacity="0.35"/>' +
      '<stop offset="100%" stop-color="' + stroke + '" stop-opacity="0"/>' +
      "</linearGradient></defs>" + grid +
      '<polygon points="' + area + '" fill="url(#stkGrad)"/>' +
      '<polyline points="' + poly + '" fill="none" stroke="' + stroke +
      '" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>';

    const hoverLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
    hoverLine.setAttribute("y1", padT);
    hoverLine.setAttribute("y2", h - padB);
    hoverLine.setAttribute("class", "stk-hover-line");
    hoverLine.style.display = "none";
    svg.appendChild(hoverLine);

    const hoverDot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    hoverDot.setAttribute("r", "5");
    hoverDot.setAttribute("fill", stroke);
    hoverDot.setAttribute("stroke", "#0a1628");
    hoverDot.setAttribute("stroke-width", "2");
    hoverDot.style.display = "none";
    svg.appendChild(hoverDot);

    const tip = document.createElement("div");
    tip.className = "stk-chart-tip";
    tip.style.display = "none";

    chartSvg.appendChild(svg);
    chartSvg.appendChild(tip);

    svg.addEventListener("mousemove", function (e) {
      const rect = svg.getBoundingClientRect();
      const rel = ((e.clientX - rect.left) / rect.width) * w;
      let idx = Math.round((rel - padL) / stepX);
      idx = Math.max(0, Math.min(points.length - 1, idx));
      const [x, y] = coords[idx];
      hoverLine.setAttribute("x1", x);
      hoverLine.setAttribute("x2", x);
      hoverLine.style.display = "block";
      hoverDot.setAttribute("cx", x);
      hoverDot.setAttribute("cy", y);
      hoverDot.style.display = "block";
      tip.style.display = "block";
      tip.style.left = Math.min(90, Math.max(10, (x / w) * 100)) + "%";
      tip.innerHTML = "<strong>" + fmtPrice(points[idx].c) + "</strong><span>" + esc(points[idx].t) + "</span>";
    });
    svg.addEventListener("mouseleave", function () {
      hoverLine.style.display = "none";
      hoverDot.style.display = "none";
      tip.style.display = "none";
    });
  }

  async function loadChart(ticker, range) {
    const token = ++chartToken;
    chartStatus.hidden = false;
    chartStatus.textContent = "Loading chart…";
    try {
      const resp = await fetch("/api/chart/" + encodeURIComponent(ticker) + "?range=" + encodeURIComponent(range));
      const data = await resp.json();
      if (token !== chartToken) return;
      if (!resp.ok) {
        if (data.fallback_range) {
          currentRange = data.fallback_range;
          document.querySelectorAll(".stk-range-btn").forEach((b) =>
            b.classList.toggle("active", b.dataset.range === currentRange)
          );
          return loadChart(ticker, currentRange);
        }
        chartStatus.textContent = data.error || "Chart unavailable";
        return;
      }
      document.getElementById("stkPrice").textContent = "$" + fmtPrice(data.latest_price);
      const ch = document.getElementById("stkChange");
      ch.textContent = (data.day_change_pct >= 0 ? "▲ " : "▼ ") + fmtPct(data.day_change_pct);
      ch.className = "stk-change " + clsPct(data.day_change_pct);
      const vs = document.getElementById("stkVsClose");
      if (vs) {
        vs.textContent = (data.day_change >= 0 ? "▲ +" : "▼ ") + fmtPrice(Math.abs(data.day_change)) + " vs previous close";
        vs.className = "stk-vs-close " + clsPct(data.day_change);
      }
      const asof = document.getElementById("stkAsof");
      if (asof) asof.textContent = "Range " + range + " · Yahoo Finance (may be delayed)";
      drawChart(data.points, data.range_change_pct);
    } catch (e) {
      if (token === chartToken) chartStatus.textContent = "Could not load chart.";
    }
  }

  async function loadProfile(ticker) {
    try {
      const resp = await fetch("/api/stock-profile/" + encodeURIComponent(ticker));
      const d = await resp.json();
      if (!resp.ok) throw new Error(d.error || "Profile failed");
      document.getElementById("stkSymbol").textContent = d.ticker || ticker;
      document.getElementById("stkName").textContent = d.name || ticker;
      const bits = [d.exchange, d.sector, d.industry].filter(Boolean);
      document.getElementById("stkMeta").textContent = bits.join(" · ");

      const stats = [
        ["Market Cap", fmtMoney(d.market_cap)],
        ["P/E (TTM)", d.pe_ratio != null ? Number(d.pe_ratio).toFixed(1) : "—"],
        ["Forward P/E", d.forward_pe != null ? Number(d.forward_pe).toFixed(1) : "—"],
        ["EPS", d.eps != null ? Number(d.eps).toFixed(2) : "—"],
        ["Beta", d.beta != null ? Number(d.beta).toFixed(2) : "—"],
        ["Div. Yield", d.dividend_yield != null ? (Number(d.dividend_yield) * 100).toFixed(2) + "%" : "—"],
        ["52W High", fmtPrice(d.fifty_two_week_high)],
        ["52W Low", fmtPrice(d.fifty_two_week_low)],
        ["Rev. Growth", d.revenue_growth != null ? fmtPct(Number(d.revenue_growth) * 100) : "—"],
      ];
      document.getElementById("stkStats").innerHTML = stats.map(function (row) {
        return '<div class="stk-stat"><span>' + esc(row[0]) + "</span><strong>" + esc(row[1]) + "</strong></div>";
      }).join("");

      const a = d.analyst || {};
      const box = document.getElementById("stkAnalyst");
      if (a.target_mean || a.recommendation) {
        const rec = (a.recommendation || "—").toString().replace(/_/g, " ");
        const score = a.rating_score;
        // Simple ring label
        box.innerHTML =
          '<div class="stk-consensus">' +
          '<div class="stk-consensus-ring"><span class="stk-consensus-label">' + esc(rec) + "</span></div>" +
          '<div class="stk-consensus-meta">' +
          '<div class="stk-stat"><span>Mean Target</span><strong>' + fmtPrice(a.target_mean) + "</strong></div>" +
          '<div class="stk-stat"><span>Low / High</span><strong>' + fmtPrice(a.target_low) + " / " + fmtPrice(a.target_high) + "</strong></div>" +
          '<div class="stk-stat"><span>Analysts</span><strong>' + (a.num_analysts != null ? a.num_analysts : "—") + "</strong></div>" +
          "</div></div>";
      } else {
        box.innerHTML = '<p class="stk-perf-empty">No consensus data.</p>';
      }

      const about = document.getElementById("stkAboutCard");
      if (d.description) {
        about.hidden = false;
        document.getElementById("stkAbout").textContent = d.description;
      } else {
        about.hidden = true;
      }
    } catch (e) {
      document.getElementById("stkName").textContent = "Profile limited";
    }
  }

  async function loadPerformance(ticker) {
    const el = document.getElementById("stkPerf");
    el.innerHTML = "<div class='stk-perf-empty'>Loading…</div>";
    try {
      const resp = await fetch("/api/stock/performance/" + encodeURIComponent(ticker));
      const d = await resp.json();
      if (!resp.ok) throw new Error(d.error || "Failed");
      const order = ["1W", "1M", "3M", "YTD", "1Y", "5Y"];
      const periods = d.periods || {};
      el.innerHTML =
        order.map(function (k) {
          const v = periods[k];
          return '<div class="stk-perf-cell"><span>' + k + '</span><strong class="' +
            clsPct(v) + '">' + (v != null && v >= 0 ? "▲ " : v != null ? "▼ " : "") + fmtPct(v) + "</strong></div>";
        }).join("") +
        '<div class="stk-perf-cell"><span>vs 52W high</span><strong class="' + clsPct(d.from_high_pct) + '">' +
        fmtPct(d.from_high_pct) + "</strong></div>" +
        '<div class="stk-perf-cell"><span>vs 52W low</span><strong class="' + clsPct(d.from_low_pct) + '">' +
        fmtPct(d.from_low_pct) + "</strong></div>";
    } catch (e) {
      el.innerHTML = "<div class='stk-perf-empty'>" + esc(e.message || "Unavailable") + "</div>";
    }
  }


  async function loadTechnical(ticker) {
    const body = document.getElementById("stkTechBody");
    const flags = document.getElementById("stkTechFlags");
    if (!body) return;
    body.textContent = "Loading technical read…";
    if (flags) flags.innerHTML = "";
    try {
      const resp = await fetch("/api/stock/technical/" + encodeURIComponent(ticker));
      const d = await resp.json();
      if (!resp.ok) throw new Error(d.error || "Failed");
      if (flags) {
        const chips = [];
        if (d.trend) chips.push('<span class="stk-tech-chip">' + esc(d.trend) + " trend</span>");
        if (d.rsi_14 != null) chips.push('<span class="stk-tech-chip">RSI ' + Number(d.rsi_14).toFixed(1) + "</span>");
        if (d.support_20 != null) chips.push('<span class="stk-tech-chip">Supp ' + fmtPrice(d.support_20) + "</span>");
        if (d.resistance_20 != null) chips.push('<span class="stk-tech-chip">Res ' + fmtPrice(d.resistance_20) + "</span>");
        flags.innerHTML = chips.join("");
      }
      let s = esc(d.text || "");
      s = s.replace(/^### (.+)$/gm, "<h4>$1</h4>");
      s = s.replace(/^## (.+)$/gm, "<h3>$1</h3>");
      s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
      s = s.replace(/^- (.+)$/gm, "<div class='rd-md-li'>• $1</div>");
      s = s.replace(/\n\n/g, "</p><p>");
      s = s.replace(/\n/g, "<br>");
      body.innerHTML = "<p>" + s + "</p>";
      if (d.disclaimer) {
        body.innerHTML += "<p class='stk-tech-disc'>" + esc(d.disclaimer) + "</p>";
      }
    } catch (e) {
      body.textContent = e.message || "Technical analysis unavailable.";
    }
  }

  async function showTicker(ticker) {
    ticker = (ticker || "").trim().toUpperCase();
    if (!ticker) return;
    currentTicker = ticker;
    input.value = ticker;
    view.hidden = false;
    statusEl.hidden = false;
    statusEl.textContent = "Loading " + ticker + "…";
    setActions(ticker);
    try { history.replaceState(null, "", "/stock/" + encodeURIComponent(ticker)); } catch (e) {}
    await Promise.all([loadChart(ticker, currentRange), loadProfile(ticker), loadPerformance(ticker), loadTechnical(ticker)]);
    statusEl.textContent = ticker + " · Yahoo Finance";
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    showTicker(input.value);
  });

  document.getElementById("stkRanges").addEventListener("click", function (e) {
    const btn = e.target.closest(".stk-range-btn");
    if (!btn || !currentTicker) return;
    currentRange = btn.dataset.range;
    document.querySelectorAll(".stk-range-btn").forEach(function (b) {
      b.classList.toggle("active", b === btn);
    });
    loadChart(currentTicker, currentRange);
  });

  const pre = (input.value || "").trim();
  if (pre) showTicker(pre);
})();
