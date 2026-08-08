import QtQuick

// A section band: `needs you`, `the triangle`, `landed`.
//
// A heading here is told apart by a RULE and by spacing, never by size or
// weight — reader's reading of docs/DESIGN.md §2.2 (the font ships Regular only
// and every size on this desktop is one setting), and the same idiom so the two
// document-shaped apps do not disagree one alt-tab apart. The bands differ by
// the rule's COLOUR: accent for the one that wants him (`needs you` — still
// the ONLY thing "active" means on this control, §3.8 law 2), `accent2` — the
// secondary hue, at foreground value — for every other one. It used to be the
// plain `border` hairline; §3.8 names exactly this ("a section header, a
// group rule") as the case that hue is for, so every band reads as structure
// without any of them claiming to be current.
//
// It is also the collapse control, and it says so: `[-]` open, `[+]` closed,
// ASCII because the font has no triangles (§2.3). Clicking the band toggles.
Item {
    id: head

    property string label: ""
    property bool accented: false
    property bool collapsed: false
    property color fgAccent: Theme.accent
    property color fgAccent2: Theme.accent2
    property color fgDim: Theme.textDim
    property bool interactive: true
    //: [his ask, 2026-08-01; re-ask 2026-08-02] the TOP-LEVEL bands are drag
    //  handles as well as collapse toggles: a vertical drag on the band reorders
    //  the section it heads, and the page turns the displacement into a target
    //  and repersists the display order. Every heading is now a top-level
    //  section — `to do` and `workings` (the live tool-call band) were promoted
    //  out of `needs` and the triangle so he can place them anywhere. OPT-IN —
    //  only the section bands set it; a sub-band (a tag group, a LANDED day)
    //  stays a plain toggle, because a reorder that grabs a sub-section is not a
    //  thing this page offers. The one gesture does both jobs: a drag is a drag (the
    //  `clicked` is suppressed once the pointer crosses the threshold, so the
    //  band never reorders on the tap that toggles it), and a tap is the usual
    //  collapse toggle.
    property bool reorderable: false

    signal toggled()
    signal reorderRequested(real dy)

    implicitHeight: Theme.lineHeight + 14
    height: implicitHeight

    Rectangle {              // the row lights on hover like every other row
        anchors.fill: parent
        color: ma.containsMouse && head.interactive ? Theme.highlight : "transparent"
    }

    PixelText {
        id: mark
        x: 0
        anchors.verticalCenter: parent.verticalCenter
        color: head.fgDim
        text: head.collapsed ? "[+]" : "[-]"
        visible: head.interactive
    }

    PixelText {
        id: name
        x: mark.visible ? mark.width + 8 : 0
        anchors.verticalCenter: parent.verticalCenter
        color: head.accented ? head.fgAccent : head.fgDim
        text: head.label
    }

    // The rule runs from the label to the far edge, so the band reads as one
    // line of type with a hairline finishing it rather than as a boxed header.
    // A band with NO label (`needs you`, [his, 2026-07-29] "just have the line
    // and collapse toggle") keeps ONE 8px gutter after the toggle rather than
    // the two an empty label would leave behind it.
    Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        x: head.label === "" ? name.x : name.x + name.width + 8
        width: Math.max(0, parent.width - x)
        height: 1
        color: head.accented ? head.fgAccent : head.fgAccent2
    }

    //: the drag's hidden proxy, so the band itself never moves — the page reads
    //  the displacement off `dragProxy.y` on release, exactly like a decision's
    //  title grip (`Decision.qml`). §6.4 direct manipulation: the pointer moves
    //  the band's phantom 1:1, and only a real drag emits anything.
    Item { id: dragProxy; visible: false }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        enabled: head.interactive
        cursorShape: head.reorderable && head.interactive
                     ? Qt.SizeVerCursor : Qt.PointingHandCursor
        drag.target: head.reorderable ? dragProxy : null
        drag.axis: Drag.YAxis
        drag.threshold: 8
        onPressed: if (head.reorderable) dragProxy.y = 0
        // A tap (no threshold crossed) never emits: it is the collapse toggle.
        onReleased: if (head.reorderable && ma.drag.active)
                        head.reorderRequested(dragProxy.y)
        onClicked: head.toggled()
    }
}
