import QtQuick

// The theme, instantiated once by main.py and installed as the global `Theme`
// context property (referenced as `Theme.*` everywhere, no import) — the same
// ergonomics Quickshell's Theme singleton had.
//
// It lives in this subdirectory, NOT in qml/ next to the components, on purpose:
// a `Theme.qml` sitting beside the files that use it would register as a *type*
// named `Theme` and shadow the context property. From here it's out of their
// implicit import, so `Theme` resolves to the context property.
//
// Colours bind to the `Palette` context property (main.py), which parses and
// watches the panel's Theme.qml — the file wal-set.sh rewrites on every
// wallpaper change — so filer recolours live, in lock-step with the bar.
QtObject {
    // Everything uses the same pixel font kitty uses, at the size the Settings
    // window sets for the WHOLE desktop: DeskStyle (pylib/deskstyle.py, a
    // context property installed by main.py) reads the panel's own
    // settings.json, so one slider moves the panel, the titlebars and all six
    // apps together — docs/DESIGN.md 2.1. These two are deliberately NOT parsed out
    // of the panel's Theme.qml the way the palette below is: there they are QML
    // expressions (SettingsStore.d.*) that only Quickshell can evaluate.
    readonly property string font: DeskStyle.fontFamily

    // Text size in PIXELS (not points), matched to kitty's on-screen size.
    // See PixelText.qml for why native rendering + integer pixel sizes matter.
    readonly property int fontSize: DeskStyle.fontSize
    readonly property int clockSize: DeskStyle.fontSize

    // The same font, as a whole QFont with NoAntialias pinned — bound as
    // `font:` on the TextEdit/TextInput he types into. Editable items ignore
    // `antialiasing:false`/`renderType` and draw a scalable pixel font
    // grey-fringed; only the font's style strategy reaches the rasteriser
    // (docs/DESIGN.md 2.2). Labels keep `font: Theme.font` — `Text` is crisp
    // already.
    readonly property font editorFont: DeskStyle.editorFont

    // Panel geometry (logical px) — kept for component compatibility.
    readonly property int barWidth: 48
    readonly property int cell: 40
    readonly property int wsCell: 32
    readonly property int gap: 8

    // Live wallpaper palette (WalPalette in main.py — not "Palette", which is a
    // built-in Qt Quick type name that would shadow the context property).
    readonly property color bg:        WalPalette.bg
    readonly property color bgAlt:     WalPalette.bgAlt
    readonly property color border:    WalPalette.border
    readonly property color accent:    WalPalette.accent
    readonly property color dim:       WalPalette.dim
    readonly property color text:      WalPalette.text
    readonly property color textDim:   WalPalette.textDim
    readonly property color highlight: WalPalette.highlight
    readonly property color ok:        WalPalette.ok
    readonly property color warn:      WalPalette.warn
    readonly property color crit:      WalPalette.crit
    readonly property color info:      WalPalette.info

    // The exact grey the hyprvtb titlebar fades its text/glyphs to when the
    // window is unfocused (plugin inactiveColor 0xaa595959). Used across filer
    // so its own controls grey to the SAME tone as the titlebar when unfocused
    // — not the wallpaper-derived `dim`, which is a different colour.
    readonly property color inactive: Qt.rgba(0x59 / 255, 0x59 / 255, 0x59 / 255, 0xaa / 255)

    // Frame matching the Hyprland active-window border, so overlay surfaces read
    // as windows. Derived from accent so it recolours alongside the palette.
    readonly property color windowBorder:         Qt.rgba(accent.r, accent.g, accent.b, 0xee / 255)
    readonly property color windowBorderInactive: Qt.rgba(0x59 / 255, 0x59 / 255, 0x59 / 255, 0xaa / 255)
    readonly property int   windowBorderWidth: 2
    readonly property int   windowRounding:    0
}
