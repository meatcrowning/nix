import QtQuick
import QtQuick.Controls

// Picker, in a Plasma session: a real ComboBox, with the style's own popup —
// so the dropdown is the desktop's menu, at the desktop's metrics, and the
// "parent it at the top of the scene or it gets clipped" problem ../Picker.qml
// solves by hand is the toolkit's problem here instead (a Controls popup is its
// own window).
//
// Same API — options, value, picked(value), and `open` for anything that dims
// while a list is showing. `value` is still never written from here: it is bound
// to the model and assigning it would destroy the binding (../Picker.qml's
// accept() carries the full reasoning).
Item {
    id: picker
    property string face: "plasma"
    property var options: []
    property string value: ""
    property int visibleRows: 12
    readonly property bool open: box.popup.visible
    signal picked(string value)

    function accept(v) { picker.picked(v) }

    width: 160
    implicitHeight: box.implicitHeight
    height: implicitHeight

    ComboBox {
        id: box
        anchors.fill: parent
        model: picker.options
        currentIndex: {
            var opts = picker.options || []
            for (var i = 0; i < opts.length; i++)
                if (String(opts[i]) === String(picker.value)) return i
            return -1
        }
        displayText: picker.value
        onActivated: (i) => picker.accept(String(picker.options[i]))
    }
}
