import QtQuick

// A hard-edged on/off switch matching the panel's square aesthetic: a track
// with a block that snaps left (off) / right (on). `checked` is two-way; on a
// click it flips and emits toggled(newValue) so the caller can persist.
Rectangle {
    id: root
    property bool checked: false
    // Greyed out and inert when a sibling setting makes this one meaningless
    // (e.g. "pure black background" under light mode). 0.4 is the design
    // language's disabled opacity; the row's desc says WHY, per §10.
    property bool enabled: true
    signal toggled(bool value)

    width: 44
    height: 20
    radius: 0
    opacity: enabled ? 1.0 : 0.4
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
        // 90ms, deliberately NOT the desktop's 260. This is a ~14px knob inside
        // a control the user just clicked — direct feedback on a press, which
        // §6.4 says belongs with the pointer, not a reveal sliding out of an
        // edge. At 260 the switch lags the click that threw it. The curve and
        // the motion settings are still the desktop's.
        Behavior on x { NumberAnimation { duration: ViewMode.ms(90); easing.type: ViewMode.slideEasing } }
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        enabled: root.enabled
        hoverEnabled: root.enabled
        cursorShape: Qt.PointingHandCursor
        // Controlled: don't flip our own state — emit intent and let the
        // caller's binding (checked: Store.d.key) flow the new value back, so
        // revert/restore-defaults refresh the switch too.
        onClicked: root.toggled(!root.checked)
    }
}
