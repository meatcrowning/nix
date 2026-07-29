import QtQuick

// One decision from NEEDS YOU: the question, what it is about, the options he
// may tick, the line he may write his own answer on, and what happens if he
// never answers at all.
//
// THE ORDER IS THE POINT, and it is the file's own: options first, then his own
// words, then `if unanswered`. The store says "Free text always beats the
// options offered", so the answer field is never a fallback tucked under a
// fold — and the `if unanswered` line is drawn ALWAYS, in every state, because
// that sentence is the whole reason a question here can wait a week. This app
// does not badge, count or age anything; the calmest thing it can say about an
// open decision is exactly what the file already says.
//
// Everything is honest about what it will do (docs/DESIGN.md §10): the options
// are a RADIO — they are alternatives — so ticking one clears the others, and
// ticking the chosen one clears it, which is how he changes his mind without
// asking anyone. An item with no `>` line in the store gets no answer editor at
// all rather than an editor that would have nowhere to write.
Item {
    id: card

    property var decision: null
    property real cellW: 8
    property bool editing: false
    property string draft: ""            // typed, not yet committed
    property color fgAccent: Theme.accent
    property color fgText: Theme.text
    property color fgDim: Theme.textDim

    signal choose(int index, bool checked)
    signal commit(string body)
    signal draftEdited(string body)
    signal contextRequested(real mx, real my)

    readonly property bool answered: decision && decision.answered === true
    readonly property bool picked: {
        if (!decision)
            return false;
        for (var i = 0; i < decision.options.length; i++)
            if (decision.options[i].checked)
                return true;
        return false;
    }
    readonly property bool canAnswer: decision && decision.answerFrom >= 0
    readonly property bool hasDraft: draft !== "" && draft !== (decision ? decision.answer : "")

    implicitHeight: col.implicitHeight + 12
    height: implicitHeight

    function beginEdit() {
        if (!card.canAnswer)
            return;
        card.editing = true;
        editor.forceActiveFocus();
        editor.cursorPosition = editor.length;
    }

    // An answered item carries the 2px accent gutter §9.1 gives a current row —
    // used here for "you have said something about this", which is the one
    // thing worth marking. Nothing marks an UNanswered one: an open question is
    // the resting state of this file, not an exception to flag.
    Rectangle {
        width: 2
        height: parent.height - 8
        visible: card.answered
        color: card.fgAccent
    }

    MouseArea {                        // §7.1: every item is right-clickable
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        onClicked: (m) => {
            var p = mapToItem(null, m.x, m.y);
            card.contextRequested(p.x, p.y);
        }
    }

    Column {
        id: col
        x: 10
        width: parent.width - x

        // The title, and WHEN this went on the board — his: *"mesages in the
        // needs you section should all have the time they were placed on the
        // board indicated on them."*
        //
        // The time sits at the TRAILING EDGE in `dim` (§9.1: metadata clusters
        // there, a rung quieter than the line it belongs to), exactly as a
        // LANDED row's `when` does, so the question stays the thing the eye
        // lands on. Its width is a CHARACTER COUNT, not `implicitWidth`, and
        // the title RESERVES it whatever the item's age (§5.4) — so an item
        // that has no stamp and an item that gains one wrap identically and the
        // question text never moves under him.
        //
        // It is an absolute time and must stay one: no age, no "3 days ago",
        // no badge. `boardparse.format_placed` is the only formatter.
        Item {
            width: col.width
            implicitHeight: title.implicitHeight
            height: implicitHeight

            Para {
                id: title
                width: parent.width - (15 * card.cellW + 8)
                color: card.fgAccent
                text: (card.decision && card.decision.num ? card.decision.num + ". " : "")
                      + (card.decision ? card.decision.title : "")
            }
            PixelText {
                anchors.right: parent.right
                width: 15 * card.cellW      // `jul 29 11:04 pm`, the longest it gets
                horizontalAlignment: Text.AlignRight
                color: Theme.dim
                text: card.decision && card.decision.placed ? card.decision.placed : ""
            }
        }

        Item { width: 1; height: 4 }

        // what the decision is about, in the file's own words
        Repeater {
            model: card.decision ? card.decision.body : []
            delegate: Para {
                required property var modelData
                width: col.width
                color: card.fgDim
                text: (modelData.kind === "bullet" ? "- " : "") + modelData.text
                bottomPadding: 6
            }
        }

        // ---- the options ----
        Repeater {
            model: card.decision ? card.decision.options : []
            delegate: Item {
                id: opt
                required property var modelData
                required property int index
                width: col.width
                implicitHeight: label.implicitHeight
                height: implicitHeight

                Rectangle {
                    anchors.fill: parent
                    color: oma.containsMouse ? Theme.highlight : "transparent"
                }
                PixelText {
                    id: box
                    x: 0
                    y: 0
                    color: opt.modelData.checked ? card.fgAccent : card.fgDim
                    text: opt.modelData.checked ? "[x]" : "[ ]"
                }
                Para {
                    id: label
                    x: box.width + 8
                    y: 0
                    width: parent.width - x
                    // Once a choice is made the alternatives RECEDE a rung
                    // (§3.3's brightness ladder). They have to: body text on
                    // this desktop IS the accent (§3.1), so "chosen" cannot be
                    // said by making one label brighter — there is nothing
                    // brighter to go to. The ones not taken go quieter instead.
                    color: opt.modelData.checked || !card.picked ? card.fgText
                                                                 : card.fgDim
                    text: opt.modelData.label
                }
                MouseArea {
                    id: oma
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    // Clicking the chosen option clears it: a choice made here
                    // can be unmade here (§10.2), not only by editing the file.
                    onClicked: card.choose(opt.index, !opt.modelData.checked)
                }
            }
        }

        Item { width: 1; height: 6; visible: card.canAnswer }

        // ---- his own answer ----
        // Drawn whether or not there is one, because "none of these, do X" is a
        // valid answer to anything and it should never be the hidden option.
        Item {
            width: col.width
            visible: card.canAnswer
            implicitHeight: card.editing ? editBox.height : shown.height
            height: implicitHeight

            // resting: the answer, or an invitation that is not a demand
            Item {
                id: shown
                width: parent.width
                visible: !card.editing
                implicitHeight: Math.max(Theme.fontSize + 6, answerText.implicitHeight + 6)
                height: implicitHeight

                Rectangle {
                    anchors.fill: parent
                    color: ama.containsMouse ? Theme.highlight : "transparent"
                }
                PixelText {
                    id: caret
                    x: 0
                    y: 3
                    color: card.fgDim
                    text: ">"
                }
                Para {
                    id: answerText
                    x: caret.width + 8
                    y: 3
                    width: parent.width - x
                    color: card.hasDraft ? card.fgDim
                         : (card.decision && card.decision.answer !== "") ? card.fgText
                         : card.fgDim
                    text: card.hasDraft ? card.draft
                        : (card.decision && card.decision.answer !== "") ? card.decision.answer
                        : "your own answer"
                }
                MouseArea {
                    id: ama
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.IBeamCursor
                    onClicked: card.beginEdit()
                }
            }

            // editing: an inset box in the desktop's own text-field idiom
            // (bgAlt fill, 1px accent border — §7.2's modal spec, same as
            // reader's search chip).
            Rectangle {
                id: editBox
                width: parent.width
                visible: card.editing
                height: editor.implicitHeight + hint.height + 14
                color: Theme.bgAlt
                border.width: 1
                border.color: card.fgAccent

                TextEdit {
                    id: editor
                    x: 6
                    y: 5
                    width: parent.width - 12
                    // NOTE: no `lineHeight`/`lineHeightMode` here. They are
                    // Text-only properties; assigning them to a TextEdit is a
                    // component-creation ERROR, not a no-op — it is what made
                    // painter unable to load its QML at all (§19.1). So this
                    // one editor leads at Qt's rounded 16px rather than the
                    // 15px cell, the same recorded exception painter's prompt
                    // box carries.
                    font.family: Theme.font
                    font.pixelSize: Theme.fontSize
                    font.hintingPreference: Font.PreferFullHinting
                    renderType: Text.NativeRendering
                    color: card.fgText
                    selectionColor: Theme.highlight
                    selectedTextColor: Theme.accent
                    selectByMouse: true
                    wrapMode: TextEdit.Wrap
                    text: card.draft !== "" ? card.draft
                                            : (card.decision ? card.decision.answer : "")
                    onTextChanged: card.draftEdited(text)
                    Keys.onPressed: (e) => {
                        if (e.key === Qt.Key_Escape) {
                            // Leaves the editor and KEEPS what he typed. An
                            // unsaved sentence is never thrown away by this
                            // app — it is persisted and shown as a draft.
                            card.editing = false;
                            e.accepted = true;
                        } else if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter)
                                   && !(e.modifiers & Qt.ShiftModifier)) {
                            card.commit(editor.text);
                            card.editing = false;
                            e.accepted = true;
                        }
                    }
                }
                PixelText {
                    id: hint
                    x: 6
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 4
                    color: card.fgDim
                    text: "enter saves - shift+enter is a new line - esc keeps a draft"
                }
            }
        }

        // A draft says so, so nothing he typed can quietly look saved.
        PixelText {
            width: col.width
            visible: card.hasDraft && !card.editing
            height: visible ? implicitHeight : 0
            color: card.fgDim
            text: "  (a draft, not written to board.md yet)"
        }

        Item { width: 1; height: 6 }

        // The reassurance, from the file. Never hidden, never abbreviated.
        Para {
            width: col.width
            visible: text !== ""
            height: visible ? implicitHeight : 0
            color: card.fgDim
            text: card.decision && card.decision.ifUnanswered !== ""
                  ? "if unanswered: " + card.decision.ifUnanswered : ""
        }
    }
}
