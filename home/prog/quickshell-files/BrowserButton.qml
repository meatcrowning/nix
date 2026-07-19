import QtQuick

// Small themed button for the file browser toolbar/header.
Rectangle {
    id: root
    property string label: ""
    property bool enabled: true
    property bool danger: false
    signal clicked()

    width: t.implicitWidth + 16
    height: 22
    color: ma.containsMouse && enabled ? Theme.bgAlt : "transparent"
    border.width: 1
    border.color: !enabled ? Theme.border
                 : danger ? Theme.crit
                 : ma.containsMouse ? Theme.accent : Theme.border
    opacity: enabled ? 1 : 0.4

    PixelText {
        id: t
        anchors.centerIn: parent
        text: root.label
        color: root.danger ? Theme.crit : (ma.containsMouse && root.enabled ? Theme.accent : Theme.text)
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: root.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: if (root.enabled) root.clicked()
    }
}
