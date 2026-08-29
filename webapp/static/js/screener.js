(function () {
  const universeSelect = document.getElementById("universe");
  const customField = document.getElementById("customTickersField");
  const csvField = document.getElementById("csvUploadField");
  const presetSelect = document.getElementById("preset");
  const presetDesc = document.getElementById("presetDesc");
  const filterRows = document.getElementById("filterRows");
  const addFilterRowBtn = document.getElementById("addFilterRow");
  const customFiltersJson = document.getElementById("customFiltersJson");
  const form = document.getElementById("screenerForm");

  const presetData = JSON.parse(document.getElementById("presetData")?.textContent || "{}");
  const metricCatalog = JSON.parse(document.getElementById("metricCatalogData")?.textContent || "[]");

  // ------------------------------------------------------ universe toggle
  function syncUniverseFields() {
    if (!universeSelect) return;
    const v = universeSelect.value;
    customField.style.display = v === "custom" ? "" : "none";
    csvField.style.display = v === "csv" ? "" : "none";
  }
  if (universeSelect) {
    universeSelect.addEventListener("change", syncUniverseFields);
    syncUniverseFields();
  }

  // --------------------------------------------------------- preset desc
  function syncPresetDesc() {
    if (!presetSelect || !presetDesc) return;
    const p = presetData[presetSelect.value];
    presetDesc.textContent = p ? p.description : "";
  }
  if (presetSelect) {
    presetSelect.addEventListener("change", syncPresetDesc);
    syncPresetDesc();
  }

  // ------------------------------------------------------- filter builder
  const OPERATORS = [">", ">=", "<", "<=", "==", "!="];

  function addFilterRow(prefill) {
    const row = document.createElement("div");
    row.className = "filter-row";

    const metricSelect = document.createElement("select");
    metricCatalog.forEach(([key, label]) => {
      const opt = document.createElement("option");
      opt.value = key;
      opt.textContent = label;
      metricSelect.appendChild(opt);
    });

    const opSelect = document.createElement("select");
    OPERATORS.forEach((op) => {
      const opt = document.createElement("option");
      opt.value = op;
      opt.textContent = op;
      opSelect.appendChild(opt);
    });

    const valueInput = document.createElement("input");
    valueInput.type = "number";
    valueInput.step = "any";
    valueInput.placeholder = "value";

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "remove-filter-row";
    removeBtn.textContent = "\u2715";
    removeBtn.addEventListener("click", () => row.remove());

    if (prefill) {
      metricSelect.value = prefill.metric;
      opSelect.value = prefill.op;
      valueInput.value = prefill.value;
    }

    row.appendChild(metricSelect);
    row.appendChild(opSelect);
    row.appendChild(valueInput);
    row.appendChild(removeBtn);
    filterRows.appendChild(row);
  }

  if (addFilterRowBtn) {
    addFilterRowBtn.addEventListener("click", () => addFilterRow());
  }

  if (form) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const rows = [];
      filterRows.querySelectorAll(".filter-row").forEach((row) => {
        const [metricSelect, opSelect, valueInput] = row.querySelectorAll("select, input");
        if (valueInput.value !== "") {
          rows.push({ metric: metricSelect.value, op: opSelect.value, value: valueInput.value });
        }
      });
      customFiltersJson.value = JSON.stringify(rows);
      submitScreenerForm(form);
    });
  }

  // -------------------------------------------------- async job submission
  // A screen with Kronos enabled runs one forecast call per ticker that
  // survives to the final stage -- easily the slowest form submission in
  // the app. /screener/run now returns a job id immediately instead of
  // blocking the request; poll /screener/job/<id> until done, then
  // navigate to /screener/result/<id>, which renders this exact page
  // fresh from the completed result -- so all of the rendering logic
  // below (renderTable, detail panel, etc.) runs completely unmodified,
  // exactly as if this had been a normal synchronous page load.
  const POLL_INTERVAL_MS = 1500;

  function clearInlineError(form) {
    const existing = form.querySelector(".flash-error");
    if (existing) existing.remove();
  }

  function showInlineError(form, message) {
    clearInlineError(form);
    const el = document.createElement("div");
    el.className = "flash flash-error";
    el.textContent = message;
    form.prepend(el);
  }

  function pollScreenerJob(jobId, form, submitBtn, originalText) {
    fetch("/screener/job/" + jobId)
      .then((r) => r.json())
      .then((data) => {
        if (data.status === "pending") {
          setTimeout(() => pollScreenerJob(jobId, form, submitBtn, originalText), POLL_INTERVAL_MS);
          return;
        }
        window.KronosLoading && window.KronosLoading.hide();
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = originalText;
        }
        if (data.status === "done") {
          window.location.href = "/screener/result/" + jobId;
        } else if (data.status === "error") {
          showInlineError(form, data.error || "Screen failed.");
        } else {
          showInlineError(form, "Lost track of that screen -- please try again.");
        }
      })
      .catch(() => {
        // Transient network hiccup while polling -- the job keeps running
        // server-side regardless, so keep polling rather than giving up.
        setTimeout(() => pollScreenerJob(jobId, form, submitBtn, originalText), POLL_INTERVAL_MS);
      });
  }

  function submitScreenerForm(form) {
    clearInlineError(form);
    const submitBtn = form.querySelector('button[type="submit"]');
    const originalText = submitBtn ? submitBtn.textContent : null;
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Scanning…";
    }
    window.KronosLoading && window.KronosLoading.show(form.dataset.loadingMessage);

    fetch(form.action, { method: "POST", body: new FormData(form) })
      .then((r) => r.json().then((data) => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (!ok || data.error) {
          window.KronosLoading && window.KronosLoading.hide();
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
          }
          showInlineError(form, data.error || "Request failed.");
          return;
        }
        pollScreenerJob(data.job_id, form, submitBtn, originalText);
      })
      .catch(() => {
        window.KronosLoading && window.KronosLoading.hide();
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = originalText;
        }
        showInlineError(form, "Couldn't reach the server -- please try again.");
      });
  }

  // ------------------------------------------------------------ results
  const resultDataEl = document.getElementById("screenerResultData");
  if (!resultDataEl) return;

  const result = JSON.parse(resultDataEl.textContent);
  const tbody = document.getElementById("screenerTableBody");
  const table = document.getElementById("screenerTable");
  const searchInput = document.getElementById("resultSearch");
  const detailPanel = document.getElementById("screenerDetail");
  const exportBtn = document.getElementById("exportCsvBtn");

  let sortKey = "rank";
  let sortAsc = true;
  let filterText = "";

  function scoreClass(v) {
    if (v === null || v === undefined) return "score-mid";
    if (v >= 70) return "score-high";
    if (v >= 45) return "score-mid";
    return "score-low";
  }

  function signalClass(signal) {
    return "signal-" + signal.toLowerCase().replace(/\s+/g, "-");
  }

  function scoreCell(v) {
    if (v === null || v === undefined) return '<span class="score-pill score-mid">—</span>';
    return `<span class="score-pill ${scoreClass(v)}">${v.toFixed(0)}</span>`;
  }

  function kronosCell(row) {
    if (!row.in_kronos_stage || !row.kronos) return "—";
    if (row.kronos.error) return '<span title="' + row.kronos.error.replace(/"/g, "&quot;") + '">n/a</span>';
    const er = row.kronos.expected_return;
    if (er === null || er === undefined) return "—";
    const pct = (er * 100).toFixed(1) + "%";
    return `<span class="${er >= 0 ? 'score-high' : 'score-low'}" style="font-family:var(--mono);">${er >= 0 ? "+" : ""}${pct}</span>`;
  }

  function sortValue(row, key) {
    switch (key) {
      case "rank": return row.rank;
      case "ticker": return row.ticker;
      case "price": return row.price ?? -Infinity;
      case "overall_score": return row.overall_score ?? -Infinity;
      case "trend": return row.category_scores.trend ?? -Infinity;
      case "momentum": return row.category_scores.momentum ?? -Infinity;
      case "relative_strength": return row.category_scores.relative_strength ?? -Infinity;
      case "volatility": return row.category_scores.volatility ?? -Infinity;
      case "liquidity": return row.category_scores.liquidity ?? -Infinity;
      case "risk": return row.category_scores.risk ?? -Infinity;
      case "kronos": return row.kronos && row.kronos.expected_return != null ? row.kronos.expected_return : -Infinity;
      case "signal": return row.signal;
      default: return 0;
    }
  }

  function renderTable() {
    let rows = result.rows.filter((r) => r.ticker.toLowerCase().includes(filterText.toLowerCase()));
    rows.sort((a, b) => {
      const av = sortValue(a, sortKey);
      const bv = sortValue(b, sortKey);
      if (typeof av === "string") return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
      return sortAsc ? av - bv : bv - av;
    });

    tbody.innerHTML = rows.map((row) => `
      <tr data-ticker="${row.ticker}">
        <td class="num-cell">${row.rank}</td>
        <td><strong>${row.ticker}</strong></td>
        <td class="num-cell">${row.price != null ? row.price.toFixed(2) : "—"}</td>
        <td>${scoreCell(row.overall_score)}</td>
        <td>${scoreCell(row.category_scores.trend)}</td>
        <td>${scoreCell(row.category_scores.momentum)}</td>
        <td>${scoreCell(row.category_scores.relative_strength)}</td>
        <td>${scoreCell(row.category_scores.volatility)}</td>
        <td>${scoreCell(row.category_scores.liquidity)}</td>
        <td>${scoreCell(row.category_scores.risk)}</td>
        <td class="num-cell">${kronosCell(row)}</td>
        <td><span class="signal-badge ${signalClass(row.signal)}">${row.signal}</span></td>
      </tr>
    `).join("");

    tbody.querySelectorAll("tr").forEach((tr) => {
      tr.addEventListener("click", () => showDetail(tr.dataset.ticker));
    });

    table.querySelectorAll("th").forEach((th) => {
      th.classList.remove("sorted", "sorted-asc");
      if (th.dataset.sort === sortKey) th.classList.add("sorted", sortAsc ? "sorted-asc" : "");
    });
  }

  table.querySelectorAll("th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (sortKey === key) {
        sortAsc = !sortAsc;
      } else {
        sortKey = key;
        sortAsc = key === "ticker" || key === "rank";
      }
      renderTable();
    });
  });

  if (searchInput) {
    searchInput.addEventListener("input", () => {
      filterText = searchInput.value.trim();
      renderTable();
    });
  }

  function fmtPct(v) {
    return v === null || v === undefined ? "n/a" : (v * 100).toFixed(1) + "%";
  }
  function fmtNum(v, digits) {
    return v === null || v === undefined ? "n/a" : v.toFixed(digits === undefined ? 2 : digits);
  }

  function showDetail(ticker) {
    const row = result.rows.find((r) => r.ticker === ticker);
    if (!row) return;

    tbody.querySelectorAll("tr").forEach((tr) => tr.classList.toggle("selected", tr.dataset.ticker === ticker));

    const m = row.metrics;
    const kronosHtml = row.kronos && !row.kronos.error ? `
      <div class="screener-detail-col">
        <div class="card-title">Kronos forecast</div>
        <table class="metric-mini-table">
          <tr><td>Current price</td><td>${fmtNum(row.kronos.current_price)}</td></tr>
          <tr><td>Forecast price</td><td>${fmtNum(row.kronos.forecast_price)}</td></tr>
          <tr><td>Expected return</td><td>${fmtPct(row.kronos.expected_return)}</td></tr>
          <tr><td>Direction</td><td>${row.kronos.direction || "n/a"}</td></tr>
          <tr><td>Horizon</td><td>${row.kronos.pred_len} trading days</td></tr>
        </table>
      </div>` : row.kronos && row.kronos.error ? `
      <div class="screener-detail-col">
        <div class="card-title">Kronos forecast</div>
        <p class="page-desc" style="margin:0;">${row.kronos.error}</p>
      </div>` : "";

    detailPanel.innerHTML = `
      <div class="card screener-detail-panel">
        <div class="screener-detail-head">
          <h3>${row.ticker}</h3>
          <span class="signal-badge ${signalClass(row.signal)}">${row.signal}</span>
          <span class="score-pill ${scoreClass(row.overall_score)}">${row.overall_score.toFixed(1)}</span>
          <a class="btn btn-ghost btn-small" href="/chat?prefill=forecast+${row.ticker}" style="margin-left:auto;">Analyze with Kronos</a>
        </div>
        <div class="screener-detail-grid">
          <div class="screener-detail-col">
            <div class="card-title">Why it ranked here</div>
            <ul class="reason-list strengths">${row.reasons.strengths.map((s) => `<li>${s}</li>`).join("")}</ul>
            <ul class="reason-list risks" style="margin-top:8px;">${row.reasons.risks.map((s) => `<li>${s}</li>`).join("")}</ul>
          </div>
          <div class="screener-detail-col">
            <div class="card-title">Trend &amp; momentum</div>
            <table class="metric-mini-table">
              <tr><td>Regime</td><td>${m.trend_regime}</td></tr>
              <tr><td>Price vs SMA50</td><td>${fmtPct(m.trend_price_vs_sma50)}</td></tr>
              <tr><td>Price vs SMA200</td><td>${fmtPct(m.trend_price_vs_sma200)}</td></tr>
              <tr><td>6M return</td><td>${fmtPct(m.trend_return_6m)}</td></tr>
              <tr><td>RSI (14)</td><td>${fmtNum(m.momentum_rsi14, 1)}</td></tr>
              <tr><td>ADX</td><td>${fmtNum(m.momentum_adx, 1)}</td></tr>
            </table>
          </div>
          <div class="screener-detail-col">
            <div class="card-title">Volatility, liquidity &amp; risk</div>
            <table class="metric-mini-table">
              <tr><td>Volatility regime</td><td>${m.volatility_regime}</td></tr>
              <tr><td>20D avg $ volume</td><td>${m.liquidity_avg_dollar_volume_20d != null ? "$" + Math.round(m.liquidity_avg_dollar_volume_20d).toLocaleString() : "n/a"}</td></tr>
              <tr><td>Relative volume</td><td>${fmtNum(m.liquidity_relative_volume, 2)}x</td></tr>
              <tr><td>Max drawdown (1Y)</td><td>${fmtPct(m.risk_max_drawdown_1y)}</td></tr>
              <tr><td>Sharpe</td><td>${fmtNum(m.risk_sharpe, 2)}</td></tr>
              <tr><td>Relative strength</td><td>${m.rs_classification}</td></tr>
            </table>
          </div>
          ${kronosHtml}
        </div>
      </div>
    `;
    detailPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  if (exportBtn) {
    exportBtn.addEventListener("click", () => {
      const header = ["Rank", "Ticker", "Price", "Score", "Trend", "Momentum", "RelativeStrength",
        "Volatility", "Liquidity", "Risk", "KronosExpectedReturn", "Signal"];
      const lines = [header.join(",")];
      result.rows.forEach((row) => {
        lines.push([
          row.rank, row.ticker, row.price, row.overall_score,
          row.category_scores.trend, row.category_scores.momentum, row.category_scores.relative_strength,
          row.category_scores.volatility, row.category_scores.liquidity, row.category_scores.risk,
          row.kronos && row.kronos.expected_return != null ? row.kronos.expected_return : "",
          row.signal,
        ].join(","));
      });
      const blob = new Blob([lines.join("\n")], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "kronos_screener_results.csv";
      a.click();
      URL.revokeObjectURL(url);
    });
  }

  renderTable();
  if (result.rows.length) showDetail(result.rows[0].ticker);
})();
