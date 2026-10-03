// Freeze the origin while Steam restores its route history. Intermediate
// autofocus events must not replace the game/scroll position we left from.
export function createHomeHistory() {
  return {
    appid: null, scroll: 0, pending: null, returned: null,
    interact() { this.pending = null; this.returned = null; },
    navigationOrigin(appid) {
      const origin = (this.pending || this.returned)?.appid ?? appid;
      this.interact();
      return origin;
    },
    select(appid) {
      const saved = this.pending || this.returned;
      if (saved && saved.appid !== appid) {
        this.pending = saved;
        return false;
      }
      this.appid = appid;
      return true;
    },
    measure(scroll) { if (!this.pending && !this.returned) this.scroll = scroll; },
    leave(appid, scroll) {
      this.returned = null;
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
      // Steam may restore another child after TakeFocus succeeds. Keep the
      // origin until actual navigation, not an arbitrary animation timeout.
      this.returned = saved;
      this.appid = saved.appid; this.scroll = viewport.scrollTop;
      return true;
    },
  };
}
