import QtQuick

// The theme, instantiated once by main.py and installed as the global `Theme`
// context property (referenced as `Theme.*` everywhere, no import) -- the same
// ergonomics as reader/filer. Lives in this subdirectory, not beside the QML
// components, so it does not register as a type named `Theme` and shadow the
// context property.
QtObject {
    // The desktop's pixel font, at the size Settings sets for everything.
    readonly property string font: DeskStyle.fontFamily

    // True when the live face is a normal SMOOTH outline (Phenex, the
    // cursive) rather than a pixel one; PixelText branches its render path on
    // it. Guarded like lineHeight below: harnesses stub DeskStyle.
    readonly property bool fontSmooth: (typeof DeskStyle !== "undefined" && DeskStyle)
                                       ? DeskStyle.smooth === true : false
    readonly property bool fontTerminalCell: (typeof DeskStyle !== "undefined" && DeskStyle)
                                             ? DeskStyle.terminalCell === true : false

    readonly property real fontAdvanceRatio: (typeof DeskStyle !== "undefined" && DeskStyle)
                                           ? Number(DeskStyle.advanceRatio) || 0 : 0
    function fontLetterSpacing(deviceScale) {
        const scale = Number(deviceScale);
        if (!(fontAdvanceRatio > 0) || !(scale > 0) || !isFinite(scale))
            return 0;
        const advance = fontSize * fontAdvanceRatio;
        return Math.round(advance * scale) / scale - advance;
    }
    readonly property int fontSize: DeskStyle.fontSize

    // ONE TEXT ROW: the live FACE's cell (ascent + descent), which is only
    // sometimes the em size we asked for — docs/DESIGN.md 2.1. Measured, per
    // face, at 10/15/17/24 px: the DOS pair gives 11/15/17/24 and Botis 4x6
    // gives 8/12/13/19, so at the default 15 a row pinned to `fontSize` carries
    // 3px of dead leading under Botis and is a pixel out even on the DOS pair
    // at the slider's low end. Bind this for anything that means "one text
    // row"; bind `fontSize` only for an actual font size. (The panel has had
    // the same property, off a QML FontMetrics, since it was written.)
    readonly property int lineHeight: {
        // GUARDED, not assumed — the same typeof shape qmlcommon/Motion.qml uses
        // on DeskStyle's motion keys, and for a sharper reason. A bare
        // `DeskStyle.lineHeight` resolves to 0 against any DeskStyle that does
        // not publish it — an offscreen harness with a stub, or an app whose
        // pylib is momentarily older than its QML (the two sync separately). On
        // an `int` property that 0 is not an error, it is a LAYOUT: every text
        // row on the surface collapses to nothing. That is exactly what happened
        // to player/tools/album-playnext-test.py the day this property landed —
        // a menu row went to height 0 and the click passed through it.
        const lh = (typeof DeskStyle !== "undefined" && DeskStyle)
                 ? Number(DeskStyle.lineHeight) : NaN;
        return (isFinite(lh) && lh > 0) ? Math.round(lh) : fontSize;
    }

    // The same font, as a whole QFont with NoAntialias pinned — bound as
    // `font:` on the TextEdit/TextInput he types into. Editable items ignore
    // `antialiasing:false`/`renderType` and draw a scalable pixel font
    // grey-fringed; only the font's style strategy reaches the rasteriser
    // (docs/DESIGN.md 2.2). Labels keep `font: Theme.font` — `Text` is crisp
    // already.
    readonly property font editorFont: {
        // Guarded for the same reason `lineHeight` above is: a DeskStyle that
        // does not publish this (a harness stub, or a pylib momentarily older
        // than the QML) would otherwise assign `undefined` to a `font` property,
        // which Qt reports as "Unable to assign [undefined] to QFont" and leaves
        // the editor drawing in the SYSTEM font — the one thing docs/DESIGN.md
        // §2.1 says must never appear on this desktop.
        //
        // The fallback cannot carry NoAntialias (the QML `font` group has no way
        // to express a style strategy — that is the whole reason this property
        // exists), so it degrades to the right family at the right size and
        // loses only the crispness. Wrong-but-legible beats unset.
        if (typeof DeskStyle !== "undefined" && DeskStyle && DeskStyle.editorFont)
            return DeskStyle.editorFont;
        return Qt.font({ family: font, pixelSize: fontSize,
                         hintingPreference: Font.PreferFullHinting });
    }

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

    // The desktop's GLOBAL corner rounding (DeskStyle.rounding, the radius the
    // compositor clips every window to) — bind it on every corner drawn here.
    // Guarded like lineHeight above (harnesses stub DeskStyle, and a pylib
    // momentarily older than this QML publishes neither key); the shipped
    // defaults are rounding 0, border width 2.
    readonly property int rounding: {
        const r = (typeof DeskStyle !== "undefined" && DeskStyle)
                ? Number(DeskStyle.rounding) : NaN;
        return (isFinite(r) && r > 0) ? r : 0;
    }

    // Control-weight border: half the global window border width
    // (DeskStyle.borderWidth), but never 0 unless the setting itself is 0 —
    // the hairline every in-window control (button, field, tab, toast) takes.
    readonly property int ctrlBorder: {
        const w = (typeof DeskStyle !== "undefined" && DeskStyle)
                ? Number(DeskStyle.borderWidth) : NaN;
        const b = (isFinite(w) && w >= 0) ? w : 2;
        return b > 0 ? Math.max(1, Math.round(b / 2)) : 0;
    }
}
