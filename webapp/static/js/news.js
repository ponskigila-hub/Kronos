(function () {
  const form = document.getElementById("newsForm");
  const input = document.getElementById("newsTicker");
  const suggestBox = document.getElementById("newsTickerSuggest");
  const results = document.getElementById("newsResults");
  if (!form || !input || !results) return;

  // ------------------------------------------------------- ticker autocomplete
  let debounceTimer = null;
  let currentResults = [];
  let activeIndex = -1;

  function renderSuggestions(list) {
    currentResults = list;
    activeIndex = -1;
    if (!list.length) {
      suggestBox.classList.remove("open");
      suggestBox.innerHTML = "";
      return;
    }
    suggestBox.innerHTML = list.map((r, i) =>
      `<div class="ticker-suggest-item" data-index="${i}"><span class="sym">${r.symbol}</span><span class="name">${r.name}</span></div>`
    ).join("");
    suggestBox.classList.add("open");
  }

  function applySuggestion(r) {
    input.value = r.symbol;
    suggestBox.classList.remove("open");
    input.focus();
  }

  input.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    const q = input.value.trim();
    if (q.length < 1) {
      suggestBox.classList.remove("open");
      return;
    }
    debounceTimer = setTimeout(async () => {
      try {
        const resp = await fetch("/api/tickers/search?q=" + encodeURIComponent(q));
        const data = await resp.json();
        renderSuggestions(data.results || []);
      } catch (err) { /* silently skip suggestions on error */ }
    }, 120);
  });

  suggestBox.addEventListener("click", (e) => {
    const item = e.target.closest(".ticker-suggest-item");
    if (item) applySuggestion(currentResults[Number(item.dataset.index)]);
  });

  input.addEventListener("keydown", (e) => {
    if (!suggestBox.classList.contains("open")) return;
    const items = suggestBox.querySelectorAll(".ticker-suggest-item");
    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIndex = Math.min(activeIndex + 1, items.length - 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIndex = Math.max(activeIndex - 1, 0);
    } else if (e.key === "Enter" && activeIndex >= 0) {
      e.preventDefault();
      applySuggestion(currentResults[activeIndex]);
      return;
    } else if (e.key === "Escape") {
      suggestBox.classList.remove("open");
      return;
    } else {
      return;
    }
    items.forEach((it, i) => it.classList.toggle("highlighted", i === activeIndex));
  });

  document.addEventListener("click", (e) => {
    if (!suggestBox.contains(e.target) && e.target !== input) suggestBox.classList.remove("open");
  });

  // --------------------------------------------------------------- fetching
  function sentimentClass(label) {
    if (label === "positive") return "sent-pos";
    if (label === "negative") return "sent-neg";
    return "sent-neu";
  }

  function timeAgo(raw) {
    if (!raw) return "";
    let ms;
    if (typeof raw === "number") {
      ms = raw > 1e12 ? raw : raw * 1000; // seconds vs ms epoch
    } else {
      const parsed = Date.parse(raw);
      if (Number.isNaN(parsed)) return "";
      ms = parsed;
    }
    const diffMin = Math.round((Date.now() - ms) / 60000);
    if (diffMin < 1) return "just now";
    if (diffMin < 60) return diffMin + "m ago";
    const diffH = Math.round(diffMin / 60);
    if (diffH < 24) return diffH + "h ago";
    return Math.round(diffH / 24) + "d ago";
  }

  function renderSkeleton(ticker) {
    results.innerHTML = `
      <div class="card">
        <div class="card-title">Headlines — ${ticker}</div>
        <div class="news-item skeleton" style="height:64px;"></div>
        <div class="news-item skeleton" style="height:64px; margin-top:10px;"></div>
        <div class="news-item skeleton" style="height:64px; margin-top:10px;"></div>
      </div>`;
  }

  function renderError(ticker, message) {
    results.innerHTML = `
      <div class="card">
        <div class="card-title">Headlines — ${ticker}</div>
        <p class="page-desc" style="margin:0;">${message}</p>
      </div>`;
  }

  function renderResults(data) {
    const { ticker, items, summary, source_label } = data;

    if (!items.length) {
      renderError(ticker, `No recent headlines found for ${ticker}.`);
      return;
    }

    const summaryHtml = `
      <div class="news-summary">
        <span class="news-summary-label ${sentimentClass(summary.label.includes('positive') ? 'positive' : summary.label.includes('negative') ? 'negative' : 'neutral')}">${summary.label}</span>
        <span class="news-summary-counts">${summary.positive} positive &middot; ${summary.neutral} neutral &middot; ${summary.negative} negative</span>
      </div>`;

    const itemsHtml = items.map((it) => `
      <a class="news-item" href="${it.link || '#'}" target="_blank" rel="noopener noreferrer">
        <div class="news-item-main">
          <div class="news-item-title">${it.title}</div>
          <div class="news-item-meta">${it.publisher || ''}${it.published ? ' &middot; ' + timeAgo(it.published) : ''}</div>
        </div>
        <span class="sent-badge ${sentimentClass(it.sentiment_label)}">${it.sentiment_label}</span>
      </a>`).join("");

    results.innerHTML = `
      <div class="card">
        <div class="card-title">Headlines — ${ticker}</div>
        ${summaryHtml}
        <div class="news-list">${itemsHtml}</div>
        <p class="news-source-note">Source: ${source_label}</p>
      </div>`;
  }

  async function loadNews(ticker) {
    renderSkeleton(ticker);
    try {
      const resp = await fetch("/api/news?ticker=" + encodeURIComponent(ticker));
      const data = await resp.json();
      if (!resp.ok) {
        renderError(ticker, data.error || `Couldn't fetch news for ${ticker}.`);
        return;
      }
      renderResults(data);
    } catch (err) {
      renderError(ticker, `Couldn't fetch news for ${ticker} -- check your connection and try again.`);
    }
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const ticker = input.value.trim().toUpperCase();
    if (!ticker) return;
    suggestBox.classList.remove("open");
    const url = new URL(window.location);
    url.searchParams.set("ticker", ticker);
    window.history.replaceState({}, "", url);
    loadNews(ticker);
  });

  if (input.value.trim()) {
    loadNews(input.value.trim().toUpperCase());
  }
})();
