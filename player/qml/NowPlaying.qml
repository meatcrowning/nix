import QtQuick

// Now playing, two ROWS. The top row is the cover art, edge to edge — it fills
// the full width and meets the window's outline, no margins (its height is a
// draggable, persisted fraction of the view; square covers crop, not
// letterbox). The bottom row is split into two columns: the left carries the
// playing track's identity + transport controls + position readout (scrubbing
// lives on the titlebar's vertical track), and under those the queue; the right column is the lyrics, which
// collapses to zero width whenever the track has none. Lyrics are requested per
// track change and delivered async by the LyricsProvider (embedded → .lrc →
// LRCLIB).
Item {
    id: root
    signal openAlbum(int albumId)

    readonly property var cur: Player.current
    readonly property bool hasLyrics: lyricsView.hasContent

    // Both splits are user-draggable and persisted: the art row's height
    // fraction and the lyrics column's width.
    property real artFrac: Number(Prefs.get("npArtFrac", 0.45))
    property real lyricsW: Number(Prefs.get("npLyricsWidth", 320))

    function fmt(s) {
        s = Math.max(0, Math.round(s));
        return Math.floor(s / 60) + ":" + (s % 60 < 10 ? "0" : "") + (s % 60);
    }

    // ---- top row: cover art -------------------------------------------------
    Item {
        id: artRow
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: Math.max(60, Math.min(root.height * 0.8, root.height * root.artFrac))

        Rectangle {
            id: artBox
            // Edge to edge: the cover fills the whole top row, meeting the
            // window's own outline — no letterbox margins around it. Square
            // art is therefore cropped, not fitted.
            anchors.fill: parent
            color: Theme.bgAlt
            clip: true

            Image {
                anchors.fill: parent
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
    }

    Rectangle {
        id: hsep
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: artRow.bottom
        height: 1
        color: Theme.border
    }
    Item {   // drag handle over the row split
        anchors.left: parent.left
        anchors.right: parent.right
        y: hsep.y - 3
        height: 7
        z: 10
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.SplitVCursor
            onPositionChanged: function(mouse) {
                if (!pressed || root.height <= 0) return;
                var gy = mapToItem(root, 0, mouse.y).y;
                root.artFrac = Math.max(0.1, Math.min(0.8, gy / root.height));
            }
            onReleased: Prefs.set("npArtFrac", root.artFrac)
        }
    }

    // ---- bottom row ---------------------------------------------------------
    Item {
        id: bottomRow
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: hsep.bottom
        anchors.bottom: parent.bottom

        // ---- right column: lyrics (zero width when the track has none) ----
        LyricsView {
            id: lyricsView
            objectName: "lyricsPane"
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.right: parent.right
            width: root.hasLyrics
                   ? Math.max(180, Math.min(bottomRow.width * 0.6, root.lyricsW))
                   : 0
            visible: root.hasLyrics
            clip: true
            trackId: root.cur.id !== undefined ? root.cur.id : -1
            active: root.visible
        }

        Rectangle {
            id: vsep
            anchors.right: lyricsView.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: root.hasLyrics ? 1 : 0
            visible: root.hasLyrics
            color: Theme.border
        }
        Item {   // drag handle over the column split
            x: vsep.x - 3
            width: 7
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            z: 10
            visible: root.hasLyrics
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.SplitHCursor
                onPositionChanged: function(mouse) {
                    if (!pressed) return;
                    var gx = mapToItem(bottomRow, mouse.x, 0).x;
                    root.lyricsW = Math.max(180, Math.min(bottomRow.width * 0.6,
                                                          bottomRow.width - gx));
                }
                onReleased: Prefs.set("npLyricsWidth", root.lyricsW)
            }
        }

        // ---- left column: track identity + transport, queue underneath ----
        Item {
            id: leftCol
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.right: vsep.left

            Column {
                id: info
                anchors.top: parent.top
                anchors.topMargin: 10
                anchors.left: parent.left
                anchors.leftMargin: 8
                anchors.right: parent.right
                anchors.rightMargin: 8
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
                Item { width: 1; height: 8 }

                // ---- transport (same actions as the titlebar buttons), with
                // the track's rating stars + favourite heart trailing it ----
                Row {
                    spacing: 6
                    HeaderButton {
                        label: "<<"
                        onClicked: Player.previous()
                    }
                    HeaderButton {
                        label: Player.playing ? "||" : ">"
                        onClicked: Player.toggle()
                    }
                    HeaderButton {
                        label: ">>"
                        onClicked: Player.next()
                    }
                    Item { width: 6; height: 1 }
                    HeaderButton {
                        label: "*"
                        lit: Player.shuffle
                        onClicked: Player.setShuffle(!Player.shuffle)
                    }
                    HeaderButton {
                        label: Player.loop === 1 ? "1" : "o"
                        lit: Player.loop > 0
                        onClicked: Player.cycleLoop()
                    }
                    Item { width: 6; height: 1 }
                    Stars {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: root.cur.id !== undefined
                        rating: root.cur.rating === null || root.cur.rating === undefined
                                ? -1 : root.cur.rating
                        onRated: function(fmps) { Library.setRating(root.cur.id, fmps); }
                    }
                    Item {
                        width: 14; height: 20
                        visible: root.cur.id !== undefined
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

                // no seek bar here: the titlebar's vertical scrub track (vtb
                // PLAYBAR/SEEK) is the one place to scrub, so this column just
                // reads out the position.
                PixelText {
                    visible: Player.duration > 0
                    text: root.fmt(Player.position) + " / " + root.fmt(Player.duration)
                    color: Theme.textDim
                }
            }

            // ---- queue, filling the rest of the left column ----
            PixelText {
                id: queueHead
                anchors.top: info.bottom
                anchors.topMargin: 10
                x: 8
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
    }
}
