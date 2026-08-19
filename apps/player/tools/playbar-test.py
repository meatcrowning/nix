#!/usr/bin/env python3
"""Harness for the Plasma-session transport strip (player/qml/PlayBar.qml).

    <an app python> apps/player/tools/playbar-test.py

(PySide6 is not in the bare python3 here: use an app wrapper's interpreter, e.g.
`$(tail -1 $(command -v player) | sed 's/^exec "//; s/".*//')`.)

OFFSCREEN, and against a FAKE Player — it never starts mpv, never touches MPRIS
and never speaks to the running player (~/nix/AGENTS.md: "never drive the
running player; he listens on it live"). The clicks are synthetic events posted
into this process's own offscreen window.

Covers: the session gate (invisible and 0 high outside Plasma); that the fill
follows `Player.position`; that a drag holds the handle and only the RELEASE
seeks (a scrub that snapped back mid-drag was the thing to avoid); that the seek
fraction matches where the pointer was; and that with nothing playing the bar
draws no handle and swallows no clicks.
"""

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QObject, Property, Signal, Slot, Qt, QPoint  # noqa: E402
from PySide6.QtGui import QGuiApplication, QColor  # noqa: E402
from PySide6.QtQuick import QQuickView  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"   [{detail}]" if detail else ""))
    if not ok:
        fails.append(name)


class FakeTheme(QObject):
    def _c(value):  # noqa: N805 - a tiny factory, not a method
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


class FakePlayer(QObject):
    """Only the surface PlayBar.qml reads: no audio, no MPRIS, no file."""
    changed = Signal()

    def __init__(self, duration=200.0, index=0, queue=3):
        super().__init__()
        self._pos, self._dur, self._idx, self._q = 0.0, duration, index, queue
        self._playing = True
        self.seeks = []            # every seekFrac the bar asked for
        self.calls = []            # previous/toggle/next

    @Property(float, notify=changed)
    def position(self):
        return self._pos

    def set_position(self, v):
        self._pos = v
        self.changed.emit()

    @Property(float, notify=changed)
    def duration(self):
        return self._dur

    @Property(int, notify=changed)
    def index(self):
        return self._idx

    @Property(int, notify=changed)
    def queueLength(self):
        return self._q

    @Property(bool, notify=changed)
    def playing(self):
        return self._playing

    @Slot(float)
    def seekFrac(self, frac):
        self.seeks.append(float(frac))
        self.set_position(frac * self._dur)

    @Slot()
    def previous(self):
        self.calls.append("previous")

    @Slot()
    def next(self):
        self.calls.append("next")

    @Slot()
    def toggle(self):
        self.calls.append("toggle")


QML = """
import QtQuick
import "%s"

Item {
    width: 600
    height: 120
    PlayBar {
        objectName: "bar"
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
    }
}
""" % (APP / "qml").as_uri()


def build(plasma, player):
    tmp = Path(tempfile.mkdtemp(prefix="playbar-test-")) / "Probe.qml"
    tmp.write_text(QML)
    view = QQuickView()
    theme, style = FakeTheme(), FakeStyle(plasma)
    for name, obj in (("Theme", theme), ("DeskStyle", style), ("Player", player)):
        view.rootContext().setContextProperty(name, obj)
    view.setSource(tmp.as_uri())
    if view.status() == QQuickView.Error:
        for e in view.errors():
            print("   ", e.toString())
        raise SystemExit("Probe.qml did not load")
    view.resize(600, 120)
    view.show()          # offscreen platform: nothing is mapped anywhere
    QTest.qWait(60)
    bar = view.rootObject().findChild(QObject, "bar")
    view._keep = (theme, style, player, tmp)   # context properties must outlive the bindings
    return view, bar


app = QGuiApplication([])

print("session gate")
p = FakePlayer()
view, bar = build(False, p)
check("hypr: the bar is 0 high", bar.property("height") == 0)
check("hypr: and invisible", bar.property("visible") is False)
view.close()

print("\nthe fill follows playback")
p = FakePlayer(duration=200.0)
view, bar = build(True, p)
check("plasma: the bar has height", bar.property("height") == 40)
check("plasma: and is visible", bar.property("visible") is True)
check("nothing played yet, so the fill is empty", bar.property("frac") == 0)
p.set_position(50.0)
QTest.qWait(30)
check("a quarter played is a quarter filled", abs(bar.property("frac") - 0.25) < 1e-6,
      str(bar.property("frac")))

print("\nscrubbing")
barY = int(view.rootObject().property("height") - bar.property("height") / 2)
# The track is the bar minus the transport row and the two clock slots; its own
# geometry is what the seek maths uses, so ask the item rather than guess.
track = None
for it in bar.findChildren(QObject):
    if it.property("width") and it.property("height") == 16:
        track = it
        break
check("the scrub track exists", track is not None)
tx = int(track.mapToItem(view.rootObject(), 0, 0).x()) if track else 0
tw = int(track.property("width")) if track else 0
mid = QPoint(tx + tw // 2, barY)
QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, mid)
QTest.qWait(30)
check("pressing holds the handle where the pointer is",
      abs(bar.property("frac") - 0.5) < 0.02, str(bar.property("frac")))
check("...and seeks NOTHING yet — the release does that", p.seeks == [], str(p.seeks))
QTest.mouseMove(view, QPoint(tx + int(tw * 0.75), barY))
QTest.qWait(30)
check("dragging moves the handle, still without seeking",
      abs(bar.property("frac") - 0.75) < 0.02 and p.seeks == [],
      f"{bar.property('frac')} {p.seeks}")
QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, QPoint(tx + int(tw * 0.75), barY))
QTest.qWait(30)
check("releasing seeks to where it was let go",
      len(p.seeks) == 1 and abs(p.seeks[0] - 0.75) < 0.02, str(p.seeks))
check("and the handle goes back to following playback", bar.property("dragFrac") == -1)
view.close()

print("\nnothing playing")
p = FakePlayer(duration=0.0, index=-1, queue=0)
view, bar = build(True, p)
check("no track means no scrub position", bar.property("hasTrack") is False)
QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier,
                 QPoint(300, int(view.rootObject().property("height") - 20)))
QTest.qWait(30)
check("clicking the dead track seeks nothing", p.seeks == [], str(p.seeks))
view.close()

print()
if fails:
    print(f"{len(fails)} FAILED: " + ", ".join(fails))
    sys.exit(1)
print("all checks passed")
