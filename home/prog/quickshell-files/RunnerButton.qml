import QtQuick

// The launcher ("runner") button — an outlined square matching the task cells.
// When the runner is open it takes the same active treatment as a focused task
// cell: bgAlt fill with a bright 2px accent border.
//
// Extracted from shell.qml so the classic bar's top cluster and the dock
// panel's horizontal header share one button. It owns no state: `active`
// mirrors the launcher and `toggled` is emitted on click, because the launcher
// itself lives in shell.qml's scope, not here.
Rectangle {
    id: root

    property bool active: false
    signal toggled()

    width: Theme.wsCell
    height: Theme.wsCell
    radius: 0
    color: active ? Theme.bgAlt : "transparent"
    border.width: active ? 2 : 1
    border.color: active ? Theme.accent : Theme.border

    // solid square icon — a real Rectangle centres cleanly, where the font's ■
    // glyph sits high in its line box and floats up.
    Rectangle {
        anchors.centerIn: parent
        width: Theme.wsCell - 18
        height: width
        radius: 0
        color: root.active ? Theme.text : Theme.accent
    }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggled()
    }
}
