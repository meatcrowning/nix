import QtQuick

// GPU usage% + temperature history — CpuContent's twin, over the nvidia-smi
// backed gpu* properties.
MetricChart {
    title: "gpu"
    series: [
        { data: SysInfo.gpuTempHist, color: Theme.crit },
        { data: SysInfo.gpuHist,     color: Theme.accent },
    ]

    Row {
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
