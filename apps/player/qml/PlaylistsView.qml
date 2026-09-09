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
    readonly property bool plasma: (typeof DeskStyle !== "undefined" && DeskStyle)
                                   ? DeskStyle.plasma === true : false
    function raised(c, amount) {
        return Qt.rgba(c.r + (1 - c.r) * amount,
                       c.g + (1 - c.g) * amount,
                       c.b + (1 - c.b) * amount, c.a)
    }
    function sunken(c, amount) {
        return Qt.rgba(c.r * (1 - amount), c.g * (1 - amount),
                       c.b * (1 - amount), c.a)
    }
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
        width: root.plasma ? 178 : 190
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.left: parent.left

        // Plasma keeps Oxygen's window gradient visible around a raised,
        // scheme-derived sidebar. The pixel face remains completely flat.
        Rectangle {
            anchors.fill: parent
            anchors.leftMargin: root.plasma ? 8 : 0
            anchors.topMargin: root.plasma ? 8 : 0
            anchors.bottomMargin: root.plasma ? 8 : 0
            color: "transparent"
            radius: root.plasma ? Math.max(2, Theme.rounding) : 0
            border.width: root.plasma ? Theme.ctrlBorder : 0
            border.color: Theme.border
            clip: true
            StyledBackground {
                anchors.fill: parent
                visible: root.plasma
            }
        }

        KineticListView {
            id: sideList
            anchors.fill: parent
            anchors.leftMargin: root.plasma ? 9 : 0
            anchors.rightMargin: root.plasma ? 1 : 0
            anchors.topMargin: root.plasma ? 14 : 10
            anchors.bottomMargin: root.plasma ? 12 : 0
            clip: true
            spacing: 2
            model: Library.smartLists
            ScrollBar.vertical: VScroll { visible: sideList.contentHeight > sideList.height }

            delegate: Rectangle {
                id: listRow
                required property var modelData
                width: root.plasma ? sideList.width : side.width
                height: root.plasma ? Math.max(22, Theme.lineHeight + 7) : 20
                color: !root.plasma && (nameMouse.containsMouse || modelData.name === root.current)
                       ? Theme.highlight : "transparent"
                gradient: Gradient {
                    GradientStop {
                        position: 0
                        color: root.plasma && (nameMouse.containsMouse || modelData.name === root.current)
                               ? root.raised(Theme.highlight, modelData.name === root.current ? 0.28 : 0.12)
                               : "transparent"
                    }
                    GradientStop {
                        position: 0.55
                        color: root.plasma && (nameMouse.containsMouse || modelData.name === root.current)
                               ? Theme.highlight : "transparent"
                    }
                    GradientStop {
                        position: 1
                        color: root.plasma && (nameMouse.containsMouse || modelData.name === root.current)
                               ? root.sunken(Theme.highlight, 0.22) : "transparent"
                    }
                }
                Rectangle {
                    visible: root.plasma && listRow.modelData.name === root.current
                    anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                    height: 1; color: root.raised(Theme.accent, 0.35)
                }
                Rectangle {
                    visible: root.plasma && listRow.modelData.name === root.current
                    anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                    height: 1; color: root.sunken(Theme.accent, 0.36)
                }
                PixelText {
                    x: root.plasma ? 9 : 10
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
                    x: root.plasma ? 7 : 6
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
        color: root.plasma ? "transparent" : Theme.border
    }

    Item {
        id: content
        anchors.left: side.right
        anchors.leftMargin: 1
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.bottom: parent.bottom

        Rectangle {
            id: listHead
            x: root.plasma ? 0 : 8
            y: root.plasma ? 8 : 8
            width: parent.width - x
            height: root.plasma ? Math.max(34, headRow.implicitHeight + 10) : headRow.implicitHeight
            color: "transparent"
            radius: root.plasma ? Math.max(2, Theme.rounding) : 0
            border.width: root.plasma ? Theme.ctrlBorder : 0
            border.color: Theme.border
            clip: true
            StyledBackground {
                anchors.fill: parent
                visible: root.plasma
            }
            Row {
                id: headRow
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: root.plasma ? 9 : 0
                anchors.rightMargin: root.plasma ? 7 : 0
                spacing: root.plasma ? 6 : 12
                PixelText {
                    width: root.plasma ? Math.max(0, parent.width - playAll.width - editRules.width - parent.spacing * 2) : implicitWidth
                    anchors.verticalCenter: parent.verticalCenter
                    elide: Text.ElideRight
                    text: root.current + "  (" + PlaylistModel.count + ")"
                    color: root.plasma ? root.fgText : root.fgDim
                }
                HeaderButton {
                    id: playAll
                    label: "> play all"
                    plainLabel: "play all"; iconName: "media-playback-start"
                    fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                    onClicked: Player.playSmart(root.current)
                }
                HeaderButton {
                    id: editRules
                    label: "edit rules"
                    plainLabel: "edit"; iconName: "document-edit"
                    fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                    onClicked: editor.edit(root.current)
                }
            }
        }
        Rectangle {
            id: trackWell
            anchors.top: listHead.bottom
            anchors.topMargin: root.plasma ? 0 : 4
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.rightMargin: root.plasma ? 8 : 0
            anchors.bottomMargin: root.plasma ? 8 : 0
            color: root.plasma ? root.sunken(Theme.bgAlt, 0.18) : "transparent"
            radius: root.plasma ? Math.max(2, Theme.rounding) : 0
            border.width: root.plasma ? Theme.ctrlBorder : 0
            border.color: Theme.border
        }
        TrackList {
            anchors.fill: trackWell
            anchors.margins: root.plasma ? Theme.ctrlBorder : 0
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
