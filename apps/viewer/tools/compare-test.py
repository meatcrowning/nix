#!/usr/bin/env python3
"""Offscreen harness for viewer's --compare reveal slider.

Loads the REAL qml/Main.qml in compare mode (as `viewer --compare <before>
<after>` does) under QT_QPA_PLATFORM=offscreen, and asserts the contract painter
drives: the two paths land as before (left) and after (right), the pane grid is
NOT built, the reveal line starts centred and then TRACKS THE POINTER 1:1 with
no click, and the before image is revealed by a clip box pinned to x:0 (so it
never rescales as the line moves). The *appearance* is the user's visual check.

Also checks the argv contract at the python level: `--compare a b` parses to the
pair in order and is kept out of the flip list, and its presence forces its own
window (the handoff is skipped).

    python3 apps/viewer/tools/compare-test.py

Run it with viewer's own Qt env, the same way split-test.py is (viewer/AGENTS.md).
"""
import os
import sys
import tempfile

SCRATCH = tempfile.mkdtemp(prefix="t_viewer-compare-")
os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session
os.environ.pop("DISPLAY", None)
os.environ["XDG_CONFIG_HOME"] = os.path.join(SCRATCH, "config")

VIEWER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, VIEWER)
sys.path.insert(0, os.path.join(os.path.dirname(VIEWER), "pylib"))

from PySide6.QtCore import Qt, QPointF, QEvent  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QColor, QMouseEvent, QKeyEvent  # noqa: E402

import main as viewermain  # noqa: E402
# Reuse split-test's build()/spin()/png() — the shared way every viewer harness
# loads the real Main.qml with all its context properties installed. Loaded by
# path because the filename has a dash.
import importlib.util as _ilu  # noqa: E402
_spec = _ilu.spec_from_file_location(
    "viewer_split_test",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "split-test.py"))
splittest = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(splittest)
build, spin, png = splittest.build, splittest.spin, splittest.png

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def child(win, name):
    for c in win.findChildren(object):
        if c.objectName() == name:
            return c
    return None


def move(win, x, y):
    """Post a real hover MouseMove (no buttons) at window coords (x, y)."""
    p = QPointF(x, y)
    ev = QMouseEvent(QEvent.MouseMove, p, Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    QGuiApplication.sendEvent(win, ev)
    spin(40)


def key(win, k):
    QGuiApplication.sendEvent(win, QKeyEvent(QKeyEvent.KeyPress, k, Qt.NoModifier))
    QGuiApplication.sendEvent(win, QKeyEvent(QKeyEvent.KeyRelease, k, Qt.NoModifier))
    spin(40)


def main():
    app = QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())

    d = os.path.join(SCRATCH, "pics")
    os.makedirs(d)
    before = png(os.path.join(d, "input.png"), (20, 20, 20))
    after = png(os.path.join(d, "output.png"), (200, 40, 40))

    # ---- 1. the argv contract ----
    order, split, back, rest, comp = viewermain.split_args(
        ["--compare", before, after])
    check("--compare parses its two paths in order (before, after)",
          comp == (before, after), comp)
    check("...and keeps them out of the flip list", rest == [], rest)
    check("split_args without --compare returns compare=None",
          viewermain.split_args([before])[4] is None)
    check("a lone --compare (missing a path) does not crash and yields no pair",
          viewermain.split_args(["--compare", before])[4] is None)

    # ---- 2. the window opens straight into compare mode ----
    be = viewermain.entry(before)
    af = viewermain.entry(after)
    engine, win, keep = build(app, [be, af], compare=(be, af))
    win.show()
    spin(250)
    check("compare mode is on", win.property("compare") is True)
    check("...and the pane grid is NOT built (no ImageViewer panes)",
          win.property("paneCount") == 0, win.property("paneCount"))

    cv = child(win, "compareView")
    check("the CompareView is loaded", cv is not None)
    if cv is None:
        finish()
        return
    check("before is the first path, after the second",
          cv.property("beforePath") == before and cv.property("afterPath") == after,
          (cv.property("beforePath"), cv.property("afterPath")))

    # ---- 3. the reveal line is centred until the pointer first tracks it ----
    # (offscreen may synthesize an initial hover, which is the real "follows the
    # mouse" behaviour; the centring is the binding value while untracked.)
    W = cv.property("width")
    cv.setProperty("tracked", False)
    spin(20)
    check("the reveal line is centred before the pointer tracks it",
          abs(cv.property("splitX") - W / 2) < 1.0, (cv.property("splitX"), W))

    # ---- 4. it follows the pointer 1:1, no click ----
    tx = W * 0.3
    move(win, tx, cv.property("height") / 2)
    check("a bare hover move (no button) tracks the line to the pointer x",
          abs(cv.property("clampedX") - tx) < 2.0, (cv.property("clampedX"), tx))
    tx2 = W * 0.75
    move(win, tx2, cv.property("height") / 2)
    check("...and follows it again to the right",
          abs(cv.property("clampedX") - tx2) < 2.0, (cv.property("clampedX"), tx2))

    # ---- 5. the reveal is a clip, not a rescale ----
    # The before image sits inside a clip box pinned at x:0 whose width is the
    # reveal point; the image itself is the full window width, so it never
    # rescales as the line moves — only what shows changes.
    clip = None
    for c in cv.findChildren(object):
        # the clip Item is the one whose width equals clampedX and clips
        if c.property("clip") is True and abs((c.property("width") or -1)
                                              - cv.property("clampedX")) < 2.0:
            clip = c
            break
    check("the before image is revealed by a clip box the width of the reveal point",
          clip is not None)

    # ---- 6. the chrome is a comparison, not a flip list ----
    check("no flip/zoom/split titlebar buttons in compare mode",
          len(splittest.unwrap(win.property("tbButtons"))) == 0,
          win.property("tbButtons"))
    fs = win.property("footerStr")
    check("the footer names both sides",
          "input.png" in fs and "output.png" in fs, fs)

    # ---- 7. the reveal is clamped to the window ----
    # A pointer only reports moves INSIDE the window, so an out-of-range trackX
    # can only ever come from a resize or a stray value; clampedX must still hold
    # the line on-screen. Driven through trackX directly, since an off-window
    # mouse move is never delivered to the MouseArea to begin with.
    cv.setProperty("trackX", -500)
    spin(20)
    check("an out-of-range reveal point clamps to 0 on the left",
          abs(cv.property("clampedX")) < 0.01, cv.property("clampedX"))
    cv.setProperty("trackX", W + 500)
    spin(20)
    check("...and to the full width on the right",
          abs(cv.property("clampedX") - W) < 0.01, (cv.property("clampedX"), W))

    # ---- 8. q still quits ----
    quits = []
    engine.quit.connect(lambda: quits.append(1))
    key(win, Qt.Key_Q)
    check("`q` quits the comparison window", len(quits) == 1, quits)

    finish()


def finish():
    print()
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        sys.exit(1)
    print("all compare checks passed")


if __name__ == "__main__":
    main()
