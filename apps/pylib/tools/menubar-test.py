#!/usr/bin/env python3
"""Harness for the Plasma-session menubar (qmlcommon/DeskMenuBar.qml).

    <an app python> apps/pylib/tools/menubar-test.py

(PySide6 is not in the bare python3 here: use an app wrapper's interpreter, e.g.
`$(tail -1 $(command -v filer) | sed 's/^exec "//; s/".*//')`.)

OFFSCREEN, always: `QT_QPA_PLATFORM=offscreen` is forced before Qt loads, so
nothing here can map a window on his screen, take his focus or move his pointer
(~/nix/AGENTS.md — "Testing without interfering with the user"). The clicks
below are synthetic events posted into THIS process's offscreen window.

Covers: the session gate (0 height, invisible, outside a Plasma session); the
grouping of a real `tbButtons` array into menus, in `menuOrder`'s order; the
"-" spacer and `menuSep:` separators; that `state` 2 greys a row and `state` 1
lights it; that the tooltip becomes the row's label and a tipless button falls
back to its glyph; and end to end, that clicking a title opens its menu and
clicking a row emits `triggered` with the id the TITLEBAR would have sent — the
one property that keeps the two chromes from drifting apart.
"""

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
APPS = HERE.parent.parent

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QObject, Property, Qt, QPoint  # noqa: E402
from PySide6.QtGui import QGuiApplication, QColor  # noqa: E402
from PySide6.QtQuick import QQuickView  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

fails = []


def val(v):
    """A `property var` arrives as a QJSValue; the harness wants plain data."""
    return v.toVariant() if hasattr(v, "toVariant") else v


def check(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"   [{detail}]" if detail else ""))
    if not ok:
        fails.append(name)


# ---- the two context properties the component reads --------------------------
# A stand-in for each app's Theme.qml / DeskStyle, with only the keys
# DeskMenuBar.qml and PixelText.qml touch.
class FakeTheme(QObject):
    def _c(name, value):  # noqa: N805 - a tiny factory, not a method
        return Property(QColor, lambda self: QColor(value), constant=True)

    bg = _c("bg", "#101010")
    bgAlt = _c("bgAlt", "#181818")
    border = _c("border", "#404040")
    accent = _c("accent", "#70dbf6")
    text = _c("text", "#f0f0f0")
    highlight = _c("highlight", "#303030")
    inactive = _c("inactive", "#595959")

    @Property(str, constant=True)
    def font(self):
        return "More Perfect DOS VGA"

    @Property(int, constant=True)
    def fontSize(self):
        return 15

    @Property(bool, constant=True)
    def fontSmooth(self):
        return False

    @Property(int, constant=True)
    def lineHeight(self):
        return 15

    @Property(int, constant=True)
    def rounding(self):
        return 3

    @Property(int, constant=True)
    def ctrlBorder(self):
        return 1


class FakeStyle(QObject):
    def __init__(self, plasma):
        super().__init__()
        self._plasma = plasma

    @Property(bool, constant=True)
    def plasma(self):
        return self._plasma


# filer's real array, trimmed to the shapes that matter: a disabled entry, a lit
# one, a "-" spacer, a `menuSep`, and a button with no tip at all.
BUTTONS = """[
    { id: "up",     label: "^",  state: 2, tip: "up a directory", menu: "go" },
    { id: "sort",   label: "n",  state: 1, tip: "sort by name",   menu: "view" },
    "-",
    { id: "new",    label: "+",  state: 0, tip: "new file or folder", menu: "file" },
    { id: "rename", label: "r",  state: 0, tip: "rename selected",    menu: "file" },
    { id: "trash",  label: "t",  state: 0, tip: "move to trash", menu: "file", menuSep: true },
    { id: "bare",   label: "zz", state: 0 }
]"""

QML = """
import QtQuick
import "%s"

Item {
    width: 800
    height: 600
    DeskMenuBar {
        id: mb
        objectName: "mb"
        anchors { top: parent.top; left: parent.left; right: parent.right }
        buttons: %s
        menuOrder: ["file", "go", "view"]
        property string lastId: ""
        onTriggered: (id) => mb.lastId = id
    }
}
""" % ((APPS / "qmlcommon").as_uri(), BUTTONS)


