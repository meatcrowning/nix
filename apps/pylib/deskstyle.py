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
from PySide6.QtGui import QFont

# Written by the panel's SettingsStore (Quickshell.shellDir + "/settings.json").
SETTINGS_PATH = Path.home() / ".config" / "quickshell" / "settings.json"

# Must match SettingsStore.qml's inline defaults, and SetPgAppearance.qml's
# slider bounds. A value outside the range means a hand-edited or corrupt file,
# and a font size of 0 (or 400) is unrecoverable from inside a GUI, so clamp.
DEFAULT_FONT_FAMILY = "More Perfect DOS VGA"
DEFAULT_FONT_SIZE = 15
MIN_FONT_SIZE = 10
MAX_FONT_SIZE = 24

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
    """Live `fontFamily` / `fontSize` / `reduceMotion` / `animSpeed` / `scrollbarStyle`.

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
        now = (family, size, reduce_motion, speed, bar)
        if now != (self._family, self._size, self._reduce, self._speed, self._scrollbar):
            (self._family, self._size, self._reduce,
             self._speed, self._scrollbar) = now
            self.changed.emit()

    @Property(str, notify=changed)
    def fontFamily(self):
        return self._family

    @Property(int, notify=changed)
    def fontSize(self):
        return self._size

    @Property(QFont, notify=changed)
    def editorFont(self):
        """The desktop font as a QFont with NoAntialias pinned — for editable
        items ONLY (`TextEdit`/`TextInput`).

        A `Text` honours `antialiasing: false` and draws a scalable pixel font
        (the default "More Perfect DOS VGA") as crisp mono glyphs. An *editable*
        item does NOT: `QQuickTextEdit`/`QQuickTextInput` ignore the QML
        `antialiasing` and `renderType` levers for glyph rasterisation and draw
        grey-fringed AA glyphs regardless of the face (all three pixel faces are
        scalable outlines now, so none escapes it on its own). The one lever
        that reaches the font engine is `QFont::NoAntialias`, which the QML
        `font` group cannot express — so it is set here and bound as a whole
        `font:` (docs/DESIGN.md §2.2). Verified: 17 grey levels in a glyph -> 2.
        """
        f = QFont(self._family)
        f.setPixelSize(self._size)
        f.setHintingPreference(QFont.PreferFullHinting)
        f.setStyleStrategy(QFont.NoAntialias)
        return f

    @Property(bool, notify=changed)
    def reduceMotion(self):
        return self._reduce

    @Property(float, notify=changed)
    def animSpeed(self):
        return self._speed

    @Property(str, notify=changed)
    def scrollbarStyle(self):
        return self._scrollbar
