#!/usr/bin/env python3
"""viewer — standalone Qt/QML image (and, later, media) viewer for the `top`
desktop.

Split out of filer's built-in overlay so image viewing is its own window/process
(filer's `openFile` now shells out to `viewer <path>`): a real Wayland window
with the same hyprvtb vertical titlebar — prev/next/zoom/fit/close live there —
that filer and every other app get. Being its own process means it outlives the
file browser and can grow into a general media viewer without bloating filer.

Given one image path it scans that file's directory for the rest (the sibling
images, name-sorted) so << / >> flip through the folder; given several paths it
uses exactly those. `--order FILE` overrides the scan with a caller-supplied
order — that is how filer makes << / >> follow the sort the user is actually
looking at. `--split` opens one PANE per path instead of a flip list.

The window is a GRID of panes (one is the ordinary case): each pane holds its
own position in the shared list, its own zoom, and is its own drop target — drag
images out of filer into whichever pane should show them. Theme/palette wiring
mirrors filer: the live wallpaper
palette is parsed from the panel's Theme.qml and watched, so viewer recolours in
lock-step with the bar. See filer/main.py for the shared design notes.
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

# ---- hand off to a viewer that is already open, BEFORE importing Qt --------
# Opening an image cost ~0.5s and only 0.04s of that was the file; the rest was
# starting this process. So the first thing a new `viewer` does is ask a running
# one to show the image instead — and it has to do that up here, above the
# PySide6 imports, because those imports are 0.10s of what we are trying not to
# spend. A running viewer that cannot do it VISIBLY says no, and we carry on and
# open our own window; see pylib/handoff.py and `--new-window` below.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pylib"))
if __name__ == "__main__" and "--new-window" not in sys.argv[1:]:
    from handoff import send as _handoff_send, took as _handoff_took  # noqa: E402

    if _handoff_took(_handoff_send("viewer", {"argv": sys.argv[1:],
                                              "cwd": os.getcwd()})):
        raise SystemExit(0)

from PySide6.QtCore import (QObject, QProcess, Slot, Signal, Property, QUrl,
                            QFileSystemWatcher)
from PySide6.QtGui import QGuiApplication, QColor
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"
CLIPFILE = HERE.parent / "pylib" / "clipfile.py"

sys.path.insert(0, str(HERE.parent / "pylib"))
from vtbclient import VtbClient, close_animated  # noqa: E402  (needs the path insert above)
from handoff import Listener  # noqa: E402  (pylib; the running-app socket)
from deskstyle import DeskStyle  # noqa: E402  (pylib; the desktop-wide font setting)

# Same set filer classifies as images, so anything filer shows a thumbnail for
# opens here (keep the two in sync — filer/main.py IMAGE_EXTS).
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
              ".avif", ".jxl", ".tif", ".tiff", ".ico", ".ppm", ".pgm"}

# Video/animation formats played through QtMultimedia (ffmpeg backend). Mixed in
# with the images when scanning a folder so << / >> (skip prev/next) flip across
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


def _consume(path):
    """Delete a hand-over file we were given, best effort. Only inside a temp
    root — `--order` transfers ownership, but never let a typo'd flag delete
    something of the user's."""
    roots = [tempfile.gettempdir()]
    rt = os.environ.get("XDG_RUNTIME_DIR")
    if rt:
        roots.append(rt)
    real = os.path.realpath(path)
    if any(real.startswith(os.path.realpath(r) + os.sep) for r in roots):
        try:
            os.unlink(real)
        except OSError:
            pass


