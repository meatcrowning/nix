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
        if (!persistKey) return
        collapsed = Prefs.get(persistKey) === true
        try { panel.pins = JSON.parse(Prefs.get(persistKey + ".pins") || "[]") }
        catch (e) { panel.pins = [] }
    }
    onCollapsedChanged: if (persistKey) Prefs.set(persistKey, collapsed)

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
            visible: !pinStrip.visible
            text: panel.badge
            elide: Text.ElideMiddle
            opacity: 0.7
            horizontalAlignment: Text.AlignRight
        }
        Row {
            id: pinStrip
            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            visible: panel.collapsed && panel.pinnedRows.length > 0
            spacing: 10
            Repeater {
                model: panel.pinnedRows
                delegate: Label { text: modelData.pinLabel + " " + modelData.pinValue }
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
