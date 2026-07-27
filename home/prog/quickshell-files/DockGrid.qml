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
    // condensed form (current conditions on one line, graph dropped — see
    // WeatherContent's `condensed`), whereas a shorter task table just shows
    // fewer processes and a shorter queue is the thing being asked for. Four
    // rows leaves the forecast two, which is its header plus its legend line.
    readonly property int queueRows: 4
    readonly property bool queueOpen: SettingsStore.d.mediaQueueOpen
    readonly property int q: queueOpen ? queueRows : 0

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

    Repeater {
        model: root.placements
        delegate: DockTile {
            required property var modelData

            x: root.cellX(modelData.col)
            y: root.cellY(modelData.row + (modelData.qRow || 0) * root.q)
            width: root.cellW(modelData.cs)
            height: root.cellH(modelData.rs + (modelData.qSpan || 0) * root.q)

            tileKey: modelData.key
            source: modelData.src
            // Only the visible mode's copy of a widget polls. The popup copies
            // gate on their own `open`; these gate on the dock being on screen.
            active: root.active
        }
    }
}
