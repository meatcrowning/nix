import QtQuick
import Quickshell
import Quickshell.Wayland

// Lets you switch workspaces by scrolling on bare desktop background —
// never over a window or a Quickshell component, both of which sit on
// layers above this one and always claim the wheel event first. Bottom
// layer, not Background, for the same reason as EdgeAccent: hyprpaper's own
// surface is Background and re-stacks on every wallpaper change.
//
// mainMod+scroll (hypr/hyprland.lua) does the same thing with a modifier,
// for when the pointer IS over a window; this is the unmodified,
// background-only version. Both go through WorkspaceNav.go() (same process,
// no IPC round trip needed here) so the dynamic-creation gating behaves
// identically either way. Flip the two branches below if the direction
// feels backwards (mouse vs. trackpad/"natural scrolling" can invert
// angleDelta.y).
PanelWindow {
    required property var modelData
    screen: modelData

    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    exclusiveZone: -1

    WlrLayershell.layer: WlrLayer.Bottom
    WlrLayershell.namespace: "qs-background-scroll"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    // Collapses a trackpad's flood of small wheel events into one switch per
    // gesture, instead of flying through several workspaces on one swipe.
    property bool cooling: false
    Timer {
        id: cooldown
        interval: 200
        onTriggered: cooling = false
    }

    MouseArea {
        anchors.fill: parent
        onWheel: (wheel) => {
            if (cooling) return;
            cooling = true;
            cooldown.restart();
            if (wheel.angleDelta.y < 0) {
                WorkspaceNav.go(1);
            } else if (wheel.angleDelta.y > 0) {
                WorkspaceNav.go(-1);
            }
        }
    }
}
