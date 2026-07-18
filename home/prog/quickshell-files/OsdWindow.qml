import QtQuick
import Quickshell
import Quickshell.Wayland

// A transient OSD for volume / brightness. It is a short VERTICAL bar that
// slides out horizontally from behind the panel (like the runner and the
// cheatsheet), docked near the bottom of the bar. A vertical fill bar inside
// shows the current level; it slides back off the right edge when it auto-hides.
// One per screen; all observe the shared Osd singleton. Instantiated via
// Variants in shell.qml.
PanelWindow {
    id: w
    required property var modelData
    screen: modelData

    // Stay mapped through the slide-out, then hide once the card has travelled
    // back off the right edge (matching the runner / cheatsheet).
    visible: Osd.active || card.x < card.hidden - 1

    // Dock to the bottom-right, just left of the bar, so it reads as pulling out
    // from behind the panel near its bottom.
    anchors { right: true; bottom: true }
    margins.right: Theme.gap
    margins.bottom: Theme.gap

    // The window is only as wide as the card; the card slides across that width.
    implicitWidth: 40
    implicitHeight: 184
    color: "transparent"
    exclusiveZone: 0

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "qs-osd"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    Rectangle {
        id: card
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: parent.width

        // Slide in horizontally from the right edge — out from behind the bar.
        // Open: flush against the window's right edge. Closed: fully off the right.
        readonly property real shown: 0
        readonly property real hidden: width
        x: Osd.active ? shown : hidden
        Behavior on x { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

        radius: 0
        color: Theme.bgAlt
        border.color: Theme.accent
        border.width: 2

        readonly property color tint: Osd.kind === "brightness" ? Theme.warn
                                    : Osd.muted ? Theme.crit : Theme.info
        // 0..1 fill fraction; a muted sink reads as empty.
        readonly property real level: (Osd.kind === "volume" && Osd.muted)
                                    ? 0 : Math.max(0, Math.min(100, Osd.value)) / 100

        // kind label at the top
        PixelText {
            id: kindLabel
            anchors.top: parent.top
            anchors.topMargin: 6
            anchors.horizontalCenter: parent.horizontalCenter
            text: Osd.kind === "brightness" ? "bri" : "vol"
            color: card.tint
        }

        // value at the bottom ("x" when muted)
        PixelText {
            id: valLabel
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 6
            anchors.horizontalCenter: parent.horizontalCenter
            text: (Osd.kind === "volume" && Osd.muted) ? "x" : Osd.value
            color: Theme.text
        }

        // vertical level bar between the two labels — fills from the bottom up
        Rectangle {
            id: track
            anchors.top: kindLabel.bottom
            anchors.bottom: valLabel.top
            anchors.topMargin: 6
            anchors.bottomMargin: 6
            anchors.horizontalCenter: parent.horizontalCenter
            width: 12
            radius: 0
            color: Theme.highlight
            border.color: Theme.border
            border.width: 1

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: 2
                height: Math.max(0, (track.height - 4) * card.level)
                radius: 0
                color: card.tint
                Behavior on height { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
            }
        }
    }
}
