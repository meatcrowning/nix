import QtQuick

// The album grid: cover tiles with name + artist/year, fed by AlbumsModel
// (sorted/filtered in Python). Thumbs are pre-rendered 256px JPEGs in the art
// cache, loaded async, so scrolling never decodes original artwork.
Item {
    id: root
    signal opened(int albumId)

    GridView {
        id: grid
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.topMargin: 8
        clip: true
        cellWidth: 196
        cellHeight: 196 + 38
        cacheBuffer: 400
        model: AlbumsModel

        delegate: Item {
            width: grid.cellWidth
            height: grid.cellHeight

            Rectangle {
                id: tile
                anchors.top: parent.top
                anchors.horizontalCenter: parent.horizontalCenter
                width: 180
                height: 180
                color: Theme.bgAlt
                border.color: tileMouse.containsMouse ? Theme.accent : Theme.border
                border.width: 1

                Image {
                    anchors.fill: parent
                    anchors.margins: 1
                    source: thumbPath ? "file://" + thumbPath : ""
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                    cache: true
                    sourceSize.width: 256
                    sourceSize.height: 256
                    visible: status === Image.Ready
                }
                PixelText {
                    anchors.centerIn: parent
                    visible: !thumbPath
                    text: "♫"
                    font.pixelSize: 45
                    color: Theme.dim
                }
            }
            PixelText {
                id: nameText
                anchors.top: tile.bottom
                anchors.topMargin: 3
                anchors.left: tile.left
                anchors.right: tile.right
                text: album
                elide: Text.ElideRight
                color: tileMouse.containsMouse ? Theme.accent : Theme.text
            }
            PixelText {
                anchors.top: nameText.bottom
                anchors.left: tile.left
                anchors.right: tile.right
                text: (year > 0 ? year + "  " : "") + artist
                elide: Text.ElideRight
                color: Theme.textDim
            }
            MouseArea {
                id: tileMouse
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.LeftButton | Qt.MiddleButton
                onClicked: function(m) {
                    if (m.button === Qt.MiddleButton) Player.queueAlbum(albumId);
                    else root.opened(albumId);
                }
                onDoubleClicked: Player.playAlbum(albumId, 0)
            }
        }
    }

    PixelText {
        anchors.centerIn: parent
        visible: grid.count === 0
        text: "no albums — is the library drive mounted?"
        color: Theme.textDim
    }
}