def order_from(order_file, target):
    """(entries, index) from a caller-supplied order file, or None.

    filer writes the paths it is displaying, in display order, and passes
    `--order <file>`; viewer flips through exactly that instead of its own
    name-sort of the directory. NUL-separated, because a filename may contain a
    newline. Non-media entries (filer lists directories and plain files too) are
    dropped here rather than filer-side, so the caller need not know what viewer
    can decode.

    It is a LAUNCH-TIME snapshot, deliberately: the file is consumed on read and
    nothing watches it, so re-sorting filer afterwards leaves an open viewer's
    order alone. None (→ fall back to the directory scan) if the file is
    unreadable or does not contain `target`."""
    try:
        raw = open(order_file, "rb").read().decode("utf-8", "surrogateescape")
    except OSError:
        return None
    finally:
        _consume(order_file)
    # NO STAT PER ENTRY. This list comes from a caller that has just finished
    # listing the directory, and `os.path.isfile()` on every path used to be
    # here to drop anything that had gone away since. Over a network mount that
    # is one round trip each: measured on book against a folder on top, 891
    # entries cost **3.6s** before viewer had even built its window — the whole
    # of "opening a remote image takes ages", spent stat-ing 890 files nobody
    # asked to see. `is_media` is a string test and stays; a path that really
    # has vanished now shows as a broken image if you flip to it, which is a
    # rare, visible and honest failure rather than a guaranteed one.
    entries = [{"name": os.path.basename(p), "path": p}
               for p in (os.path.abspath(q) for q in raw.split("\0") if q)
               if is_media(p)]
    idx = next((i for i, e in enumerate(entries) if e["path"] == target), -1)
    return (entries, idx) if idx >= 0 else None


# Most panes the split view will lay out. 3x3 of a 900x620 window is already
# ~290x200 per pane; past that a pane is a thumbnail, not a view.
MAX_PANES = 9


def split_args(argv):
    """(--order file or None, --split seen?, the remaining positional paths).

    `--new-window` is consumed here and nowhere else: it is acted on at the top
    of this file, before Qt is even imported, and only has to be kept out of
    `rest` — everything left over is treated as a path to open, so a flag that
    fell through would be opened as a file."""
    order, split, rest, it = None, False, [], iter(argv)
    for a in it:
        if a == "--order":
            order = next(it, None)
        elif a.startswith("--order="):
            order = a[len("--order="):]
        elif a == "--split":
            split = True
        elif a == "--new-window":
            pass
        else:
            rest.append(a)
    return order, split, rest


def images_for(argv):
    """(list of {name, path}, start index, pane count) for the given argv.

    One existing media file → the name-sorted media of its directory, positioned
    on it (or the caller's `--order`, if it gave one containing that file).
    Several paths → exactly those, in the order given. Anything else that
    exists → just itself.

    The pane count is 1 unless `--split` was passed with several paths, in which
    case each path opens in its own pane (capped at MAX_PANES). It is a flag and
    not the default because several paths have always meant "flip through
    exactly these", and filer relies on that."""
    order_file, split, argv = split_args(argv)
    paths = [os.path.abspath(a) for a in argv if os.path.exists(a)]
    panes = min(len(paths), MAX_PANES) if (split and len(paths) > 1) else 1
    if order_file and len(paths) == 1 and os.path.isfile(paths[0]):
        got = order_from(order_file, paths[0])
        if got is not None:
            return got[0], got[1], 1
    elif order_file:
        _consume(order_file)
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
        return entries, idx, 1
    entries = [{"name": os.path.basename(p), "path": p} for p in paths]
    return entries, 0, panes


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

    @Slot(result=bool)
    def requestClose(self):
        """Quit the way the titlebar's [x] does — rolled up into the bar, not
        faded out. False means the compositor did not take it and QML must call
        Qt.quit() itself; see vtbclient.close_animated."""
        return close_animated()


