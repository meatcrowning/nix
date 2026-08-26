import QtQuick
import QtQuick.Controls as QQC

// qmlcommon's copy of the apps' +oxygen PixelText — byte-identical below this
// header to `apps/oracle/qml/+oxygen/PixelText.qml`, exactly as the two
// unselected siblings are byte-identical to each other. Retune both together.
//
// IT IS THE ONE THAT ACTUALLY DRAWS chatter's log. A QML file that explicitly
// imports a directory resolves that directory's types AHEAD of its own
// (verified: an `import "../../qmlcommon"` in `oracle/qml/Root.qml` makes
// `PixelText` resolve HERE, not to the file sitting beside Root.qml). Every
// oracle file that imports qmlcommon — Root, PromptBox, PromptEditor, JobRow,
// InlineImage, MiniPlayer, ImageGallery, VideoStage, Lightbox — therefore takes
// this copy; the ones that do not (Bubble, Chip, CtxMenu, JobsTray, Meter,
// VideoTransport, CaptionStrip, ViewFrame) take oracle's. Both must exist or
// half the window changes clothes.
//
// INERT FOR EVERY OTHER APP. `+oxygen` is only ever a selector for an engine
// whose app asked for it (`pylib/kdeshell.select_plasma_files(extra=...)`), and
// today that is chatter alone. The other nine apps that share this directory
// resolve `../PixelText.qml` exactly as before.
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
