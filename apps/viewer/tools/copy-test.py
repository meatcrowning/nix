#!/usr/bin/env python3
"""Offscreen harness for viewer's right-click menu and its one row, "copy image".

It posts a REAL right-click at a pane in the REAL qml/Main.qml and then clicks
the row that comes up, so the TapHandler, CtxMenu, the trigger closure, the
`Clip` bridge and the footer report are all exercised together.

**It never touches his clipboard.** `main.CLIPFILE` is repointed at a stub
script that records its argv and exits with whatever code the test wants, so
nothing here speaks the Wayland data-control protocol at all. The real thing —
that clipfile actually owns the selection and offers what it says it does — is
`apps/pylib/tools/clipfile-test.sh`, inside a headless sway of its own.

Run it with viewer's own Qt env (see ../AGENTS.md), not the bare system python:

    python3 apps/viewer/tools/copy-test.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# split-test does the environment hardening (offscreen, no WAYLAND_DISPLAY, a
# scratch XDG_CONFIG_HOME) at import time, and owns build().
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("splittest", os.path.join(HERE, "split-test.py"))
splittest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(splittest)

from PySide6.QtCore import QEvent, QObject, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QMouseEvent  # noqa: E402

import main as viewermain  # noqa: E402

build, check, spin, png, centre = (splittest.build, splittest.check,
                                   splittest.spin, splittest.png, splittest.centre)
SCRATCH = splittest.SCRATCH

# The stub that stands in for pylib/clipfile.py. `RC` and `ARGV` below are
# rewritten between checks; it never sets a selection.
STUB = os.path.join(SCRATCH, "clipstub.py")
ARGV_LOG = os.path.join(SCRATCH, "clipstub-argv")
RC_FILE = os.path.join(SCRATCH, "clipstub-rc")


def write_stub():
    with open(STUB, "w") as f:
        f.write(
            "import sys\n"
            "open(%r, 'a').write(repr(sys.argv[1:]) + '\\n')\n"
            "rc = int(open(%r).read().strip())\n"
            "if rc:\n"
            "    sys.stderr.write('first line\\nthe compositor said no\\n')\n"
            "sys.exit(rc)\n" % (ARGV_LOG, RC_FILE))


def set_rc(rc):
    with open(RC_FILE, "w") as f:
        f.write(str(rc))


def runs():
    try:
        return [eval(line) for line in open(ARGV_LOG) if line.strip()]  # noqa: S307
    except OSError:
        return []


def clear_runs():
    if os.path.exists(ARGV_LOG):
        os.unlink(ARGV_LOG)


def rclick(win, pos):
    """A real right press/release at window coordinates `pos`."""
    p = QPointF(pos)
    for typ in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        QGuiApplication.sendEvent(
            win, QMouseEvent(typ, p, p, Qt.RightButton,
                             Qt.RightButton if typ == QEvent.MouseButtonPress else Qt.NoButton,
                             Qt.NoModifier))
    spin(60)


def lclick(win, x, y):
    p = QPointF(x, y)
    QGuiApplication.sendEvent(win, QMouseEvent(QEvent.MouseButtonPress, p, p, Qt.LeftButton,
                                               Qt.LeftButton, Qt.NoModifier))
    QGuiApplication.sendEvent(win, QMouseEvent(QEvent.MouseButtonRelease, p, p, Qt.LeftButton,
                                               Qt.NoButton, Qt.NoModifier))
    spin(60)


def menu_rows(menu):
    """The visible menu's row labels, read off its items model."""
    items = menu.property("items")
    if hasattr(items, "toVariant"):     # a JS array arrives as one QJSValue
        items = items.toVariant()
    return [it.get("label", "") for it in (items or []) if isinstance(it, dict)]


