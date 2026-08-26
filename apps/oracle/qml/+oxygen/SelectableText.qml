import QtQuick

// The selectable, read-only PLAIN-text line, in a Plasma session wearing
// OXYGEN — the selectable twin of `+oxygen/PixelText.qml`, the same way
// `../SelectableText.qml` is the twin of `../PixelText.qml`.
//
// A `TextEdit`, not a `QQC.TextArea`: this item is not a field. It has no
// frame, no focus ring and no editing affordance — it is a run of log text
// that happens to be highlightable, so drawing it through the style's
// text-field background would promise an editor that is not there
// (docs/DESIGN.md §10.2 — the one house rule that is about honesty rather
// than looks, and so survives the change of clothes). What DOES come from the
// style is the type and the palette, which is what makes it match the window.
//
// What the sibling pins and this drops:
//   • `Theme.editorFont` — a whole QFont with `NoAntialias` set, so a scalable
//     PIXEL face rasterises as crisp mono glyphs. There is no pixel face here;
//     antialiasing off on Oxygen's Sans Serif is exactly the wrong picture.
//   • `renderType: Text.NativeRendering` — an override the rest of the window
//     does not carry.
//   • `Theme.highlight` / `Theme.accent` as the selection pair. Selection is a
//     PALETTE ROLE, and Oxygen draws its own: `highlight` behind,
//     `highlightedText` on top. Binding them is what makes a selection here
//     look like a selection in Kate.
//
// The API is the sibling's — `text`, `color`, `width`, `wrapMode`, `visible`,
// `selectedText` and its change signal — so no call site branches.
TextEdit {
    id: root

    property string face: "oxygen"

    readOnly: true
    selectByMouse: true
    textFormat: TextEdit.PlainText
    wrapMode: TextEdit.Wrap

    // The session's font, resolved exactly as +oxygen/PixelText.qml resolves
    // it: `kdeglobals` via DeskStyle in a real Plasma session, Qt's own
    // application font under a forced `--face=oxygen` on the Hyprland roof.
    readonly property bool kdeType: (typeof DeskStyle !== "undefined" && DeskStyle
                                     && DeskStyle.plasma === true)
    font.family: root.kdeType ? Theme.font : Qt.application.font.family
    font.pixelSize: {
        if (root.kdeType)
            return Theme.fontSize;
        const af = Qt.application.font;
        if (af.pixelSize > 0)
            return af.pixelSize;
        const dpi = Screen.logicalPixelDensity > 0
                  ? Screen.logicalPixelDensity * 25.4 : 96;
        return Math.max(1, Math.round(af.pointSize * dpi / 72));
    }

    // No `lineHeight`/`lineHeightMode` here either — but for the sibling's
    // reason, not this face's: they are Text-only, and assigning them to a
    // TextEdit is a component-creation ERROR.

    color: root.palette.text
    selectionColor: root.palette.highlight
    selectedTextColor: root.palette.highlightedText
}
