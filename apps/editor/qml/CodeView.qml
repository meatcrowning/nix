import QtQuick
import QtQuick.Controls.Basic
import "../../qmlcommon"

// ONE open document: the gutter, the code, the current-line band, and every
// Kate key that edits text. Main.qml keeps one of these per tab and shows the
// current one — so each document keeps its own undo stack, its own selection and
// its own caret, which is Qt's `TextEdit` doing the bookkeeping rather than us.
//
// Three things about the shape here are deliberate and should not be "tidied":
//
//  * **The gutter is OUTSIDE the flickable.** It scrolls with the content
//    vertically (it offsets by `flick.contentY`) and never horizontally, which
//    is what every editor does and what a gutter parked inside the content
//    cannot do.
//  * **Its numbers come from the DOCUMENT's layout, not from `n * lineH`**
//    (`Buffers.gutter`). With wrap on a document line is several rows tall, and
//    an arithmetic gutter drifts by a line per wrapped paragraph — silently,
//    and only for the files where it matters most.
//  * **Multi-line edits go to Python** (`Buffers.*` -> `textops.py`) and come
//    back as a selection to apply. A `QTextCursor` edit block is what makes
//    indent-4-lines ONE Ctrl+Z; the same work done on `ed.text` in QML is one
//    whole-document replace that loses the caret and re-highlights everything.
//
// The one bare `Flickable` rule (apps/AGENTS.md) is honoured with
// `KineticFlickable`: the compositor generates the momentum and a view that adds
// its own is two decay curves fighting.
Item {
    id: root

    property int tid: -1
    property string path: ""
    property string docName: ""
    //: The language KEY, or "" to let Python detect it from the path (which is the
    //: normal case). Never default this to "text": `Buffers.attach` honours any
    //: key it is handed, so a "helpful" fallback here PINS every file to no
    //: highlighting at all — measured, and it looked exactly like a broken
    //: highlighter.
    property string lang: ""

    // indentation — Main owns the settings, this applies them
    property bool useTabs: false
    property int indentWidth: 4

    property bool showNumbers: true
    property bool winActive: true
    property real cellW: 8

    // find state, pushed in by Main so the view can step matches
    property string query: ""
    property bool queryRegex: false
    property bool queryCase: false
    property bool queryWhole: false

    // The view's SURFACE, and the whole of it. Everything outside this file —
    // Main.qml and the offscreen harness — goes through these rather than
    // reaching into `ed`: PySide6 wraps no `QQuickTextEdit`, so a harness that
    // pokes the TextEdit directly cannot even get a reference to it ("Can't find
    // converter for 'QQuickTextEdit*'"), and one that goes through a QML property
    // works on both sides.
    //: `content` is for READING (and for the harness). Assigning it goes through
    //: `QTextDocument::setPlainText`, which clears the modified flag and the undo
    //: stack — so a real edit is a keystroke or `Buffers.*`, never this.
    property alias content: ed.text
    readonly property alias selectedText: ed.selectedText
    readonly property alias canUndo: ed.canUndo
    readonly property alias canRedo: ed.canRedo
    readonly property alias cursorPos: ed.cursorPosition
    readonly property alias selStart: ed.selectionStart
    readonly property alias selEnd: ed.selectionEnd

    //: `12:34` for the footer. Both come from the document (one tree walk), never
    //: from counting newlines in a JS string.
    property int line: 1
    property int col: 1
    property int lines: 1

    function focusEditor() { ed.forceActiveFocus(); }
    function undo() { ed.undo(); }
    function redo() { ed.redo(); }
    function cut() { ed.cut(); }
    function copy() { ed.copy(); }
    function paste() { ed.paste(); }
    function selectAll() { ed.selectAll(); }

    signal statusReported(string message)
    //: `pos` is the CHARACTER offset under the pointer, so the menu can offer
    //: spelling corrections for the word that was actually right-clicked.
    signal contextRequested(real x, real y, int pos)
    signal edited()

    // ---- spelling --------------------------------------------------------
    //: PROSE ONLY, and that is a deliberate limit. `spellcheck.py`'s tokeniser
    //: already refuses identifiers and paths, but a code file is mostly
    //: identifiers with prose in the comments, and no per-line grammar here
    //: knows which is which (`highlight.py` is regex-per-line, not a parser).
    //: So `.md`/`.txt` — the files whose whole content is prose, and the reason
    //: he asked for this — are checked, and a source file is not. Widening it
    //: means teaching the highlighter to publish its comment/string spans; the
    //: language menu switching a file to `text` already turns it on by hand.
    readonly property var proseLangs: ["text", "md"]   //: highlight.py's KEYS
    property bool prose: false

    function refreshSpell() {
        root.prose = root.proseLangs.indexOf(Buffers.language(root.tid)) >= 0;
        spell.rebuild();
    }

    //: The menu items for the word at character `pos`, or [] — Main.qml puts
    //: them at the top of the document menu.
    function spellItems(pos) { return spell.menuItems(pos); }

    //: How many words are marked wrong right now. Part of the view's surface for
    //: the same reason everything else here is: the harness cannot reach `spell`
    //: (PySide6 wraps no QML component type), and a marker nobody can count is a
    //: marker nobody can test.
    readonly property int spellCount: spell.spans.length

    // §3.1.1: an unfocused window fades its WHOLE foreground, body text
    // included. The ternary lives HERE, once, and the delegates below bind to
    // these — a per-glyph ternary would re-evaluate on every focus change.
    readonly property color fg:       winActive ? Theme.text    : Theme.inactive
    readonly property color fgDim:    winActive ? Theme.textDim : Theme.inactive
    readonly property color fgAccent: winActive ? Theme.accent  : Theme.inactive

    // ---- geometry -------------------------------------------------------
    readonly property int gutterDigits: Math.max(3, String(lines).length)
    readonly property real gutterW: showNumbers
        ? Math.round(gutterDigits * cellW + 12) : 0

    function refreshCursor() {
        var lc = Buffers.lineCol(tid, ed.cursorPosition);
        line = lc.line;
        col = lc.col;
        var r = Buffers.blockRect(tid, ed.cursorPosition);
        curBand.y = r.y;
        curBand.height = Math.max(1, r.h);
    }

    function refreshLines() {
        lines = Math.max(1, Buffers.lineCount(tid));
        gutter.reload();
    }

    // ---- applying an edit Python performed -------------------------------
    // Python moves the TEXT; the view owns the CARET, so every command lands
    // back here. `deselect()` first: assigning cursorPosition while a selection
    // is live leaves the selection behind and the next keystroke eats it.
    function applySel(res) {
        if (!res || !res.ok) return false;
        ed.deselect();
        if (res.end > res.start) ed.select(res.start, res.end);
        else ed.cursorPosition = res.start;
        ensureVisible(ed.cursorPosition);
        root.edited();
        return true;
    }

    function ensureVisible(pos) {
        var r = ed.positionToRectangle(pos);
        if (r.height <= 0) return;
        var top = r.y, bot = r.y + r.height;
        if (top < flick.contentY) flick.contentY = Math.max(0, top);
        else if (bot > flick.contentY + flick.height)
            flick.contentY = Math.min(Math.max(0, flick.contentHeight - flick.height),
                                      bot - flick.height);
        // Horizontally, keep a couple of columns of lead so the caret is never
        // flush against the edge it just arrived at.
        var lead = 2 * cellW;
        if (r.x - lead < flick.contentX) flick.contentX = Math.max(0, r.x - lead);
        else if (r.x + lead > flick.contentX + flick.width)
            flick.contentX = Math.min(Math.max(0, flick.contentWidth - flick.width),
                                      r.x + lead - flick.width);
    }

    function goToLine(n) {
        var pos = Buffers.lineStart(tid, n);
        ed.deselect();
        ed.cursorPosition = pos;
        ensureVisible(pos);
    }

    // ---- find, on this document -----------------------------------------
    function stepMatch(backward) {
        if (query.length === 0) return false;
        // Start from the far side of the current selection so Enter walks
        // forward through matches instead of re-finding the one you are on.
        var from = backward ? ed.selectionStart : ed.selectionEnd;
        var hit = Buffers.find(tid, query, from, backward, queryRegex,
                               queryCase, queryWhole);
        if (!hit.ok) return false;
        ed.deselect();
        ed.select(hit.start, hit.end);
        ensureVisible(hit.start);
        ensureVisible(hit.end);
        return true;
    }

    // Replace = "replace what you are standing on, then move to the next one",
    // which is Kate's Replace button and also why it is not a separate control
    // that can be pressed when there is nothing to replace. Asked as a FUNCTION
    // and not a binding: whether the selection is a match is a document search,
    // and a binding would run one on every arrow key.
    function selectionIsMatch() {
        if (query.length === 0 || ed.selectionStart === ed.selectionEnd) return false;
        var hit = Buffers.find(tid, query, ed.selectionStart, false, queryRegex,
                               queryCase, queryWhole);
        return hit.ok && hit.start === ed.selectionStart && hit.end === ed.selectionEnd;
    }

    function replaceStep(text) {
        if (selectionIsMatch()) {
            applySel(Buffers.replaceOne(tid, ed.selectionStart, ed.selectionEnd, text));
            return stepMatch(false) || true;
        }
        return stepMatch(false);
    }

    // ---- the commands ----------------------------------------------------
    function cmdIndent()   { applySel(Buffers.indent(tid, ed.selectionStart, ed.selectionEnd, useTabs, indentWidth)); }
    function cmdUnindent() { applySel(Buffers.unindent(tid, ed.selectionStart, ed.selectionEnd, useTabs, indentWidth)); }
    function cmdComment()  { applySel(Buffers.toggleComment(tid, ed.selectionStart, ed.selectionEnd)); }
    function cmdDuplicate(){ applySel(Buffers.duplicateLines(tid, ed.selectionStart, ed.selectionEnd)); }
    function cmdDeleteLine(){ applySel(Buffers.deleteLines(tid, ed.selectionStart, ed.selectionEnd)); }
    function cmdMove(d)    { applySel(Buffers.moveLines(tid, ed.selectionStart, ed.selectionEnd, d)); }
    function cmdNewline()  { applySel(Buffers.newline(tid, ed.cursorPosition, useTabs, indentWidth)); }

    clip: true

    // ---- the gutter ------------------------------------------------------
    Rectangle {
        id: gutter
        visible: root.showNumbers
        x: 0
        y: 0
        width: root.gutterW
        height: parent.height
        color: Theme.bgAlt
        clip: true

        // Re-asked whenever the view scrolls, resizes, or the document changes.
        // Only the VISIBLE rows are ever built — a 3000-line file draws the
        // sixty numbers you can see, not three thousand items.
        property var rows: []
        function reload() {
            if (!root.showNumbers || height <= 0) { rows = []; return; }
            rows = Buffers.gutter(root.tid, flick.contentY,
                                  flick.contentY + flick.height);
        }

        Repeater {
            model: gutter.rows
            delegate: PixelText {
                required property var modelData
                x: 4
                y: modelData.y - flick.contentY
                width: gutter.width - 8
                horizontalAlignment: Text.AlignRight
                text: modelData.n
                // The current line's own number is the brighter tier (§3.2):
                // the bulk of the gutter is dim, the indicator on it is not.
                color: modelData.n === root.line ? root.fgAccent : root.fgDim
            }
        }

        // A 1px rule, not a gap: the gutter is a column, and §5.1 is
        // zero-gap/edge-to-edge.
        Rectangle {
            anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
            width: 1
            color: Theme.border
        }
    }

    // ---- the code --------------------------------------------------------
    KineticFlickable {
        id: flick
        x: root.gutterW
        y: 0
        width: parent.width - x
        height: parent.height
        clip: true
        contentWidth: Math.max(width, ed.contentWidth)
        contentHeight: Math.max(height, ed.contentHeight)
        ScrollBar.vertical: VScroll {}

        onContentYChanged: gutter.reload()
        onHeightChanged: gutter.reload()

        // The current line's band, BEHIND the text and spanning the whole
        // content width so it does not stop at the end of the line's characters.
        // Its y/height are written by refreshCursor() from the document layout,
        // not bound — `positionToRectangle` is not a notifying property and a
        // binding on it evaluates exactly once, before layout even exists
        // (measured: it returned y=0 forever).
        Rectangle {
            id: curBand
            z: -1
            x: 0
            width: flick.contentWidth
            height: Theme.fontSize
            color: Theme.highlight
            visible: root.winActive
        }

        TextEdit {
            id: ed
            x: 0
            y: 0
            // Wrap is always on, so the text lays out to the viewport width and
            // never overflows it. Binding to `contentWidth` here (as the old
            // no-wrap path did) loops, because wrapping makes contentWidth depend
            // on width in turn.
            width: flick.width
            // The BODY is not PixelText (that is a Text subclass), so the four
            // things PixelText pins for the chrome are pinned again here — and
            // for the same reasons (§2.2): native rasterisation at an integer
            // pixel size, full hinting, no antialiasing. `lineHeightMode` does
            // not exist on TextEdit, so the line box is Qt's own
            // ascent+descent; measured with this font it comes out exactly
            // `Theme.fontSize`, i.e. kitty's cell, which is why the gutter lines
            // up at all.
            font.family: Theme.font
            font.pixelSize: Theme.fontSize
            font.hintingPreference: Font.PreferFullHinting
            renderType: Text.NativeRendering
            antialiasing: false

            // PLAIN TEXT, ALWAYS — §2.6, and here it is not merely a security
            // rule but a correctness one: `AutoText` would sniff an HTML file
            // and RENDER it, so opening a web page in the editor would show the
            // page instead of the source.
            textFormat: TextEdit.PlainText
            // Wrap is UNCONDITIONAL — the editor always wraps long lines, with no
            // toggle to turn it off (his call). So the code area never pans
            // horizontally: `flick.contentX` stays 0 and no HScroll is needed.
            wrapMode: TextEdit.WrapAtWordBoundaryOrAnywhere
            selectByMouse: true
            selectByKeyboard: true
            persistentSelection: true
            color: root.fg
            // Selection is a background tint in the palette's own ladder. The
            // selected text takes ONE colour — Qt gives no way to keep the
            // syntax colours under a selection — so it takes the brightest one
            // that is still legible on `highlight`.
            selectionColor: Theme.border
            selectedTextColor: root.winActive ? Theme.accent : Theme.inactive
            activeFocusOnPress: true

            cursorDelegate: Rectangle {
                width: 1
                color: root.fgAccent
            }

            onCursorPositionChanged: {
                root.refreshCursor();
                root.ensureVisible(cursorPosition);
            }
            onTextChanged: {
                root.refreshLines();
                root.refreshCursor();
            }

            // Every editing key Kate binds INSIDE the document. The app-wide ones
            // (Ctrl+S/O/N/W, Ctrl+F, Ctrl+R, Ctrl+G) are window `Shortcut`s in
            // Main.qml, so they work wherever the focus is — docs/DESIGN.md §11.2.
            //
            // `Keys.priority: BeforeItem` is load-bearing for exactly one key:
            // without it Tab is consumed by focus navigation before this handler
            // ever sees it, and indent does nothing at all.
            Keys.priority: Keys.BeforeItem
            Keys.onPressed: (e) => {
                const ctrl = (e.modifiers & Qt.ControlModifier) !== 0;
                const shift = (e.modifiers & Qt.ShiftModifier) !== 0;
                const alt = (e.modifiers & Qt.AltModifier) !== 0;

                if (e.key === Qt.Key_Tab && !ctrl && !alt) {
                    root.cmdIndent();
                    e.accepted = true;
                    return;
                }
                if (e.key === Qt.Key_Backtab || (e.key === Qt.Key_Tab && shift)) {
                    root.cmdUnindent();
                    e.accepted = true;
                    return;
                }
                if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter)
                        && !ctrl && !alt) {
                    root.cmdNewline();
                    e.accepted = true;
                    return;
                }
                if (e.key === Qt.Key_Backspace && !ctrl && !shift
                        && ed.selectionStart === ed.selectionEnd) {
                    // Only inside leading whitespace, and Python says so by
                    // returning nothing — otherwise the ordinary Backspace runs.
                    var r = Buffers.backspaceIndent(root.tid, ed.cursorPosition,
                                                    root.useTabs, root.indentWidth);
                    if (r.ok) { root.applySel(r); e.accepted = true; }
                    return;
                }
                if (ctrl && shift && e.key === Qt.Key_Up) {
                    root.cmdMove(-1); e.accepted = true; return;
                }
                if (ctrl && shift && e.key === Qt.Key_Down) {
                    root.cmdMove(1); e.accepted = true; return;
                }
                if (ctrl && alt && e.key === Qt.Key_Down) {
                    root.cmdDuplicate(); e.accepted = true; return;
                }
                if (ctrl && !shift && e.key === Qt.Key_K) {
                    root.cmdDeleteLine(); e.accepted = true; return;
                }
                if (ctrl && e.key === Qt.Key_D) {
                    root.cmdComment(); e.accepted = true; return;
                }
                if (ctrl && e.key === Qt.Key_I) {
                    if (shift) root.cmdUnindent(); else root.cmdIndent();
                    e.accepted = true; return;
                }
            }

            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.RightButton
                onPressed: (m) => {
                    var p = mapToItem(root, m.x, m.y);
                    root.contextRequested(p.x, p.y, ed.positionAt(m.x, m.y));
                }
            }
        }

        // The spelling marks. A SIBLING of `ed` inside the content item, so it
        // scrolls with the text and shares its coordinate space; `viewport`
        // keeps the check to the screenful that is actually visible.
        SpellMarks {
            id: spell
            target: ed
            viewport: flick
            x: ed.x
            y: ed.y
            width: ed.width
            height: ed.height
            active: root.prose
            //: One undo step per correction. `remove` + `insert` — SpellMarks'
            //: default — would cost two Ctrl+Z, and every other multi-character
            //: edit in this editor is one (`textops.py`'s edit blocks).
            replaceFn: function (s, e, w) {
                root.applySel(Buffers.replaceOne(root.tid, s, e, w));
            }
        }
    }

    // ---- loading and reloading -------------------------------------------
    // The order matters: text FIRST, then attach — the highlighter's first pass
    // must see the real content, and `attach` is also what clears the undo stack
    // so the first Ctrl+Z cannot empty the file.
    function loadText(text) {
        ed.text = text;
        Buffers.attach(root.tid, ed.textDocument, root.path, root.lang);
        refreshLines();
        refreshCursor();
        refreshSpell();
    }

    // §6.1, the most-repeated rule in the corpus: a document edited underneath
    // us comes back WITHOUT moving the user. Caret, selection and scroll are all
    // restored around the swap.
    function reloadText(text) {
        var pos = ed.cursorPosition, a = ed.selectionStart, b = ed.selectionEnd;
        var y = flick.contentY, x = flick.contentX;
        Buffers.replaceAllText(root.tid, text);
        var max = ed.length;
        ed.deselect();
        if (b > a) ed.select(Math.min(a, max), Math.min(b, max));
        else ed.cursorPosition = Math.min(pos, max);
        flick.contentY = Math.min(y, Math.max(0, flick.contentHeight - flick.height));
        flick.contentX = Math.min(x, Math.max(0, flick.contentWidth - flick.width));
        refreshLines();
        refreshCursor();
        refreshSpell();
    }

    onShowNumbersChanged: gutter.reload()
    onHeightChanged: gutter.reload()
}
