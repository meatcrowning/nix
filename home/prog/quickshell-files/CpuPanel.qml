import QtQuick
import Quickshell

// CPU-usage popup: the hover/pinned window around CpuContent.qml. The widget
// itself is that component, so the dock grid can show the same thing without a
// window at all.
SlidePopup {
    id: root

    popupNamespace: "qs-cpu"
    persistKey: "cpu"
    implicitWidth: body.implicitWidth
    implicitHeight: body.implicitHeight
    aboveDiskWhenPinned: true // stack above the disk panel while it's open
    pinInPlace: true          // pinning freezes it here, not the bottom row

    onOpened: body.repaint()

    CpuContent {
        id: body
        anchors.fill: parent
        active: root.open
    }
}
