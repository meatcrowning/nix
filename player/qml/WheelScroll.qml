import QtQuick

// player's scrolling policy: the SCROLLBAR and the WHEEL only — no
// click-and-drag flicking. Qt gives you both or neither (a Flickable with
// `interactive: false` ignores the wheel too), so every scrollable view sets
// `interactive: false` and overlays one of these to translate wheel notches
// into contentY.
//
// It accepts NO buttons, so presses, double-clicks and hover fall straight
// through to the rows (and the scrollbar) underneath — it only ever sees the
// wheel. Unhandled wheels are left unaccepted, so a view that cannot scroll
// passes the notch out to whatever is behind it (e.g. the album gallery
// scrolling while the pointer is over an open album section).
MouseArea {
    id: root
    property Flickable view: null
    property real step: Theme.fontSize + 2   // one "line"
    property int lines: 3                    // lines per wheel notch
    signal scrolled()                        // after contentY actually moved

    anchors.fill: parent
    acceptedButtons: Qt.NoButton
    propagateComposedEvents: true

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
    // A real mouse wheel is told apart by its detent: |angleDelta| >= 120.
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
        var dy = wheel.pixelDelta.y !== 0 ? wheel.pixelDelta.y
               : Math.abs(ad) >= 120      ? (ad / 120) * root.lines * root.step
               :                            ad / 12;
        view.contentY = Math.max(minY, Math.min(minY + span, view.contentY - dy));
        wheel.accepted = true;
        root.scrolled();
    }
}
