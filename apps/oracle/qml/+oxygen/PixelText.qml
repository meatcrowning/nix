import QtQuick
import QtQuick.Controls as QQC

// THE label type, in a Plasma session wearing OXYGEN: the system's own type,
// not the desktop's pixel idiom.
//
// `../PixelText.qml` — the sibling this file is selected in place of — is a
// `Text` pinned to the pixel pipeline: `Theme.font` at `Theme.fontSize`,
// NativeRendering, full hinting, and a per-line cell pinned to
// `Theme.lineHeight` in `Text.FixedHeight` mode. Every one of those pins is
// right for "More Perfect DOS VGA" drawn on the Hyprland face and wrong here:
//
//   • The FIXED CELL is the load-bearing one. It exists to make a bitmap face
//     lead exactly like a terminal row. A proportional system font (Oxygen's
//     default is Sans Serif at the kdeglobals size) has ascent + descent +
//     leading that the cell does not know about, so pinning it clips
//     descenders and cramps wrapped paragraphs. Qt's own metric is the only
//     correct one for a scalable face, so this type sets NO lineHeight at all.
//   • The HINTING OVERRIDE is the second. The sibling forces
//     PreferNoHinting for a smooth face; in a KDE session the hinting style is
//     the user's fontconfig setting and Qt already honours it. Overriding it
//     makes this one label disagree with every real widget in the window.
//
// It is a `QQC.Label`, not a bare `Text`, on purpose: Label carries the
// application palette and the application font, which under a KDE platform
// theme ARE `kdeglobals`. That is the same route the rest of this face takes —
// `QtQuick.Controls` under `org.kde.desktop` hands the drawing to the live
// `QStyle` rather than imitating it (apps/AGENTS.md → kdeshell). Label derives
// from Text, so every property the 87 call sites set — `text`, `color`,
// `elide`, `wrapMode`, `horizontalAlignment`, `opacity`, the anchors — and
// every property they read back — `contentWidth`, `paintedHeight`,
// `lineCount`, `truncated` — is unchanged. No call site branches.
QQC.Label {
    id: root

    // The only proof the swap took: an unowned QQmlFileSelector is collected
    // silently and every file falls back with no error at all.
    property string face: "oxygen"

    // PLAIN TEXT, ALWAYS — the sibling's whole-desktop defence, and it does not
    // relax just because the clothes changed. QML's Text defaults to AutoText,
    // which sniffs for HTML and INTERPRETS it, so any string this app did not
    // author itself (a filename, a model name, a tool's error line) could style
    // the chrome or pull a remote <img>. The one place markup is wanted is the
    // model's own reply, and that goes through MarkdownText.
    textFormat: Text.PlainText

    // THE SESSION'S FONT. In a Plasma session `DeskStyle` (pylib/deskstyle.py,
    // `_kde_type`) already resolves `kdeglobals [General] font=` to a family
    // and a PIXEL size converted at the screen's own logical DPI — that is what
    // `Theme.font` / `Theme.fontSize` hold here, and it is the same face
    // Oxygen paints every menu, button and toolbar label with.
    //
    // Outside a Plasma session — `--face=oxygen` forced on the Hyprland roof,
    // which is a test route, not a real one — `DeskStyle` reports the panel's
    // pixel face instead, and drawing THAT would defeat the point of this file.
    // So the fallback there is Qt's own application font, which is still the
    // system's rather than the desktop's.
    readonly property bool kdeType: (typeof DeskStyle !== "undefined" && DeskStyle
                                     && DeskStyle.plasma === true)
    font.family: root.kdeType ? Theme.font : Qt.application.font.family
    font.pixelSize: {
        if (root.kdeType)
            return Theme.fontSize;
        const af = Qt.application.font;
        if (af.pixelSize > 0)
            return af.pixelSize;
        // Qt reports a point size when nothing pinned pixels; convert at the
        // screen's own logical DPI, the way DeskStyle._kde_type does.
        const dpi = Screen.logicalPixelDensity > 0
                  ? Screen.logicalPixelDensity * 25.4 : 96;
        return Math.max(1, Math.round(af.pointSize * dpi / 72));
    }

    // Deliberately NOT set: `renderType`, `antialiasing`, `hintingPreference`,
    // `lineHeight`, `lineHeightMode`. Every one of them is a pixel-face
    // override; leaving them at Qt's defaults is what makes this label render
    // identically to the QLabel beside it in the same window.

    // The palette's text role, so an unstyled label is the same tone as the
    // window's own chrome. 85 of the 87 call sites assign `color:` themselves
    // (from `Theme.*`, which in a Plasma session is parsed out of the KDE
    // colour scheme — pylib/kdetheme.py), and those keep winning; this is only
    // what an unstyled one falls back to, instead of Text's off-palette black.
    color: root.palette.windowText
}
