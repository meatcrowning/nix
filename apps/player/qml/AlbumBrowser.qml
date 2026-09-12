import QtQuick
import QtQuick.Controls
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
            width: Math.min(96, parent.width / 3); height: width
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
            anchors { left: openArt.right; leftMargin: 8; right: parent.right
                      top: parent.top }
            spacing: 2
            PixelText { width: parent.width; color: root.fgText; wrapMode: Text.Wrap
                maximumLineCount: 2; text: glyphs.px(root.openInfo.album || "") }
            PixelText { width: parent.width; color: root.fgDim; elide: Text.ElideRight
                text: glyphs.px(root.openInfo.artist || "") }
            PixelText { width: parent.width; color: root.fgDim
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
                        Rectangle {
                            anchors.fill: parent
                            visible: tileMouse.containsMouse
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
                            acceptedButtons: Qt.LeftButton | Qt.MiddleButton
                            onClicked: function(m) {
                                if (m.button === Qt.MiddleButton)
                                    Player.queueAlbum(tile.a.albumId);
                                else
                                    root.openAlbum(tile.a.albumId);
                            }
                            onDoubleClicked: Player.playAlbum(tile.a.albumId, -1)
                        }
                    }
                }
            }
        }
    }
    PixelText {
        anchors.centerIn: list
        visible: root.openId <= 0 && BrowseAlbumsModel.count === 0
        color: Theme.dim
        text: search.text === "" ? "no albums" : "nothing matches"
    }
}
