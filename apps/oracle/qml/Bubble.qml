import QtQuick

// One message's frame — a BUTTON, not a tinted slab [his, 2026-08-22]. Under
// Hyprland that is this desktop's own button spec (docs/DESIGN.md §4, §7.2):
// `Theme.bg` on the `bgAlt` reply panel, a `Theme.ctrlBorder` hairline at
// `Theme.border`, `Theme.rounding` corners. In a Plasma session the file
// selector swaps in `+plasma/Bubble.qml`, which is a real KStyle button frame.
//
// It draws no hover or pressed state in either face: the log is selectable
// text and nothing in it is clickable, so a fill that answered the pointer
// would promise a press that never happens (docs/DESIGN.md §10.2).
//
// Same API either way: `user`, `isError`, and whatever is put inside it.
Item {
    id: root
    property string face: "hypr"     // how a harness proves which one loaded
    property bool user: false
    property bool isError: false
    readonly property real tailHeight: 0
    default property alias content: holder.data

    Rectangle {
        anchors.fill: parent
        radius: Theme.rounding
        color: Theme.bg
        border.width: Theme.ctrlBorder
        border.color: root.isError ? Theme.crit
                      : (root.user ? Theme.accent : Theme.border)
    }
    Item { id: holder; anchors.fill: parent }
}
