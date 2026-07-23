import QtQuick

// One cell of the directory's preview grid (the strip of thumbnails filer pins
// above the file list). Currently renders images only — straight from the file
// through a downscaled, async Image — but the `entry.kind` switch is the
// scaffold for file previews in general: add a branch here per previewable kind
// (video poster frame, PDF first page, …) and a matching classifier in main.py's
// `preview_kind`. Non-image kinds fall through to a filename-only card, so a new
// kind still renders something before its preview branch exists.
Rectangle {
    id: tile

    required property var entry     // a listDir row: { name, path, kind, ... }
    property bool selected: false
    property bool winActive: true
    property int tileSize: 96

    signal clicked(int mods)   // mods: the keyboard modifiers at press (shift/ctrl)
    signal opened()

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
    // encodeURI matches PreviewTile's Image source and the row drag code.
    Drag.active: tileMa.drag.active
    Drag.dragType: Drag.Automatic
    Drag.supportedActions: Qt.CopyAction | Qt.LinkAction
    Drag.mimeData: ({ "text/uri-list": "file://" + encodeURI(tile.entry.path) + "\r\n" })
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
        visible: tile.entry.kind === "image"
        source: tile.entry.kind === "image" ? ("image://thumb" + encodeURI(tile.entry.path)) : ""
        sourceSize.width: tile.tileSize * 2
        sourceSize.height: tile.tileSize * 2
        fillMode: Image.PreserveAspectFit
        asynchronous: true
        cache: true
        smooth: false
    }

    // placeholder glyph: a previewable kind whose real preview isn't wired yet
    // (▢), an image still decoding (…), or one that failed to decode — e.g. a
    // truncated/misnamed download (✕).
    PixelText {
        anchors.centerIn: parent
        visible: tile.entry.kind !== "image" || thumb.status !== Image.Ready
        text: tile.entry.kind !== "image" ? "▢"
            : thumb.status === Image.Error ? "✕" : "…"
        color: (tile.entry.kind === "image" && thumb.status === Image.Error)
               ? Theme.crit : (tile.winActive ? Theme.textDim : Theme.inactive)
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
        onPressed: (mouse) => {
            tile.clicked(mouse.modifiers);
            // stage the drag image from the tile itself (thumbnail + name), so
            // it's ready by the time the drag passes the threshold.
            tile.grabToImage(function(res) { tile.Drag.imageSource = res.url; });
        }
        onDoubleClicked: tile.opened()
    }
}
