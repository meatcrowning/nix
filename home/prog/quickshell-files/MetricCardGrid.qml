import QtQuick

// The 4x2 block of square metric cards, extracted from TaskManagerContent so the
// book-only top-mirror drawer (TopProcDrawer) can show the SAME grid sourced from
// `top` over the tailnet instead of the local machine. One implementation of the
// card set, so book's own tile and the mirror of top's cannot drift apart.
//
//   src         a SysInfo-shaped data object — SysInfo itself, or TopStats for
//               the mirror. Every reading and both fmt* helpers come off it.
//   noGpu       picks the card set: false = cpu/gpu/mem/net/load/vram/swap/fan
//               (a machine with an nvidia GPU, i.e. `top`); true = book's
//               psi/io/batt substitutes in the gpu/vram/fan slots.
//   wheelTarget receives the fan card's brightness scroll. NULL disables it — a
//               mirror of top must never drive book's backlight from top's fan
//               card, and top's SysInfo would be the wrong target anyway.
//
// Content components stretch and gate on `active` per quickshell-files/AGENTS.md
// ("One widget, two places"); every reading is `--` until its source reports.
Item {
    id: root

    property bool active: false
    // The data source. SysInfo or TopStats — same property/method surface.
    property var src: null
    property bool noGpu: false
    // null: the fan card does not scroll. Otherwise the object whose
    // adjustBrightness(step) the wheel drives (SysInfo).
    property var wheelTarget: null
    property int pad: 8
    readonly property real inner: Math.max(160, width - pad * 2)

    // Eight squares, 4 x 2. Square is the point: the width is whatever it is
    // given, so the HEIGHT follows it, and the block grows and shrinks instead
    // of the charts going letterbox at one end of the range.
    readonly property real cardW: (inner - Theme.gap * 3) / 4
    readonly property real cardH: cardW

    implicitWidth: 300
    implicitHeight: cards.implicitHeight

    // Every fan, reduced to lines, a headline and a tooltip. A plain object, not
    // a singleton: it is pure derivation over the source's readings, and keeping
    // it out of the data layer is what lets tools/fan-harness.sh drive it
    // offscreen with synthetic fan sets.
    Fans {
        id: fans
        rows: root.src ? root.src.fans : []
        hist: root.src ? root.src.fanPctHist : ({})
        varied: root.src ? root.src.fanVaried : ({})
        showFixed: SettingsStore.d.fanShowFixed
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
        // Optional wheel stepper, null on every card that has none. Same two
        // signals and the same semantics as StatusPanel's Stat, so a card and a
        // status row scroll identically: NOTCH-based via WheelNotch (a coast
        // must not walk a value to 0), and a multi-notch burst is COLLAPSED to
        // one call rather than replayed — at most one subprocess spawn per
        // event by construction, which is what keeps a flick off the ~1.5s DDC
        // write. The card stays generic: what a step does is the caller's.
        property var onWheelUp: null
        property var onWheelDown: null

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
        // The wheel zone. `acceptedButtons: Qt.NoButton` is what keeps the rule
        // above intact — a MouseArea is the only way to reach `onWheel` here,
        // but with no buttons accepted it still declines every press, so the
        // card is exactly as clickable as it was before.
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.NoButton
            enabled: card.onWheelUp !== null || card.onWheelDown !== null
            WheelNotch { id: cardNotch }
            onWheel: (wheel) => {
                const n = cardNotch.steps(wheel);
                if (n > 0) { if (card.onWheelUp) card.onWheelUp(); }
                else if (n < 0) { if (card.onWheelDown) card.onWheelDown(); }
            }
        }
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

    Grid {
        id: cards
        anchors { top: parent.top; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        columns: 4
        columnSpacing: Theme.gap
        rowSpacing: Theme.gap

        MetricCard {
            width: root.cardW; height: root.cardH
            label: "cpu"
            tip: "busy time across all cores, sampled every poll\nred: package temperature"
            value: root.src.cpuUsage < 0 ? "--" : root.src.cpuUsage + "%"
            sub: root.src.cpuTemp < 0 ? "" : root.src.cpuTemp + "C"
            series: [
                { data: root.src.tempHist, color: Theme.crit },
                { data: root.src.cpuHist,  color: Theme.accent },
            ]
        }
        MetricCard {
            width: root.cardW; height: root.cardH
            visible: !root.noGpu
            label: "gpu"
            tip: "nvidia-smi utilization\nred: gpu temperature"
            value: root.src.gpuUsage < 0 ? "--" : root.src.gpuUsage + "%"
            sub: root.src.gpuTemp < 0 ? "" : root.src.gpuTemp + "C"
            series: [
                { data: root.src.gpuTempHist, color: Theme.crit },
                { data: root.src.gpuHist,     color: Theme.accent },
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
            value: root.src.psiCpu < 0 ? "--" : root.src.psiCpu.toFixed(1) + "%"
            sub: root.src.psiIo < 0 ? "" : "io" + root.src.psiIo.toFixed(0)
            valueColor: root.src.psiCpu >= 50 ? Theme.crit
                      : root.src.psiCpu >= 20 ? Theme.warn : Theme.text
            // Autoscaled off a floor of 20%: a desktop sits in the low single
            // digits, so a fixed 0-100 axis would draw a permanent flat line.
            scaleMax: 0
            autoFloor: 20
            series: [
                { data: root.src.psiMemHist, color: Theme.crit },
                { data: root.src.psiIoHist,  color: Theme.warn },
                { data: root.src.psiCpuHist, color: Theme.accent },
            ]
        }
        MetricCard {
            width: root.cardW; height: root.cardH
            label: "mem"
            tip: "memory in use: total minus MemAvailable,\ni.e. what a new allocation could not have"
            value: root.src.memUsage < 0 ? "--" : root.src.memUsage + "%"
            sub: root.src.fmtSize(root.src.memUsedKb)
            series: [ { data: root.src.memHist, color: Theme.accent } ]
        }
        MetricCard {
            width: root.cardW; height: root.cardH
            label: "net"
            tip: "network throughput\nblue: down (the readout)   amber: up"
            value: root.src.fmtSpeed(root.src.rxSpeed)
            sub: root.src.fmtSpeed(root.src.txSpeed)
            scaleMax: 0
            autoFloor: 64 * 1024
            series: [
                { data: root.src.txHist, color: Theme.warn },
                { data: root.src.rxHist, color: Theme.info },
            ]
        }

        MetricCard {
            width: root.cardW; height: root.cardH
            label: "load"
            tip: "load average over 1 minute:\nthreads running or waiting for a core"
            value: root.src.load1 < 0 ? "--" : root.src.load1.toFixed(2)
            // 16 threads on this box; a run queue past a quarter of them is
            // where it starts being something you can feel
            valueColor: root.src.load1 >= 8 ? Theme.crit
                      : root.src.load1 >= 4 ? Theme.warn : Theme.text
            scaleMax: 0
            autoFloor: 4
            series: [ { data: root.src.loadHist, color: Theme.accent } ]
        }
        MetricCard {
            width: root.cardW; height: root.cardH
            visible: !root.noGpu
            label: "vram"
            tip: "gpu memory in use, and how much of it"
            value: root.src.gpuMemUsage < 0 ? "--" : root.src.gpuMemUsage + "%"
            sub: root.src.gpuMemUsedMb < 0 ? "" : (root.src.gpuMemUsedMb / 1024).toFixed(1) + "G"
            valueColor: root.src.gpuMemUsage >= 90 ? Theme.crit : Theme.text
            series: [ { data: root.src.vramHist, color: Theme.accent } ]
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
            value: root.src.fmtSpeed(root.src.dskRead)
            sub: root.src.fmtSpeed(root.src.dskWrite)
            scaleMax: 0
            autoFloor: 1024 * 1024
            series: [
                { data: root.src.dskWHist, color: Theme.warn },
                { data: root.src.dskRHist, color: Theme.info },
            ]
        }
        MetricCard {
            width: root.cardW; height: root.cardH
            label: "swap"
            tip: "swap in use; anything sustained here\nmeans the machine is short of memory"
            value: root.src.swapUsage < 0 ? "--" : root.src.swapUsage + "%"
            sub: root.src.swapTotalKb > 0
                 ? root.src.fmtSize(root.src.swapTotalKb - root.src.swapFreeKb) : ""
            valueColor: root.src.swapUsage >= 25 ? Theme.warn : Theme.text
            series: [ { data: root.src.swapHist, color: Theme.accent } ]
        }
        MetricCard {
            width: root.cardW; height: root.cardH
            visible: !root.noGpu
            label: "fan"
            // EVERY fan in the box, one line each — the chassis and cooler fans
            // from hwmon plus the GPU fan. The readout is the FASTEST fan going;
            // see Fans.qml for what that percentage is and is not.
            tip: "every fan, brightest line first. the readout is the\n"
                 + "fastest going - percent of each fan's own full scale\n"
                 + "(commanded pwm duty for the chassis fans), not of a\n"
                 + "maximum rpm, which sysfs does not publish\n\n"
                 + fans.detail
                 + "\n\na fan pinned at full that has never once been seen to\n"
                 + "move is not shown at all - it says nothing about load.\n"
                 + "a fan that STOPS reappears, marked, since that is the\n"
                 + "one thing hiding it would cost you"
                 + (root.wheelTarget ? "\n\nscroll: screen brightness" : "")
            // A STOPPED fixed-speed fan takes the card over (docs/DESIGN.md 3.5):
            // the readout goes crit AND the secondary reading is replaced by the
            // fan's name.
            value: fans.headline
            sub: (root.src.fanAlarm !== undefined && root.src.fanAlarm !== "")
                 ? root.src.fanAlarm + "!" : fans.subline
            valueColor: (root.src.fanAlarm !== undefined && root.src.fanAlarm !== "")
                        ? Theme.crit : Theme.text
            scaleMax: 100
            series: fans.series
            // Scrolling this card is screen brightness — but only where a target
            // is given. The mirror leaves it null: scrolling top's fan card must
            // not move book's backlight.
            onWheelUp: root.wheelTarget
                       ? () => root.wheelTarget.adjustBrightness(SettingsStore.d.brightnessStep) : null
            onWheelDown: root.wheelTarget
                       ? () => root.wheelTarget.adjustBrightness(-SettingsStore.d.brightnessStep) : null
        }
        // In the fan slot on book: the BATTERY — charge over the last hour, with
        // the wattage kept as the secondary reading. See TaskManagerContent's
        // history for why this slot is a battery and not whole-machine watts.
        MetricCard {
            width: root.cardW; height: root.cardH
            visible: root.noGpu
            label: "batt"
            tip: "battery charge, one sample per 40s (an hour across).\n+ and \"chg\" mean charging; \"ac\" is plugged in but idle"
            value: root.src.batteryPct < 0 ? "--"
                   : (root.src.batteryStatus === 2 ? "+" : "") + root.src.batteryPct + "%"
            sub: root.src.batteryLabel
            // Charging outranks the level: 15% and climbing is not a warning.
            valueColor: root.src.batteryPct < 0 ? Theme.text
                      : root.src.batteryStatus === 2 ? Theme.info
                      : root.src.batteryPct <= 10 ? Theme.crit
                      : root.src.batteryPct <= 20 ? Theme.warn : Theme.text
            series: [ { data: root.src.batteryHist, color: Theme.accent } ]
        }
    }
}
