#!/usr/bin/env python3
"""filer — standalone Qt/QML file browser for the `top` desktop.

Ported out of the Quickshell panel (~/nix/home/prog/quickshell-files) so it runs
as its own process and no longer gets torn down every time the Quickshell config
hot-reloads. The UI is the same QML; this host supplies what Quickshell used to:

  * FileOps — replaces Quickshell's `Process` / `execDetached`. Runs file ops
             asynchronously via QProcess (so large copies never freeze the UI),
             plus directory listing and path completion for the tree + location
             bar.
  * Palette — the live wallpaper palette. The panel's Theme.qml is rewritten by
             wal-set.sh on every wallpaper change; Palette parses that file and
             watches it, so filer recolours in lock-step with the bar instead of
             drifting to a stale snapshot. Installed as the `WalPalette` context
             property; the Theme object (qml/theme/Theme.qml) binds to it.

Theme and WalPalette are context properties (not QML singletons): a singleton
can't read context properties, and a Theme.qml next to the components would
shadow the name as a type — so Theme lives in qml/theme/ and is injected here.
(Likewise the palette is "WalPalette", not "Palette", which is a built-in type.)
"""
import json
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Slot, Signal, Property, QProcess, QUrl, QFileSystemWatcher
from PySide6.QtGui import QGuiApplication, QColor
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"

sys.path.insert(0, str(HERE.parent / "pylib"))
from vtbclient import VtbClient  # noqa: E402  (needs the path insert above)

# Preview classification. `kind` is the scaffold for file previews: the QML side
# groups/renders entries by it (images get a thumbnail grid at the top of the
# dir; everything else stays a plain row). Extend this — a new extension set and
# a new kind — to teach filer to preview more types (video poster frames, PDFs,
# …); the matching render branch lives in qml/PreviewTile.qml.
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
              ".avif", ".jxl", ".tif", ".tiff", ".ico", ".ppm", ".pgm"}


def preview_kind(name, is_dir):
    """Coarse type of an entry, for the preview layer. "dir" | "image" | "file"."""
    if is_dir:
        return "dir"
    ext = os.path.splitext(name)[1].lower()
    if ext in IMAGE_EXTS:
        return "image"
    return "file"


# The panel's palette file, rewritten by wal-set.sh between the wal markers.
PANEL_THEME = Path.home() / ".config" / "quickshell" / "Theme.qml"
PALETTE_KEYS = ["bg", "bgAlt", "border", "accent", "dim", "text", "textDim",
                "highlight", "ok", "warn", "crit", "info"]
# Fallback until the panel theme is read (also what shows if it's ever missing).
PALETTE_DEFAULTS = {
    "bg": "#000000", "bgAlt": "#120b08", "border": "#382216", "accent": "#cc4400",
    "dim": "#54382a", "text": "#cc4400", "textDim": "#8c5438", "highlight": "#21140d",
    "ok": "#e08e65", "warn": "#b86237", "crit": "#fa5c0c", "info": "#ad7457",
}


class Palette(QObject):
    """The live wallpaper palette, parsed from the panel's Theme.qml and kept in
    sync via a filesystem watch. Each colour is a NOTIFYing property, so QML
    bindings (Theme.* → Palette.*) recolour the whole window when it changes."""

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
        # Editors/wal-set.sh replace the file (rename), which drops the file
        # watch — re-add it whenever it exists and isn't currently watched.
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


