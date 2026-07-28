#!/usr/bin/env python3
"""Offscreen harness for the mouse back/forward buttons (DESIGN.md §11).

Loads the REAL qml/Main.qml under QT_QPA_PLATFORM=offscreen and posts real
QMouseEvent press/release pairs carrying Qt.BackButton / Qt.ForwardButton at the
window — the same events the compositor delivers for evdev BTN_SIDE (275) and
BTN_EXTRA (276). So `qmlcommon/NavButtons.qml`, `qmlcommon/NavHistory.qml` and
filer's per-pane directory history are all exercised end to end, with no window
on anyone's screen.

It also covers the two properties the shared stack is supposed to have and the
hand-rolled one it replaced did not: the forward stack is dropped on a new
navigation, and `canBack`/`canForward` actually NOTIFY (an in-place push on a
QML `var` array emits no change signal).

Titlebar is stubbed — the real one talks to the hyprvtb socket, which would
register buttons against this harness's pid in the live compositor.
"""
import os
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"

FILER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FILER)
sys.path.insert(0, os.path.join(os.path.dirname(FILER), "pylib"))
from deskstyle import DeskStyle  # noqa: E402  (pylib; Theme.qml binds to it)

from PySide6.QtCore import QUrl, QObject, Slot, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QMouseEvent  # noqa: E402
from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent  # noqa: E402

import main as filermain  # noqa: E402

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
    @Slot(bool)
    def setTitleEdit(self, on): pass


def build(app, start_dir):
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    keep = (filermain.FileOps(), filermain.Palette(filermain.PANEL_THEME),
            filermain.Settings(), filermain.DirWatch(), filermain.WinCtl(),
            filermain.VideoConv(), StubTitlebar(), filermain.Picker(None))
    ctx.setContextProperty("FileOps", keep[0])
    _deskstyle = DeskStyle(parent=engine)
    ctx.setContextProperty("WalPalette", keep[1])
    ctx.setContextProperty("DeskStyle", _deskstyle)
    ctx.setContextProperty("Settings", keep[2])
    ctx.setContextProperty("DirWatch", keep[3])
    ctx.setContextProperty("WinCtl", keep[4])
    ctx.setContextProperty("VideoConv", keep[5])
    ctx.setContextProperty("Titlebar", keep[6])
    ctx.setContextProperty("Picker", keep[7])
    ctx.setContextProperty("startDir", start_dir)
    ctx.setContextProperty("startSortField", "name")
    ctx.setContextProperty("startSortAsc", True)
    ctx.setContextProperty("startShowHidden", True)
    ctx.setContextProperty("startGridPanelH", 200)
    ctx.setContextProperty("startSplit", False)
    ctx.setContextProperty("startSplitDir", "")
    ctx.setContextProperty("startSplitRatio", 0.5)
    ctx.setContextProperty("startSplitVertical", True)
    comp = QQmlComponent(engine, QUrl.fromLocalFile(os.path.join(FILER, "qml/theme/Theme.qml")))
    theme = comp.create()
    if theme is None:
        raise SystemExit("Theme.qml failed: " + comp.errorString())
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)
    engine.load(QUrl.fromLocalFile(os.path.join(FILER, "qml/Main.qml")))
    roots = engine.rootObjects()
    if not roots:
        raise SystemExit("Main.qml failed to load")
    return engine, roots[0], keep + (theme,)


def spin(ms=120):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QGuiApplication.processEvents()
        time.sleep(0.005)


