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

    onWheel: function(wheel) {
        var max = view ? Math.max(0, view.contentHeight - view.height) : 0;
        if (!view || max <= 0) {
            wheel.accepted = false;   // nothing to scroll — let it bubble out
            return;
        }
        var dy = wheel.pixelDelta.y !== 0
                 ? wheel.pixelDelta.y
                 : (wheel.angleDelta.y / 120) * root.lines * root.step;
        view.contentY = Math.max(0, Math.min(max, view.contentY - dy));
        wheel.accepted = true;
        root.scrolled();
    }
}
