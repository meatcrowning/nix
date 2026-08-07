import QtQuick

// A push button matching the panel's square controls (SetToggle/SetSelect): a
// bordered block whose edge and label take the accent on hover, and that dents
// to bgAlt while pressed. `clicked()` fires on release; nothing about it is
// stateful, so callers just wire the action.
//
// `minWidth`/`maxWidth` exist for callers with less room than a settings page:
// a notification card is 300px wide and may carry three actions, so its buttons
// size to their label and elide rather than holding the settings pages' 96px
// floor. Both default to the settings-page behaviour.
Rectangle {
    id: root
    property string text: ""
    property int minWidth: 96
    property int maxWidth: 0          // 0 = no cap
    signal clicked()

    width: {
        const w = Math.max(root.minWidth, label.implicitWidth + 24);
        return root.maxWidth > 0 ? Math.min(w, root.maxWidth) : w;
    }
    height: 22
    radius: 0
    color: ma.pressed ? Theme.bgAlt : "transparent"
    border.width: 1
    border.color: (ma.containsMouse || ma.pressed) ? Theme.accent : Theme.border

    PixelText {
        id: label
        anchors.centerIn: parent
        width: root.maxWidth > 0 ? Math.min(implicitWidth, root.maxWidth - 24) : implicitWidth
        elide: Text.ElideRight
        horizontalAlignment: Text.AlignHCenter
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
