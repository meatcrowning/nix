import QtQuick
import QtQuick.Controls

// Panel, in a Plasma session: THE SECTION IS A BUTTON, and an open one is that
// button held down.
//
// [his] "can we maybe try making the subsections i.e. model, resolution,
// prompt, etc... look as if buttons? and when clicked, the expanded section has
// the look of a pressed button?" — so the panel's background is a real `Button`
// drawn by the KStyle, `checked` while it is open, which is exactly how Oxygen
// and Breeze draw a sunken/held one. The button is the WHOLE section rather
// than its header: a header that goes dark while its own rows sit on the window
// background reads as two unrelated things.
//
// It replaced a `GroupBox` and keeps that file's API exactly — title,
// persistKey, collapsed, collapsible, badge, default content,
// sectionKey/reorderable and the pin protocol — so no call site changes, and
// ../Panel.qml (the Hyprland look) is untouched.
Item {
    id: panel
    property string face: "plasma"

    property string title: ""
    property string persistKey: ""
    property bool collapsed: false
    property bool collapsible: true
    property string badge: ""
    property string headerActionLabel: ""
    property bool headerActionLit: false
    property bool headerActionPill: false
    signal headerAction()
    default property alias content: inner.data

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

    // Reordering and pinning, same API and same rules as ../Panel.qml — read
    // the comments there; only the drawing differs.
    property string sectionKey: ""
    property bool reorderable: sectionKey !== "" && typeof root !== "undefined"
                               && root && root.dragSection !== undefined
    property var pins: []

    function togglePin(item) {
        var k = item && item.pinLabel ? "" + item.pinLabel : ""
        if (k === "") return
        var p = panel.pins.slice()
        var i = p.indexOf(k)
        if (i >= 0) p.splice(i, 1)
        else p.push(k)
        panel.pins = p
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
    // The header, plus whatever is still in the column — everything when open,
    // the pinned rows when folded, nothing when folded with none pinned.
    implicitHeight: header.height + (inner.visible ? inner.implicitHeight + 12 : 0)
    height: implicitHeight

    // THE WHOLE SECTION IS THE BUTTON, not just its header. Open, the style's
    // held-down face covers the panel from the title to its last row, which is
    // the look he asked for — a header that goes dark while the rows below it
    // sit on the window background read as two unrelated things.
    //
    // It is a BACKGROUND: `blocker` above it eats every press so the button
    // cannot be clicked through its own contents, and the header and the rows
    // are drawn over both. Only the header toggles.
    Button {
        id: bg
        anchors.fill: parent
        checkable: true
        checked: !panel.collapsed
        hoverEnabled: false
        focusPolicy: Qt.NoFocus
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.AllButtons
        onPressed: function (m) { m.accepted = true }
    }

    Item {
        id: header
        width: parent.width
        height: Math.max(titleLabel.implicitHeight + 10, 28)

        Label {
            id: titleLabel
            anchors.left: parent.left
            anchors.leftMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            text: panel.title
            font.bold: true
        }
        // The badge, and the pins that replace it while folded — the same rule
        // as ../Panel.qml: both say what the panel says when you cannot see
        // inside it, and the pins are the half he chose. ELIDED and bounded on
        // both sides: a model filename is longer than any panel is wide, and it
        // used to run out through the button's edge.
        Label {
            anchors.left: titleLabel.right
            anchors.leftMargin: 8
            anchors.right: headerButton.visible ? headerButton.left : parent.right
            anchors.rightMargin: headerButton.visible ? 4 : 10
            anchors.verticalCenter: parent.verticalCenter
            text: panel.badge
            elide: Text.ElideMiddle
            opacity: 0.7
            horizontalAlignment: Text.AlignRight
        }
        TextButton {
            id: headerButton
            z: 2
            visible: panel.headerActionLabel !== ""
            anchors.right: parent.right
            anchors.rightMargin: 6
            anchors.verticalCenter: parent.verticalCenter
            label: panel.headerActionLabel
            pillIcon: panel.headerActionPill
            lit: panel.headerActionLit
            onClicked: panel.headerAction()
        }
        // Click folds. Drag moves the section. Right-click offers the way back
        // to the built-in order. Handlers rather than a MouseArea so the drag
        // can take the grab off the tap past the threshold.
        TapHandler {
            acceptedButtons: Qt.LeftButton
            onTapped: if (panel.collapsible) panel.collapsed = !panel.collapsed
        }
        DragHandler {
            target: null
            enabled: panel.reorderable
            onCentroidChanged: if (active)
                root.dragSection(panel.sectionKey, centroid.scenePosition.y)
            onActiveChanged: if (!active && panel.reorderable) root.dropSection()
        }
        TapHandler {
            acceptedButtons: Qt.RightButton
            enabled: panel.reorderable
            onTapped: root.ctxMenu.open(point.scenePosition.x, point.scenePosition.y, [
                { label: "Reset Panel Order", trigger: () => root.resetOrder() }
            ])
        }
    }

    // A COLUMN, exactly as ../Panel.qml's inner is — every caller stacks bare
    // Fields inside a panel and relies on it. Its own implicitHeight is also
    // the honest one when a child is hidden (a Column excludes what it does not
    // lay out, childrenRect does not).
    Column {
        id: inner
        anchors.top: header.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: 10
        anchors.rightMargin: 10
        spacing: 5
        visible: !panel.collapsed || panel.pins.length > 0
    }

    // Where an unpinned row waits out a collapse. Never drawn.
    Item { id: stash; visible: false }
}
