import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

Scope {
    id: shell

    // Toast on hot-reload, routed through our own notification server (see
    // Notifications.qml) with notify-send so it renders like any other toast.
    // These signals fire on *reloads* only, never the initial startup, so there
    // is no login spam. reloadFailed is delivered to the still-running old
    // instance (the new one never came up), so a broken edit announces itself as
    // a critical toast that — per the server's urgency-2 rule — stays until
    // clicked, with the parse error as the body.
    //
    // wal-set.sh rewrites Theme.qml in place on every wallpaper change, which
    // also triggers this same reload path. WallpaperPicker touches a marker
    // file right before running wal-set.sh; onReloadCompleted checks whether
    // that marker is fresh (an in-memory flag can't survive the reload it's
    // meant to gate — Quickshell recreates this whole object tree from source
    // on every reload, so anything set on the old tree is already gone by the
    // time this fires on the new one). Failures are never gated on it: a
    // broken edit should always announce itself regardless of what else is
    // going on.
    //
    // The check + conditional notify-send is ONE detached shell command, not
    // a Process object here awaiting a callback: onReloadCompleted fires on
    // the OLD tree in its last moments before teardown, so anything short of
    // an already-detached fire-and-forget process risks getting killed before
    // it can act on the result. The brief sleep gives Notifications.qml's own
    // NotificationServer (keepOnReload: false — it's recreated every reload
    // too) a moment to re-register on D-Bus before the toast is sent. "fresh"
    // = touched in the last 3s, generous enough to cover file-watcher
    // detection lag without leaving a crashed wal-set.sh run suppressing
    // toasts forever (the marker just goes stale and stops mattering).
    Connections {
        target: Quickshell
        function onReloadCompleted() {
            Quickshell.execDetached(["sh", "-c",
                "sleep 0.3; " +
                "f=\"$HOME/.cache/wal/.suppress-reload\"; " +
                "if [ -f \"$f\" ] && [ $(( $(date +%s) - $(stat -c %Y \"$f\" 2>/dev/null || echo 0) )) -le 3 ]; then exit 0; fi; " +
                "notify-send -a quickshell Quickshell 'config reloaded'"]);
        }
        function onReloadFailed(error) {
            Quickshell.execDetached(["notify-send", "-a", "quickshell", "-u", "critical", "Quickshell reload failed", error]);
        }
    }

    // Applies settings that live outside Quickshell's surfaces: Hyprland input
    // (key repeat, pointer, scroll, tap) and the night-light filter.
    SettingsApply {}

    // The runner overlay.
    Launcher {
        id: launcher
    }

    // The keybinding cheatsheet that drops down from the top edge.
    Cheatsheet {
        id: cheatsheet
    }

    // The secure lock screen (ext-session-lock + PAM).
    Lock {
        id: lock
    }

    // The power menu (logout/sleep/reboot/poweroff) that slides out near the
    // clock, like the OSD.
    PowerMenu {
        id: powermenu
    }

    // The wallpaper picker/setter that slides out from the right.
    WallpaperPicker {
        id: wallpaperPicker
    }

    // The Spectacle-style screenshot / screen-recording overlay (Meta+Shift+S).
    Screenshot {
        id: screenshot
    }

    // The "recording..." toast, top-right, shown while a recording is running.
    // Lives outside the overlay so it survives the overlay closing; clicking it
    // stops the recording (SIGINT -> wf-recorder finalises the file).
    RecordingToast {
        recording: screenshot.recording
        onStopRequested: screenshot.stopRecording()
    }

    // The month calendar that slides out when hovering the panel date.
    Calendar {
        id: calendar
    }

    // The analog clock that slides out when hovering the digital clock.
    AnalogClock {
        id: analogClock
        // On air the clock is the TOP of the bottom-right stack (above eth), not
        // a tiled row widget — so it stacks in place instead of tiling.
        aboveDiskWhenPinned: Host.name === "air"
        pinInPlace: Host.name === "air"
    }

    // The 7-day forecast that slides out when hovering the weather block.
    WeatherPanel {
        id: weatherPanel
        // air row, left→right: media, weather, cpu-stack. weather must rank
        // ABOVE media (lower rank = further right) so it lands right of media.
        tileRank: Host.name === "air" ? 20 : 30
    }

    // Status-metric popups: per-drive usage + SMART, CPU usage/temp history,
    // network throughput history — each opened by hovering its bar block.
    DiskPanel { id: diskPanel }
    // On air, cpu is the base of the bottom-right stack (eth, then clock, above
    // it) — it bottom-anchors to the corner where the disk sits on top.
    CpuPanel { id: cpuPanel; stackFloor: Host.name === "air" }
    GpuPanel { id: gpuPanel }
    EthPanel { id: ethPanel }

    // The MPRIS media widget — a tiled desktop widget that fans out just left
    // of the disk (i.e. between the disk and clock widgets in the row).
    MediaPanel { id: mediaPanel }

    // File-browser windows (real FloatingWindows, hyprvtb-decorated), one per
    // open entry in the Browsers registry — spawned by a drive's "open".
    Variants {
        model: Browsers.entries
        FileBrowser {
            required property var modelData
            browserId: modelData.id
            startPath: modelData.path
        }
    }

    // The "<" button at the bottom of the bar: reveal ALL popups at once as
    // desktop widgets, restoring whatever was pinned before on toggle-off.
    //
    // The reveal/hide is STAGED into a little fan rather than flipping every
    // pin at once. Reveal order (out): disk+media; then clock+gpu; then
    // weather+cpu; then calendar+eth — the tiled row fans out leftward from the
    // disk (disk rightmost, then media, then clock/weather/calendar) while the
    // stack fans upward above it. Hide runs the same stages in reverse.
    // Each stage is ~_fanStepMs after the last, so widgets cascade in/out
    // instead of popping together. Whatever was pinned BEFORE a reveal is kept
    // pinned on the following hide (_savedPins), so the toggle is lossless.
    property bool allRevealed: false
    property var _savedPins: []

    // every pinnable widget, and the two fan orders. The stack order fixes the
    // bottom-up stacking (each stackable sits above the ones pinned before it);
    // the tiled order fixes the row's left fan. Branched per host: top anchors
    // the stack on the disk (disk→gpu→cpu→eth); air has no disk — cpu is the
    // corner floor with eth then clock stacked above it, media+weather tiled left.
    readonly property var _allWidgets: Host.name === "air"
        ? [analogClock, weatherPanel, mediaPanel, cpuPanel, ethPanel]
        : [calendar, analogClock, weatherPanel, diskPanel, mediaPanel, cpuPanel, gpuPanel, ethPanel]
    readonly property var _fanOut: Host.name === "air"
        ? [[cpuPanel], [ethPanel, weatherPanel], [analogClock, mediaPanel]]
        : [[diskPanel, mediaPanel], [analogClock, gpuPanel], [weatherPanel, cpuPanel], [calendar, ethPanel]]

    // The desktop widgets fanned out at login when nothing has been saved yet
    // (first boot / cleared state). persistKeys, NOT widget refs — declarative
    // so this stays a trivial one-line edit, and a saved set (Meta+Ctrl+S writes
    // the live pins) always overrides it. Branched per host via the generated
    // Host.qml singleton (see quickshell.nix): top keeps the disk-anchored set;
    // air is the corner stack (cpu/eth/clock) plus media+weather tiled to its left.
    readonly property var _defaultWidgets: Host.name === "air"
        ? ["media", "weather", "cpu", "eth", "clock"]
        : ["clock", "weather", "disk", "media", "cpu", "gpu"]

    // one stage every _fanStepMs — set to just past a single widget's full
    // reveal (stacked = ~32ms remap + 260ms rise ≈ 292ms; tiled = 220ms) so a
    // stage finishes animating before the next one starts.
    readonly property int _fanStepMs: SettingsStore.d.fanStepMs
    property var _fanStages: []
    property int _fanIndex: 0
    property bool _fanRevealing: true

    Timer {
        id: fanTimer
        interval: shell._fanStepMs
        repeat: true
        onTriggered: shell._fanStep()
    }
    function _fanStep() {
        if (_fanIndex >= _fanStages.length) { fanTimer.stop(); return; }
        const grp = _fanStages[_fanIndex];
        for (const w of grp) {
            // in-place stackables (gpu/cpu/eth) emerge from / sink into the
            // widget below them; tiled ones (disk/clock/weather/calendar) keep
            // the plain horizontal slide via pinnedOpen.
            if (w.aboveDiskWhenPinned) {
                if (_fanRevealing) w.fanRevealStacked(); else w.fanHideStacked();
            } else {
                w.pinnedOpen = _fanRevealing;
            }
        }
        _fanIndex++;
        if (_fanIndex >= _fanStages.length) fanTimer.stop();
    }
    function _runFan(stages, revealing) {
        fanTimer.stop();
        _fanStages = stages;
        _fanRevealing = revealing;
        _fanIndex = 0;
        _fanStep();          // first stage fires immediately
        if (_fanIndex < _fanStages.length) fanTimer.start();
    }

    function toggleRevealAll() {
        if (!allRevealed) {
            _savedPins = _allWidgets.filter(p => p.pinnedOpen);
            allRevealed = true;
            _runFan(_fanOut, true);
        } else {
            allRevealed = false;
            // exact reverse of the fan-out: same stage pairing, reversed order
            // (empty stages kept so the cadence stays symmetric). Anything that
            // was pinned before the reveal is left pinned.
            const stages = _fanOut.slice().reverse()
                .map(grp => grp.filter(p => _savedPins.indexOf(p) < 0));
            _runFan(stages, false);
        }
    }

    // ---- desktop-widget persistence (Meta+Ctrl+S, alongside the window
    // session save) -------------------------------------------------------
    // Snapshot exactly which widgets are pinned right now — the user may have
    // revealed all then unpinned a few, so this reads the live pins, not the
    // "show all" flag. Restored once at startup below.
    function saveWidgets() {
        const keys = _allWidgets.filter(p => p.pinnedOpen).map(p => p.persistKey).join(" ");
        Quickshell.execDetached(["sh", "-c",
            "d=\"$HOME/.local/state/quickshell\"; mkdir -p \"$d\"; printf '%s\\n' \"$1\" > \"$d/widgets\"",
            "_", keys]);
    }
    // pin order for the instant (reload) path: stackables first, in bottom-up
    // order, so each reads the already-pinned one below it; tiled widgets after
    // (their slot is fixed by tileRank, not pin order). air: cpu→eth→clock.
    readonly property var _pinOrder: Host.name === "air"
        ? [cpuPanel, ethPanel, analogClock, weatherPanel, mediaPanel]
        : [diskPanel, mediaPanel, analogClock, weatherPanel, calendar, gpuPanel, cpuPanel, ethPanel]

    // Login restore: fan the saved (or default) set out. text is the first line
    // of the saved-widgets file — space-separated persistKeys.
    function applyWidgetState(text) {
        const saved = (text || "").split("\n")[0].trim().split(/\s+/).filter(s => s.length);
        // saved set wins; otherwise the baked-in default (first boot).
        const want = saved.length ? saved : _defaultWidgets;
        if (!want.length) return;
        if (want.length === _allWidgets.length) allRevealed = true;

        // Fan the wanted widgets OUT (staged cascade), reusing the exact stage
        // grouping/order the reveal button uses so tiling and stacking land
        // right — filtered to the wanted set (empty stages fall through).
        const stages = _fanOut.map(grp => grp.filter(w => want.indexOf(w.persistKey) >= 0));
        _runFan(stages, true);
    }

    // Read the explicitly saved (Meta+Ctrl+S) pin set. Only ever started on a
    // genuine login — a hot reload restores from the live pin file below instead.
    Process {
        id: widgetStateProc
        command: ["sh", "-c",
            "cat \"$HOME/.local/state/quickshell/widgets\" 2>/dev/null | head -1"]
        stdout: StdioCollector {
            onStreamFinished: shell.applyWidgetState(this.text)
        }
    }

    // ---- hot-reload continuity ------------------------------------------
    // Quickshell rebuilds this entire object tree on every reload (a QML edit,
    // or wal-set.sh rewriting Theme.qml on a wallpaper change), so the desktop
    // widgets are recreated unpinned and would otherwise blink out and replay
    // their entry animation. To make a reload a straight swap instead:
    //
    //   * the LIVE pin set is mirrored to a file in $XDG_RUNTIME_DIR on every
    //     change (not the Meta+Ctrl+S file — that one is the deliberate login
    //     set and must not be overwritten by casual pinning), and
    //   * it is read back SYNCHRONOUSLY here in Component.onCompleted, i.e.
    //     while the tree is still being constructed and before any surface has
    //     mapped, and applied with snapPinned() — no slide, no layer remap.
    //     (The old async Process read landed after the windows were already up,
    //     which is exactly what produced the disappear/reappear.)
    //
    // $XDG_RUNTIME_DIR is wiped at logout, so the file's absence IS the
    // login-vs-reload flag — no separate marker needed.
    readonly property string livePinsPath: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/qs-live-pins"
    readonly property string livePins: _allWidgets.filter(w => w.pinnedOpen).map(w => w.persistKey).join(" ")

    FileView {
        id: livePinsFile
        path: shell.livePinsPath
        blockLoading: true    // synchronous read — see Component.onCompleted
        printErrors: false    // absent on the session's first load; not an error
    }

    // Debounced so the staged fan (one stage every _fanStepMs) writes once at
    // the end rather than four times. The "v2" prefix keeps the file non-empty
    // when nothing is pinned, so "exists" stays distinguishable from "absent".
    //
    // The PID after it is what makes a reload distinguishable from a fresh
    // Quickshell start in the same session. On a RELOAD, Quickshell hands the
    // live layer surface from the outgoing window to the incoming one, so a
    // restored widget is already mapped at the layer it had — remapping it
    // would tear that surface down and build a new one, i.e. exactly the
    // blink this whole mechanism exists to avoid. On a fresh start (a crash,
    // or `systemctl --user restart quickshell`) the pin file outlives the
    // process, the windows are genuinely new, and they DO need the remap or
    // they come up on Overlay. Same PID = same process = surfaces reused.
    onLivePinsChanged: livePinsWriteTimer.restart()
    Timer {
        id: livePinsWriteTimer
        interval: 400
        onTriggered: Quickshell.execDetached(["sh", "-c",
            "printf 'v2 %s %s\\n' \"$2\" \"$3\" > \"$1\"", "_", shell.livePinsPath,
            String(Quickshell.processId), shell.livePins])
    }

    // ---- reload continuity, part 2: the widgets' CONTENTS -----------------
    // Restoring the pins (above) puts the desktop widgets back in place, but
    // each one still came back with empty data — no drives, no forecast, no
    // spectrum, empty chart ring buffers, every readout "--" — and then filled
    // in over the following seconds. Since most of these widgets are sized to
    // their content and bottom-anchored, "filling in" means visibly growing,
    // and the in-place stackables above the disk chase it up the screen. That
    // is the meander: the widgets were in the right place immediately, but the
    // layout underneath them was still arriving.
    //
    // PersistentProperties hands an object's properties from the outgoing tree
    // to the incoming one in-process. Two hard-won constraints:
    //
    //   * It must be a DIRECT child of this root Scope. Nested one level down
    //     inside a plain Item it silently never restores (verified: the value
    //     comes back empty on every reload) — a non-Reloadable parent breaks
    //     the chain Quickshell walks to match old objects to new ones.
    //   * Every carried property is a STRING. Quickshell alternates between two
    //     QML engines across reloads, and a JSValue — i.e. any `property var`
    //     holding an array or object — cannot move between them: every OTHER
    //     reload logs "JSValue can't be reassigned to another engine" and the
    //     property arrives `undefined`. That intermittency is worse than no
    //     persistence at all, so everything is JSON round-tripped.
    //
    // Timing: onLoaded fires after every Component.onCompleted in the new tree
    // but still inside the same synchronous reload pass, so no frame can be
    // rendered in between — the widgets are laid out from restored data before
    // anything is drawn. That's what makes the swap invisible rather than fast.
    PersistentProperties {
        id: persist
        reloadableId: "qsPanelState"

        property string sysinfo: ""
        property string weather: ""
        property string disk: ""
        property string media: ""
        property string meters: ""
        property string procs: ""

        onLoaded: {
            SysInfo.restoreState(sysinfo);
            SysInfo.restoreMeters(meters);
            Weather.restoreState(weather);
            Disks.restoreState(disk);
            Media.restoreState(media);
            Procs.restoreState(procs);
        }
    }

    // Mirror each source into the carrier. Plain assignments, never bindings:
    // the restore above writes these properties directly, which would break a
    // binding permanently on the first reload.
    Connections {
        target: SysInfo
        function onStateRevChanged() { persist.sysinfo = SysInfo.stateJson(); }
    }
    Connections {
        target: Weather
        function onStateRevChanged() { persist.weather = Weather.stateJson(); }
    }
    Connections {
        target: Disks
        function onStateRevChanged() { persist.disk = Disks.stateJson(); }
    }
    Connections {
        target: Procs
        function onStateRevChanged() { persist.procs = Procs.stateJson(); }
    }
    // The VU and spectrum feeds run at cava's 60fps — far too hot to stringify
    // per frame, and a snapshot a quarter-second old is indistinguishable from
    // a live one at the moment a reload lands. So these two are sampled.
    Timer {
        interval: 250
        running: true
        repeat: true
        onTriggered: {
            persist.meters = SysInfo.metersJson();
            persist.media = Media.stateJson();
        }
    }

    Component.onCompleted: {
        // Dock mode owns the widgets; neither the reload restore nor the login
        // fan should put any of them back on the wallpaper. Returning early
        // leaves _preDockPins empty, so a later switch to classic comes up on
        // the default set — correct, since nothing was pinned to remember.
        if (ViewMode.dock) return;

        const live = livePinsFile.text().trim();
        const tok = live.split(/\s+/).filter(s => s.length);
        if (tok.length && (tok[0] === "v2" || tok[0] === "v1")) {
            // hot reload — put the widgets back exactly as they were, instantly.
            // v2 carries the writing process's PID; ours means this is a reload
            // of the SAME process, so every restored surface is one Quickshell
            // handed over still mapped and must NOT be remapped (see snapPinned).
            // A v1 file, or another PID, means new windows: let them remap.
            const reused = tok[0] === "v2" && Number(tok[1]) === Quickshell.processId;
            const want = tok.slice(tok[0] === "v2" ? 2 : 1);
            if (want.length === _allWidgets.length) allRevealed = true;
            for (const w of _pinOrder)
                if (want.indexOf(w.persistKey) >= 0) w.snapPinned(reused);
        } else {
            widgetStateProc.running = true;   // genuine login — fan them in
        }
    }

    // ---- dock mode retires the desktop widgets --------------------------
    // The two modes own the same widgets, so only one may display them: in dock
    // mode they belong to the panel's grid, and leaving them ALSO pinned to the
    // wallpaper would mean two live instances of each — two copies of every
    // polling script, and a row of cards stranded behind the panel where a big
    // chunk of the screen they used to sit on no longer exists.
    //
    // The pre-dock pin set is remembered so switching back to classic restores
    // the desktop exactly as it was left, rather than dumping the user onto the
    // baked-in default set. snapPinned(false) rather than the staged fan: this
    // is a mode switch, not a reveal, so the widgets should simply be there when
    // the crossfade finishes.
    property var _preDockPins: []
    Connections {
        target: ViewMode
        function onDockChanged() {
            if (ViewMode.dock) {
                shell._preDockPins = shell._allWidgets.filter(w => w.pinnedOpen);
                fanTimer.stop();
                for (const w of shell._allWidgets) w.pinnedOpen = false;
                shell.allRevealed = false;
            } else {
                for (const w of shell._pinOrder)
                    if (shell._preDockPins.indexOf(w) >= 0) w.snapPinned(false);
                shell._preDockPins = [];
            }
        }
    }

    // Switch view mode: `qs ipc call view toggle|dock|classic`. Dragging the
    // bar's inner edge is the primary gesture (see ViewMode.qml); this is the
    // keyboard/scripted path, for a hyprland.lua bind.
    IpcHandler {
        target: "view"
        function toggle(): void { ViewMode.toggle(); }
        function dock(): void { ViewMode.setMode("dock"); ViewMode.applyReserve(); }
        function classic(): void { ViewMode.setMode("classic"); ViewMode.applyReserve(); }
        function mode(): string { return SettingsStore.d.viewMode; }

        // Geometry + the last drag's trace, for verifying the edge gesture
        // without watching it: `qs ipc call view geom` / `... view trace`.
        // Each trace sample is dragWidth,surfaceWidth,liveWidth for one pointer
        // event — if the middle column chases the first instead of matching it,
        // the surface is lagging; if either oscillates around a value the
        // pointer is holding still at, the tracking maths is wrong.
        function geom(): string {
            return "mode=" + SettingsStore.d.viewMode
                + " barWidth=" + ViewMode.barWidth
                + " liveWidth=" + ViewMode.liveWidth
                + " dockPx=" + ViewMode.dockPx
                + " range=" + ViewMode.minPx + "-" + ViewMode.maxPx
                + " enterPx=" + Math.round(ViewMode.enterPx)
                + " exitPx=" + Math.round(ViewMode.exitPx)
                + " dragging=" + ViewMode.dragging
                + " samples=" + ViewMode.dragTrace.length;
        }
        function trace(): string { return ViewMode.dragTrace.join(" "); }

        // Slow every view-mode animation down by a factor, so a glitch that
        // lasts two frames at 1x can be recorded and watched:
        // `qs ipc call view slowmo 10`, and `... slowmo 1` to put it back.
        // Not persisted — a reload resets it to 1.
        function slowmo(factor: string): string {
            const f = parseFloat(factor);
            ViewMode.animScale = (isFinite(f) && f > 0) ? f : 1.0;
            return "animScale=" + ViewMode.animScale;
        }
    }

    // Reload-continuity probe: `qs ipc call state carried`. Reports how much of
    // each carried blob survived the last reload, so the swap can be verified
    // without looking at the screen — all five must be non-zero after a reload
    // and are all zero on a genuine login. (Sizes, not contents: this is a
    // health check, not a data dump.)
    IpcHandler {
        target: "state"
        function carried(): string {
            return "sysinfo=" + persist.sysinfo.length
                + " meters=" + persist.meters.length
                + " weather=" + persist.weather.length
                + " disk=" + persist.disk.length
                + " media=" + persist.media.length
                + " procs=" + persist.procs.length
                + " cpuHist=" + SysInfo.cpuHist.length
                + " drives=" + Disks.drives.length
                + " days=" + Weather.days.length
                + " spectrum=" + Media.spectrumLevels.length
                + " tasks=" + Procs.rows.length;
        }
    }

    // Which data singletons are actually polling: `qs ipc call state live`.
    // The two-copies invariant is otherwise invisible — every widget exists twice
    // (a popup and a dock tile) and only the one on screen may drive its scripts.
    // A `true` here for something you are not looking at is the bug.
    IpcHandler {
        target: "live"
        function all(): string {
            return "mode=" + SettingsStore.d.viewMode
                + " disks=" + Disks.live
                + " media=" + Media.live
                + " procs=" + Procs.live
                + " watchers=" + (Disks._watchers.length + Media._watchers.length
                                  + Procs._watchers.length);
        }
        // Per dock tile: the height the grid gave it, the height its content
        // wants, and the difference. Negative slack = the tile is clipping;
        // a large positive one = the dead space this layout exists to avoid.
        function tiles(): string {
            let out = [];
            for (const k in ViewMode.tileInfo) {
                const t = ViewMode.tileInfo[k];
                out.push(k + " got=" + t.a + " wants=" + t.w + " slack=" + (t.a - t.w));
            }
            return out.join("\n");
        }
    }

    // Let Hyprland lock the session: `qs ipc call lock activate` (Super+L).
    // `suspend` is the before-sleep entry point (hypridle) and obeys the
    // `lockOnSuspend` setting; `activate` is unconditional.
    IpcHandler {
        target: "lock"
        function activate(): void { lock.activate(); }
        function suspend(): void { lock.suspend(); }
    }

    // Let Hyprland toggle the launcher: `qs ipc call launcher toggle`.
    IpcHandler {
        target: "launcher"
        function toggle(): void { launcher.open = !launcher.open; }
        function show(): void { launcher.open = true; }
        function hide(): void { launcher.open = false; }
    }

    // Let Hyprland toggle the cheatsheet: `qs ipc call cheatsheet toggle`.
    IpcHandler {
        target: "cheatsheet"
        function toggle(): void { cheatsheet.open = !cheatsheet.open; }
        function show(): void { cheatsheet.open = true; }
        function hide(): void { cheatsheet.open = false; }
    }

    // Let Hyprland toggle the power menu: `qs ipc call powermenu toggle`.
    IpcHandler {
        target: "powermenu"
        function toggle(): void { powermenu.open = !powermenu.open; }
        function show(): void { powermenu.open = true; }
        function hide(): void { powermenu.open = false; }
    }

    // Let Hyprland toggle the wallpaper picker: `qs ipc call wallpaper toggle`.
    IpcHandler {
        target: "wallpaper"
        function toggle(): void { wallpaperPicker.open = !wallpaperPicker.open; }
        function show(): void { wallpaperPicker.open = true; }
        function hide(): void { wallpaperPicker.open = false; }
        // What the panel is actually drawing as the wallpaper, and whether it
        // decoded: `qs ipc call wallpaper status`.
        function status(): string {
            return "path=" + Wall.path + " mode=" + Wall.mode
                + " front=" + Wall.frontStatus + " url=" + Wall.frontUrl;
        }
    }

    // Let Hyprland toggle the screenshot overlay: `qs ipc call screenshot toggle`.
    IpcHandler {
        target: "screenshot"
        function toggle(): void { screenshot.open = !screenshot.open; }
        function show(): void { screenshot.open = true; }
        function hide(): void { screenshot.open = false; }
    }

    // Open a file browser at a path: `qs ipc call browser open <path>`
    // (drives' "open" buttons call Browsers.open directly).
    IpcHandler {
        target: "browser"
        function open(path: string): void { Browsers.open(path && path.length ? path : "/home/lam"); }
    }

    // Reveal/hide all widgets: `qs ipc call widgets toggle` (also the bar's
    // "<" button).
    IpcHandler {
        target: "widgets"
        function toggle(): void { shell.toggleRevealAll(); }
        function save(): void { shell.saveWidgets(); }
    }

    // Pop the OSD from the brightness keys: `qs ipc call osd brightness`.
    // (Volume no longer uses the OSD — the VU meter's level line in the bar
    // is the always-visible indicator.)
    IpcHandler {
        target: "osd"
        function brightness(): void { Osd.trigger("brightness"); }
    }

    // Volume keys route through SysInfo like brightness does — optimistic
    // panel update + wpctl + the Vista ding, no OSD.
    IpcHandler {
        target: "volume"
        function up(): void { SysInfo.adjustVolume(SettingsStore.d.volumeStep); }
        function down(): void { SysInfo.adjustVolume(-SettingsStore.d.volumeStep); }
    }

    // Hardware brightness keys (hypr/hyprland.lua) routed through
    // SysInfo.adjustBrightness — same debounced ddcutil write + optimistic
    // panel update as scrolling "bri" in the status panel, instead of
    // calling ddcutil directly from a `repeating = true` keybind (holding
    // the key would otherwise stack up several ~1.5s DDC calls).
    IpcHandler {
        target: "brightness"
        function up(): void { SysInfo.adjustBrightness(SettingsStore.d.brightnessStep); }
        function down(): void { SysInfo.adjustBrightness(-SettingsStore.d.brightnessStep); }
    }

    // The wallpaper, one Background-layer surface per monitor. Drawn here rather
    // than by hyprpaper so it can be centred in the non-panel desktop and follow
    // the panel edge live — see Wall.qml.
    Variants {
        model: Quickshell.screens
        WallpaperLayer {}
    }

    // The volume/brightness OSD popup, one per monitor.
    Variants {
        model: Quickshell.screens
        OsdWindow {}
    }

    // The accent stripes bookending the desktop: the left screen edge (2px,
    // opposite the bar's own left-edge accent) plus 2px lines across the top
    // and bottom edges. One of each per monitor.
    Variants {
        model: Quickshell.screens
        // the 2px stripe that sits OPPOSITE the bar — flips to the right screen
        // edge when the bar is moved to the left.
        EdgeAccent { edge: SettingsStore.d.barEdge === "left" ? "right" : "left" }
    }
    Variants {
        model: Quickshell.screens
        EdgeAccent { edge: "top" }
    }
    Variants {
        model: Quickshell.screens
        EdgeAccent { edge: "bottom" }
    }

    // Window titlebars are NOT drawn by quickshell: they're compositor-side
    // (the hyprvtb Hyprland plugin, ~/nix/home/prog/hyprvtb/) so they stay
    // locked to windows frame-for-frame. A layer-shell approach lived here
    // once (TitlebarOverlay/WindowTitlebar/WindowTracker) but could only
    // chase window geometry over IPC, always a frame or two behind.

    // Desktop notifications: Quickshell owns org.freedesktop.Notifications and
    // renders toasts bottom-right, just inside the bar. One window (single
    // monitor); the Notifications singleton holds the one bus server.
    NotificationWindow {}

    // The vertical panel, one per monitor.
    Variants {
        model: Quickshell.screens

        PanelWindow {
            id: bar
            required property var modelData
            screen: modelData

            // barEdge picks which screen edge the bar hugs; the accent strip
            // below moves to the opposite (inner) edge to match.
            readonly property bool barLeft: SettingsStore.d.barEdge === "left"

            anchors { top: true; bottom: true; left: bar.barLeft; right: !bar.barLeft }

            // THE SURFACE NEVER RESIZES. It is always as wide as the widest the
            // panel may ever be; the VISIBLE bar is `barBody` inside it, and
            // that is what changes width.
            //
            // This is the same lesson as EdgeGrip.qml, applied to the thing
            // being dragged. Resizing a layer surface is a configure/ack
            // roundtrip with the compositor, so a surface whose width tracks the
            // pointer is always a frame or more behind it — and everything
            // pinned to the panel edge (the wallpaper boundary, the accent
            // stripes, the grip's hover highlight) is computed from
            // ViewMode.liveWidth and therefore lands EXACTLY, while the panel
            // itself trailed. They disagreed on screen for the whole drag.
            //
            // With a fixed surface, the edge is an Item's x/width binding, which
            // takes effect in the frame it is set. Everything now moves together
            // and none of it waits on a roundtrip. It also removes the jump on
            // release: the surface used to resize once more as the committed
            // width landed, which read as the edge flicking away and back.
            //
            // The surface is transparent and input-masked to barBody, so the
            // part of it hanging over the desktop neither paints nor takes
            // clicks.
            //
            // It is a CONSTANT — the widest the panel may ever be — and must
            // stay one. Sizing it to the bar except while dragging seemed
            // tidier, but that put a surface resize on the press and another on
            // the release, and each one made the panel visibly jump (right on
            // click, left on release): resizing a surface anchored to the right
            // edge changes its position too, and the compositor can apply the
            // new geometry a frame before the matching buffer arrives. The
            // surface must simply never change.
            implicitWidth: ViewMode.maxPx
            color: "transparent"
            // Explicit coordinates rather than `Region { item: barBody }`. Both
            // should work, but this is the identical form EdgeGrip.qml uses, and
            // that one is proven every second the desktop is usable: it is a
            // full-screen surface on the OVERLAY layer, so if masks did not
            // confine input, nothing on screen would be clickable at all.
            mask: Region {
                x: bar.barLeft ? 0 : bar.width - ViewMode.liveWidth
                y: 0
                width: ViewMode.liveWidth
                height: bar.height
            }

            // Publish the VISIBLE bar width for the drag trace (`qs ipc call
            // view trace`). Diagnostic only, and single-monitor by nature — the
            // first screen's panel wins, which is the one the fractions are
            // measured against anyway.
            readonly property bool _reports: screen === Quickshell.screens[0]
            // Reserve one window-border less than the bar's real width. The bar
            // still occupies its full barWidth (it's anchored right and this
            // layer sits above windows), but a maximized window is now allowed
            // to extend that 2px further right — tucking its right border UNDER
            // the accent strip below instead of leaving it visible just to the
            // left of it. Otherwise the window's 2px border and the bar's 2px
            // accent stack side by side and read as one double-width border on
            // maximized windows. This mirrors the left screen edge, where the
            // EdgeAccent and a window's left border already share the same
            // pixels. Keep in sync with the window border (hypr border_size).
            // Frozen at the COMMITTED width during a drag. Changing the
            // exclusive zone makes Hyprland recompute the monitor's reserved
            // area and re-run the layout, and doing that on every pointer event
            // fights the same frame the resize is trying to land in. Nothing is
            // lost by deferring it: windows are pushed clear once, on release
            // (applyReserve), which is also when the wallpaper recomposes.
            exclusiveZone: (ViewMode.dragging ? ViewMode.barWidth
                                              : ViewMode.liveWidth)
                           - Theme.windowBorderWidth

            WlrLayershell.namespace: "qs-bar"

            // THE VISIBLE BAR. Its width is the only thing that moves when the
            // panel is resized — a plain binding, applied in the frame it
            // changes, with no compositor roundtrip. Deliberately NOT animated
            // while the pointer is driving it (an animation on a value that is
            // already following the cursor is just added lag); ViewMode.snapping
            // marks the discrete jumps — the entry from 48px to the dock width,
            // the collapse preview — which do glide.
            Item {
                id: barBody
                anchors {
                    top: parent.top; bottom: parent.bottom
                    left: bar.barLeft ? parent.left : undefined
                    right: bar.barLeft ? undefined : parent.right
                }
                width: ViewMode.liveWidth

                Behavior on width {
                    enabled: !ViewMode.dragging || ViewMode.snapping
                    NumberAnimation { duration: ViewMode.ms(200); easing.type: Easing.OutCubic }
                }

                onWidthChanged: if (bar._reports) ViewMode.surfaceWidth = width;

                // the bar's own background, which the surface no longer paints
                Rectangle {
                    anchors.fill: parent
                    color: Theme.bg
                }

                // accent strip down the bar's inner edge — same width as the window
                // border. Sits on the left when the bar is anchored right, and flips
                // to the right when barEdge moves the bar to the left screen edge.
                Rectangle {
                    z: 1
                    anchors {
                        top: parent.top; bottom: parent.bottom
                        left: bar.barLeft ? undefined : parent.left
                        right: bar.barLeft ? parent.right : undefined
                    }
                    width: 2
                    color: Theme.accent
                }

                // ================= CLASSIC LAYOUT =================
                // The 48px bar this config has always been: launcher/tasks/tray at
                // the top, status + clock + date + reveal toggle at the bottom.
                // Wrapped in one Item purely so the whole thing can be crossfaded
                // against the dock layout below — the children are unchanged and
                // still anchor to a parent that exactly fills the bar.
                //
                // `visible: opacity > 0` matters: a fully faded-out layout must stop
                // taking input, or the classic hover zones would keep firing popups
                // from underneath the dock panel.
                Item {
                    id: classicLayout
                    anchors.fill: parent
                    visible: opacity > 0
                    opacity: ViewMode.showDock ? 0 : 1
                    Behavior on opacity { NumberAnimation { duration: ViewMode.ms(140) } }

                    // ---- top cluster: launcher, workspaces, tray ----
                    Column {
                        id: top
                        anchors { top: parent.top; horizontalCenter: parent.horizontalCenter }
                        anchors.topMargin: Theme.gap
                        spacing: Theme.gap

                        RunnerButton {
                            anchors.horizontalCenter: parent.horizontalCenter
                            active: launcher.open
                            onToggled: launcher.open = !launcher.open
                        }

                        // divider
                        Rectangle {
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: Theme.cell - 8
                            height: 1
                            color: Theme.border
                        }

                        Taskbar {
                            anchors.horizontalCenter: parent.horizontalCenter
                        }

                        // divider
                        Rectangle {
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: Theme.cell - 8
                            height: 1
                            color: Theme.border
                        }

                        Tray {
                            anchors.horizontalCenter: parent.horizontalCenter
                            hostWindow: bar
                        }
                    }

                    // ---- system status, sitting just above the clock ----
                    StatusPanel {
                        width: parent.width
                        anchors {
                            bottom: statusDivider.top
                            bottomMargin: Theme.gap * 2
                            horizontalCenter: parent.horizontalCenter
                        }
                        // weather slides out at the BOTTOM like the clock/date popups
                        // (anchorCenterY stays -1), not centered on its bar module
                        onWeatherHovered: (h, cy) => weatherPanel.hoverChanged(h)
                        // disk slides out at the BOTTOM (anchorCenterY stays -1) — it's
                        // tall, so bottom-anchoring reads better than centering
                        onDiskHovered: (h, cy) => diskPanel.hoverChanged(h)
                        // hovering the VU/volume bar slides out the media widget
                        onMediaHovered: (h) => mediaPanel.hoverChanged(h)
                        onCpuHovered: (h, cy) => { if (h) cpuPanel.anchorCenterY = cy; cpuPanel.hoverChanged(h); }
                        onGpuHovered: (h, cy) => { if (h) gpuPanel.anchorCenterY = cy; gpuPanel.hoverChanged(h); }
                        onEthHovered: (h, cy) => { if (h) ethPanel.anchorCenterY = cy; ethPanel.hoverChanged(h); }
                    }

                    // divider between the status indicators and the clock
                    Rectangle {
                        id: statusDivider
                        anchors { bottom: clock.top; bottomMargin: Theme.gap * 2; horizontalCenter: parent.horizontalCenter }
                        width: Theme.cell - 8
                        height: 1
                        color: Theme.border
                    }

                    // ---- time, on top of the date ----
                    Clock {
                        id: clock
                        anchors { bottom: dateDisplay.top; horizontalCenter: parent.horizontalCenter }
                        anchors.bottomMargin: 6
                    }

                    // ---- date (month / day / year), above the reveal button ----
                    DateDisplay {
                        id: dateDisplay
                        anchors { bottom: revealBtn.top; horizontalCenter: parent.horizontalCenter }
                        anchors.bottomMargin: 6
                    }

                    // ---- reveal-all-widgets toggle, at the very bottom ----
                    Rectangle {
                        id: revealBtn
                        anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter }
                        anchors.bottomMargin: Theme.gap
                        width: Theme.wsCell
                        height: 16
                        color: shell.allRevealed ? Theme.bgAlt : "transparent"
                        border.width: shell.allRevealed ? 2 : 1
                        border.color: (shell.allRevealed || revealMa.containsMouse) ? Theme.accent : Theme.border
                        PixelText {
                            anchors.centerIn: parent
                            text: shell.allRevealed ? ">" : "<"
                            color: (shell.allRevealed || revealMa.containsMouse) ? Theme.accent : Theme.text
                        }
                        MouseArea {
                            id: revealMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: shell.toggleRevealAll()
                        }
                    }

                    // Hover zones for the popups: the whole lower strip of the bar at
                    // full width, not just the glyphs. The clock band pops the analog
                    // clock; the date band pops the calendar. NoButton = hover only.
                    MouseArea {
                        anchors { top: clock.top; topMargin: -Theme.gap; bottom: dateDisplay.top; left: parent.left; right: parent.right }
                        hoverEnabled: true
                        acceptedButtons: Qt.NoButton
                        onEntered: analogClock.hoverChanged(true)
                        onExited: analogClock.hoverChanged(false)
                    }
                    MouseArea {
                        anchors { top: dateDisplay.top; bottom: revealBtn.top; left: parent.left; right: parent.right }
                        hoverEnabled: true
                        acceptedButtons: Qt.NoButton
                        onEntered: calendar.hoverChanged(true)
                        onExited: calendar.hoverChanged(false)
                    }
                }

                // ================= DOCK LAYOUT =================
                // The wide panel: runner + wrapping task icons across the top, the
                // widget grid filling everything below. The grid's tiles are the
                // SAME widgets the popups show — one *Content.qml each — so the
                // two modes can't drift apart (see DockGrid.qml).
                Item {
                    id: dockLayout
                    anchors.fill: parent
                    anchors.margins: Theme.gap
                    visible: opacity > 0
                    opacity: ViewMode.showDock ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: ViewMode.ms(140) } }

                    DockHeader {
                        id: dockHeader
                        anchors { left: parent.left; right: parent.right; top: parent.top }
                        runnerActive: launcher.open
                        onRunnerToggled: launcher.open = !launcher.open
                    }

                    Rectangle {
                        id: dockDivider
                        anchors {
                            left: parent.left; right: parent.right
                            top: dockHeader.bottom; topMargin: Theme.gap
                        }
                        height: 1
                        color: Theme.border
                    }

                    DockGrid {
                        // Only the mode on screen polls: the popup copies of each
                        // widget gate on their own `open`, the grid's copies on
                        // this. Both layouts are always instantiated, so without
                        // it every widget would have two live instances.
                        active: dockLayout.visible
                        anchors {
                            left: parent.left; right: parent.right
                            top: dockDivider.bottom; topMargin: Theme.gap
                            bottom: parent.bottom
                        }
                    }
                }
            }
        }
    }

    // The panel's resize / mode-switch handle. A separate full-screen surface
    // per monitor, masked to an 8px strip over the panel's inner edge — see
    // EdgeGrip.qml for why it cannot live inside the panel it resizes.
    Variants {
        model: Quickshell.screens
        EdgeGrip {}
    }
}
