import QtQuick

// A flat pixel-text button for the header row: dim by default, accent when
// lit (active view), highlight tint on hover — the MediaPanel MediaButton
// idiom without the box.
Item {
    id: root
    property string label: ""
    // THE SAME BUTTON, SPELT FOR A REAL KDE TOOLBAR (apps/AGENTS.md -> kdeshell).
    // `label` carries this desktop's two-character affordance glyphs ("> play",
    // "x close") because the pixel face has no icons and the titlebar column is
    // where that vocabulary comes from. On a styled Button those prefixes are
    // exactly the imitation the Plasma face exists to drop, so a call site that
    // has one states the plain words and a freedesktop icon name beside it and
    // `+plasma/HeaderButton.qml` uses those instead. Both are INERT here — the
    // Hyprland button is byte-for-byte what it was.
    property string plainLabel: ""
    property string iconName: ""
    // The pixel face's bare glyph buttons ("x", "-", "+") have no words at all:
    // there, the character IS the affordance. On a KDE button the icon is, so
    // the row says so rather than the twin guessing from an empty `plainLabel`.
    property bool iconOnly: false
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
