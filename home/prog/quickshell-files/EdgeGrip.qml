import QtQuick
import Quickshell
import Quickshell.Wayland

// The panel's resize/mode-switch handle — a FULL-SCREEN surface that never
// changes size, with its input region masked down to an 8px strip that follows
// the panel's inner-edge border — including the detour out around the shortcut
// notch (docs/DESIGN.md §12.2.2: the accent "runs down the panel, out around
// the notch's three exposed sides, and back", and the handle traces the same
// line).
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

    // The shortcut notch's detour, in this surface's coordinates. Five pieces
    // tile the contour with no overlap: the panel-edge strip above and below
    // the notch, the strip down the notch's outer face, and two horizontal
    // jogs along its top and bottom edges joining them. Every piece keys off
    // notchPx/notchH, which are 0 with no notch — the jogs and the face strip
    // go zero-area and the two edge strips meet at mid-height, so the whole
    // thing degenerates to the plain full-height strip with nothing gated.
    //
    // Zeroed while the runner drawer is out: the drawer is its own Overlay
    // surface covering the notch, mapped before this one and therefore BELOW
    // it, so a face strip left in the mask would sit over the drawer's content
    // and steal its clicks.
    property bool drawerOut: false
    readonly property int notchPx: drawerOut ? 0 : ViewMode.notchPx
    readonly property int notchH: drawerOut ? 0 : ViewMode.notchH
    readonly property int notchX: barLeft ? edgeX + notchPx : edgeX - notchPx
    readonly property int notchTop: Math.round((height - notchH) / 2)
    readonly property int notchBottom: notchTop + notchH
    // The jogs span the gap between the two vertical strips, plus the corner
    // over whichever one is absent at their height — the panel-edge strip,
    // which stops at the notch.
    readonly property int jogX: barLeft ? edgeX : notchX + gripW
    readonly property int jogW: notchPx

    // The vertical span the notch WOULD occupy, centred on the surface, even
    // while it is disabled (notchH is 0 then). This is the target the RE-ENABLE
    // double-click aims at — the plain edge strip at the notch's would-be height.
    readonly property int reNotchH: NotchModel.slabH0
    readonly property int reNotchTop: Math.round((height - reNotchH) / 2)
    readonly property int reNotchBottom: reNotchTop + reNotchH

    // Input region: only the contour is clickable, so the rest of the desktop
    // is untouched by this window despite it covering the screen.
    mask: Region {
        x: root.edgeX; y: 0; width: root.gripW; height: root.notchTop
        Region {   // panel edge, below the notch
            intersection: Intersection.Combine
            x: root.edgeX; y: root.notchBottom
            width: root.gripW; height: root.height - root.notchBottom
        }
        Region {   // the notch's outer face
            intersection: Intersection.Combine
            x: root.notchX; y: root.notchTop
            width: root.gripW; height: root.notchH
        }
        Region {   // top jog
            intersection: Intersection.Combine
            x: root.jogX; y: root.notchTop
            width: root.jogW; height: root.gripW
        }
        Region {   // bottom jog
            intersection: Intersection.Combine
            x: root.jogX; y: root.notchBottom - root.gripW
            width: root.jogW; height: root.gripW
        }
    }

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

        // DOUBLE-CLICK THE NOTCH'S OUTER FACE to disable the shortcut notch —
        // the same toggle the Settings control drives (SetPgAppearance.qml's
        // `desktopIcons`, docs/DESIGN.md §12.2.2). The face is the notch's
        // leading (left) edge, the vertical strip the mask exposes at
        // `notchX`; double-clicking anywhere else on the handle does nothing,
        // so the plain resize edge keeps its bare drag.
        //
        // The single click and the drag are UNTOUCHED: a MouseArea only emits
        // doubleClicked for two quick presses with no travel, and the two
        // no-op drags those presses fire commit the same width (a click on
        // this edge is already a no-op — see commitDrag). Only when the notch
        // is actually up (`notchPx > 0`, i.e. enabled and the drawer in) is
        // there a face to hit; disabled or drawer-out, notchPx is 0 and this
        // returns. Re-enabling is via Settings, there being no notch to click.
        function onNotchFace(mx, my) {
            return root.notchPx > 0
                && mx >= root.notchX && mx < root.notchX + root.gripW
                && my >= root.notchTop && my < root.notchBottom;
        }

        // ...and the INVERSE: with the notch disabled there is no face to hit, so
        // double-clicking the plain edge strip at the span the notch would occupy
        // (reNotchTop..reNotchBottom) turns it back on — fully reversible and
        // symmetric with onNotchFace above. The mask exposes that strip
        // full-height already, so the click lands with no change to the input
        // region. Guarded so the two can never both fire: this needs the notch
        // OFF, onNotchFace needs it up. Held off while the drawer is out, matching
        // the notch-face gate (notchPx is 0 then too).
        function onNotchReenable(mx, my) {
            return !NotchModel.enabled && !root.drawerOut
                && mx >= root.edgeX && mx < root.edgeX + root.gripW
                && my >= root.reNotchTop && my < root.reNotchBottom;
        }
        onDoubleClicked: (mouse) => {
            if (!onNotchFace(mouse.x, mouse.y) && !onNotchReenable(mouse.x, mouse.y))
                return;
            SettingsStore.d.desktopIcons = !SettingsStore.d.desktopIcons;
            SettingsStore.save();
        }
    }

    // Affordance: the edge brightens under the cursor, so the handle is
    // discoverable without a permanent chrome element. Purely visual, so it can
    // safely sit at the moving edge. The same five pieces as the mask — the
    // rects tile with no overlap, because translucent siblings that overlap
    // double-blend at the corners (parent opacity is per-item, not group).
    Item {
        opacity: (ma.containsMouse || ViewMode.dragging) ? 0.25 : 0
        // Hover feedback, not a slide: 120ms is the desktop's hover/scrollbar
        // fade. It had no easing at all, i.e. Linear by default, against a house
        // style that is OutCubic almost everywhere — nothing chose that.
        Behavior on opacity { NumberAnimation { duration: ViewMode.ms(120); easing.type: ViewMode.slideEasing } }

        Rectangle {   // panel edge, above the notch
            x: root.edgeX; y: 0
            width: root.gripW; height: root.notchTop
            color: Theme.accent
        }
        Rectangle {   // panel edge, below the notch
            x: root.edgeX; y: root.notchBottom
            width: root.gripW; height: root.height - root.notchBottom
            color: Theme.accent
        }
        Rectangle {   // the notch's outer face
            x: root.notchX; y: root.notchTop
            width: root.gripW; height: root.notchH
            color: Theme.accent
        }
        Rectangle {   // top jog
            x: root.jogX; y: root.notchTop
            width: root.jogW; height: root.gripW
            color: Theme.accent
        }
        Rectangle {   // bottom jog
            x: root.jogX; y: root.notchBottom - root.gripW
            width: root.jogW; height: root.gripW
            color: Theme.accent
        }
    }
}
