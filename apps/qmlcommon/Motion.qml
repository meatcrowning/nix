import QtQuick

// THE desktop's motion, for the six apps. One duration, one curve, one place.
//
//     import "../../qmlcommon"
//     Motion { id: motion }
//     Behavior on slide { NumberAnimation { duration: motion.ms(motion.slideMs)
//                                           easing.type: motion.slideEasing } }
//
// docs/DESIGN.md §6.2 is a single rule for the whole desktop: everything that slides,
// grows or glides between two resting positions runs at the same duration and
// the same curve, and the reference is hyprvtb's window roll in/out. The user
// stated it as a design-language rule, not a per-widget choice:
//
//   "make the sliding animations ... match the sliding animation speed /
//    timing of the window roll in and out --- !! this is another thing that
//    should always happen when we do a new feature or program etc design
//    language"
//
// Before this file, surfer's tooltips and player's settings drawer each carried
// their own literal (220 and 200), so three of the four codebases that draw on
// this screen slid at three different speeds. This is the apps' half of the fix;
// the panel's half is `ViewMode.slideMs` in home/prog/quickshell-files.
//
// WHERE THE NUMBER COMES FROM — it is NOT a fourth hand-copy of 260. hyprvtb
// owns it, as `plugin:hyprvtb:slide_duration_ms` in hyprland.lua, and publishes
// the resolved value on every config reload as a tiny generated QML object at
// ~/.local/state/hyprvtb/DeskMotion.qml, which the Loader below reads. Retune
// the key, `hyprctl reload`, and the compositor, the panel and these apps all
// move together.
//
// WHY A LOADER AND NOT A FILE READ. Plain Qt QML has no file reader: there is no
// FileView outside Quickshell, and `XMLHttpRequest` refuses a file:// URL unless
// QML_XHR_ALLOW_FILE_READ is exported into the app — which is a blanket
// local-file-read permission, and one of these apps is a web browser. Measured
// both ways offscreen: a synchronous XHR throws "Invalid state" and an
// asynchronous one never reaches DONE, while a Loader on an absolute file: URL
// resolves immediately and reports `Loader.Error` for a missing file. That error
// state is exactly the fallback signal wanted, so the awkward-looking mechanism
// is the one that degrades correctly.
//
// It resolves ONCE, at construction. Not a limitation being glossed over: apps
// here run live source with no hot reload of any kind (apps/AGENTS.md), so
// "relaunch the app to pick the change up" is already the rule for every other
// line in this tree — and the panel, which does hot-reload, watches the JSON
// twin of this file properly.
QtObject {
    id: root

    // The canon. `slideEasing` matches the roll's LEADING beat — the one that
    // carries the visible travel, and the one an ease-out cubic describes.
    //
    // The literals are the FALLBACK, for a machine where the plugin is disabled,
    // was quarantined after a crash, or has not published yet. They must stay
    // equal to the key's default in hyprvtb/main.cpp.
    property int slideMs: styleMs > 0 ? styleMs : 260
    readonly property int slideEasing: Easing.OutCubic

    // IN A PLASMA SESSION THE WIDGET STYLE OWNS THIS INSTEAD, and it is not a
    // second opinion about the same thing — it is the only one that applies
    // there. The reference above is hyprvtb's window roll, and in a Plasma
    // session there is no hyprvtb and no roll; what the eye compares an app's
    // motion against is the real QWidget chrome around the QML, which fades at
    // the style's own duration (Oxygen: `GenericAnimationsDuration`, 150ms
    // against this desktop's 260). `DeskStyle.styleMs` is that number, 0
    // whenever no style is saying — outside Plasma, under a style other than
    // Oxygen, or with Oxygen's animations switched off (which arrives as
    // reduceMotion instead, so it is not silently ignored).
    //
    // It also has to WIN over the Loader below, not merely be preferred by it:
    // hyprvtb's published file stays on disk from the last Hyprland session, so
    // in a Plasma session that Loader loads successfully and would otherwise
    // overwrite this with a number from the other session's compositor.
    readonly property int styleMs: {
        if (typeof DeskStyle === "undefined" || !DeskStyle) return 0;
        const v = Number(DeskStyle.styleMs);
        return (isFinite(v) && v > 0) ? Math.round(v) : 0;
    }

    // The user-facing motion settings. `reduceMotion` and `animSpeed` are the
    // panel's (Settings > Appearance), and they existed for a long time driving
    // nothing at all, because every animation on the desktop carried its own
    // literal duration. They reach the apps through `DeskStyle` — the same
    // context property every app already installs for fontFamily/fontSize
    // (pylib/deskstyle.py), which reads the panel's own settings.json.
    //
    // Guarded with a typeof rather than assumed: an offscreen harness that
    // builds a component without installing DeskStyle must still get sane
    // motion rather than a ReferenceError, and older builds of the apps predate
    // those two properties existing on it.
    readonly property bool reduceMotion:
        (typeof DeskStyle !== "undefined" && DeskStyle && DeskStyle.reduceMotion === true)
    readonly property real animSpeed: {
        if (typeof DeskStyle === "undefined" || !DeskStyle) return 1.0;
        const s = Number(DeskStyle.animSpeed);
        return (isFinite(s) && s > 0) ? s : 1.0;
    }

    // EVERY duration in an app goes through here, or those two settings are
    // decorative. reduceMotion returns 0: a NumberAnimation treats that as an
    // immediate assignment, so the app still changes state, it just stops
    // travelling to get there.
    function ms(base) {
        if (root.reduceMotion) return 0;
        return Math.max(0, Math.round(base * root.animSpeed));
    }

    // Absolute and hardcoded, the same convention (and the same justification)
    // as home/prog/<app>.nix pointing at /home/lam/nix/apps/<app>/main.py: QML
    // has no getenv, and $HOME is /home/lam on both machines this repo builds.
    property Loader _pub: Loader {
        source: "file:///home/lam/.local/state/hyprvtb/DeskMotion.qml"
        asynchronous: false
        onLoaded: {
            // The style's number is authoritative where there is one; see
            // `styleMs`. Leaving the binding intact also keeps it live, so a
            // change in System Settings reaches a running app.
            if (root.styleMs > 0) return;
            // Guard the range the plugin itself clamps to. A 0 would make every
            // animation instant and read as the app being broken, and this file
            // is on disk where anything can edit it.
            const v = item ? Number(item.slideMs) : NaN;
            if (isFinite(v) && v >= 20 && v <= 4000)
                root.slideMs = Math.round(v);
        }
    }
}
