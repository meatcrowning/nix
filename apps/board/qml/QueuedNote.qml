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

    Para {
        id: line
        width: row.width
        color: row.fgDim
        // THE WORD IS ORDER — [his, 2026-07-29] this list says orders, not
        // messages — and what it waits for is the next SUMMONER, which is who
        // drains the queue (`board-watch.work_the_queue`). It never waits for a
        // minister: Solomon is the one who reads it and decides who does it.
        text: "  order waiting for the next summoner: "
              + (row.note ? row.note.text : "")

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
