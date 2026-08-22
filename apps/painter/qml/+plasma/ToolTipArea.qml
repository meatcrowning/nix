import QtQuick
import QtQuick.Controls

// ToolTipArea, in a Plasma session: the STYLE'S tooltip.
//
// ../ToolTipArea.qml is a hand-built flyout — a chip re-parented into the
// window's contentItem (painter's left column is clip:true panels inside a
// Flickable, so a tooltip drawn in place is cut off), sliding out of a fixed
// edge in 220ms, docs/DESIGN.md §8. All of that is this desktop's tooltip
// vocabulary, and none of it is KDE's: here a tooltip is the desktop's own,
// with the desktop's dwell, its palette, and its own window — so the clipping
// problem does not arise either.
//
// Same API: `text`, `open`, and it is still a MouseArea that takes no buttons,
// so it never eats a click from what it covers.
MouseArea {
    id: area
    property string face: "plasma"
    property string text: ""
    property bool open: tip.visible
    hoverEnabled: enabled && text !== ""
    acceptedButtons: Qt.NoButton

    ToolTip {
        id: tip
        text: area.text
        visible: area.enabled && area.text !== "" && area.containsMouse
        delay: 600
    }
}
