/**
 * US (NYSE) + IDX session clocks.
 * Status computed in exchange TZ; times shown in that exchange TZ
 * (ET for US, WIB for IDX) so labels match "09:30 ET" / "09:00 WIB".
 */
(function () {
  function getZonedParts(date, timeZone) {
    // en-GB + hourCycle h23 avoids 24:00 edge cases on some engines
    var fmt = new Intl.DateTimeFormat("en-GB", {
      timeZone: timeZone,
      weekday: "short",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    });
    var map = {};
    fmt.formatToParts(date).forEach(function (p) {
      if (p.type !== "literal") map[p.type] = p.value;
    });
    var hour = parseInt(map.hour, 10);
    var minute = parseInt(map.minute, 10);
    if (hour === 24) hour = 0;
    return {
      weekday: map.weekday, // Mon, Tue, ...
      hour: hour,
      minute: minute,
      minutes: hour * 60 + minute,
      clock: (hour < 10 ? "0" : "") + hour + ":" + (minute < 10 ? "0" : "") + minute,
    };
  }

  function isWeekend(wd) {
    // en-GB short: Mon..Sun
    return wd === "Sat" || wd === "Sun";
  }

  /** NYSE regular 09:30–16:00 America/New_York (DST-aware via Intl) */
  function usStatus(now) {
    var p = getZonedParts(now, "America/New_York");
    if (isWeekend(p.weekday)) {
      return { state: "closed", label: "Closed", clock: p.clock };
    }
    var m = p.minutes;
    if (m >= 4 * 60 && m < 9 * 60 + 30) {
      return { state: "pre", label: "Pre-market", clock: p.clock };
    }
    if (m >= 9 * 60 + 30 && m < 16 * 60) {
      return { state: "open", label: "Open", clock: p.clock };
    }
    if (m >= 16 * 60 && m < 20 * 60) {
      return { state: "after", label: "After-hours", clock: p.clock };
    }
    return { state: "closed", label: "Closed", clock: p.clock };
  }

  /** IDX sessions in Asia/Jakarta (no DST) */
  function idxStatus(now) {
    var p = getZonedParts(now, "Asia/Jakarta");
    if (isWeekend(p.weekday)) {
      return { state: "closed", label: "Closed", clock: p.clock };
    }
    var m = p.minutes;
    var fri = p.weekday === "Fri";
    var s1End = fri ? 11 * 60 + 30 : 12 * 60;
    var s2Start = fri ? 14 * 60 : 13 * 60 + 30;
    var s2End = 15 * 60 + 50;
    if (m >= 9 * 60 && m < s1End) {
      return { state: "open", label: "Open", clock: p.clock };
    }
    if (m >= s1End && m < s2Start) {
      return { state: "break", label: "Break", clock: p.clock };
    }
    if (m >= s2Start && m < s2End) {
      return { state: "open", label: "Open", clock: p.clock };
    }
    return { state: "closed", label: "Closed", clock: p.clock };
  }

  function apply(prefix, status) {
    var st = document.getElementById(prefix + "Status");
    var tm = document.getElementById(prefix + "Time");
    var dot = document.getElementById(prefix + "Dot");
    if (!st) return;
    st.textContent = status.label;
    if (tm) tm.textContent = status.clock || "";
    var pill = st.closest(".mkt-pill");
    if (pill) {
      pill.classList.remove("is-open", "is-closed", "is-pre", "is-after", "is-break");
      if (status.state === "open") pill.classList.add("is-open");
      else if (status.state === "pre" || status.state === "after") pill.classList.add("is-pre");
      else if (status.state === "break") pill.classList.add("is-break");
      else pill.classList.add("is-closed");
    }
    if (dot) dot.className = "mkt-dot mkt-dot-" + status.state;
  }

  function tick() {
    var now = new Date();
    apply("us", usStatus(now));
    apply("id", idxStatus(now));
  }

  tick();
  setInterval(tick, 15000);
})();
