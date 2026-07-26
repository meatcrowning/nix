import QtQuick

// A centered confirm dialog. `danger` gives the red/"destructive" treatment
// (permanent delete, overwrite); leave it off for a neutral confirm. Emits
// confirmed() on OK and dismissed() on cancel / click-outside.
Item {
    id: root
    anchors.fill: parent
    visible: false
    property string text: ""
    property string confirmLabel: "ok"
    property bool danger: false
    signal confirmed()
    signal dismissed()

    function open() { visible = true; }
    function close() { visible = false; }
    function cancel() { root.dismissed(); close(); }

    MouseArea { anchors.fill: parent; onClicked: root.cancel() }
    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.5) }

    Rectangle {
        anchors.centerIn: parent
        width: 320
        height: box.implicitHeight + 24
        color: Theme.bg
        border.color: root.danger ? Theme.crit : Theme.windowBorder
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
                color: root.danger ? Theme.crit : Theme.text
            }
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 8
                BrowserButton { label: "cancel"; onClicked: root.cancel() }
                BrowserButton { label: root.confirmLabel; danger: root.danger; onClicked: { root.confirmed(); root.close(); } }
            }
        }
    }
}
