import QtQuick

// A flat pixel-text button for the header row: dim by default, accent when
// lit (active view), highlight tint on hover — the MediaPanel MediaButton
// idiom without the box.
Item {
    id: root
    property string label: ""
    property bool lit: false
    // The three foreground tones, handed in already faded by whatever pane owns
    // this button (docs/DESIGN.md §3.1.1). A button must not know whether the
    // window is focused; the defaults are the lit tones so a standalone/harness
    // instance still draws correctly.
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent
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
        // A button that cannot act says so (docs/DESIGN.md §10): `enabled` is
        // Item's own, so setting it both kills the MouseArea and greys the
        // label. Every call site that never disables one is unaffected.
        color: !root.enabled ? Theme.inactive
             : root.lit ? root.fgAccent : (mouse.containsMouse ? root.fgText : root.fgDim)
    }
    MouseArea {
        cursorShape: Qt.PointingHandCursor
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        onClicked: root.clicked()
    }
}
