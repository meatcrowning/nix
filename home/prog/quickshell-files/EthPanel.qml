import QtQuick
import Quickshell

// Network-throughput popup (SlidePopup): line chart of rx/tx history from
// SysInfo's ring buffers, auto-scaled to the window's peak (with a small
// floor so an idle link doesn't blow up the axis).
SlidePopup {
    id: root

    popupNamespace: "qs-eth"
    implicitWidth: 220
    implicitHeight: content.implicitHeight + 20
    aboveDiskWhenPinned: true // stack above the disk panel while it's open
    pinInPlace: true          // pinning freezes it here, not the bottom row

    Connections {
        target: SysInfo
        function onRxHistChanged() { if (root.visible) chart.requestPaint(); }
        function onTxHistChanged() { if (root.visible) chart.requestPaint(); }
    }
    onOpened: chart.requestPaint()

    Column {
        id: content
        anchors { top: parent.top; horizontalCenter: parent.horizontalCenter; topMargin: 10 }
        spacing: 6

        PixelText {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "eth"
            color: Theme.accent
        }

        Canvas {
            id: chart
            width: 196
            height: 96
            anchors.horizontalCenter: parent.horizontalCenter

            function peak() {
                let m = 64 * 1024; // 64 KB/s floor
                for (const a of [SysInfo.rxHist, SysInfo.txHist])
                    for (const v of (a || [])) if (v > m) m = v;
                return m;
            }
            function line(ctx, data, scale, color) {
                if (!data || data.length < 2) return;
                const n = SysInfo.chartLen;
                const w = width, h = height;
                ctx.strokeStyle = color;
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                for (let i = 0; i < data.length; i++) {
                    const x = w * (i / (n - 1));
                    const y = h - h * Math.min(1, data[i] / scale);
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

                const s = peak();
                line(ctx, SysInfo.txHist, s, Theme.warn); // up
                line(ctx, SysInfo.rxHist, s, Theme.info); // down (on top)
            }
        }

        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 12
            PixelText { text: "dn " + SysInfo.fmtSpeed(SysInfo.rxSpeed); color: Theme.info }
            PixelText { text: "up " + SysInfo.fmtSpeed(SysInfo.txSpeed); color: Theme.warn }
        }
        PixelText {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "peak " + SysInfo.fmtSpeed(chart.peak())
            color: Theme.textDim
        }
    }
}
