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
    implicitHeight: body.implicitHeight + (mirror ? drawer.implicitHeight : 0)
    aboveDiskWhenPinned: true // stack above the disk panel while it's open
    pinInPlace: true          // pinning freezes it here, not the bottom row

    // Book-only: a disclosure that rolls out top's CPU graph beneath the local
    // one (TopProcDrawer). Gated to air because watching top from book is
    // book-specific; on top the popup is exactly what it always was.
    readonly property bool mirror: Host.name === "air"

    onOpened: body.repaint()

    CpuContent {
        id: body
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: body.implicitHeight
        active: root.open
    }
    TopProcDrawer {
        id: drawer
        visible: root.mirror
        active: root.open
        anchors { top: body.bottom; left: parent.left; right: parent.right }
    }
}
