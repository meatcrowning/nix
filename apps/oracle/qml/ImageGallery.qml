import QtQuick
import "../../qmlcommon"

// The pictures a reply carries, as ONE object rather than a stack.
//
// [his, 2026-08-23] — "when an agent wants to attach multiple images, can you
// make it so they first appear in a sort of gallery? and the user can click on
// one to enlarge it? i dont like how right now they are all one on top of the
// other." One image is still one image, full width; TWO OR MORE become a
// tiled grid, and a tile opens the Lightbox.
//
// The tiling is docs/DESIGN.md §5.1 read literally: tiles butt together at 0px,
// imagery bleeds to the frame with no letterboxing (a square crop, never a
// pillarbox), the frame is the gallery's own outline and nothing draws a second
// one inside it, and the caption moves INSIDE the artwork on hover instead of
// claiming a strip of its own. Rows are JUSTIFIED — a short last row divides
// the same width between however many tiles it has — so a remainder can never
// leave a dead half-row (§5.2).
//
// Gapless means positioning from the SHARED EDGE, `round(w*i/n)`, never
// `spacing: 0` on a Row: fractional widths round independently and leave
// subpixel seams (§5.1's implementation note).
Column {
    id: gal

    // The turn's `images` array, already parsed: {ok, url, path, alt, w, h}
    // for a fetched picture, {ok:false, url, error} for one that failed.
    property var entries: []
    // Asked to open the lightbox at `i` of `oks`.
    signal enlarge(int index)
    // RIGHT-CLICK ON A PICTURE, so it can leave the window [his, 2026-08-24].
    // The gallery does not own a menu — it says which picture was clicked and
    // where, and Root (which has the one `ctxMenu` and the Clip object) puts
    // the rows on it. Same shape as `enlarge`.
    signal contextRequested(string path, real x, real y)

    readonly property var oks: {
        var out = [];
        for (var i = 0; i < (entries ? entries.length : 0); i++)
            if (entries[i] && entries[i].ok) out.push(entries[i]);
        return out;
    }
    readonly property var bads: {
        var out = [];
        for (var i = 0; i < (entries ? entries.length : 0); i++)
            if (entries[i] && !entries[i].ok) out.push(entries[i]);
        return out;
    }

    spacing: 6

    // The picture's SOURCE, for the small caption under it: the host of the
    // url it was fetched from, lowercased — `danbooru.donmai.us`, never the
    // whole path (his-voice §3: a number/name, not a sentence).
    function hostOf(u) {
        var s = "" + (u || "");
        s = s.replace(/^[a-z]+:\/\//i, "").split("/")[0];
        return s;
    }

    // ---- one picture: unchanged — full width, framed, its caption under it --
    Column {
        width: gal.width
        spacing: 2
        visible: gal.oks.length === 1

        Rectangle {
            width: solo.width + 2
            height: solo.height + 2
            color: Theme.bgAlt
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border
            Image {
                id: solo
                x: 1; y: 1
                readonly property var e: gal.oks.length === 1 ? gal.oks[0] : null
                // sourceSize.width caps the decode to the column and, set
                // alone, scales height by the real aspect — never upscaling
                // past native.
                readonly property real natW: (e && e.w > 0) ? e.w : (gal.width - 2)
                sourceSize.width: Math.min(gal.width - 2, natW)
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                source: e ? "file://" + e.path : ""
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                onClicked: function (m) {
                    if (m.button === Qt.RightButton) {
                        var p = mapToItem(null, m.x, m.y);
                        gal.contextRequested(solo.e ? (solo.e.path || "") : "",
                                             p.x, p.y);
                    } else {
                        gal.enlarge(0);
                    }
                }
            }
        }
        // The caption (the model's alt text), subordinated (§9.1).
        PixelText {
            visible: gal.oks.length === 1 && !!gal.oks[0].alt
            width: gal.width
            wrapMode: Text.Wrap
            text: gal.oks.length === 1 ? (gal.oks[0].alt || "") : ""
            color: Theme.textDim
        }
        // One step dimmer: where the picture CAME FROM — the host for a
        // fetched one, and for a generated one what made it (the model, the
        // size, the sampling, the seed) [his, 2026-08-24]. It is the rest of
        // the answer to "what is this", and the seed is what makes the same
        // picture again.
        PixelText {
            visible: gal.oks.length === 1
                     && (!!gal.oks[0].meta || !!gal.oks[0].url)
            width: gal.width
            wrapMode: Text.Wrap
            text: gal.oks.length !== 1 ? ""
                  : (gal.oks[0].meta || hostOf(gal.oks[0].url))
            color: Theme.textDim
            opacity: 0.6
        }
        // A file that saved but will not decode (§10 — say so, never a blank).
        PixelText {
            visible: solo.status === Image.Error
            width: gal.width
            wrapMode: Text.Wrap
            text: "image: could not display"
            color: Theme.crit
        }
    }

    // ---- two or more: the grid ---------------------------------------------
    Rectangle {
        id: frame
        width: gal.width
        height: grid.height + 2
        visible: gal.oks.length > 1
        color: Theme.bgAlt
        radius: Theme.rounding
        border.width: Theme.ctrlBorder
        border.color: Theme.border
        clip: true

        Item {
            id: grid
            x: 1; y: 1
            width: frame.width - 2
            readonly property int n: gal.oks.length
            // A tile aims at ~120px and the count is clamped to 2..4: below two
            // there is no grid, and past four a tile is smaller than the pixel
            // font's own line box, which is where a thumbnail stops being one.
            readonly property int maxCols:
                Math.max(2, Math.min(4, Math.floor(width / 120)))
            // Then the rows are BALANCED — take the fewest rows that fit at
            // maxCols and divide the pictures evenly between them. Five at four
            // across would put one lone tile on a row of its own, and a
            // justified row of one is a 4x-wide crop of a square picture; five
            // at three across is 3 + 2. Balance first, density second.
            readonly property int rows: Math.max(1, Math.ceil(n / maxCols))
            readonly property int cols: Math.max(1, Math.ceil(n / rows))
            readonly property int cellH: Math.round(width / cols)
            height: rows * cellH

            Repeater {
                model: grid.n
                delegate: Item {
                    id: tile
                    readonly property var e: gal.oks[index]
                    readonly property int row: Math.floor(index / grid.cols)
                    // The JUSTIFIED row: the last one divides the width between
                    // however many tiles it actually has, so no dead space.
                    readonly property int inRow:
                        Math.min(grid.cols, grid.n - row * grid.cols)
                    readonly property int col: index - row * grid.cols
                    // Shared edges: this tile's right edge IS the next one's
                    // left edge, so nothing rounds into a seam.
                    x: Math.round(grid.width * col / inRow)
                    width: Math.round(grid.width * (col + 1) / inRow) - x
                    y: row * grid.cellH
                    height: grid.cellH
                    clip: true

                    Image {
                        id: thumb
                        anchors.fill: parent
                        // Crop, never pillarbox (§5.1) — the tile's shape is
                        // the grid's, and the picture bleeds to it.
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                        sourceSize.width: Math.max(1, tile.width)
                        sourceSize.height: Math.max(1, tile.height)
                        source: tile.e ? "file://" + tile.e.path : ""
                    }
                    // The one that will not decode says so in its own cell,
                    // rather than leaving a hole (§10).
                    PixelText {
                        anchors.centerIn: parent
                        visible: thumb.status === Image.Error
                        text: "?"
                        color: Theme.crit
                    }
                    MouseArea {
                        id: hover
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        onClicked: function (m) {
                            if (m.button === Qt.RightButton) {
                                var p = mapToItem(null, m.x, m.y);
                                gal.contextRequested(
                                    tile.e ? (tile.e.path || "") : "", p.x, p.y);
                            } else {
                                gal.enlarge(index);
                            }
                        }
                    }
                    // Hover: the accent wash the drop overlay already uses
                    // (§3 — an alpha of an existing token, no new colour)...
                    Rectangle {
                        anchors.fill: parent
                        visible: hover.containsMouse
                        color: Qt.rgba(Theme.accent.r, Theme.accent.g,
                                       Theme.accent.b, 0.14)
                    }
                    // ...and the caption INSIDE the artwork, not a strip of its
                    // own (§5.1) — and ALWAYS DRAWN, not only on hover [his,
                    // 2026-08-22]: a caption you have to go looking for with the
                    // pointer is not a caption, and a solo picture has had its
                    // own under it all along. The wash goes one step more opaque
                    // as the pointer arrives, so the text stays readable over a
                    // busy crop without hiding the picture the rest of the time.
                    // The source host joins the alt line beneath it [his,
                    // 2026-08-23] — the strip names where the tile came from.
                    Rectangle {
                        anchors { left: parent.left; right: parent.right
                                  bottom: parent.bottom }
                        height: tileCap.height + 4
                        visible: !!tile.e && (!!tile.e.alt || !!tile.e.url
                                              || !!tile.e.meta)
                        color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b,
                                       hover.containsMouse ? 0.92 : 0.72)
                        Column {
                            id: tileCap
                            anchors { left: parent.left; right: parent.right
                                      verticalCenter: parent.verticalCenter
                                      leftMargin: 3; rightMargin: 3 }
                            spacing: 0
                            PixelText {
                                width: tileCap.width
                                visible: !!tile.e && !!tile.e.alt
                                text: (tile.e && tile.e.alt) ? tile.e.alt : ""
                                elide: Text.ElideRight
                                color: Theme.text
                            }
                            PixelText {
                                width: tileCap.width
                                visible: !!tile.e && (!!tile.e.url || !!tile.e.meta)
                                text: !tile.e ? ""
                                      : (tile.e.meta || gal.hostOf(tile.e.url))
                                elide: Text.ElideRight
                                color: Theme.text
                                opacity: 0.6
                            }
                        }
                    }
                }
            }
        }
    }

    // ---- the failures, whatever the count ----------------------------------
    Repeater {
        model: gal.bads
        delegate: PixelText {
            width: gal.width
            wrapMode: Text.Wrap
            text: "image: " + (modelData.error ? modelData.error
                                               : "could not display")
                  + (modelData.url ? " (" + modelData.url + ")" : "")
            color: Theme.crit
        }
    }
}
