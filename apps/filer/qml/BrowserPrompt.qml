import QtQuick

// A centered text-input prompt overlaid on the browser (new folder / rename).
Item {
    id: root
    anchors.fill: parent
    visible: false
    property string title: ""
    property string value: ""
    signal accepted(string text)

    function open() { field.text = value; visible = true; field.forceActiveFocus(); field.selectAll(); }
    function close() { visible = false; }

    // dim + click-outside to cancel
    MouseArea { anchors.fill: parent; onClicked: root.close() }
    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.5) }

    Rectangle {
        anchors.centerIn: parent
        width: 320
        height: box.implicitHeight + 24
        color: Theme.bg
        border.color: Theme.windowBorder
        border.width: Theme.windowBorderWidth
        MouseArea { anchors.fill: parent } // swallow clicks

        Column {
            id: box
            anchors { top: parent.top; left: parent.left; right: parent.right; margins: 12 }
            spacing: 8

            PixelText { text: root.title; color: Theme.accent }

            Rectangle {
                width: parent.width
                height: 24
                color: Theme.bgAlt
                border.color: Theme.accent
                border.width: 1
                TextInput {
                    id: field
                    anchors { fill: parent; margins: 4 }
                    verticalAlignment: TextInput.AlignVCenter
                    color: Theme.text
                    font.family: Theme.font
                    font.pixelSize: Theme.fontSize
                    renderType: Text.NativeRendering
                    clip: true
                    onAccepted: { root.accepted(text); root.close(); }
                    Keys.onEscapePressed: root.close()
                }
            }

            Row {
                anchors.right: parent.right
                spacing: 6
                BrowserButton { label: "cancel"; onClicked: root.close() }
                BrowserButton { label: "ok"; onClicked: { root.accepted(field.text); root.close(); } }
            }
        }
    }
}
