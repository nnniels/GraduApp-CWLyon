(function () {
  const SWIPE_THRESHOLD = 60;
  const INTERACTIVE_SELECTOR = "a, button, input, textarea, select, iframe, [contenteditable='true']";
  let start = null;

  document.addEventListener("pointerdown", (event) => {
    if (event.pointerType !== "touch" || !event.isPrimary) return;
    const target = event.target;
    if (!(target instanceof Element) || !target.closest("#panel")) return;
    if (target.closest(INTERACTIVE_SELECTOR)) {
      start = null;
      return;
    }
    start = { x: event.clientX, y: event.clientY };
  }, { passive: true });

  document.addEventListener("pointerup", (event) => {
    if (!start || event.pointerType !== "touch" || !event.isPrimary) return;
    const deltaX = event.clientX - start.x;
    const deltaY = event.clientY - start.y;
    start = null;

    if (Math.abs(deltaX) < SWIPE_THRESHOLD || Math.abs(deltaX) < Math.abs(deltaY) * 1.25) return;

    const tabs = Array.from(document.querySelectorAll("#panel .toggle .tab"));
    const activeIndex = tabs.findIndex((tab) => tab.matches("[aria-current='page']") || tab.classList.contains("active"));
    const nextIndex = activeIndex + (deltaX < 0 ? 1 : -1);
    if (activeIndex >= 0 && nextIndex >= 0 && nextIndex < tabs.length) tabs[nextIndex].click();
  }, { passive: true });

  document.addEventListener("pointercancel", () => {
    start = null;
  });
})();