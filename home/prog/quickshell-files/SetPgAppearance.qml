import QtQuick
import Quickshell.Io

// Appearance = Paper + theme (the embedded chooser) + Wallpaper + Theme
// (accent, font, palette + the swatch picker, rgb) + Titlebar + Window
// decorations + Motion.
// (The wallpaper DRIVES this palette via wal, so it leads: it is the top
// section, not a separate page.)
Column {
    id: page
    width: parent ? parent.width : 480
    spacing: 4

    property var d: SettingsStore.d

    // The Meta+W picker's tiles, embedded in the page: a horizontally
    // paginated grid of paper + palette, flipped by the full-height page
    // buttons on its edges. Clicking a tile applies that wallpaper and its
    // theme — in solid mode ("display wallpaper" off) the palette changes and
    // the image simply stays hidden (WallpaperLayer.qml), same as the picker.
    SetSection {
        title: "paper + theme"
        SetPaperGrid { }
        SetRow {
            // Right-click any tile above (or in the Meta+W picker) to hide a
            // paper from both surfaces; this brings the hidden ones back —
            // dimmed and right-clickable to unhide — so hiding is never a
            // one-way trap (docs/DESIGN.md §10.2).
            label: "show hidden papers"
            SetToggle {
                checked: page.d.wallpaperShowHidden
                onToggled: (v) => { page.d.wallpaperShowHidden = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "wallpaper"
        SetRow {
            // The ONE control for this feature: show the wallpaper image, or fill
            // the desktop with a solid block of the theme's background colour
            // (Theme.bg — WallpaperLayer.qml). The theme is identical either way;
            // only the IMAGE is suppressed. Stored inverted as `wallpaperSolid`,
            // so on = image, off = solid.
            label: "display wallpaper"
            SetToggle {
                checked: !page.d.wallpaperSolid
                onToggled: (v) => { page.d.wallpaperSolid = !v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "wallpaper dir"
            SetTextField {
                fieldWidth: 220
                value: page.d.wallpaperDir
                onCommitted: (t) => { page.d.wallpaperDir = t; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "fit"
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

    // The rgb row is drawn ONLY on top — book is a MacBook with no OpenRGB
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
            // The stored key is still themeMode ("auto"/"manual") — the toggle
            // is just its face: on = manual, the fixed accent below; off =
            // recolour from the wallpaper (wal).
            label: "manual accent"
            SetToggle {
                checked: page.d.themeMode === "manual"
                onToggled: (v) => { page.d.themeMode = v ? "manual" : "auto"; SettingsStore.save(); }
            }
        }
        SetRow {
            // The picked colour supplies the HUE; the palette is still built
            // by wal-extract.py's value ladder, so the accent comes back
            // pastel-capped exactly like a wallpaper-derived one (docs/DESIGN.md
            // 3.1). Greyed, not hidden, while manual accent is off (§10.1) —
            // it still shows what turning the toggle on would use.
            label: "accent colour"
            SetColor {
                enabled: page.d.themeMode === "manual"
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
            label: "font"
            SetSelect {
                options: FontFaces.families
                labels: FontFaces.labels
                // the values are the family names themselves, so every row of
                // the dropdown is a specimen of the face it picks
                optionsAreFonts: true
                value: page.d.fontFamily
                // Through the store, not a direct write: it remembers the
                // size per face (fontSizeByFamily) across switches.
                onChanged: (v) => SettingsStore.setFontFamily(v)
            }
        }
        SetRow {
            label: "font size"
            SetSelect {
                options: {
                    const a = [];
                    for (let s = 10; s <= 24; s++) a.push(String(s));
                    return a;
                }
                value: String(page.d.fontSize)
                onChanged: (v) => { page.d.fontSize = parseInt(v, 10); SettingsStore.save(); }
            }
        }
        SetRow {
            // Polarity axis over the same wallpaper-derived hue: wal-extract.py
            // inverts its value ladder so the background is white and the ink is
            // the dark end of the hue. Orthogonal to colour source and full
            // palette; every downstream surface (kitty, Qt/KDE, hyprvtb) follows
            // the twelve tokens with no further knowledge of polarity.
            label: "light mode"
            SetToggle {
                checked: page.d.lightMode
                // Shared with the Meta+D keybind — see SettingsStore.setLightMode.
                // Enabling light mode forces "pure black background" off: a
                // black-titled control is a lie on a white desktop, and the two
                // extremes fight (the light-mode analogue is pure WHITE, chosen
                // by the same pureBlackBg key). The pure-black toggle flips off
                // in the UI as this writes, so nothing hidden diverges.
                onToggled: (v) => SettingsStore.setLightMode(v)
            }
        }
        SetRow {
            // The colour-count slider this replaced set how finely wal
            // quantises the wallpaper (paletteColorCount, still in the store,
            // no UI); this shows the resulting clusters themselves and lets
            // the actual colours be picked (paletteDropped -> wal-extract.py).
            label: "colours"
            SetSwatches { }
        }
        SetRow {
            // Dark-mode only. In light mode the toggle is greyed out and inert:
            // its light analogue is pure WHITE (a control labelled "pure black"
            // would be a lie there), and setLightMode already forces the key off
            // on the way in — so there is nothing here to change. With it OFF in
            // dark mode the background is now light mode's foreground and the
            // foreground light mode's background (wal-extract.py's fg/bg swap).
            label: "pure black background"
            SetToggle {
                checked: page.d.pureBlackBg
                enabled: !page.d.lightMode
                onToggled: (v) => { page.d.pureBlackBg = v; SettingsStore.save(); }
            }
        }
        SetRow {
            // A global chroma/value transform over the wallpaper-derived palette
            // (docs/DESIGN.md 3.1.2 — the full palette is always on now).
            label: "variant"
            SetSelect {
                options: ["vivid", "normal", "fidelity", "muted", "pastel"]
                value: page.d.paletteVariant
                onChanged: (v) => { page.d.paletteVariant = v; SettingsStore.save(); }
            }
        }
        SetRow {
            // GLOBAL, not just the panel's own surfaces: the same number is
            // the compositor's general:border_size (every program's window
            // border — SettingsApply.applyFrame + wal-set.sh persistence)
            // and the apps' DeskStyle.borderWidth.
            label: "border width"
            SetSlider {
                from: 0; to: 6; step: 1; unit: "px"
                value: page.d.windowBorderWidth
                onMoved: (v) => { page.d.windowBorderWidth = v; SettingsStore.save(); }
            }
        }
        SetRow {
            // GLOBAL likewise: decoration:rounding clips every window on the
            // desktop to this radius; the panel and apps read the same key.
            label: "corner rounding"
            SetSlider {
                from: 0; to: 20; step: 1; unit: "px"
                value: page.d.windowRounding
                onMoved: (v) => { page.d.windowRounding = v; SettingsStore.save(); }
            }
        }
        SetRow {
            // Drawn ONLY on top (hasRgb) — book has no OpenRGB devices and an
            // inert toggle is what docs/DESIGN.md §10 forbids.
            label: "rgb follows theme"
            visible: page.hasRgb
            SetToggle {
                checked: page.d.rgbFollowTheme
                onToggled: (v) => { page.d.rgbFollowTheme = v; SettingsStore.save(); }
            }
        }
    }

    // The titlebar (hyprvtb) — its own section so the controls that shape the
    // compositor-drawn bar sit together: orientation, side, compact, its drop
    // shadow and its unfocused dimming (docs/DESIGN.md 12). The rows below in
    // "window decorations" are the desktop-wide chrome that is NOT the bar.
    SetSection {
        title: "titlebar"
        // Side, orientation and compact are set by direct manipulation on an
        // interactive mock of the bar — the three GLOBAL knobs only; there is
        // no global key for which app buttons show (they are per-app over the
        // vtbclient socket). It writes the same store keys the old three rows
        // did, so SettingsApply.qml's live-apply is unchanged.
        SetTitlebarMock { }
        SetRow {
            label: "drop shadow"
            SetSlider {
                from: 0; to: 1; step: 0.05
                value: page.d.shadowAlpha
                onMoved: (v) => { page.d.shadowAlpha = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "dim unfocused windows"
            SetToggle {
                checked: page.d.dimUnfocused
                onToggled: (v) => { page.d.dimUnfocused = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "window decorations"
        SetRow {
            // Desktop-wide: it reaches all seven apps through settings.json ->
            // pylib/deskstyle.py -> apps/qmlcommon/VScroll.qml. It sits under
            // Appearance beside the font and the motion controls because those
            // are the other two settings that cross the app boundary the same
            // way; the panel draws no scrollbar of its own.
            // Labels rather than raw keys: "win 3.1" is what he called it.
            label: "scrollbars"
            SetSelect {
                options: ["win31", "beveled", "flat"]
                labels: ({ win31: "win 3.1", beveled: "beveled", flat: "flat" })
                value: page.d.scrollbarStyle
                onChanged: (v) => { page.d.scrollbarStyle = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "tint tray icons"
            SetToggle {
                checked: page.d.trayTint
                onToggled: (v) => { page.d.trayTint = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "shortcut notch"
            SetToggle {
                checked: page.d.desktopIcons
                onToggled: (v) => { page.d.desktopIcons = v; SettingsStore.save(); }
            }
        }
    }

    SetSection {
        title: "motion"
        SetRow {
            label: "reduce motion"
            SetToggle {
                checked: page.d.reduceMotion
                onToggled: (v) => { page.d.reduceMotion = v; SettingsStore.save(); }
            }
        }
        SetRow {
            label: "animation speed"
            SetSlider {
                from: 0.5; to: 2.0; step: 0.1; unit: "x"
                value: page.d.animSpeed
                onMoved: (v) => { page.d.animSpeed = v; SettingsStore.save(); }
            }
        }
    }

}
