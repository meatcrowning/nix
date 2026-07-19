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

    // mapToItem in a plain binding captures ancestor positions ONCE at
    // creation — an item that gets laid out later (e.g. a Repeater cell in a
    // Column) keeps its birth position (y=0, i.e. "near the top") forever.
    // So: recompute the mapping every time the tooltip is shown instead.
    property real anchorX: 0
    property real anchorY: 0
    function reposition() {
        if (!ready)
            return;
        const p = tip.target.mapToItem(null, 0, tip.target.height / 2);
        anchorX = p.x - 8;
        anchorY = p.y;
    }
    onVisibleChanged: if (visible) reposition()

    anchor {
        window: tip.target ? tip.target.QsWindow.window : null
        rect {
            x: tip.anchorX
            y: tip.anchorY
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
