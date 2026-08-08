import QtQuick

// 0–5 star rating as pixel glyphs: filled '*' up to the rating, '·' beyond.
// Click star N → N/5 stars (FMPS 0..1); clicking the current rating again
// clears it (passes -1 through). rating < 0 means unrated.
Row {
    id: root
    property real rating: -1   // FMPS 0..1, or -1 unrated
    property bool interactive: true
    // A filled star is an accent foreground and fades with the window
    // (docs/DESIGN.md §3.1.1); the empty '·' stays `Theme.dim`, which is already
    // below the inactive grey.
    property color fgAccent: Theme.accent
    signal rated(real fmps)  // 0..1, or -1 to clear

    spacing: 0

    Repeater {
        model: 5
        Item {
            width: 10
            height: 15
            PixelText {
                anchors.centerIn: parent
                text: root.rating >= (index + 0.5) / 5 ? "*" : "·"
                color: root.rating >= (index + 0.5) / 5 ? root.fgAccent : Theme.dim
            }
            MouseArea {
                cursorShape: root.interactive ? Qt.PointingHandCursor : Qt.ArrowCursor
                anchors.fill: parent
                enabled: root.interactive
                onClicked: {
                    var v = (index + 1) / 5;
                    root.rated(Math.abs(root.rating - v) < 0.01 ? -1 : v);
                }
            }
        }
    }
}
