import QtQuick

// A hard-edged on/off switch matching the panel's square aesthetic: a track
// with a block that snaps left (off) / right (on). `checked` is two-way; on a
// click it flips and emits toggled(newValue) so the caller can persist.
Rectangle {
    id: root
    property bool checked: false
    signal toggled(bool value)

    width: 44
    height: 20
    radius: 0
    color: checked ? Theme.bgAlt : "transparent"
    border.width: 1
    border.color: (checked || ma.containsMouse) ? Theme.accent : Theme.border

    // ON / OFF ghost label, so state reads even without colour
    PixelText {
        anchors {
            verticalCenter: parent.verticalCenter
            left: root.checked ? parent.left : undefined
            right: root.checked ? undefined : parent.right
            leftMargin: 5
            rightMargin: 5
        }
        text: root.checked ? "on" : "off"
        color: root.checked ? Theme.accent : Theme.textDim
    }

    Rectangle {
        width: 8
        height: parent.height - 6
        radius: 0
        anchors.verticalCenter: parent.verticalCenter
        x: root.checked ? parent.width - width - 3 : 3
        color: root.checked ? Theme.accent : Theme.dim
        Behavior on x { NumberAnimation { duration: 90; easing.type: Easing.OutCubic } }
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        // Controlled: don't flip our own state — emit intent and let the
        // caller's binding (checked: Store.d.key) flow the new value back, so
        // revert/restore-defaults refresh the switch too.
        onClicked: root.toggled(!root.checked)
    }
}
