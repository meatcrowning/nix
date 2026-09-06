import QtQuick
import QtQuick.Controls

// The same collapse/reorder contract as ../SectionHead.qml, with the section
// presented as an Oxygen tool button rather than a terminal rule.
Item {
    id: head
    property string label: ""
    property bool accented: false
    property bool collapsed: false
    property color fgAccent: Theme.accent
    property color fgAccent2: Theme.accent2
    property color fgDim: Theme.textDim
    property bool interactive: true
    property bool reorderable: false
    signal toggled()
    signal reorderRequested(real dy)

    implicitHeight: button.implicitHeight
    height: implicitHeight

    Button {
        id: button
        anchors.fill: parent
        text: (head.interactive ? (head.collapsed ? "+  " : "-  ") : "") + head.label
        enabled: head.interactive
        // The mouse area retains Goetia's drag-to-reorder gesture; this real
        // button supplies Oxygen's material, focus and pressed surface.
        down: area.pressed
        onClicked: head.toggled()
    }

    Item { id: dragProxy; visible: false }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        enabled: head.interactive
        cursorShape: head.reorderable ? Qt.SizeVerCursor : Qt.PointingHandCursor
        drag.target: head.reorderable ? dragProxy : null
        drag.axis: Drag.YAxis
        drag.threshold: 8
        onPressed: if (head.reorderable) dragProxy.y = 0
        onReleased: {
            if (head.reorderable && area.drag.active)
                head.reorderRequested(dragProxy.y)
            else
                head.toggled()
        }
    }
}
