import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic
import "../../qmlcommon"

// board's window: one page, three sections, in his stated order of interest —
// what needs him, what is moving, what happened.
//
// ONE SCROLL REGION, deliberately. docs/DESIGN.md §9.2 forbids nested scroll
// regions ("the user should not be able to scroll the tracklist in the
// slidedown. it should display ALL tracks"), so the whole board is a single
// `KineticFlickable` over a `Column` — every section sizes to its whole content
// and the wheel always means the same thing wherever the cursor is. Momentum is
// the compositor's; the bar is `VScroll` and the gutter is reserved from its own
// `barW`, never a literal.
//
// NOTHING HERE NAGS. No counts, no badges, no ages, no colours from the
// warn/crit ramp, no ordering by urgency — the file's own order is kept, and
// every decision carries the sentence saying what happens if he never answers.
// That is the requirement he stated in the same breath as the feature ("i feel
// pressured to act quickly when really i dont need to"), and it is as
// load-bearing as the parse.
Window {
    id: win

    // Focus-aware foreground, in lock-step with the titlebar (§3.1.1, filer's
    // idiom). Leaves take the tone they are handed; none reads Window.active.
    readonly property color fgAccent: win.active ? Theme.accent  : Theme.inactive
    readonly property color fgText:   win.active ? Theme.text    : Theme.inactive
    readonly property color fgDim:    win.active ? Theme.textDim : Theme.inactive

    // ONE measurement gives every layout its column (the font is monospace),
    // measured against the real family rather than derived from §2.7's rounded
    // advance, so it stays right if the desktop font family changes.
    TextMetrics {
        id: metrics
        font.family: Theme.font
        font.pixelSize: Theme.fontSize
        text: "MMMMMMMMMM"
    }
    readonly property real cellW: metrics.width > 0 ? metrics.width / 10
                                                    : Math.round(0.533 * Theme.fontSize)

    Motion { id: motion }

    readonly property var doc: Board.doc
    readonly property var needs: doc && doc.needs ? doc.needs : []
    readonly property var todo: doc && doc.todo ? doc.todo : []
    // The same bullets as `todo`, in sub-sections by what they SAY THEY ARE.
    // Grouped once per load in `boardparse.todo_groups()`, never here: a view
    // that regrouped per delegate would do it on every scroll (§2.3's ingest
    // rule, the same reason the glyph map lives at the parse). `todo` stays the
    // flat list everything else — removal, undo, reply — still works from.
    readonly property var todoGroups: doc && doc.todoGroups ? doc.todoGroups : []
    readonly property var flight: doc && doc.flight ? doc.flight : []
    readonly property var landed: doc && doc.landed ? doc.landed : []
    readonly property var intro: doc && doc.intro ? doc.intro : ({})

    // The machine, not the store: who is running, and what he has written to
    // them that nobody has picked up yet (`boardagents.py`).
    readonly property var agents: Agents.list
    readonly property var agentCards: Agents.cards
    readonly property var queuedNotes: Agents.queued

    // A note to an agent takes the SAME path his answers take: never lost, and
    // honest about which of the two things happened. `boardagents.send()` files
    // it either in a running agent's inbox or in the queue, and says which; the
    // footer repeats it in his own words rather than in an exit code.
    function sendTo(agent, body) {
        if (body.trim() === "")
            return;
        var msg = Agents.send(agent ? agent.id : "", agent ? agent.title : "",
                              agent ? agent.kind : "", body);
        if (msg !== "") {
            win.status = msg;
            win.setDraft("msg:" + (agent ? agent.id : "queue"), "");
        }
    }

    // A window sized for reading one column of prose beside the panel: the bar
    // reserves 376px on the right of a 1920px screen and Hyprland's `gaps_out`
    // takes 35 top and bottom of 1080, so 880x880 sits inside what is actually
    // free with room for a second window next to it, and gives ~100 monospace
    // columns of text after the gutter. It survives far smaller (§5.6): the
    // layout has no minimum sized for this desktop's monitor.
    width: 880
    height: 880
    minimumWidth: 360
    minimumHeight: 240
    visible: true
    color: Theme.bg
    title: "board"

    // ---- state he would notice reverting (§14) ----
    property var collapsed: ({})
    property var drafts: ({})

    function isCollapsed(k) { return collapsed[k] === true; }
    function toggleCollapsed(k) {
        var c = {};
        for (var i in collapsed) c[i] = collapsed[i];
        c[k] = !(c[k] === true);
        collapsed = c;
        Settings.set("collapsed", c);
    }
    function draftOf(k) { return drafts[k] !== undefined ? String(drafts[k]) : ""; }
    function setDraft(k, v) {
        var d = {};
        for (var i in drafts) d[i] = drafts[i];
        if (v === "") delete d[k]; else d[k] = v;
        drafts = d;
        draftTimer.restart();
    }
    // His unsaved words are persisted on a settle timer, so a crash, a relaunch
    // or a stray Escape cannot lose a sentence he typed.
    Timer {
        id: draftTimer
        interval: 700
        onTriggered: Settings.set("drafts", win.drafts)
    }

    Component.onCompleted: {
        var c = Settings.get("collapsed", {});
        collapsed = (c && typeof c === "object") ? c : ({});
        var d = Settings.get("drafts", {});
        drafts = (d && typeof d === "object") ? d : ({});
        Titlebar.setButtons(tbButtons);
        Titlebar.setFooter(footerStr);
    }
    onClosing: {
        Settings.set("drafts", win.drafts);
        Qt.quit();
    }

    // ---- status: a report, never a permanent label ----
    property string status: ""
    onStatusChanged: if (status !== "") statusClear.restart()
    Timer {
        id: statusClear
        interval: 4000
        onTriggered: win.status = ""
    }

    Connections {
        target: Board
        function onStatus(msg) { win.status = msg; }
        // The file changed underneath us — an agent, or the five-minute sync.
        // §6.1: the maintenance mechanism must not be visible, so the scroll
        // position is put back where it was rather than jumping to the top.
        function onReloaded() {
            var y = scroller.contentY;
            Qt.callLater(function () {
                scroller.contentY = Math.max(0, Math.min(y, scroller.contentHeight
                                                            - scroller.height));
            });
            win.status = "board.md changed on disk - reloaded";
        }
    }

    // ---- hyprvtb titlebar: board's whole chrome (§12, §7.4) ----
    // ASCII, lowercase, one or two characters (§12.1). The three section cells
    // are jumps AND a position readout — the lit one is the section the top of
    // the viewport is in, exactly like reader's outline marking.
    //
    // There are deliberately no `<`/`>` history cells and no `NavButtons`:
    // board has one page and no journey to retrace, and §11.1 says a program
    // with no genuine history gets nothing rather than an invented one.
    readonly property string section: {
        if (secLanded.visible && scroller.contentY >= secLanded.y - 4) return "landed";
        if (secAgents.visible && scroller.contentY >= secAgents.y - 4) return "agents";
        if (secFlight.visible && scroller.contentY >= secFlight.y - 4) return "flight";
        return "needs";
    }
    readonly property var tbButtons: [
        { id: "needs",  label: "ny", state: section === "needs" ? 1 : 0,
          tip: "what needs you" },
        { id: "flight", label: "if", state: section === "flight" ? 1 : 0,
          tip: "what is in flight" },
        { id: "agents", label: "ag", state: section === "agents" ? 1 : 0,
          tip: "who is running now" },
        { id: "landed", label: "ld", state: section === "landed" ? 1 : 0,
          tip: "what landed" },
        "-",
        { id: "reader", label: "md", state: 0, tip: "open board.md in reader" },
    ]
    onTbButtonsChanged: Titlebar.setButtons(tbButtons)

    readonly property string footerStr: status !== "" ? status : "board"
    onFooterStrChanged: Titlebar.setFooter(footerStr)

    function jump(item) {
        scroller.contentY = Math.max(0, Math.min(item.y,
                                                 scroller.contentHeight - scroller.height));
    }

    Connections {
        target: Titlebar
        function onClicked(id) {
            switch (id) {
            case "needs":  win.jump(secNeeds);  break;
            case "flight": win.jump(secFlight); break;
            case "agents": win.jump(secAgents); break;
            case "landed": win.jump(secLanded); break;
            case "reader":
                if (!Board.openInReader())
                    win.status = "could not run reader";
                break;
            }
        }
    }

    // ---- the page ----
    readonly property int pad: 12

    KineticFlickable {
        id: scroller
        anchors.fill: parent
        clip: true
        contentWidth: width
        contentHeight: page.implicitHeight + win.pad * 2
        ScrollBar.vertical: VScroll { id: vbar }

        Column {
            id: page
            x: win.pad
            y: win.pad
            // ======================================== the one box he types in
            // His control surface, in his own words: *"a single box that i
            // could type things into, press enter, and have them sent to an
            // inbox. then an agent figures out what agents to assign to what"*.
            //
            // It is FIRST, above everything, because it is the only thing on
            // this page that starts something. Everything below it is a report.
            //
            // It writes down exactly one path — `boardagents.send()` with no
            // agent named, into `inbox/queue/` — which is the same path a note
            // to a running agent takes and the same one whose conservation the
            // harness asserts. There is no second write, and there is nothing
            // typed here that can end up nowhere: if the orchestrator that
            // picks it up fails, board-watch puts his sentence itself back onto
            // the board (`QUEUE_FAIL`).
            //
            // What it may NOT say is "done": nothing here fires immediately,
            // and the gate is that he is at the machine. So the footer says
            // where it went, never what will come of it (§10).
            InputBox {
                id: askBox
                width: page.width
                fgAccent: win.fgAccent
                fgText: win.fgText
                fgDim: win.fgDim
                draft: win.draftOf("msg:queue")
                placeholder: "type anything - press enter and it goes to the inbox"
                hintText: "enter sends - shift+enter is a new line - esc keeps a draft"
                onDraftEdited: (b) => win.setDraft("msg:queue", b)
                onSubmitted: (b) => win.sendTo(null, b)
            }

            Item { width: 1; height: 14 }
            // The gutter is read off the bar itself: its width is a setting and
            // ranges 11-16px, and four call sites across the tree used to leave
            // content under an opaque bar by hardcoding a 10 or a 12 (§9.2).
            width: scroller.width - win.pad * 2 - vbar.barW

            // ================================================ what needs you
            SectionHead {
                id: headNeeds
                width: page.width
                label: "needs you"
                accented: true
                collapsed: win.isCollapsed("needs")
                fgAccent: win.fgAccent
                fgDim: win.fgDim
                onToggled: win.toggleCollapsed("needs")
            }

            Item {
                id: secNeeds
                width: page.width
                visible: !win.isCollapsed("needs")
                implicitHeight: visible ? needsCol.implicitHeight : 0
                height: implicitHeight

                Column {
                    id: needsCol
                    width: parent.width

                    // the section's own framing sentence, from the file
                    Repeater {
                        model: win.intro.needs ? win.intro.needs : []
                        delegate: Para {
                            required property var modelData
                            width: needsCol.width
                            color: win.fgDim
                            text: modelData.text
                            bottomPadding: 8
                        }
                    }

                    // The state he will see most often, and it must read as
                    // finished rather than as broken: no empty frame, no
                    // placeholder box, no "0 items" — one dim sentence in the
                    // token whose own job is "empty & unviewed" (§3.4), and the
                    // section rule above it unchanged so nothing looks missing.
                    Item {
                        width: needsCol.width
                        visible: win.needs.length === 0 && win.todo.length === 0
                        implicitHeight: visible ? Theme.fontSize * 2 + 40 : 0
                        height: implicitHeight

                        Column {
                            anchors.centerIn: parent
                            width: parent.width
                            PixelText {
                                width: parent.width
                                horizontalAlignment: Text.AlignHCenter
                                color: Theme.dim
                                text: "nothing needs you"
                            }
                            PixelText {
                                width: parent.width
                                horizontalAlignment: Text.AlignHCenter
                                color: Theme.dim
                                text: "nothing here expires - come back whenever"
                            }
                        }
                    }

                    Repeater {
                        model: win.needs
                        delegate: Decision {
                            required property var modelData
                            width: needsCol.width
                            decision: modelData
                            cellW: win.cellW
                            fgAccent: win.fgAccent
                            fgText: win.fgText
                            fgDim: win.fgDim
                            draft: win.draftOf(modelData.key)
                            onChoose: (i, on) => Board.choose(modelData.key, i, on)
                            onDraftEdited: (body) => win.setDraft(modelData.key, body)
                            onCommit: (body) => {
                                if (Board.answer(modelData.key, body))
                                    win.setDraft(modelData.key, "");
                            }
                            onContextRequested: (mx, my) => win.decisionMenu(modelData, mx, my)
                        }
                    }

                    Item { width: 1; height: win.todo.length > 0 ? 10 : 0 }

                    // Actions rather than decisions — the file's own second
                    // list. They carry no checkbox in the store, so none is
                    // drawn: a box that cannot be written is exactly the
                    // control §10 says must not exist.
                    PixelText {
                        width: needsCol.width
                        visible: win.todo.length > 0
                        height: visible ? implicitHeight : 0
                        color: win.fgDim
                        text: "to do, when you feel like it"
                    }
                    // ...and they are grouped by that first word — his:
                    // *"the information, completion, partial etc of a message
                    // should be used to organize them on the board. under the
                    // needs you section there should be sub sections for each
                    // of these headers"*.
                    //
                    // A sub-heading is the SAME band the sections use, one rung
                    // quieter: no accent, and `interactive: false` so it carries
                    // no `[-]` and cannot be clicked — it groups, it does not
                    // collapse. It is a heading and NOT a count: no tally, no
                    // badge, no severity colour, exactly as the flat list had
                    // none (AGENTS.md, and §8.1's ramp means a machine fault).
                    // A tag with no bullets has no heading at all; the order and
                    // why it is that order live in `boardparse.TODO_ORDER`.
                    Repeater {
                        model: win.todoGroups
                        delegate: Column {
                            id: todoGroup
                            required property var modelData
                            width: needsCol.width

                            Item {
                                width: 1
                                height: todoGroup.modelData.label !== "" ? 4 : 0
                            }
                            SectionHead {
                                width: todoGroup.width
                                visible: todoGroup.modelData.label !== ""
                                label: todoGroup.modelData.label
                                interactive: false
                                fgDim: win.fgDim
                            }

                            Repeater {
                                model: todoGroup.modelData.items
                                delegate: Item {
                                    id: todoRow
                                    required property var modelData
                                    // The reply box is opened from the row's own menu
                                    // and stays open until he sends or clears it, like
                                    // every other editor here — a draft is never thrown
                                    // away by a click somewhere else.
                                    property bool replying: win.draftOf("todo:" + modelData.line) !== ""
                                    width: needsCol.width
                                    implicitHeight: bar.implicitHeight
                                                    + (replying ? replyBox.height + 4 : 0)
                                    height: implicitHeight

                                    Item {
                                        id: bar
                                        width: parent.width
                                        implicitHeight: todoText.implicitHeight
                                        height: implicitHeight
                                        Rectangle {
                                            anchors.fill: parent
                                            color: tma.containsMouse ? Theme.highlight : "transparent"
                                        }
                                        PixelText {
                                            id: todoMark
                                            x: 0
                                            color: win.fgDim
                                            text: "-"
                                        }
                                        Para {
                                            id: todoText
                                            x: todoMark.width + 8
                                            width: parent.width - x
                                            color: win.fgText
                                            text: todoRow.modelData.text
                                        }
                                        MouseArea {
                                            id: tma
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            // Left is here for the DOUBLE click only —
                                            // *"i should be able to just double click
                                            // on stuff in the to do when you feel like
                                            // it section to remove them"*. A single
                                            // left click stays inert: there is nothing
                                            // for it to do on a bullet the store gives
                                            // no checkbox, and a row that reacted to
                                            // one pass of the pointer would make the
                                            // removal an accident waiting to happen.
                                            acceptedButtons: Qt.LeftButton | Qt.RightButton
                                            onClicked: (m) => {
                                                if (m.button !== Qt.RightButton)
                                                    return;
                                                var p = mapToItem(null, m.x, m.y);
                                                win.todoMenu(todoRow.modelData, p.x, p.y,
                                                             todoRow);
                                            }
                                            onDoubleClicked: (m) => {
                                                if (m.button !== Qt.LeftButton)
                                                    return;
                                                Board.removeTodo(todoRow.modelData.line);
                                            }
                                        }
                                    }

                                    // *"the top item on the right click menu for to do
                                    // items should be `reply` that lets me reply
                                    // directly to it instead of typing in the top box
                                    // like i am doing now"*. Same component, same
                                    // `boardagents.send()` path, same conservation
                                    // property — what it adds is the quote, so whoever
                                    // picks it up knows which chore he meant, and the
                                    // removal: a chore he has answered leaves the list.
                                    InputBox {
                                        id: replyBox
                                        y: bar.height + 4
                                        width: parent.width
                                        visible: todoRow.replying
                                        height: visible ? implicitHeight : 0
                                        draft: win.draftOf("todo:" + todoRow.modelData.line)
                                        fgAccent: win.fgAccent
                                        fgText: win.fgText
                                        fgDim: win.fgDim
                                        placeholder: "reply to this one - it goes to the inbox"
                                        onDraftEdited: (b) => win.setDraft(
                                            "todo:" + todoRow.modelData.line, b)
                                        onSubmitted: (b) => {
                                            if (win.replyToTodo(todoRow.modelData, b))
                                                todoRow.replying = false;
                                        }
                                    }

                                    function beginReply() {
                                        todoRow.replying = true;
                                        replyBox.beginEdit();
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Item { width: 1; height: 18 }

            // ================================================ what is moving
            SectionHead {
                width: page.width
                label: "in flight"
                collapsed: win.isCollapsed("flight")
                fgAccent: win.fgAccent
                fgDim: win.fgDim
                onToggled: win.toggleCollapsed("flight")
            }

            Item {
                id: secFlight
                width: page.width
                visible: !win.isCollapsed("flight")
                implicitHeight: visible ? flightCol.implicitHeight : 0
                height: implicitHeight

                Column {
                    id: flightCol
                    width: parent.width

                    Repeater {
                        model: win.intro.flight ? win.intro.flight : []
                        delegate: Para {
                            required property var modelData
                            width: flightCol.width
                            color: win.fgDim
                            text: modelData.text
                            bottomPadding: 8
                        }
                    }

                    PixelText {
                        width: flightCol.width
                        visible: win.flight.length === 0
                        height: visible ? implicitHeight : 0
                        color: Theme.dim
                        text: "nothing running"
                    }

                    // A row is one line: what on the left, where on the right in
                    // the dim tone, with the note under it. The `where` column
                    // drops widest-first as the window narrows (§9.1) — at
                    // width 0, so what is beside it keeps its anchor.
                    Repeater {
                        model: win.flight
                        delegate: Item {
                            id: frow
                            required property var modelData
                            width: flightCol.width
                            implicitHeight: whatT.implicitHeight
                                            + (noteT.visible ? noteT.implicitHeight : 0) + 4
                            height: implicitHeight

                            readonly property bool wide: width > 56 * win.cellW
                            // Sized from the CHARACTER COUNT, not from the
                            // item's own implicitWidth: `width: min(implicitWidth,
                            // ...)` on an elided Text is self-referential and
                            // resolves to zero — measured, the column simply
                            // vanished. The font is monospace, so a count is
                            // exact anyway (§2.7).
                            readonly property real whereW: wide
                                ? Math.min(modelData.where.length * win.cellW + 2,
                                           frow.width * 0.4)
                                : 0

                            Rectangle {
                                anchors.fill: parent
                                color: fma.containsMouse ? Theme.highlight : "transparent"
                            }
                            PixelText {
                                id: whereT
                                anchors.right: parent.right
                                y: 0
                                width: frow.whereW
                                horizontalAlignment: Text.AlignRight
                                elide: Text.ElideLeft
                                color: win.fgDim
                                text: frow.modelData.where
                            }
                            Para {
                                id: whatT
                                x: 0
                                y: 0
                                width: parent.width - whereT.width - (whereT.width > 0 ? 8 : 0)
                                color: win.fgText
                                text: frow.modelData.what
                            }
                            Para {
                                id: noteT
                                x: 12
                                y: whatT.implicitHeight
                                width: parent.width - x
                                visible: frow.modelData.notes !== ""
                                color: win.fgDim
                                text: frow.modelData.notes
                            }
                            MouseArea {
                                id: fma
                                anchors.fill: parent
                                hoverEnabled: true
                                acceptedButtons: Qt.RightButton
                                onClicked: (m) => {
                                    var p = mapToItem(null, m.x, m.y);
                                    win.rowMenu(frow.modelData.what + "  "
                                                + frow.modelData.where, p.x, p.y);
                                }
                            }
                        }
                    }
                }
            }

            Item { width: 1; height: 18 }

            // ================================================ who is running
            // NOT part of the store. Every other section on this page is
            // `board.md`; this one is the machine — stashes, `/proc` and one
            // systemctl query, read by `boardagents.py`. It sits under IN
            // FLIGHT because it answers the next question that section raises
            // ("is anything actually working on that?") and above LANDED,
            // which is history.
            //
            // It obeys the same no-pressure rule as the rest: no ages, no
            // counts, no urgency ordering, nothing in the warn/crit ramp. A
            // running agent is just running.
            SectionHead {
                width: page.width
                label: "agents"
                collapsed: win.isCollapsed("agents")
                fgAccent: win.fgAccent
                fgDim: win.fgDim
                onToggled: win.toggleCollapsed("agents")
            }

            Item {
                id: secAgents
                width: page.width
                visible: !win.isCollapsed("agents")
                implicitHeight: visible ? agentsCol.implicitHeight : 0
                height: implicitHeight

                Column {
                    id: agentsCol
                    width: parent.width

                    // Nothing running is the NORMAL state, and it must read as
                    // finished rather than as broken — one dim sentence, no
                    // empty frame, no "0 agents". The box at the top of the
                    // page still works, which is the point: what he writes
                    // there waits for the next orchestrator.
                    PixelText {
                        width: agentsCol.width
                        visible: win.agentCards.length === 0
                        height: visible ? implicitHeight : 0
                        color: Theme.dim
                        text: "nothing is running"
                    }

                    // What this section is, said once. It is the honest frame
                    // for every card below it: two sentences, the agent's own
                    // account of itself and then what its tool calls show.
                    // Once, here — not repeated per card, which would be a
                    // disclaimer where a sentence belongs (§5.2).
                    Para {
                        width: agentsCol.width
                        visible: win.agentCards.length > 0
                        height: visible ? implicitHeight : 0
                        bottomPadding: 6
                        color: Theme.dim
                        text: "each agent says what it is doing, and the line "
                              + "under it is what it is actually doing, read "
                              + "from its tool calls. oldest first."
                    }

                    // ---- the cards ----
                    // ONE FLAT LIST, oldest first. The phase headings his first
                    // sentence asked for are gone at his second — *"take out
                    // the 'coding' 'Testing' 'finishing touches' text and just
                    // keep agents ordered by birth/age so they dont move around
                    // so much"* — because a card jumped between sections every
                    // time its agent picked up a different tool. `boardwork.py`
                    // owns the order and it is birth and nothing else: a new
                    // agent appends at the bottom and the rows above it stay
                    // put, including when one stops. The two states that were
                    // headings rather than phases — a task queued above the cap
                    // and an agent that has stopped — say so in words on the
                    // card itself.
                    Repeater {
                        model: win.agentCards
                        delegate: AgentRow {
                            required property var modelData
                            width: agentsCol.width
                            agent: modelData
                            cellW: win.cellW
                            fgAccent: win.fgAccent
                            fgText: win.fgText
                            fgDim: win.fgDim
                            draft: win.draftOf("msg:" + modelData.id)
                            onDraftEdited: (b) =>
                                win.setDraft("msg:" + modelData.id, b)
                            onSend: (b) => win.sendTo(modelData, b)
                            // `copy line` gives him the whole row as a
                            // sentence, and the observed one already leads with
                            // WHO — that is the half he would otherwise have to
                            // go back to the screen for. A card with no
                            // sentence (a queued task, an agent that stopped
                            // unseen) falls back to the line that says what it
                            // is instead.
                            onContextRequested: (mx, my) =>
                                win.rowMenu((modelData.doingLine !== ""
                                             ? modelData.doingLine
                                             : (modelData.name
                                                ? modelData.name + " - " : "")
                                               + modelData.detail)
                                            + "  (" + modelData.title + ")",
                                            mx, my)
                        }
                    }

                    // Notes waiting for the NEXT agent — either he wrote them
                    // with nothing running, or an agent went away without
                    // reading them. Drawn because a message he cannot see is a
                    // message he has to assume was lost.
                    // ...and one he has changed his mind about can be rewritten
                    // or taken back, up until the moment board-watch drains it
                    // (`QueuedNote.qml` carries what that race costs him).
                    Repeater {
                        model: win.queuedNotes
                        delegate: QueuedNote {
                            required property var modelData
                            width: agentsCol.width
                            note: modelData
                            fgDim: win.fgDim
                            fgText: win.fgText
                            fgAccent: win.fgAccent
                            draft: win.draftOf("queued:" + modelData.id)
                            onDraftEdited: (b) => win.setDraft("queued:" + modelData.id, b)
                            onStatusMessage: (t) => { if (t !== "") win.status = t; }
                            onMenuRequested: (mx, my, head, tail) =>
                                menu.open(mx, my, head.concat(win.fileItems())
                                                      .concat(win.undoItems())
                                                      .concat(tail))
                        }
                    }

                    Item { width: 1; height: 6 }

                    // The watcher's own state, from systemd. It is the thing
                    // that will pick the queue up, so "is it armed?" is a fair
                    // question for this section to answer.
                    PixelText {
                        width: agentsCol.width
                        visible: Agents.watcher !== ""
                        height: visible ? implicitHeight : 0
                        elide: Text.ElideRight
                        color: Theme.dim
                        text: Agents.watcher
                    }
                }
            }

            Item { width: 1; height: 18 }

            // ================================================ what happened
            SectionHead {
                width: page.width
                label: "landed"
                collapsed: win.isCollapsed("landed")
                fgAccent: win.fgAccent
                fgDim: win.fgDim
                onToggled: win.toggleCollapsed("landed")
            }

            Item {
                id: secLanded
                width: page.width
                visible: !win.isCollapsed("landed")
                implicitHeight: visible ? landedCol.implicitHeight : 0
                height: implicitHeight

                Column {
                    id: landedCol
                    width: parent.width

                    Repeater {
                        model: win.intro.landed ? win.intro.landed : []
                        delegate: Para {
                            required property var modelData
                            width: landedCol.width
                            color: win.fgDim
                            text: modelData.text
                            bottomPadding: 8
                        }
                    }

                    // History reads as history: the whole section is drawn in
                    // the secondary tone, with the commit in `dim`. It is the
                    // answer to "what did that session actually do to my
                    // machine", not something that wants attention.
                    Repeater {
                        model: win.landed
                        delegate: Column {
                            id: group
                            required property var modelData
                            width: landedCol.width

                            PixelText {
                                width: parent.width
                                topPadding: 6
                                bottomPadding: 2
                                color: win.fgDim
                                text: group.modelData.date
                            }

                            Repeater {
                                model: group.modelData.rows
                                delegate: Item {
                                    id: lrow
                                    required property var modelData
                                    width: landedCol.width
                                    implicitHeight: lwhat.implicitHeight
                                    height: implicitHeight
                                    Rectangle {
                                        anchors.fill: parent
                                        color: lma.containsMouse ? Theme.highlight : "transparent"
                                    }
                                    PixelText {
                                        id: lcommit
                                        x: 0
                                        width: 8 * win.cellW
                                        elide: Text.ElideRight
                                        color: Theme.dim
                                        text: lrow.modelData.commit
                                    }
                                    Para {
                                        id: lwhat
                                        x: lcommit.width + 8
                                        width: parent.width - x
                                               - (lwhen.width > 0 ? lwhen.width + 8 : 0)
                                        color: win.fgDim
                                        text: lrow.modelData.what
                                    }
                                    // WHEN it happened, at the trailing edge
                                    // (§9.1: metadata clusters there) and a
                                    // rung dimmer than the line it belongs to,
                                    // because the what is the point and the
                                    // time is not. Its width is a CHARACTER
                                    // COUNT like the commit's — `implicitWidth`
                                    // on an elided Text measures out at zero —
                                    // and it is 0 for a row that has no time,
                                    // so the old rows give the space back.
                                    PixelText {
                                        id: lwhen
                                        anchors.right: parent.right
                                        width: lrow.modelData.when ? 8 * win.cellW : 0
                                        visible: width > 0
                                        horizontalAlignment: Text.AlignRight
                                        color: Theme.dim
                                        text: lrow.modelData.when ? lrow.modelData.when : ""
                                    }
                                    MouseArea {
                                        id: lma
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        acceptedButtons: Qt.RightButton
                                        onClicked: (m) => {
                                            var p = mapToItem(null, m.x, m.y);
                                            win.rowMenu(lrow.modelData.commit + "  "
                                                        + lrow.modelData.what
                                                        + (lrow.modelData.when
                                                           ? "  " + lrow.modelData.when : ""),
                                                        p.x, p.y);
                                        }
                                    }
                                }
                            }

                            Repeater {
                                model: group.modelData.prose
                                delegate: Para {
                                    id: lprose
                                    required property var modelData
                                    width: landedCol.width
                                    topPadding: lprose.modelData.kind === "bullet" ? 0 : 6
                                    color: win.fgDim
                                    text: (lprose.modelData.kind === "bullet" ? "- " : "")
                                          + lprose.modelData.text
                                }
                            }
                        }
                    }
                }
            }

            Item { width: 1; height: 20 }

            // The store's own path, so it is never a mystery where this came
            // from — and it is the honest answer to "can I just edit the file?"
            PixelText {
                width: page.width
                color: Theme.dim
                text: Board.path
                elide: Text.ElideLeft
            }
        }
    }

    // An unreadable store says so instead of drawing an empty board (§10.2:
    // "an app that cannot do its job says so instead of opening broken").
    Rectangle {
        anchors.fill: parent
        visible: Board.error !== ""
        color: Theme.bg
        PixelText {
            anchors.centerIn: parent
            horizontalAlignment: Text.AlignHCenter
            color: win.fgDim
            text: "cannot read " + Board.path + "\n" + Board.error
        }
    }

    // Right-click anywhere that is not a row.
    MouseArea {
        anchors.fill: parent
        z: -1
        acceptedButtons: Qt.RightButton
        onClicked: (m) => win.rowMenu("", m.x, m.y)
    }

    CtxMenu {
        id: menu
        anchors.fill: parent
    }

    // ---- the menus (§7.1: every list ships with one; §7.2: ours, lowercase,
    // read-only actions first and nothing destructive here at all) ----
    function fileItems() {
        return [
            { label: "open board.md in reader",
              trigger: () => { if (!Board.openInReader()) win.status = "could not run reader"; } },
            { label: "open folder in filer",
              trigger: () => { if (!Board.openFolder()) win.status = "could not run filer"; } },
            { label: "copy path", trigger: () => Board.copy(Board.path) },
        ];
    }

    function decisionMenu(d, x, y) {
        var items = [
            { label: "copy question", trigger: () => Board.copy(d.title) },
            { label: "copy my answer", enabled: d.answer !== "",
              trigger: () => Board.copy(d.answer) },
            { separator: true },
            { label: "clear my answer", enabled: d.answered === true,
              trigger: () => {
                  for (var i = 0; i < d.options.length; i++)
                      if (d.options[i].checked) Board.choose(d.key, i, false);
                  if (d.answer !== "") Board.answer(d.key, "");
              } },
            { separator: true },
        ];
        menu.open(x, y, items.concat(fileItems()));
    }

    // The undo for a removed `to do` bullet. Absent, not greyed, when there is
    // nothing to put back (§10: a control that cannot work is not drawn), and
    // offered from EVERY menu — he may have removed the only bullet there was,
    // in which case there is no row left to right-click.
    function undoItems() {
        if (Board.undoText === "")
            return [];
        var t = Board.undoText;
        if (t.length > 44) t = t.substring(0, 44) + "...";
        return [{ separator: true },
                { label: "put back \"" + t + "\"", trigger: () => Board.undoRemove() }];
    }

    function rowMenu(text, x, y) {
        var items = [];
        if (text !== "")
            items.push({ label: "copy line", trigger: () => Board.copy(text) });
        menu.open(x, y, items.concat(fileItems()).concat(undoItems()));
    }

    // Replying to one chore rather than to the board as a whole — *"the top
    // item on the right click menu for to do items should be `reply` that lets
    // me reply directly to it instead of typing in the top box like i am doing
    // now"*.
    //
    // It is NOT a second way of writing: it is `boardagents.send()`, the one
    // path the top box and every agent card already take, so a reply is a file
    // in exactly one of `to/`, `queue/`, `taken/` at every instant and the
    // conservation argument still holds. The only thing this adds is the QUOTE —
    // the chore's own text travels with his sentence, because "yes, do that one"
    // means nothing to the orchestrator that reads it half an hour later.
    // Returns whether it went, so the row can close its editor.
    //
    // HIS SENTENCE COMES FIRST, and the quote after it. Everything downstream
    // leads with the HEAD of this one string — the `waiting for the next agent`
    // line drawn above, `board-watch`'s card title for the orchestrator it
    // spawns (`msgs[0]["text"][:70]`), every `boardctl` listing — so a body that
    // opened with the quote made all of them announce the chore he was
    // answering and bury the answer. *"the resulting agent created should
    // indicate the reply from the user rather than the original message"*.
    //
    // And answered is answered: the bullet LEAVES the list once the message is
    // on disk (`msg !== ""`), never before, so a reply he made and a chore still
    // sitting there cannot both be true.
    function replyToTodo(t, body) {
        if (body.trim() === "")
            return false;
        var msg = Agents.send("", "", "",
                              body + "  (about the `to do` bullet \""
                              + t.text + "\")");
        if (msg === "")
            return false;
        win.setDraft("todo:" + t.line, "");
        // `Board.removeTodo` is the ONE removal path — the menu entry and the
        // double click take it too — so this inherits its one-level undo and a
        // reply to the wrong row costs a right-click, not his prose. Re-resolved
        // against the doc as it is NOW rather than trusting the index this row
        // was drawn from: three programs write this file and it syncs every five
        // minutes, and a stale line would take somebody else's bullet.
        var line = win.todoLineOf(t);
        win.status = (line >= 0 && Board.removeTodo(line))
                     ? msg + " - chore removed, `put it back` undoes it"
                     : msg;
        return true;
    }

    // Where that bullet is NOW, or -1 if it has gone. Its own line when the text
    // there still matches, so two chores worded identically cannot swap places.
    function todoLineOf(t) {
        var rows = win.todo;
        for (var i = 0; i < rows.length; i++)
            if (rows[i].line === t.line && rows[i].text === t.text)
                return rows[i].line;
        for (var j = 0; j < rows.length; j++)
            if (rows[j].text === t.text)
                return rows[j].line;
        return -1;
    }

    // A `to do` bullet. §7.2's ordering is a safety property: the thing he does
    // most is first, then read-only, then the undo, and the one destructive
    // entry LAST behind its own separator so the pointer never lands on it.
    //
    // No confirm on the removal, and now two ways to reach it: this entry, and
    // a DOUBLE click on the row (his ask). Neither is a single click, and the
    // undo above is what covers the misclick — §10.3's deliberateness is in the
    // second click and in the fact that a removed line can be put back
    // byte-for-byte, which is not true of a signal to a process.
    function todoMenu(t, x, y, row) {
        var items = [];
        if (row)
            items.push({ label: "reply", trigger: () => row.beginReply() });
        items.push({ label: "copy line", trigger: () => Board.copy(t.text) });
        items = items.concat(fileItems()).concat(undoItems());
        items.push({ separator: true });
        items.push({ label: "remove this from the list",
                     trigger: () => Board.removeTodo(t.line) });
        menu.open(x, y, items);
    }
}
