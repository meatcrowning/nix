import QtQuick

// Now playing, two columns: the left is split horizontally — queue on top,
// lyrics below (the queue takes the full height when the track has none);
// the right column is art + track identity + rating/favourite (toward the
// titlebar edge). Lyrics are requested per track change and delivered async
// by the LyricsProvider (embedded → .lrc → LRCLIB).
Item {
    id: root
    signal openAlbum(int albumId)

    readonly property var cur: Player.current

    // Both splits are user-draggable and persisted: the art column's width
    // and the queue/lyrics fraction.
    property real sideW: Number(Prefs.get("npSideWidth", 268))
    property real lyricsFrac: Number(Prefs.get("npLyricsFrac", 0.5))

    // ---- right: art + identity (cover scales with the column) ----
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
                source: root.cur.artPath ? "file://" + root.cur.artPath : ""
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                sourceSize.width: 1024
                sourceSize.height: 1024
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
                color: root.cur.title ? Theme.text : Theme.textDim
            }
            PixelText {
                width: parent.width
                text: root.cur.artist || ""
                clip: true
                height: Theme.fontSize + 2  // descender room: 16px ink in the 15px line
                color: Theme.textDim
            }
            PixelText {
                width: parent.width
                text: root.cur.album || ""
                clip: true
                height: Theme.fontSize + 2  // descender room: 16px ink in the 15px line
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
    Item {   // drag handle over the column split
        x: sep1.x - 3
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
            onReleased: Prefs.set("npSideWidth", root.sideW)
        }
    }

    // ---- left column, top: queue (full height when the track has no lyrics) ----
    Item {
        id: queuePane
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.right: sep1.left
        anchors.bottom: sep2.top

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
        anchors.left: parent.left
        anchors.right: sep1.left
        anchors.bottom: lyricsView.top
        height: lyricsView.hasContent ? 1 : 0
        visible: lyricsView.hasContent
        color: Theme.border
    }
    Item {   // drag handle over the queue/lyrics split
        anchors.left: parent.left
        anchors.right: sep1.left
        y: sep2.y - 3
        height: 7
        z: 10
        visible: lyricsView.hasContent
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.SplitVCursor
            onPositionChanged: function(mouse) {
                if (!pressed) return;
                var gy = mapToItem(root, 0, mouse.y).y;
                root.lyricsFrac = Math.max(0.1, Math.min(0.85, 1 - gy / root.height));
            }
            onReleased: Prefs.set("npLyricsFrac", root.lyricsFrac)
        }
    }

    // ---- left column, bottom: lyrics — zero height until the track has some ----
    LyricsView {
        id: lyricsView
        objectName: "lyricsPane"
        anchors.left: parent.left
        anchors.right: sep1.left
        anchors.bottom: parent.bottom
        height: hasContent ? parent.height * root.lyricsFrac : 0
        visible: hasContent
        clip: true
        trackId: root.cur.id !== undefined ? root.cur.id : -1
        active: root.visible
    }
}
