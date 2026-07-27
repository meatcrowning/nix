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

    // Stay mapped through the slide-back-in, then unmap once it is fully
    // off-screen. An IMPERATIVE flag, not a test on the card's x: `visible`
    // gates layer-surface mapping, and the card's geometry depends on the
    // window being mapped, so deriving one from the other maps and unmaps the
    // surface for no reason. It did — Hyprland logged an openlayer/closelayer
    // pair for `qs-recording` on every reload, because the label's implicit
    // width lands a moment after construction and the slide Behavior then
    // animated x across the "still on screen" test with nobody recording.
    // Same idiom, and the same reason for it, as SlidePopup's `_visSurface`.
    property bool _vis: false
    visible: recording || _vis
    onRecordingChanged: {
        if (recording) { hideTimer.stop(); _vis = true; }
        else hideTimer.restart();
    }
    Timer {
        id: hideTimer
        interval: 260               // the slide-out, plus a frame
        onTriggered: if (!root.recording) root._vis = false
    }
    color: "transparent"

    anchors { top: true; right: true }
    margins { top: Theme.gap; right: Theme.gap }
    // Size to the text rather than a fixed slab — just enough padding around
    // "recording..." to breathe.
    implicitWidth: label.implicitWidth + 32
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
        //
        // NOT `width`, which is the WINDOW's mapped width — 0 while unmapped,
        // and `visible` above is derived from x, so reading it here closed the
        // loop visible -> width -> hidden -> x -> visible. Qt reported it as a
        // binding loop on this Rectangle's width on every single load, and
        // resolving it flickered the surface: Hyprland logged an
        // openlayer+closelayer pair for `qs-recording` on every reload, i.e. a
        // toast nobody had asked for was mapped and unmapped behind the scenes.
        // `root.implicitWidth` is a plain constant off the label, which is what
        // SlidePopup's card uses for exactly the same reason.
        readonly property real shown: 0
        readonly property real hidden: root.implicitWidth + Theme.gap
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
