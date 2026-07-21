import QtQuick
import Quickshell

// GPU-usage popup (SlidePopup): a line chart of usage% and temperature
// history from SysInfo's ring buffers (both share a 0-100 scale — usage in
// percent, temp in Celsius, which for this GPU stays under 100). Mirrors
// CpuPanel exactly, reading the nvidia-smi-backed gpu* properties instead.
SlidePopup {
    id: root

    popupNamespace: "qs-gpu"
    persistKey: "gpu"
    implicitWidth: 220
    implicitHeight: content.implicitHeight + 20
    aboveDiskWhenPinned: true // stack above the disk panel while it's open
    pinInPlace: true          // pinning freezes it here, not the bottom row

    Connections {
        target: SysInfo
        function onGpuHistChanged() { if (root.visible) chart.requestPaint(); }
        function onGpuTempHistChanged() { if (root.visible) chart.requestPaint(); }
    }
    onOpened: chart.requestPaint()

    Column {
        id: content
        anchors { top: parent.top; horizontalCenter: parent.horizontalCenter; topMargin: 10 }
        spacing: 6

        PixelText {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "gpu"
            color: Theme.accent
        }

        Canvas {
            id: chart
            width: 196
            height: 96
            anchors.horizontalCenter: parent.horizontalCenter

            function line(ctx, data, color) {
                if (!data || data.length < 2) return;
                const n = SysInfo.chartLen;
                const w = width, h = height;
                ctx.strokeStyle = color;
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                for (let i = 0; i < data.length; i++) {
                    const x = w * (i / (n - 1));
                    const y = h - h * Math.max(0, Math.min(100, data[i])) / 100;
                    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
                }
                ctx.stroke();
            }

            onPaint: {
                const ctx = getContext("2d");
                ctx.reset();
                ctx.clearRect(0, 0, width, height);
                // frame + mid gridline
                ctx.strokeStyle = Theme.border;
                ctx.lineWidth = 1;
                ctx.strokeRect(0.5, 0.5, width - 1, height - 1);
                ctx.beginPath();
                ctx.moveTo(0, height / 2);
                ctx.lineTo(width, height / 2);
                ctx.stroke();

                line(ctx, SysInfo.gpuTempHist, Theme.crit); // temperature
                line(ctx, SysInfo.gpuHist, Theme.accent);   // usage (on top)
            }
        }

        // legend / current values
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 12
            PixelText {
                text: "use " + (SysInfo.gpuUsage < 0 ? "--" : SysInfo.gpuUsage + "%")
                color: Theme.accent
            }
            PixelText {
                text: "tmp " + (SysInfo.gpuTemp < 0 ? "--" : SysInfo.gpuTemp + "C")
                color: Theme.crit
            }
        }
    }
}
