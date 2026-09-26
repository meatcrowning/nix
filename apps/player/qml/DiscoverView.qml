import QtQuick
import QtQuick.Controls
import "../../qmlcommon"

Item {
    id: root
    Glyphs { id: glyphs }
    property Item overlayParent: root
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent
    property string expanded: ""
    property string filter: "all"
    property bool showSettings: false
    readonly property var backend: typeof Discovery !== "undefined" ? Discovery : null
    readonly property var settings: backend ? backend.settings : ({})
    readonly property var entries: {
        var items = backend ? backend.items : [];
        return items.filter(function(r) {
            if (root.filter === "saved") return r.saved;
            if (root.filter === "review") return r.status === "review";
            if (root.filter === "new") return !r.known;
            if (root.filter === "known") return r.known;
            if (root.filter === "recent") return Date.parse(r.date) > Date.now() - 365 * 86400000;
            return true;
        });
    }
    function activate() { if (visible && backend) backend.activate(); }
    onVisibleChanged: activate()
    Component.onCompleted: activate()
    function menuAt(x, y, items) {
        var p = menu.mapFromItem(null, x, y);
        menu.open(p.x, p.y, items);
    }
    function releaseActions(r) {
        return [
            {label: "Preview clips", enabled: !backend.busy, trigger: function() { root.expanded = r.key; backend.preview(r.key, -1); }},
            {label: r.albumId ? "Play" : "Get release", enabled: !backend.busy && (r.albumId > 0 || (backend.canAcquire && (r.status === "" || r.status === "review"))), trigger: function() { if (r.albumId) Player.playAlbum(r.albumId, 0); else backend.acquire(r.key); }},
            {label: r.saved ? "Remove from saved" : "Save for later", trigger: function() { backend.feedback(r.key, "saved"); }},
            {label: "More like this", trigger: function() { backend.feedback(r.key, "liked"); }},
            {label: "Listen on Apple Music", trigger: function() { backend.openSource(r.url); }},
            {label: "Dismiss", trigger: function() { backend.feedback(r.key, "dismissed"); }}
        ];
    }
    CtxMenu { id: menu; parent: root.overlayParent; anchors.fill: parent }

    // Local wrappers keep every discovery action's tooltip and foreground API together.
    component Action: HeaderButton {
        fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
        HoverHandler { id: hover }
        ToolTip.visible: hover.hovered
        ToolTip.text: plainLabel || label
        ToolTip.delay: 350
    }
    component Choice: SelectButton {
        fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
        onPicked: (x, y, items) => root.menuAt(x, y, items)
    }

    Column {
        id: controls
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 8 }
        spacing: 6
        Flow {
            width: parent.width; spacing: 6
            Choice {
                width: Math.min(190, controls.width)
                label: ({all: "New to you", new: "New artists", known: "Familiar artists", recent: "Recent releases", saved: "Saved", review: "Review queue"})[root.filter]
                options: [{label:"New to you", value:"all"}, {label:"New artists", value:"new"},
                          {label:"Familiar artists", value:"known"}, {label:"Recent releases", value:"recent"},
                          {label:"Saved", value:"saved"}, {label:"Review queue", value:"review"}]
                onChose: value => root.filter = value
            }
            Action { label: "refresh"; plainLabel: "Refresh"; iconName: "view-refresh"; enabled: backend && !backend.busy; onClicked: backend.refresh() }
            Action { label: "settings"; plainLabel: "Settings"; iconName: "configure"; lit: root.showSettings; onClicked: root.showSettings = !root.showSettings }
        }
        Column {
            visible: root.showSettings
            width: parent.width; spacing: 6
            Flow {
                width: parent.width; spacing: 6
                Choice {
                    width: Math.min(190, controls.width)
                    label: ({manual:"Manual acquisition", review:"Review before acquiring", automatic:"Automatic acquisition"})[root.settings.mode || "manual"]
                    options: [{label:"Manual acquisition", value:"manual"}, {label:"Review before acquiring", value:"review"}, {label:"Automatic acquisition", value:"automatic"}]
                    onChose: value => backend.configure("mode", value)
                }
                Choice {
                    width: Math.min(150, controls.width)
                    label: ({lossless:"Lossless only", high:"256 kbps or better", any:"Any quality"})[root.settings.quality || "lossless"]
                    options: [{label:"Lossless only", value:"lossless"}, {label:"256 kbps or better", value:"high"}, {label:"Any quality", value:"any"}]
                    onChose: value => backend.configure("quality", value)
                }
                Choice {
                    width: Math.min(150, controls.width)
                    label: (root.settings.weekly || 2) + " albums / week"
                    options: [{label:"1 album / week", value:1}, {label:"2 albums / week", value:2}, {label:"5 albums / week", value:5}, {label:"10 albums / week", value:10}]
                    onChose: value => backend.configure("weekly", value)
                }
                Choice {
                    width: Math.min(150, controls.width)
                    label: (root.settings.budget || 2) + " GiB / week"
                    options: [{label:"1 GiB / week", value:1}, {label:"2 GiB / week", value:2}, {label:"5 GiB / week", value:5}, {label:"10 GiB / week", value:10}]
                    onChose: value => backend.configure("budget", value)
                }
                Action { label: "restore dismissed"; plainLabel: "Restore dismissed"; onClicked: backend.feedback("", "undo") }
            }
            PixelText {
                width: parent.width; wrapMode: Text.Wrap
                color: root.fgDim
                text: "Acquisition uses Soulseek on top while Player is open. Select Manual to pause new automatic requests. Limits cover the last seven days."
            }
        }
        Flow {
            visible: Player.previewing === true
            width: parent.width; spacing: 6
            Action { label: "end preview"; plainLabel: "End preview"; iconName: "media-playback-stop"; onClicked: Player.endPreview() }
            PixelText { width: parent.width; wrapMode: Text.Wrap; text: "Apple Music preview clips · " + Player.previewLabel; color: root.fgAccent }
        }
        PixelText {
            width: parent.width; wrapMode: Text.Wrap; color: root.fgDim
            visible: text !== ""
            text: backend ? (backend.busy ? "Working…" : backend.message) : "Discovery unavailable"
        }
    }

    KineticListView {
        id: list
        objectName: "discoveryList"
        anchors { left: parent.left; right: parent.right; top: controls.bottom; bottom: parent.bottom; margins: 8 }
        clip: true; spacing: 12
        onModelChanged: {
            const previousY = contentY;
            Qt.callLater(function() { list.contentY = Math.max(list.originY, Math.min(previousY, list.originY + Math.max(0, list.contentHeight - list.height))); });
        }
        model: root.entries
        ScrollBar.vertical: VScroll { visible: list.contentHeight > list.height }
        delegate: Column {
            id: card
            required property var modelData
            width: list.width - 12
            spacing: 6
            readonly property bool opened: root.expanded === modelData.key
            Row {
                width: parent.width; spacing: 8
                Image {
                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.RightButton
                    onClicked: function(mouse) {
                        const p = mapToItem(null, mouse.x, mouse.y);
                        root.menuAt(p.x, p.y, root.releaseActions(card.modelData));
                    }
                }
                    width: Math.min(72, card.width * .22); height: width
                    source: card.modelData.art; asynchronous: true; fillMode: Image.PreserveAspectFit
                    Rectangle { anchors.fill: parent; color: Theme.bgAlt; visible: parent.status !== Image.Ready }
                }
                Column {
                    width: parent.width - Math.min(72, card.width * .22) - 8; spacing: 3
                    PixelText { width: parent.width; wrapMode: Text.Wrap; text: glyphs.px(card.modelData.album); color: root.fgText }
                    PixelText { width: parent.width; wrapMode: Text.Wrap; text: glyphs.px(card.modelData.artist); color: root.fgAccent }
                    PixelText { text: card.modelData.kind + " · " + card.modelData.year; color: root.fgDim }
                }
            }
            PixelText { width: parent.width; wrapMode: Text.Wrap; text: glyphs.px(card.modelData.reason); color: root.fgDim }
            Flow {
                width: parent.width; spacing: 6
                Action {
                    label: "preview"; plainLabel: "Preview clips"; iconName: "media-playback-start"
                    enabled: !backend.busy
                    onClicked: { root.expanded = card.modelData.key; backend.preview(card.modelData.key, -1); }
                }
                Action {
                    label: card.opened ? "hide tracks" : "tracks"; plainLabel: card.opened ? "Hide tracks" : "Tracks"
                    enabled: !backend.busy
                    onClicked: { var opening = !card.opened; root.expanded = opening ? card.modelData.key : ""; if (opening) backend.expand(card.modelData.key); }
                }
                Action {
                    label: card.modelData.albumId ? "play" : "get"; plainLabel: card.modelData.albumId ? "Play" : "Get release"; iconName: "download"
                    enabled: !backend.busy && (card.modelData.albumId > 0 || (backend.canAcquire && (card.modelData.status === "" || card.modelData.status === "review")))
                    onClicked: { if (card.modelData.albumId) Player.playAlbum(card.modelData.albumId, 0); else backend.acquire(card.modelData.key); }
                }
                Action { label: card.modelData.saved ? "saved" : "save"; plainLabel: card.modelData.saved ? "Saved" : "Save for later"; lit: card.modelData.saved; onClicked: backend.feedback(card.modelData.key, "saved") }
                Action { label: "more like this"; plainLabel: "More like this"; lit: card.modelData.liked; onClicked: backend.feedback(card.modelData.key, "liked") }
                Action { label: "dismiss"; plainLabel: "Dismiss"; onClicked: backend.feedback(card.modelData.key, "dismissed") }
            }
            PixelText {
                width: parent.width; wrapMode: Text.Wrap; color: root.fgDim
                visible: text !== ""
                text: card.modelData.status + (card.modelData.detail ? " · " + card.modelData.detail : "")
            }
            Action { label: "Apple Music"; plainLabel: "Listen on Apple Music"; onClicked: backend.openSource(card.modelData.url) }
            Column {
                width: parent.width
                visible: card.opened
                spacing: 4
                Repeater {
                    model: card.opened ? card.modelData.tracks : []
                    delegate: Row {
                        required property var modelData
                        required property int index
                        width: card.width; spacing: 6
                        Action {
                            id: trackPreview
                            label: ">"; plainLabel: "Preview track"; iconName: "media-playback-start"; iconOnly: true
                            enabled: modelData.preview !== "" && !backend.busy
                            onClicked: backend.preview(card.modelData.key, index)
                        }
                        PixelText {
                            width: parent.width - trackPreview.width - 6; wrapMode: Text.Wrap; color: root.fgText
                            text: modelData.track + ". " + glyphs.px(modelData.title) + (modelData.preview ? "" : " — no preview available")
                        }
                    }
                }
                PixelText {
                    width: parent.width; wrapMode: Text.Wrap; color: root.fgDim
                    visible: card.modelData.tracks.length === 0 && !backend.busy
                    text: "No preview available. Try the source link."
                }
            }
        }
        PixelText {
            anchors { left: parent.left; right: parent.right; top: parent.top }
            visible: list.count === 0 && backend && !backend.busy
            wrapMode: Text.Wrap; color: root.fgDim
            text: "No recommendations in this view. Refresh to discover music, or choose another filter."
        }
    }
}
