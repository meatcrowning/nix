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
//
// AND SO IS THE LABEL'S GLYPH. `label` is written for the pixel face, where an
// affordance is a character — "> play", "+ queue", "x close", a bare "x" —
// because there are no icons in that vocabulary and the hyprvtb titlebar
// column is where it comes from. A styled Button reading `x close` is that
// vocabulary leaking into a session that has a whole icon theme for it, so a
// call site with a glyph states `plainLabel` and `iconName` beside it and this
// face draws THOSE: the words alone, with the desktop's own icon. Both are
// inert in the sibling, so nothing about the Hyprland button moves.
Item {
    id: root
    property string face: "plasma"   // how a harness proves the swap happened
    property string label: ""
    property string plainLabel: ""
    property string iconName: ""
    property bool iconOnly: false
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
        // `plainLabel` wins where the pixel label carries a glyph; a label that
        // is already plain words is used as it stands. Only `iconOnly` drops the
        // text — an empty `plainLabel` is a call site that had nothing to
        // restate, not one asking for a wordless button.
        text: root.iconOnly ? "" : (root.plainLabel !== "" ? root.plainLabel : root.label)
        icon.name: root.iconName
        display: root.iconOnly ? Button.IconOnly
               : (root.iconName === "" ? Button.TextOnly : Button.TextBesideIcon)
        enabled: root.enabled
        // A LIT button IS its state (§12.1) — `highlighted` is the KStyle's own
        // way of saying so, the same one a checked toolbar row gets.
        highlighted: root.lit
        onClicked: root.clicked()
    }
}
