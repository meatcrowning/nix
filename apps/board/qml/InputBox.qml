import QtQuick

// The one thing on this board he types into — and there are three call sites
// for it, all the same component on purpose:
//
//   * the box at the TOP of the window, which is the control surface he asked
//     for ("a single box that i could type things into, press enter, and have
//     them sent to an inbox"),
//   * the box on a running agent's card, for a correction mid-flight,
//   * the answer editor's sibling idiom on a decision (`Decision.qml` keeps its
//     own, because it also has to show the store's existing answer).
//
// It is ONE component because it is one promise. Whatever he types goes down
// the same path — `boardagents.send()`, a file that is in exactly one of
// `to/`, `queue/`, `taken/` at every instant — and a second editor here would
// eventually become a second way of writing, which is exactly what the
// conservation argument in `boardagents.py` cannot survive.
//
// The idiom is the desktop's own (docs/DESIGN.md §7.2): a resting `>` invitation
// that is not a demand, and an inset `bgAlt` field with a 1px accent border when
// it is open. Escape KEEPS what he typed — nothing in this app throws away a
// sentence he wrote.
Item {
    id: box

    property bool editing: false
    property string draft: ""
    property string placeholder: ""
    property string hintText: "enter sends - shift+enter is a new line - esc keeps a draft"
    property color fgAccent: Theme.accent
    property color fgText: Theme.text
    property color fgDim: Theme.textDim

    signal submitted(string body)
    signal draftEdited(string body)

    //: HE HAS THE CARET IN HERE, at `pos` — or he has just left it. The window
    //  keeps that, not this box: a reload that ADDS or REMOVES a row has no
    //  delegate to keep, so the box he was typing in is destroyed and built
    //  again, and `openCaret` is how it comes back open with his caret where he
    //  left it. Reported only while the editor genuinely has focus, and `left`
    //  only when HE leaves it (escape, enter, or the caret going somewhere
    //  else) — never on destruction, which would erase the one thing this is
    //  for. Read once, at creation; a later change to it does nothing.
    signal caretHeld(int pos)
    signal caretLeft()
    property int openCaret: -1

    //: a RESTING height, never a cap — the box is at least this tall in both
    //  states, and still grows past it line by line as he types. The top box
    //  sets it from the chooser column beside it; every other call site leaves
    //  it 0 and is one line tall as before.
    property real minHeight: 0

    //: what the content alone needs. Derived from the two states' own
    //  implicitHeight and NEVER from `height` — that is the binding loop §5.2
    //  warns about, and here it would also make `minHeight` self-referential.
    readonly property real contentHeight: editing ? editBox.implicitHeight
                                                  : shown.implicitHeight

    implicitHeight: Math.max(minHeight, contentHeight)
    height: implicitHeight

    function beginEdit(at) {
        box.editing = true;
        editor.forceActiveFocus();
        editor.cursorPosition = (at === undefined || at < 0)
                                ? editor.length : Math.min(at, editor.length);
    }

    //: HIS WORDS BACK, after a ctrl+z cancelled the order they were sent as.
    //  The editor is opened with the sentence in it and the caret at the end,
    //  because the point of the key is that he edits it and sends it again.
    //
    //  `editor.text` is assigned, not only `draft`: typing in a TextEdit breaks
    //  the `text: box.draft` binding for good (Qt does that to every editable
    //  text item), so this box — the one call site that is never rebuilt — would
    //  otherwise keep whatever was in it when he pressed enter.
    function restore(body) {
        box.draftEdited(body);
        editor.text = body;
        box.beginEdit();
    }

    Component.onCompleted: if (box.openCaret >= 0) box.beginEdit(box.openCaret);

    Item {
        id: shown
        width: parent.width
        visible: !box.editing
        implicitHeight: Math.max(Theme.lineHeight + 6, msgText.implicitHeight + 6)
        // Fills the box, so a `minHeight` taller than the invitation gives the
        // whole of that area to the hover fill and the click target (§5.3 —
        // the target is the region, not the line of text in it).
        height: box.height

        Rectangle {
            anchors.fill: parent
            color: sma.containsMouse ? Theme.highlight : "transparent"
        }
        PixelText {
            id: caret
            x: 0
            y: 3
            color: box.fgDim
            text: ">"
        }
        Para {
            id: msgText
            x: caret.width + 8
            y: 3
            width: parent.width - x
            // A draft reads in the body tone; an invitation reads a rung down,
            // so an empty box never looks like something he already wrote.
            color: box.draft !== "" ? box.fgText : box.fgDim
            text: box.draft !== "" ? box.draft : box.placeholder
        }
        MouseArea {
            id: sma
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.IBeamCursor
            onClicked: box.beginEdit()
        }
    }

    Rectangle {
        id: editBox
        width: parent.width
        visible: box.editing
        implicitHeight: editor.implicitHeight + hint.height + 14
        height: box.height
        color: Theme.bgAlt
        radius: Theme.rounding
        border.width: Theme.ctrlBorder
        border.color: box.fgAccent

        TextEdit {
            id: editor
            x: 6
            y: 5
            width: parent.width - 12
            // No lineHeight/lineHeightMode: they are Text-only and assigning
            // them to a TextEdit is a component-creation ERROR, not a no-op
            // (§19.1) — the same recorded exception the decision editor and
            // painter's prompt box carry.
            // A whole QFont with NoAntialias pinned — NOT font.family/pixelSize
            // and NOT `antialiasing: false`. An editable item ignores those and
            // draws a scalable pixel font grey-fringed; only the font's style
            // strategy reaches the rasteriser (docs/DESIGN.md §2.2).
            font: (typeof DeskStyle !== "undefined" && DeskStyle
                       && typeof DeskStyle.editorFontForScale === "function")
                      ? DeskStyle.editorFontForScale(Screen.devicePixelRatio)
                      : Theme.editorFontForScale(Screen.devicePixelRatio)
            renderType: Text.NativeRendering
            color: box.fgText
            selectionColor: Theme.highlight
            selectedTextColor: Theme.accent
            selectByMouse: true
            wrapMode: TextEdit.Wrap
            text: box.draft
            onTextChanged: box.draftEdited(text)
            onActiveFocusChanged: if (activeFocus) box.caretHeld(cursorPosition);
            onCursorPositionChanged: if (activeFocus) box.caretHeld(cursorPosition);
            Keys.onPressed: (e) => {
                if (e.key === Qt.Key_Escape) {
                    box.editing = false;
                    box.caretLeft();
                    e.accepted = true;
                } else if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter)
                           && !(e.modifiers & Qt.ShiftModifier)) {
                    box.submitted(editor.text);
                    box.editing = false;
                    box.caretLeft();
                    e.accepted = true;
                }
            }
        }
        PixelText {
            id: hint
            x: 6
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 4
            color: box.fgDim
            text: box.hintText
        }
    }
}
