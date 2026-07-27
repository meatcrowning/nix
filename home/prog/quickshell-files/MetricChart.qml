import QtQuick

// The shared body of the three history widgets (cpu, gpu, eth): a title, a line
// chart of one or more ring buffers, and a legend under it. CpuContent /
// GpuContent / EthContent are each about ten lines on top of this.
//
// It is a CONTENT component, i.e. it draws a widget and owns no data and no
// window. That is what lets the same widget appear as a hover popup on the
// wallpaper (classic mode) and as a tile in the dock's grid, from one source —
// see DockGrid.qml. Two rules follow from being used in both places:
//
//   * It must STRETCH. In a popup it is given its implicit size; in a grid cell
//     it is given the cell. So the title sits at the top, the legend at the
//     bottom, and the chart takes whatever is left — never a fixed 196x96.
//   * It must be able to go DORMANT. Both copies exist in the QML tree at once,
//     but only one is on screen, so `active` gates the repaints. Anything that
//     costs something when nobody is looking hangs off that flag.
Item {
    id: root

    property string title: ""
    // [{ data: [...], color: <color> }] — painted in order, so the series that
    // matters most goes LAST and ends up on top.
    property var series: []
    // Fixed top of the y axis, or <= 0 to auto-scale to the data's own peak
    // (never below autoFloor, so an idle network doesn't blow the axis up).
    property real scaleMax: 100
    property real autoFloor: 1
    property bool midline: true
    // Denominator for the x axis: the ring buffer's FULL length, so a
    // half-filled buffer draws across half the width rather than being stretched.
    property int pointCount: SysInfo.chartLen

    property bool active: true
    property int pad: 10
    property int spacing: 6
    property int chartMinHeight: 96

    // Legend contents (a Row of readouts, usually). Declared as the default
    // property so a consumer just writes its readouts inside MetricChart {}.
    default property alias legend: legendCol.data

    readonly property real axisMax: {
        if (scaleMax > 0) return scaleMax;
        let m = autoFloor;
        for (const s of series)
            for (const v of (s.data || [])) if (v > m) m = v;
        return m;
    }

    implicitWidth: 220
    implicitHeight: pad * 2 + titleText.height + spacing
                    + chartMinHeight + spacing + legendCol.implicitHeight

    // `series` is a binding over the source ring buffers, so it re-evaluates
    // whenever one of them is replaced — which makes this the only repaint
    // trigger any of the three widgets needs.
    onSeriesChanged: repaint()
    onAxisMaxChanged: repaint()
    onActiveChanged: repaint()
    function repaint() { if (active) chart.requestPaint(); }

    PixelText {
        id: titleText
        anchors { top: parent.top; topMargin: root.pad; horizontalCenter: parent.horizontalCenter }
        text: root.title
        color: Theme.accent
    }

    Column {
        id: legendCol
        anchors { bottom: parent.bottom; bottomMargin: root.pad; horizontalCenter: parent.horizontalCenter }
        spacing: 2
    }

    Canvas {
        id: chart
        anchors {
            top: titleText.bottom; topMargin: root.spacing
            bottom: legendCol.top; bottomMargin: root.spacing
            left: parent.left; leftMargin: root.pad
            right: parent.right; rightMargin: root.pad
        }

        function line(ctx, data, color) {
            if (!data || data.length < 2) return;
            const n = Math.max(2, root.pointCount);
            const w = width, h = height, s = root.axisMax;
            ctx.strokeStyle = color;
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            for (let i = 0; i < data.length; i++) {
                const x = w * (i / (n - 1));
                const y = h - h * Math.max(0, Math.min(1, data[i] / s));
                if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            }
            ctx.stroke();
        }

        onPaint: {
            const ctx = getContext("2d");
            ctx.reset();
            ctx.clearRect(0, 0, width, height);

            ctx.strokeStyle = Theme.border;
            ctx.lineWidth = 1;
            ctx.strokeRect(0.5, 0.5, width - 1, height - 1);
            if (root.midline) {
                ctx.beginPath();
                ctx.moveTo(0, height / 2);
                ctx.lineTo(width, height / 2);
                ctx.stroke();
            }

            for (const s of root.series) line(ctx, s.data, s.color);
        }
    }
}
