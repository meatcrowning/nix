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
    // answer is), `isError`.
    ListModel { id: chatLog }

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
        function onReplyChunk(piece) {
            if (win.activeIndex < 0) return;
            var cur = chatLog.get(win.activeIndex);
            chatLog.setProperty(win.activeIndex, "body", cur.body + piece);
            if (cur.thinkingActive)
                chatLog.setProperty(win.activeIndex, "thinkingActive", false);
        }
        function onReplyThinking(piece) {
            if (win.activeIndex < 0) return;
            var cur = chatLog.get(win.activeIndex);
            chatLog.setProperty(win.activeIndex, "thinking", cur.thinking + piece);
            if (!cur.thinkingActive)
                chatLog.setProperty(win.activeIndex, "thinkingActive", true);
        }
        // The live reasoning-token count, written into the active row so the
        // collapsed heading shows it climbing while the model thinks.
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
        function onReplyDone() {
            if (win.activeIndex < 0) return;
            chatLog.setProperty(win.activeIndex, "streaming", false);
            chatLog.setProperty(win.activeIndex, "thinkingActive", false);
            chatLog.setProperty(win.activeIndex, "searching", false);
            chatLog.setProperty(win.activeIndex, "filesActive", false);
            chatLog.setProperty(win.activeIndex, "imagesActive", false);
            chatLog.setProperty(win.activeIndex, "toolsActive", false);
            win.saveCurrent();          // the finished turn persists to the session
        }
        function onReplyError(reason) {
            if (win.activeIndex < 0) return;
            chatLog.setProperty(win.activeIndex, "body", "error: " + reason);
            chatLog.setProperty(win.activeIndex, "isError", true);
            chatLog.setProperty(win.activeIndex, "streaming", false);
            chatLog.setProperty(win.activeIndex, "thinkingActive", false);
            chatLog.setProperty(win.activeIndex, "searching", false);
            chatLog.setProperty(win.activeIndex, "filesActive", false);
            chatLog.setProperty(win.activeIndex, "imagesActive", false);
            chatLog.setProperty(win.activeIndex, "toolsActive", false);
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
            turns.push({ isUser: t.isUser, who: t.who, body: t.body,
                         thinking: t.thinking, thinkTokens: t.thinkTokens,
                         sources: t.sources, searchCount: t.searchCount,
                         files: t.files, fileCount: t.fileCount,
                         images: t.images,
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

    // Open the custom-prompt editor (from the picker's "custom…" or the "edit"
    // button), prefilled with his saved custom text.
    function openPromptEditor() {
        promptPicker.open = false;
        promptEditor.load();
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
                             sources: t.sources || "", searchCount: t.searchCount || 0,
                             searching: false,
                             files: t.files || "", fileCount: t.fileCount || 0,
                             filesActive: false, filesPending: 0,
                             images: t.images || "[]", imagesActive: false, imagesPending: 0,
                             tools: t.tools || "", toolCount: t.toolCount || 0, toolsActive: false,
                             streaming: false, isError: !!t.isError });
        }
        win.sessionId = id;
        win.sessionTitle = title;
        win.activeIndex = -1;
        win.status = "";
        sessionPicker.open = false;
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
            history.push({ role: h.isUser ? "user" : "assistant", content: h.body });
        }
        // Append the pair now, then stream into the assistant row. Prior turns
        // are left untouched — the log grows downward (docs/DESIGN.md §14).
        chatLog.append({ isUser: true, who: "you", body: shownBody,
                         thinking: "", thinkingActive: false, thinkTokens: 0,
                         sources: "", searchCount: 0, searching: false,
                         files: "", fileCount: 0, filesActive: false, filesPending: 0,
                         images: "[]", imagesActive: false, imagesPending: 0,
                         tools: "", toolCount: 0, toolsActive: false,
                         streaming:false, isError: false });
        chatLog.append({ isUser: false, who: win.model, body: "",
                         thinking: "", thinkingActive: false, thinkTokens: 0,
                         sources: "", searchCount: 0, searching: false,
                         files: "", fileCount: 0, filesActive: false, filesPending: 0,
                         images: "[]", imagesActive: false, imagesPending: 0,
                         tools: "", toolCount: 0, toolsActive: false,
                         streaming:true, isError: false });
        win.activeIndex = chatLog.count - 1;
        Ollama.rememberModel(win.model);   // the model he last used is next launch's default
        Ollama.send(win.model, sendPrompt, JSON.stringify(history), JSON.stringify(atts));
        promptBox.clear();
        win.clearAttachments();
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
        out.push({ id: "send", menu: "chat",
                   menuText: Ollama.busy ? "Stop Generating" : "Send",
                   tip: Ollama.busy ? "stop the reply" : "send the prompt",
                   icon: Ollama.busy ? "process-stop" : "document-send",
                   bar: true, shortcut: "Ctrl+Return",
                   state: (Ollama.busy || win.canSend) ? 0 : 2 });
        out.push("-");
        out.push({ id: "attach", menu: "chat", menuText: "Attach Files…",
                   tip: "attach files to the next message",
                   icon: "mail-attachment", bar: true, shortcut: "@Open" });
        out.push({ id: "detach", menu: "chat", menuText: "Clear Attachments",
                   state: attachments.count > 0 ? 0 : 2 });

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
        case "send":           if (Ollama.busy) win.stopReply(); else win.send(); break;
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
        }
    }

    // ---- the KDE status bar ------------------------------------------------
    // Dolphin's shape: what is HAPPENING on the left, the standing fact on the
    // right. Under Hyprland nothing reads these — the same two readouts are
    // drawn in the window (`serverNoteText`, and the server row itself).
    readonly property string statusLine: {
        if (win.serverNote !== "") return win.serverNote;
        if (win.status !== "") return win.status;
        if (Ollama.busy) return "generating…";
        return "";
    }
    // No honest fraction: a reply has no known length. The line says it instead.
    readonly property real statusProgress: -1
    readonly property string statusRight: {
        if (!Backend.serverUp) return "ollama down";
        return Backend.loadedModels.length > 0
               ? "ollama · " + Backend.loadedModels.join(", ") : "ollama idle";
    }
    // The taskbar entry says which conversation this is (kdeshell.bind_title).
    readonly property string windowTitle:
        win.sessionTitle !== "" ? "chatter — " + win.sessionTitle : "chatter"

    // Stop an in-flight reply and settle the row it was writing into: cancel()
    // fires no replyDone/replyError, so nothing else would (§10.6 — a stopped
    // stream must not still read as running).
    function stopReply() {
        Ollama.cancel();
        if (win.activeIndex >= 0) {
            chatLog.setProperty(win.activeIndex, "streaming", false);
            chatLog.setProperty(win.activeIndex, "thinkingActive", false);
            chatLog.setProperty(win.activeIndex, "searching", false);
            chatLog.setProperty(win.activeIndex, "filesActive", false);
            chatLog.setProperty(win.activeIndex, "imagesActive", false);
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
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
            text: "model"
            color: Theme.textDim
        }

        // The selector: a boxed control showing the current model, which opens
        // an inline list of the daemon's models under itself (docs/DESIGN.md
        // §7.2 — no combo boxes on this desktop).
        Rectangle {
            id: picker
            anchors { left: modelLabel.right; leftMargin: 10
                      right: parent.right
                      verticalCenter: parent.verticalCenter }
            height: 24
            color: pickerMouse.containsMouse ? Theme.highlight : Theme.bgAlt
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border

            property bool open: false

            PixelText {
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
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
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

        Rectangle {
            id: sessionPicker
            anchors { left: sessionLabel.right; leftMargin: 10
                      right: newBtn.left; rightMargin: 10
                      verticalCenter: parent.verticalCenter }
            height: 24
            color: sessionMouse.containsMouse ? Theme.highlight : Theme.bgAlt
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border

            property bool open: false

            PixelText {
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
        height: visible ? Theme.lineHeight : 0

        // Compact token formatter: 8192 → "8K", 8000 → "7.8K", 512 → "512".
        function fmtTok(n) {
            if (n >= 1000)
                return (n / 1024).toFixed(n % 1024 === 0 ? 0 : 1) + "K";
            return "" + n;
        }

        // "ctx used/ceiling" (or just the ceiling before a turn has run).
        PixelText {
            visible: statsRow.hasCtx
            anchors.verticalCenter: parent.verticalCenter
            text: "ctx " + (statsRow.hasFill
                            ? statsRow.fmtTok(Ollama.contextUsed) + "/"
                              + statsRow.fmtTok(Ollama.contextMax)
                            : statsRow.fmtTok(Ollama.contextMax) + " tok")
            color: Theme.textDim
        }

        // The fill bar: a track with a proportional fill, animated (docs/DESIGN.md
        // §9 meter, §4 corners, §6 motion). Warns as it approaches full.
        Rectangle {
            visible: statsRow.hasFill
            anchors.verticalCenter: parent.verticalCenter
            width: 88
            height: 6
            radius: Theme.rounding
            color: Theme.bgAlt
            border.width: Theme.ctrlBorder
            border.color: Theme.border
            Rectangle {
                anchors { left: parent.left; top: parent.top; bottom: parent.bottom
                          margins: 1 }
                width: Math.max(0, (parent.width - 2) * statsRow.fillFrac)
                radius: Theme.rounding
                color: statsRow.fillFrac > 0.9 ? Theme.crit
                       : statsRow.fillFrac > 0.75 ? Theme.warn : Theme.accent
                Behavior on width {
                    NumberAnimation { duration: motion.ms(motion.slideMs)
                                      easing.type: motion.slideEasing }
                }
            }
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
            delegate: Rectangle {
                required property string modelData
                height: capLabelText.implicitHeight + 4
                width: capLabelText.implicitWidth + 10
                radius: 3
                color: Theme.bgAlt
                border.width: Theme.ctrlBorder
                border.color: Theme.border
                PixelText {
                    id: capLabelText
                    anchors.centerIn: parent
                    text: capsRow.capLabel(parent.modelData)
                    color: Theme.textDim
                }
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

    // The custom-prompt editor — a floating panel over the reply area with a
    // TextEdit for his own base text and Save / Cancel (docs/DESIGN.md §10:
    // Save applies it; Cancel discards, nothing changes silently). Selecting
    // "custom…" in the dropdown, or the "edit" button, opens it.
    Rectangle {
        id: promptEditor
        visible: false
        anchors { left: parent.left; right: parent.right
                  leftMargin: 20; rightMargin: 20
                  top: promptRow.bottom; topMargin: 8 }
        height: 220
        z: 60
        color: Theme.bgAlt
        radius: Theme.rounding
        border.width: Theme.ctrlBorder
        border.color: Theme.accent

        function load() {
            editorArea.text = Ollama.customPrompt;
            promptEditor.visible = true;
            editorArea.forceActiveFocus();
        }

        PixelText {
            id: editorHeading
            anchors { top: parent.top; left: parent.left; right: parent.right
                      margins: 10 }
            text: "your custom system prompt"
            color: Theme.textDim
            wrapMode: Text.NoWrap
            elide: Text.ElideRight
        }

        Rectangle {
            anchors { top: editorHeading.bottom; topMargin: 8
                      left: parent.left; right: parent.right
                      bottom: editorButtons.top; bottomMargin: 8
                      leftMargin: 10; rightMargin: 10 }
            color: Theme.bg
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: editorArea.activeFocus ? Theme.accent : Theme.border

            KineticFlickable {
                id: editorFlick
                anchors { fill: parent; margins: 8 }
                contentWidth: width
                contentHeight: editorArea.implicitHeight
                clip: true
                TextEdit {
                    id: editorArea
                    width: editorFlick.width
                    font: Theme.editorFont
                    renderType: Text.NativeRendering
                    color: Theme.text
                    selectionColor: Theme.accent
                    selectedTextColor: Theme.bg
                    wrapMode: TextEdit.Wrap
                    persistentSelection: true
                    Keys.onPressed: function (e) {
                        if (e.key === Qt.Key_Escape) {
                            promptEditor.visible = false;
                            e.accepted = true;
                        }
                    }
                    PixelText {
                        anchors { left: parent.left; verticalCenter: parent.top
                                  verticalCenterOffset: parent.implicitHeight / 2 }
                        visible: editorArea.text === "" && !editorArea.activeFocus
                        text: "write the base instructions the model gets every turn…"
                        color: Theme.textDim
                    }
                }
            }
        }

        Row {
            id: editorButtons
            anchors { bottom: parent.bottom; right: parent.right; margins: 10 }
            spacing: 8

            Rectangle {
                width: 64; height: 24
                radius: Theme.rounding
                border.width: Theme.ctrlBorder
                border.color: Theme.border
                color: cancelMouse.containsMouse ? Theme.highlight : Theme.bg
                PixelText { anchors.centerIn: parent; text: "cancel"; color: Theme.textDim }
                MouseArea {
                    id: cancelMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: promptEditor.visible = false
                }
            }
            Rectangle {
                width: 64; height: 24
                radius: Theme.rounding
                border.width: Theme.ctrlBorder
                border.color: Theme.border
                color: saveMouse.containsMouse ? Theme.highlight : Theme.bg
                PixelText { anchors.centerIn: parent; text: "save"; color: Theme.accent }
                MouseArea {
                    id: saveMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    // Persist the text AND select custom as the active base, so
                    // saving is also applying it (docs/DESIGN.md §10 — the button
                    // does what it says).
                    onClicked: {
                        Ollama.setCustomPrompt(editorArea.text);
                        Ollama.setPromptChoice("custom");
                        promptEditor.visible = false;
                    }
                }
            }
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
    Rectangle {
        id: replyBox
        anchors { top: statsRow.bottom; topMargin: 10
                  left: parent.left; right: parent.right
                  bottom: attachBar.top
                  leftMargin: 10; rightMargin: 10; bottomMargin: 10 }
        color: Theme.bgAlt
        radius: Theme.rounding
        border.width: Theme.ctrlBorder
        border.color: Theme.border

        KineticFlickable {
            id: replyFlick
            anchors { fill: parent; margins: 8 }
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
                        width: replyCol.width
                        height: turnCol.height

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

                        Column {
                            id: turnCol
                            width: parent.width
                            spacing: 4

                            PixelText {
                                text: who
                                color: Theme.textDim
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
                                visible: !isUser && thinking !== ""
                                height: visible ? thinkToggle.height + thinkReveal.height : 0

                                readonly property bool expanded: turn.userSet ? turn.userOpen
                                                                              : false

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
                                        running: thinkingActive && !motion.reduceMotion
                                        repeat: true
                                        onTriggered: thinkToggle.dotPhase = (thinkToggle.dotPhase + 1) % 4
                                    }
                                    Row {
                                        anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                                        spacing: 6
                                        PixelText { text: think.expanded ? "-" : "+"; color: Theme.textDim }
                                        PixelText {
                                            text: "thinking"
                                            color: thinkingActive ? Theme.text : Theme.textDim
                                        }
                                        // The reasoning-token count, and — while
                                        // active — an animated ellipsis. The count
                                        // PERSISTS once counted, so a COLLAPSED block
                                        // still reports its size after the answer
                                        // starts (the header is all he sees when it
                                        // is folded); the ellipsis is the only part
                                        // that ends with the thinking (§9.1
                                        // subordinated — one step dim, never accent).
                                        PixelText {
                                            visible: thinkTokens > 0 || thinkingActive
                                            text: (thinkTokens > 0 ? "· " + thinkTokens : "")
                                                  + (thinkingActive ? " " + thinkToggle.dots : "")
                                            color: Theme.textDim
                                        }
                                    }
                                    MouseArea {
                                        anchors.fill: parent
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
                                        text: thinking
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
                                visible: !isUser && (tools !== "" || toolsActive)
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
                                        running: toolsActive && !motion.reduceMotion
                                        repeat: true
                                        onTriggered: toolToggle.dotPhase = (toolToggle.dotPhase + 1) % 4
                                    }
                                    Row {
                                        anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                                        spacing: 6
                                        PixelText { text: toolAct.expanded ? "-" : "+"; color: Theme.textDim }
                                        PixelText {
                                            text: toolsActive ? "calling tools"
                                                              : "tools · " + toolCount
                                            color: toolsActive ? Theme.text : Theme.textDim
                                        }
                                        PixelText {
                                            visible: toolsActive
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
                                        text: tools
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
                                visible: !isUser && (sources !== "" || searching)
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
                                        running: searching && !motion.reduceMotion
                                        repeat: true
                                        onTriggered: srcToggle.dotPhase = (srcToggle.dotPhase + 1) % 4
                                    }
                                    Row {
                                        anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                                        spacing: 6
                                        PixelText { text: src.expanded ? "-" : "+"; color: Theme.textDim }
                                        PixelText {
                                            text: searching ? "searching the web"
                                                            : "web · " + searchCount + (searchCount === 1 ? " source" : " sources")
                                            color: searching ? Theme.text : Theme.textDim
                                        }
                                        PixelText {
                                            visible: searching
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
                                        text: sources
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
                                visible: !isUser && (files !== "" || filesActive)
                                height: visible ? fileToggle.height + fileReveal.height : 0

                                readonly property bool expanded: turn.fileUserSet ? turn.fileUserOpen
                                                                                  : false

                                Item {
                                    id: fileToggle
                                    width: parent.width
                                    height: Theme.lineHeight
                                    property int dotPhase: 0
                                    readonly property string dots:
                                        motion.reduceMotion ? "…" : "...".substring(0, dotPhase)
                                    Timer {
                                        interval: motion.ms(motion.slideMs)
                                        running: filesActive && !motion.reduceMotion
                                        repeat: true
                                        onTriggered: fileToggle.dotPhase = (fileToggle.dotPhase + 1) % 4
                                    }
                                    Row {
                                        anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                                        spacing: 6
                                        PixelText { text: fileAct.expanded ? "-" : "+"; color: Theme.textDim }
                                        PixelText {
                                            text: filesActive ? "working with files"
                                                              : "files · " + fileCount
                                            color: filesActive ? Theme.text : Theme.textDim
                                        }
                                        PixelText {
                                            visible: filesActive
                                            text: fileToggle.dots
                                            color: Theme.textDim
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
                                    height: fileAct.expanded ? fileBody.height : 0
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
                                        text: files
                                        color: Theme.textDim
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
                                width: parent.width
                                visible: (isUser || isError) && body !== ""
                                text: body
                                color: isError ? Theme.crit : Theme.text
                            }
                            PixelText {
                                width: parent.width
                                wrapMode: Text.Wrap
                                visible: !isUser && !isError && body === "" && streaming
                                         && thinking === ""
                                text: "…"
                                color: Theme.text
                            }

                            // The model's answer, rendered as Markdown (the reply
                            // comes back in it — docs/DESIGN.md §2). Only the
                            // assistant body; user text and errors above stay plain.
                            //
                            // A markdown IMAGE (`![alt](url)`) is DEMOTED to a plain
                            // link (`[alt](url)`) first: Text.MarkdownText would draw
                            // it at its intrinsic pixel size — overflowing the column
                            // — and fetch the URL on render (the risk MarkdownText.qml
                            // itself flags). A picture the model wants shown comes
                            // through fetch_image and the capped `images` delegate
                            // below, exactly ONCE; a stray `![](…)` in the prose must
                            // not become a second, giant, uncontrolled copy. As a link
                            // the URL is still there and clickable (docs/DESIGN.md §10
                            // — nothing hidden), just not auto-fetched or upscaled.
                            MarkdownText {
                                width: parent.width
                                visible: !isUser && !isError && body !== ""
                                text: body.replace(/!\[([^\]]*)\]\(/g, "[$1](")
                            }

                            // Images the model fetched from the web with
                            // fetch_image, rendered INLINE — the one place a reply
                            // becomes a picture. Each entry (the Python↔QML
                            // contract) is either a fetched image, framed like
                            // every surface here (1px border, Theme.rounding,
                            // never upscaled past its own size), with the model's
                            // caption under it, or an honest crit line for a fetch
                            // that failed or a file that will not load
                            // (docs/DESIGN.md §10 — surfaced, never vanished).
                            Column {
                                id: imageCol
                                width: parent.width
                                spacing: 6
                                visible: !isUser && (images !== "[]" || imagesActive)

                                Repeater {
                                    model: {
                                        try { return JSON.parse(images); }
                                        catch (e) { return []; }
                                    }
                                    delegate: Column {
                                        width: imageCol.width
                                        spacing: 2

                                        Rectangle {
                                            visible: !!modelData.ok
                                            width: pic.width + 2
                                            height: pic.height + 2
                                            color: Theme.bgAlt
                                            radius: Theme.rounding
                                            border.width: Theme.ctrlBorder
                                            border.color: Theme.border
                                            Image {
                                                id: pic
                                                x: 1; y: 1
                                                // sourceSize.width caps the decode
                                                // to the column and, set alone,
                                                // scales height by the real aspect
                                                // — and never upscales past native.
                                                readonly property real natW:
                                                    (modelData.w && modelData.w > 0)
                                                    ? modelData.w : (imageCol.width - 2)
                                                sourceSize.width:
                                                    Math.min(imageCol.width - 2, natW)
                                                fillMode: Image.PreserveAspectFit
                                                asynchronous: true
                                                source: modelData.ok
                                                        ? "file://" + modelData.path : ""
                                            }
                                        }
                                        // The caption (the model's alt text),
                                        // subordinated (§9.1 — one step dim).
                                        PixelText {
                                            visible: !!modelData.ok
                                                     && !!modelData.alt && modelData.alt !== ""
                                            width: imageCol.width
                                            wrapMode: Text.Wrap
                                            text: modelData.alt || ""
                                            color: Theme.textDim
                                        }
                                        // The honest failure: a refused/failed
                                        // fetch, or a saved file that will not
                                        // load (§10 — say so, never a blank).
                                        PixelText {
                                            visible: !modelData.ok || pic.status === Image.Error
                                            width: imageCol.width
                                            wrapMode: Text.Wrap
                                            text: "image: "
                                                  + (modelData.error ? modelData.error
                                                                     : "could not display")
                                                  + (modelData.url ? " (" + modelData.url + ")" : "")
                                            color: Theme.crit
                                        }
                                    }
                                }

                                // A fetch still in flight (§10 — the wait is shown).
                                PixelText {
                                    visible: imagesActive
                                    text: "fetching an image…"
                                    color: Theme.text
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

            ScrollBar.vertical: VScroll { id: replyScroll }
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

    // --------------------------------------------------------- the prompt box
    // The compose box: the framed input and the send/stop button, as ONE
    // component with two implementations — ours here, and the KStyle's own
    // Frame/TextArea/Button under Plasma (`+plasma/PromptBox.qml`, chosen by
    // the file selector, apps/AGENTS.md → kdeshell.select_plasma_files).
    PromptBox {
        id: promptBox
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom
                  leftMargin: 10; rightMargin: 10; bottomMargin: 10 }
        busy: Ollama.busy
        armed: win.canSend
        onSubmitted: win.send()
        onStopped: win.stopReply()
        onEscaped: replyFlick.forceActiveFocus()
    }
}
