import QtQuick

// Panel = the bar surface and its taskbar. The desktop-widget set, the
// monitoring widget's thresholds/sensors, etc. live on the Widgets page.
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
}
