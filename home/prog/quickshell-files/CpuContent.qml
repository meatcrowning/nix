import QtQuick

// CPU usage% + temperature history. Both series share a 0-100 axis — usage in
// percent, temperature in Celsius, which for this CPU stays under 100.
MetricChart {
    title: "cpu"
    series: [
        { data: SysInfo.tempHist, color: Theme.crit },   // temperature
        { data: SysInfo.cpuHist,  color: Theme.accent }, // usage, drawn on top
    ]

    Row {
        spacing: 12
        PixelText {
            text: "use " + (SysInfo.cpuUsage < 0 ? "--" : SysInfo.cpuUsage + "%")
            color: Theme.accent
        }
        PixelText {
            text: "tmp " + (SysInfo.cpuTemp < 0 ? "--" : SysInfo.cpuTemp + "C")
            color: Theme.crit
        }
    }
}
