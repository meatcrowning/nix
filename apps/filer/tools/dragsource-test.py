#!/usr/bin/env python3
"""Offscreen harness for filer's drag-and-drop: the DRAG-OUT (source) half.

`drop-test.py` covers the receiving end. This one covers the end that crashed:
a QDrag started from a LIST ROW or a PREVIEW TILE, while something rebuilds the
model underneath it.

`Drag.active` is bound on the delegate, so `QQuickDragAttached::startDrag` runs
`QDrag::exec()` — a NESTED event loop — from inside the delegate's own
`QQuickMouseArea::mouseMoveEvent`. Timers keep running in that loop, so
`DirWatch`'s debounce fires, `refreshAll()` reassigns `rows`/`previews`, and every
delegate is destroyed — including the one whose `mouseMoveEvent` is still on the
stack and whose child `QDrag` the drag manager is still holding. Both halves are
then use-after-free; the four filer coredumps on `top` between 2026-08-03 and
2026-08-05 are exactly those two signatures.

So this harness starts a real drag (QTest, so the events go in at the platform
layer the way a compositor delivers them) and fires a real DirWatch rebuild
while it is live. What it asserts is the INVARIANT that makes the crash
impossible: no model reassignment while a drag-out is in flight, and the
delegate that started it is still standing when the drag ends.

It cannot assert the segfault itself. The offscreen platform's QPlatformDrag
returns without spinning QDrag::exec()'s nested event loop, so the drag here is
Qt-side only and the window of use-after-free never opens. That is also why
`dragInFlight` has to be checked directly rather than inferred from a hang.

No window is ever mapped (QT_QPA_PLATFORM=offscreen, hard) and the user's
session is never touched.
"""
import os
import shutil
import struct
import sys
import tempfile
import time
import zlib

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session: with no
os.environ.pop("DISPLAY", None)          # display Qt aborts, it cannot fall back

FILER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FILER)
sys.path.insert(0, os.path.join(os.path.dirname(FILER), "pylib"))
from deskstyle import DeskStyle  # noqa: E402  (pylib; Theme.qml binds to it)

from PySide6.QtCore import QObject, QPoint, QPointF, QUrl, Qt, Slot  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QJSValue, QQmlApplicationEngine, QQmlComponent  # noqa: E402
from PySide6.QtQuick import QQuickItem  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

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
    @Slot(bool, float)
    def setPlaybar(self, on, frac): pass


def unwrap(v):
    return v.toVariant() if isinstance(v, QJSValue) else v


def walk(obj, depth=0):
    """Every descendant QObject. A view's delegates hang off the contentItem as
    VISUAL children only, so `children()` alone never reaches a row — the
    `childItems()` half is what makes the delegates findable at all."""
    yield obj
    if depth > 40:
        return
    kids = list(obj.children())
    if isinstance(obj, QQuickItem):
        for c in obj.childItems():
            if c not in kids:
                kids.append(c)
    for ch in kids:
        yield from walk(ch, depth + 1)


def find(root, prop):
    for o in walk(root):
        try:
            if o.property(prop) is not None:
                return o
        except Exception:
            pass
    return None


def find_row(pane, name):
    """The list delegate whose `modelData.name` is `name`."""
    for o in walk(pane):
        try:
            md = unwrap(o.property("modelData"))
        except Exception:
            continue
        if isinstance(md, dict) and md.get("name") == name and o.property("indent") is not None:
            return o
    return None


def find_tile(pane, path):
    """The preview-grid delegate for `path` (PreviewTile carries `entry`)."""
    for o in walk(pane):
        try:
            e = unwrap(o.property("entry"))
        except Exception:
            continue
        if isinstance(e, dict) and e.get("path") == path:
            return o
    return None


def spin(ms=120):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QGuiApplication.processEvents()
        time.sleep(0.005)


def write_png(path, w=8, h=8):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + b"\xa0\x40\x80" * w for _ in range(h))
    open(path, "wb").write(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b""))


def build(app, start_dir):
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    keep = (filermain.FileOps(), filermain.Palette(filermain.PANEL_THEME),
            filermain.Settings(), filermain.DirWatch(), filermain.WinCtl(),
            filermain.VideoConv(), StubTitlebar(), filermain.Picker(None),
            filermain.Phone())
    names = ("FileOps", "WalPalette", "Settings", "DirWatch", "WinCtl",
             "VideoConv", "Titlebar", "Picker", "Phone")
    for n, o in zip(names, keep):
        ctx.setContextProperty(n, o)
    _deskstyle = DeskStyle(parent=engine)
    ctx.setContextProperty("DeskStyle", _deskstyle)
    # The preview grid's tiles bind their Image to `image://thumb/`; without the
    # provider every tile sits at Image.Null for ever, which silently disables
    # anything a harness wants to assert about a READY tile (thumb-test.py's
    # play marker, for one).
    engine.addImageProvider("thumb", filermain.ThumbProvider())
    for n, v in (("startDir", start_dir), ("startSortField", "name"),
                 ("startSortAsc", True), ("startShowHidden", True),
                 ("startGridPanelH", 200), ("startSplit", False),
                 ("startSplitDir", ""), ("startSplitRatio", 0.5),
                 ("startSplitVertical", True)):
        ctx.setContextProperty(n, v)
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
    return engine, roots[0], keep + (theme, _deskstyle)


