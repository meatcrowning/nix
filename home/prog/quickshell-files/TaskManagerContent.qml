import QtQuick
import Quickshell

// The task manager: the machine's load at a glance, and the processes causing
// it, with the means to end them.
//
// Three sections, top to bottom: a 4x2 block of square chart cards (cpu, gpu,
// mem, net, load, vram, swap, fan — see `noGpu` for the psi/io/batt set book
// puts in the gpu/vram/fan slots instead), a chassis-fan bar, and the process table
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

    // book has no gpu, vram or fan to draw: Asahi's DRM driver publishes no
    // utilization counter, its GPU memory IS system memory, and the machine is
    // fanless. Those three slots go to psi, io and batt there instead — see
    // sysinfo.sh. Keyed on the build-time Host singleton rather than on the
    // readings being -1, so the card set is fixed before the first poll and the
    // grid can't relabel itself two seconds after it opens.
    readonly property bool noGpu: Host.name === "air"

    implicitWidth: 300
    implicitHeight: 360

    // Handing the keyboard back is not optional: the dock closing (or this
    // widget being torn down by a reload) while the filter box still held focus
    // would leave the bar's layer holding a keyboard grab with nothing on screen
    // to type into.
    onActiveChanged: {
        Procs.watch(root, active);
        if (!active) {
            filterInput.focus = false;
            Procs.filterFocus = false;
            Procs.filterHover = false;
            Procs.filterLatch = false;
        }
    }
    Component.onCompleted: Procs.watch(root, active)
    Component.onDestruction: {
        Procs.watch(root, false);
        Procs.filterFocus = false;
        Procs.filterLatch = false;
    }

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
        // Hover text. These labels are four characters of jargon each — "psi",
        // "vram", "res" — and the card cannot say what it is measuring in the
        // space it has, so it says it here instead.
        property string tip: ""
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
        // Hover anywhere on the card, chart included. HoverHandler rather than a
        // MouseArea so it cannot eat a click the card might want later.
        HoverHandler { id: cardHover }
        Tooltip {
            target: card
            show: cardHover.hovered && card.tip !== "" && card.visible
            text: card.tip
        }

        ChartCanvas {
            id: plot
            // Both card sets are instantiated and the unused three are hidden
            // (a Grid lays out only its visible children), so gate the canvas on
            // visibility too — otherwise the hidden trio repaints every poll.
            active: root.active && card.visible
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
            tip: "busy time across all cores, sampled every poll\nred: package temperature"
            value: SysInfo.cpuUsage < 0 ? "--" : SysInfo.cpuUsage + "%"
            sub: SysInfo.cpuTemp < 0 ? "" : SysInfo.cpuTemp + "C"
            series: [
                { data: SysInfo.tempHist, color: Theme.crit },
                { data: SysInfo.cpuHist,  color: Theme.accent },
            ]
        }
        MetricCard {
            width: root.cardW; height: root.cardH
            visible: !root.noGpu
            label: "gpu"
            tip: "nvidia-smi utilization\nred: gpu temperature"
            value: SysInfo.gpuUsage < 0 ? "--" : SysInfo.gpuUsage + "%"
            sub: SysInfo.gpuTemp < 0 ? "" : SysInfo.gpuTemp + "C"
            series: [
                { data: SysInfo.gpuTempHist, color: Theme.crit },
                { data: SysInfo.gpuHist,     color: Theme.accent },
            ]
        }
        // In the gpu slot on book: pressure stall, the share of the last 10s in
        // which something was blocked waiting for cpu / io / memory. Unlike
        // utilization it says whether the machine is actually costing you time —
        // a pegged cpu with nothing waiting on it reads 0 here. Three series,
        // cpu on top because it is the one the readout shows.
        MetricCard {
            width: root.cardW; height: root.cardH
            visible: root.noGpu
            label: "psi"
            tip: "pressure stall: share of the last 10s spent\nwaiting on cpu (blue), disk io (amber), memory (red)"
            value: SysInfo.psiCpu < 0 ? "--" : SysInfo.psiCpu.toFixed(1) + "%"
            sub: SysInfo.psiIo < 0 ? "" : "io" + SysInfo.psiIo.toFixed(0)
            valueColor: SysInfo.psiCpu >= 50 ? Theme.crit
                      : SysInfo.psiCpu >= 20 ? Theme.warn : Theme.text
            // Autoscaled off a floor of 20%: a desktop sits in the low single
            // digits, so a fixed 0-100 axis would draw a permanent flat line.
            scaleMax: 0
            autoFloor: 20
            series: [
                { data: SysInfo.psiMemHist, color: Theme.crit },
                { data: SysInfo.psiIoHist,  color: Theme.warn },
                { data: SysInfo.psiCpuHist, color: Theme.accent },
            ]
        }
        MetricCard {
            width: root.cardW; height: root.cardH
            label: "mem"
            tip: "memory in use: total minus MemAvailable,\ni.e. what a new allocation could not have"
            value: SysInfo.memUsage < 0 ? "--" : SysInfo.memUsage + "%"
            sub: SysInfo.fmtSize(SysInfo.memUsedKb)
            series: [ { data: SysInfo.memHist, color: Theme.accent } ]
        }
        MetricCard {
            width: root.cardW; height: root.cardH
            label: "net"
            tip: "network throughput\nblue: down (the readout)   amber: up"
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
            tip: "load average over 1 minute:\nthreads running or waiting for a core"
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
            visible: !root.noGpu
            label: "vram"
            tip: "gpu memory in use, and how much of it"
            value: SysInfo.gpuMemUsage < 0 ? "--" : SysInfo.gpuMemUsage + "%"
            sub: SysInfo.gpuMemUsedMb < 0 ? "" : (SysInfo.gpuMemUsedMb / 1024).toFixed(1) + "G"
            valueColor: SysInfo.gpuMemUsage >= 90 ? Theme.crit : Theme.text
            series: [ { data: SysInfo.vramHist, color: Theme.accent } ]
        }
        // In the vram slot on book: disk throughput, drawn exactly like the net
        // card next to it — read as the primary reading, write as the secondary,
        // both autoscaled together off a shared floor so the two lines stay
        // comparable to each other.
        MetricCard {
            width: root.cardW; height: root.cardH
            visible: root.noGpu
            label: "io"
            tip: "disk throughput across the physical drives\nblue: read (the readout)   amber: write"
            value: SysInfo.fmtSpeed(SysInfo.dskRead)
            sub: SysInfo.fmtSpeed(SysInfo.dskWrite)
            scaleMax: 0
            autoFloor: 1024 * 1024
            series: [
                { data: SysInfo.dskWHist, color: Theme.warn },
                { data: SysInfo.dskRHist, color: Theme.info },
            ]
        }
        MetricCard {
            width: root.cardW; height: root.cardH
            label: "swap"
            tip: "swap in use; anything sustained here\nmeans the machine is short of memory"
            value: SysInfo.swapUsage < 0 ? "--" : SysInfo.swapUsage + "%"
            sub: SysInfo.swapTotalKb > 0
                 ? SysInfo.fmtSize(SysInfo.swapTotalKb - SysInfo.swapFreeKb) : ""
            valueColor: SysInfo.swapUsage >= 25 ? Theme.warn : Theme.text
            series: [ { data: SysInfo.swapHist, color: Theme.accent } ]
        }
        MetricCard {
            width: root.cardW; height: root.cardH
            visible: !root.noGpu
            label: "fan"
            tip: "gpu fan speed. 0% is a real reading -\nthe card stops its fans when it is cool"
            // The GPU fan, as a percentage. Zero is a real reading, not a
            // missing one — this card idles at 0% because the card stops its
            // fans entirely when it is cool.
            value: SysInfo.gpuFanPct < 0 ? "--" : SysInfo.gpuFanPct + "%"
            series: [ { data: SysInfo.gpuFanHist, color: Theme.accent } ]
        }
        // In the fan slot on book: the BATTERY — charge over the last hour, with
        // the wattage kept as the secondary reading.
        //
        // This slot held whole-machine watts first, on the reasoning that it is
        // what a fanless box has in place of a fan gauge. But "how hard is it
        // working" is already the cpu, psi and io cards' job three times over,
        // while on a laptop the one question none of them answer is how long it
        // has left — which is a slope, and therefore exactly the thing a graph
        // says better than a number. The watts did not have to be given up for
        // it: they are the sub reading, next to the state in words ("chg", "ac",
        // "full"), so the card still shows the draw AND says which way it is
        // pushing the line.
        //
        // CHARGING is called twice, deliberately. The sub line is the one the
        // card drops when the three readings won't fit (MetricCard.sub), and a
        // panel dragged narrow is exactly when you'd still want to know you are
        // plugged in — so the percentage itself carries a "+" as well, on the
        // line that is never dropped, and the readout goes Theme.info with it.
        //
        // FIXED 0-100 axis, and no arithmetic on a capacity that could be zero:
        // this is the one card that must not autoscale, or a battery sitting at
        // 96% would be drawn against a 96% ceiling and read as full-to-empty.
        // With no battery found at all (a desktop, or a node named something
        // nobody predicted) `batteryPct` is -1: the readout is "--", the history
        // stays empty and the plot draws its frame with no line in it — the same
        // way every other card here reports a sensor it hasn't got.
        MetricCard {
            width: root.cardW; height: root.cardH
            visible: root.noGpu
            label: "batt"
            tip: "battery charge, one sample per 40s (an hour across).\n+ and \"chg\" mean charging; \"ac\" is plugged in but idle"
            value: SysInfo.batteryPct < 0 ? "--"
                   : (SysInfo.batteryStatus === 2 ? "+" : "") + SysInfo.batteryPct + "%"
            sub: SysInfo.batteryLabel
            // Charging outranks the level: 15% and climbing is not a warning.
            valueColor: SysInfo.batteryPct < 0 ? Theme.text
                      : SysInfo.batteryStatus === 2 ? Theme.info
                      : SysInfo.batteryPct <= 10 ? Theme.crit
                      : SysInfo.batteryPct <= 20 ? Theme.warn : Theme.text
            series: [ { data: SysInfo.batteryHist, color: Theme.accent } ]
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

    // ---- filter box ------------------------------------------------------
    // Substring match on name or pid, live as you type. The panel's layer
    // surface takes the keyboard ONLY while this box holds it (Procs.filterFocus,
    // read in shell.qml): a bar that were always focusable would swallow the
    // keystroke you meant for the window you were working in. Escape clears and
    // hands it straight back.
    Rectangle {
        id: filterBox
        anchors { top: fanBar.bottom; topMargin: 6; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        height: 19
        color: Theme.bgAlt
        border.width: 1
        border.color: filterInput.activeFocus ? Theme.accent : Theme.border

        PixelText {
            id: filterIcon
            anchors { left: parent.left; leftMargin: 5; verticalCenter: parent.verticalCenter }
            text: "/"
            color: filterInput.activeFocus ? Theme.accent : Theme.textDim
        }
        TextInput {
            id: filterInput
            anchors {
                left: filterIcon.right; leftMargin: 5
                right: filterClear.left; rightMargin: 5
                verticalCenter: parent.verticalCenter
            }
            // A TextInput is not a Text, so it inherits none of PixelText's
            // settings and would rasterise the pixel font through the
            // distance-field path — blurry, next to a panel of crisp text.
            font.family: Theme.font
            font.pixelSize: Theme.fontSize
            font.hintingPreference: Font.PreferFullHinting
            renderType: Text.NativeRendering
            color: Theme.text
            selectionColor: Theme.accent
            selectedTextColor: Theme.bg
            clip: true
            text: Procs.filter
            onTextEdited: Procs.setFilter(text)
            // The window is only ACTIVE while this layer surface holds the
            // wl_keyboard, so losing activeFocus is how the box hears that the
            // user clicked into a window or onto the desktop — the compositor
            // moved the keyboard and never told the panel anything else. Drop
            // the item's own focus with it, or the caret silently comes back
            // the next time the pointer crosses the box.
            onActiveFocusChanged: {
                Procs.filterFocus = activeFocus;
                if (!activeFocus) filterInput.focus = false;
            }
            Keys.onEscapePressed: {
                Procs.setFilter("");
                filterInput.focus = false;
            }
            PixelText {
                anchors.fill: parent
                visible: filterInput.text === "" && !filterInput.activeFocus
                text: "filter"
                color: Theme.textDim
            }
        }
        // How much of the machine the filter is hiding, and the click target
        // that clears it. Only while filtering — with an empty box the table is
        // the whole list and the count would be noise.
        PixelText {
            id: filterClear
            anchors { right: parent.right; rightMargin: 5; verticalCenter: parent.verticalCenter }
            visible: Procs.filter !== ""
            text: Procs.sorted.length + "/" + Procs.total + " x"
            color: clearMa.containsMouse ? Theme.crit : Theme.textDim
            MouseArea {
                id: clearMa
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: { Procs.setFilter(""); filterInput.focus = false; }
            }
        }
        // Click anywhere in the box to type. z below the clear button so it
        // doesn't swallow that click. Hover ARMS the layer's keyboard focus (see
        // shell.qml) — the compositor grants it on the click, so it has to be
        // offered before the click, not from inside its handler.
        MouseArea {
            anchors.fill: parent
            z: -1
            hoverEnabled: true
            cursorShape: Qt.IBeamCursor
            // Hovering ARMS the layer's keyboard focus and LATCHES it. The
            // compositor grants the keyboard on the next pointer motion over
            // the surface, so it has to be offered before the pointer gets
            // here; the latch is what defers giving it back until the pointer
            // has left the bar, which is the only place that is safe.
            onEntered: { Procs.filterHover = true; Procs.filterLatch = true; }
            onExited: Procs.filterHover = false
            onClicked: filterInput.forceActiveFocus()
        }
    }

    // "Give the keyboard back" from anywhere else in the panel (shell.qml's
    // catcher). A counter rather than a call, because this widget is behind an
    // asynchronous Loader and there is nothing stable to reach into.
    Connections {
        target: Procs
        function onBlurSeqChanged() { filterInput.focus = false; }
    }

    // ---- process table ---------------------------------------------------
    Rectangle {
        id: rule
        anchors { top: filterBox.bottom; topMargin: 5; horizontalCenter: parent.horizontalCenter }
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

        // process name first, then pid: the name is what you scan for, and the
        // pid is a detail about the row you already found. The numeric columns
        // stay grouped on the right, so pid sits between them and the name.
        Head { width: root.colName; key: "name"; text: "process" }
        Head {
            width: root.colPid
            visible: root.showPid
            key: "pid"
            text: "pid"
            horizontalAlignment: Text.AlignRight
            // keeps the number off cpu%'s left edge, which is right-aligned too
            rightPadding: 6
        }
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
                    width: root.colPid
                    visible: root.showPid
                    horizontalAlignment: Text.AlignRight
                    rightPadding: 6
                    text: row.modelData.pid
                    color: Theme.textDim
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
