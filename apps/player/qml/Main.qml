import QtQuick
import QtQuick.Window
import QtQuick.Controls as Controls
import QtQuick.Layouts

// Hyprland uses a plain frame; Unity adds view and playback bars below.
// Both wrap `Root.qml`, which is the
// whole app. In a Plasma session this file is never loaded — main.py puts the
// same `Root.qml` inside a QMainWindow instead (`pylib/kdeshell.py`), so the
// window, its chrome and its background come from the KDE style rather than
// from here.
Window {
    id: win
    visible: true
    width: 1080
    height: 720
    // air's screen is a fraction of top's — let the window shrink well past
    // top's floor there (the layouts already flow; the now-playing cover has
    // its own air-side cap so it stays proportionate).
    minimumWidth: OnAir ? 320 : 480
    minimumHeight: OnAir ? 240 : 320
    title: content.windowTitle
    color: Theme.bg

    onClosing: Qt.quit()

    Root {
        id: content
        anchors { left: parent.left; right: parent.right; top: viewBar.bottom; bottom: playBar.top }
    }

    Controls.ToolBar {
        id: viewBar
        objectName: "standaloneViewBar"
        anchors { left: parent.left; right: parent.right; top: parent.top }
        visible: StandaloneControls && !content.visualFullscreen
        height: visible ? implicitHeight : 0
        Flow {
            width: parent.width
            Repeater {
                model: content.tbButtons.filter(function(b) { return b.bar === true || b.id === "settings"; })
                Controls.ToolButton {
                    required property var modelData
                    text: modelData.menuText || modelData.tip
                    enabled: modelData.state !== 2
                    highlighted: modelData.state === 1
                    onClicked: content.tbAction(modelData.id)
                }
            }
        }
    }

    Controls.ToolBar {
        id: playBar
        objectName: "standalonePlayBar"
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        visible: StandaloneControls && !content.visualFullscreen
        height: visible ? implicitHeight : 0
        ColumnLayout {
            width: parent.width
            spacing: 0
            Flow {
                Layout.fillWidth: true
                Repeater {
                    model: content.tbButtons.filter(function(b) { return b.bar === "transport"; })
                    Controls.ToolButton {
                        required property var modelData
                        text: modelData.menuText || modelData.tip
                        enabled: modelData.state !== 2
                        highlighted: modelData.state === 1
                        onClicked: content.tbAction(modelData.id)
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Controls.Label { text: content.fmtTime(Player.position) }
                Controls.Slider {
                    id: seek
                    Layout.fillWidth: true
                    from: 0
                    to: 1
                    enabled: Player.duration > 0 && Player.index >= 0
                    onMoved: Player.seekFrac(value)
                    Binding {
                        target: seek
                        property: "value"
                        value: Player.duration > 0 ? Player.position / Player.duration : 0
                        when: !seek.pressed
                    }
                }
                Controls.Label { text: content.fmtTime(Player.duration) }
            }
        }
    }
}