def centre(item):
    c = item.mapToScene(QPointF(item.property("width") / 2, item.property("height") / 2))
    return int(c.x()), int(c.y())


def start_drag(win, item):
    """Press on `item` and move past the drag threshold, so `drag.active` — and
    with it the window's `dragInFlight` — turns on. Returns the press point."""
    x, y = centre(item)
    QTest.mousePress(win, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    spin(60)
    for i in range(1, 5):
        QTest.mouseMove(win, QPoint(x + i * 14, y + i * 14))
        spin(20)
    return x, y


def end_drag(win, at):
    QTest.mouseRelease(win, Qt.LeftButton, Qt.NoModifier, QPoint(at[0] + 70, at[1] + 70))
    spin(400)


def main():
    app = QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":   # a mapped window would be HIS screen
        raise SystemExit("refusing to run on platform %r, not offscreen" % app.platformName())

    tmp = tempfile.mkdtemp(prefix="filer-dragsrc-")
    for n in ("alpha.txt", "beta.txt", "gamma.txt"):
        open(os.path.join(tmp, n), "w").write("x")
    os.mkdir(os.path.join(tmp, "sub"))

    engine, win, keep = build(app, tmp)
    dirwatch = keep[3]
    spin(500)

    pane = find(win, "watchKey")
    check("pane found", pane is not None)
    if pane is None:
        return 1
    check("model populated", len(unwrap(pane.property("rows"))) == 4,
          unwrap(pane.property("rows")))

    # ---- 1. a plain drag, nothing disturbing it: the baseline ----------------
    row = find_row(pane, "alpha.txt")
    check("row delegate found", row is not None)
    if row is None:
        return 1
    at = start_drag(win, row)
    check("a row drag raises the window's dragInFlight",
          unwrap(win.property("dragInFlight")) is True)
    check("nothing is deferred yet", unwrap(pane.property("rebuildDeferred")) is False)
    end_drag(win, at)
    check("the release clears dragInFlight",
          unwrap(win.property("dragInFlight")) is False)

    # ---- 2. THE CRASH: DirWatch rebuilds the model mid-drag ------------------
    row = find_row(pane, "beta.txt")
    at = start_drag(win, row)
    open(os.path.join(tmp, "delta.txt"), "w").write("x")
    dirwatch.changed.emit()
    spin(300)
    check("a rebuild during a drag is deferred, not applied",
          unwrap(pane.property("rebuildDeferred")) is True)
    # A destroyed delegate keeps its PySide wrapper (shiboken6.isValid stays
    # true), so "still the live source of the drag" is read off the required
    # property the delegate model owns — that goes null the moment it is torn
    # down. This is the assertion that stands in for the segfault.
    check("the drag source delegate was not torn down",
          unwrap(row.property("modelData")) is not None)
    check("the model was not reassigned under the drag",
          sorted(r["name"] for r in unwrap(pane.property("rows")))
          == ["alpha.txt", "beta.txt", "gamma.txt", "sub"])
    end_drag(win, at)
    check("the deferred rebuild is flushed on release",
          unwrap(pane.property("rebuildDeferred")) is False)
    check("the file that appeared mid-drag is listed afterwards",
          "delta.txt" in sorted(r["name"] for r in unwrap(pane.property("rows"))),
          sorted(r["name"] for r in unwrap(pane.property("rows"))))

    # ---- 3. same for a preview tile (the grid's model is reassigned too) -----
    png = os.path.join(tmp, "pic.png")
    write_png(png)
    dirwatch.changed.emit()
    spin(400)
    tile = find_tile(pane, png)
    check("preview tile found", tile is not None)
    if tile is not None:
        at = start_drag(win, tile)
        check("a tile drag raises dragInFlight too",
              unwrap(win.property("dragInFlight")) is True)
        open(os.path.join(tmp, "eps.txt"), "w").write("x")
        dirwatch.changed.emit()
        spin(300)
        check("the tile was not torn down across a mid-drag rebuild",
              unwrap(tile.property("entry")) is not None)
        check("the grid model was not reassigned",
              len(unwrap(pane.property("previews"))) == 1,
              unwrap(pane.property("previews")))
        end_drag(win, at)
        check("the tile drag's deferred rebuild is flushed",
              "eps.txt" in [r["name"] for r in unwrap(pane.property("rows"))])

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
