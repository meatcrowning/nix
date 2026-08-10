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

    // The book-only top-mirror disclosure (TopProcDrawer) used to sit here under
    // the local chart; it now lives in the dock's system-info tile, under the
    // process list, where its reveal reflows the list (TaskManagerContent.qml).

    onOpened: body.repaint()

    CpuContent {
        id: body
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: body.implicitHeight
        active: root.open
    }
}