class FileOps(QObject):
    """Backend for shell-outs. argv arrays only — never string interpolation —
    so paths containing spaces or shell metacharacters are safe."""

    finished = Signal(str)  # emits the path to reselect after the op ("" = none)

    @Slot(list, str)
    def run(self, argv, reselect):
        argv = [str(a) for a in argv]
        proc = QProcess(self)

        def done(*_):
            self.finished.emit(reselect)
            proc.deleteLater()

        proc.finished.connect(done)
        proc.errorOccurred.connect(done)
        proc.start(argv[0], argv[1:])

    @Slot(list)
    def execDetached(self, argv):
        argv = [str(a) for a in argv]
        QProcess.startDetached(argv[0], argv[1:])

    @Slot(str, result="QVariantList")
    def listDir(self, path):
        """One directory level, for the tree model. Returns a list of
        {name, path, isDir, kind, size, created, modified, hidden}. created/modified
        are epoch seconds — created is st_birthtime where the platform/filesystem
        exposes it, else st_ctime. Hidden entries are included (the QML side sorts
        and orders them). Unreadable dirs return an empty list."""
        try:
            entries = list(os.scandir(path))
        except OSError:
            return []
        items = []
        for e in entries:
            try:
                is_dir = e.is_dir()
            except OSError:
                is_dir = False
            try:
                st = e.stat(follow_symlinks=False)
                size = 0 if is_dir else st.st_size
                modified = st.st_mtime
                created = getattr(st, "st_birthtime", None) or st.st_ctime
            except OSError:
                size = modified = created = 0
            items.append({"name": e.name, "path": e.path, "isDir": is_dir,
                          "kind": preview_kind(e.name, is_dir),
                          "size": size, "created": created, "modified": modified,
                          "hidden": e.name.startswith(".")})
        return items

    @Slot(str, result=bool)
    def isDir(self, path):
        return os.path.isdir(path)

    @Slot(str, result="QVariantList")
    def completePath(self, text):
        """Directory completions for the location bar. Given a partial absolute
        path, returns matching subdirectory paths (with a trailing slash),
        sorted. Only directories, since the bar navigates to directories."""
        text = text.strip()
        if not text.startswith("/"):
            return []
        if text.endswith("/"):
            parent, base = text, ""
        else:
            parent, base = os.path.dirname(text), os.path.basename(text)
        try:
            entries = list(os.scandir(parent or "/"))
        except OSError:
            return []
        out = []
        for e in entries:
            if e.name.startswith(".") and not base.startswith("."):
                continue
            if not e.name.startswith(base):
                continue
            try:
                if e.is_dir():
                    out.append(e.path.rstrip("/") + "/")
            except OSError:
                pass
        out.sort()
        return out


STATE_PATH = Path.home() / ".local" / "state" / "filer" / "state.json"


class Settings(QObject):
    """Tiny persisted UI state (~/.local/state/filer/state.json): the last
    directory viewed and the last sort field/direction, so filer reopens where
    and how you left it. Written by QML on navigation / sort change."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = {}
        try:
            self._data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._data = {}

    def value(self, key, default=None):
        return self._data.get(key, default)

    @Slot(str, str, bool, bool)
    def save(self, directory, sort_field, sort_asc, show_hidden):
        self._data["dir"] = directory
        self._data["sortField"] = sort_field
        self._data["sortAsc"] = bool(sort_asc)
        self._data["showHidden"] = bool(show_hidden)
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_PATH.write_text(json.dumps(self._data), encoding="utf-8")
        except OSError:
            pass


class Titlebar(QObject):
    """Bridge to the hyprvtb titlebar's app-button column (the inner half of
    the compositor's double-wide bar — where filer's sort/op strip moved).

    QML pushes the full button set whenever any label/state changes, and
    receives clicks back through the `clicked` signal. VtbClient's callback
    fires on its reader thread; emitting a Signal from there is safe — Qt
    queues the delivery onto the main thread for the QML Connections item."""

    clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = VtbClient(on_click=self.clicked.emit)

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


class WinCtl(QObject):
    """Lets the QML sort strip act like a titlebar: dragging its empty area
    starts a compositor-side window move, so the strip + the hyprvtb bar behave
    as one draggable bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._win = None

    def setWindow(self, win):
        self._win = win

    @Slot()
    def startMove(self):
        if self._win is not None:
            self._win.startSystemMove()


def main():
    app = QGuiApplication(sys.argv)
    app.setApplicationName("filer")
    app.setDesktopFileName("filer")

    settings = Settings()

    # Start directory: an explicit existing-directory argument (e.g. `filer
    # /mnt/foo`, used by the disk widget's open button) wins; otherwise reopen
    # the last-viewed directory; otherwise fall back to home.
    start_dir = None
    for arg in sys.argv[1:]:
        if os.path.isdir(arg):
            start_dir = os.path.abspath(arg)
            break
    if start_dir is None:
        saved = settings.value("dir", "")
        start_dir = saved if saved and os.path.isdir(saved) else str(Path.home())

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()

    ops = FileOps()
    palette = Palette(PANEL_THEME)
    winctl = WinCtl()
    titlebar = Titlebar()
    # NB: exposed as "WalPalette", not "Palette" — "Palette" is a built-in Qt
    # Quick type name and would shadow the context property.
    # WalPalette first, so Theme's bindings resolve it when Theme is instantiated.
    ctx.setContextProperty("FileOps", ops)
    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("WinCtl", winctl)
    ctx.setContextProperty("Titlebar", titlebar)
    ctx.setContextProperty("Settings", settings)
    ctx.setContextProperty("startDir", start_dir)
    # Last-used sort + hidden-files toggle, restored into the view on startup.
    ctx.setContextProperty("startSortField", settings.value("sortField", "name"))
    ctx.setContextProperty("startSortAsc", bool(settings.value("sortAsc", True)))
    ctx.setContextProperty("startShowHidden", bool(settings.value("showHidden", True)))

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
    winctl.setWindow(engine.rootObjects()[0])

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
