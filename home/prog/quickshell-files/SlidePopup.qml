import QtQuick
import Quickshell
import Quickshell.Wayland

// Shared base for the bar's hover popups (Calendar / AnalogClock /
// WeatherPanel). All sit bottom-right, slide in from the right edge, stay
// while hovered (350ms grace so the cursor can travel from the bar into
// the card), and are mutually exclusive via the Popups coordinator — an
// open popup slides fully away before the next slides in.
//
// Subclass usage: set popupNamespace + implicitWidth/Height, put content
// as children (they land inside the card), hook onOpened for refresh work.
// The bar's hover zones call hoverChanged(bool).
PanelWindow {
    id: root

    default property alias contentData: contentHolder.data
    property string popupNamespace: "qs-popup"
    property bool open: false
    property bool wantOpen: false

    signal opened()

    visible: open || card.x < card.hidden - 1
    color: "transparent"

    anchors { bottom: true; right: true }
    margins { bottom: Theme.gap; right: Theme.gap }
    exclusiveZone: 0

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: popupNamespace

    function hoverChanged(h) {
        if (h) show();
        else closeTimer.restart();
    }

    function show() {
        closeTimer.stop();
        wantOpen = true;
        if (open) return;
        const wait = Popups.claim(root);
        if (wait > 0) {
            pendTimer.interval = wait;
            pendTimer.restart();
        } else {
            reallyOpen();
        }
    }

    function reallyOpen() {
        if (!wantOpen) return; // hover left during the wait
        opened();
        open = true;
    }

    // called by the coordinator when another popup takes the spot
    function dismiss() {
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
