import QtQuick
import QtQuick.Shapes

// The as-you-type spelling marker, for ANY text-entry item in `apps/` —
// `TextEdit`, `TextArea` or `TextInput`. `pylib/spellcheck.py` decides what is
// a word and what is wrong; this file is only how that reaches the glass, and
// it is the only place in the apps that draws it.
//
// docs/DESIGN.md §3.6 is the nearest precedent (a find mark) and the reasoning
// carries: the palette is monochromatic, so a state that must be noticed
// borrows from the status ramp rather than inventing a hue. A misspelling is
// the ramp's `crit` — the one slot given extra chroma so an alarm can read
// against a monochrome desktop (§3.1) — drawn as a **1px dashed underline,
// 1 on / 1 off**, which is the pixel-era spelling idiom and cannot be mistaken
// for the accent-coloured find fill or for a selection.
//
// **Qt Quick draws exactly one underline style and ignores its colour.**
// Measured offscreen, PySide6 6.11: of `SingleUnderline`, `DashUnderline`,
// `DotLine`, `DashDotLine`, `WaveUnderline` and `SpellCheckUnderline` set on a
// `QTextCharFormat` through a `QSyntaxHighlighter`, only `SingleUnderline`
// reaches the scenegraph at all, and it paints in the text's own colour —
// `setUnderlineColor` is dropped. So the marker cannot be a character format
// (which is what a Qt Widgets app would do); it is geometry, and
// `QtQuick.Shapes` is what draws a real 1px dash pattern.
//
// Usage — a SIBLING of the text item, filling it, in the same coordinate space
// (inside the flickable's content item when the text scrolls):
//
//     TextEdit { id: input; ... }
//     SpellMarks { target: input; viewport: flick; anchors.fill: input }
//
// and, in the right-click handler, prepend `marks.menuItems(pos)` to whatever
// the app's own context menu already offers. `menuItems` returns [] unless the
// word under `pos` is actually misspelled, so a menu gains nothing on a
// machine with no dictionary — §10's rule that an offered action must not be
// able to silently fail.
Item {
    id: root

    //: The text item being checked. Must expose `text`, `positionToRectangle`,
    //: `positionAt`, `remove` and `insert` — all three QML text types do.
    property Item target: null

    //: Optional. When the text scrolls inside a Flickable, only the visible
    //: range is judged: a 40k-word document costs a screenful of words per
    //: refresh instead of all of them.
    property Flickable viewport: null

    //: Off switches the whole thing off and clears the marks. A field that is
    //: not prose (a filename, a query, a path) simply does not host one of
    //: these — see apps/AGENTS.md.
    property bool active: true

    //: Left inset of the text inside `target`, for the second row of a word
    //: that wrapped. Zero is right for every current call site.
    property real textLeft: 0

    //: How a correction is applied. The default is `remove` + `insert`, which
    //: costs two undo steps; a host with a real edit block (editor's
    //: `Buffers`) passes a one-step function instead.
    property var replaceFn: null

    readonly property bool available: typeof Spell !== "undefined" && Spell.available
    readonly property color markColor: typeof Theme !== "undefined" ? Theme.crit : "#ff6d6d"

    //: [[start, end], ...] — character ranges, not pixels.
    property var spans: []

    // A rebuild is debounced: it is one Python call, but it is a Python call
    // per keystroke otherwise, and the answer for a half-typed word is noise.
    Timer {
        id: debounce
        interval: 250
        onTriggered: root.rebuild()
    }

    function schedule() {
        if (!root.active || !root.available || !root.target) {
            if (root.spans.length > 0) { root.spans = []; root.regeometry(); }
            return;
        }
        debounce.restart();
    }

    function rebuild() {
        if (!root.active || !root.available || !root.target) {
            root.spans = [];
            root.regeometry();
            return;
        }
        var from = 0, to = -1;
        if (viewport) {
            // One line of slack either side, so the mark is already there when
            // a partly-visible row scrolls fully into view.
            from = target.positionAt(0, Math.max(0, viewport.contentY - 40));
            to = target.positionAt(target.width,
                                   viewport.contentY + viewport.height + 40);
            if (to <= from) to = -1;
        }
        root.spans = Spell.spans(target.text, from, to);
        root.regeometry();
    }

    // ---- geometry -----------------------------------------------------------
    property var polys: []

    function regeometry() {
        if (!target || root.spans.length === 0) { root.polys = []; return; }
        var out = [];
        for (var i = 0; i < root.spans.length; i++) {
            var a = target.positionToRectangle(root.spans[i][0]);
            var b = target.positionToRectangle(root.spans[i][1]);
            if (Math.abs(a.y - b.y) < 0.5) {
                out.push(root.seg(a.x, b.x, a));
            } else {
                // The word wrapped. A word never wraps twice, so this is two
                // segments: to the right edge on its first row, from the left
                // inset on its second.
                out.push(root.seg(a.x, target.width, a));
                out.push(root.seg(root.textLeft, b.x, b));
            }
        }
        root.polys = out;
    }

    //: One horizontal 1px run. The `+0.5` puts the stroke on a pixel row
    //: rather than across two, or a 1px dash pattern renders as grey mush.
    function seg(x0, x1, rect) {
        var y = Math.round(rect.y + rect.height) - 1.5;
        return [Qt.point(Math.round(x0) + 0.5, y),
                Qt.point(Math.max(Math.round(x0) + 1, Math.round(x1)) - 0.5, y)];
    }

    Shape {
        anchors.fill: parent
        asynchronous: false
        //: The default (geometry) renderer on purpose: it is the one that
        //: honours `dashPattern`, and this shape is six straight lines.
        visible: root.active && root.polys.length > 0
        ShapePath {
            strokeColor: root.markColor
            strokeWidth: 1
            fillColor: "transparent"
            strokeStyle: ShapePath.DashLine
            dashPattern: [1, 1]
            capStyle: ShapePath.FlatCap
            PathMultiline { paths: root.polys }
        }
    }

    // ---- the right-click offer ----------------------------------------------
    //: Menu items for the word at character `pos`, in `CtxMenu`'s own
    //: `{label, enabled, separator, trigger}` shape, or [] when there is
    //: nothing to offer. Suggestions first (they are why the menu was opened),
    //: then "add to dictionary", then a separator before the app's own items.
    function menuItems(pos) {
        if (!root.active || !root.available || !root.target) return [];
        var w = Spell.wordAt(target.text, pos);
        if (!w || w.start < 0 || !w.bad) return [];
        var items = [];
        var sug = Spell.suggest(w.word);
        for (var i = 0; i < sug.length; i++) {
            items.push({ label: sug[i], trigger: root.corrector(w.start, w.end, sug[i]) });
        }
        if (sug.length === 0)
            items.push({ label: "no suggestions", enabled: false });
        items.push({ label: "add to dictionary",
                     trigger: root.learner(w.word) });
        items.push({ separator: true });
        return items;
    }

    function corrector(s, e, word) {
        return function () { root.correct(s, e, word); };
    }

    function learner(word) {
        return function () {
            Spell.learn(word);
            root.rebuild();
        };
    }

    function correct(s, e, word) {
        if (replaceFn) {
            replaceFn(s, e, word);
        } else {
            target.remove(s, e);
            target.insert(s, word);
        }
        rebuild();
    }

    // ---- what makes it re-run ------------------------------------------------
    Connections {
        target: root.target
        enabled: root.target !== null
        function onTextChanged() { root.schedule(); }
        function onWidthChanged() { root.regeometry(); }
        function onHeightChanged() { root.regeometry(); }
    }

    Connections {
        target: root.viewport
        enabled: root.viewport !== null
        function onContentYChanged() { root.schedule(); }
    }

    onActiveChanged: active ? rebuild() : (spans = [], regeometry())
    Component.onCompleted: schedule()
}
