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
    document.getElementById("stkLinkForecast").href = "/forecast?ticker=" + encodeURIComponent(ticker);
    document.getElementById("stkLinkNews").href = "/news?ticker=" + encodeURIComponent(ticker);
    document.getElementById("stkLinkInsights").href = "/insights";
    document.getElementById("stkLinkChat").href =
      "/chat?prefill=" + encodeURIComponent("full wall street breakdown on " + ticker);
  }

  function drawChart(points, rangeChangePct) {
    chartSvg.innerHTML = "";
    const minEl = document.getElementById("stkChartMin");
    const midEl = document.getElementById("stkChartMid");
    const maxEl = document.getElementById("stkChartMax");
    if (!points || points.length < 2) {
      chartStatus.hidden = false;
      chartStatus.textContent = "Not enough points for this range.";
      minEl.textContent = midEl.textContent = maxEl.textContent = "—";
      return;
    }
    chartStatus.hidden = true;
    const closes = points.map((p) => p.c);
    const min = Math.min(...closes);
    const max = Math.max(...closes);
    const mid = (min + max) / 2;
    minEl.textContent = "Low " + fmtPrice(min);
    midEl.textContent = points[0].t + " → " + points[points.length - 1].t;
    maxEl.textContent = "High " + fmtPrice(max);

    const w = 720, h = 280;
    const padL = 52, padR = 16, padT = 16, padB = 28;
    const range = max - min || 1;
    const stepX = (w - padL - padR) / (points.length - 1);
    const yOf = (v) => padT + (1 - (v - min) / range) * (h - padT - padB);
    const coords = points.map((p, i) => [padL + i * stepX, yOf(p.c)]);
    const poly = coords.map(([x, y]) => x.toFixed(1) + "," + y.toFixed(1)).join(" ");
    const up = rangeChangePct == null ? closes[closes.length - 1] >= closes[0] : rangeChangePct >= 0;
    const stroke = up ? "#3fb950" : "#f85149";
    const area =
      poly +
      " " +
      (padL + (points.length - 1) * stepX).toFixed(1) +
      "," +
      (h - padB) +
      " " +
      padL +
      "," +
      (h - padB);

    // horizontal grid at min / mid / max
    const gridYs = [min, mid, max].map(yOf);

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 " + w + " " + h);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("class", "stk-svg");

    let grid = "";
    gridYs.forEach(function (gy, i) {
      const label = i === 0 ? min : i === 1 ? mid : max;
      grid +=
        '<line x1="' + padL + '" y1="' + gy.toFixed(1) + '" x2="' + (w - padR) +
        '" y2="' + gy.toFixed(1) + '" class="stk-grid-line"/>' +
        '<text x="' + (padL - 8) + '" y="' + (gy + 3).toFixed(1) +
        '" class="stk-axis-label" text-anchor="end">' +
        fmtPrice(label) +
        "</text>";
    });

    // end labels
    const first = points[0].t;
    const last = points[points.length - 1].t;
    grid +=
      '<text x="' + padL + '" y="' + (h - 8) + '" class="stk-axis-label">' + esc(first) + "</text>" +
      '<text x="' + (w - padR) + '" y="' + (h - 8) + '" class="stk-axis-label" text-anchor="end">' +
      esc(last) +
      "</text>";

    svg.innerHTML =
      '<defs><linearGradient id="stkGrad" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0%" stop-color="' + stroke + '" stop-opacity="0.28"/>' +
      '<stop offset="100%" stop-color="' + stroke + '" stop-opacity="0"/>' +
      "</linearGradient></defs>" +
      grid +
      '<polygon points="' + area + '" fill="url(#stkGrad)"/>' +
      '<polyline points="' + poly + '" fill="none" stroke="' + stroke +
      '" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>';

    const hoverLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
    hoverLine.setAttribute("y1", padT);
    hoverLine.setAttribute("y2", h - padB);
    hoverLine.setAttribute("class", "stk-hover-line");
    hoverLine.style.display = "none";
    svg.appendChild(hoverLine);

    const hoverDot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    hoverDot.setAttribute("r", "4.5");
    hoverDot.setAttribute("class", "stk-hover-dot");
    hoverDot.setAttribute("fill", stroke);
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
      tip.style.left = Math.min(92, Math.max(8, (x / w) * 100)) + "%";
      tip.textContent = points[idx].t + "  ·  " + fmtPrice(points[idx].c);
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
      const resp = await fetch(
        "/api/chart/" + encodeURIComponent(ticker) + "?range=" + encodeURIComponent(range)
      );
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
      document.getElementById("stkPrice").textContent = fmtPrice(data.latest_price);
      const ch = document.getElementById("stkChange");
      ch.textContent = fmtPrice(data.day_change) + " (" + fmtPct(data.day_change_pct) + ")";
      ch.className = "stk-change " + clsPct(data.day_change_pct);
      const rc = document.getElementById("stkRangeChg");
      rc.textContent = range + " " + fmtPct(data.range_change_pct);
      rc.className = "stk-range-pill " + clsPct(data.range_change_pct);
      const asof = document.getElementById("stkAsof");
      if (asof) asof.textContent = "Range " + range + " · Yahoo (may be delayed)";
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
      const ex = document.getElementById("stkExchange");
      if (ex) ex.textContent = d.exchange || "";
      const bits = [d.sector, d.industry, d.country].filter(Boolean);
      document.getElementById("stkMeta").textContent = bits.join(" · ");

      const stats = [
        ["Market cap", fmtMoney(d.market_cap)],
        ["P/E (TTM)", d.pe_ratio != null ? Number(d.pe_ratio).toFixed(1) : "—"],
        ["Forward P/E", d.forward_pe != null ? Number(d.forward_pe).toFixed(1) : "—"],
        ["EPS", d.eps != null ? Number(d.eps).toFixed(2) : "—"],
        ["Beta", d.beta != null ? Number(d.beta).toFixed(2) : "—"],
        ["Div. yield", d.dividend_yield != null ? (Number(d.dividend_yield) * 100).toFixed(2) + "%" : "—"],
        ["52W high", fmtPrice(d.fifty_two_week_high)],
        ["52W low", fmtPrice(d.fifty_two_week_low)],
        ["Rev growth", d.revenue_growth != null ? fmtPct(Number(d.revenue_growth) * 100) : "—"],
        ["Profit margin", d.profit_margin != null ? (Number(d.profit_margin) * 100).toFixed(1) + "%" : "—"],
      ];
      document.getElementById("stkStats").innerHTML = stats
        .map(function (row) {
          return (
            '<div class="stk-stat"><span>' +
            esc(row[0]) +
            "</span><strong>" +
            esc(row[1]) +
            "</strong></div>"
          );
        })
        .join("");

      const a = d.analyst || {};
      const ac = document.getElementById("stkAnalystCard");
      if (a.target_mean || a.recommendation) {
        ac.hidden = false;
        const rows = [
          ["Consensus", (a.recommendation || "—").toString().replace(/_/g, " ")],
          ["# analysts", a.num_analysts != null ? String(a.num_analysts) : "—"],
          ["Mean target", fmtPrice(a.target_mean)],
          ["Low / high", fmtPrice(a.target_low) + " / " + fmtPrice(a.target_high)],
        ];
        document.getElementById("stkAnalyst").innerHTML = rows
          .map(function (r) {
            return (
              '<div class="stk-stat"><span>' +
              esc(r[0]) +
              "</span><strong>" +
              esc(r[1]) +
              "</strong></div>"
            );
          })
          .join("");
      } else {
        ac.hidden = true;
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
      const order = ["1W", "1M", "3M", "6M", "YTD", "1Y", "5Y"];
      const periods = d.periods || {};
      el.innerHTML =
        order
          .map(function (k) {
            const v = periods[k];
            return (
              '<div class="stk-perf-cell"><span>' +
              k +
              '</span><strong class="' +
              clsPct(v) +
              '">' +
              fmtPct(v) +
              "</strong></div>"
            );
          })
          .join("") +
        '<div class="stk-perf-cell"><span>vs 52W high</span><strong class="' +
        clsPct(d.from_high_pct) +
        '">' +
        fmtPct(d.from_high_pct) +
        "</strong></div>" +
        '<div class="stk-perf-cell"><span>vs 52W low</span><strong class="' +
        clsPct(d.from_low_pct) +
        '">' +
        fmtPct(d.from_low_pct) +
        "</strong></div>";
    } catch (e) {
      el.innerHTML = "<div class='stk-perf-empty'>" + esc(e.message || "Unavailable") + "</div>";
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
    try {
      history.replaceState(null, "", "/stock/" + encodeURIComponent(ticker));
    } catch (e) {}
    await Promise.all([loadChart(ticker, currentRange), loadProfile(ticker), loadPerformance(ticker)]);
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
