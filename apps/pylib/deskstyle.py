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

**In a PLASMA session the store is `kdeglobals` instead**, for the whole of the
above: family, size, the two motion settings and the scrollbar. That session's
appearance belongs to the KDE global theme he picked in System Settings, which
every other Qt app on the box already obeys — an app still drawing the panel's
pixel font there is the one window that ignores the theme. The switch is
`kdetheme.is_plasma()` and it is the same switch that moves the palette
(`kdetheme.py`, which owns the mapping and the reasoning); nothing downstream —
no `Theme.qml`, no binding, no component — knows which session it is in.
"""

import json
import math
import os
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, Property, Signal
from PySide6.QtGui import QFont, QFontMetrics

from kdetheme import is_plasma, kde_font, kde_motion, kdeglobals_path, read_ini

# Written by the panel's SettingsStore (Quickshell.shellDir + "/settings.json").
SETTINGS_PATH = Path.home() / ".config" / "quickshell" / "settings.json"

# Must match SettingsStore.qml's inline defaults, and SetPgAppearance.qml's
# slider bounds. A value outside the range means a hand-edited or corrupt file,
# and a font size of 0 (or 400) is unrecoverable from inside a GUI, so clamp.
DEFAULT_FONT_FAMILY = "More Perfect DOS VGA"
DEFAULT_FONT_SIZE = 15
MIN_FONT_SIZE = 10
MAX_FONT_SIZE = 24

# The KDE session's own bounds. A KDE font size is HIS, set in System Settings
# against KDE's own preview, so it is not clamped to the panel slider's 10..24
# — only to what is legible at all. (The panel's own range is unchanged; this
# range applies only when the size came from kdeglobals.)
KDE_MIN_FONT_SIZE = 6
KDE_MAX_FONT_SIZE = 64

# Faces that are normal smooth outlines and must be ANTIALIASED, never
# pixel-snapped (Phenex the hand-authored cursive, and Tahoma the proportional
# MS TrueType). Twin of the `smooth` flag in home/pkgs/desktop/font.nix
# selectableFaces / the generated FontFaces.qml — keep the two in step.
# CozetteVector and Terminus are pixel/bitmap designs and stay OUT (crisp,
# pixel-snapped). Everything font-rendering branches on `DeskStyle.smooth`:
# PixelText's renderType/antialiasing, and editorFont's style strategy below.
SMOOTH_FAMILIES = {"Phenex", "Tahoma"}

# The other side of the same list, and it is needed only for the KDE branch:
# there the family is whatever System Settings holds, so `smooth` cannot be an
# allowlist of this desktop's own faces — a KDE font is a normal outline unless
# it is one of the pixel designs, which stay crisp if he pins one there too.
PIXEL_FAMILIES = {"More Perfect DOS VGA", "Perfect DOS VGA 437", "Botis 4x6",
                  "Botis", "CozetteVector", "Cozette", "Terminus",
                  "xos4 Terminus"}

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
        self._smooth = self._family in SMOOTH_FAMILIES
        self._plasma = is_plasma()
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_change)
        self._watcher.directoryChanged.connect(self._on_change)
        self._rewatch()
        self._load()

    def _rewatch(self):
        want = [str(self._path.parent), str(self._path)]
        if self._plasma:
            # Same file+directory pair, same reason: KDE rewrites kdeglobals by
            # temp-file-and-rename, so a file-only watch misses every change
            # System Settings makes.
            kg = kdeglobals_path()
            want += [str(kg.parent), str(kg)]
        have = set(self._watcher.files()) | set(self._watcher.directories())
        for p in want:
            if p not in have and os.path.exists(p):
                self._watcher.addPath(p)

    def _on_change(self, _path):
        self._rewatch()
        self._load()

    def _load(self):
        # Read ONCE per load, and before the panel's store: in a Plasma session
        # every type/motion key below is overridden from it, and a half-written
        # settings.json must not be able to skip that (`{}` there just leaves
        # the KDE branch on its own defaults).
        self._ini = read_ini() if self._plasma else {}
        try:
            with open(self._path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = None
        if not isinstance(data, dict):
            if not self._plasma or self._path.exists():
                return  # half-written (or not our file): keep the last good values
            data = {}   # no panel store at all, and KDE owns type/motion here
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
        smooth = family in SMOOTH_FAMILIES

        if self._plasma:
            # The KDE global theme owns type, motion and the scrollbar in this
            # session; the two GEOMETRY keys (border width, corner rounding) do
            # not move — they are his numbers for how this desktop's own
            # surfaces are framed, KDE publishes no equivalent, and a window
            # that changed shape between sessions would be the surprise.
            family, size, smooth = self._kde_type(family, size, smooth)
            reduce_motion, speed = kde_motion(self._ini)
            bar = "flat"   # beveled/win31 chrome inside a Breeze window is the
                           # one thing that would still read as "not themed"

        now = (family, size, reduce_motion, speed, bar, border, rounding, smooth)
        if now != (self._family, self._size, self._reduce, self._speed,
                   self._scrollbar, self._border, self._rounding, self._smooth):
            (self._family, self._size, self._reduce, self._speed,
             self._scrollbar, self._border, self._rounding, self._smooth) = now
            self.changed.emit()

    def _kde_type(self, family, size, smooth):
        """`kdeglobals [General] font=` as (family, PIXEL size, smooth).

        KDE stores a point size and this desktop draws in pixels everywhere
        (docs/DESIGN.md §2.1), so it is converted at the screen's own logical
        DPI rather than at an assumed 96 — book is a Retina panel and the two
        are not the same number there. With no QGuiApplication yet (a harness
        constructing DeskStyle bare) it falls back to 96.
        """
        got = kde_font(self._ini)
        if not got:
            return (family, size, smooth)
        fam, pt, px = got
        if px:
            size = px
        else:
            dpi = 96.0
            try:
                from PySide6.QtGui import QGuiApplication
                screen = QGuiApplication.primaryScreen()
                if screen is not None:
                    dpi = float(screen.logicalDotsPerInch()) or 96.0
            except Exception:
                pass
            size = pt * dpi / 72.0
        size = max(KDE_MIN_FONT_SIZE, min(KDE_MAX_FONT_SIZE, int(round(size))))
        return (fam, size, fam not in PIXEL_FAMILIES)

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
        under the pixel pipeline a cursive face is a jagged staircase.

        In a Plasma session the test inverts (see `_kde_type`): the family is
        whatever System Settings holds, so it is smooth unless it is one of the
        known pixel designs."""
        return self._smooth

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
        if self._smooth:
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

        `QFontMetrics.height()` per face (Botis re-measured 2026-08-09):

            px:                  10   15   17   24
            More Perfect DOS VGA 11   15   17   24
            Perfect DOS VGA 437  11   15   17   24
            Botis 4x6            10   15   17   24

        The three now coincide across the slider. Botis used to read 8/12/13/19
        — 3px short at the default — because its outline TTF sized a row from
        the glyph BOUNDING BOX (the authored 6-row cell, ink flush to both
        edges, zero leading), which read as cramped rows everywhere the face
        was used. That is a font-build fix, not an app one: build-4x6.py now
        pads the typo line box to a full em and flags USE_TYPO_METRICS so this
        `height()` (and Pango's, and the panel's) sees the leading. Bind
        `lineHeight` for anything that means "one text row"; bind `fontSize`
        only for an actual font size.
        """
        f = QFont(self._family)
        f.setPixelSize(self._size)
        f.setHintingPreference(QFont.PreferFullHinting)
        return max(1, QFontMetrics(f).height())

    @Property(bool, constant=True)
    def plasma(self):
        """Which session this app was started in — the same switch that moves
        the palette (`kdetheme.is_plasma`), published so QML can read it.

        The one thing QML does with it is `qmlcommon/DeskMenuBar.qml`: there is
        no hyprvtb in a Plasma session, so the app's inner-titlebar buttons have
        nowhere to draw and come back as a menubar instead. Constant, not
        notified: an app is themed by the session that STARTED it, and nothing
        moves a running window between the two."""
        return self._plasma

    @Property(bool, notify=changed)
    def reduceMotion(self):
        return self._reduce

    @Property(float, notify=changed)
    def animSpeed(self):
        return self._speed

    @Property(str, notify=changed)
    def scrollbarStyle(self):
        return self._scrollbar
