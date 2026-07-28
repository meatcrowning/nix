#!/usr/bin/env python3
"""Offscreen harness for filer's SPLIT VIEW.

Loads the REAL qml/Main.qml under QT_QPA_PLATFORM=offscreen and drives the
window through its own API — the titlebar button ids, the pane geometry, and
real QDrag*/QDrop events posted at window coordinates that land in one pane or
the other. So the split, the pane the chrome is pointed at, and a drag from one
pane to the other are all exercised with no window on anyone's screen.

The interesting assertions are the ones reasoning gets wrong:

  * the chrome (title, buttons, footer) follows the FOCUSED pane, not the left
    one — a sort or a paste must not land in the half you are not looking at;
  * the panes are independent — navigating one leaves the other where it was;
  * DirWatch holds the UNION of the two panes' directories, which is what the
    keyed setDirs() is for (unkeyed, the right pane's rebuild silently
    unwatched the left pane's dirs);
  * a drop in the right pane targets the RIGHT pane's directory, and claims the
    chrome — dragging between the panes being the point of the split;
  * a picker is never split.

Titlebar is stubbed (the real one talks to the hyprvtb socket) but it RECORDS,
so what the chrome was told is assertable.

`Settings` is redirected into the temp dir before anything is built. It has to
be: unlike the other harnesses this one navigates and sorts, which PERSISTS —
and against the real ~/.local/state/filer/state.json that means the next filer
the user opens reopens in a since-deleted /tmp directory, sorted by whatever
the test asserted on.
"""
import os
import pathlib
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"

FILER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FILER)
sys.path.insert(0, os.path.join(os.path.dirname(FILER), "pylib"))

from PySide6.QtCore import QUrl, QObject, Slot, QMimeData, QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtGui import (QGuiApplication, QDragEnterEvent, QDragMoveEvent,  # noqa: E402
                           QDropEvent)
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QJSValue  # noqa: E402
from PySide6.QtQuick import QQuickItem  # noqa: E402,F401  (registers Item* for property())

import main as filermain  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


class RecTitlebar(QObject):
    """Stub bridge that remembers what the window pushed at it."""

    def __init__(self):
        super().__init__()
        self.buttons = []
        self.footer = ""

    @Slot("QVariantList")
    def setButtons(self, b):
        self.buttons = [dict(x) for x in b if not isinstance(x, str)]

    @Slot(str)
    def setFooter(self, t):
        self.footer = t

    @Slot(bool)
    def setTitleEdit(self, on):
        pass

    def button(self, bid):
        for b in self.buttons:
            if b.get("id") == bid:
                return b
        return None


def unwrap(v):
    return v.toVariant() if isinstance(v, QJSValue) else v


def build(app, start_dir, picker=None, state=None):
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    tb = RecTitlebar()
    watch = filermain.DirWatch()
    keep = (filermain.FileOps(), filermain.Palette(filermain.PANEL_THEME),
            filermain.Settings(), watch, filermain.WinCtl(), filermain.VideoConv(),
            tb, filermain.Picker(picker))
    ctx.setContextProperty("FileOps", keep[0])
    ctx.setContextProperty("WalPalette", keep[1])
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
    state = state or {}
    ctx.setContextProperty("startSplit", bool(state.get("split", False)))
    ctx.setContextProperty("startSplitDir", state.get("splitDir", ""))
    ctx.setContextProperty("startSplitRatio", float(state.get("splitRatio", 0.5)))
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
    return engine, roots[0], tb, watch, keep + (theme,)


def spin(ms=150):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QGuiApplication.processEvents()
        time.sleep(0.005)


def click(tb_conn, bid):
    """What the compositor does when a titlebar button is pressed."""
    tb_conn.clicked.emit(bid)


