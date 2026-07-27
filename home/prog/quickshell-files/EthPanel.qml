import QtQuick
import Quickshell

// Network-throughput popup — the window around EthContent.qml.
SlidePopup {
    id: root

    popupNamespace: "qs-eth"
    persistKey: "eth"
    implicitWidth: body.implicitWidth
    implicitHeight: body.implicitHeight
    aboveDiskWhenPinned: true // stack above the disk panel while it's open
    pinInPlace: true          // pinning freezes it here, not the bottom row

    onOpened: body.repaint()

    EthContent {
        id: body
        anchors.fill: parent
        active: root.open
    }
}
