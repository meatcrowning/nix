import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window
import "../../qmlcommon"

// A reusable track table (album detail, playlists, search, queue): one packed
// pixel-text row per track — number, title, optional artist, rating stars,
// favourite heart, duration. Rows grey to Theme.inactive when the file is
// missing (library drive unplugged). Double-click plays from that row.
Item {
    id: root

    // display-site px() for foreign text (docs/DESIGN.md 2.3)
    Glyphs { id: glyphs }
    property alias model: list.model
    // The three foreground tones, handed in ALREADY FADED by the owning pane
    // (docs/DESIGN.md §3.1.1) — a row must not know whether the window is
    // focused. This is the app's hottest delegate, so the ternary lives ONCE at
    // the window and a row just reads the resulting colour — exactly where it
    // used to read `Theme.text`. Delegate construction cost and binding count
    // are therefore unchanged; a per-row `winActive ? … : …` would have added
    // one live conditional per row per column. Defaults are the lit tones, for
    // a harness that builds a TrackList on its own.
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent
    property bool showArtist: true
    // Artist name to LEAVE OFF every row, set explicitly. Normally you want
    // autoHideArtist instead.
    property string hideArtist: ""
    // Work the redundant name out from the LIST rather than being told it (the
    // queue): in a listing that is mostly one artist, repeating their name on
    // every row says nothing — the rows that differ are the ones worth naming.
    //
    // This used to be the now-playing track's artist, passed in verbatim, and
    // it never once fired: that string is the FULL credit ("J Dilla feat. MED
    // & Guilty Simpson"), so it matched no row — not even its own siblings on
    // the same album — and all 24 rows of The Shining rendered "title - J
    // Dilla" clipped mid-name to "J Dill" / "J Di" / "J". Match on the BASE
    // artist (the credit with its feature tail stripped) and the tail is what
    // survives on the row, which is the only part that differs anyway.
    property bool autoHideArtist: false

    // Credit with any "feat. X" / "ft X" / "featuring X" / "with X" tail cut off.
    function baseArtist(a) {
        if (!a) return "";
        var m = String(a).match(/^(.*?)\s+(?:feat\.?|ft\.?|featuring|w\/|with)\s+/i);
        return (m ? m[1] : String(a)).trim();
    }

    // The one name worth suppressing, or "" if the list has no clear majority.
    // Driven by a function and an explicit modelReset hook, NOT by a binding on
    // list.count: the models here are replaced wholesale (DictListModel.set_rows
    // → beginResetModel), and swapping one 12-track album queue for another
    // leaves count untouched, so a count-dependent binding would keep the
    // previous album's artist suppressed.
    property string autoHidden: ""
    function recomputeAutoHidden() {
        if (!autoHideArtist || !list.model || list.count < 3 || !list.model.get) {
            autoHidden = "";
            return;
        }
        var tally = ({}), best = "", bestN = 0;
        for (var i = 0; i < list.count; i++) {
            var r = list.model.get(i);
            if (!r) { autoHidden = ""; return; }
            var b = root.baseArtist(r.artist);
            if (b === "") continue;
            tally[b] = (tally[b] || 0) + 1;
            if (tally[b] > bestN) { bestN = tally[b]; best = b; }
        }
        // A bare majority isn't enough — half a list of names is still worth
        // reading. Two thirds means the column has stopped saying anything.
        autoHidden = bestN >= list.count * 0.66 ? best : "";
    }
    onAutoHideArtistChanged: recomputeAutoHidden()
    Connections {
        target: list.model
        ignoreUnknownSignals: true
        function onModelReset() { root.recomputeAutoHidden(); }
    }
    readonly property string effectiveHide: hideArtist !== "" ? hideArtist : autoHidden

    // What a row prints for `artist`: nothing when it IS the hidden name, just
    // the feature tail when it's that name plus guests, the full credit
    // otherwise.
    function artistLabel(a) {
        if (!showArtist || !a) return "";
        var hide = root.effectiveHide;
        if (hide === "") return String(a);
        if (String(a).toLowerCase() === hide.toLowerCase()) return "";
        var b = root.baseArtist(a);
        if (b.toLowerCase() !== hide.toLowerCase()) return String(a);
        return String(a).substring(b.length).trim();
    }

    // True when the label is only the guest tail of the suppressed name, i.e.
    // supplementary. A label that is a whole, DIFFERENT credit is not: on a
    // mixed listing that name is the point of the column and must survive even
    // clipped, whereas "feat. Dwele" is worth dropping before it gets cut.
    function artistIsTail(a) {
        if (root.effectiveHide === "" || !a) return false;
        return root.baseArtist(a).toLowerCase() === root.effectiveHide.toLowerCase();
    }
    property bool showNumber: true
    // false where the owner sizes itself to hold every row (the gallery's
    // inline album section): no scrollbar, and wheel notches pass through to
    // whatever is behind, so the page underneath scrolls instead.
    property bool scrollable: true
    property int currentTrackId: Player.current.id !== undefined ? Player.current.id : -1
    // Row-index identity of the now-playing track, for owners whose model IS the
    // play order (the queue). -1 = fall back to matching by track id, which is
    // all an album/search listing can do — but wrong for a queue holding the
    // same track twice.
    property int currentRow: -1
    // Keep the now-playing row parked in the middle of the view as playback
    // walks down the list.
    property bool followCurrent: false
    // Hide each row's stars + heart until the cursor is over that row (the
    // queue): 146 rows of always-on rating glyphs read as noise next to the
    // one persistent setter on the now-playing title. A hidden row releases
    // their width to the title, which is the whole point — a long "title -
    // artist" would otherwise clip against blank space.
    property bool ratingsOnHover: false
    signal played(int index)

    // ---- right-click (docs/DESIGN.md §7.1) ----
    // Every listing gets the SAME menu (TrackMenu.qml); what differs is the two
    // facts only the owner knows — which album this listing already is, and
    // whether its rows are queue rows. Navigation is relayed rather than acted
    // on here: a table has no business knowing how the window switches views.
    property int inAlbum: 0          // this listing IS this album -> no "go to album"
    property bool isQueue: false     // rows are queue rows -> "remove from queue"
    signal openAlbumRequested(int albumId)
    signal browseArtistRequested(string artist)

    // Parented to the WINDOW, not to this list. The queue column is ~240px
    // wide and every listing here clips, so a menu living inside one would be
    // measured and clamped against a sliver of the window — or simply cut off
    // at the list's edge. CtxMenu clamps against its own bounds, so those
    // bounds have to be the window's.
    TrackMenu {
        id: trackMenu
        objectName: "trackMenu"
        parent: root.Window.contentItem ? root.Window.contentItem : root
        anchors.fill: parent
    }

    function centerCurrent() {
        if (!followCurrent || currentRow < 0 || currentRow >= list.count || list.height <= 0)
            return;
        list.positionViewAtIndex(currentRow, ListView.Center);
    }
    onCurrentRowChanged: centerCurrent()
    Component.onCompleted: { centerCurrent(); recomputeAutoHidden(); }

    KineticListView {
        id: list
        anchors.fill: parent
        clip: true
        // A non-scrollable table (AlbumPanel sizes itself to hold every row)
        // hands the wheel straight out to whatever is behind it — the album
        // gallery keeps scrolling under an open album section.
        wheelEnabled: root.scrollable
        ScrollBar.vertical: VScroll { id: vscroll; visible: root.scrollable }

        // Re-centre once the view actually has a size / rows (the queue's height
        // and model both arrive after this component is built, and a
        // positionViewAtIndex against a 0-height or empty view does nothing).
        onHeightChanged: root.centerCurrent()
        onCountChanged: { root.centerCurrent(); root.recomputeAutoHidden(); }
        onModelChanged: root.recomputeAutoHidden()

        delegate: Rectangle {
            id: row
            width: list.width
            height: Theme.lineHeight + 2   // descender room: one cell + 1px each side
            readonly property bool isCurrent: root.currentRow >= 0
                                              ? index === root.currentRow
                                              : trackId === root.currentTrackId
            color: isCurrent || rowHover.hovered ? Theme.highlight : "transparent"
            readonly property bool showRatings: !root.ratingsOnHover || rowHover.hovered

            // Hover state comes from a HoverHandler, not from rowMouse: that
            // MouseArea deliberately stops 130px short of the right edge to
            // leave the stars/heart clickable, so its containsMouse goes FALSE
            // exactly where the hover-revealed rating glyphs live. A handler
            // covers the whole row and steals no clicks from them.
            HoverHandler { id: rowHover }

            // Accent gutter, so the playing row still reads as the playing row
            // when the cursor is hovering some other one.
            Rectangle {
                width: 2
                height: parent.height
                color: root.fgAccent
                visible: row.isCurrent
            }
            // A missing file is ALREADY the inactive grey, so an unfocused
            // window simply makes every row agree with it.
            // The highlight fill is saturated, so its readable ink is the
            // panel's light card foreground, not the dark playing-state accent.
            // Carry it through every selected-row label and control.
            readonly property color selectedFg: root.fgText
            readonly property color fg: !available ? Theme.inactive
                                        : (isCurrent ? selectedFg : root.fgText)

            // Text at integer y=1 in the cell-height row — packed like kitty
            // lines, so per-title ascender ink can't read as uneven gaps.
            PixelText {
                id: numText
                visible: root.showNumber
                x: 8
                width: 30
                y: 1
                text: track > 0 ? ((disc > 1 ? disc + "-" : "") + track) : ""
                color: row.isCurrent ? row.selectedFg : root.fgDim
            }
            // Title and artist are two texts, not one concatenated string, so
            // the TITLE gets first claim on the width and only the artist is
            // allowed to run off the end. Concatenated, a narrow column (the
            // queue is ~240px on air) clipped both as one run and the cut
            // landed mid-artist with nothing to say it had been cut — "Body
            // Movin' - J Dilla" read as "Body Movin' - J Dill". Dimming the
            // artist is what marks the tail as secondary; there is no ellipsis
            // to mark it with, since More Perfect DOS VGA has no U+2026 and
            // the fallback that supplies it drops the whole line 5px out of
            // the row rect.
            Item {
                id: nameCell
                anchors.left: root.showNumber ? numText.right : parent.left
                anchors.leftMargin: root.showNumber ? 4 : 8
                anchors.right: rightBits.left
                anchors.rightMargin: 8
                y: 1
                height: Theme.lineHeight + 2  // descender room: one cell + 1px each side
                clip: true

                readonly property string artistText: root.artistLabel(artist)
                readonly property bool artistOptional: root.artistIsTail(artist)

                PixelText {
                    id: titleText
                    // The title is the primary datum and never yields width to
                    // the artist — it clips only against the cell itself.
                    width: Math.max(0, Math.min(implicitWidth, nameCell.width))
                    height: parent.height
                    clip: true
                    text: glyphs.px(title)
                    color: row.fg
                }
                PixelText {
                    id: artistText
                    // A guest tail is all-or-nothing: half of one ("feat.
                    // Dwel") is worse than none, because it reads as part of
                    // the title and there is no ellipsis available to disown
                    // it — the playing track's full credit is on the header
                    // above anyway. A whole different credit still clips
                    // rather than vanish. Compared against IMPLICIT widths
                    // only; reading titleText.width here is a binding loop.
                    readonly property real room:
                        nameCell.width - Math.min(titleText.implicitWidth, nameCell.width) - 6
                    readonly property bool fits: room >= implicitWidth
                    // ...and even a clippable credit needs somewhere to start:
                    // "Starpoint" cut down to "S" is a stray letter hanging off
                    // the title, not a column.
                    readonly property bool worthDrawing:
                        room >= 4 * (implicitWidth / Math.max(1, text.length))
                    visible: nameCell.artistText !== ""
                             && worthDrawing
                             && (!nameCell.artistOptional || fits)
                    anchors.left: titleText.right
                    anchors.leftMargin: 6
                    anchors.right: parent.right
                    clip: true
                    height: parent.height
                    text: glyphs.px(nameCell.artistText)
                    color: !available ? Theme.inactive
                           : (row.isCurrent ? row.selectedFg : root.fgDim)
                }
            }
            Row {
                id: rightBits
                anchors.right: parent.right
                // Clear the scrollbar, which is always on and up to 16px wide
                // now (docs/DESIGN.md 9.2) — the old flat 8 put the duration
                // under it. The delegate is the view's full width on purpose
                // (the row highlight runs edge to edge), so the gutter is the
                // trailing column's margin rather than the list's.
                anchors.rightMargin: root.scrollable ? vscroll.barW + 4 : 8
                y: 1
                height: 15
                spacing: 8

                // The rating glyphs give their SPACE back when hidden (visible,
                // not opacity — a Row skips an invisible child's width AND its
                // spacing), so an unhovered row spends that width on its title
                // instead of clipping a name in front of empty pixels.
                Row {
                    height: 15
                    spacing: 8
                    visible: row.showRatings

                    Stars {
                        anchors.verticalCenter: parent.verticalCenter
                        rating: model.rating !== undefined ? model.rating : -1
                        fgAccent: row.isCurrent ? row.selectedFg : root.fgAccent
                        fgDim: row.isCurrent ? row.selectedFg : Theme.dim
                        onRated: function(fmps) { Library.setRating(trackId, fmps); }
                    }
                    Item {
                        width: 12
                        height: 15
                        anchors.verticalCenter: parent.verticalCenter
                        PixelText {
                            anchors.centerIn: parent
                            text: "♥"
                            color: row.isCurrent ? row.selectedFg
                                  : (favorite ? Theme.crit : Theme.dim)
                        }
                        MouseArea {
                            cursorShape: Qt.PointingHandCursor
                            anchors.fill: parent
                            onClicked: Library.setFavorite(trackId, !favorite)
                        }
                    }
                }
                // Play count sits immediately left of the duration — both are
                // numbers about the track itself, so they read as one column
                // pair rather than splitting the title from its time.
                PixelText {
                    visible: playCount > 0
                    anchors.verticalCenter: parent.verticalCenter
                    text: playCount + "x"
                    color: row.isCurrent ? row.selectedFg : Theme.dim
                }
                PixelText {
                    anchors.verticalCenter: parent.verticalCenter
                    text: {
                        var s = Math.max(0, Math.round(duration));
                        return Math.floor(s / 60) + ":" + (s % 60 < 10 ? "0" : "") + (s % 60);
                    }
                    color: row.isCurrent ? row.selectedFg : root.fgDim
                }
            }
            MouseArea {
                cursorShape: Qt.PointingHandCursor
                id: rowMouse
                anchors.fill: parent
                // Stop short of the right-hand column so its stars/heart stay
                // clickable (this MouseArea is declared last, so it would sit
                // on top of them). Measured, not a magic 130: the column's
                // width now varies with the hover-revealed glyphs.
                anchors.rightMargin: rightBits.width + 8
                hoverEnabled: true
                onDoubleClicked: root.played(index)
            }
            // Right-click opens the shared track menu. Declared LAST so it is
            // on top of the whole row — including the right-hand column that
            // rowMouse deliberately stops short of — and accepting ONLY the
            // right button, so every left click still falls through to the
            // stars, the heart and rowMouse underneath it.
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.RightButton
                onPressed: function (m) {
                    var p = mapToItem(trackMenu, m.x, m.y);
                    trackMenu.openForTrack(p.x, p.y, {
                        trackId: trackId,
                        artist: artist,
                        albumId: albumId,
                        available: available,
                        favorite: favorite,
                        playNow: function () { root.played(index); },
                        queueIndex: root.isQueue ? index : -1,
                        inAlbum: root.inAlbum,
                        openAlbum: function (aid) { root.openAlbumRequested(aid); },
                        browseArtist: function (a) { root.browseArtistRequested(a); }
                    });
                }
            }
        }
    }

}
