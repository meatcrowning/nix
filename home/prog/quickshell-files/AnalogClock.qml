import QtQuick
import Quickshell
import Quickshell.Io

// Analog clock popup (SlidePopup: bottom-right, exclusive, hover-kept),
// opened by the clock band of the bar's lower hover strip. Canvas face in
// theme colors, with a world-clock list under it: zone name on the left,
// its local time on the right. Times come from `date` under each TZ (Qt's
// QML JS engine ignores Intl timeZone), refreshed on open + every 30s.
// NixOS has no /usr/share/zoneinfo, so TZDIR must point at /etc/zoneinfo
// or bare TZ names silently fall back to local time. Indiana (Indianapolis)
// is Eastern, so it reads the same as New York — geographically correct.
SlidePopup {
    id: root

    popupNamespace: "qs-analog-clock"
    persistKey: "clock"
    tileRank: 20
    implicitWidth: 168
    implicitHeight: content.implicitHeight + 20

    onOpened: { face.requestPaint(); if (root.zones.length) tzProc.running = true; }

    // short label derived from the Olson TZ (last path segment); the zone list
    // itself comes from Settings (worldClocks — a free-length array), so this
    // stays live. Blank/whitespace entries (a just-added, not-yet-filled row in
    // Settings) are dropped so they don't emit an empty clock line.
    function tzLabel(tz) {
        const p = tz.split("/");
        return p[p.length - 1].replace(/_/g, " ").toLowerCase();
    }
    readonly property var zones: (SettingsStore.d.worldClocks || [])
        .filter(z => z && z.trim().length > 0)
        .map(z => ({ label: root.tzLabel(z), tz: z }))
    property var times: []

    SystemClock {
        id: sc
        precision: SystemClock.Seconds
        onDateChanged: if (root.visible) face.requestPaint()
    }

    // one process prints every zone's time, newline-separated, in `zones` order
    Process {
        id: tzProc
        // TZDIR differs per host: Fedora (air/book) ships the zone db at
        // /usr/share/zoneinfo, NixOS (top) at /etc/zoneinfo. Probe for whichever
        // exists rather than hardcoding one — a wrong/missing TZDIR makes every
        // TZ=... silently fall back to UTC, so all the world clocks read alike.
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
    // re-run the time fetch, unless there are no zones (an empty `for z in`
    // loop would be a shell syntax error — just leave times cleared).
    function refreshTimes() {
        if (!root.zones.length) { root.times = []; return; }
        tzProc.running = false; tzProc.running = true;
    }

    Timer {
        interval: 30000
        running: root.open
        repeat: true
        onTriggered: root.refreshTimes()
    }

    // Re-fetch the world-clock times immediately when the zone list changes in
    // Settings (the labels rebind live; the times come from the Process).
    Connections {
        target: SettingsStore.d
        function onWorldClocksChanged() { root.refreshTimes(); }
    }

    Column {
        id: content
        anchors { top: parent.top; horizontalCenter: parent.horizontalCenter; topMargin: 10 }
        spacing: 8

        // clock face
        Item {
            width: 148
            height: 140
            anchors.horizontalCenter: parent.horizontalCenter

            Canvas {
                id: face
                anchors.fill: parent
                anchors.margins: 4

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
        }

        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 148
            height: 1
            color: Theme.border
        }

        // world clocks: zone left, time right
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 3

            Repeater {
                model: root.zones.length
                Item {
                    required property int index
                    width: 148
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
}
