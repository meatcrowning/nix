import QtQuick
import Quickshell.Io

// Appearance = Theme + Palette generation + RGB lighting + Window frame +
// Motion + Wallpaper.
// (Wallpaper drives the palette via wal, so it lives with colours, not apps.)
Column {
    id: page
    width: parent ? parent.width : 480
    spacing: 4

    property var d: SettingsStore.d

    // The RGB section is drawn ONLY on top — book is a MacBook with no OpenRGB
    // devices and no openrgb.service, so the toggle there would be the inert
    // control docs/DESIGN.md §10 forbids. Read via `hostname`, same as
    // SetPgSession.qml's lid gate: absent until the answer arrives, never
    // wrongly present.
    property bool hasRgb: false
    Process {
        running: true
        command: ["hostname"]
        stdout: StdioCollector { onStreamFinished: page.hasRgb = (this.text || "").trim() === "top" }
    }

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
            // The picked colour supplies the HUE; the palette is still built
            // by wal-extract.py's value ladder, so the accent comes back
            // pastel-capped exactly like a wallpaper-derived one (docs/DESIGN.md
            // 3.1). Saying so here, because "I picked #ff0000 and got a pale
            // red" otherwise reads as the control not working.
            label: "accent colour"
            desc: "hue used when colour source is manual; still pastel-capped like a wallpaper accent"
            SetColor {
                value: page.d.accentOverride
                onChanged: (h) => { page.d.accentOverride = h; SettingsStore.save(); }
            }
        }
        SetRow {
            // The desktop's pixel font. One key (fontFamily) drives Theme.font in
            // the panel AND DeskStyle.fontFamily in the apps, so flipping it here
            // switches the whole desktop live via settings.json. The faces offered
            // are enumerated from home/pkgs/desktop/font.nix (the selectableFaces
            // list) through the generated FontFaces singleton, so a face added to
            // font.nix appears here automatically — including Botis 4x6.
            label: "pixel font"
            desc: "the face the desktop draws with; more perfect is the default"
            SetSelect {
                options: FontFaces.families
                labels: FontFaces.labels
                value: page.d.fontFamily
                onChanged: (v) => { page.d.fontFamily = v; SettingsStore.save(); }
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
        SetRow {
            // Polarity axis over the same wallpaper-derived hue: wal-extract.py
            // inverts its value ladder so the background is white and the ink is
            // the dark end of the hue. Orthogonal to colour source and full
            // palette; every downstream surface (kitty, Qt/KDE, hyprvtb) follows
            // the twelve tokens with no further knowledge of polarity.
            label: "light mode"
            desc: "on = a light background with dark ink, from the same wallpaper hue"
            SetToggle {
                checked: page.d.lightMode
                // Enabling light mode forces "pure black background" off: a
                // black-titled control is a lie on a white desktop, and the two
                // extremes fight (the light-mode analogue is pure WHITE, chosen
                // by the same pureBlackBg key). The pure-black toggle flips off
                // in the UI as this writes, so nothing hidden diverges.
                onToggled: (v) => {
                    page.d.lightMode = v;
                    if (v) page.d.pureBlackBg = false;
                    SettingsStore.save();
                }
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
            desc: "off = bg takes the theme hue's extreme tone instead (darkest, or lightest in light mode)"
            SetToggle {
                checked: page.d.pureBlackBg
                onToggled: (v) => { page.d.pureBlackBg = v; SettingsStore.save(); }
            }
        }
        SetRow {
            // Opt-in departure from the one-hue palette (docs/DESIGN.md 3.1):
            // on = frames take the wallpaper's SECOND colour and the status ramp
            // takes real green/amber/red/blue, so the desktop reads as several
            // wallpaper colours rather than shades of one. Off is the default.
            label: "full palette"
            desc: "on = build a whole multi-colour palette from the wallpaper, not one accent + shades"
            SetToggle {
                checked: page.d.paletteFull
                onToggled: (v) => { page.d.paletteFull = v; SettingsStore.save(); }
            }
        }
        SetRow {
            // A global chroma/value transform over the full palette. Only bites
            // when full palette is on; in the default one-hue mode the look is
            // already the settled pastel and this is inert.
            label: "variant"
            desc: "full-palette style: vivid = punchy, muted = washed, pastel = soft (default)"
            SetSelect {
                options: ["vivid", "muted", "pastel"]
                value: page.d.paletteVariant
                onChanged: (v) => { page.d.paletteVariant = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "rgb lighting"
        visible: page.hasRgb
        SetRow {
            label: "follow the theme"
            desc: "off = the DRAM and case lights keep their current colour instead of taking each new accent"
            SetToggle {
                checked: page.d.rgbFollowTheme
                onToggled: (v) => { page.d.rgbFollowTheme = v; SettingsStore.save(); }
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
            // Desktop-wide: it reaches all seven apps through settings.json ->
            // pylib/deskstyle.py -> apps/qmlcommon/VScroll.qml. It sits under
            // Appearance beside the font and the motion controls because those
            // are the other two settings that cross the app boundary the same
            // way; the panel draws no scrollbar of its own.
            // Labels rather than raw keys: "win 3.1" is what he called it.
            label: "scrollbars"
            desc: "win 3.1 = arrows + bevel; beveled = no arrows; flat = plain pixel block"
            SetSelect {
                options: ["win31", "beveled", "flat"]
                labels: ({ win31: "win 3.1", beveled: "beveled", flat: "flat" })
                value: page.d.scrollbarStyle
                onChanged: (v) => { page.d.scrollbarStyle = v; SettingsStore.save(); }
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
