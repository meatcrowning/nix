import QtQuick

// Smart playlists: the registry names down the left (5 starred, favourites,
// recently added, most played, …), the selected list's tracks on the right.
// Lists are SQL in main.py (SMART_PLAYLISTS) — adding one there is enough.
Item {
    id: root
    property string current: ""

    onVisibleChanged: {
        if (visible && current === "") {
            var names = Library.smartNames();
            if (names.length > 0) select(names[0]);
        } else if (visible && current !== "") {
            Library.openSmart(current);   // refresh — counts may have moved
        }
    }

    function select(name) {
        current = name;
        Library.openSmart(name);
    }

    Item {
        id: side
        width: 190
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.left: parent.left

        Column {
            anchors.top: parent.top
            anchors.topMargin: 10
            anchors.left: parent.left
            anchors.right: parent.right
            spacing: 2

            Repeater {
                model: Library.smartNames()
                Rectangle {
                    width: side.width
                    height: 20
                    color: nameMouse.containsMouse || modelData === root.current
                           ? Theme.highlight : "transparent"
                    PixelText {
                        x: 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData
                        color: modelData === root.current ? Theme.accent
                               : (nameMouse.containsMouse ? Theme.text : Theme.textDim)
                    }
                    MouseArea {
                        id: nameMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: root.select(modelData)
                    }
                }
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
                color: Theme.textDim
            }
            HeaderButton {
                label: "> play all"
                onClicked: Player.playSmart(root.current)
            }
        }
        TrackList {
            anchors.top: listHead.bottom
            anchors.topMargin: 4
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            model: PlaylistModel
            showNumber: false
            onPlayed: function(index) { Library.playFromModel(PlaylistModel, index); }
        }
    }
}
