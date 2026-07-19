pragma Singleton
import Quickshell
import QtQuick

// Coordinator for the bar's slide-out popups (Calendar / AnalogClock /
// WeatherPanel / DiskPanel / CpuPanel / EthPanel).
//
// Transient popups (hover) are mutually exclusive — one at a time. Any popup
// can also be PINNED via its pin indicator, turning it into a desktop widget:
// it stays open, drops to the bottom z-layer (behind windows), is exempt from
// the one-at-a-time rule, and joins a right-to-left row along the bottom so
// pinned widgets tile instead of overlapping.
Singleton {
    id: root

    property var current: null   // the transient (non-pinned) popup
    property var pinned: []       // pinned widgets, in pin order (for layout)

    // DiskPanel: whether it's currently open, and its top scene-Y — so cpu/eth
    // stack their transient popups above it only while it's actually open.
    property bool diskOpen: false
    property real diskTopY: 0

    function claim(who) {
        if (who.pinnedOpen) return 0; // pinned widgets open independently
        if (current && current !== who && (current.open || current.wantOpen)) {
            current.dismiss();
            current = who;
            return 260; // slide-out (220ms) + a beat
        }
        current = who;
        return 0;
    }
    function released(who) {
        if (current === who) current = null;
    }

    function pin(who) {
        if (pinned.indexOf(who) >= 0) return;
        const p = pinned.slice();
        p.push(who);
        pinned = p;
        released(who); // free the transient slot it may have held
    }
    function unpin(who) {
        pinned = pinned.filter(w => w !== who);
    }

    // right-margin offset for a pinned widget: past every widget pinned
    // before it, so they tile right-to-left along the bottom
    function offsetFor(who) {
        let x = 0;
        for (const w of pinned) {
            if (w === who) break;
            x += w.implicitWidth + Theme.gap;
        }
        return x;
    }
}
