pragma Singleton
import Quickshell
import Quickshell.Io
import QtQuick

// Shared state for the on-screen-display popup. `trigger(kind)` re-reads the
// live value for that kind (brightness/volume), shows the OSD, and (re)starts
// the auto-hide timer. The visual window(s) in OsdWindow.qml observe this.
Singleton {
    id: root

    property bool   active: false
    property string kind: "volume"     // "volume" | "brightness"
    property int    value: 0           // 0-100
    property bool   muted: false

    readonly property int holdMs: 1600

    function trigger(k) {
        kind = k;
        active = true;
        hideTimer.restart();
        if (k === "brightness") {
            // Brightness lives in SysInfo already (DDC/ddcutil is too slow,
            // ~1.5s/call, to re-read synchronously here). This used to run
            // its own independent `brightnessctl` read (wrong on this
            // desktop — no laptop backlight — and worse, its async result
            // would land ~300ms later and clobber whatever
            // SysInfo.adjustBrightness had just optimistically set, right
            // as its debounced write was about to fire, so the wrong value
            // got written to the monitor). Just read the value SysInfo is
            // already maintaining instead of re-querying hardware.
            value = SysInfo.brightness < 0 ? 0 : SysInfo.brightness;
            muted = false;
        } else {
            readProc.command = ["sh", "-c", "wpctl get-volume @DEFAULT_AUDIO_SINK@ 2>/dev/null"];
            readProc.running = false;
            readProc.running = true;
        }
    }

    Process {
        id: readProc
        stdout: StdioCollector {
            onStreamFinished: {
                const t = (this.text || "").trim();
                root.muted = /MUTED/.test(t);
                const m = t.match(/([0-9]*\.?[0-9]+)/);
                if (m) root.value = Math.round(parseFloat(m[1]) * 100);
                SysInfo.volume = root.value;
                SysInfo.muted = root.muted;
            }
        }
    }

    Timer {
        id: hideTimer
        interval: root.holdMs
        onTriggered: root.active = false
    }
}
