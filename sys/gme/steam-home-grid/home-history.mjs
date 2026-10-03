// Freeze the origin while Steam restores its route history. Intermediate
// autofocus events must not replace the game/scroll position we left from.
export function createHomeHistory() {
  return {
    appid: null, scroll: 0, pending: null,
    select(appid) {
      if (this.pending && this.pending.appid !== appid) return false;
      this.appid = appid;
      return true;
    },
    measure(scroll) { if (!this.pending) this.scroll = scroll; },
    leave(appid, scroll) {
      this.appid = appid; this.scroll = scroll;
      this.pending = { appid, scroll };
    },
    restore(handles, viewport) {
      const saved = this.pending;
      const handle = saved && handles.get(saved.appid);
      if (!handle) return false;
      this.pending = null;
      if (!handle.TakeFocus()) { this.pending = saved; return false; }
      viewport.scrollTop = saved.scroll;
      this.appid = saved.appid; this.scroll = viewport.scrollTop;
      return true;
    },
  };
}
