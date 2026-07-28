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
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import (QObject, Slot, Signal, Property, QProcess, QUrl,
                            QFileSystemWatcher, Qt, QThreadPool, QRunnable,
                            QTimer)
from PySide6.QtGui import QGuiApplication, QColor, QImage, QImageReader, QImageWriter
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuick import (QQuickAsyncImageProvider, QQuickImageResponse,
                             QQuickTextureFactory)

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"

sys.path.insert(0, str(HERE.parent / "pylib"))
from vtbclient import VtbClient  # noqa: E402  (needs the path insert above)
from deskstyle import DeskStyle  # noqa: E402  (pylib; the desktop-wide font setting)

from notify import tool, toast  # noqa: E402  (next to this file; filer's one toast path)
from videoconv import VideoConv  # noqa: E402  (next to this file; see its docstring)
from pick import Picker, load_spec  # noqa: E402  (picker mode — see its docstring)

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


# ---- thumbnails -------------------------------------------------------------
# filer serves preview-grid thumbnails through the freedesktop.org *Thumbnail
# Managing Standard* — the same shared, per-user cache Dolphin/Thunar/Nautilus
# use — instead of re-decoding each original on every visit. That cache lives at
# ~/.cache/thumbnails/{normal(128px),large(256px)}/, one PNG per file named
# md5(file-URI).png, carrying the source's mtime in a Thumb::MTime tEXt chunk so
# a stale thumbnail is regenerated when the file changes. Because the naming is
# the shared standard, a warm hit (the common case — KDE has usually thumbnailed
# the file already) is a near-instant read of a tiny PNG; a miss decodes once,
# writes back into the shared cache (so Dolphin benefits too), and is instant
# ever after. The heavy work runs off the GUI thread (see ThumbProvider).
THUMB_ROOT = Path.home() / ".cache" / "thumbnails"
THUMB_MAX = 256  # the "large" band; tiles are 96px, so 256 is crisp with headroom
THUMB_MAX_SRC = 128 * 1024 * 1024  # skip generating for sources above this (see make_thumb)


def _thumb_uri(path):
    # Must match the URI other thumbnailers hash: the canonical, percent-encoded
    # absolute file:// URI (Path.as_uri() == QUrl's fully-encoded form).
    return Path(os.path.abspath(path)).as_uri()


def _thumb_hash(path):
    return hashlib.md5(_thumb_uri(path).encode("utf-8")).hexdigest()


def _fail_path(path):
    # Per-app failure marker: a file we couldn't decode (truncated download,
    # bogus extension, …). Caching the failure stops us re-attempting the
    # expensive decode on every revisit. Keyed by mtime like a real thumbnail.
    return THUMB_ROOT / "fail" / "filer" / (_thumb_hash(path) + ".png")


def _valid_for(fp, mtime):
    """Load the cached PNG at fp iff its Thumb::MTime still matches the source's
    current mtime; else None (missing/stale/corrupt → caller regenerates)."""
    if not fp.exists():
        return None
    img = QImageReader(str(fp)).read()
    if img.isNull():
        return None
    stored = img.text("Thumb::MTime")
    return img if stored.strip() == str(int(mtime)) else None


