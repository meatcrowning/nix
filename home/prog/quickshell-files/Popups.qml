pragma Singleton
import Quickshell
import QtQuick

// Coordinator for the bar's slide-out popups (Calendar / AnalogClock /
// WeatherPanel / DiskPanel / CpuPanel / EthPanel). Only one transient popup
// is open at a time. The DiskPanel is special: while pinned (a file browser
// was opened via it, or the user pinned it) it stays open at the bottom
// z-layer, exempt from the one-at-a-time rule; the CPU/EthPanel then slide
// out ABOVE it (see SlidePopup.aboveDiskWhenPinned) instead of over it.
Singleton {
    property var current: null   // the transient (non-pinned) popup

    // DiskPanel state: pinned (browser open or manually) + its top scene-Y,
    // so cpu/eth can stack their popups above it.
    property bool diskPinned: false
    property real diskTopY: 0

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
