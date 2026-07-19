pragma Singleton
import Quickshell
import QtQuick

// Coordinator for the bar's slide-out popups.
//
// Transient popups (hover) are mutually exclusive — one at a time. Any popup
// can be PINNED into a desktop widget (stays open, bottom z-layer). Two
// pinning styles:
//   tiled (calendar/clock/weather/disk): join a right-to-left row along the
//     bottom via offsetFor; the disk widget is always pinned rightmost.
//   in-place (cpu/eth): freeze where they were (above the disk / a pinned
//     sibling, or centered on their module) via stackObstacleTop.
Singleton {
    id: root

    property var current: null    // the transient (non-pinned) popup
    property var pinned: []        // tiled pinned widgets, in pin order
    property var stackPinned: []   // in-place pinned popups (cpu/eth)

    // DiskPanel: whether it's currently open + its top scene-Y, so cpu/eth
    // stack their popups above it while it's open.
    property bool diskOpen: false
    property real diskTopY: 0

    function claim(who) {
        if (who.pinnedOpen) return 0; // pinned widgets open independently
        if (current && current !== who && (current.open || current.wantOpen)) {
            current.dismiss();
            current = who;
            return 260;
        }
        current = who;
        return 0;
    }
    function released(who) {
        if (current === who) current = null;
    }

    // ---- tiled widgets (bottom row) ----
    function pin(who) {
        if (pinned.indexOf(who) >= 0) return;
        const p = pinned.slice();
        p.push(who);
        pinned = p;
        released(who);
    }
    function unpin(who) {
        pinned = pinned.filter(w => w !== who);
    }
    // right-margin offset: the disk widget is ALWAYS rightmost (offset 0);
    // every other tiled widget sits to its left, in pin order.
    function offsetFor(who) {
        if (who.isDisk) return 0;
        let x = 0;
        for (const w of pinned)
            if (w.isDisk) { x += w.implicitWidth + Theme.gap; break; }
        for (const w of pinned) {
            if (w === who) break;
            if (w.isDisk) continue;
            x += w.implicitWidth + Theme.gap;
        }
        return x;
    }

    // ---- in-place stackables (cpu/eth) ----
    function registerStack(who, on) {
        if (on) {
            if (stackPinned.indexOf(who) < 0) {
                const s = stackPinned.slice();
                s.push(who);
                stackPinned = s;
                released(who);
            }
        } else {
            stackPinned = stackPinned.filter(w => w !== who);
        }
    }
    // Highest obstacle a transient stackable must sit above: the disk panel
    // (if open) and any pinned stackable sibling. Returns the min top scene-Y,
    // or -1 if there's nothing to stack above (so it centers on its module).
    function stackObstacleTop(exclude) {
        let t = -1;
        if (diskOpen) t = diskTopY;
        for (const p of stackPinned) {
            if (p === exclude) continue;
            if (t < 0 || p.pinnedTopY < t) t = p.pinnedTopY;
        }
        return t;
    }
}
