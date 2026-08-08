import QtQuick

// ONE markdown block, drawn. The parse (`mdparse.py`) decides what a block IS;
// this decides what it looks like, and every decision in here comes out of
// ~/nix/docs/DESIGN.md rather than out of a markdown stylesheet:
//
//   * NOTHING is bold and nothing is drawn at another size. The font ships
//     Regular only (§2.2) and the size is one desktop-wide setting (§2.1/§2.7),
//     so a heading is told apart by a RULE and by spacing — position and
//     colour, which is exactly what §20 says emphasis is carried by here.
//   * There are no invented colours, and no colour is read off `Theme` where
//     the window's focus can change it — the pane hands `fg`/`fgDim`/`fgAccent`
//     in already faded (§3.1.1). Body text is `Theme.text` (which IS the
//     accent, §3.1); a quotation is the secondary label `Theme.textDim` behind
//     the 2px accent gutter §9.1 already uses for "this row"; a code block is
//     the inset `Theme.bgAlt` inside the 1px `Theme.border` hairline §4 uses
//     for every framed surface. No radius anywhere (§4).
//   * A row of text is exactly one font cell (§2.1). The gap between blocks is
//     one blank cell — the blank line the markdown source itself has — and not
//     a margin scale.
Item {
    id: root

    property var block: ({})
    property real cellW: 8
    property string query: ""
    property bool current: false      // the search match the user is ON
    // The three foreground tones, passed in already faded by the pane
    // (docs/DESIGN.md §3.1.1) rather than read off Theme here: a block must not
    // know whether the window is focused, and one ternary per pane beats one
    // per block per focus change.
    property color fg: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent

    readonly property string btype: block.type || "p"
    readonly property int level: block.level || 1
    // One blank line above every block, two above a heading (which is what the
    // source looks like), none between consecutive list items — they are rows.
    property int topGap: 0

    signal linkActivated(string href, string lt)
    signal linkHovered(string href)

    implicitHeight: topGap + body.implicitHeight

    // The current match is told apart by its FILL — an accent bar where the
    // other matches get `dim` (docs/DESIGN.md §3.6) — and not by §9.1's 2px
    // gutter. That gutter used to be here at `x: -6` and drew NOTHING: a block
    // delegate sits at x=0 in the list's content item, so a negative x is
    // outside the viewport and `clip: true` ate every pixel of it. Measured
    // offscreen — all three match rows came back identical to the pixel, which
    // is why find-next read as a scroll and nothing else. §9.1's gutter exists
    // to disambiguate a uniform selection fill under a hovering pointer; a
    // whole different fill needs no help, and a document is not a hover list.

    Item {
        id: body
        y: root.topGap
        width: parent.width
        implicitHeight: content.implicitHeight

        Loader {
            id: content
            width: parent.width
            // Synchronous, like everything else that has to be in a frame
            // (§6.1): a document must never paint a hole where a block will be.
            asynchronous: false
            sourceComponent: root.btype === "code" ? codeBlock
                           : root.btype === "table" ? tableBlock
                           : root.btype === "hr" ? ruleBlock
                           : textBlock
        }
    }

    // ---- paragraphs, headings, list items, quotations ----
    Component {
        id: textBlock
        Item {
            implicitHeight: (headRule.visible ? Theme.lineHeight : 0) + rich.implicitHeight

            // h1 takes an accent rule, h2 the ordinary border hairline: the two
            // structural levels of a document, told apart the way every other
            // pair of states on this desktop is — a step on one hue (§3.3).
            Rectangle {
                id: headRule
                visible: root.btype === "h" && root.level <= 2
                width: parent.width
                height: 1
                y: Math.floor(Theme.fontSize / 2)
                color: root.level === 1 ? root.fgAccent : Theme.border
            }

            // A quotation's gutter — 2px accent, the width every accent edge on
            // this desktop is (§4).
            Rectangle {
                visible: root.btype === "quote"
                x: (root.block.depth > 1 ? (root.block.depth - 1) * 2 * root.cellW : 0)
                y: headRule.visible ? Theme.fontSize : 0
                width: 2
                height: rich.implicitHeight
                color: root.fgAccent
            }

            // The list marker sits in its own column so the text of a wrapped
            // item lines up under itself rather than under the bullet. `-` and
            // `1.`, ASCII, because the font has no bullet (§2.3).
            PixelText {
                id: marker
                visible: root.btype === "li"
                x: (root.block.depth || 0) * 2 * root.cellW
                y: headRule.visible ? Theme.fontSize : 0
                text: root.block.marker || "-"
                color: root.fgDim
            }

            RichText {
                id: rich
                y: headRule.visible ? Theme.fontSize : 0
                x: root.btype === "li"
                     ? ((root.block.depth || 0) * 2 + String(root.block.marker || "-").length + 1) * root.cellW
                   : root.btype === "quote"
                     ? ((root.block.depth || 1) * 2) * root.cellW
                   : root.btype === "h" ? Math.max(0, root.level - 2) * 2 * root.cellW
                   : 0
                width: parent.width - x
                cellW: root.cellW
                runs: root.block.runs || []
                query: root.query
                current: root.current
                color: root.btype === "quote" ? root.fgDim : root.fg
                codeColor: root.fg
                onLinkActivated: (href, lt) => root.linkActivated(href, lt)
                onLinkHovered: (href) => root.linkHovered(href)
            }
        }
    }

    // ---- fenced code ----
    // Wrapped, never scrolled sideways and never elided: the content has to
    // stay complete, because it is meant to be read and copied, and a nested
    // scroll region is not a thing this desktop has (§9.2). A continuation
    // carries a two-cell hanging indent so a wrapped line is visibly one line.
    Component {
        id: codeBlock
        Rectangle {
            id: box
            implicitHeight: Math.max(Theme.lineHeight, codeCol.implicitHeight) + 8
            color: Theme.bgAlt
            radius: Theme.rounding
            border.width: Theme.ctrlBorder
            border.color: Theme.border

            readonly property int cols: Math.max(8, Math.floor((width - 12) / root.cellW))
            readonly property var wrapped: {
                var src = root.block.lines || [], out = [];
                for (var i = 0; i < src.length; i++) {
                    var s = String(src[i]);
                    if (s.length <= cols) { out.push(s); continue; }
                    out.push(s.slice(0, cols));
                    var rest = s.slice(cols);
                    while (rest.length > 0) {
                        out.push("  " + rest.slice(0, Math.max(1, cols - 2)));
                        rest = rest.slice(Math.max(1, cols - 2));
                    }
                }
                return out;
            }

            Column {
                id: codeCol
                x: 6
                y: 4
                width: parent.width - 12
                spacing: 0
                Repeater {
                    model: box.wrapped
                    delegate: Item {
                        id: codeLine
                        required property var modelData
                        width: parent.width
                        height: Theme.lineHeight
                        readonly property bool hit: root.query.length > 1
                            && String(modelData).toLowerCase().indexOf(root.query.toLowerCase()) >= 0
                        // dim for a match, accent for the one you are on — the
                        // same two marks as prose (docs/DESIGN.md §3.6)
                        Rectangle {
                            anchors.fill: parent
                            visible: codeLine.hit
                            color: root.current ? Theme.accent : Theme.dim
                        }
                        PixelText {
                            text: codeLine.modelData
                            color: (codeLine.hit && root.current) ? Theme.bg : root.fg
                        }
                    }
                }
            }
        }
    }

    // ---- tables ----
    // Monospace makes a table free: a column is as many CELLS wide as its
    // widest entry, and the columns are shrunk proportionally (never below four
    // characters) when the row does not fit. Cells elide, which is allowed with
    // this font — Qt substitutes ASCII periods for the missing U+2026 (§2.2).
    Component {
        id: tableBlock
        Item {
            id: tbl
            implicitHeight: rowCol.implicitHeight

            readonly property var rows: root.block.rows || []
            readonly property int ncols: {
                var n = 0;
                for (var i = 0; i < rows.length; i++) n = Math.max(n, rows[i].length);
                return n;
            }
            function cellText(cell) {
                var s = "";
                for (var i = 0; cell && i < cell.length; i++) s += cell[i].t;
                return s;
            }
            // widths in CHARACTER CELLS, then fitted to the width available
            readonly property var widths: {
                var w = [], i, c;
                for (c = 0; c < ncols; c++) w.push(3);
                for (i = 0; i < rows.length; i++)
                    for (c = 0; c < rows[i].length; c++)
                        w[c] = Math.max(w[c], cellText(rows[i][c]).length);
                var avail = Math.max(8, Math.floor(tbl.width / root.cellW)) - 2 * (ncols - 1);
                var total = 0;
                for (c = 0; c < ncols; c++) total += w[c];
                if (total > avail && total > 0) {
                    var k = avail / total;
                    for (c = 0; c < ncols; c++) w[c] = Math.max(4, Math.floor(w[c] * k));
                }
                return w;
            }

            Column {
                id: rowCol
                width: parent.width
                spacing: 0
                Repeater {
                    model: tbl.rows
                    delegate: Item {
                        id: trow
                        required property var modelData
                        required property int index
                        width: parent.width
                        height: Theme.lineHeight + (index === 0 ? 1 : 0)

                        // `cellText` takes a CELL — a list of runs — and this
                        // delegate's modelData is a ROW, a list of cells. Handed
                        // one, it read `.t` off each cell and joined the word
                        // "undefined" once per column: a table row lit up for
                        // the query `undefined` and for NOTHING else, so a match
                        // inside a table was the one hit with no mark at all
                        // (measured offscreen). The row's text is its cells'.
                        readonly property string rowText: {
                            var s = "";
                            for (var i = 0; i < modelData.length; i++)
                                s += tbl.cellText(modelData[i]) + " ";
                            return s;
                        }
                        readonly property bool hit: root.query.length > 1
                            && rowText.toLowerCase()
                                  .indexOf(root.query.toLowerCase()) >= 0

                        Rectangle {
                            anchors.fill: parent
                            visible: trow.hit
                            color: root.current ? Theme.accent : Theme.dim
                        }
                        Row {
                            spacing: 2 * root.cellW
                            Repeater {
                                model: trow.modelData
                                delegate: PixelText {
                                    required property var modelData
                                    required property int index
                                    width: (tbl.widths[index] || 4) * root.cellW
                                    height: Theme.lineHeight
                                    elide: Text.ElideRight
                                    text: tbl.cellText(modelData)
                                    // The header row is the label; the body is
                                    // the reading. Two tiers on one hue (§3.2)
                                    // — both inverting to `bg` on the current
                                    // match's accent bar (§3.6).
                                    color: (trow.hit && root.current) ? Theme.bg
                                         : trow.index === 0 ? root.fg : root.fgDim
                                }
                            }
                        }
                        Rectangle {   // hairline under the header row
                            visible: trow.index === 0
                            anchors.bottom: parent.bottom
                            width: parent.width
                            height: 1
                            color: Theme.border
                        }
                    }
                }
            }
        }
    }

    // ---- a horizontal rule ----
    Component {
        id: ruleBlock
        Item {
            implicitHeight: Theme.lineHeight
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                height: 1
                color: Theme.border
            }
        }
    }
}
