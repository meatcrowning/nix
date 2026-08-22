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
            { label: on ? "unpin " + k + " from the header"
                        : "pin " + k + " to the header",
              trigger: () => panel.togglePin(item) },
            { separator: true },
            { label: panel.collapsed ? "expand this panel" : "collapse this panel",
              trigger: () => { panel.collapsed = !panel.collapsed } }
        ])
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
    implicitHeight: header.height + (collapsed ? 0 : inner.implicitHeight + 12)
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
            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            visible: panel.pins.length === 0 || !panel.collapsed
            text: panel.badge
            elide: Text.ElideMiddle
            opacity: 0.7
            horizontalAlignment: Text.AlignRight
        }
        // WHERE A PINNED ROW LIVES while the panel is folded. Not a copy of it
        // — the row itself (`applyPins`), so it still works up here.
        Item {
            anchors.left: titleLabel.right
            anchors.leftMargin: 12
            anchors.right: parent.right
            anchors.rightMargin: 10
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
                { label: "reset panel order", trigger: () => root.resetOrder() }
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
        visible: !panel.collapsed
    }
}
