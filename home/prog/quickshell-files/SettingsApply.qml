import QtQuick
import Quickshell
import Quickshell.Io

// Applies the settings that live OUTSIDE Quickshell's own surfaces — Hyprland
// input (keyboard repeat, pointer sensitivity, scroll, tap-to-click) and the
// night-light colour filter. Instantiated once by shell.qml.
//
// Input is (re)applied at every startup AND whenever a value changes, via
// `hyprctl eval hl.config(...)` — the exact live-config path wal-set.sh uses for
// colours. settings.json is the source of truth, re-applied on each login, so it
// survives reboots without editing hyprland.lua. NOTE: pointerSpeed sets the
// GLOBAL input.sensitivity; a per-device override in hyprland.lua (e.g. the
// trackball) still wins for that device.
//
// Night light runs `hyprsunset -t <kelvin>` while enabled and is killed when
// disabled (hyprsunset restores the normal gamma on exit).
Item {
    id: root

    function _b(x) { return x ? "true" : "false"; }

    function applyInput() {
        const d = SettingsStore.d;
        const lua = "hl.config({input = { "
            + "repeat_delay = " + Math.round(d.keyRepeatDelay) + ", "
            + "repeat_rate = " + Math.round(d.keyRepeatRate) + ", "
            + "sensitivity = " + d.pointerSpeed + ", "
            + "natural_scroll = " + _b(d.naturalScroll) + ", "
            + "touchpad = { natural_scroll = " + _b(d.naturalScroll)
            + ", [\"tap-to-click\"] = " + _b(d.tapToClick) + " } "
            + "}})";
        Quickshell.execDetached(["hyprctl", "eval", lua]);
    }

    Component.onCompleted: applyInput()

    Connections {
        target: SettingsStore.d
        function onKeyRepeatDelayChanged() { root.applyInput(); }
        function onKeyRepeatRateChanged() { root.applyInput(); }
        function onPointerSpeedChanged() { root.applyInput(); }
        function onNaturalScrollChanged() { root.applyInput(); }
        function onTapToClickChanged() { root.applyInput(); }
    }

    // ---- night light (hyprsunset) ----
    Process {
        id: sunset
        running: SettingsStore.d.nightLight
        command: ["hyprsunset", "-t", String(SettingsStore.d.nightTemp)]
    }
    // hyprsunset takes its temperature as a launch arg and doesn't re-read it, so
    // when the temperature changes while it's on, cycle it (kill + relaunch a
    // tick later so the old instance has released before the new one starts).
    Timer { id: sunsetRestart; interval: 60; onTriggered: sunset.running = true }
    Connections {
        target: SettingsStore.d
        function onNightTempChanged() {
            if (SettingsStore.d.nightLight) { sunset.running = false; sunsetRestart.restart(); }
        }
    }
}
