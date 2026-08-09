"""The desktop's typography and motion settings, read from the panel's store.

docs/DESIGN.md §2.1 is a single rule for the whole desktop: one font, at kitty's
size, in the panel, the titlebar and all six apps. The panel already obeys the
Settings window's "font family" / "font size" controls — its `Theme.qml` binds
straight to `SettingsStore.d.fontFamily` / `.fontSize` — but each app carried its
own hardcoded `"More Perfect DOS VGA"` / `15`, so the slider moved the panel and
the titlebars and left all six apps behind. This module is the apps' half of
that binding.

**The source of truth is the panel's `settings.json`, not its `Theme.qml`.** The
apps already parse `~/.config/quickshell/Theme.qml` for the wallpaper palette
(the `Palette` class in every `main.py`), so that file is the obvious place to
look — but the palette is written there as *literals* by `wal-set.sh`, whereas
the font keys are QML *expressions* (`SettingsStore.d.fontSize`) that only
Quickshell can evaluate. Parsing them out would yield the string
"SettingsStore.d.fontSize". `~/.config/quickshell/settings.json` is what
`SettingsStore` itself persists, so reading it is reading the same value the
panel reads — not a second source of truth.

Usage mirrors `WalPalette`: instantiate once in `main()`, install as a root
context property BEFORE the app's `Theme.qml` is created (its bindings resolve
at construction), and keep a Python reference for the process's lifetime.

    from deskstyle import DeskStyle
    style = DeskStyle()
    ctx.setContextProperty("DeskStyle", style)   # then instantiate Theme.qml

Set `DESK_SETTINGS` in the environment to point at another JSON file; that is
how the offscreen layout tests render at a non-default size without touching
the user's live settings.

It carries the two MOTION settings for the same reason (docs/DESIGN.md §6.2):
`reduceMotion` and `animSpeed` are Settings > Appearance controls that the panel
applies in `ViewMode.ms()`, and `qmlcommon/Motion.qml` is the apps' half of the
same function — it reads both off `DeskStyle` behind a `typeof` guard. Until
they were published here, every app's `motion.ms()` silently used the 1.0/false
fallback, so the two controls moved the panel and left all six apps behind, in
exactly the way the font size did.

It carries `scrollbarStyle` (docs/DESIGN.md 9.2) for the third time on the same
argument. That one is unusual in that the panel does not consume it at all — the
panel has no scrollbar anywhere — so it is a setting that lives in the panel's
store and is read only by the apps. That is deliberate: settings.json is the one
channel a Settings-window control has into `apps/`, and a second one would be a
second thing to keep in sync for no gain.
"""

import json
import math
import os
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, Property, Signal
from PySide6.QtGui import QFont, QFontMetrics

# Written by the panel's SettingsStore (Quickshell.shellDir + "/settings.json").
SETTINGS_PATH = Path.home() / ".config" / "quickshell" / "settings.json"

# Must match SettingsStore.qml's inline defaults, and SetPgAppearance.qml's
# slider bounds. A value outside the range means a hand-edited or corrupt file,
# and a font size of 0 (or 400) is unrecoverable from inside a GUI, so clamp.
DEFAULT_FONT_FAMILY = "More Perfect DOS VGA"
DEFAULT_FONT_SIZE = 15
MIN_FONT_SIZE = 10
MAX_FONT_SIZE = 24

# Faces that are normal smooth outlines and must be ANTIALIASED, never
# pixel-snapped (currently just Phenex, the hand-authored cursive). Twin of
# the `smooth` flag in home/pkgs/desktop/font.nix selectableFaces / the
# generated FontFaces.qml — keep the two in step. Everything font-rendering
# branches on `DeskStyle.smooth`: PixelText's renderType/antialiasing, and
# editorFont's style strategy below.
SMOOTH_FAMILIES = {"Phenex"}

# Motion, likewise from SettingsStore.qml's inline defaults. The validation is
# the panel's, not the slider's: `ViewMode.ms()` accepts any finite animSpeed
# > 0 and falls back to 1.0 otherwise, and it must stay that way here or an
# animSpeed outside the slider's 0.5..2.0 would scale the panel and the apps by
# different amounts — two speeds on one desktop, which is the whole thing §6.2
# exists to prevent. A 0 or a string is rejected because it would freeze or NaN
# every animation in the app at once.
DEFAULT_REDUCE_MOTION = False
DEFAULT_ANIM_SPEED = 1.0

