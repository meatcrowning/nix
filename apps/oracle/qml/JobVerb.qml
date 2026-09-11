import QtQuick

// One verb on a job row — `log`, `stop`, `clear` — in the Hyprland session's own
// idiom: a lowercase word in a `bgAlt` cell that lights to `highlight` under the
// pointer (docs/DESIGN.md §7.2, §12.1). Small, quiet, and never a button
// pretending to be a button: it does exactly what its word says (§10.2).
//
// A component because it has a Plasma twin (`+plasma/JobVerb.qml`, a real
// KStyle button). API: `label`, `lit`, `enabled`, `clicked()`.
//
// `lit` is the PRESSED-AND-STAYING-PRESSED state a decision card needs
// (ChoiceCard.qml): once he has answered, the option he took stays held down
// beside its greyed siblings, so the card reads as the record of a choice
// rather than as a live control. §3.3 — state is a brightness ladder on one
// hue, and §3.5 — the answered row says it twice, in tone and in weight.
Rectangle {
    id: root
    property string face: "hypr"
    property alias label: verbText.text
    property bool lit: false

    signal clicked()

    readonly property bool live: root.enabled
    readonly property bool hot: root.live && mouse.containsMouse

    implicitWidth: verbText.implicitWidth + 12
    implicitHeight: verbText.implicitHeight + 6
    width: implicitWidth
    height: implicitHeight
    radius: 3
    color: root.hot ? Theme.highlight
         : root.lit ? Theme.highlight : Theme.bgAlt
    border.width: Theme.ctrlBorder
    border.color: root.lit ? Theme.accent : Theme.border

    PixelText {
        id: verbText
        anchors.centerIn: parent
        // A verb given a WIDTH (a decision card divides its row between the
        // candidates) shrinks its own name to fit; one sized by its text —
        // the jobs tray's `log` / `stop` — is unaffected, since implicitWidth
        // is the natural width and never reads this back.
        width: Math.max(0, root.width - 12)
        horizontalAlignment: Text.AlignHCenter
        elide: Text.ElideRight
        // The unlit-and-dead verb drops a step rather than vanishing: it is
        // still being read, just not offered (§3.2, §10.1).
        color: root.hot ? Theme.accent
             : root.lit ? Theme.accent
             : root.live ? Theme.textDim : Theme.dim
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: root.live
        enabled: root.live
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
