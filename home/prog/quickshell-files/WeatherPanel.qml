import QtQuick
import Quickshell
import Quickshell.Wayland

// 7-day redacted-city forecast that slides out when hovering the panel's weather
// block — same choreography as Calendar/AnalogClock. One row per day:
// day, condition, high/low, precip (inches + max probability).
PanelWindow {
    id: root

    property bool open: false

    visible: open || card.x < card.hidden - 1
    color: "transparent"

    anchors { bottom: true; right: true }
    margins { bottom: Theme.gap * 16; right: Theme.gap }
    implicitWidth: 252
    implicitHeight: 8 * 20 + 40
    exclusiveZone: 0

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "qs-weather"

    function wxHover(h) {
        if (h) show();
        else closeTimer.restart();
    }
    function show() {
        closeTimer.stop();
        open = true;
    }
    Timer {
        id: closeTimer
        interval: 350
        onTriggered: root.open = false
    }

    Rectangle {
        id: card
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: parent.width

        readonly property real shown: 0
        readonly property real hidden: width + Theme.gap
        x: root.open ? shown : hidden
        Behavior on x { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

        color: Theme.bg
        border.color: Theme.windowBorder
        border.width: Theme.windowBorderWidth
        radius: Theme.windowRounding

        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.NoButton
            onEntered: root.show()
            onExited: closeTimer.restart()
        }

        Column {
            anchors { top: parent.top; horizontalCenter: parent.horizontalCenter; topMargin: 10 }
            spacing: 4

            PixelText {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "redacted-city"
                color: Theme.accent
            }

            Repeater {
                model: Weather.days
                Row {
                    required property var modelData
                    spacing: 0
                    PixelText { width: 44; text: parent.modelData.name;  color: Theme.textDim }
                    PixelText { width: 56; text: parent.modelData.cond;  color: Theme.info }
                    PixelText { width: 74; text: parent.modelData.hi + "/" + parent.modelData.lo; color: Theme.text }
                    PixelText {
                        width: 60
                        // precip: inches when meaningful, plus max chance
                        text: (parent.modelData.precip >= 0.05 ? parent.modelData.precip.toFixed(1) + "\"" : "-")
                              + (parent.modelData.prob >= 0 ? " " + parent.modelData.prob + "%" : "")
                        color: parent.modelData.precip >= 0.05 ? Theme.info : Theme.textDim
                    }
                }
            }

            PixelText {
                visible: Weather.days.length === 0
                anchors.horizontalCenter: parent.horizontalCenter
                text: "no data yet"
                color: Theme.textDim
            }
        }
    }
}
