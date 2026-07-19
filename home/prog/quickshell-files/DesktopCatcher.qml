import QtQuick
import Quickshell
import Quickshell.Wayland

// Fullscreen transparent surface on the BOTTOM layer: a click that reaches
// it hit bare desktop (no window above), and unfocuses every window via the
// hyprvtb lua helper. Sits above the wallpaper, below all windows —
// including the scratchpad terminal.
PanelWindow {
    id: root
    required property var modelData
    screen: modelData

    anchors { top: true; bottom: true; left: true; right: true }
    exclusiveZone: -1
    color: "transparent"

    WlrLayershell.layer: WlrLayer.Bottom
    WlrLayershell.namespace: "qs-desktop-catcher"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    MouseArea {
        anchors.fill: parent
        onClicked: Quickshell.execDetached(["hyprctl", "eval", "hl.plugin.hyprvtb.unfocus_all()"])
    }
}
