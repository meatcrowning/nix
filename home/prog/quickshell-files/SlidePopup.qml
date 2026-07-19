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
    property real _pinnedTop: -1

    signal opened()

    // stack above the disk panel only while it's actually open (and we're not
    // already pinned)
    readonly property bool aboveDisk: aboveDiskWhenPinned && Popups.diskOpen && !pinnedOpen
    readonly property bool tiled: pinnedOpen && !pinInPlace       // bottom widget row
    readonly property bool frozenTop: pinnedOpen && pinInPlace    // stay where pinned
    readonly property bool topAnchored: aboveDisk || frozenTop || (!pinnedOpen && anchorCenterY >= 0)

    // top position when we're top-anchored but NOT frozen
    function _liveTop() {
        if (aboveDiskWhenPinned && Popups.diskOpen)
            return Math.max(Theme.gap, Math.round(Popups.diskTopY - Theme.gap - implicitHeight));
        if (anchorCenterY >= 0)
            return Math.max(Theme.gap, Math.round(anchorCenterY - implicitHeight / 2));
        return Theme.gap;
    }

    visible: open || card.x < card.hidden - 1
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
        top: root.frozenTop ? root._pinnedTop : (root.topAnchored ? root._liveTop() : 0)
        bottom: root.topAnchored ? 0 : Theme.gap
    }
    exclusiveZone: 0

    // pinned widgets live on the desktop, behind windows
    WlrLayershell.layer: root.pinnedOpen ? WlrLayer.Bottom : WlrLayer.Overlay
    WlrLayershell.namespace: popupNamespace

    onPinnedOpenChanged: {
        if (pinnedOpen) {
            if (pinInPlace) { _pinnedTop = _liveTop(); Popups.released(root); }
            else Popups.pin(root);
            closeTimer.stop(); pendTimer.stop();
            wantOpen = true; open = true;
        } else {
            _pinnedTop = -1;
            if (!pinInPlace) Popups.unpin(root);
            closeTimer.restart();
        }
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
        // pinned widgets read as "unfocused" — inactive border colour
        border.color: root.pinnedOpen ? Theme.windowBorderInactive : Theme.windowBorder
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

        // pin indicator / toggle (top-right): a dot + "pn". Dot filled when
        // pinned; click to pin this popup as a desktop widget (or unpin it).
        Item {
            anchors { top: parent.top; right: parent.right; topMargin: 7; rightMargin: 8 }
            width: pinRow.implicitWidth
            height: pinRow.implicitHeight
            z: 10

            Row {
                id: pinRow
                spacing: 3
                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 7
                    height: 7
                    radius: 4
                    color: root.pinnedOpen ? Theme.accent : "transparent"
                    border.color: (root.pinnedOpen || pinMa.containsMouse) ? Theme.accent : Theme.textDim
                    border.width: 1
                }
                PixelText {
                    text: "pn"
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
