import QtQuick
// `Motion` — the desktop's one duration and curve, for the tick on the observed
// line. Nothing here writes a duration of its own (§6.2).
import "../../qmlcommon"

// One agent's card: WHAT IT SAYS it is doing, WHAT IT IS OBSERVED DOING, what
// it was asked to do, and the box he types into to reach it.
//
// THE TWO LINES ARE THE POINT, and they are his call — *"i want both. i want
// what its saying its doing and what its actually doing"*. The first is a plain
// SENTENCE led by the agent's own name, because that is how he asked to read it:
// *"[agent name] is [what the agent says its doing]"*. The bare words `says`
// and `doing` in a label column beside the two texts are what that replaced.
//
// **The second line is the description ALONE** — his call, 2026-07-29:
// *"actually just take out the [agent] is actually and just display the text
// after it"*. So it reads `editing Main.qml`, not *"Marbas is actually editing
// Main.qml"*. The name is already the subject of the line above it, and a card
// that said it twice was the repeated metadata docs/DESIGN.md §9.1 rules out.
//
// **The two lines come FIRST, and the title row is the THIRD** — his call
// again, in as many words: *"the very first line of an agent in the agent
// section should be the [name] is [what the agent says theyre doing]. the
// second line should be [name] is actually doing XYZ. the third line should be
// what the current first line is"*. What a card is FOR is the live pair; the
// brief it was handed and the `where` it works in never change for the life of
// the agent, so they sit UNDER the two lines that do.
//
//   <name> is ...      the agent's own words (`boardctl.py phase`). Carries the
//                      OBJECT — "the vtbclient parser" — which watching tool
//                      calls can never give. Absent until it says something;
//                      absence is drawn as absence. The right end of this row
//                      — the card's top row — carries `62k/200k`, how much
//                      context the agent is standing in against what it holds
//                      (`boardphase.context_line`, measured out of the
//                      transcript's own `usage` stamps, absent when nothing
//                      could be measured).
//   <the description>  derived from the tool calls in its live transcript
//                      (`boardphase.py`). Carries the VERB — "editing
//                      Main.qml" — and cannot be faked, forgotten or left
//                      stale. No subject, no opener, and a ticking `...` on
//                      the end of it while that is happening NOW (`liveDots`
//                      below, which is the only moving thing on the card).
//
// **Both lines are built in `boardphase.py` (`says_line`/`doing_line`), not
// here**, because the joining is a judgement about the real strings rather than
// string concatenation: an agent that named no phase is quoted instead of
// forced after "is", and a STOPPED agent goes into the past tense — with no
// subject on the line there is nowhere else for the tense to live, so *"last
// seen editing Main.qml"* is the honest form of the same fact.
//
// **Neither is ever shown as the other, and neither is ever filled in from the
// other.** The second line is the OBSERVED one, so an agent claiming
// *testing* while it edits says *testing* on one line and *editing
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
// The ladder does the rest, and the reorder RETUNED it (§10.6): **the lead
// tone goes to whichever of the three lines is actually drawn first**, so a
// card never opens on its quietest text. Ordinarily that is `says`, at
// `fgText`; `doing` keeps the ordinary secondary tone under it; and the title
// row — the standing brief, unchanged since the agent was handed it — drops to
// `Theme.dim` now that it is third.
//
// It reads the other way round when it has to: a card with no claim leads with
// `doing`, and a card with neither sentence leads with the title row, which is
// the case the name column exists for. Position, not trust, picks the tone —
// the old order had `says` a rung quieter than `doing` for being somebody's
// account of themselves, and that reading would now make the first line of
// every card the dimmest thing on it. §10.6's rule is that neither side is
// filled in from the other; it was never that one outranks the other.
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
    // Which of `boardphase.observe`'s four outcomes the line above came from.
    // Only `ok` is something actually happening right now, which is what the
    // ticking dots below are allowed to claim.
    readonly property string observed: agent && agent.observed ? agent.observed : ""
    // HOW FULL IT IS — `62k/200k`, at the right end of the card's TOP row, his
    // call: *"on the very right of the top row of the agent's information box
    // it should keep a running tally of how much context that agent has vs how
    // much it can handle"*. Already formatted by `boardphase.context_line`;
    // empty means nothing could be measured, and empty is drawn as nothing.
    readonly property string contextLine: agent && agent.contextLine
                                          ? agent.contextLine : ""
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
    // The title row is the card's THIRD line — unless there is no sentence
    // above it to be third to. Both the name column and the tone ladder hang
    // off that one condition.
    readonly property bool titleFirst: saysLine === "" && doingLine === ""
    // The name gets a cell of its own ONLY when no line ABOVE it is going to
    // say it — otherwise it would be drawn three times in four lines.
    // (`boardagents.NAMES`' width rule is this column's.)
    //
    // That is now the CLAIM alone: since the observed line dropped its
    // *"<name> is actually"* opener it names nobody, so a card whose agent has
    // said nothing would be anonymous without this — which is the one thing
    // this list may never be. It is drawn on the title row either way; the
    // title row just is not always that card's top line any more.
    readonly property bool nameNeeded: name !== "" && saysLine === ""
    // The lead tone, for whichever line is drawn first. A stopped agent leads
    // at `fgDim` rather than `fgText` — that was already how the title row
    // said "this one is over", and it is one rung, not a colour (§3.5's job is
    // done by the words in the detail line).
    readonly property color leadTone: running ? fgText : fgDim

    // ---- the tick on the end of the observed line ----
    // His: *"at the end of the second row of an agents information, it should
    // have an animated elipsies to show its currently happening"*. So the
    // observed line ends in `.`, `..`, `...`, cycling, and the card reads as
    // live without a number anywhere on it.
    //
    // **It is drawn HERE and not in `doing_line()`**, which builds prose: an
    // animated suffix is not prose, it is presentation, and putting it in the
    // Python would mean the sentence a test asserts on changed four times a
    // second and the model re-emitted on a timer.
    //
    // **It claims only what is true.** `ok` is the one observed state that
    // means a tool call happened recently; `nothing recently`, `nothing yet`
    // and the unlinked line are the states where something is NOT happening, so
    // they get no tick — an animation over those would be the dishonest
    // affordance §10 forbids, and a stopped agent's past-tense line likewise.
    //
    // ASCII dots, never U+2026 (§2.3), and the field is **always three cells
    // wide** — the trailing spaces are what stop the line reflowing under a
    // wrap as the dots cycle, exact because the font is monospace (§2.7).
    readonly property bool ticking: running && observed === "ok" && doingLine !== ""
    property int dotPhase: 0
    readonly property string liveDots: {
        if (!ticking)
            return ""
        // Reduced motion still says the line is live; it just stops moving.
        if (motion.reduceMotion)
            return "..."
        return [".  ", ".. ", "..."][dotPhase % 3]
    }
    // One step per desktop slide (§6.2's own number, through `ms()` so the
    // panel's motion settings reach it) — about a second for the full cycle,
    // which is quiet enough to sit on every running card at once.
    Motion { id: motion }
    Timer {
        interval: Math.max(60, motion.ms(motion.slideMs))
        running: row.ticking && !motion.reduceMotion && row.visible
        repeat: true
        onTriggered: row.dotPhase = (row.dotPhase + 1) % 3
    }

    // Cut a string to `cells` characters, marking the cut with ASCII "..." —
    // never the unicode ellipsis, which is a hardcoded UI string and therefore
    // ASCII by rule (docs/DESIGN.md §2.3). A width in characters is exact here
    // because the font is monospace (§2.7). Under about a dozen cells there is
    // no honest truncation left to draw, so it gives back the marker alone
    // rather than one letter and a stub.
    function clipTo(s, cells) {
        if (cells < 4)
            return "..."
        return s.length <= cells ? s : s.slice(0, cells - 3) + "..."
    }

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

    // ---- HOW FULL IT IS, at the right end of the TOP row ----
    // His call, and it is standing metadata rather than an alert: one dim
    // string that carries its own denominator, so it needs no legend (§10.5)
    // and no ramp — a full context is not a machine fault, which is the only
    // thing warn/crit may mean here (§8.1, §9.3). It clusters at the trailing
    // edge with the other trailing metadata (§9.1), and the line it shares
    // reserves the width, so nothing reflows when the number changes.
    //
    // It rides whichever line is the card's OWN top row, and a card with no
    // line above the title row gets none at all: that row's right edge already
    // belongs to `where`, and two things in one corner is worse than a tally
    // that waits.
    PixelText {
        id: tallyT
        readonly property bool onDoing: row.saysLine === ""
        visible: row.contextLine !== ""
                 && (row.saysLine !== "" || row.doingLine !== "")
        anchors.right: col.right
        y: 0
        color: Theme.dim
        text: row.contextLine
    }

    Column {
        id: col
        x: 10
        width: parent.width - x

        // ---- FIRST LINE: "<name> is <what it says it is doing>" ----
        // Its own words. Drawn only when there are some: an agent that has not
        // said anything is silent, and manufacturing a claim out of the
        // observation below would make the two agree by construction and throw
        // away the only thing having two of them buys.
        //
        // It takes the lead tone because it is the card's top line, not
        // because a claim outranks an observation — see the ladder note at the
        // top of this file. An agent that has said nothing yields the lead to
        // the line under it.
        Para {
            id: saysT
            width: col.width - (tallyT.visible && !tallyT.onDoing
                                ? tallyT.width + 8 : 0)
            visible: row.saysLine !== ""
            height: visible ? implicitHeight : 0
            color: row.leadTone
            text: row.saysLine
        }

        // ---- SECOND LINE: what it is observed doing, and nothing else ----
        // No subject and no *"is actually"* opener: the description alone, his
        // call. Observed, never the claim. When it cannot be observed it says
        // that ("board cannot see what it is doing", "nothing
        // recently") rather than quietly falling back to the line above —
        // §10's rule, and the reason there are two lines at all. Past tense
        // once the process is gone, and nothing at all when a stopped agent
        // was never seen doing anything: `boardphase.doing_line` decides both,
        // and hands this an empty string to say so.
        Para {
            id: doingT
            width: col.width - (tallyT.visible && tallyT.onDoing
                                ? tallyT.width + 8 : 0)
            visible: row.doingLine !== ""
            height: visible ? implicitHeight : 0
            color: row.saysLine === "" ? row.leadTone : row.fgDim
            text: row.doingLine + row.liveDots
        }

        // ---- THIRD LINE ----
        // name left, title, where right — the flight row's shape, so the two
        // live sections read the same way one under the other. The `where`
        // column drops widest-first as the window narrows (§9.1), at width 0.
        //
        // It is LAST of the three: what the agent was handed, and where it
        // works, are fixed for the life of the card, and the two lines above
        // are the ones worth re-reading. So it takes the quiet tone — except on
        // a card with no sentence above it at all, where it IS the top line and
        // takes the lead one.
        //
        // The name is normally NOT drawn here: it is the subject of both
        // sentences above, and repeating it in a column of its own would say it
        // three times. It comes back in its 7-cell column for a card that has
        // no sentence to carry it, so nothing on this list is ever anonymous —
        // which is the same condition, `row.titleFirst`.
        Item {
            width: col.width
            implicitHeight: titleT.implicitHeight
            height: implicitHeight

            readonly property bool wide: width > 56 * row.cellW
            readonly property real whereW: wide && row.agent && row.agent.where !== ""
                ? Math.min(row.agent.where.length * row.cellW + 2, width * 0.4)
                : 0
            // 7 cells for a six-character pool name plus its space — and it
            // MEASURES rather than assuming, because one name is longer than
            // the pool allows: the orchestrator is always `Solomon`, seven
            // characters, and truncating the one row he asked to have pinned
            // at the top would be the worst possible place to elide. Nothing
            // is drawn between this column and the title, so widening it costs
            // the title one cell on that card and nothing anywhere else.
            readonly property real nameW: row.nameNeeded
                ? Math.max(7, row.name.length + 1) * row.cellW : 0

            PixelText {
                id: nameT
                x: 0
                y: 0
                visible: row.nameNeeded
                // Same rung as the rest of its row: lead tone when the title
                // row IS the top line, the quiet one when it is the third.
                color: row.titleFirst ? row.leadTone : Theme.dim
                text: row.name
            }

            PixelText {
                id: whereT
                anchors.right: parent.right
                y: 0
                width: parent.whereW
                horizontalAlignment: Text.AlignRight
                elide: Text.ElideLeft
                color: row.titleFirst ? row.fgDim : Theme.dim
                text: row.agent ? row.agent.where : ""
            }
            Para {
                id: titleT
                x: parent.nameW
                y: 0
                width: parent.width - x - whereT.width - (whereT.width > 0 ? 8 : 0)
                color: row.titleFirst ? row.leadTone : Theme.dim
                text: row.agent ? row.agent.title : ""
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
        //
        // ONE LINE EACH, and the message is cut to fit it. He types whole
        // paragraphs into that box; wrapped in full they buried the three lines
        // the card is actually for under somebody's own words (§5.2 — the card
        // is a status readout, not a transcript). The label stays whole, so
        // what is cut is only the body, and nothing is lost: `boardctl.py inbox
        // take` hands the agent the untouched text.
        Repeater {
            model: row.waiting
            delegate: PixelText {
                required property var modelData
                readonly property string label: "  waiting in its inbox: "
                width: col.width
                // No wrap and no `elide`: Qt elides with U+2026, and a
                // hardcoded marker on this desktop is ASCII (§2.3). The font is
                // monospace, so a character count is an exact width (§2.7) —
                // the same reasoning the `where` columns size themselves by.
                wrapMode: Text.NoWrap
                clip: true
                color: row.fgDim
                text: label + row.clipTo(String(modelData),
                                         Math.floor(width / row.cellW)
                                         - label.length)
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
