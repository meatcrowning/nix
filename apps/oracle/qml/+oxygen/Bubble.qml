import QtQuick
import QtQuick.Shapes

// One message's frame under Oxygen. Unlike the generic Plasma KStyle Button,
// this is one continuous Shape: its lower outer corner becomes the speech curl
// itself [his, 2026-09-05]. A Button plus an attached piece always exposes the
// rectangular bottom bevel and therefore can never read as one bubble.
//
// `isError` changes that same uninterrupted outline to the scheme's negative
// foreground. There is no second error frame and no separate tail material.
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
    // Root.qml reserves the curl's height below the message contents.
    readonly property real tailHeight: 9
    readonly property real tailWidth: 11
    default property alias content: holder.data

    Item {
        id: frame
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: Math.max(0, parent.height - root.tailHeight)
    }

    // ONE silhouette: the lower outer corner itself continues into the curl.
    // A separate native Button plus a tail cannot do this — Oxygen paints the
    // button's complete rectangular bevel before QML can add anything, leaving
    // either its bottom rule or a mismatched patch across the join.
    Shape {
        anchors.fill: parent
        visible: !root.user
        ShapePath {
            strokeWidth: 1
            strokeColor: root.isError ? Theme.crit : Theme.border
            fillGradient: LinearGradient {
                x1: 0; y1: 0; x2: 0; y2: root.height
                GradientStop { position: 0; color: Qt.lighter(Theme.bgAlt, 1.16) }
                GradientStop { position: 1; color: Theme.bgAlt }
            }
            startX: 3; startY: 0
            PathLine { x: root.width - 3; y: 0 }
            PathQuad { x: root.width; y: 3; controlX: root.width; controlY: 0 }
            PathLine { x: root.width; y: frame.height - 3 }
            PathQuad {
                x: root.width - 3; y: frame.height
                controlX: root.width; controlY: frame.height
            }
            PathLine { x: root.tailWidth; y: frame.height }
            PathCubic {
                x: 0; y: frame.height + root.tailHeight
                control1X: 8; control1Y: frame.height + root.tailHeight - 2
                control2X: 3; control2Y: frame.height + root.tailHeight
            }
            PathLine { x: 0; y: 3 }
            PathQuad { x: 3; y: 0; controlX: 0; controlY: 0 }
        }
    }

    Shape {
        anchors.fill: parent
        visible: root.user
        ShapePath {
            strokeWidth: 1
            strokeColor: root.isError ? Theme.crit : Theme.accent
            fillGradient: LinearGradient {
                x1: 0; y1: 0; x2: 0; y2: root.height
                GradientStop { position: 0; color: Qt.lighter(Theme.bgAlt, 1.16) }
                GradientStop { position: 1; color: Theme.bgAlt }
            }
            startX: 3; startY: 0
            PathLine { x: root.width - 3; y: 0 }
            PathQuad { x: root.width; y: 3; controlX: root.width; controlY: 0 }
            PathLine { x: root.width; y: frame.height + root.tailHeight }
            PathCubic {
                x: root.width - root.tailWidth; y: frame.height
                control1X: root.width - 3; control1Y: frame.height + root.tailHeight
                control2X: root.width - 8; control2Y: frame.height + root.tailHeight - 2
            }
            PathLine { x: 3; y: frame.height }
            PathQuad { x: 0; y: frame.height - 3; controlX: 0; controlY: frame.height }
            PathLine { x: 0; y: 3 }
            PathQuad { x: 3; y: 0; controlX: 0; controlY: 0 }
        }
    }

    Item {
        id: holder
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: frame.height
    }
}
