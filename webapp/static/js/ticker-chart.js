/**
 * Shared "click a ticker, see a price chart" popup -- used from Watchlist
 * cards, Screener rows, and the Simulation positions/trades tables. Loaded
 * once globally (see templates/base.html) rather than per-page, and wires
 * itself up via a single delegated click listener rather than requiring
 * each page to call anything -- any element anywhere in the DOM with
 * class="chart-trigger" and a data-ticker attribute opens this popup,
 * including elements injected later by screener.js's re-renders.
 *
 * Backend: GET /api/chart/<ticker>?range=1M|3M|6M|YTD|1Y|5Y|MAX
 * (see webapp/app.py's api_chart) -- reuses the exact same
 * assistant.data_fetcher.fetch_history() every other page already uses,
 * just with a different lookback per range. Daily bars only (no intraday
 * 1D/5D view) -- see the code comment on CHART_RANGE_LOOKBACK in app.py
 * for why.
 */
(function () {
  const RANGES = ["1M", "3M", "6M", "YTD", "1Y", "5Y", "MAX"];
  const DEFAULT_RANGE = "6M";

  let overlay, panel, titleEl, priceEl, changeEl, rangeTabsEl, svgWrap, statusEl;
  let currentTicker = null;
  let currentRange = DEFAULT_RANGE;
  let requestToken = 0;

  function buildModal() {
    overlay = document.createElement("div");
    overlay.className = "ticker-chart-overlay";
    overlay.innerHTML = `
      <div class="ticker-chart-panel" role="dialog" aria-modal="true">
        <button type="button" class="ticker-chart-close" aria-label="Close">&times;</button>
        <div class="ticker-chart-head">
          <div class="ticker-chart-title"></div>
          <div class="ticker-chart-price-row">
            <span class="ticker-chart-price"></span>
            <span class="ticker-chart-change"></span>
          </div>
        </div>
        <div class="ticker-chart-svg-wrap">
          <div class="ticker-chart-status"></div>
        </div>
        <div class="ticker-chart-ranges"></div>
        <div class="ticker-chart-foot">
          <a class="btn btn-ghost btn-small ticker-chart-forecast-link" href="#">Analyze with Kronos &rarr;</a>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    panel = overlay.querySelector(".ticker-chart-panel");
    titleEl = overlay.querySelector(".ticker-chart-title");
    priceEl = overlay.querySelector(".ticker-chart-price");
    changeEl = overlay.querySelector(".ticker-chart-change");
    svgWrap = overlay.querySelector(".ticker-chart-svg-wrap");
    statusEl = overlay.querySelector(".ticker-chart-status");
    rangeTabsEl = overlay.querySelector(".ticker-chart-ranges");

    RANGES.forEach((r) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ticker-chart-range-btn";
      btn.textContent = r;
      btn.dataset.range = r;
      btn.addEventListener("click", () => {
        if (r === currentRange) return;
        currentRange = r;
        updateActiveRangeBtn();
        loadChart();
      });
      rangeTabsEl.appendChild(btn);
    });

    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) close();
    });
    overlay.querySelector(".ticker-chart-close").addEventListener("click", close);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && overlay.classList.contains("open")) close();
    });
  }

  function updateActiveRangeBtn() {
    rangeTabsEl.querySelectorAll(".ticker-chart-range-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.range === currentRange);
    });
  }

  function open(ticker) {
    if (!overlay) buildModal();
    currentTicker = ticker.toUpperCase();
    currentRange = DEFAULT_RANGE;
    titleEl.textContent = currentTicker;
    priceEl.textContent = "";
    changeEl.textContent = "";
    changeEl.className = "ticker-chart-change";
    overlay.querySelector(".ticker-chart-forecast-link").href =
      "/chat?prefill=forecast+" + encodeURIComponent(currentTicker);
    updateActiveRangeBtn();
    overlay.classList.add("open");
    document.body.style.overflow = "hidden";
    loadChart();
  }

  function close() {
    overlay.classList.remove("open");
    document.body.style.overflow = "";
  }

  function fmtPct(v) {
    const sign = v > 0 ? "+" : "";
    return `${sign}${v.toFixed(2)}%`;
  }
  function fmtNum(v) {
    const sign = v > 0 ? "+" : "";
    return `${sign}${v.toFixed(2)}`;
  }

  async function loadChart() {
    const myToken = ++requestToken;
    statusEl.textContent = "Loading…";
    statusEl.style.display = "flex";
    svgWrap.querySelector("svg")?.remove();

    try {
      const resp = await fetch(`/api/chart/${encodeURIComponent(currentTicker)}?range=${currentRange}`);
      const data = await resp.json();
      if (myToken !== requestToken) return; // a newer request superseded this one

      if (!resp.ok || data.error) {
        statusEl.textContent = data.error || "Couldn't load chart data.";
        return;
      }
      statusEl.style.display = "none";
      renderChart(data);
    } catch (err) {
      if (myToken !== requestToken) return;
      statusEl.textContent = "Connection error — is the server still running?";
    }
  }

  function renderChart(data) {
    priceEl.textContent = data.latest_price != null ? "$" + data.latest_price.toFixed(2) : "—";

    // Google Finance shows day-over-day change on short ranges, but the
    // change across the whole selected window once you've picked a longer
    // range -- that's the more useful number once you're looking at 1Y/5Y.
    const useRangeChange = currentRange !== "1M";
    const changeVal = useRangeChange ? data.range_change : data.day_change;
    const changePct = useRangeChange ? data.range_change_pct : data.day_change_pct;
    const up = changeVal >= 0;
    changeEl.textContent = `${fmtNum(changeVal)} (${fmtPct(changePct)})`;
    changeEl.className = "ticker-chart-change " + (up ? "positive" : "negative");

    const points = data.points || [];
    if (points.length < 2) {
      statusEl.textContent = "Not enough data to draw a chart.";
      statusEl.style.display = "flex";
      return;
    }

    const w = 640, h = 220, padTop = 14, padBottom = 14;
    const closes = points.map((p) => p.c);
    const min = Math.min(...closes);
    const max = Math.max(...closes);
    const range = (max - min) || 1;
    const stepX = w / (points.length - 1);

    const coords = closes.map((c, i) => {
      const x = i * stepX;
      const y = padTop + (h - padTop - padBottom) * (1 - (c - min) / range);
      return [x, y];
    });

    const lineD = coords.map(([x, y], i) => (i === 0 ? `M${x},${y}` : `L${x},${y}`)).join(" ");
    const areaD = `${lineD} L${w},${h} L0,${h} Z`;
    const color = up ? "var(--teal)" : "var(--red)";
    const gradId = "tcg-" + Math.random().toString(36).slice(2, 9);

    const first = points[0].t;
    const last = points[points.length - 1].t;

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${w} ${h + 24}`);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.classList.add("ticker-chart-svg");
    svg.innerHTML = `
      <defs>
        <linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${color}" stop-opacity="0.28"/>
          <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
        </linearGradient>
      </defs>
      <path d="${areaD}" fill="url(#${gradId})" stroke="none"></path>
      <path d="${lineD}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"></path>
      <text x="0" y="${h + 18}" class="ticker-chart-axis-label" text-anchor="start">${first}</text>
      <text x="${w}" y="${h + 18}" class="ticker-chart-axis-label" text-anchor="end">${last}</text>
    `;

    // Hover crosshair + readout, matching the "hover to see the price on
    // that day" behavior Google's stock chart has.
    const hoverLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
    hoverLine.setAttribute("y1", padTop);
    hoverLine.setAttribute("y2", h - padBottom);
    hoverLine.setAttribute("class", "ticker-chart-hover-line");
    hoverLine.style.display = "none";
    svg.appendChild(hoverLine);

    const hoverDot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    hoverDot.setAttribute("r", "3.5");
    hoverDot.setAttribute("class", "ticker-chart-hover-dot");
    hoverDot.style.display = "none";
    svg.appendChild(hoverDot);

    const tooltip = document.createElement("div");
    tooltip.className = "ticker-chart-tooltip";
    tooltip.style.display = "none";

    svg.addEventListener("mousemove", (e) => {
      const rect = svg.getBoundingClientRect();
      const relX = ((e.clientX - rect.left) / rect.width) * w;
      let idx = Math.round(relX / stepX);
      idx = Math.max(0, Math.min(points.length - 1, idx));
      const [x, y] = coords[idx];
      hoverLine.setAttribute("x1", x);
      hoverLine.setAttribute("x2", x);
      hoverLine.style.display = "block";
      hoverDot.setAttribute("cx", x);
      hoverDot.setAttribute("cy", y);
      hoverDot.style.display = "block";
      tooltip.style.display = "block";
      tooltip.style.left = (x / w) * 100 + "%";
      tooltip.textContent = `${points[idx].t} · $${points[idx].c.toFixed(2)}`;
    });
    svg.addEventListener("mouseleave", () => {
      hoverLine.style.display = "none";
      hoverDot.style.display = "none";
      tooltip.style.display = "none";
    });

    svgWrap.appendChild(svg);
    svgWrap.querySelectorAll(".ticker-chart-tooltip").forEach((t) => t.remove());
    svgWrap.appendChild(tooltip);
  }

  // Capture phase so this can stop the click from also reaching an
  // ancestor's own click handler (e.g. a screener table row that opens
  // its detail panel on row-click) -- by the time a bubble-phase listener
  // on document would run, the row's own listener has already fired.
  document.addEventListener("click", (e) => {
    const trigger = e.target.closest(".chart-trigger");
    if (!trigger || !trigger.dataset.ticker) return;
    e.preventDefault();
    e.stopPropagation();
    open(trigger.dataset.ticker);
  }, true);
})();
