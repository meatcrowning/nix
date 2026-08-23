import QtQuick
import QtQuick.Controls as QQC

// One message's frame in a Plasma session: the KStyle's own BUTTON, drawn by
// qqc2-desktop-style rather than imitated (apps/AGENTS.md → kdeshell) — his
// ask, 2026-08-22, that the bubbles read as buttons.
//
// The frame is a real `Button`'s background item and nothing else: the button
// itself is never in the input path (`enabled: false` on the control, so it
// takes no hover, no press and no focus), while the message's own text is
// drawn ABOVE it at full colour and stays selectable. A live button under a
// log of read-only text would promise a press that never happens
// (docs/DESIGN.md §10.2).
//
// Same API as ../Bubble.qml: `user`, `isError`, and whatever is put inside it.
Item {
    id: root
    property string face: "plasma"
    property bool user: false
    property bool isError: false
    default property alias content: holder.data

    QQC.Button {
        id: frame
        anchors.fill: parent
        enabled: false
        // The KStyle draws the background; the label stays empty because the
        // message is `holder`'s children, above this.
        text: ""
        // A disabled control is drawn dimmed, which is the wrong reading here
        // — nothing is unavailable. Paint the background at full opacity and
        // let the disable only take the input.
        background.opacity: 1.0
        contentItem: Item {}
    }
    Item { id: holder; anchors.fill: parent }
}
