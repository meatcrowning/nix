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

        TextButton {
            anchors.verticalCenter: parent.verticalCenter
            label: row.on ? "[x]" : "[ ]"
            tone: row.on ? Theme.accent : Theme.dim
            winActive: root.winActive
            onClicked: Loras.setEnabled(row.rowIndex, !row.on)
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
        // Order changes the result, so it is adjustable. At either end the
        // control is DISABLED rather than drawn in Theme.highlight (which is
        // near-invisible on the panel fill but still clickable, so the first
        // row's "up" was a live button for a move that could never happen).
        TextButton {
            label: "v"                 // the same glyph, mirrored - see flipY
            flipY: true
            tone: Theme.dim
            enabled: row.rowIndex > 0
            winActive: root.winActive
            anchors.verticalCenter: parent.verticalCenter
            onClicked: Loras.move(row.rowIndex, row.rowIndex - 1)
        }
        TextButton {
            label: "v"
            tone: Theme.dim
            enabled: row.rowIndex < Loras.count - 1
            winActive: root.winActive
            anchors.verticalCenter: parent.verticalCenter
            onClicked: Loras.move(row.rowIndex, row.rowIndex + 1)
        }
        TextButton {
            label: "x"
            tone: Theme.crit
            winActive: root.winActive
            anchors.verticalCenter: parent.verticalCenter
            onClicked: Loras.remove(row.rowIndex)
        }
    }
}
