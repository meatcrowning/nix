import QtQuick

// THE SURFACE A MODAL SHEET SITS ON. One user (the rule editor), and it is a
// component for the same reason `ViewFrame` is one in chatter: so the Plasma
// session can hand the painting to the style.
//
// Under Hyprland it is docs/DESIGN.md §7.2's modal box — `Theme.bg`, the
// window's own frame width and colour, the window's corner radius — because a
// sheet over an app of ours reads as a window and the desktop draws its own
// windows. In a Plasma session that same frame is a window drawn INSIDE a real
// KDE window, in a colour derived from the scheme's focus decoration, and it is
// the last hand-drawn surround in this app (`+plasma/SheetFrame.qml`).
//
// Content goes straight in and anchors to `parent`; the wrapper is an Item of
// exactly the sheet's size in both faces, so nothing inside it moves.
Item {
    id: root
    property string face: "hypr"     // how a harness proves which one loaded
    default property alias content: inner.data

    Rectangle {
        anchors.fill: parent
        color: Theme.bg
        radius: Theme.windowRounding
        border.width: Theme.windowBorderWidth
        border.color: Theme.windowBorder
    }

    Item { id: inner; anchors.fill: parent }
}
