import QtQuick
import QtQuick.Controls
import "../../qmlcommon"

// The now-playing notebook: lyrics, release facts, then related music. The
// release view keeps identity and credits ahead of optional prose.
Item {
    id: root
    property int trackId: -1
    property var track: ({})
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent
    property string tab: "lyrics"
    property bool editing: false
    property string actionError: ""
    onTrackIdChanged: {
        editing = false;
        actionError = "";
        if (candidates) candidates.visible = false;
    }

    readonly property var info: Library.nowInfo || ({})
    // Status/recommendation deliveries must not recreate the release delegates.
    property var album: ({})
    property string albumJson: ""
    function syncAlbum() {
        var value = info.album || ({});
        var encoded = JSON.stringify(value);
        if (encoded !== albumJson) {
            albumJson = encoded;
            album = JSON.parse(encoded);
        }
    }
    onInfoChanged: syncAlbum()
    Component.onCompleted: syncAlbum()
    readonly property var artist: album.artistInfo || ({})
    readonly property var albumCredits: album.credits || []
    readonly property var releaseCredits: albumCredits.filter(function(c) { return c.scope === "album"; })
    readonly property var trackCredits: albumCredits.filter(function(c) { return c.scope === "track"; })
    readonly property var albumTracks: tab !== "album" ? [] : album.tracks && album.tracks.length
                                       ? album.tracks
                                       : ((track.albumId || 0) > 0
                                          ? Library.albumTrackInfo(track.albumId) : [])
    readonly property var relatedRows: {
        var out = [];
        var owned = info.similar || [];
        var discoveries = info.discoveries || [];
        if (owned.length) {
            out.push({ section: true, title: "in your library" });
            for (var i = 0; i < owned.length; ++i) out.push(owned[i]);
        }
        if (discoveries.length) {
            out.push({ section: true, title: "discoveries" });
            for (var j = 0; j < discoveries.length; ++j) out.push(discoveries[j]);
        }
        return out;
    }
    readonly property bool actionsInline: tabs.width + actions.width + 12 <= width
    readonly property int tabBaseHeight: Math.max(25, Theme.lineHeight + 8)

    function text(v) { return v === undefined || v === null ? "" : String(v); }
    function artistHeading() {
        var name = text(artist.name), note = text(artist.disambiguation);
        return name + (note !== "" ? "  (" + note + ")" : "");
    }
    function artistFacts() {
        return [text(artist.type), text(artist.area), text(artist.years)]
               .filter(function(v) { return v !== ""; }).join(" · ");
    }
    function validUrl(url) { return /^(https?):\/\/[^\s]+$/i.test(text(url)); }
    function isOwned(item) { return item && item.owned !== false; }
    function openUrl(url) {
        if (!validUrl(url)) { actionError = "no source link"; return; }
        var accepted = Library.openInfoUrl(text(url));
        actionError = accepted === false ? "source link failed" : "";
    }
    function browse(kind, entity) {
        entity = entity || ({});
        var entityId = text(entity.id), entityName = text(entity.name);
        if (entityId === "" && entityName === "") return;
        var accepted = Library.browseInfoConnection(kind, entityId, entityName);
        if (accepted === false) {
            actionError = "connection unavailable";
        } else {
            actionError = "";
            tab = "similar";
        }
    }
    function candidateLabel(candidate) {
        var bits = [], title = text(candidate.title || candidate.label);
        var artist = text(candidate.artist);
        if (title !== "") bits.push(title);
        if (artist !== "" && artist !== title) bits.push(artist);
        var detail = [text(candidate.date), text(candidate.country), text(candidate.format)]
                     .filter(function(v) { return v !== ""; });
        var discs = Number(candidate.discs || 0), tracks = Number(candidate.trackCount || 0);
        if (discs > 0) detail.push(discs + " " + (discs === 1 ? "disc" : "discs"));
        if (tracks > 0) detail.push(tracks + " tracks");
        if (detail.length) bits.push(detail.join(" · "));
        return bits.join(" — ");
    }
    function releaseDateText() {
        var first = text(album.firstReleaseDate), release = text(album.releaseDate);
        if (first !== "" && release !== "" && first !== release)
            return "original " + first + " · this release " + release;
        return first !== "" ? "original " + first : release !== "" ? "release " + release : "";
    }
    function mediaText(media) {
        var result = text(media.format), discs = album.media ? album.media.length : 0;
        var tracks = Number(media.trackCount || 0);
        if (discs > 1) result += (result ? " · " : "") + discs + " discs";
        if (tracks > 0) result += (result ? " · " : "") + tracks + " tracks";
        return result;
    }
    function infoStateText() {
        var err = text(info.albumError || info.error);
        if (info.status === "loading") return "loading release information...";
        if (info.status === "ambiguous") return "choose the correct release";
        if (info.status === "no_match") return "no release match found";
        if (err !== "") return "release fetch failed: " + err;
        if (info.stale) return "cached release information · refresh available";
        return album.sources && album.sources.length ? "sources: " + album.sources.join(" · ") : "";
    }

    Rectangle {
        anchors.fill: parent
        color: Qt.darker(Theme.bgAlt, 1.08)
        border.width: Theme.ctrlBorder; border.color: Theme.border
        radius: Math.max(2, Theme.rounding); clip: true
    }
    Rectangle {
        id: tabBar
        objectName: "tabBar"
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: root.actionsInline || root.tab === "lyrics"
                ? root.tabBaseHeight : root.tabBaseHeight + actions.height + 3
        color: "transparent"
        border.width: Theme.ctrlBorder; border.color: Theme.border; clip: true
        StyledBackground { anchors.fill: parent }
    }
    Row {
        id: tabs
        x: 4; y: root.actionsInline || root.tab === "lyrics"
              ? Math.round((tabBar.height - height) / 2) : 2; spacing: 1
        Repeater {
            model: ["lyrics", "album", "similar"]
            HeaderButton {
                required property string modelData
                label: modelData; lit: root.tab === modelData; depressed: true
                onClicked: root.tab = modelData
            }
        }
    }
    Row {
        id: actions
        objectName: "actions"
        anchors.right: parent.right; anchors.rightMargin: 4
        y: root.actionsInline ? Math.round((tabBar.height - height) / 2)
                              : root.tabBaseHeight + 2
        spacing: 1; visible: root.tab !== "lyrics"
        HeaderButton {
            label: "refresh"; plainLabel: "refresh"; iconName: "view-refresh"; iconOnly: true
            onClicked: {
                var accepted = Library.refreshNowInfo();
                root.actionError = accepted === false ? "refresh refused" : "";
            }
        }
        HeaderButton {
            label: "change match"; plainLabel: "change match"; iconName: "edit-find-replace"; iconOnly: true
            onClicked: candidates.visible = !candidates.visible
        }
        HeaderButton {
            label: "edit"; plainLabel: "edit"; iconName: "document-edit"; iconOnly: true
            visible: root.tab === "album"
            onClicked: {
                editTitle.text = root.text(root.album.title);
                editArtist.text = root.text(root.album.artist);
                editDescription.text = root.text(root.album.description);
                root.actionError = ""; root.editing = true;
            }
        }
    }

    Item {
        id: body
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom
                  top: tabBar.bottom; margins: Theme.ctrlBorder }
        LyricsView {
            anchors.fill: parent; visible: root.tab === "lyrics"; active: visible
            trackId: root.trackId
            fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
        }

        Item {
            id: albumView
            anchors.fill: parent; visible: root.tab === "album" && !root.editing
            PixelText {
                id: albumState
                x: 8; y: 6; width: Math.max(0, parent.width - 16)
                color: root.actionError !== "" || root.info.status === "error"
                       || root.info.albumError || root.info.error ? Theme.crit : root.fgDim
                text: root.actionError !== "" ? root.actionError : root.infoStateText()
                elide: Text.ElideRight
            }
            KineticFlickable {
                id: albumFlick
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom
                          top: albumState.bottom; margins: 8; topMargin: 6 }
                contentWidth: width; contentHeight: albumColumn.height; clip: true
                ScrollBar.vertical: VScroll { id: albumScroll }
                Column {
                    id: albumColumn
                    width: Math.max(0, albumFlick.width - albumScroll.barW); spacing: 5
                    PixelText { width: parent.width; color: root.fgText; wrapMode: Text.Wrap
                        text: root.text(root.album.title || root.track.album) }
                    PixelText { width: parent.width; color: root.fgDim; wrapMode: Text.Wrap
                        text: root.text(root.album.artist || root.track.artist) }
                    Repeater {
                        model: root.tab === "album" ? (root.album.labels || []) : []
                        delegate: Row {
                            required property var modelData; spacing: 4
                            PixelText { color: root.fgDim; text: "label" }
                            HeaderButton {
                                label: root.text(modelData.name) + (modelData.catalogNumber ? "  " + modelData.catalogNumber : "")
                                plainLabel: label; iconName: "go-next"
                                enabled: !!modelData.id
                                onClicked: root.browse("label", modelData)
                            }
                            HeaderButton {
                                visible: root.validUrl(modelData.url)
                                label: "source"; plainLabel: "source"; iconName: "external-link"
                                onClicked: root.openUrl(modelData.url)
                            }
                        }
                    }
                    PixelText { width: parent.width; color: root.fgDim; wrapMode: Text.Wrap
                        visible: root.album.country || root.album.barcode
                        text: [root.text(root.album.country), root.album.barcode ? "barcode " + root.album.barcode : ""]
                              .filter(function(v) { return v !== ""; }).join(" · ") }
                    PixelText { width: parent.width; color: root.fgText; wrapMode: Text.Wrap
                        visible: !!root.album.description; text: root.text(root.album.description) }
                    HeaderButton {
                        visible: root.validUrl(root.album.descriptionUrl)
                        label: "open description source"; plainLabel: "open description source"; iconName: "external-link"
                        onClicked: root.openUrl(root.album.descriptionUrl)
                    }
                    PixelText { width: parent.width; color: root.fgDim; wrapMode: Text.Wrap
                        visible: root.releaseDateText() !== ""; text: root.releaseDateText() }
                    Repeater {
                        model: root.tab === "album" ? (root.album.media || []) : []
                        delegate: PixelText {
                            required property var modelData; width: albumColumn.width; color: root.fgDim
                            text: "format " + root.mediaText(modelData)
                        }
                    }
                    PixelText {
                        width: parent.width; color: root.fgText
                        visible: (root.album.credits || []).some(function(c) { return c.scope === "album"; })
                        text: "album credits"
                    }
                    Repeater {
                        model: root.tab === "album" ? root.releaseCredits : []
                        delegate: Item {
                            required property var modelData
                            objectName: "releaseCreditRow"
                            readonly property bool albumScope: modelData.scope === "album"
                            width: albumColumn.width; height: albumScope ? Theme.lineHeight + 2 : 0; visible: albumScope
                            PixelText {
                                anchors { left: parent.left; right: creditAction.left; verticalCenter: parent.verticalCenter }
                                color: root.fgDim; elide: Text.ElideRight
                                text: root.text(modelData.role) + "  " + root.text(modelData.name)
                            }
                            HeaderButton {
                                id: creditAction
                                anchors.right: creditSource.left; anchors.rightMargin: 2
                                anchors.verticalCenter: parent.verticalCenter
                                label: "open"; plainLabel: "open"; iconName: "go-next"
                                visible: !!modelData.id
                                onClicked: root.browse("artist", modelData)
                            }
                            HeaderButton {
                                id: creditSource
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                visible: root.validUrl(modelData.url)
                                label: "source"; plainLabel: "source"; iconName: "external-link"
                                onClicked: root.openUrl(modelData.url)
                            }
                        }
                    }
                    PixelText {
                        width: parent.width; color: root.fgText
                        visible: (root.album.credits || []).some(function(c) { return c.scope === "track"; })
                        text: "track credits"
                    }
                    Repeater {
                        model: root.tab === "album" ? root.trackCredits : []
                        delegate: Item {
                            required property var modelData
                            objectName: "trackCreditRow"
                            readonly property bool trackScope: modelData.scope === "track"
                            width: albumColumn.width; height: trackScope ? Theme.lineHeight + 2 : 0; visible: trackScope
                            PixelText {
                                anchors { left: parent.left; right: trackCreditAction.left; verticalCenter: parent.verticalCenter }
                                color: root.fgDim; elide: Text.ElideRight
                                text: (modelData.disc ? "disc " + root.text(modelData.disc) + " · " : "")
                                      + root.text(modelData.trackTitle || (modelData.trackPosition ? "track " + modelData.trackPosition : "track"))
                                      + "  " + root.text(modelData.role) + "  " + root.text(modelData.name)
                            }
                            HeaderButton {
                                id: trackCreditAction
                                anchors.right: trackCreditSource.left; anchors.rightMargin: 2
                                anchors.verticalCenter: parent.verticalCenter
                                label: "open"; plainLabel: "open"; iconName: "go-next"
                                visible: !!modelData.id
                                onClicked: root.browse("artist", modelData)
                            }
                            HeaderButton {
                                id: trackCreditSource
                                anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                                visible: root.validUrl(modelData.url)
                                label: "source"; plainLabel: "source"; iconName: "external-link"
                                onClicked: root.openUrl(modelData.url)
                            }
                        }
                    }
                    PixelText { width: parent.width; color: root.fgDim; visible: !!root.album.url; text: "release source" }
                    HeaderButton {
                        visible: root.validUrl(root.album.url)
                        label: "open source"; plainLabel: "open source"; iconName: "external-link"
                        onClicked: root.openUrl(root.album.url)
                    }
                    // The artist stands on its own: this section is filled
                    // even when the release above could not be identified.
                    PixelText { width: parent.width; color: root.fgDim
                        visible: !!root.artist.id; text: "artist" }
                    PixelText { width: parent.width; color: root.fgText; wrapMode: Text.Wrap
                        visible: !!root.artist.id; text: root.artistHeading() }
                    PixelText { width: parent.width; color: root.fgDim; wrapMode: Text.Wrap
                        visible: root.artistFacts() !== ""; text: root.artistFacts() }
                    PixelText { width: parent.width; color: root.fgText; wrapMode: Text.Wrap
                        visible: !!root.artist.description; text: root.text(root.artist.description) }
                    Row {
                        spacing: 2
                        visible: root.validUrl(root.artist.url) || root.validUrl(root.artist.descriptionUrl)
                        HeaderButton {
                            visible: root.validUrl(root.artist.url)
                            label: "open artist"; plainLabel: "open artist"; iconName: "external-link"
                            onClicked: root.openUrl(root.artist.url)
                        }
                        HeaderButton {
                            visible: root.validUrl(root.artist.descriptionUrl)
                            label: "open biography source"; plainLabel: "open biography source"
                            iconName: "external-link"
                            onClicked: root.openUrl(root.artist.descriptionUrl)
                        }
                    }
                    PixelText { width: parent.width; color: root.fgDim; wrapMode: Text.Wrap
                        visible: root.track.title !== undefined
                        text: "track: " + root.text(root.track.title) + " · " + Math.round(Number(root.track.duration || 0) / 60) + " min · " + Number(root.track.playCount || 0) + " plays" }
                    Repeater {
                        model: root.albumTracks
                        delegate: PixelText {
                            required property var modelData; width: albumColumn.width
                            color: modelData.trackId === root.trackId
                                   || (modelData.recordingId && modelData.recordingId === root.info.recordingId)
                                   ? root.fgAccent : root.fgDim; elide: Text.ElideRight
                            text: (modelData.disc ? "disc " + root.text(modelData.disc) + " · " : "")
                                  + (modelData.position || modelData.track || (index + 1)) + "  " + root.text(modelData.title)
                        }
                    }
                    Row {
                        spacing: 2
                        HeaderButton { label: "revert edits"; plainLabel: "revert edits"; iconName: "edit-undo"
                            onClicked: {
                                if (Library.revertNowInfo("album") !== true) root.actionError = "revert refused";
                                else root.actionError = "";
                            } }
                        HeaderButton { label: "clear cache (edits kept)"; plainLabel: "clear cache (edits kept)"; iconName: "edit-clear"
                            onClicked: {
                                var accepted = Library.clearNowInfo();
                                if (accepted === false) root.actionError = "clear cache refused";
                                else root.actionError = "";
                            } }
                    }
                }
            }
        }

        KineticListView {
            id: relatedList
            anchors.fill: parent; anchors.margins: 6; visible: root.tab === "similar"; clip: true
            model: root.relatedRows
            ScrollBar.vertical: VScroll { id: relatedScroll }
            header: PixelText {
                width: Math.max(0, relatedList.width - relatedScroll.barW); height: Theme.lineHeight + 6
                color: root.actionError !== "" || (root.info.similarError && !root.info.connectionEmpty)
                       ? Theme.crit : root.fgDim
                text: root.actionError !== "" ? root.actionError
                    : root.info.status === "loading" ? "loading related music..."
                    : root.info.connectionEmpty ? "no related music in your library"
                    : root.info.similarError ? "related music failed"
                    : root.relatedRows.length ? "owned tracks and discoveries" : "no related music"
            }
            delegate: Item {
                required property var modelData
                width: Math.max(0, relatedList.width - relatedScroll.barW)
                height: modelData.section ? Theme.lineHeight + 6 : Theme.lineHeight + 10
                PixelText {
                    visible: modelData.section; anchors.verticalCenter: parent.verticalCenter
                    color: root.fgDim; text: modelData.section ? modelData.title : ""
                }
                PixelText {
                    visible: !modelData.section
                    anchors { left: parent.left; right: relatedAction.left; verticalCenter: parent.verticalCenter }
                    anchors.leftMargin: 5; color: root.fgText; elide: Text.ElideRight
                    text: root.text(modelData.title) + "  " + root.text(modelData.artist) + (modelData.album ? "  ·  " + root.text(modelData.album) : "")
                }
                HeaderButton {
                    id: relatedAction
                    anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                    label: root.isOwned(modelData) ? "play" : "open"; plainLabel: label
                    iconName: root.isOwned(modelData) ? "media-playback-start" : "external-link"
                    enabled: root.isOwned(modelData) ? Number(modelData.trackId || 0) > 0 : root.validUrl(modelData.url)
                    visible: !modelData.section
                    onClicked: {
                        if (root.isOwned(modelData)) Player.playTracks([Number(modelData.trackId)], 0);
                        else root.openUrl(modelData.url);
                    }
                }
                PixelText {
                    visible: !modelData.section && !!modelData.reason
                    anchors { left: parent.left; right: relatedAction.left; bottom: parent.bottom }
                    anchors.leftMargin: 5; color: root.fgDim; text: root.text(modelData.reason); elide: Text.ElideRight
                }
                MouseArea {
                    anchors.fill: parent
                    enabled: !modelData.section && root.isOwned(modelData) && Number(modelData.trackId || 0) > 0
                    cursorShape: Qt.PointingHandCursor
                    onDoubleClicked: Player.playTracks([Number(modelData.trackId)], 0)
                }
            }
        }
    }

    Rectangle {
        id: candidates
        visible: false; z: 20
        anchors { left: parent.left; right: parent.right; top: tabBar.bottom; bottom: parent.bottom }
        color: Theme.bgAlt; border.width: Theme.ctrlBorder; border.color: Theme.border
        KineticListView {
            id: candidateList
            anchors.fill: parent; anchors.margins: 5; clip: true
            model: root.info.candidates || []
            ScrollBar.vertical: VScroll { id: candidateScroll }
            header: PixelText {
                width: Math.max(0, candidateList.width - candidateScroll.barW); height: Theme.lineHeight + 5
                color: root.fgDim; text: "choose a release"
            }
            delegate: Item {
                required property var modelData
                width: Math.max(0, candidateList.width - candidateScroll.barW); height: Theme.lineHeight + 8
                HeaderButton {
                    anchors.fill: parent; label: root.candidateLabel(modelData); plainLabel: label
                    enabled: !!modelData.id
                    onClicked: {
                        var accepted = Library.chooseNowInfoMatch(modelData.id);
                        if (accepted === true) { candidates.visible = false; root.actionError = ""; }
                        else root.actionError = "match choice refused";
                    }
                }
            }
        }
    }

    Rectangle {
        visible: root.editing; z: 30; anchors.fill: parent
        color: Theme.bgAlt; border.width: Theme.ctrlBorder; border.color: Theme.border
        Column {
            anchors.fill: parent; anchors.margins: 8; spacing: 5
            TextField { id: editTitle; width: parent.width; font: Theme.editorFont; placeholderText: "album title" }
            TextField { id: editArtist; width: parent.width; font: Theme.editorFont; placeholderText: "artist" }
            TextArea { id: editDescription; width: parent.width; font: Theme.editorFont
                height: Math.max(60, parent.height - editTitle.height - editArtist.height - editButtons.height - 25)
                placeholderText: "description"; wrapMode: TextEdit.Wrap }
            Row {
                id: editButtons; spacing: 3
                HeaderButton { label: "save"; plainLabel: "save"; iconName: "document-save"
                    onClicked: {
                        var accepted = Library.editNowInfo("album", { title: editTitle.text, artist: editArtist.text, description: editDescription.text });
                        if (accepted === true) { root.editing = false; root.actionError = ""; }
                        else root.actionError = "save refused";
                    } }
                HeaderButton { label: "cancel"; plainLabel: "cancel"; iconName: "dialog-cancel"; onClicked: root.editing = false }
            }
        }
    }
}
