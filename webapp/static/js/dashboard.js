(function () {
  const cards = document.querySelectorAll(".feature-card");
  if (!cards.length) return;

  // Reveal each card as it scrolls into view (staggered via the --i custom
  // property set inline on each card). Falls back to showing everything
  // immediately if IntersectionObserver isn't available.
  if (!("IntersectionObserver" in window)) {
    cards.forEach((c) => c.classList.add("in-view"));
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("in-view");
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.15, rootMargin: "0px 0px -40px 0px" }
  );

  cards.forEach((card) => observer.observe(card));
})();