def _atomic_write(img, dest, texts):
    """Write img to dest as PNG with the given Thumb:: tEXt metadata, via a
    temp file + rename so a reader never sees a half-written thumbnail."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(dest.parent, 0o700)  # spec: the thumbnails dir is private
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(prefix=".filer-", suffix=".png", dir=str(dest.parent))
    os.close(fd)
    # set the Thumb:: metadata on the image itself — the PNG handler writes an
    # image's embedded text as tEXt chunks reliably (QImageWriter.setText did
    # not round-trip here). This is what makes a thumbnail re-validatable.
    for k, v in texts.items():
        img.setText(k, v)
    writer = QImageWriter(tmp, b"png")
    if not writer.write(img):
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return
    try:
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _generate(path, mtime):
    """Decode the original scaled down to THUMB_MAX, cache it, and return it.
    On decode failure, drop a fail marker and return a null image."""
    reader = QImageReader(path)
    reader.setAutoTransform(True)  # honour EXIF orientation
    size = reader.size()
    if size.isValid() and (size.width() > THUMB_MAX or size.height() > THUMB_MAX):
        reader.setScaledSize(size.scaled(THUMB_MAX, THUMB_MAX, Qt.KeepAspectRatio))
    img = reader.read()
    uri = _thumb_uri(path)
    meta = {"Thumb::URI": uri, "Thumb::MTime": str(int(mtime)), "Software": "filer"}
    if img.isNull():
        _atomic_write(QImage(1, 1, QImage.Format_ARGB32), _fail_path(path), meta)
        return QImage()
    # formats that don't honour setScaledSize (e.g. size wasn't known up front)
    # still need bounding to the standard's max edge.
    if img.width() > THUMB_MAX or img.height() > THUMB_MAX:
        img = img.scaled(THUMB_MAX, THUMB_MAX, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    try:
        meta["Thumb::Size"] = str(os.path.getsize(path))
    except OSError:
        pass
    _atomic_write(img, THUMB_ROOT / "large" / (_thumb_hash(path) + ".png"), meta)
    return img


def make_thumb(path):
    """A ready-to-display thumbnail QImage for `path` (≤THUMB_MAX px), or a null
    QImage if it can't be produced. Prefers the shared cache; regenerates on a
    miss/stale entry; short-circuits known failures. Safe to call off-thread."""
    try:
        st = os.stat(path)
    except OSError:
        return QImage()
    mtime = st.st_mtime
    h = _thumb_hash(path)
    for band in ("large", "normal"):
        hit = _valid_for(THUMB_ROOT / band / (h + ".png"), mtime)
        if hit is not None:
            return hit
    if _valid_for(_fail_path(path), mtime) is not None:
        return QImage()
    # oversized-source guard (cf. Dolphin's "max preview size"): don't tie up a
    # pool thread fully decoding a monster file — render the no-preview marker
    # instead. Placed after the cache lookup so an already-thumbnailed big file
    # still shows instantly.
    if st.st_size > THUMB_MAX_SRC:
        return QImage()
    return _generate(path, mtime)


class ThumbResponse(QQuickImageResponse, QRunnable):
    """One in-flight `image://thumb/<path>` request. Runs make_thumb() on a
    thread-pool worker (QRunnable), then hands the result back to the QML render
    thread via textureFactory — so decoding a big image never stalls the UI."""

    def __init__(self, path):
        QQuickImageResponse.__init__(self)
        QRunnable.__init__(self)
        self.setAutoDelete(False)  # QML owns the response's lifetime, not the pool
        self._path = path
        self._image = QImage()

    def run(self):
        try:
            self._image = make_thumb(self._path)
        except Exception:
            self._image = QImage()
        self.finished.emit()

    def textureFactory(self):
        return QQuickTextureFactory.textureFactoryForImage(self._image)


class ThumbProvider(QQuickAsyncImageProvider):
    """Serves `image://thumb/<abs-path>`. Async so the engine gets a response
    handle immediately and the decode happens on the pool. `image_id` arrives
    percent-decoded and with the URL path's leading slash stripped — restore it
    to recover the absolute path."""

    def __init__(self):
        super().__init__()
        self._pool = QThreadPool()
        # leave cores for the UI/render thread + file ops; thumbnailing is not
        # the only thing filer does.
        self._pool.setMaxThreadCount(max(2, (os.cpu_count() or 4) // 2))

    def requestImageResponse(self, image_id, requested_size):
        path = image_id if image_id.startswith("/") else "/" + image_id
        resp = ThumbResponse(path)
        self._pool.start(resp)
        return resp


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


def _resolve(prog):
    """Absolute path for a program name. QProcess resolves a bare name against
    the launcher's PATH, which — when filer is started from the Quickshell runner
    / a .desktop entry — need not include ~/.nix-profile/bin, so a nix-profile
    binary like `viewer` would be "not found" even though it's installed. Resolve
    it ourselves, falling back to the profile dirs, so opening an image works
    regardless of how filer itself was launched. (`notify.tool` is the same
    lookup videoconv has always used for ffmpeg — one implementation.)"""
    return prog if os.path.isabs(prog) else tool(prog)


def _op_label(argv):
    """What to call this argv in a message the user reads. Derived rather than
    passed in from QML, so a call site cannot forget it and every operation gets
    an honest noun even when a new one is added."""
    prog = os.path.basename(argv[0])
    rest = [a for a in argv[1:] if a != "--" and not a.startswith("-")]
    if prog == "gio":
        return rest[0] if rest else "gio"
    if prog == "mv" and len(rest) == 2 and \
            os.path.dirname(rest[0]) == os.path.dirname(rest[1]):
        return "rename"          # same directory: that is a rename, not a move
    return {"cp": "copy", "mv": "move", "rm": "delete", "ln": "link",
            "mkdir": "new folder"}.get(prog, prog)


def _stderr_lines(text, keep=3):
    """The useful part of a failed helper's stderr. coreutils puts the reason on
    the FIRST line ("cp: cannot create regular file 'x': Permission denied"),
    and a multi-path `rm`/`gio trash` prints one such line per failed file — so
    keep the first few and count the rest rather than the last one."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    out = lines[:keep]
    if len(lines) > keep:
        out.append("+%d more" % (len(lines) - keep))
    return "\n".join(out)


