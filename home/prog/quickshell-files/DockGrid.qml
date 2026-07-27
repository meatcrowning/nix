import QtQuick

// The dock panel's widget grid: `columns` fixed-width columns, `rowHeight`-tall
// rows, Theme.gap between them. A widget occupies a (col, row, colSpan, rowSpan)
// rectangle in those coordinates, which is what lets it "take up as much space as
// possible" — the full width, half of it, or a single cell.
//
// Column count is FIXED rather than derived from the panel width: the panel only
// ranges over 14-33% of the screen, and letting the count change inside that
// range would silently invalidate every saved placement each time the edge was
// dragged. Widening the panel makes each column wider instead.
//
// PLACEMENTS is plain data on purpose. Phase 2 ships it as a constant default;
// phase 3 makes it the thing the user drags around and the thing that gets
// persisted, and nothing else in here has to change for that — cellX/cellY/cellW/
// cellH stay the single place grid coordinates become pixels, and the drag will
// read back through them.
Flickable {
    id: root

    property bool active: true

    readonly property int columns: 4
    readonly property int rowHeight: 44
    readonly property int spacing: Theme.gap

    // Usable width per column, gaps removed. Bound to the live panel width, so it
    // tracks a drag frame by frame.
    readonly property real cellWidth: (width - spacing * (columns - 1)) / columns

    function cellX(col) { return col * (cellWidth + spacing); }
    function cellY(row) { return row * (rowHeight + spacing); }
    function cellW(colSpan) { return colSpan * cellWidth + (colSpan - 1) * spacing; }
    function cellH(rowSpan) { return rowSpan * rowHeight + (rowSpan - 1) * spacing; }

    // Default layout. Row spans are sized to each widget's natural height at a
    // four-column width, so nothing is clipped at the default panel width; the
    // two charts pair up side by side because they are the only two that read
    // fine at half width.
    readonly property var placements: [
        { key: "media",    src: "MediaContent.qml",    col: 0, row: 0,  cs: 4, rs: 5 },
        { key: "disk",     src: "DiskContent.qml",     col: 0, row: 5,  cs: 4, rs: 9 },
        { key: "cpu",      src: "CpuContent.qml",      col: 0, row: 14, cs: 2, rs: 4 },
        { key: "gpu",      src: "GpuContent.qml",      col: 2, row: 14, cs: 2, rs: 4 },
        { key: "eth",      src: "EthContent.qml",      col: 0, row: 18, cs: 4, rs: 4 },
        { key: "weather",  src: "WeatherContent.qml",  col: 0, row: 22, cs: 4, rs: 5 },
        { key: "clock",    src: "ClockContent.qml",    col: 0, row: 27, cs: 4, rs: 6 },
        { key: "calendar", src: "CalendarContent.qml", col: 0, row: 33, cs: 4, rs: 5 },
    ]

    // Rows the placements actually occupy — the grid is taller than the panel, so
    // it scrolls rather than shrinking the widgets to fit.
    readonly property int usedRows: {
        let m = 0;
        for (const p of placements) m = Math.max(m, p.row + p.rs);
        return m;
    }

    contentWidth: width
    contentHeight: cellY(usedRows) - spacing
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    // A panel-sized grid that happens to fit needs no scrollbar and no drag.
    interactive: contentHeight > height

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
