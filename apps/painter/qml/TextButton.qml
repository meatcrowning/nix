import QtQuick

// THE clickable label for painter. Every action in this app used to be a bare
// PixelText with a MouseArea dropped on it: no hover feedback, no cursor
// change, no disabled state, and nothing stopping a click on a control whose
// action could not happen. That is the shape docs/DESIGN.md §10 rules out, so the
// affordances live here once instead of being re-decided (or forgotten) at
// twenty-odd call sites.
//
// The idiom is player's HeaderButton — a flat pixel-text button, hover tinted
// with Theme.highlight, no box — carrying filer's BrowserButton semantics for
// `enabled` (0.4 opacity, arrow cursor, click refused) and for greying to
// Theme.inactive when the window is unfocused, which is the exact tone the
// hyprvtb titlebar fades its own glyphs to. Labels keep painter's bracket
// idiom, "[ start ]", written by the caller.
Item {
    id: root
    property string label: ""
    property color tone: Theme.accent      // resting colour; semantic per action
    property bool lit: false               // this action is the current state
    // `enabled` is Item's own, deliberately not redeclared: shadowing it warns
    // at load and leaves the base property still doing its job underneath.
    // Item.enabled propagates down, so a disabled button's MouseArea is
    // disabled too and Qt refuses the click for us.
    property bool winActive: true
    // A paired up/down affordance is ONE glyph mirrored, never two characters
    // (docs/DESIGN.md §2.4): "^" is not "v" upside down in this font — from the glyf
    // table "v" sits on the baseline while "^" is hard against the ascender, so
    // the two read as sitting at different heights inside the same button. Set
    // `flipY` on the "up" one and give it the "v" label.
    property bool flipY: false
    signal clicked()

    implicitWidth: txt.implicitWidth + 8
    implicitHeight: Theme.fontSize + 5
    width: implicitWidth
    height: implicitHeight
    opacity: enabled ? 1 : 0.4

    Rectangle {
        anchors.fill: parent
        color: (ma.containsMouse && root.enabled) ? Theme.highlight : "transparent"
    }

    PixelText {
        id: txt
        anchors.horizontalCenter: parent.horizontalCenter
        // Integer origin, so NativeRendering stays crisp under the flip.
        y: Math.round((root.height - height) / 2)
        transform: Scale {
            yScale: root.flipY ? -1 : 1
            origin.x: txt.width / 2
            origin.y: Math.round(txt.height / 2)
        }
        text: root.label
        // Unfocused window: chrome greys with the titlebar rather than staying
        // brighter than the bar above it.
        color: !root.winActive ? Theme.inactive
             : root.lit ? Theme.accent
             : root.tone
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: root.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: if (root.enabled) root.clicked()
    }
}
