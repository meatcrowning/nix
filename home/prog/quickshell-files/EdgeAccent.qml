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
    // Stripe thickness: a flat 2px on every edge (matching the window-border
    // width). A 1px top/bottom line vanishes on a scale-1.0 1080p monitor — it's
    // a single physical pixel pinned to the screen edge — whereas 2px stays
    // visible there and matches the left/right stripe.
    property int thickness: 2

    // The horizontal stripes span the desktop the panel does NOT cover, and they
    // must follow the panel edge EXACTLY while it is being dragged.
    //
    // They used to get that for free by being anchored to both side edges and
    // letting the exclusive zone shorten them. That broke the moment the zone
    // stopped being rewritten per drag frame (it makes Hyprland re-run the whole
    // layout, which fights the resize): the stripes then only updated on
    // release, so widening the desktop left a gap at the end of each one — the
    // shortfall was invisible while the panel GREW, because the stripe was
    // simply covered, and obvious the other way.
    //
    // So they are sized explicitly off ViewMode.liveWidth instead, anchored to
    // one side only, and ignore exclusive zones entirely (with the zone still in
    // play the panel's reservation would shorten them a second time on top of
    // this). Same reason EdgeGrip.qml needs Ignore, and the same rule applies:
    // do not set exclusiveZone alongside it.
    readonly property bool horizontal: edge === "top" || edge === "bottom"
    readonly property bool barLeft: SettingsStore.d.barEdge === "left"

    anchors {
        left: horizontal ? true : edge !== "right"
        right: horizontal ? false : edge !== "left"
        top: edge !== "bottom"
        bottom: edge !== "top"
    }
    exclusionMode: ExclusionMode.Ignore

    implicitWidth: horizontal
        ? Math.max(1, (screen ? screen.width : 1920) - ViewMode.liveWidth)
        : thickness
    implicitHeight: thickness
    // With the bar on the left the stripes start past it rather than at 0.
    margins.left: (horizontal && barLeft) ? ViewMode.liveWidth : 0
    color: Theme.accent

    WlrLayershell.layer: WlrLayer.Bottom
    WlrLayershell.namespace: "qs-edge-accent"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
}
