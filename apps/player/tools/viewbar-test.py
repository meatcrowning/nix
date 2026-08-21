#!/usr/bin/env python3
"""Harness for the Plasma-session view/sort/finder toolbar (player/qml/ViewBar.qml).

    /usr/bin/python3 apps/player/tools/viewbar-test.py     # book (Fedora PySide6)

(On top, use an app wrapper's interpreter — PySide6 is not in the bare python3.)

OFFSCREEN and self-contained: it builds the bar against fake Theme/DeskStyle,
posts synthetic clicks into this process's own offscreen window, and never
touches the running player or his screen (~/nix/AGENTS.md).

Covers: the session gate (0 high and invisible outside Plasma); that the three
view switches light the current page and emit `viewRequested` with the right
id; that the sort control emits `sortRequested` and shows the full word; and
that at the ~480px window width the finder slot still has usable width (graceful
degradation).
"""

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")

from PySide6.QtCore import QObject, Property, Qt, QPoint  # noqa: E402
from PySide6.QtGui import QGuiApplication, QColor  # noqa: E402
from PySide6.QtQuick import QQuickView  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"   [{detail}]" if detail else ""))
    if not ok:
        fails.append(name)


class FakeTheme(QObject):
    def _c(value):  # noqa: N805
        return Property(QColor, lambda self: QColor(value), constant=True)

    bg = _c("#101010")
    bgAlt = _c("#181818")
    border = _c("#404040")
    accent = _c("#70dbf6")
    text = _c("#f0f0f0")
    textDim = _c("#a0a0a0")
    dim = _c("#808080")
    highlight = _c("#303030")
    inactive = _c("#595959")

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


QML = """
import QtQuick
import "%s"

Item {
    width: 900
    height: 120
    property string view: "albums"
    property string sortMode: "orig_year"
    ViewBar {
        objectName: "bar"
        anchors { top: parent.top; left: parent.left; right: parent.right }
        view: parent.view
        sortMode: parent.sortMode
    }
}
""" % (APP / "qml").as_uri()


def build(plasma, width=900):
    tmp = Path(tempfile.mkdtemp(prefix="viewbar-test-")) / "Probe.qml"
    tmp.write_text(QML)
    view = QQuickView()
    view.setResizeMode(QQuickView.SizeRootObjectToView)   # resize() drives root width
    theme, style = FakeTheme(), FakeStyle(plasma)
    for name, obj in (("Theme", theme), ("DeskStyle", style)):
        view.rootContext().setContextProperty(name, obj)
    view.setSource(tmp.as_uri())
    if view.status() == QQuickView.Error:
        for e in view.errors():
            print("   ", e.toString())
        raise SystemExit("Probe.qml did not load")
    view.resize(width, 120)
    view.show()
    QTest.qWait(60)
    bar = view.rootObject().findChild(QObject, "bar")
    view._keep = (theme, style, tmp)
    return view, bar


def header_button(bar, label):
    for it in bar.findChildren(QObject):
        if it.property("label") == label and it.metaObject().className().startswith("HeaderButton"):
            return it
    # HeaderButton is an inline .qml type; className may be QQuickItem-derived.
    for it in bar.findChildren(QObject):
        if it.property("label") == label and it.property("lit") is not None:
            return it
    return None


def click(view, bar, item):
    c = item.mapToItem(view.rootObject(), item.property("width") / 2, item.property("height") / 2)
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, QPoint(int(c.x()), int(c.y())))
    QTest.qWait(20)


app = QGuiApplication([])

print("session gate")
view, bar = build(False)
check("hypr: the bar is 0 high", bar.property("height") == 0)
check("hypr: and invisible", bar.property("visible") is False)
view.close()

print("\nplasma: the bar is present")
view, bar = build(True)
check("visible", bar.property("visible") is True)
check("has height", bar.property("height") > 0, str(bar.property("height")))

print("\nthe view switches")
requests = []
bar.viewRequested.connect(lambda v: requests.append(v))
for label, want in (("albums", "albums"), ("playlists", "playlists"), ("now playing", "now")):
    b = header_button(bar, label)
    check(f"the '{label}' switch exists", b is not None)
    if b:
        click(view, bar, b)
check("each switch emitted its view id in order", requests == ["albums", "playlists", "now"],
      str(requests))

print("\nthe lit page")
alb = header_button(bar, "albums")
now = header_button(bar, "now playing")
check("albums is lit when view == albums", alb and alb.property("lit") is True)
check("now playing is not", now and now.property("lit") is False)

print("\nthe sort control")
sorts = []
bar.sortRequested.connect(lambda: sorts.append(1))
srt = header_button(bar, "sort: year")
check("the sort control shows the full word", srt is not None)
if srt:
    click(view, bar, srt)
check("clicking it emits sortRequested", sorts == [1], str(sorts))
view.close()

print("\nsort label tracks the mode")
view, bar = build(True)
view.rootObject().setProperty("sortMode", "artist")
QTest.qWait(20)
check("artist mode reads 'sort: artist'", header_button(bar, "sort: artist") is not None)
view.close()

print("\nnarrow window (~480) — the finder slot survives")
view, bar = build(True, width=480)
slot = None
for it in bar.findChildren(QObject):
    # searchSlot is the only 22-high Item with a positive width in the bar
    if it.property("height") == 22 and it.property("width") and it.property("width") > 0:
        slot = it
        break
check("the finder slot exists and has width at 480", slot is not None and slot.property("width") > 40,
      str(slot.property("width")) if slot else "none")
view.close()

print()
if fails:
    print(f"{len(fails)} FAILED: " + ", ".join(fails))
    sys.exit(1)
print("all checks passed")
