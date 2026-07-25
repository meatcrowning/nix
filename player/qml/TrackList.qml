import QtQuick

// A reusable track table (album detail, playlists, search, queue): one packed
// pixel-text row per track — number, title, optional artist, rating stars,
// favourite heart, duration. Rows grey to Theme.inactive when the file is
// missing (library drive unplugged). Double-click plays from that row.
Item {
    id: root
    property alias model: list.model
    property bool showArtist: true
    property bool showNumber: true
    property int currentTrackId: Player.current.id !== undefined ? Player.current.id : -1
    signal played(int index)

    ListView {
        id: list
        anchors.fill: parent
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        delegate: Rectangle {
            id: row
            width: list.width
            height: 20
            color: rowMouse.containsMouse ? Theme.highlight : "transparent"
            readonly property bool isCurrent: trackId === root.currentTrackId
            readonly property color fg: !available ? Theme.inactive
                                        : (isCurrent ? Theme.accent : Theme.text)

            PixelText {
                id: numText
                visible: root.showNumber
                x: 8
                width: 30
                anchors.verticalCenter: parent.verticalCenter
                text: track > 0 ? ((disc > 1 ? disc + "-" : "") + track) : ""
                color: Theme.textDim
            }
            PixelText {
                anchors.left: root.showNumber ? numText.right : parent.left
                anchors.leftMargin: root.showNumber ? 4 : 8
                anchors.right: rightBits.left
                anchors.rightMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                text: title + (root.showArtist && artist ? "  —  " + artist : "")
                elide: Text.ElideRight
                color: row.fg
            }
            Row {
                id: rightBits
                anchors.right: parent.right
                anchors.rightMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8

                PixelText {
                    visible: playCount > 0
                    anchors.verticalCenter: parent.verticalCenter
                    text: playCount + "x"
                    color: Theme.dim
                }
                Stars {
                    anchors.verticalCenter: parent.verticalCenter
                    rating: model.rating !== undefined ? model.rating : -1
                    onRated: function(fmps) { Library.setRating(trackId, fmps); }
                }
                Item {
                    width: 12
                    height: 15
                    anchors.verticalCenter: parent.verticalCenter
                    PixelText {
                        anchors.centerIn: parent
                        text: "♥"
                        color: favorite ? Theme.crit : Theme.dim
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: Library.setFavorite(trackId, !favorite)
                    }
                }
                PixelText {
                    anchors.verticalCenter: parent.verticalCenter
                    text: {
                        var s = Math.max(0, Math.round(duration));
                        return Math.floor(s / 60) + ":" + (s % 60 < 10 ? "0" : "") + (s % 60);
                    }
                    color: Theme.textDim
                }
            }
            MouseArea {
                id: rowMouse
                anchors.fill: parent
                anchors.rightMargin: 130   // keep stars/heart clickable
                hoverEnabled: true
                onDoubleClicked: root.played(index)
            }
        }
    }
}
