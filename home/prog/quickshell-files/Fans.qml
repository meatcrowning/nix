import QtQuick

// Every fan on the machine, reduced to what the square `fan` card draws: one
// coloured series per fan, a headline, and the exact speeds for the tooltip.
//
// PURE DERIVATION — no polling, no drawing, no Quickshell. Everything comes in
// through `rows` and `hist`, which is what lets tools/fan-harness.sh exercise it
// offscreen at 0, 1, 2 and 5 fans. That mattered when this machine reported no
// fans at all, and it still does: the board has four, so the empty case and the
// many-fan case have no hardware here either way.
//
// `rows` is [{ name, rpm, pct }] in a STABLE order (see sysinfo.sh):
//   rpm  tachometer reading, -1 where the source has none (the GPU fan)
//   pct  how hard the fan is being driven as a share of its own full scale,
//        -1 where nothing reports it
//
// `hist` is { name: [pct samples] } — kept by name rather than by index so a
// fan appearing or disappearing does not slide every other fan's history onto
// the wrong line.
QtObject {
    id: root

    property var rows: []
    property var hist: ({})
    // name -> true for every fan ever seen to change its duty. See fixed().
    property var varied: ({})
    // Escape hatch: put the fixed-duty fans back in the headline.
    property bool includeFixed: false

    // How far down the brightness ladder the last fan sits. See shade().
    property real shadeSpread: 0.75

    readonly property int count: rows ? rows.length : 0

    // ---- which fans the HEADLINE is allowed to be about -------------------
    //
    // [his] *"exclude the pump that one i cannot change even via the mobo
    // settings and im pretty sure i cant even hear it anyway"*. The pump sits at
    // 255/255 duty permanently, is not adjustable in the BIOS, and is inaudible
    // — so as a "how hard is this machine working" reading it is a constant, and
    // a constant is not a reading. It pinned the headline at 100% for ever.
    //
    // TWO CONDITIONS, AND BOTH ARE LOad-BEARING. A fan is excluded only when it
    // is pinned at maximum duty AND has never once been seen to move.
    //
    //   * "Pinned at max" ALONE would hide a chassis fan that has ramped to 100%
    //     in a thermal event — which is the exact moment the headline matters
    //     most. That rule is worse than no rule.
    //   * "Never moved" ALONE would hide almost everything. Measured on this
    //     box: at idle all four chassis duties sit rock steady (14/255/124/118)
    //     across a 20s sample, so over any short window every fan looks constant
    //     and the headline would fall through to nothing.
    //
    // Together they are safe, because `varied` is STICKY (SysInfo sets it once
    // and never clears it, and carries it across a panel reload). A fan that has
    // ever answered the machine keeps its place in the headline for good,
    // including while it sits at 100% under load. Only a fan that has been at
    // full tilt for its whole observed life — which is what a pump IS — drops
    // out.
    //
    // A fan is never judged before there is something to judge: under
    // settleSamples observations it counts as ordinary. And if the rule would
    // exclude EVERY fan (a fresh boot with the whole set pinned, or a board with
    // one fan and it a pump) the headline falls back to all of them, because a
    // summary of nothing is worse than a summary of a constant.
    //
    // NOTHING IS HIDDEN BY THIS. An excluded fan keeps its coloured line and its
    // tooltip row with its exact RPM, and the row says `fixed` so the headline
    // does not look like it is lying about the fan sitting above it.
    property int settleSamples: 30      // 60s at the 2s poll
    property int fixedPctFloor: 99

    function fixed(i) {
        if (includeFixed) return false;
        const r = rows[i];
        if (!r || r.pct < fixedPctFloor) return false;
        const h = (hist || {})[r.name] || [];
        if (h.length < settleSamples) return false;
        return !((varied || {})[r.name]);
    }

    // The rows the headline may summarise, with the all-excluded fallback.
    readonly property var headlineIdx: {
        const keep = [];
        for (let i = 0; i < count; i++)
            if (!fixed(i)) keep.push(i);
        if (keep.length > 0) return keep;
        const all = [];
        for (let i = 0; i < count; i++) all.push(i);
        return all;
    }

    // ---- what the percentage MEANS, and why it is the only shared axis ----
    //
    // The fans here are two different kinds of sensor and they do not report the
    // same thing. The chassis fans (hwmon nct6687) publish RPM, plus a pwm
    // register that is the duty the chip is COMMANDING — not a fraction of the
    // fan's maximum RPM, because sysfs publishes no such maximum and there is
    // therefore no honest denominator to divide by. The GPU fan (nvidia-smi)
    // publishes a percentage and no RPM at all.
    //
    // So there is exactly one axis all of them can share: "how hard is this fan
    // being driven, out of its own full scale". That is a real question and both
    // sensors answer it. What it is NOT is a claim that the lines are comparable
    // in air moved or in noise — the pump at 100% duty and the GPU at 100% are
    // both flat out, and that is all they have in common. The EXACT speeds are
    // what the tooltip is for, and they are never rounded into this axis.
    //
    // A fan with no percentage anywhere is therefore NOT PLOTTED. It keeps its
    // row in the tooltip with its exact RPM, because putting it on a 0-100 axis
    // would mean inventing the denominator this whole comment exists to refuse.
    readonly property int pctCount: {
        let n = 0;
        for (let i = 0; i < count; i++)
            if (rows[i] && rows[i].pct >= 0) n++;
        return n;
    }

    // The fastest fan going — the headline, as asked for. It is the highest
    // PERCENTAGE among the rows the rule above admits, i.e. the fan closest to
    // flat out that can still tell you something. Where nothing reports a
    // percentage at all it falls back to the highest RPM and says "rpm", rather
    // than printing a percent sign over a number that is not one.
    readonly property int topPct: {
        let m = -1;
        for (const i of headlineIdx)
            if (rows[i] && rows[i].pct > m) m = rows[i].pct;
        return m;
    }
    readonly property int topRpm: {
        let m = -1;
        for (const i of headlineIdx)
            if (rows[i] && rows[i].rpm > m) m = rows[i].rpm;
        return m;
    }
    // The RPM of the fan the headline is about — not the highest RPM on the
    // machine, which would be a second, different claim sitting next to the
    // first one and quietly disagreeing with it.
    readonly property int topPctRpm: {
        let m = -1, r = -1;
        for (const i of headlineIdx)
            if (rows[i] && rows[i].pct > m) { m = rows[i].pct; r = rows[i].rpm; }
        return r;
    }
    readonly property string topName: {
        let m = -1, n = "";
        for (const i of headlineIdx)
            if (rows[i] && rows[i].pct > m) { m = rows[i].pct; n = rows[i].name; }
        return n;
    }

    readonly property string headline:
        count === 0 ? "--"
      : topPct >= 0 ? topPct + "%"
      : topRpm >= 0 ? topRpm + "rpm" : "--"

    // Secondary reading: the exact speed of that same fan, so the card carries
    // one real number as well as the summary. Blank for a fan with no
    // tachometer (the GPU), which MetricCard then simply does not draw.
    readonly property string subline:
        topPct >= 0 && topPctRpm >= 0 ? topPctRpm + "r" : ""

    // ---- the colours -----------------------------------------------------
    // A brightness ladder on the accent hue, brightest first — NOT a set of
    // different colours, because there are none to hand out. The palette is
    // derived from the wallpaper and is ONE HUE by construction (DESIGN.md 3.1:
    // every slot including ok/warn/crit/info is a near-neighbour of accent), and
    // inventing hues outside it is the single thing that file forbids outright.
    // Monotonic steps of accent brightness is the established answer for
    // multiple states of one thing (3.3); this is the same shape of problem.
    //
    // The ladder stays legible to about five or six lines. Past that the steps
    // are closer than the eye resolves on a chart this size — survivable only
    // because the colour is never the sole identifier: the tooltip lists every
    // fan by name with its exact speed, in the same order. So a seventh fan
    // degrades to "two lines look alike", not to an unreadable widget.
    function shade(i) {
        if (count <= 1 || i <= 0) return Theme.accent;
        const t = (i / (count - 1)) * root.shadeSpread;
        return Qt.tint(Theme.accent, Qt.rgba(Theme.dim.r, Theme.dim.g, Theme.dim.b, t));
    }

    // One series per fan THAT HAS A PERCENTAGE, in row order, so a line's colour
    // and its tooltip row always agree. Fans without one are absent here and
    // present there.
    readonly property var series: {
        const out = [];
        const h = root.hist || {};
        for (let i = 0; i < count; i++) {
            const r = rows[i];
            if (!r || r.pct < 0) continue;
            out.push({ data: h[r.name] || [], color: root.shade(i) });
        }
        return out;
    }

    // The exact speed of every fan, which is what the card has no room for.
    // Ordered as the lines are, so "the third line" can be found by counting.
    // Plain text, monospace: two columns line up on spaces.
    readonly property string detail: {
        if (count === 0) return "no fan reports a tachometer";
        let s = "";
        for (let i = 0; i < count; i++) {
            const r = rows[i];
            if (!r) continue;
            let line = r.name;
            while (line.length < 9) line += " ";
            line += r.rpm >= 0 ? (r.rpm + "rpm") : "   --  ";
            while (line.length < 19) line += " ";
            line += r.pct >= 0 ? (r.pct + "%") : "--";
            // Say WHY this fan is not the headline, on the row itself. Without
            // it the card reads as wrong: a tooltip listing a fan at 100% next
            // to a readout saying 59% looks like the readout is lying.
            if (fixed(i)) {
                while (line.length < 25) line += " ";
                line += "fixed";
            }
            s += (s === "" ? "" : "\n") + line;
        }
        return s;
    }
}
