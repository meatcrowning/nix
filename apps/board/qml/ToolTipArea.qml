import QtQuick
import "../../qmlcommon"

// Hover explanation for one thing in the window, per docs/DESIGN.md §8: a dwell,
// then a 220ms clipped slide out of a FIXED edge, in theme colours and
// `PixelText`. Retraction is immediate. Never a `QtQuick.Controls` `ToolTip` —
// that draws in the SYSTEM font and palette, the one way a non-pixel-font
// surface can appear on this desktop (§2.1).
//
// A second copy of `apps/painter/qml/ToolTipArea.qml` in everything but its
// DIRECTION — painter's slides out of a fixed left edge and this one out of a
// fixed right edge, which is what §8 actually specifies. Kept as a copy because
// `qmlcommon/` cannot hold this one: the chip is
// `PixelText` and that type is resolved per app directory — a shared version
// would have to re-implement the font rules every app's own `PixelText` states.
// §19.1 already tracks the tooltip as living in more than one place; retune the
// dwell and the slide in both.
//
// The chip is reparented into the window's `contentItem`: goetia draws inside a
// `clip: true` flickable, so a tooltip drawn in place would be cut off by the
// viewport edge and would scroll away with the row it belongs to.
MouseArea {

    // The desktop's one slide duration + curve (docs/DESIGN.md 6.2):
    // hyprvtb's roll, scaled by reduceMotion/animSpeed. NEVER a literal.
    Motion { id: motion }
    id: area
    property string text: ""
    hoverEnabled: enabled && text !== ""
    acceptedButtons: Qt.NoButton

    property bool open: false

    onContainsMouseChanged: {
        if (containsMouse && text !== "") {
            dwell.restart();
        } else {
            dwell.stop();
            area.close();
        }
    }
    onEnabledChanged: if (!enabled) { dwell.stop(); area.close(); }

    // The retraction has to SNAP (§8), and the flag is cleared BEFORE the
    // assignment for a reason: `Behavior { enabled: area.open }` is a second
    // binding over the same property, and QML gives no ordering between the two
    // — painter's copy has it that way and animates its retraction anyway
    // (measured offscreen: 240 -> 143 -> 42 -> 0 over ~200ms). Setting the gate
    // imperatively first cannot lose that race.
    function close() {
        chip.animate = false;
        chip.slide = 0;
        area.open = false;
    }

    // 350ms, the panel's `Tooltip.qml` dwell (§8's known divergence is hyprvtb's
    // 450, not a third number here).
    Timer {
        id: dwell
        interval: 350
        onTriggered: {
            chip.place();
            chip.animate = true;
            chip.slide = 1;
            area.open = true;
        }
    }

    Item {
        id: chip
        parent: area.Window.contentItem
        z: 5000
        clip: true
        visible: slide > 0.001

        // Recomputed on every open: a plain `mapToItem` binding captures the
        // ancestor positions once, at creation, and this window scrolls.
        //
        // `originX` is the chip's RIGHT edge — the fixed one — and it sits just
        // off the row's LEFT side, the side the free space is on: these meters
        // are anchored to the chooser's right edge, so a chip hung off their
        // right has the window edge immediately beyond it.
        property real originX: 0
        property real originY: 0
        function place() {
            if (!area.Window.contentItem)
                return;
            var p = area.mapToItem(area.Window.contentItem, 0, area.height / 2);
            chip.originX = p.x - 8;
            chip.originY = p.y;
        }

        // The reveal is the CLIP growing LEFTWARD from a fixed right edge
        // (docs/DESIGN.md §8, and the panel's `Tooltip.qml` it is specified from);
        // the card inside is full size the whole time, so nothing reflows.
        // `slide` is DRIVEN (by the dwell and by `area.close()`), not bound to
        // `open` — see the note on that function.
        //
        // It grew the other way for its first hours because this file was copied
        // from painter's, which has always slid out of a fixed LEFT edge (§19.2
        // records that shape) — a divergence from §8 that the copy inherited
        // wholesale. [his, 2026-07-29] *"it slides out to the right, it was
        // supposed to slide out to the left"*.
        property bool animate: false
        property real slide: 0
        Behavior on slide {
            enabled: chip.animate   // out over 220ms; back in one frame
            NumberAnimation { duration: motion.ms(motion.slideMs); easing.type: motion.slideEasing }
        }

        readonly property real fullW: Math.min(metrics.implicitWidth + 16, 360)
        readonly property real fullH: label.implicitHeight + 10

        // The right edge is what is pinned, so `x` trails the width instead of
        // leading it: the clip opens to the left and closes back to the right,
        // the same way it came. Clamped as a RIGHT edge — never past the window
        // edge, never so far left that the full card cannot fit beside it.
        readonly property real rightX:
            Math.max(fullW + 4, Math.min(originX, (parent ? parent.width : 0) - 4))

        width: fullW * slide
        height: fullH
        x: rightX - width
        y: Math.max(4, Math.min(originY - fullH / 2,
                                (parent ? parent.height : 0) - fullH - 4))

        // Natural (unwrapped) width of the string, so `fullW` is not defined in
        // terms of the wrapped label's own width — that is the §8 binding loop.
        PixelText {
            id: metrics
            visible: false
            text: area.text
        }

        Rectangle {
            width: chip.fullW
            height: chip.fullH
            anchors.right: parent.right   // revealed right-to-left as the clip grows
            color: Theme.bgAlt
            border.color: Theme.border
            border.width: 1
            PixelText {
                id: label
                x: 7
                y: 5
                width: chip.fullW - 14
                wrapMode: Text.Wrap
                text: area.text
                color: Theme.text
            }
        }
    }
}
