import QtQuick
import Quickshell
import Quickshell.Wayland

// Shared base for the bar's hover popups. Slides in from the right edge,
// stays while hovered (350ms grace), mutually exclusive via Popups.
//
// Positioning (unpinned):
//   anchorCenterY >= 0 -> vertical CENTER at that scene-Y (cpu/eth), UNLESS
//                         aboveDiskWhenPinned and the disk widget is open, in
//                         which case it stacks just above the disk panel.
//   anchorCenterY < 0  -> bottom-anchored (clock/date/weather/disk).
//
// Pinning (pin indicator, top-right): a pinned popup becomes a desktop widget
// — stays open, drops to the bottom z-layer, and its border goes inactive.
//   pinInPlace = false (default): tiles into a right-to-left row along the
//                bottom (Popups.offsetFor) so pinned widgets don't overlap.
//   pinInPlace = true  (cpu/eth): freezes wherever it was when pinned (above
//                the disk, or centered on its module) rather than dropping to
//                the bottom row.
PanelWindow {
    id: root

    default property alias contentData: contentHolder.data
    property string popupNamespace: "qs-popup"
    property bool open: false
    property bool wantOpen: false
    property bool pinnedOpen: false

    property real anchorCenterY: -1
    property bool isDisk: false
    property bool aboveDiskWhenPinned: false
    property bool pinInPlace: false
    property string persistKey: ""   // stable id for save/restore of pins

    // Fan reveal (vertical emerge), used ONLY by the reveal-all fan for the
    // in-place stackables (gpu/cpu/eth): instead of sliding in horizontally
    // from the right edge, the card rises up out of the widget below it
    // (disk -> gpu -> cpu -> eth), and sinks back into it on hide — the
    // reverse. _fanActive suppresses the normal horizontal card slide while
    // the vertical one plays; _fanY is the card's downward offset (its own
    // height + a gap = fully tucked below its surface, i.e. over the widget
    // below); _fanYAnim gates whether a _fanY change animates or snaps.
    property bool _fanActive: false
    property bool _fanYAnim: false
    property bool _fanRevealPending: false
    property real _fanY: 0
    Behavior on _fanY { enabled: root._fanYAnim; NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }

    // Scene-Y of our top edge while pinned in-place, recomputed LIVE (not
    // frozen at pin time) so an obstacle growing below us — the disk widget
    // filling in its rows/SMART lines as its scripts finish — pushes us up
    // instead of ending up underneath us. Read by stacking siblings via
    // Popups.stackObstacleTop.
    readonly property real pinnedTopY: frozenTop ? _topPos : -1

    // Hyprland files a layer surface into its layer array at creation and
    // never moves it, so a live WlrLayershell.layer change is ignored. When
    // the pinned state (=> layer) flips on an already-mapped popup, force a
    // remap (unmap for a frame, then re-map) so it re-files at the new layer:
    // Overlay (above windows) transient, Bottom (behind windows) pinned.
    property bool _mapped: true

    // Whether the surface should be on screen. Kept as an IMPERATIVE flag —
    // set true when opening, cleared a slide-duration after closing (hideTimer)
    // — rather than derived from card.x / the slide animation. `visible` gates
    // layer-surface mapping, and mapping perturbs the card's geometry/animation
    // state, so deriving `visible` from either formed a binding loop on the
    // top-anchored stackables (gpu/cpu/eth).
    property bool _visSurface: false

    signal opened()

    // Combined hover over the card OR the pin indicator. Driving open/close
    // off the OR (rather than each MouseArea's own enter/exit) means the
    // card->pin handoff never momentarily reads as "left the popup", which
    // was causing the slide-out/in flicker while hovering the pin.
    readonly property bool cardHovered: cardMa.containsMouse || pinMa.containsMouse
    onCardHoveredChanged: {
        if (pinnedOpen) return;
        if (cardHovered) show();
        else closeTimer.restart();
    }

    // stackable transients (cpu/gpu/eth) sit above the highest obstacle below
    // them (the open disk panel and/or a pinned stackable sibling); -1 = none.
    readonly property real obstacleTop: (aboveDiskWhenPinned && !pinnedOpen) ? Popups.stackObstacleTop(root) : -1
    readonly property bool stackAbove: obstacleTop >= 0
    readonly property bool tiled: pinnedOpen && !pinInPlace       // bottom widget row
    readonly property bool frozenTop: pinnedOpen && pinInPlace    // in-place, tracks obstacle
    readonly property bool topAnchored: stackAbove || frozenTop || (!pinnedOpen && anchorCenterY >= 0)

    // Top position when top-anchored (transient stacking OR pinned in place):
    // just above the obstacle chain below us, else centered on our bar module,
    // else the top gap. Reactive on Popups state + implicitHeight, so it moves
    // as the obstacle chain shifts.
    readonly property real _topPos: {
        if (aboveDiskWhenPinned) {
            const o = Popups.stackObstacleTop(root);
            if (o >= 0) return Math.max(Theme.gap, Math.round(o - Theme.gap - implicitHeight));
        }
        if (anchorCenterY >= 0)
            return Math.max(Theme.gap, Math.round(anchorCenterY - implicitHeight / 2));
        return Theme.gap;
    }

    visible: _mapped && _visSurface
    color: "transparent"

    anchors {
        right: true
        top: root.topAnchored
        bottom: !root.topAnchored
    }
    margins {
        // tiled widgets tile right-to-left (reference pinned.length so the
        // offset recomputes when the pinned set changes)
        right: Theme.gap + ((root.tiled && Popups.pinned.length >= 0) ? Popups.offsetFor(root) : 0)
        top: root.topAnchored ? root._topPos : 0
        bottom: root.topAnchored ? 0 : Theme.gap
    }
    exclusiveZone: 0

    // pinned widgets live on the desktop, behind windows
    WlrLayershell.layer: root.pinnedOpen ? WlrLayer.Bottom : WlrLayer.Overlay
    WlrLayershell.namespace: popupNamespace

    onPinnedOpenChanged: {
        if (pinnedOpen) {
            if (pinInPlace) Popups.registerStack(root, true);
            else Popups.pin(root);
            closeTimer.stop(); pendTimer.stop(); hideTimer.stop();
            wantOpen = true; open = true;
            _visSurface = true;
            // pinning opens the popup directly, bypassing show()/reallyOpen() —
            // so fire opened() here too, or onOpened work never runs on a
            // pin/reveal (e.g. Calendar.refresh(), leaving it a blank grid).
            opened();
        } else {
            if (pinInPlace) Popups.registerStack(root, false);
            else Popups.unpin(root);
            closeTimer.restart();
        }
        // let the stackables distinguish a pinned disk (which should push them
        // up as it grows) from a merely transient disk hover
        if (isDisk) Popups.diskPinned = pinnedOpen;
        // Recreate the surface AFTER the layer binding settles (a synchronous
        // map reads the old layer). The deferred remap re-files it at the new
        // one. Only when it should be on-screen — a plain close needs no remap.
        if (open) { _mapped = false; remapTimer.restart(); }
    }

    Timer {
        id: remapTimer
        interval: 32
        onTriggered: {
            root._mapped = true;
            // once re-mapped at the new layer, let the fan reveal rise up
            if (root._fanRevealPending) {
                root._fanYAnim = true;
                root._fanY = 0;
                root._fanRevealPending = false;
            }
        }
    }

    // Reveal as part of the fan: emerge upward from the widget below rather
    // than slide in from the right. No-op if already a desktop widget (a pin
    // that was set before the reveal must stay put, not re-animate/vanish).
    function fanRevealStacked() {
        if (pinnedOpen) return;
        _fanActive = true;
        _fanYAnim = false;
        _fanY = implicitHeight + Theme.gap; // snap: tucked below our surface
        _fanRevealPending = true;           // remapTimer animates _fanY -> 0
        pinnedOpen = true;
    }
    // Reverse: sink the card back down into the widget below, then unpin.
    function fanHideStacked() {
        if (!pinnedOpen) return;
        _fanActive = true;
        _fanYAnim = true;
        _fanY = implicitHeight + Theme.gap;
        fanHideTimer.restart();
    }
    Timer {
        id: fanHideTimer
        interval: 260
        onTriggered: root.pinnedOpen = false
    }

    function hoverChanged(h) {
        if (pinnedOpen) return;
        if (h) show();
        else closeTimer.restart();
    }
    function show() {
        closeTimer.stop();
        wantOpen = true;
        if (open) return;
        const wait = Popups.claim(root);
        if (wait > 0) { pendTimer.interval = wait; pendTimer.restart(); }
        else reallyOpen();
    }
    function reallyOpen() {
        if (!wantOpen) return;
        opened();
        open = true;
        _visSurface = true; hideTimer.stop();
    }
    function dismiss() {
        if (pinnedOpen) return;
        wantOpen = false;
        open = false;
        closeTimer.stop();
        pendTimer.stop();
        hideTimer.restart();   // stay mapped through the slide-out, then unmap
    }

    // Unmap the surface a slide-duration after it closes (so the card can
    // animate off first). Only fires when genuinely closed, never when pinned.
    Timer {
        id: hideTimer
        interval: 260
        onTriggered: if (!root.open && !root.pinnedOpen) root._visSurface = false
    }

    Timer {
        id: pendTimer
        interval: 260
        onTriggered: root.reallyOpen()
    }
    Timer {
        id: closeTimer
        interval: 350
        onTriggered: {
            if (root.pinnedOpen) return;
            root.wantOpen = false;
            root.open = false;
            Popups.released(root);
            hideTimer.restart();  // keep mapped through the slide-out
            // fully closed — reset fan state so the next hover slides normally
            root._fanActive = false;
            root._fanYAnim = false;
            root._fanY = 0;
        }
    }

    Rectangle {
        id: card
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: parent.width

        readonly property real shown: 0
        // off-screen x target. Uses root.implicitWidth (a fixed per-panel
        // constant), NOT card.width — card.width is the window's mapped width,
        // which is 0 while unmapped and itself depends on `visible`, so reading
        // it here would form a visible -> width -> hidden -> x -> visible loop.
        readonly property real hidden: root.implicitWidth + Theme.gap
        x: root.open ? shown : hidden
        // horizontal slide for hover/tiled popups; suppressed during a fan
        // reveal, where the card rises vertically (transform below) instead
        Behavior on x { enabled: !root._fanActive; NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

        // vertical fan emerge/collapse (0 = in place; +height = tucked below)
        transform: Translate { y: root._fanY }

        color: Theme.bg
        // pinned widgets read as "unfocused" — inactive border colour
        border.color: root.pinnedOpen ? Theme.windowBorderInactive : Theme.windowBorder
        border.width: 0   // borderless desktop widgets (was Theme.windowBorderWidth)
        radius: Theme.windowRounding

        MouseArea {
            id: cardMa
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.NoButton
        }

        Item {
            id: contentHolder
            anchors.fill: parent
        }

        // pin indicator / toggle (top-right): just the letter "p" (accent when
        // pinned or hovered). Click to pin this popup as a desktop widget.
        Item {
            anchors { top: parent.top; right: parent.right; topMargin: 7; rightMargin: 8 }
            width: pinRow.implicitWidth
            height: pinRow.implicitHeight
            z: 10

            Row {
                id: pinRow
                PixelText {
                    text: "p"
                    color: (root.pinnedOpen || pinMa.containsMouse) ? Theme.accent : Theme.textDim
                }
            }
            MouseArea {
                id: pinMa
                anchors { fill: parent; margins: -4 }
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.pinnedOpen = !root.pinnedOpen
            }
        }
    }
}
