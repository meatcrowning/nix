import QtQuick
import Quickshell

// The task manager: the machine's load at a glance, and the processes causing
// it, with the means to end them.
//
// Three sections, top to bottom: a 2x2 block of chart cards (cpu / gpu / mem /
// net), a two-line sensor strip for the readouts with no history worth
// plotting, and the process table taking everything that is left. The table is
// the point of the widget, so it gets the slack — the cards are CAPPED at
// roughly square rather than allowed to grow, so a taller tile turns into more
// visible processes, not bigger charts.
//
// The cards draw through the same ChartCanvas the cpu/gpu/eth popups use, so
// there is one implementation of the plot. They were thin sparkline strips
// first, to save height; tightening the dock's other widgets bought back the
// room for the real thing.
Item {
    id: root

    // Defaults to FALSE, and every host sets it: the popup passes its `open`,
    // DockTile binds it to the dock's visibility. A `true` default would mean a
    // grid tile polls once at construction, before that Binding has applied —
    // measured as a full /proc scan and a drive scan on every reload, for a
    // widget nobody was looking at.
    property bool active: false
    property int pad: 8
    readonly property real inner: Math.max(160, width - pad * 2)

    implicitWidth: 300
    implicitHeight: 360

    onActiveChanged: Procs.watch(root, active)
    Component.onCompleted: Procs.watch(root, active)
    Component.onDestruction: Procs.watch(root, false)

    function fmtUptime(s) {
        if (!s || s <= 0) return "--";
        const d = Math.floor(s / 86400);
        const h = Math.floor((s % 86400) / 3600);
        const m = Math.floor((s % 3600) / 60);
        if (d > 0) return d + "d" + h + "h";
        if (h > 0) return h + "h" + m + "m";
        return m + "m";
    }

    // ---- one metric as a card: label + readout over its history ----------
    component MetricCard: Item {
        id: card
        property string label: ""
        property string value: ""
        property alias series: plot.series
        property alias scaleMax: plot.scaleMax
        property alias autoFloor: plot.autoFloor

        PixelText {
            id: cardLabel
            anchors { left: parent.left; top: parent.top }
            text: card.label
            color: Theme.accent
        }
        PixelText {
            anchors { right: parent.right; top: parent.top }
            text: card.value
            color: Theme.textDim
        }
        ChartCanvas {
            id: plot
            active: root.active
            anchors {
                left: parent.left; right: parent.right
                top: cardLabel.bottom; topMargin: 3
                bottom: parent.bottom
            }
        }
    }

    readonly property real cardW: (inner - Theme.gap) / 2
    readonly property real cardH: Math.max(52, Math.min(cardW * 0.55, 80))

    Grid {
        id: cards
        anchors { top: parent.top; topMargin: root.pad; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        columns: 2
        columnSpacing: Theme.gap
        rowSpacing: Theme.gap

        MetricCard {
            width: root.cardW; height: root.cardH
            label: "cpu"
            value: (SysInfo.cpuUsage < 0 ? "--" : SysInfo.cpuUsage + "%")
                   + " " + (SysInfo.cpuTemp < 0 ? "--" : SysInfo.cpuTemp + "C")
            series: [
                { data: SysInfo.tempHist, color: Theme.crit },
                { data: SysInfo.cpuHist,  color: Theme.accent },
            ]
        }
        MetricCard {
            width: root.cardW; height: root.cardH
            label: "gpu"
            value: (SysInfo.gpuUsage < 0 ? "--" : SysInfo.gpuUsage + "%")
                   + " " + (SysInfo.gpuTemp < 0 ? "--" : SysInfo.gpuTemp + "C")
            series: [
                { data: SysInfo.gpuTempHist, color: Theme.crit },
                { data: SysInfo.gpuHist,     color: Theme.accent },
            ]
        }
        MetricCard {
            width: root.cardW; height: root.cardH
            label: "mem"
            value: (SysInfo.memUsage < 0 ? "--" : SysInfo.memUsage + "%")
                   + " " + SysInfo.fmtSize(SysInfo.memUsedKb)
            series: [ { data: SysInfo.memHist, color: Theme.accent } ]
        }
        MetricCard {
            width: root.cardW; height: root.cardH
            label: "net"
            value: SysInfo.fmtSpeed(SysInfo.rxSpeed) + " " + SysInfo.fmtSpeed(SysInfo.txSpeed)
            scaleMax: 0
            autoFloor: 64 * 1024
            series: [
                { data: SysInfo.txHist, color: Theme.warn },
                { data: SysInfo.rxHist, color: Theme.info },
            ]
        }
    }

    // ---- the readouts with no history worth plotting ---------------------
    component Sensor: Row {
        id: sen
        property string label: ""
        property string value: ""
        property color tint: Theme.text
        spacing: 4
        PixelText { text: sen.label; color: Theme.textDim }
        PixelText { text: sen.value; color: sen.tint }
    }

    Column {
        id: sensors
        anchors { top: cards.bottom; topMargin: 6; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        spacing: 1

        Row {
            width: parent.width
            Sensor {
                width: root.inner / 3
                label: "load"
                value: SysInfo.load1 < 0 ? "--" : SysInfo.load1.toFixed(2)
                // this box has 16 threads; a run queue past a quarter of them is
                // where it starts being something you can feel
                tint: SysInfo.load1 >= 8 ? Theme.crit
                    : SysInfo.load1 >= 4 ? Theme.warn : Theme.text
            }
            Sensor {
                width: root.inner / 3
                label: "swap"
                value: SysInfo.swapUsage < 0 ? "--" : SysInfo.swapUsage + "%"
                tint: SysInfo.swapUsage >= 25 ? Theme.warn : Theme.text
            }
            Sensor {
                width: root.inner / 3
                label: "up"
                value: root.fmtUptime(SysInfo.uptimeSec)
            }
        }
        Row {
            width: parent.width
            Sensor {
                width: root.inner / 3
                label: "vram"
                value: SysInfo.gpuMemUsage < 0 ? "--"
                     : SysInfo.gpuMemUsage + "% " + (SysInfo.gpuMemUsedMb / 1024).toFixed(1) + "G"
                tint: SysInfo.gpuMemUsage >= 90 ? Theme.crit : Theme.text
            }
            Sensor {
                width: root.inner / 3
                label: "pwr"
                value: SysInfo.gpuPowerW < 0 ? "--" : Math.round(SysInfo.gpuPowerW) + "W"
            }
            Sensor {
                width: root.inner / 3
                label: "fan"
                value: SysInfo.gpuFanPct < 0 ? "--" : SysInfo.gpuFanPct + "%"
            }
        }
    }

    // ---- process table ---------------------------------------------------
    Rectangle {
        id: rule
        anchors { top: sensors.bottom; topMargin: 5; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        height: 1
        color: Theme.border
    }

    // Column geometry, shared by the header and every row so they line up.
    readonly property real colKill: 14
    readonly property real colCpu: 44
    readonly property real colMem: 44
    readonly property real colRss: 42
    readonly property real colName: Math.max(40, inner - colCpu - colMem - colRss - colKill)

    // A clickable column heading. Inline components have to be members of the
    // file's root object, so it is declared here rather than inside the Row.
    component Head: PixelText {
        id: head
        property string key: ""
        color: Procs.sortKey === head.key ? Theme.accent : Theme.textDim
        MouseArea {
            anchors { fill: parent; topMargin: -3; bottomMargin: -3 }
            cursorShape: Qt.PointingHandCursor
            onClicked: Procs.sortKey = head.key
        }
    }

    // Clicking a heading sorts by it. The sort lives in Procs so it survives a
    // reload along with the rows.
    Row {
        id: header
        anchors { top: rule.bottom; topMargin: 4; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        spacing: 0

        Head { width: root.colName; key: "name"; text: "process" }
        Head { width: root.colCpu;  key: "cpu";  text: "cpu%"; horizontalAlignment: Text.AlignRight }
        Head { width: root.colMem;  key: "mem";  text: "mem%"; horizontalAlignment: Text.AlignRight }
        Head { width: root.colRss;  key: "mem";  text: "res";  horizontalAlignment: Text.AlignRight }
        Item { width: root.colKill; height: 1 }
    }

    ListView {
        id: list
        anchors {
            top: header.bottom; topMargin: 3
            bottom: parent.bottom; bottomMargin: root.pad
            horizontalCenter: parent.horizontalCenter
        }
        width: root.inner
        clip: true
        // The rows re-sort under the pointer every 2s; without this a flick
        // would be fighting the refresh.
        boundsBehavior: Flickable.StopAtBounds
        model: Procs.sorted
        // Reuse the delegates: the model is replaced wholesale on every poll and
        // rebuilding 60 rows twice a second is real work for no change on screen.
        reuseItems: true

        delegate: Item {
            id: row
            required property var modelData
            width: list.width
            height: 17

            Rectangle {
                anchors.fill: parent
                color: rowMa.containsMouse ? Theme.highlight : "transparent"
            }
            MouseArea {
                id: rowMa
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.NoButton
            }

            Row {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                spacing: 0

                PixelText {
                    width: root.colName
                    text: row.modelData.name
                    color: Theme.text
                    elide: Text.ElideRight
                }
                PixelText {
                    width: root.colCpu
                    horizontalAlignment: Text.AlignRight
                    text: row.modelData.cpu.toFixed(1)
                    // anything holding a core is worth spotting in a glance
                    color: row.modelData.cpu >= 50 ? Theme.crit
                         : row.modelData.cpu >= 10 ? Theme.warn : Theme.textDim
                }
                PixelText {
                    width: root.colMem
                    horizontalAlignment: Text.AlignRight
                    text: row.modelData.mem.toFixed(1)
                    color: row.modelData.mem >= 10 ? Theme.warn : Theme.textDim
                }
                PixelText {
                    width: root.colRss
                    horizontalAlignment: Text.AlignRight
                    text: Procs.fmtMem(row.modelData.rss)
                    color: Theme.textDim
                }

                // End it. Left click is SIGTERM — the same "click the [x]"
                // courtesy hyprvtb's close button extends, so the process gets to
                // save. SIGKILL is deliberately on the RIGHT button: rows re-sort
                // under the cursor every 2s, and an unrecoverable action must not
                // be one mis-timed left click away.
                Item {
                    width: root.colKill
                    height: 15
                    PixelText {
                        anchors.centerIn: parent
                        visible: rowMa.containsMouse || killMa.containsMouse
                        text: "x"
                        color: killMa.containsMouse ? Theme.crit : Theme.textDim
                    }
                    MouseArea {
                        id: killMa
                        anchors { fill: parent; margins: -2 }
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        onClicked: (mouse) => Procs.kill(row.modelData.pid,
                                                        mouse.button === Qt.RightButton)
                    }
                }
            }
        }

        PixelText {
            anchors.centerIn: parent
            visible: Procs.rows.length === 0
            text: "reading…"
            color: Theme.textDim
        }
    }
}
