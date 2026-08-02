import QtQuick

// A push button matching the panel's square controls (SetToggle/SetSelect): a
// bordered block whose edge and label take the accent on hover, and that dents
// to bgAlt while pressed. `clicked()` fires on release; nothing about it is
// stateful, so callers just wire the action.
Rectangle {
    id: root
    property string text: ""
    signal clicked()

    width: Math.max(96, label.implicitWidth + 24)
    height: 22
    radius: 0
    color: ma.pressed ? Theme.bgAlt : "transparent"
    border.width: 1
    border.color: (ma.containsMouse || ma.pressed) ? Theme.accent : Theme.border

    PixelText {
        id: label
        anchors.centerIn: parent
        text: root.text
        color: (ma.containsMouse || ma.pressed) ? Theme.accent : Theme.text
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
