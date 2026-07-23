import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic

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
            case "paste": {
                if (view.clip === null) break;
                const paths = view.clip.paths, cut = view.clip.op === "cut";
                for (let i = 0; i < paths.length; i++) {
                    const src = paths[i];
                    const dst = view.join(view.path, view.dirNameOf(src));
                    const reselect = i === paths.length - 1 ? dst : "";
                    if (cut) FileOps.run(["mv", "--", src, dst], reselect);
                    else     FileOps.run(["cp", "-a", "--", src, dst], reselect);
                }
                if (cut) view.clip = null;
                break;
            }
            case "trash":  if (view.selection.length) { FileOps.run(["gio", "trash", "--"].concat(view.selection), ""); view.clearSelection(); } break;
            case "hidden": view.toggleHidden(); break;
            }
        }
        // the in-bar path editor was submitted: navigate if it's a directory
        function onAddrSubmitted(text) {
            const p = text.trim();
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

        function clearSelection() { selection = []; selected = ""; anchor = ""; }
        function isSelected(p) { return selection.indexOf(p) >= 0; }

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

        // tree state: the flat list of currently-visible rows, plus the set of
        // directory paths the user has expanded (persisted across refreshes so
        // an op doesn't collapse the tree).
        property var rows: []
        property var expandedPaths: new Set()

        // Image entries of the CURRENT dir, pulled out of `rows` and shown in a
        // thumbnail grid pinned above the list (the ListView header). Only the
        // current dir — images inside expanded subdirs stay inline as rows.
        property var images: []

        // Open a file with the right thing for its kind: images go to `viewer`
        // (the standalone image/media viewer — it scans the file's directory
        // itself for the flip-through set), the rest to xdg-open. (Dirs → go().)
        function openFile(p, kind) {
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
        function persist() { Settings.save(path, sortField, sortAsc, showHidden); }

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
        }
        function refresh() { rebuildKeepScroll(); }

        // Reassigning the model resets ListView.contentY to 0, which is right for
        // a cd but jarring for expand/collapse/refresh (the view jumps to the
        // top). Save and restore the scroll offset around those rebuilds.
        function rebuildKeepScroll() {
            const y = list.contentY;
            rebuild();
            list.contentY = Math.max(0, Math.min(y, list.contentHeight - list.height));
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

        // ---- tree list ----
        // (No in-window location bar any more — the editable path lives in the
        // titlebar address bar, and "up" is the "^" titlebar button.)
        ListView {
            id: list
            anchors { top: parent.top; left: parent.left; right: parent.right; bottom: parent.bottom; margins: 2 }
            clip: true
            model: view.rows
            boundsBehavior: Flickable.StopAtBounds

            // ---- preview grid: the current dir's images, above the rows ----
            // Scrolls with the list (it's the header), so it reads as the top of
            // the directory. Collapses to nothing when the dir has no images.
            header: Item {
                width: list.width
                visible: view.images.length > 0
                height: visible ? grid.implicitHeight + 8 : 0

                Flow {
                    id: grid
                    anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: 4; rightMargin: 4; topMargin: 4 }
                    spacing: 4
                    Repeater {
                        model: view.images
                        PreviewTile {
                            required property var modelData
                            entry: modelData
                            winActive: win.active
                            selected: view.selection.indexOf(modelData.path) >= 0
                            onClicked: (mods) => view.clickSelect(modelData.path, false, mods)
                            onOpened: view.openFile(modelData.path, modelData.kind)
                        }
                    }
                }
            }

            delegate: Rectangle {
                id: row
                required property var modelData
                required property int index
                width: list.width
                height: 22
                readonly property string abs: modelData.path
                readonly property int indent: modelData.depth * 14
                color: view.selection.indexOf(abs) >= 0 ? Theme.highlight : "transparent"

                // Drag-out: hand this file to other apps as a text/uri-list, so
                // it can be dropped onto a browser upload field, another file
                // manager, etc. — the standard desktop "drag a file out" gesture.
                // Binding Drag.active to the MouseArea's drag (which drags an
                // INVISIBLE proxy, so the row itself stays put) is what actually
                // starts the real cross-app QDrag under dragType Automatic — a
                // bare Drag.startDrag() didn't initiate one on Wayland.
                Drag.active: rowMa.drag.active
                Drag.dragType: Drag.Automatic
                Drag.supportedActions: Qt.CopyAction | Qt.LinkAction
                Drag.mimeData: ({ "text/uri-list": "file://" + encodeURI(row.abs) + "\r\n" })
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
                        text: row.modelData.name
                        color: Theme.text
                    }
                }

                // row-wide select / open / drag-out. Declared first so the expand
                // toggle (declared last → higher z) wins clicks in its own area.
                MouseArea {
                    id: rowMa
                    anchors.fill: parent
                    // preventStealing so the ListView's Flickable can't grab the
                    // press-drag and scroll instead of starting the file drag.
                    // (Scroll the list with the wheel/trackpad.)
                    preventStealing: true
                    drag.target: dragProxy
                    onPressed: (m) => {
                        view.clickSelect(row.abs, row.modelData.isDir, m.modifiers);
                        // stage the drag image; ready by the time the drag passes
                        // the threshold and Drag.active turns on
                        dragBadge.grabToImage(function(res) { row.Drag.imageSource = res.url; });
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
                    anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                    text: "m: " + view.fmtRel(row.modelData.modified)
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
                        text: row.modelData.expanded ? "−" : "+"
                        color: !win.active ? Theme.inactive : Theme.accent
                    }
                }
            }
        }

        // ---- modal dialogs (simple centered prompts) ----
        // (delDlg is kept for the delete action, which moves to the right-click
        // menu — see the trash/delete split; it's wired there later.)
        BrowserPrompt {
            id: newDlg
            title: "new folder name"
            onAccepted: (t) => { if (t) FileOps.run(["mkdir", "--", view.join(view.path, t)], view.join(view.path, t)); }
        }
        BrowserPrompt {
            id: renameDlg
            title: "rename to"
            onAccepted: (t) => {
                if (t) {
                    const dst = view.join(view.parentOf(view.selected), t);
                    FileOps.run(["mv", "--", view.selected, dst], dst);
                }
            }
        }
        BrowserConfirm {
            id: delDlg
            text: "permanently delete?\n" + view.dirNameOf(view.selected)
            onConfirmed: { FileOps.run(["rm", "-rf", "--", view.selected], ""); view.selected = ""; }
        }
    }
}
