/**
 * Shared "click a ticker, see a price chart" popup -- used from Watchlist
 * cards, Screener rows, and the Simulation positions/trades tables. Loaded
 * once globally (see templates/base.html) rather than per-page, and wires
 * itself up via a single delegated click listener rather than requiring
 * each page to call anything -- any element anywhere in the DOM with
 * class="chart-trigger" and a data-ticker attribute opens this popup,
 * including elements injected later by screener.js's re-renders.
 *
 * Backend:
 *   GET /api/chart/<ticker>?range=1D|1W|1M|3M|6M|YTD|1Y|5Y|MAX
 *     (webapp/app.py's api_chart) -- 1D/1W use intraday bars via
 *     data_fetcher.fetch_intraday(); everything else reuses
 *     fetch_history() exactly like every other page in the app.
 *   GET /api/stock-profile/<ticker>
 *     (webapp/app.py's api_stock_profile) -- company info + analyst
 *     consensus, fetched once per popup open (doesn't change per range).
 */
(function () {
  const RANGES = ["1D", "1W", "1M", "3M", "6M", "YTD", "1Y", "5Y", "MAX"];
  const DEFAULT_RANGE = "1D";
  const RATING_LABELS = ["Strong Sell", "Sell", "Hold", "Buy", "Strong Buy"];

  let overlay, titleEl, priceEl, changeEl, rangeTabsEl, svgWrap, statusEl, profileEl;
  let currentTicker = null;
  let currentRange = DEFAULT_RANGE;
  let requestToken = 0;
  let profileToken = 0;

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
        <div class="ticker-chart-profile"></div>
        <div class="ticker-chart-foot">
          <a class="btn btn-ghost btn-small ticker-chart-forecast-link" href="#">Analyze with Kronos &rarr;</a>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    titleEl = overlay.querySelector(".ticker-chart-title");
    priceEl = overlay.querySelector(".ticker-chart-price");
    changeEl = overlay.querySelector(".ticker-chart-change");
    svgWrap = overlay.querySelector(".ticker-chart-svg-wrap");
    statusEl = overlay.querySelector(".ticker-chart-status");
    rangeTabsEl = overlay.querySelector(".ticker-chart-ranges");
    profileEl = overlay.querySelector(".ticker-chart-profile");

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
    profileEl.innerHTML = "";
    overlay.querySelector(".ticker-chart-forecast-link").href =
      "/chat?prefill=forecast+" + encodeURIComponent(currentTicker);
    updateActiveRangeBtn();
    overlay.classList.add("open");
    document.body.style.overflow = "hidden";
    loadChart();
    loadProfile();
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
  function fmtLarge(n) {
    if (n == null) return "n/a";
    const abs = Math.abs(n);
    if (abs >= 1e12) return (n / 1e12).toFixed(2) + "T";
    if (abs >= 1e9) return (n / 1e9).toFixed(2) + "B";
    if (abs >= 1e6) return (n / 1e6).toFixed(2) + "M";
    return n.toFixed(0);
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
        // Intraday (1D/1W) commonly has nothing to show outside market
        // hours or for symbols Yahoo doesn't serve intraday bars for --
        // fall back to a daily range automatically rather than dead-ending
        // on an error the first time someone opens the popup after close.
        if (data.fallback_range && data.fallback_range !== currentRange) {
          currentRange = data.fallback_range;
          updateActiveRangeBtn();
          return loadChart();
        }
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

  async function loadProfile() {
    const myToken = ++profileToken;
    try {
      const resp = await fetch(`/api/stock-profile/${encodeURIComponent(currentTicker)}`);
      const data = await resp.json();
      if (myToken !== profileToken) return;
      if (!resp.ok || data.error) return; // non-fatal -- chart still works without this
      renderProfile(data);
    } catch (err) { /* non-fatal */ }
  }

  function renderProfile(data) {
    const a = data.analyst || {};
    const parts = [];

    parts.push(`
      <div class="ticker-chart-profile-head">
        ${data.name ? `<div class="ticker-chart-company-name">${data.name}</div>` : ""}
        <div class="ticker-chart-tags">
          ${data.sector ? `<span class="ticker-chart-tag">${data.sector}</span>` : ""}
          ${data.industry ? `<span class="ticker-chart-tag">${data.industry}</span>` : ""}
          ${data.exchange ? `<span class="ticker-chart-tag">${data.exchange}</span>` : ""}
        </div>
      </div>
    `);

    if (data.description) {
      parts.push(`<p class="ticker-chart-description">${data.description}</p>`);
    }

    parts.push(`
      <div class="ticker-chart-stats-grid">
        <div><span class="label">Market cap</span><span class="value">${fmtLarge(data.market_cap)}</span></div>
        <div><span class="label">P/E (TTM)</span><span class="value">${data.pe_ratio != null ? data.pe_ratio.toFixed(1) : "n/a"}</span></div>
        <div><span class="label">Forward P/E</span><span class="value">${data.forward_pe != null ? data.forward_pe.toFixed(1) : "n/a"}</span></div>
        <div><span class="label">Beta</span><span class="value">${data.beta != null ? data.beta.toFixed(2) : "n/a"}</span></div>
        <div><span class="label">52w range</span><span class="value">${data.fifty_two_week_low != null && data.fifty_two_week_high != null ? `${data.fifty_two_week_low.toFixed(2)}–${data.fifty_two_week_high.toFixed(2)}` : "n/a"}</span></div>
        <div><span class="label">Dividend yield</span><span class="value">${data.dividend_yield != null ? (data.dividend_yield * 100).toFixed(2) + "%" : "n/a"}</span></div>
      </div>
    `);

    if (a.rating_score != null || a.target_mean != null) {
      const scorePct = a.rating_score != null ? (a.rating_score / 4) * 100 : 50;
      const ratingLabel = a.rating_score != null ? RATING_LABELS[a.rating_score] : (a.recommendation || "n/a");
      parts.push(`
        <div class="ticker-chart-analyst">
          <div class="ticker-chart-analyst-head">
            <span class="card-title" style="margin:0;">Analyst view</span>
            <span class="ticker-chart-rating-label">${ratingLabel}${a.num_analysts ? ` · ${a.num_analysts} analysts` : ""}</span>
          </div>
          ${a.rating_score != null ? `
            <div class="ticker-chart-gauge">
              <div class="ticker-chart-gauge-track"></div>
              <div class="ticker-chart-gauge-marker" style="left:${scorePct}%;"></div>
            </div>
            <div class="ticker-chart-gauge-labels">
              <span>Strong Sell</span><span>Hold</span><span>Strong Buy</span>
            </div>
          ` : ""}
          ${a.target_mean != null ? `
            <div class="ticker-chart-targets">
              <span>Low <strong>$${a.target_low != null ? a.target_low.toFixed(2) : "n/a"}</strong></span>
              <span>Mean <strong>$${a.target_mean.toFixed(2)}</strong></span>
              <span>High <strong>$${a.target_high != null ? a.target_high.toFixed(2) : "n/a"}</strong></span>
            </div>
          ` : ""}
          <p class="ticker-chart-source-note">Analyst consensus via Yahoo Finance -- not a TradingView feed (this app has no TradingView integration), shown here as the closest equivalent already used elsewhere in the app.</p>
        </div>
      `);
    }

    profileEl.innerHTML = parts.join("");
  }

  function renderChart(data) {
    priceEl.textContent = data.latest_price != null ? "$" + data.latest_price.toFixed(2) : "—";

    // Short/intraday ranges read better as "change since this range
    // started" (today's move, this week's move); longer ranges already
    // mean that by definition, so range_change and day_change converge --
    // simplest to just always use range_change and drop the special case.
    const changeVal = data.range_change;
    const changePct = data.range_change_pct;
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
