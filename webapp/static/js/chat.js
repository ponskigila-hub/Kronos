(function () {
  const log = document.getElementById("chatLog");
  const form = document.getElementById("chatForm");
  const input = document.getElementById("chatInput");
  const suggestionsBar = document.getElementById("suggestions");
  const modeToggle = document.getElementById("modeToggle");
  const tickerSuggest = document.getElementById("tickerSuggest");
  const sendBtn = form.querySelector('button[type="submit"]');
  const chatWrap = document.querySelector(".chat-wrap");

  // ---------------------------------------------------------------- sparkline
  function sparklineSvg(points) {
    if (!points || points.length < 2) return "";
    const w = 120, h = 28, pad = 2;
    const min = Math.min(...points), max = Math.max(...points);
    const range = max - min || 1;
    const stepX = (w - pad * 2) / (points.length - 1);
    const coords = points.map((v, i) => {
      const x = pad + i * stepX;
      const y = h - pad - ((v - min) / range) * (h - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    const up = points[points.length - 1] >= points[0];
    const color = up ? "#49c5b6" : "#e0685f";
    return `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">
      <polyline points="${coords.join(" ")}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>
    </svg>`;
  }

  // ------------------------------------------------------- scroll-to-bottom
  let scrollBtn = null;
  if (chatWrap) {
    scrollBtn = document.createElement("button");
    scrollBtn.type = "button";
    scrollBtn.className = "chat-scroll-btn";
    scrollBtn.innerHTML =
      '<svg viewBox="0 0 12 12" fill="none"><path d="M2 4.5L6 8.5L10 4.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg><span>New messages</span>';
    chatWrap.appendChild(scrollBtn);
    scrollBtn.addEventListener("click", () => {
      log.scrollTo({ top: log.scrollHeight, behavior: "smooth" });
    });
    log.addEventListener("scroll", updateScrollBtn);
  }

  function isNearBottom() {
    return log.scrollHeight - log.scrollTop - log.clientHeight < 80;
  }

  function updateScrollBtn() {
    if (!scrollBtn) return;
    scrollBtn.classList.toggle("visible", !isNearBottom());
  }

  // -------------------------------------------------------------- messages
  function addTypingIndicator() {
    const wrap = document.createElement("div");
    wrap.className = "msg msg-bot msg-animate";
    const bubble = document.createElement("div");
    bubble.className = "msg-bubble";
    bubble.innerHTML = '<span class="typing-dots"><span></span><span></span><span></span></span>';
    wrap.appendChild(bubble);
    log.appendChild(wrap);
    log.scrollTop = log.scrollHeight;
    return wrap;
  }

  function addCopyButton(wrap, text) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "msg-copy-btn";
    btn.title = "Copy reply";
    btn.setAttribute("aria-label", "Copy reply");
    btn.innerHTML =
      '<svg viewBox="0 0 16 16" fill="none"><rect x="5.5" y="5.5" width="8" height="8" rx="1.3" stroke="currentColor" stroke-width="1.3"/><path d="M3.2 10.2V3.7a1 1 0 0 1 1-1h6.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>';
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(text);
        btn.classList.add("copied");
        btn.innerHTML =
          '<svg viewBox="0 0 16 16" fill="none"><path d="M3.5 8.5l3 3 6-7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
        setTimeout(() => {
          btn.classList.remove("copied");
          btn.innerHTML =
            '<svg viewBox="0 0 16 16" fill="none"><rect x="5.5" y="5.5" width="8" height="8" rx="1.3" stroke="currentColor" stroke-width="1.3"/><path d="M3.2 10.2V3.7a1 1 0 0 1 1-1h6.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>';
        }, 1400);
      } catch (err) { /* clipboard unavailable -- fail silently */ }
    });
    wrap.appendChild(btn);
  }

  function addMessage(role, text, imageUrl, sparkline) {
    const wrap = document.createElement("div");
    wrap.className = "msg " + (role === "user" ? "msg-user" : "msg-bot") + " msg-animate";
    const bubble = document.createElement("div");
    bubble.className = "msg-bubble";
    bubble.textContent = text;
    wrap.appendChild(bubble);

    if (role !== "user") {
      bubble.classList.add("bot-bubble");
    }

    if (sparkline && sparkline.length > 1) {
      const sWrap = document.createElement("div");
      sWrap.className = "sparkline-wrap";
      sWrap.innerHTML = sparklineSvg(sparkline) +
        `<span class="sparkline-label">last ${sparkline.length} sessions</span>`;
      wrap.appendChild(sWrap);
    }
    if (imageUrl) {
      const img = document.createElement("img");
      img.src = imageUrl;
      img.alt = "chart";
      wrap.appendChild(img);
    }
    if (role !== "user" && text) {
      addCopyButton(wrap, text);
    }
    log.appendChild(wrap);
    if (isNearBottom() || role === "user") {
      log.scrollTop = log.scrollHeight;
    }
    updateScrollBtn();
    return wrap;
  }

  function setSuggestions(chips) {
    suggestionsBar.innerHTML = "";
    const options = chips && chips.length ? chips : [
      "What can you do?",
      "Forecast AAPL",
      "Compare NVDA and AMD",
      "Screen the market",
      "My watchlist",
    ];
    options.forEach((text, i) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "suggestion-chip";
      btn.textContent = text;
      btn.style.animationDelay = (i * 40) + "ms";
      btn.addEventListener("click", () => send(text));
      suggestionsBar.appendChild(btn);
    });
  }

  function setSending(isSending) {
    if (!sendBtn) return;
    sendBtn.disabled = isSending;
    sendBtn.classList.toggle("sending", isSending);
    input.disabled = isSending;
  }

  // ------------------------------------------------------------ job polling
  // A chat reply runs server-side in a background thread (see
  // webapp/app.py: /api/chat/send + _run_chat_job) so it keeps computing
  // even if the user navigates to another page mid-reply. This polls for
  // the result rather than awaiting one long-lived request/response.
  const POLL_INTERVAL_MS = 600;
  let activePoll = null;

  function stopPolling() {
    if (activePoll) {
      clearTimeout(activePoll);
      activePoll = null;
    }
  }

  function pollJob(jobId, thinkingEl) {
    stopPolling();
    const tick = async () => {
      try {
        const resp = await fetch("/api/chat/job/" + encodeURIComponent(jobId));
        if (resp.status === 404) {
          thinkingEl.remove();
          setSending(false);
          return; // job expired/unknown -- give up quietly
        }
        const data = await resp.json();
        if (data.status === "pending") {
          activePoll = setTimeout(tick, POLL_INTERVAL_MS);
          return;
        }
        thinkingEl.remove();
        if (data.status === "error") {
          addMessage("bot", data.text || "⚠️ Something went wrong.");
        } else {
          addMessage("bot", data.text || "(no response)", data.image_url, data.sparkline);
          setSuggestions(data.suggestions);
        }
        setSending(false);
        input.focus();
      } catch (err) {
        activePoll = setTimeout(tick, POLL_INTERVAL_MS * 1.5);
      }
    };
    tick();
  }

  async function send(text) {
    if (!text.trim()) return;
    addMessage("user", text);
    setSending(true);
    const thinking = addTypingIndicator();

    try {
      const resp = await fetch("/api/chat/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      const data = await resp.json();
      if (!data.job_id) throw new Error("no job id");
      pollJob(data.job_id, thinking);
    } catch (err) {
      thinking.remove();
      addMessage("bot", "Connection error — is the server still running?");
      setSending(false);
    }
  }

  // wire up the static default chips rendered server-side on first load
  suggestionsBar.querySelectorAll(".suggestion-chip").forEach((chip) => {
    chip.addEventListener("click", () => send(chip.textContent));
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value;
    input.value = "";
    tickerSuggest.classList.remove("open");
    send(text);
  });

  // ------------------------------------------------------------- mode toggle
  modeToggle.addEventListener("click", async (e) => {
    const btn = e.target.closest(".toggle-btn");
    if (!btn) return;
    modeToggle.querySelectorAll(".toggle-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const mode = btn.dataset.mode;
    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: mode }),
      });
      const data = await resp.json();
      addMessage("bot", data.text || `Switched to ${mode} mode.`);
    } catch (err) { /* non-critical */ }
  });

  // -------------------------------------------------------- chat history
  async function loadHistory() {
    try {
      const resp = await fetch("/api/chat/history");
      const data = await resp.json();
      (data.history || []).forEach((turn) => {
        addMessage(turn.role === "user" ? "user" : "bot", turn.text);
      });
      if (data.beginner_mode) {
        modeToggle.querySelectorAll(".toggle-btn").forEach((b) =>
          b.classList.toggle("active", b.dataset.mode === "beginner")
        );
      }
    } catch (err) { /* fine to start with an empty log */ }

    // Resume watching a reply that was still computing when this page was
    // last left (e.g. the user switched to Screener mid-forecast) -- the
    // background job kept running server-side the whole time.
    try {
      const resp = await fetch("/api/chat/pending");
      const data = await resp.json();
      if (data.job_id) {
        if (data.message) addMessage("user", data.message);
        setSending(true);
        pollJob(data.job_id, addTypingIndicator());
      }
    } catch (err) { /* no pending job -- normal case */ }
  }
  loadHistory();

  // ----------------------------------------------------- ticker autocomplete
  let debounceTimer = null;
  let activeIndex = -1;
  let currentResults = [];

  function currentTokenBounds() {
    const val = input.value;
    const caret = input.selectionStart;
    const before = val.slice(0, caret);
    const match = before.match(/[A-Za-z][A-Za-z.\-]*$/);
    if (!match) return null;
    return { start: caret - match[0].length, end: caret, token: match[0] };
  }

  function renderSuggestions(results) {
    currentResults = results;
    activeIndex = -1;
    if (!results.length) {
      tickerSuggest.classList.remove("open");
      tickerSuggest.innerHTML = "";
      return;
    }
    tickerSuggest.innerHTML = results.map((r, i) =>
      `<div class="ticker-suggest-item" data-index="${i}"><span class="sym">${r.symbol}</span><span class="name">${r.name}</span></div>`
    ).join("");
    tickerSuggest.classList.add("open");
  }

  function applySuggestion(result) {
    const bounds = currentTokenBounds();
    if (!bounds) return;
    const before = input.value.slice(0, bounds.start);
    const after = input.value.slice(bounds.end);
    input.value = before + result.symbol + after;
    tickerSuggest.classList.remove("open");
    input.focus();
  }

  input.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    const bounds = currentTokenBounds();
    if (!bounds || bounds.token.length < 2) {
      tickerSuggest.classList.remove("open");
      return;
    }
    debounceTimer = setTimeout(async () => {
      try {
        const resp = await fetch("/api/tickers/search?q=" + encodeURIComponent(bounds.token));
        const data = await resp.json();
        renderSuggestions(data.results || []);
      } catch (err) { /* silently skip suggestions on error */ }
    }, 120);
  });

  tickerSuggest.addEventListener("click", (e) => {
    const item = e.target.closest(".ticker-suggest-item");
    if (item) applySuggestion(currentResults[Number(item.dataset.index)]);
  });

  input.addEventListener("keydown", (e) => {
    if (!tickerSuggest.classList.contains("open")) return;
    const items = tickerSuggest.querySelectorAll(".ticker-suggest-item");
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
      tickerSuggest.classList.remove("open");
      return;
    } else {
      return;
    }
    items.forEach((it, i) => it.classList.toggle("highlighted", i === activeIndex));
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".ticker-input-wrap")) tickerSuggest.classList.remove("open");
  });

  // support ?prefill=... from dashboard/watchlist links
  const params = new URLSearchParams(window.location.search);
  const prefill = params.get("prefill");
  if (prefill) {
    input.value = prefill.replace(/\+/g, " ");
  }
})();
