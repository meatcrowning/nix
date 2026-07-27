import QtQuick
import Quickshell

// Disk-usage popup — the window around DiskContent.qml. The drive list, SMART
// and the scripts behind them live in the Disks singleton; what remains here is
// this widget's role in the desktop layout, which the dock tile has no use for:
// it is the base other in-place stackables (gpu/cpu/eth) sit on top of, so it
// has to publish where its top edge is.
SlidePopup {
    id: root

    popupNamespace: "qs-disk"
    persistKey: "disk"
    tileRank: 0     // always rightmost in the tiled row
    implicitWidth: body.implicitWidth
    implicitHeight: body.implicitHeight

    isDisk: true

    // let cpu/eth know when we're open so they can stack above us
    onOpenChanged: Popups.diskOpen = open

    // report our top scene-Y (bottom-anchored: screen bottom minus our height)
    // so cpu/eth transient popups can stack above us
    function _reportTop() {
        const sh = screen ? screen.height : 1080;
        Popups.diskTopY = Math.max(Theme.gap, sh - Theme.gap - implicitHeight);
    }
    onImplicitHeightChanged: _reportTop()
    Component.onCompleted: _reportTop()

    DiskContent {
        id: body
        anchors.fill: parent
        active: root.open
    }
}
