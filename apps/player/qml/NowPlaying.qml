import QtQuick
import "../../qmlcommon"

// Now playing, in two parts: the cover art, and everything else. The art is
// edge to edge — it meets the window's outline with no margins, and square
// covers crop rather than letterbox (docs/DESIGN.md §5.1). WHICH edge it takes
// is responsive (`sideArt`, below): a top row in the narrow window this page
// normally lives in, its height a draggable persisted fraction of the view; a
// left column once the window is wide, where a top row would crop the cover
// down to a band. The rest is split into two columns: the left carries the
// playing track's identity (title + rating + artist + album) and under it the
// queue — no transport controls and no position readout, both of which live in
// the titlebar now; the right column is the lyrics, which
// collapses to zero width whenever the track has none. Lyrics are requested per
// track change and delivered async by the LyricsProvider (embedded → .lrc →
// LRCLIB).
Item {
    id: root

    // display-site px() for foreign text (docs/DESIGN.md 2.3)
    Glyphs { id: glyphs }
    signal openAlbum(int albumId)
    // "show me this artist": the window lands on the gallery with the search
    // bar carrying that name, exactly as if it had been typed.
    signal browseArtist(string artist)

    // Foreground tones, handed in already faded by Main (docs/DESIGN.md §3.1.1)
    // and passed straight on to the queue, the lyrics pane and the stars.
    //
    // THE COVER ART FADES TOO, via `fgArt` — his explicit call (2026-07-28),
    // reversing the earlier reading that an image is content and stays lit:
    // *"dim it with everything else — the window reads as one unfocused
    // surface"*. On this page the cover IS the page, so leaving it lit was the
    // one place where the two-step fade was most visible. It has no
    // `Theme.inactive` version, so it composites toward the `Theme.bgAlt` fill
    // behind it instead; Main.qml owns the multiplier and the measurement.
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent
    property real fgArt: 1.0

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

    // Art on TOP, or art in a COLUMN down the left? A top row spans the whole
    // window width, so `PreserveAspectCrop` scales a square cover to that WIDTH
    // and keeps only the horizontal band the row is tall. In the narrow window
    // this page normally lives in that costs little (480x826: 77% of the cover
    // survives); maximized it is ruinous (1880x1050: a 1880x472 band — 25% of
    // the art, a slice of somebody's hair). The crop gets worse the wider the
    // window, which is the opposite of what more space should buy.
    //
    // So once the window is wide enough that a full-height cover leaves a usable
    // content column, the art becomes that column: as good as uncropped, still
    // bleeding to the three edges it touches (docs/DESIGN.md §5.1), and the
    // width it frees goes to the queue and the lyrics rather than to nothing
    // (§5.2). Same responsive reading as AlbumPanel's `stacked`, and §5.6.
    //
    // Two constants. The content column's floor is 420 — near the 480 the whole
    // page gets in the narrowest window player will open (Main.qml's
    // `minimumWidth` on top), so nothing in it is squeezed below a width it
    // already survives every day, and the cover keeps the rest. That matters at
    // the size this is actually judged at: maximized here is ~1406x1006, not
    // 1880, because the panel reserves 376px of the 1920 — 420 leaves 98% of
    // the cover, 480 would clip 8% of it. 0.6 is the point where the column is
    // worth taking — it shows at least 60% of the cover against the 25-42% the
    // row shows at those widths — and every pixel above the floor goes to the
    // content, so a genuinely wide window gets both a whole cover and a roomy
    // queue.
    //
    // The test is WINDOW GEOMETRY only, never `artFrac` — a layout that could
    // flip mid-drag would be the split handle rearranging the page under the
    // cursor.
    readonly property int artColMin: 420
    readonly property bool sideArt: width >= height * 0.6 + artColMin

    // IN A PLASMA SESSION THE COVER IS NEVER CROPPED. His call, 2026-08-18 —
    // and it is a straight trade, not a refinement of the reasoning above: the
    // edge-to-edge fill (docs/DESIGN.md §5.1, and the whole row-vs-column
    // argument overhead) buys a cover with no letterbox at the price of a band
    // through the middle of the art, and in that session he wants the art. So
    // the picture is FITTED inside whatever region `artRow` is, centred, with
    // the shortfall showing `artBox`'s own `bgAlt` — the same surface the row
    // already draws behind a track with no art at all.
    //
    // The Hyprland session is untouched (and keeps the crop), which is why this
    // is a property and not an edit to the fillMode line.
    readonly property bool plasma: (typeof DeskStyle !== "undefined" && DeskStyle)
                                   ? DeskStyle.plasma === true : false

    // ---- cover art: the top row, or the left column --------------------------
    Item {
        id: artRow
        x: 0
        y: 0
        // On air the window runs narrow: never let the row grow taller than
        // it is wide, or a square cover crops away most of its width. On top
        // the window is wide enough that the fraction alone is the right cap.
        readonly property real hCap: OnAir ? Math.min(root.height * 0.8, root.width)
                                           : root.height * 0.8
        // In the column the cover runs the full height and takes every pixel of
        // width the content column can spare, up to square. There is nothing
        // left to trade at that point, so that mode has no drag handle.
        width: root.sideArt ? Math.min(root.height, root.width - root.artColMin)
                            : root.width
        height: root.sideArt ? root.height
                             : Math.max(60, Math.min(hCap, root.height * root.artFrac))

        Rectangle {
            id: artBox
            // Edge to edge: the cover fills whichever region artRow is —
            // the top row, or the left column — meeting the window's own
            // outline with no letterbox margins around it. Art that does not
            // match that region's shape is therefore cropped, not fitted —
            // EXCEPT in a Plasma session, where it is fitted whole (see
            // `root.plasma` above).
            anchors.fill: parent
            color: Theme.bgAlt
            clip: true

            Image {
                anchors.fill: parent
                source: root.cur.artPath ? "file://" + root.cur.artPath : ""
                fillMode: root.plasma ? Image.PreserveAspectFit : Image.PreserveAspectCrop
                asynchronous: true
                sourceSize.width: 1024
                sourceSize.height: 1024
                visible: status === Image.Ready
                opacity: root.fgArt   // fades with the foreground, onto artBox's bgAlt
            }
            PixelText {
                anchors.centerIn: parent
                visible: !root.cur.artPath
                text: "♫"
                font.pixelSize: 60
                color: Theme.dim
            }
            MouseArea {
                cursorShape: Qt.PointingHandCursor
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
                          trigger: function() { Player.playAlbum(aid, -1); } },
                        // The album grid's row, on the cover you are looking
                        // at: the whole album in track order, straight after
                        // the playing song. Greyed with an empty queue, where
                        // it would only be a second "play album" (AlbumGrid
                        // greys its twin for the same reason).
                        { label: "play album next", enabled: Player.queueLength > 0,
                          trigger: function() { Player.playAlbumNext(aid); } },
                        { label: "queue album",
                          trigger: function() { Player.queueAlbum(aid); } },
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

    // The one divider between the art and the content — under it when the art
    // is a top row, beside it when the art is a left column.
    Rectangle {
        id: hsep
        x: root.sideArt ? artRow.width : 0
        y: root.sideArt ? 0 : artRow.height
        width: root.sideArt ? 1 : root.width
        height: root.sideArt ? root.height : 1
        color: Theme.border
    }
    Item {   // drag handle over the row split (top-row layout only)
        anchors.left: parent.left
        anchors.right: parent.right
        y: hsep.y - 3
        height: 7
        z: 10
        visible: !root.sideArt
        enabled: !root.sideArt
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

    // ---- the content: under the art, or beside it ---------------------------
    Item {
        id: bottomRow
        x: root.sideArt ? hsep.x + hsep.width : 0
        y: root.sideArt ? 0 : hsep.y + hsep.height
        width: Math.max(0, root.width - x)
        height: Math.max(0, root.height - y)

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
            fgText: root.fgText
            fgDim: root.fgDim
            fgAccent: root.fgAccent
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
                        text: glyphs.px(root.cur.title || "") || "nothing playing"
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        color: root.cur.title ? root.fgText : root.fgDim
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
                            fgAccent: root.fgAccent
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
                                cursorShape: Qt.PointingHandCursor
                                anchors.fill: parent
                                onClicked: Library.setFavorite(root.cur.id, !root.cur.favorite)
                            }
                        }
                    }
                }
                PixelText {
                    width: parent.width
                    text: glyphs.px(root.cur.artist || "")
                    clip: true
                    height: Theme.lineHeight + 2  // descender room: one cell + 1px each side
                    color: root.fgDim
                }
                // Album, with its original release year trailing the name. The
                // name yields width to the year rather than the other way round,
                // so a long album title clips and the date stays readable.
                Row {
                    width: parent.width
                    height: Theme.lineHeight + 2
                    spacing: 6

                    PixelText {
                        text: glyphs.px(root.cur.album || "")
                        clip: true
                        width: Math.max(0, Math.min(implicitWidth,
                                        parent.width - (albumYear.visible
                                                        ? albumYear.width + parent.spacing : 0)))
                        height: Theme.lineHeight + 2  // descender room: one cell + 1px each side
                        color: root.fgDim
                    }
                    PixelText {
                        id: albumYear
                        visible: (root.cur.year || 0) > 0 && (root.cur.album || "") !== ""
                        // `text` is evaluated even while the row is invisible,
                        // and with nothing playing `cur.year` is undefined — a
                        // QML warning on every launch ("Unable to assign
                        // [undefined] to QString"), which is one more line of
                        // noise between a real one and whoever is reading.
                        text: root.cur.year ? String(root.cur.year) : ""
                        height: Theme.lineHeight + 2
                        color: Theme.dim
                    }
                }
                // Nothing else lives under the album line any more. Shuffle and
                // loop moved out to the titlebar (they were the last duplicated
                // controls left down here), and the position readout moved to
                // the titlebar footer, under the scrub track it belongs to — so
                // every transport control is now in exactly one place.
            }

            // The now-playing header is a track too (docs/DESIGN.md §7.1). The
            // cover above it carries the ALBUM's menu; this one carries the
            // playing track's, so "add to queue"/"go to album" are reachable
            // from the thing they are about. Right button ONLY, so the stars
            // and the heart underneath keep every left click, and no "play
            // now" — this row is what is already playing.
            MouseArea {
                anchors.fill: info
                acceptedButtons: Qt.RightButton
                enabled: root.cur.id !== undefined
                onPressed: function(m) {
                    var p = mapToItem(headerMenu, m.x, m.y);
                    headerMenu.openForTrack(p.x, p.y, {
                        trackId: root.cur.id,
                        artist: root.cur.artist || "",
                        albumId: root.cur.albumId || 0,
                        favorite: root.cur.favorite === true,
                        openAlbum: function(aid) { root.openAlbum(aid); },
                        browseArtist: function(a) { root.browseArtist(a); }
                    });
                }
            }

            // ---- queue, filling the rest of the left column ----
            PixelText {
                id: queueHead
                anchors.top: info.bottom
                anchors.topMargin: 10
                x: 8
                text: "queue  (" + Player.queueLength + ")"
                color: root.fgDim
            }
            TrackList {
                objectName: "queueList"   // handle for headless layout harnesses
                anchors.top: queueHead.bottom
                anchors.topMargin: 4
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                model: QueueModel
                fgText: root.fgText
                fgDim: root.fgDim
                fgAccent: root.fgAccent
                showNumber: false
                // A queue is usually one artist deep; let the list work out
                // whose name has stopped carrying information and drop it.
                autoHideArtist: true
                // the queue model IS the play order, so identify the playing row
                // by index (a queue can hold the same track twice) and scroll it
                // to the middle as playback advances.
                currentRow: Player.index
                followCurrent: true
                ratingsOnHover: true
                // These rows ARE the queue, so their menu can remove them.
                isQueue: true
                onPlayed: function(index) { Player.jumpTo(index); }
                onOpenAlbumRequested: function(aid) { root.openAlbum(aid); }
                onBrowseArtistRequested: function(a) { root.browseArtist(a); }
            }
        }
    }

    CtxMenu {
        id: coverMenu
        objectName: "coverMenu"   // handle for headless harnesses
        anchors.fill: parent
    }
    // The shared track menu, for the header block. (The queue below owns its
    // own instance, inside TrackList.)
    TrackMenu {
        id: headerMenu
        objectName: "headerMenu"
        anchors.fill: parent
    }
}
