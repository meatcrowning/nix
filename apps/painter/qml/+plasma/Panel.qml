import QtQuick
import QtQuick.Controls

// Panel, in a Plasma session: THE HEADER IS A BUTTON, and an open panel is that
// button held down.
//
// [his] "can we maybe try making the subsections i.e. model, resolution,
// prompt, etc... look as if buttons? and when clicked, the expanded section has
// the look of a pressed button?" — so the header is a real `Button` drawn by
// the KStyle, `checked` while the panel is open, which is exactly how Oxygen
// and Breeze draw a sunken/held button. The content below it sits in the
// style's own sunken `Frame`, so an open panel reads as one pressed control
// with its contents inside rather than as a labelled group.
//
// It replaced a `GroupBox` (kept at
// scratch: the earlier shape is in this file's history) and keeps that file's
// API exactly — title, persistKey, collapsed, collapsible, badge, default
// content, sectionKey/reorderable and the pin protocol — so no call site
// changes and ../Panel.qml (the Hyprland look) is untouched.
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
    implicitHeight: header.height + (collapsed ? 0 : frame.height + 2)
    height: implicitHeight

    Button {
        id: header
        width: parent.width
        // The whole point: open == held down.
        checkable: panel.collapsible
        checked: !panel.collapsed
        onClicked: if (panel.collapsible) panel.collapsed = !panel.collapsed

        contentItem: Item {
            implicitHeight: Math.max(titleLabel.implicitHeight, 20)
            Label {
                id: titleLabel
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                text: panel.title
                font.bold: true
            }
            // The badge, and the pins that replace it while folded — the same
            // rule as ../Panel.qml: both say what the panel says when you
            // cannot see inside it, and the pins are the half he chose.
            Label {
                anchors.left: titleLabel.right
                anchors.leftMargin: 8
                anchors.right: parent.right
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
                anchors.verticalCenter: parent.verticalCenter
                visible: panel.collapsed && panel.pinnedRows.length > 0
                spacing: 10
                Repeater {
                    model: panel.pinnedRows
                    delegate: Label { text: modelData.pinLabel + " " + modelData.pinValue }
                }
            }
        }

        // DRAG THE HEADER TO MOVE THE SECTION. A DragHandler rather than a
        // MouseArea over the button: handlers negotiate the grab, so the drag
        // takes over past the threshold and cancels the press, and the button
        // keeps its own hover, focus and keyboard behaviour the rest of the
        // time. A MouseArea on top would have taken all three away.
        DragHandler {
            id: headerDrag
            target: null
            enabled: panel.reorderable
            onCentroidChanged: if (active)
                root.dragSection(panel.sectionKey, centroid.scenePosition.y)
            onActiveChanged: if (!active && panel.reorderable) root.dropSection()
        }
        TapHandler {
            acceptedButtons: Qt.RightButton
            enabled: panel.reorderable
            onTapped: function (evt, btn) {
                root.ctxMenu.open(point.scenePosition.x, point.scenePosition.y, [
                    { label: "reset panel order", trigger: () => root.resetOrder() }
                ])
            }
        }
    }

    // The style's own sunken frame, under the held-down header.
    Frame {
        id: frame
        anchors.top: header.bottom
        anchors.topMargin: 2
        width: parent.width
        visible: !panel.collapsed
        height: visible ? implicitHeight : 0

        // A COLUMN, exactly as ../Panel.qml's inner is — every caller stacks
        // bare Fields inside a panel and relies on it. Its own implicitHeight
        // is also the honest one when a child is hidden (a Column excludes what
        // it does not lay out, childrenRect does not).
        contentItem: Column {
            id: inner
            spacing: 5
        }
    }
}
