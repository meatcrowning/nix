import QtQuick
import "../../qmlcommon"

// THE one dropdown list, over everything — the same shape as `CtxMenu` and for
// the same reason.
//
// A `Picker` used to carry its own popup as a child. `z` only orders siblings
// inside one parent, so that popup could never rise above the panels below it:
// it was clipped by the left column's Flickable (`clip: true`), and the panels
// that come after it in the Column drew straight over the rows. Every list in
// the app was affected — sampler, scheduler, curve, outside, the per-model
// family assignment — and the deeper the picker sat, the more of it was eaten.
//
// So the list lives here, at the top of the scene, positioned in SCENE
// coordinates (what `mapToItem(null, …)` at the call site gives). Nothing can
// draw over it, and nothing clips it.
Item {
    id: overlay
    visible: false
    z: 2900

    property var options: []
    property string value: ""
    property int visibleRows: 12
    property var onPicked: null

    // Open under `item` (a Picker's box), matching its width. Everything is
    // measured from the item itself so a caller cannot get the arithmetic wrong.
    function openFor(item, opts, current, cb) {
        var p = item.mapToItem(null, 0, item.height)
        overlay.options = opts || []
        overlay.value = current || ""
        overlay.onPicked = cb || null
        pop.width = Math.max(item.width, 180)
        pop.x = p.x
        pop.y = p.y + 1
        overlay.visible = true
        // Clamp INTO the window rather than let a picker near the bottom edge
        // open off-screen — the same rule CtxMenu follows.
        if (pop.x + pop.width > overlay.width - 4)
            pop.x = Math.max(4, overlay.width - pop.width - 4)
        if (pop.y + pop.height > overlay.height - 4) {
            var above = p.y - item.height - pop.height - 1
            pop.y = above >= 4 ? above : Math.max(4, overlay.height - pop.height - 4)
        }
        list.positionViewAtIndex(Math.max(0, overlay.options.indexOf(overlay.value)),
                                 ListView.Contain)
        focusSink.forceActiveFocus()
    }

    function close() {
        overlay.visible = false
        overlay.onPicked = null
    }

    // Outside click dismisses and is SWALLOWED, so the click that closes a list
    // does not also press whatever sits under it.
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onPressed: overlay.close()
        // A dropdown pinned to scene coordinates would float away from its box
        // if the column scrolled underneath it, so a wheel closes it instead of
        // leaving a list pointing at nothing.
        onWheel: overlay.close()
    }

    Item {
        id: focusSink
        focus: overlay.visible
        Keys.onEscapePressed: overlay.close()
    }

    Rectangle {
        id: pop
        height: Math.min(overlay.visibleRows, list.count) * 19 + 2
        color: Theme.bgAlt
        border.color: Theme.accent
        border.width: 1

        KineticListView {
            id: list
            anchors.fill: parent
            anchors.margins: 1
            model: overlay.options
            clip: true
            currentIndex: overlay.options.indexOf(overlay.value)

            delegate: Rectangle {
                width: list.width
                height: 19
                color: hover.containsMouse || modelData === overlay.value
                     ? Theme.highlight : "transparent"
                PixelText {
                    anchors.verticalCenter: parent.verticalCenter
                    x: 5
                    width: parent.width - 10
                    elide: Text.ElideRight
                    text: modelData
                    color: modelData === overlay.value ? Theme.accent : Theme.text
                }
                MouseArea {
                    id: hover
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        var cb = overlay.onPicked
                        overlay.close()
                        if (cb) cb(modelData)
                    }
                }
            }
        }
    }
}
