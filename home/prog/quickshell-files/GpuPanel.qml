import QtQuick
import Quickshell

// GPU-usage popup — the window around GpuContent.qml.
SlidePopup {
    id: root

    popupNamespace: "qs-gpu"
    persistKey: "gpu"
    implicitWidth: body.implicitWidth
    implicitHeight: body.implicitHeight
    aboveDiskWhenPinned: true // stack above the disk panel while it's open
    pinInPlace: true          // pinning freezes it here, not the bottom row

    onOpened: body.repaint()

    GpuContent {
        id: body
        anchors.fill: parent
        active: root.open
    }
}
