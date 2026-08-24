import QtQuick

// A picture's caption: ONE LINE, at the bottom of the picture, truncated.
//
// It used to sit UNDER the image as wrapped prose, and an Anima prompt is forty
// tags long — so a picture in the chat came with a paragraph of tag soup taller
// than some of the replies [his, 2026-08-24]. The caption's job in the log is to
// say which picture this is, not to be read; the whole of it is one click away
// in the Lightbox, which wraps it in full.
//
// It sits UNDER the picture, not over it [his, 2026-08-24]: over the artwork it
// covers the bottom of the very thing it is captioning, and a picture is worth
// more than the line naming it. `over` puts it back inside the frame for the
// one call site that needs it — the gallery TILES, where a grid of cropped
// thumbnails has no room under each cell and the strip has always been a wash
// on the crop (docs/DESIGN.md §5.1).
//
// Two lines at most: the caption, and under it the dimmer line saying what MADE
// the picture, each elided on its own.
//
// API: `caption`, `meta`, `over` (draw on the picture), and `wash` for a call
// site that wants that more or less opaque (the tiles darken theirs on hover).
Rectangle {
    id: strip

    property string caption: ""
    property string meta: ""
    property bool over: false
    property real wash: 0.78

    height: visible ? lines.height + (over ? 4 : 2) : 0
    visible: caption !== "" || meta !== ""
    color: over ? Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, strip.wash)
                : "transparent"

    Column {
        id: lines
        anchors { left: parent.left; right: parent.right
                  verticalCenter: parent.verticalCenter
                  leftMargin: strip.over ? 4 : 0
                  rightMargin: strip.over ? 4 : 0 }
        spacing: 0

        PixelText {
            width: lines.width
            visible: strip.caption !== ""
            text: strip.caption
            elide: Text.ElideRight
            color: strip.over ? Theme.text : Theme.textDim
        }
        PixelText {
            width: lines.width
            visible: strip.meta !== ""
            text: strip.meta
            elide: Text.ElideRight
            color: strip.over ? Theme.text : Theme.textDim
            opacity: 0.6
        }
    }
}
