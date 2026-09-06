import QtQuick

// One capability the selected model reports (vision, tools, thinking, …), as a
// small NON-clickable indicator chip (docs/DESIGN.md §3.2 subordinated
// indicator, §7.2 chip: bgAlt + 1px border + radius 3).
//
// A component rather than a Rectangle in Root.qml because it has a Plasma twin
// (`+plasma/CapChip.qml`, the KStyle's own frame). API: `label`.
Rectangle {
    id: root
    property string face: "hypr"     // how a harness proves which one loaded
    property string label: ""

    height: capText.implicitHeight + 4
    width: capText.implicitWidth + 10
    radius: 3
    color: Theme.bgAlt
    border.width: Theme.ctrlBorder
    border.color: Theme.border

    PixelText {
        id: capText
        anchors.centerIn: parent
        text: root.label
        // Full-strength text, not textDim: at chip size on bgAlt the dim grey
        // was not readable [his, 2026-09-05]. The subordination is the chip's
        // size and its frame, not a washed-out label.
        color: Theme.text
    }
}
