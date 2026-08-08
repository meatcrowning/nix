import QtQuick

// One cell of the directory's preview grid (the strip of thumbnails filer pins
// above the file list). Renders images and video poster frames — both straight
// from `image://thumb/`, because the provider is keyed on the PATH and works out
// how to make a thumbnail itself (main.py's make_thumb / _video_frame). The
// `entry.kind` switch is the scaffold for previews in general: add a branch here
// per previewable kind (PDF first page, …) and a matching classifier in main.py's
// `preview_kind`. Kinds with no branch fall through to a filename-only card, so
// a new kind still renders something before its preview branch exists.
Rectangle {
    id: tile

    required property var entry     // a listDir row: { name, path, kind, ... }
    // Everything the thumbnail provider can serve. Video differs from an image
    // only in wearing the play marker below.
    readonly property bool isVideo: entry.kind === "video"
    readonly property bool hasThumb: entry.kind === "image" || isVideo
    property bool selected: false
    property bool winActive: true
    property int tileSize: 96

    // What a drag from this tile carries (the view's whole selection when this
    // tile is part of a multi-selection, else just this file) and whether that
    // multi-selection exists — the view owns both, the tile only reports them.
    property var dragPaths: [entry.path]
    property bool inMultiSelection: false

    signal clicked(int mods)   // mods: the keyboard modifiers at press (shift/ctrl)
    // carries the click's modifiers: shift-open means a NEW viewer window
    // rather than reusing the one already on screen (BrowserPane.openFile).
    signal opened(int mods)
    // A drag-out starting/ending here. The view has to freeze its model while
    // one is live, or the rebuild destroys this tile mid-drag — the crash
    // documented on BrowserPane.qml's `rebuild()`.
    signal dragStateChanged(bool active)

    width: tileSize
    height: tileSize
    color: selected ? Theme.highlight : Theme.bgAlt
    border.width: 1
    border.color: selected ? (winActive ? Theme.accent : Theme.inactive) : Theme.border

    // Drag-out: same cross-app text/uri-list gesture as the file rows, so a
    // thumbnail can be dropped onto a browser upload field, another file
    // manager, etc. Drag.active is bound to the MouseArea dragging an INVISIBLE
    // proxy (so the tile itself stays put) — that's what starts the real QDrag
    // under dragType Automatic (a bare startDrag() doesn't fire one on Wayland).
    // mimeData is filled on PRESS, not bound: the payload depends on the
    // selection, and a binding would re-run FileOps.uriList for every realised
    // tile on every selection change.
    Drag.active: tileMa.drag.active
    Drag.dragType: Drag.Automatic
    Drag.supportedActions: Qt.CopyAction | Qt.MoveAction | Qt.LinkAction
    Drag.hotSpot.x: 6
    Drag.hotSpot.y: 6

    // the MouseArea drags THIS (invisible, zero-size) proxy instead of the tile,
    // so drag.active flips on without the tile moving.
    Item { id: dragProxy }

    // image preview: served by the `image://thumb/` provider (main.py), which
    // reads/writes the shared freedesktop thumbnail cache so a big photo is
    // decoded once (across all runs, and shared with Dolphin) rather than every
    // time this dir is opened. encodeURI leaves the path's slashes intact and
    // escapes spaces/metachars; the provider re-adds the leading slash Qt strips.
    Image {
        id: thumb
        anchors.fill: parent
        anchors.margins: 3
        visible: tile.hasThumb
        source: tile.hasThumb ? ("image://thumb" + encodeURI(tile.entry.path)) : ""
        sourceSize.width: tile.tileSize * 2
        sourceSize.height: tile.tileSize * 2
        fillMode: Image.PreserveAspectFit
        asynchronous: true
        cache: true
        smooth: false
    }

    // Placeholder glyph: a previewable kind whose real preview isn't wired yet
    // (a filled block), an image still decoding (...), or one that failed to
    // decode — e.g. a truncated/misnamed download (x).
    //
    // ALL THREE MUST BE DRAWABLE BY THE PIXEL FONT (docs/DESIGN.md §2.3). This drew
    // U+25A2 / U+2715 / U+2026, none of which More Perfect DOS VGA has — checked
    // with QRawFont.glyphIndexesForString, all three return glyph 0 — so every
    // not-ready and every failed tile in the grid took a fallback font's taller
    // ascent and clipped. U+25A0 IS in the font (it is what the dot-matrix clock
    // is built from, §3.4); the other two use the same ASCII forms Glyphs.px()
    // maps them to.
    PixelText {
        anchors.centerIn: parent
        visible: !tile.hasThumb || thumb.status !== Image.Ready
        text: !tile.hasThumb ? "■"
            : thumb.status === Image.Error ? "x" : "..."
        color: (tile.hasThumb && thumb.status === Image.Error)
               ? Theme.crit : (tile.winActive ? Theme.textDim : Theme.inactive)
    }

    // The play marker: this tile is a clip, not a still. Only once the poster
    // frame is actually up — over the "..." placeholder it would claim a preview
    // that has not arrived, and over the "x" it would label a file that could not
    // be decoded as playable (docs/DESIGN.md §10: never say an action is available
    // when it may silently fail).
    //
    // DRAWN, NOT LETTERED. The obvious "▶" is U+25B6, and the pixel font is the
    // user's choice: Botis 4x6 has it, More Perfect DOS VGA and Perfect DOS VGA
    // 437 both return glyph 0 (checked with QRawFont.glyphIndexesForString, the
    // same way §2.3's other traps were found), so on two of the three fonts it
    // would take a fallback's taller ascent and clip the chip. A triangle built
    // from a staircase of 1px-tall rows needs no glyph, is exact at any size, and
    // is the same dot-matrix construction the panel's clock uses (§3.4).
    // A Loader, not a `visible: false` Rectangle: the chip is nine items
    // (frame + 7 staircase rows + their parent) and the grid is virtualized for
    // folders of thousands, so a still must not pay for a marker it never wears.
    Loader {
        active: tile.isVideo && thumb.status === Image.Ready
        anchors { left: parent.left; top: parent.top; margins: 4 }
        sourceComponent: Rectangle {
            width: 15
            height: 15
            color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.72)
            border.width: 1
            border.color: tile.winActive ? Theme.border : Theme.inactive
            Item {
                anchors.centerIn: parent
                width: 7
                height: 7
                Repeater {
                    model: 7
                    Rectangle {
                        required property int index
                        // rows 0..6 widen 1,2,3,4,3,2,1 — a symmetric arrowhead
                        // pointing right, centred on the middle row.
                        x: 0
                        y: index
                        height: 1
                        width: 4 - Math.abs(index - 3)
                        color: tile.winActive ? Theme.text : Theme.inactive
                    }
                }
            }
        }
    }

    // filename ribbon across the bottom, over a translucent scrim so it stays
    // legible on top of a bright thumbnail.
    Rectangle {
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        anchors.margins: 1
        height: nameLabel.implicitHeight + 4
        color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.72)
        PixelText {
            id: nameLabel
            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 3; rightMargin: 3 }
            text: tile.entry.name
            elide: Text.ElideMiddle
            horizontalAlignment: Text.AlignHCenter
            color: !tile.winActive ? Theme.inactive : (tile.selected ? Theme.accent : Theme.text)
        }
    }

    MouseArea {
        id: tileMa
        anchors.fill: parent
        // preventStealing so an enclosing Flickable can't grab the press-drag
        // and scroll instead of starting the file drag.
        preventStealing: true
        drag.target: dragProxy
        // A press inside an EXISTING multi-selection must not collapse it — the
        // drag that may follow has to carry the whole set — so that click is
        // deferred to the release and applied only if no drag happened.
        // `dragged` latches on the way in because drag.active is already back to
        // false by the time onReleased runs. (Same rule as the file rows.)
        property bool deferSelect: false
        property bool dragged: false
        drag.onActiveChanged: {
            if (tileMa.drag.active) tileMa.dragged = true;
            tile.dragStateChanged(tileMa.drag.active);
        }
        onPressed: (mouse) => {
            tileMa.dragged = false;
            tileMa.deferSelect = !(mouse.modifiers & (Qt.ShiftModifier | Qt.ControlModifier))
                                 && tile.inMultiSelection;
            if (!tileMa.deferSelect) tile.clicked(mouse.modifiers);
            tile.Drag.mimeData = { "text/uri-list": FileOps.uriList(tile.dragPaths) };
            // stage the drag image from the tile itself (thumbnail + name), so
            // it's ready by the time the drag passes the threshold.
            tile.grabToImage(function(res) { tile.Drag.imageSource = res.url; });
        }
        onReleased: {
            if (tileMa.deferSelect && !tileMa.dragged) tile.clicked(0);   // plain click: collapse to this one
            tileMa.deferSelect = false;
            tile.dragStateChanged(false);
        }
        onCanceled: tile.dragStateChanged(false)
        onDoubleClicked: (m) => tile.opened(m.modifiers)
    }
}
