"""The Plasma session's transport bar — the seek widget on it.

In a Plasma session player is a real QMainWindow (`pylib/kdeshell.py`) and its
transport lives on a `QToolBar` along the bottom of the window, where every
other music player on that desktop keeps it. The prev/play/next and
favourite/repeat/shuffle rows on that bar are the app's own `QAction`s, routed
there by `bar: "transport"` on the one button table — so they cannot drift from
the Playback menu or from the hyprvtb titlebar column.

What an action cannot be is the SEEK BAR, and that is what this file is: a
`QSlider` between two clocks, drawn by the KDE style like every other slider in
that session.

CONTROLLED, NEVER STATEFUL, exactly as `PlayBar.qml` was before it (this file
replaces it, and the reasoning is carried over rather than reinvented): the
handle follows `Player.position` and a drag or a wheel notch only calls
`Player.seekFrac`, whose result flows back through the same signal. Two held
values are the exceptions, both bounded and both deferring to the source:

  * `_drag`, alive only while the pointer is down — a scrub that snapped back to
    the playing position on every mouse move would be unusable;
  * `_pending`, alive until the source catches up with the last wheel seek, so a
    burst of notches accumulates instead of each one re-deriving its step from a
    stale position.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QSlider, QStyle,
                               QStyleOptionSlider, QWidget)

# One wheel detent is 5% of the track — a FRACTION, not a count of seconds, the
# same step the panel seekbar (home/prog/quickshell-files/MediaContent.qml) and
# hyprvtb's titlebar scrub track use (docs/DESIGN.md §9.2).
WHEEL_STEP = 0.05
ECHO_EPS = 0.004      # how close the source has to get before we let go
ECHO_MS = 1500        # ...and how long we wait for it before giving up anyway
STEPS = 1000          # slider resolution; the value IS the fraction * 1000


def _fmt(secs):
    """m:ss, minutes unbounded — an 80-minute mix reads 80:14, not 1:20:14."""
    secs = max(0, int(round(secs)))
    return "%d:%02d" % (secs // 60, secs % 60)


class SeekSlider(QSlider):
    """A QSlider that seeks to where you CLICK, not one page towards it.

    Qt's default is `SliderPageStepAdd` on a groove press, which on a five
    minute track means clicking near the end moves you ten seconds. Every media
    player on this desktop jumps to the click (§5.3), so this maps the press
    position to a value directly — and the whole groove height is the target.
    """

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.setRange(0, STEPS)
        self.setPageStep(int(STEPS * WHEEL_STEP))
        self.setSingleStep(int(STEPS * WHEEL_STEP))
        self._wheel_rem = 0.0

    def _value_at(self, x):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(
            QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self)
        handle = self.style().subControlRect(
            QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)
        span = groove.width() - handle.width()
        pos = x - groove.x() - handle.width() / 2.0
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), int(round(pos)), max(1, int(span)))

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.isEnabled():
            self.setSliderDown(True)
            self.setValue(self._value_at(ev.position().x()))
            self.sliderMoved.emit(self.value())
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self.isSliderDown():
            self.setValue(self._value_at(ev.position().x()))
            self.sliderMoved.emit(self.value())
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self.isSliderDown():
            # `setSliderDown(False)` emits `sliderReleased` itself — emitting it
            # here as well seeks twice for one release.
            self.setSliderDown(False)
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def wheelEvent(self, ev):
        """One classic detent is one 5% step, and a touchpad's sub-detent
        remainder is CARRIED rather than rounded up.

        A touchpad is ~125Hz of sub-pixel deltas, and a sign-only handler fires
        a full step per event — the bug hyprvtb's titlebar copy had to fix and
        the reason `qmlcommon/WheelNotch.qml` exists. This is that algorithm,
        in Python, for the one control on this face that is not QML.
        """
        if not self.isEnabled():
            ev.ignore()
            return
        delta = ev.angleDelta().y() or ev.angleDelta().x()
        if not delta:
            ev.accept()
            return
        self._wheel_rem += delta / 120.0
        steps = int(self._wheel_rem)          # truncates towards zero
        self._wheel_rem -= steps
        if steps:
            steps = max(-3, min(3, steps))    # a flick cannot throw the song
            self.setValue(max(0, min(STEPS, self.value()
                                     + steps * int(STEPS * WHEEL_STEP))))
            self.sliderMoved.emit(self.value())
            self.sliderReleased.emit()
        ev.accept()


class TransportSeek(QWidget):
    """elapsed · seek slider · total, as one widget on the transport toolbar.

    One widget rather than three, because a `QToolBar` hands its spare room to
    whichever widget's size policy asks for it, and what should take that room
    is the slider WITH its two clocks pinned either side of it — not the slider
    alone with the clocks drifting.
    """

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self._player = player
        self._drag = False
        self._pending = -1.0

        self._elapsed = QLabel("-:--")
        self._total = QLabel("-:--")
        for lab in (self._elapsed, self._total):
            lab.setAlignment(Qt.AlignCenter)
            # FIXED-WIDTH SLOTS, so the track does not reflow as the digits
            # change (§5.4) — the readout is the one thing here that changes
            # every second.
            lab.setMinimumWidth(lab.fontMetrics().horizontalAdvance("000:00"))
        self._slider = SeekSlider(self)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(8)
        lay.addWidget(self._elapsed)
        lay.addWidget(self._slider, 1)
        lay.addWidget(self._total)

        self._echo = QTimer(self)
        self._echo.setSingleShot(True)
        self._echo.setInterval(ECHO_MS)
        self._echo.timeout.connect(self._drop_pending)

        self._slider.sliderPressed.connect(self._on_press)
        self._slider.sliderMoved.connect(self._on_move)
        self._slider.sliderReleased.connect(self._on_release)

        player.positionChanged.connect(self._pull)
        player.durationChanged.connect(self._pull)
        player.indexChanged.connect(self._pull)
        self._pull()

    # ---- the source -> the handle -------------------------------------
    def _has_track(self):
        return self._player.duration > 0 and self._player.index >= 0

    def _pull(self):
        has = self._has_track()
        self._slider.setEnabled(has)
        dur = float(self._player.duration or 0.0)
        play_frac = max(0.0, min(1.0, (self._player.position / dur))) if has else 0.0
        if self._pending >= 0 and abs(play_frac - self._pending) <= ECHO_EPS:
            self._drop_pending()
        if self._drag:
            frac = self._slider.value() / float(STEPS)
        elif self._pending >= 0:
            frac = self._pending
        else:
            frac = play_frac
            self._slider.setValue(int(round(frac * STEPS)))
        self._elapsed.setText(_fmt(frac * dur) if has else "-:--")
        self._total.setText(_fmt(dur) if has else "-:--")

    def _drop_pending(self):
        self._pending = -1.0
        self._echo.stop()

    # ---- the handle -> the source --------------------------------------
    def _on_press(self):
        self._drag = True

    def _on_move(self, value):
        self._drag = True
        dur = float(self._player.duration or 0.0)
        self._elapsed.setText(_fmt(value / float(STEPS) * dur)
                              if self._has_track() else "-:--")

    def _on_release(self):
        self._drag = False
        if not self._has_track():
            return
        frac = self._slider.value() / float(STEPS)
        # The wheel path lands here too, and it is the one that needs the echo:
        # a drag ends where the pointer is, but a burst of notches has to
        # accumulate against what we last ASKED for, not against a position mpv
        # has not reported yet.
        self._pending = frac
        self._echo.start()
        self._player.seekFrac(frac)
