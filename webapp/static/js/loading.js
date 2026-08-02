(function () {
  let overlay = null;

  function ensureOverlay() {
    if (overlay) return overlay;
    overlay = document.createElement("div");
    overlay.className = "loading-overlay";
    overlay.innerHTML = `
      <div class="loading-box">
        <div class="loading-spinner" aria-hidden="true"></div>
        <div class="loading-message">Working…</div>
        <div class="loading-sub">This can take a while on CPU-only hardware — please keep this tab open.</div>
      </div>`;
    document.body.appendChild(overlay);
    return overlay;
  }

  function showLoading(message) {
    const el = ensureOverlay();
    el.querySelector(".loading-message").textContent = message || "Working…";
    el.classList.add("visible");
  }

  // Any form with data-loading-message="..." gets the overlay + a
  // disabled submit button automatically on submit. This is a real
  // full-page POST (not AJAX) -- the overlay just covers the wait until
  // the new page arrives, so there's no need to hide it again on success;
  // it only needs to disappear if the browser shows a cached page on
  // back/forward navigation, handled by the pageshow listener below.
  document.querySelectorAll("form[data-loading-message]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      if (form.dataset.skipLoading === "true") return;
      const btn = form.querySelector('button[type="submit"]');
      if (btn) {
        btn.disabled = true;
        btn.dataset.originalText = btn.textContent;
        btn.textContent = "Working…";
      }
      showLoading(form.dataset.loadingMessage);
    });
  });

  // Same treatment for plain links that trigger a slow server-side
  // computation (e.g. the watchlist correlation matrix).
  document.querySelectorAll("a[data-loading-message]").forEach((link) => {
    link.addEventListener("click", () => showLoading(link.dataset.loadingMessage));
  });

  window.addEventListener("pageshow", (e) => {
    if (e.persisted && overlay) overlay.classList.remove("visible");
  });

  window.KronosLoading = { show: showLoading };
})();
