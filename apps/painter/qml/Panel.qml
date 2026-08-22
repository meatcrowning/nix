import QtQuick

// A titled, collapsible box.  The left column is a stack of these.
Rectangle {
    id: panel
    property string title: ""
    // Collapsed or not is remembered per panel, under this key. A panel without
    // one still collapses; it just forgets (nothing in-tree does that).
    property string persistKey: ""
    property bool collapsed: false
    Component.onCompleted: {
        // The declared order of the rows, captured once — see `applyPins`.
        var order = []
        for (var i = 0; i < inner.children.length; i++) order.push(inner.children[i])
        panel.rowOrder = order
        if (persistKey) {
            collapsed = Prefs.get(persistKey) === true
            try { panel.pins = JSON.parse(Prefs.get(persistKey + ".pins") || "[]") }
            catch (e) { panel.pins = [] }    // a corrupt list just pins nothing
        }
        panel.applyPins()
    }

    onCollapsedChanged: {
        if (persistKey) Prefs.set(persistKey, collapsed)
        panel.applyPins()
    }
    property bool collapsible: true
    property string badge: ""
    default property alias content: inner.data

    // WHICH SECTION THIS IS, and whether the column lets you move it. Both are
    // set by ParamsPane's loader; a panel used anywhere else is simply not
    // draggable (docs/painter-kde-layout.md phase 7).
    property string sectionKey: ""
    property bool reorderable: sectionKey !== "" && typeof root !== "undefined"
                               && root && root.dragSection !== undefined

    // PINS. A collapsed panel normally says only its badge; a pinned row keeps
    // its value visible there too, so folding a panel no longer costs you the
    // one number you were watching. Right-click a row's LABEL to pin or unpin
    // it (Field.qml, Toggle.qml). Stored beside the collapsed state, under the
    // same key, so a panel with no `persistKey` pins for the session only.
    property var pins: []

    function togglePin(item) {
        var k = item && item.pinLabel ? "" + item.pinLabel : ""
        if (k === "") return
        var p = panel.pins.slice()
        var i = p.indexOf(k)
        if (i >= 0) p.splice(i, 1)
        else p.push(k)
        panel.pins = p                       // a NEW array: see Root.qml's `gen`
        if (persistKey) Prefs.set(persistKey + ".pins", JSON.stringify(p))
    }


    // PINS ARE THE ROWS THEMSELVES, moved. A pinned row is REPARENTED into the
    // header strip while the panel is folded, so it is the live control — a
    // pinned Spin still steps, a pinned Toggle still toggles — rather than a
    // copy of its value. His call, 2026-08-22: "keeping the pins per-header and
    // making them editable".
    //
    // The order problem that made a read-only chip look tempting: QML has no
    // way to put a child BACK at an index, so a returned row would land at the
    // end of the column. `rowOrder` is the answer — expanding reparents EVERY
    // row in the panel's declared order, which rebuilds the Column exactly as
    // it was however many rows were away.
    property var rowOrder: []

    function applyPins() {
        if (panel.rowOrder.length === 0) return
        for (var i = 0; i < panel.rowOrder.length; i++) {
            var r = panel.rowOrder[i]
            if (!r) continue
            var pinned = panel.collapsed
                         && r.pinLabel !== undefined
                         && panel.pins.indexOf("" + r.pinLabel) >= 0
            if (pinned) {
                var slot = null
                for (var k = 0; k < pinSlots.count; k++) {
                    var it = pinSlots.itemAt(k)
                    if (it && it.pinKey === "" + r.pinLabel) { slot = it; break }
                }
                if (slot) {
                    r.parent = slot
                    // A plain Item does not position what it adopts, and the
                    // Column had already put this row at its column y — so
                    // without these it draws below the panel entirely.
                    r.x = 0
                    r.y = 0
                }
            } else if (!panel.collapsed) {
                r.parent = inner
            }
        }
    }
    onPinsChanged: panel.applyPins()

    width: parent ? parent.width : 320
    // A PANEL FOLLOWS ITS CONTENT DOWN AS WELL AS UP. This used to size from
    // `inner.childrenRect.height`, which only ever GREW once a child was
    // hidden: an invisible child keeps the y a Column last positioned it at,
    // and childrenRect still spans to it — so with the negative prompt box
    // hidden (any video or edit family) dragging the positive box SMALLER left
    // the panel at its old height, with a hand-sized blank under the box.
    // Measured offscreen against the real window, his own prefs: box 392 -> 242,
    // panel 435 -> 435. The Column's own `implicitHeight` is the honest number —
    // it is the sum of the children it actually LAYS OUT, so it excludes the
    // hidden ones by construction and tracks both directions.
    implicitHeight: header.height + (collapsed ? 0 : inner.implicitHeight + 14)
    height: implicitHeight
    color: Theme.bgAlt
    radius: Theme.rounding
    border.color: Theme.border
    border.width: Theme.ctrlBorder
    clip: true

    Item {
        id: header
        width: parent.width
        height: 24

        PixelText {
            id: caret
            visible: panel.collapsible
            x: 6
            anchors.verticalCenter: parent.verticalCenter
            text: panel.collapsed ? "+" : "-"
            color: Theme.dim
        }
        PixelText {
            id: titleText
            anchors.verticalCenter: parent.verticalCenter
            x: panel.collapsible ? 20 : 8
            text: panel.title
            color: root.fgAccent
        }
        // A BADGE IS NEVER WIDER THAN WHAT IS LEFT. The model panel's badge is a
        // filename, which in a 300px column ran off the edge and out of the
        // panel entirely. Elided in the middle, because the tail of a model name
        // (the quant, the variant) is the half worth keeping.
        PixelText {
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right
            anchors.rightMargin: 8
            anchors.left: titleText.right
            anchors.leftMargin: 10
            horizontalAlignment: Text.AlignRight
            elide: Text.ElideMiddle
            // The pin strip takes this space when there is one, because both
            // are the same thing — what the panel says while it is folded — and
            // the pins are the half he chose.
            visible: panel.pins.length === 0 || !panel.collapsed
            text: panel.badge
            color: Theme.textDim
        }

        // WHERE A PINNED ROW LIVES while the panel is folded — the row itself,
        // moved here and moved back (`applyPins`), not a copy of its value.
        Item {
            anchors.left: titleText.right
            anchors.leftMargin: 12
            anchors.right: parent.right
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            height: 24
            clip: true
            Row {
                id: pinBar
                spacing: 12
                clip: true
                Repeater {
                    id: pinSlots
                    // One slot per pin, only while folded. A FIXED width, because
                    // the row inside takes its width from its parent — a slot sized
                    // to its contents would be the binding loop the other way
                    // round, and every attempt to make the row size itself instead
                    // ended in one (measured, twice).
                    model: panel.collapsed ? panel.pins : []
                    // The slots appear a beat after `collapsed` flips, so the
                    // move has to wait for them — running it on the flip alone
                    // found no slot and left the row where it was.
                    onCountChanged: panel.applyPins()
                    delegate: Item {
                        property string pinKey: modelData
                        width: 190
                        height: 24
                    }
                }
            }
        }
        // ONE HEADER, THREE GESTURES. A click folds. A drag past the threshold
        // moves the whole section in the column, live, with the others sliding
        // out of the way (ParamsPane's `move` transition) — the file-manager
        // idiom, docs/DESIGN.md §13. A right-click offers the way back to the
        // built-in order, which is otherwise a thing you cannot undo.
        MouseArea {
            id: headerDrag
            anchors.fill: parent
            enabled: panel.collapsible || panel.reorderable
            hoverEnabled: true
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            cursorShape: dragging ? Qt.ClosedHandCursor
                       : panel.collapsible ? Qt.PointingHandCursor : Qt.ArrowCursor

            property real pressY: 0
            property bool dragging: false

            onPressed: function (m) { pressY = m.y; dragging = false }
            onPositionChanged: function (m) {
                if (!panel.reorderable || !pressed) return
                // 6px, the same slack every other press-then-drag on this
                // desktop allows before it stops being a click.
                if (!dragging && Math.abs(m.y - pressY) < 6) return
                dragging = true
                root.dragSection(panel.sectionKey, mapToItem(null, m.x, m.y).y)
            }
            onReleased: if (dragging) root.dropSection()
            onCanceled: dragging = false
            onClicked: function (m) {
                if (m.button === Qt.RightButton) {
                    if (!panel.reorderable) return
                    var pt = mapToItem(null, m.x, m.y)
                    root.ctxMenu.open(pt.x, pt.y, [
                        { label: "reset panel order",
                          trigger: () => root.resetOrder() }
                    ])
                    return
                }
                if (dragging) { dragging = false; return }
                if (panel.collapsible) panel.collapsed = !panel.collapsed
            }
        }
        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: 1
            color: Theme.border
            visible: !panel.collapsed
        }
    }

    Column {
        id: inner
        anchors.top: header.bottom
        anchors.topMargin: 7
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        spacing: 5
        visible: !panel.collapsed
    }
}
