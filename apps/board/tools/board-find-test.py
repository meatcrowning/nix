#!/usr/bin/env python3
"""goetia's Ctrl+F find harness — offscreen, no window on anyone's screen.

The board is ONE scroll region (docs/DESIGN.md §9.2), but its two ever-growing
lists — LANDED and the triangle's minister cards — had no way to find anything
by eye. §11.2 makes Ctrl+F the key for that; this asserts the real `qml/Main.qml`
under QT_QPA_PLATFORM=offscreen:

  * Ctrl+F opens the bar (a window-scoped `Shortcut`, resolved by the app's
    shortcut map — so `QTest.keyClick`, not `sendEvent`, §11.2), and a second
    Ctrl+F leaves it open.
  * the query FILTERS: `findCount` reports the rows that match across both lists,
    and `findHit` hides a non-matching LANDED row.
  * Escape closes the bar and restores the full list (`findText` cleared).

Run it with goetia's own Qt env, not the bare system python:

    W=$(readlink -f "$(which goetia)")
    PY=$(grep -o '/nix/store/[^"]*/bin/python3' "$W" | head -1)
    ( QT_QPA_PLATFORM=offscreen "$PY" apps/board/tools/board-find-test.py )

`XDG_STATE_HOME` is redirected into a scratch dir: a harness must never rewrite
where the user's own goetia reopens. The Titlebar is stubbed, because the real
one registers buttons against this process's pid in the LIVE compositor.
"""
import os
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session: with no
os.environ.pop("DISPLAY", None)          # display Qt aborts, it cannot fall back

BOARD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS = os.path.dirname(BOARD)
sys.path.insert(0, BOARD)
sys.path.insert(0, os.path.join(APPS, "pylib"))

FAILS = []


def prop(obj, name):
    v = obj.property(name)
    return v.toVariant() if hasattr(v, "toVariant") else v


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


BOARD_MD = """# board

## NEEDS YOU

nothing.

## LANDED

Newest first. Append-only.

### 2026-08-09

| Commit | What | When |
|---|---|---|
| `aaa1111` | player: dim the cover art on pause | 1:00 am |
| `bbb2222` | surfer: page find over the focused pane | 1:01 am |
| `ccc3333` | player: gapless queue crossfade | 1:02 am |
"""


def spin(ms=150):
    from PySide6.QtGui import QGuiApplication
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QGuiApplication.processEvents()


def build(app, start):
    from PySide6.QtCore import QUrl, QObject, Slot
    from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
    import PySide6.QtQuick  # noqa: F401  (registers the QQuickItem converter)
    import main as bd

    class StubTitlebar(QObject):
        @Slot("QVariantList")
        def setButtons(self, b): pass
        @Slot(str)
        def setFooter(self, t): pass
        @Slot(bool)
        def setTitleText(self, v): pass

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    keep = (bd.Palette(bd.PANEL_THEME), bd.DeskStyle(), StubTitlebar(),
            bd.Board(start), bd.Agents(), bd.Usage(), bd.Spend(), bd.Settings())
    ctx.setContextProperty("WalPalette", keep[0])
    ctx.setContextProperty("DeskStyle", keep[1])
    ctx.setContextProperty("Titlebar", keep[2])
    ctx.setContextProperty("Board", keep[3])
    ctx.setContextProperty("Agents", keep[4])
    ctx.setContextProperty("Usage", keep[5])
    ctx.setContextProperty("Spend", keep[6])
    ctx.setContextProperty("Settings", keep[7])
    comp = QQmlComponent(engine, QUrl.fromLocalFile(os.path.join(BOARD, "qml/theme/Theme.qml")))
    theme = comp.create()
    if theme is None:
        raise SystemExit("Theme.qml failed: " + comp.errorString())
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)
    engine.load(QUrl.fromLocalFile(os.path.join(BOARD, "qml/Main.qml")))
    roots = engine.rootObjects()
    if not roots:
        raise SystemExit("Main.qml failed to load")
    return engine, roots[0], keep + (theme,)


def main():
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    tmp = tempfile.mkdtemp(prefix="board-find-test-")
    os.environ["XDG_STATE_HOME"] = os.path.join(tmp, "state")
    start = os.path.join(tmp, "board.test.md")
    open(start, "w", encoding="utf-8").write(BOARD_MD)

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    engine, win, _keep = build(app, start)
    spin()

    # ---- Ctrl+F opens the bar (window-scoped Shortcut; keyClick, §11.2) ----
    check("find starts closed", prop(win, "findOpen") is False)
    QTest.keyClick(win, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    spin()
    check("Ctrl+F opens the find bar", prop(win, "findOpen") is True)
    # a second Ctrl+F must not close it — it re-selects the query (§11.2)
    QTest.keyClick(win, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    spin()
    check("second Ctrl+F leaves it open", prop(win, "findOpen") is True)

    # ---- the query filters both lists ----
    win.setProperty("findText", "player")
    spin()
    check("findQ lowercased+trimmed", prop(win, "findQ") == "player")
    check("findCount counts matching rows", prop(win, "findCount") == 2,
          prop(win, "findCount"))

    # findHit is the per-row predicate every filtered delegate calls
    hit = win.findHit("player: dim the cover art on pause")
    miss = win.findHit("surfer: page find over the focused pane")
    check("findHit keeps a matching row", hit is True)
    check("findHit hides a non-matching row", miss is False)

    win.setProperty("findText", "surfer")
    spin()
    check("re-query re-counts", prop(win, "findCount") == 1, prop(win, "findCount"))

    win.setProperty("findText", "zzznotfound")
    spin()
    check("a query with no match counts zero", prop(win, "findCount") == 0)
    # with find OPEN and no match, every row is hidden
    check("no-match hides the row", win.findHit("player: dim the cover art on pause") is False)

    # ---- Escape closes and restores the full list ----
    win.closeFind()
    spin()
    check("close clears the query", prop(win, "findText") == "")
    check("close reopens every row", win.findHit("surfer: page find over the focused pane") is True)

    del engine
    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        sys.exit(1)
    print("all board-find checks passed")


if __name__ == "__main__":
    main()
