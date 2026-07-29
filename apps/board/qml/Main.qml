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
    readonly property var flight: doc && doc.flight ? doc.flight : []
    readonly property var landed: doc && doc.landed ? doc.landed : []
    readonly property var intro: doc && doc.intro ? doc.intro : ({})

    // The machine, not the store: who is running, and what he has written to
    // them that nobody has picked up yet (`boardagents.py`).
    readonly property var agents: Agents.list
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
                    Repeater {
                        model: win.todo
                        delegate: Item {
                            required property var modelData
                            width: needsCol.width
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
                                text: modelData.text
                            }
                            MouseArea {
                                id: tma
                                anchors.fill: parent
                                hoverEnabled: true
                                acceptedButtons: Qt.RightButton
                                onClicked: (m) => {
                                    var p = mapToItem(null, m.x, m.y);
                                    win.rowMenu(modelData.text, p.x, p.y);
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
                    // empty frame, no "0 agents". The box below it still works,
                    // which is the point: what he writes waits for the next one.
                    PixelText {
                        width: agentsCol.width
                        visible: win.agents.length === 0
                        height: visible ? implicitHeight : 0
                        color: Theme.dim
                        text: "nothing is running"
                    }

                    Repeater {
                        model: win.agents
                        delegate: AgentRow {
                            required property var modelData
                            width: agentsCol.width
                            agent: modelData
                            cellW: win.cellW
                            fgAccent: win.fgAccent
                            fgText: win.fgText
                            fgDim: win.fgDim
                            draft: win.draftOf("msg:" + modelData.id)
                            onDraftEdited: (b) => win.setDraft("msg:" + modelData.id, b)
                            onSend: (b) => win.sendTo(modelData, b)
                            onContextRequested: (mx, my) =>
                                win.rowMenu(modelData.title + "  " + modelData.detail, mx, my)
                        }
                    }

                    // With nobody running there is no row to type into, so the
                    // section grows its own box. Same component, no target:
                    // `boardagents.send()` files it in the queue and the next
                    // agent board-watch spawns is handed it.
                    AgentRow {
                        width: agentsCol.width
                        visible: win.agents.length === 0
                        height: visible ? implicitHeight : 0
                        agent: ({ id: "", kind: "", title: "", where: "",
                                  running: false, waiting: [],
                                  detail: "board-watch spawns one when you answer a decision" })
                        cellW: win.cellW
                        fgAccent: win.fgAccent
                        fgText: win.fgText
                        fgDim: win.fgDim
                        draft: win.draftOf("msg:queue")
                        onDraftEdited: (b) => win.setDraft("msg:queue", b)
                        onSend: (b) => win.sendTo(null, b)
                    }

                    // Notes waiting for the NEXT agent — either he wrote them
                    // with nothing running, or an agent went away without
                    // reading them. Drawn because a message he cannot see is a
                    // message he has to assume was lost.
                    Repeater {
                        model: win.queuedNotes
                        delegate: Para {
                            required property var modelData
                            width: agentsCol.width
                            color: win.fgDim
                            text: "  waiting for the next agent: " + modelData
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
                                        color: win.fgDim
                                        text: lrow.modelData.what
                                    }
                                    MouseArea {
                                        id: lma
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        acceptedButtons: Qt.RightButton
                                        onClicked: (m) => {
                                            var p = mapToItem(null, m.x, m.y);
                                            win.rowMenu(lrow.modelData.commit + "  "
                                                        + lrow.modelData.what, p.x, p.y);
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

    function rowMenu(text, x, y) {
        var items = [];
        if (text !== "")
            items.push({ label: "copy line", trigger: () => Board.copy(text) });
        menu.open(x, y, items.concat(fileItems()));
    }
}
