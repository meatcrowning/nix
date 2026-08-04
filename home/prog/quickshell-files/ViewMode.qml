pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

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

    // ---- slow motion, for diagnosing the settle after a release -----------
    // Multiplies the duration of EVERY animation involved in a view-mode change
    // — the bar's width settle, the wallpaper's glide, the layout crossfade, the
    // grip highlight — so a glitch that lasts a couple of frames at 1x can be
    // recorded and watched. Set at runtime with `qs ipc call view slowmo 10`,
    // back with `qs ipc call view slowmo 1`.
    //
    // Deliberately NOT persisted and NOT in SettingsStore: it is a debug knob,
    // and it resets to 1 on the next panel reload so it can't be left on by
    // accident. (SettingsStore.d.animSpeed is a different, user-facing thing.)
    property real animScale: 1.0

    // ---- ms(): THE one place a duration becomes a number ------------------
    // Every duration in the panel goes through here, and that is what makes the
    // two USER-FACING motion settings real. They were in SettingsStore and in
    // the Settings UI (Appearance > Motion) from the day they shipped and drove
    // nothing at all, because every Behavior carried its own literal — the debt
    // docs/DESIGN.md §6.2 describes. Three factors, in this order:
    //
    //   reduceMotion  — a hard off switch. Returns 0, which a NumberAnimation
    //                   treats as "assign immediately": the desktop still
    //                   changes state, it just stops travelling to get there.
    //   animSpeed     — the user's own multiplier (Settings > Appearance).
    //                   1.0 is the canon; <1 is faster, >1 slower.
    //   animScale     — the debug `slowmo` knob above, NOT persisted.
    //
    // Both settings are validated here rather than at the call site: a
    // settings.json hand-edited to `"animSpeed": 0` or to a string would
    // otherwise freeze or NaN every animation on the desktop at once.
    function ms(base) {
        if (SettingsStore.d.reduceMotion) return 0;
        const s = Number(SettingsStore.d.animSpeed);
        const f = (isFinite(s) && s > 0) ? s : 1.0;
        return Math.max(0, Math.round(base * f * animScale));
    }

    // ---- the desktop's canonical slide ------------------------------------
    // ONE duration and ONE curve for everything on this desktop that slides,
    // grows or glides between two resting positions. Take these — always
    // through ms() — and never write a duration literal into a widget.
    //
    // The numbers are not a preference, they are hyprvtb's window roll-up /
    // roll-out: the largest and most-used motion here and therefore the one
    // everything else is judged against. Its leading beat (the drawer slide,
    // the first 55%) is an ease-out cubic, which is what slideEasing matches;
    // the residual difference between the two animation systems is written out
    // in AGENTS.md, "One slide, one duration".
    //
    // IT IS NO LONGER A HAND-COPY. Until hyprvtb 2.89 the roll's timing was a
    // compiled-in `static constexpr` with nothing to read, so this was a literal
    // 260 with a comment asking whoever changed the C++ to remember this file —
    // a duplication that had already gone stale once. The plugin now owns the
    // number as `plugin:hyprvtb:slide_duration_ms` and publishes the resolved
    // value to the state file below on every config reload, so editing
    // hyprland.lua and running `hyprctl reload` retunes the compositor, this
    // panel and the six apps together, with nothing restarted.
    //
    // The literal survives as the FALLBACK, and it has to: the panel outlives
    // any single plugin instance, starts independently of it, and must still
    // draw a correct desktop if the plugin is disabled, quarantined after a
    // crash, or simply has not published yet. It must stay equal to the key's
    // default in main.cpp.
    readonly property int slideEasing: Easing.OutCubic
    property int slideMs: 260

    // Published by hyprvtb (main.cpp, vtbPublishMotion) — atomically, so this
    // reader sees a whole blob or the previous one. watchChanges is what makes
    // a `hyprctl reload` reach the panel with no polling and no process spawn;
    // a missing file is the normal state on a machine with no plugin and is not
    // an error, hence the silent onLoadFailed.
    FileView {
        id: motionFile
        path: (Quickshell.env("HOME") || "") + "/.local/state/hyprvtb/motion.json"
        watchChanges: true
        onFileChanged: reload()
        onLoadFailed: () => {}
        onLoaded: {
            try {
                const m = JSON.parse(text());
                // Guard the same range the plugin clamps to. A 0 here would
                // make every Behavior instant and look exactly like the panel
                // being broken, and this file is on disk where anything can
                // edit it.
                if (m && m.slideMs >= 20 && m.slideMs <= 4000)
                    root.slideMs = Math.round(m.slideMs);
            } catch (e) { /* half-written or hand-mangled: keep the last good */ }
        }
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

    // Diagnostic only: what each dock tile was allotted vs what its content
    // wants, published by DockTile and read back through
    // `qs ipc call live tiles`.
    //
    // IT IS A MEASURING INSTRUMENT, SO IT HAS TO BE HARDER TO POISON THAN THE
    // THING IT MEASURES. Plain last-writer-wins was not: several agents,
    // including the one that wrote this, spent a session reasoning from numbers
    // that belonged to a panel which no longer existed. Two ways it went wrong,
    // both measured rather than supposed:
    //
    // - **A RELOAD OVERLAPS TWO LIVE PANEL TREES.** Quickshell hands the
    //   outgoing window's layer surface to the incoming object, and the old tree
    //   keeps ticking — timers and all — for a while afterwards. Both trees own
    //   a full set of DockTiles reporting under the SAME keys, so the dying one
    //   could win the last write and leave its geometry here permanently: a tile
    //   whose height never changes again never corrects it. Caught with a
    //   per-tile id in the log — `tasks got=257` from a tree whose panel was
    //   583px tall, while the live tile was 397px and reporting alongside it.
    //   The overlap is BY DESIGN (it is what stops the widgets blinking on every
    //   theme change), so the tree is not the thing to fix — this channel is.
    // - **Construction and teardown both lay a tile out at a degenerate size.**
    //   Measured: `h=-87 want=-1` with a parent 185px tall in the wrong
    //   direction. Nothing true can be said about a tile that is not on screen.
    //
    // So a grid takes a GENERATION at completion and stamps every report with
    // it. A report from an older generation is dropped; a newer one wipes the
    // table first, so the instrument shows exactly one panel — the newest — and
    // never a mixture.
    property var tileInfo: ({})
    property int tileGen: 0
    property int lastGen: 0
    function nextGen() { return ++lastGen; }
    function reportTile(key, allotted, wanted, gen) {
        if (!key) return;
        if (!(allotted > 0) || !(wanted >= 0)) return;
        // A negative generation is a grid that has declared itself unfit to
        // measure — today, one on an output the user cannot see (DockGrid.qml).
        const g = gen || 0;
        if (g < 0) return;
        if (g < tileGen) return;
        if (g > tileGen) { tileGen = g; tileInfo = ({}); }
        tileInfo[key] = { a: Math.round(allotted), w: Math.round(wanted) };
    }
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
    // The shortcut notch's VISIBLE protrusion past the bar's inner edge,
    // published by DesktopNotch.qml (0 when it is off). The panel reserves it
    // along with its own width — [his] "reserve space when a window is
    // maximized or the user disables floating mode globally or per window" —
    // so a tiled or maximized window stops at the notch instead of covering it.
    // A FLOATING window still can, exactly as it can cover the bar itself.
    property int notchPx: 0
    // ...and its height, for the seam patch (NotchSeam.qml), which has to cover
    // exactly the part of a window's border the notch is beside.
    property int notchH: 0
    function applyReserve() {
        const edge = SettingsStore.d.barEdge === "left" ? "left" : "right";
        const px = dock ? barWidth + notchPx : 0;
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
    // ---- the reload settle -----------------------------------------------
    // A RELOAD MUST NOT ANIMATE. Quickshell rebuilds the whole QML tree on every
    // theme or wallpaper change, and the tree is built before the settings have
    // been read back off disk — so for the first moments of a reload every
    // consumer of this singleton sees the SHIPPED DEFAULTS: viewMode "classic",
    // dockWidthFrac 0.15. Measured on book, in dock mode at 356px, the sequence
    // is barWidth 48 -> 230 -> 356 within ~30ms of "Configuration Loaded".
    //
    // The values landing late is harmless on its own: it happens inside the load
    // pass, so nothing renders in between. What is NOT harmless is that every
    // Behavior in the tree is armed by then, so those two steps were played as
    // ANIMATIONS — the panel visibly grew from the classic bar out to the dock
    // width, the classic layout faded out behind the dock one, and the wallpaper
    // slid across the screen over 260ms. That is the "the panel fails to hot
    // reload in place" report: the desktop re-entered dock mode instead of
    // simply being in it.
    //
    // So: everything that animates a view-mode change gates its Behavior on
    // `!ViewMode.settling`. Anything that changes while this is true snaps.
    // It is deliberately a wall-clock window rather than a signal from
    // SettingsStore — the values arrive from several independent sources (the
    // settings file, Quickshell.screens, the panel's own surface size) and the
    // gate has to outlast the last of them, not the first.
    property bool settling: true
    Timer {
        id: settleTimer
        interval: 400
        running: true
        onTriggered: {
            root.settling = false;
            // Seed _lastReservePx from the SETTLED width. Done here rather than
            // at completion because at completion `dock` is still the default
            // false, which would seed 0 and make the next release look like the
            // panel had grown from nothing and push every window.
            root._lastReservePx = -1;
            root.applyReserve();
        }
    }
}
