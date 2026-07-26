import QtQuick

Item {
    id: row
    property int rowIndex: 0
    property string loraName: ""
    property real strength: 1.0
    property bool on: true

    height: 22

    Row {
        anchors.verticalCenter: parent.verticalCenter
        spacing: 5
        width: parent.width

        PixelText {
            text: row.on ? "[x]" : "[ ]"
            color: row.on ? Theme.accent : Theme.dim
            MouseArea {
                anchors.fill: parent
                onClicked: Loras.setEnabled(row.rowIndex, !row.on)
            }
        }
        PixelText {
            text: row.loraName
            color: row.on ? Theme.text : Theme.dim
            elide: Text.ElideMiddle
            width: Math.min(implicitWidth, row.width - 165)
            anchors.verticalCenter: parent.verticalCenter
        }
        Spin {
            width: 58
            value: row.strength
            from: -4
            to: 4
            step: 0.05
            decimals: 2
            anchors.verticalCenter: parent.verticalCenter
            onEdited: function (v) { Loras.setStrength(row.rowIndex, v) }
        }
        // Order changes the result, so it is adjustable.
        PixelText {
            text: "^"
            color: row.rowIndex > 0 ? Theme.dim : Theme.highlight
            anchors.verticalCenter: parent.verticalCenter
            MouseArea {
                anchors.fill: parent
                onClicked: Loras.move(row.rowIndex, row.rowIndex - 1)
            }
        }
        PixelText {
            text: "v"
            color: row.rowIndex < Loras.count - 1 ? Theme.dim : Theme.highlight
            anchors.verticalCenter: parent.verticalCenter
            MouseArea {
                anchors.fill: parent
                onClicked: Loras.move(row.rowIndex, row.rowIndex + 1)
            }
        }
        PixelText {
            text: "x"
            color: Theme.crit
            anchors.verticalCenter: parent.verticalCenter
            MouseArea { anchors.fill: parent; onClicked: Loras.remove(row.rowIndex) }
        }
    }
}
