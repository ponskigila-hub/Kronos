(function () {
  const container = document.getElementById("watchlistCards");
  if (!container) return;  // empty watchlist -- nothing to wire up

  const cards = Array.from(container.querySelectorAll(".wl-card"));
  const PRICE_POLL_MS = 45000;

  function fmtPrice(p) {
    return p == null ? "n/a" : p.toFixed(2);
  }

  const SESSION_META = {
    pre: { label: "Pre-Market", cls: "sess-pre" },
    regular: { label: "Market Open", cls: "sess-regular" },
    post: { label: "After-Hours", cls: "sess-post" },
    closed: { label: "Market Closed", cls: "sess-closed" },
  };

  function fmtAsOf(iso) {
    if (!iso) return "";
    try {
      const d = new Date(iso);
      const now = new Date();
      const sameDay = d.toDateString() === now.toDateString();
      const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      return sameDay ? `as of ${time}` : `as of ${d.toLocaleDateString()} ${time}`;
    } catch (err) {
      return "";
    }
  }

  function applyPrice(card, priceInfo) {
    const priceEl = card.querySelector(".wl-price");
    const changeEl = card.querySelector(".wl-change");
    const sessionEl = card.querySelector(".wl-session-badge");
    const asOfEl = card.querySelector(".wl-asof");
    priceEl.classList.remove("skeleton");

    if (!priceInfo || priceInfo.price == null) {
      priceEl.textContent = "n/a";
      priceEl.classList.add("stale");
      changeEl.textContent = "";
      sessionEl.textContent = "";
      asOfEl.textContent = "";
      return;
    }
    priceEl.textContent = fmtPrice(priceInfo.price);
    priceEl.classList.remove("stale");
    if (priceInfo.change_pct != null) {
      const up = priceInfo.change_pct >= 0;
      changeEl.textContent = (up ? "+" : "") + priceInfo.change_pct.toFixed(2) + "%";
      changeEl.className = "wl-change " + (up ? "up" : "down");
    } else {
      changeEl.textContent = "";
    }

    const meta = SESSION_META[priceInfo.session] || SESSION_META.closed;
    sessionEl.textContent = meta.label;
    sessionEl.className = "wl-session-badge " + meta.cls;
    asOfEl.textContent = fmtAsOf(priceInfo.as_of);

    updateZoneBadge(card, priceInfo.price);
  }

  function updateZoneBadge(card, price) {
    const badge = card.querySelector(".wl-zone-badge");
    const low = card.querySelector(".wl-zone-low").value;
    const high = card.querySelector(".wl-zone-high").value;
    if (!low || !high || price == null) {
      badge.style.display = "none";
      return;
    }
    let status, label;
    if (price < parseFloat(low)) { status = "below"; label = "Below zone"; }
    else if (price > parseFloat(high)) { status = "above"; label = "Above zone"; }
    else { status = "in"; label = "In buy zone"; }
    badge.textContent = label;
    badge.className = "wl-zone-badge zone-" + status;
    badge.style.display = "inline-block";
  }

  function applyEarnings(card, earnings) {
    const el = card.querySelector(".wl-earnings-value");
    el.classList.remove("skeleton");
    if (!earnings || !earnings.date) {
      el.textContent = "no data";
      el.classList.remove("soon");
      return;
    }
    el.textContent = `${earnings.date} (${earnings.quarter}) · ${earnings.days_until}d`;
    el.classList.toggle("soon", earnings.days_until <= 14);
  }

  async function loadDetails() {
    try {
      const resp = await fetch("/api/watchlist/details");
      const data = await resp.json();
      (data.tickers || []).forEach((row) => {
        const card = container.querySelector(`.wl-card[data-ticker="${row.ticker}"]`);
        if (!card) return;
        applyPrice(card, row.price);
        applyEarnings(card, row.earnings);
        if (row.entry_zone) {
          card.querySelector(".wl-zone-low").value = row.entry_zone.low;
          card.querySelector(".wl-zone-high").value = row.entry_zone.high;
        }
        if (row.price && row.price.price != null) updateZoneBadge(card, row.price.price);
        if (row.note) card.querySelector(".wl-notes").value = row.note;
      });
    } catch (err) {
      cards.forEach((card) => {
        card.querySelector(".wl-price").classList.remove("skeleton");
        card.querySelector(".wl-price").textContent = "error";
        card.querySelector(".wl-earnings-value").classList.remove("skeleton");
        card.querySelector(".wl-earnings-value").textContent = "error";
      });
    }
  }

  async function pollPrices() {
    try {
      const resp = await fetch("/api/watchlist/prices");
      const data = await resp.json();
      cards.forEach((card) => {
        const ticker = card.dataset.ticker;
        applyPrice(card, (data.prices || {})[ticker]);
      });
    } catch (err) { /* keep last known prices on a failed poll */ }
  }

  cards.forEach((card) => {
    const ticker = card.dataset.ticker;

    // ---- entry zone save/clear ----
    const zoneForm = card.querySelector(".wl-zone-form");
    zoneForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const low = card.querySelector(".wl-zone-low").value;
      const high = card.querySelector(".wl-zone-high").value;
      if (!low || !high) return;
      try {
        const resp = await fetch("/watchlist/entry_zone", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ticker, low, high }),
        });
        const data = await resp.json();
        const priceEl = card.querySelector(".wl-price");
        const currentPrice = parseFloat(priceEl.textContent);
        if (data.entry_zone && !isNaN(currentPrice)) updateZoneBadge(card, currentPrice);
      } catch (err) { /* non-critical */ }
    });

    card.querySelector(".wl-zone-clear").addEventListener("click", async () => {
      card.querySelector(".wl-zone-low").value = "";
      card.querySelector(".wl-zone-high").value = "";
      card.querySelector(".wl-zone-badge").style.display = "none";
      try {
        await fetch("/watchlist/entry_zone", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ticker, clear: true }),
        });
      } catch (err) { /* non-critical */ }
    });

    // ---- notes autosave on blur ----
    const notesEl = card.querySelector(".wl-notes");
    const notesStatus = card.querySelector(".wl-notes-status");
    let lastSavedValue = notesEl.value;
    notesEl.addEventListener("blur", async () => {
      if (notesEl.value === lastSavedValue) return;
      try {
        await fetch("/watchlist/note", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ticker, note: notesEl.value }),
        });
        lastSavedValue = notesEl.value;
        notesStatus.textContent = "saved";
        notesStatus.classList.add("saved");
        setTimeout(() => { notesStatus.textContent = ""; notesStatus.classList.remove("saved"); }, 1500);
      } catch (err) {
        notesStatus.textContent = "save failed";
      }
    });
  });

  loadDetails();
  setInterval(pollPrices, PRICE_POLL_MS);
})();
