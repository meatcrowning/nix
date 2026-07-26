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
    property int    cpuTemp: -1         // Celsius, k10temp's Tctl (or book's Battery Hotspot fallback), or -1
    property int    gpuUsage: -1        // 0-100, nvidia-smi utilization, or -1 (no nvidia-smi, e.g. book)
    property int    gpuTemp: -1         // Celsius, nvidia-smi temperature, or -1 (no nvidia-smi, e.g. book)
    property int    batteryPct: -1      // 0-100, or -1 when no BAT*/macsmc-battery node (desktop)
    property bool   batteryCharging: false

    // Brightness. On a machine with a real panel backlight (laptops) this
    // goes through brightnessctl against /sys/class/backlight, which is
    // fast. Otherwise it falls back to DDC/CI over I2C via ddcutil for an
    // external monitor, which takes ~1.5s per call — far too slow for the
    // 2s main poll, hence the separate polling/debounce machinery below.
    // adjustBrightness() updates this optimistically so scrolling feels
    // instant; the periodic poll here just corrects for drift (e.g. the
    // monitor's own physical buttons).
    property int    brightness: -1      // 0-100, or -1 until first poll
    // Which brightness backend to drive. "auto" uses whatever was detected at
    // startup (_hasBacklight); the Settings "brightness backend" override forces
    // backlight (brightnessctl) or ddc (ddcutil) regardless of detection.
    property bool   _hasBacklight: false
    readonly property bool useBacklight: {
        const be = SettingsStore.d.brightnessBackend;
        return be === "backlight" ? true : be === "ddc" ? false : _hasBacklight;
    }

    // "Negative brightness". Once the hardware is at 0 and the user keeps
    // lowering, the extra steps come out of the compositor's gamma ramp
    // instead (hyprsunset), so the screen can go darker than the monitor
    // alone allows. 100 = no gamma reduction = the feature is off; anything
    // below means we're in the negative region and the panel/OSD read out a
    // negative level (gamma 80 -> "-20"). SettingsApply owns the hyprsunset
    // process and pushes this value to it — including killing it (which
    // restores the normal ramp) the moment we return to 100.
    //
    // The level is PERSISTED (SettingsStore.d.gammaLevel), so it survives a
    // panel reload — a theme change or an agent's Theme.qml bump rebuilds the
    // whole QML tree, and a plain `property int gamma: 100` here meant the
    // screen jumped back to full brightness every time. Read-only on purpose:
    // adjustGamma() writes the store, and the binding brings the new value
    // back, so there is exactly one copy of this state. Clamped to the current
    // floor on the way in, so raising the floor (or setting it to 100, which
    // disables the feature) takes effect on an already-negative screen.
    readonly property int gamma: {
        const floor = Math.max(5, Math.min(100, SettingsStore.d.gammaFloor));
        return Math.max(floor, Math.min(100, SettingsStore.d.gammaLevel));
    }
    readonly property bool negativeBrightness: gamma < 100
    // Signed level for display: the hardware value normally, gamma-below-100
    // once negative.
    readonly property int brightnessLevel: gamma < 100 ? gamma - 100 : brightness

    // throughput history for the sparkline (bytes/s totals)
    property var history: []
    readonly property int historyLen: 24

    // Longer per-metric ring buffers for the hover line charts (CpuPanel,
    // EthPanel). chartLen samples * intervalSec = window; 90 * 2s = 3 min.
    readonly property int chartLen: 90
    property var cpuHist: []
    property var tempHist: []
    property var gpuHist: []
    property var gpuTempHist: []
    property var rxHist: []
    property var txHist: []

    function _pushHist(arr, v) {
        const h = arr.slice();
        h.push(v);
        while (h.length > chartLen) h.shift();
        return h;
    }

    property real _prevRx: -1
    property real _prevTx: -1
    property real _prevCpuTotal: -1
    property real _prevCpuIdle: -1
    readonly property real intervalSec: SettingsStore.d.monPollSec

    readonly property string scriptPath:
        Qt.resolvedUrl("scripts/sysinfo.sh").toString().replace("file://", "")

    function parse(text) {
        const line = (text || "").trim();
        if (line === "") return;
        const f = line.split("|");
        if (f.length < 13) return;

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

        const gu = parseInt(f[9]);
        gpuUsage = isNaN(gu) || gu < 0 ? -1 : gu;
        const gt = parseInt(f[10]);
        gpuTemp = isNaN(gt) || gt < 0 ? -1 : gt;

        const bp = parseInt(f[11]);
        batteryPct = isNaN(bp) || bp < 0 ? -1 : bp;
        batteryCharging = f[12] === "1";

        if (_prevRx >= 0) {
            rxSpeed = Math.max(0, (rx - _prevRx) / intervalSec);
            txSpeed = Math.max(0, (tx - _prevTx) / intervalSec);
            const h = history.slice();
            h.push(rxSpeed + txSpeed);
            while (h.length > historyLen) h.shift();
            history = h;
            rxHist = _pushHist(rxHist, rxSpeed);
            txHist = _pushHist(txHist, txSpeed);
        }
        _prevRx = rx;
        _prevTx = tx;

        // CPU/temp history for the hover charts (cpuUsage/cpuTemp are set above)
        if (cpuUsage >= 0) cpuHist = _pushHist(cpuHist, cpuUsage);
        if (cpuTemp >= 0) tempHist = _pushHist(tempHist, cpuTemp);
        if (gpuUsage >= 0) gpuHist = _pushHist(gpuHist, gpuUsage);
        if (gpuTemp >= 0) gpuTempHist = _pushHist(gpuTempHist, gpuTemp);
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
        Quickshell.execDetached(["wpctl", "set-volume", "-l", "1", SettingsStore.d.audioSink,
            Math.abs(step) + "%" + (step >= 0 ? "+" : "-")]);
        Sounds.playThrottled(SettingsStore.d.soundVolume, 250);
    }

    // Absolute set — the VU meter's draggable level line. Optimistic like
    // adjustVolume; no-op when the target equals the current value so a drag
    // only fires wpctl when the integer actually changes.
    function setVolume(v) {
        v = Math.round(Math.max(0, Math.min(100, v)));
        if (v === volume) return;
        volume = v;
        Quickshell.execDetached(["wpctl", "set-volume", "-l", "1", SettingsStore.d.audioSink, v + "%"]);
        // (audioSink defaults to "@DEFAULT_AUDIO_SINK@" — the system default.)
        Sounds.playThrottled(SettingsStore.d.soundVolume, 250);
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
        // Below hardware zero, and back up again: lowering at 0 eats gamma,
        // and raising gives all of the gamma back BEFORE the hardware level
        // starts climbing again, so the two halves of the range are one
        // continuous line.
        if (step < 0 && brightness === 0) { adjustGamma(step); return; }
        if (step > 0 && gamma < 100)      { adjustGamma(step); return; }
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

    // Gamma side of the range. No debounce needed — hyprsunset's IPC is
    // instant (unlike the ~1.5s DDC write), so every tick lands right away.
    function adjustGamma(step) {
        const floor = Math.max(5, Math.min(100, SettingsStore.d.gammaFloor));
        SettingsStore.d.gammaLevel = Math.max(floor, Math.min(100, gamma + step));
        SettingsStore.save();
        Osd.trigger("brightness");
    }

    function fireBrightnessWrite() {
        ddcBusy = true;
        ddcutilWriteProc.command = useBacklight
            ? ["brightnessctl", "set", String(root.brightness) + "%"]
            : ["ddcutil", "setvcp", "10", String(root.brightness)];
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
        command: root.useBacklight
            ? ["brightnessctl", "-m", "i"]
            : ["ddcutil", "getvcp", "10", "--brief"]
        onExited: ddcBusy = false
        stdout: StdioCollector {
            onStreamFinished: {
                if (root.useBacklight) {
                    // "<class>,<name>,<current>,<percent>%,<max>"
                    const parts = text.trim().split(",");
                    if (parts.length >= 4) {
                        const v = parseInt(parts[3]);
                        if (!isNaN(v)) root.brightness = v;
                    }
                } else {
                    // "VCP 10 C <current> <max>"
                    const parts = text.trim().split(/\s+/);
                    if (parts.length >= 4) {
                        const v = parseInt(parts[3]);
                        if (!isNaN(v)) root.brightness = v;
                    }
                }
            }
        }
    }

    // Detect a real panel backlight once at startup; ddcutilProc/Write above
    // pick brightnessctl vs ddcutil off this. Runs before the timer below
    // (triggeredOnStart) issues the first read.
    Process {
        id: backlightDetectProc
        command: ["sh", "-c", "ls /sys/class/backlight/*/brightness 2>/dev/null | head -n1"]
        running: true
        stdout: StdioCollector {
            onStreamFinished: root._hasBacklight = text.trim() !== ""
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