class FileOps(QObject):
    """Backend for shell-outs. argv arrays only — never string interpolation —
    so paths containing spaces or shell metacharacters are safe.

    **Every operation reports its outcome.** `run()` used to wire `finished` and
    `errorOccurred` to one handler that read neither the exit code nor stderr,
    so a denied `rm -rf`, a cross-device `mv`, a full disk and a successful copy
    were indistinguishable on screen — DESIGN.md 10's headline rule, inverted.
    Now a non-zero exit raises a failure toast carrying the helper's own stderr
    (which already names the file and the reason), through the same
    `notify.toast` path videoconv's conversions use. Three distinctions the old
    code collapsed and this one keeps:

      * **failed** vs **could not be started** — `errorOccurred(FailedToStart)`
        means the binary is missing, which is a different sentence ("cannot run
        gio") and a different fix from "trash failed: Permission denied".
      * **partial** vs **total** — a paste of ten items is ten processes, so
        three failures must not read as a flat success *or* as a flat failure.
        QML wraps such a loop in `beginBatch`/`endBatch` and gets one toast
        naming the count: "copy: 3 of 10 failed".
      * **failed** vs **declined** — the no-clobber flags (`cp -an`, `mv -n`)
        exit 0 when they skip, so the overwrite-confirm flow above them is
        untouched: a held-back conflict is still a dialog, never a failure.

    `finished(reselect)` still fires either way, because a failed batch may have
    changed the disk anyway and the view must show what is actually there.
    """

    finished = Signal(str)  # emits the path to reselect after the op ("" = none)
    failed = Signal(str, str)  # (label, message) — same content as the toast

    def __init__(self, parent=None):
        super().__init__(parent)
        self._batches = {}
        self._seq = 0

    # ---- failure reporting ----
    def _report(self, title, message):
        """One failure toast, and the same content on `failed` for anything in
        QML that wants to react to it."""
        self.failed.emit(title, message)
        toast(title, message[:400], urgency="critical")

    @Slot(str, result=str)
    def beginBatch(self, label):
        """Open a group of related `run()`s (a multi-item paste/drop). Returns
        the token to pass as `run`'s third argument. Failures inside a batch are
        collected instead of toasted one by one, and reported once by
        `endBatch` — which must be called, or nothing is ever reported."""
        self._seq += 1
        tok = "b%d" % self._seq
        self._batches[tok] = {"label": str(label) or "file operation",
                              "total": 0, "done": 0, "fails": [], "sealed": False}
        return tok

    @Slot(str)
    def endBatch(self, tok):
        """No more `run()`s will join this batch. Reports now if every process
        has already settled, else the last one to settle reports."""
        b = self._batches.get(str(tok))
        if b is None:
            return
        b["sealed"] = True
        self._settle_batch(str(tok))

    def _settle_batch(self, tok):
        b = self._batches.get(tok)
        if b is None or not b["sealed"] or b["done"] < b["total"]:
            return
        del self._batches[tok]
        if not b["fails"]:
            return
        n, total = len(b["fails"]), b["total"]
        # An honest count, because "3 of 10 failed" and "all 10 failed" are
        # different facts and the seven that landed are on disk either way.
        head = b["label"] + (" failed" if n == total and total == 1 else
                             ": %d of %d failed" % (n, total))
        body = "\n".join(m for _, m in b["fails"][:3])
        if n > 3:
            body += "\n+%d more" % (n - 3)
        self.failed.emit(b["label"], body)
        toast(head, body[:400], urgency="critical")

    @Slot(list, str)
    @Slot(list, str, str)
    def run(self, argv, reselect, batch=""):
        """Run one file operation. `batch` is a `beginBatch` token when this is
        one item of a multi-item transfer, "" for a standalone op."""
        argv = [str(a) for a in argv]
        label = _op_label(argv)
        tok = str(batch)
        b = self._batches.get(tok)
        if b is not None:
            b["total"] += 1
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.SeparateChannels)
        state = {"settled": False, "err": ""}

        def drain():
            try:
                state["err"] += bytes(proc.readAllStandardError()).decode("utf-8", "replace")
            except (RuntimeError, UnicodeError):
                pass

        def settle(message, title=""):
            # errorOccurred(Crashed) and finished() both fire for one crash;
            # latch so a single failure is reported once.
            if state["settled"]:
                return
            state["settled"] = True
            if message:
                if b is not None:
                    b["fails"].append((label, message))
                else:
                    self._report(title or (label + " failed"), message)
            if b is not None:
                b["done"] += 1
                self._settle_batch(tok)
            # Always refresh: a partly-failed batch still moved files.
            self.finished.emit(reselect)
            proc.deleteLater()

        def on_finished(code, status):
            drain()
            err = _stderr_lines(state["err"])
            if status == QProcess.CrashExit:
                settle(err or ("%s crashed" % os.path.basename(argv[0])))
            elif code != 0:
                settle(err or ("%s exited %d" % (os.path.basename(argv[0]), code)))
            else:
                settle("")

        def on_error(err):
            # FailedToStart is the one that is NOT "the operation failed": the
            # helper is missing from filer's PATH, so nothing was attempted.
            prog = os.path.basename(argv[0])
            if err == QProcess.FailedToStart:
                settle("%s: %s" % (prog, proc.errorString()),
                       title="cannot run " + prog)
            elif err != QProcess.Crashed:   # Crashed is reported by on_finished
                drain()
                settle(_stderr_lines(state["err"]) or proc.errorString())

        proc.readyReadStandardError.connect(drain)
        proc.finished.connect(on_finished)
        proc.errorOccurred.connect(on_error)
        proc.start(_resolve(argv[0]), argv[1:])

    @Slot(list, result=bool)
    def execDetached(self, argv):
        """Launch something and forget it (a viewer, a terminal, "open with").
        There is no exit code to wait for, but "the binary does not exist" is
        knowable immediately — and a launcher that silently does nothing is
        exactly what DESIGN.md 10 forbids — so a failed start is toasted."""
        argv = [str(a) for a in argv]
        # PySide returns the `qint64 *pid` out-parameter alongside the bool.
        ok = QProcess.startDetached(_resolve(argv[0]), argv[1:])
        ok = bool(ok[0] if isinstance(ok, tuple) else ok)
        if not ok:
            prog = os.path.basename(argv[0])
            self._report("cannot run " + prog, prog + " is not installed, or not on filer's PATH")
        return ok

    @Slot(list, result=str)
    def writeOrder(self, paths):
        """Hand `viewer` the exact order this window is showing.

        viewer's ‹ / › normally walk its own name-sort of the opened file's
        directory, which is not what the user sees once they have sorted filer by
        size or date. So opening an image writes the displayed paths, in display
        order, to a throwaway file and passes `viewer --order <file>`; viewer
        keeps the media among them and flips through those. NUL-separated: a
        filename may legally contain a newline.

        viewer consumes (unlinks) the file, so it is a launch-time snapshot —
        re-sorting filer afterwards does not disturb an already-open viewer.
        Returns "" if the file can't be written; the caller then launches viewer
        plainly and gets the old directory-scan behaviour."""
        d = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()) / "filer-order"
        try:
            d.mkdir(parents=True, exist_ok=True, mode=0o700)
            now = time.time()
            for stale in d.iterdir():  # a viewer that never started leaves one behind
                try:
                    if now - stale.stat().st_mtime > 300:
                        stale.unlink()
                except OSError:
                    pass
            blob = "\0".join(os.path.abspath(str(p)) for p in paths)
            fd, name = tempfile.mkstemp(dir=str(d), prefix="order-")
            with os.fdopen(fd, "wb") as f:
                f.write(blob.encode("utf-8", "surrogateescape"))
            return name
        except OSError:
            return ""

    @Slot(str, result=str)
    def expandUser(self, path):
        """~ / ~user expansion for the address bar (os.path.expanduser)."""
        return os.path.expanduser(str(path))

    @Slot(str)
    def copyText(self, text):
        """Put text on the system clipboard (the context menu's "copy path").
        QML has no clipboard API of its own, so this bridges to Qt's."""
        QGuiApplication.clipboard().setText(str(text))

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

    @Slot(list, result=str)
    def uriList(self, paths):
        """The `text/uri-list` payload for dragging `paths` out (CRLF-terminated,
        per RFC 2483). QUrl does the percent-encoding, which matters: encodeURI()
        leaves `#` and `?` alone, so a filename containing either used to drag out
        as a truncated path."""
        out = ""
        for p in paths:
            out += QUrl.fromLocalFile(os.path.abspath(str(p))).toString() + "\r\n"
        return out

    @Slot(list, result="QVariantList")
    def urlsToPaths(self, urls):
        """The inverse, for a drop: local absolute paths out of a drag's URLs.
        Anything that isn't a local file (an http:// drag from a browser, say)
        yields no path, so the drop is simply not accepted."""
        out = []
        for u in urls:
            p = (u if isinstance(u, QUrl) else QUrl(str(u))).toLocalFile()
            if p:
                out.append(os.path.normpath(p))
        return out

    @Slot(str, result=bool)
    def isDir(self, path):
        return os.path.isdir(path)

    @Slot(str, result=bool)
    def pathExists(self, path):
        """Whether something already lives at `path` (broken symlinks count).
        Used to guard paste/rename against silently clobbering an existing name."""
        return os.path.lexists(str(path))

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


