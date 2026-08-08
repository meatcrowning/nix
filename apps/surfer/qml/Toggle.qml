import QtQuick
import "../../qmlcommon"

// The desktop's on/off switch — the settings program's SetToggle, wearing no
// on/off ghost text ([his, 2026-08-08] "on off toggles should not have the on
// off text on them", systemwide): a hard-edged track whose block snaps left
// (off) / right (on); the knob's side, the fill and the accent carry the
// state. `checked` is controlled — a click emits toggled(newValue) and the
// caller's binding flows the new state back.
Rectangle {
    id: root
    property bool checked: false
    property bool enabled: true      // greyed and inert (0.4, the disabled opacity)
    property bool winActive: true    // unfocused window: chrome drops to Theme.inactive
    signal toggled(bool value)

    width: 44
    height: 20
    radius: Theme.rounding
    opacity: enabled ? 1.0 : 0.4
    color: checked ? Theme.bgAlt : "transparent"
    border.width: Theme.ctrlBorder
    border.color: !winActive ? Theme.inactive
                 : (checked || ma.containsMouse) ? Theme.accent : Theme.border

    Rectangle {
        width: 8
        height: parent.height - 6
        radius: 0
        anchors.verticalCenter: parent.verticalCenter
        x: root.checked ? parent.width - width - 3 : 3
        color: !root.winActive ? Theme.inactive
             : root.checked ? Theme.accent : Theme.dim
        // 90ms, not the desktop's 260: direct feedback on a press stays with
        // the pointer (§6.4) — at 260 the switch lags the click that threw it.
        Behavior on x { NumberAnimation { duration: motion.ms(90); easing.type: motion.slideEasing } }
    }

    Motion { id: motion }

    MouseArea {
        id: ma
        anchors.fill: parent
        enabled: root.enabled
        hoverEnabled: root.enabled
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggled(!root.checked)
    }
}
