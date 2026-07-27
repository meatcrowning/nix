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
    readonly property int rows: 26
    readonly property int spacing: Theme.gap

    readonly property real cellWidth: (width - spacing * (columns - 1)) / columns
    readonly property real cellHeight: (height - spacing * (rows - 1)) / rows

    function cellX(col) { return col * (cellWidth + spacing); }
    function cellY(row) { return row * (cellHeight + spacing); }
    function cellW(colSpan) { return colSpan * cellWidth + (colSpan - 1) * spacing; }
    function cellH(rowSpan) { return rowSpan * cellHeight + (rowSpan - 1) * spacing; }

    // Reading bottom-up, which is how it was asked for: clock and calendar side
    // by side on the bottom row, the forecast above them, the player above that,
    // and the task manager taking everything that's left — it is the one widget
    // whose usefulness scales with the space it gets, since every extra row is
    // another process you can see.
    readonly property var placements: [
        { key: "tasks",    src: "TaskManagerContent.qml", col: 0, row: 0,  cs: 4, rs: 8 },
        { key: "media",    src: "MediaContent.qml",       col: 0, row: 8,  cs: 4, rs: 6 },
        { key: "weather",  src: "WeatherContent.qml",     col: 0, row: 14, cs: 4, rs: 6 },
        { key: "clock",    src: "ClockContent.qml",       col: 0, row: 20, cs: 2, rs: 6 },
        { key: "calendar", src: "CalendarContent.qml",    col: 2, row: 20, cs: 2, rs: 6 },
    ]

    Repeater {
        model: root.placements
        delegate: DockTile {
            required property var modelData

            x: root.cellX(modelData.col)
            y: root.cellY(modelData.row)
            width: root.cellW(modelData.cs)
            height: root.cellH(modelData.rs)

            source: modelData.src
            // Only the visible mode's copy of a widget polls. The popup copies
            // gate on their own `open`; these gate on the dock being on screen.
            active: root.active
        }
    }
}
