import QtQuick

// Full search results over the whole library (SearchModel, casefolded
// substring match on title/artist/album — fed live by the header search
// field). Covers the content area; Esc or the close button dismisses.
Rectangle {
    id: root
    property string query: ""
    signal closed()
    // From the track list's right-click menu; the window owns navigation (and
    // dismisses this overlay on the way, since it covers the view it lands on).
    signal openAlbumRequested(int albumId)
    signal browseArtistRequested(string artist)

    color: Theme.bg

    Row {
        id: head
        x: 8
        y: 8
        spacing: 12
        PixelText {
            anchors.verticalCenter: parent.verticalCenter
            text: "results for \"" + root.query + "\"  (" + SearchModel.count + ")"
            color: Theme.textDim
        }
        HeaderButton {
            label: "> play all"
            onClicked: Library.playFromModel(SearchModel, 0)
        }
        HeaderButton {
            label: "× close"
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
