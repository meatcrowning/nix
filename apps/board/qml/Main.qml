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
    readonly property color fgAccent:  win.active ? Theme.accent  : Theme.inactive
    readonly property color fgAccent2: win.active ? Theme.accent2 : Theme.inactive
    readonly property color fgText:    win.active ? Theme.text    : Theme.inactive
    readonly property color fgDim:     win.active ? Theme.textDim : Theme.inactive

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
    // NEEDS YOU is drawn in a DISPLAY order held here, not in `board.md`'s own
    // order ([his answer, 2026-08-01]: a drag rearranges the on-screen order and
    // the store's sections stay intact — the same model the four top-level bands
    // already use). `needsOrder` is a saved list of decision keys; unknown keys
    // (a decision just added, or one handed back) keep their file position after
    // the known ones. The store is never rewritten by a reorder.
    readonly property var needs: win.applyDisplayOrder(
        doc && doc.needs ? doc.needs : [], win.needsOrder, "key")
    readonly property var todo: doc && doc.todo ? doc.todo : []
    // The same bullets as `todo`, in sub-sections by what they SAY THEY ARE.
    // Grouped once per load in `boardparse.todo_groups()`, never here: a view
    // that regrouped per delegate would do it on every scroll (§2.3's ingest
    // rule, the same reason the glyph map lives at the parse). `todo` stays the
    // flat list everything else — removal, undo, reply — still works from.
    readonly property var todoGroups: {
        var g = doc && doc.todoGroups ? doc.todoGroups : [];
        // The SUMMONED/COMMANDED announcements are hidden unless the inner
        // titlebar cell is lit (`showSummoned`, below). `boardparse.section_of`
        // draws COMMANDED under the SUMMONED group, so dropping the one group
        // whose tag is "SUMMONED" hides both.
        return win.showSummoned
             ? g : g.filter(function(x) { return String(x.tag) !== "SUMMONED"; });
    }
    readonly property var landed: doc && doc.landed ? doc.landed : []
    readonly property var intro: doc && doc.intro ? doc.intro : ({})

    // The machine, not the store: who is running, and what he has written to
    // them that nobody has picked up yet (`boardagents.py`).
    readonly property var agents: Agents.list
    // TWO LISTS OUT OF ONE ORDERING — [his, 2026-07-29, asked twice] *"solmon
    // should be in his own \"summoner\" section above the agents section"*. He
    // used to be a row pinned to the top of this list. `boardwork.cards()` still
    // decides the whole order (the pin, birth under it, the standing row when
    // nothing runs) and `main.py` splits that one list in two, so the two
    // sections cannot disagree about who is where.
    readonly property var summonerCards: Agents.summoner
    readonly property var agentCards: Agents.workers
    readonly property var queuedNotes: Agents.queued
    // The triangle's LIVE SHELLS — a little tail per bound minister ([his ask,
    // 2026-08-01]). `main.py` builds them off the same `workers` list, so this
    // can never disagree with the cards above it about who is bound.
    readonly property var agentShells: Agents.shells
    // Is anything actually HAPPENING? This is the WORKERS' list now, so the
    // question is just whether it is empty — Solomon's standing row, which is
    // drawn whether or not anything is running, is in his own section above.
    readonly property bool nothingRunning: win.agentCards.length === 0

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

    // CTRL+Z TAKES THE LAST ORDER BACK, and hands his words back to him.
    //
    // [his, 2026-07-29] *"before solomon summons a minister, allow the user to
    // crtl+z to stop solomon from doing that ... and then insert the prompt back
    // into the prompt box for the user to edit. if the last prompt had to be
    // placed in the pending [orders] section, then ctrl+z should remove it from
    // the pending list and insert it back into the prompt box"*. Two cases, one
    // key, one path: `boardundo.cancel()` answers both and `main.py` turns each
    // answer into a sentence. What comes back here is that sentence plus, ONLY
    // when something was really cancelled, the text — so a box refilled by this
    // is proof the summon did not happen.
    function undoSend() {
        var r = Agents.undoSend();
        win.status = r.said;
        if (r.text === "")
            return;
        // NOTHING HE TYPED IS THROWN AWAY — `InputBox.qml`'s rule, and the box
        // can genuinely hold a draft already (he typed, sent, typed again, then
        // clicked away, which is what makes the key ours rather than the
        // editor's). So the cancelled order goes ABOVE what is in there and the
        // footer says it did, rather than overwriting a sentence of his.
        var had = win.draftOf("msg:queue");
        if (had.trim() !== "" && had.trim() !== r.text.trim()) {
            askBox.restore(r.text + "\n" + had);
            win.status = r.said + " - above the draft that was in the box";
        } else {
            askBox.restore(r.text);
        }
    }

    // The key is only OURS while there is an order to take back (§10.2 — never
    // offer an action that no-ops). The rest of the time it is not bound at all,
    // so Ctrl+Z is the ordinary undo of whatever text field has the caret; and
    // it stays that even when there IS one, because a shortcut that fired while
    // he was mid-sentence in a reply would eat the undo he actually meant. The
    // duck-type is the whole test: everything on this board that edits text is a
    // `TextEdit`, and nothing else has a `cursorPosition`.
    readonly property bool inAnEditor: win.activeFocusItem !== null
                                       && win.activeFocusItem.cursorPosition !== undefined
    Shortcut {
        sequences: [StandardKey.Undo]
        enabled: Agents.canUndo && !win.inAnEditor
        onActivated: win.undoSend()
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
    // KEYED ON THE BULLET'S OWN TEXT. A bullet's line number is what the rest
    // of this app addresses it by, and it is exactly the wrong key here: the
    // file is rewritten under this window by agents and by the docs sync, so a
    // line remembered as folded would come back folded over a DIFFERENT chore —
    // the one failure this list may not have. The text moves with the bullet
    // and cannot do that; two identical bullets folding together is a tie, not
    // a lie, and an agent rewording one unfolds it, which is right.
    //
    // PERSISTED (§14), by the same `Settings` the section folds use: the text
    // key survives a relaunch because the bullet itself survives on disk, so
    // his per-message fold is restored the next time this window opens.
    property var todoFolded: ({})
    function isTodoFolded(t) { return todoFolded[t] === true; }
    function toggleTodoFolded(t) {
        var f = {};
        for (var i in todoFolded) f[i] = todoFolded[i];
        f[t] = !(f[t] === true);
        todoFolded = f;          // reassigned: a mutated object notifies nothing
        Settings.set("todoFolded", f);
    }

    // ---- ...and which pending orders he has expanded past their one line ----
    // A queued order is his own prose, and a long one crowded the whole page, so
    // `QueuedNote` draws it as ONE line until he expands it. The exception is
    // held HERE and keyed by the message id, not in the delegate: a queued row
    // is rebuilt whenever the queue list changes, so a bool in the delegate
    // would collapse on the next drain. Session-only, unlike `todoFolded`: an id
    // names a message board-watch will take, so there is nothing to remember
    // next time this window opens.
    property var queuedExpanded: ({})
    function isQueuedExpanded(id) { return queuedExpanded[String(id)] === true; }
    function toggleQueuedExpanded(id) {
        var e = {};
        for (var i in queuedExpanded) e[i] = queuedExpanded[i];
        var k = String(id);
        e[k] = !(e[k] === true);
        queuedExpanded = e;      // reassigned: a mutated object notifies nothing
    }

    // ---- ...and which cards have their output drawer open ----
    // [his, 2026-07-30] clicking a minister card slides a drawer out from under
    // it with what that minister is actually saying. Held HERE and keyed by the
    // AGENT'S ID, for the reason the caret below is: a card is destroyed and
    // rebuilt whenever the key list changes — one agent finishing is enough —
    // so a drawer remembered in the delegate, or by list index, would shut
    // itself on the next poll or reopen under a different agent's card. Several
    // at once is the point, hence a map.
    //
    // Session-only, like `todoFolded`: an id names one process that no longer
    // exists next time this window opens, so there is nothing there to remember.
    // The map holds EXCEPTIONS to `allLogs` below, not absolute states — see
    // there for why a per-card entry cannot be the whole answer.
    property var outputOpen: ({})
    function isOutputOpen(id) {
        var v = outputOpen[String(id)];
        return v === undefined ? allLogs : v === true;
    }
    function toggleOutputOpen(id) {
        var o = {};
        for (var i in outputOpen) o[i] = outputOpen[i];
        var k = String(id);
        // Back to the default is the ABSENCE of an entry, never an entry that
        // happens to equal it: otherwise a card he opened and shut again would
        // stay pinned shut when the global switch is next turned on.
        if (isOutputOpen(k) === allLogs) o[k] = !allLogs; else delete o[k];
        outputOpen = o;          // reassigned: a mutated object notifies nothing
    }

    // ---- ...and the one switch that opens EVERY card's drawer ----
    // [his, 2026-07-30] one control that expands, and collapses, the log view on
    // all cards at once. It is a DEFAULT, not a bulk edit of the map above, and
    // that is the whole design: cards come and go on every 2.5s poll, so a
    // switch that merely wrote `true` into the ids present when he pressed it
    // would leave the next agent to appear shut — which is not "all cards".
    //
    // PERSISTED (§14), unlike the exception map: this is a view preference he
    // sets by using the app and would notice reverting, and it names no process,
    // so it still means the same thing tomorrow. Flipping it CLEARS the
    // exceptions, so both directions are visible on every card at once rather
    // than on all but the few he had touched by hand.
    property bool allLogs: false
    function toggleAllLogs() {
        allLogs = !allLogs;
        outputOpen = ({});
        Settings.set("allLogs", allLogs);
    }

    // [his, 2026-08-01] *"i actually don't need to see the summoned / commanded
    // messages. those can be hidden behind a button in the inner left
    // titlebar."* A view-only filter on `todoGroups` above; default HIDDEN,
    // remembered across relaunch like `allLogs`. The two summon tags share one
    // drawn group (`section_of` folds COMMANDED into SUMMONED), so one flag
    // governs both, and the titlebar cell is lit exactly when they are shown.
    property bool showSummoned: false
    function toggleSummoned() {
        showSummoned = !showSummoned;
        Settings.set("showSummoned", showSummoned);
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

    // ---- a reload must not rebuild the world (§6.1) ----
    // Every list on this page used to hand its Repeater the ROWS themselves,
    // and a Repeater over a JS array has no diff: change one character in one
    // row and every delegate on the page is destroyed and built again. That is
    // invisible for a paragraph and ruinous for the one thing on this page he is
    // ever half-way through — an open editor, which loses its focus, its caret
    // and the keystroke he was in the middle of typing. `board.md` is rewritten
    // under this window by an unattended watcher AND by the five-minute docs
    // sync, so a reload lands mid-word as a matter of routine.
    //
    // So the model is the list of KEYS instead. Qt compares the value written
    // to `model`: an equal list is not a change, so a row whose text moved
    // updates THROUGH the delegate's own binding and the delegate itself is
    // never touched. Only a row appearing, leaving or changing place rebuilds
    // anything, which is the one case where there is no delegate to keep.
    //
    // The keys are the ones the rest of this app already addresses a row by — a
    // decision's `key`, a chore's `line`, an agent's `id` — so nothing here
    // invents an identity the store does not have. The delegate gets its row
    // back by INDEX, the key list being built from the row list in order: the
    // two are parallel, and a delegate still alive is one whose key did not
    // move. `modelData` therefore still means what it always meant — the row.
    function keysOf(rows, field) {
        var out = [];
        for (var i = 0; i < rows.length; i++)
            out.push(String(rows[i][field]));
        return out;
    }

    // ---- drag-to-reorder: the four top-level SECTIONS, by their bands ----
    // [his ask, 2026-08-01]. The grip on each top-level band reports `key` and
    // `dy` (pixels, positive = dragged down). We take the band's RESTING centre,
    // add the displacement, and count how many other section headers centre
    // above it — that is the section's new position. A no-op (crossed nothing)
    // writes nothing (§12.1); a real move repersists `sectionOrder` to Settings
    // and the `Repeater` re-lays the sections (§6.1's diff trick — equal lists
    // are not a change, so only a real move rebuilds).
    //
    // PERSISTED SEPARATELY, NOT IN board.md ([his answer, 2026-08-01]): the page
    // order is a display order only (`guide/drawing.md`), and summoner and the
    // triangle are the machine, not the store — there is nowhere for them in
    // board.md. So the order lives in `~/.local/state/board/state.json`, the
    // same `Settings` the folds and drafts use, never in the store file.
    // [his re-ask, 2026-08-02] EVERY heading is a full section he can place
    // anywhere: `to do` and `shells` used to be trapped inside `needs` and the
    // triangle, so he could not lift `to do` above the decisions or drop it
    // below `summoner`. They are top-level entries now, so all six bands drag.
    property var sectionOrder: ["needs", "todo", "summoner", "agents", "shells", "spend", "landed"]
    function normalizeOrder(o) {
        var def = ["needs", "todo", "summoner", "agents", "shells", "spend", "landed"];
        var out = [];
        if (o) for (var i = 0; i < o.length; i++)
            if (def.indexOf(o[i]) >= 0 && out.indexOf(o[i]) < 0) out.push(o[i]);
        // A key the saved order never knew about (an older state.json from
        // before `to do`/`shells` were promoted) is inserted at its DEFAULT
        // neighbour, not appended at the end — so a first launch after the
        // upgrade puts them where they have always sat, not below `landed`.
        for (var j = 0; j < def.length; j++) {
            if (out.indexOf(def[j]) >= 0) continue;
            var at = 0;
            for (var p = j - 1; p >= 0; p--) {
                var idx = out.indexOf(def[p]);
                if (idx >= 0) { at = idx + 1; break; }
            }
            out.splice(at, 0, def[j]);
        }
        return out;
    }
    function reorderSection(key, dy) {
        var order = win.sectionOrder.slice();
        var from = order.indexOf(key);
        var n = order.length;
        if (n < 2 || from < 0)
            return;
        var center = function (i) {
            var it = sectionsRepeater ? sectionsRepeater.itemAt(i) : null;
            return it ? it.y + it.height / 2 : 0;
        };
        var myCenter = center(from) + (dy || 0);
        var target = 0;
        for (var i = 0; i < n; i++)
            if (i !== from && myCenter >= center(i)) target++;
        if (target === from)
            return;
        var k = order.splice(from, 1)[0];
        order.splice(target, 0, k);
        win.sectionOrder = order;
        Settings.set("sectionOrder", order);
    }
    function jumpSection(key) {
        for (var i = 0; i < win.sectionOrder.length; i++)
            if (win.sectionOrder[i] === key && sectionsRepeater.itemAt(i)) {
                win.jump(sectionsRepeater.itemAt(i));
                return;
            }
    }

    // ---- drag-to-reorder: the DECISIONS within NEEDS YOU, same display model ----
    // [his answer, 2026-08-01] a drag rearranges only the on-screen order; the
    // store keeps its sections intact and the arrangement lives in state.json,
    // exactly as the top bands already do. `needsOrder` is a saved list of
    // decision keys. `applyDisplayOrder` draws the rows in that order, with any
    // key it does not mention (a decision just added, or one handed back) kept in
    // its file position after the ordered ones — so a new question is never lost
    // and never jumps to the top. board.md is never rewritten by a reorder.
    property var needsOrder: []
    function applyDisplayOrder(rows, order, field) {
        if (!order || order.length === 0)
            return rows;
        var byKey = {};
        for (var i = 0; i < rows.length; i++)
            byKey[String(rows[i][field])] = rows[i];
        var out = [], used = {};
        for (var j = 0; j < order.length; j++) {
            var k = String(order[j]);
            if (byKey[k] !== undefined && !used[k]) { out.push(byKey[k]); used[k] = true; }
        }
        for (var m = 0; m < rows.length; m++) {
            var rk = String(rows[m][field]);
            if (!used[rk]) { out.push(rows[m]); used[rk] = true; }
        }
        return out;
    }
    function setNeedsOrder(keys) {
        var o = [];
        for (var i = 0; i < keys.length; i++) o.push(String(keys[i]));
        win.needsOrder = o;
        Settings.set("needsOrder", o);
    }

    // ---- drag-to-reorder ACROSS the NEEDS YOU content — [his ask, 2026-08-01] ----
    // *"i should be able to drag any subheading from any heading to any place
    // (full cross-section free-drag), not just reorder within a section or the
    // top-level bands."* The two orders above only move like-with-like: decisions
    // among decisions, bands among bands. This one is the CROSS-section one — the
    // NEEDS YOU sub-blocks (each decision, and the to-do area as a whole) share
    // ONE flat display order, so a decision can be dropped below the to-do area
    // and the to-do area lifted up among the decisions. Same rule as every other
    // drag on this page: it is a DISPLAY order in state.json, `board.md` is never
    // rewritten (`guide/drawing.md`), and a stale or hand-edited value cannot drop
    // a block — `applyDisplayOrder` keeps any bkey the saved list does not mention
    // in its default position, so a decision just added is drawn, never lost.
    //
    // The decisions reorder among themselves here. `to do` is no longer one of
    // these blocks: [his re-ask, 2026-08-02] it is a top-level section now, so
    // it lifts above the decisions or drops below `summoner` through
    // `sectionOrder`, not through this within-needs order. The tag groups inside
    // `to do` keep their own order and folds; whether each should also be
    // independently placeable among the decisions is a further step for his call.
    property var needsBlockOrder: []
    readonly property var needsBlocks: {
        var out = [];
        var nd = win.needs;
        for (var i = 0; i < nd.length; i++)
            out.push({ kind: "decision",
                       bkey: "dec:" + String(nd[i].key),
                       dec: nd[i] });
        return win.applyDisplayOrder(out, win.needsBlockOrder, "bkey");
    }
    function setNeedsBlockOrder(keys) {
        var o = [];
        for (var i = 0; i < keys.length; i++) o.push(String(keys[i]));
        win.needsBlockOrder = o;
        Settings.set("needsBlockOrder", o);
    }

    // ---- ...and where his caret is, for the reload that CANNOT keep a row ----
    // A row appearing or leaving changes the key list, so that one list is built
    // again and the box he was typing in goes with it. One key and one offset,
    // held here rather than in the delegate — the delegate is the thing that
    // goes away — and every editor on the page reports into it, so there is
    // exactly one holder and a rebuilt row cannot take the caret off another box
    // that has it. Cleared only when HE leaves an editor: a destruction must
    // never clear it, or the rebuild would erase what this exists to restore.
    property string caretIn: ""
    property int caretPos: -1
    function caretHeld(k, pos) { caretIn = k; caretPos = pos; }
    function caretLeft(k) { if (caretIn === k) { caretIn = ""; caretPos = -1; } }
    function caretOf(k) { return caretIn === k ? caretPos : -1; }

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
        allLogs = Settings.get("allLogs", false) === true;
        showSummoned = Settings.get("showSummoned", false) === true;
        var tf = Settings.get("todoFolded", {});
        todoFolded = (tf && typeof tf === "object") ? tf : ({});
        // The saved display order of the four sections, validated so a stale or
        // hand-edited value can never drop a section from the page.
        win.sectionOrder = win.normalizeOrder(Settings.get("sectionOrder", null));
        // The saved display order of the NEEDS YOU decisions. A stale or
        // hand-edited value cannot drop a decision: `applyDisplayOrder` keeps
        // any key the saved list does not mention.
        // Iterated by `.length`, not `Array.isArray`: `Settings.get` hands QML a
        // QVariant list for which `Array.isArray` is FALSE, so the old form loaded
        // an empty order every launch and a reordered decision list never survived
        // a relaunch (it held only in-session, on the live property).
        var no = Settings.get("needsOrder", null);
        var nord = [];
        if (no) for (var ni = 0; ni < no.length; ni++) nord.push(String(no[ni]));
        win.needsOrder = nord;
        // The saved cross-section order of the NEEDS YOU sub-blocks (decisions +
        // the to-do area). `applyDisplayOrder` keeps any block the saved list
        // omits, so a stale value cannot hide one. Iterated by `.length` rather
        // than `Array.isArray`, which is false for the QVariant list `Settings.get`
        // returns — the same reason `normalizeOrder` iterates it directly.
        var nb = Settings.get("needsBlockOrder", null);
        var nbo = [];
        if (nb) for (var bi = 0; bi < nb.length; bi++) nbo.push(String(nb[bi]));
        win.needsBlockOrder = nbo;
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
        // position is put back where it was rather than jumping to the top —
        // and, since 2026-07-30, nothing is said about it either. It used to
        // put `the board changed on disk - reloaded` in the titlebar footer,
        // which is the same rule breaking itself: every agent write and every
        // five-minute sync flashed text onto the inner bar for something he
        // did not do and cannot act on. The rows changing is the report.
        function onReloaded() {
            var y = scroller.contentY;
            Qt.callLater(function () {
                scroller.contentY = Math.max(0, Math.min(y, scroller.contentHeight
                                                            - scroller.height));
            });
        }
    }

    // A refresh HE asked for, reported in his own words rather than in a reason
    // word (§10): a click on a meter that cannot reach the account has to say
    // that it could not, or it is an inert control with a pointing cursor over
    // it. Only hand-driven fetches emit this — the 60s and 300s clocks stay
    // silent, since nothing just happened at his hand (§10.4).
    Connections {
        target: Usage
        function onRefreshed(why) {
            if (why === "ok")
                win.status = "usage reading refreshed";
            else if (why === "off")
                win.status = "usage fetching is off here - showing the last reading";
            else if (why === "offline")
                win.status = "no network - showing the last reading, with its age";
            else if (why === "expired" || why === "no-token" || why === "unauthorized")
                win.status = "claude-code needs signing in again - showing the last reading";
            else
                win.status = "could not refresh usage (" + why
                             + ") - showing the last reading, with its age";
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
    // ("for now"). IN FLIGHT was the bottom-most and is gone [2026-07-30], so
    // LANDED is asked first and `needs` is still the fallback.
    //
    // `y > 0` on each test is NOT redundant: before the Column has laid out,
    // every section sits at y 0, so `contentY (0) >= 0 - 4` was TRUE for the
    // LAST section and the first thing the titlebar was told was that he is
    // looking at `if` — then it was corrected to `ny` a frame later. Every
    // REGISTER bumps the plugin's IPC serial and repaints the bar, so a wrong
    // one is a visible flash of the wrong lit cell. Only `needs` can honestly
    // be at y 0, and it is the fallback anyway.
    //
    // Since 2026-08-01 the four sections are order-driven (`sectionOrder`), so
    // the readout asks the SAME question over the Repeater's own delegates in
    // order, bottom-up, rather than over the old hardcoded `secLanded` /
    // `secAgents` / `summonerHead` ids. The `ag` cell covers summoner AND the
    // triangle — they are one region of the page (who is working on what) — so
    // either section matching lights it, exactly as the cell did before.
    readonly property string section: {
        var order = win.sectionOrder;
        for (var i = order.length - 1; i >= 0; i--) {
            var it = sectionsRepeater ? sectionsRepeater.itemAt(i) : null;
            if (!it || it.y <= 0 || scroller.contentY < it.y - 4) continue;
            var k = order[i];
            if (k === "landed") return "landed";
            if (k === "agents" || k === "summoner") return "agents";
        }
        return "needs";
    }
    // ...and the cells read left-to-right as the page reads top-to-bottom.
    readonly property var tbButtons: [
        { id: "needs",  label: "ny", state: section === "needs" ? 1 : 0,
          tip: "what needs you" },
        { id: "agents", label: "ag", state: section === "agents" ? 1 : 0,
          tip: "the triangle - who is running now" },
        { id: "landed", label: "ld", state: section === "landed" ? 1 : 0,
          tip: "what landed" },
        "-",
        { id: "reader", label: "md", state: 0, tip: "open board.md in reader" },
        // Its own section, under `md`: a toggle is not a jump and not a launch.
        // §12.1 — a lit cell IS the state (inverted, accent-filled), so there is
        // no second glyph for "off" and no status line saying what it did; the
        // drawers opening on every card say it. The tooltip names what the click
        // will DO, which is the half that is not on screen.
        "-",
        { id: "logs", label: "lg", state: allLogs ? 1 : 0,
          tip: allLogs ? "hide every card's log" : "show every card's log" },
        { id: "summoned", label: "sm", state: showSummoned ? 1 : 0,
          tip: showSummoned ? "hide the summoned + commanded notes"
                            : "show the summoned + commanded notes" },
    ]
    onTbButtonsChanged: Titlebar.setButtons(tbButtons)

    // [his, 2026-07-29] *"remove the 'goetia' text at the bottom of the inner
    // titlebar"* — so the footer is the STATUS and nothing else, and the bar is
    // empty down there when there is nothing to report. The program's name is
    // already the window title the plugin draws up the side of the same bar;
    // saying it twice was the redundancy §9.1 rules out, and a standing label is
    // not a report (the rule this property's own comment states).
    //
    // ...and since this slot is the ONLY text the inner bar ever holds, what
    // goes in it is now scoped to match: **a failure, or an outcome nothing
    // else on screen shows** — where an order went, what Ctrl+Z took back, why
    // a usage refresh he asked for could not happen. Not a confirmation of a
    // control that relabels itself (the four choosers), and not maintenance he
    // did not ask for (a reload). Both of those appeared and left again with
    // an empty bar on either side, which is what he reads as the bar flashing
    // text at him ([his, 2026-07-30], `capItems` below).
    readonly property string footerStr: status
    onFooterStrChanged: Titlebar.setFooter(footerStr)

    // ...and the stacked title beside it is NOT ours to turn off. [his,
    // 2026-07-29] *"really for now there should be no title text in the left
    // side inner bar of goetia"* was answered with `TITLETEXT 0`, and that was
    // the wrong lever: the stacked title is drawn in the OUTER column, while the
    // inner bar he was talking about only ever holds the app buttons and the
    // footer. So the flag suppressed the title on the RIGHT OUTER bar, where he
    // had not asked for anything, and the inner bar was already nameless.
    // Dropped 2026-07-30 (Kimaris' finding); goetia now reads
    // `"titleText":true` in `~/.local/state/hyprvtb/ipc-dump.json`. The
    // `Titlebar.setTitleText` wrapper in `main.py` stays — the plugin verb is
    // correct and is what an app with a real document identity would use.

    function jump(item) {
        scroller.contentY = Math.max(0, Math.min(item.y,
                                                 scroller.contentHeight - scroller.height));
    }

    Connections {
        target: Titlebar
        function onClicked(id) {
            switch (id) {
            case "needs":  win.jumpSection("needs"); break;
            // The `ag` cell jumps to the TOP of the region it names — summoner
            // is above the triangle, so that is where the cell points, whether
            // or not he has since moved the sections around.
            case "agents": win.jumpSection("summoner"); break;
            case "landed": win.jumpSection("landed"); break;
            case "summoned": win.toggleSummoned(); break;
            case "reader":
                if (!Board.openInReader())
                    win.status = "could not run reader";
                break;
            case "logs":   win.toggleAllLogs(); break;
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
            //   * `summonerPick` sits at y 0 and the rest of the column — the
            //     summoner model, the cap, the minister model, then the meters —
            //     hangs off it, and nothing in it looks at the box.
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
                readonly property real pickCol: ministerPick.y + ministerPick.height
                    + (usageCol.visible ? 4 + usageCol.height : 0)

                // ONE edge for the whole column, and it is the widest control in
                // it — his rule for the meters ("exactly as wide as the model
                // selection box") is that the column has a single right and a
                // single left edge, and four dropdowns of different label lengths
                // would otherwise give it five. Bound to the labels, never a
                // number, so a longer model name still widens all of it (§2.7).
                readonly property real colW:
                    Math.max(summonerPick.implicitWidth, modelPick.implicitWidth,
                             capPick.implicitWidth, ministerPick.implicitWidth)

                // ...and ONE arrow column, for the same reason. Every label is
                // padded out to the longest of the four so the `v` on each lands
                // on the same cell; a character count, because the font is
                // monospace and the controls are centred (§2.7).
                readonly property int pickCells:
                    Math.max(Agents.summonerLabel.length, Agents.modelLabel.length,
                             Agents.capLabel.length, Agents.ministerLabel.length)

                InputBox {
                    id: askBox
                    width: parent.width - parent.colW - 10
                    minHeight: parent.pickCol - summonerPick.y
                    fgAccent: win.fgAccent
                    fgText: win.fgText
                    fgDim: win.fgDim
                    draft: win.draftOf("msg:queue")
                    placeholder: "type anything and press enter to command Solomon and his ministers"
                    hintText: "enter sends - shift+enter is a new line - esc keeps a draft"
                    // This box is never a delegate and is never rebuilt, so it
                    // takes no `openCaret` — it reports only, which is what
                    // stops a row appearing below it from stealing his caret.
                    onDraftEdited: (b) => win.setDraft("msg:queue", b)
                    onSubmitted: (b) => win.sendTo(null, b)
                    onCaretHeld: (p) => win.caretHeld("msg:queue", p)
                    onCaretLeft: () => win.caretLeft("msg:queue")
                }

                // FOUR of these, and the ORDER IS HIS. [his, 2026-07-29] *"1.
                // number of summoners 2. summoner model 3. number of ministers
                // 4. minister model"* — so the column reads count, model, count,
                // model, and each count names the role of the model under it.
                // That pairing is what lets the labels stay as short as they are:
                // `fable 5` on its own is ambiguous between the two models, and
                // `1 summoner` directly above it is not.
                //
                // Every one of them is a MENU, not a combo box: §7.2 says menus
                // on this desktop are ours and are `CtxMenu`, and a chooser with a
                // handful of entries is that menu with a resting label. They are
                // one component (`PickBox.qml`) because they are one control —
                // [his, 2026-07-29] the second was *"another drop down"*, in the
                // idiom of the first — and the tick beside each live entry comes
                // from `boardwork`, so none of them can disagree with what will
                // actually happen.
                PickBox {
                    id: summonerPick
                    padTo: parent.pickCells
                    anchors.right: parent.right
                    // Flush with the box's own top, not inset by the 3px the
                    // box pads its first line by: the box is as tall as this
                    // column, so the two are only "the same height" if they
                    // start and end on the same rows.
                    y: 0
                    width: parent.colW
                    label: Agents.summonerLabel
                    // What it changes and WHEN, which is the whole promise: a
                    // summoner already planning is not restarted, and a tick with
                    // one sentence in it runs one summoner however high this is.
                    hint: "how many summoners may plan at once - the next tick honours it"
                    items: () => win.summonerItems()
                    popup: menu
                    fgDim: win.fgDim
                    fgAccent: win.fgAccent
                }

                PickBox {
                    id: modelPick
                    padTo: parent.pickCells
                    anchors.top: summonerPick.bottom
                    anchors.topMargin: 4
                    anchors.right: summonerPick.right
                    width: parent.colW
                    label: Agents.modelLabel
                    // What it changes, and WHEN it takes effect. The second half
                    // is the whole of the promise: a running orchestrator is not
                    // restarted and not re-pointed.
                    hint: "which model a summoner reads what you type on, and how hard it thinks - the one running now keeps its own"
                    items: () => win.modelItems()
                    popup: menu
                    fgDim: win.fgDim
                    fgAccent: win.fgAccent
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
                    padTo: parent.pickCells
                    anchors.top: modelPick.bottom
                    anchors.topMargin: 4
                    anchors.right: modelPick.right
                    width: parent.colW
                    label: Agents.capLabel
                    hint: "the most ministers allowed to work at once - the next tick honours it"
                    items: () => win.capItems()
                    popup: menu
                    fgDim: win.fgDim
                    fgAccent: win.fgAccent
                }

                // ...and under THAT, what those ministers run on. [his,
                // 2026-07-29] *"do not allow ministers to be anything higher than
                // opus 5 medium thinking."* So this control offers
                // `boardwork.MINISTER_MODELS` and nothing else, ceiling first —
                // and the ceiling is enforced AGAIN at the spawn
                // (`boardwork.role_flags`), because a control is not a guard
                // against a file he or an agent edited by hand.
                //
                // The label carries the thinking budget as well as the family
                // (`opus 5 medium`) — it is one choice, and a chooser that showed
                // only half of what it set would be the §10 failure with a
                // shorter string.
                PickBox {
                    id: ministerPick
                    padTo: parent.pickCells
                    anchors.top: capPick.bottom
                    anchors.topMargin: 4
                    anchors.right: capPick.right
                    width: parent.colW
                    label: Agents.ministerLabel
                    hint: "what ministers run on, up to opus 5 medium - the next one dispatched gets it"
                    items: () => win.ministerItems()
                    popup: menu
                    fgDim: win.fgDim
                    fgAccent: win.fgAccent
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
                // above it … stacked vertically"*. The width is bound to the
                // dropdown column (`ministerPick`, its foot), not to a number,
                // so the box and the bars stay flush when a longer model name
                // widens it.
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
                    anchors.top: ministerPick.bottom
                    anchors.topMargin: 4
                    anchors.right: ministerPick.right
                    width: ministerPick.width
                    visible: (Usage.rows.length + Usage.hrows.length) > 0
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
                            // A click is a refresh [his, 2026-07-30]. The meter
                            // draws the in-flight state itself; the OUTCOME is a
                            // report, so it goes where every other report in
                            // this window goes — the footer (§10, and `PickBox`'s
                            // note on why a hover is not allowed there).
                            busy: Usage.busy
                            onRefreshRequested: {
                                win.status = "refreshing the usage reading...";
                                Usage.refreshNow();
                            }
                        }
                    }

                    // ===================== hermes minister usage =====================
                    // [his, 2026-07-31] when a minister runs on the hermes
                    // (deepseek) backend, keep his Anthropic bars as they are and
                    // show the real hermes usage here. These are FIGURES — tokens
                    // and cost Hermes recorded for `source='tool'` sessions
                    // (`boardusage.hermes_readings`) — never a percentage, because
                    // there is no published hermes limit to be a % of
                    // (docs/DESIGN.md §10; `boardusage`'s docstring). Same
                    // paired-edge row as the meters, without the bar: window name
                    // hard left, figures hard right.
                    Item { width: 1; height: 4 }
                    PixelText {
                        text: "hermes ministers"
                        color: Theme.textDim
                    }
                    // The one hermes "how much I have left" figure [his,
                    // 2026-07-31]: he chose to count DOWN FROM THE REAL NOUS
                    // ACCOUNT BALANCE, so this row is `Usage.hprox` —
                    // `boardusage.hermes_proximity()`, the balance the portal
                    // publishes (remaining + monthly % used when the plan
                    // defines a cap), or the honest unknown when it has not read
                    // one here yet. Bound, never derived (§5.3, §10).
                    //
                    // It used to pair a "balance" label against the figure on
                    // the same line; at the column's width the two could not
                    // both fit and the figure's left edge ran under the label,
                    // so the reading looked broken. §5.4 says the content
                    // identifies itself — "13% used · $19.06 left" needs no word
                    // in front of it — so the label came off and the figure is
                    // the whole clean line. The two FIGURE rows that used to sit
                    // under it (5h and 7d tokens+cost) are gone too: the
                    // percentage is the entire readout now, and what it does not
                    // say about itself lives in the tooltip.
                    Item {
                        id: hproxrow
                        width: usageCol.width
                        height: lineH
                        readonly property int lineH: Theme.fontSize + 4
                        PixelText {
                            y: Math.round((hproxrow.lineH - height) / 2)
                            color: Usage.hprox && Usage.hprox.known
                                   ? Theme.text : Theme.textDim
                            text: Usage.hprox ? (Usage.hprox.text || "unknown")
                                              : "unknown"
                        }
                        // ...and when this window COMES BACK is the row's own
                        // tooltip — `boardusage.hermes_proximity()`'s
                        // `resets in ____` (`_left` on the nous account's
                        // `renews`), one short line, never empty (§10), the same
                        // wording every usage meter's tooltip uses. [his,
                        // 2026-07-30] "the tooltip should just say `resets in
                        // ____`".
                        ToolTipArea {
                            anchors.fill: parent
                            text: (Usage.hprox && Usage.hprox.reset)
                                  ? Usage.hprox.reset : ""
                        }
                    }
                    // ...and the TOP-UP money left [his, 2026-08-02: "hermes
                    // agent usage should also show the top up money left as
                    // well"]. The row above counts down the monthly
                    // subscription; this one is the purchased pay-as-you-go pool
                    // (`boardusage.hermes_topup` -> the portal's
                    // `purchased_credits_remaining`), the money that is actually
                    // left when the subscription credits are spent. Same clean
                    // self-identifying line as the row above (§5.4) — "$18.70
                    // top-up left" needs no label — bound never derived (§5.3,
                    // §10), and an honest "top-up unknown" until the account has
                    // been read here.
                    Item {
                        id: htopuprow
                        width: usageCol.width
                        height: lineH
                        readonly property int lineH: Theme.fontSize + 4
                        PixelText {
                            y: Math.round((htopuprow.lineH - height) / 2)
                            color: Usage.htopup && Usage.htopup.known
                                   ? Theme.text : Theme.textDim
                            text: Usage.htopup ? (Usage.htopup.text || "top-up unknown")
                                               : "top-up unknown"
                        }
                        // The hover carries the read age — the same §3.5 honesty
                        // the Anthropic meters draw, so a stale figure says so.
                        ToolTipArea {
                            anchors.fill: parent
                            text: (Usage.htopup && Usage.htopup.detail)
                                  ? Usage.htopup.detail : ""
                        }
                    }
                }
            }

            Item { width: 1; height: 14 }
            // The gutter is read off the bar itself: its width is a setting and
            // ranges 11-16px, and four call sites across the tree used to leave
            // content under an opaque bar by hardcoding a 10 or a 12 (§9.2).
            width: scroller.width - win.pad * 2 - vbar.barW

            // ========================================== the four sections
            // [his ask, 2026-08-01] needs / summoner / the triangle / landed
            // are drawn in `win.sectionOrder`: drag one of their bands to move
            // it, and the new display order persists to Settings, not board.md
            // (summoner and the triangle are the machine, not the store —
            // guide/drawing.md). Keyed on the order array so a drop just
            // changes the model and the Column re-lays everything (§6.1's
            // diff trick — an equal list is not a change, so a no-op reload
            // touches nothing).
            Column {
                id: sectionsCol
                width: page.width
                Repeater {
                    id: sectionsRepeater
                    model: win.sectionOrder
                    delegate: Loader {
                        readonly property string sectionKey: String(modelData)
                        width: sectionsCol.width
                        // Size to the loaded section so the Column lays the
                        // sections out by their real heights (§6.1); when one
                        // collapses or grows the re-flow follows.
                        //
                        // Read the item's IMPLICIT height, not its height: a
                        // Loader with an explicit `height` also *forces*
                        // `item.height := Loader.height`, so `height: item.height`
                        // is a feedback loop with no independent driver and sticks
                        // at whatever transient it first hit (~161px), leaving the
                        // section shorter than its own cards. The overflow still
                        // PAINTS (clip is false) but falls outside the section's
                        // hit-test bounds, so clicks on a card below the fold never
                        // reached it. `implicitHeight` is driven only by the
                        // children, so it breaks the loop (2026-08-01).
                        height: item ? item.implicitHeight : 0
                        sourceComponent: {
                            switch (String(modelData)) {
                            case "needs": return needsSection
                            case "todo": return todoSection
                            case "summoner": return summonerSection
                            case "agents": return agentsSection
                            case "shells": return shellsSection
                            case "spend": return spendSection
                            case "landed": return landedSection
                            }
                            return null
                        }
                    }
                }
            }


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


Component {
    id: needsSection
    //: the section as a delegate of the page's `sectionsCol` Repeater,
    //  so dragging its band reorders it ([his answer, 2026-08-01]: the
    //  four top-level sections move, persisted apart from board.md). The
    //  root is a Column so it sizes to its children exactly as the old
    //  page Column did — a section's collapse, growth or shrinkage re-flows
    //  the ones below it.
    Column {
        id: needsSectionRoot
        width: page.width
        // Prohibit the Loader from resizing this root to its own (initially 0)
        // size: an explicit `height` here is what lets the needs section keep
        // its own height and the sections below it lay out by it (2026-08-01).
        height: implicitHeight

        //: drag-to-reorder a NEEDS YOU sub-block to any position among the others
        //  — a decision, or the to-do area as a whole ([his ask, 2026-08-01], full
        //  cross-section free-drag; see `win.needsBlocks`). It lives here, not on
        //  `win`, so the grip can reach the section's OWN `blockRepeater` — the
        //  page can no longer name it, now that the section is a delegate. Same
        //  target math as the section bands: the dragged block's resting centre +
        //  displacement, count how many other blocks centre above it. The new
        //  order is a DISPLAY order saved in state.json ([his answer, 2026-08-01]),
        //  never a rewrite of board.md.
        function reorderBlock(bkey, dy) {
            var blocks = win.needsBlocks;
            var n = blocks.length;
            var from = -1;
            for (var i = 0; i < n; i++)
                if (blocks[i].bkey === bkey) { from = i; break; }
            if (n < 2 || from < 0)
                return;
            var center = function (i) {
                var it = blockRepeater.itemAt(i);
                return it ? it.y + it.height / 2 : 0;
            };
            var myCenter = center(from) + (dy || 0);
            var target = 0;
            for (var k = 0; k < n; k++)
                if (k !== from && myCenter >= center(k)) target++;
            if (target === from)
                return;
            var keys = [];
            for (var j = 0; j < n; j++)
                keys.push(blocks[j].bkey);
            var moved = keys.splice(from, 1)[0];
            keys.splice(target, 0, moved);
            win.setNeedsBlockOrder(keys);
        }

                // ================================================ what needs you
                // NO LABEL — [his, 2026-07-29] "just have the line and collapse
                // toggle". The band keeps its accent rule and its `[-]`, and the
                // rule simply starts where the word used to. The whole band has
                // always been the MouseArea (`SectionHead`), so losing the label
                // costs the toggle no hit target; the section still reads as one
                // because the accent rule is what told it apart (§9.1, §5.1).
                SectionHead {
                    id: headNeeds
                    width: page.width
                    label: ""
                    accented: true
                    collapsed: win.isCollapsed("needs")
                    fgAccent: win.fgAccent
                    fgDim: win.fgDim
                    reorderable: true
                    onToggled: win.toggleCollapsed("needs")
                    onReorderRequested: (dy) => win.reorderSection("needs", dy)
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

                        //: The line under the section rule is a CONSTANT — [his,
                        //: 2026-07-30] it must not change with what is in the
                        //: section, and the EMPTY wording is the one that stays:
                        //: [his, 2026-07-29] *"decisions brought to you from
                        //: Solomon."*. So the store's own framing paragraph is
                        //: never drawn here — it was already suppressed while the
                        //: section was empty, and drawing it once there was
                        //: something to frame made the same line say two different
                        //: things depending on the board's contents. One sentence,
                        //: one place, both states (§5.2).
                        readonly property string framing:
                            "decisions brought to you from Solomon."

                        //: EMPTY is the state he sees most often, and there this ONE
                        //: sentence is the whole of the section. `to do` is its own
                        //: top-level section now, so it no longer bears on whether
                        //: NEEDS YOU reads as empty — only the decisions do.
                        readonly property bool empty:
                            win.needs.length === 0

                        // Populated, the same sentence frames the cards: the
                        // paragraph treatment the store's intro used to have, in the
                        // empty state's own token so the line itself is unchanged.
                        Para {
                            width: needsCol.width
                            visible: !needsCol.empty
                            height: visible ? implicitHeight : 0
                            color: Theme.dim
                            text: needsCol.framing
                            bottomPadding: 8
                        }

                        // It must read as finished rather than as broken: no empty
                        // frame, no placeholder box, no "0 items" — one dim
                        // sentence in the token whose own job is "empty & unviewed"
                        // (§3.4), and the section rule above it unchanged so
                        // nothing looks missing.
                        Item {
                            width: needsCol.width
                            visible: needsCol.empty
                            implicitHeight: visible ? Theme.fontSize * 2 + 40 : 0
                            height: implicitHeight

                            PixelText {
                                anchors.centerIn: parent
                                width: parent.width
                                horizontalAlignment: Text.AlignHCenter
                                color: Theme.dim
                                text: needsCol.framing
                            }
                        }

                        // The NEEDS YOU decisions as a reorderable list
                        // (`win.needsBlocks`). Each decision is a block a drag can
                        // move among the others. `to do` used to be a block here too
                        // ([his ask, 2026-08-01]); [his re-ask, 2026-08-02] it is a
                        // top-level section now, so it drags among ALL the bands, not
                        // only within needs. Keyed on each block's stable `bkey`
                        // (`dec:<key>`), for
                        // the same reason the old decisions Repeater keyed on `key` —
                        // an agent editing one card must not pull the answer editor
                        // out from under him on another (see `keysOf`). The Loader
                        // sizes to its loaded block so the Column lays them out by
                        // their real heights, exactly as the top-level sectionsCol —
                        // and it reads the block's IMPLICIT height for the same
                        // reason that one does (see the comment there): a Loader
                        // with an explicit `height` force-resizes its item, which
                        // DESTROYS the item's own `height: implicitHeight` binding.
                        // Reading `item.height` then froze the to-do block at
                        // whatever it measured before its last bullet's wrapped
                        // elaboration laid out — 60px short — so the summoner
                        // section drew over the tail of a long INFORMATION bullet.
                        // `implicitHeight` is content-driven and keeps updating.
                        Repeater {
                            id: blockRepeater
                            model: win.keysOf(win.needsBlocks, "bkey")
                            delegate: Loader {
                                id: blockLoader
                                required property int index
                                readonly property var blockData: win.needsBlocks[index]
                                width: needsCol.width
                                height: item ? item.implicitHeight : 0
                                sourceComponent: blockData && blockData.kind === "decision"
                                    ? decisionBlockComp : null
                            }
                        }

                        // One decision as a draggable block. Its data comes from the
                        // Loader (`parent.blockData`); the grip's displacement goes to
                        // `reorderBlock`, which places it anywhere among the blocks and
                        // saves the display order to state.json (board.md left intact).
                        Component {
                            id: decisionBlockComp
                            Decision {
                                id: decCard
                                readonly property var blockData:
                                    parent ? parent.blockData : null
                                readonly property var modelData:
                                    blockData ? blockData.dec : null
                                readonly property string dkey:
                                    modelData ? String(modelData.key) : ""
                                width: needsCol.width
                                decision: decCard.modelData
                                cellW: win.cellW
                                fgAccent: win.fgAccent
                                fgText: win.fgText
                                fgDim: win.fgDim
                                draft: win.draftOf(decCard.dkey)
                                openCaret: win.caretOf(decCard.dkey)
                                onCaretHeld: (p) => win.caretHeld(decCard.dkey, p)
                                onCaretLeft: () => win.caretLeft(decCard.dkey)
                                onChoose: (i, on) => Board.choose(decCard.dkey, i, on)
                                onDraftEdited: (body) => win.setDraft(decCard.dkey, body)
                                onCommit: (body) => {
                                    if (Board.answer(decCard.dkey, body))
                                        win.setDraft(decCard.dkey, "");
                                }
                                onContextRequested: (mx, my) =>
                                    win.decisionMenu(decCard.modelData, mx, my)
                                onReorderRequested: (from, dy) =>
                                    needsSectionRoot.reorderBlock(
                                        decCard.blockData
                                        ? decCard.blockData.bkey : "", dy)
                            }
                        }

                }
                }

                Item { width: 1; height: 18 }
    }
}

Component {
                            id: todoSection
                            Column {
                                id: todoAreaRoot
                                width: page.width
                                // Set height explicitly (like `needsSectionRoot`),
                                // or the block Loader's `height: item.height` clamps
                                // this Column to its initial 0 and the to-do area
                                // renders with no height, overlapping the decisions.
                                height: implicitHeight

                        Item { width: 1; height: win.todo.length > 0 ? 10 : 0 }

                        // Actions rather than decisions — the file's own second
                        // list. They carry no checkbox in the store, so none is
                        // drawn: a box that cannot be written is exactly the
                        // control §10 says must not exist.
                        // ...under a band of their own, and a collapsible one:
                        // this line heads a sub-section (the second list in the
                        // section), so it wears what every other heading here
                        // wears rather than being the one dim label that could not
                        // be folded. Folding it takes every tag group with it.
                        SectionHead {
                            width: page.width
                            visible: win.todo.length > 0
                            height: visible ? implicitHeight : 0
                            label: "to do"
                            collapsed: win.isCollapsed("todo")
                            fgDim: win.fgDim
                            fgAccent2: win.fgAccent2
                            // [his re-ask, 2026-08-02] the `to do` band is a
                            // top-level section grip now: a vertical drag places
                            // it anywhere among the other sections, a tap folds.
                            reorderable: true
                            onToggled: win.toggleCollapsed("todo")
                            onReorderRequested: (dy) =>
                                win.reorderSection("todo", dy)
                        }
                        // ...and they are grouped by that first word — his:
                        // *"the information, completion, partial etc of a message
                        // should be used to organize them on the board. under the
                        // needs you section there should be sub sections for each
                        // of these headers"*.
                        //
                        // A sub-heading is the SAME band the sections use, one rung
                        // quieter: no accent. [his, 2026-07-30] *"all sections /
                        // subsections should be collapseable like the top
                        // decisions one"* — so it carries the band's own `[-]`,
                        // the same hit area, the same hover light and the same
                        // persisted state (§14), and it stopped being the
                        // `interactive: false` label it shipped as.
                        // It is a heading and NOT a count: no tally, no
                        // badge, no severity colour, exactly as the flat list had
                        // none (AGENTS.md, and §8.1's ramp means a machine fault).
                        // A tag with no bullets has no heading at all; the order and
                        // why it is that order live in `boardparse.TODO_ORDER`.
                        // Keyed twice over — the group by its tag, the bullets in it
                        // by their line — so a note arriving under one tag leaves
                        // every other bullet's reply box exactly as he left it.
                        Item {
                            width: page.width
                            visible: !win.isCollapsed("todo")
                            implicitHeight: visible ? todoCol.implicitHeight : 0
                            height: implicitHeight

                            Column {
                                id: todoCol
                                width: parent.width

                            Repeater {
                                model: win.keysOf(win.todoGroups, "tag")
                                delegate: Column {
                                    id: todoGroup
                                    required property int index
                                    readonly property var modelData:
                                        win.todoGroups[todoGroup.index]
                                        || ({ label: "", items: [] })
                                    width: page.width

                                    // Its own collapse key, so folding `information`
                                    // says nothing about `failed` — and namespaced by
                                    // the TAG rather than by position, because the
                                    // groups come and go with what is on the board and
                                    // an index would remember the wrong one. The
                                    // untagged group has no band, so it has no fold:
                                    // there would be no way back.
                                    readonly property string ckey:
                                        "todo:" + String(todoGroup.modelData.tag || "")
                                    readonly property bool folded:
                                        todoGroup.modelData.label !== ""
                                        && win.isCollapsed(todoGroup.ckey)

                                    Item {
                                        width: 1
                                        height: todoGroup.modelData.label !== "" ? 4 : 0
                                    }
                                    SectionHead {
                                        width: todoGroup.width
                                        visible: todoGroup.modelData.label !== ""
                                        label: todoGroup.modelData.label
                                        collapsed: todoGroup.folded
                                        fgDim: win.fgDim
                                        fgAccent2: win.fgAccent2
                                        onToggled: win.toggleCollapsed(todoGroup.ckey)
                                    }

                                    // ...and the bullets under it, which the band
                                    // hides and shows with the same `visible` +
                                    // `implicitHeight` pair every section on this
                                    // page collapses with — a sub-section folds
                                    // exactly the way the one above it does.
                                    Item {
                                        width: todoGroup.width
                                        visible: !todoGroup.folded
                                        implicitHeight: visible ? groupCol.implicitHeight : 0
                                        height: implicitHeight

                                        Column {
                                            id: groupCol
                                            width: parent.width

                                        Repeater {
                                            // Keyed by the bullet's TEXT, not its file
                                            // `line`: a new message posted anywhere above
                                            // shifts every later line index, and a
                                            // line-keyed row is then destroyed and rebuilt
                                            // under a new key — which closed his open reply
                                            // box and orphaned the draft stored under the
                                            // old line. Text is stable across inserts (the
                                            // same id folding already keys by), so an
                                            // unrelated message leaves his reply untouched.
                                            model: win.keysOf(todoGroup.modelData.items, "text")
                                            delegate: Item {
                                                id: todoRow
                                                required property int index
                                                readonly property var modelData:
                                                    todoGroup.modelData.items[todoRow.index] || ({})
                                                // The reply box is opened from the row's own menu
                                                // and stays open until he sends or clears it, like
                                                // every other editor here — a draft is never thrown
                                                // away by a click somewhere else.
                                                property bool replying: win.draftOf("todo:" + todoRow.modelData.text) !== ""
                                                // Folded to its one summary line, by his
                                                // click on the mark. `win.todoFolded` says
                                                // what the key is and why it is the text.
                                                readonly property bool folded:
                                                    win.isTodoFolded(todoRow.modelData.text)
                                                // The author and the when, joined for the
                                                // COLLAPSED one-line form: the message folded
                                                // to a single row puts them on one line
                                                // together, so that combined string and its
                                                // width are computed once here. Open, the
                                                // gutter draws them as its usual two rows;
                                                // folded, this is the one row that stays.
                                                readonly property string metaBy:
                                                    todoRow.modelData.by ? todoRow.modelData.by : ""
                                                readonly property string metaWhen:
                                                    todoRow.modelData.when ? todoRow.modelData.when : ""
                                                readonly property string metaCombined:
                                                    (metaBy ? metaBy + "  " : "") + metaWhen
                                                width: page.width
                                                implicitHeight: bar.implicitHeight
                                                                + (replying ? replyBox.height + 4 : 0)
                                                height: implicitHeight

                                                Item {
                                                    id: bar
                                                    width: parent.width
                                                    // ...and never shorter than the GUTTER
                                                    // beside it. A one-line bullet with a
                                                    // `by:` stamp has two lines of metadata
                                                    // against one line of text, and without
                                                    // this the name and the time spilled out
                                                    // of the row and drew over the bullet
                                                    // below — which is what a stack of
                                                    // one-line SUMMONED lines is made of.
                                                    implicitHeight: Math.max(
                                                        todoText.implicitHeight
                                                        + todoFor.height
                                                        + (todoMore.visible
                                                           ? todoMore.implicitHeight + 6 : 0),
                                                        todoRow.folded
                                                          ? todoMeta.implicitHeight
                                                          : gutter.implicitHeight)
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
                                                        width: parent.width - x - 8
                                                               - (todoRow.folded
                                                                  ? todoRow.metaCombined.length * win.cellW
                                                                  : 15 * win.cellW)
                                                        color: win.fgText
                                                        maximumLineCount: todoRow.folded ? 1 : 9999
                                                        text: todoRow.folded
                                                              ? win.clipTo(full,
                                                                    Math.floor(width / win.cellW))
                                                              : full
                                                    }
                                                    // WHICH OF HIS ASKS THIS CAME OUT OF —
                                                    // [his, 2026-07-30] *"information
                                                    // messages should display a truncated
                                                    // version of the original user prompt
                                                    // that spawned the message between the
                                                    // top line and the second verbose
                                                    // line"*. So it goes exactly there,
                                                    // between the summary and the
                                                    // elaboration, and it is HIS sentence:
                                                    // carried down from the box he typed it
                                                    // into (`boardparse.for_now`).
                                                    //
                                                    // ONE line, cut in CHARACTERS with an
                                                    // ASCII `...` — `win.clipTo`, never
                                                    // `Text.ElideRight`, whose U+2026 this
                                                    // font does not have (§2.3). It is
                                                    // reference and not the message, so it
                                                    // takes the `dim` rung the metadata
                                                    // does, a rung under the elaboration.
                                                    // ABSENT when nothing was recorded and
                                                    // when the row is folded: every bullet
                                                    // written before this existed has none,
                                                    // and so has one nobody dispatched.
                                                    PixelText {
                                                        id: todoFor
                                                        x: todoText.x
                                                        y: todoText.height + 2
                                                        width: todoText.width
                                                        visible: todoRow.modelData.order
                                                                 && !todoRow.folded
                                                        height: visible ? implicitHeight : 0
                                                        color: Theme.dim
                                                        text: visible
                                                              ? win.clipTo(
                                                                    "for: " + todoRow.modelData.order,
                                                                    Math.floor(width / win.cellW))
                                                              : ""
                                                    }
                                                    Para {
                                                        id: todoMore
                                                        x: todoText.x
                                                        y: todoText.height + todoFor.height + 6
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
                                                    // ...and WHO put it there, on the line
                                                    // ABOVE the time. One metadata cluster
                                                    // at the trailing edge (§9.1), so it
                                                    // takes the same `dim` rung and the
                                                    // same reserved character width — a
                                                    // name is not louder than a time.
                                                    //
                                                    // ABSENT, not blank, when nothing is
                                                    // recorded (§10): every bullet written
                                                    // before the stamp existed has none,
                                                    // and so does one no writer could name
                                                    // an author for. Its height
                                                    // collapses with it, so the time is
                                                    // back on the first line and those
                                                    // bullets draw exactly as they did.
                                                    // Folded, the message is ONE row — his
                                                    // *"collapse to a single line"* — so the
                                                    // author and the time share that row, on
                                                    // the same `dim` rung and the same
                                                    // trailing edge the two rows use open. Its
                                                    // width is the CHARACTER COUNT the summary
                                                    // just reserved for it, so the right edge
                                                    // never clips and folding reflows the
                                                    // summary by exactly that much (`metaBy  `
                                                    // + `metaWhen`, or just whichever exists).
                                                    PixelText {
                                                        id: todoMeta
                                                        visible: todoRow.folded && text !== ""
                                                        anchors.right: parent.right
                                                        anchors.top: parent.top
                                                        width: text.length * win.cellW
                                                        horizontalAlignment: Text.AlignRight
                                                        color: Theme.dim
                                                        // Populated only when folded: an open
                                                        // row does not carry a ghost copy of the
                                                        // combined line for anything to read.
                                                        text: todoRow.folded
                                                              ? todoRow.metaCombined : ""
                                                    }
                                                    Column {
                                                        id: gutter
                                                        visible: !todoRow.folded
                                                        anchors.right: parent.right
                                                        anchors.top: parent.top
                                                        width: 15 * win.cellW
                                                        PixelText {
                                                            id: todoBy
                                                            objectName: "gutterBy"
                                                            width: parent.width
                                                            horizontalAlignment: Text.AlignRight
                                                            color: Theme.dim
                                                            visible: text !== ""
                                                            height: visible ? implicitHeight : 0
                                                            text: todoRow.modelData.by
                                                                  ? todoRow.modelData.by : ""
                                                        }
                                                        PixelText {
                                                            id: todoWhen
                                                            width: parent.width
                                                            horizontalAlignment: Text.AlignRight
                                                            color: Theme.dim
                                                            text: todoRow.modelData.when
                                                                  ? todoRow.modelData.when : ""
                                                        }
                                                    }
                                                    MouseArea {
                                                        id: tma
                                                        anchors.fill: parent
                                                        hoverEnabled: true
                                                        // Left is here for the DOUBLE click only —
                                                        // *"i should be able to just double click
                                                        // on stuff in the to do
                                                        // section to remove them"*. A single
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
                                                    draft: win.draftOf("todo:" + todoRow.modelData.text)
                                                    openCaret: win.caretOf("todo:" + todoRow.modelData.text)
                                                    onCaretHeld: (p) => win.caretHeld(
                                                        "todo:" + todoRow.modelData.text, p)
                                                    onCaretLeft: () => win.caretLeft(
                                                        "todo:" + todoRow.modelData.text)
                                                    fgAccent: win.fgAccent
                                                    fgText: win.fgText
                                                    fgDim: win.fgDim
                                                    placeholder: "reply to this one - it goes to the inbox"
                                                    onDraftEdited: (b) => win.setDraft(
                                                        "todo:" + todoRow.modelData.text, b)
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
                            }
                        }
                    }
                }

Component {
    id: summonerSection
    //: the section as a delegate of the page's `sectionsCol` Repeater,
    //  so dragging its band reorders it ([his answer, 2026-08-01]: the
    //  four top-level sections move, persisted apart from board.md). The
    //  root is a Column so it sizes to its children exactly as the old
    //  page Column did — a section's collapse, growth or shrinkage re-flows
    //  the ones below it.
    Column {
        width: page.width
        // Prohibit the Loader from resizing this root to its own (initially 0)
        // size: an explicit `height` here is what lets the section keep its own
        // height and the Column below the Loader lay out by it (2026-08-01).
        height: implicitHeight

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
                // ---- SUMMONER: Solomon, and nothing else ----
                // [his, 2026-07-29, asked twice] *"solmon should be in his own
                // \"summoner\" section above the agents section"*. He was a row
                // pinned to the top of the agents list; the pin is still what orders
                // him first (`boardwork.cards()`), but he is drawn in a section of
                // his own above the workers.
                //
                // It is a TITLED section, the same `SectionHead` band every other
                // section on this page wears — not a bare card floated above the
                // list. He said "section" and he said it twice, and the band is what
                // makes a section one on this page: same casing, same rule, same
                // collapse control (docs/DESIGN.md §9.1, §5.1). A headerless card
                // would have been a fourth way of grouping things in one window.
                //
                // No framing sentence under it, unlike AGENTS: there is exactly one
                // card in here and its own detail line already says what he can do
                // with it, so a paragraph would be the dead space §5.2 calls a
                // defect.
                SectionHead {
                    id: summonerHead
                    width: page.width
                    label: "summoner"
                    collapsed: win.isCollapsed("summoner")
                    fgAccent: win.fgAccent
                    fgAccent2: win.fgAccent2
                    fgDim: win.fgDim
                    reorderable: true
                    onToggled: win.toggleCollapsed("summoner")
                    onReorderRequested: (dy) => win.reorderSection("summoner", dy)
                }

                Item {
                    id: secSummoner
                    width: page.width
                    visible: !win.isCollapsed("summoner")
                    implicitHeight: visible ? summonerCol.implicitHeight : 0
                    height: implicitHeight

                    Column {
                        id: summonerCol
                        width: parent.width

                        Repeater {
                            model: win.keysOf(win.summonerCards, "id")
                            delegate: AgentRow {
                                id: sumRow
                                required property int index
                                readonly property var modelData:
                                    win.summonerCards[sumRow.index] || ({})
                                width: summonerCol.width
                                agent: sumRow.modelData
                                cellW: win.cellW
                                // HIS TEXT NEVER FADES — [his, 2026-07-29] *"his
                                // text should never become the unfocused colors"*.
                                // The fade is handed down (docs/DESIGN.md §3.1.1),
                                // so the exemption is one place: the `Theme` tones
                                // instead of the window's `fgX` ternaries. That
                                // covers every label on the card, the inbox box
                                // included, without a leaf reading `Window.active`
                                // itself — which §3.1.1 forbids for its own reasons.
                                // A recorded exception to that section, not a drift
                                // from it (DESIGN.md §20).
                                fgAccent: Theme.accent
                                fgText: Theme.text
                                fgDim: Theme.textDim
                                outputOpen: win.isOutputOpen(sumRow.modelData.id)
                                onOutputToggled: () =>
                                    win.toggleOutputOpen(sumRow.modelData.id)
                                draft: win.draftOf("msg:" + sumRow.modelData.id)
                                openCaret: win.caretOf("msg:" + sumRow.modelData.id)
                                onCaretHeld: (p) => win.caretHeld("msg:" + sumRow.modelData.id, p)
                                onCaretLeft: () => win.caretLeft("msg:" + sumRow.modelData.id)
                                onDraftEdited: (b) =>
                                    win.setDraft("msg:" + sumRow.modelData.id, b)
                                onSend: (b) => win.sendTo(sumRow.modelData, b)
                                onContextRequested: (mx, my) =>
                                    win.agentRowMenu(sumRow,
                                        (sumRow.modelData.doingLine !== ""
                                         ? sumRow.modelData.doingLine
                                         : (sumRow.modelData.name
                                            ? sumRow.modelData.name + " - " : "")
                                           + sumRow.modelData.detail)
                                        + "  (" + sumRow.modelData.title + ")",
                                        mx, my)
                            }
                        }

                        // PENDING ORDERS — what he typed that is waiting for the
                        // next summoner, either because nothing was running when he
                        // sent it or because a minister went away without reading
                        // it. Drawn because an order he cannot see is one he has to
                        // assume was lost.
                        // ...and one he has changed his mind about can be rewritten,
                        // taken back from the menu, or undone with ctrl+z, up until
                        // the moment board-watch drains it (`QueuedNote.qml` carries
                        // what that race costs him).
                        //
                        // THE WORD IS ORDERS, not messages — [his, 2026-07-29]
                        // *"instead of messages it says orders"*, of this list. The
                        // group is labelled rather than left to speak for itself
                        // because that is the section he named; it appears with the
                        // first order and goes with the last.
                        //
                        // IT SITS AT THE FOOT OF THE SUMMONER SECTION, not of the
                        // triangle — [his, 2026-07-30] *"pending orders for solomon
                        // should be shown at the bottom of the summoner section NOT
                        // at the bottom of the triangle"*. An order is addressed to
                        // the summoner and is waiting on HIM to pick it up; the
                        // triangle is the ministers already bound, which is a
                        // different question.
                        PixelText {
                            width: summonerCol.width
                            visible: win.queuedNotes.length > 0
                            height: visible ? implicitHeight : 0
                            topPadding: visible ? 6 : 0
                            color: Theme.dim
                            text: "pending orders"
                        }

                        Repeater {
                            model: win.keysOf(win.queuedNotes, "id")
                            delegate: QueuedNote {
                                id: qNote
                                required property int index
                                readonly property var modelData:
                                    win.queuedNotes[qNote.index] || ({})
                                width: summonerCol.width
                                note: qNote.modelData
                                cellW: win.cellW
                                fgDim: win.fgDim
                                fgText: win.fgText
                                fgAccent: win.fgAccent
                                expanded: win.isQueuedExpanded(qNote.modelData.id)
                                onExpandToggled: win.toggleQueuedExpanded(qNote.modelData.id)
                                draft: win.draftOf("queued:" + qNote.modelData.id)
                                openCaret: win.caretOf("queued:" + qNote.modelData.id)
                                onCaretHeld: (p) => win.caretHeld("queued:" + qNote.modelData.id, p)
                                onCaretLeft: () => win.caretLeft("queued:" + qNote.modelData.id)
                                onDraftEdited: (b) => win.setDraft("queued:" + qNote.modelData.id, b)
                                onStatusMessage: (t) => { if (t !== "") win.status = t; }
                                onMenuRequested: (mx, my, head, tail) =>
                                    menu.open(mx, my, head.concat(win.fileItems())
                                                          .concat(win.undoItems())
                                                          .concat(tail))
                            }
                        }
                    }
                }

                Item { width: 1; height: 12 }
    }
}

Component {
    id: agentsSection
    //: the section as a delegate of the page's `sectionsCol` Repeater,
    //  so dragging its band reorders it ([his answer, 2026-08-01]: the
    //  four top-level sections move, persisted apart from board.md). The
    //  root is a Column so it sizes to its children exactly as the old
    //  page Column did — a section's collapse, growth or shrinkage re-flows
    //  the ones below it.
    Column {
        width: page.width
        // Prohibit the Loader from resizing this root to its own (initially 0)
        // size: an explicit `height` here is what lets the section keep its own
        // height and the Column below the Loader lay out by it (2026-08-01).
        height: implicitHeight

                // ---- THE TRIANGLE: where the ministers reside ----
                // [his, 2026-07-29] *"what triangle should refer to is the area the
                // ministers reside"*. Solomon etches the CIRCLE on his own card in
                // the summoner section above; the spirits are bound in the triangle,
                // which is this list. The section `id` stays `agents` — it keys the
                // collapse state, `jump()` and the `ag` titlebar cell — so this is
                // the drawn word only.
                SectionHead {
                    width: page.width
                    // "the triangle", with the article, matching "the circle" on
                    // Solomon's own card - [his, 2026-07-29]. Since 2026-07-31 the
                    // band also says how many ministers the triangle is BINDING
                    // right now, in the same voice as the rest of the card — his
                    // call, *"the triangle binds three ministers"*. The count is
                    // `Agents.boundMinisters`, which counts the running minister
                    // cards drawn HERE — sessions he started are already filtered
                    // out of the drawn set, so an anonymous terminal of his is
                    // never counted. With none bound the band keeps the plain name
                    // and lets the dim `binds ministers.` line below say the empty
                    // state, so the two never contradict.
                    label: Agents.boundMinisters === 0 ? "the triangle"
                         : "the triangle binds " + ({
                                1: "one", 2: "two", 3: "three", 4: "four",
                                5: "five", 6: "six"
                            }[Agents.boundMinisters] || Agents.boundMinisters)
                           + " minister" + (Agents.boundMinisters === 1 ? "" : "s")
                    collapsed: win.isCollapsed("agents")
                    fgAccent: win.fgAccent
                    fgAccent2: win.fgAccent2
                    fgDim: win.fgDim
                    reorderable: true
                    onToggled: win.toggleCollapsed("agents")
                    onReorderRequested: (dy) => win.reorderSection("agents", dy)
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
                        // empty frame, no "0 agents". [his, 2026-07-29] that
                        // sentence is now *"binds ministers."*: what the triangle
                        // IS, rather than a report that it is currently holding
                        // none. Gated on the WORKERS and not on the list's length,
                        // as before.
                        PixelText {
                            width: agentsCol.width
                            visible: win.nothingRunning
                            height: visible ? implicitHeight : 0
                            color: Theme.dim
                            text: "binds ministers."
                        }

                        // ...and the ONE thing that can make that sentence a lie:
                        // nothing is running and nothing is going to start. [his,
                        // 2026-07-29] armed, the line above is the only text here;
                        // not armed, this follows it. `Agents.armed` is polled with
                        // the units every ten seconds, never per repaint, and it is
                        // three-valued — `undefined` is "systemctl could not be
                        // asked", which §10 does not let us report as either answer,
                        // so that case says what it actually knows.
                        PixelText {
                            width: agentsCol.width
                            visible: win.nothingRunning && Agents.armed !== true
                            height: visible ? implicitHeight : 0
                            elide: Text.ElideRight
                            color: Theme.dim
                            text: Agents.armed === false ? "board-watch is not armed"
                                                         : Agents.watcher
                        }

                        // NO description of this section. [his, 2026-07-30] the
                        // triangle explains itself with cards: bound ministers ->
                        // the cards and nothing else, none bound -> the one line
                        // above. The paragraph that used to stand here ("each
                        // minister says what it is doing...") is gone; the two
                        // sentences on a card are legible without a preface, and
                        // §5.2 already refuses a disclaimer where a sentence
                        // belongs.

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
                        // Keyed on the agent's id: a card's two sentences change
                        // every time its agent picks up a different tool, and that
                        // must not close the inbox box on the card beside it.
                        Repeater {
                            model: win.keysOf(win.agentCards, "id")
                            delegate: AgentRow {
                                id: agRow
                                required property int index
                                readonly property var modelData:
                                    win.agentCards[agRow.index] || ({})
                                width: agentsCol.width
                                agent: agRow.modelData
                                cellW: win.cellW
                                fgAccent: win.fgAccent
                                fgText: win.fgText
                                fgDim: win.fgDim
                                outputOpen: win.isOutputOpen(agRow.modelData.id)
                                onOutputToggled: () =>
                                    win.toggleOutputOpen(agRow.modelData.id)
                                draft: win.draftOf("msg:" + agRow.modelData.id)
                                openCaret: win.caretOf("msg:" + agRow.modelData.id)
                                onCaretHeld: (p) => win.caretHeld("msg:" + agRow.modelData.id, p)
                                onCaretLeft: () => win.caretLeft("msg:" + agRow.modelData.id)
                                onDraftEdited: (b) =>
                                    win.setDraft("msg:" + agRow.modelData.id, b)
                                onSend: (b) => win.sendTo(agRow.modelData, b)
                                // `copy line` gives him the whole row as a
                                // sentence, and the observed one already leads with
                                // WHO — that is the half he would otherwise have to
                                // go back to the screen for. A card with no
                                // sentence (a queued task, an agent that stopped
                                // unseen) falls back to the line that says what it
                                // is instead.
                                onContextRequested: (mx, my) =>
                                    win.agentRowMenu(agRow,
                                        (agRow.modelData.doingLine !== ""
                                         ? agRow.modelData.doingLine
                                         : (agRow.modelData.name
                                            ? agRow.modelData.name + " - " : "")
                                           + agRow.modelData.detail)
                                        + "  (" + agRow.modelData.title + ")",
                                        mx, my)
                            }
                        }


                        // The watcher's own systemd sentence used to sit here, under
                        // the cards. It does not any more: [his, 2026-07-30] with
                        // ministers bound the section draws the cards and the shells
                        // and NOTHING else. It is still read (`Agents.watcher`/
                        // `armed`) and it is still SAID in the one case where
                        // silence would make the empty line a lie — a watcher that
                        // will never fire, up beside "binds ministers." (§10).
                    }
                }

                Item { width: 1; height: 18 }
    }
}

Component {
    id: shellsSection
    //: a top-level section [his re-ask, 2026-08-02]: the live workings
    //  of the bound ministers, placeable anywhere among the other bands.
    Column {
        width: page.width
        height: implicitHeight

                        // ---- their LIVE SHELLS ----
                        // [his ask, 2026-08-01] a small live tail per bound minister,
                        // under the cards: the last couple of lines each one is
                        // actually producing, so a running spirit reads as a live
                        // process rather than two sentences and a name. It is the
                        // SAME source the card drawer tails (the transcript — a
                        // running worker's `.log` is buffered till exit), built in
                        // `main.py` off the same `workers` list, so the section can
                        // never disagree with the cards about who is bound.
                        //
                        // It shows only when there is something to show (§5.2 — an
                        // empty shell slot is a hole he has to fill): no bound
                        // ministers, or none with anything to say, draws no
                        // band and no rows. Each row's foreGROUND tail is the
                        // transcript; [his, 2026-08-01] the backgrounded
                        // long-runners it left running ride under it, read from
                        // the worker's own unit cgroup. It collapses like every
                        // heading here.

                SectionHead {
                    id: shellsHead
                    width: page.width
                    visible: win.agentShells.length > 0
                    height: visible ? implicitHeight : 0
                    // [ask 1, 2026-08-02] renamed from "shells": the band is the
                    // live tail of each bound minister's tool calls, not a
                    // terminal — *"the other section labeled 'shells'"* read as
                    // the shell it runs in. `workings` names what it shows in the
                    // summoning register: what each spirit is actively doing. The
                    // collapse key stays "shells" (internal, one fold state).
                    label: "workings"
                    collapsed: win.isCollapsed("shells")
                    fgAccent: win.fgAccent
                    fgAccent2: win.fgAccent2
                    fgDim: win.fgDim
                    reorderable: true
                    onToggled: win.toggleCollapsed("shells")
                    onReorderRequested: (dy) => win.reorderSection("shells", dy)
                }

                        Item {
                            width: page.width
                            visible: win.agentShells.length > 0
                                     && !win.isCollapsed("shells")
                            implicitHeight: visible ? shellsCol.implicitHeight : 0
                            height: implicitHeight

                            Column {
                                id: shellsCol
                                width: parent.width
                                spacing: 2

                                Repeater {
                                    model: win.keysOf(win.agentShells, "id")
                                    delegate: Shell {
                                        id: shellRow
                                        required property int index
                                        readonly property var modelData:
                                            win.agentShells[shellRow.index] || ({})
                                        width: shellsCol.width
                                        name: shellRow.modelData.name
                                        lines: shellRow.modelData.lines
                                        bg: shellRow.modelData.bg
                                        cellW: win.cellW
                                        fgDim: win.fgDim
                                    }
                                }
                            }
                        }
    }
}

Component {
    id: spendSection
    //: the spend section — what the board's automation costs across every
    //  provider. Its own file (SpendSection.qml), a Column so it sizes to its
    //  children and drags as one band like every other section.
    SpendSection {}
}

Component {
    id: landedSection
    //: the section as a delegate of the page's `sectionsCol` Repeater,
    //  so dragging its band reorders it ([his answer, 2026-08-01]: the
    //  four top-level sections move, persisted apart from board.md). The
    //  root is a Column so it sizes to its children exactly as the old
    //  page Column did — a section's collapse, growth or shrinkage re-flows
    //  the ones below it.
    Column {
        width: page.width
        // Prohibit the Loader from resizing this root to its own (initially 0)
        // size: an explicit `height` here is what lets the section keep its own
        // height and the Column below the Loader lay out by it (2026-08-01).
        height: implicitHeight

                // ================================================ what happened
                SectionHead {
                    width: page.width
                    label: "landed"
                    collapsed: win.isCollapsed("landed")
                    fgAccent: win.fgAccent
                    fgAccent2: win.fgAccent2
                    fgDim: win.fgDim
                    reorderable: true
                    onToggled: win.toggleCollapsed("landed")
                    onReorderRequested: (dy) => win.reorderSection("landed", dy)
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

                                // A DAY is a sub-section of `landed`, so it wears
                                // the same band as everything else here rather
                                // than the bare dim line it shipped as — [his,
                                // 2026-07-30] *"all sections / subsections should
                                // be collapseable like the top decisions one"*.
                                // Keyed by the DATE and not by position: the list
                                // grows a new day at the top, and an index would
                                // hand yesterday's fold to today.
                                readonly property string ckey:
                                    "landed:" + String(group.modelData.date)

                                SectionHead {
                                    width: group.width
                                    label: String(group.modelData.date)
                                    collapsed: win.isCollapsed(group.ckey)
                                    fgDim: win.fgDim
                                    fgAccent2: win.fgAccent2
                                    onToggled: win.toggleCollapsed(group.ckey)
                                }

                                Item {
                                    width: group.width
                                    visible: !win.isCollapsed(group.ckey)
                                    implicitHeight: visible ? dayCol.implicitHeight : 0
                                    height: implicitHeight

                                    Column {
                                        id: dayCol
                                        width: parent.width

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
                    }
                }

                Item { width: 1; height: 20 }
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
    // The cap dropdown's entries. Same shape as `modelItems`.
    //
    // A SUCCESSFUL PICK SAYS NOTHING. [his, 2026-07-30] *"when i change the
    // number of ministers in goetia itll flash text indicating that on the
    // inner bar"* — reported as the inner titlebar flashing text, and it is
    // this: `footerStr` IS `status`, so a four-second confirmation is the only
    // thing that slot ever holds, appearing and going again with nothing on
    // either side of it. Nothing was clobbered and nothing was drawn wrong; the
    // announcement should not have been there.
    //
    // It costs no honesty, which is why it can go. The closed box relabels
    // itself from the store (`Agents.capLabel`) and the tick moves, so the
    // CHANGE is on screen; and the WHEN — the half that is not — is the
    // `PickBox`'s own `hint`, permanently, before he picks rather than for four
    // seconds after. A FAILURE still reports: that is the one outcome nothing
    // else on screen can show, and §10's rule is about those.
    function modelItems() {
        return Agents.models.map((m) => ({
            label: (m.current ? "* " : "  ") + m.label,
            trigger: () => {
                if (!Agents.chooseModel(m.name))
                    win.status = "could not save that choice";
            }
        }));
    }

    function capItems() {
        return Agents.caps.map((c) => ({
            label: (c.current ? "* " : "  ") + c.label,
            trigger: () => {
                if (!Agents.chooseCap(c.n))
                    win.status = "could not save that choice";
            }
        }));
    }

    // How many summoners may plan at once. Same shape and the same silence on
    // success as the two above.
    function summonerItems() {
        return Agents.summonerCounts.map((s) => ({
            label: (s.current ? "* " : "  ") + s.label,
            trigger: () => {
                if (!Agents.chooseSummoners(s.n))
                    win.status = "could not save that choice";
            }
        }));
    }

    // What the ministers run on. The list is `boardwork.MINISTER_MODELS`, which
    // stops at opus 5 medium by his rule, so there is nothing here to disable
    // and nothing greyed out: a chooser that draws what it will not do is the
    // §10 failure (see `boardwork.role_flags`, which enforces the same ceiling
    // where a minister is actually spawned).
    function ministerItems() {
        return Agents.ministers.map((m) => ({
            label: (m.current ? "* " : "  ") + m.label,
            trigger: () => {
                if (!Agents.chooseMinister(m.name))
                    win.status = "could not save that choice";
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
        items = items.concat(fileItems()).concat(undoItems());
        // §7.2: the destructive entry LAST, behind a separator of its own, so
        // the pointer never lands on it over a list that re-numbers itself when
        // the question goes. No confirm -- the right-click is act one, this
        // entry is act two (§10.3), and `put it back` above is what covers the
        // misclick, exactly as it does a removed chore.
        items.push({ separator: true });
        items.push({ label: "remove this question",
                     trigger: () => Board.removeDecision(d.key) });
        menu.open(x, y, items);
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

    // Right-click on an AGENT card. The top entry is the send — the inline
    // "send a command..." box no longer rests on the card, so this menu entry
    // is how he reaches it: it opens the card's own box (and its caret/draft,
    // both still keyed by the agent's id) and he types and submits from there.
    // Below that come the same staples every other row's menu carries.
    function agentRowMenu(ar, text, x, y) {
        var items = [];
        if (ar.addressable)
            items.push({ label: "send " + (ar.name !== "" ? ar.name : "it")
                                + " a command, an idea or a fix",
                         trigger: () => ar.beginSend() });
        if (text !== "")
            items.push({ label: "copy line", trigger: () => Board.copy(text) });
        items = items.concat(fileItems()).concat(undoItems());
        // Force-stopping a bound minister — §10.3's destructive act, so it is a
        // menu entry (never a click on a list that re-sorts under the cursor)
        // at the FOOT of the menu behind its own separator, where the pointer
        // does not land by accident. Offered ONLY for a RUNNING worker or
        // decision minister: Solomon is not force-stopped from here and a
        // subminister has no unit of its own (`boardwork.force_stop` refuses
        // both, so nothing here can silently no-op). `forceStop` SIGKILLs the
        // unit and re-reads liveness before the footer speaks, so this is never
        // the inert control §10 rules out.
        var k = ar.agent ? ar.agent.kind : "";
        if (ar.running && ar.addressable && !ar.summoner
                && (k === "worker" || k === "decision")) {
            items.push({ separator: true });
            items.push({ label: "force-stop "
                                + (ar.name !== "" ? ar.name : "this minister"),
                         trigger: () =>
                             { win.status = Agents.forceStop(String(ar.agent.id)); } });
        }
        menu.open(x, y, items);
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
        // ...but it is not an ORDER from the box, so ctrl+z does not claim it —
        // see `Agents.notAnOrder`. This reply also cleared a bullet, and `put it
        // back` in the row menu is what undoes that pair.
        Agents.notAnOrder();
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
