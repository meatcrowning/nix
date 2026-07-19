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

    // The Spectacle-style screenshot overlay (Meta+Shift+S).
    Screenshot {
        id: screenshot
    }

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

    // Pop the OSD from the media-key binds:
    //   `qs ipc call osd volume` / `qs ipc call osd brightness`
    IpcHandler {
        target: "osd"
        function volume(): void { Osd.trigger("volume"); }
        function brightness(): void { Osd.trigger("brightness"); }
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

    // The accent stripe on the true left edge of the screen, one per monitor.
    Variants {
        model: Quickshell.screens
        EdgeAccent {}
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

            // ---- system status, sitting just above the date ----
            StatusPanel {
                width: parent.width
                anchors {
                    bottom: statusDivider.top
                    bottomMargin: Theme.gap * 2
                    horizontalCenter: parent.horizontalCenter
                }
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

            // ---- bottom: date (month / year / day) ----
            DateDisplay {
                id: dateDisplay
                anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter }
                anchors.bottomMargin: Theme.gap
            }
        }
    }
}
