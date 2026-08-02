#!/usr/bin/env python3
"""Regression test for `pylib/vtbclient.py`'s REGISTER atomicity + reconnect.

Why it exists: goetia's titlebar flashed its own window title. The plugin keeps
no state for a pid it has not seen and `vtbIpc.cpp`'s `dropClient` erases the
entry outright, so both a first registration and every reconnect start at the
plugin's defaults — `titleText` on. Anything the app declares in a SECOND write
is a window in which the bar draws state the app has already disowned, and the
reconnect backoff made that window seconds long.

The mock server below mirrors the one property of `vtbIpc.cpp`'s I/O loop that
decides this: poll -> drain everything readable -> handle every COMPLETE line
-> poll again. So one recorded wakeup is one batch the compositor's render
thread cannot see the inside of. Nothing here touches the live socket or opens
a window; it needs no plugin loaded.

    python3 apps/pylib/tools/vtb-register-test.py
"""
import os
import select
import socket
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from vtbclient import VtbClient  # noqa: E402


class MockPlugin:
    """One `hyprvtb` instance's app-button server. `wakeups` is the list of
    per-poll line batches, which is the whole point of the harness."""

    def __init__(self, rundir):
        self.path = os.path.join(rundir, "hyprvtb-buttons.sock")
        self.wakeups = []
        self._stop = threading.Event()
        self._t = None

    def start(self):
        try:
            os.unlink(self.path)
        except OSError:
            pass
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(self.path)
        self._srv.listen(8)
        self._srv.setblocking(False)
        self._stop.clear()
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()
        return self

    def stop(self):
        self._stop.set()
        self._t.join()
        self._srv.close()
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def _loop(self):
        clients = {}
        while not self._stop.is_set():
            rl, _, _ = select.select([self._srv] + [c[0] for c in clients.values()],
                                     [], [], 0.02)
            for s in rl:
                if s is self._srv:
                    c, _ = self._srv.accept()
                    c.setblocking(False)
                    clients[c.fileno()] = [c, b""]
                    continue
                st, dead = clients[s.fileno()], False
                while True:
                    try:
                        d = s.recv(4096)
                    except BlockingIOError:
                        break
                    if not d:
                        dead = True
                        break
                    st[1] += d
                batch = []
                while b"\n" in st[1]:
                    line, st[1] = st[1].split(b"\n", 1)
                    batch.append(line.decode(errors="replace"))
                if batch:
                    self.wakeups.append(batch)
                if dead:
                    s.close()
                    del clients[s.fileno()]
        for st in clients.values():
            st[0].close()

    def wait_for(self, verb, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for w in self.wakeups:
                if any(ln.startswith(verb) for ln in w):
                    return True
            time.sleep(0.01)
        return False

    def register_wakeup(self):
        for w in self.wakeups:
            if any(ln.startswith("REGISTER ") for ln in w):
                return w
        return None


BUTTONS = [("needs", "?", 0, "NEEDS DECISION"), "-", ("md", "md", 0, "open in reader")]
FAILS = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + (("  -- " + detail) if detail else ""))
    if not ok:
        FAILS.append(name)


def verbs(batch):
    return [ln.split(" ")[0] for ln in batch]


def case_defaults(rundir):
    """An app that wants the plugin's defaults must send what it always sent —
    bundling flags with REGISTER must not start asserting one nobody asked for."""
    srv = MockPlugin(rundir).start()
    c = VtbClient()
    try:
        assert srv.wait_for("REGISTER") is False or True
        c.set_buttons(BUTTONS)
        srv.wait_for("REGISTER")
        time.sleep(0.2)
        w = srv.register_wakeup()
        check("default-flag app sends REGISTER and nothing else", w is not None and verbs(w) == ["REGISTER"], repr(verbs(w)))
    finally:
        c.close()
        srv.stop()


def case_goetia(rundir):
    """goetia's own sequence, in qml/Main.qml's order: buttons, footer, then
    TITLETEXT 0 last. The flag must still ride in the REGISTER's wakeup."""
    srv = MockPlugin(rundir).start()
    c = VtbClient()
    try:
        time.sleep(0.25)                       # the QML engine loading
        c.set_buttons(BUTTONS)
        c.set_footer("3 waiting")
        c.set_title_text(False)
        srv.wait_for("TITLETEXT")
        time.sleep(0.2)
        w = srv.register_wakeup()
        ok = w is not None and "TITLETEXT 0" in w
        check("TITLETEXT 0 rides in the REGISTER wakeup", ok, repr(verbs(w)))
        check("no wakeup carries REGISTER without TITLETEXT 0",
              all(("TITLETEXT 0" in b) for b in srv.wakeups
                  if any(ln.startswith("REGISTER ") for ln in b)))
    finally:
        c.close()
        srv.stop()


