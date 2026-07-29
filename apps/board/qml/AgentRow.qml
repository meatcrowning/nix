import QtQuick

// One agent's card: what it was asked to do, WHAT IT SAYS it is doing, WHAT IT
// IS OBSERVED DOING, and the box he types into to reach it.
//
// THE TWO LINES ARE THE POINT, and they are his call — *"i want both. i want
// what its saying its doing and what its actually doing"*:
//
//   says:   the agent's own words (`boardctl.py phase`). Carries the OBJECT —
//           "the vtbclient parser" — which watching tool calls can never give.
//           Absent until it says something; absence is drawn as absence.
//   doing:  derived from the tool calls in its live transcript
//           (`boardphase.py`). Carries the VERB — "editing Main.qml" — and
//           cannot be faked, forgotten or left stale.
//
// **Neither is ever shown as the other, and neither is ever filled in from the
// other.** The card is filed under the section its OBSERVED phase names, so an
// agent claiming `testing` while it edits appears under *coding*, saying
// *testing*. That divergence is information he asked to be able to see: it is
// not an error, so there is no warning, no badge and nothing from the warn/crit
// ramp — which on this desktop means a machine fault (§8.1, §9.3), not an agent
// being optimistic about itself. Two true statements, drawn plainly.
//
// The ladder does the rest (§3.3): `doing` is the load-bearing fact and takes
// the ordinary secondary tone; `says` sits a rung quieter, because it is
// somebody's account of themselves.
//
// WHAT THIS CARD STILL MAY NOT SAY (docs/DESIGN.md §10, and `boardagents.py`'s
// docstring):
//
//   * **It never claims delivery it cannot prove.** A note he sends sits under
//     the card saying `waiting in its inbox` until the agent actually takes it.
//   * **A failed agent says so in WORDS**, never in a colour.
//   * **Nothing counts and nothing ages.** No elapsed time, no "started at", no
//     step count — including on the quiet line, which says "nothing recently"
//     and never how long ago.
//
// The one mark is §9.1's 2px accent gutter, for the same thing it means on an
// answered decision: this row is current.
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
    // WHO IT IS, in one ordinary first name — his call: *"i think itd be
    // interesting to have them referred to by regular names"*. The coded id is
    // still the key underneath (the inbox this card's box writes to is named by
    // it, and so are the unit and the log), and it is deliberately NOT drawn:
    // there is nothing he can do with a hex string on screen, and the name is
    // the thing he can type back at the machine.
    readonly property string name: agent && agent.name ? agent.name : ""
    readonly property var waiting: agent && agent.waiting ? agent.waiting : []
    readonly property string says: agent && agent.says ? agent.says : ""
    readonly property string actually: agent && agent.actually ? agent.actually : ""
    // A card with no id is not an agent — it is a task waiting for a slot, or
    // the section's own box. It gets no inbox, because there is nothing running
    // to put a message in front of.
    readonly property bool addressable: agent && agent.id !== undefined
                                        && String(agent.id) !== ""
    // The process-level sentence earns its line only when it has something to
    // say. For an ordinary running agent the group heading and the two lines
    // above have already said everything, and a third dim line repeating "it
    // reads its inbox between steps" under every card is the noise §5.2 calls a
    // defect.
    readonly property bool showDetail: agent && (!running || waiting.length > 0
                                                 || agent.kind === "pending")
    // Something was genuinely seen in its transcript. When nothing was AND the
    // agent has stopped, the observed line is dropped rather than drawn in the
    // past tense about a thing that never happened.
    readonly property bool seen: agent && (agent.observed === "ok"
                                           || agent.observed === "quiet")

    implicitHeight: col.implicitHeight + 8
    height: implicitHeight

    function beginEdit() { msgBox.beginEdit(); }

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

        // name left, title, where right — the flight row's shape, so the two
        // live sections read the same way one under the other. The `where`
        // column drops widest-first as the window narrows (§9.1), at width 0.
        //
        // The name sits in the SAME 7-cell label column as `says` and `doing`
        // below it, so the three lines of a card line up as one block and the
        // name reads as the subject of both sentences under it. It takes the
        // title's own colour: it is part of that line, not a second tier, and
        // §3.3's ladder is already carrying the says/doing distinction.
        Item {
            width: col.width
            implicitHeight: titleT.implicitHeight
            height: implicitHeight

            readonly property bool wide: width > 56 * row.cellW
            readonly property real whereW: wide && row.agent && row.agent.where !== ""
                ? Math.min(row.agent.where.length * row.cellW + 2, width * 0.4)
                : 0
            readonly property real nameW: row.name !== "" ? 7 * row.cellW : 0

            PixelText {
                id: nameT
                x: 0
                y: 0
                visible: row.name !== ""
                color: row.running ? row.fgText : row.fgDim
                text: row.name
            }

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
                x: parent.nameW
                y: 0
                width: parent.width - x - whereT.width - (whereT.width > 0 ? 8 : 0)
                color: row.running ? row.fgText : row.fgDim
                text: row.agent ? row.agent.title : ""
            }
        }

        // ---- what it SAYS ----
        // Its own words. Drawn only when there are some: an agent that has not
        // said anything is silent, and manufacturing a claim out of the
        // observation below would make the two agree by construction and throw
        // away the only thing having two of them buys.
        Item {
            width: col.width
            visible: row.says !== ""
            implicitHeight: visible ? saysT.implicitHeight : 0
            height: implicitHeight
            PixelText {
                id: saysLabel
                x: 0
                color: Theme.dim
                text: "says"
            }
            Para {
                id: saysT
                x: 7 * row.cellW
                width: parent.width - x
                color: Theme.dim
                text: row.says
            }
        }

        // ---- what it is ACTUALLY doing ----
        // Observed, never the claim. When it cannot be observed it says that
        // ("cannot read its transcript", "nothing recently") rather than
        // quietly falling back to the line above — §10's rule, and the reason
        // there are two lines at all.
        Item {
            width: col.width
            visible: row.actually !== "" && (row.running || row.seen)
            implicitHeight: visible ? doingT.implicitHeight : 0
            height: implicitHeight
            PixelText {
                id: doingLabel
                x: 0
                color: row.fgDim
                // Present tense only while the process is there. A stopped
                // agent's last observed action is evidence, not activity, and
                // saying `doing` over it would be this card's one dishonest
                // word.
                text: row.running ? "doing" : "last"
            }
            Para {
                id: doingT
                x: 7 * row.cellW
                width: parent.width - x
                color: row.fgDim
                text: row.actually
            }
        }

        // The process-level fact, in words: gone, hand-started, or holding an
        // unread note. This is the running/failed distinction, and it is words
        // and not colour (§3.5).
        Para {
            width: col.width
            visible: row.showDetail && row.agent && row.agent.detail !== ""
            height: visible ? implicitHeight : 0
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

        Item { width: 1; height: 4; visible: row.addressable }

        // ---- the box ----
        // §10 again: a task that has not started has no process to put a
        // message in front of, so it is not offered one.
        InputBox {
            id: msgBox
            width: col.width
            visible: row.addressable
            height: visible ? implicitHeight : 0
            draft: row.draft
            fgAccent: row.fgAccent
            fgText: row.fgText
            fgDim: row.fgDim
            // ...and it says WHO it reaches. `send Rosa a command` is the whole
            // point of the name: the box under a card has always gone to that
            // one agent's inbox, and until now it said `it`.
            placeholder: row.running
                ? "send " + (row.name !== "" ? row.name : "it")
                  + " a command, an idea or a fix"
                : "leave a note - it goes to the next agent"
            onDraftEdited: (b) => row.draftEdited(b)
            onSubmitted: (b) => row.send(b)
        }
    }
}
