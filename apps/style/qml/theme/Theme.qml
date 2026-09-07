import QtQuick

// Style uses the identical live palette and typography contract as the other
// desktop applications.  The controller changes the source; this QML simply
// follows it, so the control centre itself never becomes an old-colour island.
QtObject {
    readonly property string font: DeskStyle.fontFamily
    readonly property int fontSize: DeskStyle.fontSize
    readonly property int lineHeight: DeskStyle.lineHeight
    readonly property bool fontSmooth: DeskStyle.smooth
    readonly property bool fontTerminalCell: DeskStyle.terminalCell
    readonly property int gap: 8
    readonly property color bg: WalPalette.bg
    readonly property color bgAlt: WalPalette.bgAlt
    readonly property color border: WalPalette.border
    readonly property color accent: WalPalette.accent
    readonly property color dim: WalPalette.dim
    readonly property color text: WalPalette.text
    readonly property color textDim: WalPalette.textDim
    readonly property color highlight: WalPalette.highlight
    readonly property color ok: WalPalette.ok
    readonly property color warn: WalPalette.warn
    readonly property color crit: WalPalette.crit
    readonly property color info: WalPalette.info
    readonly property color inactive: Qt.rgba(0x59 / 255, 0x59 / 255, 0x59 / 255, 0xaa / 255)
    readonly property int ctrlBorder: Math.max(1, Math.round(DeskStyle.borderWidth / 2))
}
