#!/usr/bin/env python3
"""Offscreen harness for the RETURN LEG of the viewer handoff: flipping through
images in `viewer` moves this filer's selection with them.

filer launches viewer with `--select-back <sock>:<pane>`; viewer echoes each
image it lands on back at that socket; `Main.qml selectFromViewer` selects it in
the pane that asked. So closing the viewer leaves filer on the picture you
stopped at rather than the one you opened.

Both halves are REAL here — viewer's own `FilerLink` client (imported from
`../../viewer/main.py`) driving filer's own `Listener` and the real `qml/`. The
client runs off the GUI thread, exactly as it does across two processes: it is a
synchronous round trip, so calling it inline would have this test's listener
waiting on its own event loop.

What is worth asserting, i.e. what a reasonable-looking implementation gets
wrong:

  * the echo lands in the pane that OPENED the viewer, by `watchKey` — flipping
    in a viewer opened from the right-hand pane must not move the left one;
  * a pane that has navigated away, or a path it never listed, moves NOTHING —
    a window the person is not looking at must not go hunting for the file;
  * both models are searched: the preview grid (where an opened image came
    from) and the tree list (where one in an expanded subdirectory lives);
  * a picker takes no socket name at all, so a transient file chooser is never
    the thing a viewer reports to;
  * `filer-<pid>.sock` left by a killed filer is swept, and a LIVE one is not.

$XDG_RUNTIME_DIR is redirected to a temp dir before anything computes a socket
path, so this can never reach the filer or viewer the user has open. Offscreen;
no window is ever mapped.

    ./tools/viewer-select-test.py
"""
import importlib.util
import os
import pathlib
import shutil
import sys
import tempfile
import threading

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)
_RT = tempfile.mkdtemp(prefix="t_vselect-rt-")
os.environ["XDG_RUNTIME_DIR"] = _RT           # before handoff computes a path

FILER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS = os.path.dirname(FILER)
sys.path.insert(0, FILER)
sys.path.insert(0, os.path.join(APPS, "pylib"))

from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402
from PySide6.QtQml import QJSValue  # noqa: E402
from PySide6.QtQuick import QQuickItem  # noqa: E402,F401  (registers Item* for property())

import main as filermain  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def unwrap(v):
    return v.toVariant() if isinstance(v, QJSValue) else v


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def png(path, rgb):
    im = QImage(16, 16, QImage.Format_RGB32)
    im.fill(rgb)
    im.save(path, "png")
    return path


def dead_pid():
    """A pid nothing owns — for the stale-socket sweep."""
    for pid in range(4000000, 4001000):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return pid
        except OSError:
            continue
    raise SystemExit("no free pid to test the sweep with")


def echo(link, path, spin, timeout=2.0):
    """viewer's real client, off the GUI thread, pumping Qt while it waits —
    the listener under test is in THIS process's event loop."""
    t = threading.Thread(target=lambda: link.echo(path), daemon=True)
    t.start()
    while t.is_alive():
        QGuiApplication.processEvents()
    t.join(timeout)
    spin(120)


def sel(pane):
    return pane.property("selected")


