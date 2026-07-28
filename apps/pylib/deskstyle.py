"""The desktop's typography settings, read by every app from the panel's store.

DESIGN.md §2.1 is a single rule for the whole desktop: one font, at kitty's
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
"""

import json
import os
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, Property, Signal

# Written by the panel's SettingsStore (Quickshell.shellDir + "/settings.json").
SETTINGS_PATH = Path.home() / ".config" / "quickshell" / "settings.json"

# Must match SettingsStore.qml's inline defaults, and SetPgAppearance.qml's
# slider bounds. A value outside the range means a hand-edited or corrupt file,
# and a font size of 0 (or 400) is unrecoverable from inside a GUI, so clamp.
DEFAULT_FONT_FAMILY = "More Perfect DOS VGA"
DEFAULT_FONT_SIZE = 15
MIN_FONT_SIZE = 10
MAX_FONT_SIZE = 24


def settings_path():
    return Path(os.environ.get("DESK_SETTINGS") or SETTINGS_PATH)


class DeskStyle(QObject):
    """Live `fontFamily` / `fontSize` from the panel's settings.json.

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
        if (family, size) != (self._family, self._size):
            self._family, self._size = family, size
            self.changed.emit()

    @Property(str, notify=changed)
    def fontFamily(self):
        return self._family

    @Property(int, notify=changed)
    def fontSize(self):
        return self._size
