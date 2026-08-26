import QtQuick

// The wheel-to-contentY translator, in a Plasma session wearing OXYGEN.
//
// SAME JOB, DIFFERENT REASON. `../WheelScroll.qml` exists to get OUT OF THE
// WAY of the compositor: hyprvtb synthesizes macOS-style momentum at the seat,
// so a coast arrives as an ordinary high-resolution axis stream and a view
// honours it only if it moves proportionally and adds nothing of its own.
// KWin synthesizes no such thing, so under this roof there is no momentum to
// honour — and there must be none to invent either. A KDE list does not coast:
// one wheel notch moves `wheelScrollLines` lines and stops, which is exactly
// what a proportional, momentum-free translator produces. So the algorithm
// below is the sibling's, kept because it is already the right one, not
// because a compositor demands it.
//
// What actually differs:
//   • THE UNIT. The sibling's "line" is `Theme.fontSize + 2` — a pixel-face
//     cell. Here it is the SESSION FONT'S line spacing, measured with
//     FontMetrics off the same face `+oxygen/PixelText.qml` draws with, so a
//     notch moves three rows of the text actually on screen.
//   • Qt's own flicking stays OFF in the Kinetic* twins that host this, which
//     under this roof is not a workaround but the correct desktop behaviour:
//     press-and-drag inside a list selects, it does not throw the view.
//
// It accepts NO buttons, so presses, double-clicks and hover fall straight
// through to the rows (and the scrollbar) underneath; unhandled wheels are left
// unaccepted, so a view that cannot scroll passes the notch out to whatever is
// behind it.
MouseArea {
    id: root

    property string face: "oxygen"

    property Flickable view: null

    // ONE LINE, in the session's face. FontMetrics is Qt's own measurement of
    // the live font, which is what every real KDE view scrolls by. The guard is
    // for teardown and for a harness with no Theme/DeskStyle, where reading
    // through a null would spam TypeErrors.
    readonly property bool kdeType: (typeof DeskStyle !== "undefined" && DeskStyle
                                     && DeskStyle.plasma === true)
    FontMetrics {
        id: fm
        font.family: root.kdeType && typeof Theme !== "undefined" && Theme
                   ? Theme.font : Qt.application.font.family
        font.pixelSize: {
            if (root.kdeType && typeof Theme !== "undefined" && Theme)
                return Theme.fontSize;
            const af = Qt.application.font;
            if (af.pixelSize > 0)
                return af.pixelSize;
            const dpi = Screen.logicalPixelDensity > 0
                      ? Screen.logicalPixelDensity * 25.4 : 96;
            return Math.max(1, Math.round(af.pointSize * dpi / 72));
        }
    }
    property real step: Math.max(1, Math.round(fm.height))

    // Lines per classic wheel detent. Qt's own default (QApplication::
    // wheelScrollLines) and KDE's (`kdeglobals [KDE] WheelScrollLines`) are
    // both 3; neither is published to QML today, so 3 is the documented
    // default rather than a taste.
    property int lines: 3

    // Present for API compatibility with the sibling — the Kinetic* twins alias
    // it — and 1 under this roof. The one caller that needs it is surfer, whose
    // ZoomFilter pre-divides the stream; surfer does not wear this face.
    property real gain: 1.0

    signal scrolled()                        // after contentY actually moved

    anchors.fill: parent
    acceptedButtons: Qt.NoButton
    propagateComposedEvents: true

    // Wire-level constants, fixed by the Wayland/Qt seam, not tunables. Kept in
    // step with apps/pylib/kinetic.py.
    readonly property int detent: 120        // one classic mouse-wheel notch
    readonly property int anglePerPixel: 12  // QtWayland: angleDelta = 12 x surface px

    // THE SUB-PIXEL TRAP, carried over verbatim from the sibling because it is
    // a property of the Qt/Wayland seam, not of either desktop: `pixelDelta` is
    // an INTEGER, so a touchpad moving slower than one pixel per report arrives
    // as pixelDelta 0 with a small angleDelta, and sending that down the
    // wheel-notch branch scrolls three lines where the finger moved a quarter
    // of a pixel. QtWayland sets angleDelta = 12 x the true surface-pixel
    // delta, so that is the high-resolution signal to divide by; a real mouse
    // wheel is told apart by its detent (|angleDelta| >= 120, and it never
    // carries a pixelDelta).
    //
    // CLAMP AGAINST originY, NOT 0: a Flickable's content does not have to
    // start at 0 (a ListView recomputes originY whenever delegate sizes change
    // under it), and Qt's own bounds are [originY, originY + contentHeight -
    // height].
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
