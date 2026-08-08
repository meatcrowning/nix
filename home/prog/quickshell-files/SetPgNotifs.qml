import QtQuick

// Notifications & Sounds — the toast server behaviour, when it stays quiet, the
// per-sender rules, and the per-event sound map (urgency maps directly to a
// sound file, so they belong together).
//
// Structured after Plasma's kcm_notifications, which splits the question into
// global conditions and a per-application block; the divergences (no history,
// no badges, no per-event table, and criticals default to piercing DND) are
// noted where they sit, and in Notifications.qml at the enforcement point.
Column {
    id: page
    width: parent ? parent.width : 480
    spacing: 4

    property var d: SettingsStore.d

    // The per-app list, built from the senders the panel has actually seen.
    // Derived through a JSON string rather than straight off `notifSeen`: the
    // store re-reads settings.json a few times a second, and rebuilding this
    // array on every one of those reloads would collapse an expanded row under
    // the pointer. The string only changes when the contents do.
    readonly property string seenJson: JSON.stringify(page.d.notifSeen || {})
    property var seenApps: []
    function _rebuildSeen() {
        const seen = page.d.notifSeen || {};
        const out = [];
        for (const k in seen)
            if (k !== "@other")
                out.push({ key: k, label: (seen[k] || k) });
        out.sort((a, b) => a.label.toLowerCase() < b.label.toLowerCase() ? -1 : 1);
        page.seenApps = out;
    }
    onSeenJsonChanged: page._rebuildSeen()
    Component.onCompleted: page._rebuildSeen()

    // Timed do-not-disturb. The picker's value is the stored duration; arming
    // it stamps the instant the server actually obeys.
    readonly property var dndMins: ({ "off": 0, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "8h": 480 })
    function _dndLabel() {
        const m = page.d.notifDndFor;
        for (const k in page.dndMins) if (page.dndMins[k] === m) return k;
        return "off";
    }
    function _setDnd(optionLabel) {
        const mins = page.dndMins[optionLabel] || 0;
        page.d.notifDndFor = mins;
        page.d.notifDndUntil = mins > 0 ? Date.now() + mins * 60000 : 0;
        SettingsStore.save();
    }
    // What the armed timer says, refreshed on its own clock so the row does not
    // sit claiming "lifts in 1h" for the whole hour.
    property double now: Date.now()
    Timer {
        interval: 30000
        repeat: true
        running: page.d.notifDndUntil > 0
        onTriggered: page.now = Date.now()
    }
    function _dndRemaining() {
        const left = page.d.notifDndUntil - page.now;
        if (page.d.notifDndUntil <= 0 || left <= 0)
            return "";
        const mins = Math.ceil(left / 60000);
        return mins >= 60
            ? "quiet for another " + Math.floor(mins / 60) + "h " + (mins % 60) + "m"
            : "quiet for another " + mins + "m";
    }

    SetSection {
        title: "notifications"
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
            label: "low priority popups"
            desc: "urgency 0 - a background job's chatter"
            SetToggle {
                checked: page.d.notifLowPopup
                onToggled: (v) => { page.d.notifLowPopup = v; SettingsStore.save(); }
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
        title: "do not disturb"
        SetRow {
            label: "do not disturb"
            desc: "suppress toasts until you turn this back off"
            SetToggle {
                checked: page.d.doNotDisturb
                onToggled: (v) => { page.d.doNotDisturb = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "for a while"
            desc: page._dndRemaining()
            SetSelect {
                options: ["off", "15m", "30m", "1h", "2h", "4h", "8h"]
                value: page._dndLabel()
                onChanged: (v) => page._setDnd(v)
            }
        }
        SetRow {
            label: "while fullscreen"
            desc: "quiet for as long as a fullscreen window is up"
            SetToggle {
                checked: page.d.notifDndFullscreen
                onToggled: (v) => { page.d.notifDndFullscreen = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "let critical through"
            desc: "urgency 2 ignores do not disturb"
            SetToggle {
                checked: page.d.notifCriticalInDnd
                onToggled: (v) => { page.d.notifCriticalInDnd = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "mute notification sound"
            desc: "keep the toast, drop the chime"
            SetToggle {
                checked: page.d.notifSoundMute
                onToggled: (v) => { page.d.notifSoundMute = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "per-app"

        // The default every unlisted sender inherits — Plasma's "@other"
        // ("Other Applications") row, which serves the same purpose there.
        SetNotifApp {
            appKey: "@other"
            label: "all other senders"
            isDefault: true
        }

        Repeater {
            model: page.seenApps
            SetNotifApp {
                appKey: modelData.key
                label: modelData.label
            }
        }

        // Nothing is enumerable up front: there is no notification-capability
        // declaration to read, so the list is the senders that have actually
        // toasted since the panel started keeping the list.
        PixelText {
            visible: page.seenApps.length === 0
            width: parent.width
            wrapMode: Text.WordWrap
            color: Theme.textDim
            text: "no app has sent a notification yet - each one appears here the first time it does"
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
