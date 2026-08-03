(function () {
  const toggle = document.getElementById("navToggle");
  const sidebar = document.getElementById("sidebar");
  const backdrop = document.getElementById("sidebarBackdrop");
  if (!toggle || !sidebar || !backdrop) return;

  function closeNav() {
    sidebar.classList.remove("open");
    backdrop.classList.remove("visible");
    toggle.setAttribute("aria-expanded", "false");
    document.body.classList.remove("nav-open");
  }

  function openNav() {
    sidebar.classList.add("open");
    backdrop.classList.add("visible");
    toggle.setAttribute("aria-expanded", "true");
    document.body.classList.add("nav-open");
  }

  toggle.addEventListener("click", () => {
    sidebar.classList.contains("open") ? closeNav() : openNav();
  });
  backdrop.addEventListener("click", closeNav);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeNav(); });
  // Tapping a nav link on mobile navigates to a new page anyway, but
  // closing immediately avoids a flash of the open drawer on the next page.
  sidebar.querySelectorAll(".nav a").forEach((a) => a.addEventListener("click", closeNav));

  // If the viewport is resized past the mobile breakpoint while the drawer
  // is open (e.g. rotating a tablet), reset state so desktop layout isn't
  // stuck mid-transition.
  window.addEventListener("resize", () => {
    if (window.innerWidth > 768) closeNav();
  });
})();
