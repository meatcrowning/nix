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

    // ONE TEXT ROW: the live FACE's cell (ascent + descent), which is only
    // sometimes the em size we asked for — docs/DESIGN.md 2.1. Measured, per
    // face, at 10/15/17/24 px: the DOS pair gives 11/15/17/24 and Botis 4x6
    // gives 8/12/13/19, so at the default 15 a row pinned to `fontSize` carries
    // 3px of dead leading under Botis and is a pixel out even on the DOS pair
    // at the slider's low end. Bind this for anything that means "one text
    // row"; bind `fontSize` only for an actual font size. (The panel has had
    // the same property, off a QML FontMetrics, since it was written.)
    readonly property int lineHeight: DeskStyle.lineHeight

    // The same font, as a whole QFont with NoAntialias pinned — bound as
    // `font:` on the TextEdit/TextInput he types into. Editable items ignore
    // `antialiasing:false`/`renderType` and draw a scalable pixel font
    // grey-fringed; only the font's style strategy reaches the rasteriser
    // (docs/DESIGN.md 2.2). Labels keep `font: Theme.font` — `Text` is crisp
    // already.
    readonly property font editorFont: DeskStyle.editorFont

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
