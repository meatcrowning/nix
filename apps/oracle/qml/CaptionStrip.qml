import QtQuick

// A picture's caption: ONE LINE, at the bottom of the picture, truncated.
//
// It used to sit UNDER the image as wrapped prose, and an Anima prompt is forty
// tags long — so a picture in the chat came with a paragraph of tag soup taller
// than some of the replies [his, 2026-08-24]. The caption's job in the log is to
// say which picture this is, not to be read; the whole of it is one click away
// in the Lightbox, which wraps it in full.
//
// Anchored INSIDE the artwork rather than below it (docs/DESIGN.md §5.1 — a
// caption strip of its own is a second slab), over a wash of the page colour so
// the text stays readable on a busy crop. Two lines at most: the caption, and
// under it the dimmer line saying what MADE the picture, each elided on its own.
//
// API: `caption`, `meta`, and `wash` for a call site that wants it more or less
// opaque (the gallery tiles darken theirs on hover).
Rectangle {
    id: strip

    property string caption: ""
    property string meta: ""
    property real wash: 0.78

    anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
    height: visible ? lines.height + 4 : 0
    visible: caption !== "" || meta !== ""
    color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, strip.wash)

    Column {
        id: lines
        anchors { left: parent.left; right: parent.right
                  verticalCenter: parent.verticalCenter
                  leftMargin: 4; rightMargin: 4 }
        spacing: 0

        PixelText {
            width: lines.width
            visible: strip.caption !== ""
            text: strip.caption
            elide: Text.ElideRight
            color: Theme.text
        }
        PixelText {
            width: lines.width
            visible: strip.meta !== ""
            text: strip.meta
            elide: Text.ElideRight
            color: Theme.text
            opacity: 0.6
        }
    }
}
