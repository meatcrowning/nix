import QtQuick
import QtQml.Models

// One paragraph's worth of inline RUNS, wrapped and drawn as terminal rows.
//
// WHY THE WRAPPING IS DONE HERE instead of by `Text`'s own `Wrap`: a run of
// inline code or a link has to be a separate item (its own background, its own
// click target), and a Row of Texts wraps at RUN boundaries, not word ones. The
// font is monospace, so the arithmetic is exact — every glyph advances by the
// same measured `cellW` — and a line of N characters is N*cellW wide whatever
// it is made of. That is what lets a line be cut at a word boundary and then
// re-assembled out of several Texts with no drift.
//
// Each output line is exactly ONE font cell tall with zero gap between lines
// (docs/DESIGN.md §2.1, kitty's packing), which is also why nothing here scales a
// font size: `Theme.fontSize` is the desktop's one setting (§2.7) and the
// columns fall out of it.
Item {
    id: root

    property var runs: []
    property real cellW: 8            // measured advance, from Main.qml
    property color color: Theme.text
    property color codeColor: Theme.text
    property int indent: 0            // leading character cells
    property string query: ""         // search term; matching LINES highlight
    property bool current: false      // this block is the match being stepped to

    signal linkActivated(string href, string lt)
    signal linkHovered(string href)

    readonly property int cols: Math.max(8, Math.floor((width - indent * cellW) / cellW))
    readonly property string plain: {
        var s = "";
        for (var i = 0; i < runs.length; i++) s += runs[i].t;
        return s;
    }

    // ---- the wrap ----
    // Greedy, on whitespace, over a token stream that remembers which run each
    // token came from. A token longer than the whole line (a URL, a long path)
    // is hard-split rather than allowed to overflow: nothing here may draw
    // outside its own width, because the pane is clipped.
    //
    // The token stream depends on `runs` ALONE — not on the width — so it is
    // its own property rather than a call inside the wrap. As a call it re-ran
    // the regex and re-allocated every token on each re-evaluation of `lines`,
    // and `lines` re-evaluates several times per delegate (measured: 4.1).
    readonly property var toks: {
        var out = [];
        for (var i = 0; i < runs.length; i++) {
            var r = runs[i];
            var parts = String(r.t).split(/(\s+)/);
            for (var j = 0; j < parts.length; j++) {
                if (parts[j] === "") continue;
                out.push({ t: parts[j], sp: /^\s+$/.test(parts[j]),
                           k: r.k || "", href: r.href || "", lt: r.lt || "" });
            }
        }
        return out;
    }

    readonly property var lines: {
        // A delegate is built before layout has given it a width, and `cols`
        // floors to its minimum of 8 until it does. Wrapping at that width is
        // not merely a wasted pass: it produces ~10x the rows the delegate will
        // keep, and the Repeater below builds every one of them, only to throw
        // them away when the real width lands a moment later. Half of all wrap
        // evaluations during a scroll were this (98 of 201, measured).
        if (width <= 0) return [];
        var n = cols;
        var out = [], cur = [], used = 0;
        function push() {
            while (cur.length && cur[cur.length - 1].sp) cur.pop();
            out.push(cur);
            cur = [];
            used = 0;
        }
        for (var i = 0; i < toks.length; i++) {
            var t = toks[i], len = t.t.length;
            if (t.sp && used === 0) continue;             // no leading space on a wrap
            if (used + len > n && used > 0) push();
            while (len > n) {                             // a token longer than a line
                var head = t.t.slice(0, n - used);
                cur.push({ t: head, sp: false, k: t.k, href: t.href, lt: t.lt });
                push();
                t = { t: t.t.slice(head.length), sp: false, k: t.k, href: t.href, lt: t.lt };
                len = t.t.length;
            }
            cur.push(t);
            used += len;
        }
        push();
        return out;
    }

    implicitHeight: Math.max(Theme.lineHeight, lines.length * Theme.lineHeight)

    Column {
        x: root.indent * root.cellW
        width: parent.width - x
        spacing: 0

        Repeater {
            model: root.lines
            delegate: Item {
                id: lineItem
                required property var modelData
                required property int index
                width: parent.width
                height: Theme.lineHeight

                readonly property string lineText: {
                    var s = "";
                    for (var i = 0; i < modelData.length; i++) s += modelData[i].t;
                    return s;
                }
                // A hit HIGHLIGHTS THE LINE rather than the characters: the
                // matched substring can straddle two runs and two Texts, and a
                // per-character highlight would have to re-implement the layout
                // it is drawn over.
                readonly property bool hit: root.query.length > 1
                    && lineText.toLowerCase().indexOf(root.query.toLowerCase()) >= 0

                // A find mark is `dim` for every match and `accent` for the one
                // you are ON, exactly as surfer paints its own (docs/DESIGN.md
                // §3.6). It was `Theme.highlight`, the selection fill, which is
                // 1.15:1 against the pure-black page — measured offscreen, and
                // the reason he could barely see a hit at all.
                readonly property color fill: root.current ? Theme.accent : Theme.dim
                // The accent fill is bright, so the words on it invert to `bg`.
                // One binding per LINE that the words below read, never a
                // ternary per word: this delegate is one Text per word and the
                // pane's fade already pays that cost once (§3.1.1).
                readonly property color ink: (lineItem.hit && root.current)
                                             ? Theme.bg : root.color

                Rectangle {
                    anchors.fill: parent
                    visible: lineItem.hit
                    color: lineItem.fill
                }

                // ONE ITEM PER SEGMENT OF PROSE, and the chrome only where
                // there is chrome. Every segment used to be an Item wrapping
                // two Rectangles, a PixelText and a MouseArea — five items to
                // draw a word, on a line that is almost always nothing but
                // words. That was ~40% of the GUI thread during a scroll
                // (docs/perf-cpu-hotspots.md H2).
                //
                // The chooser is what makes it conditional: the background and
                // the hit target exist only for the kinds that use them, and
                // the Row still lays every segment out, so their geometry is
                // exact by construction. Positioning a separate chrome layer by
                // character arithmetic instead is WRONG and was tried: the font
                // advances 8.9px but Qt rounds each Text's width up to 9, so a
                // background drifts a pixel further off its text with every
                // segment in the row.
                Row {
                    spacing: 0
                    Repeater {
                        model: lineItem.modelData
                        delegate: DelegateChooser {
                            role: "k"

                            // Inline code takes the inset background every
                            // other inset surface on this desktop takes
                            // (Theme.bgAlt, §3.1) — no new colour, and it reads
                            // against the body text without a second hue.
                            //
                            // On the CURRENT match's accent bar it gives that
                            // chrome up: `bgAlt` inside an accent fill is a
                            // hole, and `bg` ink on `bgAlt` cannot be read at
                            // all. The bar is the inset surface there.
                            DelegateChoice {
                                roleValue: "code"
                                Rectangle {
                                    width: codeLabel.implicitWidth
                                    height: Theme.lineHeight
                                    color: (lineItem.hit && root.current)
                                           ? "transparent" : Theme.bgAlt
                                    PixelText {
                                        id: codeLabel
                                        text: modelData.t
                                        color: (lineItem.hit && root.current)
                                               ? Theme.bg : root.codeColor
                                    }
                                }
                            }

                            // The palette is ONE HUE and body text IS the accent
                            // (§3.1), so there is no brighter colour to promote
                            // a link to. It is underlined instead — a property
                            // of the type, not a new colour — and says so on
                            // hover with the same selection fill a menu row
                            // takes (§7.2 — hover lightens, one step up the
                            // ladder).
                            DelegateChoice {
                                roleValue: "link"
                                Rectangle {
                                    width: linkLabel.implicitWidth
                                    height: Theme.lineHeight
                                    color: ma.containsMouse ? Theme.highlight
                                                            : "transparent"
                                    PixelText {
                                        id: linkLabel
                                        text: modelData.t
                                        font.underline: true
                                        color: lineItem.ink
                                    }
                                    MouseArea {
                                        id: ma
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        acceptedButtons: Qt.LeftButton
                                        cursorShape: Qt.PointingHandCursor
                                        onEntered: root.linkHovered(modelData.href)
                                        onExited: root.linkHovered("")
                                        onClicked: root.linkActivated(modelData.href,
                                                                      modelData.lt)
                                    }
                                }
                            }

                            // Everything else: a word, and nothing around it.
                            DelegateChoice {
                                PixelText {
                                    text: modelData.t
                                    color: lineItem.ink
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
