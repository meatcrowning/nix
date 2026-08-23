import QtQuick
import "../../qmlcommon"

// The inline album section: opens INSIDE the gallery, directly under the row
// holding the clicked cover (AlbumGrid instantiates one for the open row and
// grows that row to fit it) — it carries what the old separate album page did:
// big art, album/artist/year, play + queue actions, and the album's tracks.
//
// The panel LOADS ITS OWN tracks (Library.openAlbum fills the shared
// AlbumTracksModel) rather than trusting whoever opened it to have done so —
// it is created on every open, including a delegate rebuilt after scrolling
// away and back, so the track list can never come up empty/stale.
//
// Its layout is RESPONSIVE, because the player window is often a narrow
// column: side by side (art | info | tracks) when there is room, otherwise
// stacked — art + info on top, the track list full-width underneath. Geometry
// is set explicitly rather than by anchors so nothing can be squeezed to a
// zero-width sliver on a narrow window.
Item {
    id: root

    // display-site px() for foreign text (docs/DESIGN.md 2.3)
    Glyphs { id: glyphs }
    property int albumId: 0
    property var info: ({})
    // Foreground tones, handed in already faded by the gallery
    // (docs/DESIGN.md §3.1.1), plus `fgArt` — the opacity this section's cover
    // fades to alongside them. See AlbumGrid, and Main.qml for the value.
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent
    property real fgArt: 1.0
    signal closed()
    // Relayed out of the track list's right-click menu (AlbumGrid passes them
    // on to the window, which owns navigation).
    signal openAlbumRequested(int albumId)
    signal browseArtistRequested(string artist)

    readonly property int rowH: Theme.lineHeight + 2
    readonly property int pad: 10

    // Not enough width for three columns → stack the track list underneath.
    // "Enough" is judged by what the TRACKS column would get, not by whether
    // three columns technically fit: below ~900 the side-by-side list is ~200px
    // and the stars/heart/duration cut every title to its first word.
    readonly property bool stacked: width < 900
    // Stacked art shrinks only when the width genuinely forces it — a panel
    // that used to be side-by-side keeps its full-size cover; the ~480 narrow
    // window keeps exactly the layout it had.
    readonly property int artSide: stacked ? Math.max(60, Math.min(width >= 700 ? 200 : 150, width - 240)) : 200
    readonly property int metaX: pad + artSide + 12
    readonly property int metaW: Math.max(80, stacked ? width - metaX - pad
                                                      : Math.min(260, width - metaX - 212))
    // The section shows EVERY track — it never scrolls internally, it just
    // gets as tall as the album needs and the gallery scrolls past it.
    readonly property int listH: Math.max(20, AlbumTracksModel.count * rowH + 6)

    implicitHeight: stacked ? pad + artSide + 8 + listH + 8
                            : Math.max(232, listH + 16)

    onAlbumIdChanged: load()
    Component.onCompleted: load()

    property int _loadedId: 0

    function load() {
        // Both the initial binding and onCompleted land here — load once.
        if (albumId <= 0 || albumId === _loadedId)
            return;
        _loadedId = albumId;
        Library.openAlbum(albumId);   // fills AlbumTracksModel for this album
        info = Library.albumInfo(albumId);
    }
    Connections {
        target: Library
        function onScanStatus() {     // art / tracks may have just landed
            if (root.albumId > 0)
                root.info = Library.albumInfo(root.albumId);
        }
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.bg
        radius: Theme.rounding
        border.color: Theme.border
        border.width: Theme.ctrlBorder
    }
    // Accent edge along the top, tying the section to the cover above it.
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 1
        color: root.fgAccent
    }

    Rectangle {
        id: artBox
        x: root.pad
        y: root.stacked ? root.pad : Math.max(root.pad, (root.height - root.artSide) / 2)
        width: Math.max(1, root.artSide)
        height: width
        color: Theme.bgAlt
        radius: Theme.rounding
        border.color: Theme.border
        border.width: Theme.ctrlBorder

        Image {
            anchors.fill: parent
            anchors.margins: 1
            source: root.info.fullArt ? "file://" + root.info.fullArt : ""
            fillMode: Image.PreserveAspectFit
            asynchronous: true
            sourceSize.width: 1024
            sourceSize.height: 1024
            visible: status === Image.Ready
            opacity: root.fgArt      // fades with the foreground, onto artBox's bgAlt
        }
        PixelText {
            anchors.centerIn: parent
            visible: !root.info.fullArt
            text: "♫"
            font.pixelSize: 50
            color: Theme.dim
        }
    }

    Column {
        id: meta
        x: root.metaX
        y: artBox.y
        width: root.metaW
        spacing: 2

        PixelText {
            width: parent.width
            text: glyphs.px(root.info.album || "")
            wrapMode: Text.Wrap
            maximumLineCount: root.stacked ? 2 : 3
            color: root.fgText
        }
        PixelText {
            width: parent.width
            text: glyphs.px(root.info.artist || "")
            clip: true
            height: Theme.lineHeight + 2  // descender room: one cell + 1px each side
            color: root.fgDim
        }
        PixelText {
            width: parent.width
            text: (root.info.year > 0 ? root.info.year + "  ·  " : "")
                  + (root.info.trackCount || 0) + " tracks"
            color: root.fgDim
        }
        Item { width: 1; height: 8 }
        Row {
            spacing: 10
            HeaderButton {
                label: "> play"
                plainLabel: "play"; iconName: "media-playback-start"
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                onClicked: Player.playAlbum(root.albumId, -1)  // -1: nothing pinned under shuffle
            }
            HeaderButton {
                label: "+ queue"
                plainLabel: "queue"; iconName: "list-add"
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                onClicked: Player.queueAlbum(root.albumId)
            }
            HeaderButton {
                label: "x close"
                plainLabel: "close"; iconName: "window-close"
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                onClicked: root.closed()
            }
        }
    }

    TrackList {
        id: tracks
        x: root.stacked ? root.pad : root.metaX + root.metaW + 12
        y: root.stacked ? artBox.y + root.artSide + 8 : 8
        width: Math.max(1, root.width - x - (root.stacked ? root.pad : 4))
        height: Math.max(1, root.height - y - 8)
        model: AlbumTracksModel
        fgText: root.fgText
        fgDim: root.fgDim
        fgAccent: root.fgAccent
        showArtist: false
        scrollable: false      // the panel is sized to hold every row
        inAlbum: root.albumId  // "go to album" would land where we already are
        onPlayed: function(index) { Player.playAlbum(root.albumId, index); }
        onOpenAlbumRequested: function(aid) { root.openAlbumRequested(aid); }
        onBrowseArtistRequested: function(a) { root.browseArtistRequested(a); }
    }
    PixelText {
        x: tracks.x
        y: tracks.y + 4
        visible: AlbumTracksModel.count === 0
        text: "no tracks"
        color: Theme.dim
    }
}
