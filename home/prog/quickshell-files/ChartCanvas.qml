import QtQuick

// The line-chart drawing itself, with no titles, legends or padding around it —
// just a framed plot of one or more ring buffers.
//
// It is its own component because the same plot is drawn at two very different
// sizes: a 196x96 chart in the cpu/gpu/eth popups (MetricChart.qml wraps this in
// a title and a legend) and a ~30px sparkline strip in the task manager, where
// there is no room for either. One implementation, so the two can't drift.
Canvas {
    id: root

    // [{ data: [...], color: <color> }] — painted in order, so the series that
    // matters most goes LAST and ends up on top.
    property var series: []
    // Fixed top of the y axis, or <= 0 to auto-scale to the data's own peak
    // (never below autoFloor, so an idle network doesn't blow the axis up).
    property real scaleMax: 100
    property real autoFloor: 1
    property bool frame: true
    property bool midline: true
    property real lineWidth: 1.5
    // Denominator for the x axis: the ring buffer's FULL length, so a
    // half-filled buffer draws across half the width rather than being stretched.
    property int pointCount: SysInfo.chartLen
    property bool active: true

    readonly property real axisMax: {
        if (scaleMax > 0) return scaleMax;
        let m = autoFloor;
        for (const s of series)
            for (const v of (s.data || [])) if (v > m) m = v;
        return m;
    }

    // `series` is a binding over the source ring buffers, so it re-evaluates
    // whenever one of them is replaced — which makes this the only repaint
    // trigger the widgets built on it need. Don't add Connections back.
    onSeriesChanged: repaint()
    onAxisMaxChanged: repaint()
    onActiveChanged: repaint()
    function repaint() { if (active) requestPaint(); }

    function _line(ctx, data, color) {
        if (!data || data.length < 2) return;
        const n = Math.max(2, pointCount);
        const w = width, h = height, s = axisMax;
        ctx.strokeStyle = color;
        ctx.lineWidth = root.lineWidth;
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
        if (frame) ctx.strokeRect(0.5, 0.5, width - 1, height - 1);
        if (midline) {
            ctx.beginPath();
            ctx.moveTo(0, height / 2);
            ctx.lineTo(width, height / 2);
            ctx.stroke();
        }

        for (const s of series) _line(ctx, s.data, s.color);
    }
}
