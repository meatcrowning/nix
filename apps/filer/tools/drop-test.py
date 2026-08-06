#!/usr/bin/env python3
"""Offscreen harness for filer's drag-and-drop: the DROP half.

Loads the REAL qml/Main.qml under QT_QPA_PLATFORM=offscreen and posts real
QDragEnter/QDragMove/QDrop events at the window, so the DropArea, the hit-test
that picks the target directory and the transfer itself are all exercised
without a window on anyone's screen. Also covers the payload half
(FileOps.uriList / urlsToPaths) and the guards that keep a drop from eating a
directory by dropping it into itself.

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

from PySide6.QtCore import QUrl, QObject, Slot, QMimeData, QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtGui import (QGuiApplication, QDragEnterEvent, QDragMoveEvent,  # noqa: E402
                           QDragLeaveEvent, QDropEvent)
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


def unwrap(v):
    return v.toVariant() if isinstance(v, QJSValue) else v


def find(root, prop):
    """The first descendant carrying `prop`. Some QML/Qt properties have no
    Python converter (QQmlDelegateModelGroup*); those items simply aren't it."""
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


def by_name(root, name):
    if root.objectName() == name:
        return root
    for ch in root.children():
        hit = by_name(ch, name)
        if hit is not None:
            return hit
    return None


def build(app, start_dir):
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ops = filermain.FileOps()
    keep = (ops, filermain.Palette(filermain.PANEL_THEME), filermain.Settings(),
            filermain.DirWatch(), filermain.WinCtl(), filermain.VideoConv(),
            StubTitlebar(), filermain.Picker(None), filermain.Phone(),
            filermain.Remote())
    ctx.setContextProperty("FileOps", keep[0])
    ctx.setContextProperty("Remote", keep[9])
    _deskstyle = DeskStyle(parent=engine)
    ctx.setContextProperty("WalPalette", keep[1])
    # Theme.qml binds font/fontSize to DeskStyle (pylib/deskstyle.py), so the
    # harness must install it too or the theme loads with an empty font.
    ctx.setContextProperty("DeskStyle", _deskstyle)
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
    return engine, roots[0], keep + (theme,)


def spin(ms=120):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QGuiApplication.processEvents()
        time.sleep(0.005)


