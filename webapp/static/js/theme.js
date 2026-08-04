(function () {
  const STORAGE_KEY = "kronos-theme";
  const root = document.documentElement;

  function getStoredTheme() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return null;
    }
  }

  function getCurrentTheme() {
    return root.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }

  function syncButtons(theme) {
    document.querySelectorAll(".theme-toggle").forEach((btn) => {
      btn.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
      btn.title = theme === "dark" ? "Switch to light mode" : "Switch to dark mode";
    });
  }

  function applyTheme(theme) {
    if (theme === "dark") {
      root.setAttribute("data-theme", "dark");
    } else {
      root.removeAttribute("data-theme");
    }
    syncButtons(theme);
  }

  // The inline <head> script already set data-theme before paint if the
  // saved/preferred theme was dark -- just sync the button icons to match
  // whatever ended up applied (covers the "no theme attr = light" case too).
  syncButtons(getCurrentTheme());

  document.querySelectorAll(".theme-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const next = getCurrentTheme() === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch (e) { /* private browsing etc -- theme just won't persist */ }
      applyTheme(next);
    });
  });

  // If the user hasn't explicitly chosen a theme yet, keep following the
  // OS-level preference live (e.g. their system switches to dark at sunset).
  if (!getStoredTheme() && window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
      if (!getStoredTheme()) applyTheme(e.matches ? "dark" : "light");
    });
  }
})();