def side_click(win, button):
    """A real press/release pair for one of the mouse's side buttons."""
    pos = QPointF(win.width() / 2.0, win.height() / 2.0)
    glob = QPointF(win.x() + pos.x(), win.y() + pos.y())
    for kind, held in ((QEvent.Type.MouseButtonPress, button),
                       (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
        ev = QMouseEvent(kind, pos, pos, glob, button, held, Qt.KeyboardModifier.NoModifier)
        QGuiApplication.sendEvent(win, ev)
    spin(60)


def main():
    app = QGuiApplication(sys.argv)
    with tempfile.TemporaryDirectory() as tmp:
        a = os.path.join(tmp, "a"); os.makedirs(os.path.join(a, "deep"))
        b = os.path.join(tmp, "b"); os.makedirs(b)
        engine, win, _keep = build(app, tmp)
        spin(300)

        pane = win.property("pane")
        check("pane reachable", pane is not None)
        if pane is None:
            return 1
        check("starts at tmp", pane.property("path") == tmp, pane.property("path"))

        # Nothing recorded yet: back must be a no-op, not a crash or a wrap.
        side_click(win, Qt.MouseButton.BackButton)
        check("back with empty history is a no-op", pane.property("path") == tmp,
              pane.property("path"))

        pane.go(a)
        spin(80)
        check("go(a) moved", pane.property("path") == a, pane.property("path"))
        pane.go(os.path.join(a, "deep"))
        spin(80)

        # --- the actual rule: the side buttons walk that history -------------
        side_click(win, Qt.MouseButton.BackButton)
        check("BackButton -> a", pane.property("path") == a, pane.property("path"))
        side_click(win, Qt.MouseButton.BackButton)
        check("BackButton -> tmp", pane.property("path") == tmp, pane.property("path"))
        side_click(win, Qt.MouseButton.BackButton)
        check("BackButton stops at the bottom", pane.property("path") == tmp,
              pane.property("path"))
        side_click(win, Qt.MouseButton.ForwardButton)
        check("ForwardButton -> a", pane.property("path") == a, pane.property("path"))
        side_click(win, Qt.MouseButton.ForwardButton)
        check("ForwardButton -> deep", pane.property("path") == os.path.join(a, "deep"),
              pane.property("path"))
        side_click(win, Qt.MouseButton.ForwardButton)
        check("ForwardButton stops at the top",
              pane.property("path") == os.path.join(a, "deep"), pane.property("path"))

        # --- browser semantics: a new navigation drops the forward stack ------
        side_click(win, Qt.MouseButton.BackButton)          # -> a
        pane.go(b)
        spin(80)
        side_click(win, Qt.MouseButton.ForwardButton)
        check("a new navigation clears the forward stack", pane.property("path") == b,
              pane.property("path"))
        side_click(win, Qt.MouseButton.BackButton)
        check("...and back still works after it", pane.property("path") == a,
              pane.property("path"))

        # --- re-opening the current directory is not a move ------------------
        cur = pane.property("path")
        pane.go(cur)
        spin(60)
        side_click(win, Qt.MouseButton.BackButton)
        check("go(current) recorded nothing", pane.property("path") != cur,
              pane.property("path"))

        # --- the buttons must NOT eat ordinary presses ------------------------
        # A left press at the same point has to reach the pane underneath, or
        # the overlay has broken selection for the whole window.
        before = pane.property("path")
        pos = QPointF(win.width() / 2.0, win.height() / 2.0)
        glob = QPointF(win.x() + pos.x(), win.y() + pos.y())
        ev = QMouseEvent(QEvent.Type.MouseButtonPress, pos, pos, glob,
                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier)
        accepted_by_nav = QGuiApplication.sendEvent(win, ev) and False
        ev2 = QMouseEvent(QEvent.Type.MouseButtonRelease, pos, pos, glob,
                          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                          Qt.KeyboardModifier.NoModifier)
        QGuiApplication.sendEvent(win, ev2)
        spin(60)
        check("a left click does not navigate", pane.property("path") == before,
              (before, pane.property("path"), accepted_by_nav))

        # --- per-pane, not global -------------------------------------------
        win.setSplit(True)
        spin(300)
        right = win.property("rightPane")
        check("split opened a second pane", right is not None)
        if right is not None:
            win.setProperty("focusPane", 1)
            spin(60)
            right.go(a)
            spin(80)
            left_before = win.property("leftPane").property("path")
            side_click(win, Qt.MouseButton.BackButton)
            check("back moved the FOCUSED pane only",
                  right.property("path") != a
                  and win.property("leftPane").property("path") == left_before,
                  (right.property("path"), left_before))

    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("all nav-test checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
