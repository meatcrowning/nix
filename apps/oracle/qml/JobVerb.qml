import QtQuick

// One verb on a job row — `log`, `stop`, `clear` — in the Hyprland session's own
// idiom: a lowercase word in a `bgAlt` cell that lights to `highlight` under the
// pointer (docs/DESIGN.md §7.2, §12.1). Small, quiet, and never a button
// pretending to be a button: it does exactly what its word says (§10.2).
//
// A component because it has a Plasma twin (`+plasma/JobVerb.qml`, a real
// KStyle button). API: `label`, `clicked()`.
Rectangle {
    id: root
    property string face: "hypr"
    property alias label: verbText.text

    signal clicked()

    implicitWidth: verbText.implicitWidth + 12
    implicitHeight: verbText.implicitHeight + 6
    width: implicitWidth
    height: implicitHeight
    radius: 3
    color: mouse.containsMouse ? Theme.highlight : Theme.bgAlt
    border.width: Theme.ctrlBorder
    border.color: Theme.border

    PixelText {
        id: verbText
        anchors.centerIn: parent
        color: mouse.containsMouse ? Theme.accent : Theme.textDim
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
