import QtQuick
import "../../../qmlcommon"
import ".."

// Plasma's compact now-playing composition: artwork and information share the
// upper section; the queue takes the full-width well below it.
Item {
    id: root
    property string face: "plasma"
    signal openAlbum(int albumId)
    signal browseArtist(string artist)
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent
    property real fgArt: 1.0
    readonly property var cur: Player.current
    property real topFrac: Number(Prefs.get("npPlasmaTopFrac", 0.48))
    property real artFrac: Number(Prefs.get("npPlasmaArtFrac", 0.39))
    readonly property int topH: Math.max(180, Math.min(height - 120, height * topFrac))
    readonly property int artW: Math.max(140, Math.min(width - 260, width * artFrac))

    function lighter(c, amount) {
        return Qt.rgba(c.r + (1 - c.r) * amount, c.g + (1 - c.g) * amount,
                       c.b + (1 - c.b) * amount, c.a)
    }

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
                Stars { rating: root.cur.rating === undefined || root.cur.rating === null ? -1 : root.cur.rating
                    onRated: function(v) { Library.setRating(root.cur.id, v) } }
                HeaderButton { label: "favourite"; iconName: "favorites"; iconOnly: true
                    lit: root.cur.favorite === true
                    onClicked: Library.setFavorite(root.cur.id, !root.cur.favorite) }
            }
            PixelText { y: 18; width: parent.width; color: root.fgDim
                elide: Text.ElideRight; text: root.cur.artist || "" }
            PixelText { y: 36; width: parent.width; color: root.fgDim
                elide: Text.ElideRight
                text: (root.cur.album || "") + (root.cur.year ? " · " + root.cur.year : "") }
        }

        NowInfoPane {
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom
                      top: identity.bottom; leftMargin: 8; rightMargin: 8; bottomMargin: 8 }
            trackId: root.cur.id === undefined ? -1 : root.cur.id
            track: root.cur
            fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
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

    Rectangle {
        id: queueWell
        anchors { left: parent.left; right: parent.right; top: artBox.bottom; bottom: parent.bottom }
        anchors.topMargin: 1
        color: Qt.darker(Theme.bgAlt, 1.08)
        border.width: Theme.ctrlBorder; border.color: Theme.border
        gradient: Gradient {
            GradientStop { position: 0; color: root.lighter(Theme.bgAlt, 0.07) }
            GradientStop { position: 1; color: Qt.darker(Theme.bgAlt, 1.13) }
        }
        PixelText { id: queueHead; x: 8; y: 5
            text: "queue  (" + Player.queueLength + ")"; color: root.fgDim }
        TrackList {
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom
                      top: queueHead.bottom; topMargin: 4; margins: Theme.ctrlBorder }
            model: QueueModel
            fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
            showNumber: false; autoHideArtist: true; currentRow: Player.index
            followCurrent: true; ratingsOnHover: true; isQueue: true
            onPlayed: function(index) { Player.jumpTo(index) }
            onOpenAlbumRequested: function(aid) { root.openAlbum(aid) }
            onBrowseArtistRequested: function(artist) { root.browseArtist(artist) }
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
