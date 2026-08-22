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

    // Pinnable like a Field row is (see ../Field.qml).
    // THE PANEL THIS ROW IS IN, found by walking up rather than by the id
    // `panel` alone: `ParamsPanel.qml` had no such id and every row in the
    // sampling section was quietly unpinnable for it. The id is still the fast
    // path; this is the one that cannot be forgotten.
    function pinHost() {
        if (typeof panel !== "undefined" && panel && panel.pinMenu) return panel
        var p = root.parent
        for (var i = 0; i < 8 && p; i++) {
            if (p.pinMenu !== undefined) return p
            p = p.parent
        }
        return null
    }

    property string pinLabel: root.label
    readonly property string pinValue: root.checked ? "on" : "off"

    implicitWidth: box.implicitWidth
    implicitHeight: box.implicitHeight
    height: implicitHeight

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        onClicked: function (m) {
            var host = root.pinHost()
            if (!host) return
            var pt = mapToItem(null, m.x, m.y)
            host.pinMenu(root, pt.x, pt.y)
        }
    }

    CheckBox {
        id: box
        anchors.verticalCenter: parent.verticalCenter
        text: root.label
        checked: root.checked
        onToggled: root.toggled(checked)
    }
}
