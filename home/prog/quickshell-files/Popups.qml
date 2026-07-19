pragma Singleton
import Quickshell
import QtQuick

// Coordinator for the bar's slide-out popups (Calendar / AnalogClock /
// WeatherPanel — all SlidePopup instances sharing the bottom-right spot):
// only one may be open at a time. Claiming while another is open dismisses
// it and tells the claimant how long to wait so the old card slides fully
// away before the new one slides in.
Singleton {
    property var current: null

    function claim(who) {
        if (current && current !== who && (current.open || current.wantOpen)) {
            current.dismiss();
            current = who;
            return 260; // slide-out duration (220ms) + a beat
        }
        current = who;
        return 0;
    }

    function released(who) {
        if (current === who)
            current = null;
    }
}
