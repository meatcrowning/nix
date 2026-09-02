import QtQuick

// A read-only, mouse-selectable PLAIN-text line for the conversation log — so a
// user prompt or an error line can be highlighted and copied, not just read.
//
// It is the selectable twin of PixelText, and keeps that type's two guarantees:
//   • PlainText, ALWAYS. A user prompt, a filename in an error — nothing this
//     app did not author is ever interpreted as markup (see PixelText.qml). The
//     assistant's own reply is the one place markup is wanted, and that goes
//     through MarkdownText.
//   • The crisp pixel face. An EDITABLE item (TextEdit) ignores
//     `antialiasing:false`/`renderType` and would grey-fringe a scalable pixel
//     font, so the face is pinned as a whole QFont with NoAntialias
//     (`Theme.editorFont`) — the same rule board's editors carry
//     (docs/DESIGN.md §2.2).
//
// NOTE: no `lineHeight`/`lineHeightMode`. They are Text-only; assigning them to
// a TextEdit is a component-creation ERROR (the bug that once broke painter's
// QML entirely — see apps/board/qml/Decision.qml), so this leads at Qt's rounded
// cell rather than the measured one, like every editable field here.
TextEdit {
    readOnly: true
    selectByMouse: true
    textFormat: TextEdit.PlainText
    wrapMode: TextEdit.Wrap

    font: (typeof DeskStyle !== "undefined" && DeskStyle
                       && typeof DeskStyle.editorFontForScale === "function")
                      ? DeskStyle.editorFontForScale(Screen.devicePixelRatio)
                      : Theme.editorFontForScale(Screen.devicePixelRatio)
    renderType: Text.NativeRendering
    selectionColor: Theme.highlight
    selectedTextColor: Theme.accent
    // The default is Qt's off-palette blue; the caller sets a themed colour.
    color: Theme.text
}
