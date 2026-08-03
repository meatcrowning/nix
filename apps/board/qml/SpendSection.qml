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
// how many agents it was dispatched, its cost, and its tokens in/out. Below the
// list, one split bar for the whole system's tokens (input vs output), and the
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

            // ---------------------------------------- one ranked row per model
            Repeater {
                model: Spend.models ? Spend.models : []
                delegate: Item {
                    id: mrow
                    required property var modelData
                    width: spendCol.width
                    implicitHeight: mtop.implicitHeight + 2 + bar.height
                                    + 2 + mbot.implicitHeight + 8
                    height: implicitHeight

                    Rectangle {
                        anchors.fill: parent
                        anchors.bottomMargin: 8
                        color: mma.containsMouse ? Theme.highlight : "transparent"
                    }
                    MouseArea { id: mma; anchors.fill: parent; hoverEnabled: true }

                    // top line: model (its own legend, at foreground) hard left,
                    // its cost hard right (§5.4 paired edges).
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
                        text: "$" + mrow.modelData.cost.toFixed(2)
                    }

                    // the cost-share bar (§9.3): the whole hue is accent2, the
                    // length is the meaning. Unlit track is bgAlt, never dim (§3.4).
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
                            width: Math.round((parent.width - 2)
                                   * mrow.modelData.cost / spendRoot.maxCost)
                            visible: width > 0
                            color: Theme.accent2
                        }
                    }

                    // the measured figures: agents dispatched, tokens in/out.
                    PixelText {
                        id: mbot
                        x: 0
                        y: bar.y + bar.height + 2
                        width: parent.width
                        elide: Text.ElideRight
                        color: Theme.textDim
                        text: mrow.modelData.dispatched + " agents  ·  "
                            + Spend.fmtTokens(mrow.modelData["in"]) + " in  /  "
                            + Spend.fmtTokens(mrow.modelData["out"]) + " out"
                    }

                    // an invisible sizing anchor for the top line's height, so
                    // the bar's y does not depend on a laid-out sibling's height.
                    PixelText { id: mtop; visible: false; text: "X" }
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
