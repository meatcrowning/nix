import QtQuick

// On/off switch drawn in the pixel-font idiom: [x] / [ ].
Item {
    id: sw
    property bool checked: false
    property string label: ""
    signal toggled(bool value)

    // Pinnable like a Field row is (see ../Field.qml).
    property string pinLabel: sw.label
    readonly property string pinValue: sw.checked ? "on" : "off"

    width: box.width + (label ? txt.implicitWidth + 6 : 0)
    height: 18

    PixelText {
        id: box
        anchors.verticalCenter: parent.verticalCenter
        text: sw.checked ? "[x]" : "[ ]"
        color: sw.checked ? Theme.accent : (ma.containsMouse ? Theme.text : Theme.dim)
    }
    PixelText {
        id: txt
        anchors.verticalCenter: parent.verticalCenter
        anchors.left: box.right
        anchors.leftMargin: 6
        text: sw.label
        color: sw.checked ? Theme.text : Theme.textDim
    }
    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: function (m) {
            if (m.button === Qt.RightButton) {
                if (typeof panel !== "undefined" && panel && panel.pinMenu) {
                    var pt = mapToItem(null, m.x, m.y)
                    panel.pinMenu(sw, pt.x, pt.y)
                }
                return
            }
            sw.checked = !sw.checked
            sw.toggled(sw.checked)
        }
    }
}
