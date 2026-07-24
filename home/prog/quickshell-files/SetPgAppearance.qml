import QtQuick

// Appearance = Theme + Palette generation + Window frame + Motion + Wallpaper.
// (Wallpaper drives the palette via wal, so it lives with colours, not apps.)
Column {
    id: page
    width: parent ? parent.width : 480
    spacing: 4

    property var d: SettingsStore.d

    SetSection {
        title: "theme"
        SetRow {
            label: "colour source"
            desc: "auto = recolour from the wallpaper (wal); manual = fixed accent below"
            SetSelect {
                options: ["auto", "manual"]
                value: page.d.themeMode
                onChanged: (v) => { page.d.themeMode = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "accent colour"
            desc: "used when colour source is manual"
            SetColor {
                value: page.d.accentOverride
                onChanged: (h) => { page.d.accentOverride = h; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "font family"
            SetTextField {
                fieldWidth: 200
                value: page.d.fontFamily
                onCommitted: (t) => { page.d.fontFamily = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "font size"
            desc: "pixels; matched to the terminal cell"
            SetSlider {
                from: 10; to: 24; step: 1; unit: "px"
                value: page.d.fontSize
                onMoved: (v) => { page.d.fontSize = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "palette generation"
        SetRow {
            label: "colour count"
            desc: "clusters wal quantises the wallpaper into"
            SetSlider {
                from: 8; to: 32; step: 1
                value: page.d.paletteColorCount
                onMoved: (v) => { page.d.paletteColorCount = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "pure black background"
            desc: "force bg to #000000 instead of the darkest wallpaper tone"
            SetToggle {
                checked: page.d.pureBlackBg
                onToggled: (v) => { page.d.pureBlackBg = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "window frame"
        SetRow {
            label: "border width"
            SetSlider {
                from: 0; to: 6; step: 1; unit: "px"
                value: page.d.windowBorderWidth
                onMoved: (v) => { page.d.windowBorderWidth = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "corner rounding"
            SetSlider {
                from: 0; to: 20; step: 1; unit: "px"
                value: page.d.windowRounding
                onMoved: (v) => { page.d.windowRounding = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "tint tray icons"
            desc: "recolour system-tray icons to the accent"
            SetToggle {
                checked: page.d.trayTint
                onToggled: (v) => { page.d.trayTint = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "motion"
        SetRow {
            label: "reduce motion"
            desc: "disable slide/fan animations"
            SetToggle {
                checked: page.d.reduceMotion
                onToggled: (v) => { page.d.reduceMotion = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "animation speed"
            desc: "multiplier on the 220ms base slide"
            SetSlider {
                from: 0.5; to: 2.0; step: 0.1; unit: "x"
                value: page.d.animSpeed
                onMoved: (v) => { page.d.animSpeed = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "wallpaper"
        SetRow {
            label: "wallpaper folder"
            SetTextField {
                fieldWidth: 220
                value: page.d.wallpaperDir
                onCommitted: (t) => { page.d.wallpaperDir = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "fit"
            desc: "auto decides tile vs scale from image size"
            SetSelect {
                options: ["auto", "tile", "scale"]
                value: page.d.wallpaperFit
                onChanged: (v) => { page.d.wallpaperFit = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "sort order"
            SetSelect {
                options: ["name", "mtime", "random"]
                value: page.d.wallpaperSort
                onChanged: (v) => { page.d.wallpaperSort = v; SettingsStore.save(); }
            }
        }
    }
}
