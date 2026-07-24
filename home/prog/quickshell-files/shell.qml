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
    readonly property int _fanStepMs: 300
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

    // text is two lines: "<space-separated keys>\n<login|reload>".
    function applyWidgetState(text) {
        const lines = (text || "").split("\n");
        const saved = (lines[0] || "").trim().split(/\s+/).filter(s => s.length);
        const login = (lines[1] || "").trim() !== "reload";
        // saved set wins; otherwise the baked-in default (first boot).
        const want = saved.length ? saved : _defaultWidgets;
        if (!want.length) return;
        if (want.length === _allWidgets.length) allRevealed = true;

        if (login) {
            // Fan the wanted widgets OUT (staged cascade) at a genuine login,
            // reusing the exact stage grouping/order the reveal button uses so
            // tiling and stacking land right — filtered to the wanted set (empty
            // stages fall through). Mirrors "how they are now": they fan in.
            const stages = _fanOut.map(grp => grp.filter(w => want.indexOf(w.persistKey) >= 0));
            _runFan(stages, true);
        } else {
            // A hot reload (e.g. wal-set.sh rewriting Theme.qml) recreates this
            // whole tree — snap the pins back instantly instead of replaying the
            // ~1.2s fan on every wallpaper change.
            for (const w of _pinOrder)
                if (want.indexOf(w.persistKey) >= 0) w.pinnedOpen = true;
        }
    }

    // Read the saved pin set once at startup, plus a login-vs-reload flag: a
    // marker in $XDG_RUNTIME_DIR (wiped on logout) exists on reloads but not on
    // the session's first load, so only a real login gets the fan cascade. A
    // Process (not FileView) keeps it simple and the async read doubles as a
    // small settle delay before pins map.
    Process {
        id: widgetStateProc
        command: ["sh", "-c",
            "printf '%s\\n' \"$(cat \"$HOME/.local/state/quickshell/widgets\" 2>/dev/null | head -1)\"; " +
            "m=\"${XDG_RUNTIME_DIR:-/tmp}/qs-fanned\"; " +
            "[ -e \"$m\" ] && echo reload || { touch \"$m\"; echo login; }"]
        stdout: StdioCollector {
            onStreamFinished: shell.applyWidgetState(this.text)
        }
    }
    Component.onCompleted: widgetStateProc.running = true

    // Let Hyprland lock the session: `qs ipc call lock activate` (Super+L).
    IpcHandler {
        target: "lock"
        function activate(): void { lock.activate(); }
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
        function up(): void { SysInfo.adjustVolume(5); }
        function down(): void { SysInfo.adjustVolume(-5); }
    }

    // Hardware brightness keys (hypr/hyprland.lua) routed through
    // SysInfo.adjustBrightness — same debounced ddcutil write + optimistic
    // panel update as scrolling "bri" in the status panel, instead of
    // calling ddcutil directly from a `repeating = true` keybind (holding
    // the key would otherwise stack up several ~1.5s DDC calls).
    IpcHandler {
        target: "brightness"
        function up(): void { SysInfo.adjustBrightness(5); }
        function down(): void { SysInfo.adjustBrightness(-5); }
    }

    // The volume/brightness OSD popup, one per monitor.
    Variants {
        model: Quickshell.screens
        OsdWindow {}
    }

    // The accent stripes bookending the desktop: the left screen edge (2px,
    // opposite the bar's own left-edge accent) plus 1px lines across the top
    // and bottom edges. One of each per monitor.
    Variants {
        model: Quickshell.screens
        EdgeAccent { edge: "left" }
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

            anchors { top: true; bottom: true; right: true }
            implicitWidth: Theme.barWidth
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
            exclusiveZone: Theme.barWidth - Theme.windowBorderWidth
            color: Theme.bg

            WlrLayershell.namespace: "qs-bar"

            // accent strip down the left edge — same width as the window border
            Rectangle {
                z: 1
                anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
                width: 2
                color: Theme.accent
            }

            // ---- top cluster: launcher, workspaces, tray ----
            Column {
                id: top
                anchors { top: parent.top; horizontalCenter: parent.horizontalCenter }
                anchors.topMargin: Theme.gap
                spacing: Theme.gap

                // launcher button — outlined square, matching the workspaces.
                // When open it takes the SAME active treatment as the current
                // workspace cell: bgAlt fill with a bright 2px accent border.
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: Theme.wsCell
                    height: Theme.wsCell
                    radius: 0
                    color: launcher.open ? Theme.bgAlt : "transparent"
                    border.width: launcher.open ? 2 : 1
                    border.color: launcher.open ? Theme.accent : Theme.border

                    // solid square icon — a real Rectangle centres cleanly, where
                    // the font's ■ glyph sits high in its line box and floats up.
                    Rectangle {
                        anchors.centerIn: parent
                        width: Theme.wsCell - 18
                        height: width
                        radius: 0
                        color: launcher.open ? Theme.text : Theme.accent
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: launcher.open = !launcher.open
                    }
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
    }
}
