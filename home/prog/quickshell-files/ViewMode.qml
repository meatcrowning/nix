pragma Singleton
import QtQuick
import Quickshell

// The desktop's VIEW MODE and the bar's live width.
//
// Two modes:
//   "classic" — the 48px vertical bar this config has always had, with the
//               desktop widgets living on the wallpaper as pinned popups.
//   "dock"    — the bar becomes a wide panel (14-33% of the screen) holding the
//               widgets themselves in a grid, with the runner + task icons laid
//               out horizontally across its top.
//
// THE SWITCH IS THE DRAG HANDLE. There is no separate toggle to hunt for: you
// grab the bar's inner edge and pull.
//
// OPENING IT HAS ONE DESTINATION. The entry drag is a gesture, not a resize:
// the bar stays at its 48px until the pull passes `enterFrac` past its own
// width, then opens in one movement at `dockPx` — the same size every time.
// Resizing is something you do once you are already in the mode, where the
// panel does track the pointer, clamped to [minFrac, maxFrac]. Dragging a dock
// panel below `exitFrac` collapses it back to classic.
//
// `exitFrac` (10%) sits well below `minFrac` (14%) on purpose: if the collapse
// threshold reached into the legal width range, the narrowest dock the user is
// allowed to choose would already be inside the "about to collapse" zone and
// the panel could never rest there.
//
// Width lives in two properties on purpose:
//   barWidth  — the COMMITTED width, what the desktop settles at.
//   liveWidth — what the bar is actually rendering at THIS frame; equals
//               barWidth except mid-drag, when it follows the pointer.
// Only barWidth feeds the persisted setting, so a drag doesn't hammer
// settings.json. The wallpaper follows liveWidth directly (WallpaperLayer.qml)
// and re-centres every frame, including mid-drag.
Singleton {
    id: root

    // ---- clamps + thresholds (fractions of the screen width) -------------
    readonly property real minFrac: 0.14
    readonly property real maxFrac: 0.33
    // how far past the classic bar's own width you must pull to enter dock
    readonly property real enterFrac: 0.05
    // pushing a dock panel narrower than this collapses back to classic. Must
    // stay clear of minFrac, or the narrowest legal dock width would already be
    // inside the collapse zone and the panel could never rest there.
    readonly property real exitFrac: 0.10

    // The screen the width fractions are measured against. Multi-monitor setups
    // size the dock off the FIRST screen rather than per-monitor: the panel is
    // one width for the whole desktop, and a per-screen dock width would make
    // the same widget grid a different number of columns on each monitor.
    readonly property real screenWidth: Quickshell.screens.length
        ? Quickshell.screens[0].width : 1920

    readonly property bool dock: SettingsStore.d.viewMode === "dock"

    function clampFrac(f) {
        const v = Number(f);
        if (!isFinite(v)) return minFrac;
        return Math.max(minFrac, Math.min(maxFrac, v));
    }

    // NOTE: dock widths used to be quantized to an 8px grid. That existed
    // ONLY because each distinct width meant a fresh ImageMagick compose and a
    // hyprpaper set, and a set re-rendered the background layer as a visible
    // flash — so it was worth snapping nearby widths together to avoid one.
    // The panel draws the wallpaper itself now (Wall.qml), a width change costs
    // a property binding, and the grid's only remaining effect would be to jump
    // the panel up to 4px away from where the drag was released. It is gone; do
    // not reintroduce it without a reason that isn't the compose cost.

    // The dock's legal width range and the two thresholds, in pixels.
    readonly property int minPx: Math.round(screenWidth * minFrac)
    readonly property int maxPx: Math.round(screenWidth * maxFrac)
    readonly property real enterPx: Theme.barWidth + screenWidth * enterFrac
    readonly property real exitPx: screenWidth * exitFrac

    // The one width the dock opens at.
    readonly property int dockPx: Math.round(screenWidth * clampFrac(SettingsStore.d.dockWidthFrac))

    // committed width — classic reads the user's bar setting (Settings > Panel),
    // dock uses the stored fraction.
    readonly property int barWidth: dock ? dockPx : Theme.barWidth

    // ---- live drag state -------------------------------------------------
    property bool dragging: false
    property real dragWidth: 0

    // THE ENTRY GESTURE HAS EXACTLY ONE TARGET WIDTH. Pulling the classic bar
    // out does not stretch it continuously — the panel stays at 48px until the
    // pull passes enterPx and then opens, in one movement, at dockPx. Resizing
    // is a thing you do once you are IN the mode, not part of getting there.
    // Same in reverse: a dock panel dragged below exitPx shows the classic width
    // immediately, so you can see the collapse coming before you let go.
    //
    // Only the in-dock resize tracks the pointer, clamped to [minPx, maxPx],
    // and it follows it pixel for pixel — see the note above about the 8px grid
    // that used to be here.
    readonly property int liveWidth: {
        if (!dragging) return barWidth;
        if (!dock) return dragWidth >= enterPx ? dockPx : Theme.barWidth;
        if (dragWidth < exitPx) return Theme.barWidth;
        return Math.round(Math.max(minPx, Math.min(maxPx, dragWidth)));
    }

    // Diagnostic trace of the last drag, read with `qs ipc call view trace`:
    // one "dragWidth,surfaceWidth,liveWidth" sample per pointer event. The
    // surface width is what the compositor actually gave us, so comparing the
    // three columns shows directly whether the edge is tracking, lagging or
    // oscillating — this is a gesture nobody can verify from a log line, and
    // it has already been mis-diagnosed twice by reasoning instead of measuring.
    //
    // A plain JS array mutated IN PLACE, never reassigned: reassigning would
    // emit a change signal and copy the array on every pointer event, which
    // would itself cost more than the thing being measured.
    property var dragTrace: []
    // The panel publishes its ACTUAL surface width here (shell.qml), which is
    // what exposed the original tracking bug: it lagged the requested width, and
    // the computed target moved with it instead of with the pointer.
    property real surfaceWidth: 0
    function traceAdd() {
        if (dragTrace.length < 500)
            dragTrace.push(Math.round(dragWidth) + ","
                           + Math.round(surfaceWidth) + "," + liveWidth);
    }

    // True while liveWidth is a SNAPPED value (the entry jump, or the preview of
    // a collapse) rather than one tracking the pointer. shell.qml animates those
    // transitions and leaves the tracked resize un-animated, because animating a
    // width that is already following the cursor is exactly what makes a drag
    // feel like it is lagging and bouncing.
    readonly property bool snapping:
        dragging && (!dock || dragWidth < exitPx)

    // Would a release at width `w` leave us in dock mode? Drives the live layout
    // crossfade, so the panel visibly BECOMES the dock as the threshold is
    // crossed rather than only once the button comes up.
    function wouldDock(w) {
        return dock ? w >= exitPx : w >= enterPx;
    }
    readonly property bool showDock: dragging ? wouldDock(dragWidth) : dock

    // ---- committing ------------------------------------------------------
    function setMode(m) {
        if (SettingsStore.d.viewMode === m) return;
        SettingsStore.d.viewMode = m;
        SettingsStore.save();
    }

    // Called on drag release. Decides mode from the released width, stores the
    // resulting fraction, and pushes windows clear if the panel grew.
    //
    // ENTERING dock deliberately does NOT take its width from the drag — it
    // keeps whatever dockPx already was. The entry gesture is a single "open it"
    // motion with one destination; letting the release width set the size would
    // reintroduce the continuous stretch it exists to avoid, and would make the
    // panel a slightly different size every time it was opened.
    function commitDrag(w) {
        const wasDock = dock;
        const nowDock = wouldDock(w);
        if (nowDock && wasDock) {
            const px = Math.round(Math.max(minPx, Math.min(maxPx, w)));
            const f = px / screenWidth;
            if (SettingsStore.d.dockWidthFrac !== f) {
                SettingsStore.d.dockWidthFrac = f;
                SettingsStore.save();
            }
        } else if (nowDock) {
            SettingsStore.d.viewMode = "dock";
            SettingsStore.save();
        } else if (wasDock) {
            SettingsStore.d.viewMode = "classic";
            SettingsStore.save();
        }
        dragging = false;
        applyReserve();
    }

    function toggle() { setMode(dock ? "classic" : "dock"); applyReserve(); }

    // ---- committing a width change --------------------------------------
    // The wallpaper needs nothing done to it here: WallpaperLayer.qml binds its
    // geometry to ViewMode.liveWidth, so the art re-centres in the remaining
    // desktop on its own, every frame, including mid-drag. That used to be an
    // ImageMagick compose plus a hyprpaper set on every committed width, which
    // is what made the background flash.
    //
    // What DOES need doing is pushing the windows, and only when the panel GREW.
    // Hyprland's exclusive zone reflows TILED windows only, and this desktop is
    // almost entirely floating (hyprvtb draws the chrome and remembers geometry
    // per class), so widening the panel would otherwise simply cover whatever
    // was on that side. Shrinking needs no equivalent: it uncovers windows, and
    // moving them "back" would fight hyprvtb's own geometry memory.
    property int _lastReservePx: -1
    function applyReserve() {
        const edge = SettingsStore.d.barEdge === "left" ? "left" : "right";
        const px = dock ? barWidth : 0;
        const grew = px > _lastReservePx && _lastReservePx >= 0;
        _lastReservePx = px;

        // Match the exclusive zone rather than the full panel width, so a pushed
        // window sits exactly where a maximized one's edge lands — one window
        // border tucked under the bar's accent strip (see shell.qml).
        if (grew)
            Quickshell.execDetached([
                Quickshell.shellDir + "/scripts/push-windows.py",
                edge, String(px - Theme.windowBorderWidth)]);
    }

    // Seed _lastReservePx without pushing anything: at startup (and on every hot
    // reload) the windows are already wherever the user left them, and a reload
    // is not a width change. The -1 sentinel above is what distinguishes "first
    // observation" from "the panel grew".
    Component.onCompleted: applyReserve()
}
