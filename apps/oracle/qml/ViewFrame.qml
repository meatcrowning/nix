import QtQuick

// The frame around the conversation — the app's one VIEW, in the Hyprland
// session's own idiom: a `bgAlt` surface with a 1px border and the desktop's
// corner radius (docs/DESIGN.md §4, §9.1).
//
// A component rather than a Rectangle in Root.qml because it has a Plasma twin
// (`+plasma/ViewFrame.qml`, the KStyle's own frame). Whatever is put inside it
// anchors to `parent` and is already inset by `pad` — the padding lives here so
// the two faces can differ (the KStyle's frame has margins of its own) without
// the call site knowing.
Rectangle {
    id: root
    property string face: "hypr"     // how a harness proves which one loaded
    readonly property int pad: 8
    default property alias content: inner.data

    color: Theme.bgAlt
    radius: Theme.rounding
    border.width: Theme.ctrlBorder
    border.color: Theme.border

    Item {
        id: inner
        anchors { fill: parent; margins: root.pad }
    }
}
