import QtQuick

// Now playing: the play queue on the left, lyrics in the middle, art + track
// identity + rating/favourite on the right (toward the titlebar edge). Lyrics
// are requested per track change and delivered async by the LyricsProvider
// (embedded → .lrc → LRCLIB).
Item {
    id: root
    signal openAlbum(int albumId)

    readonly property var cur: Player.current

    // ---- right: art + identity ----
    Item {
        id: side
        width: 268
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: parent.right

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
                source: root.cur.artPath ? "file://" + root.cur.artPath : ""
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                sourceSize.width: 488
                sourceSize.height: 488
                visible: status === Image.Ready
            }
            PixelText {
                anchors.centerIn: parent
                visible: !root.cur.artPath
                text: "♫"
                font.pixelSize: 60
                color: Theme.dim
            }
            MouseArea {
                anchors.fill: parent
                enabled: (root.cur.albumId || 0) > 0
                onDoubleClicked: root.openAlbum(root.cur.albumId)
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
                text: root.cur.title || "nothing playing"
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
                color: root.cur.title ? Theme.text : Theme.textDim
            }
            PixelText {
                width: parent.width
                text: root.cur.artist || ""
                elide: Text.ElideRight
                color: Theme.textDim
            }
            PixelText {
                width: parent.width
                text: root.cur.album || ""
                elide: Text.ElideRight
                color: Theme.textDim
            }
            Item { width: 1; height: 6 }
            Row {
                spacing: 12
                visible: root.cur.id !== undefined
                Stars {
                    anchors.verticalCenter: parent.verticalCenter
                    rating: root.cur.rating === null || root.cur.rating === undefined
                            ? -1 : root.cur.rating
                    onRated: function(fmps) { Library.setRating(root.cur.id, fmps); }
                }
                Item {
                    width: 12; height: 15
                    anchors.verticalCenter: parent.verticalCenter
                    PixelText {
                        anchors.centerIn: parent
                        text: "♥"
                        color: root.cur.favorite ? Theme.crit : Theme.dim
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: Library.setFavorite(root.cur.id, !root.cur.favorite)
                    }
                }
            }
            Item { width: 1; height: 6 }
            PixelText {
                function fmt(s) {
                    s = Math.max(0, Math.round(s));
                    return Math.floor(s / 60) + ":" + (s % 60 < 10 ? "0" : "") + (s % 60);
                }
                visible: Player.duration > 0
                text: fmt(Player.position) + " / " + fmt(Player.duration)
                color: Theme.textDim
            }
        }
    }

    Rectangle {
        id: sep1
        anchors.right: side.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 1
        color: Theme.border
    }

    // ---- left: queue ----
    Item {
        id: queuePane
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: Math.max(260, (parent.width - side.width) * 0.45)

        PixelText {
            id: queueHead
            x: 8
            y: 8
            text: "queue  (" + Player.queueLength + ")"
            color: Theme.textDim
        }
        TrackList {
            anchors.top: queueHead.bottom
            anchors.topMargin: 4
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            model: QueueModel
            showNumber: false
            onPlayed: function(index) { Player.jumpTo(index); }
        }
    }

    Rectangle {
        id: sep2
        anchors.left: queuePane.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 1
        color: Theme.border
    }

    // ---- middle: lyrics ----
    LyricsView {
        anchors.left: sep2.right
        anchors.top: parent.top
        anchors.right: sep1.left
        anchors.bottom: parent.bottom
        trackId: root.cur.id !== undefined ? root.cur.id : -1
        active: root.visible
    }
}
