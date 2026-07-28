import QtQuick
import Quickshell

// A small hover tooltip that SLIDES OUT to the LEFT of `target`, after a beat.
// The bar hugs the right screen edge, so tooltips grow leftward.
// Set `target` to the item to point at, `text` to the label, and drive `show`
// from a HoverHandler / MouseArea.containsMouse.
//
// `show` — not `visible`. The window's own visibility belongs to the animation,
// not to the caller: it has to outlive the hover by the length of the slide back
// in, and it must not appear the instant the pointer crosses the item. A tooltip
// that pops instantly turns every pass across a dense panel into a flicker of
// boxes.
//
// The reveal is the one surfer draws for page tooltips and hyprvtb for titlebar
// ones: a clipped chip growing leftward from a FIXED right edge, OutCubic over
// 220ms. The window never resizes — it is full size throughout and the clip
// inside it grows — because a resizing surface is a configure roundtrip per
// frame and would lag the animation it is supposed to be.
PopupWindow {
    id: tip

    property Item target
    property string text: ""
    // The caller's hover state.
    property bool show: false
    // How long the pointer has to stay before this appears. 350ms is the usual
    // desktop dwell: long enough that crossing a card does nothing, short enough
    // that stopping on one feels answered.
    property int delayMs: 350

    // True only once the target is actually attached to a window; itemRect
    // throws before that (and re-evaluates via windowChanged once it is).
    readonly property bool ready: target && target.QsWindow && target.QsWindow.window

    // 0 = retracted, 1 = fully out. The window lives exactly as long as this is
    // off zero, so the slide back in finishes before it unmaps.
    property real slide: 0
    Behavior on slide { NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing } }

    Timer {
        id: dwell
        interval: tip.delayMs
        onTriggered: if (tip.show) tip.slide = 1
    }
    onShowChanged: {
        if (show) {
            // Only the OPENING waits. Retracting is immediate: the pointer has
            // already left, and a tooltip that lingers is in the way.
            reposition();
            dwell.restart();
        } else {
            dwell.stop();
            slide = 0;
        }
    }
    // Text can change while the chip is out (a task cell's window title); it
    // must re-measure, but it must not restart the reveal.
    onTextChanged: if (slide > 0) reposition()

    visible: slide > 0.001
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

    // The clip. Its RIGHT edge is the window's right edge — the side nearest the
    // thing being pointed at — so the chip slides out from under it.
    Item {
        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
        width: box.implicitWidth * tip.slide
        height: box.implicitHeight
        clip: true

        Rectangle {
            id: box
            anchors.right: parent.right
            width: implicitWidth
            height: implicitHeight
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
                // NB: no lineHeight override here — PixelText sets lineHeightMode:
                // FixedHeight, which makes lineHeight a PIXEL count, so the old
                // `lineHeight: 1.1` (read as a multiplier) collapsed every line to
                // 1.1px: a two-line tooltip measured 15px tall instead of 30 and
                // drew its lines on top of each other.
                color: Theme.text
            }
        }
    }
}
