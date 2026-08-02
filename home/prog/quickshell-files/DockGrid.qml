import QtQuick

// The dock panel's widget grid: `columns` columns by `rows` rows, Theme.gap
// between them, filling the panel exactly. A widget occupies a
// (col, row, colSpan, rowSpan) rectangle in those coordinates, which is what
// lets it "take up as much space as possible" — the full width, half of it, or a
// single cell.
//
// IT IS ONE PAGE, AND IT MUST STAY ONE PAGE. The row height is derived from the
// panel's own height (`rows` divides it) rather than being a fixed pixel value,
// so every widget is on screen at once with no scrolling, at any panel height.
// That is a deliberate constraint on what can be added: a new widget takes rows
// away from the others, and if nothing can spare them it doesn't fit. The
// alternative — a taller-than-the-screen grid that scrolls — was tried first and
// is exactly what the user didn't want.
//
// Neither count is derived from the panel WIDTH. The panel only ranges over
// 14-33% of the screen, and letting the geometry change inside that range would
// silently invalidate every saved placement each time the edge was dragged.
// Widening the panel makes each column wider instead.
//
// `placements` is plain data on purpose. It ships as a constant default; phase 3
// makes it the thing the user drags around and the thing that gets persisted,
// and nothing else in here has to change for that — cellX/cellY/cellW/cellH stay
// the single place grid coordinates become pixels, and the drag reads back
// through them.
Item {
    id: root

    property bool active: true

    readonly property int columns: 4
    readonly property int rows: 29
    readonly property int spacing: Theme.gap

    readonly property real cellWidth: (width - spacing * (columns - 1)) / columns
    readonly property real cellHeight: (height - spacing * (rows - 1)) / rows

    function cellX(col) { return col * (cellWidth + spacing); }
    function cellY(row) { return row * (cellHeight + spacing); }
    function cellW(colSpan) { return colSpan * cellWidth + (colSpan - 1) * spacing; }
    function cellH(rowSpan) { return rowSpan * cellHeight + (rowSpan - 1) * spacing; }

    // Reading bottom-up, which is how it was asked for: calendar and clock side
    // by side on the bottom row, the forecast above them, the player above that,
    // and the task manager taking everything that's left — it is the one widget
    // whose usefulness scales with the space it gets, since every extra row is
    // another process you can see.
    //
    // The other four are sized to what they actually need, which is measurable
    // rather than a matter of taste:
    //
    //     qs ipc call live tiles      # per tile: got, wants, slack
    //
    // Aim for a small POSITIVE slack. But read it knowing that `wants` is the
    // widget's NATURAL height, not a minimum: the calendar's weeks, the clock's
    // face and the player's artwork all grow or shrink into the tile they are
    // given rather than leaving a gap under them, so the clock sitting at a
    // large negative slack just means it is drawing a smaller face — which is
    // the point, since the bottom row is sized by the calendar.
    // The player's queue drawer takes its rows FROM THE FORECAST, not from the
    // task manager: the forecast is the one widget below it that has a genuine
    // condensed form (current conditions on one line over a MINIATURE of the
    // graph — see WeatherContent's `condensed`), whereas a shorter task table
    // just shows fewer processes and a shorter queue is the thing being asked
    // for. Four rows is the most it may take, and the cap below is what it
    // actually gets.
    readonly property int queueRows: 4
    readonly property bool queueOpen: SettingsStore.d.mediaQueueOpen

    // …but only as many of them as the forecast can actually spare. Four rows
    // is four rows of a grid whose row height is DERIVED from the panel height,
    // so on a short panel (or a tall dock header, which eats the grid) the two
    // rows the forecast keeps can be shorter than the single line its condensed
    // form exists to show — and a widget squeezed below its own minimum draws
    // nothing at all. This is the only queue-side number that may depend on the
    // panel's geometry; it is NOT in `placements` (see below), so capping it
    // costs nothing.
    //
    // The floor mirrors WeatherContent's `minCondensed` (its pad plus one line
    // of text). It is duplicated rather than read off the loaded item because
    // the tile's Loader is asynchronous: a binding through `loader.item` would
    // be undefined for the first frames and the grid would re-lay itself out
    // when it resolved.
    // Mirrors WeatherContent's `minCondensed`: its padding, one line of text,
    // the 3px gap and `minMiniGraph` (20) — because the condensed forecast is
    // not a bare line, it keeps a miniature of the graph, and asking for that
    // form is asking for the room it needs. Raising this is what buys the room,
    // and it buys it in whole ROWS (35.3px on this panel) — there is no smaller
    // unit, so a few pixels either side of a row boundary decide whether the
    // forecast takes two rows or three. At `minMiniGraph` 24 it demanded three
    // (97.9px of tile) and the drawer got three rows; at 20 it fits in two
    // (62.6px of tile = 60.6px of content against a 58px minimum, the miniature
    // graph still drawn at 22.6px) and the drawer has its fourth row back.
    //
    // PLUS `tileInset`, and that term is not a rounding allowance — leaving it
    // out is what made the condensed forecast a bare header line for its whole
    // life. What this number reserves is a TILE, but what has to fit inside it
    // is `DockTile`'s Loader, which is anchored with `margins: 1` for the frame
    // and is therefore 2px shorter than the tile. Measured on this panel: two
    // grid rows = 62.6px of tile = 60.6px of content, against a 62px minimum —
    // one and a half pixels short, so `miniGraph` went false, the graph was
    // dropped ENTIRELY and the widget drew the bare-header tier that only
    // exists for panels with no room at all. Any floor mirrored from a content
    // component has to carry the frame it is drawn inside.
    readonly property real tileInset: 2
    readonly property real minWeatherPx: 2 * 10 + Theme.fontSize + 3 + 20 + tileInset
    readonly property int minWeatherRows: cellHeight > 0
        ? Math.max(1, Math.ceil((minWeatherPx + spacing) / (cellHeight + spacing))) : 2
    // 6 is the forecast's own `rs` below; it may not be reduced past its minimum.
    readonly property int q: queueOpen ? Math.max(0, Math.min(queueRows, 6 - minWeatherRows)) : 0

    // PLACEMENTS MUST NOT DEPEND ON ANYTHING THAT CHANGES AT RUNTIME. It is the
    // Repeater's model, and a JS array model is replaced wholesale when the
    // expression re-evaluates: the Repeater destroys and re-creates EVERY
    // delegate. When `q` was inlined here, opening or closing the queue tore
    // down all five tiles — with `DockTile`'s Loader being asynchronous, every
    // other widget (charts, task table, forecast, calendar, clock) came back
    // as an empty framed rectangle for a frame or more, which is exactly the
    // "everything flashes black" the drawer was reported for. Proved with a
    // `Component.onDestruction` warn in DockTile: five destroys + five creates
    // per toggle, none after this change.
    //
    // So the queue's effect is a per-tile DELTA applied in the delegate's own
    // y/height bindings instead: `qRow` rows the tile moves down and `qSpan`
    // rows it gains, each multiplied by `q`. Those are ordinary property
    // bindings on items that survive, so DockTile's Behaviors glide them.
    readonly property var placements: [
        { key: "tasks",    src: "TaskManagerContent.qml", col: 0, row: 0,  cs: 4, rs: 13, qRow: 0, qSpan:  0 },
        { key: "media",    src: "MediaContent.qml",       col: 0, row: 13, cs: 4, rs: 5,  qRow: 0, qSpan:  1 },
        { key: "weather",  src: "WeatherContent.qml",     col: 0, row: 18, cs: 4, rs: 6,  qRow: 1, qSpan: -1 },
        { key: "calendar", src: "CalendarContent.qml",    col: 0, row: 24, cs: 2, rs: 5,  qRow: 0, qSpan:  0 },
        { key: "clock",    src: "ClockContent.qml",       col: 2, row: 24, cs: 2, rs: 5,  qRow: 0, qSpan:  0 },
    ]

    // Taken at completion, NOT as a `readonly property int gen: ViewMode.nextGen()`
    // — that reads `lastGen` inside its own initialiser, which makes the binding
    // depend on the counter it increments.
    // The Quickshell screen this grid is drawn on, handed down by the bar. Only
    // used to decide whether this copy of the grid may MEASURE (below).
    property var screenRef: null

    property int gen: 0
    Component.onCompleted: {
        // A grid on an output the user cannot see must not report its tiles.
        // There is one grid PER MONITOR and `ViewMode.tileInfo` is a singleton,
        // so whichever completes last wins the table — and while an agent's
        // `tools/sandbox.sh` monitor is up, that is a panel on a screen nobody
        // is looking at, at a different height. `qs ipc call live tiles` then
        // answers about the wrong panel with no sign that it has: it read
        // `tasks got=433` against a true 451 for the whole of 2026-07-27. A
        // measuring instrument has to be harder to poison than the thing it
        // measures; a virtual output has nothing true to say about layout, so
        // it says nothing. gen -1 is refused by reportTile.
        gen = WinState.screenIsVirtual(screenRef) ? -1 : ViewMode.nextGen();
        _auditFirstPaint();
    }

    // THE REGRESSION CHECK FOR THE RELOAD FLASH, and it is silent when correct.
    //
    // Whatever is not `ready` at this point is what the reload's first frame
    // paints as an empty framed rectangle — the panel flashing black. There is
    // no IPC call for it because the answer is only true for one instant, the
    // one this runs in; a poll from outside always arrives after the tiles have
    // caught up and reports a clean panel either way.
    //
    // So it warns into `qs log`, once per reload, ONLY on a regression:
    //
    //     qs log | grep "dock tiles"        # nothing = every tile was painted
    //
    // The way to put a tile back in this list is to make its Loader (or any
    // Loader/Image inside its content) asynchronous again.
    function _auditFirstPaint(): void {
        let late = [];
        for (let i = 0; i < tiles.count; i++) {
            const t = tiles.itemAt(i);
            if (t && !t.ready) late.push(t.tileKey);
        }
        if (late.length)
            console.warn("dock tiles not painted at completion:",
                         late.length + "/" + tiles.count, late.join(","));
    }

    Repeater {
        id: tiles
        model: root.placements
        delegate: DockTile {
            required property var modelData

            x: root.cellX(modelData.col)
            y: root.cellY(modelData.row + (modelData.qRow || 0) * root.q)
            width: root.cellW(modelData.cs)
            height: root.cellH(modelData.rs + (modelData.qSpan || 0) * root.q)
            // The tile's height with no queue rows — the closed configuration.
            // MediaContent sizes its queue drawer from this so the drawer can
            // never push the artwork around, in any state (see `gridClosedH`).
            gridClosedH: root.cellH(modelData.rs) - root.tileInset

            tileKey: modelData.key
            source: modelData.src
            gen: root.gen
            // Only the visible mode's copy of a widget polls. The popup copies
            // gate on their own `open`; these gate on the dock being on screen.
            active: root.active
        }
    }
}
