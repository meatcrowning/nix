import QtQuick

// The MODELS' replies, in a Plasma session wearing OXYGEN — markdown drawn in
// the session's own type and palette rather than the desktop's pixel idiom.
//
// Everything the sibling (`../MarkdownText.qml`) does about SAFETY and about
// COPYING is kept verbatim, because none of it is about looks:
//   • This is the one type in the app that opts into markup, and only for
//     assistant `body` text. User prompts and error lines stay on the plain
//     SelectableText; `Ollama.replyRuns` (main.py) has already demoted any
//     image the turn never fetched to a link, so rendering cannot cause a
//     remote fetch.
//   • Links open on CLICK, never on render.
//   • `Md.styleCode` still walks the laid-out document to let fenced blocks
//     wrap — Qt's markdown reader marks every one of them `NonBreakableLines`
//     and a long line would otherwise paint straight out of the bubble. Still
//     debounced, because a streaming reply rewrites the document per delta and
//     each rewrite brings the flag back.
//   • Ctrl+C still hands over the MARKDOWN via `Clip.copyMarkdown`, not Qt's
//     flattened render, and `source` still carries the text this item was
//     given (reading `text` back re-serialises the parsed document).
//
// What changes is the drawing:
//   • The face is the session's, not `Theme.editorFont` (a QFont with
//     `NoAntialias` pinned for a scalable pixel design). Oxygen's body font is
//     proportional and antialiased, and headings/emphasis in a markdown
//     document want its real family variants.
//   • CODE still comes out MONOSPACE with nothing pinned here. The sibling
//     gets its grid for free because its whole face is mono; this one gets it
//     because Qt's markdown reader gives every fenced block and inline `code`
//     span a monospace char format of its own, which the body family does not
//     override (`Md.styleCode` in main.py relies on exactly that family
//     surviving, to find the blocks again on a re-run).
//   • Selection and links are PALETTE ROLES (`highlight`/`highlightedText`,
//     `link`), so a selection here matches one in Kate.
//   • The inset behind a code block is `palette.base` — Oxygen's role for a
//     recessed, text-bearing surface — instead of a quarter-step from the
//     wallpaper palette's `bg` toward its `border`. The bubble around it is a
//     real Button background (`+oxygen/Bubble.qml` falls through to
//     `+plasma/Bubble.qml`), i.e. `palette.button`, so `base` reads as sunk
//     into it the way a field does.
TextEdit {
    id: mdRoot

    property string face: "oxygen"

    // The markdown this item was GIVEN — see the sibling: `text` is not it.
    property string source: ""

    readOnly: true
    selectByMouse: true
    textFormat: TextEdit.MarkdownText
    wrapMode: TextEdit.Wrap

    readonly property bool kdeType: (typeof DeskStyle !== "undefined" && DeskStyle
                                     && DeskStyle.plasma === true)
    font.family: mdRoot.kdeType ? Theme.font : Qt.application.font.family
    font.pixelSize: {
        if (mdRoot.kdeType)
            return Theme.fontSize;
        const af = Qt.application.font;
        if (af.pixelSize > 0)
            return af.pixelSize;
        const dpi = Screen.logicalPixelDensity > 0
                  ? Screen.logicalPixelDensity * 25.4 : 96;
        return Math.max(1, Math.round(af.pointSize * dpi / 72));
    }

    color: mdRoot.palette.text
    selectionColor: mdRoot.palette.highlight
    selectedTextColor: mdRoot.palette.highlightedText

    // TextEdit has no `linkColor` (that is Text-only); the colour comes off the
    // item's palette Link role, which under a KDE platform theme is the colour
    // scheme's own link tone.
    onLinkActivated: (url) => Qt.openUrlExternally(url)

    // The inset panel behind a fenced block. Guarded so a harness with no
    // palette (or an item measured before it has one) still gets a colour
    // rather than a transparent black.
    property color codeBackground: mdRoot.palette.base

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

    // BEHIND the glyphs and the full width of the item, so a two-word command
    // reads as an embedded block rather than a tinted two-word strip.
    // `positionToRectangle` is measured off the laid-out document, so it
    // follows a re-wrap for free.
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
            // Oxygen frames a sunken surface rather than rounding it; the
            // desktop's global rounding is 0 by default and this follows it
            // through `Theme.rounding` exactly as the sibling does.
            radius: Theme.rounding
            color: mdRoot.codeBackground
        }
    }

    // Ctrl+C copies the MARKDOWN, not the flattened render — see the sibling.
    Keys.onPressed: (event) => {
        if (event.key === Qt.Key_C && (event.modifiers & Qt.ControlModifier)
                && selectedText !== "") {
            if (Clip.copyMarkdown(textDocument, selectionStart, selectionEnd,
                                  source !== "" ? source : text))
                event.accepted = true;
        }
    }
}
