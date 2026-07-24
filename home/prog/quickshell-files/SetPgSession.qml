import QtQuick

// Lock & Power — the lock screen, idle behaviour, and the power-menu commands.
Column {
    id: page
    width: parent ? parent.width : 480
    spacing: 4

    property var d: SettingsStore.d

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

    SetSection {
        title: "power behaviour"
        SetRow {
            label: "lid close"
            SetSelect {
                options: ["suspend", "lock", "nothing"]
                value: page.d.lidCloseAction
                onChanged: (v) => { page.d.lidCloseAction = v; SettingsStore.save(); }
            }
        }
    }
}
