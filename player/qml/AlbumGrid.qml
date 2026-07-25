import QtQuick
import QtQuick.Controls.Basic

// The album grid: edge-to-edge cover tiles with ZERO gap — the cell size
// adapts so whole covers tile the full width exactly. Title / artist / year
// appear only on hover, overlaid on the lower part of the cover itself.
// Thumbs are pre-rendered 256px JPEGs in the art cache, loaded async, so
// scrolling never decodes original artwork.
Item {
    id: root
    signal opened(int albumId)
    signal searchArtist(string artist)

    GridView {
        id: grid
        anchors.fill: parent
        clip: true
        // Seven covers across, whatever the window width — covers scale so the
        // rows stay flush left and right with 0px gaps.
        readonly property int cols: 7
        cellWidth: Math.floor(width / cols)
        cellHeight: cellWidth
        cacheBuffer: 600
        model: AlbumsModel
        ScrollBar.vertical: VScroll {}

        delegate: Rectangle {
            id: tile
            width: grid.cellWidth
            height: grid.cellHeight
            color: Theme.bgAlt

            Image {
                anchors.fill: parent
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

            // Hover: the metadata, inside the cover's lower edge.
            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: labelCol.implicitHeight + 10
                visible: tileMouse.containsMouse
                color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.82)

                Column {
                    id: labelCol
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left
                    anchors.leftMargin: 6
                    anchors.right: parent.right
                    anchors.rightMargin: 6

                    PixelText {
                        width: parent.width
                        text: album
                        elide: Text.ElideRight
                        color: Theme.text
                    }
                    PixelText {
                        width: parent.width
                        text: (year > 0 ? year + "  " : "") + artist
                        elide: Text.ElideRight
                        color: Theme.textDim
                    }
                }
            }
            Rectangle {  // hover frame, drawn over the art's edge
                anchors.fill: parent
                visible: tileMouse.containsMouse
                color: "transparent"
                border.color: Theme.accent
                border.width: 1
            }

            MouseArea {
                id: tileMouse
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
                onClicked: function(m) {
                    if (m.button === Qt.MiddleButton) {
                        Player.queueAlbum(albumId);
                    } else if (m.button === Qt.RightButton) {
                        var p = tileMouse.mapToItem(root, m.x, m.y);
                        var aid = albumId, art = artist;
                        ctxMenu.open(p.x, p.y, [
                            { label: "play",          trigger: function() { Player.playAlbum(aid, 0); } },
                            { label: "play shuffled", trigger: function() { Player.setShuffle(true); Player.playAlbum(aid, 0); } },
                            { label: "add to queue",  trigger: function() { Player.queueAlbum(aid); } },
                            { separator: true },
                            { label: "open album",    trigger: function() { root.opened(aid); } },
                            { label: "search artist", enabled: art !== "",
                              trigger: function() { root.searchArtist(art); } },
                        ]);
                    } else {
                        root.opened(albumId);
                    }
                }
                onDoubleClicked: function(m) {
                    if (m.button === Qt.LeftButton) Player.playAlbum(albumId, 0);
                }
            }
        }
    }

    PixelText {
        anchors.centerIn: parent
        visible: grid.count === 0
        text: "no albums — is the library drive mounted?"
        color: Theme.textDim
    }

    CtxMenu {
        id: ctxMenu
        anchors.fill: parent
    }
}
