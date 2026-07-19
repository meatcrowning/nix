import QtQuick

// A centered confirm dialog for destructive actions (permanent delete).
Item {
    id: root
    anchors.fill: parent
    visible: false
    property string text: ""
    signal confirmed()

    function open() { visible = true; }
    function close() { visible = false; }

    MouseArea { anchors.fill: parent; onClicked: root.close() }
    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.5) }

    Rectangle {
        anchors.centerIn: parent
        width: 320
        height: box.implicitHeight + 24
        color: Theme.bg
        border.color: Theme.crit
        border.width: Theme.windowBorderWidth
        MouseArea { anchors.fill: parent }

        Column {
            id: box
            anchors { top: parent.top; left: parent.left; right: parent.right; margins: 12 }
            spacing: 10

            PixelText {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                text: root.text
                color: Theme.crit
            }
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 8
                BrowserButton { label: "cancel"; onClicked: root.close() }
                BrowserButton { label: "delete"; danger: true; onClicked: { root.confirmed(); root.close(); } }
            }
        }
    }
}
