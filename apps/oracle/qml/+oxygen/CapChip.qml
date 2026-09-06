import QtQuick
import QtQuick.Controls as QQC

// One capability the selected model reports, in an Oxygen session.
//
// `+plasma/CapChip.qml` already gets the frame from the style — a real Button's
// background, never in the input path, because a chip that reads as pressable
// but does nothing is an affordance lie in any style. What this face adds is
// the LABEL COLOUR. It wore KColorScheme's disabled foreground for a while,
// on the reading that a chip is subordinate; measured under Oxygen offscreen
// that is #736162 against a live #f4eaf4 — a different hue, not a dimmer one,
// and at chip size he could not read it [his, 2026-09-05]. Subordination here
// is the chip's size and its frame; the words are full strength.
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
        // The LIVE foreground, not KColorScheme's disabled one. That disabled
        // grey (#736162 against the chip's frame) is what a greyed caption
        // wears, and at chip size he could not read it [his, 2026-09-05]. The
        // frame and the size are what say "subordinate" here.
        enabled: true
    }
}
