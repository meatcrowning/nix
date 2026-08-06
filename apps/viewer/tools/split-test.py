#!/usr/bin/env python3
"""Offscreen harness for viewer's split view + per-pane drops.

Loads the REAL qml/Main.qml under QT_QPA_PLATFORM=offscreen with a scratch
XDG_CONFIG_HOME, then drives it the way the user does: adds and closes panes,
posts real QDragEnter/QDragMove/QDrop events at a chosen pane, sends key events,
drags a divider. Everything asserted is a property or a geometry function on the
window, so pane layout, drop routing, focus and the persisted divider weights are
all checkable with no window on anyone's screen. The *appearance* (the divider,
the focus frame, the drop highlight) is the user's visual check.

Titlebar is stubbed — the real one talks to the hyprvtb socket, which would
register buttons against this harness's pid in the live compositor.

    python3 apps/viewer/tools/split-test.py
"""
import os
import sys
import tempfile
import time

SCRATCH = tempfile.mkdtemp(prefix="t_viewer-split-")
os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session: with no
os.environ.pop("DISPLAY", None)          # display Qt aborts, it cannot fall back
os.environ["XDG_CONFIG_HOME"] = os.path.join(SCRATCH, "config")

VIEWER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, VIEWER)
sys.path.insert(0, os.path.join(os.path.dirname(VIEWER), "pylib"))
from deskstyle import DeskStyle  # noqa: E402  (pylib; Theme.qml binds to it)

from PySide6.QtCore import QUrl, QObject, Slot, QMimeData, QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtGui import (QGuiApplication, QImage, QColor, QKeyEvent,  # noqa: E402
                           QDragEnterEvent, QDragMoveEvent, QDropEvent)
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QJSValue  # noqa: E402

import main as viewermain  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


class StubTitlebar(QObject):
    @Slot("QVariantList")
    def setButtons(self, b): pass
    @Slot(str)
    def setFooter(self, t): pass
    @Slot(bool, float)
    def setPlaybar(self, shown, pos): pass


def unwrap(v):
    return v.toVariant() if isinstance(v, QJSValue) else v


def spin(ms=120):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QGuiApplication.processEvents()
        time.sleep(0.005)


def png(path, rgb):
    img = QImage(16, 16, QImage.Format_RGB32)
    img.fill(QColor(*rgb))
    img.save(path, "PNG")
    return path


def build(app, entries, index=0, panes=1):
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    keep = (viewermain.Palette(viewermain.PANEL_THEME), StubTitlebar(),
            viewermain.Files(), viewermain.Prefs())
    _deskstyle = DeskStyle(parent=engine)
    ctx.setContextProperty("WalPalette", keep[0])
    # Theme.qml binds font/fontSize to DeskStyle (pylib/deskstyle.py), so the
    # harness must install it too or the theme loads with an empty font.
    ctx.setContextProperty("DeskStyle", _deskstyle)
    ctx.setContextProperty("Titlebar", keep[1])
    ctx.setContextProperty("Files", keep[2])
    ctx.setContextProperty("Prefs", keep[3])
    ctx.setContextProperty("startImages", entries)
    ctx.setContextProperty("startIndex", index)
    ctx.setContextProperty("startPanes", panes)
    ctx.setContextProperty("maxPanes", viewermain.MAX_PANES)
    comp = QQmlComponent(engine, QUrl.fromLocalFile(os.path.join(VIEWER, "qml/theme/Theme.qml")))
    theme = comp.create()
    if theme is None:
        raise SystemExit("Theme.qml failed: " + comp.errorString())
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)
    engine.load(QUrl.fromLocalFile(os.path.join(VIEWER, "qml/Main.qml")))
    roots = engine.rootObjects()
    if not roots:
        raise SystemExit("Main.qml failed to load")
    return engine, roots[0], keep + (theme,)


