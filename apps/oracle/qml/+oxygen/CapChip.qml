import QtQuick
import QtQuick.Controls as QQC

// One capability the selected model reports, in an Oxygen session.
//
// `+plasma/CapChip.qml` already gets the frame from the style — a real Button's
// background, never in the input path, because a chip that reads as pressable
// but does nothing is an affordance lie in any style. What it still carries is
// `opacity: 0.75` standing in for "this is subordinate", and a fraction of the
// live foreground is not a colour Oxygen has: KColorScheme publishes a DISABLED
// foreground for exactly this reading, and that is what every greyed caption in
// the same window is wearing. Measured under Oxygen offscreen: the live label
// is #f4eaf4 and the disabled one #736162 — a different hue, not a dimmer one,
// so the fraction was never going to land on it.
//
// The chip's geometry stays the sibling's rather than the Button's own: letting
// the style size it gives Oxygen's full 32px button height (measured), and this
// row is anchored across the stats strip beside the context bar, which a
// control that tall would overrun. Sizing is layout; the frame and the colour
// are the style's, and those are the parts that were ours.
//
// Same API as ../CapChip.qml — `label` — so Root.qml is untouched.
Item {
    id: root
    property string face: "oxygen"
    property string label: ""

    implicitWidth: capText.implicitWidth + 14
    implicitHeight: capText.implicitHeight + 6
    width: implicitWidth
    height: implicitHeight

    QQC.Button {
        anchors.fill: parent
        enabled: false
        focusPolicy: Qt.NoFocus
        // NOT flat: a flat button draws no relief until it is hovered, and this
        // one never is. The frame is the whole point of a chip.
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
        // The style's own subordinated foreground, not a fraction of the live
        // one.
        enabled: false
    }
}