# Which scrollbar apps/qmlcommon/VScroll.qml draws (docs/DESIGN.md 9.2). The
# panel has no scrollbar anywhere, so this key's only consumers are the apps —
# it still lives in the panel's settings.json because that file IS the
# cross-app settings channel, and a second one would be a second thing to keep
# in sync. Validate against the known set rather than passing the string
# through: an unknown value would silently draw nothing, and VScroll's own
# fallback (for a harness with no DeskStyle at all) is the same default.
SCROLLBAR_STYLES = ("win31", "beveled", "flat")
DEFAULT_SCROLLBAR_STYLE = "win31"


def settings_path():
    return Path(os.environ.get("DESK_SETTINGS") or SETTINGS_PATH)


class DeskStyle(QObject):
    """Live `fontFamily` / `fontSize` / `reduceMotion` / `animSpeed` /
    `scrollbarStyle` / `borderWidth` / `rounding`.

    Watches the file AND its directory. The directory watch is the load-bearing
    one: SettingsStore writes atomically (temp file + rename), which swaps the
    inode out from under a plain file watch, so the file-only signal is exactly
    what an atomic write fails to deliver. The panel works around the same thing
    by polling; a directory watch costs nothing and needs no timer.
    """

    changed = Signal()

    def __init__(self, path=None, parent=None):
        super().__init__(parent)
        self._path = Path(path) if path else settings_path()
        self._family = DEFAULT_FONT_FAMILY
        self._size = DEFAULT_FONT_SIZE
        self._reduce = DEFAULT_REDUCE_MOTION
        self._speed = DEFAULT_ANIM_SPEED
        self._scrollbar = DEFAULT_SCROLLBAR_STYLE
        self._border = 2
        self._rounding = 0
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_change)
        self._watcher.directoryChanged.connect(self._on_change)
        self._rewatch()
        self._load()

    def _rewatch(self):
        want = [str(self._path.parent), str(self._path)]
        have = set(self._watcher.files()) | set(self._watcher.directories())
        for p in want:
            if p not in have and os.path.exists(p):
                self._watcher.addPath(p)

    def _on_change(self, _path):
        self._rewatch()
        self._load()

    def _load(self):
        try:
            with open(self._path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return  # missing or half-written: keep the last good values
        if not isinstance(data, dict):
            return
        family = data.get("fontFamily")
        if not isinstance(family, str) or not family.strip():
            family = DEFAULT_FONT_FAMILY
        size = data.get("fontSize")
        if not isinstance(size, (int, float)) or isinstance(size, bool):
            size = DEFAULT_FONT_SIZE
        size = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, int(size)))
        reduce_motion = data.get("reduceMotion")
        if not isinstance(reduce_motion, bool):
            reduce_motion = DEFAULT_REDUCE_MOTION
        speed = data.get("animSpeed")
        if isinstance(speed, bool) or not isinstance(speed, (int, float)):
            speed = DEFAULT_ANIM_SPEED
        speed = float(speed)
        if not math.isfinite(speed) or speed <= 0:
            speed = DEFAULT_ANIM_SPEED
        bar = data.get("scrollbarStyle")
        if bar not in SCROLLBAR_STYLES:
            bar = DEFAULT_SCROLLBAR_STYLE
        border = data.get("windowBorderWidth")
        if isinstance(border, bool) or not isinstance(border, (int, float)):
            border = 2
        border = max(0, min(6, int(border)))
        rounding = data.get("windowRounding")
        if isinstance(rounding, bool) or not isinstance(rounding, (int, float)):
            rounding = 0
        rounding = max(0, min(20, int(rounding)))
        now = (family, size, reduce_motion, speed, bar, border, rounding)
        if now != (self._family, self._size, self._reduce, self._speed,
                   self._scrollbar, self._border, self._rounding):
            (self._family, self._size, self._reduce, self._speed,
             self._scrollbar, self._border, self._rounding) = now
            self.changed.emit()

    @Property(str, notify=changed)
    def fontFamily(self):
        return self._family

    @Property(int, notify=changed)
    def fontSize(self):
        return self._size

    @Property(int, notify=changed)
    def borderWidth(self):
        """The desktop's global border width (Settings > appearance > theme >
        border width, settings.json windowBorderWidth) — the same number the
        compositor draws real window borders at and the panel draws its
        surfaces with. For any border an app draws itself."""
        return self._border

    @Property(int, notify=changed)
    def rounding(self):
        """The desktop's global corner rounding (windowRounding) — the radius
        the compositor clips every window to. For any corner an app rounds
        itself."""
        return self._rounding

    @Property(bool, notify=changed)
    def smooth(self):
        """True when the live face is a normal smooth outline (SMOOTH_FAMILIES)
        rather than a pixel one. PixelText.qml branches its render path on
        this: pixel faces keep NativeRendering + antialiasing:false +
        full hinting; a smooth face gets antialiased, unhinted rendering —
        under the pixel pipeline a cursive face is a jagged staircase."""
        return self._family in SMOOTH_FAMILIES

    @Property(QFont, notify=changed)
    def editorFont(self):
        """The desktop font as a QFont with the rasterisation pinned — for
        editable items ONLY (`TextEdit`/`TextInput`).

        A `Text` honours `antialiasing: false` and draws a scalable pixel font
        (the default "More Perfect DOS VGA") as crisp mono glyphs. An *editable*
        item does NOT: `QQuickTextEdit`/`QQuickTextInput` ignore the QML
        `antialiasing` and `renderType` levers for glyph rasterisation and draw
        grey-fringed AA glyphs regardless of the face (the pixel faces are
        scalable outlines, so none escapes it on its own). The one lever
        that reaches the font engine is `QFont::NoAntialias`, which the QML
        `font` group cannot express — so it is set here and bound as a whole
        `font:` (docs/DESIGN.md §2.2). Verified: 17 grey levels in a glyph -> 2.

        For a SMOOTH face the pin flips the other way: editable items already
        antialias, which is exactly what a cursive outline wants — so no
        NoAntialias, and no hinting (matching PixelText and fontconfig; full
        hinting visibly kinks the connected joins)."""
        f = QFont(self._family)
        f.setPixelSize(self._size)
        if self._family in SMOOTH_FAMILIES:
            f.setHintingPreference(QFont.PreferNoHinting)
        else:
            f.setHintingPreference(QFont.PreferFullHinting)
            f.setStyleStrategy(QFont.NoAntialias)
        return f

    @Property(int, notify=changed)
    def lineHeight(self):
        """One text row: the LIVE FACE's cell, not the em size we asked for.

        docs/DESIGN.md §2.1 — "a text-only row is exactly one font cell tall,
        with zero inter-row gap", and the cell is the face's own
        `ascent + descent`, which is only sometimes `fontSize`. The panel has
        had this since it was written (`Theme.qml`, `Math.round(metrics.height)`
        off a QML `FontMetrics`); the apps never did, so every app row was
        pinned to `fontSize` and inherited whatever gap that left.

        Measured on `top` 2026-08-07, `QFontMetrics.height()` per face:

            px:                  10   15   17   24
            More Perfect DOS VGA 11   15   17   24
            Perfect DOS VGA 437  11   15   17   24
            Botis 4x6             8   12   13   19

        So the two coincide for the DOS pair only in the middle of the slider —
        at 10px even they are a pixel out — and **Botis is 3px short at the
        default 15**, which is the dead leading under every label in every app
        that this property exists to remove. Bind `lineHeight` for anything that
        means "one text row"; bind `fontSize` only for an actual font size.
        """
        f = QFont(self._family)
        f.setPixelSize(self._size)
        f.setHintingPreference(QFont.PreferFullHinting)
        return max(1, QFontMetrics(f).height())

    @Property(bool, notify=changed)
    def reduceMotion(self):
        return self._reduce

    @Property(float, notify=changed)
    def animSpeed(self):
        return self._speed

    @Property(str, notify=changed)
    def scrollbarStyle(self):
        return self._scrollbar
