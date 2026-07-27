import QtQuick
import Quickshell

// The task manager: the machine's load at a glance, and the processes causing
// it, with the means to end them.
//
// The three history charts appear here as SPARKLINE STRIPS rather than as the
// full cpu/gpu/eth cards. At the dock's width three of those cards side by side
// would each be ~85px wide — narrower than their own legend line — so they are
// laid out one per row instead: a label, the current readout, and the same
// ChartCanvas the popups use filling whatever is left. Same data, same drawing
// code, a quarter of the height, which is the whole point: the process table is
// what this widget is FOR, so the charts must not eat the space.
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
    implicitHeight: 320

    onActiveChanged: Procs.watch(root, active)
    Component.onCompleted: Procs.watch(root, active)
    Component.onDestruction: Procs.watch(root, false)

    // ---- one metric as a label + readout + sparkline --------------------
    component SparkRow: Item {
        id: srow
        property string label: ""
        property string value: ""
        property alias series: spark.series
        property alias scaleMax: spark.scaleMax
        property alias autoFloor: spark.autoFloor
        height: 26

        PixelText {
            id: lbl
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
            width: 30
            text: srow.label
            color: Theme.accent
        }
        PixelText {
            id: val
            anchors { left: lbl.right; verticalCenter: parent.verticalCenter }
            width: 82
            text: srow.value
            color: Theme.textDim
        }
        ChartCanvas {
            id: spark
            active: root.active
            anchors {
                left: val.right; right: parent.right
                top: parent.top; bottom: parent.bottom
                topMargin: 2; bottomMargin: 2
            }
            // no frame and no midline: at 22px tall they would be most of the
            // ink on screen and the trace would be lost in them
            frame: false
            midline: false
            lineWidth: 1
        }
    }

    Column {
        id: stats
        anchors { top: parent.top; topMargin: root.pad; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        spacing: 2

        SparkRow {
            width: parent.width
            label: "cpu"
            value: (SysInfo.cpuUsage < 0 ? "--" : SysInfo.cpuUsage + "%")
                   + "  " + (SysInfo.cpuTemp < 0 ? "--" : SysInfo.cpuTemp + "C")
            series: [
                { data: SysInfo.tempHist, color: Theme.crit },
                { data: SysInfo.cpuHist,  color: Theme.accent },
            ]
        }
        SparkRow {
            width: parent.width
            label: "gpu"
            value: (SysInfo.gpuUsage < 0 ? "--" : SysInfo.gpuUsage + "%")
                   + "  " + (SysInfo.gpuTemp < 0 ? "--" : SysInfo.gpuTemp + "C")
            series: [
                { data: SysInfo.gpuTempHist, color: Theme.crit },
                { data: SysInfo.gpuHist,     color: Theme.accent },
            ]
        }
        SparkRow {
            width: parent.width
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

    // ---- process table ---------------------------------------------------
    Rectangle {
        id: rule
        anchors { top: stats.bottom; topMargin: 6; horizontalCenter: parent.horizontalCenter }
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
