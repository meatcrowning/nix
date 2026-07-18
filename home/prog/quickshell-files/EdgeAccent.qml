import QtQuick
import Quickshell
import Quickshell.Wayland

// A thin accent-coloured stripe on the true left edge of the screen — the
// mirror of the accent stripe drawn on the bar's own left edge (see shell.qml),
// so the desktop reads as bookended by the same accent line on both sides.
// No exclusive zone: hyprland.lua's gaps_out (35px) keeps tiled windows well
// clear of the screen edges, so this is always visible without reserving
// space or covering anything.
//
// Deliberately Bottom, not Background: hyprpaper's own surface is Background,
// and same-level layers stack by creation order, not z-index — whichever one
// last (re)mapped wins. hyprpaper remaps its surface on every wallpaper
// change (unload/preload/wallpaper), so on Background this stripe would go
// invisible under it the moment hyprpaper next churns. Bottom always paints
// above Background regardless of mapping order.
PanelWindow {
    required property var modelData
    screen: modelData

    anchors { left: true; top: true; bottom: true }
    implicitWidth: 2
    color: Theme.accent
    exclusiveZone: 0

    WlrLayershell.layer: WlrLayer.Bottom
    WlrLayershell.namespace: "qs-edge-accent"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
}
