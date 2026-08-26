import QtQuick
import QtQuick.Controls as QQC

// A picture's caption in an Oxygen session: the STYLE'S OWN label, twice.
//
// `../CaptionStrip.qml` sets a PixelText at the desk's pixel face and picks its
// colours out of the wal palette. In a Plasma window wearing Oxygen the caption
// under a picture is a piece of body text like any other, so it is a `Label` —
// the system font at the system size, dimmed by the style's own disabled text
// colour rather than by a token of ours.
//
// Same API as the sibling — `caption`, `meta`, `over`, `wash` — so
// ImageGallery, InlineImage and VideoCard are untouched; the file selector
// picks between the three.
//
// `over` (the gallery TILES) keeps a translucent band, and deliberately not a
// `Frame`: it lies on artwork, and the style's frame would put a lit relief
// between him and the picture. The colour is the style's own window brush read
// off a Label's palette, not a colour of ours.
Rectangle {
    id: strip

    property string face: "oxygen"

    property string caption: ""
    property string meta: ""
    property bool over: false
    property real wash: 0.78

    height: visible ? lines.height + (over ? 4 : 2) : 0
    visible: caption !== "" || meta !== ""

    readonly property color surface: capLine.palette.window
    color: over ? Qt.rgba(surface.r, surface.g, surface.b, strip.wash)
                : "transparent"

    Column {
        id: lines
        anchors { left: parent.left; right: parent.right
                  verticalCenter: parent.verticalCenter
                  leftMargin: strip.over ? 4 : 0
                  rightMargin: strip.over ? 4 : 0 }
        spacing: 0

        QQC.Label {
            id: capLine
            width: lines.width
            visible: strip.caption !== ""
            text: strip.caption
            elide: Text.ElideRight
            // Over the artwork it is the one thing naming the picture, so it
            // takes full text weight; under it, it is a subordinate line.
            opacity: strip.over ? 1.0 : 0.75
        }
        QQC.Label {
            width: lines.width
            visible: strip.meta !== ""
            text: strip.meta
            elide: Text.ElideRight
            opacity: strip.over ? 0.75 : 0.55
        }
    }
}
