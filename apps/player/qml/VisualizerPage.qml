import QtQuick
import QtQuick.Controls as QQC
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
    property real topFrac: Number(Prefs.get("visualizerTopFrac", .65)) || .65
    property real queueFrac: Number(Prefs.get("visualizerQueueFrac", .44)) || .44
    readonly property real topH: Math.max(80, Math.min(height-120, height*topFrac))
    readonly property real queueW: Math.max(120, Math.min(width-240, width*queueFrac))

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
        y: root.topH+7; width: parent.width; height: Math.max(0,parent.height-y)
        Item {
            id: queue
            objectName: "visualizerQueue"
            width: root.queueW; height: parent.height
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
            x: root.queueW+7; width: Math.max(0,parent.width-x); height: parent.height
            KineticFlickable {
                id: informationScroll
                objectName: "visualizerInformationScroll"
                anchors.fill: parent
                clip: true
                contentWidth: width
                contentHeight: card.height
                QQC.ScrollBar.vertical: VScroll { id: informationBar }
                Item {
                    id: card
                    width: informationScroll.width-informationBar.barW
                    // Leave a readable metadata viewport when the lower pane
                    // is shortened; the whole card then remains reachable.
                    height: Math.max(informationScroll.height, details.y+album.y+album.height+5+Theme.lineHeight*12+8)
                    Image {
                        id: art
                        width: Math.max(48, card.width*.32); height: Math.min(card.height, width)
                        source: root.cur.artPath ? "file://"+root.cur.artPath : ""
                        fillMode: Image.PreserveAspectFit
                        asynchronous: true; sourceSize.width: 512; sourceSize.height: 512
                        opacity: root.fgArt
                        MouseArea { anchors.fill: parent
                            enabled: (root.cur.albumId || 0)>0
                            onDoubleClicked: root.openAlbum(root.cur.albumId) }
                    }
                    Item {
                        id: details
                        anchors { left: art.right; right: parent.right; top: parent.top; bottom: parent.bottom; margins: 8 }
                        Row {
                            id: rating
                            anchors { right: parent.right; top: parent.top }
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
                        PixelText { id: title
                            y: rating.height+3
                            width: parent.width; text: root.cur.title || "nothing playing"
                            color: root.fgText; elide: Text.ElideRight }
                        PixelText { id: artist; y: title.y+title.height+3; width: parent.width
                            text: root.cur.artist || ""; color: root.fgDim; elide: Text.ElideRight }
                        PixelText { id: album; y: artist.y+artist.height+3; width: parent.width
                            text: (root.cur.album || "")+(root.cur.year ? " · "+root.cur.year : "")
                            color: root.fgDim; elide: Text.ElideRight }
                        NowInfoPane {
                            objectName: "visualizerInfoPane"
                            anchors { left: parent.left; right: parent.right; top: album.bottom; topMargin: 5; bottom: parent.bottom }
                            trackId: root.cur.id === undefined ? -1 : root.cur.id
                            track: root.cur
                            fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                        }
                    }
                }
            }
        }
        MouseArea {
            x: root.queueW; width: 7; height: parent.height
            cursorShape: Qt.SplitHCursor
            onPositionChanged: mouse => {
                if (pressed && bottom.width>0)
                    root.queueFrac=Math.max(.2,Math.min(.7,mapToItem(bottom,mouse.x,0).x/bottom.width));
            }
            onReleased: Prefs.set("visualizerQueueFrac",root.queueFrac)
        }
    }
    MouseArea {
        y: root.topH; width: parent.width; height: 7
        cursorShape: Qt.SplitVCursor
        onPositionChanged: mouse => {
            if (pressed && root.height>0)
                root.topFrac=Math.max(.2,Math.min(.85,mapToItem(root,0,mouse.y).y/root.height));
        }
        onReleased: Prefs.set("visualizerTopFrac",root.topFrac)
    }
}
