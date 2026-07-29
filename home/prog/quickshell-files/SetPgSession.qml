import QtQuick
import Quickshell.Io

// Lock & Power — the lock screen, idle behaviour, the power-menu commands, and
// (on a machine with a lid) what closing it does.
Column {
    id: page
    width: parent ? parent.width : 480
    spacing: 4

    property var d: SettingsStore.d

    // The lid section is drawn ONLY on book, the one machine here that has a
    // lid — top is a desktop, and a picker for a switch that does not exist is
    // exactly the inert control docs/DESIGN.md §10 forbids. Read via `hostname`
    // for the same reason SetPgSystem.qml does: no dependency on a generated
    // file. Absent until the answer arrives, never wrongly present.
    property bool hasLid: false
    Process {
        running: true
        command: ["hostname"]
        stdout: StdioCollector { onStreamFinished: page.hasLid = (this.text || "").trim() === "book" }
    }

    SetSection {
        title: "lock screen"
        SetRow {
            label: "24-hour clock"
            SetToggle {
                checked: page.d.lockClock24h
                onToggled: (v) => { page.d.lockClock24h = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "auto-lock after"
            desc: "idle minutes before locking; 0 = never"
            SetSlider {
                from: 0; to: 60; step: 1; unit: "min"
                value: page.d.autoLockMin
                onMoved: (v) => { page.d.autoLockMin = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "lock on suspend"
            SetToggle {
                checked: page.d.lockOnSuspend
                onToggled: (v) => { page.d.lockOnSuspend = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "PAM service"
            desc: "config under /etc/pam.d"
            SetTextField {
                fieldWidth: 180
                value: page.d.lockPamService
                onCommitted: (t) => { page.d.lockPamService = t; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "power menu commands"
        SetRow {
            label: "log out"
            SetTextField {
                fieldWidth: 240
                value: page.d.cmdLogout
                onCommitted: (t) => { page.d.cmdLogout = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "sleep"
            SetTextField {
                fieldWidth: 240
                value: page.d.cmdSleep
                onCommitted: (t) => { page.d.cmdSleep = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "reboot"
            SetTextField {
                fieldWidth: 240
                value: page.d.cmdReboot
                onCommitted: (t) => { page.d.cmdReboot = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "power off"
            SetTextField {
                fieldWidth: 240
                value: page.d.cmdPoweroff
                onCommitted: (t) => { page.d.cmdPoweroff = t; SettingsStore.save(); }
            }
        }
    }

    // Lid close — book only (see `hasLid`). It IS honoured: the lid-inhibit
    // user service holds logind's handle-lid-switch, and Hyprland's own switch
    // bind runs ~/.config/scripts/lid-close.sh, which re-reads this key on
    // every event — so a change here applies to the very next close, with
    // nothing to restart. Whole mechanism: home/srvs/lid.nix.
    SetSection {
        title: "laptop lid"
        visible: page.hasLid
        SetRow {
            label: "when the lid closes"
            desc: "blank turns the display off without locking; nothing leaves it running"
            SetSelect {
                options: ["suspend", "lock", "blank", "nothing"]
                labels: ({ suspend: "sleep", lock: "lock", blank: "screen off", nothing: "nothing" })
                value: page.d.lidClose
                onChanged: (v) => { page.d.lidClose = v; SettingsStore.save(); }
            }
        }
    }
}
