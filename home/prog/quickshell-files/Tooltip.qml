import QtQuick
import Quickshell

// A small hover tooltip that pops out to the LEFT of `target`.
// The bar hugs the right screen edge, so tooltips grow leftward.
// Set `target` to the item to point at and `text` to the label;
// drive `visible` from a HoverHandler / MouseArea.containsMouse.
PopupWindow {
    id: tip

    property Item target
    property string text: ""

    // True only once the target is actually attached to a window; itemRect
    // throws before that (and re-evaluates via windowChanged once it is).
    readonly property bool ready: target && target.QsWindow && target.QsWindow.window

    visible: false
    color: "transparent"
    implicitWidth: box.implicitWidth
    implicitHeight: box.implicitHeight

    anchor {
        window: tip.target ? tip.target.QsWindow.window : null
        // mapToItem(null, …) yields window/scene coordinates and never throws
        // (QsWindow.itemRect does, before the item is a window member).
        rect {
            x: tip.ready ? tip.target.mapToItem(null, 0, 0).x - 8 : 0
            y: tip.ready
                ? tip.target.mapToItem(null, 0, tip.target.height / 2).y
                : 0
            width: 1
            height: 1
        }
        edges: Edges.Left
        gravity: Edges.Left
    }

    Rectangle {
        id: box
        anchors.fill: parent
        implicitWidth: label.implicitWidth + 16
        implicitHeight: label.implicitHeight + 10
        color: Theme.bgAlt
        border.color: Theme.border
        border.width: 1
        radius: 3

        PixelText {
            id: label
            anchors.centerIn: parent
            text: tip.text
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            lineHeight: 1.1
            color: Theme.text
        }
    }
}
