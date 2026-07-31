import QtQuick
import QtQuick.Controls.Basic
import "../../qmlcommon"

// ONE browsing pane: the whole file browser — tree, preview grid, selection,
// context menu, drop target, dialogs — as a component, so `Main.qml` can put
// two of them side by side (split view). It used to be an inline
// `Rectangle { id: view }` filling the window, which is exactly what a single
// unsplit pane still is; the id stayed `view` so every internal reference
// reads the same as it did.
//
// Everything the pane needs from outside comes in as a property — it must not
// reach for `win`, or the second instance would fight the first over the
// window's chrome:
//
//   startPath   where this pane opens
//   winActive   the WINDOW's focus (the greyed "inactive" tone), not the pane's
//   paneFocused whether the titlebar acts on THIS pane (the accent frame is
//               drawn by Main, over the pane)
//   picking     file-picker mode (see ../pick.py); a picker is never split
//   primary     the left pane, which owns the persisted dir/sort/hidden state
//   watchKey    this pane's slot in the shared DirWatch (see main.py) — two
//               panes watch two different sets and setDirs() is keyed, or the
//               second pane's rebuild would silently unwatch the first's dirs
//
// and `focusClaimed` goes back the other way: any press in here means "the
// chrome is talking to this pane now".

Rectangle {
    id: view
    color: Theme.bg

    // ---- what the window supplies (see the header) ----
    property string startPath: ""
    property bool winActive: true
    property bool paneFocused: true
    property bool picking: false
    property bool primary: true
    property string watchKey: "main"
    signal focusClaimed()
    // Called from every press site in here. Cheap and idempotent: the window
    // ignores it unless the focus actually moves.
    function claimFocus() { if (!paneFocused) focusClaimed(); }
    // The titlebar's "+" and "r" open dialogs that live in here, and a pane's
    // ids are not reachable from Main — so they are opened through the pane,
    // and a dialog is always the FOCUSED pane's.
    function openNewDialog() { newDlg.open(); }
    function openRenameDialog() {
        if (selection.length !== 1) return;
        renameDlg.value = dirNameOf(selected);
        renameDlg.open();
    }

    property string path: view.startPath

    // ---- selection ----
    // `selection` is the full set of selected absolute paths (an array, so
    // the delegates can bind `indexOf` reactively); `selected` is the
    // primary/anchor path used by single-item ops (rename) and titlebar
    // state; `anchor` is where a shift-range extends FROM. Range selection
    // works across the whole view — the preview grid's images then the tree
    // rows, in `orderPaths()` order — so shift-clicking spans both.
    property var selection: []
    property string selected: ""        // primary (anchor) selected path
    property string anchor: ""          // shift-range anchor
    property bool selectedIsDir: false
    property var clip: null             // { op:"copy"|"cut", paths:[...] }
    property var pendingPaste: null     // conflicting {src,dst} items awaiting overwrite confirm
    property var pendingRename: null     // {src,dst} awaiting overwrite confirm

    // Run a batch of {src,dst} transfers. `op` is "cut" (move), "copy" or
    // "link" (symlink). `overwrite` false adds the no-clobber flag so an
    // existing target is skipped rather than replaced (the safe default);
    // true lets it replace (after the user OK'd it).
    //
    // One item is one process, so ten pasted files are ten exit codes — and
    // three of them failing must read as "3 of 10 failed", not as a flat
    // success and not as a flat failure. `beginBatch`/`endBatch` (main.py) group
    // them into ONE failure toast with that count. Both calls are mandatory:
    // without `endBatch` a failure is collected and never reported.
    function runPaste(items, op, overwrite) {
        if (!items.length) return;
        const batch = FileOps.beginBatch(op === "cut" ? "move"
                                       : op === "link" ? "link" : "copy");
        for (let i = 0; i < items.length; i++) {
            const reselect = i === items.length - 1 ? items[i].dst : "";
            const s = items[i].src, d = items[i].dst;
            if (op === "cut")       FileOps.run(overwrite ? ["mv", "--", s, d]
                                                          : ["mv", "-n", "--", s, d], reselect, batch);
            else if (op === "link") FileOps.run(overwrite ? ["ln", "-sfn", "--", s, d]
                                                          : ["ln", "-s", "--", s, d], reselect, batch);
            else                    FileOps.run(overwrite ? ["cp", "-a", "--", s, d]
                                                          : ["cp", "-an", "--", s, d], reselect, batch);
        }
        FileOps.endBatch(batch);
    }

    // Move/copy/link an explicit list of sources into `dst`. Splits into
    // names that are free vs. already-taken at the target: free ones go
    // immediately; conflicts wait for an overwrite OK so a transfer can
    // never silently clobber a file. Returns whether it raised that confirm
    // (the caller may have cleanup to defer until the dialog answers).
    // Shared by paste (clipboard) and drop (drag-and-drop).
    function transferInto(paths, dst, op, clearClip) {
        const clear = [], conflicts = [];
        for (let i = 0; i < paths.length; i++) {
            const src = paths[i];
            const d = join(dst, dirNameOf(src));
            (FileOps.pathExists(d) ? conflicts : clear).push({ src: src, dst: d });
        }
        runPaste(clear, op, true);
        if (!conflicts.length) return false;
        pendingPaste = { items: conflicts, op: op, clearClip: clearClip };
        overwriteDlg.text = conflicts.length + " item(s) already exist here — overwrite?";
        overwriteDlg.open();
        return true;
    }

    // Paste the clipboard into `dst`. A cut's clipboard is spent once the
    // move actually happens — which is on the dialog's answer when anything
    // conflicted, hence the `clearClip` hand-off rather than clearing here.
    // (Shared by the titlebar "p" button and the context menu.)
    function pasteInto(dst) {
        if (clip === null) return;
        const cut = clip.op === "cut";
        if (!transferInto(clip.paths, dst, clip.op, cut) && cut) clip = null;
    }

    function clearSelection() { selection = []; selected = ""; anchor = ""; }
    function isSelected(p) { return selection.indexOf(p) >= 0; }

    // ---- drag-out ----
    // What a drag starting on `p` carries: the WHOLE selection when `p` is
    // part of a multi-selection, otherwise just `p` — the ordinary file
    // manager rule. (The press handlers cooperate: pressing inside an
    // existing multi-selection defers collapsing it to the release, so the
    // drag that may follow still has the whole set to hand.)
    function dragPaths(p) {
        return (selection.length > 1 && isSelected(p)) ? selection.slice() : [p];
    }

    // ---- drop target ----
    // The directory a drop lands in: the directory under the cursor, the
    // parent of a file under the cursor, or the current dir over empty
    // space. Set while a drag hovers, "" otherwise (the rows and the frame
    // below highlight off it).
    property string dropTarget: ""

    function dropDirAt(x, y) {
        const e = entryAt(x, y);
        if (!e) return path;
        return e.isDir ? e.path : parentOf(e.path);
    }

    // The sources a drop of `paths` into `dst` may actually act on. Three
    // things are dropped silently rather than run as a no-op or a
    // filesystem-eating recursion: a source already sitting in `dst`, a
    // directory dropped onto itself, and a directory dropped into its own
    // subtree.
    function dropCandidates(paths, dst) {
        const d = dst.replace(/\/+$/, "") || "/";
        const out = [];
        for (let i = 0; i < paths.length; i++) {
            const src = paths[i].replace(/\/+$/, "");
            if (src === "" || src[0] !== "/") continue;
            if (parentOf(src) === d) continue;              // already here
            if (d === src || d.indexOf(src + "/") === 0) continue;  // into itself
            out.push(src);
        }
        return out;
    }

    // Ask what the drop meant. A drag carries no reliable move-vs-copy
    // signal between two windows here — the modifier keys never reach the
    // DESTINATION process (Wayland keeps keyboard focus on the drag source,
    // a different process entirely), and the compositor does not vary the
    // proposed action by modifier — so guessing would mean silently moving
    // files on a hunch. Dolphin asks with exactly this menu; so do we.
    function askDrop(srcs, dst, x, y) {
        const n = srcs.length > 1 ? " " + srcs.length + " items" : " \"" + dirNameOf(srcs[0]) + "\"";
        ctxMenu.open(x, y, [
            { label: "to " + (dirNameOf(dst) || "/") + "/", enabled: false },
            { separator: true },
            { label: "move" + n + " here", trigger: () => transferInto(srcs, dst, "cut",  false) },
            { label: "copy" + n + " here", trigger: () => transferInto(srcs, dst, "copy", false) },
            { label: "link" + n + " here", trigger: () => transferInto(srcs, dst, "link", false) },
            { separator: true },
            { label: "cancel" },
        ]);
    }

    // The flat top-to-bottom order of every selectable item: the preview
    // grid's images (Flow order == array order) followed by the tree rows.
    function orderPaths() {
        const out = [];
        for (let i = 0; i < images.length; i++) out.push(images[i].path);
        for (let i = 0; i < rows.length; i++) out.push(rows[i].path);
        return out;
    }
    function selectSingle(p, isDir) { selection = [p]; selected = p; anchor = p; selectedIsDir = isDir; }
    function selectToggle(p, isDir) {
        const s = selection.slice(), i = s.indexOf(p);
        if (i >= 0) s.splice(i, 1); else s.push(p);
        selection = s; selected = p; anchor = p; selectedIsDir = isDir;
    }
    function selectRange(p, isDir) {
        if (anchor === "") { selectSingle(p, isDir); return; }
        const ord = orderPaths(), a = ord.indexOf(anchor), b = ord.indexOf(p);
        if (a < 0 || b < 0) { selectSingle(p, isDir); return; }
        selection = ord.slice(Math.min(a, b), Math.max(a, b) + 1);
        selected = p; selectedIsDir = isDir;   // anchor left where it was
    }
    // A click on an item: plain replaces, Shift extends the range from the
    // anchor, Ctrl toggles the one item — the usual file-manager gestures.
    function clickSelect(p, isDir, mods) {
        if (mods & Qt.ShiftModifier) selectRange(p, isDir);
        else if (mods & Qt.ControlModifier) selectToggle(p, isDir);
        else selectSingle(p, isDir);
    }
    function selectAll() {
        const ord = orderPaths();
        selection = ord;
        if (ord.length) { selected = ord[0]; anchor = ord[0]; }
    }

    // ---- context menu ----
    // The entry (preview-grid image or tree row) under a view-space point,
    // or null for empty space. Uses the views' own indexAt hit-testing, so
    // the one right-click overlay covers tiles, rows and background alike.
    function entryAt(x, y) {
        if (hasImages) {
            const g = view.mapToItem(pgrid, x, y);
            if (g.x >= 0 && g.y >= 0 && g.x < pgrid.width && g.y < pgrid.height) {
                const i = pgrid.indexAt(g.x + pgrid.contentX, g.y + pgrid.contentY);
                return i >= 0 ? images[i] : null;
            }
        }
        if (hasRows) {
            const l = view.mapToItem(list, x, y);
            if (l.x >= 0 && l.y >= 0 && l.x < list.width && l.y < list.height) {
                const i = list.indexAt(l.x + list.contentX, l.y + list.contentY);
                return i >= 0 ? rows[i] : null;
            }
        }
        return null;
    }

    // Menu over an entry. Cut/copy/trash/delete act on the WHOLE selection
    // (the overlay ensures the clicked entry is part of it); open/open with/
    // paste-into target the entry itself. Rename needs exactly one selected.
    function entryMenuItems(e) {
        const one = selection.length === 1;
        const n = selection.length > 1 ? " (" + selection.length + ")" : "";
        const items = [
            { label: "open", trigger: () => e.isDir ? go(e.path) : openFile(e.path, e.kind) },
            { label: "open with...", trigger: () => { openWithDlg.targetPath = e.path; openWithDlg.open(); } },
        ];
        // videos get the "squeeze it under an upload limit" action. Only the
        // clicked entry, not the selection: each conversion is its own long
        // job with its own toast.
        if (!e.isDir && VideoConv.isVideo(e.path))
            items.push({ label: "compress to <10MB", trigger: () => compressVideo(e.path) });
        return items.concat(sendToPhoneItems()).concat([
            { separator: true },
            { label: "cut" + n,  trigger: () => { clip = { op: "cut",  paths: selection.slice() }; } },
            { label: "copy" + n, trigger: () => { clip = { op: "copy", paths: selection.slice() }; } },
            { label: e.isDir ? "paste into" : "paste", enabled: clip !== null,
              trigger: () => pasteInto(e.isDir ? e.path : path) },
            { separator: true },
            { label: "copy path", trigger: () => FileOps.copyText(selection.join("\n")) },
            { label: "rename...", enabled: one,
              trigger: () => { renameDlg.value = dirNameOf(selected); renameDlg.open(); } },
            { separator: true },
            { label: "trash" + n, trigger: () => { FileOps.run(["gio", "trash", "--"].concat(selection), ""); clearSelection(); } },
            { label: "delete..." + n, trigger: () => delDlg.open() },
        ]);
    }

    // "compress to <10MB": VideoConv.plan() decides everything (resolution,
    // bitrate, encoder) and estimates the encode. It only asks first when
    // there's something worth asking about — a long encode, or a budget so
    // tight the result will look rough; anything quick and decent just runs.
    // Progress lives in a desktop toast either way, so nothing blocks here.
    function compressVideo(p) {
        const plan = VideoConv.plan(p);
        if (!plan.ok) { VideoConv.start(p); return; }   // start() toasts the reason
        if (plan.ask) { compressDlg.targetPath = p; compressDlg.text = plan.warning; compressDlg.open(); }
        else VideoConv.start(p);
    }

    // "send to phone" — KDE Connect, acting on the whole selection.
    //
    // ONE ENTRY PER DEVICE, named after the device. CtxMenu has no submenus, and
    // with one or two phones paired a flat row each is both shorter to reach and
    // more honest than "send to phone" over an invisible choice. The devices are
    // enumerated HERE, as the menu is built (Phone.devices() is a ~10ms
    // kdeconnect-cli call), never once at startup: a phone that walked out of
    // wifi range must leave the menu rather than linger as a row that fails.
    //
    // docs/DESIGN.md 10 decides the two empty cases: a row that would quietly do
    // nothing is not offered, so with nothing reachable — or nothing sendable —
    // the entry is greyed AND says which of the two it is. Sending is
    // FileOps.run like every other shell-out, so a failure is the same critical
    // toast a failed copy is (apps/filer/AGENTS.md, "File operations REPORT").
    function sendToPhoneItems() {
        const paths = Phone.sendable(selection);
        const devs = Phone.devices();
        if (devs.length === 0)
            return [{ label: "send to phone - no device reachable", enabled: false }];
        if (paths.length === 0)
            return [{ label: "send to phone - directories cannot be sent", enabled: false }];
        // The count is in the label rather than implied, so a 12-file send never
        // looks like a 1-file one; it counts the SENDABLE files, so a selection
        // of five files and a folder reads (5) and sends five.
        const n = paths.length > 1 ? " (" + paths.length + ")" : "";
        return devs.map(d => ({ label: "send to " + d.name + n,
                                trigger: () => sendToPhone(d.id, paths) }));
    }

    // One kdeconnect-cli per file, so a multi-file send is a BATCH exactly like
    // a multi-item paste: three failures out of ten report once, as
    // "send to phone: 3 of 10 failed", instead of ten separate toasts or none.
    // endBatch is mandatory — without it failures are collected and never shown.
    function sendToPhone(devId, paths) {
        const tok = FileOps.beginBatch("send to phone");
        for (let i = 0; i < paths.length; i++)
            FileOps.run(["kdeconnect-cli", "-d", devId, "--share", paths[i]], "", tok);
        FileOps.endBatch(tok);
    }

    // Menu over empty space: dir-level actions.
    function bgMenuItems() {
        return [
            { label: "new...", trigger: () => newDlg.open() },
            { label: "paste", enabled: clip !== null, trigger: () => pasteInto(path) },
            { separator: true },
            { label: "select all", enabled: rows.length + images.length > 0, trigger: () => selectAll() },
            { label: "copy path", trigger: () => FileOps.copyText(path) },
            { separator: true },
            { label: "open terminal here", trigger: () => FileOps.execDetached(["kitty", "--directory", path]) },
        ];
    }

    // tree state: the flat list of currently-visible rows, plus the set of
    // directory paths the user has expanded (persisted across refreshes so
    // an op doesn't collapse the tree).
    property var rows: []
    property var expandedPaths: new Set()

    // Image entries of the CURRENT dir, pulled out of `rows` and shown in a
    // thumbnail grid pinned above the list (the preview panel). Only the
    // current dir — images inside expanded subdirs stay inline as rows.
    property var images: []
    readonly property bool hasImages: images.length > 0
    // Whether the list has anything (dirs, non-image files, expanded subtrees).
    // When a dir is nothing but images, `rows` is empty and the bottom section
    // + splitter are hidden so the preview grid takes the whole window.
    readonly property bool hasRows: rows.length > 0

    // Height (px) of the preview panel above the list. User-adjustable by
    // dragging the splitter between the panel and the list; persisted across
    // runs (Settings "gridPanelH"). The panel caps at its own content height,
    // so a dir with only a few images shows a snug panel, not empty space.
    property int gridPanelH: startGridPanelH

    // The scrollbar is `qmlcommon/VScroll.qml` (imported above), not an inline
    // component here: docs/DESIGN.md 9.2 is one idiom for the whole desktop and
    // 19.1 listed this copy as a real divergence. Folded in 2026-07-28 with the
    // rewrite to the three pixel-era variants.

    // Open a file with the right thing for its kind: images go to `viewer`
    // (the standalone image/media viewer), the rest to xdg-open. (Dirs → go().)
    //
    // viewer would otherwise build its flip-through set by name-sorting the
    // file's directory itself, which contradicts what the user is looking at
    // the moment they have sorted by size or date. So hand it `orderPaths()`
    // — this window's exact top-to-bottom order — via FileOps.writeOrder, and
    // its ‹ / › walk that instead. It is a snapshot taken at launch: viewer
    // consumes the file, nothing watches it, so re-sorting filer while a
    // viewer is open deliberately leaves that viewer's order alone.
    // In picker mode "open" means "this is my answer" — double-clicking a
    // file returns it. Launching viewer/xdg-open from inside a dialog the
    // portal spawned would be both wrong and, for xdg-open, circular.
    function openFile(p, kind) {
        if (view.picking) {
            if (Picker.selectable(p)) { selectSingle(p, false); pickBar.submit(); }
            return;
        }
        if (kind === "image") {
            const order = FileOps.writeOrder(orderPaths());
            FileOps.execDetached(order ? ["viewer", "--order", order, p]
                                       : ["viewer", p]);
        }
        else FileOps.execDetached(["xdg-open", p]);
    }

    // sort state (driven by the header sort buttons). Grouping is always
    // hidden → dirs → files; sortField/sortAsc order within each group.
    property string sortField: startSortField   // "name" | "created" | "size"
    property bool sortAsc: startSortAsc
    function setSort(f) {
        if (sortField === f) sortAsc = !sortAsc;   // re-click flips direction
        else { sortField = f; sortAsc = true; }
        rebuild();
        persist();
    }

    // Whether dotfiles are listed. Toggled by the "h" strip button; when
    // off, hidden entries are filtered out of the tree entirely.
    property bool showHidden: startShowHidden
    function toggleHidden() { showHidden = !showHidden; rebuildKeepScroll(); persist(); }

    // Persist the last directory + sort + hidden toggle so filer reopens
    // how you left it (main.py's Settings writes ~/.local/state/filer/state.json).
    // A picker is a transient errand, not a browsing session: it must not
    // move where the user's own filer window reopens.
    //
    // Only the PRIMARY pane owns that state — one state file cannot hold two
    // panes' sort orders, and the left pane is the one an unsplit window
    // reopens as. The right pane persists just its directory, which is all
    // Main needs to put the split back where it was.
    function persist() {
        if (view.picking) return;
        if (view.primary) Settings.save(path, sortField, sortAsc, showHidden);
        else Settings.set("splitDir", path);
    }

    // total size of the files directly in the current dir (not recursive —
    // instant, no du). Shown at the bottom of the titlebar (via the window
    // title, rendered by the hyprvtb plugin).
    property real dirBytes: 0
    readonly property string dirSizeStr: sizeStr(dirBytes)
    function refreshDirSize() {
        const es = FileOps.listDir(path);
        let t = 0;
        for (let i = 0; i < es.length; i++) t += es[i].size;
        dirBytes = t;
    }

    function join(dir, name) { return dir.replace(/\/+$/, "") + "/" + name; }
    function parentOf(p) {
        const q = p.replace(/\/+$/, "");
        const i = q.lastIndexOf("/");
        return i > 0 ? q.substring(0, i) : "/";
    }
    function dirNameOf(p) {
        const q = p.replace(/\/+$/, "");
        const i = q.lastIndexOf("/");
        return i >= 0 ? q.substring(i + 1) : q;
    }

    // ---- tree model ----
    // Order one directory level: hidden entries first, then dirs, then files
    // (always), and within each group by the active sort field/direction.
    function sortEntries(entries) {
        const f = sortField, asc = sortAsc;
        const arr = entries.slice();
        arr.sort((a, b) => {
            const ga = a.hidden ? 0 : (a.isDir ? 1 : 2);
            const gb = b.hidden ? 0 : (b.isDir ? 1 : 2);
            if (ga !== gb) return ga - gb;   // group order is fixed
            let c;
            if (f === "size") c = a.size - b.size;
            else if (f === "created") c = a.created - b.created;
            else if (f === "modified") c = a.modified - b.modified;
            else c = 0;
            if (c === 0) {                    // name tie-break (and f==="name")
                const an = a.name.toLowerCase(), bn = b.name.toLowerCase();
                c = an < bn ? -1 : (an > bn ? 1 : 0);
            }
            return asc ? c : -c;
        });
        return arr;
    }

    // Recursively flatten `dir` into `out`, descending into any subdir whose
    // path is in expandedPaths. At depth 0 (the current dir) images are
    // diverted into `imgOut` instead of `out` — they render in the preview
    // grid, not the list. Reassigning `rows`/`images` at the end drives the view.
    function buildRows(dir, depth, out, imgOut) {
        const entries = sortEntries(FileOps.listDir(dir));
        for (let i = 0; i < entries.length; i++) {
            const e = entries[i];
            if (!view.showHidden && e.hidden) continue;   // "h" toggle: drop dotfiles
            // picker mode: narrow the listing to what the calling app asked
            // for. Directories always survive — they are how you navigate —
            // so `dir` mode leaves a pure folder tree. (pick.py::accepts)
            if (view.picking && !Picker.accepts(e.name, e.isDir)) continue;
            if (depth === 0 && e.kind === "image") { imgOut.push(e); continue; }
            const exp = e.isDir && view.expandedPaths.has(e.path);
            out.push({ name: e.name, path: e.path, isDir: e.isDir, kind: e.kind,
                       size: e.size, created: e.created, modified: e.modified,
                       depth: depth, expanded: exp });
            if (exp) buildRows(e.path, depth + 1, out, imgOut);
        }
    }
    function rebuild() {
        const out = [], imgs = [];
        buildRows(path, 0, out, imgs);
        rows = out; images = imgs;
        // keep the watch set in lock-step with what's on screen: the
        // current dir + every expanded subdir (deleted ones are dropped
        // python-side; a stale expandedPaths entry is harmless).
        // Keyed by this pane: DirWatch holds one set per pane and watches
        // their union, so the second pane's rebuild does not unwatch the
        // first pane's directories (setDirs used to replace the lot).
        DirWatch.setDirs(view.watchKey, [path].concat(Array.from(expandedPaths)));
    }
    function refresh() { rebuildKeepScroll(); }

    // Reassigning the model resets ListView.contentY to 0, which is right for
    // a cd but jarring for expand/collapse/refresh (the view jumps to the
    // top). Save and restore the scroll offset around those rebuilds.
    function rebuildKeepScroll() {
        const y = list.contentY;
        rebuild();
        // Clamp against originY: a ListView's content does not have to
        // start at contentY 0 once delegate sizes have changed under it
        // (expand/collapse does exactly that). Same fix as the players'
        // WheelScroll.qml, which carries the full explanation.
        list.contentY = Math.max(list.originY,
                                 Math.min(y, list.originY + list.contentHeight - list.height));
    }

    function toggleExpand(p) {
        if (expandedPaths.has(p)) expandedPaths.delete(p);
        else expandedPaths.add(p);
        rebuildKeepScroll();
    }

    // ---- directory history -------------------------------------------------
    // filer's reading of the desktop-global back/forward rule (docs/DESIGN.md §11):
    // "back" is the directory you were in, not the parent — the titlebar's `^`
    // already means parent, and the two are different journeys.
    //
    // The stack is PER PANE, because `path` is: going back in the pane you are
    // using must not move the other one. `go()` is the single choke point every
    // navigation already runs through (double-click, context-menu open, the `^`
    // button, the path bar), so recording there covers all four for free.
    NavHistory {
        id: navHist
        here: function () { return view.path; }
        onNavigate: function (p) { view._goTo(p); }
    }
    function goBack() { return navHist.back(); }
    function goForward() { return navHist.forward(); }

    function _goTo(p) { path = p; clearSelection(); rebuild(); refreshDirSize(); persist(); }
    function go(p) {
        if (p === path) return;     // re-opening the current dir is not a move
        navHist.record();
        _goTo(p);
    }

    Component.onCompleted: { rebuild(); refreshDirSize(); }
    // A closing pane (the split folding back to one) must hand its watch slot
    // back, or DirWatch keeps firing rebuilds for a directory nothing shows.
    Component.onDestruction: DirWatch.setDirs(view.watchKey, [])

    // integer byte size -> compact string (delegate helper)
    function sizeStr(b) {
        if (b < 1024) return b + "B";
        if (b < 1048576) return Math.round(b / 1024) + "K";
        if (b < 1073741824) return (b / 1048576).toFixed(1) + "M";
        return (b / 1073741824).toFixed(1) + "G";
    }
    // epoch seconds -> relative "N units ago" (delegate helper)
    function fmtRel(sec) {
        if (!sec) return "";
        let d = Date.now() / 1000 - sec;
        if (d < 0) d = 0;
        const u = (n, w) => n + " " + w + (n === 1 ? "" : "s") + " ago";
        if (d < 45) return "just now";
        if (d < 5400) return u(Math.max(1, Math.round(d / 60)), "minute");
        if (d < 79200) return u(Math.round(d / 3600), "hour");
        if (d < 2160000) return u(Math.round(d / 86400), "day");     // < ~25d
        if (d < 31557600) return u(Math.round(d / 2629800), "month");
        return u(Math.round(d / 31557600), "year");
    }

    // (the right strip that used to live here — sort buttons, file-op
    // buttons, dir-size readout — moved into the REAL compositor titlebar:
    // see tbButtons/Connections up top, and the dirSizeStr footer below.)

    // titlebar footer readout (drawn by the plugin at the bottom of the
    // inner column): the current dir's total size. Main pushes the FOCUSED
    // pane's — one titlebar, one footer.
    readonly property string footerStr: dirSizeStr

    // Clicking a pane points the titlebar at it. The rows, tiles, right-click
    // overlay and drop area all call claimFocus() themselves; this catches the
    // rest — a press on empty space below the last row. Declared FIRST, so it
    // is the bottom-most item and sees only what nothing above it wanted, and
    // it declines the press (`accepted = false`) rather than grabbing it, so
    // nothing about the existing gestures changes.
    MouseArea {
        anchors.fill: parent
        onPressed: (m) => { view.claimFocus(); m.accepted = false; }
    }

    // ---- preview panel: the current dir's images, in a VIRTUALIZED grid
    // above the list. A GridView (not the old Flow+Repeater, which realised
    // every tile up front) so only the cells on screen exist and only their
    // thumbnails are requested — a folder of thousands of images stays cheap,
    // the way Dolphin recycles item widgets. `cacheBuffer` prefetches ~2 rows
    // for smooth scrolling without an unbounded request storm.
    KineticGridView {
        id: pgrid
        anchors { top: parent.top; left: parent.left; right: parent.right; margins: 2 }
        // no list below → the panel takes the whole window; otherwise it's the
        // user's splitter height, capped at the grid's own content height.
        height: !view.hasImages ? 0
                : !view.hasRows ? (view.height - 4)
                : Math.min(view.gridPanelH, contentHeight)
        visible: view.hasImages
        clip: true
        model: view.images
        cellWidth: 100
        cellHeight: 100
        cacheBuffer: cellHeight * 2
        wheelLines: 1
        wheelStep: cellHeight
        ScrollBar.vertical: VScroll {}

        delegate: Item {
            id: cell
            required property var modelData
            width: pgrid.cellWidth
            height: pgrid.cellHeight
            PreviewTile {
                anchors.centerIn: parent
                entry: cell.modelData
                winActive: view.winActive
                selected: view.selection.indexOf(cell.modelData.path) >= 0
                dragPaths: view.dragPaths(cell.modelData.path)
                inMultiSelection: view.selection.length > 1 && selected
                onClicked: (mods) => { view.claimFocus(); view.clickSelect(cell.modelData.path, false, mods); }
                onOpened: view.openFile(cell.modelData.path, cell.modelData.kind)
            }
        }
    }

    // splitter: drag to trade height between the preview panel and the list.
    // Sets gridPanelH to the pointer's y (in `view` coords), clamped so both
    // areas keep a usable minimum; the new height is persisted on release.
    MouseArea {
        id: splitter
        anchors { top: pgrid.bottom; left: parent.left; right: parent.right }
        height: (view.hasImages && view.hasRows) ? 7 : 0
        visible: view.hasImages && view.hasRows
        hoverEnabled: true
        cursorShape: Qt.SplitVCursor
        preventStealing: true
        onPositionChanged: (m) => {
            if (!pressed) return;
            const y = splitter.mapToItem(view, m.x, m.y).y;
            view.gridPanelH = Math.max(pgrid.cellHeight / 2,
                                       Math.min(y - 2, view.height - 90));
        }
        onReleased: Settings.set("gridPanelH", view.gridPanelH)
        Rectangle {
            anchors.fill: parent
            color: splitter.pressed ? Theme.highlight : "transparent"
            Rectangle {
                anchors.centerIn: parent
                width: 28; height: 2
                color: (splitter.containsMouse || splitter.pressed) ? Theme.accent : Theme.border
            }
        }
    }

    // ---- tree list ----
    // (No in-window location bar any more — the editable path lives in the
    // titlebar address bar, and "up" is the "^" titlebar button.)
    KineticListView {
        id: list
        anchors { top: splitter.bottom; left: parent.left; right: parent.right; bottom: pickBar.top; margins: 2 }
        visible: view.hasRows
        clip: true
        model: view.rows
        ScrollBar.vertical: VScroll {}

        delegate: Rectangle {
            id: row
            required property var modelData
            required property int index
            width: list.width
            // terminal-style file list: one kitty cell per entry — row height
            // IS the font line box (text-only), vs the old fixed 22px
            height: Theme.fontSize
            readonly property string abs: modelData.path
            readonly property int indent: modelData.depth * 14
            // a directory row the cursor is over during a drag: it, not the
            // current dir, is where a drop would land.
            readonly property bool isDropTarget: view.dropTarget === abs && modelData.isDir
            color: isDropTarget ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.35)
                 : view.selection.indexOf(abs) >= 0 ? Theme.highlight : "transparent"

            // Drag-out: hand this file to other apps as a text/uri-list, so
            // it can be dropped onto a browser upload field, another file
            // manager, or another filer window (the DropArea below) — the
            // standard desktop "drag a file out" gesture.
            // Binding Drag.active to the MouseArea's drag (which drags an
            // INVISIBLE proxy, so the row itself stays put) is what actually
            // starts the real cross-app QDrag under dragType Automatic — a
            // bare Drag.startDrag() didn't initiate one on Wayland.
            // mimeData is filled on PRESS, not bound: the payload depends on
            // the selection, and a binding would re-run FileOps.uriList for
            // every realised row on every selection change.
            Drag.active: rowMa.drag.active
            Drag.dragType: Drag.Automatic
            Drag.supportedActions: Qt.CopyAction | Qt.MoveAction | Qt.LinkAction
            Drag.hotSpot.x: 6
            Drag.hotSpot.y: 6

            // the MouseArea drags THIS (invisible, zero-size) proxy instead
            // of the row, so drag.active flips on without the row moving.
            Item { id: dragProxy }

            // the little chip that follows the cursor while dragging: the
            // filename on a small badge, grabbed into Drag.imageSource on
            // press (layer + off-screen so grabToImage always renders it).
            // LATER (file previews): swap this chip's content for a small
            // thumbnail of the preview.
            Rectangle {
                id: dragBadge
                x: -10000
                width: Math.min(badgeText.implicitWidth + 16, 320)
                height: badgeText.implicitHeight + 10
                color: Theme.bgAlt
                border.color: Theme.accent
                border.width: 1
                layer.enabled: true
                PixelText {
                    id: badgeText
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 8; rightMargin: 8 }
                    elide: Text.ElideMiddle
                    text: view.selection.length > 1 && view.isSelected(row.abs)
                          ? view.selection.length + " items" : row.modelData.name
                    color: Theme.text
                }
            }

            // row-wide select / open / drag-out. Declared first so the expand
            // toggle (declared last → higher z) wins clicks in its own area.
            MouseArea {
                id: rowMa
                anchors.fill: parent
                // preventStealing so nothing above can grab the press-drag
                // and scroll instead of starting the file drag. (The list is
                // a KineticListView, so its own flicking is already off; the
                // wheel/trackpad scrolls it.)
                preventStealing: true
                drag.target: dragProxy
                // A press inside an EXISTING multi-selection must not
                // collapse it — the drag that may follow has to carry the
                // whole set. So that click is deferred to the release, and
                // only applied if no drag happened. `dragged` latches on the
                // way in because drag.active is already back to false by the
                // time onReleased runs.
                property bool deferSelect: false
                property bool dragged: false
                drag.onActiveChanged: if (rowMa.drag.active) rowMa.dragged = true;
                onPressed: (m) => {
                    view.claimFocus();
                    rowMa.dragged = false;
                    rowMa.deferSelect = !(m.modifiers & (Qt.ShiftModifier | Qt.ControlModifier))
                                        && view.selection.length > 1 && view.isSelected(row.abs);
                    if (!rowMa.deferSelect)
                        view.clickSelect(row.abs, row.modelData.isDir, m.modifiers);
                    // the payload is the selection now that it has settled
                    row.Drag.mimeData = { "text/uri-list": FileOps.uriList(view.dragPaths(row.abs)) };
                    // stage the drag image; ready by the time the drag passes
                    // the threshold and Drag.active turns on
                    dragBadge.grabToImage(function(res) { row.Drag.imageSource = res.url; });
                }
                onReleased: {
                    if (rowMa.deferSelect && !rowMa.dragged)
                        view.selectSingle(row.abs, row.modelData.isDir);
                    rowMa.deferSelect = false;
                }
                onDoubleClicked: {
                    if (row.modelData.isDir) view.go(row.abs);
                    else view.openFile(row.abs, row.modelData.kind);
                }
            }

            // tree guide lines: one vertical rule per ancestor level, aligned
            // under that ancestor's expand toggle, so an expanded subtree
            // reads as a connected branch.
            Repeater {
                model: row.modelData.depth
                Rectangle {
                    required property int index
                    width: 1
                    height: row.height
                    x: 6 + index * 14 + 8
                    color: Theme.border
                }
            }

            PixelText {
                id: nameText
                anchors { left: parent.left; leftMargin: 6 + row.indent + 20; right: szText.left; rightMargin: 4; verticalCenter: parent.verticalCenter }
                elide: Text.ElideRight
                text: row.modelData.name
                color: !view.winActive ? Theme.inactive : (row.modelData.isDir ? Theme.accent : Theme.text)
            }
            // columns: size | modified | created. The timestamps are fixed
            // widths so they line up across rows; the SIZE is intrinsic, and
            // that is deliberate — see below. Dirs show no size but keep their
            // timestamps.
            //
            // A pane is half a window wide in split view, and three fixed
            // columns left the NAME — the one thing you are reading — elided to
            // nothing. So the timestamp columns drop out, widest-first, when the
            // pane cannot afford them: width 0 rather than `visible: false`,
            // because the next column anchors to this one's left edge and an
            // invisible item still occupies its geometry.
            readonly property bool wideCols: row.width > 620
            readonly property bool midCols: row.width > 470
            // The size is the ONE column whose width is its text's, not a fixed
            // slot: it is right-anchored, so every size still ends on the same
            // pixel — a fixed 52px slot bought nothing but dead space to the
            // LEFT of a short size, and the name (the thing you are reading)
            // elided into it. A directory has no size at all, so a listing of
            // directories reserved a whole empty column and truncated every
            // name by 60px for it. Intrinsic width hands that slack back to the
            // name, per row, and also stops the widest size ("1023.9G", 7 cells)
            // clipping against the 52.
            PixelText {
                id: szText
                width: implicitWidth
                horizontalAlignment: Text.AlignRight
                anchors { right: modifiedText.left; rightMargin: row.midCols ? 12 : 8; verticalCenter: parent.verticalCenter }
                text: row.modelData.isDir ? "" : view.sizeStr(row.modelData.size)
                color: !view.winActive ? Theme.inactive : Theme.textDim
            }
            PixelText {
                id: modifiedText
                width: row.midCols ? 146 : 0
                visible: row.midCols
                elide: Text.ElideRight
                anchors { right: createdText.left; rightMargin: row.wideCols ? 12 : 0; verticalCenter: parent.verticalCenter }
                text: "m: " + view.fmtRel(row.modelData.modified)
                color: !view.winActive ? Theme.inactive : Theme.textDim
            }
            PixelText {
                id: createdText
                width: row.wideCols ? 146 : 0
                visible: row.wideCols
                elide: Text.ElideRight
                anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                text: "c: " + view.fmtRel(row.modelData.created)
                color: !view.winActive ? Theme.inactive : Theme.textDim
            }

            // expand/collapse toggle, in the slot where the [ ] brackets were.
            MouseArea {
                visible: row.modelData.isDir
                width: 16; height: 16
                anchors { left: parent.left; leftMargin: 6 + row.indent; verticalCenter: parent.verticalCenter }
                cursorShape: Qt.PointingHandCursor
                onClicked: view.toggleExpand(row.abs)
                PixelText {
                    anchors.centerIn: parent
                    text: row.modelData.expanded ? "-" : "+"
                    color: !view.winActive ? Theme.inactive : Theme.accent
                }
            }
        }
    }

    // ---- picker bar ----
    // Anchored to the bottom and given zero height when not picking, so an
    // ordinary filer window lays out exactly as before (the list anchors to
    // pickBar.top either way). `picked` is the selection filtered down to
    // what this mode can actually return — files for "open", folders for
    // "dir" — so selecting a folder in a file picker greys accept rather
    // than returning something the app cannot use.
    PickerBar {
        id: pickBar
        visible: view.picking
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: view.picking ? implicitHeight : 0
        winActive: view.winActive
        currentDir: view.path
        picked: {
            if (!view.picking) return [];
            return view.selection.filter(p => Picker.selectable(p));
        }
    }

    // Enter accepts, Escape cancels — the two keys every file dialog owes
    // the user. Only bound while picking, so they stay free in the browser.
    Shortcut {
        enabled: view.picking
        sequences: [StandardKey.Cancel]
        onActivated: Picker.cancel()
    }
    Shortcut {
        enabled: view.picking
        sequences: ["Return", "Enter"]
        onActivated: pickBar.submit()
    }

    // ---- right-click layer ----
    // One overlay catches every right-click (RightButton ONLY — left
    // presses, drags and wheel pass straight through to the views) and
    // hit-tests via entryAt(): a tile/row gets the entry menu, blank space
    // the dir menu. Right-clicking an unselected entry selects it first;
    // right-clicking inside a multi-selection keeps it, so the menu's
    // cut/copy/trash act on the whole set — the usual gesture. Disabled
    // while a dialog is up (their scrims only swallow left-clicks).
    MouseArea {
        id: ctxArea
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        enabled: !newDlg.visible && !renameDlg.visible && !openWithDlg.visible
                 && !overwriteDlg.visible && !renameOverwriteDlg.visible && !delDlg.visible
                 && !compressDlg.visible
        onPressed: (m) => {
            view.claimFocus();
            const e = view.entryAt(m.x, m.y);
            if (e) {
                if (!view.isSelected(e.path)) view.selectSingle(e.path, e.isDir);
                else { view.selected = e.path; view.selectedIsDir = e.isDir; }
                ctxMenu.open(m.x, m.y, view.entryMenuItems(e));
            } else {
                ctxMenu.open(m.x, m.y, view.bgMenuItems());
            }
        }
    }
    // ---- drop layer ----
    // The receiving half of the drag-out the rows and tiles already do:
    // anything offering local file URLs — another filer window, Dolphin, a
    // browser's "drag this download out" — can be dropped here. One
    // DropArea over the whole view, hit-tested with the same entryAt() the
    // right-click overlay uses, so a drop can target a directory row, a
    // directory in an expanded subtree, or the current dir (empty space).
    //
    // It is an Item with no input handling of its own, so it does not
    // shadow the views, the right-click overlay or the splitter — a
    // DropArea only ever sees drag events.
    DropArea {
        id: dropArea
        anchors.fill: parent
        onEntered: (drag) => view.dropTarget = view.dropDirAt(drag.x, drag.y)
        onPositionChanged: (drag) => view.dropTarget = view.dropDirAt(drag.x, drag.y)
        onExited: view.dropTarget = ""
        onDropped: (drop) => {
            const dst = view.dropDirAt(drop.x, drop.y);
            view.dropTarget = "";
            const srcs = view.dropCandidates(FileOps.urlsToPaths(drop.urls), dst);
            // Nothing local, or nothing that isn't already where it landed:
            // decline, so the source shows a refused drop rather than us
            // popping a menu with nothing behind it.
            if (!srcs.length) { drop.accepted = false; return; }
            drop.acceptProposedAction();
            // the menu that follows is this pane's, so the chrome had better
            // be pointed here — dragging INTO the other pane is the whole
            // point of the split.
            view.claimFocus();
            view.askDrop(srcs, dst, drop.x, drop.y);
        }
    }

    // Drop feedback for the CURRENT dir (empty space / no row under the
    // cursor): a frame around the whole view. A drop onto a directory row
    // highlights that row instead — see the list delegate.
    Rectangle {
        anchors.fill: parent
        visible: dropArea.containsDrag && view.dropTarget === view.path
        color: "transparent"
        border.width: 2
        border.color: Theme.accent
        z: 2000
    }

    // objectName so tools/drop-test.py can find it offscreen (the drop menu
    // is the only visible outcome of a drop it can assert on).
    CtxMenu { id: ctxMenu; objectName: "ctxMenu"; anchors.fill: parent }

    // ---- modal dialogs (simple centered prompts) ----
    BrowserPrompt {
        id: newDlg
        title: "new folder name"
        onAccepted: (t) => { if (t) FileOps.run(["mkdir", "--", view.join(view.path, t)], view.join(view.path, t)); }
    }
    BrowserPrompt {
        id: renameDlg
        title: "rename to"
        onAccepted: (t) => {
            if (!t) return;
            const dst = view.join(view.parentOf(view.selected), t);
            if (dst === view.selected) return;               // unchanged name
            if (FileOps.pathExists(dst)) {                    // don't clobber silently
                view.pendingRename = { src: view.selected, dst: dst };
                renameOverwriteDlg.text = "\"" + t + "\" already exists — overwrite?";
                renameOverwriteDlg.open();
            } else {
                FileOps.run(["mv", "--", view.selected, dst], dst);
            }
        }
    }
    // Overwrite confirmations for paste / rename: only reached when a target
    // name is already taken, so a file op can never silently destroy data.
    BrowserConfirm {
        id: overwriteDlg
        danger: true
        confirmLabel: "overwrite"
        onConfirmed: {
            if (view.pendingPaste) {
                view.runPaste(view.pendingPaste.items, view.pendingPaste.op, true);
                if (view.pendingPaste.clearClip) view.clip = null;
                view.pendingPaste = null;
            }
        }
        onDismissed: { if (view.pendingPaste && view.pendingPaste.clearClip) view.clip = null; view.pendingPaste = null; }
    }
    BrowserConfirm {
        id: renameOverwriteDlg
        danger: true
        confirmLabel: "overwrite"
        onConfirmed: {
            if (view.pendingRename) {
                FileOps.run(["mv", "--", view.pendingRename.src, view.pendingRename.dst], view.pendingRename.dst);
                view.pendingRename = null;
            }
        }
        onDismissed: view.pendingRename = null
    }
    // "open with…": run the typed command with the right-clicked path
    // appended (splitting the input on whitespace, so "mpv --loop" works).
    BrowserPrompt {
        id: openWithDlg
        property string targetPath: ""
        title: "open with (command)"
        onAccepted: (t) => {
            t = t.trim();
            if (t) FileOps.execDetached(t.split(/\s+/).concat([openWithDlg.targetPath]));
        }
    }
    // slow-conversion confirm: only shown when VideoConv's estimate crosses
    // its "quick" threshold, so a short clip never asks. Neutral, not danger
    // — it writes a NEW file beside the source and touches nothing else.
    BrowserConfirm {
        id: compressDlg
        property string targetPath: ""
        confirmLabel: "compress"
        onConfirmed: if (targetPath) VideoConv.start(targetPath)
    }
    // permanent delete (the context menu's "delete…"; trash is the safe
    // default elsewhere). Acts on the whole selection.
    BrowserConfirm {
        id: delDlg
        danger: true
        confirmLabel: "delete"
        text: view.selection.length > 1
              ? "permanently delete " + view.selection.length + " items?"
              : "permanently delete?\n" + view.dirNameOf(view.selected)
        onConfirmed: { FileOps.run(["rm", "-rf", "--"].concat(view.selection), ""); view.clearSelection(); }
    }
}
