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

    // NO "power behaviour / lid close" section. Nothing in this desktop can
    // honour it: lid handling belongs to logind, top has no lid at all, and the
    // one machine that does (book) gets home-manager only from this repo — its
    // logind config is Fedora system state we cannot write. hypridle, which
    // owns the idle side above, has no lid event either. Implementing it would
    // mean the panel taking a systemd-inhibit lock and watching
    // /proc/acpi/button/lid — a feature, and one that cannot be tested from
    // here. Removed rather than left drawn; ask and it can be built on book.
}