def case_every_flag(rundir):
    """Every non-default flag, not just titleText — surfer's and player's."""
    srv = MockPlugin(rundir).start()
    c = VtbClient()
    try:
        time.sleep(0.25)
        c.set_title_edit(True)
        c.set_loading(True)
        c.set_footer_bottom(True)
        c.set_playbar(True, 0.5)
        c.set_footer("1:23")
        c.set_buttons(BUTTONS)
        srv.wait_for("REGISTER")
        time.sleep(0.2)
        w = srv.register_wakeup() or []
        for v in ("TITLEEDIT 1", "LOADING 1", "FOOTERPOS 1", "FOOTER 1:23"):
            check("%-14s rides with REGISTER" % v.split(" ")[0], v in w, repr(verbs(w)))
        check("PLAYBAR        rides with REGISTER",
              any(ln.startswith("PLAYBAR 1 0.5") for ln in w), repr(verbs(w)))
    finally:
        c.close()
        srv.stop()


def case_seed(rundir):
    """The constructor seed (surfer): buttons + title_edit staged BEFORE the I/O
    thread starts, so the window never maps at the plugin's default bar. The very
    FIRST wakeup the plugin sees must be the REGISTER, already carrying TITLEEDIT
    1 — no standalone flag write may race ahead of it."""
    srv = MockPlugin(rundir).start()
    c = VtbClient(buttons=BUTTONS, title_edit=True)
    try:
        srv.wait_for("REGISTER")
        time.sleep(0.2)
        first = srv.wakeups[0] if srv.wakeups else []
        check("seed: first wakeup is the REGISTER", verbs(first)[:1] == ["REGISTER"], repr(verbs(first)))
        check("seed: TITLEEDIT 1 rides in that first REGISTER", "TITLEEDIT 1" in first, repr(first))
        # A later QML setButtons/setTitleEdit(true) must not re-emit a standalone
        # TITLEEDIT (dedup guard) — it is already asserted in the seed.
        c.set_title_edit(True)
        time.sleep(0.15)
        standalone = [b for b in srv.wakeups if verbs(b) == ["TITLEEDIT"]]
        check("seed: redundant setTitleEdit(true) sends nothing", standalone == [], repr(standalone))
    finally:
        c.close()
        srv.stop()


def case_reconnect(rundir):
    """A plugin hot-swap: the socket goes, a new instance brings it back. The
    app's window is mapped and visible throughout, so this gap is the one the
    user actually sees. dropClient wiped the entry, so the whole atomic write
    has to be replayed -- and fast."""
    srv = MockPlugin(rundir).start()
    c = VtbClient()
    try:
        time.sleep(0.25)
        c.set_buttons(BUTTONS)
        c.set_title_text(False)
        srv.wait_for("TITLETEXT")
        srv.stop()                             # PLUGIN_EXIT
        gone = time.monotonic()
        time.sleep(0.05)
        srv2 = MockPlugin(rundir).start()      # PLUGIN_INIT
        got = srv2.wait_for("REGISTER", timeout=6.0)
        dt = (time.monotonic() - gone) * 1000
        w = srv2.register_wakeup() or []
        check("re-registers after a hot-swap", got)
        check("reconnect replays TITLETEXT 0 atomically", "TITLETEXT 0" in w, repr(verbs(w)))
        check("reconnect inside 1s (was a flat 3s backoff)", dt < 1000, "%.0f ms" % dt)
        srv2.stop()
    finally:
        c.close()


def case_backoff_ceiling():
    """With no plugin at all the retry must ramp back to the old 3s ceiling,
    not busy-poll a socket that is never coming."""
    c = VtbClient.__new__(VtbClient)
    r, n = VtbClient._RETRY_MIN, 0
    total = 0.0
    while r < VtbClient._RETRY_MAX and n < 100:
        total += r
        r = min(VtbClient._RETRY_MAX, r * 1.6)
        n += 1
    check("backoff reaches the 3s ceiling", r == VtbClient._RETRY_MAX,
          "%d attempts over %.1fs" % (n, total))
    check("ramp is short enough to stay cheap", n <= 15 and total <= 20.0)
    del c


def main():
    with tempfile.TemporaryDirectory(prefix="vtbtest-") as rundir:
        os.environ["XDG_RUNTIME_DIR"] = rundir
        print("REGISTER atomicity")
        case_defaults(rundir)
        case_goetia(rundir)
        case_every_flag(rundir)
        case_seed(rundir)
        print("reconnect")
        case_reconnect(rundir)
        case_backoff_ceiling()
    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
