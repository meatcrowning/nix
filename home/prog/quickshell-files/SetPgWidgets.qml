import QtQuick

// Widgets — everything that drives the desktop widgets that fan out on the
// session: which set is shown at login and the cascade timing, the monitoring
// widget's thresholds/sensors, the media widget's spectrum/player, plus the
// clock/calendar, weather, and world-clock data those widgets render.
Column {
    id: page
    width: parent ? parent.width : 480
    spacing: 4

    property var d: SettingsStore.d

    // world-clock list mutators — a JsonAdapter `var` only emits a change (so the
    // panel's clock and this Repeater update) when the whole array is REASSIGNED,
    // never on in-place edits, so each helper works on a copy and assigns it back.
    function _wcSet(i, tz) { const a = (d.worldClocks || []).slice(); a[i] = tz; d.worldClocks = a; SettingsStore.save(); }
    function _wcAdd()      { const a = (d.worldClocks || []).slice(); a.push(""); d.worldClocks = a; SettingsStore.save(); }
    function _wcRemove(i)  { const a = (d.worldClocks || []).slice(); a.splice(i, 1); d.worldClocks = a; SettingsStore.save(); }

    SetSection {
        title: "desktop widgets"
        SetRow {
            label: "shown at login"
            desc: "which widgets fan out on a fresh session"
            // full-width chips wrap below the label on narrow layouts
        }
        SetChips {
            options: ["clock", "weather", "disk", "media", "cpu", "gpu", "eth", "calendar"]
            selected: page.d.defaultWidgets
            onChanged: (vs) => { page.d.defaultWidgets = vs; SettingsStore.save(); }
        }
        Item { width: 1; height: 6 }
        SetRow {
            label: "fan step"
            desc: "delay between cascade stages when revealing all"
            SetSlider {
                from: 100; to: 600; step: 10; unit: "ms"
                value: page.d.fanStepMs
                onMoved: (v) => { page.d.fanStepMs = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "monitoring"
        SetRow {
            label: "poll interval"
            desc: "how often sensors refresh"
            SetSlider {
                from: 1; to: 10; step: 1; unit: "s"
                value: page.d.monPollSec
                onMoved: (v) => { page.d.monPollSec = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "cpu / gpu usage warn"
            SetSlider {
                from: 40; to: 100; step: 1; unit: "%"
                value: page.d.cpuWarn
                onMoved: (v) => { page.d.cpuWarn = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "cpu / gpu usage critical"
            SetSlider {
                from: 40; to: 100; step: 1; unit: "%"
                value: page.d.cpuCrit
                onMoved: (v) => { page.d.cpuCrit = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "temperature warn"
            SetSlider {
                from: 40; to: 100; step: 1; unit: "°C"
                value: page.d.tempWarn
                onMoved: (v) => { page.d.tempWarn = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "temperature critical"
            SetSlider {
                from: 40; to: 110; step: 1; unit: "°C"
                value: page.d.tempCrit
                onMoved: (v) => { page.d.tempCrit = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "disk usage warn"
            SetSlider {
                from: 40; to: 100; step: 1; unit: "%"
                value: page.d.diskWarn
                onMoved: (v) => { page.d.diskWarn = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "disk usage critical"
            SetSlider {
                from: 40; to: 100; step: 1; unit: "%"
                value: page.d.diskCrit
                onMoved: (v) => { page.d.diskCrit = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "battery low warn"
            SetSlider {
                from: 5; to: 60; step: 1; unit: "%"
                value: page.d.batteryWarn
                onMoved: (v) => { page.d.batteryWarn = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "battery low critical"
            SetSlider {
                from: 1; to: 40; step: 1; unit: "%"
                value: page.d.batteryCrit
                onMoved: (v) => { page.d.batteryCrit = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "network interface"
            desc: "auto sums every interface except lo"
            SetTextField {
                fieldWidth: 120
                value: page.d.netInterface
                onCommitted: (t) => { page.d.netInterface = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "disk mount"
            desc: "filesystem shown in the bar's free/used readout"
            SetTextField {
                fieldWidth: 120
                value: page.d.rootMount
                onCommitted: (t) => { page.d.rootMount = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "SMART on SSD/NVMe only"
            desc: "skip health polling on spinning disks"
            SetToggle {
                checked: page.d.smartSsdOnly
                onToggled: (v) => { page.d.smartSsdOnly = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "media widget"
        SetRow {
            label: "spectrum bars"
            SetSlider {
                from: 4; to: 32; step: 1
                value: page.d.mediaSpectrumBars
                onMoved: (v) => { page.d.mediaSpectrumBars = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "prefer playing source"
            desc: "auto-follow whichever player is actively playing"
            SetToggle {
                checked: page.d.mediaPreferPlaying
                onToggled: (v) => { page.d.mediaPreferPlaying = v; SettingsStore.save(); }
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
            label: "zones"
            desc: "Olson names (e.g. Europe/London), top-to-bottom in the clock popup"
        }

        // one editable row per zone: the TZ field + a remove button. Reassigning
        // page.d.worldClocks rebuilds this Repeater in place.
        Repeater {
            model: page.d.worldClocks
            Row {
                id: wcRow
                required property int index
                required property var modelData
                spacing: 6
                bottomPadding: 4

                SetTextField {
                    fieldWidth: 240
                    placeholder: "Region/City"
                    value: wcRow.modelData
                    onCommitted: (t) => page._wcSet(wcRow.index, t.trim())
                }
                // remove this zone
                Rectangle {
                    width: 24; height: 24
                    color: rmMa.containsMouse ? Theme.bgAlt : "transparent"
                    radius: Theme.windowRounding
                    border.width: Theme.ctrlBorder
                    border.color: rmMa.containsMouse ? Theme.crit : Theme.border
                    PixelText {
                        anchors.centerIn: parent
                        text: "-"
                        color: rmMa.containsMouse ? Theme.crit : Theme.textDim
                    }
                    MouseArea {
                        id: rmMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page._wcRemove(wcRow.index)
                    }
                }
            }
        }

        // add a new (blank) zone row
        Rectangle {
            width: addT.implicitWidth + 20
            height: 24
            color: addMa.containsMouse ? Theme.bgAlt : "transparent"
            radius: Theme.windowRounding
            border.width: Theme.ctrlBorder
            border.color: addMa.containsMouse ? Theme.accent : Theme.border
            PixelText {
                id: addT
                anchors.centerIn: parent
                text: "+ add zone"
                color: addMa.containsMouse ? Theme.accent : Theme.text
            }
            MouseArea {
                id: addMa
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: page._wcAdd()
            }
        }
    }
}
