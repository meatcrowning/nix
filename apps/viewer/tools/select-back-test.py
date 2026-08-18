#!/usr/bin/env python3
"""Offscreen harness for `--select-back`: viewer telling filer where it got to.

filer passes `--select-back <sock>:<pane>` when it opens an image; every time
the focused pane lands on a different picture, viewer echoes that path at the
socket and filer selects it (the filer half, including the real round trip, is
`../../filer/tools/viewer-select-test.py`). This half covers what viewer owes:

  * the flag is CONSUMED — anything left in `rest` is opened as a file, so a
    token that fell through would be "opened" as a path;
  * flipping echoes, and echoes the image actually on screen;
  * it is DEBOUNCED: holding › walks the folder as fast as it decodes, and each
    echo is a synchronous round trip on the GUI thread. One at rest is what
    filer needs;
  * changing the focused pane echoes that pane's image — the chrome and the
    echo must agree on what "current" means;
  * a viewer opened with no token (`viewer x.png` from a terminal) echoes
    NOWHERE, and a handoff re-points the echo at whichever filer just asked, so
    a second filer's click is not reported to the first one.

The far end is a plain socket server in a thread, not a Qt Listener: the echo is
synchronous on the GUI thread, so a listener in this process's event loop would
be waiting for a reply that only the same thread could send. $XDG_RUNTIME_DIR is
redirected before anything computes a socket path, so this can never reach the
filer the user has open. Offscreen; no window is ever mapped.

    ./tools/select-back-test.py
"""
import importlib.util
import json
import os
import shutil
import socket
import sys
import tempfile
import threading

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)
_RT = tempfile.mkdtemp(prefix="t_vback-rt-")
os.environ["XDG_RUNTIME_DIR"] = _RT           # before handoff computes a path

VIEWER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, VIEWER)
sys.path.insert(0, os.path.join(os.path.dirname(VIEWER), "pylib"))

from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402

import handoff  # noqa: E402
import main as viewermain  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


class StubFiler:
    """The listening half, in a thread: records every payload and answers it.

    Answers, always — an echo that got no reply would sit on the GUI thread for
    handoff.TIMEOUT, and this test would be measuring that instead of the
    debounce."""

    def __init__(self, name):
        self.path = handoff.sock_path(name)
        self.got = []
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(self.path)
        self._srv.listen(8)
        self._srv.settimeout(0.2)
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._serve, daemon=True)
        self._t.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(1.0)
                buf = b""
                try:
                    while b"\n" not in buf:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
                    if buf:
                        self.got.append(json.loads(buf.split(b"\n", 1)[0].decode()))
                    conn.sendall(b'{"taken": true}\n')
                except OSError:
                    pass

    def stop(self):
        self._stop.set()
        self._t.join(2.0)
        self._srv.close()


def main():
    app = QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":   # a mapped window would be HIS screen
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())
    tmp = tempfile.mkdtemp(prefix="t_vback-")
    stub = StubFiler("stub-filer")
    try:
        run(app, tmp, stub)
    finally:
        stub.stop()
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(_RT, ignore_errors=True)
    print()
    if FAILS:
        print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("all select-back checks passed")
    return 0


def run(app, tmp, stub):
    spec = importlib.util.spec_from_file_location(
        "vsplit", os.path.join(VIEWER, "tools", "split-test.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # ---- the flag, before any of it reaches a window ----------------------
    o, s, b, rest, _cmp = viewermain.split_args(
        ["--select-back", "filer-9:left", "--order", "/tmp/o", "a.png"])
    check("--select-back is consumed, not treated as a file",
          rest == ["a.png"] and b == "filer-9:left" and o == "/tmp/o" and s is False,
          (rest, b))
    check("...in its = form too",
          viewermain.split_args(["--select-back=filer-9:right", "a.png"])[2:4]
          == ("filer-9:right", ["a.png"]))
    check("a viewer nobody asked has no token",
          viewermain.split_args(["a.png"])[2] == "")

    link = viewermain.FilerLink("filer-9:left")
    check("the token splits on the LAST colon", (link._sock, link._pane) == ("filer-9", "left"))
    link.setToken("bare-socket")
    check("...and a token with no pane is all socket",
          (link._sock, link._pane) == ("bare-socket", ""))
    link.setToken("")
    link.echo("/tmp/whatever.png")      # must not raise, must not send
    check("an echo with no token is a no-op", stub.got == [], stub.got)

    # ---- the window ---------------------------------------------------------
    names = []
    for i, c in enumerate((0xffff0000, 0xff00ff00, 0xff0000ff, 0xffffff00)):
        p = os.path.join(tmp, "img%d.png" % i)
        im = QImage(16, 16, QImage.Format_RGB32)
        im.fill(c)
        im.save(p, "png")
        names.append(p)
    entries = [{"name": os.path.basename(p), "path": p} for p in names]
    engine, win, keep = mod.build(app, entries, 0, 1)   # noqa: F841
    win.show()
    mod.spin(400)
    filerlink = keep[5]
    filerlink.setToken("stub-filer:left")
    del stub.got[:]

    win.next()
    mod.spin(400)
    check("flipping echoes the new image at filer",
          stub.got == [{"select": names[1], "pane": "left"}], stub.got)

    # ---- the debounce -------------------------------------------------------
    del stub.got[:]
    win.next(); win.next(); win.next()   # noqa: E702  — a held ›, three frames
    mod.spin(400)
    check("a burst of flips echoes ONCE, not once per image",
          len(stub.got) == 1, stub.got)
    check("...and what it echoes is where the burst STOPPED",
          stub.got and stub.got[0]["select"] == names[0], stub.got)

    # ---- the focused pane is what gets reported -----------------------------
    del stub.got[:]
    win.addPane()                        # opens on the image after the last one
    mod.spin(400)
    check("focusing another pane echoes THAT pane's image",
          stub.got == [{"select": names[1], "pane": "left"}], stub.got)

    # ---- a handoff re-points the echo ---------------------------------------
    del stub.got[:]
    filerlink.setToken(viewermain.split_args(["--select-back", "stub-filer:right",
                                              names[2]])[2])
    win.next()
    mod.spin(400)
    check("a later open re-points the echo at the filer pane that asked",
          stub.got == [{"select": names[2], "pane": "right"}], stub.got)

    del stub.got[:]
    filerlink.setToken("")               # `viewer x.png` from a terminal
    win.next()
    mod.spin(400)
    check("a viewer opened with no token echoes nowhere", stub.got == [], stub.got)


if __name__ == "__main__":
    sys.exit(main())
