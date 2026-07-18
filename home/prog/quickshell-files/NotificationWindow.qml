import QtQuick
import Quickshell
import Quickshell.Wayland

// The toast stack, tucked into the bottom-right corner just inside the bar. The
// bar reserves its own exclusive zone, so anchoring right lands us flush against
// the bar's inner edge automatically — no hard-coded barWidth offset needed.
// Overlay layer, no keyboard focus (never steals focus, like the OSD/launcher).
PanelWindow {
    id: win

    anchors { bottom: true; right: true }
    margins { bottom: Theme.gap; right: Theme.gap }

    implicitWidth: 300
    implicitHeight: Math.max(1, col.implicitHeight)
    color: "transparent"
    exclusiveZone: 0

    // Stay unmapped while empty so the transparent surface can't eat stray
    // clicks in the corner.
    visible: Notifications.count > 0

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "qs-notifications"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    Column {
        id: col
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        spacing: Theme.gap

        // slide new toasts in from the right; ease the stack when one leaves
        add: Transition {
            NumberAnimation { properties: "x"; from: 48; duration: 180; easing.type: Easing.OutCubic }
        }
        move: Transition {
            NumberAnimation { properties: "y"; duration: 180; easing.type: Easing.OutCubic }
        }

        Repeater {
            model: Notifications.model
            delegate: NotificationCard {
                required property var modelData
                width: col.width
                notif: modelData
            }
        }
    }
}