class Files(QObject):
    """The receiving end of a drag: local media paths out of a drop's URLs.

    Mirrors filer's `FileOps.urlsToPaths` (see filer/main.py) and for the same
    reason — **QUrl owns the encoding**. The hand-rolled `encodeURI()` version
    filer used to drag OUT leaves `#` and `?` unescaped, so a file called
    `a#b.png` arrived truncated; decoding a uri-list in QML would repeat that
    bug from the other side. Anything that isn't a local file (an http:// drag
    out of a browser) yields nothing, so the drop is simply declined.

    Non-media files are dropped here rather than by the caller, exactly as
    `--order` does: a pane can only show what viewer can decode."""

    @Slot("QVariantList", result="QVariantList")
    def mediaEntries(self, urls):
        out, seen = [], set()
        for u in urls:
            p = (u if isinstance(u, QUrl) else QUrl(str(u))).toLocalFile()
            if not p:
                continue
            p = os.path.normpath(p)
            if p in seen or not is_media(p) or not os.path.isfile(p):
                continue
            seen.add(p)
            out.append({"name": os.path.basename(p), "path": p})
        return out


class Clip(QObject):
    """The context menu's "copy image" — `pylib/clipfile.py`, never QClipboard.

    Two reasons it is a subprocess and not `QClipboard.setImage`, both already
    paid for elsewhere on this desktop (apps/AGENTS.md → `pylib/`):

      * **A Wayland selection dies with the process that offered it.** Copy an
        image, close the viewer, paste — nothing. clipfile forks a holder that
        outlives us and lets go when something else takes the clipboard, which
        is what makes a copy behave like a copy.
      * `QClipboard.setMimeData` takes a Python-built `QMimeData` that Qt's
        global-static clipboard frees AFTER the interpreter is gone — a SIGSEGV
        on exit from any run that copied, which is how painter's harness exited
        139 with every check passing.

    `--image` additionally offers the file's bytes under its image mime, so a
    paste lands as the picture in an editor and as the file (with its name)
    anywhere that understands one. A video gets the file offer alone — there is
    no "the picture" to hand over.

    The outcome is REPORTED, always (docs/DESIGN.md §10): `done(message, bad)`
    goes to the titlebar footer, which is where viewer already talks. A copy
    that silently did nothing would look exactly like one that worked, right up
    until the paste."""

    done = Signal(str, bool)      # message for the footer, and whether it failed

    def __init__(self, parent=None):
        super().__init__(parent)
        self._procs = set()       # a QProcess with no Python ref is collected

    @Slot(str)
    def copyImage(self, path):
        self._copy(path, True)

    @Slot(str)
    def copyFile(self, path):
        self._copy(path, False)

    def _copy(self, path, as_image):
        src = str(path)
        name = os.path.basename(src)
        if not os.path.exists(src):
            self.done.emit("can't copy " + name + ": it is gone", True)
            return
        argv = [sys.executable, str(CLIPFILE)] + (["--image"] if as_image else []) + [src]
        proc = QProcess(self)
        self._procs.add(proc)

        def finished(code, _status):
            err = bytes(proc.readAllStandardError()).decode("utf-8", "replace").strip()
            if code == 0:
                self.done.emit("copied " + name, False)
            else:
                self.done.emit("copy failed: " + (err.splitlines()[-1] if err
                                                  else "exit %d" % code), True)
            self._procs.discard(proc)
            proc.deleteLater()

        def failed(_e):
            # clipfile could not be started at all — a different sentence,
            # because the fix is a packaging one and not the clipboard's.
            if proc in self._procs:
                self.done.emit("copy failed: cannot run clipfile", True)
                self._procs.discard(proc)
                proc.deleteLater()

        proc.finished.connect(finished)
        proc.errorOccurred.connect(failed)
        proc.start(argv[0], argv[1:])


