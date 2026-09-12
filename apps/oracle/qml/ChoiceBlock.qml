import QtQuick

// ONE CANDIDATE ON A DECISION CARD, drawn as a button — an oversized one, the
// size of the block it holds [his, 2026-09-12: "can you make them look like
// actual buttons just larger than normal"]. A decision card's options are not
// a word each: they are a name, a line of details and a note, so the control
// is a real relief cell with all of that inside it rather than a verb-sized
// chip under a paragraph.
//
// The Hyprland face is JobVerb's cell grown to fit (docs/DESIGN.md §7.2,
// §12.1): `bgAlt`, a 1px border, lighting to `highlight` under the pointer and
// holding `highlight` + an `accent` border once it is the one he took (§3.3 —
// state is a brightness ladder on one hue). `+plasma/ChoiceBlock.qml` is the
// twin, a real KStyle button (§7.6).
//
// Text colour belongs to the SURFACE, so the block publishes it and the card
// paints with what it is given: on a KStyle button that is `buttonText`, not
// the window's own text colour, and a dead block drops a step rather than
// vanishing (§3.2, §10.1).
//
// API: `lit`, `enabled`, `clicked()`, the content as children, and the three
// foreground colours `fg` / `fgDim` / `fgFaint`.
Rectangle {
    id: root
    property string face: "hypr"
    property bool lit: false
    default property alias blockData: holder.data

    signal clicked()

    readonly property bool live: root.enabled
    readonly property bool hot: root.live && mouse.containsMouse

    readonly property color fg: root.live ? Theme.text : Theme.textDim
    readonly property color fgDim: root.live ? Theme.textDim : Theme.dim
    readonly property color fgFaint: Theme.dim

    readonly property int pad: 10
    implicitHeight: holder.childrenRect.height + pad * 2
    height: implicitHeight
    radius: 3
    color: (root.hot || root.lit) ? Theme.highlight : Theme.bgAlt
    border.width: Theme.ctrlBorder
    border.color: root.lit ? Theme.accent : Theme.border

    Item {
        id: holder
        x: root.pad
        y: root.pad
        width: parent.width - root.pad * 2
        height: childrenRect.height
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
