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

    // DiskPanel: whether it's currently open (transient hover OR pinned),
    // whether it's PINNED specifically, and its top scene-Y — so the in-place
    // stackables (cpu/gpu/eth) can sit above it. diskPinned is tracked apart
    // from diskOpen so a transient disk hover doesn't shove already-pinned
    // widgets around, while a pinned disk that grows as its data loads DOES
    // push the widgets stacked above it upward (see stackObstacleTop).
    property bool diskOpen: false
    property bool diskPinned: false
    property real diskTopY: 0

    // Width reserved at the right edge for a pinned stackable FLOOR (air's cpu,
    // which sits bottom-right with eth/clock stacked above it). 0 when the floor
    // is a tiled widget already in `pinned` (top's disk) or nothing is pinned.
    property real tiledFloorWidth: 0

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
    // right-margin offset: tiled widgets sit in a FIXED left-to-right order by
    // tileRank (disk = rank 0, always rightmost), independent of pin insertion
    // order — so a widget always lands in the same slot regardless of when it
    // was pinned or revealed. A widget's offset is the summed width of every
    // pinned tiled widget ranked to its right (smaller rank).
    function offsetFor(who) {
        let x = 0;
        for (const w of pinned) {
            if (w === who) continue;
            if (w.tileRank < who.tileRank) x += w.implicitWidth + Theme.gap;
        }
        // a pinned stackable floor (air's cpu) holds the rightmost column, so
        // every tiled widget is pushed left of it
        if (tiledFloorWidth > 0) x += tiledFloorWidth + Theme.gap;
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
    // Highest obstacle the stackable `who` must sit above. Returns the min top
    // scene-Y of everything below it, or -1 if there's nothing (so it centers
    // on its module). Two regimes, so a pinned widget stays put on a transient
    // disk hover yet re-stacks when a pinned disk grows:
    //   who is TRANSIENT (not pinned): above the disk whenever it's open, and
    //     above every pinned stackable sibling.
    //   who is PINNED in place: above the disk only when the disk is itself
    //     PINNED, and above only the siblings pinned BEFORE it (a deterministic
    //     bottom-up chain: disk -> gpu -> cpu -> eth, no mutual reference).
    function stackObstacleTop(who) {
        const idx = stackPinned.indexOf(who);
        const pinnedWho = idx >= 0;
        let t = -1;
        if (pinnedWho ? diskPinned : diskOpen) t = diskTopY;
        for (let i = 0; i < stackPinned.length; i++) {
            const p = stackPinned[i];
            if (p === who) continue;
            if (pinnedWho && i > idx) continue; // only sit above earlier-pinned
            if (t < 0 || p.pinnedTopY < t) t = p.pinnedTopY;
        }
        return t;
    }
}
