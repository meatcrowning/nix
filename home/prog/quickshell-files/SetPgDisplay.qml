import QtQuick

// Display & Brightness — brightness control backend and colour temperature.
// (Kept apart from Appearance: this is hardware, not styling.)
Column {
    id: page
    width: parent ? parent.width : 480
    spacing: 4

    property var d: SettingsStore.d

    SetSection {
        title: "brightness"
        SetRow {
            label: "step"
            desc: "change per scroll / key press"
            SetSlider {
                from: 1; to: 20; step: 1; unit: "%"
                value: page.d.brightnessStep
                onMoved: (v) => { page.d.brightnessStep = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "backend"
            desc: "auto = backlight if present, else DDC/CI to an external monitor"
            SetSelect {
                options: ["auto", "backlight", "ddc"]
                value: page.d.brightnessBackend
                onChanged: (v) => { page.d.brightnessBackend = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "colour temperature"
        SetRow {
            label: "night light"
            desc: "warm the display on a schedule"
            SetToggle {
                checked: page.d.nightLight
                onToggled: (v) => { page.d.nightLight = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "warmth"
            desc: "lower kelvin = warmer"
            SetSlider {
                from: 2500; to: 6500; step: 100; unit: "K"
                value: page.d.nightTemp
                onMoved: (v) => { page.d.nightTemp = v; SettingsStore.save(); }
            }
        }
    }
}
