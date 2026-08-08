import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

// Wallpaper picker: a two-column grid of previews from ~/Pictures/wall that
// slides out like the Launcher/Cheatsheet. On open it lands on (and centres)
// the wallpaper you're already using. Flipping through it with the arrow
// keys (or clicking a thumbnail) *is* setting the wallpaper — each
// highlight change actually runs wal-set.sh on that image (debounced so key
// repeat doesn't hammer it), which tiles/scales exactly like every other
// wallpaper change in this config and regenerates the theme. There is no
// separate confirm step and no revert: whatever you land on stays when you
// close the picker. Single instance, like Launcher/Cheatsheet/PowerMenu.
PanelWindow {
    id: root

    property bool open: false

    // The picker ALWAYS shows wallpaper thumbnails, whether or not the desktop
    // is currently painting the image ("display wallpaper" off → solid Theme.bg,
    // SettingsStore.wallpaperSolid). Picking one always runs the full wal-set.sh,
    // which re-extracts and re-themes the whole desktop from that wallpaper;
    // `wallpaperSolid` is left untouched, so in solid mode the palette changes
    // and the image simply stays hidden behind Theme.bg (WallpaperLayer.qml).
    // Each thumbnail also carries a strip of the palette it produces along its
    // bottom edge, so the colour theme is visible without applying it.

    // Stay mapped through the slide-out, then hide once off-screen — same
    // lifecycle as Launcher/Cheatsheet.
    visible: open || card.x < card.hidden - 1
    color: "transparent"

    anchors { top: true; bottom: true; right: true }
    margins { top: Theme.gap; bottom: Theme.gap; right: Theme.gap }
    implicitWidth: 460   // two thumbnail columns (see the GridView below)
    exclusiveZone: 0

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "qs-wallpaper"
    WlrLayershell.keyboardFocus: visible ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None

    // Qt.resolvedUrl() resolves against this file's real path in a Singleton
    // (see SysInfo.qml) but returns a bogus "qrc:/qs-blackhole" placeholder
    // from inside a PanelWindow-rooted component, so paths here are resolved
    // via a shell's own $HOME expansion instead — same trick currentProc
    // below already uses to read ~/.cache/wal/current.
    readonly property string wallSetPath: "$HOME/.config/scripts/wal-set.sh"
    readonly property string listScriptPath: "$HOME/.config/quickshell/scripts/list-wallpapers.sh"

    property var images: []          // absolute source paths, name-sorted
    property var thumbs: []          // cached thumbnail path per image (parallel to images)
    property var palettes: []        // "#hex,#hex,…" strip per image (parallel), solid mode
    property string currentPath: ""  // the wallpaper active when the picker opened
    // True once the user actually flipped to a different wallpaper this
    // session — opening and closing the picker without touching anything
    // must NOT re-apply the theme. Set ONLY by userNav()/the click handler, so
    // the view's own model-driven index resets can never mark the picker dirty.
    property bool dirty: false

    // The path of the highlighted thumbnail, kept in sync with list.currentIndex
    // by updateSelected() below. This is deliberately NOT read off
    // list.currentItem: a GridView/ListView updates currentItem ASYNCHRONOUSLY
    // (on its next polish/layout pass), so right after `list.currentIndex = i`
    // — which is exactly when a click both selects AND closes the picker —
    // currentItem still points at the PREVIOUS delegate. Reading it there made
    // the commit apply the previously-highlighted wallpaper: the cursor accent
    // and ~/.cache/wal/current both ended up one pick behind, so you had to pick
    // the same wallpaper twice for it to "take". images[currentIndex] resolves
    // synchronously off the model, so it's always the wallpaper you're on.
    property string selectedPath: ""
    function updateSelected() {
        selectedPath = (list.currentIndex >= 0 && list.currentIndex < images.length)
            ? images[list.currentIndex] : "";
    }

    function toFileUrl(p) {
        return "file://" + encodeURI(p);
    }
    function fileName(p) {
        const i = p.lastIndexOf("/");
        return i >= 0 ? p.substring(i + 1) : p;
    }

    // Re-scan the directory (picks up newly-added images) and re-read which
    // wallpaper is currently active, then (re)sync the selection to it.
    //
    // `openSync` is true ONLY for the refresh fired when the picker opens: that
    // one lands the selection on the current wallpaper and centres the view on
    // it. The 3-second poll passes false — it re-reads the folder (new files,
    // freshly generated thumbnails/palettes) but must NOT touch the selection
    // or the scroll position. A poll that resynced dragged the highlight back
    // to the current wallpaper and snapped the view to centre every few seconds
    // while you were browsing — most visibly in the colour-theme grid, which
    // never marks `dirty` and so had nothing to stop the revert.
    property bool _openSync: false
    function refresh(openSync) {
        _openSync = openSync === true;
        listProc.running = false;
        listProc.running = true;
        currentProc.running = false;
        currentProc.running = true;
    }

    function trySyncSelection() {
        if (images.length === 0) return;
        // Once the user has intentionally flipped, list.currentIndex is the
        // source of truth — do NOT let a late async refresh (the on-open
        // listProc/currentProc, or the 3s poll) yank the selection back to the
        // still-active wallpaper. That race is what made the first pick after
        // opening get discarded, so the theme only changed on the *second* pick.
        if (dirty) return;
        // Only the OPEN refresh moves the selection and the view; a poll refresh
        // leaves both exactly where the user put them (see refresh() above).
        if (!_openSync) return;
        const idx = currentPath ? images.indexOf(currentPath) : -1;
        const at = idx >= 0 ? idx : 0;
        list.currentIndex = at;
        updateSelected();
        // Land the view ON the current entry, centred — opening the picker
        // should show where you already are, not the top of the list. Do it now
        // AND once more after layout settles (positionViewAtIndex is a no-op if
        // the grid hasn't laid its delegates out yet, which it often hasn't on
        // the very first frame after the model is (re)assigned).
        list.positionViewAtIndex(at, GridView.Center);
        centerTimer.restart();
    }

    // Deferred re-centre: fires after the current event loop turn so the grid
    // has had a chance to instantiate delegates for positionViewAtIndex to act
    // on. See trySyncSelection above.
    Timer {
        id: centerTimer
        interval: 0
        onTriggered: {
            if (list.count > 0)
                list.positionViewAtIndex(list.currentIndex, GridView.Center);
        }
    }

    Process {
        id: listProc
        command: ["sh", "-c", root.listScriptPath]
        stdout: StdioCollector {
            onStreamFinished: {
                // Each line is "source\tthumbnail\tpalette" (see
                // list-wallpapers.sh). The palette field is a comma-separated
                // list of raw hex tokens (no '#'), possibly empty.
                const lines = this.text.split("\n").map(s => s.trim()).filter(s => s.length > 0);
                const nextImages = [];
                const nextThumbs = [];
                const nextPalettes = [];
                for (const line of lines) {
                    const f = line.split("\t");
                    nextImages.push(f[0]);
                    nextThumbs.push(f.length > 1 && f[1] ? f[1] : f[0]);
                    // "aabbcc,ddeeff,…" -> ["#aabbcc", …]; [] when unprepared.
                    const raw = (f.length > 2 && f[2]) ? f[2] : "";
                    nextPalettes.push(raw ? raw.split(",").filter(s => s.length > 0).map(h => "#" + h) : []);
                }
                // Only reassign `images` when the source set actually changed:
                // assigning a new array (even an identical one) resets the
                // GridView, clobbering currentIndex. `thumbs`/`palettes` are
                // always refreshed — reassigning them does NOT reset the view
                // (the model is `images`), so a thumbnail or palette that
                // finished generating between polls swaps in live without
                // disturbing the selection.
                if (nextImages.length !== root.images.length
                        || nextImages.some((v, i) => v !== root.images[i]))
                    root.images = nextImages;
                root.thumbs = nextThumbs;
                root.palettes = nextPalettes;
                root.trySyncSelection();
            }
        }
    }

    Process {
        id: currentProc
        command: ["sh", "-c", "cat \"$HOME/.cache/wal/current\" 2>/dev/null"]
        stdout: StdioCollector {
            onStreamFinished: {
                root.currentPath = this.text.trim();
                root.trySyncSelection();
            }
        }
    }

    // Two-phase apply, forced by how Quickshell's hot-reload actually works:
    // wal-set.sh's full run rewrites Theme.qml in place, which Quickshell
    // sees as a config change and hot-reloads — but a reload destroys and
    // recreates the ENTIRE QML object tree from source (confirmed by
    // testing), so `root.open` itself resets to its default and the picker
    // window closes out from under you on every single flip. So while
    // flipping, only `previewProc` runs (--wallpaper-only: hyprpaper IPC,
    // no Theme.qml write, no reload, picker stays open, instant); the full
    // apply (theme/kitty/border) only runs once via `commitProc`, when the
    // picker actually closes, on whatever was last highlighted.
    //
    // previewProc runs at most one wal-set.sh at a time; a flip that lands
    // mid-run just overwrites pendingPath, and onExited immediately re-runs
    // with whatever the latest pick was — so rapid flipping always converges
    // on the last image instead of piling up overlapping runs.
    property string pendingPath: ""

    // wal-set.sh rewrites Theme.qml in place on every full apply, which
    // Quickshell sees as a config change and hot-reloads — normally
    // announced with a "config reloaded" toast (see shell.qml). That's the
    // right toast for an actual edit but not for a wallpaper change, so
    // commitPath() touches this marker just before running the full
    // wal-set.sh; shell.qml checks its freshness (not just existence, so a
    // stale marker from a crashed run doesn't suppress forever) before
    // deciding whether to toast. A plain in-memory flag can't do this job —
    // see the reload comment above, it wouldn't survive the very reload it's
    // meant to gate.
    readonly property string suppressMarker: "$HOME/.cache/wal/.suppress-reload"

    Process {
        id: previewProc
        onExited: {
            if (root.pendingPath) {
                const p = root.pendingPath;
                root.pendingPath = "";
                root.previewPath(p);
            }
        }
    }

    function previewPath(path) {
        if (previewProc.running) {
            pendingPath = path;
            return;
        }
        // "$1" via the sh -c argv-splice idiom, not string interpolation, so
        // a path can't smuggle in shell metacharacters.
        previewProc.command = ["sh", "-c",
            "exec \"" + root.wallSetPath + "\" --wallpaper-only \"$1\" >>\"$HOME/.cache/wal/wallpaper-picker.log\" 2>&1",
            "_", path];
        previewProc.running = true;
    }

    Process {
        id: commitProc
    }

    // Runs the full (theme-included) apply exactly once, on whatever's
    // currently highlighted — called when the picker closes, not per-flip.
    // A close with no flips is a no-op (see `dirty`).
    function commitFinal() {
        if (!dirty || commitProc.running) return;
        if (!root.selectedPath) return;
        commitProc.command = ["sh", "-c",
            "touch \"" + root.suppressMarker + "\"; exec \"" + root.wallSetPath + "\" \"$1\" >>\"$HOME/.cache/wal/wallpaper-picker.log\" 2>&1",
            "_", root.selectedPath];
        commitProc.running = true;
    }

    // Debounced so holding an arrow key doesn't queue a wal-set.sh per repeat.
    Timer {
        id: applyTimer
        interval: 90
        onTriggered: {
            if (root.selectedPath)
                root.previewPath(root.selectedPath);
        }
    }

    // Poll for new files while open (FolderListModel-style live watching isn't
    // worth the extra dependency for a rarely-changing directory); a fresh
    // scan also happens on every open.
    Timer {
        interval: 3000
        running: root.open
        repeat: true
        onTriggered: root.refresh(false)
    }

    onOpenChanged: {
        if (open) {
            dirty = false;
            refresh(true);   // open sync: land + centre on the current wallpaper
            list.forceActiveFocus();
        } else {
            // The full theme apply runs once, on close, on whatever was last
            // highlighted — in solid mode too, where it re-themes but leaves the
            // image hidden (wallpaperSolid untouched). A close with no flip is a
            // no-op (see `dirty`).
            commitFinal();
        }
    }

    Rectangle {
        id: card
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: parent.width

        readonly property real shown: 0
        readonly property real hidden: width
        x: root.open ? shown : hidden
        Behavior on x { NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing } }

        color: Theme.bg
        border.color: Theme.windowBorder
        border.width: Theme.windowBorderWidth
        radius: Theme.windowRounding

        PixelText {
            id: title
            anchors { top: parent.top; horizontalCenter: parent.horizontalCenter; topMargin: 10 }
            text: "paper + theme"
            color: Theme.accent
        }

        KineticGridView {
            id: list
            focus: true
            anchors {
                top: title.bottom; topMargin: 8
                left: parent.left; right: parent.right; bottom: parent.bottom
                margins: 10
            }
            clip: true
            // Two columns. cellWidth is derived from the live width so the grid
            // always fills the card exactly (no ragged right gutter); cellHeight
            // keeps the ~16:9 thumbnail plus a little vertical breathing room.
            readonly property int columns: 2
            cellWidth: Math.floor(width / columns)
            cellHeight: 158   // thumbnail + the theme's palette strip along the bottom
            model: root.images
            boundsBehavior: Flickable.StopAtBounds
            cacheBuffer: 800   // keep a couple of off-screen rows warm for smooth scroll
            // Index changes ONLY keep the highlight path in sync and scroll the
            // view. Crucially, dirty/preview are NOT set here: a GridView fires
            // this handler on its OWN model-driven resets too — most importantly
            // the -1 -> 0 jump when the model goes from empty to populated on the
            // first open after a hot-reload. Marking dirty there made
            // trySyncSelection's `if (dirty) return` bail, so the selection never
            // synced to the active wallpaper and sat on the first entry (the
            // "reopen jumps back to the first wallpaper" bug). dirty is set
            // exclusively by real user input, via userNav()/the click handler.
            onCurrentIndexChanged: {
                positionViewAtIndex(currentIndex, GridView.Contain);
                root.updateSelected();
            }

            // A genuine user flip: mark dirty (so it commits on close) and queue
            // the debounced live preview. Everything else that moves currentIndex
            // (model resets, trySyncSelection) deliberately goes around this.
            function userNav(idx) {
                currentIndex = Math.max(0, Math.min(idx, count - 1));
                root.updateSelected();
                root.dirty = true;
                applyTimer.restart();
            }

            // Grid navigation: left/right step one thumbnail, up/down jump a row.
            Keys.onLeftPressed:  userNav(currentIndex - 1)
            Keys.onRightPressed: userNav(currentIndex + 1)
            Keys.onUpPressed:    userNav(currentIndex - columns)
            Keys.onDownPressed:  userNav(currentIndex + columns)
            Keys.onEscapePressed: root.open = false
            Keys.onReturnPressed: root.open = false
            Keys.onEnterPressed: root.open = false

            delegate: Item {
                id: cell
                required property string modelData
                required property int index
                readonly property string path: modelData
                // Cached thumbnail (parallel `thumbs` array); falls back to the
                // full-res source if its thumbnail hasn't been generated yet.
                readonly property string thumb: (root.thumbs && root.thumbs[index]) || modelData

                width: list.cellWidth
                height: list.cellHeight

                Rectangle {
                    id: delegateRoot
                    anchors.fill: parent
                    anchors.margins: 4   // gutter between cells
                    color: Theme.bgAlt
                    radius: 0
                    border.width: cell.index === list.currentIndex ? 2 : 1
                    border.color: cell.index === list.currentIndex ? Theme.accent : Theme.border

                    Image {
                        anchors {
                            top: parent.top; left: parent.left; right: parent.right
                            bottom: paletteStrip.top
                        }
                        anchors.margins: delegateRoot.border.width + 2
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                        clip: true
                        sourceSize.width: 260
                        sourceSize.height: 150
                        source: root.toFileUrl(cell.thumb)
                    }

                    Rectangle {
                        anchors { left: parent.left; right: parent.right; bottom: paletteStrip.top }
                        anchors.margins: delegateRoot.border.width + 2
                        height: 18
                        color: Qt.rgba(0, 0, 0, 0.55)

                        PixelText {
                            anchors.centerIn: parent
                            width: parent.width - 8
                            elide: Text.ElideMiddle
                            horizontalAlignment: Text.AlignHCenter
                            // Label only; `cell.path` is what gets set as the
                            // wallpaper and must stay byte-exact.
                            text: Glyphs.px(root.fileName(cell.path))
                            color: Theme.text
                        }
                    }

                    // The theme this wallpaper produces: a compact strip of its
                    // extracted palette along the bottom of the box, so every
                    // entry shows the thumbnail AND the colour theme it applies.
                    // Same idiom as the colour-theme grid above and DESIGN §3 —
                    // equal-width columns of the wal tokens, no invented hues.
                    // Empty (palette not generated yet) leaves the bare bgAlt.
                    // An EXACT partition, not a Row of ceil'd cells: ceil
                    // overflowed the box right by up to n-1 px, unclipped —
                    // same fix as SetPaperGrid/SetSwatches.
                    Item {
                        id: paletteStrip
                        readonly property var palette: (root.palettes && root.palettes[cell.index]) || []
                        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                        anchors.margins: delegateRoot.border.width + 2
                        height: 16
                        function cutAt(i) { return Math.round(i * width / Math.max(1, palette.length)); }
                        Repeater {
                            model: paletteStrip.palette
                            delegate: Rectangle {
                                required property int index
                                required property string modelData
                                x: paletteStrip.cutAt(index)
                                width: paletteStrip.cutAt(index + 1) - x
                                height: paletteStrip.height
                                color: modelData
                            }
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        // Click = pick it: select, apply the full theme, close.
                        // (Hover deliberately does NOT flip the selection — it
                        // caused accidental re-themes just from mousing past.)
                        onClicked: {
                            applyTimer.stop();
                            list.userNav(cell.index);   // marks dirty so it commits on close
                            root.open = false;
                        }
                    }
                }
            }
        }
    }
}
