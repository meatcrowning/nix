import QtQuick

// Markdown-rendered text, for the MODELS' replies only — headings, bold/italic,
// bullet and numbered lists, inline code, fenced code blocks, blockquotes and
// links, drawn in the desktop's pixel idiom (docs/DESIGN.md §2). Read-only and
// mouse-selectable, so a reply (or a code block inside it) can be highlighted
// and copied.
//
// Deliberately NOT PixelText/SelectableText. Those types are pinned to PlainText
// as the whole desktop's defence against interpreting strings it did not author
// (a filename, a tag, a page title). Here the opposite is wanted: the model's
// reply IS markup we asked it to format, so this ONE place opts into
// MarkdownText. It is scoped to assistant `body` text (the delegate keeps user
// prompts and error lines on the plain SelectableText), and the reply comes off
// a local ollama daemon the user chose to run — an adversarial `![](url)` could
// still cause a remote fetch on render, which is why Main.qml DEMOTES image
// markdown to a link before it reaches this type.
//
// A TextEdit, not a Text, so the reply is selectable. An editable item ignores
// `antialiasing:false`/`renderType` and would grey-fringe the pixel font, so the
// face is a whole QFont with NoAntialias pinned (`Theme.editorFont`) — the same
// rule board's editors carry (docs/DESIGN.md §2.2). Code and inline code inherit
// that face, which is itself monospaced (More Perfect DOS VGA), so fenced blocks
// stay a clean grid. No `lineHeight` pin: it is Text-only (a TextEdit errors on
// it), and markdown mixes heading and body sizes a single cell would clip.
TextEdit {
    // The markdown this item was GIVEN. `text` is not it: a TextEdit whose
    // format is MarkdownText re-serialises the parsed document when read back
    // (escapes and all — `<Picture 1>` returns as `\<Picture 1>`), so the
    // source has to be kept beside it for the copy path below. Callers set both
    // from one expression; when unset, `text` is the best available.
    property string source: ""

    readOnly: true
    selectByMouse: true
    textFormat: TextEdit.MarkdownText
    wrapMode: TextEdit.Wrap

    font: Theme.editorFont
    renderType: Text.NativeRendering
    color: Theme.text
    selectionColor: Theme.highlight
    selectedTextColor: Theme.accent

    // Links take the palette accent, not Qt's off-palette default blue. TextEdit
    // has no `linkColor` (that is Text-only); the link colour comes from the
    // item's palette Link role instead. They open in the browser on click — an
    // explicit action, never on render.
    palette.link: Theme.accent
    onLinkActivated: (url) => Qt.openUrlExternally(url)

    // Ctrl+C copies the MARKDOWN, not the flattened render. Qt's own copy hands
    // over the rendered document as plain text, which drops the blank line
    // between paragraphs and every list marker — so a prompt copied out of the
    // chat arrived in the next program as one run-on block [his, 2026-08-22].
    // `Clip.copyMarkdown` serves it from this item's own source instead (main.py
    // → Clip). If it cannot (no document yet), the key falls through to Qt's
    // copy rather than doing nothing.
    Keys.onPressed: (event) => {
        if (event.key === Qt.Key_C && (event.modifiers & Qt.ControlModifier)
                && selectedText !== "") {
            if (Clip.copyMarkdown(textDocument, selectionStart, selectionEnd,
                                  source !== "" ? source : text))
                event.accepted = true;
        }
    }
}
