import QtQuick
import QtQuick.Controls.Basic

// A reusable track table (album detail, playlists, search, queue): one packed
// pixel-text row per track — number, title, optional artist, rating stars,
// favourite heart, duration. Rows grey to Theme.inactive when the file is
// missing (library drive unplugged). Double-click plays from that row.
Item {
    id: root
    property alias model: list.model
    property bool showArtist: true
    // Artist name to LEAVE OFF a row (the queue passes the now-playing track's
    // artist): in a queue that is mostly one artist, repeating their name on
    // every row says nothing — the rows that differ are the ones worth naming.
    property string hideArtist: ""
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

    function centerCurrent() {
        if (!followCurrent || currentRow < 0 || currentRow >= list.count || list.height <= 0)
            return;
        list.positionViewAtIndex(currentRow, ListView.Center);
    }
    onCurrentRowChanged: centerCurrent()
    Component.onCompleted: centerCurrent()

    ListView {
        id: list
        anchors.fill: parent
        clip: true
        interactive: false     // scrollbar + wheel only — no drag-flicking
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: VScroll { visible: root.scrollable }

        // Re-centre once the view actually has a size / rows (the queue's height
        // and model both arrive after this component is built, and a
        // positionViewAtIndex against a 0-height or empty view does nothing).
        onHeightChanged: root.centerCurrent()
        onCountChanged: root.centerCurrent()

        delegate: Rectangle {
            id: row
            width: list.width
            height: Theme.fontSize + 2   // kitty-tight: one font cell + 1px each side
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
                color: Theme.accent
                visible: row.isCurrent
            }
            readonly property color fg: !available ? Theme.inactive
                                        : (isCurrent ? Theme.accent : Theme.text)

            // Text at integer y=1 in the cell-height row — packed like kitty
            // lines, so per-title ascender ink can't read as uneven gaps.
            PixelText {
                id: numText
                visible: root.showNumber
                x: 8
                width: 30
                y: 1
                text: track > 0 ? ((disc > 1 ? disc + "-" : "") + track) : ""
                color: Theme.textDim
            }
            PixelText {
                anchors.left: root.showNumber ? numText.right : parent.left
                anchors.leftMargin: root.showNumber ? 4 : 8
                anchors.right: rightBits.left
                anchors.rightMargin: 8
                y: 1
                // ASCII hyphen, NOT an em dash: More Perfect DOS VGA has no
                // U+2014, and the fallback font that supplies it carries a
                // taller ascent that drops the whole line 5px (ink at row
                // offsets 8-16 instead of 3-11) — out the bottom of the row
                // rect, which is what made the current-row highlight and the
                // hover band look offset from their own text.
                text: title + (root.showArtist && artist && artist !== root.hideArtist
                               ? "  -  " + artist : "")
                clip: true
                height: Theme.fontSize + 2  // descender room: 16px ink in the 15px line
                color: row.fg
            }
            Row {
                id: rightBits
                anchors.right: parent.right
                anchors.rightMargin: 8
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
                        onRated: function(fmps) { Library.setRating(trackId, fmps); }
                    }
                    Item {
                        width: 12
                        height: 15
                        anchors.verticalCenter: parent.verticalCenter
                        PixelText {
                            anchors.centerIn: parent
                            text: "♥"
                            color: favorite ? Theme.crit : Theme.dim
                        }
                        MouseArea {
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
                    color: Theme.dim
                }
                PixelText {
                    anchors.verticalCenter: parent.verticalCenter
                    text: {
                        var s = Math.max(0, Math.round(duration));
                        return Math.floor(s / 60) + ":" + (s % 60 < 10 ? "0" : "") + (s % 60);
                    }
                    color: Theme.textDim
                }
            }
            MouseArea {
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
        }
    }

    WheelScroll {
        view: root.scrollable ? list : null
    }
}
