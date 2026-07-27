import QtQuick
import Quickshell

// The task manager: the machine's load at a glance, and the processes causing
// it, with the means to end them.
//
// Three sections, top to bottom: a 4x2 block of square chart cards (cpu, gpu,
// mem, net, load, vram, swap, fan), a chassis-fan bar, and the process table
// taking everything that is left. The table is the point of the widget, so it
// gets the slack — the cards are SQUARE, i.e. their height follows the panel
// width, and a taller tile turns into more visible processes rather than
// letterboxed charts.
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
        // Secondary reading, shown to the left of the primary one on the same
        // line.
        property string sub: ""
        property color valueColor: Theme.text
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
            id: cardValue
            anchors { right: parent.right; top: parent.top }
            text: card.value
            color: card.valueColor
        }
        // The secondary reading sits to the LEFT of the primary one on the SAME
        // line, not under it: two stacked lines cost a card of this size a
        // third of its chart.
        //
        // Dropped when the three would not all fit, measured against their own
        // implicit widths rather than a guessed card width — a fixed threshold
        // was wrong for "vram 0.5G 4%", whose label and value are both wider
        // than cpu's, so it collided while the others had room.
        PixelText {
            id: cardSub
            anchors { right: cardValue.left; rightMargin: 5; top: parent.top }
            visible: card.sub.length > 0
                     && cardLabel.implicitWidth + implicitWidth
                        + cardValue.implicitWidth + 10 <= card.width
            text: card.sub
            color: Theme.textDim
        }
        ChartCanvas {
            id: plot
            active: root.active
            anchors {
                left: parent.left; right: parent.right
                top: cardValue.bottom
                topMargin: 3
                bottom: parent.bottom
            }
        }
    }

    // Eight squares, 4 x 2. Square is the point: the width is whatever the
    // panel is, so the HEIGHT follows it, and the block grows and shrinks with
    // the panel instead of the charts going letterbox at one end of the range.
    readonly property real cardW: (inner - Theme.gap * 3) / 4
    readonly property real cardH: cardW

    Grid {
        id: cards
        anchors { top: parent.top; topMargin: root.pad; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        columns: 4
        columnSpacing: Theme.gap
        rowSpacing: Theme.gap

        MetricCard {
            width: root.cardW; height: root.cardH
            label: "cpu"
            value: SysInfo.cpuUsage < 0 ? "--" : SysInfo.cpuUsage + "%"
            sub: SysInfo.cpuTemp < 0 ? "" : SysInfo.cpuTemp + "C"
            series: [
                { data: SysInfo.tempHist, color: Theme.crit },
                { data: SysInfo.cpuHist,  color: Theme.accent },
            ]
        }
        MetricCard {
            width: root.cardW; height: root.cardH
            label: "gpu"
            value: SysInfo.gpuUsage < 0 ? "--" : SysInfo.gpuUsage + "%"
            sub: SysInfo.gpuTemp < 0 ? "" : SysInfo.gpuTemp + "C"
            series: [
                { data: SysInfo.gpuTempHist, color: Theme.crit },
                { data: SysInfo.gpuHist,     color: Theme.accent },
            ]
        }
        MetricCard {
            width: root.cardW; height: root.cardH
            label: "mem"
            value: SysInfo.memUsage < 0 ? "--" : SysInfo.memUsage + "%"
            sub: SysInfo.fmtSize(SysInfo.memUsedKb)
            series: [ { data: SysInfo.memHist, color: Theme.accent } ]
        }
        MetricCard {
            width: root.cardW; height: root.cardH
            label: "net"
            value: SysInfo.fmtSpeed(SysInfo.rxSpeed)
            sub: SysInfo.fmtSpeed(SysInfo.txSpeed)
            scaleMax: 0
            autoFloor: 64 * 1024
            series: [
                { data: SysInfo.txHist, color: Theme.warn },
                { data: SysInfo.rxHist, color: Theme.info },
            ]
        }

        MetricCard {
            width: root.cardW; height: root.cardH
            label: "load"
            value: SysInfo.load1 < 0 ? "--" : SysInfo.load1.toFixed(2)
            // 16 threads on this box; a run queue past a quarter of them is
            // where it starts being something you can feel
            valueColor: SysInfo.load1 >= 8 ? Theme.crit
                      : SysInfo.load1 >= 4 ? Theme.warn : Theme.text
            scaleMax: 0
            autoFloor: 4
            series: [ { data: SysInfo.loadHist, color: Theme.accent } ]
        }
        MetricCard {
            width: root.cardW; height: root.cardH
            label: "vram"
            value: SysInfo.gpuMemUsage < 0 ? "--" : SysInfo.gpuMemUsage + "%"
            sub: SysInfo.gpuMemUsedMb < 0 ? "" : (SysInfo.gpuMemUsedMb / 1024).toFixed(1) + "G"
            valueColor: SysInfo.gpuMemUsage >= 90 ? Theme.crit : Theme.text
            series: [ { data: SysInfo.vramHist, color: Theme.accent } ]
        }
        MetricCard {
            width: root.cardW; height: root.cardH
            label: "swap"
            value: SysInfo.swapUsage < 0 ? "--" : SysInfo.swapUsage + "%"
            sub: SysInfo.swapTotalKb > 0
                 ? SysInfo.fmtSize(SysInfo.swapTotalKb - SysInfo.swapFreeKb) : ""
            valueColor: SysInfo.swapUsage >= 25 ? Theme.warn : Theme.text
            series: [ { data: SysInfo.swapHist, color: Theme.accent } ]
        }
        MetricCard {
            width: root.cardW; height: root.cardH
            label: "fan"
            // The GPU fan, as a percentage. Zero is a real reading, not a
            // missing one — this card idles at 0% because the card stops its
            // fans entirely when it is cool.
            value: SysInfo.gpuFanPct < 0 ? "--" : SysInfo.gpuFanPct + "%"
            series: [ { data: SysInfo.gpuFanHist, color: Theme.accent } ]
        }
    }

    // ---- chassis fans ----------------------------------------------------
    // A bar rather than a ninth square: it is one number with no interesting
    // history, and it belongs to the whole box rather than to one component.
    //
    // HIDDEN when nothing reports a tachometer, which is the case on `top` as
    // it stands — no Super-I/O driver is loaded for the B650's sensor chip, so
    // /sys/class/hwmon has no fan*_input at all. Drawing a permanent zero would
    // be worse than drawing nothing. It lights up by itself if that driver is
    // ever loaded.
    Item {
        id: fanBar
        anchors { top: cards.bottom; topMargin: 6; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        height: visible ? 14 : 0
        visible: SysInfo.fanCount > 0

        // 2000 rpm full scale: case fans live well under that, and a scale that
        // autoranged would make an idle machine look like it was screaming.
        readonly property real frac: Math.max(0, Math.min(1, SysInfo.fanAvgRpm / 2000))

        PixelText {
            id: fanLabel
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
            text: "fans"
            color: Theme.textDim
        }
        PixelText {
            id: fanVal
            anchors { right: parent.right; verticalCenter: parent.verticalCenter }
            text: SysInfo.fanAvgRpm + "rpm"
            color: Theme.text
        }
        Rectangle {
            anchors {
                left: fanLabel.right; leftMargin: 6
                right: fanVal.left; rightMargin: 6
                verticalCenter: parent.verticalCenter
            }
            height: 6
            color: Theme.bgAlt
            border.width: 1
            border.color: Theme.border
            Rectangle {
                anchors { left: parent.left; top: parent.top; bottom: parent.bottom; margins: 1 }
                width: Math.round((parent.width - 2) * fanBar.frac)
                color: Theme.accent
            }
        }
    }

    // ---- process table ---------------------------------------------------
    Rectangle {
        id: rule
        anchors { top: fanBar.bottom; topMargin: 5; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        height: 1
        color: Theme.border
    }

    // Column geometry, shared by the header and every row so they line up.
    // The pid column is dropped on a narrow panel rather than squeezed: at 14%
    // of the screen the process NAME is already down to a few characters, and
    // that is the column you actually read.
    readonly property bool showPid: inner >= 300
    // 58, not 44: this kernel hands out six-digit pids routinely (pid_max is
    // 4194304), and at 44 they ran straight into the process name.
    readonly property real colPid: showPid ? 58 : 0
    readonly property real colKill: 14
    readonly property real colCpu: 44
    readonly property real colMem: 44
    readonly property real colRss: 42
    readonly property real colName:
        Math.max(40, inner - colPid - colCpu - colMem - colRss - colKill)

    // A clickable column heading. Inline components have to be members of the
    // file's root object, so it is declared here rather than inside the Row.
    component Head: PixelText {
        id: head
        property string key: ""
        color: Procs.sortKey === head.key ? Theme.accent : Theme.textDim
        MouseArea {
            anchors { fill: parent; topMargin: -3; bottomMargin: -3 }
            cursorShape: Qt.PointingHandCursor
            onClicked: Procs.setSort(head.key)
        }
    }

    // Clicking a heading sorts by it. The sort lives in Procs so it survives a
    // reload along with the rows.
    Row {
        id: header
        anchors { top: rule.bottom; topMargin: 4; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        spacing: 0

        Head {
            width: root.colPid
            visible: root.showPid
            key: "pid"
            text: "pid"
        }
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
                    width: root.colPid
                    visible: root.showPid
                    text: row.modelData.pid
                    color: Theme.textDim
                }
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
            text: "reading..."
            color: Theme.textDim
        }
    }
}
