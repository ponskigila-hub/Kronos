(function () {
  const toggle = document.getElementById("navToggle");
  const nav = document.getElementById("nav");
  const backdrop = document.getElementById("navBackdrop");
  if (!toggle || !nav || !backdrop) return;

  function closeNav() {
    nav.classList.remove("open");
    backdrop.classList.remove("visible");
    toggle.setAttribute("aria-expanded", "false");
    document.body.classList.remove("nav-open");
  }

  function openNav() {
    nav.classList.add("open");
    backdrop.classList.add("visible");
    toggle.setAttribute("aria-expanded", "true");
    document.body.classList.add("nav-open");
  }

  toggle.addEventListener("click", () => {
    nav.classList.contains("open") ? closeNav() : openNav();
  });
  backdrop.addEventListener("click", closeNav);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeNav(); });
  // Tapping a nav link on mobile navigates to a new page anyway, but
  // closing immediately avoids a flash of the open menu on the next page.
  nav.querySelectorAll("a").forEach((a) => a.addEventListener("click", closeNav));

  // If the viewport is resized past the mobile breakpoint while the menu
  // is open (e.g. rotating a tablet), reset state so the desktop layout
  // isn't stuck mid-transition.
  window.addEventListener("resize", () => {
    if (window.innerWidth > 768) closeNav();
    placeIndicator(nav.querySelector("a.active"));
  });

  // ------------------------------------------------------ sliding indicator
  // Tracks whichever link is hovered, falling back to the active page link
  // when the mouse leaves the nav -- gives the centered nav a tactile,
  // "gliding" feel instead of a static underline.
  const indicator = document.getElementById("navIndicator");
  const links = Array.from(nav.querySelectorAll("a"));

  function placeIndicator(link) {
    if (!indicator || !link || window.innerWidth <= 768) {
      if (indicator) indicator.classList.remove("visible");
      return;
    }
    const navRect = nav.getBoundingClientRect();
    const linkRect = link.getBoundingClientRect();
    indicator.style.width = linkRect.width + "px";
    indicator.style.transform = `translateX(${linkRect.left - navRect.left - 4}px)`;
    indicator.classList.add("visible");
  }

  links.forEach((link) => {
    link.addEventListener("mouseenter", () => placeIndicator(link));
  });
  nav.addEventListener("mouseleave", () => placeIndicator(nav.querySelector("a.active")));

  // Initial placement + re-check once web fonts settle (they can shift
  // link widths slightly after first paint).
  placeIndicator(nav.querySelector("a.active"));
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => placeIndicator(nav.querySelector("a.active")));
  }
})();
