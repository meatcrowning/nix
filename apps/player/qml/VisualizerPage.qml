import QtQuick
import Player.Visualizer 1.0
import "../../qmlcommon"

Item {
    id: root
    signal openAlbum(int albumId)
    signal browseArtist(string artist)
    signal editAliases(string artist)
    signal toggleSidebar()
    property bool sidebar: true
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent
    property real fgArt: 1
    readonly property var cur: Player.current || ({})
    property real topFrac: Number(Prefs.get("visualizerStackTopFrac", .5)) || .5
    property bool bottomCollapsed: Prefs.get("visualizerBottomCollapsed", false) === true
    property real infoFrac: Number(Prefs.get("visualizerInfoWidthFrac", .5)) || .5
    readonly property real topH: bottomCollapsed ? Math.max(0, height-7)
                                : Math.max(0, Math.min(Math.max(0, height-107), Math.max(80, height*topFrac)))
    readonly property real infoW: Math.round(Math.max(0, bottom.width-7)
                                            * Math.max(.2, Math.min(.8, infoFrac)))

    Item {
        id: upper
        width: parent.width; height: root.topH
        VisualizerSurface {
            id: surface
            objectName: "visualizerSurface"
            source: Visualizer
            width: Math.max(1, parent.width-(root.sidebar ? controls.width+6 : 0))
            height: parent.height
            function resize() { Visualizer.setSize(Math.round(width), Math.round(height)); }
            onWidthChanged: resize()
            onHeightChanged: resize()
            Component.onCompleted: resize()
        }
        HeaderButton {
            id: sidebarButton
            anchors { left: parent.left; top: parent.top; margins: 6 }
            label: root.sidebar ? "hide controls (Tab)" : "show controls (Tab)"
            iconName: "sidebar-show"
            onClicked: root.toggleSidebar()
        }
        HeaderButton {
            anchors { left: sidebarButton.right; top: parent.top; margins: 6 }
            label: "retry"
            visible: (Visualizer.stateInfo.status || "").indexOf("stopped") >= 0
                     || (Visualizer.stateInfo.status || "").indexOf("unavailable") >= 0
            onClicked: Visualizer.retry()
        }
        PixelText {
            anchors { left: surface.left; right: surface.right; bottom: surface.bottom; margins: 8 }
            text: Visualizer.stateInfo.status || ""
            color: "white"
            wrapMode: Text.Wrap
            visible: text !== ""
        }
        VisualizerControls {
            id: controls
            objectName: "visualizerControls"
            anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
            width: Math.min(300, parent.width*.42)
            visible: root.sidebar
        }
    }

    Item {
        id: bottom
        visible: !root.bottomCollapsed
        clip: true
        y: root.topH+7; width: parent.width; height: Math.max(0,parent.height-y)
        Item {
            id: queue
            objectName: "visualizerQueue"
            x: root.infoW+7; width: Math.max(0,parent.width-x); height: parent.height
            PixelText { id: queueHead; x: 8; y: 4
                text: "queue  ("+Player.queueLength+")"; color: root.fgDim }
            TrackList {
                anchors { left: parent.left; right: parent.right; top: queueHead.bottom; bottom: parent.bottom; margins: 8 }
                model: QueueModel
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                showNumber: false; autoHideArtist: true; currentRow: Player.index
                followCurrent: true; ratingsOnHover: true; isQueue: true
                onPlayed: index => Player.jumpTo(index)
                onOpenAlbumRequested: aid => root.openAlbum(aid)
                onBrowseArtistRequested: artist => root.browseArtist(artist)
                onEditAliasesRequested: artist => root.editAliases(artist)
            }
        }
        Item {
            id: information
            clip: true
            objectName: "visualizerInformation"
            width: root.infoW; height: parent.height
            Image {
                id: art
                objectName: "visualizerArt"
                // Follow the pane's height; only constrain the square when
                // a narrow pane needs room for the metadata and controls.
                height: Math.max(0, Math.min(parent.height,
                            parent.width-Math.max(120, rating.width)-16))
                width: height
                source: root.cur.artPath ? "file://"+root.cur.artPath : ""
                fillMode: Image.PreserveAspectFit
                asynchronous: true; sourceSize.width: 512; sourceSize.height: 512
                opacity: root.fgArt
                MouseArea { anchors.fill: parent
                    enabled: (root.cur.albumId || 0)>0
                    onDoubleClicked: root.openAlbum(root.cur.albumId) }
            }
            Column {
                id: details
                anchors { left: art.right; right: parent.right; top: parent.top; margins: 8 }
                anchors.topMargin: Math.min(8, Math.max(0, parent.height-height))
                spacing: Math.max(0, Math.min(3, (parent.height-8
                         -title.height-artist.height-album.height-rating.height)/3))
                PixelText {
                    id: title
                    width: parent.width; text: root.cur.title || "nothing playing"
                    color: root.fgText; elide: Text.ElideRight
                }
                PixelText {
                    id: artist
                    width: parent.width; text: root.cur.artist || ""
                    color: root.fgDim; elide: Text.ElideRight
                }
                PixelText {
                    id: album
                    objectName: "visualizerAlbumYear"
                    width: parent.width
                    text: (root.cur.album || "")+(root.cur.year ? " · "+root.cur.year : "")
                    color: root.fgDim; elide: Text.ElideRight
                }
                Row {
                    id: rating
                    objectName: "visualizerRating"
                    spacing: 4
                    height: Math.max(stars.height, favorite.height)
                    Stars {
                        id: stars
                        objectName: "visualizerStars"
                        anchors.verticalCenter: parent.verticalCenter
                        rating: root.cur.rating === undefined || root.cur.rating === null ? -1 : root.cur.rating
                        enabled: root.cur.id !== undefined
                        onRated: v => Library.setRating(root.cur.id,v)
                    }
                    HeaderButton {
                        id: favorite
                        objectName: "visualizerFavorite"
                        anchors.verticalCenter: parent.verticalCenter
                        label: "favourite"; iconName: "heart"; iconOnly: true
                        lit: root.cur.favorite === true
                        enabled: root.cur.id !== undefined
                        onClicked: Library.setFavorite(root.cur.id, !root.cur.favorite)
                    }
                }
            }
        }
        MouseArea {
            id: infoDivider
            objectName: "visualizerInfoDivider"
            hoverEnabled: true
            preventStealing: true
            x: root.infoW; width: 7; height: parent.height
            cursorShape: Qt.SplitHCursor
            onPositionChanged: mouse => {
                if (pressed && bottom.width>width)
                    root.infoFrac=Math.max(.2,Math.min(.8,
                        (mapToItem(bottom,mouse.x,0).x-width/2)/(bottom.width-width)));
            }
            onReleased: Prefs.set("visualizerInfoWidthFrac",root.infoFrac)
            Rectangle {
                anchors.centerIn: parent
                width: 1; height: parent.height
                color: infoDivider.containsMouse || infoDivider.pressed ? root.fgAccent : Theme.border
            }
        }
    }
    MouseArea {
        id: topDivider
        objectName: "visualizerTopDivider"
        hoverEnabled: true
        preventStealing: true
        y: root.topH; width: parent.width; height: 7
        cursorShape: Qt.SplitVCursor
        onPositionChanged: mouse => {
            if (!pressed || root.height<=0) return;
            const y = mapToItem(root,0,mouse.y).y;
            root.bottomCollapsed = y >= root.height-14;
            if (!root.bottomCollapsed)
                root.topFrac=Math.max(.2,Math.min(1,y/root.height));
        }
        onReleased: {
            Prefs.set("visualizerStackTopFrac",root.topFrac);
            Prefs.set("visualizerBottomCollapsed",root.bottomCollapsed);
        }
        Rectangle {
            anchors.centerIn: parent
            width: parent.width; height: 1
            color: topDivider.containsMouse || topDivider.pressed ? root.fgAccent : Theme.border
        }
    }
}
