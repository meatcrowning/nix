import QtQuick

// A flat pixel-text button for the header row: dim by default, accent when
// lit (active view), highlight tint on hover — the MediaPanel MediaButton
// idiom without the box.
Item {
    id: root
    property string label: ""
    property bool lit: false
    signal clicked()

    width: txt.implicitWidth + 8
    height: 20

    Rectangle {
        anchors.fill: parent
        color: mouse.containsMouse ? Theme.highlight : "transparent"
    }
    PixelText {
        id: txt
        anchors.centerIn: parent
        text: root.label
        color: root.lit ? Theme.accent : (mouse.containsMouse ? Theme.text : Theme.textDim)
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        onClicked: root.clicked()
    }
}
