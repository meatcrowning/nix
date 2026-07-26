import QtQuick

// Small themed button for the file browser header (the ↑ up button). Greys its
// accent/text to the titlebar's inactive tone when the window is unfocused —
// the parent passes the window's active state in via `winActive` (the same
// `win.active` source the rest of filer uses), rather than the Window.active
// attached property, which wasn't tracking here.
Rectangle {
    id: root
    property string label: ""
    property bool enabled: true
    property bool danger: false
    property bool winActive: true
    signal clicked()

    width: t.implicitWidth + 16
    height: 22
    color: ma.containsMouse && enabled ? Theme.bgAlt : "transparent"
    border.width: 1
    border.color: !enabled ? Theme.border
                 : danger ? Theme.crit
                 : ma.containsMouse ? (winActive ? Theme.accent : Theme.inactive) : Theme.border
    opacity: enabled ? 1 : 0.4

    PixelText {
        id: t
        anchors.centerIn: parent
        text: root.label
        color: root.danger ? Theme.crit
             : (ma.containsMouse && root.enabled) ? (root.winActive ? Theme.accent : Theme.inactive)
             : (root.winActive ? Theme.text : Theme.inactive)
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: root.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: if (root.enabled) root.clicked()
    }
}
