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
    readonly property int cols: 3
    readonly property int rows: 2
    readonly property int cellW: Math.max(1, Math.floor((width - 2 * (btnW + btnGap)) / cols))
    readonly property int cellH: Math.round(cellW * 158 / 225)
    readonly property int vpW: cellW * cols

    // ---- the model: same three parallel arrays as the picker -------------
    property var images: []          // absolute source paths
    property var thumbs: []          // cached thumbnail per image
    property var palettes: []        // ["#hex", …] per image
    property string currentPath: ""  // what ~/.cache/wal/current names

    property int pageIdx: 0
    readonly property int perPage: cols * rows
    readonly property int pageCount: Math.max(1, Math.ceil(images.length / perPage))
    onPageCountChanged: if (pageIdx >= pageCount) pageIdx = pageCount - 1

    // Land the view on the page holding the current wallpaper ONCE, when both
    // lists have arrived — the 3s poll below must never yank the view off the
    // page the user flipped to (the picker's _openSync lesson, WallpaperPicker.qml).
    property bool _landed: false
    function tryLand() {
        if (_landed || images.length === 0) return;
        const i = images.indexOf(currentPath);
        if (i < 0) return;
        pageIdx = Math.floor(i / perPage);
        _landed = true;
    }

    function toFileUrl(p) { return "file://" + encodeURI(p); }
    function fileName(p) {
        const i = p.lastIndexOf("/");
        return i >= 0 ? p.substring(i + 1) : p;
    }

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
                // Only reassign `images` when the set changed — it is the
                // Repeaters' model, and a wholesale reassign rebuilds every
                // tile (the picker's GridView-reset lesson). thumbs/palettes
                // refresh unconditionally so late-generated ones swap in live.
                if (nextImages.length !== root.images.length
                        || nextImages.some((v, i) => v !== root.images[i]))
                    root.images = nextImages;
                root.thumbs = nextThumbs;
                root.palettes = nextPalettes;
                root.tryLand();
            }
        }
    }

    Process {
        id: currentProc
        command: ["sh", "-c", "cat \"$HOME/.cache/wal/current\" 2>/dev/null"]
        stdout: StdioCollector {
            onStreamFinished: {
                root.currentPath = this.text.trim();
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
        border.width: 1
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
            // desktop's one slide (§6.2), instant under reduce motion.
            x: -root.pageIdx * root.vpW
            Behavior on x {
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
                                width: root.cellW
                                height: root.cellH

                                Rectangle {
                                    id: tile
                                    anchors.fill: parent
                                    anchors.margins: 4   // gutter between tiles
                                    color: Theme.bgAlt
                                    radius: 0
                                    border.width: cell.isCurrent ? 2 : 1
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

                                    Rectangle {
                                        anchors { left: parent.left; right: parent.right; bottom: paletteStrip.top }
                                        anchors.margins: tile.border.width + 2
                                        height: 18
                                        color: Qt.rgba(0, 0, 0, 0.55)
                                        PixelText {
                                            anchors.centerIn: parent
                                            width: parent.width - 8
                                            elide: Text.ElideMiddle
                                            horizontalAlignment: Text.AlignHCenter
                                            text: Glyphs.px(root.fileName(cell.path))
                                            color: Theme.text
                                        }
                                    }

                                    // The theme this wallpaper applies — equal
                                    // columns of its wal tokens, no invented
                                    // hues (§3). Empty until generated.
                                    Row {
                                        id: paletteStrip
                                        readonly property var palette: (root.palettes && root.palettes[cell.gIdx]) || []
                                        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                                        anchors.margins: tile.border.width + 2
                                        height: 16
                                        Repeater {
                                            model: paletteStrip.palette
                                            Rectangle {
                                                required property string modelData
                                                width: Math.ceil(paletteStrip.width / Math.max(1, paletteStrip.palette.length))
                                                height: paletteStrip.height
                                                color: modelData
                                            }
                                        }
                                    }

                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        // Click = pick it; hover deliberately
                                        // never selects (the picker's lesson —
                                        // mousing past must not re-theme).
                                        onClicked: root.applyPath(cell.path)
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
