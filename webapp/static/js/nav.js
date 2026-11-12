(function () {
  var nav = document.getElementById("nav");
  var toggle = document.getElementById("navToggle");
  var backdrop = document.getElementById("navBackdrop");

  function closeAllGroups() {
    if (!nav) return;
    nav.querySelectorAll(".nav-group.open").forEach(function (g) {
      g.classList.remove("open");
      var btn = g.querySelector(".nav-group-btn");
      if (btn) btn.setAttribute("aria-expanded", "false");
    });
  }

  function setMobileOpen(open) {
    if (!nav || !toggle) return;
    nav.classList.toggle("open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    document.body.classList.toggle("nav-open", open);
    if (backdrop) backdrop.classList.toggle("visible", open);
    if (!open) closeAllGroups();
  }

  if (toggle) {
    toggle.addEventListener("click", function () {
      setMobileOpen(!nav.classList.contains("open"));
    });
  }
  if (backdrop) {
    backdrop.addEventListener("click", function () { setMobileOpen(false); });
  }

  if (nav) {
    nav.querySelectorAll(".nav-group-btn").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var group = btn.closest(".nav-group");
        var wasOpen = group.classList.contains("open");
        closeAllGroups();
        if (!wasOpen) {
          group.classList.add("open");
          btn.setAttribute("aria-expanded", "true");
        }
      });
    });

    document.addEventListener("click", function (e) {
      if (!nav.contains(e.target)) closeAllGroups();
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        closeAllGroups();
        setMobileOpen(false);
      }
    });
  }
})();

/* ---- Global tool search / command palette ---- */
(function () {
  var input = document.getElementById("toolSearch");
  var results = document.getElementById("toolSearchResults");
  var wrap = document.getElementById("toolSearchWrap");
  if (!input || !results) return;

  var TOOLS = [
    { title: "Stock", desc: "Price chart & performance", href: "/stock", keywords: "pluang performance price chart stats" },
    { title: "Forecast", desc: "Kronos path + range outlook", href: "/forecast", keywords: "predict price kronos outlook cone" },
    { title: "Screener", desc: "Find candidates by rules", href: "/screener", keywords: "filter universe score" },
    { title: "Valuation", desc: "Relative peer multiples", href: "/valuation", keywords: "pe ps peers fair value" },
    { title: "News", desc: "Headlines & sentiment", href: "/news", keywords: "headlines sentiment" },
    { title: "Research", desc: "Deep research notes", href: "/research", keywords: "deep notes wall street breakdown" },
    { title: "Wall Street breakdown", desc: "Full equity-analyst style note", href: "/chat", keywords: "wall street full analysis equity report breakdown" },
    { title: "Insights", desc: "Fundamentals & financials dig", href: "/insights", keywords: "macro financials statements income balance" },
    { title: "Dig through financials", desc: "Income, balance, cash flow trends", href: "/insights", keywords: "financials dig income statement cash flow" },
    { title: "Watchlist", desc: "Favorites, notes, zones", href: "/watchlist", keywords: "favorites list" },
    { title: "Chat", desc: "Conversational assistant", href: "/chat", keywords: "ask assistant llm" },
    { title: "Day trade", desc: "Scanner, entry, exits", href: "/daytrade", keywords: "intraday scanner" },
    { title: "Backtest", desc: "Walk-forward history", href: "/backtest", keywords: "validation history" },
    { title: "Simulation", desc: "Paper trading portfolio", href: "/simulation", keywords: "paper trade portfolio" },
    { title: "Invest plan", desc: "Entry zone & targets", href: "/invest", keywords: "targets stop" },
    { title: "Home", desc: "Dashboard overview", href: "/", keywords: "dashboard home" },
  ];

  function filter(q) {
    q = (q || "").trim().toLowerCase();
    if (!q) return TOOLS.slice(0, 8);
    return TOOLS.filter(function (t) {
      var hay = (t.title + " " + t.desc + " " + t.keywords).toLowerCase();
      return hay.indexOf(q) !== -1;
    }).slice(0, 10);
  }

  function render(list) {
    if (!list.length) {
      results.innerHTML = '<div class="tool-search-empty">No matching tools</div>';
      results.hidden = false;
      return;
    }
    results.innerHTML = list.map(function (t, i) {
      return '<a class="tool-search-item" role="option" href="' + t.href + '" data-idx="' + i + '">' +
        '<span class="tool-search-title">' + t.title + '</span>' +
        '<span class="tool-search-desc">' + t.desc + '</span></a>';
    }).join("");
    results.hidden = false;
  }

  function open() {
    render(filter(input.value));
    wrap.classList.add("open");
  }
  function close() {
    results.hidden = true;
    wrap.classList.remove("open");
  }

  input.addEventListener("focus", open);
  input.addEventListener("input", function () { render(filter(input.value)); });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { close(); input.blur(); }
    if (e.key === "Enter") {
      var first = results.querySelector(".tool-search-item");
      if (first) { e.preventDefault(); window.location = first.getAttribute("href"); }
    }
  });
  document.addEventListener("click", function (e) {
    if (!wrap.contains(e.target)) close();
  });
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      input.focus();
      open();
    }
  });
})();
