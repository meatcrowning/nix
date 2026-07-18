pragma Singleton
import Quickshell
import QtQuick

Singleton {
    // Everything uses the same pixel font kitty uses.
    readonly property string font: "More Perfect DOS VGA"

    // Text size in PIXELS (not points). The pixel font's native cell is 16px,
    // so an integer multiple of that stays crisp; point sizes get DPI-scaled to
    // a fractional pixel height that smears the glyphs. See PixelText.qml.
    readonly property int fontSize: 16
    readonly property int clockSize: 16   // same size as the rest of the panel

    // Panel geometry (logical px)
    readonly property int barWidth: 48
    readonly property int cell: 40          // square size for launcher button / tray
    readonly property int wsCell: 32        // workspace squares (a touch smaller)
    readonly property int gap: 8

    // Palette DERIVED FROM THE WALLPAPER. The block between the two markers is
    // rewritten by ~/.config/scripts/wal-set.sh every time the wallpaper
    // changes; the values checked in here are just the fallback until it first
    // runs. Everything else references Theme.* as before, so the whole panel
    // recolours from this one block.
    // >>> wal palette
    readonly property color bg:        "#000000"
    readonly property color bgAlt:     "#080e12"
    readonly property color border:    "#192c38"
    readonly property color accent:    "#5c9fcc"   // active / occupied
    readonly property color dim:       "#2a4354"      // empty & unviewed
    readonly property color text:      "#6dbdf2"
    readonly property color textDim:   "#3f6d8c"
    readonly property color highlight: "#0f1a21"   // selection bg
    readonly property color ok:        "#65afe0"
    readonly property color warn:      "#538fb8"
    readonly property color crit:      "#70c3fa"
    readonly property color info:      "#578bad"
    // <<< wal palette

    // Frame matching the Hyprland active-window border (see hypr/hyprland.lua
    // general.active_border / border_size / decoration.rounding), so overlay
    // surfaces like the launcher and cheatsheet read as windows. active_border
    // is accent at 0xee alpha; border_size = 2; rounding = 0. Derived from
    // accent so it recolours with the wallpaper alongside the rest of the panel.
    readonly property color windowBorder:      Qt.rgba(accent.r, accent.g, accent.b, 0xee / 255)
    // hypr general.col.inactive_border — rgba(595959aa), static (not wal-derived).
    readonly property color windowBorderInactive: Qt.rgba(0x59 / 255, 0x59 / 255, 0x59 / 255, 0xaa / 255)
    readonly property int   windowBorderWidth: 2
    readonly property int   windowRounding:    0
}
