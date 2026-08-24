import QtQuick
import "../../qmlcommon"

// A picture the model placed INLINE with a reply's text — the `![alt](url)`
// it wrote, drawn at that spot in the prose rather than hoisted to the top of
// the bubble.
//
// [his, 2026-08-23] — "remove the 'all images must be at top of message'
// requirement, allow them to be put in line i.e. in with the text, AND support
// transparancy". The old reply hoisted every picture into a gallery above the
// words; a bubble now lays its markdown out as runs (`Ollama.replyRuns`) and
// this is what an `img` run renders.
//
// Capped to the column and never upscaled past native (docs/DESIGN.md §1); a
// very tall source is capped to a generous 1.5:1 of the column so one picture
// cannot blow the whole bubble. The frame's fill is TRANSPARENT so a PNG's
// alpha shows the bubble behind it rather than a solid slab [his, 2026-08-23]
// — transparency is carried through, not flattened. One click opens the
// Lightbox, which is where a capped picture is seen full size.
Item {
    id: inl

    // The run's entry: {url, path, alt, w, h} — the local path of a fetched
    // picture and the model's alt text.
    property var entry: null
    // The bubble's inner width; the image caps to this and never exceeds it.
    property real maxWidth: 480
    signal enlarge()
    // Right-click, so the picture can leave the window — Root owns the menu.
    signal contextRequested(string path, real x, real y)

    readonly property var e: (entry && entry.path) ? entry : null
    readonly property real natW: (e && e.w > 0) ? e.w : maxWidth
    readonly property real natH: (e && e.h > 0) ? e.h : maxWidth
    // The height ceiling, and it is not generous on purpose: a portrait render
    // sized by the bubble's width alone is nearly three times the height of a
    // landscape one and pushes the reply off the screen [his, 2026-08-24]. Same
    // 420 the gallery and VideoCard use, so every shape of media in a reply
    // takes comparable room; click it for the full size.
    readonly property real maxH: Math.max(240, Math.min(420, maxWidth * 1.5))
    readonly property real scaleFit: Math.min(1, maxWidth / Math.max(1, natW),
                                              maxH / Math.max(1, natH))
    readonly property real dispW: Math.max(1, Math.round(natW * scaleFit))
    readonly property real dispH: Math.max(1, Math.round(natH * scaleFit))

    width: Math.max(1, Math.round(maxWidth))
    height: dispH + 2 + (caption.visible ? caption.height + 2 : 0)
    visible: e !== null

    // The frame: a hairline around the picture, and the fill is TRANSPARENT so
    // the alpha of a transparent PNG shows the bubble behind it (docs/DESIGN.md
    // §4, and transparency [his, 2026-08-23]) rather than a second slab.
    Rectangle {
        width: inl.dispW + 2
        height: inl.dispH + 2
        color: "transparent"
        radius: Theme.rounding
        border.width: Theme.ctrlBorder
        border.color: Theme.border

        Image {
            id: pic
            x: 1; y: 1
            width: inl.dispW
            height: inl.dispH
            // Aspect preserved, never upscaled past native. The decode is
            // capped so a huge source is not decoded at full size.
            sourceSize.width: Math.max(1, Math.round(inl.dispW))
            sourceSize.height: Math.max(1, Math.round(inl.dispH))
            fillMode: Image.PreserveAspectFit
            asynchronous: true
            source: inl.e ? "file://" + inl.e.path : ""
        }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            onClicked: function (m) {
                if (m.button === Qt.RightButton) {
                    var p = mapToItem(null, m.x, m.y);
                    inl.contextRequested(inl.e ? (inl.e.path || "") : "",
                                         p.x, p.y);
                } else {
                    inl.enlarge();
                }
            }
        }
    }

    // The model's alt text, under the picture (docs/DESIGN.md §9.1 — a caption,
    // one step dim).
    PixelText {
        id: caption
        y: inl.dispH + 4
        width: inl.width
        wrapMode: Text.Wrap
        visible: inl.e && !!inl.e.alt
        text: (inl.e && inl.e.alt) ? inl.e.alt : ""
        color: Theme.textDim
    }

    // A file that saved but will not decode (§10 — say so, never a blank).
    PixelText {
        y: inl.dispH + 4
        width: inl.width
        wrapMode: Text.Wrap
        visible: pic.status === Image.Error
        text: "image: could not display"
        color: Theme.crit
    }
}
