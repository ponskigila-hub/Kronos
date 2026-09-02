(function () {
  const hourHand = document.querySelector(".clock-hour");
  const minuteHand = document.querySelector(".clock-minute");
  const secondHand = document.querySelector(".clock-second");
  const timeReadout = document.getElementById("localTime");
  const zoneReadout = document.getElementById("localZone");

  function updateClock() {
    const now = new Date();
    const seconds = now.getSeconds() + now.getMilliseconds() / 1000;
    const minutes = now.getMinutes() + seconds / 60;
    const hours = (now.getHours() % 12) + minutes / 60;
    if (hourHand) hourHand.style.transform = `rotate(${hours * 30}deg)`;
    if (minuteHand) minuteHand.style.transform = `rotate(${minutes * 6}deg)`;
    if (secondHand) secondHand.style.transform = `rotate(${seconds * 6}deg)`;
    if (timeReadout) timeReadout.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    if (zoneReadout) zoneReadout.textContent = Intl.DateTimeFormat().resolvedOptions().timeZone.replace(/_/g, " ");
  }

  if (hourHand || timeReadout) {
    updateClock();
    window.setInterval(updateClock, 250);
  }

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
