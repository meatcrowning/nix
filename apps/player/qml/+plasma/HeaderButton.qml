import QtQuick
import QtQuick.Controls

// HeaderButton, in a Plasma session: a real flat Button, drawn by the desktop's
// KStyle through qqc2-desktop-style — Oxygen's own hover glow, pressed state
// and focus ring, not an imitation of them.
//
// Same API as ../HeaderButton.qml (label, lit, the three foreground tones,
// clicked), so no call site changes; the file selector picks between the two
// (main.py -> kdeshell.select_plasma_files). The tones are ACCEPTED AND
// IGNORED: a KDE button's colours are the scheme's, and honouring a
// hand-derived accent here is exactly the imitation this face exists to stop.
Item {
    id: root
    property string face: "plasma"   // how a harness proves the swap happened
    property string label: ""
    property bool lit: false
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent
    signal clicked()

    implicitWidth: btn.implicitWidth
    implicitHeight: btn.implicitHeight
    width: implicitWidth
    height: implicitHeight

    Button {
        id: btn
        anchors.fill: parent
        flat: true
        text: root.label
        enabled: root.enabled
        // A LIT button IS its state (§12.1) — `highlighted` is the KStyle's own
        // way of saying so, the same one a checked toolbar row gets.
        highlighted: root.lit
        onClicked: root.clicked()
    }
}
