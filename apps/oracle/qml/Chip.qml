import QtQuick

// One attached file, as a removable chip (docs/DESIGN.md §7.2 boxed, §10.2 —
// a control that shows a file offers to drop it again).
//
// Same API as `+plasma/Chip.qml`, which is what the file selector puts here in
// a Plasma session: `label`, `removed()`.
Rectangle {
    id: root
    property string face: "hypr"     // how a harness proves which one loaded
    property string label: ""
    signal removed()

    height: 22
    width: chipRow.implicitWidth + 12
    radius: Theme.rounding
    color: chipMouse.containsMouse ? Theme.highlight : Theme.bgAlt
    border.width: Theme.ctrlBorder
    border.color: Theme.border

    Row {
        id: chipRow
        anchors.centerIn: parent
        spacing: 6
        PixelText {
            text: root.label
            color: Theme.text
            elide: Text.ElideRight
            width: Math.min(implicitWidth, 220)
            anchors.verticalCenter: parent.verticalCenter
        }
        // The remove affordance: an [x] that drops this one before sending
        // (§10 — a shown attachment can be taken back).
        PixelText {
            text: "x"
            color: Theme.textDim
            anchors.verticalCenter: parent.verticalCenter
            MouseArea {
                id: chipMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.removed()
            }
        }
    }
}
