import QtQuick
import QtQuick.Controls as QQC

// A picture the model placed inline with a reply, in an Oxygen session.
//
// Same API as `../InlineImage.qml` — `entry`, `maxWidth`, `enlarge()`,
// `contextRequested()` — and the same sizing arithmetic to the pixel: capped to
// the column, capped again at 320 tall so a portrait render cannot push the
// reply off the screen, and never upscaled past native.
//
// What changes is the HAND. The hairline `Rectangle` becomes the style's own
// `Frame`, so the picture sits in the same well an Oxygen list or view sits in,
// with the style's relief and the style's inset instead of our 1px and our
// radius. Transparency is still carried through, not flattened: a PNG's alpha
// now shows the FRAME's own surface rather than a slab of ours, which is what a
// framed picture looks like everywhere else in this session.
Item {
    id: inl

    property string face: "oxygen"

    property var entry: null
    property real maxWidth: 480
    signal enlarge()
    signal contextRequested(string path, real x, real y)

    readonly property var e: (entry && entry.path) ? entry : null
    readonly property real natW: (e && e.w > 0) ? e.w : maxWidth
    readonly property real natH: (e && e.h > 0) ? e.h : maxWidth
    readonly property real maxH: Math.max(200, Math.min(320, maxWidth * 1.5))

    // The frame's own padding is what the picture is inset by — the style
    // decides how far its surround stands off what it surrounds — so the fit
    // is computed against the width the frame leaves, not the raw column.
    readonly property real inset: frame.leftPadding + frame.rightPadding
    readonly property real vinset: frame.topPadding + frame.bottomPadding
    readonly property real scaleFit:
        Math.min(1, (maxWidth - inset) / Math.max(1, natW),
                 maxH / Math.max(1, natH))
    readonly property real dispW: Math.max(1, Math.round(natW * scaleFit))
    readonly property real dispH: Math.max(1, Math.round(natH * scaleFit))

    width: Math.max(1, Math.round(maxWidth))
    height: dispH + vinset + (capStrip.visible ? capStrip.height + 4 : 0)
    visible: e !== null

    QQC.Frame {
        id: frame
        // Centred like the sibling's: a portrait picture is narrower than the
        // bubble and left-aligned it reads as a mistake.
        anchors.horizontalCenter: parent.horizontalCenter
        width: inl.dispW + inl.inset
        height: inl.dispH + inl.vinset

        contentItem: Item {
            Image {
                id: pic
                anchors.fill: parent
                sourceSize.width: Math.max(1, Math.round(inl.dispW))
                sourceSize.height: Math.max(1, Math.round(inl.dispH))
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                source: inl.e ? "file://" + inl.e.path : ""
            }
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

    // One elided line under the picture; the whole of it is in the Lightbox.
    CaptionStrip {
        id: capStrip
        y: inl.dispH + inl.vinset + 4
        width: inl.width
        caption: inl.e ? (inl.e.alt || "") : ""
        meta: inl.e ? (inl.e.meta || "") : ""
    }

    // A file that saved but will not decode — say so, never a blank.
    QQC.Label {
        y: inl.dispH + inl.vinset + 4
        width: inl.width
        wrapMode: Text.Wrap
        visible: pic.status === Image.Error
        text: "image: could not display"
        color: Theme.crit
    }
}
