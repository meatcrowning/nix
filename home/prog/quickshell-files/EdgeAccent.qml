import QtQuick
import Quickshell
import Quickshell.Wayland

// A thin accent-coloured stripe on one true edge of the screen — the mirror of
// the accent stripe drawn on the bar's own left edge (see shell.qml), so the
// desktop reads as bookended by the same accent line on every side. `edge`
// picks which screen edge: "left" (default) is the vertical stripe opposite the
// bar; "top"/"bottom" are the horizontal stripes across the desktop's top and
// bottom. No exclusive zone: hyprland.lua's gaps_out (35px) keeps tiled windows
// well clear of the screen edges, so this is always visible without reserving
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

    // Which screen edge to hug: "left" (default), "top", or "bottom".
    property string edge: "left"
    // Stripe thickness. The left side is 2px (matching the window-border width);
    // the top/bottom stripes are 1px.
    property int thickness: edge === "left" ? 2 : 1

    anchors {
        left: edge !== "right"
        right: edge !== "left"
        top: edge !== "bottom"
        bottom: edge !== "top"
    }
    implicitWidth: thickness
    implicitHeight: thickness
    color: Theme.accent
    exclusiveZone: 0

    WlrLayershell.layer: WlrLayer.Bottom
    WlrLayershell.namespace: "qs-edge-accent"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
}
