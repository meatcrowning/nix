import QtQuick

// Markdown-rendered text, for the MODELS' replies only — headings, bold/italic,
// bullet and numbered lists, inline code, fenced code blocks, blockquotes and
// links, drawn in the desktop's pixel idiom (docs/DESIGN.md §2).
//
// Deliberately NOT PixelText. That type is pinned to Text.PlainText as the
// whole desktop's defence against interpreting strings it did not author (a
// filename, a tag, a page title) — see PixelText.qml. Here the opposite is
// wanted: the model's reply IS markup we asked it to format, so this ONE place
// opts into Text.MarkdownText. It is scoped to assistant `body` text (the
// delegate keeps user prompts and error lines on PixelText), and the reply comes
// off a local ollama daemon the user chose to run — an adversarial `![](url)`
// could still cause a remote fetch on render, which is the price of the feature
// and why this is not the default type.
//
// Same pixel-font rasterising as PixelText (NativeRendering, native strikes),
// but no fixed line-height pin: markdown mixes heading and body sizes, and a
// forced single cell would clip the larger blocks.
Text {
    textFormat: Text.MarkdownText
    wrapMode: Text.Wrap

    font.family: Theme.font
    font.pixelSize: Theme.fontSize
    font.hintingPreference: Theme.fontSmooth ? Font.PreferNoHinting : Font.PreferFullHinting
    renderType: Text.NativeRendering
    antialiasing: Theme.fontSmooth

    color: Theme.text
    // Links take the palette accent, not Qt's off-palette default blue, and open
    // in the user's browser on click (an explicit action — never on render).
    linkColor: Theme.accent
    onLinkActivated: (url) => Qt.openUrlExternally(url)
}
