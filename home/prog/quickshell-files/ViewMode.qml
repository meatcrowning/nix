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
// Only barWidth feeds the persisted setting and the wallpaper recompose, so a
// drag doesn't hammer settings.json or spawn an ImageMagick run per frame.
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

    // Dock widths are QUANTIZED to this many pixels. Not cosmetic: the panel's
    // width is the wallpaper's reserve, and every distinct reserve is a separate
    // ImageMagick compose plus a hyprpaper re-render — and re-rendering
    // hyprpaper's background layer reads on screen as a flash. Without a step,
    // releasing the drag a few pixels off a previous width would recompose a
    // multi-megapixel image and flash the desktop for no visible gain, and the
    // wal cache would grow a file per pixel ever landed on. Snapping to 8px
    // makes nearby releases reuse the composed image and hit wal-set.sh's
    // already-current early-out instead.
    readonly property int widthStep: 8
    function quantize(px) { return Math.round(px / widthStep) * widthStep; }

    // The dock's legal width range and the two thresholds, in pixels.
    readonly property int minPx: quantize(screenWidth * minFrac)
    readonly property int maxPx: quantize(screenWidth * maxFrac)
    readonly property real enterPx: Theme.barWidth + screenWidth * enterFrac
    readonly property real exitPx: screenWidth * exitFrac

    // The one width the dock opens at — the stored fraction, quantized.
    readonly property int dockPx: quantize(screenWidth * clampFrac(SettingsStore.d.dockWidthFrac))

    // committed width — classic reads the user's bar setting (Settings > Panel),
    // dock uses the stored fraction. Quantizing in dockPx rather than at commit
    // time keeps one definition, so a hand-edited or defaulted fraction lands on
    // the same grid a dragged one does.
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
    // Only the in-dock resize tracks the pointer, clamped to [minPx, maxPx].
    //
    // It is deliberately NOT quantized here. Quantizing the LIVE width made the
    // edge advance in 8px hops instead of following the cursor, which reads as
    // the drag being coarse and unresponsive. The 8px grid only has to hold for
    // the COMMITTED width — that's what the wallpaper is composed against — so
    // quantize() belongs in commitDrag(), not on the tracked value.
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
    // resulting fraction, and re-centres the wallpaper if the reserved strip
    // actually changed.
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
            const px = Math.max(minPx, Math.min(maxPx, quantize(w)));
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

    // ---- wallpaper recentering -------------------------------------------
    // The panel covers a strip of the screen, so the wallpaper underneath must
    // be composed with the ART CENTRED IN WHAT'S LEFT rather than on the whole
    // monitor. hyprpaper has no notion of an offset, so the recentre happens
    // upstream: wal-set.sh reads ~/.cache/wal/reserve ("<edge> <px>") and
    // composes a full-screen image with the picture fitted into the visible
    // region. Reserve 0 is the classic path, byte-for-byte unchanged.
    //
    // --wallpaper-only is REQUIRED here: a full wal-set.sh run rewrites
    // Theme.qml's palette block, and Quickshell watches that file — so a plain
    // apply would reload the entire panel every time the width changed.
    //
    // Called only on a committed change (drag release / mode toggle), never
    // per drag frame: each call is an ImageMagick compose + a hyprpaper set.
    //
    // Pushing the windows rides along here because it is the same event — the
    // reserved strip changed — and it must run when the panel GROWS. Hyprland's
    // exclusive zone only reflows TILED windows, and this desktop is almost
    // entirely floating (hyprvtb draws the chrome and remembers geometry per
    // class), so without this, widening the panel simply covers whatever was on
    // that side. Shrinking needs no equivalent: it uncovers windows, and moving
    // them "back" would fight hyprvtb's own geometry memory.
    property string _lastReserve: ""
    property int _lastReservePx: 0
    function applyReserve() {
        const edge = SettingsStore.d.barEdge === "left" ? "left" : "right";
        const px = dock ? barWidth : 0;
        const key = edge + " " + px;
        if (key === _lastReserve) return;
        const grew = px > _lastReservePx;
        _lastReserve = key;
        _lastReservePx = px;

        Quickshell.execDetached(["sh", "-c",
            "mkdir -p \"$HOME/.cache/wal\"; " +
            "printf '%s %s\\n' \"$1\" \"$2\" > \"$HOME/.cache/wal/reserve\"; " +
            "exec \"$HOME/.config/scripts/wal-set.sh\" --wallpaper-only",
            "_", edge, String(px)]);

        // Match the exclusive zone rather than the full panel width, so a pushed
        // window sits exactly where a maximized one's edge lands — one window
        // border tucked under the bar's accent strip (see shell.qml).
        if (grew)
            Quickshell.execDetached([
                Quickshell.shellDir + "/scripts/push-windows.py",
                edge, String(px - Theme.windowBorderWidth)]);
    }

    // Keep the reserve file honest across a login or a hot reload: the panel can
    // come up already in dock mode (the setting is persisted) while the wallpaper
    // on screen was composed for whatever the reserve file last said — e.g. the
    // width was changed from the Settings program with the panel down.
    //
    // _lastReserve starts empty, so this DOES spawn wal-set.sh on every reload.
    // That's deliberate and cheap: the composed image is cached by
    // (wallpaper, resolution, reserve), and wal-set.sh's hyprpaper_is_current
    // guard skips the hyprpaper set entirely when nothing changed — which
    // matters, because re-setting an already-current wallpaper makes hyprpaper
    // re-render its background layer and that reads on screen as a FLASH.
    Component.onCompleted: applyReserve()
}
