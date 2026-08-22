import QtQuick
import QtQuick.Controls

// Toggle, in a Plasma session: a real CheckBox, drawn by the desktop's KStyle
// through qqc2-desktop-style — Oxygen's own check mark, hover glow and focus
// ring, not an imitation of them. Same API as ../Toggle.qml (checked, label,
// toggled), so no call site changes; the file selector picks between the two
// (main.py -> kdeshell.select_plasma_files).
Item {
    id: root
    property string face: "plasma"   // probed by tools/plasma-face-test.py
    property bool checked: false
    property string label: ""
    signal toggled(bool value)

    implicitWidth: box.implicitWidth
    implicitHeight: box.implicitHeight
    height: implicitHeight

    CheckBox {
        id: box
        anchors.verticalCenter: parent.verticalCenter
        text: root.label
        checked: root.checked
        onToggled: root.toggled(checked)
    }
}
