import QtQuick

// One album: big art + metadata + play/queue actions on the left, the track
// list on the right. Tracks come from AlbumTracksModel (loaded by
// Library.openAlbum before this view is shown).
Item {
    id: root
    property int albumId: 0
    property var info: ({})
    signal back()

    onAlbumIdChanged: refresh()
    onVisibleChanged: if (visible) refresh()

    function refresh() {
        if (albumId > 0)
            info = Library.albumInfo(albumId);
    }
    Connections {
        target: Library
        function onScanStatus() { root.refresh(); }  // art may have just landed
    }

    Item {
        id: side
        width: 268
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.left: parent.left

        Rectangle {
            id: artBox
            anchors.top: parent.top
            anchors.topMargin: 12
            anchors.horizontalCenter: parent.horizontalCenter
            width: 244
            height: 244
            color: Theme.bgAlt
            border.color: Theme.border
            border.width: 1

            Image {
                anchors.fill: parent
                anchors.margins: 1
                source: root.info.fullArt ? "file://" + root.info.fullArt : ""
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                sourceSize.width: 488
                sourceSize.height: 488
                visible: status === Image.Ready
            }
            PixelText {
                anchors.centerIn: parent
                visible: !root.info.fullArt
                text: "♫"
                font.pixelSize: 60
                color: Theme.dim
            }
        }

        Column {
            anchors.top: artBox.bottom
            anchors.topMargin: 8
            anchors.left: parent.left
            anchors.leftMargin: 12
            anchors.right: parent.right
            anchors.rightMargin: 12
            spacing: 2

            PixelText {
                width: parent.width
                text: root.info.album || ""
                wrapMode: Text.Wrap
                maximumLineCount: 3
                elide: Text.ElideRight
                color: Theme.text
            }
            PixelText {
                width: parent.width
                text: root.info.artist || ""
                elide: Text.ElideRight
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
                    label: "< back"
                    onClicked: root.back()
                }
            }
        }
    }

    Rectangle {
        anchors.left: side.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 1
        color: Theme.border
    }

    TrackList {
        anchors.left: side.right
        anchors.leftMargin: 1
        anchors.top: parent.top
        anchors.topMargin: 8
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        model: AlbumTracksModel
        showArtist: false
        onPlayed: function(index) { Player.playAlbum(root.albumId, index); }
    }
}
