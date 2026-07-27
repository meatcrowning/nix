import QtQuick

// Network throughput history. Unlike cpu/gpu there is no natural ceiling, so
// the axis auto-scales to the window's own peak (scaleMax 0), floored at
// 64 KB/s so an idle link doesn't magnify its own noise into a mountain range.
MetricChart {
    id: root
    title: "eth"
    scaleMax: 0
    autoFloor: 64 * 1024
    midline: false
    series: [
        { data: SysInfo.txHist, color: Theme.warn },  // up
        { data: SysInfo.rxHist, color: Theme.info },  // down, drawn on top
    ]

    Row {
        spacing: 12
        PixelText { text: "dn " + SysInfo.fmtSpeed(SysInfo.rxSpeed); color: Theme.info }
        PixelText { text: "up " + SysInfo.fmtSpeed(SysInfo.txSpeed); color: Theme.warn }
    }
    PixelText {
        anchors.horizontalCenter: parent.horizontalCenter
        text: "peak " + SysInfo.fmtSpeed(root.axisMax)
        color: Theme.textDim
    }
}
