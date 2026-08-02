import QtQuick
import QtQuick.Window
import "../../qmlcommon"

// editor's window: N open documents, one visible, and every control in the
// hyprvtb titlebar because an app does not draw its own chrome strip
// (docs/DESIGN.md §12, §7.4).
//
// **The open documents ARE titlebar buttons** — surfer's idiom, and for the same
// reason: this desktop has no in-window tab strip anywhere, the inner column is
// where a program's per-thing switches live, and they are draggable there so the
// order is the user's. A dirty document's cell reads `f*` rather than `fi`, since
// a titlebar cell has no third state to say "unsaved" with and the tooltip is
// where the whole name goes.
//
// Nothing here is a `Loader`: every open document keeps its `CodeView` alive, so
// its undo stack, selection and scroll position survive switching away and back.
// That is the whole reason tabs are a Repeater over a `ListModel` and not one
// view with text swapped into it.
Window {
    id: win

    // ---- documents ----------------------------------------------------
    property int nextTid: 1
    property int current: -1
    property string status: ""

    // Settings, all persisted (§14). The indent pair is per-window rather than
    // per-document on purpose: it is a preference, and `Buffers.guessIndent`
    // already stops that preference from mangling a file that disagrees.
    property bool useTabs: false
    property int indentWidth: 4
    property bool showNumbers: true
    property bool guessIndent: true

    readonly property Item view: (current >= 0 && current < viewRep.count
                                 && viewRep.itemAt(current))
        ? viewRep.itemAt(current).view : null
    readonly property string docName: current >= 0 && current < tabs.count
        ? tabs.get(current).name : ""
    readonly property bool dirty: current >= 0 && current < tabs.count
        ? tabs.get(current).dirty : false

    // §3.1.1 — an unfocused window fades its WHOLE foreground.
    readonly property color fgAccent: win.active ? Theme.accent  : Theme.inactive
    readonly property color fgText:   win.active ? Theme.text    : Theme.inactive
    readonly property color fgDim:    win.active ? Theme.textDim : Theme.inactive

    // The pixel font is monospace, so ONE measurement gives every layout its
    // column (§2.7). Measured against the real font rather than derived from
    // `round(0.533 * fontSize)`, so it stays right if the family is changed.
    TextMetrics {
        id: metrics
        font.family: Theme.font
        font.pixelSize: Theme.fontSize
        text: "MMMMMMMMMM"
    }
    readonly property real cellW: metrics.width > 0 ? metrics.width / 10
                                                    : Math.round(0.533 * Theme.fontSize)

    ListModel { id: tabs }

    //: how many documents are open — bound, so the titlebar and the harness can
    //: both read it (`tabs.count` alone does not notify through a binding).
    readonly property int tabCount: tabs.count

    // Switching document moves the keyboard with it — §11's rule that there is
    // never a state that needs a click before you can type.
    onCurrentChanged: if (view) view.focusEditor()

    title: (docName === "" ? "editor" : docName) + (dirty ? " *" : "")
    width: 1000
    height: 760
    minimumWidth: 360
    minimumHeight: 200
    visible: true
    color: Theme.bg

    // ---- opening and closing -------------------------------------------

    function indexOfPath(p) {
        for (var i = 0; i < tabs.count; i++)
            if (tabs.get(i).path === p) return i;
        return -1;
    }
    function indexOfTid(t) {
        for (var i = 0; i < tabs.count; i++)
            if (tabs.get(i).tid === t) return i;
        return -1;
    }

    function baseName(p) {
        if (p === "") return "untitled";
        var i = p.lastIndexOf("/");
        return i < 0 ? p : p.substring(i + 1);
    }

    // A file already open is FOCUSED, never opened twice: two views over one
    // path means two undo stacks over one file and a guaranteed lost edit.
    function openPath(p, gotoLine) {
        var at = indexOfPath(p);
        if (at >= 0) {
            current = at;
            if (gotoLine > 0 && view) view.goToLine(gotoLine);
            return true;
        }
        var r = Files.read(p);
        if (!r.ok) {
            // §10.2: an app that cannot do its job says so.
            status = r.error + ": " + baseName(p);
            return false;
        }
        var tid = nextTid++;
        tabs.append({ tid: tid, path: r.path, name: baseName(r.path),
                      dirty: false, lang: "", seedText: r.text,
                      eol: r.eol, encoding: r.encoding, final: r.final,
                      mtime: r.mtime, isnew: r.isnew === true,
                      pendingLine: gotoLine > 0 ? gotoLine : 0 });
        current = tabs.count - 1;
        persist();
        return true;
    }

    function newFile() {
        var tid = nextTid++;
        tabs.append({ tid: tid, path: "", name: "untitled", dirty: false,
                      lang: "text", seedText: "", eol: "\n",
                      encoding: "utf-8", final: true, mtime: 0,
                      isnew: true, pendingLine: 0 });
        current = tabs.count - 1;
        if (view) view.focusEditor();
    }

    // Closing is where "never silently clobber" (§10.2) is enforced: a dirty
    // document asks, and the answer decides. `pendingClose` is the tab the
    // dialog is about, because the user may switch tabs while it is up.
    property int pendingClose: -1
    function closeTab(i) {
        if (i < 0 || i >= tabs.count) return;
        if (tabs.get(i).dirty) {
            pendingClose = tabs.get(i).tid;
            confirm.ask("save changes to " + tabs.get(i).name + "?",
                        tabs.get(i).path, "save", "discard");
            return;
        }
        dropTab(i);
    }

    function dropTab(i) {
        if (i < 0 || i >= tabs.count) return;
        Buffers.detach(tabs.get(i).tid);
        tabs.remove(i);
        if (tabs.count === 0) { current = -1; newFile(); }
        else current = Math.min(i, tabs.count - 1);
        persist();
    }

    function moveTab(from, to) {
        if (from < 0 || to < 0 || from >= tabs.count || to >= tabs.count
                || from === to) return;
        var cur = current >= 0 ? tabs.get(current).tid : -1;
        tabs.move(from, to, 1);
        if (cur >= 0) current = indexOfTid(cur);
        persist();
    }

    // ---- saving ---------------------------------------------------------

    function saveTab(i, asPath) {
        if (i < 0 || i >= tabs.count) return false;
        var t = tabs.get(i);
        var target = asPath && asPath !== "" ? asPath : t.path;
        if (target === "") { promptSaveAs(); return false; }
        var meta = Buffers.meta(t.tid);
        var r = Files.write(target, Buffers.text(t.tid),
                            meta.eol || "\n", meta.encoding || "utf-8",
                            t.final !== false);
        if (!r.ok) {
            status = "save failed: " + r.error;
            return false;
        }
        if (target !== t.path) {
            tabs.setProperty(i, "path", r.path);
            tabs.setProperty(i, "name", baseName(r.path));
            Buffers.setMeta(t.tid, meta.eol || "\n", meta.encoding || "utf-8",
                            r.mtime, r.path, t.final !== false);
            // The language follows the NAME: `save as x.py` makes it python.
            var lang = Buffers.detectLanguage(r.path, "");
            Buffers.setLanguage(t.tid, lang);
            tabs.setProperty(i, "lang", lang);
            if (viewRep.itemAt(i) && viewRep.itemAt(i).view) {
                viewRep.itemAt(i).view.lang = lang;
                viewRep.itemAt(i).view.refreshSpell();
            }
        }
        Buffers.markSaved(t.tid, r.mtime);
        tabs.setProperty(i, "dirty", false);
        status = "saved " + baseName(r.path);
        persist();
        return true;
    }

    function promptSaveAs() {
        var seed = current >= 0 && tabs.get(current).path !== ""
            ? tabs.get(current).path : "";
        pathBar.openPrompt("saveas", seed);
    }

    // ---- reload from disk ------------------------------------------------
    // §6.1 — reload in place, and never at the cost of unsaved typing. A clean
    // buffer reloads silently; a dirty one asks, because that is a clobber.
    property int pendingReload: -1
    function reloadTab(i, force) {
        if (i < 0 || i >= tabs.count) return;
        var t = tabs.get(i);
        if (t.path === "") return;
        if (t.dirty && force !== true) {
            pendingReload = t.tid;
            confirm.ask(t.name + " changed on disk", "reload and lose your edits?",
                        "reload", "keep mine");
            return;
        }
        var r = Files.read(t.path);
        if (!r.ok) { status = "reload failed: " + r.error; return; }
        var item = viewRep.itemAt(i);
        if (item && item.view) item.view.reloadText(r.text);
        Buffers.setMeta(t.tid, r.eol, r.encoding, r.mtime, r.path, r.final);
        Buffers.markSaved(t.tid, r.mtime);
        tabs.setProperty(i, "dirty", false);
        status = "reloaded " + t.name;
    }

    // ---- find -----------------------------------------------------------

    function refreshFind() {
        if (!view) { findBar.matches = 0; findBar.activeMatch = 0; return; }
        view.query = findBar.query;
        view.queryRegex = findBar.useRegex;
        view.queryCase = findBar.caseSensitive;
        view.queryWhole = findBar.wholeWords;
        findBar.valid = Buffers.setQuery(current >= 0 ? tabs.get(current).tid : -1,
                                        findBar.query, findBar.useRegex,
                                        findBar.caseSensitive);
        var ms = findBar.query.length > 0 && findBar.valid
            ? Buffers.matches(tabs.get(current).tid, findBar.query,
                              findBar.useRegex, findBar.caseSensitive,
                              findBar.wholeWords)
            : [];
        findBar.matches = ms.length;
        findBar.activeMatch = 0;
        for (var i = 0; i < ms.length; i++)
            if (ms[i].start === view.selStart && ms[i].end === view.selEnd)
                findBar.activeMatch = i + 1;
    }

    // The three find actions are FUNCTIONS, not code inside the bar's signal
    // handlers: the titlebar, the F3 shortcuts, the bar and the offscreen harness
    // all drive the same path, and a signal cannot be invoked from Python.
    function doStep(backward) {
        if (view && view.stepMatch(backward)) refreshFind();
    }
    function doReplaceCurrent() {
        if (!view) return;
        view.replaceStep(findBar.replacement);
        refreshFind();
    }
    function doReplaceAll() {
        if (!view || current < 0) return;
        var n = Buffers.replaceAll(tabs.get(current).tid, findBar.query,
                                   findBar.replacement, findBar.useRegex,
                                   findBar.caseSensitive, findBar.wholeWords);
        // The count is the honest report: "replace all" with no number is
        // indistinguishable from one that matched nothing (§10.2).
        status = n === 0 ? "nothing to replace"
                         : "replaced " + n + (n === 1 ? " match" : " matches");
        refreshFind();
    }

    function openFind(replacing) {
        if (view && view.selEnd > view.selStart && findBar.query.length === 0)
            findBar.seed(view.selectedText);
        findBar.openFind(replacing);
        refreshFind();
    }

    function closeFind() {
        findBar.shown = false;
        if (view) {
            view.query = "";
            Buffers.setQuery(tabs.get(current).tid, "", false, false);
            view.focusEditor();
        }
        findBar.matches = 0;
        findBar.activeMatch = 0;
    }

    // ---- the hyprvtb titlebar: editor's whole chrome --------------------
    // ASCII, lowercase, one or two characters (§12.1). `fs` is the desktop's
    // find glyph; `|`/`_` are not here because this app has no split (that is
    // deliberately out of scope, see AGENTS.md).
    property int tabRev: 0          // bumped on any add/remove/move/rename
    readonly property var tbButtons: {
        void tabRev;
        var arr = [
            { id: "new",   label: "+f", state: 0, tip: "new file (Ctrl+N)" },
            { id: "open",  label: "op", state: 0, tip: "open a file (Ctrl+O)" },
            { id: "save",  label: "sv", state: win.dirty ? 0 : 2,
              tip: win.dirty ? "save (Ctrl+S)" : "no unsaved changes" },
            { id: "saveas", label: "sa", state: win.current >= 0 ? 0 : 2,
              tip: "save as (Ctrl+Shift+S)" },
            "-",
            { id: "find",  label: "fs", state: findBar.shown && !findBar.replaceMode ? 1 : 0,
              tip: "find (Ctrl+F)" },
            { id: "replace", label: "rp", state: findBar.shown && findBar.replaceMode ? 1 : 0,
              tip: "replace (Ctrl+R)" },
            { id: "goto",  label: "gl", state: pathBar.shown && pathBar.mode === "goto" ? 1 : 0,
              tip: "go to line (Ctrl+G)" },
            "-",
            { id: "nums",  label: "ln", state: win.showNumbers ? 1 : 0,
              tip: "line numbers" },
            "-",
        ];
        for (var i = 0; i < tabs.count; i++) {
            var t = tabs.get(i);
            var nm = t.name;
            // A dirty document says so in the cell itself: one character of the
            // name plus `*`. Two characters is all a cell has (§12.1), and
            // "which of these is unsaved" is the more useful of the two.
            var label = t.dirty ? nm.substring(0, 1) + "*" : nm.substring(0, 2);
            arr.push({ id: "tab:" + t.tid, label: label,
                       state: i === win.current ? 1 : 0,
                       tip: (t.dirty ? "unsaved - " : "") + nm
                            + (i === win.current ? " - close" : ""),
                       drag: true });
        }
        return arr;
    }
    onTbButtonsChanged: Titlebar.setButtons(tbButtons)

    readonly property string footerStr: {
        if (status !== "") return status;
        if (!view) return "editor";
        var ind = win.useTabs ? "tab" : (win.indentWidth + "sp");
        return view.line + ":" + view.col + "  " + view.lines + "L  "
             + Buffers.language(tabs.get(current).tid) + "  " + ind;
    }
    onFooterStrChanged: Titlebar.setFooter(footerStr)

    Connections {
        target: Titlebar
        function onClicked(id) {
            switch (id) {
            case "new":     win.newFile(); return;
            case "open":    pathBar.openPrompt("open", win.dirName()); return;
            case "save":    win.saveTab(win.current, ""); return;
            case "saveas":  win.promptSaveAs(); return;
            case "find":
                if (findBar.shown && !findBar.replaceMode) win.closeFind();
                else win.openFind(false);
                return;
            case "replace":
                if (findBar.shown && findBar.replaceMode) win.closeFind();
                else win.openFind(true);
                return;
            case "goto":
                if (pathBar.shown && pathBar.mode === "goto") pathBar.closePrompt();
                else pathBar.openPrompt("goto", "");
                return;
            case "nums":    win.showNumbers = !win.showNumbers;
                            Settings.set("showNumbers", win.showNumbers); return;
            }
            if (id.indexOf("tab:") === 0) {
                var at = win.indexOfTid(parseInt(id.substring(4)));
                if (at < 0) return;
                // Re-clicking the document you are already in closes it — the
                // same gesture surfer's tabs have.
                if (at === win.current) win.closeTab(at);
                else win.current = at;
            }
        }
        function onReordered(srcId, dstId) {
            if (srcId.indexOf("tab:") !== 0 || dstId.indexOf("tab:") !== 0) return;
            win.moveTab(win.indexOfTid(parseInt(srcId.substring(4))),
                        win.indexOfTid(parseInt(dstId.substring(4))));
            win.tabRev++;
        }
    }

    function dirName() {
        if (current < 0 || tabs.get(current).path === "") return "";
        var p = tabs.get(current).path;
        return p.substring(0, p.lastIndexOf("/") + 1);
    }

    // ---- what Python tells us --------------------------------------------
    Connections {
        target: Buffers
        function onDirtyChanged(tid, on) {
            var at = win.indexOfTid(tid);
            if (at < 0) return;
            tabs.setProperty(at, "dirty", on);
            win.tabRev++;
        }
        function onDiskChanged(tid) {
            win.reloadTab(win.indexOfTid(tid), false);
        }
        function onReported(message) { win.status = message; }
    }

    // ---- persistence (§14) ----------------------------------------------
    function persist() {
        var open = [];
        for (var i = 0; i < tabs.count; i++)
            if (tabs.get(i).path !== "") open.push(tabs.get(i).path);
        Settings.set("open", open);
        Settings.set("current", current);
        win.tabRev++;
    }

    onClosing: (close) => {
        // Every unsaved document has to be answered for before the window goes.
        // One at a time, because a single "save all / discard all" answer over
        // several files is exactly the silent clobber §10.2 forbids.
        for (var i = 0; i < tabs.count; i++) {
            if (tabs.get(i).dirty) {
                close.accepted = false;
                current = i;
                closeTab(i);
                return;
            }
        }
        persist();
        Qt.quit();
    }

    Component.onCompleted: {
        useTabs = Settings.get("useTabs", false) === true;
        indentWidth = Number(Settings.get("indentWidth", 4)) || 4;
        showNumbers = Settings.get("showNumbers", true) !== false;
        // Wrap is unconditional now — no `wrap` key is read or written, so a
        // stale `wrap:false` in an old state.json is simply ignored.
        guessIndent = Settings.get("guessIndent", true) !== false;

        var paths = startArgs.paths || [];
        for (var i = 0; i < paths.length; i++)
            openPath(paths[i], i === 0 ? (startArgs.line || 0) : 0);
        if (tabs.count === 0) newFile();
        else {
            var want = Number(Settings.get("current", 0)) || 0;
            if (startArgs.restored === true && want >= 0 && want < tabs.count)
                current = want;
        }
        Titlebar.setButtons(tbButtons);
        Titlebar.setFooter(footerStr);
    }

    // ---- layout ----------------------------------------------------------
    Item {
        id: stage
        anchors.fill: parent

        Repeater {
            id: viewRep
            model: tabs

            // A wrapper Item, not a bare CodeView: a Repeater over a ListModel
            // injects the model's roles into the delegate, and a role called
            // `path`/`lang`/`tid` would be shadowed by CodeView's own properties
            // of those names and silently never assigned. The wrapper takes the
            // row object and binds across explicitly.
            delegate: Item {
                id: slot
                required property var model
                required property int index
                readonly property alias view: cv

                anchors.fill: parent
                visible: index === win.current
                // An invisible item gets no input, so the hidden documents cannot
                // steal the keyboard — but they stay LOADED, which is the point.
                enabled: visible

                CodeView {
                    id: cv
                    anchors.fill: parent
                    tid: slot.model.tid
                    path: slot.model.path
                    docName: slot.model.name
                    // The initial value only; `Component.onCompleted` replaces it
                    // with what Python actually detected. Not left as a binding
                    // on the model role because it is then read back one way and
                    // written the other, and the two would fight.
                    lang: slot.model.lang
                    useTabs: win.useTabs
                    indentWidth: win.indentWidth
                    showNumbers: win.showNumbers
                    winActive: win.active
                    cellW: win.cellW
                    onStatusReported: (m) => win.status = m
                    onContextRequested: (x, y, pos) => win.showMenu(x, y, pos)

                    Component.onCompleted: {
                        cv.loadText(slot.model.seedText || "");
                        Buffers.setMeta(slot.model.tid, slot.model.eol || "\n",
                                        slot.model.encoding || "utf-8",
                                        slot.model.mtime || 0,
                                        slot.model.path, slot.model.final !== false);
                        // Drop the seed: it is a whole file's text and the model
                        // would keep a second copy of every open document alive.
                        tabs.setProperty(slot.index, "seedText", "");
                        cv.lang = Buffers.language(slot.model.tid);
                        tabs.setProperty(slot.index, "lang", cv.lang);
                        if (win.guessIndent) {
                            var g = Buffers.guessIndent(slot.model.tid);
                            if (g.guessed) {
                                win.useTabs = g.tabs;
                                win.indentWidth = g.width;
                            }
                        }
                        if (slot.model.pendingLine > 0) {
                            cv.goToLine(slot.model.pendingLine);
                            tabs.setProperty(slot.index, "pendingLine", 0);
                        }
                        if (slot.index === win.current) cv.focusEditor();
                    }
                }
            }
        }

        FindBar {
            id: findBar
            parent: stage
            winActive: win.active
            onRequery: win.refreshFind()
            onStep: (backward) => win.doStep(backward)
            onReplaceCurrent: win.doReplaceCurrent()
            onReplaceEverything: win.doReplaceAll()
            onClosed: win.closeFind()
        }

        PathBar {
            id: pathBar
            parent: stage
            winActive: win.active
            onAccepted: (p) => {
                if (pathBar.mode === "goto") {
                    var n = parseInt(p);
                    if (!isNaN(n) && n > 0 && win.view) win.view.goToLine(n);
                    else win.status = "not a line number: " + p;
                    pathBar.shown = false;
                    if (win.view) win.view.focusEditor();
                    return;
                }
                if (pathBar.mode === "saveas") {
                    if (Files.exists(p) && (win.current < 0
                            || tabs.get(win.current).path !== p)) {
                        // §10.2, never silently clobber: an existing file is a
                        // confirm, not a write.
                        pathBar.shown = false;
                        win.pendingSaveAs = p;
                        confirm.ask("overwrite " + win.baseName(p) + "?", p,
                                    "overwrite", "");
                        return;
                    }
                    pathBar.shown = false;
                    win.saveTab(win.current, p);
                    if (win.view) win.view.focusEditor();
                    return;
                }
                pathBar.shown = false;
                win.openPath(p, 0);
                if (win.view) win.view.focusEditor();
            }
            onCancelled: if (win.view) win.view.focusEditor()
        }

        CtxMenu {
            id: menu
            anchors.fill: parent
        }

        Confirm {
            id: confirm
            anchors.fill: parent
            winActive: win.active
            showDiscard: discardLabel !== ""

            onAccepted: {
                if (win.pendingSaveAs !== "") {
                    var p = win.pendingSaveAs;
                    win.pendingSaveAs = "";
                    win.saveTab(win.current, p);
                } else if (win.pendingReload >= 0) {
                    var i = win.indexOfTid(win.pendingReload);
                    win.pendingReload = -1;
                    win.reloadTab(i, true);
                } else if (win.pendingClose >= 0) {
                    var at = win.indexOfTid(win.pendingClose);
                    win.pendingClose = -1;
                    if (win.saveTab(at, "")) win.dropTab(at);
                }
            }
            onDiscarded: {
                if (win.pendingReload >= 0) {
                    // "keep mine" — the buffer wins; nothing is reloaded, and the
                    // next save will overwrite the version on disk.
                    win.pendingReload = -1;
                    win.status = "kept your version";
                } else if (win.pendingClose >= 0) {
                    var at = win.indexOfTid(win.pendingClose);
                    win.pendingClose = -1;
                    win.dropTab(at);
                }
            }
            onCancelled: {
                win.pendingClose = -1;
                win.pendingReload = -1;
                win.pendingSaveAs = "";
                if (win.view) win.view.focusEditor();
            }
        }
    }
    property string pendingSaveAs: ""

    // ---- the context menu (§7.1: everything selectable is right-clickable) --
    function showMenu(x, y, pos) {
        var v = win.view;
        if (!v) return;
        var hasSel = v.selEnd > v.selStart;
        // Spelling first, when the word under the pointer is actually
        // misspelled: it is why the menu was opened, and it comes with its own
        // trailing separator. Empty in a code file, and empty on a machine with
        // no dictionary — docs/DESIGN.md §10, an offered action must not be able
        // to silently do nothing.
        var items = v.spellItems(pos === undefined ? v.cursorPos : pos);
        items = items.concat([
            { label: "undo", enabled: v.canUndo, trigger: () => v.undo() },
            { label: "redo", enabled: v.canRedo, trigger: () => v.redo() },
            { separator: true },
            { label: "cut", enabled: hasSel, trigger: () => v.cut() },
            { label: "copy", enabled: hasSel, trigger: () => v.copy() },
            { label: "paste", trigger: () => v.paste() },
            { label: "select all", trigger: () => v.selectAll() },
            { separator: true },
            { label: "comment / uncomment", trigger: () => v.cmdComment() },
            { label: "indent", trigger: () => v.cmdIndent() },
            { label: "unindent", trigger: () => v.cmdUnindent() },
            { label: "duplicate line", trigger: () => v.cmdDuplicate() },
            { label: "delete line", trigger: () => v.cmdDeleteLine() },
            { separator: true },
            { label: win.useTabs ? "indent with spaces" : "indent with tabs",
              trigger: () => { win.useTabs = !win.useTabs;
                               Settings.set("useTabs", win.useTabs); } },
            { label: "indent width: " + win.indentWidth,
              trigger: () => win.showIndentMenu(x, y) },
            { label: "language: " + Buffers.language(tabs.get(win.current).tid),
              trigger: () => win.showLangMenu(x, y) },
            { separator: true },
            { label: "copy path", enabled: tabs.get(win.current).path !== "",
              trigger: () => Files.copy(tabs.get(win.current).path) },
            { label: "reload from disk", enabled: tabs.get(win.current).path !== "",
              trigger: () => win.reloadTab(win.current, false) }
        ]);
        menu.open(x, y, items);
    }

    function showIndentMenu(x, y) {
        var items = [];
        var widths = [2, 3, 4, 8];
        for (var i = 0; i < widths.length; i++) {
            const w = widths[i];
            items.push({ label: String(w) + (w === win.indentWidth ? "  <" : ""),
                         trigger: () => { win.indentWidth = w;
                                          Settings.set("indentWidth", w); } });
        }
        menu.open(x, y, items);
    }

    function showLangMenu(x, y) {
        var langs = Buffers.languages();
        var cur = Buffers.language(tabs.get(win.current).tid);
        var items = [];
        for (var i = 0; i < langs.length; i++) {
            const k = langs[i].key;
            items.push({ label: langs[i].name + (k === cur ? "  <" : ""),
                         trigger: () => {
                             Buffers.setLanguage(tabs.get(win.current).tid, k);
                             tabs.setProperty(win.current, "lang", k);
                             if (win.view) {
                                 win.view.lang = k;
                                 // Spelling follows the language: switching a
                                 // file to `text` is how a code file gets
                                 // checked (CodeView -> "spelling").
                                 win.view.refreshSpell();
                             }
                             win.tabRev++;
                         } });
        }
        menu.open(x, y, items);
    }

    // ---- global keys -----------------------------------------------------
    // Window-scoped `Shortcut`s, not cases in an item's Keys handler: these have
    // to work while the focus is in the code, the find field or the path prompt
    // (§11.2 states it for Ctrl+F and the reasoning covers all of them).
    Shortcut { sequence: "Ctrl+N"; onActivated: win.newFile() }
    Shortcut { sequence: "Ctrl+O"; onActivated: pathBar.openPrompt("open", win.dirName()) }
    Shortcut { sequence: "Ctrl+S"; onActivated: win.saveTab(win.current, "") }
    Shortcut { sequence: "Ctrl+Shift+S"; onActivated: win.promptSaveAs() }
    Shortcut { sequence: "Ctrl+W"; onActivated: win.closeTab(win.current) }
    Shortcut { sequence: "Ctrl+Q"; onActivated: win.close() }
    Shortcut { sequence: "Ctrl+F"; onActivated: win.openFind(false) }
    Shortcut { sequence: "Ctrl+R"; onActivated: win.openFind(true) }
    Shortcut { sequence: "Ctrl+G"; onActivated: pathBar.openPrompt("goto", "") }
    Shortcut { sequence: "F3"; onActivated: win.doStep(false) }
    Shortcut { sequence: "Shift+F3"; onActivated: win.doStep(true) }
    Shortcut { sequence: "Ctrl+PgDown"; onActivated: win.current = (win.current + 1) % Math.max(1, tabs.count) }
    Shortcut { sequence: "Ctrl+PgUp"; onActivated: win.current = (win.current + Math.max(1, tabs.count) - 1) % Math.max(1, tabs.count) }
    Shortcut { sequence: "Alt+Right"; onActivated: win.current = (win.current + 1) % Math.max(1, tabs.count) }
    Shortcut { sequence: "Alt+Left"; onActivated: win.current = (win.current + Math.max(1, tabs.count) - 1) % Math.max(1, tabs.count) }

    // A status line is a report, not a permanent label: it clears itself so the
    // footer goes back to saying where the caret is.
    onStatusChanged: if (status !== "") statusClear.restart()
    Timer {
        id: statusClear
        interval: 4000
        onTriggered: win.status = ""
    }

    // Files dropped on the window open as documents. QUrl does the decoding, in
    // Python (`Files.localPaths`), for the reason filer learned the hard way.
    DropArea {
        anchors.fill: parent
        onDropped: (drop) => {
            var ps = Files.localPaths(drop.urls);
            if (ps.length === 0) { drop.accepted = false; return; }
            for (var i = 0; i < ps.length; i++) win.openPath(ps[i], 0);
        }
    }
}
