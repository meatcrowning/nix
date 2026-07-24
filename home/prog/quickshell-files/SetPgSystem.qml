import QtQuick
import Quickshell.Io

// Input & System — keyboard/pointer, the clock/calendar/weather data the bar
// shows, world-clock zones, and the read-only machine profile.
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
        title: "clock & calendar"
        SetRow {
            label: "24-hour clock"
            desc: "applies to the bar clock everywhere"
            SetToggle {
                checked: page.d.clock24h
                onToggled: (v) => { page.d.clock24h = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "week starts monday"
            SetToggle {
                checked: page.d.weekStartsMonday
                onToggled: (v) => { page.d.weekStartsMonday = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "weather"
        SetRow {
            label: "place name"
            SetTextField {
                fieldWidth: 160
                value: page.d.weatherPlace
                onCommitted: (t) => { page.d.weatherPlace = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "latitude"
            SetTextField {
                fieldWidth: 120; numeric: true
                value: "" + page.d.weatherLat
                onCommitted: (t) => { const n = parseFloat(t); if (!isNaN(n)) { page.d.weatherLat = n; SettingsStore.save(); } }
            }
        }
        SetRow {
            label: "longitude"
            SetTextField {
                fieldWidth: 120; numeric: true
                value: "" + page.d.weatherLon
                onCommitted: (t) => { const n = parseFloat(t); if (!isNaN(n)) { page.d.weatherLon = n; SettingsStore.save(); } }
            }
        }
        SetRow {
            label: "units"
            SetSelect {
                options: ["F", "C"]
                labels: ({ F: "°F", C: "°C" })
                value: page.d.weatherUnit
                onChanged: (v) => { page.d.weatherUnit = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "refresh every"
            SetSlider {
                from: 5; to: 120; step: 5; unit: "min"
                value: page.d.weatherRefreshMin
                onMoved: (v) => { page.d.weatherRefreshMin = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "world clocks"
        SetRow {
            label: "zone 1"
            SetTextField {
                fieldWidth: 240
                value: page.d.tz1
                onCommitted: (t) => { page.d.tz1 = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "zone 2"
            SetTextField {
                fieldWidth: 240
                value: page.d.tz2
                onCommitted: (t) => { page.d.tz2 = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "zone 3"
            SetTextField {
                fieldWidth: 240
                value: page.d.tz3
                onCommitted: (t) => { page.d.tz3 = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "zone 4"
            SetTextField {
                fieldWidth: 240
                value: page.d.tz4
                onCommitted: (t) => { page.d.tz4 = t; SettingsStore.save(); }
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
