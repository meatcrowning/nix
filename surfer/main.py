#!/usr/bin/env python3
"""surfer — minimal Qt/QML web browser for the `top` desktop.

filer's sibling: same PySide6 + QML + wal-palette stack, but the content area
is QtWebEngine — i.e. open Chromium, the same engine Vivaldi wraps — with the
browser chrome living in the hyprvtb titlebar's app-button column instead of
a toolbar (back/forward/reload/tab buttons in the REAL compositor titlebar).

In-window chrome is just one header row: an address bar with ghost scheme
handling (bare words search DuckDuckGo, host-ish strings get https://) and a
pixel-font tab strip. Everything else is the page.

Host support mirrors filer (home/prog/surfer.nix): on air this runs the
SYSTEM python3 + Fedora's python3-pyside6 (nixpkgs Mesa has no Apple Silicon
GBM driver), on top the nixpkgs build.
"""
import json
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Slot, Signal, QUrl, QFileSystemWatcher, Property
from PySide6.QtGui import QGuiApplication, QColor
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtWebEngineQuick import QtWebEngineQuick

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"

sys.path.insert(0, str(HERE.parent / "pylib"))
from vtbclient import VtbClient  # noqa: E402

# Same live wallpaper palette source filer parses (rewritten by wal-set.sh).
PANEL_THEME = Path.home() / ".config" / "quickshell" / "Theme.qml"
PALETTE_KEYS = ["bg", "bgAlt", "border", "accent", "dim", "text", "textDim",
                "highlight", "ok", "warn", "crit", "info"]
PALETTE_DEFAULTS = {
    "bg": "#000000", "bgAlt": "#120b08", "border": "#382216", "accent": "#cc4400",
    "dim": "#54382a", "text": "#cc4400", "textDim": "#8c5438", "highlight": "#21140d",
    "ok": "#e08e65", "warn": "#b86237", "crit": "#fa5c0c", "info": "#ad7457",
}


class Palette(QObject):
    """Live wallpaper palette — same parser/watcher as filer's (see
    ~/nix/filer/main.py for the full commentary)."""

    changed = Signal()

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._path = str(path)
        self._colors = dict(PALETTE_DEFAULTS)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_change)
        self._watcher.directoryChanged.connect(self._on_change)
        d = os.path.dirname(self._path)
        if os.path.isdir(d):
            self._watcher.addPath(d)
        self._rewatch()
        self._load()

    def _rewatch(self):
        if os.path.exists(self._path) and self._path not in self._watcher.files():
            self._watcher.addPath(self._path)

    def _on_change(self, _):
        self._rewatch()
        self._load()

    def _load(self):
        try:
            txt = open(self._path, encoding="utf-8").read()
        except OSError:
            return
        colors = dict(self._colors)
        for m in re.finditer(r'property\s+color\s+(\w+)\s*:\s*"(#[0-9a-fA-F]{3,8})"', txt):
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
    """hyprvtb app-button bridge. QML pushes button sets; the titlebar sends
    back four things, each bounced through a Qt signal (queued across the
    VtbClient I/O thread onto the GUI thread before any UI is touched):
      clicked(id)          a button was clicked
      reordered(src, dst)  a draggable tab button was dropped on another's slot
      addrSubmitted(text)  the in-bar address editor was submitted (Enter)
      wake()               the window was un-hidden (roll-up restore) — a cue to
                           repaint (QtWebEngine blacks out after a hide)."""

    clicked = Signal(str)
    reordered = Signal(str, str)
    addrSubmitted = Signal(str)
    wake = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = VtbClient(
            on_click=self.clicked.emit,
            on_reorder=lambda s, d: self.reordered.emit(s, d),
            on_addr=self.addrSubmitted.emit,
            on_wake=self.wake.emit,
        )

    @Slot("QVariantList")
    def setButtons(self, buttons):
        out = []
        for b in buttons:
            if isinstance(b, str):
                out.append("-")
            else:
                out.append((str(b["id"]), str(b["label"]), int(b.get("state", 0)),
                            str(b.get("tip", "")), bool(b.get("drag", False))))
        self._client.set_buttons(out)

    @Slot(str)
    def setFooter(self, text):
        self._client.set_footer(text)

    @Slot(bool)
    def setTitleEdit(self, on):
        """Mark the stacked title (the outer column) an editable address bar."""
        self._client.set_title_edit(on)


class Clip(QObject):
    """Clipboard access for the 'copy url' titlebar button."""

    @Slot(str)
    def copy(self, text):
        QGuiApplication.clipboard().setText(text)


class Session(QObject):
    """Persists the open tabs (their URLs) + the active tab index to
    $XDG_STATE_HOME/surfer/session.json, so a relaunch restores what was open."""

    def __init__(self, parent=None):
        super().__init__(parent)
        state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
        self._path = state / "surfer" / "session.json"

    @Slot("QVariantList", int)
    def save(self, urls, current):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {"tabs": [str(u) for u in urls if str(u)], "current": int(current)}
            self._path.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass

    @Slot(result="QVariantMap")
    def load(self):
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            tabs = [str(u) for u in data.get("tabs", []) if str(u)]
            return {"tabs": tabs, "current": int(data.get("current", 0))}
        except (OSError, ValueError, TypeError):
            return {"tabs": [], "current": 0}


def main():
    # Chromium must be initialized before the QGuiApplication exists.
    QtWebEngineQuick.initialize()

    app = QGuiApplication(sys.argv)
    app.setApplicationName("surfer")
    app.setOrganizationName("surfer")  # keys the QtWebEngine profile dirs
    app.setDesktopFileName("surfer")

    start_url = ""
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            start_url = arg
            break

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()

    palette = Palette(PANEL_THEME)
    titlebar = Titlebar()
    clip = Clip()
    session = Session()
    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("Titlebar", titlebar)
    ctx.setContextProperty("Clip", clip)
    ctx.setContextProperty("Session", session)
    ctx.setContextProperty("startUrl", start_url)

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