def drag_to(win, paths, pos):
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(p) for p in paths])
    for cls in (QDragEnterEvent, QDragMoveEvent):
        QGuiApplication.sendEvent(win, cls(pos, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
    ev = QDropEvent(pos, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    QGuiApplication.sendEvent(win, ev)
    return ev


def by_name(root, name):
    if root.objectName() == name:
        return root
    for ch in root.children():
        hit = by_name(ch, name)
        if hit is not None:
            return hit
    return None


def main():
    app = QGuiApplication(sys.argv)
    tmp = tempfile.mkdtemp(prefix="t_split-")
    left = os.path.join(tmp, "left")
    right = os.path.join(tmp, "right")
    # BEFORE anything reads or writes it: this test navigates and sorts, and
    # both persist (see the module docstring).
    filermain.STATE_PATH = pathlib.Path(tmp) / "state.json"
    os.makedirs(os.path.join(left, "sub"))
    os.makedirs(right)
    for n in ("a.txt", "b.txt"):
        open(os.path.join(left, n), "w").write("x")

    engine, win, tb, watch, keep = build(app, left)
    win.show()
    spin(300)

    focused = win.property("pane")
    check("an unsplit window has one pane, and it is the focused one",
          focused is not None and focused.property("path") == left,
          focused.property("path") if focused else None)
    check("...spanning the whole window",
          win.property("paneLeftW") == win.property("width"),
          (win.property("paneLeftW"), win.property("width")))
    check("the titlebar offers the split button", tb.button("split") is not None,
          [b.get("id") for b in tb.buttons])
    check("...unlit while the split is off", tb.button("split").get("state") == 0)

    # ---- 1. opening the split ----
    win.toggleSplit()
    spin(250)
    check("sp opens the split", win.property("splitOn") is True)
    check("...and hands the chrome to the new pane", win.property("focusPane") == 1)
    check("...which opens beside the left one (no saved split dir)",
          win.property("pane").property("path") == left,
          win.property("pane").property("path"))
    check("the two panes divide the window",
          win.property("paneLeftW") + win.property("splitterW") + win.property("paneRightW")
          == win.property("width"),
          (win.property("paneLeftW"), win.property("paneRightW"), win.property("width")))
    check("...and neither is a sliver",
          win.property("paneLeftW") >= win.property("minPaneW")
          and win.property("paneRightW") >= win.property("minPaneW"))
    check("the split button is lit while it is on", tb.button("split").get("state") == 1)

    paneR = win.property("rightPane")
    paneLeft = win.property("leftPane")
    check("the split pane is the focused one", paneR is win.property("pane"))
    check("the left pane is still there and still primary",
          paneLeft is not None and paneLeft.property("primary") is True)

    # ---- 2. the panes are independent ----
    paneR.go(right)
    spin()
    check("navigating the right pane moves only the right pane",
          paneR.property("path") == right and paneLeft.property("path") == left,
          (paneR.property("path"), paneLeft.property("path")))
    check("the window title follows the FOCUSED pane", win.property("title") == right,
          win.property("title"))
    check("the titlebar footer follows it too",
          tb.footer == paneR.property("dirSizeStr"), (tb.footer, paneR.property("dirSizeStr")))

    # ---- 3. DirWatch keeps BOTH panes' directories ----
    watched = set(watch._watcher.directories())
    check("DirWatch holds the union of the two panes, not the last one to rebuild",
          left in watched and right in watched, sorted(watched))

    # ---- 4. the chrome acts on the focused pane ----
    paneR.selectSingle(os.path.join(right, "x"), False)
    spin(60)
    check("a selection in the focused pane enables the file-op buttons",
          tb.button("copy").get("state") == 0 and tb.button("rename").get("state") == 0)
    win.setProperty("focusPane", 0)
    spin(60)
    check("moving the chrome to the empty pane disables them again",
          tb.button("copy").get("state") == 2, tb.button("copy"))
    check("...and the title follows", win.property("title") == left, win.property("title"))
    check("...and `up` is the left pane's parent, not the right's",
          tb.button("up").get("state") == 0)

    # sort is per-pane: the titlebar shows the focused pane's
    paneLeft.setSort("size")
    spin(60)
    check("sort state read from the focused pane",
          tb.button("sort-size").get("state") == 1 and tb.button("sort-name").get("state") == 0)
    win.setProperty("focusPane", 1)
    spin(60)
    check("...and the other pane keeps its own",
          tb.button("sort-name").get("state") == 1 and tb.button("sort-size").get("state") == 0)

    # ---- 5. a drop lands in the pane it was dropped on ----
    win.setProperty("focusPane", 0)
    spin(60)
    w = int(win.property("width"))
    h = int(win.property("height"))
    rx = int(win.property("paneRightX"))
    ev = drag_to(win, [os.path.join(left, "a.txt")],
                 QPoint(rx + int(win.property("paneRightW")) // 2, h - 30))
    spin()
    menu = by_name(paneR, "ctxMenu")
    labels = [i.get("label") for i in (unwrap(menu.property("items")) or [])]
    check("a drop in the RIGHT pane is accepted there", ev.isAccepted())
    check("...and asks about the right pane's directory",
          labels[:1] == ["to " + os.path.basename(right) + "/"], labels)
    check("...and points the chrome at the pane that received it",
          win.property("focusPane") == 1)
    menu.close()
    spin(40)

    # and the hit-test is pane-relative: the same y in the LEFT pane targets the
    # left pane's directory, not the right's.
    check("the left pane still hit-tests against its own directory",
          paneLeft.dropDirAt(50, h - 30) == left, paneLeft.dropDirAt(50, h - 30))

    # ---- 6. the divider ----
    win.setSplitRatio(0.9)
    spin(60)
    check("the divider cannot be dragged past the minimum pane width",
          win.property("paneRightW") >= win.property("minPaneW"),
          (win.property("splitRatio"), win.property("paneRightW")))
    win.setSplitRatio(0.0)
    spin(60)
    check("...at either end",
          win.property("paneLeftW") >= win.property("minPaneW"), win.property("paneLeftW"))
    win.setSplitRatio(0.5)

    # ---- 7. folding it back ----
    win.toggleSplit()
    spin(200)
    check("sp folds the split", win.property("splitOn") is False)
    check("...hands the chrome back to the left pane", win.property("focusPane") == 0)
    check("...which is once again the whole window",
          win.property("paneLeftW") == win.property("width"))
    check("...and the retired pane gave its watch slot back",
          right not in set(watch._watcher.directories()),
          sorted(watch._watcher.directories()))
    win.toggleSplit()
    spin(200)
    check("reopening it comes back to the directory the right pane was showing",
          win.property("pane").property("path") == right,
          win.property("pane").property("path"))
    win.toggleSplit()
    spin(150)

    # ---- 8. a restored session ----
    engine2, win2, tb2, watch2, keep2 = build(app, left,
                                              state={"split": True, "splitDir": right,
                                                     "splitRatio": 0.3})
    win2.show()
    spin(300)
    check("a saved split reopens split", win2.property("splitOn") is True)
    check("...with the right pane where it was",
          win2.property("rightPane").property("path") == right,
          win2.property("rightPane").property("path"))
    # a restored split points the chrome at the LEFT pane — unlike opening one
    # by hand, where the pane you just asked for is the one you meant to use.
    check("...and the chrome on the left one",
          win2.property("focusPane") == 0
          and win2.property("pane") is win2.property("leftPane"))
    check("...and the divider where it was",
          abs(win2.property("splitRatio") - 0.3) < 1e-6, win2.property("splitRatio"))

    # ---- 9. a picker is never split ----
    spec = {"result": os.path.join(tmp, "res.json"), "mode": "open"}
    engine3, win3, tb3, watch3, keep3 = build(app, left, picker=spec,
                                              state={"split": True, "splitDir": right})
    win3.show()
    spin(300)
    check("a picker ignores a saved split", win3.property("splitOn") is False)
    win3.toggleSplit()
    spin(100)
    check("...and refuses to open one", win3.property("splitOn") is False)
    check("...with the split button disabled", tb3.button("split").get("state") == 2,
          tb3.button("split"))

    print()
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        sys.exit(1)
    print("all split checks passed")


QTimer.singleShot(0, lambda: None)
main()
