import QtQuick
import Chatter 1.0

// One message's frame under Oxygen: OxygenBubblePaint asks the active QStyle to
// paint a button, clips that paint to one continuous speech-bubble silhouette,
// then outlines that same path [his, 2026-09-05]. The body and curl are one
// native-painted surface, not a Button with a second QML ornament under it.
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
    readonly property real tailHeight: 13
    readonly property real tailWidth: 15
    default property alias content: holder.data

    Item {
        id: frame
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: Math.max(0, parent.height - root.tailHeight)
    }

    OxygenBubblePaint {
        anchors.fill: parent
        user: root.user
        error: root.isError
        bodyHeight: frame.height
        outlineColor: root.isError ? Theme.crit
                      : (root.user ? Theme.accent : Theme.border)
    }

    Item {
        id: holder
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: frame.height
    }
}
