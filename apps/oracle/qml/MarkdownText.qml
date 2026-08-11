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
}
