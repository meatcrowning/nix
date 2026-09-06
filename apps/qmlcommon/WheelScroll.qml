import QtQuick

// The one wheel-to-contentY translator shared by every app in apps/. It exists
// because hyprvtb's compositor-side momentum arrives here as a raw wheel stream,
// and Qt's default Flickable adds its own momentum on top of it.
//
// The rule that falls out: wheel and scrollbar only, no Qt flicking. Every
// scrollable view sets `interactive: false` and overlays one of these, while
// presses and hover fall through to whatever is underneath.
MouseArea {
    id: root
    property Flickable view: null
    // One "line". Theme is a root CONTEXT PROPERTY in all six apps, so it
    // resolves here; the guard is for teardown (and for a harness that has no
    // Theme), where reading through a null would spam TypeErrors.
    property real step: (typeof Theme !== "undefined" && Theme ? Theme.fontSize : 14) + 2
    property int lines: 3                    // lines per wheel notch
    // Multiplier on the finger-pixel path, for a window whose wheel stream has
    // already been rescaled before it reaches QML. Exactly one caller needs it:
    // surfer, whose ZoomFilter divides every touchpad event by pylib/kinetic.py's
    // WHEEL_GAIN so QtWebEngine pages track the finger — its QML overlays sit in
    // the same window and must undo it (`gain: WheelGain`, published by
    // surfer/main.py from that same constant). Leave it 1 everywhere else.
    property real gain: 1.0
    signal scrolled()                        // after contentY actually moved

    anchors.fill: parent
    acceptedButtons: Qt.NoButton
    propagateComposedEvents: true

    // Wire-level constants, fixed by the Wayland/Qt seam, not tunables. Kept in
    // step with apps/pylib/kinetic.py, which is the Python half of the same
    // discriminator (surfer's event filter).
    readonly property int detent: 120        // one classic mouse-wheel notch
    readonly property int anglePerPixel: 12  // QtWayland: angleDelta = 12 x surface px

    // THE SUB-PIXEL TRAP. `pixelDelta` is an INTEGER, so a touchpad moving
    // slower than one pixel per report (which at 125Hz is most of a slow
    // scroll — measured: 226 of 413 events in one gesture) arrives as
    // pixelDelta 0 with a small angleDelta. Sending that down the wheel-notch
    // branch below scrolled it 3 lines' worth of a 120-unit detent — ~45px
    // where the finger had moved 0.25px — so scrolling SLOWLY outran scrolling
    // normally by ~4.5x, which is exactly backwards. QtWayland sets
    // angleDelta = 12 x the true surface-pixel delta, so that is the
    // high-resolution signal to divide by; contentY is a real, so fractional
    // pixels accumulate on their own with nothing to carry by hand.
    // A real mouse wheel is told apart by its detent: |angleDelta| >= 120, and
    // it never carries a pixelDelta (qtbase qwaylandinputdevice.cpp:
    // FrameData::hasPixelDelta() is false for axis_source_wheel).
    // CLAMP AGAINST originY, NOT 0. A Flickable's content does not have to
    // start at contentY 0: `originY` is where it starts, and Qt's own bounds
    // are [originY, originY + contentHeight - height]. It is 0 for a plain
    // Column, but a ListView RECOMPUTES it whenever delegate sizes change
    // under it — the album grid resizes every cell when the column count or
    // the window width changes, and one measured case landed at
    // originY = -48000. Clamping to 0 there let the wheel scroll thousands of
    // pixels into blank space at one end and stopped it just as far short of
    // the other. (Verified against Qt: parking contentY at the old clamp's
    // "bottom" and calling returnToBounds() snapped it back to exactly
    // originY + contentHeight - height.)
    onWheel: function(wheel) {
        var minY = view ? view.originY : 0;
        var span = view ? Math.max(0, view.contentHeight - view.height) : 0;
        if (!view || span <= 0) {
            wheel.accepted = false;   // nothing to scroll — let it bubble out
            return;
        }
        var ad = wheel.angleDelta.y;
        var dy = wheel.pixelDelta.y !== 0 ? wheel.pixelDelta.y * root.gain
               : Math.abs(ad) >= root.detent
                                          ? (ad / root.detent) * root.lines * root.step
               :                            (ad / root.anglePerPixel) * root.gain;
        view.contentY = Math.max(minY, Math.min(minY + span, view.contentY - dy));
        wheel.accepted = true;
        root.scrolled();
    }
}
