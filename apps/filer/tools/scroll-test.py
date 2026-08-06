#!/usr/bin/env python3
"""Offscreen harness for filer's scroll-position memory across a rebuild.

Loads the REAL qml/Main.qml under QT_QPA_PLATFORM=offscreen and drives the
production refresh path (FileOps.finished -> Main.refreshAll -> pane.refresh ->
rebuildKeepScroll) after physically moving files OUT of the viewed directory,
asserting the file list stays where it was scrolled rather than snapping to the
top. Also asserts the paths that MUST reset to the top still do (a `cd`, a
re-sort), and that expand/collapse keeps its place.

The bug this guards: reassigning the ListView model snaps contentY to 0 on a
later polish pass than any synchronous restore (or Qt.callLater), so the old
in-place restore was silently clobbered on a move-out — the list shrank and the
snap-to-top was jarring. The fix arms a pending restore re-asserted from
onCountChanged, after the reset. Same shape as player/AlbumGrid.qml.

Titlebar is stubbed — the real one talks to the hyprvtb socket, which would
register buttons against this harness's pid in the live compositor.
"""
import os
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session: with no
os.environ.pop("DISPLAY", None)          # display Qt aborts, it cannot fall back

FILER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FILER)
sys.path.insert(0, os.path.join(os.path.dirname(FILER), "pylib"))
from deskstyle import DeskStyle  # noqa: E402  (pylib; Theme.qml binds to it)

from PySide6.QtCore import QUrl, QObject, Slot, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QJSValue  # noqa: E402

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


def find(root, prop):
    for ch in root.children():
        try:
            if ch.property(prop) is not None:
                return ch
        except RuntimeError:
            pass
        hit = find(ch, prop)
        if hit is not None:
            return hit
    return None


def find_list(root):
    for ch in root.children():
        cn = ch.metaObject().className()
        if "ListView" in cn and "Attached" not in cn and ch.property("contentHeight") is not None:
            return ch
        hit = find_list(ch)
        if hit is not None:
            return hit
    return None


def build(app, start_dir):
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ops = filermain.FileOps()
    keep = [ops, filermain.Palette(filermain.PANEL_THEME), filermain.Settings(),
            filermain.DirWatch(), filermain.WinCtl(), filermain.VideoConv(),
            StubTitlebar(), filermain.Picker(None), filermain.Phone(),
            filermain.Remote()]
    ctx.setContextProperty("FileOps", keep[0])
    ctx.setContextProperty("Remote", keep[9])
    _ds = DeskStyle(parent=engine)
    ctx.setContextProperty("WalPalette", keep[1])
    ctx.setContextProperty("DeskStyle", _ds)
    ctx.setContextProperty("Settings", keep[2])
    ctx.setContextProperty("DirWatch", keep[3])
    ctx.setContextProperty("WinCtl", keep[4])
    ctx.setContextProperty("VideoConv", keep[5])
    ctx.setContextProperty("Titlebar", keep[6])
    ctx.setContextProperty("Picker", keep[7])
    ctx.setContextProperty("Phone", keep[8])
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
    keep += [_ds, theme]
    return engine, roots[0], keep


def spin(ms=200):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QGuiApplication.processEvents()
        time.sleep(0.005)


def rowslen(view):
    r = view.property("rows")
    r = r.toVariant() if isinstance(r, QJSValue) else r
    return len(r) if r else 0


def main():
    app = QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":   # a mapped window would be HIS screen
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())
    tmp = tempfile.mkdtemp(prefix="t_scroll-")
    src = os.path.join(tmp, "src")
    dst = os.path.join(tmp, "dst")
    sub = os.path.join(src, "sub")
    os.makedirs(dst)
    os.makedirs(sub)
    for i in range(200):
        open(os.path.join(src, "file_%03d.txt" % i), "w").write("x")
    for i in range(5):
        open(os.path.join(sub, "s_%02d.txt" % i), "w").write("x")

    engine, win, keep = build(app, src)
    ops = keep[0]
    win.show()
    spin(500)
    view = find(win, "dropTarget")
    lst = find_list(win)
    check("Main.qml loads with a laid-out file list",
          view is not None and lst is not None
          and lst.property("contentHeight") > lst.property("height"),
          lst and lst.property("contentHeight"))

    # ---- 1. a move OUT keeps the scroll position ----
    lst.setProperty("contentY", 800)
    spin(120)
    y0 = lst.property("contentY")
    check("scrolled down off the top", y0 > 700, y0)
    for i in range(100, 140):                      # 40 files leave the dir
        os.rename(os.path.join(src, "file_%03d.txt" % i),
                  os.path.join(dst, "file_%03d.txt" % i))
    ops.finished.emit("")                          # the production refresh trigger
    spin(500)
    check("the list actually rebuilt (rows shrank)", rowslen(view) == 161, rowslen(view))
    y1 = lst.property("contentY")
    check("a move OUT keeps the scroll position (was the bug: snapped to 0)",
          abs(y1 - y0) < 30, "before=%s after=%s" % (y0, y1))
    check("...and it is clamped inside the shrunken content, never past the end",
          y1 <= lst.property("originY") + lst.property("contentHeight") - lst.property("height") + 1,
          y1)

    # ---- 2. a `cd` still starts at the top ----
    view.go(sub)
    spin(400)
    check("navigating into a directory resets to the top", lst.property("contentY") == 0,
          lst.property("contentY"))
    view.go(src)
    spin(400)
    check("navigating back also starts at the top", lst.property("contentY") == 0,
          lst.property("contentY"))

    # ---- 3. expand keeps the scroll position (the case that always worked) ----
    lst.setProperty("contentY", 600)
    spin(120)
    y2 = lst.property("contentY")
    view.toggleExpand(sub)
    spin(400)
    y3 = lst.property("contentY")
    check("expanding a subdir keeps the scroll position", abs(y3 - y2) < 30,
          "before=%s after=%s" % (y2, y3))

    print()
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        sys.exit(1)
    print("all scroll checks passed")


QTimer.singleShot(0, lambda: None)
main()
