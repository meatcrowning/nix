import QtQuick

// Notifications & Sounds — the toast server behaviour and the per-event sound
// map (urgency maps directly to a sound file, so they belong together).
Column {
    id: page
    width: parent ? parent.width : 480
    spacing: 4

    property var d: SettingsStore.d

    SetSection {
        title: "notifications"
        SetRow {
            label: "do not disturb"
            desc: "suppress non-critical toasts"
            SetToggle {
                checked: page.d.doNotDisturb
                onToggled: (v) => { page.d.doNotDisturb = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "auto-dismiss after"
            desc: "critical toasts always stay until clicked"
            SetSlider {
                from: 1000; to: 15000; step: 500; unit: "ms"
                value: page.d.notifTimeoutMs
                onMoved: (v) => { page.d.notifTimeoutMs = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "max on screen"
            SetSlider {
                from: 1; to: 8; step: 1
                value: page.d.notifMaxVisible
                onMoved: (v) => { page.d.notifMaxVisible = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "toast width"
            SetSlider {
                from: 220; to: 480; step: 10; unit: "px"
                value: page.d.notifWidth
                onMoved: (v) => { page.d.notifWidth = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "corner"
            SetSelect {
                options: ["bottom-right", "bottom-left", "top-right", "top-left"]
                value: page.d.notifCorner
                onChanged: (v) => { page.d.notifCorner = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "show images"
            desc: "advertise image support to apps"
            SetToggle {
                checked: page.d.notifImages
                onToggled: (v) => { page.d.notifImages = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "enable actions"
            desc: "advertise action buttons to apps"
            SetToggle {
                checked: page.d.notifActions
                onToggled: (v) => { page.d.notifActions = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "sounds"
        SetRow {
            label: "system sounds"
            SetToggle {
                checked: page.d.soundsEnabled
                onToggled: (v) => { page.d.soundsEnabled = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "sound theme"
            desc: "folder under ~/.local/share/sounds"
            SetTextField {
                fieldWidth: 140
                value: page.d.soundTheme
                onCommitted: (t) => { page.d.soundTheme = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "login"
            SetTextField {
                fieldWidth: 200
                value: page.d.soundLogin
                onCommitted: (t) => { page.d.soundLogin = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "volume change"
            SetTextField {
                fieldWidth: 200
                value: page.d.soundVolume
                onCommitted: (t) => { page.d.soundVolume = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "notification"
            SetTextField {
                fieldWidth: 200
                value: page.d.soundNotify
                onCommitted: (t) => { page.d.soundNotify = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "critical notification"
            SetTextField {
                fieldWidth: 200
                value: page.d.soundCritical
                onCommitted: (t) => { page.d.soundCritical = t; SettingsStore.save(); }
            }
        }
    }
}