class Prefs(QObject):
    """viewer's own settings file, `$XDG_CONFIG_HOME/viewer/prefs.json`.

    Two things live in it. The split view's divider positions, as column and row
    weights keyed by grid shape (`"2x1"`, `"2x2"`, …) — a 2x2 split's dividers
    have nothing to say about where a 3x1's should sit, and viewer reshapes its
    grid every time a pane is added or closed. Weights, not pixels, so a resized
    window keeps the proportions. And `muted`, the titlebar's `mu` toggle, which
    is a preference about this machine's speakers rather than about one clip and
    so has to outlive the window.

    Written on RELEASE of a divider drag, never per motion event (surfer's
    `splitRatio` established that rule)."""

    mutedChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        cfg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self._path = cfg / "viewer" / "prefs.json"

    def _read(self):
        try:
            d = json.loads(self._path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _write(self, mutate):
        """Read-modify-write the whole file. Small enough that a merge is not
        worth it, and it keeps a second key from clobbering the first."""
        d = self._read()
        mutate(d)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(d), encoding="utf-8")
        except OSError:
            pass

    @Property(bool, notify=mutedChanged)
    def muted(self):
        return bool(self._read().get("muted", False))

    @Slot(bool)
    def setMuted(self, on):
        on = bool(on)
        if on == self.muted:
            return
        self._write(lambda d: d.__setitem__("muted", on))
        self.mutedChanged.emit()

    @Slot(str, result="QVariantMap")
    def loadWeights(self, shape):
        """{"col": [...], "row": [...]} for this grid shape, or {} — the QML
        falls back to an even split. Malformed entries read as absent."""
        w = self._read().get("paneWeights", {})
        got = w.get(str(shape)) if isinstance(w, dict) else None
        if not isinstance(got, dict):
            return {}
        out = {}
        for k in ("col", "row"):
            v = got.get(k)
            if isinstance(v, list) and v and all(isinstance(x, (int, float)) for x in v):
                out[k] = [float(x) for x in v]
        return out

    @Slot(str, "QVariantList", "QVariantList")
    def saveWeights(self, shape, col, row):
        def put(d):
            w = d.get("paneWeights")
            if not isinstance(w, dict):
                w = {}
            w[str(shape)] = {"col": [float(x) for x in col],
                             "row": [float(x) for x in row]}
            d["paneWeights"] = w

        self._write(put)


def main():
    app = QGuiApplication(sys.argv)
    app.setApplicationName("viewer")
    app.setDesktopFileName("viewer")

    entries, index, panes = images_for(sys.argv[1:])

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()

    palette = Palette(PANEL_THEME)
    style = DeskStyle()
    titlebar = Titlebar()
    files = Files()
    prefs = Prefs()
    clip = Clip()
    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("DeskStyle", style)
    ctx.setContextProperty("Titlebar", titlebar)
    ctx.setContextProperty("Files", files)
    ctx.setContextProperty("Prefs", prefs)
    ctx.setContextProperty("Clip", clip)
    ctx.setContextProperty("startImages", entries)
    ctx.setContextProperty("startIndex", index)
    ctx.setContextProperty("startPanes", panes)
    ctx.setContextProperty("maxPanes", MAX_PANES)

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
    win = engine.rootObjects()[0]

    # ---- be the viewer the NEXT one hands off to ---------------------------
    # The rule for taking a request is one thing and one thing only: is this
    # window on screen right now? `isExposed()` is false for a window on
    # another workspace, rolled up, or minimised — a compositor sends no frame
    # callbacks to a surface nobody can see — and loading an image into one of
    # those would make the click do nothing at all, which is strictly worse
    # than being slow. Refuse, and the caller opens its own window where the
    # person actually is. (See pylib/handoff.py; the caller is either another
    # `viewer` invocation or filer, which speaks the same protocol directly and
    # so pays no process at all.)
    def _can_take():
        return bool(win.isExposed())

    def _take(payload):
        argv = [str(a) for a in (payload.get("argv") or [])]
        cwd = payload.get("cwd") or os.getcwd()
        here = os.getcwd()
        try:
            os.chdir(cwd)          # the caller's relative paths, not ours
            entries, index, _panes = images_for(argv)
        finally:
            os.chdir(here)
        if not entries:
            raise ValueError("nothing openable in that request")
        win.openSet(entries, index)

    listener = Listener("viewer", _can_take, _take, parent=app)  # noqa: F841
    # (not listening = another viewer already owns the socket; nothing to do)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
