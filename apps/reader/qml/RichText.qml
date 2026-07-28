import QtQuick

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
    function _tokens() {
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
        var n = cols, toks = _tokens();
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

    implicitHeight: Math.max(Theme.fontSize, lines.length * Theme.fontSize)

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
                height: Theme.fontSize

                readonly property string lineText: {
                    var s = "";
                    for (var i = 0; i < modelData.length; i++) s += modelData[i].t;
                    return s;
                }
                // A hit HIGHLIGHTS THE LINE rather than the characters: the
                // matched substring can straddle two runs and two Texts, and a
                // per-character highlight would have to re-implement the layout
                // it is drawn over. One row, one selection fill — the same
                // Theme.highlight every list on this desktop selects with
                // (§9.1).
                readonly property bool hit: root.query.length > 1
                    && lineText.toLowerCase().indexOf(root.query.toLowerCase()) >= 0

                Rectangle {
                    anchors.fill: parent
                    visible: lineItem.hit
                    color: Theme.highlight
                }

                Row {
                    spacing: 0
                    Repeater {
                        model: lineItem.modelData
                        delegate: Item {
                            id: seg
                            required property var modelData
                            width: label.implicitWidth
                            height: Theme.fontSize

                            readonly property bool isLink: modelData.k === "link"
                            readonly property bool isCode: modelData.k === "code"

                            // Inline code takes the inset background every
                            // other inset surface on this desktop takes
                            // (Theme.bgAlt, §3.1) — no new colour, and it reads
                            // against the body text without a second hue.
                            Rectangle {
                                anchors.fill: parent
                                visible: seg.isCode
                                color: Theme.bgAlt
                            }
                            // A link's hover fill is the same selection fill a
                            // menu row takes (§7.2 — hover lightens, one step up
                            // the ladder).
                            Rectangle {
                                anchors.fill: parent
                                visible: seg.isLink && ma.containsMouse
                                color: Theme.highlight
                            }

                            PixelText {
                                id: label
                                text: seg.modelData.t
                                // The palette is ONE HUE and body text IS the
                                // accent (§3.1), so there is no brighter colour
                                // to promote a link to. It is underlined
                                // instead — a property of the type, not a new
                                // colour — and says so on hover with the fill
                                // above.
                                font.underline: seg.isLink
                                color: seg.isCode ? root.codeColor : root.color
                            }

                            MouseArea {
                                id: ma
                                anchors.fill: parent
                                enabled: seg.isLink
                                hoverEnabled: seg.isLink
                                acceptedButtons: Qt.LeftButton
                                cursorShape: Qt.PointingHandCursor
                                onEntered: root.linkHovered(seg.modelData.href)
                                onExited: root.linkHovered("")
                                onClicked: root.linkActivated(seg.modelData.href,
                                                              seg.modelData.lt)
                            }
                        }
                    }
                }
            }
        }
    }
}
