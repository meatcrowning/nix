import QtQuick
import "../../qmlcommon"

// Hover explanation, used wherever a control's reasoning is not obvious from
// its label (why an encoder was chosen, why a LoRA is greyed out).
//
// This used to be QtQuick.Controls.Basic's attached `ToolTip`, which draws in
// the SYSTEM font and the SYSTEM palette — the only place on this desktop a
// non-pixel-font surface could appear (docs/DESIGN.md §2.1, §8). It is now the
// desktop's own tooltip: a dwell, then a clipped slide out of a FIXED edge, in
// theme colours and PixelText, matching surfer's in-window tooltip and
// hyprvtb's titlebar one. Retraction is immediate, per §8.
//
// The chip is reparented into the window's contentItem because painter's left
// column is a stack of `clip: true` panels inside a Flickable — drawn in place
// it would be cut off by whichever box it belongs to.
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

    // The retraction SNAPS (docs/DESIGN.md §8), and the gate is cleared BEFORE the
    // assignment for a reason: `Behavior { enabled: area.open }` is a second
    // binding over the same property and QML gives no ordering between the two,
    // so the close animated anyway — measured offscreen against the real
    // component, 240 -> 143 -> 42 -> 0 over ~200ms. Doing it imperatively cannot
    // lose that race. (Same fix in `apps/board/qml/ToolTipArea.qml`.)
    function close() {
        chip.animate = false;
        chip.slide = 0;
        area.open = false;
    }

    // 350ms, the panel Tooltip.qml dwell.
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

        // The anchor is recomputed on every open: a plain mapToItem binding
        // captures the ancestor positions once, at creation, and the left
        // column scrolls.
        // Recomputed on every open: a plain `mapToItem` binding captures the
        // ancestor positions once, at creation, and this column scrolls.
        //
        // `originX` is the chip's RIGHT edge — the fixed one — sitting just off
        // the hovered item's LEFT side, which is the side the free space is on.
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
        // (docs/DESIGN.md §8, and the panel's `Tooltip.qml` it is specified
        // from); the card inside is full size the whole time.
        //
        // It grew the OTHER way until 2026-08-07, and §19.1 carried it as the
        // last unaudited divergence from §8 — "nobody has checked whether its
        // chips have room to the left of the toolbar they hang off". Audited:
        // the answer had quietly changed underneath it. This file's own comment
        // still described painter's controls as the LEFT column, which is where
        // they were when rightward was chosen — a chip then opened into the
        // gallery, with the whole window beside it. The panes were SWAPPED since
        // ("THE RESULTS LEAD", Main.qml), so the controls are the right-hand
        // column now and rightward means straight at the window edge: at the
        // 1280 default the column runs to the frame, and a chip at the 360 cap
        // off anything past x=916 hits the clamp and lands on top of the control
        // it belongs to. Leftward opens into the results pane instead, which is
        // the larger side at every width. So §8 and the layout now agree.
        //
        // DRIVEN by the dwell and by `area.close()`, never bound to `open` —
        // see the note on that function.
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
        // terms of the wrapped label's own width.
        PixelText {
            id: metrics
            visible: false
            text: area.text
        }

        Rectangle {
            width: chip.fullW
            height: chip.fullH
            anchors.right: parent.right  // revealed from the right as the clip grows
            color: Theme.bgAlt
            radius: Theme.rounding
            border.color: Theme.border
            border.width: Theme.ctrlBorder
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
