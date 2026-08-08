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
    // Two independent browsing panes, side by side or stacked, divided by a
    // draggable splitter — the point being that you can drag files from one to
    // the other (the drop half landed first; see AGENTS.md). Each pane is a
    // whole BrowserPane: its own directory, selection, sort, expanded tree,
    // context menu and drop target.
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
    //
    // ORIENTATION, kitty's two buttons: `|` splits RIGHT (a vertical divider,
    // panes side by side — `splitVertical`, the original behaviour) and `_`
    // splits DOWN (a horizontal divider, panes stacked). One geometry serves
    // both: a LEADING pane (left/top), the splitter, a TRAILING pane
    // (right/bottom), measured along whichever axis is active. `splitRatio` is
    // the same number on either axis, so re-orienting keeps the proportion.
    // (`_`, not `-`: a bare "-" is the SPACER token in the vtb button-array
    // protocol — see pylib/vtbclient.py.)
    property bool splitOn: false
    property bool splitVertical: true   // true = left|right, false = top/bottom
    property int focusPane: 0     // 0 = leading (left/top), 1 = trailing
    property real splitRatio: 0.5
    readonly property int splitterW: 4
    // The minimum along Y is NOT the minimum along X: a pane needs 220px of
    // width before the filename column elides to nothing, but vertically it
    // only needs to keep a few list rows under the (collapsible) preview
    // panel, whose own splitter already clamps itself to `view.height - 90`.
    readonly property int minPaneW: 220
    readonly property int minPaneH: 150
    // the split axis, as one set of numbers. Everything below is a projection.
    readonly property int splitSpan: splitVertical ? width : height
    readonly property int minPane: splitVertical ? minPaneW : minPaneH
    readonly property int paneLeadSize: splitOn
        ? Math.max(minPane, Math.min(splitSpan - splitterW - minPane,
                                     Math.round((splitSpan - splitterW) * splitRatio)))
        : splitSpan
    readonly property int paneTrailPos: paneLeadSize + splitterW
    // never zero: hyprvtb's renderRect aborts the compositor on a zero-size
    // box and filer feeds the vtb socket, so no rect derived from these is
    // allowed to collapse even in a window too small to hold two minimums.
    readonly property int paneTrailSize: Math.max(1, splitSpan - paneTrailPos)
    // the two panes as actual rects (x/y/w/h), so every binding below is a
    // plain read rather than a repeat of the ternary.
    readonly property int paneLeadW: splitVertical ? paneLeadSize : width
    readonly property int paneLeadH: splitVertical ? height : paneLeadSize
    readonly property int paneTrailX: splitVertical ? paneTrailPos : 0
    readonly property int paneTrailY: splitVertical ? 0 : paneTrailPos
    readonly property int paneTrailW: splitVertical ? paneTrailSize : width
    readonly property int paneTrailH: splitVertical ? height : paneTrailSize
    // where the trailing pane opens: where it was last time, else the same
    // directory as the leading one. Read at Loader time, so folding the split
    // and reopening it comes
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
    // The `|` and `_` titlebar buttons (and F3 / Shift+F3), both routed here.
    // Each stays a TOGGLE, the way the old single button was: asking for the
    // orientation you are already in closes the split. Asking for the OTHER
    // one while split re-orients in place — the panes and their directories
    // are untouched, only the axis the window is divided on changes, so the
    // trailing pane is not reloaded and does not lose its listing.
    //
    // Opening puts the trailing pane where it was last, or beside the leading
    // one, and hands it the chrome — the pane you just asked for is the one
    // you meant to use. A picker is a single transient errand and is never
    // split.
    function setSplit(vertical) {
        if (win.picking) return;
        if (splitOn && splitVertical === vertical) {
            // remember where it was before the Loader takes the pane away
            if (paneRLoader.item) splitStartPath = paneRLoader.item.path;
            splitOn = false;
            focusPane = 0;
        } else if (splitOn) {
            splitVertical = vertical;       // re-orient, keeping both panes
        } else {
            if (splitStartPath === "" || !FileOps.isDir(splitStartPath))
                splitStartPath = paneL.path;
            splitVertical = vertical;
            splitOn = true;
            focusPane = 1;
        }
        Settings.set("split", splitOn);
        Settings.set("splitVertical", splitVertical);
    }
    // F3 and the harness: toggle the split in its current (or last) orientation.
    function toggleSplit() { setSplit(splitVertical); }

    // The window title IS the address bar: the hyprvtb plugin renders it as an
    // editable path field (setTitleEdit below), same as surfer's URL bar. It
    // mirrors the focused pane's directory and, on submit, navigates there.
    //
    // Remote.pretty() shows a directory on another machine as the `:top/...`
    // that was typed to reach it, rather than the sshfs mountpoint under
    // $XDG_RUNTIME_DIR that nobody asked for and could not usefully retype, and
    // a removable drive as `:SSD/...` whichever machine it is plugged into. It
    // round-trips — submitting the bar unchanged lands back where it is — and
    // a purely local path comes back untouched. See remote.py.
    title: Remote.pretty(pane.path)
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
            // split view: two panes, one titlebar. Kitty's pair, same labels
            // and same meaning — `|` divides vertically (panes side by side),
            // `_` divides horizontally (panes stacked). The one matching the
            // current orientation is lit and closes the split; the other
            // re-orients it. Both are disabled while picking, where a second
            // pane means nothing. `_` and not `-`, which is the spacer token.
            { id: "vsplit", label: "|",
              state: win.picking ? 2 : ((win.splitOn && win.splitVertical) ? 1 : 0),
              tip: !win.splitOn ? "split right (F3)"
                   : win.splitVertical ? "close split view (F3)" : "split right instead" },
            { id: "hsplit", label: "_",
              state: win.picking ? 2 : ((win.splitOn && !win.splitVertical) ? 1 : 0),
              tip: !win.splitOn ? "split down (Shift+F3)"
                   : !win.splitVertical ? "close split view (F3)" : "split down instead" },
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
        // restore the split exactly as it was left (never in a picker) —
        // including which way it was divided. An older state.json has no
        // orientation key at all; main.py defaults that to true, i.e. the
        // side-by-side split that was the only one there used to be.
        splitRatio = startSplitRatio;
        splitVertical = startSplitVertical;
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
            case "vsplit": win.setSplit(true); break;
            case "hsplit": win.setSplit(false); break;
            }
        }
        // the in-bar path editor was submitted: navigate if it's a directory
        // (expanding a leading ~ / ~user first).
        //
        // `:host` first, though — `:top` browses lam's home on top, and `:SSD`
        // the drive of that name wherever it is plugged in, over an
        // sshfs mount Remote brings up on demand (remote.py). That can take an
        // ssh handshake, so it is asynchronous: remember which pane asked and
        // navigate on `ready`, whose payload is an ordinary local path under
        // the mountpoint. A failure toasts from remote.py and moves nothing.
        function onAddrSubmitted(text) {
            const t = text.trim();
            if (Remote.isAddr(t)) { win.remotePane = win.pane; Remote.open(t); return; }
            const p = FileOps.expandUser(t);
            if (p !== "" && FileOps.isDir(p)) win.pane.go(p);
        }
    }

    // The pane that submitted a `:host` address, held across the mount. It is
    // the pane and not `focusPane`, because a click in the other half while a
    // remote is connecting must not redirect the navigation the user asked for.
    property var remotePane: null
    Connections {
        target: Remote
        function onReady(path) {
            const p = win.remotePane || win.pane;
            win.remotePane = null;
            if (p && FileOps.isDir(path)) p.go(path);
        }
        function onFailed(host) { win.remotePane = null; }
    }

    // F3 splits and unsplits (Dolphin's key for it) in the orientation you are
    // in — or last used. Shift+F3 is "split the other way": it opens stacked
    // when the split is off, and re-orients it when it is on. One key plus a
    // modifier rather than two unrelated keys, because the second is the rarer
    // errand and the pair reads as one gesture. F6 moves the chrome to the
    // other pane without reaching for the mouse, in either orientation. All
    // are dead in picker mode, where there is only ever one pane.
    Shortcut {
        enabled: !win.picking
        sequences: ["F3"]
        onActivated: win.toggleSplit()
    }
    Shortcut {
        enabled: !win.picking
        sequences: ["Shift+F3"]
        onActivated: win.setSplit(!win.splitVertical)
    }
    Shortcut {
        enabled: !win.picking && win.splitOn
        sequences: ["F6"]
        onActivated: win.focusPane = win.focusPane === 1 ? 0 : 1
    }

    // The mouse's back/forward side buttons walk the FOCUSED pane's directory
    // history — `win.pane` is the same pane every other control acts on, so the
    // buttons follow the chrome rather than the pointer. Desktop-global rule,
    // docs/DESIGN.md §11; the handler itself is qmlcommon/NavButtons.qml.
    NavButtons {
        onBack:    if (win.pane) win.pane.goBack()
        onForward: if (win.pane) win.pane.goForward()
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

    // ...and the same courtesy for "copy under 4MB" (imgconv.py).
    Connections {
        target: ImgConv
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
    // The leading pane (left, or top when the split is horizontal) always
    // exists and is the window when the split is off; the trailing one is a
    // Loader, so an unsplit filer does not pay for a second directory listing,
    // watch set and thumbnail queue it is not showing. The Loader survives a
    // re-orientation — only the rects change — so `|` ⇄ `_` keeps both panes
    // and their directories.
    // Dragging a file from one pane to the other is ordinary DnD — the panes
    // are two DropAreas in one process, and the move/copy/link menu the drop
    // raises is the same one a drop from Dolphin gets (see AGENTS.md).
    //
    // A drag-out is live SOMEWHERE in this window. It is per WINDOW, not per
    // pane, because the drag source is one pane's delegate while the refresh
    // that would destroy it (`refreshAll`) hits BOTH — dragging into the other
    // pane is exactly that case. Every pane freezes its model while it is set;
    // BrowserPane.qml's `rebuild()` documents the use-after-free that costs.
    property bool dragInFlight: false

    BrowserPane {
        id: paneL
        x: 0
        y: 0
        width: win.paneLeadW
        height: win.paneLeadH
        startPath: win.startPath
        winActive: win.active
        picking: win.picking
        primary: true
        watchKey: "left"
        paneFocused: win.focusPane === 0
        onFocusClaimed: win.focusPane = 0
        dragInFlight: win.dragInFlight
        onDragStateChanged: (active) => win.dragInFlight = active
    }

    Loader {
        id: paneRLoader
        active: win.splitOn
        x: win.paneTrailX
        y: win.paneTrailY
        width: win.paneTrailW
        height: win.paneTrailH
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
            dragInFlight: win.dragInFlight
            onDragStateChanged: (active) => win.dragInFlight = active
        }
    }

    // Which pane the titlebar is talking to. There is one titlebar for two
    // panes, so it says which with a 1px accent frame drawn over the focused
    // one — the same answer surfer's split view gives (apps/surfer/qml/Main.qml).
    // Input-transparent: it is a label, not a control.
    Rectangle {
        visible: win.splitOn
        z: 9
        x: win.focusPane === 1 ? win.paneTrailX : 0
        y: win.focusPane === 1 ? win.paneTrailY : 0
        width: win.focusPane === 1 ? win.paneTrailW : win.paneLeadW
        height: win.focusPane === 1 ? win.paneTrailH : win.paneLeadH
        color: "transparent"
        border.width: 1
        border.color: Theme.accent
    }

    // the divider: drag it to trade size between the panes, along whichever
    // axis the split is on — sideways when vertical, up and down when
    // horizontal, with the cursor shape and the 10px grab target following the
    // axis too. The ratio is persisted on release, not on every motion event.
    Rectangle {
        id: splitBar
        visible: win.splitOn
        z: 10
        x: win.splitVertical ? win.paneLeadSize : 0
        y: win.splitVertical ? 0 : win.paneLeadSize
        width: win.splitVertical ? win.splitterW : win.width
        height: win.splitVertical ? win.height : win.splitterW
        color: splitDrag.pressed || splitDrag.containsMouse ? Theme.accent : Theme.border

        MouseArea {
            id: splitDrag
            anchors.fill: parent
            // a 4px divider is a 10px grab target, across the divider
            anchors.leftMargin: win.splitVertical ? -3 : 0
            anchors.rightMargin: win.splitVertical ? -3 : 0
            anchors.topMargin: win.splitVertical ? 0 : -3
            anchors.bottomMargin: win.splitVertical ? 0 : -3
            hoverEnabled: true
            cursorShape: win.splitVertical ? Qt.SplitHCursor : Qt.SplitVCursor
            preventStealing: true
            onPositionChanged: (m) => {
                if (!pressed) return;
                const p = mapToItem(win.contentItem, m.x, m.y);
                win.setSplitRatio(win.splitVertical
                                  ? p.x / Math.max(1, win.width)
                                  : p.y / Math.max(1, win.height));
            }
            onReleased: Settings.set("splitRatio", win.splitRatio)
        }
    }

}