def first_row_point(menu):
    """Window coordinates inside the first row of the open menu. The panel is
    the menu's only Rectangle child; a row is Theme.fontSize tall."""
    panel = None
    for kid in menu.children():
        if kid.property("contentWidth") is not None and kid.property("width"):
            panel = kid
            break
    x = menu.property("x") + panel.property("x") + 20
    y = menu.property("y") + panel.property("y") + 1 + panel.property("height") / 4
    return x, y


def wait_for(fn, ms=4000):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        if fn():
            return True
        spin(50)
    return False


def main():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":   # a mapped window would be HIS screen
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())
    write_stub()
    set_rc(0)
    viewermain.CLIPFILE = STUB          # never the real clipfile

    img = png(os.path.join(SCRATCH, "shot.png"), (10, 20, 30))
    vid = os.path.join(SCRATCH, "clip.mp4")
    open(vid, "wb").write(b"not really a video")
    entries = [{"name": "shot.png", "path": img}, {"name": "clip.mp4", "path": vid}]

    engine, win, keep = build(app, entries, 0, 1)
    win.show()
    spin(250)
    menu = win.findChild(QObject, "ctxMenu")
    if menu is None:
        raise SystemExit("no CtxMenu named ctxMenu in Main.qml")

    print("\n== the menu ==")
    check("no menu until asked", not menu.property("visible"))
    rclick(win, centre(win, 0))
    check("a right-click opens it", menu.property("visible") is True)
    check("on an image, the row is 'copy image'", menu_rows(menu) == ["copy image"],
          menu_rows(menu))

    # Escape closes it again (CtxMenu's own focus sink)
    splittest.key(win, Qt.Key_Escape)
    check("Escape closes it", not menu.property("visible"))

    print("\n== copying an image ==")
    clear_runs()
    rclick(win, centre(win, 0))
    x, y = first_row_point(menu)
    lclick(win, x, y)
    check("the row dismisses the menu", not menu.property("visible"))
    check("clipfile ran once", wait_for(lambda: len(runs()) == 1), runs())
    check("...with --image and the path", runs() and runs()[0] == ["--image", img], runs())
    check("the footer says it copied",
          wait_for(lambda: win.property("flashMsg") == "copied shot.png"),
          win.property("flashMsg"))
    check("...and the footer text is what the titlebar is given",
          win.property("footerStr") == "copied shot.png", win.property("footerStr"))

    print("\n== a video is offered as a file, not as a picture ==")
    win.next()
    spin(80)
    clear_runs()
    rclick(win, centre(win, 0))
    check("the row is 'copy file'", menu_rows(menu) == ["copy file"], menu_rows(menu))
    x, y = first_row_point(menu)
    lclick(win, x, y)
    check("clipfile ran with no --image",
          wait_for(lambda: runs() == [[vid]]), runs())

    print("\n== a failure is REPORTED, not swallowed ==")
    set_rc(1)
    win.prev()
    spin(80)
    clear_runs()
    rclick(win, centre(win, 0))
    x, y = first_row_point(menu)
    lclick(win, x, y)
    check("the footer carries clipfile's own last line",
          wait_for(lambda: win.property("flashMsg") == "copy failed: the compositor said no"),
          win.property("flashMsg"))

    print("\n== a file that went away ==")
    set_rc(0)
    clear_runs()
    os.unlink(img)
    keep[4].copyImage(img)
    check("says so, and spawns nothing",
          wait_for(lambda: win.property("flashMsg") == "can't copy shot.png: it is gone")
          and runs() == [], (win.property("flashMsg"), runs()))
    png(img, (10, 20, 30))

    print("\n== the flash is temporary ==")
    keep[4].copyImage(img)
    check("copied", wait_for(lambda: win.property("flashMsg") == "copied shot.png"))
    check("...and the footer goes back to the position readout",
          wait_for(lambda: win.property("flashMsg") == "", 6000)
          and win.property("footerStr").endswith("shot.png"),
          win.property("footerStr"))

    print("")
    if splittest.FAILS:
        print("%d failed: %s" % (len(splittest.FAILS), ", ".join(splittest.FAILS)))
        return 1
    print("copy: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
