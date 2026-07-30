import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic
import "../../qmlcommon"

// board's window: one page, four sections — what needs him, who is running,
// what happened, and what is moving. That last one sits at the BOTTOM at his
// request (*"for now"*), and it is a display order only: the store's own
// section order is untouched.
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
    // Is anything actually HAPPENING? Not `agentCards.length`, since Solomon's
    // standing row is drawn whether or not it is: `boardwork.cards()` pins the
    // orchestrator at the top and substitutes a `ready` row when none is
    // running, so the list is never empty any more. This is what the section's
    // "nothing is running" sentence and its two-lines-per-card preamble hang
    // off — both are about the cards under Solomon.
    readonly property bool nothingRunning:
        win.agentCards.filter((c) => c.state !== "idle").length === 0

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
    title: "goetia"

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
    // ---- ...and state he would NOT notice reverting: one chore, folded ----
    // *"i should be able to collapse to a single line and expand messages in
    // the to do section via the mark to the left of the messages."* A view
    // gesture and nothing else: the store is not touched, and the byte-identical
    // round trip is untouched with it.
    //
    // KEYED ON THE BULLET'S OWN TEXT, and SESSION-ONLY, and both halves are
    // deliberate. A bullet's line number is what the rest of this app addresses
    // it by, and it is exactly the wrong key here: the file is rewritten under
    // this window by agents and by the docs sync, so a line remembered as
    // folded would come back folded over a DIFFERENT chore — the one failure
    // this list may not have. The text moves with the bullet and cannot do
    // that; two identical bullets folding together is a tie, not a lie, and an
    // agent rewording one unfolds it, which is right. Session-only because
    // `collapsed` above is for the three sections, which are few, named and
    // permanent — a map of his prose growing an entry per chore he ever folded
    // is not state worth keeping, and a fold he does not remember making is
    // worse than one he has to make again.
    property var todoFolded: ({})
    function isTodoFolded(t) { return todoFolded[t] === true; }
    function toggleTodoFolded(t) {
        var f = {};
        for (var i in todoFolded) f[i] = todoFolded[i];
        f[t] = !(f[t] === true);
        todoFolded = f;          // reassigned: a mutated object notifies nothing
    }

    // Cut a string to `cells` characters, marking the cut with ASCII "...".
    // NEVER the unicode ellipsis and never `Text.ElideRight`, which draws one:
    // the font has no U+2026 and a missing glyph clips the row it is on
    // (§2.3). Exact in characters because the font is monospace (§2.7). The
    // twin of `AgentRow.clipTo`, which cuts a card's inbox line the same way.
    function clipTo(s, cells) {
        if (cells < 4)
            return "...";
        return s.length <= cells ? s : s.slice(0, cells - 3) + "...";
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
    // BOTTOM-UP, and it has to be: the first test that matches wins, so the
    // sections are asked about in reverse page order. It follows the page, and
    // the page order changed — IN FLIGHT sits below LANDED now, at his request
    // ("for now"), so `flight` is asked FIRST here and `needs` is the fallback.
    //
    // `y > 0` on each test is NOT redundant: before the Column has laid out,
    // every section sits at y 0, so `contentY (0) >= 0 - 4` was TRUE for the
    // LAST section and the first thing the titlebar was told was that he is
    // looking at `if` — then it was corrected to `ny` a frame later. Every
    // REGISTER bumps the plugin's IPC serial and repaints the bar, so a wrong
    // one is a visible flash of the wrong lit cell. Only `needs` can honestly
    // be at y 0, and it is the fallback anyway.
    readonly property string section: {
        if (secFlight.visible && secFlight.y > 0 && scroller.contentY >= secFlight.y - 4) return "flight";
        if (secLanded.visible && secLanded.y > 0 && scroller.contentY >= secLanded.y - 4) return "landed";
        if (secAgents.visible && secAgents.y > 0 && scroller.contentY >= secAgents.y - 4) return "agents";
        return "needs";
    }
    // ...and the cells read left-to-right as the page reads top-to-bottom.
    readonly property var tbButtons: [
        { id: "needs",  label: "ny", state: section === "needs" ? 1 : 0,
          tip: "what needs you" },
        { id: "agents", label: "ag", state: section === "agents" ? 1 : 0,
          tip: "who is running now" },
        { id: "landed", label: "ld", state: section === "landed" ? 1 : 0,
          tip: "what landed" },
        { id: "flight", label: "if", state: section === "flight" ? 1 : 0,
          tip: "what is in flight" },
        "-",
        { id: "reader", label: "md", state: 0, tip: "open board.md in reader" },
    ]
    onTbButtonsChanged: Titlebar.setButtons(tbButtons)

    // [his, 2026-07-29] *"remove the 'goetia' text at the bottom of the inner
    // titlebar"* — so the footer is the STATUS and nothing else, and the bar is
    // empty down there when there is nothing to report. The program's name is
    // already the window title the plugin draws up the side of the same bar;
    // saying it twice was the redundancy §9.1 rules out, and a standing label is
    // not a report (the rule this property's own comment states).
    readonly property string footerStr: status
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
            // The box, and to its right the one thing about the box that is a
            // SETTING rather than a sentence: which model reads what he types.
            // [his, 2026-07-29] *"add a drop down to the right of the top prompt
            // box that allows the user to select which model they wish the
            // orchestrator to be."*
            //
            // An Item rather than a Row because the box GROWS when he opens it
            // and the chooser must stay put against the box's TOP rather than
            // re-centring itself every keystroke. The box takes the remaining
            // width; the chooser measures itself off its own text.
            //
            // ONE Item, and the chooser column is the reference. [his,
            // 2026-07-29] *"the prompt box should extend so that it is not a
            // single line but rather multiple lines so that it is the same
            // height as from the top of the model selector box to the bottom of
            // the indicators. the indicators should be anchored to the model
            // selector box not the prompt box as they are now."* So:
            //
            //   * `modelPick` sits at y 0 and the meters hang off ITS bottom —
            //     the two are one column, and nothing in it looks at the box.
            //   * `askBox.minHeight` is that column's span, so the box is as
            //     tall as chooser + gap + meters and both edges line up. It is
            //     read off their real geometry, never a number: a longer model
            //     label, a second line on a stale meter or a font-size change
            //     moves box and column together (§2.7).
            //   * the dependency is ONE-DIRECTIONAL on purpose. Column -> box.
            //     Anchoring the meters to the box while the box sizes itself
            //     off the meters is a binding loop, which is the §5.2 trap and
            //     what the arrangement this replaces would have become.
            //
            // The slack it fills was dead space (§5.2): a one-line box left the
            // whole area beside the meters empty, and what fills it is the
            // thing he types into — more of his sentence visible at once, and a
            // click target that is the region rather than the line (§5.3).
            // He still extends it past the resting height by typing: `minHeight`
            // is a floor, not a cap.
            Item {
                width: page.width
                height: Math.max(askBox.height, pickCol) + (usageCol.visible ? 4 : 0)

                // Top of the chooser to the bottom of the last meter. The 4s are
                // the lead-ins below, stated once here and once at each of them.
                readonly property real pickCol: capPick.y + capPick.height
                    + (usageCol.visible ? 4 + usageCol.height : 0)

                // ONE edge for the whole column, and it is the widest control in
                // it — his rule for the meters ("exactly as wide as the model
                // selection box") is that the column has a single right and a
                // single left edge, and two dropdowns of different label lengths
                // would otherwise give it three. Bound to the labels, never a
                // number, so a longer model name still widens all of it (§2.7).
                readonly property real colW: Math.max(modelPick.implicitWidth,
                                                      capPick.implicitWidth)

                InputBox {
                    id: askBox
                    width: parent.width - parent.colW - 10
                    minHeight: parent.pickCol - modelPick.y
                    fgAccent: win.fgAccent
                    fgText: win.fgText
                    fgDim: win.fgDim
                    draft: win.draftOf("msg:queue")
                    placeholder: "type anything - press enter and it goes to the inbox"
                    hintText: "enter sends - shift+enter is a new line - esc keeps a draft"
                    onDraftEdited: (b) => win.setDraft("msg:queue", b)
                    onSubmitted: (b) => win.sendTo(null, b)
                }

                // Both of these are MENUS, not combo boxes: §7.2 says menus on
                // this desktop are ours and are `CtxMenu`, and a chooser with a
                // handful of entries is that menu with a resting label. They are
                // one component (`PickBox.qml`) because they are one control —
                // [his, 2026-07-29] the cap is *"another drop down"*, in the
                // idiom of the one beside it — and the tick beside each live
                // entry comes from `boardwork`, so neither control can disagree
                // with what will actually happen.
                PickBox {
                    id: modelPick
                    anchors.right: parent.right
                    // Flush with the box's own top, not inset by the 3px the
                    // box pads its first line by: the box is now as tall as
                    // this column, so the two are only "the same height" if
                    // they start and end on the same rows.
                    y: 0
                    width: parent.colW
                    label: Agents.modelLabel
                    // What it changes, and WHEN it takes effect. The second half
                    // is the whole of the promise: a running orchestrator is not
                    // restarted and not re-pointed.
                    hint: "which model reads what you type - the one running now keeps its own"
                    items: () => win.modelItems()
                    popup: menu
                    fgDim: win.fgDim
                    fgAccent: win.fgAccent
                    onHoveringChanged: (on) => win.status = on ? hint : ""
                }

                // ...and under it, how many of them may run at once. [his,
                // 2026-07-29] *"between the model selector and the indicators,
                // add another drop down for the max number of agents
                // available."* It is BETWEEN them, in his order, so the column
                // reads model -> how many -> what they have cost.
                //
                // It writes the ONE cap store — the file `boardctl.py cap`
                // writes and `promote()` re-reads at the top of every tick — so
                // nothing is restarted and nothing is killed by picking one: a
                // bigger cap starts queued work on the next tick, a smaller one
                // stops starting more. Same 4px rung under it as the meters get
                // (§4.1), rather than butting two 1px borders into a 2px seam.
                PickBox {
                    id: capPick
                    anchors.top: modelPick.bottom
                    anchors.topMargin: 4
                    anchors.right: modelPick.right
                    width: parent.colW
                    label: Agents.capLabel
                    hint: "the most agents allowed to work at once - the next tick honours it"
                    items: () => win.capItems()
                    popup: menu
                    fgDim: win.fgDim
                    fgAccent: win.fgAccent
                    onHoveringChanged: (on) => win.status = on ? hint : ""
                }

                // ======================== what is left of the usage, under it
                // [his, 2026-07-29] *"add usage indicators directly under the
                // orchestrator model-selection box: how much of his daily usage
                // and how much of his weekly usage has been consumed"* — and no
                // Fable figure, which is a real entry in the payload and is
                // dropped in `boardusage.py` rather than here.
                //
                // It sits UNDER the chooser and is EXACTLY AS WIDE as it, one
                // readout per line, because it is about the same thing: what
                // spending that model costs him. [his, 2026-07-29] *"each usage
                // indicator should be exactly as wide as the model selection box
                // above it … stacked vertically"*. The width is bound to
                // `modelPick`, not to a number, so the box and the bars stay
                // flush when a longer model name widens it.
                //
                // ANCHORED TO THE CHOOSER, not to the box he types in [his,
                // 2026-07-29] — so the two of them are one column, the box
                // measures itself against that column, and the dependency
                // cannot close into a loop. It is a sibling of the box for that
                // reason and not a row below it.
                //
                // Two readouts of one quantity, sharing one denominator each
                // (§10.5) — both are "% of that window's limit", the CLI's own
                // arithmetic against the real plan, never tokens over a ceiling
                // we guessed.
                //
                // The short window is FIVE HOURS and says so. There is no daily
                // bucket on this account, and a number under the wrong word is
                // the §10.5 failure with a nicer label. `5h` is the top line
                // because that is the one that stops him mid-afternoon.
                Column {
                    id: usageCol
                    // [his, 2026-07-29] *"there should be just a little more
                    // space between the top of the indicators and the bottom of
                    // the model selector"* — one rung of §4.1's in-widget scale,
                    // and the same 4 this block leaves under itself, so the card
                    // keeps one gap and not three. The 5h/7d rows still butt
                    // together; only the lead-in moved.
                    anchors.top: capPick.bottom
                    anchors.topMargin: 4
                    anchors.right: capPick.right
                    width: capPick.width
                    visible: Usage.rows.length > 0
                    // Zero: each meter already carries its own line box (§4.1),
                    // and stacked readouts butt together like every other tiled
                    // thing here (§5.1). Nothing invents a gap.
                    spacing: 0

                    Repeater {
                        // `Usage.rows` is in `boardusage.WINDOWS` order, which
                        // is 5h then 7d — the stack takes its order from there
                        // rather than restating it.
                        model: Usage.rows
                        delegate: UsageMeter {
                            required property var modelData
                            width: usageCol.width
                            row: modelData
                            fgDim: win.fgDim
                            fgText: win.fgText
                            onHoveringChanged: win.status = hovering
                                ? modelData.detail : ""
                        }
                    }
                }
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
                                    // Folded to its one summary line, by his
                                    // click on the mark. `win.todoFolded` says
                                    // what the key is and why it is the text.
                                    readonly property bool folded:
                                        win.isTodoFolded(modelData.text)
                                    width: needsCol.width
                                    implicitHeight: bar.implicitHeight
                                                    + (replying ? replyBox.height + 4 : 0)
                                    height: implicitHeight

                                    Item {
                                        id: bar
                                        width: parent.width
                                        implicitHeight: todoText.implicitHeight
                                                        + (todoMore.visible
                                                           ? todoMore.implicitHeight + 6 : 0)
                                        height: implicitHeight
                                        Rectangle {
                                            anchors.fill: parent
                                            color: tma.containsMouse ? Theme.highlight : "transparent"
                                        }
                                        // THE MARK IS THE FOLD CONTROL — his:
                                        // *"i should be able to collapse to a
                                        // single line and expand messages in
                                        // the to do section via the mark to the
                                        // left of the messages."* So it says
                                        // which way it goes, in the same ASCII
                                        // vocabulary the section bands use
                                        // (`SectionHead`, §2.3 — the font has
                                        // no triangles): `-` open, `+` folded.
                                        // One character rather than the band's
                                        // `[-]`, because a bullet is a bullet
                                        // and the list must not gain two cells
                                        // of indent; the pointing hand and the
                                        // row's own hover light are what say it
                                        // is a target (§10).
                                        PixelText {
                                            id: todoMark
                                            x: 0
                                            color: win.fgDim
                                            text: todoRow.folded ? "+" : "-"
                                        }
                                        // TAG plus ONE summary line, then a gap,
                                        // then the elaboration if there is any —
                                        // his: *"it should show the PARTIAL
                                        // INFORMATION whatever text, then a
                                        // single line summarizing, a new line,
                                        // and THEN the elaboration if needed. it
                                        // shouldnt really elaborate that much
                                        // though"*.
                                        //
                                        // The split is the PARSE's (`summary` /
                                        // `detail` beside the joined `text` the
                                        // rest of this app still uses); the
                                        // store on disk is untouched and its
                                        // round trip is still byte-identical.
                                        // §5.2: a bullet with nothing under it
                                        // COLLAPSES rather than reserving the
                                        // gap — that absence is permanent, not
                                        // transient, so there is no blank line
                                        // to look at.
                                        // Folded, this is ONE line — *"collapse
                                        // to a single line"* — so a summary
                                        // that does not fit is CUT, in
                                        // characters, with an ASCII marker.
                                        // **Not `Text.ElideRight`**: Qt elides
                                        // with U+2026, a glyph this font does
                                        // not have, and a missing glyph clips
                                        // the whole row (§2.3). `maximumLineCount`
                                        // still pins the height, so a string
                                        // the cut underestimates cannot grow a
                                        // second line. The width does not
                                        // change with the fold, so unfolding
                                        // reflows nothing beside it.
                                        Para {
                                            id: todoText
                                            readonly property string full:
                                                todoRow.modelData.summary
                                                ? todoRow.modelData.summary
                                                : todoRow.modelData.text
                                            x: todoMark.width + 8
                                            width: parent.width - x - (15 * win.cellW + 8)
                                            color: win.fgText
                                            maximumLineCount: todoRow.folded ? 1 : 9999
                                            text: todoRow.folded
                                                  ? win.clipTo(full,
                                                        Math.floor(width / win.cellW))
                                                  : full
                                        }
                                        Para {
                                            id: todoMore
                                            x: todoText.x
                                            y: todoText.height + 6
                                            width: todoText.width
                                            // Folded, the elaboration is the
                                            // half that goes: the summary is
                                            // what he asked to keep.
                                            visible: text !== "" && !todoRow.folded
                                            color: win.fgDim
                                            text: todoRow.modelData.detail
                                                  ? todoRow.modelData.detail : ""
                                        }
                                        // WHEN it was put on the board — his:
                                        // *"mesages in the needs you section
                                        // should all have the time they were
                                        // placed on the board indicated on
                                        // them."* Same treatment as a LANDED
                                        // row's `when` and a decision's:
                                        // trailing edge, `Theme.dim`, a width
                                        // in CHARACTERS that the message text
                                        // reserves whether or not this bullet
                                        // has a stamp (§5.4) — so a bullet
                                        // written before this existed wraps
                                        // exactly where a new one does and
                                        // nothing shifts as the list fills.
                                        PixelText {
                                            id: todoWhen
                                            anchors.right: parent.right
                                            anchors.top: parent.top
                                            width: 15 * win.cellW
                                            horizontalAlignment: Text.AlignRight
                                            color: Theme.dim
                                            text: todoRow.modelData.placed
                                                  ? todoRow.modelData.placed : ""
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
                                        // ...and the mark's own band, over the
                                        // top of that one, because the fold is
                                        // *"via the mark to the left of the
                                        // messages"*. Two rules from §5.1 and
                                        // §10 shape it: the HIT BAND EXCEEDS
                                        // THE INK — one dim character is a
                                        // 8px target and he has already
                                        // reported a collapse handle as
                                        // unclickable once — and it takes the
                                        // LEFT button only, so a right-click
                                        // anywhere on the row still opens the
                                        // row's menu underneath.
                                        //
                                        // It swallows the double-click-to-
                                        // remove in this band, and that is the
                                        // safe way round: folding twice is
                                        // nothing, and removing his chore by
                                        // accident is not.
                                        MouseArea {
                                            x: 0
                                            width: todoMark.width + 8
                                            height: parent.height
                                            acceptedButtons: Qt.LeftButton
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: win.toggleTodoFolded(
                                                todoRow.modelData.text)
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

            // ================================================ who is running
            // NOT part of the store. Every other section on this page is
            // `board.md`; this one is the machine — stashes, `/proc` and one
            // systemctl query, read by `boardagents.py`. It sits directly under
            // NEEDS YOU because it answers the next question a decision raises
            // ("is anything actually working on that?"), and above LANDED,
            // which is history.
            //
            // The page order is NEEDS YOU, AGENTS, LANDED, IN FLIGHT — IN
            // FLIGHT went to the bottom at his request, *"for now"*. It is a
            // display order only: `board.md`'s own section order is unchanged
            // and `boardparse.SECTIONS` still reads the file as it is written.
            // Three things follow this order and would lie if it moved without
            // them: the `section` position readout (asked bottom-up, first
            // match wins), the `tbButtons` cells, and `jump()`.
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
                    // there waits for the next orchestrator. Solomon's standing
                    // row below says the same thing from the other end — who
                    // will pick it up — so this stays a sentence about the
                    // WORKERS and is gated on them, not on the list's length.
                    PixelText {
                        width: agentsCol.width
                        visible: win.nothingRunning
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
                        visible: !win.nothingRunning
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
                    // owns the order and it is birth and nothing else BELOW
                    // the first row: a new agent appends at the bottom and the
                    // rows above it stay put, including when one stops. The
                    // first row is Solomon, pinned — *"he should always be kept
                    // on the top of the agent list"* — and it is drawn even
                    // with no orchestrator running, saying `ready`. The two
                    // states that were
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

    // The model chooser's rows. A tick marks the live one rather than the row
    // being disabled — picking what is already picked is a no-op he can see the
    // result of, and a greyed row would read as "unavailable" (§10).
    // The cap dropdown's entries. Same shape as `modelItems`, and the same
    // honesty: the tick is the store's, and the footer says WHEN it applies
    // rather than claiming the change already happened (§10).
    function capItems() {
        return Agents.caps.map((c) => ({
            label: (c.current ? "* " : "  ") + c.label,
            trigger: () => {
                if (!Agents.chooseCap(c.n))
                    win.status = "could not save that choice";
                else
                    win.status = "at most " + c.label
                        + " from the next tick on - nothing running is stopped";
            }
        }));
    }

    function modelItems() {
        return Agents.models.map((m) => ({
            label: (m.current ? "* " : "  ") + m.label,
            trigger: () => {
                if (!Agents.chooseModel(m.flag))
                    win.status = "could not save that choice";
                else
                    win.status = m.label + " orchestrates from the next prompt on";
            }
        }));
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
