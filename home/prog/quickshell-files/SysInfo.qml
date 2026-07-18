pragma Singleton
import Quickshell
import Quickshell.Io
import QtQuick

// Polls system state on a timer and exposes it to the panel widgets.
Singleton {
    id: root

    property real   rxSpeed: 0          // bytes/s
    property real   txSpeed: 0
    property int    diskFreeKb: 0
    property int    diskUsePct: 0
    property int    volume: -1          // 0-100, or -1 when unavailable
    property bool   muted: false
    property int    cpuUsage: -1        // 0-100, or -1 until the second poll
    property int    cpuTemp: -1         // Celsius, k10temp's Tctl reading, or -1

    // Brightness (DDC/CI over I2C via ddcutil — this monitor is external,
    // no laptop backlight). Polled separately from everything else below:
    // ddcutil takes ~1.5s per call, far too slow for the 2s main poll.
    // adjustBrightness() updates this optimistically so scrolling feels
    // instant; the periodic poll here just corrects for drift (e.g. the
    // monitor's own physical buttons).
    property int    brightness: -1      // 0-100, or -1 until first poll

    // throughput history for the sparkline (bytes/s totals)
    property var history: []
    readonly property int historyLen: 24

    property real _prevRx: -1
    property real _prevTx: -1
    property real _prevCpuTotal: -1
    property real _prevCpuIdle: -1
    readonly property real intervalSec: 2

    readonly property string scriptPath:
        Qt.resolvedUrl("scripts/sysinfo.sh").toString().replace("file://", "")

    function parse(text) {
        const line = (text || "").trim();
        if (line === "") return;
        const f = line.split("|");
        if (f.length < 9) return;

        const rx      = parseFloat(f[0]) || 0;
        const tx      = parseFloat(f[1]) || 0;
        diskFreeKb    = parseInt(f[2]) || 0;
        diskUsePct    = parseInt(f[3]) || 0;
        volume        = parseInt(f[4]);
        muted         = f[5] === "1";

        const cpuTotal = parseFloat(f[6]) || 0;
        const cpuIdle  = parseFloat(f[7]) || 0;
        if (_prevCpuTotal >= 0) {
            const dTotal = cpuTotal - _prevCpuTotal;
            const dIdle  = cpuIdle - _prevCpuIdle;
            cpuUsage = dTotal > 0 ? Math.round(100 * (1 - dIdle / dTotal)) : 0;
        }
        _prevCpuTotal = cpuTotal;
        _prevCpuIdle  = cpuIdle;

        const rawTemp = parseInt(f[8]);
        cpuTemp = rawTemp < 0 ? -1 : Math.round(rawTemp / 1000);

        if (_prevRx >= 0) {
            rxSpeed = Math.max(0, (rx - _prevRx) / intervalSec);
            txSpeed = Math.max(0, (tx - _prevTx) / intervalSec);
            const h = history.slice();
            h.push(rxSpeed + txSpeed);
            while (h.length > historyLen) h.shift();
            history = h;
        }
        _prevRx = rx;
        _prevTx = tx;
    }

    // Human-readable bytes/s -> e.g. "1.2M", "34K", "0"
    function fmtSpeed(bps) {
        if (bps < 1024) return "0";
        if (bps < 1024 * 1024) return Math.round(bps / 1024) + "K";
        return (bps / 1024 / 1024).toFixed(1) + "M";
    }

    function fmtSize(kb) {
        if (kb < 1024 * 1024) return Math.round(kb / 1024) + "M";
        return (kb / 1024 / 1024).toFixed(0) + "G";
    }

    // Scroll-to-adjust from the panel. wpctl is fast (~8ms measured) so this
    // just fires straight through per tick, same as the media-key binds
    // (hypr/hyprland.lua) — 5%-per-tick steps, -l 1 caps at 100%.
    function adjustVolume(step) {
        if (volume < 0) volume = 50;
        volume = Math.max(0, Math.min(100, volume + step));
        Quickshell.execDetached(["wpctl", "set-volume", "-l", "1", "@DEFAULT_AUDIO_SINK@",
            Math.abs(step) + "%" + (step >= 0 ? "+" : "-")]);
        Osd.trigger("volume");
    }

    // Optimistic local update (instant panel feedback) + a debounced actual
    // ddcutil write — see the brightness property doc above for why.
    //
    // ddcBusy mutually excludes the periodic read poll and the write below,
    // as a defensive measure against overlapping I2C/DDC transactions (the
    // actual bug found live was elsewhere — Osd.qml independently re-read
    // brightness via a stale/broken command and clobbered this property
    // right before the debounced write picked it up — but two ddcutil
    // calls racing the same I2C bus is still worth avoiding on its own).
    property bool ddcBusy: false

    function adjustBrightness(step) {
        if (brightness < 0) brightness = 50;
        brightness = Math.max(0, Math.min(100, brightness + step));
        Osd.trigger("brightness");
        // Leading-edge fire: a single tick after being idle writes
        // immediately (0ms artificial delay — ddcutil itself is still
        // ~1.5s, a hard DDC/I2C protocol limit, not something software can
        // speed up). Only coalesce into the trailing debounce when a write
        // is already in flight or another tick landed within the last
        // debounce window, so rapid scrolling still doesn't stack up
        // several overlapping slow calls.
        if (ddcBusy || brightnessWriteDebounce.running) {
            brightnessWriteDebounce.restart();
        } else {
            fireBrightnessWrite();
        }
    }

    function fireBrightnessWrite() {
        ddcBusy = true;
        ddcutilWriteProc.command = ["ddcutil", "setvcp", "10", String(root.brightness)];
        ddcutilWriteProc.running = true;
    }

    Timer {
        id: brightnessWriteDebounce
        interval: 300
        repeat: false
        onTriggered: {
            if (ddcBusy) { brightnessWriteDebounce.restart(); return; }
            fireBrightnessWrite();
        }
    }

    Process {
        id: ddcutilWriteProc
        onExited: ddcBusy = false
    }

    Process {
        id: ddcutilProc
        command: ["ddcutil", "getvcp", "10", "--brief"]
        onExited: ddcBusy = false
        stdout: StdioCollector {
            onStreamFinished: {
                // "VCP 10 C <current> <max>"
                const parts = text.trim().split(/\s+/);
                if (parts.length >= 4) {
                    const v = parseInt(parts[3]);
                    if (!isNaN(v)) root.brightness = v;
                }
            }
        }
    }

    Timer {
        interval: 30000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: {
            if (ddcBusy) return;
            ddcBusy = true;
            ddcutilProc.running = true;
        }
    }

    Process {
        id: proc
        command: ["sh", root.scriptPath]
        stdout: StdioCollector {
            onStreamFinished: root.parse(this.text)
        }
    }

    Timer {
        interval: root.intervalSec * 1000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: proc.running = true
    }
}