def main():
    app = QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":   # a mapped window would be HIS screen
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())
    tmp = tempfile.mkdtemp(prefix="t_vselect-")
    try:
        run(app, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(_RT, ignore_errors=True)
    print()
    if FAILS:
        print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("all viewer-select checks passed")
    return 0


def run(app, tmp):
    split = load("fsplit", os.path.join(FILER, "tools", "split-test.py"))
    viewermain = load("viewermain", os.path.join(APPS, "viewer", "main.py"))

    home = os.path.join(tmp, "pics")
    sub = os.path.join(home, "sub")
    other = os.path.join(tmp, "other")
    os.makedirs(sub)
    os.makedirs(other)
    imgs = [png(os.path.join(home, "img%d.png" % i), c)
            for i, c in enumerate((0xffff0000, 0xff00ff00, 0xff0000ff, 0xffffff00))]
    deep = png(os.path.join(sub, "deep.png"), 0xff00ffff)
    png(os.path.join(other, "elsewhere.png"), 0xffff00ff)
    # this harness splits, which persists — never against the user's state.json
    filermain.STATE_PATH = pathlib.Path(tmp) / "state.json"

    engine, win, tb, watch, keep = split.build(app, home)   # noqa: F841
    win.show()
    split.spin(300)
    left = win.property("pane")

    # ---- the socket, and the token filer hands to viewer -------------------
    listener = filermain._start_select_listener(app, win)
    check("filer listens on a per-pid socket", listener.listening)
    check("...named for THIS process, so two filer windows never cross",
          filermain.SELECT_BACK_SOCK == "filer-%d" % os.getpid(),
          filermain.SELECT_BACK_SOCK)
    ops = keep[0]
    check("the token names the socket and the pane",
          ops.selectBackToken("left") == "filer-%d:left" % os.getpid(),
          ops.selectBackToken("left"))

    saved = filermain.SELECT_BACK_SOCK
    filermain.SELECT_BACK_SOCK = ""
    check("...and is empty when nothing is listening (a picker), so filer "
          "launches viewer without the flag",
          ops.selectBackToken("left") == "")
    filermain.SELECT_BACK_SOCK = saved

    # ---- the round trip ----------------------------------------------------
    link = viewermain.FilerLink(ops.selectBackToken("left"))
    check("viewer splits the token into socket and pane",
          (link._sock, link._pane) == ("filer-%d" % os.getpid(), "left"),
          (link._sock, link._pane))

    echo(link, imgs[2], split.spin)
    check("flipping in viewer selects that image in filer", sel(left) == imgs[2], sel(left))
    check("...as the only selection, the way a click would leave it",
          unwrap(left.property("selection")) == [imgs[2]],
          unwrap(left.property("selection")))

    echo(link, imgs[0], split.spin)
    check("...and it follows every flip", sel(left) == imgs[0], sel(left))

    # ---- the tree list, not just the preview grid --------------------------
    left.toggleExpand(sub)
    split.spin(200)
    echo(link, deep, split.spin)
    check("an image in an expanded subdirectory is found in the list too",
          sel(left) == deep, sel(left))

    # ---- a path this pane is not showing moves nothing ----------------------
    before = sel(left)
    echo(link, os.path.join(other, "elsewhere.png"), split.spin)
    check("a file the pane does not list moves nothing — it does not go and "
          "find it", sel(left) == before, sel(left))
    check("...and revealPath says so", left.revealPath(os.path.join(other, "x.png")) is False)

    # ---- which pane ---------------------------------------------------------
    win.toggleSplit()
    split.spin(300)
    right = win.property("pane")
    check("the split opened a second pane", right is not None and right is not left)
    right.go(home)
    split.spin(250)
    check("...showing the same directory, so the routing is the only thing "
          "under test", right.property("path") == home, right.property("path"))

    rlink = viewermain.FilerLink(ops.selectBackToken("right"))
    echo(rlink, imgs[3], split.spin)
    check("a viewer opened from the right pane moves the RIGHT pane",
          sel(right) == imgs[3], sel(right))
    check("...and leaves the left one where it was", sel(left) == before, sel(left))

    echo(link, imgs[1], split.spin)
    check("...and the left pane's viewer still moves the left pane",
          sel(left) == imgs[1] and sel(right) == imgs[3], (sel(left), sel(right)))

    # A pane key nothing answers to (the split closed while the viewer was
    # open): the selection still has to land somewhere honest.
    blink = viewermain.FilerLink("filer-%d:gone" % os.getpid())
    echo(blink, imgs[0], split.spin)
    check("an unknown pane key falls back to the focused pane",
          sel(win.property("pane")) == imgs[0], sel(win.property("pane")))

    # ---- a request that is not a select ------------------------------------
    import handoff  # noqa: PLC0415  (after $XDG_RUNTIME_DIR was redirected)
    got = {}
    t = threading.Thread(
        target=lambda: got.update(r=handoff.send(filermain.SELECT_BACK_SOCK,
                                                 {"argv": ["nonsense"]}, timeout=2.0)),
        daemon=True)
    t.start()
    while t.is_alive():
        QGuiApplication.processEvents()
    t.join(2.0)
    check("a payload that is not a select is refused, not guessed at",
          got.get("r") == {"taken": False}, got.get("r"))

    # ---- the stale-socket sweep --------------------------------------------
    ghost = os.path.join(_RT, "filer-%d.sock" % dead_pid())
    open(ghost, "w").close()
    filermain._sweep_stale_socks()
    check("a socket left by a killed filer is swept", not os.path.exists(ghost))
    check("...and the live one is left alone",
          os.path.exists(handoff.sock_path(filermain.SELECT_BACK_SOCK)))


if __name__ == "__main__":
    sys.exit(main())
