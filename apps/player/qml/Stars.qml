import QtQuick

// 0–5 star rating as pixel glyphs: filled '*' up to the rating, '·' beyond.
// Click star N → N/5 stars (FMPS 0..1); clicking the current rating again
// clears it (passes -1 through). rating < 0 means unrated.
Row {
    id: root
    property real rating: -1   // FMPS 0..1, or -1 unrated
    property bool interactive: true
    // Normally a filled star is accent foreground and the empty '·' is dim.
    // A selected track supplies one readable foreground for both, because the
    // dim/accent pair disappears against Theme.highlight.
    property color fgAccent: Theme.accent
    property color fgDim: Theme.dim
    readonly property bool plasma: (typeof DeskStyle !== "undefined" && DeskStyle)
                                   ? DeskStyle.plasma === true : false
    signal rated(real fmps)  // 0..1, or -1 to clear

    spacing: 0

    Repeater {
        model: 5
        Item {
            width: root.plasma ? 13 : 10
            height: root.plasma ? 20 : 15
            PixelText {
                anchors.centerIn: parent
                font.pixelSize: root.plasma ? Theme.fontSize + 3 : Theme.fontSize
                text: root.rating >= (index + 0.5) / 5 ? "*" : "·"
                color: root.rating >= (index + 0.5) / 5 ? root.fgAccent : root.fgDim
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
