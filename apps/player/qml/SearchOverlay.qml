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
    signal editAliasesRequested(string artist)

    // The other names of whoever `query` names, "" for ordinary text. Refreshed
    // rather than bound: it comes from a slot, which no binding can watch.
    property var alsoAs: []
    function refreshAlsoAs() { alsoAs = Library.artistOtherNames(root.query); }
    onQueryChanged: refreshAlsoAs()
    Component.onCompleted: refreshAlsoAs()
    Connections {
        target: Library
        function onArtistAliasesChanged() { root.refreshAlsoAs(); }
    }

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
        width: parent.width - 16
        spacing: 12
        PixelText {
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(0, head.width - resultCount.width - playAll.width
                            - closeSearch.width - 3 * head.spacing)
            elide: Text.ElideRight
            text: "results for \"" + root.query + "\""
            color: root.fgDim
        }
        PixelText {
            id: resultCount
            anchors.verticalCenter: parent.verticalCenter
            text: "(" + Library.searchTotal + ")"
            color: root.fgDim
        }
        HeaderButton {
            id: playAll
            label: "> play all"
            plainLabel: "play all"; iconName: "media-playback-start"
            fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
            enabled: Library.searchTotal > 0
            onClicked: Library.playSearchAll()
        }
        HeaderButton {
            id: closeSearch
            label: "x close"
            plainLabel: "close"; iconName: "window-close"
            fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
            onClicked: root.closed()
        }
    }

    // ONE PERSON, MANY NAMES: when the query names an artist identity
    // (main.py's `artistalias`), these results already include the other names'
    // records — so the line says so. Silent widening would read as the search
    // returning records it should not have (docs/DESIGN.md §10.6: a claim and
    // an observation are two readouts).
    PixelText {
        id: alsoLine
        anchors.top: head.bottom
        anchors.topMargin: visible ? 4 : 0
        x: 8
        width: parent.width - 16
        elide: Text.ElideRight
        visible: root.alsoAs.length > 0
        height: visible ? implicitHeight : 0
        text: "also as " + root.alsoAs.join(", ")
        color: root.fgDim
    }

    Row {
        id: pages
        anchors.top: alsoLine.bottom
        x: 8
        spacing: 12
        visible: Library.searchTotal > SearchModel.count
        height: visible ? implicitHeight : 0
        HeaderButton {
            label: "< previous"; plainLabel: "previous"; iconName: "go-previous"
            enabled: Library.searchOffset > 0
            fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
            onClicked: Library.searchPage(-1)
        }
        PixelText {
            anchors.verticalCenter: parent.verticalCenter
            text: (Library.searchOffset + 1) + "–"
                  + (Library.searchOffset + SearchModel.count)
                  + " of " + Library.searchTotal
            color: root.fgDim
        }
        HeaderButton {
            label: "next >"; plainLabel: "next"; iconName: "go-next"
            enabled: Library.searchOffset + SearchModel.count < Library.searchTotal
            fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
            onClicked: Library.searchPage(1)
        }
    }

    TrackList {
        anchors.top: pages.bottom
        anchors.topMargin: 4
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        model: SearchModel
        fgText: root.fgText
        fgDim: root.fgDim
        fgAccent: root.fgAccent
        showNumber: false
        onPlayed: function(index) { Library.playSearch(index); }
        onOpenAlbumRequested: function(aid) { root.openAlbumRequested(aid); }
        onBrowseArtistRequested: function(a) { root.browseArtistRequested(a); }
        onEditAliasesRequested: function(a) { root.editAliasesRequested(a); }
    }

    // The empty state is also the only place the field filters are named. A
    // placeholder cannot carry them (the box is 90px under Hyprland and the
    // platform's own line edit under Plasma), and a syntax nobody is told
    // about is a feature nobody has (docs/DESIGN.md §10).
    Column {
        anchors.centerIn: parent
        spacing: 4
        visible: SearchModel.count === 0 && root.query.length > 0
        PixelText {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "nothing found"
            color: Theme.dim
        }
        PixelText {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "genre:shoegaze   year:1997   year:1990-1999"
            color: Theme.dim
        }
    }

    // Swallow clicks meant for the views underneath.
    MouseArea {
        anchors.fill: parent
        z: -1
        onClicked: {}
    }
}
