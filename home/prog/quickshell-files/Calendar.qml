import QtQuick
import Quickshell

// Month calendar popup (SlidePopup: bottom-right, exclusive, hover-kept).
// Opened by the date band of the bar's lower hover strip; today's cell gets
// the active treatment (bgAlt fill + accent border).
SlidePopup {
    id: root

    popupNamespace: "qs-calendar"
    implicitWidth: 7 * 26 + 24
    // fit the content exactly (month is 5 or 6 rows) — no empty tail
    implicitHeight: content.implicitHeight + 20

    onOpened: refresh()

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

    Column {
        id: content
        anchors { top: parent.top; horizontalCenter: parent.horizontalCenter; topMargin: 10 }
        spacing: 8

        PixelText {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.title
            color: Theme.accent
        }

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
