import QtQuick

// Current conditions on one line, over a ten-day temperature graph sampled
// twice a day.
//
// The graph replaced a table of seven rows because a table spends a whole line
// of height per day to say two numbers. Twenty points of the same height show
// ten days AND the shape of the week — which day the warm spell breaks, whether
// nights are dropping — none of which a column of hi/lo pairs conveys.
//
// "Morning" and "night" are the 09:00 and 21:00 hourly samples (Weather.amHour
// / pmHour), not the daily max and min: a daily max is not tied to a time of
// day, so it cannot be plotted against one.
Item {
    id: root

    // Defaults to FALSE, and every host sets it: the popup passes its `open`,
    // DockTile binds it to the dock's visibility.
    property bool active: false
    property int pad: 10
    readonly property real inner: Math.max(80, width - pad * 2)

    implicitWidth: 252
    implicitHeight: pad * 2 + head.height + 6 + 120 + 2 + dayLabels.height

    // ---- header: where, and what it is doing right now -------------------
    Item {
        id: head
        anchors { top: parent.top; topMargin: root.pad; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        height: place.implicitHeight

        PixelText {
            id: place
            anchors.left: parent.left
            text: SettingsStore.d.weatherPlace
            color: Theme.accent
            elide: Text.ElideRight
            width: Math.min(implicitWidth, parent.width * 0.4)
        }

        // temp, sky, wind — right-aligned, in that order
        Row {
            anchors.right: parent.right
            spacing: 6
            PixelText {
                text: Weather.tempF <= -999 ? "--" : Weather.tempF + "°"
                color: Theme.text
            }
            PixelText {
                text: Weather.cond
                color: Theme.info
            }
            PixelText {
                text: Weather.windSpeed < 0 ? "--"
                    : Math.round(Weather.windSpeed) + (Weather.windName.length ? " " + Weather.windName : "")
                color: Theme.textDim
            }
        }
    }

    // ---- the ten-day graph -----------------------------------------------
    readonly property var slots: Weather.slots
    readonly property real tMin: {
        let m = 1e9;
        for (const s of slots) if (s.temp < m) m = s.temp;
        return m === 1e9 ? 0 : m;
    }
    readonly property real tMax: {
        let m = -1e9;
        for (const s of slots) if (s.temp > m) m = s.temp;
        return m === -1e9 ? 1 : m;
    }

    Canvas {
        id: graph
        anchors {
            top: head.bottom; topMargin: 6
            bottom: dayLabels.top; bottomMargin: 2
            left: parent.left; right: parent.right
            leftMargin: root.pad; rightMargin: root.pad
        }

        // Repaint whenever the data or the scale moves. `slots` is a binding
        // over the Weather singleton, so this is the only trigger needed.
        Connections {
            target: root
            function onSlotsChanged() { if (root.active) graph.requestPaint(); }
        }
        Connections {
            target: root
            function onActiveChanged() { if (root.active) graph.requestPaint(); }
        }

        onPaint: {
            const ctx = getContext("2d");
            ctx.reset();
            ctx.clearRect(0, 0, width, height);

            const n = root.slots.length;
            if (n < 2) {
                ctx.strokeStyle = Theme.border;
                ctx.lineWidth = 1;
                ctx.strokeRect(0.5, 0.5, width - 1, height - 1);
                return;
            }

            // A degree or two of range would otherwise be amplified into a
            // mountain profile, so keep a floor under the span.
            const lo = root.tMin, hi = root.tMax;
            const span = Math.max(6, hi - lo);
            const mid = (hi + lo) / 2;
            const y0 = mid + span / 2, y1 = mid - span / 2;
            const top = 12, bot = height - 4;          // room for the value labels
            function ty(t) { return top + (bot - top) * (y0 - t) / (y0 - y1); }
            function tx(i) { return width * (i + 0.5) / n; }

            // night bands: every second slot is a 21:00 sample, so shade its
            // half of the day. This is what makes the two-per-day structure
            // legible rather than just a wigglier line.
            ctx.fillStyle = Theme.bgAlt;
            for (let i = 0; i < n; i++) {
                if (root.slots[i].part !== "pm") continue;
                const x = width * i / n;
                ctx.fillRect(x, 0, width / n, height);
            }

            // day separators
            ctx.strokeStyle = Theme.border;
            ctx.lineWidth = 1;
            for (let i = 2; i < n; i += 2) {
                const x = Math.round(width * i / n) + 0.5;
                ctx.beginPath();
                ctx.moveTo(x, 0);
                ctx.lineTo(x, height);
                ctx.stroke();
            }

            // precipitation probability, as a column rising from the floor
            for (let i = 0; i < n; i++) {
                const p = root.slots[i].prob;
                if (!(p > 0)) continue;
                const h = (height - 2) * Math.min(100, p) / 100;
                ctx.fillStyle = Theme.info;
                ctx.globalAlpha = 0.22;
                ctx.fillRect(tx(i) - width / n * 0.3, height - h, width / n * 0.6, h);
                ctx.globalAlpha = 1;
            }

            // the temperature line
            ctx.strokeStyle = Theme.accent;
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            for (let i = 0; i < n; i++) {
                const x = tx(i), y = ty(root.slots[i].temp);
                if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            }
            ctx.stroke();

            // a marker per sample: filled for midday, hollow for night
            for (let i = 0; i < n; i++) {
                const x = tx(i), y = ty(root.slots[i].temp);
                if (root.slots[i].part === "am") {
                    ctx.fillStyle = Theme.accent;
                    ctx.fillRect(x - 1.5, y - 1.5, 3, 3);
                } else {
                    ctx.strokeStyle = Theme.accent;
                    ctx.lineWidth = 1;
                    ctx.strokeRect(x - 1.5, y - 1.5, 3, 3);
                }
            }

            // high and low of the whole window, on the axis
            ctx.fillStyle = Theme.textDim;
            ctx.font = Theme.fontSize + "px \"" + Theme.font + "\"";
            ctx.textBaseline = "top";
            ctx.fillText(Math.round(hi) + "°", 1, 0);
            ctx.textBaseline = "bottom";
            ctx.fillText(Math.round(lo) + "°", 1, height);
        }
    }

    // ---- day names, one per pair of samples ------------------------------
    Row {
        id: dayLabels
        anchors {
            bottom: parent.bottom; bottomMargin: root.pad
            left: parent.left; right: parent.right
            leftMargin: root.pad; rightMargin: root.pad
        }
        height: 16

        Repeater {
            // one entry per DAY, i.e. every second slot
            model: Math.floor(root.slots.length / 2)
            PixelText {
                required property int index
                width: dayLabels.width / Math.max(1, Math.floor(root.slots.length / 2))
                horizontalAlignment: Text.AlignHCenter
                text: root.slots[index * 2] ? root.slots[index * 2].name : ""
                color: index === 0 ? Theme.accent : Theme.textDim
                elide: Text.ElideRight
            }
        }
    }

    PixelText {
        anchors.centerIn: parent
        visible: root.slots.length === 0
        text: "no data yet"
        color: Theme.textDim
    }
}
