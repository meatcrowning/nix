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

    signal clicked()
    signal opened()

    width: tileSize
    height: tileSize
    color: selected ? Theme.highlight : Theme.bgAlt
    border.width: 1
    border.color: selected ? (winActive ? Theme.accent : Theme.inactive) : Theme.border

    // image preview: the file itself, downscaled by sourceSize so a huge photo
    // doesn't decode at full resolution just to fill a 96px cell. encodeURI on
    // the path matches the drag-out mime code — spaces/most metachars survive.
    Image {
        id: thumb
        anchors.fill: parent
        anchors.margins: 3
        visible: tile.entry.kind === "image"
        source: tile.entry.kind === "image" ? ("file://" + encodeURI(tile.entry.path)) : ""
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
        anchors.fill: parent
        onPressed: tile.clicked()
        onDoubleClicked: tile.opened()
    }
}
