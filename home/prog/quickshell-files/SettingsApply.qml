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
// It also owns the one hyprsunset daemon, shared by night light (temperature)
// and negative brightness (gamma) — see the block at the bottom.
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

    Component.onCompleted: { applyInput(); sunsetProbe.running = true; }

    Connections {
        target: SettingsStore.d
        function onKeyRepeatDelayChanged() { root.applyInput(); }
        function onKeyRepeatRateChanged() { root.applyInput(); }
        function onPointerSpeedChanged() { root.applyInput(); }
        function onNaturalScrollChanged() { root.applyInput(); }
        function onTapToClickChanged() { root.applyInput(); }
    }

    // ---- hyprsunset: night light + negative brightness ----
    // ONE daemon serves both (only one client can hold wlr-gamma-control), so
    // this is the single place that starts, feeds and stops it:
    //   * night light -> temperature (kelvin)
    //   * negative brightness (SysInfo.gamma < 100) -> gamma
    // It runs while either wants it and is killed as soon as neither does —
    // hyprsunset restores the normal ramp on exit, which is exactly how
    // negative brightness "turns itself off" on the way back to 0.
    //
    // Launch args set the initial state; after that changes go over
    // hyprsunset's IPC (`hyprctl hyprsunset temperature|gamma`), which is
    // instant and flicker-free — the old code could only re-apply the
    // temperature by killing and relaunching. The `pkill -x` in the launch
    // line takes over any instance started outside the panel (e.g. by hand),
    // rather than starting a second one that can't grab the gamma control.
    //
    // The daemon is launched DETACHED and tracked by a pgrep probe rather than
    // being a child Process, so it OUTLIVES a panel reload: a theme change
    // rebuilds this whole tree, and a child would have been killed with it —
    // restoring the ramp and throwing the screen back to full brightness for
    // the half-second until we relaunched. Now a reload just finds the daemon
    // already up and pushes the (persisted) values at it, so nothing flickers.
    property bool sunsetWanted: SettingsStore.d.nightLight || SysInfo.gamma < 100
    readonly property int sunsetTemp: SettingsStore.d.nightLight ? SettingsStore.d.nightTemp : 6000
    readonly property int sunsetGamma: SysInfo.gamma

    // Is a hyprsunset believed to be running, and is it one we drive? We only
    // ever kill a daemon we launched or adopted — an instance someone started
    // by hand while the panel wanted nothing from it is left alone.
    property bool _sunsetUp: false
    property bool _sunsetOurs: false
    property bool _sunsetProbed: false

    Process {
        id: sunsetProbe
        command: ["pgrep", "-x", "hyprsunset"]
        onExited: (code) => {
            root._sunsetUp = (code === 0);
            root._sunsetProbed = true;
            root.syncSunset();
        }
    }

    function syncSunset() {
        // Until the probe has answered we don't know what's out there; it
        // calls back into here the moment it does.
        if (!root._sunsetProbed) return;
        if (!root.sunsetWanted) {
            if (root._sunsetUp && root._sunsetOurs)
                Quickshell.execDetached(["pkill", "-x", "hyprsunset"]);
            root._sunsetUp = false;
            root._sunsetOurs = false;
            sunsetSettle.stop();
            return;
        }
        root._sunsetOurs = true;
        if (!root._sunsetUp) {
            Quickshell.execDetached(["sh", "-c",
                "pkill -x hyprsunset; sleep 0.3; exec hyprsunset -t "
                + root.sunsetTemp + " -g " + root.sunsetGamma]);
            root._sunsetUp = true;
        } else {
            pushSunset();
        }
        // The daemon isn't listening during that 0.3s handover, and repeated
        // brightness keys fire far faster than that, so re-assert the final
        // values once the dust settles.
        sunsetSettle.restart();
    }

    function pushSunset() {
        Quickshell.execDetached(["hyprctl", "hyprsunset", "temperature", String(root.sunsetTemp)]);
        Quickshell.execDetached(["hyprctl", "hyprsunset", "gamma", String(root.sunsetGamma)]);
    }

    Timer {
        id: sunsetSettle
        interval: 450
        onTriggered: if (root.sunsetWanted && root._sunsetUp) root.pushSunset()
    }

    onSunsetWantedChanged: syncSunset()
    onSunsetTempChanged: if (sunsetWanted) syncSunset()
    onSunsetGammaChanged: if (sunsetWanted) syncSunset()
}
