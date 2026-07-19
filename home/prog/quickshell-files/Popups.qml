pragma Singleton
import Quickshell
import QtQuick

// Coordinator for the bar's slide-out popups (Calendar / AnalogClock /
// WeatherPanel / DiskPanel / CpuPanel / EthPanel). Only one transient popup
// is open at a time. The DiskPanel is special: while a file browser is
// popped out it PINS open (dropping to the bottom z-layer, see SlidePopup),
// exempt from the one-at-a-time rule, and every other popup shifts left so
// its right edge meets the pinned panel's left edge.
Singleton {
    property var current: null   // the transient (non-pinned) popup

    // set by DiskPanel: its width and whether it's pinned (a browser is open)
    property bool diskPinned: false
    property real diskWidth: 0

    function claim(who) {
        // a pinned disk panel opens independently of the transient slot
        if (who.isDisk && who.pinnedOpen)
            return 0;
        if (current && current !== who && (current.open || current.wantOpen)) {
            current.dismiss();
            current = who;
            return 260; // slide-out (220ms) + a beat
        }
        current = who;
        return 0;
    }

    function released(who) {
        if (current === who)
            current = null;
    }
}
