import QtQuick
import "../../qmlcommon"

// A dropdown.  Options always come from the backend's /object_info rather than a
// hardcoded list, so a ComfyUI update that adds a sampler shows it here with no
// change on this side.
Item {
    id: picker
    property var options: []
    property string value: ""
    property int visibleRows: 12
    signal picked(string value)

    width: 160
    height: 20

    Rectangle {
        id: box
        anchors.fill: parent
        color: Theme.bg
        border.color: pop.visible ? Theme.accent : Theme.border
        border.width: 1
        radius: 1

        PixelText {
            anchors.verticalCenter: parent.verticalCenter
            x: 5
            width: parent.width - 20
            elide: Text.ElideRight
            text: picker.value
            color: Theme.text
        }
        PixelText {
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right
            anchors.rightMargin: 5
            text: "v"
            color: Theme.dim
        }
        MouseArea {
            anchors.fill: parent
            onClicked: pop.visible = !pop.visible
        }
    }

    Rectangle {
        id: pop
        visible: false
        z: 100
        width: Math.max(parent.width, 180)
        height: Math.min(picker.visibleRows, list.count) * 19 + 2
        anchors.top: box.bottom
        anchors.topMargin: 1
        color: Theme.bgAlt
        border.color: Theme.accent
        border.width: 1

        KineticListView {
            id: list
            anchors.fill: parent
            anchors.margins: 1
            model: picker.options
            clip: true
            currentIndex: picker.options.indexOf(picker.value)
            delegate: Rectangle {
                width: list.width
                height: 19
                color: hover.containsMouse ? Theme.highlight
                     : (modelData === picker.value ? Theme.highlight : "transparent")
                PixelText {
                    anchors.verticalCenter: parent.verticalCenter
                    x: 5
                    width: parent.width - 10
                    elide: Text.ElideRight
                    text: modelData
                    color: modelData === picker.value ? Theme.accent : Theme.text
                }
                MouseArea {
                    id: hover
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: {
                        picker.value = modelData
                        picker.picked(modelData)
                        pop.visible = false
                    }
                }
            }
        }
    }

    // Click anywhere else to dismiss.
    MouseArea {
        parent: picker.Window.contentItem
        anchors.fill: parent
        z: 99
        visible: pop.visible
        onClicked: pop.visible = false
    }
}
