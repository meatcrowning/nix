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
// Beside the list, right, a COMPACT TOKENS-PER-DAY CHART: one thin vertical bar
// per day over the trailing month. Hovering a day rebinds the left bars to that
// day — same bars, same hue, their length re-read as each model's share of THAT
// day's tokens rather than of total cost — and the chart's caption becomes that
// day's date and total (§9.3: one hover sample re-reads a sibling readout). With
// nothing hovered the left bars are the whole-period cost share, as ever. The
// per-day, per-model series is `boardspend.py`'s `Spend.daily`.
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

    // ---- the tokens-per-day chart, and what hovering one of its days does ----
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

    //: the hovered day's {family: tokens} map, or null when none is hovered.
    readonly property var dayModels:
        (hoveredDay >= 0 && Spend.daily && hoveredDay < Spend.daily.length)
        ? Spend.daily[hoveredDay].models : null

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

            // ---- the ranked model list (left) beside the per-day chart (right).
            // The list is the same ranked horizontal-bar vocabulary as before;
            // the chart is a compact month of tokens-per-day, and hovering one of
            // its days rebinds these left bars to that day (docs/DESIGN.md §9.3).
            Row {
                width: spendCol.width
                spacing: 12

                //: the chart's width — compact, a month of thin bars — but the
                //  list keeps the rest. Zero (chart hidden) gives the list all.
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

                            Rectangle {
                                anchors.fill: parent
                                anchors.bottomMargin: 8
                                color: mma.containsMouse ? Theme.highlight : "transparent"
                            }
                            MouseArea { id: mma; anchors.fill: parent; hoverEnabled: true }

                            // top line: model (its own legend, at foreground) hard
                            // left; hard right its cost, or — with a day hovered —
                            // its tokens on that day (§5.4 paired edges).
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
                                    ? Spend.fmtTokens(mrow.dayTok)
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
                            // default; with a day hovered, this model's share of
                            // that day (the date itself is the chart's caption).
                            PixelText {
                                id: mbot
                                x: 0
                                y: bar.y + bar.height + 2
                                width: parent.width
                                elide: Text.ElideRight
                                color: Theme.textDim
                                text: spendRoot.hoveredDay >= 0
                                    ? (spendRoot.dayTotal > 0
                                        ? Math.round(100 * mrow.dayTok / spendRoot.dayTotal)
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

                // the tokens-per-day chart: one thin vertical bar per day over
                // the trailing month, its height that day's share of the busiest
                // day. Hover a bar to rebind the list. The section's hue is
                // accent2; the day under the pointer takes the brighter accent
                // step (§3.2), and its date + total replace the caption legend
                // (§9.3 — a chart with no key is a squiggle).
                Item {
                    id: chart
                    visible: spendRoot.hasDaily && spendRoot.hasModels
                    width: parent.chartW
                    height: chartBars.height + 4 + chartCap.implicitHeight

                    readonly property var days: Spend.daily ? Spend.daily : []
                    readonly property int nDays: days.length > 0 ? days.length : 30
                    readonly property int barsH: 56
                    readonly property real maxDay: {
                        var mx = 0;
                        for (var i = 0; i < days.length; ++i)
                            if (days[i].total > mx) mx = days[i].total;
                        return mx > 0 ? mx : 1;
                    }
                    readonly property int barW:
                        Math.max(2, Math.floor((width - (nDays - 1)) / nDays))

                    Row {
                        id: chartBars
                        width: parent.width
                        height: chart.barsH
                        spacing: 1
                        Repeater {
                            model: chart.days
                            delegate: Item {
                                required property var modelData
                                required property int index
                                width: chart.barW
                                height: chartBars.height

                                // the day's bar, rising from the baseline. No
                                // per-bar bgAlt track — a month of 1px tracks is
                                // noise; the 1px baseline below is the axis, and a
                                // silent day is simply no bar.
                                Rectangle {
                                    anchors.bottom: parent.bottom
                                    width: parent.width
                                    height: modelData.total > 0
                                        ? Math.max(1, Math.round((chartBars.height - 1)
                                            * modelData.total / chart.maxDay))
                                        : 0
                                    color: spendRoot.hoveredDay === index
                                           ? Theme.accent : Theme.accent2
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    onEntered: spendRoot.hoveredDay = index
                                    onExited: if (spendRoot.hoveredDay === index)
                                                  spendRoot.hoveredDay = -1
                                }
                            }
                        }
                    }
                    // the baseline the bars stand on (§4, a 1px border hairline).
                    Rectangle {
                        y: chartBars.height
                        width: parent.width
                        height: 1
                        color: Theme.border
                    }
                    // the legend (§9.3): normally what the chart IS; under the
                    // pointer, the hovered day's date and token total.
                    PixelText {
                        id: chartCap
                        y: chartBars.height + 4
                        width: parent.width
                        elide: Text.ElideRight
                        color: Theme.textDim
                        text: (spendRoot.hoveredDay >= 0
                                && spendRoot.hoveredDay < chart.days.length)
                            ? chart.days[spendRoot.hoveredDay].date + "  "
                              + Spend.fmtTokens(spendRoot.dayTotal)
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
