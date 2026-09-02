pragma Singleton
import Quickshell
import QtQuick

Singleton {
    id: root

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

    // True when the live face is a normal SMOOTH outline (Phenex, the cursive)
    // rather than a pixel one. Read from the generated FontFaces singleton
    // (home/pkgs/desktop/font.nix), so the flag ships with the face list and
    // cannot drift. PixelText branches its whole render path on this: pixel
    // faces keep NativeRendering + antialiasing:false + full hinting; a smooth
    // face is antialiased and unhinted (the pixel pipeline turns cursive
    // curves into a jagged staircase).
    readonly property bool fontSmooth: FontFaces.smooth[font] === true
    // A face whose desktop metrics are pinned to Kitty’s terminal cell. It
    // remains antialiased; only its advances and stems are grid-fitted.
    readonly property bool fontTerminalCell: FontFaces.terminalCell[font] === true
    readonly property real fontAdvanceRatio: Number(FontFaces.advanceRatio[font]) || 0

    // Kitty receives the desktop slider as points (the generated kitty.conf
    // uses this exact conversion).  Oxygen Mono must begin from that same
    // FreeType raster, not from a similarly-sized Qt pixel font: the latter
    // has different glyph outlines before advance correction even begins.
    readonly property real kittyPointSize: Math.max(1, fontSize * 72 / 96)

    // Round the actual terminal-cell glyph advance in device pixels, then map
    // it back to the item's logical units.  The old font-table ratio described
    // the 14px Qt raster; this is measured from the point raster Kitty uses.
    function fontLetterSpacing(deviceScale) {
        const scale = Number(deviceScale);
        if (!fontTerminalCell || !(scale > 0) || !isFinite(scale))
            return 0;
        const advance = metrics.advanceWidth("M");
        return Math.round(advance * scale) / scale - advance;
    }

    function fontForScale(deviceScale) {
        if (fontTerminalCell)
            return Qt.font({ family: font, pointSize: kittyPointSize,
                             letterSpacing: fontLetterSpacing(deviceScale),
                             hintingPreference: Font.PreferFullHinting,
                             weight: Font.Medium });
        return Qt.font({ family: font, pixelSize: fontSize,
                         hintingPreference: fontSmooth ? Font.PreferNoHinting
                                                       : Font.PreferFullHinting });
    }

    // Text size in PIXELS (not points). Matched to kitty's on-screen size:
    // kitty is font_size 11pt, which at 96 DPI (1080p, scale 1.0) rasterises to
    // ~14.67px, so 15px here matches the terminal. NOTE: the font's native cell
    // is 16px, so 15 is slightly off-grid and a touch softer than 16 would be —
    // intentional, it's the price of matching kitty rather than the pixel grid.
    // See PixelText.qml.
    readonly property int fontSize: SettingsStore.d.fontSize
    readonly property int clockSize: SettingsStore.d.fontSize   // same size as the rest of the panel

    // The height of ONE text row in the LIVE face — measured, never assumed to
    // be `fontSize`. `fontSize` is the em size we ask for; the cell it actually
    // produces is the face's own ascent+descent, and the two coincide only for
    // the two DOS faces (11 + 4 = 15 at pixelSize 15, measured). Botis 4x6 is a
    // 4x6 grid, so at that same 15px it draws a 10 + 2 = 12px cell — and every
    // row pinned to 15 then carried 3px of dead leading under its text, i.e.
    // the inter-row gap docs/DESIGN.md 2.1 forbids outright, on every label in
    // the panel at once. Anything that means "one text row" binds THIS; only an
    // actual font size binds `fontSize`. Rebinds live with the face, like the
    // rest of this file.
    readonly property FontMetrics metrics: FontMetrics {
        font: root.fontForScale(1)
    }
    readonly property int lineHeight: Math.max(1, Math.round(metrics.height))

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
    // The global frame at CONTROL scale (docs/DESIGN.md §4): buttons, toggles,
    // fields and cells follow the two global numbers too — the full rounding
    // (Rectangle clamps radius to half-size itself) and a half-scale border
    // with a 1px floor, so controls keep a visible edge while windows carry
    // the weight. 0 stays 0: "no borders" means everywhere.
    readonly property int   ctrlBorder: windowBorderWidth > 0 ? Math.max(1, Math.round(windowBorderWidth / 2)) : 0
}
