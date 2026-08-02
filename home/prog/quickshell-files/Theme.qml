pragma Singleton
import Quickshell
import QtQuick

Singleton {
    // Everything uses the same pixel font kitty uses. Font, panel geometry and
    // window-chrome sizes are read from SettingsStore (the Settings program's
    // on-disk model) rather than hardcoded here, so editing them in Settings
    // takes effect live: this file is a singleton in the panel instance too, so
    // when settings.json changes the panel's SettingsStore reloads and every
    // widget bound to Theme.* rebinds in place — the same no-reload, no-flash
    // path a wallpaper recolour already uses. The values below are the shipped
    // defaults (mirrored in SettingsStore); the palette block further down is
    // still owned by wal-set.sh.
    readonly property string font: SettingsStore.d.fontFamily

    // Canvas-safe face. QML Canvas / Context2D cannot rasterise a NON-SCALABLE
    // bitmap font ("the font families specified are invalid" -> generic sans).
    // All three selectable faces are now scalable outlines (Botis 4x6 was a BDF
    // until it was rebuilt as a pixel-outline TTF — see home/pkgs/desktop/font.nix),
    // so every pick draws in the exact face and this is a plain pass-through.
    // Kept as its own property so a future non-scalable face has one place to
    // guard again; canvas text binds this rather than `font` for that reason.
    readonly property string fontCanvas: font

    // Text size in PIXELS (not points). Matched to kitty's on-screen size:
    // kitty is font_size 11pt, which at 96 DPI (1080p, scale 1.0) rasterises to
    // ~14.67px, so 15px here matches the terminal. NOTE: the font's native cell
    // is 16px, so 15 is slightly off-grid and a touch softer than 16 would be —
    // intentional, it's the price of matching kitty rather than the pixel grid.
    // See PixelText.qml.
    readonly property int fontSize: SettingsStore.d.fontSize
    readonly property int clockSize: SettingsStore.d.fontSize   // same size as the rest of the panel

    // Panel geometry (logical px)
    readonly property int barWidth: SettingsStore.d.barWidth
    readonly property int cell: SettingsStore.d.barCell     // square size for launcher button / tray
    readonly property int wsCell: 32        // workspace squares (a touch smaller)
    readonly property int gap: SettingsStore.d.barGap

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
    readonly property int   windowBorderWidth: SettingsStore.d.windowBorderWidth
    readonly property int   windowRounding:    SettingsStore.d.windowRounding
}
