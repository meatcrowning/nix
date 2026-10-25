/* Vivaldi UI only. Keep React's bookmark buttons; own only the splitter.
 * Embedded by home/pkgs/desktop/net.nix on top; changes require a rebuild.
 * Book's independently installed Flatpak retains the CSS-only fallback.
 */
(() => {
  const key = 'desktop.bookmarkSidebarHeight';
  let bar, handle, observer, pending = false;
  const height = () => bar.getBoundingClientRect().height;
  const limit = value => Math.max(60, Math.min(innerHeight * .55, value));
  const apply = value => {
    const size = limit(value);
    bar.style.height = `${size}px`;
    handle.setAttribute('aria-valuenow', String(Math.round(size)));
    return size;
  };
  const save = () => { try { localStorage.setItem(key, String(height())); } catch {} };
  function mount() {
    pending = false;
    let target = document.querySelector('#browser.tabs-left:has(.toolbar-tabbar-before .UrlBar-AddressField) .bookmark-bar');
    if (target && !getComputedStyle(target).getPropertyValue('--sidebar-bookmarks-height').trim()) target = null;
    if (target === bar && handle?.isConnected) return;
    observer?.disconnect();
    handle?.remove();
    if (bar && bar !== target) bar.style.removeProperty('height');
    bar = target;
    document.documentElement.classList.toggle('desktop-sidebar-splitter', !!bar);
    if (!bar) return;
    handle = document.createElement('div');
    handle.className = 'desktop-bookmark-splitter';
    handle.tabIndex = 0;
    handle.setAttribute('role', 'separator');
    handle.setAttribute('aria-label', 'Resize bookmarks and tabs');
    handle.setAttribute('aria-orientation', 'horizontal');
    handle.setAttribute('aria-valuemin', '60');
    document.body.append(handle);
    let drag;
    handle.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      drag = { y: event.clientY, height: height() };
      handle.setPointerCapture(event.pointerId);
      handle.classList.add('dragging');
      event.preventDefault();
    });
    handle.addEventListener('pointermove', event => {
      if (drag) apply(drag.height + event.clientY - drag.y);
    });
    const end = () => { if (drag) save(); drag = null; handle.classList.remove('dragging'); };
    handle.addEventListener('pointerup', end);
    handle.addEventListener('lostpointercapture', end);
    handle.addEventListener('pointercancel', end);
    handle.addEventListener('keydown', event => {
      if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
      const step = event.shiftKey ? 30 : 10;
      apply(event.key === 'Home' ? 60 : event.key === 'End' ? innerHeight * .55 : height() + (event.key === 'ArrowUp' ? -step : step));
      save();
      event.preventDefault();
    });
    try {
      const stored = Number(localStorage.getItem(key));
      if (Number.isFinite(stored) && stored >= 60) apply(stored);
    } catch {}
    observer = new ResizeObserver(() => {
      handle.setAttribute('aria-valuenow', String(Math.round(height())));
      handle.setAttribute('aria-valuemax', String(Math.floor(innerHeight * .55)));
    });
    observer.observe(bar);
  }
  new MutationObserver(() => {
    if (!pending) { pending = true; requestAnimationFrame(mount); }
  }).observe(document.documentElement, { childList: true, subtree: true });
  mount();
})();
