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
    // Reset every key to its shipped default, then persist.
    function restoreDefaults() {
        const def = root.defaults;
        for (const k in def) file.adapter[k] = def[k];
        file.writeAdapter();
    }

    Timer {
        id: saveTimer
        interval: 300
        onTriggered: file.writeAdapter()
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
    // instances run this, but only the reader ever acts on it.
    Timer {
        interval: 350
        running: true
        repeat: true
        onTriggered: if (!saveTimer.running) file.reload()
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

        adapter: JsonAdapter {
            property int schemaVersion: 1

            // ---- Appearance ----
            property string themeMode: "auto"          // auto (wal) | manual
            property string accentOverride: "#5c9fcc"  // used when themeMode = manual
            property string fontFamily: "More Perfect DOS VGA"
            property int    fontSize: 15               // matches kitty's on-screen cell (11pt@96dpi ≈ 14.67px); see Theme.qml
            property int    paletteColorCount: 16      // wal quantize cluster count
            property bool   pureBlackBg: true
            property int    windowBorderWidth: 2
            property int    windowRounding: 0
            property bool   trayTint: true
            // Motion
            property bool   reduceMotion: false
            property real   animSpeed: 1.0             // 1.0 = the baked 220ms; <1 faster
            // Wallpaper
            property string wallpaperDir: "~/Pictures/wall"
            property string wallpaperFit: "auto"       // auto | tile | scale
            property string wallpaperSort: "name"      // name | random | mtime

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
            property int    vuBars: 2
            property int    vuSmoothing: 20            // cava noise_reduction
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
            property bool   launcherProviderCalc: false
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
            property string lidCloseAction: "suspend"  // suspend | lock | nothing

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
            property real   weatherLat: 58.3019
            property real   weatherLon: -134.4197
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
        }
    }

    // Mirror of the inline defaults, for restoreDefaults(). Keep in sync with
    // the adapter block above.
    readonly property var defaults: ({
        schemaVersion: 1,
        themeMode: "auto", accentOverride: "#5c9fcc", fontFamily: "More Perfect DOS VGA",
        fontSize: 15, paletteColorCount: 16, pureBlackBg: true, windowBorderWidth: 2,
        windowRounding: 0, trayTint: true, reduceMotion: false, animSpeed: 1.0,
        wallpaperDir: "~/Pictures/wall", wallpaperFit: "auto", wallpaperSort: "name",
        viewMode: "classic", dockWidthFrac: 0.15,
        barWidth: 48, barEdge: "right", barGap: 8, barCell: 40, taskbarClickMinimizes: true,
        procSort: "cpu", mediaLocalLoop: 0, mediaQueueOpen: false,
        fanStepMs: 300, defaultWidgets: ["clock", "weather", "disk", "media", "cpu", "gpu"],
        monPollSec: 2, cpuWarn: 75, cpuCrit: 90, tempWarn: 65, tempCrit: 80, diskWarn: 75,
        diskCrit: 90, batteryWarn: 30, batteryCrit: 15, netInterface: "auto", rootMount: "/",
        smartSsdOnly: true, volumeStep: 5, audioSink: "@DEFAULT_AUDIO_SINK@", vuBars: 2,
        vuSmoothing: 20, vuFramerate: 60, mediaSpectrumBars: 16, mediaPreferPlaying: true,
        notifTimeoutMs: 5000, notifMaxVisible: 4, notifWidth: 300, notifCorner: "bottom-right",
        notifImages: false, notifActions: false, doNotDisturb: false, soundsEnabled: true,
        soundTheme: "vista", soundLogin: "Windows Logon Sound.wav", soundVolume: "Windows Ding.wav",
        soundNotify: "Windows Balloon.wav", soundCritical: "Windows Exclamation.wav",
        launcherTerminal: "kitty", launcherMaxResults: 0, launcherPlaceholder: "search programs",
        launcherProviderApps: true, launcherProviderCalc: false, fileBrowserStart: "/home/lam",
        fileBrowserHidden: false, fileBrowserDirsFirst: true, fileBrowserConfirmDelete: true,
        screenshotDir: "~/Pictures/Screenshots", screenshotCopy: true,
        recordingDir: "~/Videos/Screen Recordings", recordingAudio: false, recordingFps: 60,
        lockClock24h: false, lockPamService: "quickshell-lock", autoLockMin: 5, lockOnSuspend: true,
        cmdLogout: "pkill Hyprland", cmdSleep: "systemctl suspend",
        cmdReboot: "systemctl reboot", cmdPoweroff: "systemctl poweroff", lidCloseAction: "suspend",
        keyRepeatDelay: 300, keyRepeatRate: 40, pointerSpeed: 0.0, naturalScroll: false,
        tapToClick: true, clock24h: false, weekStartsMonday: false, clockFace: "analog",
        weatherLat: 58.3019,
        weatherLon: -134.4197, weatherPlace: "juneau", weatherUnit: "F", weatherRefreshMin: 20,
        worldClocks: ["America/Indiana/Indianapolis", "America/New_York", "Europe/London", "Asia/Tokyo"],
        brightnessStep: 5, brightnessBackend: "auto", nightLight: false,
        nightTemp: 4000, gammaFloor: 20, gammaLevel: 100
    })
}
