import QtQuick
import QtQuick.Controls as QQC

// A capability indicator in a Plasma session: the KStyle's own button frame
// around the label, exactly the way `+plasma/Bubble.qml` draws a message — the
// control is never in the input path (`enabled: false`, an empty contentItem),
// because a chip that reads as pressable but does nothing is the affordance lie
// docs/DESIGN.md §10.2 forbids. It is an indicator, and it says what it is by
// looking like the rest of the window rather than like a pixel-era chip.
//
// Same API as ../CapChip.qml — `label` — so Root.qml is untouched.
Item {
    id: root
    property string face: "plasma"
    property string label: ""

    implicitWidth: capText.implicitWidth + 14
    implicitHeight: capText.implicitHeight + 6
    width: implicitWidth
    height: implicitHeight

    QQC.Button {
        anchors.fill: parent
        enabled: false
        // NOT flat: a flat KStyle button draws no relief at all until it is
        // hovered, and this one never is — the chips came out as bare words
        // with nothing boxing them. The frame is the whole point of a chip.
        text: ""
        // A disabled control is drawn dimmed; nothing here is unavailable, so
        // the frame keeps full opacity and the disable takes only the input.
        background.opacity: 1.0
        contentItem: Item {}
    }
    QQC.Label {
        id: capText
        anchors.centerIn: parent
        text: root.label
        opacity: 0.75
    }
}
