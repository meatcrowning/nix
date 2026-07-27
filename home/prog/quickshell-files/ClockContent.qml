import QtQuick
import Quickshell
import Quickshell.Io

// The clock widget: the time drawn one of three ways, over a world-clock list.
//
// The face is cycled by the button in the top-right corner, and the choice is a
// persisted setting rather than local state, so it survives a reload (which
// happens on every wallpaper change) and is the same on both copies of the
// widget. `analog` is the original hand face; `dots` is a 5x7 dot-matrix
// readout; `seg` is a seven-segment one. All three are the same Canvas.
//
// SIZING: the face takes whatever is left between the top padding and the world
// clocks, so the widget has no dead space at any tile height. `naturalFace` is
// only used for `implicitHeight` — reading `height` there instead would be a
// binding loop, since the popup derives its height from exactly that.
//
// TZDIR differs per host and a wrong one is SILENT — every TZ= falls back and
// all the zones read alike — so the command probes for whichever exists:
// /usr/share/zoneinfo on Fedora (book), /etc/zoneinfo on NixOS (top).
Item {
    id: root

    // Defaults to FALSE, and every host sets it: the popup passes its `open`,
    // DockTile binds it to the dock's visibility. A `true` default would mean a
    // grid tile polls once at construction, before that Binding has applied.
    property bool active: false
    property int pad: 10
    readonly property real inner: Math.max(120, width - pad * 2)

    readonly property string mode: {
        const m = SettingsStore.d.clockFace;
        return (m === "dots" || m === "seg") ? m : "analog";
    }
    readonly property var modeOrder: ["analog", "dots", "seg"]
    // The chosen face is a SETTING, so it has to be written to disk, not just
    // assigned: SettingsStore's reader poll re-reads settings.json a few times a
    // second and an unsaved adapter change is reverted by the next reload — the
    // face flipped back on its own, and never survived a logout at all.
    function cycleFace() {
        const i = modeOrder.indexOf(root.mode);
        SettingsStore.d.clockFace = modeOrder[(i + 1) % modeOrder.length];
        SettingsStore.save();
    }

    // Natural (popup) face size, and the actual box it gets in a tile.
    readonly property int naturalFace: 148
    readonly property real _chrome: pad * 2 + 8 + 1 + 8 + list.implicitHeight
    readonly property real faceBoxH: Math.max(40, height - _chrome)

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
    implicitHeight: naturalFace + _chrome

    // The seconds clock. `enabled` follows `active` so an off-screen copy of
    // the widget (a condensed dock, a closed popup) is not woken once a second
    // for a face nobody is looking at — both faces repaint on activation
    // anyway, via onActiveChanged below.
    SystemClock {
        id: sc
        precision: SystemClock.Seconds
        enabled: root.active
        // `dots` is not a Canvas, and its digits only move once a minute — so
        // the per-second tick must not ask the (hidden) Canvas to repaint in
        // that mode. onModeChanged repaints it when the face is cycled back.
        onDateChanged: if (root.active && root.mode !== "dots") face.requestPaint()
    }
    // The digit faces only change once a minute. Driving them off the seconds
    // clock would rebuild the dot-matrix cell model 60 times more often than
    // anything on screen changes.
    SystemClock {
        id: scMin
        precision: SystemClock.Minutes
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
    onModeChanged: face.requestPaint()

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

    // ---- glyph data ------------------------------------------------------
    // 5x7 dot matrix, one bitmask per row, bit 4 = leftmost column.
    readonly property var dotGlyphs: ({
        "0": [0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E],
        "1": [0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E],
        "2": [0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F],
        "3": [0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E],
        "4": [0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02],
        "5": [0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E],
        "6": [0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E],
        "7": [0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08],
        "8": [0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E],
        "9": [0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C],
    })
    // Seven-segment: bit 0..6 = a,b,c,d,e,f,g.
    readonly property var segGlyphs: ({
        "0": 63, "1": 6, "2": 91, "3": 79, "4": 102,
        "5": 109, "6": 125, "7": 7, "8": 127, "9": 111,
    })

    function timeText() {
        const d = scMin.date;
        let h = d.getHours();
        if (!SettingsStore.d.clock24h) {
            h = h % 12;
            if (h === 0) h = 12;
        }
        const m = d.getMinutes();
        return (h < 10 ? "0" : "") + h + ":" + (m < 10 ? "0" : "") + m;
    }

    // Lit cells of the dot-matrix face: [{c, r}] in 25x7 grid coordinates.
    // Only the LIT ones — the unlit grid is not drawn at all, so there is
    // nothing to pick a dim colour for (which is what made the first version
    // unreadable). Bound to the minute clock, so this list is rebuilt once a
    // minute rather than once a second.
    //
    // The COLON is deliberately not in here: it blinks once a second, and this
    // array is a Repeater model, so putting it here would destroy and rebuild
    // all sixty-odd digit delegates (64 for "09:07") on every tick. Its column
    // is published separately as `colonCol` and its two dots are their own
    // items, so a tick recolours exactly two of them.
    readonly property var dotCells: {
        const txt = root.timeText();
        let out = [];
        let col = 0;
        for (let ci = 0; ci < txt.length; ci++) {
            const ch = txt.charAt(ci);
            if (ch === ":") {
                col += 2;
                continue;
            }
            const g = root.dotGlyphs[ch];
            if (g) {
                for (let r = 0; r < 7; r++)
                    for (let c = 0; c < 5; c++)
                        if ((g[r] >> (4 - c)) & 1) out.push({ c: col + c, r: r });
            }
            col += 6;
        }
        return out;
    }

    // Which grid column the colon sits in — walked the same way `dotCells`
    // walks the string, so a future format change moves both together. -1 if
    // the text has no colon at all.
    readonly property int colonCol: {
        const txt = root.timeText();
        let col = 0;
        for (let ci = 0; ci < txt.length; ci++) {
            if (txt.charAt(ci) === ":") return col;
            col += 6;
        }
        return -1;
    }

    // The dot-matrix face, drawn out of the pixel font's own U+25A0 block
    // rather than filled rectangles, so the dots rasterise exactly like every
    // other glyph on this desktop. (Checked against the font's cmap: More
    // Perfect DOS VGA has U+25A0 and U+2588, but not the bullet or the circle.)
    Item {
        id: dotFace
        visible: root.mode === "dots"
        anchors {
            top: parent.top; topMargin: root.pad
            left: parent.left; right: parent.right
            leftMargin: root.pad; rightMargin: root.pad
        }
        height: root.faceBoxH

        readonly property int cols: 25
        readonly property int rows: 7
        readonly property real unit: Math.min(width / cols, height / rows)
        readonly property real ox: (width - cols * unit) / 2
        readonly property real oy: (height - rows * unit) / 2

        // The colon flashes with the seconds, on the same beat and with the
        // same unlit colour as the `seg` face's colon — cycling between the
        // two digital faces must not change the rhythm. `seconds % 2` toggles
        // exactly on the second tick; `Theme.bgAlt` is a ghost rather than a
        // hole, so a dot that is off still reads as an unlit cell instead of
        // as something failing to draw.
        readonly property bool colonLit: sc.date.getSeconds() % 2 === 0

        Repeater {
            model: root.dotCells
            PixelText {
                required property var modelData
                text: "\u25a0"
                color: Theme.accent
                font.pixelSize: Math.max(6, Math.round(dotFace.unit * 1.5))
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                width: dotFace.unit
                height: dotFace.unit
                x: dotFace.ox + modelData.c * dotFace.unit
                y: dotFace.oy + modelData.r * dotFace.unit
            }
        }

        // Rows 2 and 4 of `colonCol`. A constant integer model, so these two
        // delegates are created once and only their `color` changes per tick —
        // no model rebuild, no relayout, no Canvas repaint.
        Repeater {
            model: 2
            PixelText {
                required property int index
                visible: root.colonCol >= 0
                text: "\u25a0"
                color: dotFace.colonLit ? Theme.accent : Theme.bgAlt
                font.pixelSize: Math.max(6, Math.round(dotFace.unit * 1.5))
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                width: dotFace.unit
                height: dotFace.unit
                x: dotFace.ox + root.colonCol * dotFace.unit
                y: dotFace.oy + (2 + index * 2) * dotFace.unit
            }
        }
    }

    Canvas {
        id: face
        visible: root.mode !== "dots"
        anchors {
            top: parent.top; topMargin: root.pad
            left: parent.left; right: parent.right
            leftMargin: root.pad; rightMargin: root.pad
        }
        height: root.faceBoxH

        // ---- analog: the original hand face, square and centred ----------
        function paintAnalog(ctx, w, h) {
            const side = Math.min(w, h);
            const cx = w / 2, cy = h / 2;
            const r = side / 2 - 4;
            ctx.lineCap = "butt";

            for (let i = 0; i < 12; i++) {
                const a = i * Math.PI / 6;
                const major = i % 3 === 0;
                const len = major ? r * 0.14 : r * 0.07;
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

        // ---- seven segment: "HH:MM", each digit in a 3x5 unit box --------
        function paintSeg(ctx, w, h) {
            const txt = root.timeText();
            const cols = 17, rows = 5;
            const u = Math.min(w / cols, h / rows);
            const ox = (w - cols * u) / 2, oy = (h - rows * u) / 2;
            const lit = sc.date.getSeconds() % 2 === 0;
            ctx.lineCap = "butt";
            ctx.lineWidth = Math.max(1.5, u * 0.5);

            // Unlit segments go all the way down to bgAlt — a ghost, not a
            // reading. At Theme.border (which is right for the dot grid) the
            // unlit segments still carry enough ink that every digit reads as
            // an 8; measured by rendering the same glyph data out and looking.
            function seg(x1, y1, x2, y2, on) {
                ctx.strokeStyle = on ? Theme.accent : Theme.bgAlt;
                ctx.beginPath();
                ctx.moveTo(x1, y1);
                ctx.lineTo(x2, y2);
                ctx.stroke();
            }

            let col = 0;
            for (let ci = 0; ci < txt.length; ci++) {
                const ch = txt.charAt(ci);
                if (ch === ":") {
                    const s = u * 0.5;
                    ctx.fillStyle = lit ? Theme.accent : Theme.bgAlt;
                    ctx.fillRect(ox + col * u + (u - s) / 2, oy + 1.5 * u, s, s);
                    ctx.fillRect(ox + col * u + (u - s) / 2, oy + 3.0 * u, s, s);
                    col += 2;
                    continue;
                }
                const m = root.segGlyphs[ch] || 0;
                const x0 = ox + col * u, y0 = oy;
                const x1 = x0 + 3 * u, ym = y0 + 2.5 * u, y1 = y0 + 5 * u;
                // inset the ends so adjacent segments don't overlap into a blob
                const i = ctx.lineWidth / 2;
                seg(x0 + i, y0, x1 - i, y0, m & 1);        // a
                seg(x1, y0 + i, x1, ym - i, m & 2);        // b
                seg(x1, ym + i, x1, y1 - i, m & 4);        // c
                seg(x0 + i, y1, x1 - i, y1, m & 8);        // d
                seg(x0, ym + i, x0, y1 - i, m & 16);       // e
                seg(x0, y0 + i, x0, ym - i, m & 32);       // f
                seg(x0 + i, ym, x1 - i, ym, m & 64);       // g
                col += 4;
            }
        }

        onPaint: {
            const ctx = getContext("2d");
            ctx.reset();
            ctx.clearRect(0, 0, width, height);
            if (root.mode === "seg") paintSeg(ctx, width, height);
            else paintAnalog(ctx, width, height);
        }
    }

    // Face-cycle button, top-right. Same visual language as the popups' pin
    // indicator: one dim letter that lights on hover, no chrome.
    Item {
        anchors { top: parent.top; right: parent.right; topMargin: 6; rightMargin: 7 }
        width: 12
        height: 12
        z: 5

        PixelText {
            anchors.centerIn: parent
            text: root.mode === "analog" ? "o" : root.mode === "dots" ? ":" : "8"
            color: faceMa.containsMouse ? Theme.accent : Theme.textDim
        }
        MouseArea {
            id: faceMa
            anchors { fill: parent; margins: -4 }
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.cycleFace()
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
                    elide: Text.ElideRight
                    width: parent.width - 44
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
