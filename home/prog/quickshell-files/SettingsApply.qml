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
            // tap_to_click, NOT ["tap-to-click"]. The ini/`hyprctl getoption`
            // name is `input:touchpad:tap-to-click`, but the LUA config manager
            // takes the underscored alias and only that: the hyphenated form
            // was rejected with `unknown config key 'input.touchpad.tap-to-click'`
            // in `hyprctl configerrors` — so this whole setting was a no-op for
            // its entire life and the touchpad just ran on Hyprland's default.
            // (`getoption` normalises - and _, which is why it looked fine
            // there. Both pins carry the alias: verified live on 0.55.4 and in
            // the 0.56 binary's string table.)
            + "touchpad = { natural_scroll = " + _b(d.naturalScroll)
            + ", tap_to_click = " + _b(d.tapToClick) + " } "
            + "}})";
        Quickshell.execDetached(["hyprctl", "eval", lua]);
    }

    // The hyprvtb drop-shadow opacity (Settings > Appearance). Same live-config
    // path as the input keys: `hl.config`, NOT `hyprctl keyword` (the lua parser
    // rejects the keyword form — see wal-set.sh step 5). A config reload damages
    // every monitor, so the shadow layer repaints at the new alpha with no window
    // touched. Re-applied at startup so the pick survives a reboot without
    // editing seed-once hyprland.lua.
    function applyShadow() {
        const v = SettingsStore.d.shadowAlpha;
        const lua = "hl.config({plugin = { hyprvtb = { shadow_alpha = " + v + " } }})";
        Quickshell.execDetached(["hyprctl", "eval", lua]);
    }

    // Push the "pixel font" pick (Settings > Appearance) out beyond the panel
    // and the Qt apps: kitty, the hyprvtb titlebar and kdeglobals read the same
    // settings.json via apply-pixel-font.sh, so flipping the pick here takes
    // the whole desktop with it. Debounced — the file write is itself debounced
    // in SettingsStore, and this only acts on a real value change (see
    // onFontFamilyChanged below), but the two timers need not race.
    function applyPixelFont() { fontApply.restart(); }
    Timer {
        id: fontApply
        interval: 400
        onTriggered: {
            Quickshell.execDetached(["sh", "-c",
                'exec "$HOME/.config/scripts/apply-pixel-font.sh"']);
        }
    }

    // loadNow() first: this handler branches on persisted values (the palette
    // signature below), and a one-shot handler cannot be gated — at completion
    // the adapter still holds the shipped defaults unless the read is forced.
    Component.onCompleted: {
        SettingsStore.loadNow();
        root._paletteSig = root._sig();
        applyInput();
        applyShadow();
        sunsetProbe.running = true;
    }

    Connections {
        target: SettingsStore.d
        function onKeyRepeatDelayChanged() { root.applyInput(); }
        function onKeyRepeatRateChanged() { root.applyInput(); }
        function onPointerSpeedChanged() { root.applyInput(); }
        function onNaturalScrollChanged() { root.applyInput(); }
        function onTapToClickChanged() { root.applyInput(); }
        function onShadowAlphaChanged() { root.applyShadow(); }

        // ---- pixel-font propagation (kitty / titlebar / kdeglobals) ----
        // The panel + Qt apps read the pick live themselves; this pushes it to
        // the static surfaces. Both keys fire on a real change.
        function onFontFamilyChanged() { root.applyPixelFont(); }
        function onFontSizeChanged()   { root.applyPixelFont(); }

        // ---- palette generation ----
        // The four Appearance keys that are INPUTS to wal-extract.py. Nothing
        // in QML can apply them: the palette is derived by that script and
        // spliced into Theme.qml by wal-set.sh, so "apply" means re-running the
        // theme. wal-prepare.sh already invalidates its per-image palette cache
        // when settings.json is newer than it, so a plain re-run picks the new
        // values up. Without this the four controls only took effect at the
        // NEXT wallpaper change, which is indistinguishable from doing nothing.
        function onThemeModeChanged()         { root.reapplyTheme(); }
        function onAccentOverrideChanged()    { root.reapplyTheme(); }
        function onPaletteColorCountChanged() { root.reapplyTheme(); }
        function onPureBlackBgChanged()       { root.reapplyTheme(); }
        function onPaletteVariantChanged()    { root.reapplyTheme(); }
    }

    // Re-run the full wallpaper/theme apply. DEBOUNCED, because its last step
    // rewrites Theme.qml — which hot-reloads the whole QML tree, this object
    // included — so a slider dragged across ten values must not queue ten of
    // them. Same launch shape WallpaperPicker.qml uses (a shell, so $HOME
    // expands; Qt.resolvedUrl is unusable from a non-Singleton here).
    //
    // `_paletteSig` is what stops that reload from becoming a LOOP. A fresh
    // tree evaluates its bindings against the shipped defaults and only then
    // reads settings.json (see SettingsStore), so every non-default value
    // "changes" once per reload — and a re-apply on that would rewrite
    // Theme.qml, reload again, and never stop. So the signature of the four
    // keys is recorded at completion (after loadNow(), which is what makes the
    // real values readable there) and the timer applies only a genuine change.
    readonly property var _paletteKeys: ["themeMode", "accentOverride",
                                         "paletteColorCount", "pureBlackBg",
                                         "paletteVariant", "lightMode"]
    property string _paletteSig: ""
    function _sig() {
        const d = SettingsStore.d;
        return root._paletteKeys.map(k => String(d[k])).join("|");
    }
    function reapplyTheme() { themeApply.restart(); }
    Timer {
        id: themeApply
        interval: 400
        onTriggered: {
            const s = root._sig();
            if (s === root._paletteSig) return;
            root._paletteSig = s;
            Quickshell.execDetached(["sh", "-c",
                'exec "$HOME/.config/scripts/wal-set.sh"']);
        }
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

    // NixPath.sh on the launch line: `hyprsunset` is a NIX package and Fedora
    // ships no rpm for it, so on book — where the panel inherits the Fedora
    // session's PATH and cannot see the nix profile — `exec hyprsunset` died
    // with "not found", silently (execDetached has no exit code, and
    // `_sunsetUp` was set true on the next line). Night light AND negative
    // brightness were a no-op there for their whole life. Nothing else in this
    // chain was wrong: hyprsunset 0.4.0 binds hyprland-ctm-control-v1 v2
    // against the rpm 0.55.4 compositor, and Fedora's own hyprctl drives its
    // socket fine. See NixPath.qml. Everything else here (sh, pkill, sleep,
    // hyprctl) comes from the distro on both machines.
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
                "pkill -x hyprsunset; sleep 0.3; " + NixPath.sh
                + "exec hyprsunset -t "
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
