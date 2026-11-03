// Live countdown for the timed-challenges panel. Display only: the server stays the authority.
//
// It counts down to the server's deadline using the device clock, corrected by an offset
// (server time - device time) measured when the panel was rendered. A wrong phone clock
// therefore does not matter, and Date.now() keeps running while the screen is locked.
// At zero it asks the server, which resolves the expiry and returns the next screen.
(function () {
  const REFRESH_MIN_GAP_MS = 1500; // the device may reach 0 slightly before the server does
  let current = null; // the #timer element the offset was measured for
  let offset = 0;
  let lastRefresh = 0;

  function format(ms) {
    const total = Math.ceil(ms / 1000);
    const minutes = String(Math.floor(total / 60)).padStart(2, "0");
    const seconds = String(total % 60).padStart(2, "0");
    return minutes + ":" + seconds;
  }

  function refresh(el) {
    const now = Date.now();
    if (now - lastRefresh < REFRESH_MIN_GAP_MS) return;
    lastRefresh = now;
    htmx.ajax("GET", el.dataset.refreshUrl, { target: "#panel", swap: "outerHTML" });
  }

  function tick() {
    const el = document.getElementById("timer");
    if (!el) {
      current = null;
      return;
    }
    if (el !== current) {
      // A new panel just arrived from the server: measure the clock offset again.
      current = el;
      offset = Date.parse(el.dataset.serverNow) - Date.now();
    }
    const remaining = Math.max(0, Date.parse(el.dataset.deadline) - (Date.now() + offset));
    el.textContent = format(remaining);
    el.classList.toggle("urgent", remaining <= 60000);
    if (remaining === 0) refresh(el);
  }

  setInterval(tick, 250);
  document.addEventListener("visibilitychange", tick); // catch up at once when the phone wakes up
  tick();
})();
