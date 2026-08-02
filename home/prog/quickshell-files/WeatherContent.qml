import QtQuick

// Current conditions on one line, over a ten-day forecast graph sampled twice a
// day. The LINE is the chance of rain, the BARS are the temperature.
//
// The graph replaced a table of seven rows because a table spends a whole line
// of height per day to say two numbers. Twenty points of the same height show
// ten days AND the shape of the week — which day the warm spell breaks, whether
// nights are dropping — none of which a column of hi/lo pairs conveys.
//
// Which series gets which mark is not arbitrary. Rain chance is the thing you
// look at this widget to decide something about, so it is the INDICATOR — the
// bright line, on a FIXED 0-100 axis (DESIGN.md §9.3: the battery's rule —
// autoscaling a probability against its own peak reads 30% as certain rain).
// Temperature is the context it rides over, so it is the dim FILL (§3.2), a
// column per sample scaled to the window's own low and high, both of which are
// printed on the axis because that scale moves with the week.
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
    implicitHeight: pad * 2 + head.height + 2 + legend.height + 4
                    + 110 + 2 + dayLabels.height

    // A tile too short for the graph (the player's queue drawer takes rows off
    // the forecast) drops to CURRENT CONDITIONS ONLY: header line, nothing else.
    // Clipping the graph instead would leave a half-drawn axis and a row of day
    // names cut through the middle, which reads as broken rather than compact.
    //
    // The threshold is derived from the SAME constants the layout below is built
    // from, never a magic number. The old one — `pad*2 + 16 + 14 + 40` — counted
    // the padding, the header and the legend but forgot the day-label row and
    // the three inter-element margins, so it was 24px short. Everything in that
    // 24px band claimed it could draw a forecast and then handed the Canvas
    // 0-18px: two 16px axis temperatures drawn on top of each other over a line
    // with nowhere to go, with the day names jammed under the legend. That is
    // the "the weather widget displays nothing" state — not an empty widget, an
    // expanded one with no room to be expanded in.
    readonly property real chromeH:
        pad * 2 + head.height + 2 + legend.height + 4 + 2 + dayLabels.height
    readonly property real minGraph: 40
    readonly property bool condensed: height - chromeH < minGraph

    // Condensed does NOT mean the graph is gone. It keeps a miniature of it —
    // the same twenty points, the same night bands, with the legend, the day
    // names, the axis temperatures and the per-sample markers dropped, because
    // at this size those are the parts that stop being readable rather than the
    // line, and the line is the thing the forecast is for.
    //
    // `miniChromeH` is the same sum for that layout, and `minMiniGraph` is the
    // floor under what is worth drawing. Below it the graph is dropped
    // ENTIRELY and the header re-centres — a canvas handed less than this
    // draws a temperature trace inside a band a few pixels tall, which is the
    // illegible-sliver state the derived threshold above exists to prevent, and
    // it must not come back in through the condensed door.
    //
    // It was 24, and lowering it to 20 is what makes the condensed tile SHORTER
    // rather than what makes the graph thinner: this floor feeds
    // `DockGrid.minWeatherPx`, and the dock grid can only spend height in whole
    // rows (35.3px on this panel), so 24 demanded a third row and 20 fits in
    // two — 97.9px of tile down to 62.6px, and the queue drawer's fourth row
    // back. What the canvas is actually handed at that size is 22.6px, still
    // above this floor; the number is the guard for other panel heights, not
    // the height in use. Do not raise it back without re-running the arithmetic
    // in DockGrid — the two are one calculation split across two files.
    readonly property real miniChromeH: pad * 2 + head.height + 3
    readonly property real minMiniGraph: 20
    readonly property bool miniGraph: condensed && height - miniChromeH >= minMiniGraph

    // The smallest this widget can be and still say something. DockGrid reads
    // it (as a mirrored constant) to decide how many rows the queue drawer may
    // take, and it now includes the miniature graph — asking for the mini form
    // is asking for the room it needs.
    readonly property real minCondensed: miniChromeH + minMiniGraph

    // Which sample the pointer is over, or -1. Drives both the readout that
    // replaces the legend and the cursor drawn on the graph.
    property int hoverIdx: -1

    // ---- header: where, and what it is doing right now -------------------
    Item {
        id: head
        // Condensed, this line IS the widget, so it sits in the middle of the
        // tile rather than pinned to the top with the space the graph left.
        //
        // A plain `y`, NOT a pair of anchors switched on `condensed`. Binding
        // `top` and `verticalCenter` to alternating `undefined`s means both are
        // briefly set during the switch, which Qt answers with "Cannot specify
        // top, bottom, verticalCenter anchors together" and by ignoring one of
        // them — leaving the line wherever the losing anchor put it. The clamp
        // is the other half: centring a 16px line in a tile shorter than 16px
        // gives it a negative y, and the tile's Loader clips it away to nothing.
        anchors.horizontalCenter: parent.horizontalCenter
        // Centred only in the BARE state — with the miniature graph below it the
        // header is a header again and goes back to the top.
        y: (root.condensed && !root.miniGraph)
            ? Math.max(0, (root.height - height) / 2) : root.pad
        width: root.inner
        height: place.implicitHeight

        PixelText {
            id: place
            anchors.left: parent.left
            // Display only — the raw setting is what goes into the geocoding
            // query in Weather.qml.
            text: Glyphs.px(SettingsStore.d.weatherPlace)
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

    // ---- legend, or the hovered sample -----------------------------------
    // A line chart with no key is a squiggle: this says, in the widget itself,
    // that the line is rain chance, the columns are temperature, and the two
    // marker shapes are the morning and night samples. Hovering replaces it
    // with the actual numbers for the sample under the pointer, which is the
    // other half of the same question.
    Item {
        id: legend
        anchors { top: head.bottom; topMargin: 2; horizontalCenter: parent.horizontalCenter }
        width: root.inner
        height: 14
        visible: !root.condensed

        readonly property var hov: (root.hoverIdx >= 0 && root.hoverIdx < root.slots.length)
            ? root.slots[root.hoverIdx] : null

        // swatch + word, so the key is the mark itself rather than a colour name
        component Key: Row {
            id: keyRow
            property string label: ""
            spacing: 3
            visible: root.inner >= 210
            default property alias mark: markHolder.data
            Item {
                id: markHolder
                width: 8
                height: 14
            }
            PixelText { text: keyRow.label; color: Theme.textDim }
        }

        Row {
            anchors.left: parent.left
            spacing: 10
            visible: legend.hov === null

            // The swatch IS the key, so it moved with the series: rain took the
            // line and temp took the column. The two marker shapes sit on the
            // line, so they are the line's colour.
            Key {
                label: "rain %"
                Rectangle {
                    anchors.centerIn: parent
                    width: 8; height: 2
                    color: Theme.info
                }
            }
            Key {
                label: "temp"
                Rectangle {
                    anchors.centerIn: parent
                    width: 6; height: 8
                    color: Theme.accent
                    opacity: 0.22
                }
            }
            Key {
                label: "am"
                Rectangle {
                    anchors.centerIn: parent
                    width: 4; height: 4
                    color: Theme.info
                }
            }
            Key {
                label: "pm"
                Rectangle {
                    anchors.centerIn: parent
                    width: 4; height: 4
                    color: "transparent"
                    border.width: 1
                    border.color: Theme.info
                }
            }
        }

        PixelText {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            visible: legend.hov !== null
            // "wed am", not "wed 9am" \u2014 his call. The hour was never the point:
            // 09:00 and 21:00 are just where "morning" and "night" are sampled
            // (Weather.amHour / pmHour), and printing it invited the reading
            // that the row is about that one hour. The `part` field is already
            // exactly "am"/"pm", so this is the field itself, not a trim.
            text: legend.hov
                ? legend.hov.name + " " + legend.hov.part
                  + "   " + legend.hov.temp + "\u00b0  " + legend.hov.cond
                  + (legend.hov.prob >= 0 ? "   rain " + legend.hov.prob + "%" : "")
                : ""
            color: Theme.text
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
        visible: !root.condensed || root.miniGraph
        // Both branches anchor to a real item — never to `undefined` — so this
        // is an ordinary target switch, not the anchor-clearing hazard the
        // header comment above describes.
        anchors {
            top: root.condensed ? head.bottom : legend.bottom
            topMargin: root.condensed ? 3 : 4
            bottom: root.condensed ? parent.bottom : dayLabels.top
            bottomMargin: root.condensed ? root.pad : 2
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
        Connections {
            target: root
            function onHoverIdxChanged() { if (root.active) graph.requestPaint(); }
        }
        // The mini form draws a DIFFERENT picture, so the mode is a repaint
        // trigger in its own right — a tile that crosses the threshold without
        // changing size otherwise keeps the full drawing.
        Connections {
            target: root
            function onMiniGraphChanged() { if (root.active) graph.requestPaint(); }
        }

        // Hover belongs to the FULL form only. The miniature draws no cursor
        // (see below) and the legend that would show the hovered sample's
        // numbers is not on screen either, so tracking the pointer there is a
        // full Canvas repaint per motion event that changes nothing.
        MouseArea {
            anchors.fill: parent
            enabled: !root.condensed
            hoverEnabled: !root.condensed
            onEnabledChanged: if (!enabled) root.hoverIdx = -1
            acceptedButtons: Qt.NoButton
            onPositionChanged: (mouse) => {
                const n = root.slots.length;
                root.hoverIdx = n < 1 ? -1
                    : Math.max(0, Math.min(n - 1, Math.floor(mouse.x / (width / n))));
            }
            onExited: root.hoverIdx = -1
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
            const mini = root.miniGraph;
            // 12px at the top is room for the axis labels; the mini form does
            // not draw them, so it uses the full height instead.
            const top = mini ? 2 : 12, bot = height - (mini ? 2 : 4);
            // ty: a temperature, for the COLUMNS. `y0` is the floor the columns
            // stand on and it is printed on the axis, so the non-zero baseline
            // is declared rather than implied — a 0°-based column of Fahrenheit
            // would be nine tenths ink and say nothing about the week.
            function ty(t) { return top + (bot - top) * (y0 - t) / (y0 - y1); }
            // py: a probability, for the LINE. Fixed 0-100, never autoscaled.
            function py(p) { return top + (bot - top) * (1 - Math.max(0, Math.min(100, p)) / 100); }
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
            for (let i = 2; !mini && i < n; i += 2) {
                const x = Math.round(width * i / n) + 0.5;
                ctx.beginPath();
                ctx.moveTo(x, 0);
                ctx.lineTo(x, height);
                ctx.stroke();
            }

            // temperature, as a column standing on the window's low. A sample
            // AT the low would otherwise have no column at all, which reads as
            // missing data rather than as the coldest reading of the week, so
            // there is a 1px floor under it.
            ctx.fillStyle = Theme.accent;
            ctx.globalAlpha = 0.22;
            for (let i = 0; i < n; i++) {
                const t = root.slots[i].temp;
                if (t === undefined || t === null) continue;
                const yTop = Math.min(ty(t), bot - 1);
                ctx.fillRect(tx(i) - width / n * 0.3, yTop, width / n * 0.6, bot - yTop);
            }
            ctx.globalAlpha = 1;

            // the rain-chance line. A sample whose probability is missing (-1,
            // an older API answer) BREAKS the line rather than being drawn as a
            // dry hour — hence the per-segment pen-up instead of one path.
            ctx.strokeStyle = Theme.info;
            ctx.lineWidth = mini ? 1 : 1.5;
            ctx.beginPath();
            let pen = false;
            for (let i = 0; i < n; i++) {
                const p = root.slots[i].prob;
                if (!(p >= 0)) { pen = false; continue; }
                const x = tx(i), y = py(p);
                if (!pen) ctx.moveTo(x, y); else ctx.lineTo(x, y);
                pen = true;
            }
            ctx.stroke();

            // a marker per sample: filled for midday, hollow for night. Dropped
            // in the mini form — a 3px square every few pixels reads as noise on
            // the line rather than as two samples a day.
            for (let i = 0; !mini && i < n; i++) {
                const p = root.slots[i].prob;
                if (!(p >= 0)) continue;
                const x = tx(i), y = py(p);
                if (root.slots[i].part === "am") {
                    ctx.fillStyle = Theme.info;
                    ctx.fillRect(x - 1.5, y - 1.5, 3, 3);
                } else {
                    ctx.strokeStyle = Theme.info;
                    ctx.lineWidth = 1;
                    ctx.strokeRect(x - 1.5, y - 1.5, 3, 3);
                }
            }

            // the hover cursor, behind nothing — drawn last so it reads over
            // the bands and the line. NOT in the mini form: a full-height rule
            // over a ~22px canvas is a third of the widget, and there is no
            // legend there for it to be pointing at. The MouseArea above stops
            // tracking in that mode, so this is belt and braces.
            if (!mini && root.hoverIdx >= 0 && root.hoverIdx < n) {
                const hx = tx(root.hoverIdx);
                ctx.strokeStyle = Theme.text;
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(Math.round(hx) + 0.5, 0);
                ctx.lineTo(Math.round(hx) + 0.5, height);
                ctx.stroke();
            }

            // The two scales, one per side, so neither series is read against
            // the other's axis: the columns' high and low of the whole window on
            // the LEFT (it moves with the week, so it has to be printed), the
            // line's fixed ceiling on the RIGHT. NOT in the mini form: two lines
            // of 16px text is most of a 24px canvas, and drawing them there is
            // exactly the overlap this widget was reported for.
            if (mini) return;
            ctx.fillStyle = Theme.textDim;
            ctx.font = Theme.fontSize + "px \"" + Theme.fontCanvas + "\"";
            ctx.textBaseline = "top";
            ctx.fillText(Math.round(hi) + "°", 1, 0);
            ctx.textAlign = "right";
            ctx.fillText("100%", width - 1, 0);
            ctx.textAlign = "left";
            ctx.textBaseline = "bottom";
            ctx.fillText(Math.round(lo) + "°", 1, height);
        }
    }

    // ---- day names, one per pair of samples ------------------------------
    Row {
        id: dayLabels
        visible: !root.condensed
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
        visible: root.slots.length === 0 && !root.condensed
        text: "no data yet"
        color: Theme.textDim
    }
}
