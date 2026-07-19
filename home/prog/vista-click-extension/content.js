// Vista "Navigation Start" on link clicks — the sound IE played on every
// page navigation. Fires on real <a href> clicks only (capture phase, so
// stopPropagation in page scripts can't hide navigations from us); each
// play uses a fresh Audio element so rapid clicks can overlap the tail
// instead of cutting it. The click IS a user gesture, so autoplay policy
// always allows it.
(() => {
  const src = chrome.runtime.getURL("click.wav");
  document.addEventListener(
    "click",
    (e) => {
      if (e.button !== 0) return;
      const t = e.target;
      const a = t && t.closest ? t.closest("a[href]") : null;
      if (!a) return;
      const href = a.getAttribute("href") || "";
      if (href.startsWith("javascript:")) return;
      try {
        new Audio(src).play().catch(() => {});
      } catch (_) {}
    },
    true
  );
})();
