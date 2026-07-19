import QtQuick
import Quickshell
import Quickshell.Wayland

// Shared base for the bar's hover popups. Slides in from the right edge,
// stays while hovered (350ms grace), mutually exclusive via Popups.
//
// Positioning:
//   anchorCenterY < 0  -> anchored to the bottom (clock/date popups)
//   anchorCenterY >= 0 -> vertical CENTER sits at that scene-Y, so the
//                         popup lines up with the bar module it came from
//                         (disk/cpu/eth/weather).
// When the DiskPanel is pinned (a file browser is open) every OTHER popup
// shifts left so its right edge meets the pinned panel's left edge, and the
// disk panel itself drops to the bottom z-layer and stays open.
PanelWindow {
    id: root

    default property alias contentData: contentHolder.data
    property string popupNamespace: "qs-popup"
    property bool open: false
    property bool wantOpen: false

    // vertical-centering: scene Y to center on; <0 keeps bottom anchoring
    property real anchorCenterY: -1

    // DiskPanel flags (see Popups): isDisk marks the one panel that pins;
    // pinnedOpen is driven by the browser count / manual pin.
    property bool isDisk: false
    property bool pinnedOpen: false
    // cpu/eth: when the disk panel is pinned, stack ABOVE it instead of
    // over it (their bottom edge sits just above the disk panel's top).
    property bool aboveDiskWhenPinned: false

    signal opened()

    // true when this popup should sit above the pinned disk panel
    readonly property bool stackAboveDisk: aboveDiskWhenPinned && Popups.diskPinned
    // true when the popup is top-anchored (centered on a module, or stacked
    // above the disk) vs bottom-anchored (clock/date/weather)
    readonly property bool topAnchored: stackAboveDisk || anchorCenterY >= 0

    visible: open || card.x < card.hidden - 1
    color: "transparent"

    anchors {
        right: true
        top: root.topAnchored
        bottom: !root.topAnchored
    }
    margins {
        right: Theme.gap
        top: root.stackAboveDisk
             ? Math.max(Theme.gap, Math.round(Popups.diskTopY - Theme.gap - root.implicitHeight))
             : root.anchorCenterY >= 0
               ? Math.max(Theme.gap, Math.round(root.anchorCenterY - root.implicitHeight / 2))
               : 0
        bottom: root.topAnchored ? 0 : Theme.gap
    }
    exclusiveZone: 0

    // pinned disk sits behind normal windows (the browser); everything else
    // floats on top as usual
    WlrLayershell.layer: (isDisk && pinnedOpen) ? WlrLayer.Bottom : WlrLayer.Overlay
    WlrLayershell.namespace: popupNamespace

    // pinned open: forced visible, hover no longer closes it
    onPinnedOpenChanged: {
        if (pinnedOpen) { closeTimer.stop(); pendTimer.stop(); wantOpen = true; open = true; }
        else closeTimer.restart();
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
    }

    function dismiss() {
        if (pinnedOpen) return;
        wantOpen = false;
        open = false;
        closeTimer.stop();
        pendTimer.stop();
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
        }
    }

    Rectangle {
        id: card
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: parent.width

        readonly property real shown: 0
        readonly property real hidden: width + Theme.gap
        x: root.open ? shown : hidden
        Behavior on x { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

        color: Theme.bg
        border.color: Theme.windowBorder
        border.width: Theme.windowBorderWidth
        radius: Theme.windowRounding

        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.NoButton
            onEntered: root.show()
            onExited: closeTimer.restart()
        }

        Item {
            id: contentHolder
            anchors.fill: parent
        }
    }
}
