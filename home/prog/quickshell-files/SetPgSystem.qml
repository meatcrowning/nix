import QtQuick
import Quickshell.Io

// Input & System — keyboard/pointer and the read-only machine profile. The
// clock/calendar, weather, and world-clock data live on the Widgets page.
Column {
    id: page
    width: parent ? parent.width : 480
    spacing: 4

    property var d: SettingsStore.d

    // Machine name for the read-only profile row. Read via `hostname` rather
    // than the nix-generated Host singleton so this page has no dependency on a
    // file that only exists in the deployed config.
    property string hostName: "…"
    Process {
        running: true
        command: ["hostname"]
        stdout: StdioCollector { onStreamFinished: page.hostName = (this.text || "").trim() || "unknown" }
    }

    SetSection {
        title: "keyboard"
        SetRow {
            label: "repeat delay"
            desc: "before a held key starts repeating"
            SetSlider {
                from: 100; to: 800; step: 10; unit: "ms"
                value: page.d.keyRepeatDelay
                onMoved: (v) => { page.d.keyRepeatDelay = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "repeat rate"
            desc: "keys per second while held"
            SetSlider {
                from: 10; to: 100; step: 1; unit: "/s"
                value: page.d.keyRepeatRate
                onMoved: (v) => { page.d.keyRepeatRate = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "pointer"
        SetRow {
            label: "speed"
            desc: "libinput acceleration, -1 slow … 1 fast"
            SetSlider {
                from: -1.0; to: 1.0; step: 0.1
                value: page.d.pointerSpeed
                onMoved: (v) => { page.d.pointerSpeed = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "natural scroll"
            SetToggle {
                checked: page.d.naturalScroll
                onToggled: (v) => { page.d.naturalScroll = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "tap to click"
            SetToggle {
                checked: page.d.tapToClick
                onToggled: (v) => { page.d.tapToClick = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "machine"
        SetRow {
            label: "host profile"
            desc: "the branch this session was built for (read-only)"
            PixelText {
                text: page.hostName
                color: Theme.accent
            }
        }
    }
}
