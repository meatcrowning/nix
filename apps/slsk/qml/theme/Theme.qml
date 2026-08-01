import QtQuick

// The theme, instantiated once by main.py and installed as the global `Theme`
// context property (referenced as `Theme.*` everywhere, no import) -- the same
// ergonomics as reader/filer. Lives in this subdirectory, not beside the QML
// components, so it does not register as a type named `Theme` and shadow the
// context property.
QtObject {
    // The desktop's pixel font, at the size Settings sets for everything.
    readonly property string font: DeskStyle.fontFamily
    readonly property int fontSize: DeskStyle.fontSize

    readonly property int barWidth: 48
    readonly property int cell: 40
    readonly property int gap: 8

    // Live wallpaper palette (WalPalette in main.py).
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

    // The exact grey the hyprvtb titlebar fades to when the window is unfocused.
    readonly property color inactive: Qt.rgba(0x59 / 255, 0x59 / 255, 0x59 / 255, 0xaa / 255)
}