class DirWatch(QObject):
    """Watches the directories the view is showing (the current dir plus any
    expanded subdirs) and emits `changed` when an entry is added/removed in one
    of them, so the tree picks up external changes — a download landing in the
    viewed folder, another app deleting a file — without navigating away.

    QML pushes the watch set on every rebuild via setDirs(). Kernel events are
    coalesced through a short single-shot timer so a burst (a big copy arriving
    file-by-file) triggers one rebuild, not hundreds. Content edits to existing
    files don't fire directoryChanged — that's fine, the list shows names.

    The set is KEYED, one key per pane: split view has two panes browsing two
    different trees, and an unkeyed setDirs() (which is what this was) would
    have each pane's rebuild replace the other's watches — the second pane
    would silently stop noticing external changes. The watcher holds the union
    of the keys."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sets = {}
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_dir_change)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.changed)

    @Slot(str, "QVariantList")
    def setDirs(self, key, dirs):
        """Replace one pane's watch set (an empty list retires the pane)."""
        self._sets[str(key)] = [str(d) for d in dirs if os.path.isdir(str(d))]
        want = set()
        for paths in self._sets.values():
            want.update(paths)
        old = set(self._watcher.directories())
        if old == want:
            return
        if old:
            self._watcher.removePaths(list(old))
        if want:
            self._watcher.addPaths(sorted(want))

    def _on_dir_change(self, _path):
        # If a watched dir was deleted+recreated the watch is gone; setDirs()
        # re-adds it on the rebuild this triggers.
        self._timer.start()


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

    def _flush(self):
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_PATH.write_text(json.dumps(self._data), encoding="utf-8")
        except OSError:
            pass

    @Slot(str, "QVariant")
    def set(self, key, val):
        """Persist a single UI-state key (e.g. the preview-panel height). Kept
        separate from save() so QML can store one-off bits without the fixed
        nav/sort tuple."""
        self._data[key] = val
        self._flush()

    @Slot(str, str, bool, bool)
    def save(self, directory, sort_field, sort_asc, show_hidden):
        self._data["dir"] = directory
        self._data["sortField"] = sort_field
        self._data["sortAsc"] = bool(sort_asc)
        self._data["showHidden"] = bool(show_hidden)
        self._flush()


