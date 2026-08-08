import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Services.Pam

// Secure lock screen. Uses the ext-session-lock-v1 protocol (WlSessionLock) so
// the compositor actually blanks the session and blocks access to the windows
// behind it — this is a real lock, not just an overlay. Password auth goes
// through PAM against the dedicated `quickshell-lock` service (see
// /etc/pam.d/quickshell-lock), which pulls in the base system-auth stack.
//
// Triggered from Hyprland via `qs ipc call lock activate` (Super+L; see
// hypr/hyprland.lua). The themed panel slides in from the right edge; on a
// correct password it fades out and the session unlocks.
Scope {
    id: root

    // Drive the lock. `unlocking` runs the fade-out before the surfaces are
    // torn down (setting lock.locked=false destroys them instantly, so we fade
    // first, then unlock in the animation's onFinished).
    property bool locked: false
    property bool unlocking: false

    function activate() {
        if (root.locked) return;
        root.unlocking = false;
        root.locked = true;
    }

    // Idle auto-lock. The panel owns this rather than hypridle because the
    // timeout is a live setting (`autoLockMin`): a binding re-arms the monitor
    // the instant settings.json changes, where hypridle would need its config
    // rewritten and the daemon restarted on every drag of the slider.
    // 0 = never, so `enabled` gates the whole thing.
    //
    // `respectInhibitors` keeps the video-playback behaviour hypridle had: a
    // client holding zwp_idle_inhibit_manager_v1 (Firefox/Chromium while
    // playing) stops the idle clock, so it won't lock mid-video.
    //
    // Fires activate() in-process instead of shelling out to
    // `loginctl lock-session`. That would be one more hop (logind Lock signal
    // -> hypridle lock_cmd -> `qs ipc call lock activate`) landing back here
    // anyway, and loginctl has a habit of failing silently from inside the
    // panel. Display blanking stays with hypridle — see hypridle.conf.
    IdleMonitor {
        enabled: SettingsStore.d.autoLockMin > 0
        timeout: SettingsStore.d.autoLockMin * 60
        respectInhibitors: true
        onIsIdleChanged: if (isIdle) root.activate()
    }

    // Lock before the machine suspends, honouring the `lockOnSuspend` setting.
    // hypridle's before_sleep_cmd calls this (via `qs ipc call lock suspend`)
    // rather than locking unconditionally, so the toggle actually does
    // something.
    function suspend() {
        if (!SettingsStore.d.lockOnSuspend) return;
        root.activate();
    }

    // Shared clock, so every monitor's surface reads the same time. Only ticks
    // while locked.
    property string timeText: "12:00 AM"
    function pad(n) { return (n < 10 ? "0" : "") + n }
    function refreshTime() {
        const d = sysClock.date;
        const m = root.pad(d.getMinutes());
        if (SettingsStore.d.lockClock24h) {
            root.timeText = root.pad(d.getHours()) + ":" + m;
            return;
        }
        let h = d.getHours();
        const ampm = h < 12 ? "AM" : "PM";
        h = h % 12; if (h === 0) h = 12;
        root.timeText = h + ":" + m + " " + ampm;
    }
    SystemClock {
        id: sysClock
        enabled: root.locked
        precision: SystemClock.Minutes
        onDateChanged: root.refreshTime()
    }
    onLockedChanged: if (locked) refreshTime()

    WlSessionLock {
        id: sessionLock
        locked: root.locked

        // One surface per monitor. Each is self-contained: its own PAM
        // conversation, password buffer and reveal state, so only the focused
        // output ever runs auth. The shared `root.unlocking` fades them all
        // together.
        surface: WlSessionLockSurface {
            id: surface

            // Base layer sits behind the sliding panel — black, so the desktop
            // never leaks through the shrinking gap as the panel slides in.
            color: "black"

            // Per-surface state.
            property bool revealed: false        // has the user begun to unlock?
            property bool authenticating: false  // PAM check in flight
            property string errorText: ""

            function submit() {
                if (surface.authenticating) return;
                if (password.text.length === 0) return;
                surface.errorText = "";
                surface.authenticating = true;
                if (!pam.start()) {
                    surface.authenticating = false;
                    surface.errorText = "auth unavailable";
                }
            }

            PamContext {
                id: pam
                configDirectory: "/etc/pam.d"
                config: SettingsStore.d.lockPamService

                // PAM prompts for the password once the conversation starts;
                // hand it whatever's in the field.
                onPamMessage: {
                    if (this.responseRequired)
                        this.respond(password.text);
                }
                onCompleted: (result) => {
                    if (result === PamResult.Success) {
                        // Fade every surface out, then drop the lock.
                        root.unlocking = true;
                    } else {
                        surface.authenticating = false;
                        surface.errorText = result === PamResult.MaxTries
                            ? "too many attempts" : "incorrect password";
                        password.text = "";
                        password.forceActiveFocus();
                    }
                }
            }

            Component.onCompleted: password.forceActiveFocus()

            // The themed panel. Slides in from the right on lock; fades out on
            // unlock (per the brief).
            Rectangle {
                id: panel
                width: surface.width
                height: surface.height
                color: Theme.bg

                property bool entered: false
                Component.onCompleted: panel.entered = true

                x: panel.entered ? 0 : width
                // The lock panel slides in off the screen edge — an ordinary
                // reveal, so it takes the desktop's slide (docs/DESIGN.md §6.2).
                Behavior on x { NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing } }

                opacity: root.unlocking ? 0 : 1
                // THIS ONE KEEPS ITS LITERAL, ON PURPOSE. Releasing the session
                // lock is a SIDE EFFECT of this animation finishing — see
                // onRunningChanged below — so it is the one duration on the
                // desktop that must not be reachable by a setting. Routed
                // through ViewMode.ms() it would become 0 under reduceMotion,
                // and a zero-length animation is an immediate assignment that
                // need never report a running->stopped edge: the fade would
                // "finish" with nobody left to unlock the screen. The failure
                // mode is the user locked out of their own session, so the
                // rule here is a plain number and a comment saying why.
                Behavior on opacity {
                    NumberAnimation {
                        duration: 300
                        easing.type: Easing.InOutQuad
                        onRunningChanged: {
                            // When the unlock fade finishes, actually release
                            // the session lock (this tears the surfaces down).
                            if (!running && root.unlocking)
                                root.locked = false;
                        }
                    }
                }

                Column {
                    anchors.centerIn: parent
                    spacing: Theme.gap * 2

                    PixelText {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: root.timeText
                        color: Theme.text
                    }


                    // Password field — fades in under the clock once the user
                    // starts interacting. Kept in the layout (reserving its
                    // space) so nothing shifts when it appears.
                    Item {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 220
                        height: 34
                        opacity: surface.revealed ? 1 : 0
                        Behavior on opacity { NumberAnimation { duration: ViewMode.ms(200); easing.type: ViewMode.slideEasing } }

                        Rectangle {
                            anchors.fill: parent
                            color: Theme.bgAlt
                            border.color: surface.errorText !== "" ? Theme.crit : Theme.border
                            border.width: Theme.ctrlBorder
                            radius: Math.max(2, Theme.windowRounding)

                            Row {
                                anchors.fill: parent
                                anchors.leftMargin: 8
                                anchors.rightMargin: 8
                                spacing: 6

                                PixelText {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: ">"
                                    color: Theme.accent
                                }
                                TextInput {
                                    id: password
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width - 20
                                    color: Theme.text
                                    font.family: Theme.font
                                    font.pixelSize: Theme.fontSize
                                    font.hintingPreference: Font.PreferFullHinting
                                    renderType: Text.NativeRendering
                                    clip: true
                                    focus: true
                                    echoMode: TextInput.Password
                                    passwordCharacter: "*"
                                    enabled: !surface.authenticating
                                    // The input is always focused (even while
                                    // invisible), so it — not the panel — is what
                                    // sees the keystrokes. Any key reveals the
                                    // field; the character itself still flows in.
                                    Keys.onPressed: (event) => {
                                        if (!surface.revealed && !root.unlocking)
                                            surface.revealed = true;
                                        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                                            surface.submit();
                                            event.accepted = true;
                                        }
                                    }

                                    PixelText {
                                        anchors.verticalCenter: parent.verticalCenter
                                        visible: password.text === "" && !surface.authenticating
                                        text: "password"
                                        font: password.font
                                        color: Theme.textDim
                                    }
                                }
                            }
                        }
                    }

                    // Status line: error, or "checking..." while PAM runs.
                    PixelText {
                        anchors.horizontalCenter: parent.horizontalCenter
                        opacity: surface.revealed ? 1 : 0
                        text: surface.authenticating ? "checking..." : surface.errorText
                        color: surface.authenticating ? Theme.textDim : Theme.crit
                    }
                }
            }
        }
    }
}
