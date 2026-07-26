import QtQuick

// Now playing, two ROWS. The top row is the cover art, edge to edge — it fills
// the full width and meets the window's outline, no margins (its height is a
// draggable, persisted fraction of the view; square covers crop, not
// letterbox). The bottom row is split into two columns: the left carries the
// playing track's identity (title + rating + artist + album) and under it the
// queue — no transport controls and no position readout, both of which live in
// the titlebar now; the right column is the lyrics, which
// collapses to zero width whenever the track has none. Lyrics are requested per
// track change and delivered async by the LyricsProvider (embedded → .lrc →
// LRCLIB).
Item {
    id: root
    signal openAlbum(int albumId)
    // "show me this artist": the window lands on the gallery with the search
    // bar carrying that name, exactly as if it had been typed.
    signal browseArtist(string artist)

    // Which name the cover's menu acts on: the ALBUM artist, since that's the
    // tag the gallery filter matches — except on a compilation, where it names
    // no one and the playing track's own artist is the useful answer.
    readonly property string coverArtist: {
        var aa = root.cur.albumArtist || "";
        return (aa === "" || aa.toLowerCase() === "various artists" || aa.toLowerCase() === "va")
               ? (root.cur.artist || "") : aa;
    }

    readonly property var cur: Player.current
    readonly property bool hasLyrics: lyricsView.hasContent

    // Both splits are user-draggable and persisted: the art row's height
    // fraction and the lyrics column's width.
    property real artFrac: Number(Prefs.get("npArtFrac", 0.45))
    property real lyricsW: Number(Prefs.get("npLyricsWidth", 320))

    // ---- top row: cover art -------------------------------------------------
    Item {
        id: artRow
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        // On air the window runs narrow: never let the row grow taller than
        // it is wide, or a square cover crops away most of its width. On top
        // the window is wide enough that the fraction alone is the right cap.
        readonly property real hCap: OnAir ? Math.min(root.height * 0.8, root.width)
                                           : root.height * 0.8
        height: Math.max(60, Math.min(hCap, root.height * root.artFrac))

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
                id: artMouse
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                enabled: (root.cur.albumId || 0) > 0
                onDoubleClicked: function(m) {
                    if (m.button === Qt.LeftButton) root.openAlbum(root.cur.albumId);
                }
                onClicked: function(m) {
                    if (m.button !== Qt.RightButton) return;
                    var aid = root.cur.albumId, art = root.coverArtist;
                    var p = artMouse.mapToItem(root, m.x, m.y);
                    // The queue actions stay put — you keep watching what you
                    // just started. Leaving for the gallery is its own row.
                    coverMenu.open(p.x, p.y, [
                        { label: "play album",
                          trigger: function() { Player.playAlbum(aid, 0); } },
                        { label: "shuffle artist",
                          enabled: art !== "",
                          trigger: function() { Player.playArtistShuffled(art); } },
                        { separator: true },
                        { label: "search for artist",
                          enabled: art !== "",
                          trigger: function() { root.browseArtist(art); } },
                        { label: "open album",
                          trigger: function() { root.openAlbum(aid); } },
                    ]);
                }
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

                // Title, with the rating stars + favourite heart pinned to its
                // far right — this is the one ALWAYS-visible rating setter (the
                // queue's per-row ones are hover-only), so it sits on the line
                // that names what it rates.
                Item {
                    width: parent.width
                    height: Math.max(titleText.height, rateBits.height)

                    PixelText {
                        id: titleText
                        anchors.left: parent.left
                        anchors.right: rateBits.left
                        anchors.rightMargin: 8
                        text: root.cur.title || "nothing playing"
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        color: root.cur.title ? Theme.text : Theme.textDim
                    }
                    Row {
                        id: rateBits
                        anchors.right: parent.right
                        anchors.top: parent.top
                        height: 15   // matches TrackList's right-hand column box
                        spacing: 0
                        visible: root.cur.id !== undefined

                        Stars {
                            anchors.verticalCenter: parent.verticalCenter
                            rating: root.cur.rating === null || root.cur.rating === undefined
                                    ? -1 : root.cur.rating
                            onRated: function(fmps) { Library.setRating(root.cur.id, fmps); }
                        }
                        Item {
                            width: 14
                            height: 15
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
                }
                PixelText {
                    width: parent.width
                    text: root.cur.artist || ""
                    clip: true
                    height: Theme.fontSize + 2  // descender room: 16px ink in the 15px line
                    color: Theme.textDim
                }
                // Album, with its original release year trailing the name. The
                // name yields width to the year rather than the other way round,
                // so a long album title clips and the date stays readable.
                Row {
                    width: parent.width
                    height: Theme.fontSize + 2
                    spacing: 6

                    PixelText {
                        text: root.cur.album || ""
                        clip: true
                        width: Math.max(0, Math.min(implicitWidth,
                                        parent.width - (albumYear.visible
                                                        ? albumYear.width + parent.spacing : 0)))
                        height: Theme.fontSize + 2  // descender room, as above
                        color: Theme.textDim
                    }
                    PixelText {
                        id: albumYear
                        visible: (root.cur.year || 0) > 0 && (root.cur.album || "") !== ""
                        text: root.cur.year
                        height: Theme.fontSize + 2
                        color: Theme.dim
                    }
                }
                // Nothing else lives under the album line any more. Shuffle and
                // loop moved out to the titlebar (they were the last duplicated
                // controls left down here), and the position readout moved to
                // the titlebar footer, under the scrub track it belongs to — so
                // every transport control is now in exactly one place.
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
                objectName: "queueList"   // handle for headless layout harnesses
                anchors.top: queueHead.bottom
                anchors.topMargin: 4
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                model: QueueModel
                showNumber: false
                // only name the artist on rows that aren't the playing one's
                hideArtist: root.cur.artist || ""
                // the queue model IS the play order, so identify the playing row
                // by index (a queue can hold the same track twice) and scroll it
                // to the middle as playback advances.
                currentRow: Player.index
                followCurrent: true
                ratingsOnHover: true
                onPlayed: function(index) { Player.jumpTo(index); }
            }
        }
    }

    CtxMenu {
        id: coverMenu
        objectName: "coverMenu"   // handle for headless harnesses
        anchors.fill: parent
    }
}