class Titlebar(QObject):
    """Bridge to the hyprvtb titlebar's app-button column (the inner half of
    the compositor's double-wide bar — where filer's sort/op strip moved).

    QML pushes the full button set whenever any label/state changes, and
    receives clicks back through the `clicked` signal. VtbClient's callback
    fires on its reader thread; emitting a Signal from there is safe — Qt
    queues the delivery onto the main thread for the QML Connections item.

    The window title is also the editable address bar: `setTitleEdit(True)`
    marks the plugin's title region an in-bar path editor (same as surfer's URL
    bar), and submitting it (Enter) bounces back through `addrSubmitted`."""

    clicked = Signal(str)
    addrSubmitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = VtbClient(on_click=self.clicked.emit,
                                 on_addr=self.addrSubmitted.emit)

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

    @Slot(bool)
    def setTitleEdit(self, on):
        """Mark the title region an editable address bar (the path bar)."""
        self._client.set_title_edit(on)


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

    # `filer --pick <spec.json>` runs the window as a modal file chooser for the
    # portal backend (pick.py / portal.py). An unusable spec is a hard exit: the
    # backend reads "no result file" as a cancel, so opening an ordinary browser
    # window here would leave the calling app's dialog waiting on a window the
    # user has no reason to close.
    spec = None
    if "--pick" in sys.argv[1:]:
        i = sys.argv.index("--pick")
        if i + 1 >= len(sys.argv):
            print("filer: --pick needs a spec file", file=sys.stderr)
            sys.exit(2)
        spec = load_spec(sys.argv[i + 1])
        if spec is None:
            sys.exit(2)
    picker = Picker(spec)

    # Start directory: while picking, the requested current_folder wins (falling
    # through to the same rules if it is missing or gone). Otherwise an explicit
    # existing-directory argument (e.g. `filer /mnt/foo`, used by the disk
    # widget's open button); otherwise reopen the last-viewed directory;
    # otherwise home.
    start_dir = None
    if spec:
        cf = spec.get("current_folder")
        if cf and os.path.isdir(cf):
            start_dir = os.path.abspath(cf)
    if start_dir is None:
        for arg in sys.argv[1:]:
            if arg != "--pick" and os.path.isdir(arg):
                start_dir = os.path.abspath(arg)
                break
    if start_dir is None:
        saved = settings.value("dir", "")
        start_dir = saved if saved and os.path.isdir(saved) else str(Path.home())

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()

    # thumbnails via the shared freedesktop cache (see make_thumb / ThumbProvider).
    # The engine takes ownership of the provider; keep this local ref alive too so
    # the Python-side virtual override isn't collected while exec() runs.
    thumb_provider = ThumbProvider()
    engine.addImageProvider("thumb", thumb_provider)

    ops = FileOps()
    palette = Palette(PANEL_THEME)
    style = DeskStyle()
    winctl = WinCtl()
    titlebar = Titlebar()
    dirwatch = DirWatch()
    videoconv = VideoConv()
    # NB: exposed as "WalPalette", not "Palette" — "Palette" is a built-in Qt
    # Quick type name and would shadow the context property.
    # WalPalette first, so Theme's bindings resolve it when Theme is instantiated.
    ctx.setContextProperty("FileOps", ops)
    ctx.setContextProperty("DirWatch", dirwatch)
    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("DeskStyle", style)
    ctx.setContextProperty("WinCtl", winctl)
    ctx.setContextProperty("Titlebar", titlebar)
    ctx.setContextProperty("Settings", settings)
    ctx.setContextProperty("VideoConv", videoconv)
    ctx.setContextProperty("Picker", picker)
    ctx.setContextProperty("startDir", start_dir)
    # Last-used sort + hidden-files toggle, restored into the view on startup.
    ctx.setContextProperty("startSortField", settings.value("sortField", "name"))
    ctx.setContextProperty("startSortAsc", bool(settings.value("sortAsc", True)))
    ctx.setContextProperty("startShowHidden", bool(settings.value("showHidden", True)))
    # last preview-panel height (px), restored into view.gridPanelH on startup.
    ctx.setContextProperty("startGridPanelH", int(settings.value("gridPanelH", 200) or 200))
    # split view, as it was left: whether it was open, which way it was divided,
    # what the TRAILING pane was showing (the leading one is the ordinary "dir"
    # above) and where the divider sat. A picker never restores it — Main.qml
    # gates on `picking`.
    split_dir = settings.value("splitDir", "") or ""
    ctx.setContextProperty("startSplit", bool(settings.value("split", False)))
    ctx.setContextProperty("startSplitDir", split_dir if os.path.isdir(split_dir) else "")
    # orientation: true = side by side (the `|` button), false = stacked (`_`).
    # A state.json written before the split grew an axis has no such key at all,
    # and must restore as the side-by-side split that was then the only one —
    # hence the True default rather than a falsy one.
    ctx.setContextProperty("startSplitVertical",
                           bool(settings.value("splitVertical", True)))
    try:
        ratio = float(settings.value("splitRatio", 0.5))
    except (TypeError, ValueError):
        ratio = 0.5
    ctx.setContextProperty("startSplitRatio", min(0.85, max(0.15, ratio)))

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
