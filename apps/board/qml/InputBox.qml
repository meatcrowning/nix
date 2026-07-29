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

    implicitHeight: editing ? editBox.height : shown.height
    height: implicitHeight

    function beginEdit() {
        box.editing = true;
        editor.forceActiveFocus();
        editor.cursorPosition = editor.length;
    }

    Item {
        id: shown
        width: parent.width
        visible: !box.editing
        implicitHeight: Math.max(Theme.fontSize + 6, msgText.implicitHeight + 6)
        height: implicitHeight

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
        height: editor.implicitHeight + hint.height + 14
        color: Theme.bgAlt
        border.width: 1
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
            font.family: Theme.font
            font.pixelSize: Theme.fontSize
            font.hintingPreference: Font.PreferFullHinting
            renderType: Text.NativeRendering
            color: box.fgText
            selectionColor: Theme.highlight
            selectedTextColor: Theme.accent
            selectByMouse: true
            wrapMode: TextEdit.Wrap
            text: box.draft
            onTextChanged: box.draftEdited(text)
            Keys.onPressed: (e) => {
                if (e.key === Qt.Key_Escape) {
                    box.editing = false;
                    e.accepted = true;
                } else if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter)
                           && !(e.modifiers & Qt.ShiftModifier)) {
                    box.submitted(editor.text);
                    box.editing = false;
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
