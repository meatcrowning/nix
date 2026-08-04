import QtQuick
import Quickshell
import Quickshell.Wayland

// The one place the desktop paints OVER a window: the hairline seam between a
// maximized window's edge and the shortcut notch. [his] "when the window's
// right edge touches the new bar of icons, the border between the window edge
// and the icon bar (just the part the bar covers) is not shown … so that it
// looks as if the window and the bar are connected."
//
// WHAT IS THERE TO HIDE. Measured at the boundary, window flush against the
// reserved area: the window's own 2px border, then the notch's 2px accent
// border, side by side — two lines between the window's chrome and the notch's
// inside. The window's is Hyprland's, drawn by the compositor over the panel
// (the bar is a Bottom-layer surface), so the panel cannot simply not draw it,
// and dropping only the notch's own border would still leave the window's.
//
// So this is a strip of the bar's background, the notch's height and four
// logical pixels wide, on the TOP layer — the one thing here that draws above
// windows. It covers both borders and nothing else: above and below the notch
// the window keeps its border, which is exactly "just the part the bar covers".
//
// It appears ONLY while a window's frame is flush with the boundary AND spans
// the notch, which is the maximized case (a tiled window stops a gaps_out short
// and a fullscreen one covers the notch entirely, so neither matches). Nothing
// about floating or tiling changes, and when nothing is flush this surface
// paints nothing at all.
//
// It never takes input: the mask is empty, so every click goes to the window
// underneath it.
PanelWindow {
    id: root
    required property var modelData
    screen: modelData

    anchors { top: true; bottom: true; right: !barLeft; left: barLeft }
    exclusionMode: ExclusionMode.Ignore
    color: "transparent"

    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.namespace: "qs-notch-seam"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    mask: Region {}

    readonly property bool barLeft: SettingsStore.d.barEdge === "left"
    // The two borders — the window's and the notch's own — land on the same 2px
    // (shell.qml reserves one border less so they coincide instead of stacking),
    // plus a pixel of slack either side for the rounding in a reserve computed
    // from a fractional panel width. The slack falls on Theme.bg on both sides
    // anyway — hyprvtb's titlebar one way, the notch's inside the other — so it
    // cannot show.
    readonly property int patchW: Theme.windowBorderWidth + 2

    // The notch's outer face, in this screen's coordinates and then in the
    // compositor's (which is what WinState's frames are in).
    readonly property int edgeFromSide: ViewMode.liveWidth + ViewMode.notchPx
    readonly property real faceX: barLeft
        ? modelData.x + edgeFromSide
        : modelData.x + modelData.width - edgeFromSide

    // The SCREEN's height, not this surface's: `height` is only meaningful once
    // the window exists, and the window only exists while `touching` — which is
    // computed from this. A circular dependency that silently evaluated to the
    // default 100px surface and put the notch's span off the top of the screen.
    readonly property int notchTop: Math.round((modelData.height - ViewMode.notchH) / 2)
    readonly property int notchBottom: notchTop + ViewMode.notchH

    // ONE test, shared with the notch itself (NotchModel.flushOn): the seam
    // paints over the join and the notch shifts its seals for it, and the two
    // must never disagree about whether a window is there.
    readonly property bool touching: ViewMode.notchH > 0 && NotchModel.flushOn(modelData)

    visible: touching
    implicitWidth: edgeFromSide + patchW

    // The notch's outer face, in this surface's coordinates.
    readonly property int faceLocal: barLeft ? edgeFromSide : width - edgeFromSide

    Rectangle {
        // Over the notch's face and the window border that lands on it — the
        // notch's INSIDE only. Covering its full height would paint over the
        // ends of the notch's own top and bottom borders, the corner pieces
        // where its outline meets the window's, and leave two sides touching
        // with nothing in the corner.
        x: root.barLeft ? root.faceLocal - root.patchW + 1 : root.faceLocal - 1
        y: root.notchTop + Theme.windowBorderWidth
        width: root.patchW
        height: ViewMode.notchH - 2 * Theme.windowBorderWidth
        // The bar's background — the colour on BOTH sides of the seam, since
        // the window's chrome there is hyprvtb's titlebar (drawn in the same
        // Theme.bg) and the notch's inside is the bar body.
        color: Theme.bg
    }
}
