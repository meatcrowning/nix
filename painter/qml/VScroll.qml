import QtQuick
import QtQuick.Controls.Basic

// Slim vertical scrollbar, copied from filer's VScroll so all the siblings
// scroll the same way: only visible when the view overflows (size < 1) — the
// handle stays put at rest, brightening on hover/drag; accent while pressed.
ScrollBar {
    id: vb
    policy: ScrollBar.AsNeeded
    width: 9
    contentItem: Rectangle {
        implicitWidth: 9
        color: vb.pressed ? Theme.accent : Theme.textDim
        opacity: vb.size < 1 ? (vb.active ? 0.9 : 0.5) : 0
        Behavior on opacity { NumberAnimation { duration: 120 } }
    }
    background: Rectangle {
        color: Theme.bgAlt
        opacity: vb.size < 1 && vb.active ? 0.4 : 0
        Behavior on opacity { NumberAnimation { duration: 120 } }
    }
}
