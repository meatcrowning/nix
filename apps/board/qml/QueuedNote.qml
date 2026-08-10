import QtQuick

// ONE PENDING ORDER, waiting for the next summoner, and his second thoughts
// about it: *"allow the user to remove queued `waiting for next agent` items or
// edit them in place"*.
//
// It is drawn at all because an order he cannot see is one he has to assume was
// lost — and now that it is on screen it is a thing he can change his mind
// about, because between writing it and a summoner picking it up there can be a
// whole board-watch interval. **Ctrl+Z is the third way** and reaches only the
// LAST one he sent, undoing the send itself and putting his words back in the
// box (`boardundo.py`, `Main.qml`'s `undoSend`); this menu reaches any of them.
//
// THE HONESTY IT HAS TO CARRY (docs/DESIGN.md §10.2). Neither action can be
// promised. `board-watch` drains the queue on its own clock, so a message can
// leave between this menu opening and his click landing, and after that the run
// working his sentence already exists — there is nothing to remove and nothing
// to rewrite. `boardagents` reports that case rather than papering over it
// (`remove_queued`/`edit_queued` return None), `main.py` turns it into a
// sentence, and this row puts that sentence in the footer. The one thing it
// must never do is close the editor looking like it worked.
//
// The editor is `InputBox`, the same component the top box and an agent's card
// use — one component because it is one promise, and his draft of an edit is
// persisted on the same settle timer as every other unsaved sentence here.
Item {
    id: row

    property var note: null                 // { id, text }
    property string draft: ""
    property color fgDim: Theme.textDim
    property color fgText: Theme.text
    property color fgAccent: Theme.accent
    // Monospace cell width, for cutting the collapsed line in characters (§2.7).
    property real cellW: 8
    // BOUNDED BY DEFAULT — a long order he typed in the box crowded the whole
    // page, so it is drawn as ONE line until he expands it. Held by the window
    // and keyed by the message id (session-only: a queued id names a message
    // board-watch will drain), the same way the card drawers are.
    property bool expanded: false
    signal expandToggled()

    signal draftEdited(string body)
    signal statusMessage(string text)
    //: passed straight through to the box — see `InputBox.qml`.
    signal caretHeld(int pos)
    signal caretLeft()
    property int openCaret: -1
    // head goes above the shared entries, tail below them — the destructive one
    // is LAST behind its own separator (§7.2), so the pointer never lands on it.
    signal menuRequested(real mx, real my, var head, var tail)

    implicitHeight: line.implicitHeight + editBox.height
    height: implicitHeight

    function beginEdit() {
        // Editing in place means starting from what it SAYS, not from a blank
        // box — unless he has a half-typed edit of this very message, which
        // outranks it and is what the draft is for.
        if (row.draft === "")
            row.draftEdited(row.note ? row.note.text : "");
        editBox.beginEdit();
    }

    // §7.2's ordering, and here it is a safety property: what he does most is
    // first, the read-only entry next, the shared ones after that, and the one
    // thing he cannot take back LAST behind its own separator.
    function openMenu(mx, my) {
        row.menuRequested(
            mx, my,
            [{ label: "edit what it says", trigger: () => row.beginEdit() },
             { label: "copy line",
               trigger: () => Board.copy(row.note ? row.note.text : "") }],
            [{ separator: true },
             { label: "remove it from the pending orders", trigger: () => row.removeIt() }]);
    }

    function removeIt() {
        row.statusMessage(Agents.removeQueued(row.note ? row.note.id : ""));
    }

    function commitEdit(body) {
        if (body.trim() === "")
            return false;
        var said = Agents.editQueued(row.note ? row.note.id : "", body);
        if (said === "")
            return false;
        row.statusMessage(said);
        row.draftEdited("");    // committed or refused, the draft has had its say
        return true;
    }

    // Cut a string to `cells` characters, marking the cut with ASCII "..." —
    // never U+2026, which the font lacks and whose absence clips the row
    // (docs/DESIGN.md §2.3). Exact in characters because the font is monospace
    // (§2.7). The twin of `Main.clipTo` / `AgentRow.clipTo`.
    function clipTo(s, cells) {
        if (cells < 4)
            return "..."
        return s.length <= cells ? s : s.slice(0, cells - 3) + "..."
    }

    // THE WORD IS ORDER — [his, 2026-07-29] this list says orders, not messages
    // — and what it waits for is the next SUMMONER, which drains the queue
    // (`board-watch.work_the_queue`); never a spirit. Solomon reads it and
    // decides who does it.
    readonly property string bodyText:
        "order waiting for the next summoner: " + (row.note ? row.note.text : "")
    // Is there more than the collapsed one line shows? Collapsed, that is a
    // character count against the row's width; expanded, it is whether the
    // wrapped order took more than one line. A short order that fits gets
    // neither the mark nor the toggle — a control that would do nothing is not
    // drawn (docs/DESIGN.md §10).
    readonly property bool overflowing:
        row.expanded ? line.lineCount > 1
                     : row.bodyText.length > Math.floor(line.width / row.cellW)

    // The fold mark, in the same ASCII vocabulary the sections and the to-do
    // bullets use (`+` folded, `-` open): the font has no triangles (§2.3).
    PixelText {
        id: mark
        x: 0
        y: 0
        visible: row.overflowing
        color: row.fgDim
        text: row.expanded ? "-" : "+"
    }

    Para {
        id: line
        // Sits past the mark's cell, roughly where the old two-space indent was.
        x: mark.implicitWidth + 6
        width: row.width - x
        color: row.fgDim
        // BOUNDED so a long order cannot crowd the page: one line until he
        // expands it. Collapsed, the line is cut in characters with an ASCII
        // marker (`clipTo`); expanded, the whole order, wrapped.
        maximumLineCount: row.expanded ? 9999 : 1
        text: row.expanded
              ? row.bodyText
              : row.clipTo(row.bodyText, Math.floor(width / row.cellW))

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            // A single left click stays inert, like every other row on this
            // board; the deliberate act is the second click or the menu.
            onClicked: (m) => {
                if (m.button !== Qt.RightButton)
                    return;
                var p = mapToItem(null, m.x, m.y);
                row.openMenu(p.x, p.y);
            }
            onDoubleClicked: (m) => {
                if (m.button === Qt.LeftButton)
                    row.beginEdit();
            }
        }
    }

    // The mark's own hit band — LEFT button only, so a right-click still opens
    // the row menu underneath and a double-click still edits. It exceeds the one
    // dim character it draws (§5.1: the hit band exceeds the ink), and it is
    // inert when there is nothing to expand.
    MouseArea {
        x: 0
        width: mark.implicitWidth + 6
        height: line.implicitHeight
        acceptedButtons: Qt.LeftButton
        cursorShape: row.overflowing ? Qt.PointingHandCursor : Qt.ArrowCursor
        enabled: row.overflowing
        onClicked: row.expandToggled()
    }

    InputBox {
        id: editBox
        y: line.implicitHeight + 2
        width: row.width
        visible: editing
        height: visible ? implicitHeight : 0
        draft: row.draft
        fgAccent: row.fgAccent
        fgText: row.fgText
        fgDim: row.fgDim
        placeholder: "rewrite this order - the next summoner reads it"
        openCaret: row.openCaret
        onDraftEdited: (b) => row.draftEdited(b)
        onSubmitted: (b) => row.commitEdit(b)
        onCaretHeld: (p) => row.caretHeld(p)
        onCaretLeft: () => row.caretLeft()
    }
}
