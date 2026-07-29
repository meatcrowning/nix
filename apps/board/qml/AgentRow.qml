import QtQuick

// One agent's card: what it was asked to do, WHAT IT SAYS it is doing, WHAT IT
// IS OBSERVED DOING, and the box he types into to reach it.
//
// THE TWO LINES ARE THE POINT, and they are his call — *"i want both. i want
// what its saying its doing and what its actually doing"*. They are two plain
// SENTENCES, led by the agent's own name, because that is how he asked to read
// them: *"[agent name] is [what the agent says its doing] and then the line
// below should be the [agent name] is actually [what it is actualy doing]"*.
// The bare words `says` and `doing` in a label column beside the two texts are
// what that replaced.
//
//   ...is...           the agent's own words (`boardctl.py phase`). Carries the
//                      OBJECT — "the vtbclient parser" — which watching tool
//                      calls can never give. Absent until it says something;
//                      absence is drawn as absence.
//   ...is actually...  derived from the tool calls in its live transcript
//                      (`boardphase.py`). Carries the VERB — "editing
//                      Main.qml" — and cannot be faked, forgotten or left
//                      stale.
//
// **Both sentences are built in `boardphase.py` (`says_line`/`doing_line`), not
// here**, because the joining is a judgement about the real strings rather than
// string concatenation: an agent that named no phase is quoted instead of
// forced after "is", and a STOPPED agent goes into the past tense — *"Marbas is
// actually ..."* is false about a process that is gone, and *"was last seen
// ..."* is the honest form of the same fact.
//
// **Neither is ever shown as the other, and neither is ever filled in from the
// other.** The second sentence is the OBSERVED one, so an agent claiming
// *testing* while it edits says *testing* on one line and *is actually editing
// Main.qml* on the next. That divergence is information he asked to be able to
// see: it is not an error, so there is no warning, no badge and nothing from
// the warn/crit ramp — which on this desktop means a machine fault (§8.1,
// §9.3), not an agent being optimistic about itself. Two true statements,
// drawn plainly.
//
// There are no phase headings over these cards any more, and no sections at
// all: one flat list, oldest first (`boardwork.cards()`), so a card does not
// move when the agent picks up a different tool.
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
    // WHO IT IS, in one short name — his call: *"i think itd be
    // interesting to have them referred to by regular names"*. The coded id is
    // still the key underneath (the inbox this card's box writes to is named by
    // it, and so are the unit and the log), and it is deliberately NOT drawn:
    // there is nothing he can do with a hex string on screen, and the name is
    // the thing he can type back at the machine.
    readonly property string name: agent && agent.name ? agent.name : ""
    readonly property var waiting: agent && agent.waiting ? agent.waiting : []
    readonly property string says: agent && agent.says ? agent.says : ""
    readonly property string actually: agent && agent.actually ? agent.actually : ""
    // The two sentences, as `boardphase.py` phrased them. Empty means there is
    // nothing honest to say, and empty is then drawn as nothing at all.
    readonly property string saysLine: agent && agent.saysLine ? agent.saysLine : ""
    readonly property string doingLine: agent && agent.doingLine ? agent.doingLine : ""
    // A card with no id is not an agent — it is a task waiting for a slot, or
    // the section's own box. It gets no inbox, because there is nothing running
    // to put a message in front of.
    readonly property bool addressable: agent && agent.id !== undefined
                                        && String(agent.id) !== ""
    // The process-level sentence earns its line only when it has something to
    // say — and with the phase headings gone it is what states the two
    // conditions that were headings: a task nobody has started yet, and one
    // whose agent has stopped. For an ordinary running agent the two sentences
    // above have already said everything, and a third dim line repeating "it
    // reads its inbox between steps" under every card is the noise §5.2 calls a
    // defect.
    readonly property bool showDetail: agent && (!running || waiting.length > 0
                                                 || agent.kind === "pending")
    // The name gets a cell of its own ONLY when neither sentence below is
    // going to say it — a stopped agent nothing was ever seen doing, or a
    // queued task with no name at all. Otherwise it would be drawn three times
    // in four lines. (`boardagents.NAMES`' width rule is this column's.)
    readonly property bool nameNeeded: name !== "" && saysLine === ""
                                       && doingLine === ""

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
        // The name is normally NOT drawn here: it is the subject of both
        // sentences below, and repeating it in a column of its own would say it
        // three times. It comes back in its 7-cell column for a card that has
        // no sentence to carry it, so nothing on this list is ever anonymous.
        Item {
            width: col.width
            implicitHeight: titleT.implicitHeight
            height: implicitHeight

            readonly property bool wide: width > 56 * row.cellW
            readonly property real whereW: wide && row.agent && row.agent.where !== ""
                ? Math.min(row.agent.where.length * row.cellW + 2, width * 0.4)
                : 0
            readonly property real nameW: row.nameNeeded ? 7 * row.cellW : 0

            PixelText {
                id: nameT
                x: 0
                y: 0
                visible: row.nameNeeded
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

        // ---- "<name> is <what it says it is doing>" ----
        // Its own words. Drawn only when there are some: an agent that has not
        // said anything is silent, and manufacturing a claim out of the
        // observation below would make the two agree by construction and throw
        // away the only thing having two of them buys.
        //
        // It sits a rung quieter than the line under it (§3.3): the
        // observation is the load-bearing fact and this is somebody's account
        // of themselves.
        Para {
            id: saysT
            width: col.width
            visible: row.saysLine !== ""
            height: visible ? implicitHeight : 0
            color: Theme.dim
            text: row.saysLine
        }

        // ---- "<name> is actually <what it is observed doing>" ----
        // Observed, never the claim. When it cannot be observed it says that
        // ("board cannot see what it is doing", "has actually done nothing
        // recently") rather than quietly falling back to the line above —
        // §10's rule, and the reason there are two lines at all. Past tense
        // once the process is gone, and nothing at all when a stopped agent
        // was never seen doing anything: `boardphase.doing_line` decides both,
        // and hands this an empty string to say so.
        Para {
            id: doingT
            width: col.width
            visible: row.doingLine !== ""
            height: visible ? implicitHeight : 0
            color: row.fgDim
            text: row.doingLine
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