def drag_to(win, paths, pos):
    """Post a real enter/move/drop sequence carrying `paths` at window `pos`."""
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(p) for p in paths])
    for cls in (QDragEnterEvent, QDragMoveEvent):
        QGuiApplication.sendEvent(win, cls(pos, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
    ev = QDropEvent(pos, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    QGuiApplication.sendEvent(win, ev)
    spin(60)
    return ev


def key(win, k, mods=Qt.NoModifier):
    QGuiApplication.sendEvent(win, QKeyEvent(QKeyEvent.KeyPress, k, mods))
    QGuiApplication.sendEvent(win, QKeyEvent(QKeyEvent.KeyRelease, k, mods))
    spin(40)


def centre(win, p):
    """Window coordinates of the centre of pane `p`."""
    return QPoint(int(win.paneX(p) + win.paneW(p) / 2),
                  int(win.paneY(p) + win.paneH(p) / 2))


def paths_of(win):
    return [e["path"] for e in unwrap(win.property("images"))]


def pidx(win, p):
    """Pane `p`'s position in the image list. QML numbers arrive as floats."""
    return int(win.paneIdx(p))


def main():
    app = QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":   # a mapped window would be HIS screen
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())
    d = os.path.join(SCRATCH, "pics")
    os.makedirs(d)
    files = [png(os.path.join(d, "a%d.png" % i), (i * 40, 10, 10)) for i in range(4)]
    extra = png(os.path.join(d, "dropped.png"), (0, 200, 0))
    awkward = png(os.path.join(d, "weird #1?.png"), (0, 0, 200))
    text = os.path.join(d, "notes.txt")
    open(text, "w").write("x")

    entries = [{"name": os.path.basename(p), "path": p} for p in files]

    # ---- 1. the drop payload decoder ----
    fx = viewermain.Files()
    got = unwrap(fx.mediaEntries([QUrl.fromLocalFile(awkward), QUrl.fromLocalFile(text),
                                  QUrl("https://example.com/x.png")]))
    check("mediaEntries keeps a name containing # and ? intact (encodeURI would not)",
          [e["path"] for e in got] == [awkward], got)
    check("mediaEntries drops non-media and non-local URLs", len(got) == 1, got)
    dup = unwrap(fx.mediaEntries([QUrl.fromLocalFile(files[0]), QUrl.fromLocalFile(files[0])]))
    check("mediaEntries dedupes one drop", len(dup) == 1, dup)

    # ---- 2. one pane by default ----
    engine, win, keep = build(app, entries, 1)
    win.show()
    spin(250)
    check("a plain launch is a single pane", win.property("paneCount") == 1)
    check("...spanning the whole window",
          abs(win.paneW(0) - win.property("width")) < 1.5
          and abs(win.paneH(0) - win.property("height")) < 1.5,
          (win.paneW(0), win.paneH(0)))
    check("...positioned on the opened image", pidx(win, 0) == 1)

    # ---- 3. splitting: 2 side by side, 3 as a 2x2 with a spanning last pane ----
    win.addPane()
    spin(80)
    check("sp adds a pane", win.property("paneCount") == 2)
    check("the new pane takes the chrome", win.property("focusPane") == 1)
    check("the new pane shows the NEXT image, not the same one",
          pidx(win, 1) == 2 and pidx(win, 0) == 1, (pidx(win, 0), pidx(win, 1)))
    check("two panes are side by side",
          abs(win.paneY(0) - win.paneY(1)) < 0.5 and win.paneX(1) > win.paneX(0),
          (win.paneX(0), win.paneX(1)))
    check("...and together they fill the width bar the divider",
          abs((win.paneW(0) + win.paneW(1) + win.property("divW")) - win.property("width")) < 1.5)

    win.addPane()
    spin(80)
    check("three panes make a 2x2 grid",
          win.property("cols") == 2 and win.property("rows") == 2)
    check("...with the last pane spanning the short row's leftover column",
          abs(win.paneW(2) - win.property("width")) < 1.5, win.paneW(2))
    check("...and no pane left on top of another",
          win.paneY(2) > win.paneY(0) + 1, (win.paneY(0), win.paneY(2)))

    # ---- 4. the flip keys move the FOCUSED pane only ----
    win.setProperty("focusPane", 0)
    spin(40)
    before = [pidx(win, i) for i in range(3)]
    key(win, Qt.Key_Right)
    after = [pidx(win, i) for i in range(3)]
    check("Right advances the focused pane", after[0] == (before[0] + 1) % len(files), after)
    check("...and leaves the other panes where they were",
          after[1:] == before[1:], (before, after))
    key(win, Qt.Key_Left)
    check("Left goes back", pidx(win, 0) == before[0])

    # ---- 5. Tab / Ctrl+N move the chrome; Ctrl+W closes a pane ----
    key(win, Qt.Key_Tab)
    check("Tab moves the chrome to the next pane", win.property("focusPane") == 1)
    key(win, Qt.Key_3, Qt.ControlModifier)
    check("Ctrl+3 points the chrome at pane 3", win.property("focusPane") == 2)
    key(win, Qt.Key_W, Qt.ControlModifier)
    check("Ctrl+W closes the focused pane", win.property("paneCount") == 2)
    check("...and the chrome lands on a pane that still exists",
          win.property("focusPane") == 1)

    # ---- 6. a drop lands in the pane it was dropped ON ----
    win.setProperty("focusPane", 0)
    spin(40)
    ev = drag_to(win, [extra], centre(win, 1))
    check("a local image drop is accepted", ev.isAccepted())
    check("...into the pane under the cursor, not the focused one",
          paths_of(win)[pidx(win, 1)] == extra, pidx(win, 1))
    check("...leaving the other pane alone", paths_of(win)[pidx(win, 0)] != extra)
    check("...and the dropped file joins the flip-through list once",
          paths_of(win).count(extra) == 1, paths_of(win))
    check("...and the drop takes the chrome", win.property("focusPane") == 1)

    n_before = len(paths_of(win))
    drag_to(win, [extra], centre(win, 0))
    check("dropping the SAME file again reuses its slot",
          len(paths_of(win)) == n_before, paths_of(win))

    # ---- 7. a multi-file drop opens the extras in their own panes ----
    before_panes = win.property("paneCount")
    drag_to(win, [files[0], files[1], awkward], centre(win, 0))
    spin(80)
    check("dropping three images opens two more panes",
          win.property("paneCount") == before_panes + 2, win.property("paneCount"))
    check("...the first landing in the pane that was dropped on",
          paths_of(win)[pidx(win, 0)] == files[0], pidx(win, 0))
    shown = [paths_of(win)[pidx(win, i)] for i in range(win.property("paneCount"))]
    check("...and the rest in the new panes",
          files[1] in shown and awkward in shown, shown)

    # ---- 8. a drop of nothing viewer can decode is declined ----
    ev = drag_to(win, [text], centre(win, 0))
    check("a non-media drop is declined, not swallowed", not ev.isAccepted())

    # ---- 9. the pane cap holds ----
    for _ in range(viewermain.MAX_PANES + 3):
        win.addPane()
    spin(120)
    check("the pane count is capped at MAX_PANES",
          win.property("paneCount") == viewermain.MAX_PANES, win.property("paneCount"))
    check("...and the grid stays square-ish",
          win.property("cols") == 3 and win.property("rows") == 3)
    tot = sum(win.paneW(i) for i in range(3))
    check("...with a full row still spanning the window",
          abs(tot + 2 * win.property("divW") - win.property("width")) < 1.5, tot)

    while win.property("paneCount") > 2:
        win.closePane(win.property("paneCount") - 1)
    spin(80)

    # ---- 10. the divider drag resizes the pair, and persists ----
    w0 = win.paneW(0)
    win.dragCol(0, win.property("width") * 0.25)
    spin(40)
    check("dragging the divider narrows the left pane",
          win.paneW(0) < w0 - 10, (w0, win.paneW(0)))
    check("...and widens the right one by the same space",
          abs((win.paneW(0) + win.paneW(1) + win.property("divW")) - win.property("width")) < 1.5)
    win.dragCol(0, -10000)
    check("...and cannot be dragged shut", win.paneW(0) >= win.property("minPane") - 0.5,
          win.paneW(0))
    win.dragCol(0, win.property("width") * 0.25)
    prefs = keep[3]
    prefs.saveWeights(win.property("shapeKey"), unwrap(win.property("colW")),
                      unwrap(win.property("rowW")))
    saved = unwrap(prefs.loadWeights("2x1"))
    check("the weights are persisted for this grid shape",
          "col" in saved and abs(saved["col"][0] - 0.25) < 0.05, saved)
    check("a shape with nothing saved reads empty (even split)",
          unwrap(prefs.loadWeights("3x3")) == {}, unwrap(prefs.loadWeights("3x3")))

    # ---- 11. a fresh window picks the saved divider back up ----
    engine2, win2, keep2 = build(app, entries)
    win2.show()
    spin(250)
    win2.addPane()
    spin(120)
    check("a new window restores the saved divider for that shape",
          abs(win2.paneW(0) / win2.property("width") - 0.25) < 0.05,
          win2.paneW(0) / win2.property("width"))

    # ---- 12. --split opens one pane per path ----
    engine3, win3, keep3 = build(app, entries, 0, 3)
    win3.show()
    spin(250)
    check("--split opens one pane per path", win3.property("paneCount") == 3)
    check("...each on its own image",
          sorted(pidx(win3, i) for i in range(3)) == [0, 1, 2],
          [pidx(win3, i) for i in range(3)])

    print()
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        sys.exit(1)
    print("all split-view checks passed")


# Guarded, so this file can be IMPORTED for its build()/spin() helpers the way
# filer's thumb-test reuses dragsource-test's. Without the guard the import
# runs the whole suite and then dies constructing a second QGuiApplication.
if __name__ == "__main__":
    QTimer.singleShot(0, lambda: None)
    main()
