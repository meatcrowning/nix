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

    // ---- split view ----
    // Two independent browsing panes side by side, divided by a draggable
    // splitter — the point being that you can drag files from one to the
    // other (the drop half landed first; see AGENTS.md). Each pane is a whole
    // BrowserPane: its own directory, selection, sort, expanded tree, context
    // menu and drop target.
    //
    // `focusPane` is which of the two the CHROME acts on. There is one
    // titlebar for two panes, so everything on it — the address bar, the sort
    // buttons, the file operations, the dir-size footer — reads `pane`, "the
    // focused pane", and every pane-agnostic line below kept working
    // unchanged. Clicking anywhere in a pane points the chrome at it
    // (BrowserPane's claimFocus/focusClaimed).
    //
    // The same shape as surfer's split view (apps/surfer/qml/Main.qml) minus
    // its hard part: surfer's panes show TABS, so one pane could be handed a
    // view the other was already showing and the two had to swap. Two filer
    // panes can happily show the same directory.
    property bool splitOn: false
    property int focusPane: 0     // 0 = left, 1 = right
    property real splitRatio: 0.5
    readonly property int splitterW: 4
    readonly property int minPaneW: 220
    readonly property int paneLeftW: splitOn
        ? Math.max(minPaneW, Math.min(width - splitterW - minPaneW,
                                      Math.round((width - splitterW) * splitRatio)))
        : width
    readonly property int paneRightX: paneLeftW + splitterW
    readonly property int paneRightW: Math.max(0, width - paneRightX)
    // where the right pane opens: where it was last time, else beside the left
    // one. Read at Loader time, so folding the split and reopening it comes
    // back to the directory you left (persisted by the pane itself).
    property string splitStartPath: ""

    // The two panes and the focused one, as plain `Item`s: a file-based QML
    // type has no C++ converter, so `property BrowserPane` is unreadable from
    // a PySide harness (tools/split-test.py) — and this is the one seam the
    // harness has to reach through.
    readonly property Item leftPane: paneL
    readonly property Item rightPane: paneRLoader.item
    readonly property Item pane: (splitOn && focusPane === 1 && paneRLoader.item)
                                 ? paneRLoader.item : paneL

    function setSplitRatio(r) {
        splitRatio = Math.max(0.15, Math.min(0.85, r));
    }
    // "sp" titlebar button (and F3). Opening puts the right pane where it was
    // last, or beside the left one, and hands it the chrome — the pane you
    // just asked for is the one you meant to use. A picker is a single
    // transient errand and is never split.
    function toggleSplit() {
        if (win.picking) return;
        if (splitOn) {
            // remember where it was before the Loader takes the pane away
            if (paneRLoader.item) splitStartPath = paneRLoader.item.path;
            splitOn = false;
            focusPane = 0;
        } else {
            if (splitStartPath === "" || !FileOps.isDir(splitStartPath))
                splitStartPath = paneL.path;
            splitOn = true;
            focusPane = 1;
        }
        Settings.set("split", splitOn);
    }

    // The window title IS the address bar: the hyprvtb plugin renders it as an
    // editable path field (setTitleEdit below), same as surfer's URL bar. It
    // mirrors the focused pane's directory and, on submit, navigates there.
    title: pane.path
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
    //
    // Everything here reads `pane` — the FOCUSED pane — not a fixed one, so
    // one titlebar drives whichever half of a split view you last clicked in.
    readonly property var tbButtons: {
        const view = win.pane;
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
            // split view: two panes, one titlebar. Lit for as long as it is on;
            // disabled while picking, where a second pane means nothing.
            { id: "split",  label: "sp", state: win.picking ? 2 : (win.splitOn ? 1 : 0),
              tip: win.splitOn ? "close split view" : "split view (F3)" },
        ];
    }
    onTbButtonsChanged: Titlebar.setButtons(tbButtons)
    // the dir-size readout at the foot of the titlebar column: the focused
    // pane's, like everything else on that bar.
    readonly property string footerStr: pane.footerStr
    onFooterStrChanged: Titlebar.setFooter(footerStr)
    Component.onCompleted: {
        Titlebar.setTitleEdit(true);
        Titlebar.setButtons(tbButtons);
        Titlebar.setFooter(footerStr);
        // restore the split exactly as it was left (never in a picker).
        splitRatio = startSplitRatio;
        if (!win.picking && startSplit && startSplitDir !== "" && FileOps.isDir(startSplitDir)) {
            splitStartPath = startSplitDir;
            splitOn = true;
        }
    }

    // ---- the panes, in the plural ----
    // Anything that acts on "the view" acts on EVERY pane: a file operation
    // that finishes, or an external change in a watched directory, can perfectly
    // well be visible in both (they may even be showing the same directory), and
    // a move between the panes is exactly that case. `reselect` lands wherever
    // it actually is.
    function eachPane(fn) {
        fn(paneL);
        if (paneRLoader.item) fn(paneRLoader.item);
    }
    function refreshAll(reselect) {
        eachPane(p => {
            p.refresh();
            p.refreshDirSize();
            if (reselect && reselect.indexOf(p.path.replace(/\/+$/, "") + "/") === 0) {
                p.selection = [reselect]; p.selected = reselect; p.anchor = reselect;
            }
        });
    }

    Connections {
        target: Titlebar
        function onClicked(id) {
            const view = win.pane;
            if (id.startsWith("sort-")) { view.setSort(id.substring(5)); return; }
            switch (id) {
            case "up":     view.go(view.parentOf(view.path)); break;
            case "new":    view.openNewDialog(); break;
            case "rename": view.openRenameDialog(); break;
            case "copy":   if (view.selection.length) view.clip = { op: "copy", paths: view.selection.slice() }; break;
            case "cut":    if (view.selection.length) view.clip = { op: "cut",  paths: view.selection.slice() }; break;
            case "paste":  view.pasteInto(view.path); break;
            case "trash":  if (view.selection.length) { FileOps.run(["gio", "trash", "--"].concat(view.selection), ""); view.clearSelection(); } break;
            case "hidden": view.toggleHidden(); break;
            case "split":  win.toggleSplit(); break;
            }
        }
        // the in-bar path editor was submitted: navigate if it's a directory
        // (expanding a leading ~ / ~user first).
        function onAddrSubmitted(text) {
            const p = FileOps.expandUser(text.trim());
            if (p !== "" && FileOps.isDir(p)) win.pane.go(p);
        }
    }

    // F3 splits and unsplits (Dolphin's key for it); F6 moves the chrome to the
    // other pane without reaching for the mouse. Both are dead in picker mode,
    // where there is only ever one pane.
    Shortcut {
        enabled: !win.picking
        sequences: ["F3"]
        onActivated: win.toggleSplit()
    }
    Shortcut {
        enabled: !win.picking && win.splitOn
        sequences: ["F6"]
        onActivated: win.focusPane = win.focusPane === 1 ? 0 : 1
    }

    // file-op completion: rebuild the tree, reselect the affected path
    Connections {
        target: FileOps
        function onFinished(reselect) { win.refreshAll(reselect); }
    }

    // a finished video compression: DirWatch already brings the new file into
    // the list, this just puts the selection on it (same courtesy as a file op).
    Connections {
        target: VideoConv
        function onFinished(outPath) { if (outPath) win.refreshAll(outPath); }
    }

    // external change in a watched dir (something added/removed by another
    // process — a finishing download, a shell mv, …): same keep-scroll refresh
    // as a file op. DirWatch debounces, so a burst of writes lands as one.
    Connections {
        target: DirWatch
        function onChanged() { win.refreshAll(""); }
    }


    // ---- the panes ----
    // The left pane always exists and is the window when the split is off; the
    // right one is a Loader, so an unsplit filer does not pay for a second
    // directory listing, watch set and thumbnail queue it is not showing.
    // Dragging a file from one pane to the other is ordinary DnD — the panes
    // are two DropAreas in one process, and the move/copy/link menu the drop
    // raises is the same one a drop from Dolphin gets (see AGENTS.md).
    BrowserPane {
        id: paneL
        x: 0
        y: 0
        width: win.paneLeftW
        height: win.height
        startPath: win.startPath
        winActive: win.active
        picking: win.picking
        primary: true
        watchKey: "left"
        paneFocused: win.focusPane === 0
        onFocusClaimed: win.focusPane = 0
    }

    Loader {
        id: paneRLoader
        active: win.splitOn
        x: win.paneRightX
        y: 0
        width: win.paneRightW
        height: win.height
        sourceComponent: BrowserPane {
            width: paneRLoader.width
            height: paneRLoader.height
            startPath: win.splitStartPath
            winActive: win.active
            picking: false          // a picker is never split (see toggleSplit)
            primary: false
            watchKey: "right"
            paneFocused: win.focusPane === 1
            onFocusClaimed: win.focusPane = 1
        }
    }

    // Which pane the titlebar is talking to. There is one titlebar for two
    // panes, so it says which with a 1px accent frame drawn over the focused
    // one — the same answer surfer's split view gives (apps/surfer/qml/Main.qml).
    // Input-transparent: it is a label, not a control.
    Rectangle {
        visible: win.splitOn
        z: 9
        x: win.focusPane === 1 ? win.paneRightX : 0
        y: 0
        width: win.focusPane === 1 ? win.paneRightW : win.paneLeftW
        height: win.height
        color: "transparent"
        border.width: 1
        border.color: Theme.accent
    }

    // the divider: drag it to trade width between the panes. The ratio is
    // persisted on release, not on every motion event.
    Rectangle {
        id: vsplit
        visible: win.splitOn
        z: 10
        x: win.paneLeftW
        y: 0
        width: win.splitterW
        height: win.height
        color: vsplitDrag.pressed || vsplitDrag.containsMouse ? Theme.accent : Theme.border

        MouseArea {
            id: vsplitDrag
            anchors.fill: parent
            anchors.leftMargin: -3      // a 4px divider is a 10px grab target
            anchors.rightMargin: -3
            hoverEnabled: true
            cursorShape: Qt.SplitHCursor
            preventStealing: true
            onPositionChanged: (m) => {
                if (!pressed) return;
                win.setSplitRatio(mapToItem(win.contentItem, m.x, m.y).x / Math.max(1, win.width));
            }
            onReleased: Settings.set("splitRatio", win.splitRatio)
        }
    }

}
