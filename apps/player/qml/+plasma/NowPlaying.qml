import QtQuick
import "../../../qmlcommon"
import ".."

// Plasma's now-playing composition: artwork and information share the upper
// section; the queue takes the well below it.
//
// GIVEN A WHOLE SCREEN IT BECOMES THE ALL-IN-ONE PAGE (`expanded`, his ask):
// the release pane keeps the upper half of the right-hand column and LYRICS
// take the lower half as a section of their own — so the tab that used to
// switch between them is gone, not duplicated — and an album browser with its
// own search sits beside the queue. Everything it adds is a pane that was
// already reachable somewhere else; nothing here is a second implementation.
//
// "Maximized" is read from the GEOMETRY, not from a window state: the QML in a
// Plasma session lives inside a QQuickWidget and has no window to ask, and a
// window dragged to within a pixel of full screen should get the same page a
// maximized one does. The floors are what the two new panes need to be worth
// drawing — below them the page stays exactly the compact one it was.
Item {
    id: root
    property string face: "plasma"
    signal openAlbum(int albumId)
    signal browseArtist(string artist)
    signal editAliases(string artist)
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent
    property real fgArt: 1.0
    readonly property var cur: Player.current
    property real topFrac: Number(Prefs.get("npPlasmaTopFrac", 0.48))
    property real artFrac: Number(Prefs.get("npPlasmaArtFrac", 0.39))
    // The two splits the all-in-one page adds: release pane over lyrics, and
    // queue beside the album browser. Draggable and persisted like the others.
    property real infoFrac: Number(Prefs.get("npPlasmaInfoFrac", 0.5))
    property real browseFrac: Number(Prefs.get("npPlasmaBrowseFrac", 0.42))
    readonly property bool expanded: width >= 1000 && height >= 620
    readonly property int topH: Math.max(180, Math.min(height - 120, height * topFrac))
    readonly property int artW: Math.max(140, Math.min(width - 260, width * artFrac))


    Rectangle {
        id: artBox
        width: root.artW; height: root.topH
        color: "transparent"
        Image {
            anchors.fill: parent; anchors.margins: Theme.ctrlBorder
            source: root.cur.artPath ? "file://" + root.cur.artPath : ""
            fillMode: Image.PreserveAspectFit
            asynchronous: true; sourceSize.width: 1024; sourceSize.height: 1024
            visible: status === Image.Ready; opacity: root.fgArt
        }
        PixelText { anchors.centerIn: parent; visible: !root.cur.artPath
            text: "♫"; font.pixelSize: 60; color: Theme.dim }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
            enabled: (root.cur.albumId || 0) > 0
            onDoubleClicked: root.openAlbum(root.cur.albumId) }
    }

    Item {
        id: upperRight
        anchors { left: artBox.right; leftMargin: 1; right: parent.right; top: parent.top }
        height: root.topH

        Item {
            id: identity
            x: 10; y: 7; width: parent.width - 18; height: 52
            PixelText { id: title; anchors { left: parent.left; right: rating.left; top: parent.top }
                color: root.cur.title ? root.fgText : root.fgDim
                elide: Text.ElideRight; text: root.cur.title || "nothing playing" }
            Row {
                id: rating; anchors { right: parent.right; top: parent.top }
                Stars { anchors.verticalCenter: parent.verticalCenter
                    rating: root.cur.rating === undefined || root.cur.rating === null ? -1 : root.cur.rating
                    onRated: function(v) { Library.setRating(root.cur.id, v) } }
                HeaderButton { label: "favourite"; iconName: "heart"; iconOnly: true
                    lit: root.cur.favorite === true
                    onClicked: Library.setFavorite(root.cur.id, !root.cur.favorite) }
            }
            PixelText { y: 18; width: parent.width; color: root.fgDim
                elide: Text.ElideRight; text: root.cur.artist || "" }
            PixelText { y: 36; width: parent.width; color: root.fgDim
                elide: Text.ElideRight
                text: (root.cur.album || "") + (root.cur.year ? " · " + root.cur.year : "") }
        }

        Item {
            id: infoWell
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom
                      top: identity.bottom; leftMargin: 8; rightMargin: 8; bottomMargin: 8 }
            // Compact: the pane is the whole column and carries its lyrics tab.
            // Expanded: it keeps the upper half and lyrics take the lower one.
            readonly property int infoH: root.expanded
                ? Math.max(110, Math.min(height - 130, height * root.infoFrac))
                : height

            NowInfoPane {
                objectName: "nowInfoPane"
                width: parent.width; height: infoWell.infoH
                showLyrics: !root.expanded
                trackId: root.cur.id === undefined ? -1 : root.cur.id
                track: root.cur
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
            }

            Item {
                id: lyricsSection
                objectName: "lyricsSection"
                visible: root.expanded
                y: infoWell.infoH + 7
                width: parent.width
                height: Math.max(0, parent.height - y)

                PixelText {
                    id: lyricsHead
                    x: 1; y: 1; color: root.fgDim
                    text: "lyrics"
                }
                Rectangle {
                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom
                              top: lyricsHead.bottom; topMargin: 4 }
                    color: Theme.bgAlt
                    border.width: Theme.ctrlBorder; border.color: Theme.border
                    radius: Math.max(2, Theme.rounding)
                    clip: true
                    LyricsView {
                        anchors.fill: parent; anchors.margins: Theme.ctrlBorder
                        active: lyricsSection.visible
                        trackId: root.cur.id === undefined ? -1 : root.cur.id
                        fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                    }
                }
            }
            // The split between them.
            Item {
                visible: root.expanded
                x: 0; y: infoWell.infoH; width: parent.width; height: 7; z: 9
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.SplitVCursor
                    onPositionChanged: function(mouse) {
                        if (!pressed || infoWell.height <= 0) return;
                        var gy = mapToItem(infoWell, 0, mouse.y).y;
                        root.infoFrac = Math.max(110 / infoWell.height,
                            Math.min((infoWell.height - 130) / infoWell.height,
                                     gy / infoWell.height));
                    }
                    onReleased: Prefs.set("npPlasmaInfoFrac", root.infoFrac)
                }
            }
        }
    }

    Rectangle {
        id: verticalSeparator
        x: artBox.width; y: 0; width: 1; height: root.topH
        color: Theme.border; z: 8
    }
    Item {
        x: verticalSeparator.x - 3; y: 0
        width: 7; height: root.topH; z: 9
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.SplitHCursor
            onPositionChanged: function(mouse) {
                if (!pressed || root.width <= 0) return;
                var gx = mapToItem(root, mouse.x, 0).x;
                root.artFrac = Math.max(140 / root.width,
                    Math.min((root.width - 260) / root.width, gx / root.width));
            }
            onReleased: Prefs.set("npPlasmaArtFrac", root.artFrac)
        }
    }

    Item {
        id: queueWell
        anchors { left: parent.left; right: parent.right; top: artBox.bottom; bottom: parent.bottom }
        anchors.topMargin: 1
        Rectangle { anchors { left: parent.left; right: parent.right; top: parent.top }
            height: Theme.ctrlBorder; color: Theme.border }
        // The browser takes its share off the right; compact, it takes none and
        // the queue is the full-width well it has always been.
        readonly property int browseW: root.expanded
            ? Math.round(Math.max(280, Math.min(width - 320, width * root.browseFrac)))
            : 0
        PixelText { id: queueHead; x: 8; y: 5
            text: "queue  (" + Player.queueLength + ")"; color: root.fgDim }

        Rectangle {
            id: queueListWell
            anchors { left: parent.left; bottom: parent.bottom
                      top: queueHead.bottom; topMargin: 4; leftMargin: 8
                      bottomMargin: 8 }
            width: Math.max(1, queueWell.width - 16
                               - (queueWell.browseW > 0 ? queueWell.browseW + 9 : 0))
            color: Theme.bgAlt
            border.width: Theme.ctrlBorder; border.color: Theme.border
            radius: Math.max(2, Theme.rounding)
            clip: true
            TrackList {
                anchors.fill: parent; anchors.margins: Theme.ctrlBorder
                model: QueueModel
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                showNumber: false; autoHideArtist: true; currentRow: Player.index
                followCurrent: true; ratingsOnHover: true; isQueue: true
                onPlayed: function(index) { Player.jumpTo(index) }
                onOpenAlbumRequested: function(aid) { root.openAlbum(aid) }
                onBrowseArtistRequested: function(artist) { root.browseArtist(artist) }
                onEditAliasesRequested: function(artist) { root.editAliases(artist) }
            }
        }

        // ---- the album browser, beside the queue ----
        PixelText {
            id: browseHead
            visible: root.expanded
            x: browseWell.x; y: 5
            text: "albums"; color: root.fgDim
        }
        Rectangle {
            id: browseWell
            objectName: "browseWell"
            visible: root.expanded
            anchors { right: parent.right; bottom: parent.bottom
                      top: browseHead.bottom; topMargin: 4; rightMargin: 8
                      bottomMargin: 8 }
            width: Math.max(0, queueWell.browseW)
            color: Theme.bgAlt
            border.width: Theme.ctrlBorder; border.color: Theme.border
            radius: Math.max(2, Theme.rounding)
            clip: true
            // Built only once the page is wide enough to show it: the Bridge
            // maps every album in the library the first time this asks for
            // rows, and the compact page never does.
            Loader {
                anchors.fill: parent; anchors.margins: Theme.ctrlBorder
                active: root.expanded
                sourceComponent: AlbumBrowser {
                    objectName: "albumBrowser"
                    fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                    fgArt: root.fgArt
                    onOpenAlbumRequested: function(aid) { root.openAlbum(aid) }
                    onBrowseArtistRequested: function(artist) { root.browseArtist(artist) }
                    onEditAliasesRequested: function(artist) { root.editAliases(artist) }
                }
            }
        }
        // The split between queue and browser.
        Item {
            visible: root.expanded
            x: browseWell.x - 5; y: 0
            width: 7; height: queueWell.height; z: 9
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.SplitHCursor
                onPositionChanged: function(mouse) {
                    if (!pressed || queueWell.width <= 0) return;
                    var gx = mapToItem(queueWell, mouse.x, 0).x;
                    root.browseFrac = Math.max(280 / queueWell.width,
                        Math.min((queueWell.width - 320) / queueWell.width,
                                 (queueWell.width - gx) / queueWell.width));
                }
                onReleased: Prefs.set("npPlasmaBrowseFrac", root.browseFrac)
            }
        }
    }

    Item {
        x: 0; y: queueWell.y - 3; width: root.width; height: 7; z: 9
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.SplitVCursor
            onPositionChanged: function(mouse) {
                if (!pressed || root.height <= 0) return;
                var gy = mapToItem(root, 0, mouse.y).y;
                root.topFrac = Math.max(180 / root.height,
                    Math.min((root.height - 120) / root.height, gy / root.height));
            }
            onReleased: Prefs.set("npPlasmaTopFrac", root.topFrac)
        }
    }
}
