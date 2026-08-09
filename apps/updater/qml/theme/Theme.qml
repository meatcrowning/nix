import QtQuick

// The theme, instantiated once by main.py and installed as the global `Theme`
// context property. Verbatim twin of the other apps' theme/Theme.qml — it lives
// in this subdirectory (not beside the components) so it registers as the
// context property and not a shadowing type. See reader/qml/theme/Theme.qml for
// the full commentary; keep the copies in step (docs/DESIGN.md §2).
QtObject {
    readonly property string font: DeskStyle.fontFamily

    readonly property bool fontSmooth: (typeof DeskStyle !== "undefined" && DeskStyle)
                                       ? DeskStyle.smooth === true : false

    readonly property int fontSize: DeskStyle.fontSize
    readonly property int clockSize: DeskStyle.fontSize

    readonly property int lineHeight: {
        const lh = (typeof DeskStyle !== "undefined" && DeskStyle)
                 ? Number(DeskStyle.lineHeight) : NaN;
        return (isFinite(lh) && lh > 0) ? Math.round(lh) : fontSize;
    }

    readonly property font editorFont: {
        if (typeof DeskStyle !== "undefined" && DeskStyle && DeskStyle.editorFont)
            return DeskStyle.editorFont;
        return Qt.font({ family: font, pixelSize: fontSize,
                         hintingPreference: Font.PreferFullHinting });
    }

    readonly property int gap: 8

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

    readonly property color inactive: Qt.rgba(0x59 / 255, 0x59 / 255, 0x59 / 255, 0xaa / 255)

    readonly property color windowBorder:         Qt.rgba(accent.r, accent.g, accent.b, 0xee / 255)
    readonly property color windowBorderInactive: Qt.rgba(0x59 / 255, 0x59 / 255, 0x59 / 255, 0xaa / 255)
    readonly property int   windowBorderWidth: {
        const w = (typeof DeskStyle !== "undefined" && DeskStyle)
                ? Number(DeskStyle.borderWidth) : NaN;
        return (isFinite(w) && w >= 0) ? w : 2;
    }
    readonly property int   windowRounding: rounding

    readonly property int rounding: {
        const r = (typeof DeskStyle !== "undefined" && DeskStyle)
                ? Number(DeskStyle.rounding) : NaN;
        return (isFinite(r) && r > 0) ? r : 0;
    }

    readonly property int ctrlBorder:
        windowBorderWidth > 0 ? Math.max(1, Math.round(windowBorderWidth / 2)) : 0
}
