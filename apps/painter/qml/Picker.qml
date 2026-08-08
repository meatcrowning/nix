import QtQuick
import "../../qmlcommon"

// A dropdown.  Options always come from the backend's /object_info rather than a
// hardcoded list, so a ComfyUI update that adds a sampler shows it here with no
// change on this side.
//
// The BOX is here; the LIST is `pickerOverlay` at the top of the scene (see
// PickerOverlay.qml). A popup parented here could never rise above what follows
// it in the left column — `z` orders siblings, not strangers — and the column's
// Flickable clipped it outright.
Item {
    id: picker
    property var options: []
    property string value: ""
    property int visibleRows: 12
    // Whose list is open: the overlay holds one callback, and ours is a stable
    // function reference, so this is an identity test rather than bookkeeping
    // two components have to keep in step.
    readonly property bool open: pickerOverlay.visible && pickerOverlay.onPicked === picker.accept
    signal picked(string value)

    // Report the pick; do NOT write `value`. It is bound to the model
    // (`root.gen.sampler_name`, a row's `family`, …) and assigning a bound
    // property destroys the binding — after one pick the box would stop
    // following the model, so a family's defaults or a reused image could never
    // move it again. Same rule as Spin.commit().
    function accept(v) {
        picker.picked(v)
    }

    width: 160
    height: 20

    Rectangle {
        id: box
        anchors.fill: parent
        color: Theme.bg
        radius: Theme.rounding
        border.color: picker.open ? Theme.accent : Theme.border
        border.width: Theme.ctrlBorder

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
            id: boxMa
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                if (picker.open) {
                    pickerOverlay.close()
                } else {
                    pickerOverlay.visibleRows = picker.visibleRows
                    pickerOverlay.openFor(box, picker.options, picker.value, picker.accept)
                }
            }
        }
    }
}
