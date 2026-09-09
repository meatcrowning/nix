import QtQuick
import QtQuick.Controls
import "../../qmlcommon"

// Plasma now-playing notebook: lyrics plus cached, correctable web facts.
// The controls are real QQC2 controls painted by the KDE style; the surrounding
// wells use only scheme colours so Oxygen's relief follows every colour scheme.
Item {
    id: root
    property int trackId: -1
    property var track: ({})
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent
    property string tab: "lyrics"
    property bool editing: false
    readonly property var info: Library.nowInfo || ({})
    readonly property var albumTracks: (track.albumId || 0) > 0
                                       ? Library.albumTrackInfo(track.albumId) : []

    function lighter(c, amount) {
        return Qt.rgba(c.r + (1 - c.r) * amount, c.g + (1 - c.g) * amount,
                       c.b + (1 - c.b) * amount, c.a)
    }

    Rectangle {
        anchors.fill: parent
        color: Qt.darker(Theme.bgAlt, 1.08)
        border.width: Theme.ctrlBorder
        border.color: Theme.border
        radius: Math.max(2, Theme.rounding)
        clip: true
    }

    Rectangle {
        id: tabBar
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: 25
        color: "transparent"
        border.width: Theme.ctrlBorder
        border.color: Theme.border
        clip: true
        StyledBackground { anchors.fill: parent }
    }

    Row {
        id: tabs
        x: 4; anchors.verticalCenter: tabBar.verticalCenter
        spacing: 1
        Repeater {
            model: ["lyrics", "album", "similar"]
            HeaderButton {
                required property string modelData
                label: modelData
                lit: root.tab === modelData
                onClicked: root.tab = modelData
            }
        }
    }

    Row {
        id: actions
        anchors.right: parent.right
        anchors.rightMargin: 4
        // Lives in the identity space immediately above this notebook. Keeping
        // it out of the tab row prevents the icons covering "similar" at the
        // narrow width while placing them beside the album facts they act on.
        y: -28
        spacing: 1
        visible: root.tab !== "lyrics"
        HeaderButton {
            label: "refresh"; plainLabel: "refresh"; iconName: "view-refresh"; iconOnly: true
            onClicked: Library.refreshNowInfo()
        }
        HeaderButton {
            label: "change match"; plainLabel: "change match"; iconName: "edit-find-replace"; iconOnly: true
            onClicked: candidates.visible = !candidates.visible
        }
        HeaderButton {
            label: "edit"; plainLabel: "edit"; iconName: "document-edit"; iconOnly: true
            visible: root.tab === "album"
            onClicked: {
                editTitle.text = (root.info.album || {}).title || "";
                editArtist.text = (root.info.album || {}).artist || "";
                editDescription.text = (root.info.album || {}).description || "";
                root.editing = true;
            }
        }
    }

    Item {
        id: body
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom
                  top: tabBar.bottom; margins: Theme.ctrlBorder }

        LyricsView {
            anchors.fill: parent
            visible: root.tab === "lyrics"
            active: visible
            trackId: root.trackId
            fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
        }

        Item {
            anchors.fill: parent
            visible: root.tab === "album" && !root.editing

            PixelText {
                id: albumState
                x: 8; y: 6
                width: parent.width - 16
                color: root.info.status === "error" ? Theme.crit : root.fgDim
                text: root.info.status === "loading" ? "loading information from the web..."
                    : root.info.status === "ambiguous" ? "choose the correct match"
                    : root.info.status === "no_match" ? "no web match found"
                    : root.info.error ? "web fetch failed: " + root.info.error
                    : root.info.stale ? "cached information - refresh available"
                    : "musicbrainz" + ((root.info.album || {}).description ? " + wikipedia" : "")
                elide: Text.ElideRight
            }
            KineticFlickable {
                id: albumFlick
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom
                          top: albumState.bottom; margins: 8; topMargin: 6 }
                contentWidth: width
                contentHeight: albumColumn.height
                clip: true
                ScrollBar.vertical: VScroll { id: albumScroll }
                Column {
                    id: albumColumn
                    width: Math.max(0, albumFlick.width - albumScroll.barW)
                    spacing: 5
                    PixelText { width: parent.width; color: root.fgText; wrapMode: Text.Wrap
                        text: (root.info.album || {}).title || root.track.album || "" }
                    PixelText { width: parent.width; color: root.fgDim; wrapMode: Text.Wrap
                        text: (root.info.album || {}).artist || root.track.artist || "" }
                    PixelText { width: parent.width; color: root.fgDim; wrapMode: Text.Wrap
                        text: [(root.info.album || {}).primaryType,
                               (root.info.album || {}).firstReleaseDate].filter(Boolean).join(" · ") }
                    PixelText { width: parent.width; color: root.fgDim; wrapMode: Text.Wrap
                        text: "track: " + (root.track.title || "") + " · "
                            + Math.round(Number(root.track.duration || 0) / 60) + " min · "
                            + Number(root.track.playCount || 0) + " plays" }
                    PixelText { width: parent.width; color: root.fgText; wrapMode: Text.Wrap
                        text: (root.info.album || {}).description || "no description found" }
                    PixelText { width: parent.width; color: root.fgDim; wrapMode: Text.Wrap
                        visible: !!((root.info.album || {}).artistInfo || {}).description
                        text: (((root.info.album || {}).artistInfo || {}).name || "") + "\n" +
                              (((root.info.album || {}).artistInfo || {}).description || "") }
                    Repeater {
                        model: root.albumTracks
                        delegate: PixelText {
                            required property var modelData
                            width: albumColumn.width
                            color: modelData.trackId === root.trackId ? root.fgAccent : root.fgDim
                            elide: Text.ElideRight
                            text: (modelData.track || (index + 1)) + "  " + modelData.title
                        }
                    }
                    Row {
                        spacing: 2
                        HeaderButton { label: "revert edits"; iconName: "edit-undo"
                            onClicked: Library.revertNowInfo("album") }
                        HeaderButton { label: "clear cache"; iconName: "edit-clear"
                            onClicked: Library.clearNowInfo() }
                    }
                }
            }
        }

        KineticListView {
            id: similarList
            anchors.fill: parent
            anchors.margins: 6
            visible: root.tab === "similar"
            clip: true
            model: root.info.similar || []
            ScrollBar.vertical: VScroll { id: similarScroll }
            header: PixelText {
                width: Math.max(0, similarList.width - similarScroll.barW)
                height: Theme.lineHeight + 6
                color: root.info.error ? Theme.crit : root.fgDim
                text: root.info.status === "loading" ? "loading similar tracks from last.fm..."
                    : root.info.error ? "last.fm failed - showing local matches"
                    : root.info.similarFallback ? "local matches" : "last.fm matches in your library"
            }
            delegate: Rectangle {
                required property var modelData
                width: Math.max(0, similarList.width - similarScroll.barW)
                height: Theme.lineHeight + 8
                color: hit.containsMouse ? Theme.highlight : "transparent"
                PixelText { anchors { left: parent.left; right: reason.left; verticalCenter: parent.verticalCenter }
                    anchors.leftMargin: 5; elide: Text.ElideRight; color: root.fgText
                    text: modelData.title + "  " + modelData.artist }
                PixelText { id: reason; anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                    anchors.rightMargin: 5; color: root.fgDim; text: modelData.reason }
                MouseArea { id: hit; anchors.fill: parent; hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onDoubleClicked: Player.playTracks([modelData.trackId], 0) }
            }
        }
    }

    Rectangle {
        id: candidates
        visible: false
        z: 20
        anchors { left: parent.left; right: parent.right; top: tabBar.bottom; bottom: parent.bottom }
        color: Theme.bgAlt
        border.width: Theme.ctrlBorder; border.color: Theme.border
        KineticListView {
            id: candidateList
            anchors.fill: parent; anchors.margins: 5; clip: true
            model: root.info.candidates || []
            ScrollBar.vertical: VScroll { id: candidateScroll }
            delegate: HeaderButton {
                required property var modelData
                width: Math.max(0, candidateList.width - candidateScroll.barW)
                label: modelData.label + "  (" + Math.round(modelData.confidence * 100) + "%)"
                onClicked: { Library.chooseNowInfoMatch(modelData.id); candidates.visible = false }
            }
        }
    }

    Rectangle {
        visible: root.editing
        z: 30; anchors.fill: parent
        color: Theme.bgAlt
        border.width: Theme.ctrlBorder; border.color: Theme.border
        Column {
            anchors.fill: parent; anchors.margins: 8; spacing: 5
            TextField { id: editTitle; width: parent.width
                placeholderText: "album title" }
            TextField { id: editArtist; width: parent.width
                placeholderText: "artist" }
            TextArea { id: editDescription; width: parent.width
                height: Math.max(60, parent.height - editTitle.height - editArtist.height - editButtons.height - 25)
                placeholderText: "description"; wrapMode: TextEdit.Wrap
            }
            Row {
                id: editButtons; spacing: 3
                HeaderButton { label: "save"; iconName: "document-save"
                    onClicked: {
                        Library.editNowInfo("album", { title: editTitle.text,
                            artist: editArtist.text, description: editDescription.text });
                        root.editing = false;
                    } }
                HeaderButton { label: "cancel"; iconName: "dialog-cancel"
                    onClicked: root.editing = false }
            }
        }
    }
}