def build(plasma):
    """A fresh view, with the session forced either way."""
    tmp = Path(tempfile.mkdtemp(prefix="menubar-test-")) / "Probe.qml"
    tmp.write_text(QML)
    view = QQuickView()
    theme, style = FakeTheme(), FakeStyle(plasma)
    view.rootContext().setContextProperty("Theme", theme)
    view.rootContext().setContextProperty("DeskStyle", style)
    view.setSource(tmp.as_uri())
    if view.status() == QQuickView.Error:
        for e in view.errors():
            print("   ", e.toString())
        raise SystemExit("Probe.qml did not load")
    view.resize(800, 600)
    view.show()          # offscreen platform: nothing is mapped anywhere
    QTest.qWait(60)
    mb = view.rootObject().findChild(QObject, "mb")
    # keep python references alive: a context-property QObject that is collected
    # takes its bindings with it (the qml-offscreen-grab-verification rule).
    view._keep = (theme, style, tmp)
    return view, mb


app = QGuiApplication([])

print("session gate")
view, mb = build(plasma=False)
check("hypr: the bar has no height", mb.property("height") == 0)
check("hypr: the bar is invisible", mb.property("visible") is False)
check("hypr: it still groups (the model is session-agnostic)",
      len(val(mb.property("menus"))) == 4)
view.close()

print("\ngrouping")
view, mb = build(plasma=True)
menus = val(mb.property("menus"))
names = [m["name"] for m in menus]
check("menuOrder decides the bar's order, not the array's",
      names == ["file", "go", "view", "actions"], str(names))
check("an entry with no menu: falls into defaultMenu",
      [i["id"] for i in menus[3]["items"]] == ["bare"])
check("a tipless button falls back to its glyph",
      menus[3]["items"][0]["label"] == "zz")
check("the tooltip is the row's label",
      menus[0]["items"][0]["label"] == "new file or folder")
fileIds = [(i["id"], i["separator"]) for i in menus[0]["items"]]
check("menuSep puts a divider above `move to trash`",
      fileIds == [("new", False), ("rename", False), ("", True), ("trash", False)],
      str(fileIds))
check("state 2 is a greyed row, not a dropped one",
      menus[1]["items"][0]["id"] == "up" and menus[1]["items"][0]["enabled"] is False)
check("state 1 lights the row", menus[2]["items"][0]["on"] is True)
check("the bar has real height in a Plasma session", mb.property("height") >= 20)
check("the bar is visible", mb.property("visible") is True)

print("\nclicking, end to end")
titles = view.rootObject().findChild(QObject, "deskMenuTitles")
panel = view.rootObject().findChild(QObject, "deskMenuPanel")
barH = int(mb.property("height"))
first = titles.childItems()[0] if hasattr(titles, "childItems") else None
tx = int(titles.property("x") + (first.property("width") / 2 if first else 20))
QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, QPoint(tx, barH // 2))
QTest.qWait(60)
check("clicking a title opens its menu", mb.property("openAt") == 0,
      str(mb.property("openAt")))
check("the popup is a real box, never zero-sized (§7)",
      panel.property("width") > 1 and panel.property("height") > 1,
      f'{panel.property("width")}x{panel.property("height")}')

rowH = max(18, 15 + 4)
px = int(panel.property("x") + 20)
py = int(panel.property("y") + 1 + rowH // 2)
QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, QPoint(px, py))
QTest.qWait(60)
check("clicking a row emits the TITLEBAR's id", mb.property("lastId") == "new",
      str(mb.property("lastId")))
check("choosing dismisses the menu", mb.property("openAt") == -1)

# ...and the row that cannot act does not act. `up` is state 2 in the `go` menu.
QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier,
                 QPoint(tx + int(first.property("width")) if first else tx + 40, barH // 2))
QTest.qWait(60)
opened = mb.property("openAt")
if opened == 1:
    px = int(panel.property("x") + 20)
    py = int(panel.property("y") + 1 + rowH // 2)
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, QPoint(px, py))
    QTest.qWait(60)
    check("a disabled row is inert", mb.property("lastId") == "new",
          str(mb.property("lastId")))
else:
    check("a disabled row is inert", False, f"the go menu did not open (openAt={opened})")
view.close()

print()
if fails:
    print(f"{len(fails)} FAILED: " + ", ".join(fails))
    sys.exit(1)
print("all checks passed")
