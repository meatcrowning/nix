pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// The single source of truth for the settings program. Every control in the
// Settings window reads and writes SettingsStore.d.<key>; nothing keeps its own
// copy. Persisted as ~/.config/quickshell/settings.json (Quickshell.shellDir is
// the running config's directory — the same flat dir the panel lives in, so the
// main shell can later read the very same file to consume these values).
//
// Defaults are declared inline on the JsonAdapter so the on-disk schema is
// self-describing, and mirrored once in `defaults` so "restore defaults" can
// reset the live object without re-reading the file. Writes are atomic and
// debounced (save()), so dragging a slider doesn't hammer the disk.
//
// watchChanges IS on — deliberately. This singleton lives in TWO Quickshell
// instances: the Settings window (the writer) and the panel (`qs -d`, the
// reader). The panel binds widgets to SettingsStore.d.<key> (via Theme and
// friends), so when the Settings window writes settings.json the panel's
// FileView reloads and those bindings update IN PLACE — settings apply live,
// with no panel reload and therefore no flash. In the writer instance the
// self-write reloads the same values straight back: nothing calls save() on a
// programmatic adapter change, so there is no write loop.
//
// BOTH instances write, though — not just the Settings window. The panel
// persists its own live state through here (gammaLevel/brightnessHw from
// SysInfo, viewMode/dockWidthFrac from a bar drag, procSort, mediaQueueOpen,
// clockFace…). writeAdapter() serialises the WHOLE adapter, so a panel write of
// gamma made while the panel's in-memory copy of an unrelated key was stale
// used to clobber that key back to the stale value — e.g. the Settings window
// turning "no wallpaper" OFF, then the panel writing gamma a moment later and
// reverting wallpaperSolid to true, so the desktop stayed solid and the meta+w
// picker kept showing the colour-theme grid. save() therefore does a
// read-modify-write: it reloads the freshest file, re-applies only the keys
// THIS process actually changed (diffed against the last-seen disk snapshot),
// then writes. See saveTimer/onLoaded below.
Singleton {
    id: root

    // live settings object — bind controls to SettingsStore.d.<key>
    readonly property alias d: file.adapter

    // Bump whenever the schema changes so a future migration has something to
    // key off. Written into the file alongside the values.
    readonly property int schema: 1

    // Call after any edit. Debounced so a slider drag coalesces into one write.
    function save() { saveTimer.restart(); }
    // Drop unsaved edits and re-read what's on disk.
    function revert() { file.reload(); }

    // Flip light/dark polarity in ONE place, so the Settings toggle
    // (SetPgAppearance) and the Meta+D keybind (shell.qml's `theme` IPC) share
    // it and the logic is never edited twice. Enabling light forces "pure black
    // background" off: its light analogue is pure WHITE and the two extremes
    // fight, and a black-titled control is a lie on a white desktop. The write
    // is what SettingsApply watches (onLightModeChanged) to re-run wal-set.sh,
    // so both callers re-theme the whole desktop live with no panel reload.
    //
    // The dark-mode pure-black choice is REMEMBERED across the round trip:
    // captured into pureBlackBgDark on the way out to light (single writer, at
    // the transition, so pre-existing state migrates for free), restored from it
    // on the way back to dark. Without this, Meta+D into light and back left
    // pure black off even for someone who had it on. The guards fire only on a
    // genuine polarity change, so an idempotent call never clobbers the memory
    // with the forced-off value.
    function setLightMode(v) {
        if (v && !d.lightMode) {
            d.pureBlackBgDark = d.pureBlackBg;   // remember, then force off
            d.pureBlackBg = false;
        } else if (!v && d.lightMode) {
            d.pureBlackBg = d.pureBlackBgDark;   // restore the dark choice
        }
        d.lightMode = v;
        save();
    }
    function toggleLightMode() { setLightMode(!d.lightMode); }

    // Switch the desktop font, remembering the size PER FACE. Same shape as
    // the pureBlackBgDark round trip above: the outgoing family's size is
    // captured at the transition (single writer, so pre-existing state
    // migrates for free), and the incoming family restores its own last size
    // if it has one — a face tried at 12 comes back at 12 after a detour
    // through another face at 18. A never-used face keeps the current size,
    // which is the least surprising seed.
    function setFontFamily(v) {
        if (v === d.fontFamily) { return; }
        const m = JSON.parse(JSON.stringify(d.fontSizeByFamily || {}));
        m[d.fontFamily] = d.fontSize;
        d.fontSizeByFamily = m;
        if (m[v] !== undefined) d.fontSize = m[v];
        d.fontFamily = v;
        save();
    }
    // Pull the file in NOW, synchronously (blockLoading), and let the bindings
    // that depend on it re-evaluate before this call returns.
    //
    // For IMPERATIVE code in a Component.onCompleted this is mandatory, not an
    // optimisation: the tree is built from the shipped defaults, so a handler
    // that branches on a persisted value — `if (ViewMode.dock) return;` in
    // shell.qml's reload restore — reads the DEFAULT and takes the wrong branch,
    // a good 25ms before the real value lands and anything can react to it. A
    // binding merely flickers; a one-shot handler is simply wrong.
    function loadNow() { file.reload(); return file.text(); }
    // Reset every key to its shipped default, then persist.
    function restoreDefaults() {
        const def = root.defaults;
        // Copy the container-valued defaults rather than handing out the
        // literal itself (worldClocks, defaultWidgets, notifRules, notifSeen):
        // `defaults` is readonly, but the OBJECT it holds is not, and a
        // consumer that edits the value in place would rewrite the default it
        // was restored from.
        for (const k in def) {
            const v = def[k];
            file.adapter[k] = (v !== null && typeof v === "object")
                ? JSON.parse(JSON.stringify(v)) : v;
        }
        file.writeAdapter();
    }

    // Logout commands that CANNOT work, repaired to the shipped default on
    // load. A persisted setting shadows the default forever, so a machine that
    // stored one of these back when it *was* the default kept a dead logout
    // long after the default moved on — book's power menu did nothing at all
    // until 2026-08-06.
    //   - `hyprctl dispatch hl.dsp.exit()` is not even valid POSIX sh: PowerMenu
    //     runs the stored string through `sh -c`, and the bare `()` is a syntax
    //     error, so the WHOLE line — session-exit.sh included — died before
    //     anything ran. execDetached surfaces no stderr, so it read as a no-op.
    //   - `hyprctl dispatch exit` is the classic-string form this Lua-config
    //     build rejects outright.
    // Exact matches only: a command the user wrote themselves is theirs.
    readonly property var deadLogoutCmds: [
        "hyprctl dispatch hl.dsp.exit()",
        "hyprctl dispatch exit",
    ]

    // The last state we KNOW is on disk, as key -> JSON.stringify(value) (so
    // array keys like worldClocks/defaultWidgets compare by value, not by the
    // reference the adapter hands back). Refreshed on every load in
    // file.onLoaded; the diff against it is exactly the set of keys this process
    // has changed since it last saw disk — i.e. what a save must preserve while
    // adopting everyone else's changes.
    property var _savedSnap: ({})
    // Keys pending re-application after the pre-write reload lands (see onLoaded).
    property var _pendingKeys: null
    property bool _writeArmed: false
    function _snapshot() {
        const s = {};
        for (const k in root.defaults) s[k] = JSON.stringify(file.adapter[k]);
        return s;
    }

    // A debounced read-modify-write. On fire: capture the keys we changed vs the
    // last-seen disk, then reload — file.onLoaded finishes the job once the
    // freshest values are in the adapter, re-applying only our own changes on
    // top and writing that merge. This is why the panel writing gamma no longer
    // reverts a wallpaperSolid the Settings window just cleared.
    Timer {
        id: saveTimer
        interval: 300
        onTriggered: {
            const changed = {};
            for (const k in root.defaults)
                if (JSON.stringify(file.adapter[k]) !== root._savedSnap[k])
                    changed[k] = file.adapter[k];
            root._pendingKeys = changed;
            root._writeArmed = true;
            file.reload();   // async; onLoaded does the merge + writeAdapter
        }
    }

    // Read the file once more the instant this singleton is complete, so the
    // real values are on the bindings by the end of the load pass rather than a
    // turn of the event loop later. blockLoading makes it synchronous and the
    // file is tiny.
    //
    // It cannot be pulled any earlier than this. `d` is read during binding
    // evaluation, which happens BEFORE any Component.onCompleted in the tree,
    // and neither the FileView's own initial load nor a reload() forced from a
    // binding's side effect delivers the adapter's values in time — both were
    // measured, and in both the panel's first evaluation still saw viewMode
    // "classic". Every consumer of a persisted geometry value is therefore
    // built from the shipped defaults and corrected a moment later, which is
    // what ViewMode.settling exists to keep silent.
    Component.onCompleted: file.reload()

    // Cross-process live updates. watchChanges alone does NOT reliably deliver
    // external edits here: the Settings window writes atomically (temp file +
    // rename), which swaps settings.json's inode out from under the inotify
    // watch, so the panel never gets the notification and your change never
    // reaches the desktop. An explicit file.reload() DOES pick up the new
    // values (verified), so the reader polls: a few times a second, re-read the
    // file and let the bindings update. blockLoading makes each reload cheap and
    // synchronous, so an edit lands on Theme's bindings within one tick — on the
    // fly, no config reload, no flash.
    //
    // Gated on saveTimer so the WRITER (the Settings window) never reverts a
    // control mid-drag: while you are editing, a save is pending and we skip the
    // reload; the panel never has a pending save, so it always reloads. Both
    // instances run this, but only the reader ever acts on it. Also skipped
    // while a save's own reload is armed, so the poll can't consume that landing.
    Timer {
        interval: 350
        running: true
        repeat: true
        onTriggered: if (!saveTimer.running && !root._writeArmed) file.reload()
    }

    FileView {
        id: file
        path: Quickshell.shellDir + "/settings.json"
        atomicWrites: true
        watchChanges: true
        // Load synchronously. Without this the initial read is async and the
        // JsonAdapter's values don't propagate to bindings that were evaluated
        // at construction (Theme reads SettingsStore.d.* the instant the panel
        // starts) — every consumer would see the inline defaults forever, never
        // the on-disk values. blockLoading also makes the watchChanges reload
        // synchronous, so an edit in the Settings window lands on the panel's
        // bindings in the same frame. The file is tiny; the block is imperceptible.
        blockLoading: true
        printErrors: false
        // First run: no file yet — seed it with the declared defaults.
        onLoadFailed: (err) => { if (err === FileViewError.FileNotFound) file.writeAdapter(); }

        // Every completed load — the initial one, each poll reload, and the
        // reload a save() arms — passes through here. When a write is armed the
        // adapter now holds the freshest disk values, so we re-apply ONLY the
        // keys this process changed (adopting every other key another process
        // may have just written) and persist that merge. Otherwise we simply
        // record the new disk snapshot the next save() will diff against. The
        // re-apply happens in this same synchronous handler as the load, so a
        // binding never observes the momentary pure-disk state (no flicker on,
        // e.g., wallpaperSolid when the panel saves gamma).
        onLoaded: {
            // Repair a stored logout command that cannot run (deadLogoutCmds)
            // before anything reads it. Runs on every load and is a no-op once
            // the repaired value is on disk.
            const repaired = root.deadLogoutCmds.indexOf(file.adapter.cmdLogout) !== -1;
            if (repaired)
                file.adapter.cmdLogout = root.defaults.cmdLogout;

            if (root._writeArmed) {
                root._writeArmed = false;
                for (const k in root._pendingKeys) file.adapter[k] = root._pendingKeys[k];
                root._pendingKeys = null;
                root._savedSnap = root._snapshot();
                file.writeAdapter();
            } else {
                root._savedSnap = root._snapshot();
                if (repaired) file.writeAdapter();
            }
        }

        adapter: JsonAdapter {
            property int schemaVersion: 1

            // ---- Appearance ----
            property string themeMode: "auto"          // auto (wal) | manual
            property string accentOverride: "#5c9fcc"  // used when themeMode = manual
            property string fontFamily: "More Perfect DOS VGA"
            property int    fontSize: 15               // matches kitty's on-screen cell (11pt@96dpi ≈ 14.67px); see Theme.qml
            // Last-used size per font family, family -> px. Written only by
            // setFontFamily at the switch; fontSize above stays the single
            // live key every consumer reads.
            property var    fontSizeByFamily: ({})
            property int    paletteColorCount: 16      // wal quantize cluster count
            property bool   pureBlackBg: true
            // Remembers the dark-mode pure-black choice while light mode has it
            // forced off, so returning to dark restores it. Written only by
            // setLightMode at the dark->light transition; not a wal input, so
            // it is deliberately absent from SettingsApply._paletteKeys.
            property bool   pureBlackBgDark: true
            // Light vs dark polarity (wal-extract.py inverts the value ladder):
            // off = the settled black-background look; on = white bg + dark ink,
            // same wallpaper hue. Orthogonal to themeMode.
            property bool   lightMode: false
            // The wallpaper-derived multi-colour palette (§3.1.2) is always on;
            // paletteVariant styles it. (There is no one-hue toggle any more.)
            property string paletteVariant: "pastel"   // vivid | muted | pastel
            property int    windowBorderWidth: 2
            property int    windowRounding: 0
            property bool   trayTint: true
            // The shortcut notch on the panel's inner edge (DesktopNotch.qml).
            // On by default — it is the desktop's own programs, and the panel
            // is where this desktop keeps what you click.
            property bool   desktopIcons: true
            // Opacity of the window drop shadow hyprvtb draws to the bottom-left
            // of every titlebarred window. 0.6 is the shipped look; 0 = no
            // shadow. Live-applied over `hl.config` (plugin:hyprvtb:shadow_alpha)
            // by SettingsApply.qml — the native decoration.shadow stays disabled,
            // so this is the ONE shadow there is and the control cannot no-op.
            property real   shadowAlpha: 0.6
            // How the hyprvtb outer-column title runs: "vertical" = the stacked
            // column of upright letters (the shipped look), "horizontal" = the
            // whole title turned 90° clockwise (read with the head tilted
            // right). Live-applied over `hl.config` (plugin:hyprvtb:
            // title_rotated) by SettingsApply.qml, like shadowAlpha.
            property string titleOrientation: "vertical"
            // Which scrollbar the seven Qt apps draw (docs/DESIGN.md 9.2).
            // win31 | beveled | flat. The panel itself draws no scrollbar at
            // all — its one page never scrolls — so this key exists here purely
            // because settings.json is the desktop's one cross-app settings
            // channel: pylib/deskstyle.py reads it onto the DeskStyle context
            // property and apps/qmlcommon/VScroll.qml binds to it, exactly like
            // fontFamily/fontSize/reduceMotion/animSpeed.
            property string scrollbarStyle: "win31"
            // Per-wallpaper memory of the theme swatch strip (SetSwatches.qml):
            // wallpaper path (realpath'd, = Wall.path) -> cluster hexes (bare
            // rrggbb) clicked OFF for that paper. wal-extract.py drops the
            // current paper's entry from the palette derivation; switching
            // papers restores each one's own selection.
            property var    paletteDropped: ({})
            // RGB hardware (DRAM sticks + motherboard headers) follows the
            // accent on every theme change. Read by rgb-set.py itself, which
            // wal-set.sh step 6c fires detached — so turning this off leaves
            // the lights on whatever colour they last took, and turning it
            // back on takes effect at the next wallpaper/theme change. Only
            // `top` has the hardware, so the Settings row is drawn there only.
            property bool   rgbFollowTheme: true
            // Motion
            property bool   reduceMotion: false
            property real   animSpeed: 1.0             // 1.0 = the baked 220ms; <1 faster
            // Wallpaper
            property string wallpaperDir: "~/Pictures/wall"
            property string wallpaperFit: "auto"       // auto | tile | scale
            property string wallpaperSort: "name"      // name | random | mtime
            // No wallpaper image: paint Theme.bg (the wallpaper-derived theme
            // background colour) as the desktop instead. The palette still comes
            // from a wallpaper — the meta+w picker chooses which — so this only
            // changes whether the IMAGE is drawn. Honoured in WallpaperLayer.qml.
            property bool   wallpaperSolid: false

            // ---- Panel & Widgets ----
            // The desktop's view mode, and the dock panel's width as a fraction
            // of the screen. Both are normally written by dragging the bar's
            // inner edge (see ViewMode.qml) rather than from the Settings
            // window; they live here so the choice survives a logout and so the
            // panel picks up an external change live, like every other key.
            // dockWidthFrac is clamped to ViewMode.minFrac..maxFrac on read, so
            // a hand-edited out-of-range value can't produce a broken panel.
            property string viewMode: "classic"        // classic | dock
            property real   dockWidthFrac: 0.15
            // classic-mode bar width; the dock mode's comes from dockWidthFrac
            property int    barWidth: 48
            property string barEdge: "right"           // left | right
            property int    barGap: 8
            property int    barCell: 40
            property bool   taskbarClickMinimizes: true
            // Per-widget state the user sets by USING the widget rather than
            // through the Settings window — a clicked column heading, a repeat
            // toggle on a player that has no LoopStatus of its own. It lives
            // here for the same reason viewMode does: this file is the only
            // thing on this desktop that survives both a panel reload and a
            // logout, and a setting the user changed should not quietly revert.
            property string procSort: "cpu"            // cpu | mem | name | pid
            property int    mediaLocalLoop: 0          // 0 = off, 1 = repeat-track
            // The player widget's queue drawer. Here rather than in the widget
            // because the dock GRID reads it too — the drawer's rows come off
            // the forecast tile (see DockGrid).
            property bool   mediaQueueOpen: false
            // Draw the FIXED-DUTY fans in the fan card anyway. Off by default:
            // this machine's pump sits at 255/255 for ever, is not adjustable in
            // the BIOS and is inaudible, so [his] "i dont need to see it at
            // all". See Fans.qml for the rule — it hides only fans that are at
            // full AND have never once moved, so a chassis fan ramping up under
            // load is never hidden by it. There is no Settings-window control;
            // it is a hand-editable escape hatch for a board where the rule
            // guesses wrong.
            property bool   fanShowFixed: false
            property int    fanStepMs: 300
            // which widgets are pinned at login (subset of the known set)
            property var    defaultWidgets: ["clock", "weather", "disk", "media", "cpu", "gpu"]
            // Monitoring (a widget-detail sub-section of this page)
            property int    monPollSec: 2
            property int    cpuWarn: 75
            property int    cpuCrit: 90
            property int    tempWarn: 65
            property int    tempCrit: 80
            property int    diskWarn: 75
            property int    diskCrit: 90
            property int    batteryWarn: 30
            property int    batteryCrit: 15
            property string netInterface: "auto"
            property string rootMount: "/"
            property bool   smartSsdOnly: true

            // ---- Audio & Media ----
            property int    volumeStep: 5
            property string audioSink: "@DEFAULT_AUDIO_SINK@"
            // The VU meter's cava. No bar count: the meter is stereo, one
            // bucket per channel, and any other value is a frequency split
            // (VuMeter.qml). 10 is the measured tuning that has always been in
            // cava-vu.conf — the default was 20 while it was inert.
            property int    vuSmoothing: 10            // cava noise_reduction
            property int    vuFramerate: 60
            property int    mediaSpectrumBars: 16
            property bool   mediaPreferPlaying: true

            // ---- Notifications & Sounds ----
            property int    notifTimeoutMs: 5000
            property int    notifMaxVisible: 4
            property int    notifWidth: 300
            property string notifCorner: "bottom-right"
            property bool   notifImages: false
            property bool   notifActions: false
            property bool   doNotDisturb: false
            // DND that lifts on its own: epoch ms at which it expires, 0 for
            // the plain toggle above. Plasma's [DoNotDisturb] Until — a mode
            // you can leave on by accident is the one that eats a notification
            // you wanted. Notifications.qml clears it once the moment passes.
            property real   notifDndUntil: 0
            // The duration the timed DND above was armed FOR, in minutes, 0
            // for off. The instant is what the server obeys; this is what the
            // control shows, because a picker cannot display a value that
            // counts down out of its own option list. Cleared with the instant.
            property int    notifDndFor: 0
            // Plasma's WhenFullscreen: DND for as long as a fullscreen window
            // is up. (Its two siblings, WhenScreensMirrored/WhenScreenSharing,
            // are portal-level state this desktop has no reader for.)
            property bool   notifDndFullscreen: false
            // Whether urgency 2 still gets through DND. Plasma defaults this
            // OFF; ours has always let critical through and quietly reversing
            // that would lose an alert, so the default here is the behaviour
            // that already shipped.
            property bool   notifCriticalInDnd: true
            // Plasma's LowPriorityPopups: urgency 0 is a "you may care later"
            // notification, and a background sync's chatter is exactly that.
            property bool   notifLowPopup: true
            // Mute the notification SOUND without suppressing the toast
            // (Plasma's NotificationSoundsMuted). Orthogonal to soundsEnabled,
            // which is every system sound including login and volume.
            property bool   notifSoundMute: false
            // Per-app rules, Plasma's [Applications][<desktop entry>] block:
            //   key -> { popup: bool, dnd: bool, sound: bool }
            // The key is Notifications.keyFor() — the sender's desktop entry
            // when it sends one, else its lowercased app name. "@other" is the
            // rule inherited by any sender with no entry of its own. An absent
            // field means the default, so a rule only ever stores a divergence.
            property var    notifRules: ({})
            // Senders that have actually toasted, key -> display name. Plasma
            // reads its equivalent (Seen=true) out of .desktop files plus a
            // seen-list; we have no notification-capability declaration to
            // read, so the seen-list is the whole list. Written by the panel's
            // notification server, read by the Settings window's notifs page.
            property var    notifSeen: ({})
            property bool   soundsEnabled: true
            property string soundTheme: "vista"
            property string soundLogin: "Windows Logon Sound.wav"
            property string soundVolume: "Windows Ding.wav"
            property string soundNotify: "Windows Balloon.wav"
            property string soundCritical: "Windows Exclamation.wav"

            // ---- Apps & Utilities ----
            property string launcherTerminal: "kitty"
            property int    launcherMaxResults: 0      // 0 = unlimited
            property string launcherPlaceholder: "search programs"
            property bool   launcherProviderApps: true
            property string fileBrowserStart: "/home/lam"
            property bool   fileBrowserHidden: false
            property bool   fileBrowserDirsFirst: true
            property bool   fileBrowserConfirmDelete: true
            property string screenshotDir: "~/Pictures/Screenshots"
            property bool   screenshotCopy: true
            property string recordingDir: "~/Videos/Screen Recordings"
            property bool   recordingAudio: false
            property int    recordingFps: 60

            // ---- Lock & Power ----
            property bool   lockClock24h: false
            property string lockPamService: "quickshell-lock"
            property int    autoLockMin: 5             // 0 = never
            property bool   lockOnSuspend: true
            property string cmdLogout: "pkill Hyprland"   // SIGTERM the compositor; see PowerMenu.qml for why not hyprctl/loginctl
            property string cmdSleep: "systemctl suspend"
            property string cmdReboot: "systemctl reboot"
            property string cmdPoweroff: "systemctl poweroff"
            // What closing the laptop lid does: suspend | lock | blank | nothing.
            // Read by ~/.config/scripts/lid-close.sh on every lid event (so a
            // change applies at once), and drawn only on a machine with a lid —
            // book. Mechanism and the logind trade-off: home/srvs/lid.nix.
            property string lidClose: "suspend"
        
            // ---- Input & System ----
            property int    keyRepeatDelay: 300
            property int    keyRepeatRate: 40
            property real   pointerSpeed: 0.0          // -1..1 libinput accel
            property bool   naturalScroll: false
            property bool   tapToClick: true
            property bool   clock24h: false
            property bool   weekStartsMonday: false
            // How the dock's clock widget draws the time: an analog face, a
            // 5x7 dot-matrix readout, or a seven-segment one. Cycled by the
            // button in the widget's own top-right corner.
            property string clockFace: "analog"       // analog | dots | seg
            // Two decimal places, DELIBERATELY. This repo is public and a
            // shipped default is a published fact: four places is ~10m, which
            // is a house, not a city. Two is ~1km — indistinguishable to
            // open-meteo, which resolves to a forecast grid cell far coarser
            // than either. Same reason the monitor serial was redacted from
            // WinState.qml (`ee1d105`). Do not "restore precision" here; if a
            // sharper fix is ever wanted the user sets it in settings.json,
            // which is not in the repo.
            property real   weatherLat: 58.30
            property real   weatherLon: -134.42
            property string weatherPlace: "juneau"
            property string weatherUnit: "F"           // F | C
            property int    weatherRefreshMin: 20
            // world-clock zones, top-to-bottom under the analog clock popup.
            // A free-length list (Settings adds/removes rows); each entry is an
            // Olson TZ name (e.g. "Europe/London").
            property var    worldClocks: ["America/Indiana/Indianapolis", "America/New_York", "Europe/London", "Asia/Tokyo"]

            // ---- Display & Brightness ----
            property int    brightnessStep: 5
            property string brightnessBackend: "auto"  // auto | backlight | ddc
            property bool   nightLight: false
            property int    nightTemp: 4000            // kelvin
            // "Negative brightness": how far below hardware 0 the gamma may be
            // pulled (hyprsunset gamma %, 100 = off). 20 keeps the screen just
            // readable at the bottom of the range; 5 is nearly black.
            property int    gammaFloor: 20
            // Where in that negative region we currently sit (hyprsunset gamma
            // %, 100 = at or above hardware zero). This is live STATE, not a
            // preference — it lives here so the level survives a panel reload
            // (a theme change rebuilds the QML tree), which otherwise snapped
            // the screen back to full brightness. SysInfo owns the writes.
            property int    gammaLevel: 100
            // The HARDWARE half of the same range (0-100), or -1 while the
            // user has never moved brightness through the panel — then we
            // leave whatever the machine came up with alone. Live STATE like
            // gammaLevel, and stored for the same reason one level down: the
            // hardware is not a store we control. book's backlight is only
            // written back by systemd-backlight on a CLEAN shutdown, and top's
            // level lives in the monitor's own NVRAM over DDC. This file is
            // machine-local, so each host keeps its own. SysInfo owns the
            // writes and re-applies it once per session.
            property int    brightnessHw: -1
        }
    }

    // Mirror of the inline defaults, for restoreDefaults(). Keep in sync with
    // the adapter block above.
    readonly property var defaults: ({
        schemaVersion: 1,
        themeMode: "auto", accentOverride: "#5c9fcc", fontFamily: "More Perfect DOS VGA",
        fontSize: 15, fontSizeByFamily: ({}), paletteColorCount: 16, pureBlackBg: true, pureBlackBgDark: true, lightMode: false,
        paletteVariant: "pastel", windowBorderWidth: 2,
        windowRounding: 0, trayTint: true, desktopIcons: true, shadowAlpha: 0.6, titleOrientation: "vertical", scrollbarStyle: "win31",
        paletteDropped: ({}),
        rgbFollowTheme: true, reduceMotion: false, animSpeed: 1.0,
        wallpaperDir: "~/Pictures/wall", wallpaperFit: "auto", wallpaperSort: "name",
        wallpaperSolid: false,
        viewMode: "classic", dockWidthFrac: 0.15,
        barWidth: 48, barEdge: "right", barGap: 8, barCell: 40, taskbarClickMinimizes: true,
        procSort: "cpu", mediaLocalLoop: 0, mediaQueueOpen: false,
        fanShowFixed: false,
        fanStepMs: 300, defaultWidgets: ["clock", "weather", "disk", "media", "cpu", "gpu"],
        monPollSec: 2, cpuWarn: 75, cpuCrit: 90, tempWarn: 65, tempCrit: 80, diskWarn: 75,
        diskCrit: 90, batteryWarn: 30, batteryCrit: 15, netInterface: "auto", rootMount: "/",
        smartSsdOnly: true, volumeStep: 5, audioSink: "@DEFAULT_AUDIO_SINK@",
        vuSmoothing: 10, vuFramerate: 60, mediaSpectrumBars: 16, mediaPreferPlaying: true,
        notifTimeoutMs: 5000, notifMaxVisible: 4, notifWidth: 300, notifCorner: "bottom-right",
        notifImages: false, notifActions: false, doNotDisturb: false,
        notifDndUntil: 0, notifDndFor: 0, notifDndFullscreen: false, notifCriticalInDnd: true,
        notifLowPopup: true, notifSoundMute: false, notifRules: ({}), notifSeen: ({}),
        soundsEnabled: true,
        soundTheme: "vista", soundLogin: "Windows Logon Sound.wav", soundVolume: "Windows Ding.wav",
        soundNotify: "Windows Balloon.wav", soundCritical: "Windows Exclamation.wav",
        launcherTerminal: "kitty", launcherMaxResults: 0, launcherPlaceholder: "search programs",
        launcherProviderApps: true, fileBrowserStart: "/home/lam",
        fileBrowserHidden: false, fileBrowserDirsFirst: true, fileBrowserConfirmDelete: true,
        screenshotDir: "~/Pictures/Screenshots", screenshotCopy: true,
        recordingDir: "~/Videos/Screen Recordings", recordingAudio: false, recordingFps: 60,
        lockClock24h: false, lockPamService: "quickshell-lock", autoLockMin: 5, lockOnSuspend: true,
        cmdLogout: "pkill Hyprland", cmdSleep: "systemctl suspend",
        cmdReboot: "systemctl reboot", cmdPoweroff: "systemctl poweroff",
        lidClose: "suspend",
        keyRepeatDelay: 300, keyRepeatRate: 40, pointerSpeed: 0.0, naturalScroll: false,
        tapToClick: true, clock24h: false, weekStartsMonday: false, clockFace: "analog",
        weatherLat: 58.30,
        weatherLon: -134.42, weatherPlace: "juneau", weatherUnit: "F", weatherRefreshMin: 20,
        worldClocks: ["America/Indiana/Indianapolis", "America/New_York", "Europe/London", "Asia/Tokyo"],
        brightnessStep: 5, brightnessBackend: "auto", nightLight: false,
        nightTemp: 4000, gammaFloor: 20, gammaLevel: 100, brightnessHw: -1
    })
}
