"""The Python half of the desktop's kinetic-scrolling contract.

Momentum is COMPOSITOR-SIDE. hyprvtb synthesizes macOS-style decay at the seat
(`plugin:hyprvtb:kinetic` in BOTH copies of hyprland.lua, per-host via
home/prog/hypr-host.nix; design in docs/kinetic-scroll.md), so a coast reaches
every client as an ordinary high-resolution wheel/axis stream. Nothing here
generates momentum — this module only holds the constants and the one
discriminator needed to *not destroy* it on the way in.

QML's half is apps/qmlcommon/WheelScroll.qml and the KineticListView /
KineticGridView / KineticFlickable drop-ins beside it. Any Python that touches
QWheelEvent must import from here rather than re-deriving the numbers; that
duplication is what this file exists to stop.

Import it the way every app imports pylib:

    sys.path.insert(0, str(HERE.parent / "pylib"))
    from kinetic import WHEEL_GAIN, is_wheel
"""

# One classic mouse-wheel notch, in Qt angleDelta units. Protocol constant.
DETENT = 120

# QtWayland synthesizes angleDelta = 12 x the true surface-pixel delta for a
# touchpad (qtbase qwaylandinputdevice.cpp). Protocol constant.
ANGLE_PER_PIXEL = 12

# QtWebEngine ignores pixelDelta() entirely and scrolls by
# angleDelta/120 * wheelScrollLines(3) * 20 px (web_event_factory.cpp), while
# QtWayland synthesizes angleDelta = pixelDelta * 12 for touchpads — so one
# finger-pixel of trackpad scroll moves a page ~6 px where the QML apps
# (player/filer/painter, pixelDelta 1:1) move 1. This factor cancels that: 1/6
# puts a web page at parity with the rest of the desktop, drag phase and
# kinetic coast alike (scaling at the event source keeps the coast consistent
# with the drag — deliberately NOT special-cased in the compositor's momentum
# engine). Raise it if pages should feel a bit brisker than lists.
#
# IT APPLIES TO TOUCHPADS ONLY — see is_wheel(). The correction is
# entirely about QtWayland's angleDelta = 12 x finger-pixels synthesis; a real
# mouse wheel has no such inflation, and applying the gain there made top's
# wheel scroll web pages at 1/6 speed, which is the bug this note exists to
# prevent a third time.
WHEEL_GAIN = 1 / 6

# What a QML overlay in the SAME window must multiply by to undo WHEEL_GAIN.
# surfer's ZoomFilter is window-scoped, so its file picker sees rescaled events
# too; it publishes this as the `WheelGain` context property and the picker's
# WheelScroll takes it as `gain`.
QML_WHEEL_GAIN = 1 / WHEEL_GAIN


def is_wheel(event):
    """True for a real mouse wheel (leave it alone), False for a touchpad's
    high-resolution stream (scale it).

    The scroll PHASE is the discriminator. QtWayland opens a ScrollBegin /
    ScrollUpdate / ScrollEnd sequence only for axis_source_finger, which is
    also what hyprvtb's momentum coast emits, so finger streams always carry
    a phase and a wheel never does. Since Qt 6.12 a wheel notch carries a
    pixelDelta too (FrameData::hasPixelDelta() is gone), so a null
    pixelDelta no longer identifies a wheel, and |angleDelta| >= 120 never
    did for high-resolution wheels.

    `event` is a QWheelEvent.
    """
    from PySide6.QtCore import Qt
    return event.phase() == Qt.ScrollPhase.NoScrollPhase
