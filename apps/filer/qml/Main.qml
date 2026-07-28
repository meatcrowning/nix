import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic
import "../../qmlcommon"

// Standalone port of the Quickshell panel's FileBrowser.qml. Runs as its own
// PySide6 process (main.py), so Quickshell config hot-reloads no longer restart
// it. It's a real Wayland Window, so the hyprvtb plugin still gives it the same
// vertical titlebar / drag / edge-resize / minimize as every other window.
//
// The list is a lazy tree: each row carries a depth, and directories can be
// expanded in place (the toggle to the left of the name). Rows come from
// `FileOps.listDir` (main.py); file operations go through `FileOps.run` /
// `execDetached`, argv arrays only, so paths with spaces/metachars are safe.
// `Theme` is a pragma-singleton (qml/qmldir); `FileOps` is a context property.
Window {
    id: win

    // startDir is a context property from main.py (the arg-given dir, or home).
    property string startPath: startDir

    // Focus-aware foreground: while the window is unfocused, controls and text
    // grey to the SAME tone the hyprvtb titlebar fades to (Theme.inactive), so
    // filer reads as "inactive" in lock-step with its titlebar.
    readonly property color fgAccent: win.active ? Theme.accent : Theme.inactive
    readonly property color fgText:   win.active ? Theme.text  : Theme.inactive

    // In picker mode the window IS the file dialog (`filer --pick`, see
    // ../pick.py): same tree, same navigation, plus the bar along the bottom.
    // Every picker branch in this file is gated on this, which is false in an
    // ordinary filer window.
    readonly property bool picking: Picker.active

    // The window title IS the address bar: the hyprvtb plugin renders it as an
    // editable path field (setTitleEdit below), same as surfer's URL bar. It
    // mirrors the current directory and, on submit, navigates there.
    title: view.path
    width: 720
    height: 460
    minimumWidth: 540
    // tall enough that the right strip's sort + operation buttons (3 + 7 cells)
    // always clear the dir-size readout pinned at its bottom
    minimumHeight: 400
    visible: true
    color: Theme.bg

    onClosing: Qt.quit()

    // ---- hyprvtb titlebar buttons (the old right strip, now native) ----
    // The sort + file-op buttons live in the REAL compositor titlebar: hyprvtb
    // draws a double-wide bar on every window and this registers filer's
    // buttons for its inner column (Titlebar bridge in main.py → the plugin's
    // socket). Labels and states are plain data — this array re-evaluates
    // whenever the view state it references changes, and every change pushes a
    // full re-registration (cheap: one line on a Unix socket).
    // state: 0 normal, 1 active/lit, 2 disabled ("-" spacers dropped — the
    // column reads cleaner as one uniform grid).
    readonly property var tbButtons: {
        const sort = (f, l, tip) => ({ id: "sort-" + f,
                                       label: view.sortField === f ? l + (view.sortAsc ? "↑" : "↓") : l,
                                       state: view.sortField === f ? 1 : 0, tip: tip });
        // enabled when anything's selected; rename needs exactly one.
        const sel = view.selection.length > 0 ? 0 : 2;
        const selOne = view.selection.length === 1 ? 0 : 2;
        return [
            // up-a-directory, pinned above the sort/op grid (disabled at "/").
            { id: "up", label: "^", state: view.path === "/" ? 2 : 0, tip: "up a directory" },
            sort("name", "n", "sort by name"),
            sort("created", "c", "sort by created date"),
            sort("modified", "m", "sort by modified date"),
            sort("size", "s", "sort by size"),
            { id: "new",    label: "+",  state: 0,                             tip: "new file or folder" },
            { id: "rename", label: "r",  state: selOne,                        tip: "rename selected" },
            { id: "copy",   label: "cp", state: sel,                           tip: "copy selected" },
            { id: "cut",    label: "cx", state: sel,                           tip: "cut selected" },
            { id: "paste",  label: "p",  state: view.clip !== null ? 0 : 2,    tip: "paste" },
            { id: "trash",  label: "t",  state: sel,                           tip: "move to trash" },
            { id: "hidden", label: "h",  state: view.showHidden ? 1 : 0,       tip: "toggle hidden files" },
        ];
    }
    onTbButtonsChanged: Titlebar.setButtons(tbButtons)
    Component.onCompleted: { Titlebar.setTitleEdit(true); Titlebar.setButtons(tbButtons); }

    Connections {
        target: Titlebar
        function onClicked(id) {
            if (id.startsWith("sort-")) { view.setSort(id.substring(5)); return; }
            switch (id) {
            case "up":     view.go(view.parentOf(view.path)); break;
            case "new":    newDlg.open(); break;
            case "rename": if (view.selection.length === 1) { renameDlg.value = view.dirNameOf(view.selected); renameDlg.open(); } break;
            case "copy":   if (view.selection.length) view.clip = { op: "copy", paths: view.selection.slice() }; break;
            case "cut":    if (view.selection.length) view.clip = { op: "cut",  paths: view.selection.slice() }; break;
            case "paste":  view.pasteInto(view.path); break;
            case "trash":  if (view.selection.length) { FileOps.run(["gio", "trash", "--"].concat(view.selection), ""); view.clearSelection(); } break;
            case "hidden": view.toggleHidden(); break;
            }
        }
        // the in-bar path editor was submitted: navigate if it's a directory
        // (expanding a leading ~ / ~user first).
        function onAddrSubmitted(text) {
            const p = FileOps.expandUser(text.trim());
            if (p !== "" && FileOps.isDir(p)) view.go(p);
        }
    }

    // file-op completion: rebuild the tree, reselect the affected path
    Connections {
        target: FileOps
        function onFinished(reselect) {
            view.refresh();
            if (reselect) { view.selection = [reselect]; view.selected = reselect; view.anchor = reselect; }
            view.refreshDirSize();   // an op changed what the dir holds
        }
    }

    // a finished video compression: DirWatch already brings the new file into
    // the list, this just puts the selection on it (same courtesy as a file op).
    Connections {
        target: VideoConv
        function onFinished(outPath) {
            if (!outPath) return;
            view.refresh();
            view.selection = [outPath]; view.selected = outPath; view.anchor = outPath;
        }
    }

    // external change in a watched dir (something added/removed by another
    // process — a finishing download, a shell mv, …): same keep-scroll refresh
    // as a file op. DirWatch debounces, so a burst of writes lands as one.
    Connections {
        target: DirWatch
        function onChanged() { view.refresh(); view.refreshDirSize(); }
    }

    Rectangle {
        id: view
        anchors.fill: parent
        color: Theme.bg

        property string path: win.startPath

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
        function runPaste(items, op, overwrite) {
            for (let i = 0; i < items.length; i++) {
                const reselect = i === items.length - 1 ? items[i].dst : "";
                const s = items[i].src, d = items[i].dst;
                if (op === "cut")       FileOps.run(overwrite ? ["mv", "--", s, d]
                                                              : ["mv", "-n", "--", s, d], reselect);
                else if (op === "link") FileOps.run(overwrite ? ["ln", "-sfn", "--", s, d]
                                                              : ["ln", "-s", "--", s, d], reselect);
                else                    FileOps.run(overwrite ? ["cp", "-a", "--", s, d]
                                                              : ["cp", "-an", "--", s, d], reselect);
            }
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
            return items.concat([
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

        // Reusable slim vertical scrollbar (the list and the preview grid share
        // it): only visible when its Flickable overflows (size < 1) — the handle
        // stays put at rest, brightening on hover/drag; accent while pressed.
        component VScroll: ScrollBar {
            id: vb
            policy: ScrollBar.AsNeeded
            width: 9
            contentItem: Rectangle {
                implicitWidth: 9
                color: vb.pressed ? Theme.accent : Theme.textDim
                opacity: vb.size < 1 ? (vb.active ? 0.9 : 0.5) : 0
                Behavior on opacity { NumberAnimation { duration: 120 } }
            }
            background: Rectangle {
                color: Theme.bgAlt
                opacity: vb.size < 1 && vb.active ? 0.4 : 0
                Behavior on opacity { NumberAnimation { duration: 120 } }
            }
        }

        // Open a file with the right thing for its kind: images go to `viewer`
        // (the standalone image/media viewer — it scans the file's directory
        // itself for the flip-through set), the rest to xdg-open. (Dirs → go().)
        // In picker mode "open" means "this is my answer" — double-clicking a
        // file returns it. Launching viewer/xdg-open from inside a dialog the
        // portal spawned would be both wrong and, for xdg-open, circular.
        function openFile(p, kind) {
            if (win.picking) {
                if (Picker.selectable(p)) { selectSingle(p, false); pickBar.submit(); }
                return;
            }
            if (kind === "image") FileOps.execDetached(["viewer", p]);
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
        function persist() {
            if (win.picking) return;
            Settings.save(path, sortField, sortAsc, showHidden);
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
                if (win.picking && !Picker.accepts(e.name, e.isDir)) continue;
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
            DirWatch.setDirs([path].concat(Array.from(expandedPaths)));
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

        function go(p) { path = p; clearSelection(); rebuild(); refreshDirSize(); persist(); }

        Component.onCompleted: { rebuild(); refreshDirSize(); Titlebar.setFooter(footerStr); }

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
        // inner column): the current dir's total size.
        readonly property string footerStr: dirSizeStr
        onFooterStrChanged: Titlebar.setFooter(footerStr)

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
                    winActive: win.active
                    selected: view.selection.indexOf(cell.modelData.path) >= 0
                    dragPaths: view.dragPaths(cell.modelData.path)
                    inMultiSelection: view.selection.length > 1 && selected
                    onClicked: (mods) => view.clickSelect(cell.modelData.path, false, mods)
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
                    anchors { left: parent.left; leftMargin: 6 + row.indent + 20; right: szText.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
                    elide: Text.ElideRight
                    text: row.modelData.name
                    color: !win.active ? Theme.inactive : (row.modelData.isDir ? Theme.accent : Theme.text)
                }
                // columns: size | modified (fixed widths, so they line up across
                // rows). Dirs show no size but keep their modified timestamp.
                PixelText {
                    id: szText
                    width: 52
                    horizontalAlignment: Text.AlignRight
                    anchors { right: modifiedText.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
                    text: row.modelData.isDir ? "" : view.sizeStr(row.modelData.size)
                    color: !win.active ? Theme.inactive : Theme.textDim
                }
                PixelText {
                    id: modifiedText
                    width: 146
                    elide: Text.ElideRight
                    anchors { right: createdText.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
                    text: "m: " + view.fmtRel(row.modelData.modified)
                    color: !win.active ? Theme.inactive : Theme.textDim
                }
                PixelText {
                    id: createdText
                    width: 146
                    elide: Text.ElideRight
                    anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                    text: "c: " + view.fmtRel(row.modelData.created)
                    color: !win.active ? Theme.inactive : Theme.textDim
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
                        color: !win.active ? Theme.inactive : Theme.accent
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
            visible: win.picking
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: win.picking ? implicitHeight : 0
            winActive: win.active
            currentDir: view.path
            picked: {
                if (!win.picking) return [];
                return view.selection.filter(p => Picker.selectable(p));
            }
        }

        // Enter accepts, Escape cancels — the two keys every file dialog owes
        // the user. Only bound while picking, so they stay free in the browser.
        Shortcut {
            enabled: win.picking
            sequences: [StandardKey.Cancel]
            onActivated: Picker.cancel()
        }
        Shortcut {
            enabled: win.picking
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
}
