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
// after it"*. So UNDER A CLAIM it reads `editing Main.qml`, not *"Marbas is
// actually editing Main.qml"*. The name is already the subject of the line
// above it, and a card that said it twice was the repeated metadata
// docs/DESIGN.md §9.1 rules out.
//
// **But when the observed line LEADS the card — no claim above it — it keeps
// the name on the top line** [his, 2026-08-01]: the card used to drop its name
// the moment activity was reported and that subjectless line took the lead. So
// a claimless active card reads *"Marbas is editing Main.qml..."*, name and
// all (`boardphase.doing_line`'s `lead`). It is drawn once, never twice — the
// 7-cell name column below only appears when NO sentence names the agent.
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
//                      stale. No subject, no opener, and NO dots on the end of
//                      it: the one ticking `...` on a card is on its TOP line,
//                      and no other line may have one at all.
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
// `doing` — which then opens with the agent's name (above) — and a card with
// neither sentence leads with the title row, which is the case the name column
// exists for. Position, not trust, picks the tone —
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

    //: the RIGHT-CLICK box. The card no longer carries a resting text field —
    //  his call — so `msgBox` below is CLOSED unless `beginSend()` revealed it
    //  from the row's context menu, and it closes again when he submits or
    //  leaves. The window still keys the draft and the caret by the agent's id
    //  (`Main.qml`'s `draftOf`/`caretOf`), so a rebuild in mid-sentence comes
    //  back with the box open and his caret where he left it.
    property bool composing: false

    signal send(string body)
    signal draftEdited(string body)
    //: passed straight through to the box — see `InputBox.qml`. A card is
    //  rebuilt when an agent joins or leaves the list, and his half-typed
    //  command must come back with the caret in it.
    signal caretHeld(int pos)
    signal caretLeft()
    property int openCaret: -1
    signal contextRequested(real mx, real my)

    // ---- WHAT IT IS ACTUALLY SAYING, in its own words ----
    // [his, 2026-07-30] *"a minister card should expand to show what that
    // minister is actually saying"*: clicking anywhere on the card slides a
    // drawer down out from under it with the last couple of lines the agent
    // logged, and clicking again slides it back up.
    //
    // The state is NOT held here. A card is rebuilt whenever the key list
    // changes — an agent joining or leaving is enough — so a drawer held in the
    // delegate would shut itself on the next poll; the window keys it by the
    // agent's ID, like the draft in the box below (`Main.qml`'s `outputOpen`).
    // Several may be open at once, which is why it is a map and not one key.
    property bool outputOpen: false
    signal outputToggled()
    //: The lines themselves, from `Agents.output()` — already cleaned and
    //  glyph-mapped in the Python (§2.3). Empty means nothing has been logged,
    //  and the drawer SAYS that rather than opening empty (§10).
    property var logLines: []
    function refreshOutput() {
        row.logLines = (row.outputOpen && row.addressable)
                       ? Agents.output(String(row.agent.id)) : []
    }
    onOutputOpenChanged: row.refreshOutput()
    // Rebuilt already open (see above): a binding that is true at construction
    // emits no change, so the first read has to be asked for.
    //
    // ...and the SEND BOX is restored here too, for the same reason and in the
    // same handler: QML allows exactly ONE `Component.onCompleted` per object,
    // and a second one is a hard `Property value set multiple times` that stops
    // the whole window loading. `openCaret` is the window's own hand-back
    // (`Main.qml`), read at construction, so `composing` has to follow it or a
    // card rebuilt mid-sentence would reopen its editor behind a card with no
    // box on it.
    Component.onCompleted: {
        row.refreshOutput();
        if (row.openCaret >= 0)
            row.composing = true;
    }
    // ...and it follows the same poll the card's own lines do, so an open drawer
    // keeps up with the agent instead of freezing at whatever it said when he
    // opened it. Only while it is open: closed, it reads no files at all.
    Connections {
        target: Agents
        enabled: row.outputOpen
        function onChanged() { row.refreshOutput(); }
    }

    // ---- A CARD IS NEVER WITHHELD; ONE WITH NOTHING TO SAY YET RISES ----
    // [his, 2026-07-31] *"instead of hiding the card until it shows the name on
    // the top line etc, can we just put a card in there that reads '[agent]
    // awakens...' with an animated elipsies ... the card should just show the
    // rising text and nothing else until the agent card actually starts
    // producing stuff like before"* — the word is AWAKENS, not arises: [his,
    // 2026-08-01] *"have it just say like '[agent] awakens...' with an animated
    // elipsies"*.
    //
    // There is no `visible` binding here on purpose, and putting one back is a
    // regression. The gate this replaced (`speaks`) withheld a card until its
    // top line was a real sentence [his, 2026-07-30] — correct for the two
    // seconds a healthy spawn takes, and the reason a minister wedged before
    // its first API call was undrawable and burned a core behind an empty
    // triangle for 45 minutes [top, 2026-07-31].
    //
    // `boardagents` decides (`arising`) off the observation STATE, and it flips
    // on the ordinary 2.5s poll, so the card fills itself in the moment the
    // agent claims a phase or is first seen acting, with nothing reloaded.
    readonly property bool arising: agent && agent.arising === true

    readonly property bool running: agent && agent.running === true
    //: It stopped, and it had recorded its result first. See the accent gutter.
    readonly property bool finished: agent && agent.finished === true
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
    // The claim's own SECOND line — the words the agent gave for what it is
    // doing, which used to follow a hyphen on the line above. [his, 2026-07-29]
    // the card is *"[agent] [verb]s..."* and then those words, on their own line.
    readonly property string saysDetail: agent && agent.saysDetail
                                        ? agent.saysDetail : ""
    // Which of `boardphase.observe`'s four outcomes the line above came from.
    // Only `ok` is something actually happening right now, which is what the
    // ticking dots on the card's top line are allowed to claim.
    readonly property string observed: agent && agent.observed ? agent.observed : ""
    // HOW FULL IT IS — `62k/200k`, at the right end of the card's TOP row, his
    // call: *"on the very right of the top row of the agent's information box
    // it should keep a running tally of how much context that agent has vs how
    // much it can handle"*. Already formatted by `boardphase.context_line`;
    // empty means nothing could be measured, and empty is drawn as nothing.
    readonly property string contextLine: agent && agent.contextLine
                                          ? agent.contextLine : ""
    // HOW LONG it has been working - `working for 4 minutes` (see below).
    readonly property string workedLine: agent && agent.workedLine
                                         ? agent.workedLine : ""
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
    // say it — otherwise it would be drawn twice on the same card.
    // (`boardagents.NAMES`' width rule is this column's.)
    //
    // [his, 2026-08-01] the observed line now opens with the name whenever it
    // LEADS the card (`boardphase.doing_line`'s `lead`), so a card that has a
    // claim OR an observation to show already carries its name on its top line.
    // The column is therefore needed only when NEITHER line is drawn — the
    // title row is then the card's own top line — which is exactly `titleFirst`
    // (a stopped agent nothing was seen doing, or a queued task). That is the
    // one thing this list may never be: anonymous.
    readonly property bool nameNeeded: name !== "" && titleFirst
    // The lead tone, for whichever line is drawn first. A stopped agent leads
    // at `fgDim` rather than `fgText` — that was already how the title row
    // said "this one is over", and it is one rung, not a colour (§3.5's job is
    // done by the words in the detail line).
    //
    // **SOLOMON IS EXEMPT, and from both halves** — [his, 2026-07-29] *"his text
    // should never become the unfocused colors"*. The unfocused fade is handed
    // DOWN (docs/DESIGN.md §3.1.1: a leaf takes the tone it was given), so his
    // exemption lives where his card is drawn — `Main.qml`'s summoner section
    // passes the `Theme` tones rather than the window's faded ones, which covers
    // every label on the card at once, the inbox box included. What is left here
    // is the other rung that can quiet him: this ternary. His card is not a
    // record of work that is over — he is always there — so it never leads at the
    // stopped tone either.
    readonly property bool summoner: agent && agent.kind === "orchestrator"
    readonly property color leadTone: (running || summoner) ? fgText : fgDim

    // ---- A DEEPSEEK SUBMINISTER, drawn INSET under its parent's card ----
    // [his, follow-up to the subminister feature] a subminister gets its OWN
    // card, and it reads as subordinate to the minister that spawned it: it is
    // a §9.1 block that belongs to the row above it, so it is INDENTED one 8px
    // step with a `Theme.accent2` hairline at the indent (§3.8: the secondary
    // hue is this desktop's "group rule" tone) and its own text a step
    // further — and it carries NO §9.1 accent gutter, because accent beside a
    // row already means *current* and two accents say nothing. `main.py`'s
    // `workers` interleaves each one directly under its parent; the card is
    // otherwise an ordinary agent card, visuals unchanged (his call — follow
    // the existing card, do not invent a look).
    //
    // ORPHANED — a subminister whose parent card is gone — drops the inset and
    // draws as a plain top-level card, there being nothing above it to be
    // subordinate to (`main.py` sets the flag). A parent with no subminister is
    // just an ordinary card: nothing here fires for it.
    readonly property bool orphaned: agent && agent.orphan === true
    readonly property bool subminister: agent && agent.subminister === true
                                        && !orphaned
    //: §9.1's two steps off the parent card's own text (`col.x` 10): the
    //  `accent2` hairline rule sits 8px in, this card's text 8px past that.
    readonly property real subInset: subminister ? Theme.gap * 2 : 0

    // ---- the tick, and WHICH line carries it ----
    // His, three times over, and the LAST word wins. *"at the end of the second
    // row of an agents information, it should have an animated elipsies to show
    // its currently happening"*; then, once the claim became two lines, *"take
    // the animated elipsies out of the top line"* and *"the third line of an
    // agents card should not have the animated elipsies or any elipsies at the
    // end of it"*; and then, 2026-07-29, settling it: *"the only line of an
    // agents card that should have the animated elipsies is the top line. no
    // others"*.
    //
    // So the dots live on the card's TOP LINE and nowhere else. The only thing
    // that ticks is a line whose TEXT ends in `...` and which is that top line;
    // `boardphase.py` decides which strings end that way (`says_line`, and
    // Solomon's own startup phrases, which are the first line of HIS card because
    // he has claimed nothing yet). Every other line is drawn through `untick()`,
    // so a sentence an agent happened to end in dots of its own loses them
    // entirely rather than sitting there frozen at three.
    //
    // **The three cells are drawn HERE and not in the Python**, which builds
    // prose: an animated suffix is presentation, and in the Python the sentence a
    // test asserts on would change four times a second.
    //
    // ASCII dots, never U+2026 (§2.3), and the field is **always three cells
    // wide** — the trailing spaces are what stop the line reflowing under a
    // wrap as the dots cycle, exact because the font is monospace (§2.7).
    property int dotPhase: 0
    // The three cells themselves, and there is ONE of them on this card, so no
    // two lines can tick out of step.
    readonly property string dots: motion.reduceMotion
                                   ? "..." : [".  ", ".. ", "..."][dotPhase % 3]
    // A SENTENCE THAT ENDS IN `...` ANIMATES THOSE THREE CELLS — [his,
    // 2026-07-29] *"it should just say 'researches...' or 'codes...' with
    // animated elipsies"*, and the same for Solomon's own lines. `boardphase.py`
    // decides WHICH lines end that way (`PHASE_PREDICATE`/`TICKLESS`, and his
    // startup pair); this decides only how the three cells move, which is
    // presentation and therefore QML's — putting it in the Python would mean the
    // string a test asserts on changed four times a second.
    function tick(s) {
        return s.endsWith("...") ? s.slice(0, -3) + dots : s
    }
    // ...and every line that is NOT the top one ends on its own last word.
    function untick(s) {
        return s.endsWith("...") ? s.slice(0, -3) : s
    }
    // Which Para is drawn first. An agent that has claimed nothing yields the
    // lead - and the tick with it - to the observed line under it.
    readonly property bool claimLeads: row.saysLine !== ""
    // One step per desktop slide (§6.2's own number, through `ms()` so the
    // panel's motion settings reach it) — about a second for the full cycle,
    // which is quiet enough to sit on every running card at once.
    Motion { id: motion }
    Timer {
        interval: Math.max(60, motion.ms(motion.slideMs))
        running: (row.claimLeads ? row.saysLine.endsWith("...")
                                 : row.doingLine.endsWith("..."))
                 && !motion.reduceMotion
                 && row.visible
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

    // The way INTO the box now: the row's right-click menu calls this, and the
    // resting card carries no text field at all ([his] the inline
    // "send a command..." box on every card was to go, replaced with the
    // menu). `msgBox.beginEdit()` opens the editor the same way clicking its
    // resting `>` did, so the caret and the draft machinery are untouched.
    function beginSend() {
        if (!row.addressable)
            return;
        row.composing = true;
        msgBox.beginEdit();
    }
    // (A card rebuilt mid-sentence keeps its box open and its caret where it
    // was — folded into the ONE `Component.onCompleted` this object may have,
    // above, beside the drawer's first read.)

    // The card lights on hover like every other row here, and now it has to:
    // the whole card is the hit target for the drawer, so the fill is what says
    // so (§10 — a control that is drawn is a control that works, and this one is
    // drawn by being lit). FIRST of the card's children, so it is a fill and
    // never a lid — over the text, or over the accent gutter below it.
    Rectangle {
        anchors.fill: parent
        anchors.bottomMargin: 2
        // An inset subminister's highlight starts at its subordination hairline
        // (10 + one 8px step), so the lit region reads as the inset card and not
        // the empty gutter to its left.
        anchors.leftMargin: row.subminister ? 10 + Theme.gap : 0
        color: openArea.containsMouse ? Theme.highlight : "transparent"
    }

    // §9.1's 2px accent gutter: this row is current. **Solomon has none** —
    // [his, 2026-07-29] *"he doesnt need a line to the left of his card"*, and he
    // is right that it says nothing there: the mark distinguishes a running card
    // from a stopped one in a LIST of them, and his section holds one card.
    // ...AND A WORKER THAT FINISHED KEEPS IT — [his, 2026-07-30] about a card
    // that *"still sits and proclaims 'exited without finishing - nothing was
    // committed..' ... and no vertical line on the left EVEN THOUGH its task has
    // been completed"*. A stopped worker used to be drawn the same way whether it
    // reported or was abandoned; `finished` is `boardwork.reported`, the same
    // fact `reap()` files it by, so the mark now says "this one did the work"
    // rather than only "this one is still breathing".
    Rectangle {
        width: 2
        height: parent.height - 6
        // ...but NOT on an inset subminister: that card carries the §9.1
        // subordination hairline below instead, and accent + hairline on one
        // card would be the two-accents-say-nothing case the rule rules out.
        visible: (row.running || row.finished) && !row.summoner
                 && !row.subminister
        color: row.fgAccent
    }

    // §9.1's subordination hairline: a subminister's card is a block that
    // belongs to the minister's card above it, so it hangs a rule (never
    // accent — that still means "current row", not "belongs to") one 8px step
    // in from that card's text (`col.x` 10), with this card's own text a
    // further step (`subInset`, in `col.x` below). `Theme.accent2` since
    // §3.8: it is exactly the "group rule" the section says the secondary hue
    // is for, so the belongs-to relationship reads in a second hue rather
    // than the same neutral line every other hairline on the card uses.
    Rectangle {
        visible: row.subminister
        x: 10 + Theme.gap
        y: 3
        width: 1
        height: parent.height - 6
        color: Theme.accent2
    }

    MouseArea {                          // §7.1: every row is right-clickable
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        onClicked: (m) => {
            var p = mapToItem(null, m.x, m.y);
            row.contextRequested(p.x, p.y);
        }
    }

    // ...and left-clicking it opens the drawer. Declared BEFORE the column, so
    // everything the card draws sits above it: the box he types into keeps its
    // own clicks, and only the parts of the card that accept none — the three
    // lines, the gutter, the drawer itself — fall through to here.
    MouseArea {
        id: openArea
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        hoverEnabled: true
        onClicked: row.outputToggled()
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
        // ...and never on a rising card: *"nothing else"* is his, and a tally
        // of a context nothing has been put in yet is exactly the noise the
        // rising line replaces.
        visible: row.contextLine !== "" && !row.arising
                 && (row.saysLine !== "" || row.doingLine !== "")
        anchors.right: col.right
        y: 0
        color: Theme.dim
        text: row.contextLine
    }

    // How much of the top line the trailing metadata takes, tally and spawn
    // stamp together. One number, so the two lines that may carry it reserve
    // the same space whichever of the pair is drawn.
    readonly property real trailW: (tallyT.visible ? tallyT.width + 8 : 0)
                                   + (bornT.visible ? bornT.width + 8 : 0)

    // ---- ...and HOW LONG IT HAS BEEN WORKING, left of that tally ----
    // [his, 2026-07-29] the spawn stamp this drew for a few hours became a
    // duration at his own ask the same day: *"how long the agent has been
    // working"*. It sits in the same trailing metadata cluster (§9.1), same
    // `dim` rung — standing metadata about the process, like the tally.
    //
    // **It is the ONE elapsed time in this app**, his deliberate exception to
    // the no-pressure rule (`boardphase.worked_line` carries the argument and
    // is the only formatter; the model re-reads agents every poll, which is
    // what keeps it counting on screen). Do not cite it as precedent — every
    // other time here stays absolute, and a stopped agent draws none at all.
    //
    // It rides the same line as the tally, on the same condition — a card whose
    // top line IS the title row gets neither, that corner already belonging to
    // `where`.
    PixelText {
        id: bornT
        // Not while it is rising, same rule as the tally: *"working for 2
        // seconds"* beside *"awakens..."* is two ways of saying it just started.
        visible: row.workedLine !== "" && !row.arising
                 && (row.saysLine !== "" || row.doingLine !== "")
        anchors.right: tallyT.visible ? tallyT.left : col.right
        anchors.rightMargin: tallyT.visible ? 8 : 0
        y: 0
        color: Theme.dim
        text: row.workedLine
    }

    Column {
        id: col
        // 10 is every card's own text inset; a subminister adds §9.1's two 8px
        // steps (`subInset`) so its text sits one step past its hairline.
        x: 10 + row.subInset
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
            width: col.width - (!tallyT.onDoing ? row.trailW : 0)
            visible: row.saysLine !== ""
            height: visible ? implicitHeight : 0
            color: row.leadTone
            text: row.tick(row.saysLine)
        }

        // ---- ...and the words it gave for it, on their own line ----
        // [his, 2026-07-29] the claim is two lines now: the verb with the
        // ticking dots, then this. Verbatim from the agent — `boardphase`
        // splits it off and reformats nothing — and it takes the secondary
        // tone, so the card still leads on the line above it.
        Para {
            id: saysDetailT
            width: col.width
            visible: row.saysDetail !== ""
            height: visible ? implicitHeight : 0
            color: row.fgDim
            // NO dots, animated or frozen: they are the top line's (see the tick
            // note above), and this is never the top line - it is only drawn at
            // all when the verb line above it is.
            text: row.untick(row.saysDetail)
        }

        // ---- SECOND LINE: what it is observed doing, and nothing else ----
        // No subject and no *"is actually"* opener when it sits UNDER a claim:
        // the description alone, his call. When it LEADS instead (no claim
        // above it) `boardphase.doing_line` opens it with the agent's name, so
        // the name stays on the card's top line [his, 2026-08-01].
        // Observed, never the claim. When it cannot be observed it says
        // that ("board cannot see what it is doing", "nothing
        // recently") rather than quietly falling back to the line above —
        // §10's rule, and the reason there are two lines at all. Past tense
        // once the process is gone, and nothing at all when a stopped agent
        // was never seen doing anything: `boardphase.doing_line` decides both,
        // and hands this an empty string to say so.
        Para {
            id: doingT
            width: col.width - (tallyT.onDoing ? row.trailW : 0)
            visible: row.doingLine !== ""
            height: visible ? implicitHeight : 0
            color: row.saysLine === "" ? row.leadTone : row.fgDim
            // Dots only when this IS the card's top line — Solomon's startup
            // phrases arrive on this property and end in `...` of their own, and
            // on his card they are the first line drawn (he has claimed nothing
            // yet). Under a claim it is the third line and ends on its own words,
            // his call twice: *"the third line ... should not have the animated
            // elipsies or any elipsies at the end of it"*, and *"the only line
            // ... is the top line. no others"*.
            text: row.claimLeads ? row.untick(row.doingLine)
                                 : row.tick(row.doingLine)
        }

        // ---- THIRD LINE ----
        // name left, title, where right — what the IN FLIGHT row used to be, so the two
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
            // THE RISING LINE IS THE WHOLE CARD — *"the card should just show
            // the rising text and nothing else"* [his, 2026-07-31]. What it was
            // handed and where it works are fixed for the life of the card and
            // will still be here a second later; the one thing worth reading in
            // that second is that it is coming up. Height 0 as well as
            // invisible, or the card keeps the row's gap and rises as a
            // one-line card in a three-line box.
            visible: !row.arising
            implicitHeight: visible ? titleT.implicitHeight : 0
            height: implicitHeight

            readonly property bool wide: width > 56 * row.cellW
            readonly property real whereW: wide && row.agent && row.agent.where !== ""
                ? Math.min(row.agent.where.length * row.cellW + 2, width * 0.4)
                : 0
            // 7 cells minimum, and it MEASURES per card: the pool is the full
            // Goetia now (`boardagents.NAMES`, up to `Andromalius` at eleven)
            // and the orchestrator is always `Solomon` at seven, so an assumed
            // 7 would truncate — and the pinned top row would be the worst
            // possible place to elide. Nothing is drawn between this column
            // and the title, so a long name costs the title cells on ITS card
            // and nothing anywhere else.
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
            visible: row.showDetail && !row.arising
                     && row.agent && row.agent.detail !== ""
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
        //
        // [his] the box no longer rests on the card: it is CLOSED until the
        // row's right-click menu (`beginSend()`) opens it, and it closes again
        // on submit or on his leaving. What it still says is WHO it reaches —
        // `send Eligos a command` is the whole point of the name — but that
        // sentence now lives in the menu entry instead of a permanent field.
        InputBox {
            id: msgBox
            width: col.width
            visible: row.addressable && row.composing
            height: visible ? implicitHeight : 0
            draft: row.draft
            fgAccent: row.fgAccent
            fgText: row.fgText
            fgDim: row.fgDim
            placeholder: row.running
                ? "send " + (row.name !== "" ? row.name : "it")
                  + " a command, an idea or a fix"
                : "leave a note - it goes to the next minister"
            openCaret: row.openCaret
            onDraftEdited: (b) => row.draftEdited(b)
            onSubmitted: (b) => { row.composing = false; row.send(b); }
            onCaretHeld: (p) => row.caretHeld(p)
            onCaretLeft: () => { row.composing = false; row.caretLeft(); }
        }

        // ---- the drawer: the agent's own last few lines ----
        // It slides DOWN out from under the card, INDENTED, with a rule down its
        // left edge saying it belongs to the card above it.
        //
        // The motion is §6.2's canonical reveal and not a variation on it: the
        // content is FIXED at the drawer's top edge and the CLIP grows downward,
        // so nothing inside it moves and nothing fades in from nowhere. The
        // duration and curve are the window roll's, through `Motion` — no
        // literal, ever (§6.2).
        //
        // The spine is `Theme.accent2` (§3.8): the same "belongs to the card
        // above it" rule the subminister hairline draws in the secondary hue
        // above, not the neutral `Theme.border` every other hairline on this
        // desktop uses — this is subordination, not attention, and the accent
        // here still means "current" (§9.1's gutter, two pixels to its left).
        Item {
            id: drawer
            width: col.width
            clip: true
            readonly property real openH: drawerCol.implicitHeight + 8
            height: row.outputOpen ? openH : 0
            visible: height > 0
            Behavior on height {
                NumberAnimation { duration: motion.ms(motion.slideMs)
                                  easing.type: motion.slideEasing }
            }

            Rectangle {
                x: 8
                y: 2
                width: 1
                height: drawer.openH - 4
                color: Theme.accent2
            }

            Column {
                id: drawerCol
                x: 16
                y: 4
                width: col.width - x

                // ONE LINE EACH, cut to fit — the same treatment the inbox line
                // gets, and for the same reason: this is somebody else's output
                // and a wrapped paragraph of it would bury the card it hangs off
                // (§5.2). ASCII "..." marks the cut (§2.3), and the character
                // count is an exact width because the font is monospace (§2.7).
                Repeater {
                    model: row.logLines
                    delegate: PixelText {
                        required property var modelData
                        width: drawerCol.width
                        wrapMode: Text.NoWrap
                        clip: true
                        color: row.fgDim
                        text: row.clipTo(String(modelData),
                                         Math.floor(width / row.cellW))
                    }
                }

                // Nothing logged is a FACT about the agent, said plainly. Not an
                // empty box, not an error, and nothing from the warn/crit ramp —
                // a worker that has not written yet is not a machine fault
                // (§8.1, §9.3).
                PixelText {
                    width: drawerCol.width
                    visible: row.logLines.length === 0
                    height: visible ? implicitHeight : 0
                    color: Theme.dim
                    text: "nothing logged yet"
                }
            }
        }
    }
}
