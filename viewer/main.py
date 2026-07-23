#!/usr/bin/env python3
"""viewer — standalone Qt/QML image (and, later, media) viewer for the `top`
desktop.

Split out of filer's built-in overlay so image viewing is its own window/process
(filer's `openFile` now shells out to `viewer <path>`): a real Wayland window
with the same hyprvtb vertical titlebar — prev/next/zoom/fit/close live there —
that filer and every other app get. Being its own process means it outlives the
file browser and can grow into a general media viewer without bloating filer.

Given one image path it scans that file's directory for the rest (the sibling
images, name-sorted) so ‹ / › flip through the folder; given several paths it
uses exactly those. Theme/palette wiring mirrors filer: the live wallpaper
palette is parsed from the panel's Theme.qml and watched, so viewer recolours in
lock-step with the bar. See filer/main.py for the shared design notes.
"""
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Slot, Signal, Property, QUrl, QFileSystemWatcher
from PySide6.QtGui import QGuiApplication, QColor
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"

sys.path.insert(0, str(HERE.parent / "pylib"))
from vtbclient import VtbClient  # noqa: E402  (needs the path insert above)

# Same set filer classifies as images, so anything filer shows a thumbnail for
# opens here (keep the two in sync — filer/main.py IMAGE_EXTS).
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
              ".avif", ".jxl", ".tif", ".tiff", ".ico", ".ppm", ".pgm"}

# Video/animation formats played through QtMultimedia (ffmpeg backend). Mixed in
# with the images when scanning a folder so ‹ / › (skip prev/next) flip across
# both; the QML tells video from image by extension and swaps the surface + the
# titlebar controls (play/pause + scrub bar) accordingly.
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".mpg",
              ".mpeg", ".wmv", ".flv", ".ts", ".ogv", ".3gp", ".m2ts"}


def is_image(name):
    return os.path.splitext(name)[1].lower() in IMAGE_EXTS


def is_video(name):
    return os.path.splitext(name)[1].lower() in VIDEO_EXTS


def is_media(name):
    return is_image(name) or is_video(name)


def natkey(name):
    """Natural sort key: split digit runs so img2 < img10 (not img10 < img2),
    case-insensitively — matches how a person expects a folder to flip through."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def images_for(argv):
    """(list of {name, path}, start index) for the given argv.

    One existing media file → the name-sorted media of its directory, positioned
    on it. Several paths → exactly those, in the order given. Anything else that
    exists → just itself."""
    paths = [os.path.abspath(a) for a in argv if os.path.exists(a)]
    if len(paths) == 1 and os.path.isfile(paths[0]):
        target = paths[0]
        d = os.path.dirname(target)
        try:
            names = sorted((e.name for e in os.scandir(d) if e.is_file() and is_media(e.name)), key=natkey)
        except OSError:
            names = [os.path.basename(target)]
        entries = [{"name": n, "path": os.path.join(d, n)} for n in names]
        idx = next((i for i, e in enumerate(entries) if e["path"] == target), -1)
        if idx < 0:  # target isn't a recognised media ext — show it anyway
            entries.insert(0, {"name": os.path.basename(target), "path": target})
            idx = 0
        return entries, idx
    entries = [{"name": os.path.basename(p), "path": p} for p in paths]
    return entries, 0


# The panel's palette file, rewritten by wal-set.sh between the wal markers.
PANEL_THEME = Path.home() / ".config" / "quickshell" / "Theme.qml"
PALETTE_KEYS = ["bg", "bgAlt", "border", "accent", "dim", "text", "textDim",
                "highlight", "ok", "warn", "crit", "info"]
PALETTE_DEFAULTS = {
    "bg": "#000000", "bgAlt": "#120b08", "border": "#382216", "accent": "#cc4400",
    "dim": "#54382a", "text": "#cc4400", "textDim": "#8c5438", "highlight": "#21140d",
    "ok": "#e08e65", "warn": "#b86237", "crit": "#fa5c0c", "info": "#ad7457",
}


class Palette(QObject):
    """The live wallpaper palette, parsed from the panel's Theme.qml and kept in
    sync via a filesystem watch (mirrors filer's Palette)."""

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
            self._watcher.addPath(d)  # dir watch catches atomic replaces
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
    """hyprvtb app-button bridge — the viewer controls (prev/next/zoom/fit/close,
    or play/pause + skip for video) live in the compositor's inner titlebar
    column, and so does the video scrub bar. QML pushes the button set + scrub
    position; clicks and scrub seeks bounce back through `clicked` / `seek`. See
    filer/main.py for the pattern. The vtb callbacks fire on the client's I/O
    thread — the Signals hop them onto the GUI thread (queued)."""

    clicked = Signal(str)
    seek = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = VtbClient(on_click=self.clicked.emit,
                                 on_seek=self.seek.emit)

    @Slot("QVariantList")
    def setButtons(self, buttons):
        out = []
        for b in buttons:
            if isinstance(b, str):
                out.append("-")  # spacer
            else:
                out.append((str(b["id"]), str(b["label"]), int(b.get("state", 0)),
                            str(b.get("tip", ""))))
        self._client.set_buttons(out)

    @Slot(str)
    def setFooter(self, text):
        self._client.set_footer(text)

    @Slot(bool, float)
    def setPlaybar(self, shown, pos):
        self._client.set_playbar(shown, pos)


def main():
    app = QGuiApplication(sys.argv)
    app.setApplicationName("viewer")
    app.setDesktopFileName("viewer")

    entries, index = images_for(sys.argv[1:])

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()

    palette = Palette(PANEL_THEME)
    titlebar = Titlebar()
    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("Titlebar", titlebar)
    ctx.setContextProperty("startImages", entries)
    ctx.setContextProperty("startIndex", index)

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
