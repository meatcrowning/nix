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
        if (!persistKey) return
        collapsed = Prefs.get(persistKey) === true
        try { panel.pins = JSON.parse(Prefs.get(persistKey + ".pins") || "[]") }
        catch (e) { panel.pins = [] }        // a corrupt list just pins nothing
    }
    onCollapsedChanged: if (persistKey) Prefs.set(persistKey, collapsed)
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

    // The rows currently pinned, in the panel's own order rather than the order
    // they were pinned in — a strip that reshuffles itself is unreadable.
    readonly property var pinnedRows: {
        var out = []
        if (panel.pins.length === 0) return out
        for (var i = 0; i < inner.children.length; i++) {
            var c = inner.children[i]
            if (c && c.pinLabel !== undefined
                && panel.pins.indexOf("" + c.pinLabel) >= 0) out.push(c)
        }
        return out
    }

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
            visible: !pinStrip.visible
            text: panel.badge
            color: Theme.textDim
        }

        // The pins, right-aligned where the badge sits, and only while folded:
        // open, the rows themselves are on screen and a copy of them is noise.
        Row {
            id: pinStrip
            visible: panel.collapsed && panel.pinnedRows.length > 0
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right
            anchors.rightMargin: 8
            spacing: 10
            Repeater {
                model: panel.pinnedRows
                delegate: PixelText {
                    text: modelData.pinLabel + " " + modelData.pinValue
                    color: Theme.text
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
