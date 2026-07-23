import QtQuick
import Quickshell
import Quickshell.Wayland

// The "recording..." toast that slides out from the top-right while a screen
// recording is in progress (driven by Screenshot.qml's `recording` flag, wired
// in shell.qml). It holds only the pulsing text; clicking anywhere on it stops
// the recording. Kept a separate top-level window from the screenshot overlay
// so it survives that overlay closing (the overlay must not be in the shot).
PanelWindow {
    id: root

    property bool recording: false
    signal stopRequested()

    // Stay mapped through the slide-back-in, then hide once fully off-screen —
    // same lifecycle idiom as WallpaperPicker/Launcher.
    visible: recording || card.x < card.hidden - 1
    color: "transparent"

    anchors { top: true; right: true }
    margins { top: Theme.gap; right: Theme.gap }
    implicitWidth: 180
    implicitHeight: 44
    exclusiveZone: 0

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "qs-recording"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    Rectangle {
        id: card
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: parent.width

        // Slide in from just past the right edge of our own window.
        readonly property real shown: 0
        readonly property real hidden: width + Theme.gap
        x: root.recording ? shown : hidden
        Behavior on x { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

        color: Theme.bg
        border.color: Theme.windowBorder
        border.width: Theme.windowBorderWidth
        radius: Theme.windowRounding

        PixelText {
            id: label
            anchors.centerIn: parent
            text: "recording..."
            color: Theme.text

            // Fade the text in and out for as long as we're recording.
            SequentialAnimation on opacity {
                running: root.recording
                loops: Animation.Infinite
                NumberAnimation { from: 1.0; to: 0.25; duration: 900; easing.type: Easing.InOutSine }
                NumberAnimation { from: 0.25; to: 1.0; duration: 900; easing.type: Easing.InOutSine }
            }
        }

        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: root.stopRequested()
        }
    }
}
