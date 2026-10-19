import QtQuick
import QtQuick.Controls
import "../../qmlcommon"

Rectangle {
    id: panel
    property var params: null
    property string path: ""
    color: Theme.bg
    border.color: Theme.border
    clip: true
    objectName: "parameterCompare"
    function refresh() { App.mountComparison(content, visible ? params : null) }
    onParamsChanged: refresh()
    onVisibleChanged: refresh()
    Component.onCompleted: refresh()
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.AllButtons
        onWheel: wheel => wheel.accepted = true
    }
    Label {
        id: note
        x: 10; y: 6; width: parent.width - 20
        text: panel.params ? "Saved output settings. Unrecorded fields use model defaults; edits here are temporary."
                           : "Select an output with saved settings to compare."
        wrapMode: Text.Wrap
    }
    Item {
        id: content
        anchors { left: parent.left; right: parent.right; top: note.bottom; bottom: parent.bottom; topMargin: 6 }
    }
}
