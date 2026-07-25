import QtQuick

// One album: the track list on the left, big art + metadata + play/queue
// actions on the right (toward the titlebar edge). Tracks come from
// AlbumTracksModel (loaded by Library.openAlbum before this view is shown).
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

    // The split is draggable and persisted; the cover scales with the column.
    property real sideW: Number(Prefs.get("adSideWidth", 268))

    Item {
        id: side
        width: Math.max(160, Math.min(root.width * 0.6, root.sideW))
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: parent.right

        Rectangle {
            id: artBox
            anchors.top: parent.top
            anchors.topMargin: 12
            anchors.horizontalCenter: parent.horizontalCenter
            width: parent.width - 24
            height: width
            color: Theme.bgAlt
            border.color: Theme.border
            border.width: 1

            Image {
                anchors.fill: parent
                anchors.margins: 1
                source: root.info.fullArt ? "file://" + root.info.fullArt : ""
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                sourceSize.width: 1024
                sourceSize.height: 1024
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
        id: sep
        anchors.right: side.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 1
        color: Theme.border
    }
    Item {   // drag handle over the column split
        x: sep.x - 3
        width: 7
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        z: 10
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.SplitHCursor
            onPositionChanged: function(mouse) {
                if (!pressed) return;
                var gx = mapToItem(root, mouse.x, 0).x;
                root.sideW = Math.max(160, Math.min(root.width * 0.6, root.width - gx));
            }
            onReleased: Prefs.set("adSideWidth", root.sideW)
        }
    }

    TrackList {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.topMargin: 8
        anchors.right: side.left
        anchors.rightMargin: 1
        anchors.bottom: parent.bottom
        model: AlbumTracksModel
        showArtist: false
        onPlayed: function(index) { Player.playAlbum(root.albumId, index); }
    }
}
