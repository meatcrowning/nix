pragma Singleton
import QtQuick
import Quickshell

// Cross-tree state for the desktop's hover tooltips (Tooltip.qml).
//
// The Screenshot overlay (Screenshot.qml, Meta+Shift+S) is a full-screen
// surface: the moment it maps it takes the pointer/focus away from whatever is
// being hovered, and a hover-driven tooltip retracts its chip straight away —
// so a capture fired after summoning the overlay never contains the tooltip
// that was on screen when the hotkey was struck. The overlay holds `frozen`
// true for the whole session and through the capture settle, which tells a
// visible tooltip to keep its chip out. When the freeze lifts, a tooltip whose
// hover is gone retracts normally.
Singleton {
    id: root

    // True while the screenshot overlay is up (and briefly across its capture
    // settle). A tooltip that is on screen while this is true does not retract.
    property bool frozen: false
}
