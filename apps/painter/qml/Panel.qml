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
    property string headerActionLabel: ""
    property bool headerActionLit: false
    property bool headerActionPill: false
    signal headerAction()
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


    // The row's own menu: what can be done with it, said out loud. `root` is
    // the pane (ParamsPane), which owns the one scene-level menu.
    function pinMenu(item, sceneX, sceneY) {
        var k = item && item.pinLabel ? "" + item.pinLabel : ""
        if (k === "" || typeof root === "undefined" || !root || !root.ctxMenu) return
        var on = panel.pins.indexOf(k) >= 0
        root.ctxMenu.open(sceneX, sceneY, [
            { label: on ? "Unpin " + k + " From the Header"
                        : "Pin " + k + " to the Header",
              trigger: () => panel.togglePin(item) },
            { separator: true },
            { label: panel.collapsed ? "Expand This Panel" : "Collapse This Panel",
              trigger: () => { panel.collapsed = !panel.collapsed } }
        ])
    }

    // COLLAPSING HIDES WHAT IS NOT PINNED, and nothing else. A folded panel is
    // its header plus the rows he pinned, laid out where they always were and
    // still live — a pinned Spin steps, a pinned Toggle toggles. His call,
    // 2026-08-22: "when collapsed it should just be as if everything not pinned
    // became hidden and the section shrinks accordingly". With nothing pinned
    // that is the old behaviour: header only.
    //
    // The unpinned rows are PARKED in `stash`, not hidden, because their own
    // `visible` is often bound by the caller (`visible: !panel.fromImage`) and
    // assigning it would destroy that binding for good. A Column lays out the
    // children it has, so parking one is the honest way to take it out.
    //
    // The order problem: QML has no way to put a child BACK at an index, so a
    // row returning from the stash would land at the end. `rowOrder` is the
    // answer — every row that belongs in the column is reparented in the
    // panel's declared order, which rebuilds it exactly as it was.
    property var rowOrder: []

    function applyPins() {
        if (panel.rowOrder.length === 0) return
        // The FIRST row whose home changes. Everything before it is already in
        // the right place and in the right order, and is left alone — which
        // matters: reparenting a row twice in one tick orphaned the delegates
        // of a Repeater inside it (the preset buttons vanished, laid out and
        // measured but with no visual parent). Everything from there on is
        // re-seated in declared order, which is what puts the column back
        // together, since QML cannot insert a child at an index.
        var first = -1
        for (var i = 0; i < panel.rowOrder.length; i++) {
            var r = panel.rowOrder[i]
            if (!r) continue
            if (r.parent !== panel.homeFor(r)) { first = i; break }
        }
        if (first < 0) return
        for (var j = first; j < panel.rowOrder.length; j++) {
            var q = panel.rowOrder[j]
            // A row that hides itself is never moved — see `homeFor`. It also
            // never needs to be: it is the first row in the panels that have
            // one, so the rows re-seated after it still land in order.
            if (!q || q.selfHides === true) continue
            // OUT AND BACK IN. Assigning the parent a row already has does
            // nothing, so a row returning from the stash would land after the
            // ones that never left; the bounce is what re-appends them all in
            // declared order. Through the STASH, not through null: half the
            // rows in here are `width: parent.width`, and a null parent makes
            // that a TypeError for the frame it lasts.
            q.parent = stash
            q.parent = panel.homeFor(q)
        }
    }

    // Where a row belongs right now: the column, or the stash it waits out a
    // collapse in.
    function homeFor(r) {
        // A row that hides itself is never parked (`selfHides` — ModeSwitcher,
        // whose Repeater cannot survive a reparent).
        if (r.selfHides === true) return inner
        var pinned = r.pinLabel !== undefined
                     && panel.pins.indexOf("" + r.pinLabel) >= 0
        return (panel.collapsed && !pinned) ? stash : inner
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
    // The header, plus whatever is still in the column — everything when open,
    // the pinned rows when folded, nothing when folded with none pinned.
    implicitHeight: header.height + (inner.visible ? inner.implicitHeight + 14 : 0)
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
            anchors.right: headerButton.visible ? headerButton.left : parent.right
            anchors.rightMargin: headerButton.visible ? 4 : 8
            anchors.left: titleText.right
            anchors.leftMargin: 10
            horizontalAlignment: Text.AlignRight
            elide: Text.ElideMiddle
            text: panel.badge
            color: Theme.textDim
        }

        TextButton {
            id: headerButton
            z: 2
            visible: panel.headerActionLabel !== ""
            anchors.right: parent.right
            anchors.rightMargin: 4
            anchors.verticalCenter: parent.verticalCenter
            label: panel.headerActionLabel
            pillIcon: panel.headerActionPill
            lit: panel.headerActionLit
            winActive: root.winActive
            onClicked: panel.headerAction()
        }

        MouseArea {
            id: headerDrag
            z: 1
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
                        { label: "Reset Panel Order",
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
        visible: !panel.collapsed || panel.pins.length > 0
    }

    // Where an unpinned row waits out a collapse. Never drawn.
    Item { id: stash; visible: false }
}
