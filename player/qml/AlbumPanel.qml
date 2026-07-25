import QtQuick

// The inline album section: opens INSIDE the gallery, directly under the row
// holding the clicked cover (AlbumGrid instantiates one for the open row and
// grows that row to fit it) — it carries what the old separate album page did:
// big art, album/artist/year, play + queue actions, and the album's tracks.
//
// The panel LOADS ITS OWN tracks (Library.openAlbum fills the shared
// AlbumTracksModel) rather than trusting whoever opened it to have done so —
// it is created on every open, including a delegate rebuilt after scrolling
// away and back, so the track list can never come up empty/stale.
Item {
    id: root
    property int albumId: 0
    property var info: ({})
    signal closed()

    // Tall enough for the art, and for the track list up to a sane cap — a
    // 30-track album shouldn't push the whole gallery off screen.
    readonly property int rowH: Theme.fontSize + 2
    implicitHeight: Math.max(232, Math.min(430, 24 + AlbumTracksModel.count * rowH))

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
        border.color: Theme.border
        border.width: 1
    }
    // Accent edge along the top, tying the section to the cover above it.
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 1
        color: Theme.accent
    }

    Rectangle {
        id: artBox
        anchors.left: parent.left
        anchors.leftMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        width: Math.max(1, Math.min(root.height - 24, 200))
        height: width
        color: Theme.bgAlt
        border.color: Theme.border
        border.width: 1

        Image {
            anchors.fill: parent
            anchors.margins: 1
            source: root.info.fullArt ? "file://" + root.info.fullArt : ""
            fillMode: Image.PreserveAspectFit
            asynchronous: true
            sourceSize.width: 1024
            sourceSize.height: 1024
            visible: status === Image.Ready
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
        anchors.left: artBox.right
        anchors.leftMargin: 12
        anchors.top: artBox.top
        width: Math.max(0, Math.min(260, root.width - artBox.width - 40))
        spacing: 2

        PixelText {
            width: parent.width
            text: root.info.album || ""
            wrapMode: Text.Wrap
            maximumLineCount: 3
            color: Theme.text
        }
        PixelText {
            width: parent.width
            text: root.info.artist || ""
            clip: true
            height: Theme.fontSize + 2  // descender room: 16px ink in the 15px line
            color: Theme.textDim
        }
        PixelText {
            width: parent.width
            text: (root.info.year > 0 ? root.info.year + "  ·  " : "")
                  + (root.info.trackCount || 0) + " tracks"
            color: Theme.textDim
        }
        Item { width: 1; height: 8 }
        Row {
            spacing: 10
            HeaderButton {
                label: "> play"
                onClicked: Player.playAlbum(root.albumId, 0)
            }
            HeaderButton {
                label: "+ queue"
                onClicked: Player.queueAlbum(root.albumId)
            }
            HeaderButton {
                label: "× close"
                onClicked: root.closed()
            }
        }
    }

    PixelText {
        anchors.centerIn: tracks
        visible: AlbumTracksModel.count === 0
        text: "no tracks"
        color: Theme.dim
    }
    TrackList {
        id: tracks
        anchors.left: meta.right
        anchors.leftMargin: 12
        anchors.right: parent.right
        anchors.rightMargin: 2
        anchors.top: parent.top
        anchors.topMargin: 8
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 8
        model: AlbumTracksModel
        showArtist: false
        onPlayed: function(index) { Player.playAlbum(root.albumId, index); }
    }
}
