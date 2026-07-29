import QtQuick

// One agent that is running right now, and the box he types into to reach it.
//
// WHAT THIS ROW MAY AND MAY NOT SAY (docs/DESIGN.md §10, and `boardagents.py`'s
// docstring, which is the authority on all of it):
//
//   * **It never claims delivery it cannot prove.** A note he sends sits under
//     the row saying `waiting in its inbox` until the agent actually takes it,
//     because an agent's stdin is closed and the only honest statement is
//     "the file is there".
//   * **A finished agent is gone from the list; a failed one says so in
//     WORDS.** `exited without finishing` is the label, in the dim rung — never
//     the warn/crit ramp, which on this desktop means a machine fault (§8.1,
//     §9.3) and not a subprocess that died.
//   * **Nothing counts and nothing ages.** No elapsed time, no "started at", no
//     number of steps. Same requirement as the rest of this app: a running
//     agent is just running.
//
// The one mark is §9.1's 2px accent gutter, for the same thing it means on an
// answered decision — this row is current. An exited one loses it, which is the
// second half of §3.5's "say the state twice".
Item {
    id: row

    property var agent: null
    property real cellW: 8
    property bool editing: false
    property string draft: ""
    property color fgAccent: Theme.accent
    property color fgText: Theme.text
    property color fgDim: Theme.textDim

    signal send(string body)
    signal draftEdited(string body)
    signal contextRequested(real mx, real my)

    readonly property bool running: agent && agent.running === true
    readonly property var waiting: agent && agent.waiting ? agent.waiting : []

    implicitHeight: col.implicitHeight + 8
    height: implicitHeight

    function beginEdit() {
        row.editing = true;
        editor.forceActiveFocus();
        editor.cursorPosition = editor.length;
    }

    Rectangle {
        width: 2
        height: parent.height - 6
        visible: row.running
        color: row.fgAccent
    }

    MouseArea {                          // §7.1: every row is right-clickable
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        onClicked: (m) => {
            var p = mapToItem(null, m.x, m.y);
            row.contextRequested(p.x, p.y);
        }
    }

    Column {
        id: col
        x: 10
        width: parent.width - x

        // title left, where right — the flight row's shape, so the two live
        // sections read the same way one under the other. The `where` column
        // drops widest-first as the window narrows (§9.1), at width 0.
        Item {
            width: col.width
            implicitHeight: titleT.implicitHeight
            height: implicitHeight

            readonly property bool wide: width > 56 * row.cellW
            readonly property real whereW: wide && row.agent && row.agent.where !== ""
                ? Math.min(row.agent.where.length * row.cellW + 2, width * 0.4)
                : 0

            PixelText {
                id: whereT
                anchors.right: parent.right
                y: 0
                width: parent.whereW
                horizontalAlignment: Text.AlignRight
                elide: Text.ElideLeft
                color: row.fgDim
                text: row.agent ? row.agent.where : ""
            }
            Para {
                id: titleT
                x: 0
                y: 0
                width: parent.width - whereT.width - (whereT.width > 0 ? 8 : 0)
                color: row.running ? row.fgText : row.fgDim
                text: row.agent ? row.agent.title : ""
            }
        }

        // What is actually known about it, in words. This is the whole
        // running/failed distinction.
        Para {
            width: col.width
            color: Theme.dim
            text: row.agent ? row.agent.detail : ""
        }

        // Anything he has already sent that has NOT been read yet. It stays on
        // screen until the agent takes it or the watcher moves it to the queue,
        // so a note can never quietly disappear between the two.
        Repeater {
            model: row.waiting
            delegate: Para {
                required property var modelData
                width: col.width
                color: row.fgDim
                text: "  waiting in its inbox: " + modelData
            }
        }

        Item { width: 1; height: 4 }

        // ---- the box ----
        // Same idiom as a decision's answer editor: a resting invitation that
        // is not a demand, and an inset bgAlt field with a 1px accent border
        // when it is open (§7.2).
        Item {
            width: col.width
            implicitHeight: row.editing ? editBox.height : shown.height
            height: implicitHeight

            Item {
                id: shown
                width: parent.width
                visible: !row.editing
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
                    color: row.fgDim
                    text: ">"
                }
                Para {
                    id: msgText
                    x: caret.width + 8
                    y: 3
                    width: parent.width - x
                    color: row.fgDim
                    text: row.draft !== "" ? row.draft
                        : row.running ? "send it a command, an idea or a fix"
                                      : "leave a note - it goes to the next agent"
                }
                MouseArea {
                    id: sma
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.IBeamCursor
                    onClicked: row.beginEdit()
                }
            }

            Rectangle {
                id: editBox
                width: parent.width
                visible: row.editing
                height: editor.implicitHeight + hint.height + 14
                color: Theme.bgAlt
                border.width: 1
                border.color: row.fgAccent

                TextEdit {
                    id: editor
                    x: 6
                    y: 5
                    width: parent.width - 12
                    // No lineHeight/lineHeightMode: they are Text-only and
                    // assigning them to a TextEdit is a component-creation
                    // ERROR, not a no-op (§19.1). Same recorded exception the
                    // decision editor carries.
                    font.family: Theme.font
                    font.pixelSize: Theme.fontSize
                    font.hintingPreference: Font.PreferFullHinting
                    renderType: Text.NativeRendering
                    color: row.fgText
                    selectionColor: Theme.highlight
                    selectedTextColor: Theme.accent
                    selectByMouse: true
                    wrapMode: TextEdit.Wrap
                    text: row.draft
                    onTextChanged: row.draftEdited(text)
                    Keys.onPressed: (e) => {
                        if (e.key === Qt.Key_Escape) {
                            // Keeps what he typed, exactly like the answer
                            // editor. Nothing in this app throws away a
                            // sentence he wrote.
                            row.editing = false;
                            e.accepted = true;
                        } else if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter)
                                   && !(e.modifiers & Qt.ShiftModifier)) {
                            row.send(editor.text);
                            row.editing = false;
                            e.accepted = true;
                        }
                    }
                }
                PixelText {
                    id: hint
                    x: 6
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 4
                    color: row.fgDim
                    text: "enter sends - shift+enter is a new line - esc keeps a draft"
                }
            }
        }
    }
}
