import QtQuick
import QtQuick.Controls as QQC

// The pictures a reply carries, as ONE object, in an Oxygen session.
//
// Same API as `../ImageGallery.qml` — `entries`, `maxH`, `enlarge(int)`,
// `contextRequested(path,x,y)` — and the same layout arithmetic: one picture is
// one picture, two or more tile into a JUSTIFIED grid whose tiles butt together
// at 0px and are positioned from the shared edge (`round(w*i/n)`), so no
// fractional rounding leaves a seam.
//
// What changes is the hand that draws it. The sibling's hairline `Rectangle`
// with our radius becomes the style's own `Frame` — the same well an Oxygen
// view sits in — and every line of text is a `Label` in the system font. The
// hover wash on a tile is the style's own highlight brush rather than the wal
// accent, so a tile lights the way a selected row lights everywhere else in the
// session.
Column {
    id: gal

    property string face: "oxygen"

    property var entries: []
    signal enlarge(int index)
    signal contextRequested(string path, real x, real y)

    property int maxH: 320

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

    // The style's own brushes, read off a real control rather than guessed.
    QQC.Label { id: pal; visible: false }
    readonly property color highlight: pal.palette.highlight

    function hostOf(u) {
        var s = "" + (u || "");
        s = s.replace(/^[a-z]+:\/\//i, "").split("/")[0];
        return s;
    }

    // ---- one picture --------------------------------------------------------
    Column {
        width: gal.width
        spacing: 2
        visible: gal.oks.length === 1

        QQC.Frame {
            id: soloFrame
            anchors.horizontalCenter: parent.horizontalCenter
            readonly property real inset: leftPadding + rightPadding
            readonly property real vinset: topPadding + bottomPadding
            width: solo.width + inset
            height: solo.height + vinset

            contentItem: Item {
                Image {
                    id: solo
                    readonly property var e: gal.oks.length === 1 ? gal.oks[0] : null
                    readonly property real natW:
                        (e && e.w > 0) ? e.w : (gal.width - soloFrame.inset)
                    readonly property real natH:
                        (e && e.h > 0) ? e.h : (gal.width - soloFrame.inset)
                    // Capped by the column AND by the height ceiling, never
                    // upscaled past native.
                    sourceSize.width: Math.max(1, Math.round(
                        Math.min(gal.width - soloFrame.inset, natW,
                                 gal.maxH * natW / Math.max(1, natH))))
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    source: e ? "file://" + e.path : ""
                }
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

        CaptionStrip {
            width: gal.width
            caption: (gal.oks.length === 1 && gal.oks[0].alt) ? gal.oks[0].alt : ""
            meta: gal.oks.length !== 1 ? ""
                  : (gal.oks[0].meta || gal.hostOf(gal.oks[0].url))
        }
        QQC.Label {
            visible: solo.status === Image.Error
            width: gal.width
            wrapMode: Text.Wrap
            text: "image: could not display"
            color: Theme.crit
        }
    }

    // ---- two or more: the grid ---------------------------------------------
    QQC.Frame {
        id: frame
        readonly property real inset: leftPadding + rightPadding
        readonly property real vinset: topPadding + bottomPadding
        width: gal.width
        height: grid.height + vinset
        visible: gal.oks.length > 1
        clip: true

        contentItem: Item {
            id: grid
            readonly property int n: gal.oks.length
            readonly property int maxCols:
                Math.max(2, Math.min(4, Math.floor(width / 120)))
            // Balanced rows first, density second: five at four across leaves a
            // lone tile stretched 4x wide; five at three across is 3 + 2.
            readonly property int rows: Math.max(1, Math.ceil(n / maxCols))
            readonly property int cols: Math.max(1, Math.ceil(n / rows))
            readonly property int cellH: Math.round(width / cols)
            implicitHeight: rows * cellH
            height: rows * cellH

            Repeater {
                model: grid.n
                delegate: Item {
                    id: tile
                    readonly property var e: gal.oks[index]
                    readonly property int row: Math.floor(index / grid.cols)
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
                        // Crop, never pillarbox — the tile's shape is the
                        // grid's, and the picture bleeds to it.
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                        sourceSize.width: Math.max(1, tile.width)
                        sourceSize.height: Math.max(1, tile.height)
                        source: tile.e ? "file://" + tile.e.path : ""
                    }
                    QQC.Label {
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
                    // The style's own highlight, at the weight Oxygen washes a
                    // hovered view row with — and faded at Oxygen's own generic
                    // animation duration rather than appearing instantly.
                    Rectangle {
                        anchors.fill: parent
                        color: Qt.rgba(gal.highlight.r, gal.highlight.g,
                                       gal.highlight.b, 0.28)
                        opacity: hover.containsMouse ? 1 : 0
                        Behavior on opacity {
                            NumberAnimation {
                                duration: DeskStyle.styleMs > 0
                                          ? DeskStyle.styleMs : 150
                                easing.type: Easing.InOutQuad
                            }
                        }
                    }
                    // The caption INSIDE the artwork — a grid of cropped
                    // thumbnails has no room under each cell — and always
                    // drawn, not only on hover.
                    CaptionStrip {
                        anchors { left: parent.left; right: parent.right
                                  bottom: parent.bottom }
                        over: true
                        caption: (tile.e && tile.e.alt) ? tile.e.alt : ""
                        meta: !tile.e ? ""
                              : (tile.e.meta || gal.hostOf(tile.e.url))
                        wash: hover.containsMouse ? 0.92 : 0.72
                    }
                }
            }
        }
    }

    // ---- the failures, whatever the count ----------------------------------
    Repeater {
        model: gal.bads
        delegate: QQC.Label {
            width: gal.width
            wrapMode: Text.Wrap
            text: "image: " + (modelData.error ? modelData.error
                                               : "could not display")
                  + (modelData.url ? " (" + modelData.url + ")" : "")
            color: Theme.crit
        }
    }
}
