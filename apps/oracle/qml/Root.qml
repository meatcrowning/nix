import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import "../../qmlcommon"

// chatter's CONTENT: a model selector across the top, a reply area that fills
// the middle, and a prompt box along the bottom. Every control is drawn here in
// the desktop's pixel idiom (docs/DESIGN.md).
//
// AN ITEM, NOT A WINDOW, because it has two roofs (apps/AGENTS.md → kdeshell):
// under Hyprland `Main.qml` is a plain `Window` around this and the compositor
// draws the titlebar (§12), so there is no chrome strip; in a Plasma session
// main.py puts this same item inside a real QMainWindow's QQuickWidget, so the
// window, its menubar, its toolbar, its status bar and its background come from
// the KDE style. Nothing Window-only lives here.
//
// Under Plasma the four header rows below (model, session, base prompt, server)
// COLLAPSE: their verbs are the menubar's and the toolbar's, and their readouts
// the status bar's. They stay in the tree at zero height so every id they carry
// — the three dropdowns, the prompt editor — still resolves, and so one file
// still serves both faces.
Item {
    id: win

    // Which roof this tree is under. Everything gated on it is chrome the
    // Plasma session owns as real widgets (kdeshell) and this QML must not draw
    // a second time; `DESK_SESSION=plasma|hypr` moves it for a harness.
    readonly property bool plasma: (typeof DeskStyle !== "undefined" && DeskStyle)
                                   ? DeskStyle.plasma === true : false

    // The window's own surface: `Theme.bg` under Hyprland, and under Plasma the
    // system style's gradient (StyledBackground below) showing through.
    Rectangle {
        anchors.fill: parent
        color: Theme.windowFill
        z: -2
    }
    StyledBackground { anchors.fill: parent; z: -1 }

    property string model: ""
    // Read the newly-selected model's context ceiling as soon as it changes, so
    // the stat is right before the first send (send() refreshes it again).
    onModelChanged: if (model !== "") Ollama.refreshModelInfo(model)
    property string status: ""
    // The current conversation SESSION: its store id (empty until the first
    // turn is saved — oracle mints a stable one client-side then) and its title
    // (empty until named, which happens automatically from the first prompt).
    // The whole conversation is always a session and is persisted to the shared
    // store; "+ new session" starts a fresh one, the picker switches between them.
    property string sessionId: ""
    property string sessionTitle: ""
    // The conversation is a persistent LOG, not one turn swapped out under the
    // last: every send appends a `you` row and an assistant row to `chatLog`,
    // prior turns stay in place and scrolled back, readable (docs/DESIGN.md §14 —
    // nothing scrubs history from view). `activeIndex` is the assistant row the
    // in-flight stream is writing into.
    property int activeIndex: -1
    // The result of the last start/stop/unload — its OWN readout (docs/DESIGN.md
    // §10.6), never folded into the observed up/down above and never routed to
    // the reply area, where a finished answer would hide whether the stop worked.
    property string serverNote: ""

    // The pixel font is monospace; one measurement gives the column advance.
    TextMetrics {
        id: metrics
        font.family: Theme.font
        font.pixelSize: Theme.fontSize
        text: "MMMMMMMMMM"
    }
    readonly property real cellW: metrics.width > 0 ? metrics.width / 10
                                                    : Math.round(0.533 * Theme.fontSize)

    Motion { id: motion }

    // The whole conversation, one row per turn. Roles: `isUser` (bool), `who`
    // (the caption — "you" or the answering model), `body`, `thinking`,
    // `thinkingActive` (the reasoning is streaming right now), `streaming` (the
    // answer is), `isError`, `ts` (unix seconds, when the row was appended).
    ListModel { id: chatLog }

    // WHEN a turn happened, which the model could not see at all until now. The
    // system prompt carries "the current time right now" built at send time, so
    // a session reopened three days later read as if all of it had just been
    // said — "earlier", "yesterday" and every relative reference were
    // unanswerable, and stale context passed for present. So a user turn older
    // than an hour goes into the history with its own time on it. Only HIS
    // turns: the model never sees its own output stamped, so it has no format
    // to imitate, and the pair (his last stamp, the system prompt's now) is
    // enough to place the whole gap.
    readonly property int stampAfter: 3600
    function stampedBody(h) {
        var now = Math.floor(Date.now() / 1000);
        if (!h.isUser || !h.ts || now - h.ts < win.stampAfter)
            return h.body;
        return "[sent " + Qt.formatDateTime(new Date(h.ts * 1000),
                                            "yyyy-MM-dd HH:mm") + " local] "
               + h.body;
    }

    // A row that opens a new calendar day gets a date above it; rows on the
    // same day get nothing, so a conversation held in one sitting is unchanged
    // (docs/DESIGN.md §9.1 — subordinated, and never noise for its own sake).
    function opensNewDay(i) {
        win.chatRev;                       // rows settle without notifying
        if (i <= 0 || i >= chatLog.count) return false;
        var a = chatLog.get(i - 1).ts, b = chatLog.get(i).ts;
        if (!a || !b) return false;
        return Qt.formatDate(new Date(a * 1000), "yyyy-MM-dd")
            !== Qt.formatDate(new Date(b * 1000), "yyyy-MM-dd");
    }
    function dayLabel(ts) {
        return Qt.formatDate(new Date(ts * 1000), "dddd d MMMM").toLowerCase();
    }
    // "2:07 pm" — when a message landed, under its bubble. 12h [his,
    // 2026-08-23], lowercase like every other string here (§7.2).
    function timeLabel(ts) {
        return Qt.formatTime(new Date(ts * 1000), "h:mm ap").toLowerCase();
    }

    // A line the model ended with a single newline is a line he SEES ended
    // [his, 2026-08-23]. CommonMark JOINS it into the paragraph above, so a
    // reply written as short lines came back as one run-on block; Qt's reader
    // has no "soft breaks are hard breaks" switch, and markdown's own hard
    // break (two trailing spaces) opens a whole new BLOCK, which would give a
    // soft break the same standoff as a real paragraph and make the two
    // indistinguishable.
    //
    // So a soft break becomes U+2028, the line separator Qt's layout breaks on
    // INSIDE a block: the line ends where he wrote it, and only a blank line
    // still opens a paragraph (`MdFormat.PARA_TOP` is the gap that says so).
    // Render only — the `source` beside it stays the model's text verbatim, so
    // copying still hands over exactly what it wrote.
    function hardBreaks(md) {
        if (md.indexOf("\n") < 0) return md;
        // A line that starts a block of its own: joining the line above onto it
        // would eat the list marker, the heading, the quote or the fence.
        var opensBlock = /^\s{0,3}([-*+>#]|\d+[.)]|```|~~~|\||={2,}$|-{3,}$)/;
        var lines = md.split("\n");
        var out = "";
        var fence = false;
        for (var i = 0; i < lines.length; i++) {
            var l = lines[i];
            if (i > 0) {
                var prev = lines[i - 1];
                var soft = !fence && l.trim() !== "" && prev.trim() !== ""
                           && !opensBlock.test(l) && !opensBlock.test(prev)
                           && !/\s\s$/.test(prev) && !/\\$/.test(prev);
                out += soft ? "\u2028" : "\n";
            }
            if (/^\s{0,3}(```|~~~)/.test(l)) fence = !fence;
            out += l;
        }
        return out;
    }

    // ---- one meta block per TURN, at the top of it -------------------------
    // A turn is one row PER TOOL ROUND (AGENTS.md "One bubble PER ROUND"), and
    // each of those rows used to carry its own reasoning, tool, web and file
    // headings — so between two things the model SAID there sat three or four
    // lines of bookkeeping [his, 2026-08-23]. Now the bubbles of a turn run one
    // after another with nothing between them but their timestamps, and every
    // disclosure of the turn is AGGREGATED into one block at the top of it,
    // where the counts, the clock and the live state already were.
    //
    // The head of a turn is the first model row of the run following one of his
    // prompts; it draws the block for every row under it. A round that said
    // NOTHING is drawn nowhere at all now — its bookkeeping is in the block, so
    // the row has nothing left of its own to show. That replaces the old
    // per-run fold, which existed to get exactly those rows out of the way.
    function turnHead(i) {
        win.chatRev;                       // rows settle without notifying
        if (i < 0 || i >= chatLog.count || chatLog.get(i).isUser) return -1;
        var h = i;
        while (h > 0 && !chatLog.get(h - 1).isUser) h--;
        return h;
    }
    // Did this round leave anything on screen? Media is read off the ROW's own
    // roles, never a child item's `visible` — the latch that hid a picture for
    // good (see the bubble's `visible`).
    function roundIsSilent(r) {
        return !r.isError && (r.body || "") === ""
               && (r.images || "[]") === "[]" && !r.imagesActive
               && (r.videos || "[]") === "[]" && !r.videosActive;
    }

    // `metaRev` is what re-evaluates the block. A ListModel notifies no binding
    // when setProperty writes a role, and rebuilding the aggregate per token
    // would redo it for every visible row on every delta — so the block's own
    // timer ticks this while a reply is in flight, and `chatRev` (bumped
    // wherever a row settles) carries the final state.
    property int metaRev: 0

    // Everything the rows of one turn spent, as ONE object: the block reads
    // this instead of five sets of per-row roles.
    function turnAgg(head) {
        win.chatRev; win.metaRev;
        var a = { rounds: 0, thinking: "", thinkTokens: 0, thinkMs: 0,
                  thinkStart: 0, thinkingActive: false, awaiting: false,
                  tools: "", toolCount: 0, toolsActive: false,
                  agents: "", agentCount: 0, agentsActive: false,
                  agentHead: "", agentsBad: false,
                  sources: "", searchCount: 0, searching: false,
                  files: "", fileCount: 0, filesActive: false,
                  execTail: "", execRunning: false, loading: false,
                  genLabel: "", genFrac: 0, genRunning: false };
        if (head < 0 || head >= chatLog.count) return a;
        for (var i = head; i < chatLog.count && !chatLog.get(i).isUser; i++) {
            var r = chatLog.get(i);
            a.rounds++;
            if ((r.thinking || "") !== "")
                a.thinking += (a.thinking !== "" ? "\n\n" : "") + r.thinking;
            a.thinkTokens += r.thinkTokens || 0;
            a.thinkMs += r.thinkMs || 0;
            if (r.thinkStart > 0) a.thinkStart = r.thinkStart;
            if (r.thinkingActive) a.thinkingActive = true;
            if (r.awaiting) a.awaiting = true;
            if ((r.tools || "") !== "")
                a.tools += (a.tools !== "" ? "\n" : "") + r.tools;
            a.toolCount += r.toolCount || 0;
            if (r.toolsActive) a.toolsActive = true;
            if ((r.agents || "") !== "")
                a.agents += (a.agents !== "" ? "\n\n" : "") + r.agents;
            a.agentCount += r.agentCount || 0;
            if (r.agentsActive) { a.agentsActive = true; a.agentHead = r.agentHead || ""; }
            if (r.agentsBad) a.agentsBad = true;
            if ((r.sources || "") !== "")
                a.sources += (a.sources !== "" ? "\n\n" : "") + r.sources;
            a.searchCount += r.searchCount || 0;
            if (r.searching) a.searching = true;
            if ((r.files || "") !== "")
                a.files += (a.files !== "" ? "\n" : "") + r.files;
            a.fileCount += r.fileCount || 0;
            if (r.filesActive) a.filesActive = true;
            // The tail belongs to whichever row is running a program now, or
            // to the last one that did.
            if ((r.execTail || "") !== "") {
                a.execTail = r.execTail;
                a.execRunning = !!r.execRunning;
            }
            // A render's bar belongs to whichever row is generating now.
            if (r.genRunning) {
                a.genRunning = true;
                a.genLabel = r.genLabel || "";
                a.genFrac = r.genFrac || 0;
            }
            // Nothing said and nothing thought while a row still streams: the
            // turn is waiting on its first anything, and that is a line of its
            // own — never at the same time as the clock (`waiting…`), which is
            // why the reasoning heading below stands down for it.
            if (r.streaming && (r.body || "") === "" && (r.thinking || "") === "")
                a.loading = true;
        }
        return a;
    }

    // Files he dragged onto the window, attached to the NEXT message and cleared
    // once it is sent (docs/DESIGN.md §13 — dropping into a window works like a
    // file manager). Each row is {name, path}; the paths are read locally and
    // inlined as context by Ollama.send.
    ListModel { id: attachments }
    function addAttachmentUrl(u) {
        var info = Ollama.localFileInfo("" + u);   // QUrl decode in Python (§13)
        if (!info || !info.path)
            return;
        for (var i = 0; i < attachments.count; i++)
            if (attachments.get(i).path === info.path)
                return;                            // already attached
        attachments.append({ name: info.name, path: info.path });
    }
    function removeAttachment(i) {
        if (i >= 0 && i < attachments.count) attachments.remove(i);
    }
    function clearAttachments() { attachments.clear(); }

    Component.onCompleted: Titlebar.setFooter(ollamaHost.replace(/^https?:\/\//, ""))

    // Keep a model selected, and never point at a model that has gone away.
    // On a fresh launch (or when the current pick vanishes) default to the model
    // he last used if the daemon still has it, else the first it reports.
    Connections {
        target: Ollama
        function onModelsChanged() {
            if (win.model !== "" && Ollama.models.indexOf(win.model) >= 0)
                return;                       // a still-valid selection stands
            if (Ollama.lastModel !== "" && Ollama.models.indexOf(Ollama.lastModel) >= 0)
                win.model = Ollama.lastModel;
            else
                win.model = Ollama.models.length > 0 ? Ollama.models[0] : "";
        }
        // The turns are appended by send() before the stream opens; these deltas
        // only ever write into the active assistant row. The first content delta
        // is also what SETTLES the thinking heading from "thinking…" to "thinking".
        // Any delta — reasoning or content — means the model is talking again,
        // so it is no longer waiting on a tool.
        function onReplyChunk(piece) {
            if (win.activeIndex < 0) return;
            var cur = chatLog.get(win.activeIndex);
            chatLog.setProperty(win.activeIndex, "body", cur.body + piece);
            chatLog.setProperty(win.activeIndex, "thinkingActive", false);
            chatLog.setProperty(win.activeIndex, "awaiting", false);
            win.accrueThink(win.activeIndex);
        }
        function onReplyThinking(piece) {
            if (win.activeIndex < 0) return;
            var cur = chatLog.get(win.activeIndex);
            chatLog.setProperty(win.activeIndex, "thinking", cur.thinking + piece);
            chatLog.setProperty(win.activeIndex, "thinkingActive", true);
            chatLog.setProperty(win.activeIndex, "awaiting", false);
            win.accrueThink(win.activeIndex);
        }
        // The live reasoning-token count, written into the active row so the
        // collapsed heading shows it climbing while the model thinks.
        // The reply hit the model's length ceiling mid-sentence. Mark the row
        // so it offers `continue` (§10 — a dead end is never left silent).
        // The finished reply, rewritten: a `{{show_video|…}}` the model TYPED
        // instead of calling becomes the bare URL, now that the card carries the
        // video (main.py `_attach_typed_videos`).
        function onReplyBodyFixed(text) {
            if (win.activeIndex < 0) return;
            chatLog.setProperty(win.activeIndex, "body", text);
            win.chatRev++;
        }
        function onReplyTruncated(reason) {
            if (win.activeIndex < 0) return;
            chatLog.setProperty(win.activeIndex, "cutOff", true);
            // Say WHICH wall it hit — "context" means the turn spent its window
            // on tool rounds, which is the one he can do something about (a
            // fresh conversation), so it is not left as a bare `continue`.
            win.status = reason === "context"
                       ? "it ran out of context mid-answer — press continue"
                       : "it hit the length limit — press continue";
        }
        function onReplyThinkTokens(n) {
            if (win.activeIndex < 0) return;
            chatLog.setProperty(win.activeIndex, "thinkTokens", n);
        }
        // The web_search tool loop, drawn as a subordinated per-turn disclosure
        // (docs/DESIGN.md §9.1): the model asked to search, sources came back,
        // or the search failed. Several searches in one turn accumulate.
        function onWebSearchStarted(query) {
            if (win.activeIndex < 0) return;
            chatLog.setProperty(win.activeIndex, "searching", true);
        }
        function onWebSearchDone(query, md, count) {
            if (win.activeIndex < 0) return;
            var cur = chatLog.get(win.activeIndex);
            var prefix = cur.sources !== "" ? cur.sources + "\n\n" : "";
            chatLog.setProperty(win.activeIndex, "sources", prefix + md);
            chatLog.setProperty(win.activeIndex, "searchCount", cur.searchCount + count);
            chatLog.setProperty(win.activeIndex, "searching", false);
        }
        function onWebSearchError(query, reason) {
            if (win.activeIndex < 0) return;
            var cur = chatLog.get(win.activeIndex);
            var prefix = cur.sources !== "" ? cur.sources + "\n\n" : "";
            chatLog.setProperty(win.activeIndex, "sources",
                                prefix + "search failed: " + reason);
            chatLog.setProperty(win.activeIndex, "searching", false);
        }
        // The file-tool loop, drawn as its own subordinated per-turn disclosure
        // (docs/DESIGN.md §9.1, §10 — the model touching files is shown, never
        // silent). Each op appends one outcome line; the heading counts them.
        function onFileToolStarted(heading) {
            if (win.activeIndex < 0) return;
            var cur = chatLog.get(win.activeIndex);
            chatLog.setProperty(win.activeIndex, "filesPending", cur.filesPending + 1);
            chatLog.setProperty(win.activeIndex, "filesActive", true);
        }
        function onFileToolDone(line, ok) {
            if (win.activeIndex < 0) return;
            var cur = chatLog.get(win.activeIndex);
            var prefix = cur.files !== "" ? cur.files + "\n" : "";
            chatLog.setProperty(win.activeIndex, "files", prefix + line);
            chatLog.setProperty(win.activeIndex, "fileCount", cur.fileCount + 1);
            var pending = Math.max(0, cur.filesPending - 1);
            chatLog.setProperty(win.activeIndex, "filesPending", pending);
            chatLog.setProperty(win.activeIndex, "filesActive", pending > 0);
        }
        // DELEGATION, its own subordinated disclosure (docs/DESIGN.md §9.1, §10).
        // A spawn used to be drawn through the file block, which said "files ·
        // N" about work that touched no file of his and hid both the wait and
        // the answer. Now: the heading names the live agent and counts its
        // rounds while it works, and the body keeps one block per agent — who,
        // the task, what it cost, and what it came back with.
        function onAgentStarted(name, task, model) {
            if (win.activeIndex < 0) return;
            var cur = chatLog.get(win.activeIndex);
            chatLog.setProperty(win.activeIndex, "agentsPending", cur.agentsPending + 1);
            chatLog.setProperty(win.activeIndex, "agentsActive", true);
            chatLog.setProperty(win.activeIndex, "agentHead",
                                name + (model !== "" ? " · " + model : ""));
            // The turn is WAITING on it, exactly as it waits on a tool call —
            // and a subagent is the longest wait there is.
            chatLog.setProperty(win.activeIndex, "awaiting", true);
            win.accrueThink(win.activeIndex);
        }
        function onAgentProgress(name, round, tool) {
            if (win.activeIndex < 0) return;
            chatLog.setProperty(win.activeIndex, "agentHead",
                                name + " · round " + round + " · " + tool);
        }
        function onAgentDone(name, ok, block) {
            if (win.activeIndex < 0) return;
            var cur = chatLog.get(win.activeIndex);
            var prefix = cur.agents !== "" ? cur.agents + "\n\n" : "";
            chatLog.setProperty(win.activeIndex, "agents", prefix + block);
            chatLog.setProperty(win.activeIndex, "agentCount", cur.agentCount + 1);
            if (!ok) chatLog.setProperty(win.activeIndex, "agentsBad", true);
            var pending = Math.max(0, cur.agentsPending - 1);
            chatLog.setProperty(win.activeIndex, "agentsPending", pending);
            chatLog.setProperty(win.activeIndex, "agentsActive", pending > 0);
        }
        // The generic per-round tool indicator: every tool the model calls is
        // named in the transcript (docs/DESIGN.md §9.1, §10 — never silent),
        // whether or not it also has a richer disclosure (web sources, files,
        // images) below. Each call appends one name; the heading counts them and
        // the ellipsis runs until the whole reply settles (onReplyDone/Error).
        function onToolCallStarted(name) {
            if (win.activeIndex < 0) return;
            var cur = chatLog.get(win.activeIndex);
            var prefix = cur.tools !== "" ? cur.tools + "\n" : "";
            chatLog.setProperty(win.activeIndex, "tools", prefix + name);
            chatLog.setProperty(win.activeIndex, "toolCount", cur.toolCount + 1);
            chatLog.setProperty(win.activeIndex, "toolsActive", true);
            // The turn is now WAITING on that tool — until the next delta of any
            // kind arrives. That wait counts as thinking time [his, 2026-08-22].
            chatLog.setProperty(win.activeIndex, "awaiting", true);
            win.accrueThink(win.activeIndex);
        }
        // A NEW TOOL ROUND. One bubble per round [his, 2026-08-23]: the row the
        // last round wrote into is settled where it is — with the tools IT
        // called still attached to it — and a fresh row opens for what the model
        // says next. Without this a turn that took six rounds was one bubble
        // holding six rounds of prose, every tool name and the final answer,
        // with nothing to show where one round ended and the next began.
        function onRoundStarted(n) {
            if (win.activeIndex < 0) return;
            win.stopThinkClock(win.activeIndex);
            var cur = chatLog.get(win.activeIndex);
            // A media-only round — a picture fetched (or a video resolved) with
            // no words yet — does NOT open a fresh bubble [his, 2026-08-23].
            // The next round's text lands on the SAME row, so the image and the
            // answer it accompanies read as one message instead of a detached
            // picture floating above a separate text bubble. Once a row HAS
            // words, the rounds split again (one bubble per round) as before.
            var mediaOnly = !cur.isUser && (cur.body || "") === ""
                && ((cur.images !== "[]" && cur.images !== "") || cur.imagesActive
                    || (cur.videos !== "[]" && cur.videos !== "") || cur.videosActive);
            chatLog.setProperty(win.activeIndex, "thinkingActive", false);
            chatLog.setProperty(win.activeIndex, "awaiting", false);
            chatLog.setProperty(win.activeIndex, "toolsActive", false);
            // The row this round leaves behind is finished, so nothing in it is
            // still running: without this it keeps execRunning forever and its
            // files disclosure stays auto-open for the rest of the session.
            chatLog.setProperty(win.activeIndex, "execRunning", false);
            if (mediaOnly) {
                // Stay on this row, still streaming, so the next delta's prose
                // appends here and the think-clock keeps running — the same
                // wake-up the fresh-row path gives a new row.
                chatLog.setProperty(win.activeIndex, "streaming", true);
                chatLog.setProperty(win.activeIndex, "awaiting", true);
                win.accrueThink(win.activeIndex);
                return;
            }
            chatLog.setProperty(win.activeIndex, "streaming", false);
            win.appendReplyRow(n);
        }
        // The image-fetch tool: the model asked for an image, and one entry came
        // back — either a fetched picture (rendered inline) or a failure line
        // (docs/DESIGN.md §10 — the failure is shown, never dropped). ONE data
        // contract: `imageFetchResult` is a single JSON entry we append to the
        // row's image list, which the delegate renders.
        function onImageFetchStarted(url) {
            if (win.activeIndex < 0) return;
            var cur = chatLog.get(win.activeIndex);
            chatLog.setProperty(win.activeIndex, "imagesPending", cur.imagesPending + 1);
            chatLog.setProperty(win.activeIndex, "imagesActive", true);
        }
        function onImageFetchResult(entryJson) {
            if (win.activeIndex < 0) return;
            var cur = chatLog.get(win.activeIndex);
            var arr;
            try { arr = JSON.parse(cur.images); } catch (e) { arr = []; }
            var entry;
            try { entry = JSON.parse(entryJson); } catch (e2) { entry = null; }
            if (entry) {
                arr.push(entry);
                chatLog.setProperty(win.activeIndex, "images", JSON.stringify(arr));
            }
            var pending = Math.max(0, cur.imagesPending - 1);
            chatLog.setProperty(win.activeIndex, "imagesPending", pending);
            chatLog.setProperty(win.activeIndex, "imagesActive", pending > 0);
        }
        // The video tool: one entry per call, the same contract the images
        // use one step along — a resolved stream (drawn as a card) or an honest
        // failure line. `videosActive` is the in-flight line while yt-dlp is
        // still turning a watch page into a stream, which is the slow part.
        function onVideoStarted(url) {
            if (win.activeIndex < 0) return;
            var cur = chatLog.get(win.activeIndex);
            chatLog.setProperty(win.activeIndex, "videosPending", cur.videosPending + 1);
            chatLog.setProperty(win.activeIndex, "videosActive", true);
        }
        function onVideoResult(entryJson) {
            if (win.activeIndex < 0) return;
            var cur = chatLog.get(win.activeIndex);
            var arr;
            try { arr = JSON.parse(cur.videos); } catch (e) { arr = []; }
            var entry;
            try { entry = JSON.parse(entryJson); } catch (e2) { entry = null; }
            if (entry) {
                arr.push(entry);
                chatLog.setProperty(win.activeIndex, "videos", JSON.stringify(arr));
            }
            var pending = Math.max(0, cur.videosPending - 1);
            chatLog.setProperty(win.activeIndex, "videosPending", pending);
            chatLog.setProperty(win.activeIndex, "videosActive", pending > 0);
        }
        // A run_bash / run_python program, AS IT RUNS [his, 2026-08-23]. The
        // tail is bounded (execTailMax) — this is a window on the work, not a
        // second transcript — and it lives under the files disclosure with the
        // tool lines it belongs to. It is transient: `saveCurrent` does not
        // persist it, because what the program MEANT is in the reply.
        function onExecStarted(lang) {
            if (win.activeIndex < 0) return;
            chatLog.setProperty(win.activeIndex, "execTail", "");
            chatLog.setProperty(win.activeIndex, "execRunning", true);
        }
        function onExecOutput(chunk) {
            if (win.activeIndex < 0 || chunk === "") return;
            var cur = chatLog.get(win.activeIndex);
            var t = (cur.execTail || "") + chunk;
            if (t.length > win.execTailMax)
                t = "…" + t.substring(t.length - win.execTailMax);
            chatLog.setProperty(win.activeIndex, "execTail", t);
        }
        // The program stopped. `execRunning` means one is running RIGHT NOW —
        // it is what opens the files disclosure on its own — so it falls at the
        // end of the program, not at the end of the turn.
        function onExecFinished() {
            if (win.activeIndex < 0) return;
            chatLog.setProperty(win.activeIndex, "execRunning", false);
        }
        // A RENDER, AS IT RUNS [his, 2026-08-24]. A picture is minutes and a
        // clip is tens of them, and until now the whole of it was one
        // motionless "making a picture…" — which reads as stalled. painter's
        // generator reports where it is; this puts it under the tool
        // disclosure as a labelled bar, the same place the reasoning and the
        // file lines live. Transient, like `execTail`: what it MADE is the
        // picture in the reply, so nothing here is persisted.
        function onGenProgress(label, frac) {
            if (win.activeIndex < 0) return;
            chatLog.setProperty(win.activeIndex, "genLabel", label);
            chatLog.setProperty(win.activeIndex, "genFrac", frac);
            chatLog.setProperty(win.activeIndex, "genRunning", true);
        }
        function onGenFinished() {
            if (win.activeIndex < 0) return;
            chatLog.setProperty(win.activeIndex, "genRunning", false);
            chatLog.setProperty(win.activeIndex, "genFrac", 0);
            chatLog.setProperty(win.activeIndex, "genLabel", "");
        }
        function onReplyDone() {
            if (win.activeIndex < 0) return;
            win.stopThinkClock(win.activeIndex);
            chatLog.setProperty(win.activeIndex, "streaming", false);
            chatLog.setProperty(win.activeIndex, "thinkingActive", false);
            chatLog.setProperty(win.activeIndex, "awaiting", false);
            chatLog.setProperty(win.activeIndex, "searching", false);
            chatLog.setProperty(win.activeIndex, "filesActive", false);
            chatLog.setProperty(win.activeIndex, "imagesActive", false);
            chatLog.setProperty(win.activeIndex, "videosActive", false);
            chatLog.setProperty(win.activeIndex, "execRunning", false);
            chatLog.setProperty(win.activeIndex, "genRunning", false);
            chatLog.setProperty(win.activeIndex, "toolsActive", false);
            chatLog.setProperty(win.activeIndex, "agentsActive", false);
            chatLog.setProperty(win.activeIndex, "agentsPending", 0);
            win.chatRev++;              // the compose button can offer `continue`
            win.saveCurrent();          // the finished turn persists to the session
            win.autoContinue();
        }
        function onReplyError(reason) {
            if (win.activeIndex < 0) return;
            chatLog.setProperty(win.activeIndex, "body", "error: " + reason);
            chatLog.setProperty(win.activeIndex, "isError", true);
            win.stopThinkClock(win.activeIndex);
            chatLog.setProperty(win.activeIndex, "streaming", false);
            chatLog.setProperty(win.activeIndex, "thinkingActive", false);
            chatLog.setProperty(win.activeIndex, "awaiting", false);
            chatLog.setProperty(win.activeIndex, "searching", false);
            chatLog.setProperty(win.activeIndex, "filesActive", false);
            chatLog.setProperty(win.activeIndex, "imagesActive", false);
            chatLog.setProperty(win.activeIndex, "videosActive", false);
            chatLog.setProperty(win.activeIndex, "execRunning", false);
            chatLog.setProperty(win.activeIndex, "genRunning", false);
            chatLog.setProperty(win.activeIndex, "toolsActive", false);
            chatLog.setProperty(win.activeIndex, "agentsActive", false);
            chatLog.setProperty(win.activeIndex, "agentsPending", 0);
            win.chatRev++;
            win.saveCurrent();
        }
        function onModelsError(reason) { win.status = "no models: " + reason; }
    }

    // The backend controls (server up/down, loaded model, start/stop, unload)
    // report through the same status line the model list uses, and refill the
    // model list the moment the daemon comes back up.
    Connections {
        target: Backend
        function onNote(msg) { win.serverNote = msg; }
        function onStatusChanged() {
            if (Backend.serverUp && Ollama.models.length === 0)
                Ollama.refreshModels();
        }
    }

    // ------------------------------------------------------------- sessions
    // A stable id, minted once client-side (so the store never has to mint one
    // and there is no round-trip before the first save).
    function ensureSessionId() {
        if (win.sessionId === "")
            win.sessionId = "sess-" + Date.now() + "-"
                            + Math.floor(1000 + Math.random() * 9000);
        return win.sessionId;
    }

    // Persist the whole current transcript to its session. Titles itself from
    // the first user prompt the first time (a meaningful name with no modal).
    // Only the display fields are stored; the transient stream flags are not.
    function saveCurrent() {
        if (chatLog.count === 0)
            return;
        var id = ensureSessionId();
        var title = win.sessionTitle;
        if (title === "") {
            for (var i = 0; i < chatLog.count; i++) {
                var r = chatLog.get(i);
                if (r.isUser && r.body.trim() !== "") {
                    title = r.body.trim().substring(0, 48);
                    break;
                }
            }
            if (title === "") title = "session";
            win.sessionTitle = title;
        }
        var turns = [];
        for (var j = 0; j < chatLog.count; j++) {
            var t = chatLog.get(j);
            turns.push({ isUser: t.isUser, who: t.who, body: t.body, step: t.step,
                         ts: t.ts,
                         thinking: t.thinking, thinkTokens: t.thinkTokens,
                         thinkMs: t.thinkMs, cutOff: t.cutOff,
                         sources: t.sources, searchCount: t.searchCount,
                         files: t.files, fileCount: t.fileCount,
                         agents: t.agents, agentCount: t.agentCount,
                         agentsBad: t.agentsBad,
                         images: t.images, videos: t.videos,
                         tools: t.tools, toolCount: t.toolCount,
                         isError: t.isError });
        }
        Sessions.save(id, title, JSON.stringify(turns));
    }

    // Start a fresh, empty session. Persist the current conversation FIRST
    // (auto-titled from its first prompt if it has no title yet) so starting a
    // new one never discards it — saveCurrent snapshots the log synchronously
    // before the async store write, so clearing right after is safe. Then clear
    // the view and forget the id/title so the next turn opens a new session.
    function newSession() {
        win.saveCurrent();
        Ollama.cancel();
        chatLog.clear();
        win.activeIndex = -1;
        win.sessionId = "";
        win.sessionTitle = "";
        win.status = "";
        sessionPicker.open = false;
    }

    // THE MESSAGE MENU. Right-clicking a message is how every other program on
    // this desktop offers to copy a piece of text, and the log had no way in at
    // all: Ctrl+C only, on a selection made with the mouse. The rows are the
    // three a read-only transcript can honestly offer (docs/DESIGN.md §10.2 —
    // "copy" is dead while nothing is selected rather than quietly copying
    // something else). `md` is true for a model's reply, which is Markdown and
    // must be copied AS Markdown (main.py → Clip; the rendered document
    // flattens to one run-on block).
    //
    // The words follow the session: the KDE menu around it says Copy and Select
    // All, this desktop's own menus are lowercase (docs/agents/his-voice.md).
    // THE MESSAGE THE EDIT MENU ACTS ON. A transcript is many independent
    // read-only editors, so "Copy" has no single target the way it does in a
    // text editor; the one a KDE hand means is the message it just selected in.
    // Each body reports itself here when its selection changes, and the Edit
    // menu's rows are disabled while nothing has one — never a row that looks
    // live and does nothing (docs/DESIGN.md §10).
    property var selectedBody: null
    property bool selectedIsMd: false
    property string selectedText: ""
    function noteSelection(item, md) {
        win.selectedBody = item;
        win.selectedIsMd = md;
        win.selectedText = item ? item.selectedText : "";
    }

    // Run one row of `textMenu` against the message the selection is in — the
    // Edit menu's rows and the right-click menu's are then literally the same
    // triggers, and cannot drift apart.
    function runTextRow(i) {
        var item = win.selectedBody;
        if (!item)
            return;
        var rows = win.textMenu(item, win.selectedIsMd);
        var row = rows[i];
        if (row && row.trigger && row.enabled !== false)
            row.trigger();
    }

    // BRANCHING [his, 2026-08-23]. Going back to an earlier turn and asking
    // again is not "undo": what came after is a real conversation and must not
    // evaporate. So the transcript as it stands is SAVED first, under the id it
    // already has, and the shortened one becomes a NEW session — the old branch
    // keeps its title and its rows in the picker, and this window carries on
    // from the fork. Nothing is deleted anywhere.
    function branchAt(i) {
        if (i < 0 || i >= chatLog.count || Ollama.busy)
            return false;
        win.saveCurrent();               // the branch he is leaving, intact
        win.sessionId = "";              // …and the one he is entering is new
        win.sessionTitle = "";
        Ollama.cancel();
        while (chatLog.count > i)
            chatLog.remove(chatLog.count - 1);
        win.activeIndex = -1;
        win.chatRev++;
        return true;
    }

    // Put an earlier prompt back in the box, with everything after it on its
    // own branch. He edits and presses send; nothing is sent for him.
    function editFrom(i) {
        if (i < 0 || i >= chatLog.count)
            return;
        var text = chatLog.get(i).body;
        if (!branchAt(i))
            return;
        promptBox.text = text;
        promptBox.forceActiveFocus();
    }

    // Ask the same question again: drop this answer (and anything after it) and
    // re-send the prompt above it, unchanged.
    function retryFrom(i) {
        if (i < 0 || i >= chatLog.count)
            return;
        var j = i;
        while (j >= 0 && !chatLog.get(j).isUser)
            j--;
        if (j < 0)
            return;
        var text = chatLog.get(j).body;
        if (!branchAt(j))
            return;
        promptBox.text = text;
        win.send();
    }

    function textMenu(item, md) {
        return [
            { label: win.plasma ? "Copy" : "copy",
              enabled: item.selectedText !== "",
              trigger: function () {
                  if (md && Clip.copyMarkdown(item.textDocument,
                                              item.selectionStart,
                                              item.selectionEnd, item.source))
                      return;
                  item.copy();
              } },
            { label: win.plasma ? "Copy Message" : "copy message",
              trigger: function () {
                  // A run of a split reply copies the WHOLE original markdown
                  // (its `messageSource`), image references intact — not just
                  // the one run the selection sits in.
                  var whole = md ? (item.messageSource || item.source) : item.text;
                  Clip.copyText(whole);
              } },
            { separator: true },
            { label: win.plasma ? "Select All" : "select all",
              trigger: function () { item.forceActiveFocus(); item.selectAll(); } }
        ];
    }

    // The same menu, plus what can be done to THIS turn: edit a prompt of his
    // and ask again, or ask the same question again. Both branch (above), and
    // both stand down while a reply is streaming — re-asking mid-answer would
    // race the stream (§10.2: a row that cannot act is disabled, never inert).
    function turnMenu(item, md, i, isUser) {
        var rows = win.textMenu(item, md);
        rows.push({ separator: true });
        if (isUser)
            rows.push({ label: win.plasma ? "Edit && Resend" : "edit & resend",
                        enabled: !Ollama.busy,
                        trigger: function () { win.editFrom(i); } });
        else
            rows.push({ label: win.plasma ? "Ask Again" : "ask again",
                        enabled: !Ollama.busy,
                        trigger: function () { win.retryFrom(i); } });
        return rows;
    }

    // WHAT CAN BE DONE WITH A PICTURE OR A CLIP IN THE LOG [his, 2026-08-24].
    // Copying is the point: a generated picture he likes has to be able to
    // leave the window, and until now nothing in the chat could. `copy image`
    // offers the pixels AND the file, so a paste lands as the picture in an
    // editor and as a named file everywhere else; `copy file` is the file
    // alone, which is all a video has to give (pylib/clipfile.py). Both report
    // (§10) — a copy that silently did nothing looks exactly like one that
    // worked, right up until the paste.
    function mediaMenu(path, isVideo) {
        var rows = [];
        if (!isVideo)
            rows.push({ label: win.plasma ? "Copy Image" : "copy image",
                        trigger: function () { Clip.copyImage(path); } });
        rows.push({ label: win.plasma ? "Copy File" : "copy file",
                    trigger: function () { Clip.copyFile(path); } });
        rows.push({ separator: true });
        rows.push({ label: win.plasma ? "Copy Path" : "copy path",
                    trigger: function () { Clip.copyText(path); } });
        return rows;
    }

    // One right-click on a picture or a clip, wherever in the log it was.
    function openMediaMenu(path, x, y, isVideo) {
        if (!path || path === "") return;
        ctxMenu.open(x, y, win.mediaMenu(path, isVideo === true));
    }

    // Open the custom-prompt editor (from the picker's "custom…" or the "edit"
    // button), prefilled with his saved custom text.
    function openPromptEditor() {
        promptPicker.open = false;
        promptEditor.load(Ollama.customPrompt);
    }

    // ONE assistant row, appended and made the active one. `step` is the round
    // it belongs to: 1 for the row his prompt opens, 2 and up for the row each
    // further tool round opens. The caption names it from 2 on ("model · round
    // 2") — round 1 needs no label, and an old session (no `step`) reads 0 and
    // shows none either (docs/DESIGN.md §9.1).
    function appendReplyRow(step) {
        chatLog.append({ isUser: false, who: win.model, body: "", step: step,
                         ts: Math.floor(Date.now() / 1000),
                         thinking: "", thinkingActive: false, thinkTokens: 0,
                         thinkStart: 0, thinkMs: 0, awaiting: true, cutOff: false,
                         sources: "", searchCount: 0, searching: false,
                         files: "", fileCount: 0, filesActive: false, filesPending: 0,
                         agents: "", agentCount: 0, agentsActive: false,
                         agentsPending: 0, agentHead: "", agentsBad: false,
                         images: "[]", imagesActive: false, imagesPending: 0,
                         videos: "[]", videosActive: false, videosPending: 0,
                         execTail: "", execRunning: false,
                         genLabel: "", genFrac: 0, genRunning: false,
                         tools: "", toolCount: 0, toolsActive: false,
                         streaming: true, isError: false });
        win.activeIndex = chatLog.count - 1;
        win.chatRev++;
        win.accrueThink(win.activeIndex);
    }

    // What the log holds right now, for a HARNESS to read (never drawn):
    // tools/round-split-test.py asserts on it that a turn taking two tool rounds
    // ends up as three rows — round 1, round 2, the answer — rather than one
    // bubble with everything in it.
    // How much of a running program's output the row keeps on screen.
    readonly property int execTailMax: 4000

    function rowsJson() {
        var a = [];
        for (var i = 0; i < chatLog.count; i++) {
            var r = chatLog.get(i);
            a.push({ isUser: r.isUser, who: r.who, step: r.step, ts: r.ts,
                     body: r.body, tools: r.tools, toolCount: r.toolCount,
                     agents: r.agents, agentCount: r.agentCount,
                     images: r.images, imagesActive: r.imagesActive,
                     videos: r.videos, videosActive: r.videosActive,
                     streaming: r.streaming, isError: r.isError });
        }
        return JSON.stringify(a);
    }

    // What the TURN META BLOCK is doing right now, for a HARNESS to read (never
    // drawn): tools/round-split-test.py asserts that a turn's bookkeeping comes
    // out as one block at its head, and that a round which said nothing is not
    // drawn as a row at all.
    function turnJson() {
        var a = [];
        for (var i = 0; i < chatLog.count; i++) {
            var r = chatLog.get(i);
            var h = win.turnHead(i);
            var g = h === i ? win.turnAgg(h) : null;
            a.push({ head: h,
                     drawn: r.isUser || h === i || !win.roundIsSilent(r),
                     rounds: g ? g.rounds : 0,
                     tools: g ? g.toolCount : 0 });
        }
        return JSON.stringify(a);
    }

    // Rebuild the log from a loaded transcript (transient flags reset).
    function loadTurns(id, title, turnsJson) {
        var arr;
        try { arr = JSON.parse(turnsJson); } catch (e) { arr = []; }
        // Persist the outgoing session before it is replaced, the same guard
        // "+ new session" carries — switching away must not drop an unsaved
        // turn (e.g. one still mid-stream). saveCurrent snapshots synchronously;
        // it no-ops on an empty log.
        win.saveCurrent();
        Ollama.cancel();
        chatLog.clear();
        for (var i = 0; i < arr.length; i++) {
            var t = arr[i];
            chatLog.append({ isUser: !!t.isUser, who: t.who || "", body: t.body || "",
                             thinking: t.thinking || "", thinkingActive: false,
                             thinkTokens: t.thinkTokens || 0,
                             thinkStart: 0, thinkMs: t.thinkMs || 0,
                             awaiting: false, cutOff: !!t.cutOff,
                             sources: t.sources || "", searchCount: t.searchCount || 0,
                             searching: false,
                             files: t.files || "", fileCount: t.fileCount || 0,
                             filesActive: false, filesPending: 0,
                             agents: t.agents || "", agentCount: t.agentCount || 0,
                             agentsActive: false, agentsPending: 0, agentHead: "",
                             agentsBad: !!t.agentsBad,
                             images: t.images || "[]", imagesActive: false, imagesPending: 0,
                             videos: t.videos || "[]", videosActive: false, videosPending: 0,
                             execTail: "", execRunning: false,
                             genLabel: "", genFrac: 0, genRunning: false,
                             tools: t.tools || "", toolCount: t.toolCount || 0, toolsActive: false,
                             streaming: false, isError: !!t.isError,
                             step: t.step || 0, ts: t.ts || 0 });
        }
        win.sessionId = id;
        win.sessionTitle = title;
        win.activeIndex = -1;
        win.status = "";
        sessionPicker.open = false;
    }

    // ---- the mini-player ---------------------------------------------------
    // When a video is playing whose bubble is not in view, a compact bar at the
    // top of the message view carries its transport so he always has scrub /
    // play-pause / stop [his, 2026-08-23]. The cards register themselves with
    // `videoCardActive` when a player is built (VideoCard's Loader.onLoaded)
    // and with `videoCardGone` when they are destroyed; a small timer, running
    // only while any card is registered, opens the bar for the first registered
    // card that has scrolled out of view and closes it when that card is back.
    property var miniCards: []
    // The card whose bar he dismissed — that one stays closed until it comes
    // back into view, so a dismissed bar is not reopened 200ms later.
    property var miniDismissed: null
    function videoCardActive(card) {
        if (miniCards.indexOf(card) < 0) miniCards.push(card);
        miniTimer.restart();
    }
    function videoCardGone(card) {
        var i = miniCards.indexOf(card);
        if (i >= 0) miniCards.splice(i, 1);
        if (miniDismissed === card) miniDismissed = null;
        if (miniPlayer.card === card) miniPlayer.close();
        if (miniCards.length === 0) miniTimer.stop();
    }
    function updateMini() {
        try {
            // Drop cards that died without announcing it (a reload can race the
            // destruction handler), then pick the first one out of view.
            for (var i = 0; i < miniCards.length; i++) {
                var c = miniCards[i];
                if (!c || !c.video || c.video.item === null) {
                    miniCards.splice(i, 1); i--;
                    continue;
                }
                var p = c.mapToItem(replyFlick, 0, 0);
                var inView = (p.y + c.height >= 0) && (p.y <= replyFlick.height);
                if (inView) {
                    if (miniDismissed === c) miniDismissed = null;
                    continue;
                }
                if (miniDismissed !== c && miniPlayer.card !== c)
                    miniPlayer.open(c.video.item.player, c.video.item.out, c);
                return;
            }
            if (miniPlayer.opened) miniPlayer.close();
        } catch (e) { /* a card died mid-tick — the next tick will drop it */ }
    }
    Timer {
        id: miniTimer
        interval: 200
        repeat: true
        onTriggered: win.updateMini()
    }

    Connections {
        target: Sessions
        function onLoaded(id, title, turnsJson) { win.loadTurns(id, title, turnsJson); }
        function onSaved(id, title) {
            // Deliberately does NOT touch win.sessionId / win.sessionTitle.
            // saveCurrent() sets both SYNCHRONOUSLY (ensureSessionId + the title
            // derivation) before this async store result ever arrives, so
            // re-applying them here is redundant — and worse, a hazard: a save
            // that lands AFTER "+ new session" (or a session switch) has reset
            // the identity would stamp the OLD id back onto the fresh, empty
            // session, and the next turn would then overwrite the old
            // conversation. That is exactly the "new session loses the previous
            // one" data loss. The store never rewrites the id, so there is
            // nothing to reflect back; refresh() already ran in Sessions.save.
        }
        function onError(reason) { win.status = "session store: " + reason; }
    }

    function send() {
        var p = promptBox.text.trim();
        // A message may be text, files, or both — but never empty of both.
        if ((p === "" && attachments.count === 0) || win.model === "" || Ollama.busy)
            return;
        win.status = "";
        // Snapshot the attachments for this turn, then clear the tray.
        var atts = [];
        var names = [];
        for (var a = 0; a < attachments.count; a++) {
            var at = attachments.get(a);
            atts.push({ name: at.name, path: at.path });
            names.push(at.name);
        }
        // What the model gets as the prompt (Ollama.send inlines the file text
        // after it); a files-only message still needs an instruction.
        var sendPrompt = p !== "" ? p : "Please look at the attached file(s).";
        // What is DISPLAYED and saved: his text plus a dim note of the filenames
        // (the file bodies are not dumped into the visible log).
        var shownBody = (p !== "" ? p : "(attached files)")
                      + (names.length > 0 ? "\n[attached: " + names.join(", ") + "]" : "");
        // The prior turns of THIS chat, so the model sees the whole conversation
        // rather than just the new prompt — built before the pair below is
        // appended, and skipping error placeholders / empty streams, which are
        // never real conversation content.
        var history = [];
        for (var i = 0; i < chatLog.count; i++) {
            var h = chatLog.get(i);
            if (h.isError || h.body.trim() === "")
                continue;
            history.push({ role: h.isUser ? "user" : "assistant",
                           content: win.stampedBody(h) });
        }
        // Append the pair now, then stream into the assistant row. Prior turns
        // are left untouched — the log grows downward (docs/DESIGN.md §14).
        chatLog.append({ isUser: true, who: "you", body: shownBody,
                         ts: Math.floor(Date.now() / 1000),
                         thinking: "", thinkingActive: false, thinkTokens: 0,
                         thinkStart: 0, thinkMs: 0, awaiting: false, cutOff: false,
                         sources: "", searchCount: 0, searching: false,
                         files: "", fileCount: 0, filesActive: false, filesPending: 0,
                         agents: "", agentCount: 0, agentsActive: false,
                         agentsPending: 0, agentHead: "", agentsBad: false,
                         images: "[]", imagesActive: false, imagesPending: 0,
                         videos: "[]", videosActive: false, videosPending: 0,
                         execTail: "", execRunning: false,
                         genLabel: "", genFrac: 0, genRunning: false,
                         tools: "", toolCount: 0, toolsActive: false,
                         streaming:false, isError: false, step: 0 });
        win.appendReplyRow(1);
        win.autoContinues = 0;             // a new prompt re-arms the auto-press
        Ollama.rememberModel(win.model);   // the model he last used is next launch's default
        Ollama.send(win.model, sendPrompt, JSON.stringify(history), JSON.stringify(atts));
        promptBox.clear();
        win.clearAttachments();
        // Sending puts him back at the BOTTOM [his, 2026-08-23]. Reading back
        // through the log clears `followBottom`, and without this his own new
        // prompt lands off-screen below him — the one place jumping the view is
        // not yanking it, since he just wrote the thing at the end of it.
        replyFlick.toBottom();
    }

    // ---- the Plasma chrome: one table, three widgets ----------------------
    // chatter registers NO hyprvtb titlebar buttons — it never has, and the
    // compositor draws only its title (§12). This table is the COMPLETE set of
    // its verbs, published as `actions` for `kdeshell.bind_chrome`, which builds
    // the menubar and the toolbar out of it in a Plasma session. Nothing here
    // reaches the vtb socket (`Titlebar.setButtons` is never called), so the
    // Hyprland face is exactly what it was.
    //
    //   menu:      which menu this verb belongs to
    //   menuText:  the menu's wording
    //   icon:      a freedesktop icon name, for the toolbar
    //   bar:       true = it earns a toolbar slot; the menus stay the full set
    //   group:     a radio set (the sessions are one, the base prompts another)
    //   state:     0 normal, 1 lit/checked, 2 disabled
    //   shortcut:  THIS FACE'S key ("@New" takes the platform's standard one)
    readonly property var actions: {
        const out = [];
        out.push({ id: "new-session", menu: "file", menuText: "New Session",
                   tip: "start a fresh conversation", icon: "document-new",
                   bar: true, shortcut: "@New" });
        // The saved sessions, as a radio set: one of them IS the conversation
        // on screen, and two independent checkmarks could claim otherwise. The
        // toolbar's combo carries the whole list; the menu carries the recent
        // ones, because a menu that grows without bound is not a menu.
        const ss = Sessions.sessions;
        if (ss.length > 0) {
            out.push("-");
            for (var i = 0; i < Math.min(ss.length, 12); i++)
                out.push({ id: "session:" + ss[i].id, menu: "file",
                           menuText: ss[i].title, group: "sessions",
                           state: ss[i].id === win.sessionId ? 1 : 0 });
        }
        out.push("-");
        out.push({ id: "delete-session", menu: "file",
                   menuText: "Delete Session…", icon: "edit-delete",
                   state: win.sessionId !== "" ? 0 : 2 });

        // Send is Enter in the prompt box in both sessions; this is the same
        // verb with a name on it, and the one control that reports a stream is
        // running — it becomes Stop while it is (§10.6).
        var sends = win.canSend || !win.canContinue;
        out.push({ id: "send", menu: "chat",
                   menuText: Ollama.busy ? "Stop Generating"
                             : (sends ? "Send" : "Continue"),
                   tip: Ollama.busy ? "stop the reply"
                        : (sends ? "send the prompt" : "carry the last reply on"),
                   icon: Ollama.busy ? "process-stop"
                         : (sends ? "document-send" : "media-playback-start"),
                   bar: true, shortcut: "Ctrl+Return",
                   state: (Ollama.busy || win.canSend || win.canContinue) ? 0 : 2 });
        out.push("-");
        out.push({ id: "attach", menu: "chat", menuText: "Attach Files…",
                   tip: "attach files to the next message",
                   icon: "mail-attachment", bar: true, shortcut: "@Open" });
        out.push({ id: "detach", menu: "chat", menuText: "Clear Attachments",
                   state: attachments.count > 0 ? 0 : 2 });

        // &Edit — the verbs a KDE hand goes to the menubar for. chatter was
        // the only app of ours with no Edit menu at all: Copy and Select All
        // existed ONLY on the transcript's right-click menu, so Ctrl+C had no
        // home a menu could show and no way to discover it. They act on the
        // message the selection is in (win.selectedBody), and are disabled
        // while there is none rather than silently doing nothing.
        out.push({ id: "copy", menu: "edit", menuText: "Copy",
                   tip: "copy the selected text", icon: "edit-copy",
                   shortcut: "@Copy",
                   state: win.selectedText !== "" ? 0 : 2 });
        out.push({ id: "copy-message", menu: "edit",
                   menuText: "Copy Whole Message",
                   tip: "copy the message the selection is in",
                   state: win.selectedBody !== null ? 0 : 2 });
        out.push("-");
        out.push({ id: "select-all", menu: "edit", menuText: "Select All",
                   icon: "edit-select-all", shortcut: "@SelectAll",
                   state: win.selectedBody !== null ? 0 : 2 });

        out.push({ id: "refresh-models", menu: "tools",
                   menuText: "Refresh Model List", icon: "view-refresh",
                   shortcut: "@Refresh" });
        out.push({ id: "unload", menu: "tools", menuText: "Unload Model",
                   tip: "free the loaded model's memory",
                   state: Backend.loadedModels.length > 0 ? 0 : 2 });
        out.push({ id: "server", menu: "tools",
                   menuText: Backend.serverUp ? "Stop Server" : "Start Server",
                   icon: Backend.serverUp ? "system-shutdown" : "system-run",
                   state: Backend.busy ? 2 : 0 });

        // The base system prompt: the presets plus his own custom text, one
        // radio set, and the editor that writes the custom half.
        const ps = Ollama.promptPresets;
        for (var j = 0; j < ps.length; j++)
            out.push({ id: "prompt:" + ps[j].id, menu: "settings",
                       menuText: "Base Prompt: " + ps[j].label,
                       group: "prompt", state: Ollama.promptChoice === ps[j].id ? 1 : 0 });
        out.push({ id: "prompt:custom", menu: "settings",
                   menuText: "Base Prompt: Custom", group: "prompt",
                   state: Ollama.promptChoice === "custom" ? 1 : 0 });
        out.push({ id: "edit-prompt", menu: "settings",
                   menuText: "Edit Custom Prompt…", icon: "document-edit" });
        return out;
    }
    // chatter's own group ("chat") sits where kdeshell puts an app's invented
    // menus: after the ones KDE names, before Settings.
    readonly property var menuOrder: ["chat"]

    readonly property bool canSend:
        win.model !== "" && !Ollama.busy
        && (promptBox.text.trim() !== "" || attachments.count > 0)

    // Is there a finished reply at the bottom to carry on? The compose box's
    // button reads this — `continue` lives on the button beside the box, not
    // under the bubble [his, 2026-08-23]. Only the LAST row: continuing one
    // further up would write into the middle of the conversation.
    //
    // `chatRev` is the dependency a ListModel does not give us: `count` has a
    // notify, the per-row `streaming` flag does not, and `busy` flips BEFORE
    // the handler clears it — so every place that settles a row bumps this.
    property int chatRev: 0
    readonly property bool canContinue: {
        win.chatRev;                       // re-evaluate when a row settles
        if (win.model === "" || Ollama.busy) return false;
        var i = chatLog.count - 1;
        if (i < 0) return false;
        var r = chatLog.get(i);
        return !r.isUser && !r.isError && !r.streaming;
    }

    // ONE handler, both chromes — the menubar and the toolbar click these ids.
    function tbAction(id) {
        if (id.indexOf("session:") === 0) {
            var sid = id.substring(8);
            if (sid !== win.sessionId)
                Sessions.open(sid);
            return;
        }
        if (id.indexOf("prompt:") === 0) {
            var pid = id.substring(7);
            if (pid === "custom") win.openPromptEditor();
            else Ollama.setPromptChoice(pid);
            return;
        }
        switch (id) {
        case "new-session":    win.newSession();                break;
        case "delete-session": win.deleteCurrentSession();      break;
        case "send":           if (Ollama.busy) win.stopReply();
                               else if (win.canSend || !win.canContinue) win.send();
                               else win.continueReply();
                               break;
        case "attach":         attachDialog.open();             break;
        case "detach":         win.clearAttachments();          break;
        case "refresh-models": Ollama.refreshModels();          break;
        case "unload":         Backend.unloadModels();          break;
        case "server":         if (!Backend.busy) {
                                   if (Backend.serverUp) Backend.stopServer();
                                   else Backend.startServer();
                               }
                               break;
        case "edit-prompt":    win.openPromptEditor();          break;
        // The Edit menu, through the SAME code the transcript's right-click
        // menu runs (win.textMenu) — one implementation of copy, two ways in,
        // so a reply is copied as MARKDOWN from either.
        case "copy":           win.runTextRow(0);               break;
        case "copy-message":   win.runTextRow(1);               break;
        case "select-all":     win.runTextRow(3);               break;
        }
    }

    // How many tool calls this conversation has made, and how many durable
    // memories the model is carrying [his, 2026-08-23]. Both are STANDING FACTS
    // about the chat on screen rather than about the turn in flight, which is
    // why they belong in the status bar rather than in a bubble — and, in the
    // face that has no status bar, in the stats row. `chatRev` is the dependency: ListModel rows settle without
    // notifying, so every writer bumps it (see `accrueThink`).
    readonly property int toolCallCount: {
        win.chatRev;
        var n = 0;
        for (var i = 0; i < chatLog.count; i++)
            n += chatLog.get(i).toolCount || 0;
        return n;
    }

    // ---- the KDE status bar ------------------------------------------------
    // Dolphin's shape: what is HAPPENING on the left, the standing fact on the
    // right. Under Hyprland nothing reads these — the same two readouts are
    // drawn in the window (`serverNoteText`, and the server row itself).
    readonly property string statusLine: {
        if (win.serverNote !== "") return win.serverNote;
        if (win.status !== "") return win.status;
        if (Ollama.busy) return "generating…";
        // Blank read as STUCK: he pressed stop, "generating…" went away and
        // the left half said nothing at all, which is what a wedged window
        // also looks like [his, 2026-08-23]. So the resting state is named.
        // Only when the daemon is actually there — with it down the right half
        // already says so, and "idle" beside "server down" would be a lie
        // about a server that is not running at all.
        return Backend.serverUp ? "idle" : "";
    }
    // No honest fraction: a reply has no known length. The line says it instead.
    readonly property real statusProgress: -1
    readonly property string statusRight: {
        // A running job is the standing fact that outranks the daemon's state:
        // it is the thing the machine is doing FOR HIM, it survives this window,
        // and the tray below may be scrolled past (docs/DESIGN.md §10).
        var jobs = Jobs.runningCount > 0
                 ? (Jobs.runningCount === 1 ? "1 job · " : Jobs.runningCount + " jobs · ")
                 : "";
        var counts = (win.toolCallCount > 0
                      ? win.toolCallCount + (win.toolCallCount === 1
                                             ? " tool call · " : " tool calls · ")
                      : "")
                   + (Ollama.memoryCount > 0
                      ? Ollama.memoryCount + " mem · " : "");
        // "server", never "ollama" [his, 2026-08-23]. What he is looking at is
        // this window's model server; which daemon happens to be behind it is
        // an implementation detail, and the name of one is noise in a status
        // bar (docs/agents/his-voice.md — the fact, not the plumbing).
        if (!Backend.serverUp) return jobs + counts + "server down";
        // Up with nothing loaded used to read "server idle" — a noun and a
        // state that both belong to the LEFT half, which now says "idle"
        // itself. This half is the standing fact: the daemon is running, and
        // what it is holding when it holds something.
        return jobs + counts + (Backend.loadedModels.length > 0
               ? "server · " + Backend.loadedModels.join(", ") : "server running");
    }
    // The taskbar entry says which conversation this is (kdeshell.bind_title).
    readonly property string windowTitle:
        win.sessionTitle !== "" ? "chatter — " + win.sessionTitle : "chatter"

    // Carry the last answer on. Two cases, one control: an answer that stopped
    // SHORT (the length ceiling, or he pressed stop) is resumed mid-sentence,
    // and a FINISHED answer is extended — "continue" is offered on any reply,
    // not only a truncated one [his, 2026-08-23]. Either way the continuation
    // streams into the SAME row, so it ends up one whole answer rather than two
    // bubbles that have to be read together [his, 2026-08-22]. Only ever the
    // last row: continuing one further up would write into the middle of the
    // conversation.
    function continueReply(forced) {
        var i = chatLog.count - 1;
        if (i < 0 || win.model === "") return;
        var row = chatLog.get(i);
        if (row.isUser || row.streaming || row.isError) return;
        var mode = forced ? forced : (row.cutOff ? "resume" : "extend");
        // An extension (and an auto-`proceed`) is its own paragraph; a resume
        // picks the sentence back up where it broke, so nothing may come
        // between the two halves.
        if (mode !== "resume" && row.body.trim() !== "")
            chatLog.setProperty(i, "body", row.body + "\n\n");
        var history = [];
        for (var k = 0; k < i; k++) {
            var h = chatLog.get(k);
            if (h.isError || h.body.trim() === "")
                continue;
            history.push({ role: h.isUser ? "user" : "assistant",
                           content: win.stampedBody(h) });
        }
        chatLog.setProperty(i, "cutOff", false);
        chatLog.setProperty(i, "streaming", true);
        win.chatRev++;
        win.activeIndex = i;
        Ollama.continueReply(win.model, JSON.stringify(history), row.body, mode);
    }

    // CARRY THE TURN ON BY ITSELF. A model that announces its next step instead
    // of taking it ("I'd like to proceed with…", "Shall I?") is the whole reason
    // he was pressing `continue` over and over [his, 2026-08-23]. So the app
    // presses it for him, at most AUTO_CONTINUE_MAX times per prompt, and says
    // in the status line that it did (docs/DESIGN.md §10 — nothing happens on
    // his behalf in silence). Pressing stop ends it: the count is not reset
    // until his next prompt, and a stopped row is `cutOff`, not unfinished.
    property int autoContinues: 0
    function autoContinue() {
        var i = chatLog.count - 1;
        if (i < 0 || Ollama.busy) return;
        var row = chatLog.get(i);
        if (row.isUser || row.isError || row.cutOff) return;
        if (win.autoContinues >= Ollama.autoContinueMax) {
            if (Ollama.looksUnfinished(row.body))
                win.status = "it stopped short again — press continue";
            return;
        }
        if (!Ollama.looksUnfinished(row.body)) return;
        win.autoContinues++;
        win.status = "carrying on by itself (" + win.autoContinues + "/"
                     + Ollama.autoContinueMax + ")";
        win.continueReply("proceed");
    }

    // The reasoning clock. It accrues while the model is REASONING or WAITING ON
    // A TOOL [his, 2026-08-22 — "thinking time should include waiting for
    // toolcalls and such"], and pauses while the answer itself streams: a turn
    // that thought, searched, thought again and then wrote reports the sum of
    // the three, not the wall clock of the whole turn. `thinkStart` is the open
    // interval, `thinkMs` the total closed so far, and only `thinkMs` is saved —
    // so a reloaded session still says how long each answer was worked on
    // (§10.6 — a finished block reports what actually happened).
    //
    // Call this after ANY change to the flags it reads; it is idempotent.
    function accrueThink(i) {
        if (i < 0 || i >= chatLog.count) return;
        var r = chatLog.get(i);
        var on = r.streaming && (r.thinkingActive || r.awaiting);
        if (on && r.thinkStart === 0)
            chatLog.setProperty(i, "thinkStart", Date.now());
        else if (!on && r.thinkStart > 0)
            win.stopThinkClock(i);
    }

    // Close the open interval, whatever the flags say — the turn is over.
    function stopThinkClock(i) {
        if (i < 0 || i >= chatLog.count) return;
        var r = chatLog.get(i);
        if (r.thinkStart > 0) {
            chatLog.setProperty(i, "thinkMs", r.thinkMs + (Date.now() - r.thinkStart));
            chatLog.setProperty(i, "thinkStart", 0);
        }
    }

    // "240", "1.2k" — a count, shortened once it stops being readable at a
    // glance [his, 2026-08-22]. One decimal, and no "1.0k" (that is just 1k).
    function fmtCount(n) {
        if (n < 1000) return "" + n;
        var k = n / 1000;
        var one = Math.round(k * 10) / 10;
        return (one === Math.floor(one) ? one : one.toFixed(1)) + "k";
    }

    // The last line a running program printed — what the collapsed files
    // disclosure previews. Split on \r as well as \n: a download or a build
    // redraws ONE line with carriage returns, so splitting on newlines alone
    // hands back the whole progress bar's history as a single huge line.
    function lastLine(s) {
        if (!s) return "";
        var parts = s.split(/[\r\n]+/);
        for (var i = parts.length - 1; i >= 0; i--) {
            var t = parts[i].trim();
            if (t !== "") return t;
        }
        return "";
    }

    // "12s", "1m 30s" — the reasoning duration, in the shortest honest form
    // (docs/DESIGN.md §7.2: the fact and its number, nothing else).
    function fmtDur(ms) {
        if (ms <= 0) return "";
        var sec = Math.round(ms / 1000);
        if (sec < 60) return sec + "s";
        var m = Math.floor(sec / 60);
        var r = sec % 60;
        return m + "m " + (r < 10 ? "0" : "") + r + "s";
    }

    // Stop an in-flight reply and settle the row it was writing into: cancel()
    // fires no replyDone/replyError, so nothing else would (§10.6 — a stopped
    // stream must not still read as running).
    function stopReply() {
        // Stop is stop: it also spends the auto-continue budget, so a turn he
        // interrupted is never carried on for him.
        win.autoContinues = Ollama.autoContinueMax;
        // And it drops whatever the turn was last saying about itself
        // ("carrying on by itself…", "it stopped short again…"): the turn is
        // over, so that line is no longer true, and left standing it is the
        // other half of the status bar looking stuck.
        win.status = "";
        Ollama.cancel();
        if (win.activeIndex >= 0) {
            win.stopThinkClock(win.activeIndex);
            // A stopped answer is a cut-off answer: offer the way on.
            if (chatLog.get(win.activeIndex).body !== "")
                chatLog.setProperty(win.activeIndex, "cutOff", true);
            chatLog.setProperty(win.activeIndex, "streaming", false);
            chatLog.setProperty(win.activeIndex, "thinkingActive", false);
            chatLog.setProperty(win.activeIndex, "awaiting", false);
            chatLog.setProperty(win.activeIndex, "searching", false);
            chatLog.setProperty(win.activeIndex, "filesActive", false);
            chatLog.setProperty(win.activeIndex, "imagesActive", false);
            chatLog.setProperty(win.activeIndex, "videosActive", false);
            chatLog.setProperty(win.activeIndex, "execRunning", false);
            chatLog.setProperty(win.activeIndex, "genRunning", false);
            win.chatRev++;
            win.saveCurrent();   // keep the partial turn in the session
        }
    }

    // Delete the conversation on screen, and leave a fresh one in its place —
    // the store row goes, so the window must not go on showing it.
    function deleteCurrentSession() {
        if (win.sessionId === "")
            return;
        var doomed = win.sessionId;
        Ollama.cancel();
        chatLog.clear();
        win.activeIndex = -1;
        win.sessionId = "";
        win.sessionTitle = "";
        win.status = "";
        Sessions.remove(doomed);
    }

    // Attaching by name, for the face that has a menu to ask from. The drop
    // target below is the other half and stays the way in under Hyprland.
    FileDialog {
        id: attachDialog
        title: "Attach files"
        fileMode: FileDialog.OpenFiles
        onAccepted: {
            for (var i = 0; i < selectedFiles.length; i++)
                win.addAttachmentUrl(selectedFiles[i]);
        }
    }

    // ---------------------------------------------------------------- top row
    Item {
        id: top
        anchors { top: parent.top; left: parent.left; right: parent.right
                  leftMargin: 10; rightMargin: 10
                  topMargin: win.plasma ? 0 : 10 }
        // Under Plasma the model is picked from a real combo on the toolbar and
        // this row stands down — kept in the tree at zero height so the
        // dropdown anchored to it still resolves.
        visible: !win.plasma
        height: win.plasma ? 0 : 28

        PixelText {
            id: modelLabel
            anchors { right: picker.left; rightMargin: 10
                      verticalCenter: parent.verticalCenter }
            text: "model"
            color: Theme.textDim
        }

        // The selector: a boxed control showing the current model, which opens
        // an inline list of the daemon's models under itself (docs/DESIGN.md
        // §7.2 — no combo boxes on this desktop).
        //
        // It HUGS the window's right edge with its label beside it [his,
        // 2026-08-22], rather than stretching the row: the width is the model
        // name's own laid-out width plus the caret, capped at 60% of the row so
        // a long name elides instead of pushing the label off the left.
        Rectangle {
            id: picker
            anchors { right: parent.right
                      verticalCenter: parent.verticalCenter }
            width: Math.min(Math.max(120, top.width * 0.6),
                            pickerText.implicitWidth + caret.width + 24)
            height: 24
            color: pickerMouse.containsMouse ? Theme.highlight : Theme.bgAlt
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border

            property bool open: false

            PixelText {
                id: pickerText
                anchors { left: parent.left; leftMargin: 6
                          right: caret.left; rightMargin: 6
                          verticalCenter: parent.verticalCenter }
                elide: Text.ElideRight
                text: win.model !== "" ? win.model
                                       : (Ollama.models.length > 0 ? "pick a model"
                                                                   : "no models found")
                color: win.model !== "" ? Theme.text : Theme.textDim
            }
            PixelText {
                id: caret
                anchors { right: parent.right; rightMargin: 6
                          verticalCenter: parent.verticalCenter }
                text: picker.open ? "^" : "v"
                color: Theme.textDim
            }

            MouseArea {
                id: pickerMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: picker.open = !picker.open
            }
        }
    }

    // ---------------------------------------------------------- session row
    // The named-conversation control: a picker showing the current session,
    // opening a list of every saved session under it (docs/DESIGN.md §7.2 — the
    // same boxed selector as the model picker, no combo boxes), and a "+ new"
    // that starts a fresh conversation. The whole conversation is always a
    // session and persists; switching loads that transcript back into the log.
    Item {
        id: sessionRow
        anchors { top: top.bottom; topMargin: win.plasma ? 0 : 8
                  left: parent.left; right: parent.right
                  leftMargin: 10; rightMargin: 10 }
        // Under Plasma: the File menu's session rows and the toolbar's combo.
        visible: !win.plasma
        height: win.plasma ? 0 : 24

        PixelText {
            id: sessionLabel
            anchors { right: sessionPicker.left; rightMargin: 10
                      verticalCenter: parent.verticalCenter }
            text: "session"
            color: Theme.textDim
        }

        // "+ new" — starts a fresh session (the current one is already saved).
        Rectangle {
            id: newBtn
            anchors { right: parent.right; verticalCenter: parent.verticalCenter }
            width: 52
            height: 24
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border
            color: newMouse.containsMouse ? Theme.highlight : Theme.bg
            PixelText {
                anchors.centerIn: parent
                text: "+ new"
                color: Theme.accent
            }
            MouseArea {
                id: newMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: win.newSession()
            }
        }

        // Same as the model picker: hugs the right, beside "+ new".
        Rectangle {
            id: sessionPicker
            anchors { right: newBtn.left; rightMargin: 10
                      verticalCenter: parent.verticalCenter }
            width: Math.min(Math.max(120, sessionRow.width * 0.6),
                            sessionText.implicitWidth + sessionCaret.width + 24)
            height: 24
            color: sessionMouse.containsMouse ? Theme.highlight : Theme.bgAlt
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border

            property bool open: false

            PixelText {
                id: sessionText
                anchors { left: parent.left; leftMargin: 6
                          right: sessionCaret.left; rightMargin: 6
                          verticalCenter: parent.verticalCenter }
                elide: Text.ElideRight
                text: win.sessionTitle !== "" ? win.sessionTitle : "new session"
                color: win.sessionTitle !== "" ? Theme.text : Theme.textDim
            }
            PixelText {
                id: sessionCaret
                anchors { right: parent.right; rightMargin: 6
                          verticalCenter: parent.verticalCenter }
                text: sessionPicker.open ? "^" : "v"
                color: Theme.textDim
            }
            MouseArea {
                id: sessionMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: { if (!sessionPicker.open) Sessions.refresh();
                             sessionPicker.open = !sessionPicker.open; }
            }
        }
    }

    // ----------------------------------------------------------- prompt row
    // The base system prompt: a boxed picker (docs/DESIGN.md §7.2, same as the
    // model/session selectors — no combo boxes) showing the active base, opening
    // a list of the built-in presets plus "custom…". Choosing a preset applies
    // it at once; "custom…" opens an editor for his own text. The memory block
    // and recall/save guidance are injected regardless of which base is active
    // (main.py `_system_prompt`); only this leading text swaps.
    Item {
        id: promptRow
        anchors { top: sessionRow.bottom; topMargin: win.plasma ? 0 : 8
                  left: parent.left; right: parent.right
                  leftMargin: 10; rightMargin: 10 }
        // Under Plasma: the Settings menu's "Base Prompt: …" radio set.
        visible: !win.plasma
        height: win.plasma ? 0 : 24

        // The label of the active base: the chosen preset's label, or "custom".
        function activeLabel() {
            if (Ollama.promptChoice === "custom")
                return "custom";
            var ps = Ollama.promptPresets;
            for (var i = 0; i < ps.length; i++)
                if (ps[i].id === Ollama.promptChoice)
                    return ps[i].label;
            return ps.length > 0 ? ps[0].label : "default";
        }

        PixelText {
            id: promptLabel
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
            text: "prompt"
            color: Theme.textDim
        }

        // "edit" — open the custom-text editor (writing/selecting custom text).
        Rectangle {
            id: editPromptBtn
            anchors { right: parent.right; verticalCenter: parent.verticalCenter }
            width: 52
            height: 24
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border
            color: editPromptMouse.containsMouse ? Theme.highlight : Theme.bg
            PixelText {
                anchors.centerIn: parent
                text: "edit"
                color: Theme.accent
            }
            MouseArea {
                id: editPromptMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: win.openPromptEditor()
            }
        }

        Rectangle {
            id: promptPicker
            anchors { left: promptLabel.right; leftMargin: 10
                      right: editPromptBtn.left; rightMargin: 10
                      verticalCenter: parent.verticalCenter }
            height: 24
            color: promptMouse.containsMouse ? Theme.highlight : Theme.bgAlt
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border

            property bool open: false

            PixelText {
                anchors { left: parent.left; leftMargin: 6
                          right: promptCaret.left; rightMargin: 6
                          verticalCenter: parent.verticalCenter }
                elide: Text.ElideRight
                text: promptRow.activeLabel()
                color: Theme.text
            }
            PixelText {
                id: promptCaret
                anchors { right: parent.right; rightMargin: 6
                          verticalCenter: parent.verticalCenter }
                text: promptPicker.open ? "^" : "v"
                color: Theme.textDim
            }
            MouseArea {
                id: promptMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: promptPicker.open = !promptPicker.open
            }
        }
    }

    // -------------------------------------------------- server / backend row
    // Observed state on the left (up/down + the loaded model, polled from
    // /api/ps, docs/DESIGN.md §10.6 — never claimed from a click), the two
    // controls on the right: unload the loaded model, and start/stop the daemon.
    Item {
        id: serverRow
        anchors { top: promptRow.bottom; topMargin: win.plasma ? 0 : 8
                  left: parent.left; right: parent.right
                  leftMargin: 10; rightMargin: 10 }
        // Under Plasma: observed state on the status bar's right, the two
        // controls in the Tools menu.
        visible: !win.plasma
        height: win.plasma ? 0 : 22

        PixelText {
            id: serverLabel
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
            text: "server"
            color: Theme.textDim
        }
        PixelText {
            anchors { left: serverLabel.right; leftMargin: 10
                      right: unloadBtn.left; rightMargin: 10
                      verticalCenter: parent.verticalCenter }
            elide: Text.ElideRight
            text: Backend.serverUp
                  ? (Backend.loadedModels.length > 0
                     ? "up · " + Backend.loadedModels.join(", ")
                     : "up · idle")
                  : "down"
            color: Backend.serverUp
                   ? (Backend.loadedModels.length > 0 ? Theme.ok : Theme.textDim)
                   : Theme.crit
        }

        // Unload — enabled only when a model is actually loaded (§10.2: a
        // control with no reading is dimmed and refuses, not silently inert).
        Rectangle {
            id: unloadBtn
            anchors { right: powerBtn.left; rightMargin: 8
                      verticalCenter: parent.verticalCenter }
            width: 64
            height: 22
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border
            readonly property bool armed: Backend.loadedModels.length > 0
            color: unloadMouse.containsMouse && armed ? Theme.highlight : Theme.bg
            PixelText {
                anchors.centerIn: parent
                text: "unload"
                color: unloadBtn.armed ? Theme.accent : Theme.dim
            }
            MouseArea {
                id: unloadMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: unloadBtn.armed ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: if (unloadBtn.armed) Backend.unloadModels()
            }
        }

        // Start / stop — reflects the OBSERVED server state; disabled while a
        // start/stop is in flight (the askpass dialog may be up).
        Rectangle {
            id: powerBtn
            anchors { right: parent.right; verticalCenter: parent.verticalCenter }
            width: 84
            height: 22
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border
            color: powerMouse.containsMouse && !Backend.busy ? Theme.highlight : Theme.bg
            PixelText {
                anchors.centerIn: parent
                text: Backend.busy ? "…"
                      : (Backend.serverUp ? "stop server" : "start server")
                color: Backend.busy ? Theme.textDim
                       : (Backend.serverUp ? Theme.warn : Theme.accent)
            }
            MouseArea {
                id: powerMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Backend.busy ? Qt.ArrowCursor : Qt.PointingHandCursor
                onClicked: {
                    if (Backend.busy) return;
                    if (Backend.serverUp) Backend.stopServer();
                    else Backend.startServer();
                }
            }
        }
    }

    // The last server-action result, drawn right under its controls so it is
    // seen wherever the reply area happens to be (docs/DESIGN.md §10 — a failed
    // or in-flight stop must be visible, not assumed). Collapsed until an action
    // has spoken; "…" while one is in flight (textDim), crit on failure.
    PixelText {
        id: serverNoteText
        anchors { top: serverRow.bottom; left: parent.left; right: parent.right
                  leftMargin: 10; rightMargin: 10
                  topMargin: (!win.plasma && win.serverNote !== "") ? 4 : 0 }
        height: (!win.plasma && win.serverNote !== "") ? Theme.lineHeight : 0
        // Under Plasma this is the status bar's left-hand message (statusLine).
        visible: height > 0
        clip: true
        elide: Text.ElideRight
        text: win.serverNote
        color: win.serverNote.indexOf("failed") >= 0 ? Theme.crit
               : (Backend.busy ? Theme.textDim : Theme.ok)
    }

    // Model stats: the selected model's context ceiling and the last/live
    // generation rate, a subordinated readout (docs/DESIGN.md §9 — a stat line,
    // §9.1 — one step dim). Collapses to nothing until at least one stat is
    // known. `ctx` is read from ollama's /api/show (the model's own trained
    // window); `tok/s` is the estimate while a reply streams, exact once done.
    Row {
        id: statsRow
        anchors { top: serverNoteText.bottom; left: parent.left; right: parent.right
                  leftMargin: 10; rightMargin: 10
                  topMargin: visible ? (win.plasma ? 8 : 4) : 0 }
        spacing: 10
        readonly property bool hasCtx: Ollama.contextMax > 0
        readonly property bool hasTps: Ollama.tokensPerSec > 0
        readonly property bool hasFill: hasCtx && Ollama.contextUsed > 0
        readonly property real fillFrac: hasFill
            ? Math.min(1, Ollama.contextUsed / Ollama.contextMax) : 0
        visible: hasCtx || hasTps
                 || (!win.plasma && (win.toolCallCount > 0 || Ollama.memoryCount > 0))
        height: visible ? Theme.lineHeight : 0

        // Compact token formatter: 8192 → "8K", 8000 → "7.8K", 512 → "512".
        function fmtTok(n) {
            if (n >= 1000)
                return (n / 1024).toFixed(n % 1024 === 0 ? 0 : 1) + "K";
            return "" + n;
        }

        // "ctx used/window" (or just the window before a turn has run). The
        // window is what he ACTUALLY has — ollama's own number once the model
        // is loaded, the computed fit before that — never the model's trained
        // ceiling. That ceiling was drawn beside it as "of 256K" for one
        // afternoon on 2026-08-23 and he had it out again the same day: the
        // second number is already the ceiling that matters, and a third one
        // reads as a repeat.
        PixelText {
            visible: statsRow.hasCtx
            anchors.verticalCenter: parent.verticalCenter
            text: "ctx " + (statsRow.hasFill
                            ? statsRow.fmtTok(Ollama.contextUsed) + "/"
                              + statsRow.fmtTok(Ollama.contextMax)
                            : statsRow.fmtTok(Ollama.contextMax) + " tok")
            color: Theme.textDim
        }

        // The fill bar (`Meter.qml`): a track with a proportional fill,
        // animated (docs/DESIGN.md §9 meter, §4 corners, §6 motion). Warns as
        // it approaches full.
        //
        // NO PLASMA TWIN, deliberately — the one control here that keeps its
        // own drawing in a KDE window. A `ProgressBar` from the style paints
        // NOTHING inside our QQuickWidget (measured 2026-08-22: blank in the
        // app and blank in a standalone qqc2-desktop-style harness, while a
        // Button in the same harness drew fine), and a KStyle progress bar is a
        // ~20px control in a 16px text row besides. This is a data readout in
        // the app's own content, like the picture frames in a reply — not
        // chrome pretending to be a widget.
        Meter {
            visible: statsRow.hasFill
            anchors.verticalCenter: parent.verticalCenter
            frac: statsRow.fillFrac
        }
        // The percentage, beside the bar.
        PixelText {
            visible: statsRow.hasFill
            anchors.verticalCenter: parent.verticalCenter
            text: Math.round(statsRow.fillFrac * 100) + "%"
            color: Theme.textDim
        }

        PixelText {
            visible: statsRow.hasTps
            anchors.verticalCenter: parent.verticalCenter
            text: Ollama.tokensPerSec.toFixed(1) + " tok/s"
            color: Theme.textDim
        }

        // The two counts, ONLY in the session that has no status bar to put
        // them in (§7.6 — one source, two roofs). Under Plasma they are the
        // status bar's standing facts and belong nowhere else: drawn here too
        // they said the same thing twice, once in the readout that is supposed
        // to be about the context window [his, 2026-08-23]. Each appears only
        // once it is non-zero: a fresh chat says nothing about nothing (§5.2).
        PixelText {
            visible: !win.plasma && win.toolCallCount > 0
            anchors.verticalCenter: parent.verticalCenter
            text: win.toolCallCount + (win.toolCallCount === 1
                                       ? " tool call" : " tool calls")
            color: Theme.textDim
        }

        PixelText {
            visible: !win.plasma && Ollama.memoryCount > 0
            anchors.verticalCenter: parent.verticalCenter
            text: Ollama.memoryCount + " mem"
            color: Theme.textDim
        }
    }

    // Capability chips: the selected model's native capabilities (vision, tool
    // use, thinking, …), read live off ollama's /api/show, drawn as small
    // NON-clickable indicator chips on the right of the stats area, opposite the
    // context bar (docs/DESIGN.md §3.2 — a subordinated indicator, §2140 chip
    // spec: bgAlt + 1px border + radius 3). Indicators only, no action. They
    // reflect the actual selected model and update when it changes.
    Row {
        id: capsRow
        visible: Ollama.capabilities.length > 0
        anchors { right: parent.right; rightMargin: 10
                  verticalCenter: statsRow.verticalCenter }
        spacing: 4

        // A friendlier label for the capabilities ollama names tersely; an
        // unknown capability falls through to its raw name rather than vanishing.
        function capLabel(c) {
            switch (c) {
            case "vision":    return "vision";
            case "tools":     return "tools";
            case "thinking":  return "thinking";
            case "audio":     return "audio";
            case "insert":    return "insert";
            case "embedding": return "embed";
            default:          return c;
            }
        }

        Repeater {
            model: Ollama.capabilities
            // CapChip.qml, and the KStyle's own frame under Plasma.
            delegate: CapChip {
                required property string modelData
                label: capsRow.capLabel(modelData)
            }
        }
    }

    // The dropdown floats over the reply area, overlaying the picker exactly.
    // It anchors to `top` (a sibling) and takes the picker's width rather than
    // anchoring to `picker` itself — the picker is `top`'s child, a nephew of
    // this dropdown, and QML silently drops an anchor to a non-sibling (the
    // dropdown then had width 0 and never showed). picker.right == top.right, so
    // right:top.right + width:picker.width lands it on the same span.
    Rectangle {
        id: dropdown
        visible: picker.open && Ollama.models.length > 0
        anchors { top: top.bottom; topMargin: -6; right: top.right }
        width: picker.width
        height: Math.min(Ollama.models.length * 22 + 2, 240)
        z: 50
        color: Theme.bgAlt
        radius: Theme.rounding
        border.width: Theme.ctrlBorder
        border.color: Theme.border

        KineticListView {
            id: modelList
            anchors { fill: parent; margins: 1 }
            clip: true
            model: Ollama.models
            delegate: Rectangle {
                width: modelList.width
                height: 22
                color: rowMouse.containsMouse ? Theme.highlight : "transparent"
                // A 1px rule where the agent-suggested group ends and the rest
                // begins (docs/DESIGN.md §7.2 — the menu separator). Drawn at the
                // top of the first non-suggested row.
                Rectangle {
                    visible: Ollama.suggestedCount > 0 && index === Ollama.suggestedCount
                    anchors { top: parent.top; left: parent.left; right: parent.right }
                    height: Theme.ctrlBorder
                    color: Theme.border
                }
                PixelText {
                    anchors { left: parent.left; leftMargin: 6
                              right: parent.right; rightMargin: 6
                              verticalCenter: parent.verticalCenter }
                    elide: Text.ElideRight
                    text: modelData
                    color: modelData === win.model ? Theme.accent : Theme.text
                }
                MouseArea {
                    id: rowMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: { win.model = modelData; Ollama.rememberModel(modelData);
                                 picker.open = false; }
                }
            }
            ScrollBar.vertical: VScroll {}
        }
    }

    // The session dropdown floats over the reply area under the session picker.
    // The session picker is a grandchild of `win` (it lives inside sessionRow),
    // so — like the model dropdown's note — an anchor to it would be dropped;
    // position it by arithmetic on the two items' live positions instead.
    Rectangle {
        id: sessionDropdown
        visible: sessionPicker.open
        x: sessionRow.x + sessionPicker.x
        y: sessionRow.y + sessionRow.height - 6
        width: sessionPicker.width
        height: Math.min(Math.max(Sessions.sessions.length, 1) * 22 + 2, 240)
        z: 50
        color: Theme.bgAlt
        radius: Theme.rounding
        border.width: Theme.ctrlBorder
        border.color: Theme.border

        // The empty-state line, when no session has been saved yet.
        PixelText {
            anchors { centerIn: parent }
            visible: Sessions.sessions.length === 0
            text: "no saved sessions"
            color: Theme.textDim
        }

        KineticListView {
            id: sessionList
            anchors { fill: parent; margins: 1 }
            clip: true
            visible: Sessions.sessions.length > 0
            model: Sessions.sessions
            delegate: Rectangle {
                width: sessionList.width
                height: 22
                color: sessRowMouse.containsMouse ? Theme.highlight : "transparent"
                PixelText {
                    anchors { left: parent.left; leftMargin: 6
                              right: sessCount.left; rightMargin: 6
                              verticalCenter: parent.verticalCenter }
                    elide: Text.ElideRight
                    text: modelData.title
                    color: modelData.id === win.sessionId ? Theme.accent : Theme.text
                }
                PixelText {
                    id: sessCount
                    anchors { right: parent.right; rightMargin: 6
                              verticalCenter: parent.verticalCenter }
                    text: modelData.turns
                    color: Theme.textDim
                }
                MouseArea {
                    id: sessRowMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: { Sessions.open(modelData.id); sessionPicker.open = false; }
                }
            }
            ScrollBar.vertical: VScroll {}
        }
    }

    // The prompt dropdown — the presets plus a "custom…" entry — floats under
    // the prompt picker (positioned by arithmetic, like the session dropdown,
    // since the picker is a grandchild of `win`).
    Rectangle {
        id: promptDropdown
        visible: promptPicker.open
        x: promptRow.x + promptPicker.x
        y: promptRow.y + promptRow.height - 6
        width: promptPicker.width
        // presets + the one "custom…" row, each carrying its `text` so the
        // preview pane below can show what a base actually instructs before
        // he picks it (the inbox ask: let him SEE each preset's text).
        readonly property var items: {
            var out = [];
            var ps = Ollama.promptPresets;
            for (var i = 0; i < ps.length; i++)
                out.push({ id: ps[i].id, label: ps[i].label, text: ps[i].text });
            out.push({ id: "custom", label: "custom…", text: Ollama.customPrompt });
            return out;
        }
        function textFor(id) {
            for (var i = 0; i < items.length; i++)
                if (items[i].id === id) return items[i].text;
            return "";
        }
        // Which row's text the preview shows: whatever he last hovered, reset to
        // the active base each time the dropdown opens.
        property string previewId: Ollama.promptChoice
        onVisibleChanged: if (visible) previewId = Ollama.promptChoice
        readonly property int listH: Math.min(items.length * 22 + 2, 240)
        readonly property int previewH: 108
        height: listH + previewH
        z: 50
        color: Theme.bgAlt
        radius: Theme.rounding
        border.width: Theme.ctrlBorder
        border.color: Theme.border

        KineticListView {
            id: promptList
            anchors { top: parent.top; left: parent.left; right: parent.right
                      margins: 1 }
            height: promptDropdown.listH - 1
            clip: true
            model: promptDropdown.items
            delegate: Rectangle {
                width: promptList.width
                height: 22
                color: promptRowMouse.containsMouse ? Theme.highlight : "transparent"
                // A 1px rule above the "custom…" row, separating his own text
                // from the built-in presets (docs/DESIGN.md §7.2).
                Rectangle {
                    visible: modelData.id === "custom"
                    anchors { top: parent.top; left: parent.left; right: parent.right }
                    height: Theme.ctrlBorder
                    color: Theme.border
                }
                PixelText {
                    anchors { left: parent.left; leftMargin: 6
                              right: parent.right; rightMargin: 6
                              verticalCenter: parent.verticalCenter }
                    elide: Text.ElideRight
                    text: modelData.label
                    color: modelData.id === Ollama.promptChoice ? Theme.accent : Theme.text
                }
                MouseArea {
                    id: promptRowMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onEntered: promptDropdown.previewId = modelData.id
                    onClicked: {
                        promptPicker.open = false;
                        if (modelData.id === "custom") win.openPromptEditor();
                        else Ollama.setPromptChoice(modelData.id);
                    }
                }
            }
            ScrollBar.vertical: VScroll {}
        }

        // The preview pane: the full text of the hovered (or active) base, so he
        // reads what a preset instructs before choosing it (docs/DESIGN.md §9.1
        // — a subordinated detail, one step dim; §10 — nothing hidden behind a
        // bare label). Scrolls when the text is long (a big custom prompt).
        Rectangle {
            id: promptPreview
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: promptDropdown.previewH
            color: "transparent"
            Rectangle {
                anchors { top: parent.top; left: parent.left; right: parent.right }
                height: Theme.ctrlBorder
                color: Theme.border
            }
            Flickable {
                id: promptPreviewFlick
                anchors { fill: parent; margins: 8 }
                clip: true
                contentHeight: promptPreviewText.height
                boundsBehavior: Flickable.StopAtBounds
                PixelText {
                    id: promptPreviewText
                    width: promptPreviewFlick.width
                    wrapMode: Text.Wrap
                    color: Theme.textDim
                    text: {
                        var t = promptDropdown.textFor(promptDropdown.previewId);
                        if (t !== "") return t;
                        if (promptDropdown.previewId === "custom")
                            return "(no custom prompt yet — the “edit” button writes one)";
                        return "(no persona — the model answers in its own voice)";
                    }
                }
                ScrollBar.vertical: VScroll {}
            }
        }
    }

    // The custom-prompt editor — a floating panel over the conversation, in
    // this session's own face: `PromptEditor.qml` under Hyprland, the KStyle's
    // Frame/TextArea/DialogButtonBox under Plasma (`+plasma/PromptEditor.qml`).
    // It reports what he chose and this file decides what that MEANS.
    PromptEditor {
        id: promptEditor
        anchors { left: parent.left; right: parent.right
                  leftMargin: 20; rightMargin: 20
                  // Under Hyprland it hangs off the base-prompt row it belongs
                  // to; that row is zero-height in a Plasma window (the base
                  // prompt is a menu there), so it takes the top of the view.
                  top: win.plasma ? replyBox.top : promptRow.bottom
                  topMargin: win.plasma ? 16 : 8 }
        height: implicitHeight
        z: 60
        // Persist the text AND select custom as the active base, so saving is
        // also applying it (docs/DESIGN.md §10 — the button does what it says).
        onSaved: (text) => {
            Ollama.setCustomPrompt(text);
            Ollama.setPromptChoice("custom");
        }
    }

    // A click anywhere else closes an open dropdown.
    MouseArea {
        anchors.fill: parent
        z: 40
        visible: picker.open || sessionPicker.open || promptPicker.open
        onClicked: { picker.open = false; sessionPicker.open = false;
                     promptPicker.open = false; }
    }

    // --------------------------------------------------------- the reply area
    // The surround is the session's own: our 1px bgAlt box under Hyprland, the
    // KStyle's Frame under Plasma (`+plasma/ViewFrame.qml`), which is what puts
    // the view and the compose box under it in the same hand. The inset is the
    // frame's (`pad`), so the content just fills what it is given.
    // The background jobs (`JobsTray.qml`, with its Plasma twin), ABOVE the
    // conversation [his, 2026-08-23: *"should go at the top of the chat window
    // rather than the bottom"*]. A job outlives the turn that started it, so it
    // belongs with the window's own standing facts — the stat line it sits
    // under — rather than in the gap between the reply and the compose box,
    // where it grew upward into what he was reading. Collapsed to zero height
    // when there are none, so nothing is reserved for nothing (§5.2).
    JobsTray {
        id: jobsTray
        objectName: "jobsTray"
        anchors { top: statsRow.bottom; topMargin: visible ? 8 : 0
                  left: parent.left; right: parent.right
                  leftMargin: 10; rightMargin: 10 }
    }

    ViewFrame {
        id: replyBox
        anchors { top: jobsTray.bottom
                  topMargin: jobsTray.visible ? 8 : 10
                  left: parent.left; right: parent.right
                  bottom: attachBar.top
                  leftMargin: 10; rightMargin: 10; bottomMargin: 10 }

        KineticFlickable {
            id: replyFlick
            objectName: "replyFlick"      // the harness reads the scroll off it
            anchors.fill: parent
            contentWidth: width
            contentHeight: replyCol.height
            clip: true

            Column {
                id: replyCol
                // Reserve the scrollbar's OWN width so no line runs under the
                // always-on bar (docs/DESIGN.md §9.2) — barW ranges 11-16px with
                // the desktop setting, so a literal gutter left text under an
                // opaque win31 bar. The bar overlays this reserved right strip.
                width: replyFlick.width - replyScroll.barW
                spacing: 12

                // The opening hint / model-list error, shown only on an empty log.
                PixelText {
                    width: parent.width
                    visible: chatLog.count === 0
                    wrapMode: Text.Wrap
                    text: win.status !== "" ? win.status
                                            : "ask the model something below."
                    color: win.status !== "" ? Theme.crit : Theme.textDim
                }

                // One row per turn — user prompts and model answers alike stay in
                // the log as it grows (docs/DESIGN.md §14).
                Repeater {
                    model: chatLog
                    delegate: Item {
                        id: turn
                        // Captured at creation, so a menu built on a click can
                        // name its own row without reaching for a context
                        // property that may not be there by then.
                        readonly property int rowIndex: index
                        // The reply's markdown split into render runs, and the
                        // fetched pictures it did NOT place inline — computed
                        // here so the bubble can lay a reply out as a FLOW of
                        // text + inline images (see replyFlow below) and still
                        // hug its text (natural). `Ollama.replyRuns` does the
                        // split; user/error rows carry no runs.
                        readonly property var replyData: (function () {
                            if (isUser) return { runs: [], leftovers: [] };
                            try { return JSON.parse(Ollama.replyRuns(body, images)); }
                            catch (e) { return { runs: [{ t: "text", md: body }], leftovers: [] }; }
                        })()
                        readonly property var replyRunsArr: replyData.runs || []
                        readonly property var leftoverImages: replyData.leftovers || []
                        readonly property var leftoverOks: (function () {
                            var out = [];
                            for (var i = 0; i < leftoverImages.length; i++)
                                if (leftoverImages[i] && leftoverImages[i].ok)
                                    out.push(leftoverImages[i]);
                            return out;
                        })()
                        // The widest laid-out line across the reply's TEXT runs,
                        // for the bubble's hug. Images and failures contribute
                        // nothing (a hidden run reports 0), so this is the old
                        // mdBody.contentWidth, spread over however many runs.
                        readonly property real replyTextMax: {
                            var m = 0;
                            for (var i = 0; i < replyRunsRepeater.count; i++) {
                                var it = replyRunsRepeater.itemAt(i);
                                if (it && it.runWidth > m) m = it.runWidth;
                            }
                            return m;
                        }
                        width: replyCol.width
                        height: rowStack.height
                        // A round that said nothing draws NOTHING and takes no
                        // slot — its bookkeeping is in the head's meta block, so
                        // there is nothing left on the row. `visible: false`,
                        // not height 0: an Item of height 0 still takes the
                        // column's 12px spacing, so six of them left a 72px hole.
                        visible: isUser || turn.isHead || turn.speaks

                        // Which TURN this row is in: the head is the first model
                        // row of the run after his prompt, and it is the row
                        // that draws the whole turn's meta block.
                        readonly property int head: win.turnHead(index)
                        readonly property bool isHead: head === index
                        readonly property var agg: win.turnAgg(turn.isHead ? index : -1)
                        // Did this row leave anything on screen of its own?
                        readonly property bool speaks:
                            isError || body !== "" || turn.hasMedia

                        // The disclosure's open/closed is VIEW state, per row, and
                        // it defaults CLOSED: reasoning is collapsed until he opens
                        // it (docs/DESIGN.md §9.1 — subordinated, never in his way).
                        property bool userSet: false
                        property bool userOpen: false
                        // Same, for the web-search sources disclosure below.
                        property bool srcUserSet: false
                        property bool srcUserOpen: false
                        // Same, for the file-tool activity disclosure.
                        property bool fileUserSet: false
                        property bool fileUserOpen: false
                        // Same, for the generic tool-activity disclosure.
                        property bool toolUserSet: false
                        property bool toolUserOpen: false
                        // Same, for the subagent disclosure.
                        property bool agentUserSet: false
                        property bool agentUserOpen: false

                        // ---- the bubble --------------------------------
                        // A turn is a BUBBLE, on the speaker's own side of the
                        // column: his prompts sit right in an accent-tinted
                        // slab, the model's answers left on `bgAlt`
                        // [his, 2026-08-22]. Both HUG their text — the width is
                        // the longest laid-out line, capped at `bubbleMax` —
                        // which is what makes a two-word answer read as a two-
                        // word answer instead of a full-width band.
                        //
                        // The corner is `Theme.rounding`, the desktop-wide
                        // radius (docs/DESIGN.md §4), not a shape invented here:
                        // at the shipped 0 these are square slabs, and one
                        // Settings slider rounds every corner on the desktop
                        // including these. No new colours either — the fills are
                        // alphas of `accent`/`crit` over the existing tokens,
                        // the same idiom the drop overlay already uses (§3).
                        readonly property real pad: 8
                        readonly property real bubbleMax:
                            Math.max(160, replyCol.width * 0.82)
                        readonly property real innerW: bubbleMax - 2 * pad
                        // A row carrying a picture takes the full cap: an image
                        // wraps to the bubble, and hugging a two-word caption
                        // would fold it into a column two words wide. The
                        // disclosures no longer count — they sit OUTSIDE the
                        // bubble now [his, 2026-08-22].
                        // MEDIA IS A PROPERTY OF THE ROW, not of an item's
                        // visibility. Read it off the model roles only — see
                        // the bubble's `visible` below, where reading a child's
                        // `visible` instead latched a picture off for good.
                        readonly property bool hasMedia:
                            !isUser && (images !== "[]" || imagesActive
                                        || videos !== "[]" || videosActive)
                        readonly property bool wide: hasMedia

                        Column {
                            id: rowStack
                            width: parent.width
                            spacing: 2

                            Column {
                                id: turnStack
                                width: parent.width
                                spacing: 2

                                // The date, once, on the first turn of a day that
                                // is not the previous turn's. A session held in one
                                // sitting never draws it.
                                Item {
                                    width: parent.width
                                    height: dayMark.visible ? dayMark.height + 6 : 0
                                    PixelText {
                                        id: dayMark
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        anchors.bottom: parent.bottom
                                        visible: win.opensNewDay(index)
                                        text: visible ? win.dayLabel(ts) : ""
                                        color: Theme.textDim
                                        opacity: 0.7
                                    }
                                }

                                // The speaker's name, OUTSIDE the bubble and on its
                                // side — a caption, not a line of the message
                                // (§9.1: subordinated, one step dim).
                                PixelText {
                                    id: whoText
                                    x: isUser ? turnStack.width - width : 0
                                    // Just the speaker, ONCE per turn. The caption
                                    // used to name the round from 2 on ("model ·
                                    // round 2"); the SPLIT is what he wanted, not a
                                    // label on it [his, 2026-08-22] — and the later
                                    // rounds of one turn repeat neither the name nor
                                    // anything else between their bubbles [his,
                                    // 2026-08-23].
                                    visible: isUser || turn.isHead
                                    text: who
                                    color: Theme.textDim
                                }

                                // ---- the turn's bookkeeping, ONCE, at the top of it
                                // Every disclosure of every round of this turn,
                                // aggregated into one block above the FIRST
                                // bubble [his, 2026-08-23]. The rounds' bubbles
                                // then run one after another with nothing
                                // between them but their timestamps; the
                                // counts, the clock and the live state are all
                                // still here, at the top, where he reads them.
                                Column {
                                    id: turnMeta
                                    width: parent.width
                                    spacing: 2
                                    visible: !isUser && turn.isHead

                                    // What re-evaluates the aggregate while the
                                    // reply is in flight: a ListModel notifies no
                                    // binding when setProperty writes a role, and
                                    // rebuilding it per token would redo the whole
                                    // turn for every visible row on every delta.
                                    // `chatRev` carries the settled state, so this
                                    // stops the moment the reply does.
                                    Timer {
                                        interval: 300
                                        running: turnMeta.visible && Ollama.busy
                                        repeat: true
                                        onTriggered: win.metaRev++
                                    }

                                    // Before the model has said ANYTHING — no answer, no
                                    // reasoning — the wait is a line of its own, outside
                                    // the bubble, with the same animated ellipsis every
                                    // other in-flight heading here carries [his,
                                    // 2026-08-22]. It used to be a static "…" inside an
                                    // otherwise empty bubble, which read as a message
                                    // rather than as a wait (§10 — the state is shown,
                                    // and it is honest about being a state).
                                    Item {
                                        id: waiting
                                        width: parent.width
                                        visible: turn.agg.loading
                                        height: visible ? Theme.lineHeight : 0

                                        property int dotPhase: 0
                                        Timer {
                                            interval: motion.ms(motion.slideMs)
                                            running: waiting.visible && !motion.reduceMotion
                                            repeat: true
                                            onTriggered: waiting.dotPhase = (waiting.dotPhase + 1) % 4
                                        }
                                        PixelText {
                                            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                                            text: "loading" + (motion.reduceMotion ? "…"
                                                  : "...".substring(0, waiting.dotPhase))
                                            color: Theme.text
                                        }
                                    }

                                    // The reasoning, a COLLAPSIBLE disclosure that starts
                                    // folded. Its heading reports progress: "thinking…"
                                    // (one step brighter) while the reasoning streams, and
                                    // settles to "thinking" (textDim) once the answer
                                    // starts. Subordinated per docs/DESIGN.md §9.1 —
                                    // indented, a `border` hairline at the indent, text one
                                    // step dim, never accent — revealed by §6.2's clipped
                                    // growth from under the toggle.
                                    Item {
                                        id: think
                                        width: parent.width
                                        // Shown whenever the clock ran at all: a turn
                                        // that only WAITED on tools reported nothing at
                                        // all before [his, 2026-08-22].
                                        // ...and NOT while the `loading` line above is
                                        // up. An empty bubble waiting on its first tool
                                        // satisfied both, so "loading…" and "waiting…"
                                        // stacked on top of each other [his,
                                        // 2026-08-22]. One state at a time: `loading`
                                        // owns a bubble with nothing in it yet, the
                                        // clock takes over once there is something.
                                        visible: !waiting.visible
                                                 && (hasBody || turn.agg.thinkMs > 0
                                                     || turn.agg.thinkStart > 0 || turn.agg.awaiting)
                                        height: visible ? thinkToggle.height + thinkReveal.height : 0

                                        readonly property bool hasBody: turn.agg.thinking !== ""
                                        readonly property bool expanded: hasBody && turn.userSet
                                                                         ? turn.userOpen : false

                                        // The live count for the heading, ticked half a
                                        // second at a time while the clock runs (a
                                        // binding on Date.now() would never re-evaluate).
                                        property int elapsed: 0
                                        Timer {
                                            interval: 500
                                            running: turn.agg.thinkStart > 0
                                            repeat: true
                                            triggeredOnStart: true
                                            onTriggered: think.elapsed = Date.now() - turn.agg.thinkStart
                                        }

                                        Item {
                                            id: thinkToggle
                                            width: parent.width
                                            height: Theme.lineHeight
                                            // The ellipsis cycles 0→1→2→3 dots while the
                                            // reasoning streams, so the heading reads as
                                            // alive even between token deltas. One roll
                                            // beat per dot (§6.2) — no fresh literal, and
                                            // reduceMotion collapses it to a static "…".
                                            property int dotPhase: 0
                                            readonly property string dots:
                                                motion.reduceMotion ? "…" : "...".substring(0, dotPhase)
                                            Timer {
                                                interval: motion.ms(motion.slideMs)
                                                running: (turn.agg.thinkingActive || turn.agg.awaiting)
                                                         && !motion.reduceMotion
                                                repeat: true
                                                onTriggered: thinkToggle.dotPhase = (thinkToggle.dotPhase + 1) % 4
                                            }
                                            Row {
                                                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                                                spacing: 6
                                                // No toggle when there is no reasoning to
                                                // unfold — a turn can spend its whole
                                                // clock waiting on tools (§10.2: never a
                                                // control that opens nothing).
                                                PixelText {
                                                    visible: think.hasBody
                                                    text: think.expanded ? "-" : "+"
                                                    color: Theme.textDim
                                                }
                                                // The reasoning-token count, named and
                                                // still, to the LEFT of the time [his,
                                                // 2026-08-22]: "240 tokens", "1.2k
                                                // tokens". It PERSISTS once counted, so a
                                                // COLLAPSED block still reports its size
                                                // after the answer starts — the heading is
                                                // all he sees when it is folded (§9.1
                                                // subordinated — one step dim, never
                                                // accent).
                                                PixelText {
                                                    visible: turn.agg.thinkTokens > 0
                                                    text: win.fmtCount(turn.agg.thinkTokens)
                                                          + (turn.agg.thinkTokens === 1 ? " token ·"
                                                                               : " tokens ·")
                                                    color: Theme.textDim
                                                }
                                                // The state, and the ellipsis rides it
                                                // because it is the part still running:
                                                // "waiting…" while a tool is out,
                                                // "thinking for 12s…" while it reasons,
                                                // and the TOTAL of both as "thought for
                                                // 12s" once the turn settles.
                                                PixelText {
                                                    text: {
                                                        if (turn.agg.awaiting)
                                                            return "waiting" + thinkToggle.dots;
                                                        var live = turn.agg.thinkMs + (turn.agg.thinkStart > 0
                                                                              ? think.elapsed : 0);
                                                        var d = win.fmtDur(turn.agg.thinkingActive ? live
                                                                                          : turn.agg.thinkMs);
                                                        if (turn.agg.thinkingActive)
                                                            return (d !== "" ? "thinking for " + d
                                                                             : "thinking")
                                                                   + thinkToggle.dots;
                                                        return d !== "" ? "thought for " + d
                                                                        : "thought";
                                                    }
                                                    color: (turn.agg.thinkingActive || turn.agg.awaiting) ? Theme.text
                                                                                        : Theme.textDim
                                                }
                                            }
                                            MouseArea {
                                                anchors.fill: parent
                                                enabled: think.hasBody
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: { turn.userOpen = !think.expanded; turn.userSet = true; }
                                            }
                                        }

                                        Item {
                                            id: thinkReveal
                                            anchors { top: thinkToggle.bottom; left: parent.left; right: parent.right }
                                            clip: true
                                            height: think.expanded ? thinkBody.height : 0
                                            Behavior on height {
                                                NumberAnimation { duration: motion.ms(motion.slideMs)
                                                                  easing.type: motion.slideEasing }
                                            }
                                            Rectangle {
                                                anchors { left: parent.left; leftMargin: 3
                                                          top: parent.top; bottom: parent.bottom }
                                                width: Theme.ctrlBorder
                                                color: Theme.border
                                            }
                                            PixelText {
                                                id: thinkBody
                                                anchors { top: parent.top; left: parent.left; right: parent.right
                                                          leftMargin: 12 }
                                                wrapMode: Text.Wrap
                                                text: turn.agg.thinking
                                                color: Theme.textDim
                                            }
                                        }
                                    }

                                    // The generic tool activity: every tool the model
                                    // called this round, named — the same subordinated,
                                    // folded-by-default disclosure (docs/DESIGN.md §9.1,
                                    // §10 — a tool call is shown, never silent), so a tool
                                    // with no richer block of its own still appears. The
                                    // heading reads "calling tools…" while the round is in
                                    // flight and settles to "tools · N"; the body is one
                                    // tool name per line (PixelText verbatim, dim).
                                    Item {
                                        id: toolAct
                                        width: parent.width
                                        visible: turn.agg.tools !== "" || turn.agg.toolsActive
                                        height: visible ? toolToggle.height + toolReveal.height : 0

                                        readonly property bool expanded: turn.toolUserSet ? turn.toolUserOpen
                                                                                          : false

                                        Item {
                                            id: toolToggle
                                            width: parent.width
                                            height: Theme.lineHeight
                                            property int dotPhase: 0
                                            readonly property string dots:
                                                motion.reduceMotion ? "…" : "...".substring(0, dotPhase)
                                            Timer {
                                                interval: motion.ms(motion.slideMs)
                                                running: turn.agg.toolsActive && !motion.reduceMotion
                                                repeat: true
                                                onTriggered: toolToggle.dotPhase = (toolToggle.dotPhase + 1) % 4
                                            }
                                            Row {
                                                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                                                spacing: 6
                                                PixelText { text: toolAct.expanded ? "-" : "+"; color: Theme.textDim }
                                                PixelText {
                                                    text: turn.agg.toolsActive ? "calling turn.agg.tools"
                                                                      : "tools · " + turn.agg.toolCount
                                                    color: turn.agg.toolsActive ? Theme.text : Theme.textDim
                                                }
                                                PixelText {
                                                    visible: turn.agg.toolsActive
                                                    text: toolToggle.dots
                                                    color: Theme.textDim
                                                }
                                            }
                                            MouseArea {
                                                anchors.fill: parent
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: { turn.toolUserOpen = !toolAct.expanded; turn.toolUserSet = true; }
                                            }
                                        }

                                        Item {
                                            id: toolReveal
                                            anchors { top: toolToggle.bottom; left: parent.left; right: parent.right }
                                            clip: true
                                            height: toolAct.expanded ? toolBody.height : 0
                                            Behavior on height {
                                                NumberAnimation { duration: motion.ms(motion.slideMs)
                                                                  easing.type: motion.slideEasing }
                                            }
                                            Rectangle {
                                                anchors { left: parent.left; leftMargin: 3
                                                          top: parent.top; bottom: parent.bottom }
                                                width: Theme.ctrlBorder
                                                color: Theme.border
                                            }
                                            PixelText {
                                                id: toolBody
                                                anchors { top: parent.top; left: parent.left; right: parent.right
                                                          leftMargin: 12 }
                                                wrapMode: Text.Wrap
                                                text: turn.agg.tools
                                                color: Theme.textDim
                                            }
                                        }
                                    }

                                    // The subagents this turn spawned, drawn as their own
                                    // subordinated disclosure (docs/DESIGN.md §9.1, §10).
                                    // While one works the heading is the live agent, its
                                    // round and the tool it just called — a spawn is the
                                    // longest wait in a turn and it used to be silent. It
                                    // settles to "agents · N" (or names the failure, §10),
                                    // and the body holds one block per agent: who, the
                                    // task, what it cost, and what it answered.
                                    Item {
                                        id: agentAct
                                        width: parent.width
                                        visible: turn.agg.agents !== "" || turn.agg.agentsActive
                                        height: visible ? agentToggle.height + agentReveal.height : 0

                                        readonly property bool expanded: turn.agentUserSet ? turn.agentUserOpen
                                                                                           : false

                                        Item {
                                            id: agentToggle
                                            width: parent.width
                                            height: Theme.lineHeight
                                            property int dotPhase: 0
                                            readonly property string dots:
                                                motion.reduceMotion ? "…" : "...".substring(0, dotPhase)
                                            Timer {
                                                interval: motion.ms(motion.slideMs)
                                                running: turn.agg.agentsActive && !motion.reduceMotion
                                                repeat: true
                                                onTriggered: agentToggle.dotPhase = (agentToggle.dotPhase + 1) % 4
                                            }
                                            Row {
                                                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                                                spacing: 6
                                                PixelText { text: agentAct.expanded ? "-" : "+"; color: Theme.textDim }
                                                PixelText {
                                                    text: turn.agg.agentsActive
                                                          ? (turn.agg.agentHead !== "" ? turn.agg.agentHead : "agent working")
                                                          : ((turn.agg.agentCount === 1 ? "agent · 1"
                                                                               : "agents · " + turn.agg.agentCount)
                                                             + (turn.agg.agentsBad ? " · failed" : ""))
                                                    color: turn.agg.agentsActive ? Theme.text
                                                                        : (turn.agg.agentsBad ? Theme.crit : Theme.textDim)
                                                }
                                                PixelText {
                                                    visible: turn.agg.agentsActive
                                                    text: agentToggle.dots
                                                    color: Theme.textDim
                                                }
                                            }
                                            MouseArea {
                                                anchors.fill: parent
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: { turn.agentUserOpen = !agentAct.expanded; turn.agentUserSet = true; }
                                            }
                                        }

                                        Item {
                                            id: agentReveal
                                            anchors { top: agentToggle.bottom; left: parent.left; right: parent.right }
                                            clip: true
                                            height: agentAct.expanded ? agentBody.height : 0
                                            Behavior on height {
                                                NumberAnimation { duration: motion.ms(motion.slideMs)
                                                                  easing.type: motion.slideEasing }
                                            }
                                            Rectangle {
                                                anchors { left: parent.left; leftMargin: 3
                                                          top: parent.top; bottom: parent.bottom }
                                                width: Theme.ctrlBorder
                                                color: Theme.border
                                            }
                                            PixelText {
                                                id: agentBody
                                                anchors { top: parent.top; left: parent.left; right: parent.right
                                                          leftMargin: 12 }
                                                wrapMode: Text.Wrap
                                                text: turn.agg.agents
                                                color: Theme.textDim
                                            }
                                        }
                                    }

                                    // The web-search sources: the same subordinated,
                                    // folded-by-default disclosure as the reasoning
                                    // (docs/DESIGN.md §9.1), showing which sources the
                                    // model searched. Heading reads "searching the web…"
                                    // (one step brighter) while a search is live and
                                    // settles to "web · N sources" once results land; the
                                    // body is Tavily's answer plus themed links, drawn
                                    // through MarkdownText.
                                    Item {
                                        id: src
                                        width: parent.width
                                        visible: turn.agg.sources !== "" || turn.agg.searching
                                        height: visible ? srcToggle.height + srcReveal.height : 0

                                        readonly property bool expanded: turn.srcUserSet ? turn.srcUserOpen
                                                                                         : false

                                        Item {
                                            id: srcToggle
                                            width: parent.width
                                            height: Theme.lineHeight
                                            property int dotPhase: 0
                                            readonly property string dots:
                                                motion.reduceMotion ? "…" : "...".substring(0, dotPhase)
                                            Timer {
                                                interval: motion.ms(motion.slideMs)
                                                running: turn.agg.searching && !motion.reduceMotion
                                                repeat: true
                                                onTriggered: srcToggle.dotPhase = (srcToggle.dotPhase + 1) % 4
                                            }
                                            Row {
                                                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                                                spacing: 6
                                                PixelText { text: src.expanded ? "-" : "+"; color: Theme.textDim }
                                                PixelText {
                                                    text: turn.agg.searching ? "searching the web"
                                                                    : "web · " + turn.agg.searchCount + (turn.agg.searchCount === 1 ? " source" : " turn.agg.sources")
                                                    color: turn.agg.searching ? Theme.text : Theme.textDim
                                                }
                                                PixelText {
                                                    visible: turn.agg.searching
                                                    text: srcToggle.dots
                                                    color: Theme.textDim
                                                }
                                            }
                                            MouseArea {
                                                anchors.fill: parent
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: { turn.srcUserOpen = !src.expanded; turn.srcUserSet = true; }
                                            }
                                        }

                                        Item {
                                            id: srcReveal
                                            anchors { top: srcToggle.bottom; left: parent.left; right: parent.right }
                                            clip: true
                                            height: src.expanded ? srcBody.height : 0
                                            Behavior on height {
                                                NumberAnimation { duration: motion.ms(motion.slideMs)
                                                                  easing.type: motion.slideEasing }
                                            }
                                            Rectangle {
                                                anchors { left: parent.left; leftMargin: 3
                                                          top: parent.top; bottom: parent.bottom }
                                                width: Theme.ctrlBorder
                                                color: Theme.border
                                            }
                                            MarkdownText {
                                                id: srcBody
                                                anchors { top: parent.top; left: parent.left; right: parent.right
                                                          leftMargin: 12 }
                                                text: turn.agg.sources
                                            }
                                        }
                                    }

                                    // The file-tool activity: the same subordinated,
                                    // folded-by-default disclosure (docs/DESIGN.md §9.1),
                                    // showing which files the model read or changed. The
                                    // heading reads "working with files…" while an op is in
                                    // flight and settles to "files · N" once done; the body
                                    // is one plain outcome line per op (paths, not markdown
                                    // — PixelText verbatim, the shared guard).
                                    Item {
                                        id: fileAct
                                        width: parent.width
                                        visible: turn.agg.files !== "" || turn.agg.filesActive
                                        height: visible ? fileToggle.height + fileReveal.height : 0

                                        // Closed by default, running program or not
                                        // [his, 2026-08-23]. It used to spring open on
                                        // its own while one ran — live output nobody
                                        // can see is not live output — but a build or
                                        // a download prints hundreds of lines and the
                                        // block became the flood it was meant to
                                        // contain. The heading previews the last line
                                        // instead (`execPeek`), which is the line a
                                        // progress bar is redrawing anyway. His own
                                        // click still wins, in both directions.
                                        readonly property bool expanded: turn.fileUserSet ? turn.fileUserOpen
                                                                                          : false

                                        Item {
                                            id: fileToggle
                                            width: parent.width
                                            // Two lines while a program is printing:
                                            // the heading, and the line it printed last
                                            // under it. A render adds its bar the same
                                            // way, below both.
                                            height: Theme.lineHeight
                                                    + (execPeek.visible ? Theme.lineHeight : 0)
                                                    + (genRow.visible ? Theme.lineHeight : 0)
                                            property int dotPhase: 0
                                            readonly property string dots:
                                                motion.reduceMotion ? "…" : "...".substring(0, dotPhase)
                                            Timer {
                                                interval: motion.ms(motion.slideMs)
                                                running: turn.agg.filesActive && !motion.reduceMotion
                                                repeat: true
                                                onTriggered: fileToggle.dotPhase = (fileToggle.dotPhase + 1) % 4
                                            }
                                            Row {
                                                id: fileHead
                                                anchors { left: parent.left; top: parent.top }
                                                height: Theme.lineHeight
                                                spacing: 6
                                                PixelText { text: fileAct.expanded ? "-" : "+"; color: Theme.textDim }
                                                PixelText {
                                                    text: turn.agg.filesActive ? "working with files"
                                                                      : "files · " + turn.agg.fileCount
                                                    color: turn.agg.filesActive ? Theme.text : Theme.textDim
                                                }
                                                PixelText {
                                                    visible: turn.agg.filesActive
                                                    text: fileToggle.dots
                                                    color: Theme.textDim
                                                }
                                            }
                                            // What the program printed LAST, UNDER the
                                            // heading, while the block is shut [his,
                                            // 2026-08-23]: the tool is usually a
                                            // download or a build, and the one line
                                            // that matters is the one it is redrawing
                                            // right now. Its own line rather than
                                            // trailing "working with files…" on the
                                            // same one — a path or a progress bar
                                            // beside a heading leaves neither room to
                                            // read. Elided rather than wrapped, so it
                                            // stays exactly one line however long the
                                            // program's is.
                                            //
                                            // Only while the program RUNS. A finished
                                            // console has nothing live to preview and
                                            // its last line lingering under the
                                            // heading reads as still going [his,
                                            // 2026-08-23]; the whole tail is in the
                                            // block for anyone who opens it. Gone too
                                            // the moment the block IS open, where it
                                            // is already drawn in full.
                                            Text {
                                                id: execPeek
                                                anchors { left: parent.left; leftMargin: 12
                                                          right: parent.right
                                                          top: fileHead.bottom }
                                                height: visible ? Theme.lineHeight : 0
                                                verticalAlignment: Text.AlignVCenter
                                                visible: !fileAct.expanded && turn.agg.execRunning
                                                         && win.lastLine(turn.agg.execTail) !== ""
                                                font: Theme.editorFont
                                                renderType: Text.NativeRendering
                                                textFormat: Text.PlainText
                                                elide: Text.ElideRight
                                                text: win.lastLine(turn.agg.execTail)
                                                color: Theme.text
                                            }
                                            // A RENDER'S PROGRESS, under the
                                            // heading and always visible —
                                            // open or shut, because the whole
                                            // point is that a minutes-long
                                            // wait does not look like a
                                            // stalled one [his, 2026-08-24].
                                            // The label says which part is
                                            // running; the bar is the same
                                            // Meter the context readout uses,
                                            // so there is one progress shape
                                            // in this window and not two.
                                            Row {
                                                id: genRow
                                                anchors { left: parent.left; leftMargin: 12
                                                          top: execPeek.visible ? execPeek.bottom
                                                                                : fileHead.bottom }
                                                height: visible ? Theme.lineHeight : 0
                                                spacing: 8
                                                visible: turn.agg.genRunning
                                                Meter {
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    width: 120
                                                    frac: turn.agg.genFrac
                                                }
                                                PixelText {
                                                    text: turn.agg.genLabel
                                                    color: Theme.textDim
                                                }
                                                PixelText {
                                                    text: Math.round(turn.agg.genFrac * 100) + "%"
                                                    color: Theme.textDim
                                                    opacity: 0.6
                                                }
                                            }
                                            MouseArea {
                                                anchors.fill: parent
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: { turn.fileUserOpen = !fileAct.expanded; turn.fileUserSet = true; }
                                            }
                                        }

                                        Item {
                                            id: fileReveal
                                            anchors { top: fileToggle.bottom; left: parent.left; right: parent.right }
                                            clip: true
                                            height: fileAct.expanded
                                                    ? fileBody.height + (execBody.visible
                                                       ? execBody.height + 2 : 0) : 0
                                            Behavior on height {
                                                NumberAnimation { duration: motion.ms(motion.slideMs)
                                                                  easing.type: motion.slideEasing }
                                            }
                                            Rectangle {
                                                anchors { left: parent.left; leftMargin: 3
                                                          top: parent.top; bottom: parent.bottom }
                                                width: Theme.ctrlBorder
                                                color: Theme.border
                                            }
                                            PixelText {
                                                id: fileBody
                                                anchors { top: parent.top; left: parent.left; right: parent.right
                                                          leftMargin: 12 }
                                                wrapMode: Text.Wrap
                                                text: turn.agg.files
                                                color: Theme.textDim
                                            }
                                            // What the program is printing, right now.
                                            // The editor font, because it is output and
                                            // not prose; one step dim, because it is
                                            // the machine talking (§9.1).
                                            Text {
                                                id: execBody
                                                anchors { top: fileBody.bottom; topMargin: execBody.visible ? 2 : 0
                                                          left: parent.left; right: parent.right
                                                          leftMargin: 12 }
                                                visible: turn.agg.execTail !== ""
                                                font: Theme.editorFont
                                                renderType: Text.NativeRendering
                                                textFormat: Text.PlainText
                                                wrapMode: Text.Wrap
                                                text: turn.agg.execTail
                                                color: turn.agg.execRunning ? Theme.text : Theme.textDim
                                            }
                                        }
                                    }
                                }

                                // The message itself, in a BUTTON frame
                                // (`Bubble.qml`, and the KStyle's own button under
                                // Plasma) [his, 2026-08-22].
                                Bubble {
                                    id: bubble
                                    // Nothing to box when the turn has no text yet —
                                    // the `loading…` line and the reasoning above
                                    // carry the wait, so an empty slab under them
                                    // would be a second, blank bubble (§10 — never a
                                    // control with no reading).
                                    // ...and a picture or a video, which is what a
                                    // round can carry with NO words at all —
                                    // `view_image` says nothing, it just looks.
                                    //
                                    // NEVER `imageCol.visible` here [his,
                                    // 2026-08-23: a graph the model made, and the
                                    // bubble that should have held it, absent]. QML
                                    // `visible` is EFFECTIVE visibility — false if
                                    // any ancestor is hidden — so this bubble asked
                                    // a child inside itself whether to be visible,
                                    // and a picture landing on a row with no text
                                    // found the bubble already hidden, read its own
                                    // child as invisible, and stayed hidden for
                                    // good. Reloading the session drew it, because
                                    // then the row was born with the picture on it:
                                    // the latch only catches a picture that ARRIVES.
                                    visible: body !== "" || turn.hasMedia
                                    user: isUser
                                    isError: model.isError
                                    x: isUser ? turnStack.width - width : 0
                                    // No FLOOR: a one-character message is a
                                    // one-character bubble [his, 2026-08-23]. It
                                    // used to be held open at 72px, which read as
                                    // a padded slab around a `k`.
                                    width: turn.wide ? turn.bubbleMax
                                           : Math.min(turn.bubbleMax,
                                                      turnCol.natural + 2 * turn.pad)
                                    height: visible ? turnCol.height + 2 * turn.pad : 0

                                    Column {
                                        id: turnCol
                                        x: turn.pad
                                        y: turn.pad
                                        // A FIXED wrapping width, not the bubble's:
                                        // the bubble hugs `natural`, which is measured
                                        // from these items, so reading it back here
                                        // would be a binding loop. Text is left-aligned
                                        // and never paints past what it laid out.
                                        width: turn.innerW
                                        spacing: 4

                                        // The longest line any of this turn's text
                                        // actually laid out — `contentWidth` is the
                                        // post-wrap measurement, and a hidden item
                                        // reports 0, so this is the max over whichever
                                        // of them is showing.
                                        // The CAPTION is not in this: it sits
                                        // outside the bubble, so measuring it in
                                        // held every short message open to the
                                        // width of the model's name.
                                        readonly property real natural:
                                            Math.max(plainBody.contentWidth,
                                                     turn.replyTextMax)


                                        // The reply's content, laid out as a FLOW of runs so a
                                        // picture the model wrote into the prose (`![alt](url)`)
                                        // sits AT that spot, in with the words, rather than all
                                        // hoisted to the top of the bubble [his, 2026-08-23 — "all
                                        // images must be at top of message ... allow them to be put
                                        // in line i.e. in with the text"]. `turn.replyRunsArr` is the
                                        // markdown split by Ollama.replyRuns: text runs render as
                                        // MarkdownText, image runs as an inline picture (capped to
                                        // the column, PNG alpha intact, click to enlarge), and a
                                        // failed fetch names itself where the picture was meant to
                                        // be (docs/DESIGN.md §10). A fetched picture the reply
                                        // never referenced inline is still SEEN — it falls to the
                                        // trailing gallery below, so nothing is hidden.
                                        //
                                        // A markdown image that was NOT fetched this turn is
                                        // demoted to a plain link inside its text run: MarkdownText
                                        // would draw it at its raw pixel size and fetch the URL on
                                        // render (the risk MarkdownText.qml itself flags). As a
                                        // link the URL is still there and clickable — just not
                                        // auto-fetched or upscaled.
                                        Column {
                                            id: replyFlow
                                            width: parent.width
                                            spacing: 6
                                            visible: !isUser

                                            Repeater {
                                                id: replyRunsRepeater
                                                model: turn.replyRunsArr
                                                delegate: Column {
                                                    required property var modelData
                                                    readonly property bool isText: modelData.t === "text"
                                                    readonly property bool isImg: modelData.t === "img"
                                                    readonly property bool isBad: modelData.t === "bad"
                                                    width: replyFlow.width
                                                    spacing: 0
                                                    // For the bubble's hug-width measurement: an image
                                                    // or a failure contributes no text width.
                                                    readonly property real runWidth: runText.contentWidth

                                                    MarkdownText {
                                                        id: runText
                                                        objectName: "mdBody"
                                                        width: parent.width
                                                        visible: parent.isText
                                                        // One expression, both properties: `text` is
                                                        // what is drawn, `source` is what Ctrl+C copies
                                                        // (MarkdownText.qml). `messageSource` is the
                                                        // WHOLE original reply, so "copy message" from
                                                        // any run hands over the full markdown — image
                                                        // references intact — not just the run.
                                                        readonly property string md:
                                                            parent.isText ? (parent.modelData.md || "")
                                                                          : ""
                                                        readonly property string messageSource: body
                                                        text: win.hardBreaks(md)
                                                        source: md
                                                        onSelectedTextChanged:
                                                            if (selectedText !== "" || win.selectedBody === runText)
                                                                win.noteSelection(runText, true);
                                                        MouseArea {
                                                            anchors.fill: parent
                                                            acceptedButtons: Qt.RightButton
                                                            onClicked: function (m) {
                                                                var p = mapToItem(win, m.x, m.y);
                                                                ctxMenu.open(p.x, p.y,
                                                                    win.turnMenu(runText, true,
                                                                                 turn.rowIndex, false));
                                                            }
                                                        }
                                                    }

                                                    // A picture in with the text. Capped, alpha kept,
                                                    // one click opens the Lightbox.
                                                    InlineImage {
                                                        id: runImg
                                                        width: parent.width
                                                        visible: parent.isImg
                                                        entry: parent.isImg ? parent.modelData : null
                                                        maxWidth: replyFlow.width
                                                        onEnlarge:
                                                            lightbox.openAt([parent.modelData], 0)
                                                        onContextRequested: (p, x, y) => win.openMediaMenu(p, x, y, false)
                                                    }

                                                    // A fetch that failed, where the picture was meant
                                                    // to be — surfaced, never vanished (§10).
                                                    PixelText {
                                                        visible: parent.isBad
                                                        width: parent.width
                                                        wrapMode: Text.Wrap
                                                        text: "image: " + (parent.isBad
                                                                           && parent.modelData.error
                                                                    ? parent.modelData.error
                                                                    : "could not display")
                                                        color: Theme.crit
                                                    }
                                                }
                                            }

                                            // A fetched picture the reply never tied to a word:
                                            // still shown, as the gallery below the text. ONE is
                                            // one; two or more tile (ImageGallery.qml), and a tile
                                            // opens the Lightbox.
                                            ImageGallery {
                                                width: replyFlow.width
                                                visible: turn.leftoverImages.length > 0
                                                entries: turn.leftoverImages
                                                onEnlarge: (i) => lightbox.openAt(turn.leftoverOks, i)
                                                onContextRequested: (p, x, y) => win.openMediaMenu(p, x, y, false)
                                            }

                                            // A typed/fetched image still landing (§10 — wait shown).
                                            PixelText {
                                                visible: imagesActive
                                                text: "fetching an image…"
                                                color: Theme.text
                                            }

                                            // The videos a reply carries, under the words [his,
                                            // 2026-08-23 — "are inline youtube video displays
                                            // possible … like the youtube video displays in the
                                            // bubble?"]. One card per video, playing a STREAM the
                                            // resolver found — nothing is downloaded, nothing starts
                                            // until he clicks it. VideoDeck.qml / VideoCard.qml.
                                            Column {
                                                id: videoCol
                                                width: parent.width
                                                spacing: 6
                                                visible: videos !== "[]" || videosActive

                                                VideoDeck {
                                                    width: videoCol.width
                                                    stage: videoStage
                                                    host: win
                                                    entries: {
                                                        try { return JSON.parse(videos); }
                                                        catch (e) { return []; }
                                                    }
                                                    onContextRequested: (p, x, y) => win.openMediaMenu(p, x, y, true)
                                                }

                                                // Resolving a watch page takes seconds, so the wait
                                                // is shown (§10) rather than left blank.
                                                PixelText {
                                                    visible: videosActive
                                                    text: "finding the video…"
                                                    color: Theme.text
                                                }
                                            }
                                        }

                                        // The turn's text. User prompts and error lines stay
                                        // verbatim on the plain SelectableText (PlainText —
                                        // never interpreted, the shared guard — but read-only
                                        // selectable so he can copy them). A model row with no
                                        // content yet shows "…" only when nothing else is
                                        // speaking (no reasoning block carrying the wait); that
                                        // placeholder is not selectable content, so it stays a
                                        // plain PixelText.
                                        SelectableText {
                                            id: plainBody
                                            width: parent.width
                                            visible: (isUser || isError) && body !== ""
                                            text: body
                                            color: isError ? Theme.crit : Theme.text

                                            // Tell the window which body Edit ▸ Copy
                                            // means (see win.noteSelection).
                                            onSelectedTextChanged:
                                                if (selectedText !== "" || win.selectedBody === plainBody)
                                                    win.noteSelection(plainBody, false);

                                            // Right-click only: every other button
                                            // falls through to the TextEdit under
                                            // it, so selecting and dragging are
                                            // untouched.
                                            MouseArea {
                                                anchors.fill: parent
                                                acceptedButtons: Qt.RightButton
                                                onClicked: function (m) {
                                                    var p = mapToItem(win, m.x, m.y);
                                                    ctxMenu.open(p.x, p.y,
                                                        win.turnMenu(plainBody, false,
                                                                     turn.rowIndex,
                                                                     isUser));
                                                }
                                            }
                                        }

                                    }
                                }

                                // WHEN it landed, under the bubble and on its
                                // own side [his, 2026-08-23] — a caption, one
                                // step dim and slightly faded, the same weight
                                // the speaker's name above it carries
                                // (docs/DESIGN.md §9.1). A row from before the
                                // store kept times has no `ts` and gets none,
                                // rather than a made-up one.
                                PixelText {
                                    id: stampText
                                    x: isUser ? turnStack.width - width : 0
                                    visible: ts > 0 && bubble.visible
                                    text: visible ? win.timeLabel(ts) : ""
                                    color: Theme.textDim
                                    opacity: 0.7
                                }

                            }
                        }
                    }
                }
            }

            // Follow the newest text to the bottom ONLY while he is already at
            // the bottom (docs/DESIGN.md §6.1 — never yank his position). The
            // moment he scrolls up, `followBottom` clears and streaming stops
            // forcing the position; scrolling back down to the bottom re-arms it.
            // Computed inline, not off a binding, so the height handler sees the
            // just-grown contentHeight rather than a stale max.
            property bool followBottom: true
            onContentHeightChanged: if (followBottom)
                contentY = Math.max(0, contentHeight - height)
            onContentYChanged: followBottom =
                contentY >= Math.max(0, contentHeight - height) - 2
            // Put him at the end and keep him there as the reply grows. Called
            // on send; `returnToBounds` because a kinetic flick may still be
            // running when the prompt goes.
            function toBottom() {
                cancelFlick();
                followBottom = true;
                contentY = Math.max(0, contentHeight - height);
                returnToBounds();
            }

            ScrollBar.vertical: VScroll { id: replyScroll }
        }

        // The mini-player, floating over the top of the conversation while a
        // video's bubble is out of view (see the tracking block above). A later
        // sibling, so it draws over the flick. Its strip sits at the top edge
        // with a little breathing room; the bar's own height is content-driven.
        MiniPlayer {
            id: miniPlayer
            anchors { left: parent.left; right: parent.right; top: parent.top
                      leftMargin: 6; rightMargin: 6; topMargin: 6 }
            z: 20
            onDismissedCard: (card) => win.miniDismissed = card
        }
    }

    // ---------------------------------------------------- the attachment tray
    // The files he dragged on, sitting just above the compose box until the next
    // message carries them — each a removable chip (docs/DESIGN.md §7.2 boxed,
    // §10.2 a control that shows a file offers to drop it). Collapses to nothing
    // when the tray is empty.
    Flow {
        id: attachBar
        anchors { left: parent.left; right: parent.right; bottom: promptBox.top
                  leftMargin: 10; rightMargin: 10
                  bottomMargin: attachments.count > 0 ? 6 : 0 }
        spacing: 6
        visible: attachments.count > 0

        Repeater {
            model: attachments
            // One chip per attached file, with its own [x] — and the KStyle's
            // own button under Plasma (`+plasma/Chip.qml`).
            delegate: Chip {
                label: model.name
                onRemoved: win.removeAttachment(index)
            }
        }
    }

    // Drop files ANYWHERE on the window to attach them to the next message
    // (docs/DESIGN.md §13 — dropping into a window works like a file manager;
    // the target highlights while a drag hovers it). The URLs are resolved in
    // Python (Ollama.localFileInfo), never decoded in QML.
    DropArea {
        id: fileDrop
        anchors.fill: parent
        keys: ["text/uri-list"]
        onDropped: (drop) => {
            if (drop.hasUrls) {
                for (var i = 0; i < drop.urls.length; i++)
                    win.addAttachmentUrl(drop.urls[i]);
                drop.accept();
            }
        }
    }
    Rectangle {
        anchors.fill: parent
        visible: fileDrop.containsDrag
        z: 200
        color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.10)
        border.width: 2
        border.color: Theme.accent
        radius: Theme.rounding
        PixelText {
            anchors.centerIn: parent
            text: "drop files to attach"
            color: Theme.accent
        }
    }

    // ----------------------------------------------------------- the lightbox
    // A picture from a reply, enlarged over the conversation [his, 2026-08-23].
    // Last in the tree and z:300 so it covers the drop overlay too; focus goes
    // back to the reply area on close, exactly where Escape in the compose box
    // sends it.
    Lightbox {
        id: lightbox
        onClosed: replyFlick.forceActiveFocus()
        onContextRequested: (p, x, y) => win.openMediaMenu(p, x, y, false)
    }

    // ------------------------------------------------------- the video stage
    // A video from a reply, thrown full-window [his, 2026-08-23: "can you add a
    // fullscreen button to videos?"]. It borrows the card's player rather than
    // starting a second one, so the picture moves and the stream does not —
    // VideoStage.qml. Under the lightbox, since a picture opened from a reply
    // is the more recent act when both are up.
    VideoStage {
        id: videoStage
        onClosed: replyFlick.forceActiveFocus()
    }

    // A COPY THAT FAILED HAS TO SAY SO (§10). Chatter had no transient surface
    // at all — `win.status` is drawn only on an empty log — so this is
    // painter's toast, verbatim: bottom-centre, three seconds, crit border when
    // it is bad news. A copy that WORKED says so too, because the clipboard
    // gives back no other sign until the paste.
    Rectangle {
        id: toast
        z: 2900
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 40
        width: Math.min(toastMsg.implicitWidth + 24, win.width - 60)
        height: 30
        opacity: 0
        color: Theme.bgAlt
        radius: Theme.rounding
        border.color: error ? Theme.crit : Theme.border
        border.width: Theme.ctrlBorder
        property bool error: false

        function show(text, isError) {
            toastMsg.text = text;
            error = isError === true;
            toastFade.restart();
        }

        PixelText {
            id: toastMsg
            anchors.centerIn: parent
            width: parent.width - 20
            elide: Text.ElideRight
            color: parent.error ? Theme.crit : Theme.text
        }

        // The PAUSE deliberately does not scale with animSpeed: it is how long
        // the message is READABLE, not motion, and under reduceMotion `ms()`
        // returns 0 — which would blink the report out of existence.
        SequentialAnimation {
            id: toastFade
            NumberAnimation { target: toast; property: "opacity"; to: 1; duration: motion.ms(120) }
            PauseAnimation { duration: 3200 }
            NumberAnimation { target: toast; property: "opacity"; to: 0; duration: motion.ms(400) }
        }
        Connections {
            target: Clip
            function onCopied(message, bad) { toast.show(message, bad); }
        }
    }

    // The right-click menu for the log, ours under Hyprland and the style's own
    // popup under Plasma (`+plasma/CtxMenu.qml`). Last but one in the tree and
    // z:3000 (its own default), so it covers the lightbox and the drop overlay.
    CtxMenu { id: ctxMenu; objectName: "ctxMenu"; anchors.fill: parent }

    // --------------------------------------------------------- the prompt box
    // The compose box: the framed input and the send/stop button, as ONE
    // component with two implementations — ours here, and the KStyle's own
    // Frame/TextArea/Button under Plasma (`+plasma/PromptBox.qml`, chosen by
    // the file selector, apps/AGENTS.md → kdeshell.select_plasma_files).
    PromptBox {
        id: promptBox
        objectName: "promptBox"
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom
                  leftMargin: 10; rightMargin: 10
                  // Under Plasma the status bar is already a band below this;
                  // our own 10px on top of it read as a gap [his, 2026-08-22].
                  bottomMargin: win.plasma ? 4 : 10 }
        busy: Ollama.busy
        armed: win.canSend
        canContinue: win.canContinue
        onSubmitted: win.send()
        onStopped: win.stopReply()
        onContinued: win.continueReply()
        onEscaped: replyFlick.forceActiveFocus()
    }
}
