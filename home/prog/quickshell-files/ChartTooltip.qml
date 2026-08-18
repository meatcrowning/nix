import QtQuick
import Quickshell

// The hover-detail overlay for a small metric graph. Where Tooltip.qml is a
// one-line text chip, this is its sibling for a CHART: hovering one of the tiny
// square sparklines in MetricCardGrid pops a large, labelled, still-live copy of
// the SAME plot out to the left. Same reveal as Tooltip — a dwell, then a
// clipped slide out of a fixed right edge over slideMs, in theme colours — so
// the two read as one desktop (docs/DESIGN.md §8).
//
// It draws with ChartCanvas, the exact code the small sparkline uses, at a far
// bigger size: the same `series` ring buffers spread across ~240px instead of
// ~60 (finer resolution, not more history — the buffers hold chartLen samples
// and that is all there is), plus a title, the readouts the card had no room to
// keep alongside the chart, y-axis labels and the window span. Because `series`
// is the caller's binding over the live SysInfo/TopStats ring buffers, the
// enlarged plot keeps ticking while hovered with nothing extra wired up — a new
// sample replaces the buffer, `onSeriesChanged` fires, and both the card and
// this overlay repaint from it.
PopupWindow {
    id: tip

    property Item target
    // The plot, passed straight through to ChartCanvas — same shape the small
    // card feeds it: [{ data: [...], color: <color> }], last on top.
    property var series: []
    property real scaleMax: 100
    property real autoFloor: 1
    property int pointCount: SysInfo.chartLen
    // Header + readouts + explanation, all from the card that owns this.
    property string title: ""
    property string primary: ""
    property color primaryColor: Theme.text
    property string secondary: ""
    property string caption: ""
    // How long the window of history is, in words ("3 min"), drawn under the
    // chart's left edge. "" hides it.
    property string span: ""

    // The caller's hover state, and the dwell before it appears — same 350ms as
    // Tooltip.qml, long enough that crossing the grid does nothing.
    property bool show: false
    property int delayMs: 350

    // Held out across the screenshot freeze exactly as Tooltip does: the
    // overlay's full-screen surface steals the pointer, so a displayed chart
    // holds rather than retracting the instant Meta+Shift+S fires.
    readonly property bool frozen: TooltipState.frozen

    readonly property bool ready: target && target.QsWindow && target.QsWindow.window

    // 0 = retracted, 1 = fully out; the window lives exactly as long as this is
    // off zero so the slide back in finishes before it unmaps.
    property real slide: 0
    Behavior on slide { NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing } }

    Timer {
        id: dwell
        interval: tip.delayMs
        onTriggered: if (tip.show) tip.slide = 1
    }
    onShowChanged: {
        if (show) {
            reposition();
            dwell.restart();
        } else if (!frozen) {
            dwell.stop();
            slide = 0;
        }
    }
    onFrozenChanged: {
        if (!frozen && !show && slide > 0.001) {
            dwell.stop();
            slide = 0;
        }
    }

    visible: slide > 0.001
    color: "transparent"
    implicitWidth: box.implicitWidth
    implicitHeight: box.implicitHeight

    // Recompute the mapping on every show — mapToItem in a plain binding
    // captures ancestor positions once, at creation (Tooltip.qml).
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

    // Fixed inner geometry — NEVER derived from the popup's own size, which is
    // the zero-size-popup trap that kills the whole panel
    // (quickshell-files/AGENTS.md, "A popup that maps at ZERO SIZE"). The chart
    // is a constant width and the box grows to hold it.
    readonly property int pad: 10
    readonly property int yGutter: 30
    readonly property int chartW: 240
    readonly property int chartH: 120
    readonly property int contentW: yGutter + chartW

    // The clip: right edge pinned to the window's right edge (the side nearest
    // the card), the chip sliding out from under it.
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
            implicitWidth: tip.contentW + tip.pad * 2
            implicitHeight: col.implicitHeight + tip.pad * 2
            color: Theme.bgAlt
            border.color: Theme.border
            border.width: Theme.ctrlBorder
            radius: Math.max(3, Theme.windowRounding)

            Column {
                id: col
                anchors {
                    left: parent.left; leftMargin: tip.pad
                    top: parent.top; topMargin: tip.pad
                }
                width: tip.contentW
                spacing: 6

                // Header + readouts on one line: title left, the values the card
                // could not fit beside its sparkline on the right.
                Item {
                    width: parent.width
                    height: Math.max(titleText.height, readouts.height)
                    PixelText {
                        id: titleText
                        anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                        text: tip.title
                        color: Theme.accent
                    }
                    Row {
                        id: readouts
                        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                        spacing: 8
                        PixelText {
                            visible: tip.secondary !== ""
                            text: tip.secondary
                            color: Theme.textDim
                        }
                        PixelText {
                            visible: tip.primary !== ""
                            text: tip.primary
                            color: tip.primaryColor
                        }
                    }
                }

                // The enlarged plot, with a y-axis gutter down its left: the axis
                // top and 0 labelled, so a value can be read off it. `active`
                // gates the repaints on the overlay actually being out, per the
                // "one widget, two places" contract.
                Item {
                    width: parent.width
                    height: tip.chartH

                    PixelText {
                        id: axisTop
                        anchors { left: parent.left; top: bigChart.top; topMargin: -height / 2 }
                        color: Theme.textDim
                        text: {
                            const m = bigChart.axisMax;
                            if (tip.scaleMax === 100) return m + "%";
                            if (m >= 1024 * 1024) return (m / 1024 / 1024).toFixed(1) + "M";
                            if (m >= 1024) return Math.round(m / 1024) + "K";
                            return (m >= 100 ? Math.round(m) : m.toFixed(m >= 10 ? 0 : 1)).toString();
                        }
                    }
                    PixelText {
                        anchors { left: parent.left; bottom: bigChart.bottom; bottomMargin: -height / 2 }
                        color: Theme.textDim
                        text: "0"
                    }

                    ChartCanvas {
                        id: bigChart
                        anchors {
                            left: parent.left; leftMargin: tip.yGutter
                            right: parent.right
                            top: parent.top; bottom: parent.bottom
                        }
                        active: tip.slide > 0.001
                        series: tip.series
                        scaleMax: tip.scaleMax
                        autoFloor: tip.autoFloor
                        pointCount: tip.pointCount
                        lineWidth: 2
                    }
                }

                PixelText {
                    visible: tip.span !== ""
                    anchors { left: parent.left; leftMargin: tip.yGutter }
                    text: "← " + tip.span
                    color: Theme.textDim
                }

                // The explanation the card kept in its own text tooltip — the
                // encoding of the lines, the jargon behind the label. Wrapped to
                // the chart's width (docs/DESIGN.md §8: any graph whose encoding
                // is not self-evident gets one).
                PixelText {
                    visible: tip.caption !== ""
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: tip.caption
                    color: Theme.textDim
                }
            }
        }
    }
}
