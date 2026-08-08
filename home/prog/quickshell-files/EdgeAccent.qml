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
    id: root
    required property var modelData
    screen: modelData

    // Which screen edge to hug: "left" (default), "top", or "bottom".
    property string edge: "left"
    // Stripe thickness: a flat 2px on every edge (matching the window-border
    // width). A 1px top/bottom line vanishes on a scale-1.0 1080p monitor — it's
    // a single physical pixel pinned to the screen edge — whereas 2px stays
    // visible there and matches the left/right stripe.
    // follows the global border width, floored at the legible 2px
    property int thickness: Math.max(2, Theme.windowBorderWidth)

    // The horizontal stripes span the desktop the panel does NOT cover, so they
    // have to follow the panel edge exactly while it is dragged.
    //
    // TWO wrong ways to do that, both already tried:
    //   1. Anchor them to both side edges and let the panel's EXCLUSIVE ZONE
    //      shorten them. That stopped working the moment the zone stopped being
    //      rewritten per drag frame (rewriting it makes Hyprland re-run the whole
    //      layout, which fights the resize) — the stripes then only updated on
    //      release, leaving a gap when the desktop widened. Invisible while the
    //      panel GREW, because the stripe was simply covered.
    //   2. Bind the WINDOW's implicitWidth to ViewMode.liveWidth. That is a
    //      layer-surface resize, i.e. a configure/ack roundtrip, so the stripes
    //      visibly lagged the cursor — the same mistake this file's own comment
    //      warns about elsewhere.
    //
    // So: the SURFACE is a fixed full-width strip that never resizes, and the
    // stripe inside it is a plain Rectangle whose width is the binding. An item
    // geometry change lands in the frame it is made. Ignore is needed so the
    // panel's reservation doesn't shorten the surface underneath us.
    readonly property bool horizontal: edge === "top" || edge === "bottom"
    readonly property bool barLeft: SettingsStore.d.barEdge === "left"

    anchors {
        left: horizontal || edge !== "right"
        right: horizontal || edge !== "left"
        top: edge !== "bottom"
        bottom: edge !== "top"
    }
    exclusionMode: ExclusionMode.Ignore

    implicitWidth: thickness      // ignored when anchored to both sides
    implicitHeight: thickness
    color: horizontal ? "transparent" : Theme.accent

    // The visible stripe. Horizontal only — the vertical ones are the window
    // itself, since their length never changes.
    Rectangle {
        visible: root.horizontal
        color: Theme.accent
        anchors {
            top: parent.top; bottom: parent.bottom
            left: root.barLeft ? undefined : parent.left
            right: root.barLeft ? parent.right : undefined
        }
        width: Math.max(0, parent.width - ViewMode.liveWidth)
    }

    WlrLayershell.layer: WlrLayer.Bottom
    WlrLayershell.namespace: "qs-edge-accent"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
}
