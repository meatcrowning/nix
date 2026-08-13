import QtQuick
import Quickshell.Io

// The appearance page's paper + theme chooser: the Meta+W picker's own tiles
// (wallpaper thumbnail + name + the palette strip it applies — the exact
// delegate anatomy of WallpaperPicker.qml), embedded in the page as a
// HORIZONTALLY PAGINATED grid. No scrolling: whole pages of cols x rows tiles
// slide left/right, flipped by the two page buttons that span the full height
// of the box on its left and right edges. Clicking a tile applies that
// wallpaper AND its theme (the full wal-set.sh) immediately — settings take
// effect live (docs/DESIGN.md §10). The apply rewrites Theme.qml, which
// hot-reloads this settings instance; the grid re-lands on the page holding
// the (new) current wallpaper, so the reload returns you to where you were.
//
// The box is also a DROP TARGET: local image files dragged onto it are COPIED
// into the browsed wallpaper folder (auto-versioned, never clobbering) and
// their theme/thumbnail pre-extracted (wal-prepare.sh), then the view flips to
// the page the new paper appears on. Copy-only — an upload box, so there is no
// move/copy ambiguity to ask about (§10.2); non-image and non-local payloads
// are refused at the border so the source shows a declined drop, and the box
// outlines in accent while a valid drag hovers it (§13).
Item {
    id: root
    width: parent ? parent.width : 480
    height: root.rows * root.cellH

    // ---- geometry --------------------------------------------------------
    // Tile proportions are the picker's (cellWidth ~225 : cellHeight 158);
    // the cell width is derived from the live width so the pages always fill
    // the viewport exactly at any window size (§2.7 layouts survive resizing).
    readonly property int btnW: 16          // page button, SetScroll's win31 bar width
    readonly property int btnGap: 4         // button -> viewport breath
    readonly property int cols: 4
    readonly property int rows: 3
    readonly property int cellW: Math.max(1, Math.floor((width - 2 * (btnW + btnGap)) / cols))
    readonly property int cellH: Math.round(cellW * 158 / 225)
    readonly property int vpW: cellW * cols

    // ---- the model: same three parallel arrays as the picker -------------
    // raw* are the full listing straight off list-wallpapers.sh; images/thumbs/
    // palettes are the VISIBLE view of it, with hidden papers dropped unless
    // "show hidden" is on (applyFilter). Keeping the raw arrays lets the visible
    // view recompute the instant the hidden set or the toggle changes, without
    // re-running the process.
    property var rawImages: []
    property var rawThumbs: []
    property var rawPalettes: []
    property var images: []          // absolute source paths (visible subset)
    property var thumbs: []          // cached thumbnail per visible image
    property var palettes: []        // ["#hex", …] per visible image
    property string currentPath: ""  // what ~/.cache/wal/current names

    // Recompute the visible arrays from raw* + the hidden set + the show-hidden
    // toggle. Only reassign `images` when its contents actually change — it is
    // the Repeaters' model and a wholesale reassign rebuilds every tile (the
    // GridView-reset lesson). thumbs/palettes stay aligned to it.
    function applyFilter() {
        const hidden = SettingsStore.d.wallpaperHidden || [];
        const showH = SettingsStore.d.wallpaperShowHidden;
        const imgs = [], ths = [], pals = [];
        for (let i = 0; i < rawImages.length; i++) {
            if (hidden.indexOf(rawImages[i]) !== -1 && !showH) continue;
            imgs.push(rawImages[i]);
            ths.push(rawThumbs[i]);
            pals.push(rawPalettes[i]);
        }
        if (imgs.length !== images.length || imgs.some((v, i) => v !== images[i]))
            images = imgs;
        thumbs = ths;
        palettes = pals;
    }
    Connections {
        target: SettingsStore.d
        function onWallpaperHiddenChanged() { root.applyFilter(); }
        function onWallpaperShowHiddenChanged() { root.applyFilter(); }
    }

    property int pageIdx: 0
    readonly property int perPage: cols * rows
    readonly property int pageCount: Math.max(1, Math.ceil(images.length / perPage))
    onPageCountChanged: if (pageIdx >= pageCount) pageIdx = pageCount - 1

    // Land the view on the page holding the current wallpaper ONCE, when both
    // lists have arrived — the 3s poll below must never yank the view off the
    // page the user flipped to (the picker's _openSync lesson, WallpaperPicker.qml).
    // Until then the run of pages is HIDDEN and its slide Behavior disarmed: a
    // (re)build starts at page 0, and landing from there with the Behavior live
    // sent the whole grid flying left and back on every tile pick (the apply's
    // hot-reload rebuilds this component) — a reload must look like a state
    // change in place, never a re-entry animation (AGENTS.md).
    property bool _landed: false
    property bool _gotList: false
    property bool _gotCurrent: false
    function tryLand() {
        if (_landed || !_gotList || !_gotCurrent) return;
        const i = images.indexOf(currentPath);
        if (i >= 0) pageIdx = Math.floor(i / perPage);
        _landed = true;
    }

    function toFileUrl(p) { return "file://" + encodeURI(p); }

    function refresh() {
        listProc.running = false;
        listProc.running = true;
        currentProc.running = false;
        currentProc.running = true;
    }
    Component.onCompleted: refresh()

    // Picks up newly added wallpapers and freshly generated thumbs/palettes
    // while the page is on screen — same cadence as the picker.
    Timer {
        interval: 3000
        running: root.visible
        repeat: true
        onTriggered: root.refresh()
    }

    Process {
        id: listProc
        command: ["sh", "-c", "$HOME/.config/quickshell/scripts/list-wallpapers.sh"]
        stdout: StdioCollector {
            onStreamFinished: {
                // "source\tthumb\tpalette" per line (list-wallpapers.sh).
                const lines = this.text.split("\n").map(s => s.trim()).filter(s => s.length > 0);
                const nextImages = [], nextThumbs = [], nextPalettes = [];
                for (const line of lines) {
                    const f = line.split("\t");
                    nextImages.push(f[0]);
                    nextThumbs.push(f.length > 1 && f[1] ? f[1] : f[0]);
                    const raw = (f.length > 2 && f[2]) ? f[2] : "";
                    nextPalettes.push(raw ? raw.split(",").filter(s => s.length > 0).map(h => "#" + h) : []);
                }
                // Feed the raw arrays; applyFilter derives the visible subset
                // (dropping hidden papers unless "show hidden" is on) and does
                // the change-guarded reassign of `images` there.
                root.rawImages = nextImages;
                root.rawThumbs = nextThumbs;
                root.rawPalettes = nextPalettes;
                root.applyFilter();
                root._gotList = true;
                root.tryLand();
                root.tryReveal();
            }
        }
    }

    Process {
        id: currentProc
        command: ["sh", "-c", "cat \"$HOME/.cache/wal/current\" 2>/dev/null"]
        stdout: StdioCollector {
            onStreamFinished: {
                root.currentPath = this.text.trim();
                root._gotCurrent = true;
                root.tryLand();
            }
        }
    }

    // ---- applying a pick -------------------------------------------------
    // One full wal-set.sh per click — no preview/commit split: a click here is
    // the deliberate pick, not a flip-through. The suppress marker keeps the
    // panel's "config reloaded" toast quiet, exactly like the picker's commit.
    // At most one run at a time; a click landing mid-run queues (last wins).
    property string pendingPath: ""
    Process {
        id: applyProc
        onExited: {
            if (root.pendingPath) {
                const p = root.pendingPath;
                root.pendingPath = "";
                root.applyPath(p);
            }
        }
    }
    function applyPath(path) {
        currentPath = path;   // optimistic highlight; the reload re-reads it
        if (applyProc.running) {
            pendingPath = path;
            return;
        }
        // "$1" argv-splice, not interpolation, so a path can't smuggle shell
        // metacharacters (the picker's idiom).
        applyProc.command = ["sh", "-c",
            "touch \"$HOME/.cache/wal/.suppress-reload\"; "
            + "exec \"$HOME/.config/scripts/wal-set.sh\" \"$1\" >>\"$HOME/.cache/wal/wallpaper-picker.log\" 2>&1",
            "_", path];
        applyProc.running = true;
    }

    // ---- drop-to-upload --------------------------------------------------
    // Accept only local image files, judged by the same extensions
    // list-wallpapers.sh globs — anything else is refused at onEntered so the
    // drag source draws a declined drop instead of a dead one (§10.2).
    function isImageUrl(u) {
        const s = String(u);
        return /^file:\/\//i.test(s) && /\.(png|jpe?g|webp|bmp)$/i.test(s);
    }
    // The first dropped file's destination: once it appears in `images`
    // (ingest done, poll caught up), flip to its page — the one view move that
    // is feedback for a user act, not a background yank. One-shot.
    property string revealPath: ""
    function tryReveal() {
        if (!revealPath) return;
        const i = images.indexOf(revealPath);
        if (i < 0) return;
        pageIdx = Math.floor(i / perPage);
        revealPath = "";
    }
    Process {
        id: ingestProc
        // Copy each dropped file into the browsed folder under a free name
        // (auto-versioned suffix — never clobber, §10.2), then pre-extract its
        // theme + thumbnail so the tile arrives with its palette strip. The
        // folder is resolved exactly like list-wallpapers.sh resolves it, so
        // the drop lands where the grid is looking. file:// URLs are decoded
        // by python, once — never a uri-list in QML (§13).
        stdout: StdioCollector {
            onStreamFinished: {
                const first = (this.text || "").split("\n").map(s => s.trim()).filter(s => s.length > 0)[0];
                if (first) root.revealPath = first;
                root.refresh();
            }
        }
    }
    function ingest(urls) {
        // Plain loop: `urls` is a QML sequence, not guaranteed a full JS Array.
        const args = [];
        for (let i = 0; i < urls.length; i++)
            if (isImageUrl(urls[i])) args.push(String(urls[i]));
        if (args.length === 0) return;
        ingestProc.command = ["sh", "-c",
              'SETTINGS="$HOME/.config/quickshell/settings.json"; '
            + 'DIR="$(jq -r \'.wallpaperDir // empty\' "$SETTINGS" 2>/dev/null)"; '
            + '[ -n "$DIR" ] || DIR="~/Pictures/wall"; '
            + 'case "$DIR" in "~") DIR="$HOME";; "~/"*) DIR="$HOME/${DIR#\\~/}";; esac; '
            + 'mkdir -p "$DIR"; '
            + 'for u in "$@"; do '
            +   'p="$(python3 -c \'import sys; from urllib.parse import urlparse, unquote; print(unquote(urlparse(sys.argv[1]).path))\' "$u")" || continue; '
            +   '[ -f "$p" ] || continue; '
            +   'base="$(basename "$p")"; stem="${base%.*}"; ext="${base##*.}"; '
            +   'dest="$DIR/$base"; n=2; '
            +   'while [ -e "$dest" ]; do dest="$DIR/$stem-$n.$ext"; n=$((n+1)); done; '
            +   'cp -- "$p" "$dest" || continue; '
            +   '"$HOME/.config/scripts/wal-prepare.sh" "$dest" >>"$HOME/.cache/wal/wallpaper-picker.log" 2>&1; '
            +   'printf "%s\\n" "$dest"; '
            + 'done',
            "_"].concat(args);
        ingestProc.running = true;
    }

    // ---- a page button: full-height, geometry arrow, honesty ladder ------
    // Drawn dead (dim ink, no hover, refused click) at the ends of the run
    // rather than hidden — §10, and SetScroll's steppers do the same.
    component PageBtn: Rectangle {
        id: pb
        property bool pointsLeft: false
        readonly property bool live: pointsLeft ? root.pageIdx > 0
                                                : root.pageIdx < root.pageCount - 1
        width: root.btnW
        color: pma.pressed && live ? Theme.bgAlt : "transparent"
        radius: Theme.windowRounding
        border.width: Theme.ctrlBorder
        border.color: (pma.containsMouse || pma.pressed) && live ? Theme.accent : Theme.border

        // 5x9 pixel triangle, five 1px columns — geometry, never a glyph (§2.3).
        Item {
            anchors.centerIn: parent
            width: 5; height: 9
            Repeater {
                model: 5
                Rectangle {
                    required property int index
                    width: 1
                    height: 2 * (pb.pointsLeft ? index : (4 - index)) + 1
                    x: index
                    y: Math.floor((9 - height) / 2)
                    color: !pb.live ? Theme.dim
                         : (pma.pressed ? Theme.accent
                         : (pma.containsMouse ? Theme.text : Theme.textDim))
                }
            }
        }
        MouseArea {
            id: pma
            anchors.fill: parent
            hoverEnabled: true
            enabled: pb.live
            cursorShape: pb.live ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: {
                if (!pb.live) return;
                root.pageIdx += pb.pointsLeft ? -1 : 1;
            }
        }
    }

    PageBtn {
        pointsLeft: true
        anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
    }
    PageBtn {
        pointsLeft: false
        anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
    }

    // ---- the paginated viewport ------------------------------------------
    Item {
        id: viewport
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: root.vpW
        clip: true

        Row {
            // The whole run of pages, slid by whole page widths — the
            // desktop's one slide (§6.2), instant under reduce motion. Hidden
            // and unanimated until the initial landing has happened, so a
            // rebuild appears already ON its page rather than flying there.
            visible: root._landed
            x: -root.pageIdx * root.vpW
            Behavior on x {
                enabled: root._landed
                NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing }
            }

            Repeater {
                model: root.pageCount
                Item {
                    id: pageItem
                    required property int index
                    width: root.vpW
                    height: root.rows * root.cellH

                    Grid {
                        columns: root.cols
                        Repeater {
                            model: Math.min(root.perPage,
                                            root.images.length - pageItem.index * root.perPage)
                            // One picker tile: thumbnail, name scrim, palette
                            // strip — WallpaperPicker.qml's delegate, verbatim
                            // in anatomy so the two surfaces read as one.
                            Item {
                                id: cell
                                required property int index
                                readonly property int gIdx: pageItem.index * root.perPage + index
                                readonly property string path: root.images[gIdx] || ""
                                readonly property string thumb: (root.thumbs && root.thumbs[gIdx]) || path
                                readonly property bool isCurrent: path !== "" && path === root.currentPath
                                // Only ever true while "show hidden" reveals it —
                                // otherwise a hidden paper is not in the model at
                                // all. Drawn dimmed (§10.1) and right-clickable to
                                // unhide.
                                readonly property bool hidden: path !== "" && (SettingsStore.d.wallpaperHidden || []).indexOf(path) !== -1
                                width: root.cellW
                                height: root.cellH

                                Rectangle {
                                    id: tile
                                    anchors.fill: parent
                                    anchors.margins: 4   // gutter between tiles
                                    opacity: cell.hidden ? 0.4 : 1.0
                                    color: Theme.bgAlt
                                    radius: Theme.windowRounding
                                    border.width: cell.isCurrent ? Theme.ctrlBorder + 1 : Theme.ctrlBorder
                                    border.color: cell.isCurrent ? Theme.accent : Theme.border

                                    Image {
                                        anchors {
                                            top: parent.top; left: parent.left; right: parent.right
                                            bottom: paletteStrip.top
                                        }
                                        anchors.margins: tile.border.width + 2
                                        fillMode: Image.PreserveAspectCrop
                                        asynchronous: true
                                        clip: true
                                        sourceSize.width: 260
                                        sourceSize.height: 150
                                        source: cell.path ? root.toFileUrl(cell.thumb) : ""
                                    }

                                    // The theme this wallpaper applies — equal
                                    // columns of its wal tokens, no invented
                                    // hues (§3). Empty until generated. An
                                    // EXACT partition, not a Row of ceil'd
                                    // cells: ceil overflowed the box by up to
                                    // n-1 px past the tile's right margin
                                    // (nothing clips it) — same fix as
                                    // SetSwatches.
                                    Item {
                                        id: paletteStrip
                                        readonly property var palette: (root.palettes && root.palettes[cell.gIdx]) || []
                                        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                                        anchors.margins: tile.border.width + 2
                                        // SQUARE cells: the strip width is fixed by the tile, so the
                                        // height is the per-column width (width / n) — each swatch a
                                        // square, not the tall sliver a fixed 16px height cut it into.
                                        height: palette.length ? Math.round(width / palette.length) : 0
                                        function cutAt(i) { return Math.round(i * width / Math.max(1, palette.length)); }
                                        Repeater {
                                            model: paletteStrip.palette
                                            Rectangle {
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
                                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                                        cursorShape: Qt.PointingHandCursor
                                        // Left click = pick it; hover deliberately
                                        // never selects (the picker's lesson —
                                        // mousing past must not re-theme). Right
                                        // PRESS = the hide/unhide menu (§7.1).
                                        //
                                        // The menu opens on the right PRESS, not on
                                        // `clicked`: a context menu opens on press
                                        // anyway, and `clicked` needs the RELEASE to
                                        // also land in-bounds to fire — the release
                                        // is the fragile link across the compositor
                                        // (the press always reaches the client), so
                                        // a release that never completes the click
                                        // left the affordance dead. Left stays on
                                        // click: it is a deliberate pick, never a
                                        // press-twitch.
                                        onPressed: (mouse) => {
                                            if (mouse.button === Qt.RightButton)
                                                paperMenu.openFor(tile, cell.path, cell.hidden, mouse.x, mouse.y);
                                        }
                                        onClicked: (mouse) => {
                                            if (mouse.button !== Qt.RightButton)
                                                root.applyPath(cell.path);
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

    // ---- the drop target: the whole box ----------------------------------
    DropArea {
        id: dropZone
        anchors.fill: parent
        keys: ["text/uri-list"]
        onEntered: (drag) => {
            // Refuse at the border unless something droppable is aboard, so
            // the source cursor shows the decline (§10.2).
            let ok = false;
            if (drag.hasUrls)
                for (let i = 0; i < drag.urls.length && !ok; i++)
                    ok = root.isImageUrl(drag.urls[i]);
            drag.accepted = ok;
        }
        onDropped: (drop) => {
            if (!drop.hasUrls) return;
            root.ingest(drop.urls);
            drop.accept(Qt.CopyAction);
        }
    }
    // The target highlights while a (valid) drag hovers it — §13. An outline
    // around the whole box, over the tiles, so the target reads as "this box",
    // not any one tile.
    Rectangle {
        anchors.fill: parent
        visible: dropZone.containsDrag
        color: "transparent"
        border.width: 2
        border.color: Theme.accent
    }

    // The shared right-click hide/unhide menu (§7.2, written once). Zero-size;
    // its overlay is parented to the window's contentItem on open.
    PaperCtxMenu {
        id: paperMenu
        onHide: (p) => SettingsStore.hideWallpaper(p)
        onUnhide: (p) => SettingsStore.unhideWallpaper(p)
    }
}
