import QtQuick
import Quickshell
import Quickshell.Wayland

// The toast stack, tucked into the bottom-right corner just inside the bar. The
// bar reserves its own exclusive zone, so anchoring right lands us flush against
// the bar's inner edge automatically — no hard-coded barWidth offset needed.
// Overlay layer, no keyboard focus (never steals focus, like the OSD/launcher).
PanelWindow {
    id: win

    // Which corner the toast stack lives in, decoded from notifCorner
    // ("bottom-right" | "bottom-left" | "top-right" | "top-left").
    readonly property bool _top: SettingsStore.d.notifCorner.indexOf("top") === 0
    readonly property bool _left: SettingsStore.d.notifCorner.indexOf("left") >= 0

    anchors { top: win._top; bottom: !win._top; left: win._left; right: !win._left }
    margins { top: Theme.gap; bottom: Theme.gap; left: Theme.gap; right: Theme.gap }

    implicitWidth: SettingsStore.d.notifWidth
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
        // stack from the anchored corner's vertical edge (top corners grow down,
        // bottom corners grow up)
        anchors {
            left: parent.left; right: parent.right
            top: win._top ? parent.top : undefined
            bottom: win._top ? undefined : parent.bottom
        }
        spacing: Theme.gap

        // slide new toasts in from the bar-facing (outer) edge; ease the stack
        // when one leaves
        add: Transition {
            NumberAnimation { properties: "x"; from: win._left ? -48 : 48
                              duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing }
        }
        move: Transition {
            NumberAnimation { properties: "y"
                              duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing }
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
