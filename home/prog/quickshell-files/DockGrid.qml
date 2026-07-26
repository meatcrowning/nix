import QtQuick

// The dock panel's widget grid — the SUBSTRATE only, at this stage.
//
// Phase 1 establishes the coordinate system every later phase places widgets
// into, and draws it so the geometry can actually be judged on screen before
// any widget is wired up: `columns` fixed-width columns, `rowHeight`-tall rows,
// Theme.gap between them. A widget will occupy a (col, row, colSpan, rowSpan)
// rectangle in these coordinates, which is what lets it "take up as much space
// as possible" — spanning the full width, half of it, or a single cell.
//
// Column count is FIXED rather than derived from the panel width: the panel
// only ranges over 25-33% of the screen, and letting the count change inside
// that range would silently invalidate every saved widget placement each time
// the edge was dragged. Widening the panel makes each column wider instead.
Item {
    id: root

    readonly property int columns: 4
    readonly property int rowHeight: 44
    readonly property int spacing: Theme.gap

    // Usable width per column, gaps removed. Bound to the live panel width, so
    // it tracks a drag frame by frame.
    readonly property real cellWidth:
        (width - spacing * (columns - 1)) / columns

    // Scene geometry of a (col, row, colSpan, rowSpan) placement. The single
    // place grid coordinates become pixels — phase 3's drag-to-move and
    // drag-to-resize both read back through here.
    function cellX(col) { return col * (cellWidth + spacing); }
    function cellY(row) { return row * (rowHeight + spacing); }
    function cellW(colSpan) { return colSpan * cellWidth + (colSpan - 1) * spacing; }
    function cellH(rowSpan) { return rowSpan * rowHeight + (rowSpan - 1) * spacing; }

    readonly property int rows: Math.max(1, Math.floor(
        (height + spacing) / (rowHeight + spacing)))

    // Empty-cell scaffolding. This is placeholder rendering: it exists so the
    // grid's proportions are visible while there is nothing in it yet, and goes
    // away once widgets are placed (phase 2).
    Repeater {
        model: root.rows * root.columns
        delegate: Rectangle {
            required property int index
            readonly property int col: index % root.columns
            readonly property int row: Math.floor(index / root.columns)

            x: root.cellX(col)
            y: root.cellY(row)
            width: root.cellW(1)
            height: root.cellH(1)
            color: "transparent"
            border.width: 1
            border.color: Theme.dim
            opacity: 0.35
        }
    }

    PixelText {
        anchors.centerIn: parent
        text: "widget grid"
        color: Theme.textDim
        opacity: 0.6
    }
}
