import QtQuick

// Panel & Widgets = the bar surface + the desktop-widget set + the monitoring
// widget's thresholds/sensors (its detail pane folds in here).
Column {
    id: page
    width: parent ? parent.width : 480
    spacing: 4

    property var d: SettingsStore.d

    SetSection {
        title: "bar"
        SetRow {
            label: "width"
            SetSlider {
                from: 32; to: 80; step: 1; unit: "px"
                value: page.d.barWidth
                onMoved: (v) => { page.d.barWidth = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "screen edge"
            SetSelect {
                options: ["left", "right"]
                value: page.d.barEdge
                onChanged: (v) => { page.d.barEdge = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "spacing"
            desc: "gap between bar clusters"
            SetSlider {
                from: 2; to: 20; step: 1; unit: "px"
                value: page.d.barGap
                onMoved: (v) => { page.d.barGap = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "button size"
            SetSlider {
                from: 28; to: 56; step: 1; unit: "px"
                value: page.d.barCell
                onMoved: (v) => { page.d.barCell = v; SettingsStore.save(); }
            }
        }
    }

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
        title: "taskbar"
        SetRow {
            label: "click active minimizes"
            desc: "click a focused app's icon to minimize it"
            SetToggle {
                checked: page.d.taskbarClickMinimizes
                onToggled: (v) => { page.d.taskbarClickMinimizes = v; SettingsStore.save(); }
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
            desc: "auto picks the default route"
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
}
