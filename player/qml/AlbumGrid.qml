import QtQuick
import QtQuick.Controls.Basic

// The album gallery: edge-to-edge cover tiles with ZERO gap — the cell size
// adapts so whole covers tile the full width exactly. Title / artist / year
// appear only on hover, overlaid on the lower part of the cover itself.
// Thumbs are pre-rendered 256px JPEGs in the art cache, loaded async, so
// scrolling never decodes original artwork.
//
// Clicking a cover opens an AlbumPanel section INLINE, pushing the rows below
// it down (there is no separate album page) — so the grid is a ListView of
// cover ROWS, not a GridView: only a row delegate can grow to make room for
// the panel. Each row reads its `cols` albums straight out of AlbumsModel via
// get(); `revision` (bumped on every model reset) is read by those bindings so
// a re-sort/re-filter/rescan repaints the tiles even when the count is equal.
Item {
    id: root
    // The album to expand; 0 collapses. Owned by Main (so the mouse
    // back/forward history can restore it), toggled through `opened`.
    property int expandedAlbumId: 0
    signal opened(int albumId)      // 0 == collapse
    signal searchArtist(string artist)

    // True while a search filter narrows the grid: the browse position is only
    // remembered for the UNFILTERED grid, so clearing the search puts the user
    // back where they were browsing rather than at the filtered view's top.
    property bool filtered: false
    onFilteredChanged: if (!filtered) list.requestRestore()

    // Coming back to the albums page (from a now-playing/playlists trip, or a
    // model reset behind our back) lands on the exact same row again.
    onVisibleChanged: if (visible) list.requestRestore()

    // Seven covers across, whatever the window width — covers scale so the
    // rows stay flush left and right with 0px gaps.
    readonly property int cols: 7
    readonly property int cellW: Math.max(1, Math.floor(width / cols))

    property int revision: 0
    Connections {
        target: AlbumsModel
        function onModelReset() { root.revision++; }
    }

    function albumAt(i) {
        return (i >= 0 && i < AlbumsModel.count) ? AlbumsModel.get(i) : null;
    }

    // Where the expanded album sits now — re-scanned whenever the model is
    // rebuilt, so a re-sort moves the open section to the cover's new row.
    readonly property int expandedIndex: {
        root.revision;               // dependency: re-scan after a model reset
        if (root.expandedAlbumId <= 0)
            return -1;
        for (var i = 0; i < AlbumsModel.count; i++)
            if (AlbumsModel.get(i).albumId === root.expandedAlbumId)
                return i;
        return -1;
    }
    readonly property int expandedRow: expandedIndex < 0 ? -1 : Math.floor(expandedIndex / cols)

    // Opening from elsewhere (now playing, a context menu) may target a cover
    // that is scrolled off screen — bring its row into view, then again once
    // the row has finished growing so the whole section is on screen.
    onExpandedIndexChanged: {
        if (expandedIndex >= 0) {
            Qt.callLater(list.showExpanded);
            settleTimer.restart();
        }
    }
    Timer {
        id: settleTimer
        interval: 140
        onTriggered: list.showExpanded()
    }

    ListView {
        id: list
        objectName: "albumList"
        anchors.fill: parent
        clip: true
        model: Math.ceil(AlbumsModel.count / root.cols)
        cacheBuffer: 900
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: VScroll { id: vbar }

        function showExpanded() {
            if (root.expandedRow >= 0)
                positionViewAtIndex(root.expandedRow, ListView.Contain);
        }

        // ---- scroll memory ----------------------------------------------
        // The grid's spot is kept in Prefs (so it survives a restart too) and
        // re-applied whenever the model resets under us — the albums model is
        // rebuilt wholesale on sort/filter/rescan, which snaps contentY to 0.
        // Only genuine user scrolling records a new position, so those resets
        // can't overwrite the remembered one with 0.
        property real savedY: Number(Prefs.get("albumScrollY", 0))
        property bool restored: false
        property bool pending: true      // a restore is owed (startup / filter cleared)

        function restorePos() {
            if (root.filtered || count === 0 || height <= 0 || contentHeight <= 0)
                return;
            contentY = Math.max(0, Math.min(savedY, contentHeight - height));
            restored = true;
            pending = false;
        }
        // Ask for a restore now AND once the model finishes repopulating — the
        // rows behind a cleared filter arrive a beat after the flag flips.
        function requestRestore() {
            pending = true;
            Qt.callLater(restorePos);
        }
        function rememberPos() {
            if (root.filtered || !restored || count === 0)
                return;
            savedY = contentY;
            saveTimer.restart();
        }

        Component.onCompleted: Qt.callLater(restorePos)
        // The library loads async: retry until there is something to scroll.
        onCountChanged: if (pending) Qt.callLater(restorePos)
        onMovementEnded: rememberPos()
        // Scrollbar drags move contentY without a flick, so track those too.
        onContentYChanged: if (moving || dragging || vbar.pressed) rememberPos()

        Timer {   // debounce the prefs write across a scroll
            id: saveTimer
            interval: 400
            onTriggered: Prefs.set("albumScrollY", list.savedY)
        }

        // ---- one row of covers, plus the inline section when it is open ----
        delegate: Item {
            id: rowItem
            required property int index
            readonly property bool expanded: root.expandedRow === rowItem.index

            // How much of the section is revealed. Animating THIS (rather than
            // just unloading) is what makes closing mirror opening: the panel
            // stays alive, clipped, until it has slid back up under the covers.
            property real panelH: expanded ? panelLoader.panelHeight : 0
            Behavior on panelH { NumberAnimation { duration: 130; easing.type: Easing.OutQuad } }

            width: list.width
            height: root.cellW + panelH
            clip: true

            Row {
                id: tiles
                height: root.cellW

                Repeater {
                    model: root.cols

                    delegate: Rectangle {
                        id: tile
                        required property int index
                        readonly property int albumIndex: rowItem.index * root.cols + tile.index
                        // Reading revision + count keeps this bound to model resets.
                        readonly property var a: (root.revision >= 0 && AlbumsModel.count >= 0)
                                                 ? root.albumAt(tile.albumIndex) : null

                        width: root.cellW
                        height: root.cellW
                        visible: a !== null
                        color: Theme.bgAlt

                        Image {
                            anchors.fill: parent
                            source: (tile.a && tile.a.thumbPath) ? "file://" + tile.a.thumbPath : ""
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                            cache: true
                            sourceSize.width: 256
                            sourceSize.height: 256
                            visible: status === Image.Ready
                        }
                        PixelText {
                            anchors.centerIn: parent
                            visible: !(tile.a && tile.a.thumbPath)
                            text: "♫"
                            font.pixelSize: 45
                            color: Theme.dim
                        }

                        // Hover: the metadata, inside the cover's lower edge.
                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            height: labelCol.implicitHeight + 10
                            visible: tileMouse.containsMouse
                            color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.82)

                            Column {
                                id: labelCol
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.left: parent.left
                                anchors.leftMargin: 6
                                anchors.right: parent.right
                                anchors.rightMargin: 6

                                PixelText {
                                    width: parent.width
                                    text: tile.a ? tile.a.album : ""
                                    clip: true
                                    height: Theme.fontSize + 2  // descender room: 16px ink in the 15px line
                                    color: Theme.text
                                }
                                PixelText {
                                    width: parent.width
                                    text: tile.a ? ((tile.a.year > 0 ? tile.a.year + "  " : "") + tile.a.artist) : ""
                                    clip: true
                                    height: Theme.fontSize + 2  // descender room: 16px ink in the 15px line
                                    color: Theme.textDim
                                }
                            }
                        }
                        // Hover / open frame, drawn over the art's edge. The
                        // open cover stays framed so it's obvious which one
                        // the section below belongs to.
                        Rectangle {
                            anchors.fill: parent
                            visible: tileMouse.containsMouse
                                     || (tile.a && tile.a.albumId === root.expandedAlbumId)
                            color: "transparent"
                            border.color: Theme.accent
                            border.width: 1
                        }

                        MouseArea {
                            id: tileMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            enabled: tile.a !== null
                            acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
                            onClicked: function(m) {
                                var aid = tile.a.albumId, art = tile.a.artist;
                                if (m.button === Qt.MiddleButton) {
                                    Player.queueAlbum(aid);
                                } else if (m.button === Qt.RightButton) {
                                    var p = tileMouse.mapToItem(root, m.x, m.y);
                                    ctxMenu.open(p.x, p.y, [
                                        { label: "play",          trigger: function() { Player.playAlbum(aid, 0); } },
                                        { label: "play shuffled", trigger: function() { Player.setShuffle(true); Player.playAlbum(aid, 0); } },
                                        { label: "add to queue",  trigger: function() { Player.queueAlbum(aid); } },
                                        { separator: true },
                                        { label: aid === root.expandedAlbumId ? "close album" : "open album",
                                          trigger: function() { root.opened(aid === root.expandedAlbumId ? 0 : aid); } },
                                        { label: "search artist", enabled: art !== "",
                                          trigger: function() { root.searchArtist(art); } },
                                    ]);
                                } else {
                                    // A second click on the open cover closes it.
                                    root.opened(aid === root.expandedAlbumId ? 0 : aid);
                                }
                            }
                            onDoubleClicked: function(m) {
                                if (m.button === Qt.LeftButton) Player.playAlbum(tile.a.albumId, 0);
                            }
                        }
                    }
                }
            }

            // The inline album section — only the open row instantiates one.
            // The panel keeps its full height inside this clip, so the reveal
            // slides it out from under the covers instead of squashing it.
            Item {
                id: panelClip
                anchors.top: tiles.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                height: rowItem.panelH
                clip: true

                Loader {
                    id: panelLoader
                    width: parent.width
                    // A Loader takes its implicit size from the loaded item, so
                    // this is the panel's own implicitHeight (0 when unloaded).
                    height: implicitHeight
                    readonly property real panelHeight: implicitHeight
                    // Stays loaded until the slide-up has finished.
                    active: rowItem.expanded || rowItem.panelH > 0.5
                    sourceComponent: Component {
                        AlbumPanel {
                            objectName: "albumPanel"
                            albumId: root.expandedAlbumId
                            onClosed: root.opened(0)
                        }
                    }
                }
            }
        }
    }

    PixelText {
        anchors.centerIn: parent
        visible: AlbumsModel.count === 0
        text: "no albums — is the library drive mounted?"
        color: Theme.textDim
    }

    CtxMenu {
        id: ctxMenu
        anchors.fill: parent
    }
}