def wait_for(pred, ms=4000):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QGuiApplication.processEvents()
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def drag_to(win, paths, pos):
    """Post a real enter/move/drop sequence carrying `paths` at window `pos`."""
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(p) for p in paths])
    for cls in (QDragEnterEvent, QDragMoveEvent):
        QGuiApplication.sendEvent(win, cls(pos, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
    ev = QDropEvent(pos, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    QGuiApplication.sendEvent(win, ev)
    return ev


def main():
    app = QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":   # a mapped window would be HIS screen
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())
    tmp = tempfile.mkdtemp(prefix="t_drop-")
    src = os.path.join(tmp, "src")
    dst = os.path.join(tmp, "dst")
    os.makedirs(os.path.join(dst, "sub"))
    os.makedirs(src)
    for n in ("a.txt", "b.txt", "weird #1?.txt"):
        open(os.path.join(src, n), "w").write("x")

    # ---- 1. the uri-list payload ----
    ops = filermain.FileOps()
    uris = ops.uriList([os.path.join(src, "a.txt"), os.path.join(src, "weird #1?.txt")])
    check("uriList is CRLF-terminated per line", uris.count("\r\n") == 2, repr(uris))
    check("uriList percent-encodes # and ? (encodeURI did not)",
          "%23" in uris and "%3F" in uris, uris)
    back = ops.urlsToPaths([u for u in uris.split("\r\n") if u])
    check("urlsToPaths round-trips the awkward name",
          back == [os.path.join(src, "a.txt"), os.path.join(src, "weird #1?.txt")], back)
    check("urlsToPaths drops non-file URLs", ops.urlsToPaths(["https://example.com/x"]) == [])

    # ---- 2. the window, rooted at dst ----
    engine, win, keep = build(app, dst)
    view = find(win, "dropTarget")
    check("Main.qml loads with the drop layer", view is not None)
    win.show()
    spin(300)

    # ---- 3. the guards ----
    cands = unwrap(view.dropCandidates([os.path.join(dst, "sub")], dst))
    check("a source already in the target dir is dropped", cands == [], cands)
    cands = unwrap(view.dropCandidates([dst], dst))
    check("a directory dropped on itself is dropped", cands == [], cands)
    cands = unwrap(view.dropCandidates([dst], os.path.join(dst, "sub")))
    check("a directory dropped into its own subtree is dropped", cands == [], cands)
    cands = unwrap(view.dropCandidates([os.path.join(src, "a.txt")], dst))
    check("an outside source survives", cands == [os.path.join(src, "a.txt")], cands)

    # ---- 3b. the hit-test picks the directory under the cursor ----
    # `dst` holds nothing but the `sub` dir, so it is list row 0; rows are one
    # font line box tall inside the list's 2px margin.
    row0 = 2 + 7
    check("a drop over a directory row targets THAT directory",
          view.dropDirAt(50, row0) == os.path.join(dst, "sub"), view.dropDirAt(50, row0))
    check("a drop over empty space targets the current dir",
          view.dropDirAt(50, int(win.property("height")) - 30) == dst)
    ev = drag_to(win, [os.path.join(src, "a.txt")], QPoint(50, row0))
    spin()
    menu0 = by_name(view, "ctxMenu")
    labels0 = [i.get("label") for i in (unwrap(menu0.property("items")) or [])]
    check("...and the menu names that directory, not the current one",
          ev.isAccepted() and labels0[:1] == ["to sub/"], labels0)
    menu0.close()
    spin(40)

    # ---- 4. dragPaths: one file, or the whole multi-selection ----
    view.setProperty("selection", [os.path.join(dst, "sub")])
    check("dragPaths of a single selection is just that path",
          unwrap(view.dragPaths(os.path.join(src, "a.txt"))) == [os.path.join(src, "a.txt")])
    multi = [os.path.join(dst, "sub"), os.path.join(dst, "x")]
    view.setProperty("selection", multi)
    check("dragPaths inside a multi-selection carries the whole set",
          unwrap(view.dragPaths(multi[0])) == multi, unwrap(view.dragPaths(multi[0])))
    check("dragPaths outside it carries only the dragged path",
          unwrap(view.dragPaths("/tmp/other")) == ["/tmp/other"])
    view.setProperty("selection", [])

    # ---- 5. a real drop over empty space targets the current dir ----
    menu = by_name(view, "ctxMenu")
    check("the drop menu component is present", menu is not None)
    ev = drag_to(win, [os.path.join(src, "a.txt")], QPoint(int(win.property("width")) - 30,
                                                          int(win.property("height")) - 30))
    spin()
    check("a local-file drop is accepted", ev.isAccepted())
    check("the drop asked what it meant (move/copy/link menu)", menu.property("visible") is True)
    labels = [i.get("label") for i in (unwrap(menu.property("items")) or [])]
    check("the menu offers move/copy/link and names the target",
          labels[:1] == ["to " + os.path.basename(dst) + "/"]
          and any(l and l.startswith("move") for l in labels)
          and any(l and l.startswith("copy") for l in labels)
          and any(l and l.startswith("link") for l in labels), labels)

    # ---- 6. and the transfer itself runs ----
    view.transferInto([os.path.join(src, "a.txt")], dst, "copy", False)
    check("copy lands the file in the target dir",
          wait_for(lambda: os.path.exists(os.path.join(dst, "a.txt"))))
    check("copy leaves the source alone", os.path.exists(os.path.join(src, "a.txt")))
    view.transferInto([os.path.join(src, "b.txt")], dst, "cut", False)
    check("move lands the file in the target dir",
          wait_for(lambda: os.path.exists(os.path.join(dst, "b.txt"))))
    check("move removes the source", not os.path.exists(os.path.join(src, "b.txt")))
    view.transferInto([os.path.join(src, "weird #1?.txt")], dst, "link", False)
    check("link makes a symlink, not a copy",
          wait_for(lambda: os.path.islink(os.path.join(dst, "weird #1?.txt"))))

    # ---- 7. a conflicting name raises the overwrite confirm, never clobbers ----
    open(os.path.join(src, "a.txt"), "w").write("NEW")
    raised = view.transferInto([os.path.join(src, "a.txt")], dst, "copy", False)
    spin()
    check("a name already taken raises the overwrite confirm", raised is True)
    check("...and nothing was written behind it",
          open(os.path.join(dst, "a.txt")).read() == "x")

    # ---- 8. a drop of nothing usable is declined, not swallowed ----
    ev = drag_to(win, [os.path.join(dst, "sub")], QPoint(int(win.property("width")) - 30,
                                                        int(win.property("height")) - 30))
    spin()
    check("a drop with nothing to do is declined", not ev.isAccepted())

    # ---- 9. hover feedback tracks, and clears on exit ----
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(os.path.join(src, "a.txt"))])
    pos = QPoint(int(win.property("width")) - 30, int(win.property("height")) - 30)
    QGuiApplication.sendEvent(win, QDragEnterEvent(pos, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
    QGuiApplication.sendEvent(win, QDragMoveEvent(pos, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
    spin(60)
    check("hovering over empty space marks the current dir as the target",
          view.property("dropTarget") == dst, view.property("dropTarget"))
    QGuiApplication.sendEvent(win, QDragLeaveEvent())
    spin(60)
    check("leaving clears the highlight", view.property("dropTarget") == "")

    print()
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        sys.exit(1)
    print("all drop checks passed")


QTimer.singleShot(0, lambda: None)
main()
