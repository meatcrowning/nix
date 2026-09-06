import QtQuick
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
    default property alias content: holder.data

    QQC.Button {
        id: frame
        anchors.fill: parent
        enabled: false
        text: ""
        background.opacity: 1.0
        contentItem: Item {}
    }

    // Drawn only when it is true, so a normal bubble is exactly the sibling's.
    Rectangle {
        anchors.fill: parent
        visible: root.isError
        color: "transparent"
        border.width: 1
        border.color: Theme.crit
        radius: 2
    }

    Item { id: holder; anchors.fill: parent }
}
