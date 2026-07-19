import QtQuick
import Quickshell
import Quickshell.Wayland

// Month calendar that slides out from the right edge, just above the panel's
// date — opened by hovering the DateDisplay (shell.qml wires the signal),
// stays while the cursor is over the date or the calendar itself, and slides
// back shortly after both are left. Today's cell gets the active treatment
// (bgAlt fill + accent border, same as the launcher/workspace styles).
PanelWindow {
    id: root

    property bool open: false

    // stay mapped through the slide-out, like Launcher/WallpaperPicker
    visible: open || card.x < card.hidden - 1
    color: "transparent"

    anchors { bottom: true; right: true }
    margins { bottom: Theme.gap; right: Theme.gap }
    implicitWidth: 7 * 26 + 24
    implicitHeight: header.implicitHeight + 6 * 20 + 56
    exclusiveZone: 0

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "qs-calendar"

    // hover choreography: the date hovering opens; leaving either the date
    // or this card starts a short grace timer so the cursor can travel
    // between them without the calendar snapping shut.
    function dateHover(h) {
        if (h) show();
        else closeTimer.restart();
    }
    function show() {
        closeTimer.stop();
        refresh();
        open = true;
    }
    Timer {
        id: closeTimer
        interval: 350
        onTriggered: root.open = false
    }

    property string title: ""
    property int today: 0
    property var cells: [] // flat 7xN day numbers, 0 = blank pad cell

    function refresh() {
        const now = new Date();
        today = now.getDate();
        title = Qt.formatDate(now, "MMMM yyyy").toLowerCase();
        const startDow = new Date(now.getFullYear(), now.getMonth(), 1).getDay(); // 0 = sunday
        const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
        let c = [];
        for (let i = 0; i < startDow; i++) c.push(0);
        for (let d = 1; d <= daysInMonth; d++) c.push(d);
        while (c.length % 7 !== 0) c.push(0);
        cells = c;
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

        // hover keep-alive; NoButton so it never eats clicks
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.NoButton
            onEntered: root.show()
            onExited: closeTimer.restart()
        }

        Column {
            anchors { top: parent.top; horizontalCenter: parent.horizontalCenter; topMargin: 10 }
            spacing: 8

            PixelText {
                id: header
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.title
                color: Theme.accent
            }

            // weekday row + day grid share the same 26px column rhythm
            Grid {
                columns: 7
                anchors.horizontalCenter: parent.horizontalCenter

                Repeater {
                    model: ["s", "m", "t", "w", "t", "f", "s"]
                    Item {
                        required property string modelData
                        width: 26
                        height: 18
                        PixelText {
                            anchors.centerIn: parent
                            text: parent.modelData
                            color: Theme.textDim
                        }
                    }
                }
            }

            Grid {
                columns: 7
                anchors.horizontalCenter: parent.horizontalCenter

                Repeater {
                    model: root.cells
                    Item {
                        required property int modelData
                        width: 26
                        height: 20

                        Rectangle {
                            visible: parent.modelData === root.today
                            anchors.centerIn: parent
                            width: 24
                            height: 18
                            color: Theme.bgAlt
                            border.width: 2
                            border.color: Theme.accent
                        }
                        PixelText {
                            visible: parent.modelData > 0
                            anchors.centerIn: parent
                            text: parent.modelData
                            color: parent.modelData === root.today ? Theme.accent : Theme.text
                        }
                    }
                }
            }
        }
    }
}
