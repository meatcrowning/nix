import QtQuick

// THE TAG LIST UNDER THE CARET — the completer's only drawing.
//
// One per scene, exactly like `CtxMenu` and `PickerOverlay` and for the same
// reason: a prompt box is 64-130px tall, so a list parented inside one would be
// clipped to a row and a half. Opened with scene coordinates
// (`mapToItem(null, ...)` at the call site) by `PromptBox`, which owns all the
// logic — this file shows rows and reports the one that was picked.
//
// IT NEVER TAKES THE KEYBOARD. A right-click menu can (it is the only thing on
// screen once it is up); a completer cannot — the whole point is that typing
// continues underneath it. So `PromptBox` drives it from the editor's own key
// handler: `move(+/-1)`, `accept()`, `close()`.
//
// The menu spec, unchanged (docs/DESIGN.md §7.2): `bgAlt` box, 1px border,
// `Theme.rounding`, rows the height of their own line box, the current row
// filled `Theme.highlight` — one step LIGHTER, per §3.3's ladder.
Item {
    id: root
    visible: false
    // Below CtxMenu (3000) and the picker overlay: a right-click over a prompt
    // box closes this and is drawn on top of whatever is left.
    z: 2900

    property var items: []
    property int index: 0
    readonly property int count: items ? items.length : 0
    //: The row Return would take — what the box inserts, and what a harness
    //: asks about without having to read a delegate's text back.
    readonly property string currentTag: (count > 0 && items[index]) ? items[index].tag : ""

    //: Where the list was last put, so a keystroke that does not move the tag
    //: does not move the list either — see `place`.
    property real anchorX: -1
    property real anchorY: -1

    function open(x, y, list, lineH) {
        root.items = list || [];
        if (root.count === 0) { root.close(); return }
        root.index = 0;
        root.visible = true;
        panel.remeasure();
        if (x !== root.anchorX || y !== root.anchorY || !panel.placed) {
            root.anchorX = x;
            root.anchorY = y;
            panel.place(x, y, lineH || 16);
        }
    }
    //: True for the rest of the event that closed the list — see
    //: `PromptBox.Keys.onEscapePressed` for why an Escape has to be spendable
    //: by whichever of the two handlers reaches it first.
    property bool justClosed: false
    Timer { id: closedLatch; interval: 0; onTriggered: root.justClosed = false }

    function close() {
        if (root.visible) { root.justClosed = true; closedLatch.restart() }
        root.visible = false;
        panel.placed = false;
        root.anchorX = root.anchorY = -1;
        root.items = [];
        root.index = 0;
    }
    function move(delta) {
        if (root.count === 0) return
        // WRAPS. A completer's list is eight rows; hitting the end and stopping
        // is a dead key press for no reason.
        root.index = (root.index + delta + root.count) % root.count;
    }
    function accept() {
        if (root.count === 0) return false
        var it = root.items[root.index];
        root.close();
        if (it && it.trigger) it.trigger();
        return true
    }

    // How a post count reads on a row: 4.3M, 12.3k, 940. The number is what
    // says which `blue` he means, so it is drawn, not implied.
    function posts(n) {
        if (n >= 1000000) return (n / 1000000).toFixed(1) + "M"
        if (n >= 1000) return (n / 1000).toFixed(n < 10000 ? 1 : 0) + "k"
        return "" + n
    }

    Rectangle {
        id: panel
        width: Math.min(Math.max(contentWidth + 2, 160), 420)
        height: col.implicitHeight + 2
        color: Theme.bgAlt
        radius: Theme.rounding
        border.width: Theme.ctrlBorder
        border.color: Theme.windowBorder

        // Text-derived, measured from the delegates rather than bound to the
        // Column's implicitWidth — the rows fill this panel, so binding it back
        // is the self-referential collapse `CtxMenu` documents.
        property real contentWidth: 160
        function remeasure() {
            var w = 160;
            for (var i = 0; i < rows.count; i++) {
                var it = rows.itemAt(i);
                if (it && it.implicitWidth > w) w = it.implicitWidth;
            }
            contentWidth = w;
        }

        // UNDER THE LINE BEING TYPED, and above it when there is no room below:
        // the list must never cover the caret it belongs to.
        property bool placed: false
        function place(sx, sy, lineH) {
            panel.placed = true;
            var below = sy + lineH + 2;
            panel.y = (below + height <= root.height - 4) ? below
                                                          : Math.max(4, sy - height - 2);
            panel.x = Math.max(4, Math.min(sx, root.width - width - 4));
        }
        onWidthChanged: if (root.visible) panel.x = Math.max(4, Math.min(panel.x, root.width - width - 4))

        Column {
            id: col
            anchors { top: parent.top; left: parent.left; margins: 1 }

            Repeater {
                id: rows
                model: root.items
                onCountChanged: panel.remeasure()
                delegate: Item {
                    id: row
                    required property var modelData
                    required property int index
                    width: panel.width - 2
                    height: Math.max(name.implicitHeight, meta.implicitHeight) + 4
                    implicitWidth: name.implicitWidth + meta.implicitWidth + 30

                    Rectangle {
                        anchors.fill: parent
                        color: row.index === root.index ? Theme.highlight : "transparent"
                    }

                    PixelText {
                        id: name
                        anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
                        width: Math.max(0, meta.x - x - 8)
                        elide: Text.ElideRight
                        // The tag first — it is what gets inserted — and the
                        // alias that matched after it, so a row the query does
                        // not appear in explains itself: `1girl  (sole_female)`.
                        // ASCII parentheses rather than an arrow: the pixel
                        // font's cmap is short and a missing glyph clips the
                        // whole line (docs/DESIGN.md §2.3).
                        text: row.modelData.alias !== ""
                              ? (row.modelData.tag + "  (" + row.modelData.alias + ")")
                              : row.modelData.tag
                        // A TAG ALREADY IN THE BOX IS DRAWN SPENT. The list is
                        // most useful when it says what you have not got yet,
                        // and every completer people already use marks these.
                        color: row.modelData.have ? Theme.inactive
                             : row.index === root.index ? Theme.text : Theme.textDim
                    }

                    PixelText {
                        id: meta
                        anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
                        // The category only when it is not `general` — every
                        // second tag is general and a column of it says nothing.
                        text: (row.modelData.category !== "general"
                               ? row.modelData.category + "  " : "")
                              + root.posts(row.modelData.posts)
                        color: Theme.dim
                    }

                    // HOVER MOVES THE SELECTION, rather than painting a second
                    // highlight beside the keyboard's: one row is current, and
                    // the pointer and the arrow keys agree about which.
                    MouseArea {
                        id: rowMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onEntered: root.index = row.index
                        onClicked: { root.index = row.index; root.accept() }
                    }
                }
            }
        }
    }
}
