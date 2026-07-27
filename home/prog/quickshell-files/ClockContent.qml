import QtQuick
import Quickshell
import Quickshell.Io

// Analog clock face plus a world-clock list: zone name left, its local time
// right. Times come from `date` under each TZ (the QML JS engine ignores Intl's
// timeZone), refreshed every 30s while this copy is on screen.
//
// TZDIR differs per host and a wrong one is SILENT — every TZ= falls back and
// all the zones read alike — so the command probes for whichever exists:
// /usr/share/zoneinfo on Fedora (book), /etc/zoneinfo on NixOS (top).
//
// Everything that costs anything (the seconds repaint, the timer, the process)
// hangs off `active`, because the popup copy and the dock-tile copy both exist
// in the tree and only one of them is ever being looked at.
Item {
    id: root

    property bool active: true
    property int pad: 10
    readonly property real inner: Math.max(120, width - pad * 2)
    readonly property real faceSize: Math.max(80, Math.min(inner, 148))

    function tzLabel(tz) {
        const p = tz.split("/");
        return p[p.length - 1].replace(/_/g, " ").toLowerCase();
    }
    // The zone list is a free-length array in Settings; blank entries (a
    // just-added, not-yet-filled row) are dropped so they don't emit an empty line.
    readonly property var zones: (SettingsStore.d.worldClocks || [])
        .filter(z => z && z.trim().length > 0)
        .map(z => ({ label: root.tzLabel(z), tz: z }))
    property var times: []

    implicitWidth: 168
    implicitHeight: pad * 2 + faceSize + 8 + 1 + 8 + list.implicitHeight

    SystemClock {
        id: sc
        precision: SystemClock.Seconds
        onDateChanged: if (root.active) face.requestPaint()
    }

    // one process prints every zone's time, newline-separated, in `zones` order
    Process {
        id: tzProc
        command: ["sh", "-c",
            "for d in /usr/share/zoneinfo /etc/zoneinfo; do [ -d \"$d\" ] && export TZDIR=\"$d\" && break; done; for z in "
            + root.zones.map(z => z.tz).join(" ")
            + "; do TZ=$z date +%H:%M; done"]
        stdout: StdioCollector {
            onStreamFinished: {
                root.times = this.text.split("\n").map(s => s.trim()).filter(s => s.length > 0);
            }
        }
    }
    // Re-run the fetch, unless there are no zones — an empty `for z in` loop is
    // a shell syntax error, so just leave the times cleared.
    function refreshTimes() {
        if (!root.active) return;
        if (!root.zones.length) { root.times = []; return; }
        tzProc.running = false; tzProc.running = true;
    }

    onActiveChanged: if (active) { face.requestPaint(); refreshTimes(); }
    Component.onCompleted: refreshTimes()

    Timer {
        interval: 30000
        running: root.active
        repeat: true
        onTriggered: root.refreshTimes()
    }
    Connections {
        target: SettingsStore.d
        function onWorldClocksChanged() { root.refreshTimes(); }
    }

    Canvas {
        id: face
        anchors { top: parent.top; topMargin: root.pad; horizontalCenter: parent.horizontalCenter }
        width: root.faceSize
        height: root.faceSize

        onPaint: {
            const ctx = getContext("2d");
            const w = width, h = height;
            const cx = w / 2, cy = h / 2;
            const r = Math.min(cx, cy) - 4;
            ctx.reset();
            ctx.clearRect(0, 0, w, h);
            ctx.lineCap = "butt";

            for (let i = 0; i < 12; i++) {
                const a = i * Math.PI / 6;
                const major = i % 3 === 0;
                const len = major ? 10 : 5;
                ctx.strokeStyle = major ? Theme.text : Theme.textDim;
                ctx.lineWidth = major ? 2 : 1;
                ctx.beginPath();
                ctx.moveTo(cx + Math.sin(a) * (r - len), cy - Math.cos(a) * (r - len));
                ctx.lineTo(cx + Math.sin(a) * r, cy - Math.cos(a) * r);
                ctx.stroke();
            }

            const d = sc.date;
            const hr = (d.getHours() % 12) + d.getMinutes() / 60;
            const mi = d.getMinutes() + d.getSeconds() / 60;
            const se = d.getSeconds();

            function hand(frac, len, wdt, col) {
                const a = frac * 2 * Math.PI;
                ctx.strokeStyle = col;
                ctx.lineWidth = wdt;
                ctx.beginPath();
                ctx.moveTo(cx, cy);
                ctx.lineTo(cx + Math.sin(a) * len, cy - Math.cos(a) * len);
                ctx.stroke();
            }

            hand(hr / 12, r * 0.50, 3, Theme.text);
            hand(mi / 60, r * 0.74, 2, Theme.accent);
            hand(se / 60, r * 0.80, 1, Theme.crit);

            ctx.fillStyle = Theme.accent;
            ctx.fillRect(cx - 2, cy - 2, 4, 4);
        }
    }

    Rectangle {
        id: rule
        anchors { top: face.bottom; topMargin: 8; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        height: 1
        color: Theme.border
    }

    Column {
        id: list
        anchors { top: rule.bottom; topMargin: 8; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        spacing: 3

        Repeater {
            model: root.zones.length
            Item {
                required property int index
                width: root.inner
                height: 16
                PixelText {
                    anchors.left: parent.left
                    text: root.zones[parent.index].label
                    color: Theme.textDim
                }
                PixelText {
                    anchors.right: parent.right
                    text: root.times[parent.index] || "--"
                    color: Theme.text
                }
            }
        }
    }
}
