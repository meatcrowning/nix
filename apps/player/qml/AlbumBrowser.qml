import QtQuick
import QtQuick.Controls
import QtQuick.Window
import "../../qmlcommon"

// The album browser that sits beside the queue on the all-in-one now-playing
// page: search, covers, and one album's tracks — the gallery's job in a
// column, not a second copy of the gallery.
//
// IT READS ITS OWN ROWS. `BrowseAlbumsModel` / `BrowseTracksModel` and
// `Library.setBrowseFilter` / `openBrowseAlbum` are a second, independent
// reader of the same library (main.py's Bridge). Binding this to the gallery's
// `AlbumsModel` instead would mean typing here re-filters the albums page, and
// an album opened here would yank the rows out from under the gallery's own
// open section — one track model cannot serve two visible panels.
//
// The gallery's own idioms are kept where they carry over: covers tile flush
// with no gap, the metadata appears on hover inside the cover's lower edge,
// middle-click queues, and the track rows are the shared TrackList (so the
// row menu, ratings and hearts are the same ones everywhere).
Item {
    id: root

    // display-site px() for foreign text (docs/DESIGN.md §2.3)
    Glyphs { id: glyphs }

    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent
    property real fgArt: 1.0
    readonly property bool plasma: (typeof DeskStyle !== "undefined" && DeskStyle)
                                   ? DeskStyle.plasma === true : false

    // Relayed to the window, which owns navigation and the identity sheet.
    signal openAlbumRequested(int albumId)
    signal browseArtistRequested(string artist)
    signal editAliasesRequested(string artist)

    // The album open INSIDE this pane (0 = the cover grid).
    property int openId: 0
    property var openInfo: ({})

    // Covers as wide as the gallery's, not as many: this column is a third of
    // the window, so a fixed column count would give it either postage stamps
    // or one cover per row depending on the window.
    readonly property int idealCell: 110
    readonly property int gridW: Math.max(1, width - (vbar ? vbar.barW : 16))
    readonly property int cols: Math.max(1, Math.round(gridW / idealCell))
    readonly property int cellW: Math.max(1, Math.floor(gridW / cols))

    // Ctrl-click picks covers one at a time, Shift-click takes the run from the
    // last one clicked — the gallery's gesture, in the gallery's words
    // (AlbumGrid.qml owns the reasoning). Selecting stays an EXPLICIT mode: a
    // plain click still just opens a record and drops whatever was picked.
    property var selectedIds: []
    property int _anchorId: 0

    function isSelected(albumId) { return selectedIds.indexOf(albumId) >= 0; }
    function clearSelection() { if (selectedIds.length) selectedIds = []; }
    function indexOfAlbum(albumId) {
        for (var i = 0; i < BrowseAlbumsModel.count; ++i)
            if (BrowseAlbumsModel.get(i).albumId === albumId)
                return i;
        return -1;
    }
    function selectToggle(albumId) {
        var s = selectedIds.slice(), i = s.indexOf(albumId);
        if (i >= 0) s.splice(i, 1); else s.push(albumId);
        selectedIds = s;
        _anchorId = albumId;
    }
    // The anchor stays put, so a second Shift-click re-aims the same run
    // instead of growing it one cover at a time.
    function selectRange(albumId) {
        var from = indexOfAlbum(_anchorId), to = indexOfAlbum(albumId);
        if (from < 0 || to < 0) { selectToggle(albumId); return; }
        var lo = Math.min(from, to), hi = Math.max(from, to), s = [];
        for (var i = lo; i <= hi; ++i) {
            var a = albumAt(i);
            if (a) s.push(a.albumId);
        }
        selectedIds = s;
    }

    function albumAt(i) {
        return (i >= 0 && i < BrowseAlbumsModel.count) ? BrowseAlbumsModel.get(i) : null;
    }
    function openAlbum(albumId) {
        openId = albumId;
        Library.openBrowseAlbum(albumId);
        openInfo = albumId > 0 ? Library.albumInfo(albumId) : ({});
    }
    function applyFilter(text) {
        Library.setBrowseFilter(text);
        // A pick is a set of rows in the listing that was on screen.
        clearSelection();
        // A new query is a new listing: the album that was open is not
        // necessarily in it any more.
        if (openId > 0)
            openAlbum(0);
    }

    // The rows arrive only once something asks for them (the Bridge does not
    // map every album a second time until this pane exists).
    Component.onCompleted: Library.setBrowseFilter(search.text)
    Connections {
        target: Library
        function onScanStatus() {
            if (root.openId > 0)
                root.openInfo = Library.albumInfo(root.openId);
        }
    }

    // ---- header: search, or the open album's identity ----------------------
    Item {
        id: head
        anchors { left: parent.left; right: parent.right; top: parent.top }
        anchors.margins: 6
        height: Math.max(search.implicitHeight, Theme.lineHeight + 9)

        EditField {
            id: search
            objectName: "browseSearch"
            visible: root.openId <= 0
            anchors { left: parent.left; right: count.left; rightMargin: 8
                      verticalCenter: parent.verticalCenter }
            placeholderText: "search albums..."
            fgText: root.fgText; fgAccent: root.fgAccent
            onTextEdited: root.applyFilter(text)
            onAccepted: root.applyFilter(text)
            onEscaped: { text = ""; root.applyFilter(""); }
        }
        PixelText {
            id: count
            visible: root.openId <= 0
            anchors { right: parent.right; verticalCenter: parent.verticalCenter }
            color: root.fgDim
            text: BrowseAlbumsModel.count + (BrowseAlbumsModel.count === 1 ? " album" : " albums")
        }

        Row {
            visible: root.openId > 0
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
            spacing: 8
            HeaderButton {
                label: "< back"; plainLabel: "back"; iconName: "go-previous"
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                onClicked: root.openAlbum(0)
            }
            HeaderButton {
                label: "> play"; plainLabel: "play"; iconName: "media-playback-start"
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                onClicked: Player.playAlbum(root.openId, -1)
            }
            HeaderButton {
                label: "+ queue"; plainLabel: "queue"; iconName: "list-add"
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                onClicked: Player.queueAlbum(root.openId)
            }
        }
    }

    // ---- the open album: its cover, identity and tracks --------------------
    Item {
        id: albumView
        visible: root.openId > 0
        anchors { left: parent.left; right: parent.right; top: head.bottom
                  bottom: parent.bottom; margins: 6; topMargin: 4 }

        Rectangle {
            id: openArt
            objectName: "openArt"
            // As tall as the three lines beside it and no taller: every pixel
            // above that is one the track list does not get (his call). The
            // three rows are single-line and fixed-height, so this height does
            // not depend on the width the cover leaves them.
            width: height; height: meta.height
            color: Theme.bgAlt
            border.width: Theme.ctrlBorder; border.color: Theme.border
            Image {
                anchors.fill: parent; anchors.margins: 1
                source: root.openInfo.fullArt ? "file://" + root.openInfo.fullArt : ""
                fillMode: Image.PreserveAspectFit
                asynchronous: true; sourceSize.width: 512; sourceSize.height: 512
                visible: status === Image.Ready; opacity: root.fgArt
            }
            PixelText { anchors.centerIn: parent; visible: !root.openInfo.fullArt
                text: "♫"; font.pixelSize: 30; color: Theme.dim }
            MouseArea {
                anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                onDoubleClicked: root.openAlbumRequested(root.openId)
            }
        }
        Column {
            id: meta
            readonly property int rowH: Theme.lineHeight + 2  // descender room
            anchors { left: openArt.right; leftMargin: 8; right: parent.right
                      top: parent.top }
            spacing: 2
            PixelText { width: parent.width; height: meta.rowH; clip: true
                color: root.fgText; elide: Text.ElideRight
                text: glyphs.px(root.openInfo.album || "") }
            PixelText { width: parent.width; height: meta.rowH; clip: true
                color: root.fgDim; elide: Text.ElideRight
                text: glyphs.px(root.openInfo.artist || "") }
            PixelText { width: parent.width; height: meta.rowH; clip: true
                color: root.fgDim
                text: (root.openInfo.year > 0 ? root.openInfo.year + "  ·  " : "")
                      + (root.openInfo.trackCount || 0) + " tracks" }
        }
        TrackList {
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            anchors.top: openArt.bottom
            anchors.topMargin: 6
            model: BrowseTracksModel
            fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
            hideArtist: root.openInfo.artist || ""
            inAlbum: 0            // "go to album" lands on the gallery, which is elsewhere
            onPlayed: function(index) { Player.playAlbum(root.openId, index); }
            onOpenAlbumRequested: function(aid) { root.openAlbumRequested(aid); }
            onBrowseArtistRequested: function(a) { root.browseArtistRequested(a); }
            onEditAliasesRequested: function(a) { root.editAliasesRequested(a); }
        }
    }

    // ---- the cover grid ----------------------------------------------------
    KineticListView {
        id: list
        objectName: "browseList"
        visible: root.openId <= 0
        anchors { left: parent.left; right: parent.right; top: head.bottom
                  bottom: parent.bottom; topMargin: 4 }
        clip: true
        model: Math.max(0, Math.ceil(BrowseAlbumsModel.count / root.cols))
        cacheBuffer: 600
        wheelLines: 1
        wheelStep: root.cellW
        ScrollBar.vertical: VScroll { id: vbar }

        delegate: Item {
            id: rowItem
            required property int index
            width: list.width
            height: root.cellW

            Row {
                Repeater {
                    model: root.cols
                    delegate: Rectangle {
                        id: tile
                        objectName: "browseTile"
                        required property int index
                        readonly property int albumIndex: rowItem.index * root.cols + tile.index
                        readonly property var a: BrowseAlbumsModel.count >= 0
                                                 ? root.albumAt(tile.albumIndex) : null
                        width: root.cellW; height: root.cellW
                        visible: a !== null
                        color: Theme.bgAlt

                        Image {
                            anchors.fill: parent
                            source: (tile.a && tile.a.thumbPath) ? "file://" + tile.a.thumbPath : ""
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                            // Same reason as the gallery: bound the decoded
                            // covers to the viewport, not to the whole library.
                            cache: false
                            sourceSize.width: 256; sourceSize.height: 256
                            visible: status === Image.Ready
                            opacity: root.fgArt
                        }
                        PixelText {
                            anchors.centerIn: parent
                            visible: !(tile.a && tile.a.thumbPath)
                            text: "♫"; font.pixelSize: 30; color: Theme.dim
                        }
                        Rectangle {
                            anchors.fill: parent
                            visible: root.plasma
                            color: "transparent"
                            border.width: 1; border.color: Theme.border
                            gradient: Gradient {
                                GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.16) }
                                GradientStop { position: 0.38; color: Qt.rgba(1, 1, 1, 0.025) }
                                GradientStop { position: 0.40; color: "transparent" }
                                GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.06) }
                            }
                        }
                        Rectangle {
                            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                            height: labelCol.implicitHeight + 8
                            visible: tileMouse.containsMouse
                            color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.82)
                            Column {
                                id: labelCol
                                anchors { verticalCenter: parent.verticalCenter
                                          left: parent.left; leftMargin: 5
                                          right: parent.right; rightMargin: 5 }
                                PixelText {
                                    width: parent.width; clip: true
                                    height: Theme.lineHeight + 2
                                    text: tile.a ? glyphs.px(tile.a.album) : ""
                                    color: root.fgText
                                }
                                PixelText {
                                    width: parent.width; clip: true
                                    height: Theme.lineHeight + 2
                                    text: tile.a ? glyphs.px(tile.a.artist) : ""
                                    color: root.fgDim
                                }
                            }
                        }
                        // Picked: a wash of the accent over the art, so a
                        // selected cover reads as selected from across the
                        // column and not only under the pointer.
                        readonly property bool picked: tile.a !== null
                                                       && root.isSelected(tile.a.albumId)
                        Rectangle {
                            anchors.fill: parent
                            visible: tile.picked
                            color: Qt.rgba(root.fgAccent.r, root.fgAccent.g,
                                           root.fgAccent.b, 0.28)
                        }
                        Rectangle {
                            anchors.fill: parent
                            visible: tileMouse.containsMouse || tile.picked
                            color: "transparent"
                            border.color: root.fgAccent
                            border.width: Math.max(1, Theme.ctrlBorder)
                        }
                        MouseArea {
                            id: tileMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            enabled: tile.a !== null
                            acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
                            onClicked: function(m) {
                                var aid = tile.a.albumId, art = tile.a.artist;
                                if (m.button === Qt.MiddleButton) {
                                    Player.queueAlbum(aid);
                                } else if (m.button === Qt.RightButton) {
                                    var p = tileMouse.mapToItem(albumMenu, m.x, m.y);
                                    // Inside the selection the menu acts on the
                                    // whole set; outside it, it is the one-album
                                    // menu, and the selection is left alone.
                                    if (root.isSelected(aid) && root.selectedIds.length > 1) {
                                        albumMenu.openForSelection(p.x, p.y, {
                                            ids: root.selectedIds,
                                            clearSelection: function() { root.clearSelection(); },
                                        });
                                        return;
                                    }
                                    albumMenu.openForAlbum(p.x, p.y, {
                                        albumId: aid, artist: art,
                                        isOpen: aid === root.openId,
                                        open: function(id) { root.openAlbum(id); },
                                        searchArtist: function(a) { root.browseArtistRequested(a); },
                                        editAliases: function(a) { root.editAliasesRequested(a); },
                                    });
                                } else if (m.modifiers & Qt.ShiftModifier) {
                                    root.selectRange(aid);
                                } else if (m.modifiers & Qt.ControlModifier) {
                                    root.selectToggle(aid);
                                } else {
                                    root.clearSelection();
                                    root._anchorId = aid;
                                    root.openAlbum(aid);
                                }
                            }
                            onDoubleClicked: function(m) {
                                if (m.button === Qt.LeftButton)
                                    Player.playAlbum(tile.a.albumId, -1);
                            }
                        }
                    }
                }
            }
        }
    }
    // Parented to the WINDOW, not to this column: CtxMenu clamps against its
    // own bounds, and this pane is a third of the page wide — the same reason
    // TrackList parents its row menu there.
    AlbumMenu {
        id: albumMenu
        objectName: "browseAlbumMenu"
        parent: root.Window.contentItem ? root.Window.contentItem : root
        anchors.fill: parent
    }

    PixelText {
        anchors.centerIn: list
        visible: root.openId <= 0 && BrowseAlbumsModel.count === 0
        color: Theme.dim
        text: search.text === "" ? "no albums" : "nothing matches"
    }
}
