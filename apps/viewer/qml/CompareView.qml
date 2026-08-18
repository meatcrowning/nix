import QtQuick
import "../../qmlcommon"

// Image-comparison slider (`viewer --compare <before> <after>`, driven by
// painter). Two images of the SAME dimensions — a model's input and its output
// — overlaid on top of each other, with a vertical reveal line that FOLLOWS THE
// MOUSE: `before` shows to the LEFT of the line, `after` to the RIGHT, and the
// line tracks the pointer's x exactly as it moves. No clicking.
//
// docs/DESIGN.md §6.4: anything under the cursor tracks it 1:1 — no smoothing,
// no lag, no jump on enter. The reveal line is a direct-manipulation track, so
// it has zero easing; the `before` image never rescales as the line moves, only
// its reveal changes.
Item {
    id: root

    property string beforePath: ""
    property string afterPath: ""
    property string beforeName: ""
    property string afterName: ""
    property bool winActive: true

    // Reveal-line x in this item's coordinates. Centred until the pointer first
    // enters (so a resize before any hover keeps it centred), then it follows
    // the cursor exactly. Kept as a pure binding — never an imperative write —
    // so `tracked` is the one thing the pointer flips and nothing else can
    // silently break the centring binding.
    property bool tracked: false
    property real trackX: 0
    readonly property real splitX: tracked ? trackX : width / 2

    readonly property real clampedX: Math.max(0, Math.min(width, splitX))
    readonly property color lineColor: winActive ? Theme.accent : Theme.inactive

    // The two decodes share one policy — capped, EXIF-auto-rotated, async — so a
    // before/after pair the same size lands letterboxed identically and lines up
    // pixel-for-pixel.
    component Frame : Image {
        fillMode: Image.PreserveAspectFit
        autoTransform: true
        sourceSize.width: 3840
        sourceSize.height: 3840
        asynchronous: true
        cache: false
        smooth: true
        mipmap: true
    }

    // AFTER fills the whole area.
    Frame {
        id: after
        anchors.fill: parent
        source: root.afterPath ? ("file://" + encodeURI(root.afterPath)) : ""
    }

    // BEFORE is the SAME image at the SAME full size and position, revealed only
    // to the left of the line by a clip box pinned at x:0. The image inside is
    // sized to the whole area (not the clip box), so clipping changes what shows
    // — never how big it is drawn — which is why the two halves stay aligned.
    Item {
        id: clipLeft
        x: 0
        y: 0
        width: root.clampedX
        height: root.height
        clip: true
        Frame {
            width: root.width
            height: root.height
            x: 0
            y: 0
            source: root.beforePath ? ("file://" + encodeURI(root.beforePath)) : ""
        }
    }

    // ---- corner labels ----
    // Which side is which, so a pair that looks alike is not a guessing game.
    // Dim, on a bg chip for legibility over a busy image; §5.4 — one line each.
    component Tag : Rectangle {
        property alias text: label.text
        width: label.implicitWidth + 2 * Theme.gap
        height: Theme.lineHeight + Theme.gap
        color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.7)
        border.width: Theme.ctrlBorder
        border.color: root.lineColor
        radius: Theme.rounding
        PixelText {
            id: label
            anchors.centerIn: parent
            color: root.winActive ? Theme.textDim : Theme.inactive
        }
    }
    Tag {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.margins: Theme.gap
        text: "before"
    }
    Tag {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: Theme.gap
        text: "after"
    }

    // ---- the reveal line ----
    Rectangle {
        x: root.clampedX - width / 2
        y: 0
        width: 2
        height: root.height
        color: root.lineColor
    }
    // A handle centred on the line so the reveal point is legible over any
    // image, and reads as the thing the pointer drives. The `<>` says it moves
    // horizontally (ASCII — the pixel font has both, docs/DESIGN.md §2.3).
    Rectangle {
        x: root.clampedX - width / 2
        anchors.verticalCenter: parent.verticalCenter
        width: handle.implicitWidth + 2 * Theme.gap
        height: Theme.lineHeight + Theme.gap
        color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.7)
        border.width: Theme.ctrlBorder
        border.color: root.lineColor
        radius: Theme.rounding
        PixelText {
            id: handle
            anchors.centerIn: parent
            text: "<>"
            color: root.lineColor
        }
    }

    // ---- pointer tracking ----
    // Hover only: no button is accepted, so nothing is clicked. positionChanged
    // fires on every pointer move while hoverEnabled, and the line is written
    // straight from it — §6.4, no easing, no quantizing.
    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
        cursorShape: Qt.SizeHorCursor
        onPositionChanged: (m) => {
            root.tracked = true;
            root.trackX = m.x;
        }
    }

    // can't-display card, if either half failed to decode
    PixelText {
        anchors.centerIn: parent
        horizontalAlignment: Text.AlignHCenter
        visible: after.status === Image.Error
        text: "can't display\n" + root.afterName
        color: root.winActive ? Theme.textDim : Theme.inactive
    }
}
