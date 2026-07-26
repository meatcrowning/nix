pragma Singleton
import QtQuick
import Quickshell

// The desktop's VIEW MODE and the bar's live width.
//
// Two modes:
//   "classic" — the 48px vertical bar this config has always had, with the
//               desktop widgets living on the wallpaper as pinned popups.
//   "dock"    — the bar becomes a 25-33%-of-screen panel holding the widgets
//               themselves in a grid, with the runner + task icons laid out
//               horizontally across its top.
//
// THE SWITCH IS THE DRAG HANDLE. There is no separate toggle to hunt for: you
// grab the bar's inner edge and pull. Pull the classic bar out past its own
// width + `enterFrac` of the screen and it commits to dock; push the dock panel
// in below `exitFrac` and it collapses back to classic. Everything between just
// resizes within the clamp. `enterFrac` (5%) is deliberately much smaller than
// `exitFrac` (20%): the gesture that ENTERS dock is a small deliberate tug from
// a 48px bar, while the one that LEAVES it has to be a decisive shove, or a
// user nudging the panel's width would keep falling out of the mode.
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
    readonly property real minFrac: 0.25
    readonly property real maxFrac: 0.33
    // how far past the classic bar's own width you must pull to enter dock
    readonly property real enterFrac: 0.05
    // pushing a dock panel narrower than this collapses back to classic
    readonly property real exitFrac: 0.20
    // hard floor while dragging, so the bar can never be dragged to nothing
    readonly property int dragFloor: 24

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

    // committed width — classic reads the user's bar setting (Settings > Panel),
    // dock computes from the clamped fraction. Quantizing HERE rather than at
    // commit time keeps one definition, so a hand-edited or defaulted fraction
    // lands on the same grid a dragged one does.
    readonly property int barWidth: dock
        ? quantize(screenWidth * clampFrac(SettingsStore.d.dockWidthFrac))
        : Theme.barWidth

    // ---- live drag state -------------------------------------------------
    property bool dragging: false
    property real dragWidth: 0
    readonly property int liveWidth: dragging
        ? Math.round(Math.max(dragFloor, Math.min(screenWidth * 0.45, dragWidth)))
        : barWidth

    // Would a release at width `w` leave us in dock mode? Drives the live
    // layout crossfade, so the panel visibly BECOMES the dock as you cross the
    // threshold rather than snapping into it only once you let go.
    function wouldDock(w) {
        return dock ? w >= screenWidth * exitFrac
                    : w >= Theme.barWidth + screenWidth * enterFrac;
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
    function commitDrag(w) {
        const wasDock = dock;
        const nowDock = wouldDock(w);
        if (nowDock) {
            const f = clampFrac(w / screenWidth);
            if (SettingsStore.d.dockWidthFrac !== f) SettingsStore.d.dockWidthFrac = f;
            if (!wasDock) SettingsStore.d.viewMode = "dock";
            SettingsStore.save();
        } else if (wasDock) {
            SettingsStore.d.viewMode = "classic";
            SettingsStore.save();
        }
        dragging = false;
        syncWallpaper();
    }

    function toggle() { setMode(dock ? "classic" : "dock"); syncWallpaper(); }

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
    property string _lastReserve: ""
    function syncWallpaper() {
        const edge = SettingsStore.d.barEdge === "left" ? "left" : "right";
        const px = dock ? barWidth : 0;
        const key = edge + " " + px;
        if (key === _lastReserve) return;
        _lastReserve = key;
        Quickshell.execDetached(["sh", "-c",
            "mkdir -p \"$HOME/.cache/wal\"; " +
            "printf '%s %s\\n' \"$1\" \"$2\" > \"$HOME/.cache/wal/reserve\"; " +
            "exec \"$HOME/.config/scripts/wal-set.sh\" --wallpaper-only",
            "_", edge, String(px)]);
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
    Component.onCompleted: syncWallpaper()
}
