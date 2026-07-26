import QtQuick

// On/off switch drawn in the pixel-font idiom: [x] / [ ].
Item {
    id: sw
    property bool checked: false
    property string label: ""
    signal toggled(bool value)

    width: box.width + (label ? txt.implicitWidth + 6 : 0)
    height: 18

    PixelText {
        id: box
        anchors.verticalCenter: parent.verticalCenter
        text: sw.checked ? "[x]" : "[ ]"
        color: sw.checked ? Theme.accent : Theme.dim
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
        anchors.fill: parent
        onClicked: { sw.checked = !sw.checked; sw.toggled(sw.checked) }
    }
}
