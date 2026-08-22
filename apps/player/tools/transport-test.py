#!/usr/bin/env python3
"""Harness for the Plasma-session transport bar's seek widget (player/transport.py).

    player-qtenv python3 apps/player/tools/transport-test.py

OFFSCREEN, and against a FAKE Player — it never starts mpv, never touches MPRIS
and never speaks to the running player (~/nix/AGENTS.md: "never drive the
running player; he listens on it live"). It replaces `playbar-test.py`, which
tested `PlayBar.qml`: that strip was a QML imitation of a transport bar and is
gone — the bar is a real `QToolBar` now and this is the one thing on it that is
not a `QAction`.

Covers: that the handle follows `Player.position`; that a drag HOLDS the handle
and only the release seeks (a scrub that snapped back mid-drag was the thing to
avoid); that the seek fraction matches where the pointer was; that a wheel notch
is 5% and a burst accumulates against what was last asked for rather than
re-deriving from a stale position; that a touchpad's sub-detent deltas do not
each fire a full step; and that with nothing playing the slider is disabled and
both clocks read "-:--".
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")

sys.path.insert(0, str(APP))

from PySide6.QtCore import QObject, Property, Signal, Qt, QPoint, QPointF  # noqa: E402
from PySide6.QtGui import QGuiApplication, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from transport import TransportSeek, STEPS, WHEEL_STEP  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"   [{detail}]" if detail else ""))
    if not ok:
        fails.append(name)


class FakePlayer(QObject):
    """The three properties and the one slot `TransportSeek` reads, and nothing
    else. `seeks` records every `seekFrac` so a test can assert what was asked
    for without anything ever decoding a byte of audio."""

    positionChanged = Signal()
    durationChanged = Signal()
    indexChanged = Signal()

    def __init__(self):
        super().__init__()
        self._pos = 0.0
        self._dur = 0.0
        self._index = -1
        self.seeks = []

    @Property(float, notify=positionChanged)
    def position(self):
        return self._pos

    @Property(float, notify=durationChanged)
    def duration(self):
        return self._dur

    @Property(int, notify=indexChanged)
    def index(self):
        return self._index

    def load(self, duration, index=0):
        self._dur = float(duration)
        self._index = index
        self.durationChanged.emit()
        self.indexChanged.emit()

    def advance(self, secs):
        self._pos = float(secs)
        self.positionChanged.emit()

    def seekFrac(self, frac):
        self.seeks.append(float(frac))
        # The real Player takes a tick or two to report the new time; a test
        # that echoed instantly would never exercise `_pending`.


app = QApplication(sys.argv)

player = FakePlayer()
seek = TransportSeek(player)
seek.resize(400, 30)
seek.show()
slider = seek._slider

print("transport bar seek widget")

# ---- nothing playing ----------------------------------------------------
check("idle: slider disabled", not slider.isEnabled())
check("idle: clocks read -:--",
      seek._elapsed.text() == "-:--" and seek._total.text() == "-:--",
      f"{seek._elapsed.text()} / {seek._total.text()}")

# ---- a track, and the handle following the source -----------------------
player.load(300.0)          # 5:00
player.advance(60.0)        # 1:00
check("playing: slider enabled", slider.isEnabled())
check("handle follows position", abs(slider.value() / STEPS - 0.2) < 0.005,
      str(slider.value()))
check("elapsed reads the position", seek._elapsed.text() == "1:00",
      seek._elapsed.text())
check("total reads the duration", seek._total.text() == "5:00", seek._total.text())

# ---- minutes are unbounded, not an hours field --------------------------
player.load(4814.0)         # 80:14
check("80 minutes reads 80:14, not 1:20:14", seek._total.text() == "80:14",
      seek._total.text())
player.load(300.0)
player.advance(60.0)

# ---- a drag holds the handle; only the release seeks --------------------
QTest.mousePress(slider, Qt.LeftButton, Qt.NoModifier,
                 QPoint(int(slider.width() * 0.75), slider.height() // 2))
mid = slider.value()
player.advance(65.0)        # the source moves on under the pointer
check("drag holds the handle against the source", slider.value() == mid,
      f"{slider.value()} vs {mid}")
check("drag alone does not seek", player.seeks == [], str(player.seeks))
QTest.mouseRelease(slider, Qt.LeftButton, Qt.NoModifier,
                   QPoint(int(slider.width() * 0.75), slider.height() // 2))
check("release seeks", len(player.seeks) == 1, str(player.seeks))
check("release seeks to where the pointer was",
      player.seeks and abs(player.seeks[-1] - 0.75) < 0.05,
      str(player.seeks[-1:]))

# ---- a click on the groove jumps there, it does not page ----------------
player.seeks.clear()
QTest.mouseClick(slider, Qt.LeftButton, Qt.NoModifier,
                 QPoint(int(slider.width() * 0.25), slider.height() // 2))
check("a click jumps to the click, not one page",
      player.seeks and abs(player.seeks[-1] - 0.25) < 0.05, str(player.seeks[-1:]))

# ---- the wheel: one detent is one 5% step -------------------------------
player.seeks.clear()
seek._drop_pending()
player.advance(60.0)        # back to 0.2


def wheel(units):
    """`units` in 1/8 of a detent, the way a touchpad sends them."""
    ev = QWheelEvent(QPointF(slider.width() / 2, slider.height() / 2),
                     slider.mapToGlobal(QPointF(0, 0)),
                     QPoint(0, 0), QPoint(0, int(120 * units)),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(slider, ev)


wheel(1)
check("one detent is one 5% step",
      player.seeks and abs(player.seeks[-1] - (0.2 + WHEEL_STEP)) < 0.005,
      str(player.seeks[-1:]))

# ...and a burst accumulates against what was ASKED for, not the stale source.
before = len(player.seeks)
wheel(1)
wheel(1)
check("a burst accumulates instead of re-deriving from a stale position",
      abs(player.seeks[-1] - (0.2 + 3 * WHEEL_STEP)) < 0.005,
      str(player.seeks[before:]))

# ...and sub-detent deltas are CARRIED, never rounded up to a full step.
player.seeks.clear()
for _ in range(3):
    wheel(0.25)
check("sub-detent deltas do not each fire a step", player.seeks == [],
      str(player.seeks))
wheel(0.25)
check("...they add up to one when they reach a detent", len(player.seeks) == 1,
      str(player.seeks))

print(("FAILED: " + ", ".join(fails)) if fails else "all ok")
sys.exit(1 if fails else 0)
