import QtQuick

// A section band: `needs you`, `in flight`, `landed`.
//
// A heading here is told apart by a RULE and by spacing, never by size or
// weight — reader's reading of docs/DESIGN.md §2.2 (the font ships Regular only
// and every size on this desktop is one setting), and the same idiom so the two
// document-shaped apps do not disagree one alt-tab apart. The three sections
// differ by the rule's COLOUR: accent for the one that wants him, the border
// hairline for the two that do not.
//
// It is also the collapse control, and it says so: `[-]` open, `[+]` closed,
// ASCII because the font has no triangles (§2.3). Clicking the band toggles.
Item {
    id: head

    property string label: ""
    property bool accented: false
    property bool collapsed: false
    property color fgAccent: Theme.accent
    property color fgDim: Theme.textDim
    property bool interactive: true

    signal toggled()

    implicitHeight: Theme.fontSize + 14
    height: implicitHeight

    Rectangle {              // the row lights on hover like every other row
        anchors.fill: parent
        color: ma.containsMouse && head.interactive ? Theme.highlight : "transparent"
    }

    PixelText {
        id: mark
        x: 0
        anchors.verticalCenter: parent.verticalCenter
        color: head.fgDim
        text: head.collapsed ? "[+]" : "[-]"
        visible: head.interactive
    }

    PixelText {
        id: name
        x: mark.visible ? mark.width + 8 : 0
        anchors.verticalCenter: parent.verticalCenter
        color: head.accented ? head.fgAccent : head.fgDim
        text: head.label
    }

    // The rule runs from the label to the far edge, so the band reads as one
    // line of type with a hairline finishing it rather than as a boxed header.
    Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        x: name.x + name.width + 8
        width: Math.max(0, parent.width - x)
        height: 1
        color: head.accented ? head.fgAccent : Theme.border
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        enabled: head.interactive
        cursorShape: Qt.PointingHandCursor
        onClicked: head.toggled()
    }
}
