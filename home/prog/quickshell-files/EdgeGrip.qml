import QtQuick
import Quickshell
import Quickshell.Wayland

// The panel's resize/mode-switch handle — a FULL-SCREEN surface that never
// changes size, with its input region masked down to an 8px strip over the
// panel's inner edge.
//
// WHY IT IS ITS OWN WINDOW, AND WHY IT IS FULL SCREEN. The handle lived inside
// the panel first, and the drag could not be made to track the cursor: it
// bounced, then merely felt off. Wayland delivers pointer coordinates in
// SURFACE coordinates, and resizing a layer surface is not synchronous — it
// takes a configure/ack roundtrip. So while the panel is being resized, the
// item tree the pointer is mapped through has already advanced to the requested
// width while the surface underneath has not, and every event is wrong by
// however much the surface still owes. Measured with `qs ipc call view trace`,
// the computed width moved 1:1 with the SURFACE width even while the pointer
// was nearly still — the reference frame was itself moving.
//
// No arithmetic inside a resizing surface can escape that. A surface that never
// resizes can: this one is exactly the screen, so a pointer x IS a screen x, and
// the width follows from a subtraction that cannot go stale. The panel still
// resizes live off the result — it may lag by a frame, but it is always chasing
// a correct target rather than a corrupted one.
//
// The MouseArea deliberately fills the whole window rather than sitting at the
// edge: an item positioned at the moving edge would reintroduce the same
// problem one level down (mouse.x is relative to the item, and the item moves).
// `mask` restricts input at the Wayland level instead, so the grab area tracks
// the panel edge while the coordinate system stays pinned to the screen.
PanelWindow {
    id: root
    required property var modelData
    screen: modelData

    anchors { top: true; bottom: true; left: true; right: true }
    // Reserve nothing (it covers the screen) AND ignore what everyone else
    // reserved. Without Ignore this is not actually full-screen: a surface
    // anchored to all four edges is shrunk by other surfaces' exclusive zones,
    // so it came up 1618px wide against the panel's own 302px zone. That both
    // put the grab strip in the wrong place and — far worse — made THIS window
    // resize whenever the panel did, reintroducing the moving reference frame
    // the separate window exists to escape. Verified with `hyprctl layers`:
    // qs-edge-grip must read the monitor's full width.
    // NOTE: do NOT also set exclusiveZone here. Assigning it selects the
    // "Normal" exclusion mode, which puts the shrinking back.
    exclusionMode: ExclusionMode.Ignore
    color: "transparent"

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "qs-edge-grip"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    readonly property bool barLeft: SettingsStore.d.barEdge === "left"
    readonly property int gripW: 8

    // Screen-x of the grab strip, following the panel's inner edge live.
    readonly property int edgeX: barLeft
        ? ViewMode.liveWidth - gripW
        : width - ViewMode.liveWidth

    // Input region: only the strip is clickable, so the rest of the desktop is
    // untouched by this window despite it covering the screen.
    mask: Region { x: root.edgeX; y: 0; width: root.gripW; height: root.height }

    MouseArea {
        id: ma
        anchors.fill: parent     // FIXED frame — see the note above
        hoverEnabled: true
        cursorShape: Qt.SizeHorCursor

        // Offset of the grab point within the strip, so the edge doesn't jump
        // to the cursor on press.
        property real grabOffset: 0

        // mx is a screen x: this surface is the screen and never resizes.
        function widthAt(mx) {
            return (root.barLeft ? mx : root.width - mx) + grabOffset;
        }

        onPressed: (mouse) => {
            grabOffset = 0;
            grabOffset = ViewMode.liveWidth - widthAt(mouse.x);
            ViewMode.dragWidth = ViewMode.liveWidth;
            ViewMode.dragTrace.length = 0;
            ViewMode.dragging = true;
        }

        onPositionChanged: (mouse) => {
            if (!ViewMode.dragging) return;
            ViewMode.dragWidth = widthAt(mouse.x);
            ViewMode.traceAdd();
        }

        onReleased: ViewMode.commitDrag(ViewMode.dragWidth)
        // A cancelled grab (the compositor taking the pointer, a monitor change)
        // must still settle the panel somewhere valid rather than leaving
        // `dragging` latched true forever.
        onCanceled: ViewMode.commitDrag(ViewMode.dragWidth)
    }

    // Affordance: the edge brightens under the cursor, so the handle is
    // discoverable without a permanent chrome element. Purely visual, so it can
    // safely sit at the moving edge.
    Rectangle {
        x: root.edgeX
        width: root.gripW
        height: root.height
        color: Theme.accent
        opacity: (ma.containsMouse || ViewMode.dragging) ? 0.25 : 0
        Behavior on opacity { NumberAnimation { duration: 120 } }
    }
}
