import QtQuick

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
        property real originX: 0
        property real originY: 0
        function place() {
            if (!area.Window.contentItem)
                return;
            var p = area.mapToItem(area.Window.contentItem, area.width, area.height / 2);
            chip.originX = p.x + 8;
            chip.originY = p.y;
        }

        // The reveal is the CLIP growing rightward from a fixed left edge; the
        // card inside is full size the whole time.
        // DRIVEN by the dwell and by `area.close()`, never bound to `open` —
        // see the note on that function.
        property bool animate: false
        property real slide: 0
        Behavior on slide {
            enabled: chip.animate   // out over 220ms; back in one frame
            NumberAnimation { duration: 220; easing.type: Easing.OutCubic }
        }

        readonly property real fullW: Math.min(metrics.implicitWidth + 16, 360)
        readonly property real fullH: label.implicitHeight + 10

        width: fullW * slide
        height: fullH
        x: Math.max(4, Math.min(originX, (parent ? parent.width : 0) - fullW - 4))
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
            anchors.left: parent.left   // revealed from the left as the clip grows
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
