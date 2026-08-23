import QtQuick
import "../../qmlcommon"

// Full search results over the whole library (SearchModel, casefolded
// substring match on title/artist/album — fed live by the header search
// field). Covers the content area; Esc or the close button dismisses.
Rectangle {
    id: root
    property string query: ""
    // Foreground tones, handed in already faded by Main (docs/DESIGN.md §3.1.1).
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent
    signal closed()
    // From the track list's right-click menu; the window owns navigation (and
    // dismisses this overlay on the way, since it covers the view it lands on).
    signal openAlbumRequested(int albumId)
    signal browseArtistRequested(string artist)

    // THE WINDOW'S OWN SURFACE, not a flat fill of it (docs/DESIGN.md §7.6).
    // This overlay covers the whole content area, so under Plasma a `Theme.bg`
    // rectangle was a flat patch of the scheme's window colour laid over
    // Oxygen's gradient — the one break in the surface that runs unbroken from
    // the titlebar down through the menubar and toolbar. `windowFill` is
    // transparent there and `Theme.bg` under Hyprland, exactly as before.
    color: Theme.windowFill
    // It still has to OCCLUDE the views underneath, which transparency alone
    // does not, so the style's own background is drawn behind it instead —
    // opaque, and continuous with the chrome above.
    clip: root.plasma

    readonly property bool plasma: (typeof DeskStyle !== "undefined" && DeskStyle)
                                   ? DeskStyle.plasma === true : false

    // The provider crops the style's render to the VIEW's rectangle and pads
    // from this item's own top-left (qmlcommon/StyledBackground.qml), so it is
    // put back at the view origin and the overlay's clip cuts it. This item's
    // parent fills the view, so its own x/y IS that offset. Invisible and free
    // under Hyprland.
    StyledBackground {
        x: -root.x
        y: -root.y
        width: root.width + root.x
        height: root.height + root.y
        z: -1
    }

    Row {
        id: head
        x: 8
        y: 8
        spacing: 12
        PixelText {
            anchors.verticalCenter: parent.verticalCenter
            text: "results for \"" + root.query + "\"  (" + SearchModel.count + ")"
            color: root.fgDim
        }
        HeaderButton {
            label: "> play all"
            plainLabel: "play all"; iconName: "media-playback-start"
            fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
            onClicked: Library.playFromModel(SearchModel, 0)
        }
        HeaderButton {
            label: "x close"
            plainLabel: "close"; iconName: "window-close"
            fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
            onClicked: root.closed()
        }
    }

    TrackList {
        anchors.top: head.bottom
        anchors.topMargin: 4
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        model: SearchModel
        fgText: root.fgText
        fgDim: root.fgDim
        fgAccent: root.fgAccent
        showNumber: false
        onPlayed: function(index) { Library.playFromModel(SearchModel, index); }
        onOpenAlbumRequested: function(aid) { root.openAlbumRequested(aid); }
        onBrowseArtistRequested: function(a) { root.browseArtistRequested(a); }
    }

    PixelText {
        anchors.centerIn: parent
        visible: SearchModel.count === 0 && root.query.length > 0
        text: "nothing found"
        color: Theme.dim
    }

    // Swallow clicks meant for the views underneath.
    MouseArea {
        anchors.fill: parent
        z: -1
        onClicked: {}
    }
}
