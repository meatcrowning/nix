import QtQuick
import QtQuick.Controls.Basic
import "../../qmlcommon"

// Smart playlists: the user's own lists down the left, the selected list's
// tracks on the right. A list is a set of RULES (main.py's SMART_FIELDS /
// SMART_OPS), never a stored membership — opening one re-queries the library,
// so it is live by construction and a track rated just now is in it.
//
// The seven built-ins are only the seed of the user's file: right-click any
// list to edit, duplicate or delete it, "+ new" writes one from scratch, and
// "restore defaults" puts back the built-ins that were deleted (docs/DESIGN.md
// §7.1 — everything selectable is right-clickable).
Item {
    id: root
    property string current: ""
    // Foreground tones, handed in already faded by Main (docs/DESIGN.md §3.1.1).
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent
    // From the track list's right-click menu; the window owns navigation.
    signal openAlbumRequested(int albumId)
    signal browseArtistRequested(string artist)

    // The rule editor is a modal with text fields in it, so the window's global
    // Space (play/pause) and Escape must stand down while it is up — otherwise
    // a space typed into a playlist name pauses the music instead. Gated on
    // THIS view being visible too: switching to the gallery with the editor
    // open must give Space back.
    readonly property bool modal: visible && editor.visible
    function closeModal() { editor.cancel(); }

    onVisibleChanged: {
        if (visible && current === "") {
            // Which list was open is view state the user would notice
            // reverting (docs/DESIGN.md §14), so it outlives the process — and
            // it is checked against the store, since the list it names can have
            // been deleted (here or on the other machine) since it was written.
            var want = String(Prefs.get("smartList", ""));
            var l = Library.smartLists;
            for (var i = 0; i < l.length; i++)
                if (l[i].name === want) { select(want); return; }
            if (l.length > 0) select(l[0].name);
        } else if (visible && current !== "") {
            Library.refreshSmart();   // refresh in place — keeps the scroll spot
        }
    }

    function select(name) {
        current = name;
        if (name !== "")
            Prefs.set("smartList", name);
        Library.openSmart(name);
    }

    // A list can vanish (deleted) or be renamed under the selection, and the
    // sidebar is the only thing that knows what to land on next.
    function reselect(name) {
        var l = Library.smartLists;
        for (var i = 0; i < l.length; i++)
            if (l[i].name === name) { select(name); return; }
        select(l.length > 0 ? l[0].name : "");
    }

    Connections {
        target: Library
        function onSmartListsChanged() {
            if (root.current !== "")
                root.reselect(root.current);
        }
    }

    Item {
        id: side
        width: 190
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.left: parent.left

        KineticListView {
            id: sideList
            anchors.fill: parent
            anchors.topMargin: 10
            clip: true
            spacing: 2
            model: Library.smartLists
            ScrollBar.vertical: VScroll { visible: sideList.contentHeight > sideList.height }

            delegate: Rectangle {
                id: listRow
                required property var modelData
                width: side.width
                height: 20
                color: nameMouse.containsMouse || modelData.name === root.current
                       ? Theme.highlight : "transparent"
                PixelText {
                    x: 10
                    width: parent.width - 20
                    anchors.verticalCenter: parent.verticalCenter
                    elide: Text.ElideRight
                    text: listRow.modelData.name
                    color: listRow.modelData.name === root.current ? root.fgAccent
                           : (nameMouse.containsMouse ? root.fgText : root.fgDim)
                }
                MouseArea {
                    cursorShape: Qt.PointingHandCursor
                    id: nameMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onClicked: function (mouse) {
                        if (mouse.button === Qt.RightButton) {
                            var p = mapToItem(root, mouse.x, mouse.y);
                            root.openListMenu(p.x, p.y, listRow.modelData.name);
                        } else {
                            root.select(listRow.modelData.name);
                        }
                    }
                }
            }

            // "+ new" rides with the lists rather than sitting under a fixed
            // divider: with enough lists to scroll, a pinned button would cover
            // the last row.
            footer: Item {
                width: side.width
                height: 30
                HeaderButton {
                    x: 6
                    anchors.verticalCenter: parent.verticalCenter
                    label: "+ new"
                    plainLabel: "new"; iconName: "list-add"
                    fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                    onClicked: editor.createNew()
                }
            }
        }

        // Right-click on the empty part of the sidebar: the only place
        // "restore defaults" belongs, since it is about the set of lists and
        // not about any one of them.
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.RightButton
            z: -1
            onClicked: function (mouse) {
                var p = mapToItem(root, mouse.x, mouse.y);
                listMenu.open(p.x, p.y, [
                    { label: "new playlist", trigger: function () { editor.createNew(); } },
                    { label: "restore built-in playlists",
                      trigger: function () { root.restoreDefaults(); } }
                ]);
            }
        }
    }

    Rectangle {
        anchors.left: side.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 1
        color: Theme.border
    }

    Item {
        anchors.left: side.right
        anchors.leftMargin: 1
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.bottom: parent.bottom

        Row {
            id: listHead
            x: 8
            y: 8
            spacing: 12
            PixelText {
                anchors.verticalCenter: parent.verticalCenter
                text: root.current + "  (" + PlaylistModel.count + ")"
                color: root.fgDim
            }
            HeaderButton {
                label: "> play all"
                plainLabel: "play all"; iconName: "media-playback-start"
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                onClicked: Player.playSmart(root.current)
            }
            HeaderButton {
                label: "edit rules"
                iconName: "document-edit"
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                onClicked: editor.edit(root.current)
            }
        }
        TrackList {
            anchors.top: listHead.bottom
            anchors.topMargin: 4
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            model: PlaylistModel
            fgText: root.fgText
            fgDim: root.fgDim
            fgAccent: root.fgAccent
            showNumber: false
            onPlayed: function(index) { Library.playFromModel(PlaylistModel, index); }
            onOpenAlbumRequested: function(aid) { root.openAlbumRequested(aid); }
            onBrowseArtistRequested: function(a) { root.browseArtistRequested(a); }
        }

        PixelText {
            anchors.centerIn: parent
            visible: PlaylistModel.count === 0 && root.current !== ""
            text: "no tracks match these rules"
            color: Theme.dim
        }
    }

    // §7.2's ordering: the play action first, the edits next, and the one
    // destructive entry LAST behind a separator so the pointer never lands on
    // it. Deleting is two deliberate acts anyway (§10.3) — open the menu, then
    // choose it — and a deleted list is rules, not tracks: "restore built-in
    // playlists" brings a built-in straight back.
    function openListMenu(x, y, name) {
        listMenu.open(x, y, [
            { label: "play all", trigger: function () { Player.playSmart(name); } },
            { separator: true },
            { label: "edit rules", trigger: function () { editor.edit(name); } },
            { label: "duplicate", trigger: function () {
                  var made = Library.duplicateSmart(name);
                  if (made !== "") root.select(made);
              } },
            { label: "new playlist", trigger: function () { editor.createNew(); } },
            { separator: true },
            { label: "delete", trigger: function () {
                  Library.deleteSmart(name);
                  root.reselect(root.current === name ? "" : root.current);
              } }
        ]);
    }

    function restoreDefaults() {
        var n = Library.restoreSmartDefaults();
        // §10.2: refuse visibly. Nothing to restore has to SAY nothing was
        // missing, or the menu entry reads as a control that did nothing.
        notice.show(n > 0 ? (n === 1 ? "1 playlist restored" : n + " playlists restored")
                          : "all built-in playlists are already here");
    }

    CtxMenu { id: listMenu; anchors.fill: parent }

    SmartEditor {
        id: editor
        objectName: "smartEditor"      // tools/smartlist-ui-test.py drives it
        anchors.fill: parent
        z: 80
        fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
        onSaved: function (name) { root.select(name); }
    }

    // A one-line status line in the corner, in the same spot and tone the scan
    // status uses — this view has no toast of its own and does not want one.
    Rectangle {
        id: notice
        function show(t) { text = t; opacity = 1; hide.restart(); }
        property string text: ""
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 8
        width: noticeText.implicitWidth + 12
        height: noticeText.implicitHeight + 8
        color: Theme.bgAlt
        radius: Theme.rounding
        border.width: Theme.ctrlBorder
        border.color: Theme.border
        opacity: 0
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: motion.ms(motion.slideMs) } }
        Timer { id: hide; interval: 2600; onTriggered: notice.opacity = 0 }
        PixelText {
            id: noticeText
            anchors.centerIn: parent
            text: notice.text
            color: root.fgDim
        }
    }

    Motion { id: motion }
}
