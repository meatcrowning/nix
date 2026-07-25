import QtQuick

// The inline album section: opens INSIDE the gallery, directly under the row
// holding the clicked cover (AlbumGrid instantiates one for the open row and
// grows that row to fit it) — it carries what the old separate album page did:
// big art, album/artist/year, play + queue actions, and the album's tracks.
// Tracks come from AlbumTracksModel, loaded by Library.openAlbum before the
// panel is shown.
Item {
    id: root
    property int albumId: 0
    property var info: ({})
    signal closed()

    // Tall enough for the art, and for the track list up to a sane cap — a
    // 30-track album shouldn't push the whole gallery off screen.
    readonly property int rowH: Theme.fontSize + 2
    implicitHeight: Math.max(212, Math.min(430, 24 + AlbumTracksModel.count * rowH))

    onAlbumIdChanged: refresh()
    Component.onCompleted: refresh()

    function refresh() {
        if (albumId > 0)
            info = Library.albumInfo(albumId);
    }
    Connections {
        target: Library
        function onScanStatus() { root.refresh(); }  // art may have just landed
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

    TrackList {
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
