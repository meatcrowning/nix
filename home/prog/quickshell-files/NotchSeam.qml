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
    // TWO ranges, and the difference between them is the whole trick.
    //
    // shell.qml now reserves a chrome inset less, so a flush window's INK ends
    // exactly on the notch's inner edge and its border sits inside the notch's
    // gap. What has to be erased is therefore only what lies BEYOND that ink:
    // the window's empty chrome margin and its border. Erasing from the notch's
    // outer edge instead would paint over the last pixels of hyprvtb's own
    // buttons.
    //
    // The outline pieces reach further, from the notch's outer edge, because
    // the window covers that stretch of the notch's top and bottom borders and
    // something has to draw them: over the corner rows the panel's line wins.
    readonly property int eraseX0: Theme.windowBorderWidth
    readonly property int eraseW: NotchModel.chromeInset + 1
    readonly property int lineWidth: Theme.windowBorderWidth
                                     + NotchModel.chromeInset + 1

    // The notch's outer face, in this screen's coordinates and then in the
    // compositor's (which is what WinState's frames are in).
    readonly property int edgeFromSide: ViewMode.liveWidth + ViewMode.notchPx
    readonly property real faceX: barLeft
        ? modelData.x + edgeFromSide
        : modelData.x + modelData.width - edgeFromSide
    // Where a window's frame edge lands when the compositor lays it against the
    // reserved area: a border plus a chrome inset PAST the notch's face, both of
    // which shell.qml declines to reserve (see its exclusiveZone).
    readonly property int frameOffset: Theme.windowBorderWidth + NotchModel.chromeInset
    readonly property real boundaryX: faceX + (barLeft ? -frameOffset : frameOffset)

    // The SCREEN's height, not this surface's: `height` is only meaningful once
    // the window exists, and the window only exists while `touching` — which is
    // computed from this. A circular dependency that silently evaluated to the
    // default 100px surface and put the notch's span off the top of the screen.
    readonly property int notchTop: Math.round((modelData.height - ViewMode.notchH) / 2)
    readonly property int notchBottom: notchTop + ViewMode.notchH

    // Is a window flush with that face, over the notch's whole height?
    //
    // TWO answers, because the sturdy one does not cover every case. A MAXIMIZED
    // window is laid out against the reserved area by definition — no measuring,
    // no assumption about how much chrome hangs off its right side, and it is
    // the case he asked for. Anything else has to be measured, and that
    // measurement leans on hyprvtb's titlebar being the window's right-hand
    // chrome; a window without it reads 64px too wide and simply never matches,
    // which is a miss rather than a false positive.
    //
    // 3px of slack on the measured one: the reserve is computed in logical
    // pixels from a width that is itself a rounded fraction of the screen, so
    // demanding equality would make this flicker with the panel width.
    readonly property bool touching: {
        if (ViewMode.notchH <= 0 || !NotchModel.shown)
            return false;
        const fs = WinState.frames || [];
        const top = modelData.y + notchTop;
        const bottom = modelData.y + notchBottom;
        for (let i = 0; i < fs.length; i++) {
            const f = fs[i];
            if (f.mon !== modelData.name)
                continue;
            if (f.max)
                return true;
            const edge = barLeft ? f.l : f.r;
            if (Math.abs(edge - boundaryX) <= 3 && f.t <= top && f.b >= bottom)
                return true;
        }
        return false;
    }

    visible: touching
    implicitWidth: edgeFromSide + lineWidth + 2


    // The notch's face in this surface's coordinates. Everything below is drawn
    // from here, so the three pieces cannot slip against each other.
    readonly property int faceLocal: barLeft ? edgeFromSide : width - edgeFromSide

    Rectangle {
        // The bar's background — the colour on BOTH sides of the seam, since
        // the window's chrome there is hyprvtb's titlebar (drawn in the same
        // Theme.bg) and the notch's inside is the bar body.
        x: root.barLeft ? root.faceLocal - root.eraseX0 - root.eraseW
                        : root.faceLocal + root.eraseX0
        y: root.notchTop + Theme.windowBorderWidth
        width: root.eraseW
        height: ViewMode.notchH - 2 * Theme.windowBorderWidth
        color: Theme.bg
    }

    // ...and the outline REDRAWN across the stretch of it the window covers,
    // from the same numbers as the erasure between them. Without this the
    // window's border nicks the notch's top and bottom lines where it crosses
    // them, and the corner reads as two lines meeting rather than turning.
    Repeater {
        model: 2
        Rectangle {
            required property int index
            x: root.barLeft ? root.faceLocal - root.lineWidth : root.faceLocal
            y: index === 0 ? root.notchTop
                           : root.notchBottom - Theme.windowBorderWidth
            width: root.lineWidth
            height: Theme.windowBorderWidth
            color: Theme.accent
        }
    }
}
