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
// still cause a remote fetch on render, which is why `Ollama.replyRuns`
// (main.py) DEMOTES an image the turn never fetched to a link before a reply
// reaches this type; a fetched picture is drawn INLINE at its own spot by the
// run delegate instead (qml/InlineImage.qml).
//
// A TextEdit, not a Text, so the reply is selectable. An editable item ignores
// `antialiasing:false`/`renderType` and would grey-fringe the pixel font, so the
// face is a whole QFont with NoAntialias pinned (`Theme.editorFont`) — the same
// rule board's editors carry (docs/DESIGN.md §2.2). Code and inline code inherit
// that face, which is itself monospaced (More Perfect DOS VGA), so fenced blocks
// stay a clean grid. No `lineHeight` pin: it is Text-only (a TextEdit errors on
// it), and markdown mixes heading and body sizes a single cell would clip.
TextEdit {
    id: mdRoot

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
            font.letterSpacing: Theme.fontLetterSpacing(Screen.devicePixelRatio)
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

    // CODE BLOCKS STAY INSIDE THE BUBBLE. Qt's markdown reader marks every
    // fenced block `NonBreakableLines`, so a long line lays out past this
    // item's width and paints across whatever is beside it — code spilling out
    // of the bubble it belongs to [his, 2026-08-22]. That flag lives on the
    // QTextDocument's block formats, which QML cannot reach, so `Md.styleCode`
    // (main.py → MdFormat) walks the document this item is already drawing:
    // it lets each code block wrap and gives it the inset background and
    // margins that make it read as embedded. The TEXT is never touched, so
    // Ctrl+C below still hands over the model's own markdown.
    //
    // DEBOUNCED, because a streaming reply rewrites the document on every
    // delta and each rewrite brings the flag back. The call reports whether it
    // changed anything, so re-running it on its own edit stops there rather
    // than looping.
    // A quarter of the way from the bubble's own fill toward the border tone:
    // visible as an inset panel on a near-black wallpaper palette AND on a
    // light KDE scheme, without adding a colour to docs/DESIGN.md §3 that has
    // to be kept in sync.
    property color codeBackground: Qt.rgba(
        Theme.bg.r + (Theme.border.r - Theme.bg.r) * 0.25,
        Theme.bg.g + (Theme.border.g - Theme.bg.g) * 0.25,
        Theme.bg.b + (Theme.border.b - Theme.bg.b) * 0.25, 1.0)
    property var codeRuns: []
    Timer {
        id: codeFmt
        interval: 60
        onTriggered: {
            if (typeof Md === "undefined" || !Md) { mdRoot.codeRuns = []; return; }
            try { mdRoot.codeRuns = JSON.parse(Md.styleCode(mdRoot.textDocument)); }
            catch (e) { mdRoot.codeRuns = []; }
        }
    }
    onTextChanged: codeFmt.restart()
    onWidthChanged: codeFmt.restart()
    Component.onCompleted: codeFmt.restart()

    // The panel itself, BEHIND the glyphs (z: -1) and the full width of the
    // item, so a two-word command reads as an embedded block rather than as a
    // tinted two-word strip. `positionToRectangle` is the only honest source
    // for where a block ended up — it is measured off the laid-out document,
    // so it follows a re-wrap for free.
    Repeater {
        model: mdRoot.codeRuns
        delegate: Rectangle {
            required property var modelData
            readonly property rect r0: mdRoot.positionToRectangle(modelData.start)
            readonly property rect r1: mdRoot.positionToRectangle(modelData.end)
            x: 0
            width: mdRoot.width
            y: Math.round(r0.y) - 2
            height: Math.round(r1.y + r1.height - r0.y) + 4
            z: -1
            radius: Theme.rounding
            color: mdRoot.codeBackground
        }
    }

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
