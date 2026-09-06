import QtQuick
import QtQuick.Shapes
import QtQuick.Controls as QQC

// One message's frame under Oxygen. The frame itself is `+plasma/Bubble.qml`'s,
// unchanged and for its reasons: a real `Button`'s background drawn by the
// KStyle, with the control `enabled: false` so it takes no hover, press or
// focus, and the message's own text above it at full colour.
//
// WHAT THIS FACE ADDS IS THE ERROR STATE. `isError` is declared by both other
// faces and honoured by neither in a Plasma session — a failed turn drew
// exactly like a successful one. Oxygen has no "error button" primitive, so
// this does the one thing that is an annotation rather than an imitation: a 1px
// rule in the scheme's own negative foreground around the style's frame.
//
// `Theme.crit` IS that colour here, and this is worth stating because it looks
// like the wallpaper palette and is not: `kdetheme.theme_source()` swaps the
// whole palette for one generated from `kdeglobals` whenever the session is
// Plasma, and `kdetheme.kde_palette()` maps crit/warn/ok onto
// Colors:View ForegroundNegative/Neutral/Positive. So this needs no
// `org.kde.kirigami` import to reach KColorScheme's Negative role — chatter is
// already wearing it.
//
// Same API as ../Bubble.qml: `user`, `isError`, and whatever is put inside it.
Item {
    id: root
    property string face: "oxygen"
    property bool user: false
    property bool isError: false
    // The native button retains its rectangular frame. This is the small
    // Oxygen-only speech-bubble curl below it; Root.qml reserves its height.
    readonly property real tailHeight: 9
    readonly property real tailWidth: 11
    default property alias content: holder.data

    QQC.Button {
        id: frame
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: Math.max(0, parent.height - root.tailHeight)
        enabled: false
        text: ""
        background.opacity: 1.0
        contentItem: Item {}
    }

    // Oxygen has no speech-bubble primitive. These outward curls overlap its
    // lower edge by one pixel: replies point left and user messages point
    // right. They must be ABOVE the native control — behind it their fill is
    // covered by the conversation surface and reads as a detached outline.
    // Use the control palette rather than Theme.bg: the native button is
    // lighter than Chatter's view background under Oxygen.
    Shape {
        anchors.fill: parent
        visible: !root.user
        z: 1
        ShapePath {
            strokeWidth: 1
            strokeColor: root.isError ? Theme.crit : frame.palette.mid
            fillColor: frame.palette.button
            startX: 0; startY: frame.height - 1
            PathLine { x: 0; y: frame.height + root.tailHeight }
            PathCubic {
                x: root.tailWidth; y: frame.height
                control1X: 3; control1Y: frame.height + root.tailHeight
                control2X: 8; control2Y: frame.height + root.tailHeight - 2
            }
            PathLine { x: 0; y: frame.height - 1 }
        }
    }

    Shape {
        anchors.fill: parent
        visible: root.user
        z: 1
        ShapePath {
            strokeWidth: 1
            strokeColor: root.isError ? Theme.crit : frame.palette.mid
            fillColor: frame.palette.button
            startX: root.width; startY: frame.height - 1
            PathLine { x: root.width; y: frame.height + root.tailHeight }
            PathCubic {
                x: root.width - root.tailWidth; y: frame.height
                control1X: root.width - 3; control1Y: frame.height + root.tailHeight
                control2X: root.width - 8; control2Y: frame.height + root.tailHeight - 2
            }
            PathLine { x: root.width; y: frame.height - 1 }
        }
    }

    // Drawn only when it is true, so a normal bubble is exactly the sibling's.
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: frame.height
        visible: root.isError
        color: "transparent"
        border.width: 1
        border.color: Theme.crit
        radius: 2
    }

    Item {
        id: holder
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: frame.height
    }
}
