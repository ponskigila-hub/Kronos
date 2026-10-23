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
