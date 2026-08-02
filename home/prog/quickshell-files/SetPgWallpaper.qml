import QtQuick
import Quickshell.Io

// Wallpaper — the FIRST page of the settings program. The wallpaper drives the
// whole palette (wal recolours the desktop from it), so it leads: pick one here
// and every colour follows.
//
// The picker itself is the panel's meta+w switcher (WallpaperPicker.qml). It
// lives in the PANEL process, not this one, so the button reaches it the same
// way the keybind does — `qs ipc call wallpaper toggle` — rather than
// instantiating a second copy of the switcher here.
//
// "no wallpaper" paints the theme's own background colour as the desktop instead
// of an image (honoured in WallpaperLayer.qml). The palette still comes from a
// wallpaper — each one has generated one — so the same picker chooses WHICH
// palette colours the desktop; the image just isn't drawn.
Column {
    id: page
    width: parent ? parent.width : 480
    spacing: 4

    property var d: SettingsStore.d

    // Toggle the panel's wallpaper/theme switcher. A fresh run each click: set
    // running false first so a second press re-fires even if the last spawn
    // hasn't been reaped.
    Process { id: pickerProc; command: ["qs", "ipc", "call", "wallpaper", "toggle"] }

    SetSection {
        title: "wallpaper"
        SetRow {
            label: page.d.wallpaperSolid ? "choose palette" : "change wallpaper"
            desc: page.d.wallpaperSolid
                ? "opens the switcher — flip through your wallpapers to pick which palette colours the desktop"
                : "opens the switcher — flip through your wallpapers; each one also recolours the whole desktop"
            SetButton {
                text: "open picker"
                onClicked: { pickerProc.running = false; pickerProc.running = true; }
            }
        }
        SetRow {
            label: "no wallpaper"
            desc: "on = paint the theme's background colour instead of an image; turn off 'pure black background' under appearance to tint it from the chosen palette"
            SetToggle {
                checked: page.d.wallpaperSolid
                onToggled: (v) => { page.d.wallpaperSolid = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "wallpaper folder"
            desc: "browsed by the picker; ~/Pictures/wall stays the auto-versioned drop folder"
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
