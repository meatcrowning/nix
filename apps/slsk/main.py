#!/usr/bin/env python3
"""slsk -- a native Soulseek search & download client for the slskd daemon.

The tenth vendored Qt/QML app. Everything it shows is the local slskd instance's
loopback API (slskd.nix), so it replaces the web UI for the things one does
there -- searching Soulseek, queueing files from the results, and watching the
downloads land. It reads the live source at /home/lam/nix/apps/slsk/main.py
(see ../AGENTS.md).

Structure (mirrors reader/filer):
  - slskapi.py -- the SlskApi QObject: every slskd call on a worker thread,
    results back through Qt signals so QML never blocks.
  - qml/Main.qml -- the window: a search mode and a downloads mode, every
    control drawn through the design language (Theme palette, Motion,
    KineticListView + VScroll).
  - qml/theme/Theme.qml -- instantiated here and installed as the global Theme
    context property, exactly like the other apps.

Chrome is the hyprvtb titlebar (vtbclient.py): the app does not draw a chrome
strip of its own (docs/DESIGN.md 12, 7.4). It registers a footer carrying the
live connection status, and nothing else -- like reader, it ships with no
app-button column.

State (~/.local/state/slsk/state.json) is the app's own UI state -- last query,
which mode was open, the window size -- per docs/DESIGN.md 14.
"""

import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Slot, Signal, Property, QUrl
from PySide6.QtGui import QGuiApplication, QColor
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"

sys.path.insert(0, str(HERE.parent / "pylib"))
from vtbclient import VtbClient  # noqa: E402
from deskstyle import DeskStyle  # noqa: E402

import slskapi  # noqa: E402  (beside this file)

STATE_PATH = (Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
              / "slsk" / "state.json")


# ---- the wallpaper palette (identical to reader/viewer/filer) -------------
PANEL_THEME = Path.home() / ".config" / "quickshell" / "Theme.qml"
PALETTE_KEYS = ["bg", "bgAlt", "border", "accent", "dim", "text", "textDim",
                "highlight", "ok", "warn", "crit", "info"]
PALETTE_DEFAULTS = {
    "bg": "#000000", "bgAlt": "#120b08", "border": "#382216", "accent": "#cc4400",
    "dim": "#54382a", "text": "#cc4400", "textDim": "#8c5438", "highlight": "#21140d",
    "ok": "#e08e65", "warn": "#b86237", "crit": "#fa5c0c", "info": "#ad7457",
}


class Palette(QObject):
    changed = Signal()

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._path = str(path)
        self._colors = dict(PALETTE_DEFAULTS)
        self._load()

    def _load(self):
        try:
            txt = open(self._path, encoding="utf-8").read()
        except OSError:
            return
        colors = dict(self._colors)
        for m in __import__("re").finditer(
                r'property\s+color\s+(\w+)\s*:\s*"(#[0-9a-fA-F]{3,8})"', txt):
            name, val = m.group(1), m.group(2)
            if name in PALETTE_KEYS:
                colors[name] = val
        if colors != self._colors:
            self._colors = colors
            self.changed.emit()

    def _c(self, k):
        return QColor(self._colors.get(k, PALETTE_DEFAULTS[k]))

    @Property(QColor, notify=changed)
    def bg(self): return self._c("bg")
    @Property(QColor, notify=changed)
    def bgAlt(self): return self._c("bgAlt")
    @Property(QColor, notify=changed)
    def border(self): return self._c("border")
    @Property(QColor, notify=changed)
    def accent(self): return self._c("accent")
    @Property(QColor, notify=changed)
    def dim(self): return self._c("dim")
    @Property(QColor, notify=changed)
    def text(self): return self._c("text")
    @Property(QColor, notify=changed)
    def textDim(self): return self._c("textDim")
    @Property(QColor, notify=changed)
    def highlight(self): return self._c("highlight")
    @Property(QColor, notify=changed)
    def ok(self): return self._c("ok")
    @Property(QColor, notify=changed)
    def warn(self): return self._c("warn")
    @Property(QColor, notify=changed)
    def crit(self): return self._c("crit")
    @Property(QColor, notify=changed)
    def info(self): return self._c("info")


class Titlebar(QObject):
    """hyprvtb app-button bridge -- slsk's whole chrome column is a footer with
    the live connection status (docs/DESIGN.md 12)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = VtbClient()

    @Slot(str)
    def setFooter(self, text):
        self._client.set_footer(text)


class Settings(QObject):
    """slsk's own persisted UI state, ~/.local/state/slsk/state.json."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            d = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            self._data = d if isinstance(d, dict) else {}
        except (OSError, ValueError, TypeError):
            self._data = {}

    @Slot(str, "QVariant", result="QVariant")
    def get(self, key, default=None):
        return self._data.get(key, default)

    @Slot(str, "QVariant")
    def set(self, key, val):
        self._data[key] = val
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_PATH.write_text(json.dumps(self._data), encoding="utf-8")
        except OSError:
            pass


def main():
    app = QGuiApplication(sys.argv)
    app.setApplicationName("slsk")
    app.setDesktopFileName("slsk")

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()

    settings = Settings()
    palette = Palette(PANEL_THEME)
    style = DeskStyle()
    titlebar = Titlebar()
    api = slskapi.SlskApi()
    startMode = settings.get("mode", "search")

    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("DeskStyle", style)
    ctx.setContextProperty("Titlebar", titlebar)
    ctx.setContextProperty("Slsk", api)
    ctx.setContextProperty("Settings", settings)
    ctx.setContextProperty("startMode", startMode)

    theme_comp = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "theme" / "Theme.qml")))
    theme = theme_comp.create()
    if theme is None:
        print("Theme.qml failed:\n" + theme_comp.errorString(), file=sys.stderr)
        sys.exit(1)
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)

    engine.load(QUrl.fromLocalFile(str(QML / "Main.qml")))
    if not engine.rootObjects():
        sys.exit(1)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
