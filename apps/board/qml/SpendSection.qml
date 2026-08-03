import QtQuick

// The spend section — what this board's automation costs, across every provider
// it dispatches to (the deepseek/hermes ministers AND every Claude tier). The
// numbers, and every decision about where they come from, are `boardspend.py`'s;
// this file only draws, through the `Spend` context property (main.py).
//
// A RANKED HORIZONTAL-BAR LIST, not an N-colour chart (docs/DESIGN.md §3.3.1 —
// there is only one hue to give, so a set of peers is one hue and the LABEL is
// the key, never the colour). One row per model: its name is its own legend, a
// bar sized to that model's share of total cost (§9.3), then the figures —
// how many agents it was dispatched, its cost, and its tokens in/out.
//
// Beside the list, right, a COMPACT TOKENS-PER-DAY GRID: one small square per
// day over the trailing month, laid out like a GitHub contribution graph (weeks
// down the columns, weekday across the rows) and coloured by that day's tokens —
// a single hue (accent2) stepped in intensity over an unlit bgAlt cell (§3.3.1,
// §3.4), so a busy day is a bright square and a silent day is the bare cell.
// Hovering a day rebinds the left bars to that day — same bars, same hue, their
// length re-read as each model's share of THAT day's tokens rather than of total
// cost — and the caption becomes that day's date and total (§9.3: one hover
// sample re-reads a sibling readout). With nothing hovered the left bars are the
// whole-period cost share, as ever. The per-day, per-model series is
// `boardspend.py`'s `Spend.daily`.
//
// Below the list, one split bar for the whole system's tokens (input vs output), and the
// one honest line §10/§10.5 demands: the Claude dollar is a compute-WEIGHT
// (measured tokens x public API rates), NOT a bill — he is on a plan measured
// in % of limit and there is no invoice to read. The hermes dollar is the
// provider's own estimate. Neither is invented; a missing source is UNKNOWN,
// never a confident zero (`Spend.known`).
//
// Colour is BORROWED, not invented (§3.2, §3.3.1): the cost bars are `accent2`,
// the secondary structural hue every non-active band here already wears; the
// token split reads `accent2` for input against `accent` for the output
// minority so the tiny output segment stays visible, with both labelled so the
// colour is never the only key.
Column {
    id: spendRoot
    width: page.width
    // Prohibit the Loader from resizing this root to its own (initially 0) size
    // — an explicit height here is what lets the section keep its own height and
    // the sections below it lay out by it (same idiom as every other section).
    height: implicitHeight

    //: the biggest model's cost, so every cost bar is a share of the same
    //  denominator (§10.5). Models arrive sorted cost-desc, so [0] is the max.
    readonly property real maxCost:
        (Spend.models && Spend.models.length > 0 && Spend.models[0].cost > 0)
        ? Spend.models[0].cost : 1

    //: the whole system's token total, the denominator for the split bar.
    readonly property real totalTokens:
        (Spend.totals && (Spend.totals["in"] + Spend.totals["out"]) > 0)
        ? (Spend.totals["in"] + Spend.totals["out"]) : 1

    // ---- the tokens-per-day grid, and what hovering one of its days does ----
    // -1 = no day hovered, and the left bars show the whole-period cost share as
    // they always have. Otherwise it is an index into `Spend.daily`, and the left
    // bars are rebound to THAT day's per-model token breakdown — same bars, same
    // hue, the length re-read from one day (docs/DESIGN.md §9.3).
    property int hoveredDay: -1

    //: is there a month of days with anything in it to draw? (`known` can be true
    //  with every day still zero on a box that has only ever run today.)
    readonly property bool hasDaily: {
        var d = Spend.daily;
        if (!d || d.length === 0) return false;
        for (var i = 0; i < d.length; ++i) if (d[i].total > 0) return true;
        return false;
    }

    readonly property bool hasModels: Spend.models && Spend.models.length > 0

    //: the whole period's total spend, as a fixed-2 string — added to the grid
    //  caption on hover so the day's per-item figure reads against the running
    //  total (the same $ the system-wide totals line carries below).
    readonly property string totalCost:
        (Spend.totals && Spend.totals.cost !== undefined)
        ? Spend.totals.cost.toFixed(2) : "0"

    //: the hovered day's {family: tokens} map, or null when none is hovered.
    readonly property var dayModels:
        (hoveredDay >= 0 && Spend.daily && hoveredDay < Spend.daily.length)
        ? Spend.daily[hoveredDay].models : null

    //: the hovered day's {family: cost} map, or null when none is hovered — the
    //  per-model spend the row's top-right figure reads in day mode.
    readonly property var dayCosts:
        (hoveredDay >= 0 && Spend.daily && hoveredDay < Spend.daily.length)
        ? Spend.daily[hoveredDay].costs : null

    //: the hovered day's whole-day spend, drawn in the grid caption beside the
    //  agent count (§9.3: the hover re-reads the chart's own readout to the day).
    readonly property real dayCost:
        (hoveredDay >= 0 && Spend.daily && hoveredDay < Spend.daily.length)
        ? Spend.daily[hoveredDay].cost : 0

    //: how many agents ran on the hovered day (distinct dispatches).
    readonly property int dayAgents:
        (hoveredDay >= 0 && Spend.daily && hoveredDay < Spend.daily.length)
        ? Spend.daily[hoveredDay].agents : 0

    //: this row's spend on the hovered day (0 when it did nothing that day).
    function dayCostOf(model) {
        return (dayCosts && dayCosts[model] !== undefined) ? dayCosts[model] : 0;
    }

    //: the hovered day's whole-day token total, the denominator for the per-model
    //  share text below each rebound bar.
    readonly property real dayTotal:
        (hoveredDay >= 0 && Spend.daily && hoveredDay < Spend.daily.length)
        ? Spend.daily[hoveredDay].total : 0

    //: the busiest single model in the hovered day — the bar denominator, exactly
    //  as `maxCost` is for the cost bars, so the biggest bar fills the track.
    readonly property real dayMaxModel: {
        if (!dayModels) return 1;
        var mx = 0;
        for (var k in dayModels) if (dayModels[k] > mx) mx = dayModels[k];
        return mx > 0 ? mx : 1;
    }

    //: this row's tokens on the hovered day (0 when it did nothing that day).
    function dayTokensOf(model) {
        return (dayModels && dayModels[model] !== undefined) ? dayModels[model] : 0;
    }

    SectionHead {
        width: page.width
        label: "spend"
        collapsed: win.isCollapsed("spend")
        fgAccent: win.fgAccent
        fgAccent2: win.fgAccent2
        fgDim: win.fgDim
        reorderable: true
        onToggled: win.toggleCollapsed("spend")
        onReorderRequested: (dy) => win.reorderSection("spend", dy)
    }

    Item {
        width: page.width
        visible: !win.isCollapsed("spend")
        implicitHeight: visible ? spendCol.implicitHeight : 0
        height: implicitHeight

        Column {
            id: spendCol
            width: parent.width

            // The constant framing line, like every other section's — what the
            // section IS, unchanging with its contents.
            Para {
                width: spendCol.width
                color: win.fgDim
                text: "what this board's automation has cost, across every "
                    + "provider it dispatches to."
                bottomPadding: 8
            }

            // No source could be read at all: say so, rather than draw a
            // confident set of zeroes (§10).
            PixelText {
                visible: !Spend.known
                width: spendCol.width
                wrapMode: Text.WordWrap
                color: win.fgDim
                text: "no provider ledger could be read yet — nothing to show."
            }

            // ---- the ranked model list (left) beside the per-day grid (right).
            // The list is the same ranked horizontal-bar vocabulary as before;
            // the grid is a compact month of tokens-per-day squares, and hovering
            // one of its days rebinds these left bars to that day (§9.3).
            Row {
                width: spendCol.width
                spacing: 12

                //: the grid's width — compact, a month of small squares — but the
                //  list keeps the rest. Zero (grid hidden) gives the list all.
                readonly property int chartW:
                    (spendRoot.hasDaily && spendRoot.hasModels)
                    ? Math.max(96, Math.min(160, Math.round(width * 0.36))) : 0

                Column {
                    id: leftCol
                    width: parent.chartW > 0
                           ? parent.width - parent.chartW - parent.spacing
                           : parent.width

                    Repeater {
                        model: Spend.models ? Spend.models : []
                        delegate: Item {
                            id: mrow
                            required property var modelData
                            width: leftCol.width
                            implicitHeight: mtop.implicitHeight + 2 + bar.height
                                            + 2 + mbot.implicitHeight + 8
                            height: implicitHeight

                            //: this model's tokens on the hovered day (day mode).
                            readonly property real dayTok:
                                spendRoot.dayTokensOf(modelData.model)

                            //: this model's spend on the hovered day (day mode).
                            readonly property real dayModelCost:
                                spendRoot.dayCostOf(modelData.model)

                            Rectangle {
                                anchors.fill: parent
                                anchors.bottomMargin: 8
                                color: mma.containsMouse ? Theme.highlight : "transparent"
                            }
                            MouseArea { id: mma; anchors.fill: parent; hoverEnabled: true }

                            // top line: model (its own legend, at foreground) hard
                            // left; hard right its cost — the whole period's by
                            // default, this model's spend on the hovered day in
                            // day mode (§5.4 paired edges). Same $ figure, day
                            // scope, so the edge reads the same thing throughout.
                            PixelText {
                                id: mname
                                x: 0
                                color: Theme.text
                                text: mrow.modelData.model + "  (" + mrow.modelData.provider + ")"
                            }
                            PixelText {
                                id: mcost
                                x: Math.max(mname.x + mname.width + 8, parent.width - width)
                                color: Theme.text
                                text: spendRoot.hoveredDay >= 0
                                    ? "$" + mrow.dayModelCost.toFixed(2)
                                    : "$" + mrow.modelData.cost.toFixed(2)
                            }

                            // the share bar (§9.3): the whole hue is accent2, the
                            // length is the meaning — cost share by default, this
                            // model's share of the hovered day's tokens in day
                            // mode. Unlit track is bgAlt, never dim (§3.4).
                            Rectangle {
                                id: bar
                                x: 0
                                y: mtop.implicitHeight + 2
                                width: parent.width
                                height: Math.max(6, Math.round(Theme.fontSize / 2))
                                color: Theme.bgAlt
                                border.width: 1
                                border.color: Theme.border

                                Rectangle {
                                    x: 1
                                    y: 1
                                    height: parent.height - 2
                                    width: spendRoot.hoveredDay >= 0
                                        ? Math.round((parent.width - 2)
                                            * mrow.dayTok / spendRoot.dayMaxModel)
                                        : Math.round((parent.width - 2)
                                            * mrow.modelData.cost / spendRoot.maxCost)
                                    visible: width > 0
                                    color: Theme.accent2
                                }
                            }

                            // the figures: agents dispatched + tokens in/out by
                            // default; with a day hovered, this model's tokens on
                            // that day and its share of the day (spend is on the
                            // top line; the date itself is the chart's caption).
                            PixelText {
                                id: mbot
                                x: 0
                                y: bar.y + bar.height + 2
                                width: parent.width
                                elide: Text.ElideRight
                                color: Theme.textDim
                                text: spendRoot.hoveredDay >= 0
                                    ? (spendRoot.dayTotal > 0
                                        ? Spend.fmtTokens(mrow.dayTok) + "  ·  "
                                          + Math.round(100 * mrow.dayTok / spendRoot.dayTotal)
                                          + "% of the day's tokens"
                                        : "nothing ran that day")
                                    : mrow.modelData.dispatched + " agents  ·  "
                                      + Spend.fmtTokens(mrow.modelData["in"]) + " in  /  "
                                      + Spend.fmtTokens(mrow.modelData["out"]) + " out"
                            }

                            // an invisible sizing anchor for the top line's
                            // height, so the bar's y does not depend on a
                            // laid-out sibling's height.
                            PixelText { id: mtop; visible: false; text: "X" }
                        }
                    }
                }

                // the tokens-per-day grid: one small square per day over the
                // trailing month, laid out like a GitHub contribution graph —
                // weeks step down the columns, weekday across the rows, so each
                // square sits under its own day of the week. A day's colour is
                // its share of the busiest day, in a single hue (accent2) stepped
                // in intensity over an unlit bgAlt cell (§3.3.1, §3.4); the day
                // under the pointer takes the brighter accent step (§3.2), and its
                // date + total replace the caption legend (§9.3 — a chart with no
                // key is a squiggle).
                Item {
                    id: chart
                    visible: spendRoot.hasDaily && spendRoot.hasModels
                    width: parent.chartW
                    height: gridH + 4 + chartCap.implicitHeight

                    readonly property var days: Spend.daily ? Spend.daily : []
                    readonly property int nDays: days.length

                    // the weekday the oldest day falls on (0 = Sunday), so column
                    // 0 is filled from that row down and each square lands under
                    // its weekday — the calendar shape of a contribution graph.
                    readonly property int firstDow:
                        nDays > 0 ? new Date(days[0].date + "T00:00:00").getDay() : 0
                    readonly property int nCols: Math.ceil((firstDow + nDays) / 7)

                    // the busiest single day is the intensity denominator, exactly
                    // as it was the tallest bar's denominator before.
                    readonly property real maxDay: {
                        var mx = 0;
                        for (var i = 0; i < days.length; ++i)
                            if (days[i].total > mx) mx = days[i].total;
                        return mx > 0 ? mx : 1;
                    }

                    readonly property int gap: 2
                    readonly property int cell:
                        Math.max(7, Math.min(13,
                            Math.floor((width - (nCols - 1) * gap) / nCols)))
                    readonly property int gridH: 7 * cell + 6 * gap

                    // amount -> one of four accent2 intensity steps over the unlit
                    // cell; a silent day is the bare bgAlt cell (§3.4), so the
                    // calendar shape still reads. One hue only (§3.3.1) — the
                    // intensity is the key, never a second colour.
                    function cellColor(total) {
                        if (total <= 0) return Theme.bgAlt;
                        var f = total / maxDay;
                        var a = f > 0.66 ? 1.0 : f > 0.33 ? 0.72
                              : f > 0.10 ? 0.48 : 0.28;
                        return Qt.tint(Theme.bgAlt, Qt.rgba(
                            Theme.accent2.r, Theme.accent2.g, Theme.accent2.b, a));
                    }

                    Repeater {
                        model: chart.days
                        delegate: Rectangle {
                            required property var modelData
                            required property int index
                            readonly property int slot: chart.firstDow + index
                            x: Math.floor(slot / 7) * (chart.cell + chart.gap)
                            y: (slot % 7) * (chart.cell + chart.gap)
                            width: chart.cell
                            height: chart.cell
                            radius: 1
                            color: spendRoot.hoveredDay === index
                                   ? Theme.accent
                                   : chart.cellColor(modelData.total)
                        }
                    }

                    // ONE hit area over the whole grid, not a MouseArea per cell.
                    // The 2px gaps between squares are not their own hit target:
                    // a per-cell area fired onExited crossing a gap, so the
                    // hover snapped back to the whole-period view for a frame
                    // between every two days (§5.1 — a gap is not a place the
                    // pointer can fall out of the thing). Here a gap maps to the
                    // square up-left of it (floor over cell+gap), and a position
                    // that resolves to no day at all — the caption row, an empty
                    // calendar slot — KEEPS the last hovered day rather than
                    // clearing it, so the readout only reverts when the pointer
                    // actually leaves the chart (onExited).
                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        function dayAt(mx, my) {
                            var step = chart.cell + chart.gap;
                            var col = Math.floor(mx / step);
                            var row = Math.floor(my / step);
                            if (col < 0 || col >= chart.nCols || row < 0 || row > 6)
                                return -1;
                            var idx = col * 7 + row - chart.firstDow;
                            return (idx >= 0 && idx < chart.nDays) ? idx : -1;
                        }
                        onPositionChanged: (m) => {
                            var idx = dayAt(m.x, m.y);
                            if (idx >= 0) spendRoot.hoveredDay = idx;
                        }
                        onExited: spendRoot.hoveredDay = -1
                    }
                    // the legend (§9.3): normally what the grid IS; under the
                    // pointer, the hovered day's readout — its date and token
                    // total, then that day's spend and how many agents ran, and
                    // the whole period's spend to read the day against. Wraps
                    // rather than elides so the day figures are never clipped;
                    // the rebind is instant, never animated (§9.3).
                    PixelText {
                        id: chartCap
                        y: chart.gridH + 4
                        width: parent.width
                        wrapMode: Text.WordWrap
                        color: Theme.textDim
                        text: (spendRoot.hoveredDay >= 0
                                && spendRoot.hoveredDay < chart.days.length)
                            ? chart.days[spendRoot.hoveredDay].date + "  "
                              + Spend.fmtTokens(spendRoot.dayTotal) + "\n"
                              + "$" + spendRoot.dayCost.toFixed(2) + " day  ·  "
                              + spendRoot.dayAgents + " agents  ·  $"
                              + spendRoot.totalCost + " total"
                            : "tokens / day · 30d"
                    }
                }
            }

            Item { width: 1; height: 6 }

            // ---------------------------------------------- system-wide totals
            PixelText {
                width: spendCol.width
                color: Theme.text
                text: {
                    var t = Spend.totals;
                    if (!t || t.dispatched === undefined) return "";
                    return t.dispatched + " agents  ·  $"
                         + (t.cost !== undefined ? t.cost.toFixed(2) : "0")
                         + " total";
                }
            }

            // the token split bar (metric 3): one bar, input vs output. Input
            // dwarfs output here, so output takes the brighter step (accent) to
            // stay visible; both are labelled below so the colour is not the key
            // (§3.3.1).
            Rectangle {
                id: split
                width: spendCol.width
                height: Math.max(6, Math.round(Theme.fontSize / 2))
                color: Theme.bgAlt
                border.width: 1
                border.color: Theme.border

                Rectangle {
                    id: inSeg
                    x: 1
                    y: 1
                    height: parent.height - 2
                    width: Math.round((parent.width - 2)
                           * (Spend.totals ? Spend.totals["in"] : 0)
                           / spendRoot.totalTokens)
                    color: Theme.accent2
                }
                Rectangle {
                    x: inSeg.x + inSeg.width
                    y: 1
                    height: parent.height - 2
                    width: Math.max(0, (parent.width - 2) - inSeg.width)
                    color: Theme.accent
                }
            }

            // the split legend: label + figure for each series, colour never
            // standing alone (§3.3.1).
            Item {
                width: spendCol.width
                implicitHeight: inLbl.implicitHeight
                height: implicitHeight
                PixelText {
                    id: inLbl
                    x: 0
                    color: Theme.textDim
                    text: "input " + Spend.fmtTokens(Spend.totals ? Spend.totals["in"] : 0)
                }
                PixelText {
                    x: Math.max(inLbl.x + inLbl.width + 8, parent.width - width)
                    color: Theme.textDim
                    text: "output " + Spend.fmtTokens(Spend.totals ? Spend.totals["out"] : 0)
                }
            }

            Item { width: 1; height: 6 }

            // the one honest line §10/§10.5 requires: the Claude dollar is a
            // compute-weight, not a bill. Only drawn when a Claude row is present.
            Para {
                visible: Spend.estimated
                width: spendCol.width
                color: win.fgDim
                text: "the Claude $ is a compute-weight (measured tokens × "
                    + "public API rates), not a bill; the hermes $ is the "
                    + "provider's own estimate."
            }
        }
    }
}
