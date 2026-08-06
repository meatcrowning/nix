#!/usr/bin/env python3
"""painter — text-to-image front end for a headless ComfyUI.

The fifth sibling of surfer/filer/viewer/player: PySide6 + QML, themed by the
live wallpaper palette, chrome in the hyprvtb titlebar.

What it is for: pick a diffusion model and generate.  Everything downstream of
that choice is worked out here rather than asked of you -- the matching text
encoder and VAE, the graph, sensible sampler defaults, and which LoRAs can even
apply.  Models are identified by reading their tensor headers (fingerprint.py),
so a model that did not exist when this was written still lands in the right
family; anything unrecognised stays visible and can be assigned by hand.

There is one graph (graphs/universal.json) for every family.  Differences are
values, two optional nodes (CLIPNegPip and ModelSamplingSD3Advanced, both
toggleable here), or a node-class swap at a single slot.  The sole exception is
a bundled checkpoint, which needs CheckpointLoaderSimple instead of the
loader/clip/vae trio.

ComfyUI itself runs as a systemd --user unit, started on demand and left running
so weights stay warm between launches:  journalctl --user -u comfy-painter -f
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QFileSystemWatcher, QModelIndex,
                            QObject, Property, QProcess, QSortFilterProxyModel, Qt,
                            QTimer, QUrl, Signal, Slot)
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"

sys.path.insert(0, str(HERE.parent / "pylib"))
try:
    from vtbclient import VtbClient  # noqa: E402
except Exception:  # noqa: BLE001 - the titlebar bridge is optional
    VtbClient = None
from deskstyle import DeskStyle  # noqa: E402  (pylib; the desktop-wide font setting)
from spellcheck import SpellCheck  # noqa: E402  (pylib; the prompt boxes' spelling)

sys.path.insert(0, str(HERE))
import comfy as C  # noqa: E402
import graph as G  # noqa: E402
import pngmeta  # noqa: E402
import registry as R  # noqa: E402

OUT_DIR = Path(os.environ.get("PAINTER_OUT", Path.home() / "Pictures" / "painter" / "out"))
STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "painter"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "painter"
PREFS = STATE / "prefs.json"
UNIT = "comfy-painter.service"

# WHERE THE BACKEND'S UNIT LIVES. On top it is local, so this is plain
# `systemctl --user`. On book there is no comfy-painter.service at all
# (home/prog/painter.nix gates the unit on host != "air") — the backend is
# top's, reached through the ssh forward that comfy-tunnel.sh holds open, and a
# LOCAL systemctl there fails with "unit not found" for every start, stop and
# status: the app opened saying "backend failed to start" while the backend it
# was tunnelled to sat there running. So the launcher exports the host it
# resolved and we drive systemd over the same ssh connection.
#
# The control socket matters: `is-active` runs every 3s, and paying a full ssh
# handshake for each would be ~0.2s of network per poll. Same master the
# launcher already opened, so this rides a connection that exists.
BACKEND_SSH = os.environ.get("PAINTER_BACKEND_SSH", "")
_SSH_BIN = os.environ.get("PAINTER_BACKEND_SSH_BIN", "/usr/bin/ssh")
_SSH_CTL = os.environ.get("PAINTER_BACKEND_SSH_CTL", "")


def unit_cmd(*verb: str) -> list[str]:
    """`systemctl --user <verb> comfy-painter.service`, here or on top."""
    local = ["systemctl", "--user", *verb, UNIT]
    if not BACKEND_SSH:
        return local
    ssh = [_SSH_BIN, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
    if _SSH_CTL:
        ssh += ["-o", "ControlMaster=auto", "-o", "ControlPersist=30",
                "-o", f"ControlPath={_SSH_CTL}"]
    return ssh + [BACKEND_SSH, " ".join(local)]


PANEL_THEME = Path.home() / ".config" / "quickshell" / "Theme.qml"
PALETTE_KEYS = ["bg", "bgAlt", "border", "accent", "dim", "text", "textDim",
                "highlight", "ok", "warn", "crit", "info"]
PALETTE_DEFAULTS = {
    "bg": "#000000", "bgAlt": "#120b08", "border": "#382216", "accent": "#cc4400",
    "dim": "#54382a", "text": "#cc4400", "textDim": "#8c5438", "highlight": "#21140d",
    "ok": "#e08e65", "warn": "#b86237", "crit": "#fa5c0c", "info": "#ad7457",
}



# ---------------------------------------------------------------------------


class Palette(QObject):
    """The live wallpaper palette, parsed from the panel's Theme.qml."""

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

    def _on_change(self, *_):
        self._rewatch()
        QTimer.singleShot(80, self._load)

    def _load(self):
        try:
            text = Path(self._path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        import re

        found = {}
        for key in PALETTE_KEYS:
            m = re.search(rf'property\s+color\s+{key}\s*:\s*"([^"]+)"', text)
            if m:
                found[key] = m.group(1)
        if found and found != {k: self._colors.get(k) for k in found}:
            self._colors.update(found)
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


class Prefs(QObject):
    """Small persisted settings bag (window state, last model, defaults)."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc = {}
        try:
            self._doc = json.loads(PREFS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    @Slot(str, result="QVariant")
    def get(self, key):
        return self._doc.get(key)

    @Slot(str, "QVariant")
    def set(self, key, value):
        if self._doc.get(key) == value:
            return
        self._doc[key] = value
        STATE.mkdir(parents=True, exist_ok=True)
        tmp = PREFS.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._doc, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, PREFS)
        self.changed.emit()


# ---------------------------------------------------------------------------
# list models
# ---------------------------------------------------------------------------


class ModelList(QAbstractListModel):
    """Base models, each already resolved to its encoder/VAE pairing."""

    NameRole = Qt.UserRole + 1
    FamilyRole = Qt.UserRole + 2
    LabelRole = Qt.UserRole + 3
    PairingRole = Qt.UserRole + 4
    QuantRole = Qt.UserRole + 5
    SizeRole = Qt.UserRole + 6
    ProblemRole = Qt.UserRole + 7
    KnownRole = Qt.UserRole + 8
    PathRole = Qt.UserRole + 9
    OverriddenRole = Qt.UserRole + 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []

    def roleNames(self):
        return {
            self.NameRole: b"name", self.FamilyRole: b"family",
            self.LabelRole: b"label", self.PairingRole: b"pairing",
            self.QuantRole: b"quant", self.SizeRole: b"size",
            self.ProblemRole: b"problem", self.KnownRole: b"known",
            self.PathRole: b"path", self.OverriddenRole: b"overridden",
        }

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        row = self._rows[index.row()]
        return row.get(self.roleNames().get(role, b"").decode() or "name")

    def set_rows(self, rows):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def entry_at(self, i):
        if 0 <= i < len(self._rows):
            return self._rows[i]["entry"]
        return None

    def index_of_name(self, name):
        for i, r in enumerate(self._rows):
            if r["name"] == name:
                return i
        return -1


class LoraStack(QAbstractListModel):
    """The ordered LoRA chain; order matters, so it is user-reorderable."""

    NameRole = Qt.UserRole + 1
    StrengthRole = Qt.UserRole + 2
    EnabledRole = Qt.UserRole + 3
    ClipRole = Qt.UserRole + 4

    countChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []

    def roleNames(self):
        return {self.NameRole: b"name", self.StrengthRole: b"strength",
                self.EnabledRole: b"enabled", self.ClipRole: b"patchesClip"}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r = self._rows[index.row()]
        return {self.NameRole: r["name"], self.StrengthRole: r["strength"],
                self.EnabledRole: r["enabled"], self.ClipRole: r["patches_clip"]}.get(role)

    @Slot(str, bool)
    def add(self, name, patches_clip=False):
        if any(r["name"] == name for r in self._rows):
            return
        self.beginInsertRows(QModelIndex(), len(self._rows), len(self._rows))
        self._rows.append({"name": name, "strength": 1.0, "enabled": True,
                           "patches_clip": bool(patches_clip)})
        self.endInsertRows()
        self.countChanged.emit()

    @Slot(int)
    def remove(self, i):
        if not (0 <= i < len(self._rows)):
            return
        self.beginRemoveRows(QModelIndex(), i, i)
        self._rows.pop(i)
        self.endRemoveRows()
        self.countChanged.emit()

    @Slot()
    def clear(self):
        if not self._rows:
            return
        self.beginResetModel()
        self._rows = []
        self.endResetModel()
        self.countChanged.emit()

    @Slot(int, float)
    def setStrength(self, i, value):
        if 0 <= i < len(self._rows):
            self._rows[i]["strength"] = float(value)
            idx = self.index(i, 0)
            self.dataChanged.emit(idx, idx, [self.StrengthRole])

    @Slot(int, bool)
    def setEnabled(self, i, value):
        if 0 <= i < len(self._rows):
            self._rows[i]["enabled"] = bool(value)
            idx = self.index(i, 0)
            self.dataChanged.emit(idx, idx, [self.EnabledRole])

    @Slot(int, int)
    def move(self, frm, to):
        if not (0 <= frm < len(self._rows) and 0 <= to < len(self._rows)) or frm == to:
            return
        self.beginResetModel()
        row = self._rows.pop(frm)
        self._rows.insert(to, row)
        self.endResetModel()

    def active(self):
        return [dict(r) for r in self._rows if r["enabled"]]


class LoraChoices(QAbstractListModel):
    """Every LoRA on disk, tagged with whether it fits the selected model."""

    NameRole = Qt.UserRole + 1
    OkRole = Qt.UserRole + 2
    ReasonRole = Qt.UserRole + 3
    ScoreRole = Qt.UserRole + 4
    ClipRole = Qt.UserRole + 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []

    def roleNames(self):
        return {self.NameRole: b"name", self.OkRole: b"compatible",
                self.ReasonRole: b"reason", self.ScoreRole: b"score",
                self.ClipRole: b"patchesClip"}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r = self._rows[index.row()]
        return {self.NameRole: r["name"], self.OkRole: r["ok"],
                self.ReasonRole: r["reason"], self.ScoreRole: r["score"],
                self.ClipRole: r["patches_clip"]}.get(role)

    def set_rows(self, rows):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()


VIDEO_SUFFIXES = (".mp4", ".webm", ".mkv")


class Gallery(QAbstractListModel):
    PathRole = Qt.UserRole + 1
    UrlRole = Qt.UserRole + 2
    NameRole = Qt.UserRole + 3
    VideoRole = Qt.UserRole + 4
    PosterRole = Qt.UserRole + 5

    countChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        # Poster frames are extracted one at a time, off the GUI thread. A
        # gallery of 60 videos would otherwise fork 60 ffmpegs at once on a
        # machine that is already busy sampling.
        self._poster_queue = []
        self._poster_proc = None

    def roleNames(self):
        return {self.PathRole: b"path", self.UrlRole: b"url", self.NameRole: b"name",
                self.VideoRole: b"isVideo", self.PosterRole: b"poster"}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r = self._rows[index.row()]
        return {self.PathRole: r["path"], self.UrlRole: r["url"],
                self.NameRole: r["name"], self.VideoRole: r["is_video"],
                self.PosterRole: r["poster"]}.get(role)

    def _row_for(self, path):
        p = Path(path)
        is_video = p.suffix.lower() in VIDEO_SUFFIXES
        return {"path": str(p), "url": QUrl.fromLocalFile(str(p)).toString(),
                "name": p.name, "is_video": is_video, "poster": ""}

    def add(self, path):
        self.beginInsertRows(QModelIndex(), 0, 0)
        self._rows.insert(0, self._row_for(path))
        self.endInsertRows()
        self.countChanged.emit()
        if self._rows[0]["is_video"]:
            self._want_poster(self._rows[0]["path"])

    def load_existing(self, limit=60):
        # Videos land in a subdirectory of their own, because that is where
        # SaveVideo's filename_prefix puts them — a gallery that only globbed
        # *.png here would show nothing at all for a video model.
        try:
            files = list(OUT_DIR.glob("*.png"))
            for suffix in VIDEO_SUFFIXES:
                files += list(OUT_DIR.glob(f"video/*{suffix}"))
            files = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
        except OSError:
            return
        self.beginResetModel()
        self._rows = [self._row_for(p) for p in files]
        self.endResetModel()
        self.countChanged.emit()
        for r in self._rows:
            if r["is_video"]:
                self._want_poster(r["path"])

    # -- poster frames -----------------------------------------------------

    def _poster_path(self, path):
        st = os.stat(path)
        stem = f"{Path(path).stem}-{int(st.st_mtime)}-{st.st_size}.jpg"
        return CACHE / "posters" / stem

    def _want_poster(self, path):
        try:
            dest = self._poster_path(path)
        except OSError:
            return
        if dest.exists():
            self._poster_ready(path, dest)
            return
        self._poster_queue.append((path, dest))
        self._next_poster()

    def _next_poster(self):
        if self._poster_proc is not None or not self._poster_queue:
            return
        path, dest = self._poster_queue.pop(0)
        dest.parent.mkdir(parents=True, exist_ok=True)
        proc = QProcess(self)
        self._poster_proc = proc

        def finished(*_):
            # Defensive at both ends, like _run_async: at teardown the C++ side
            # of this model (or of the process) can be gone while ffmpeg is
            # still exiting, and an exception raised out of a signal handler is
            # caught by nobody — it landed in the middle of startup and cost
            # the harness three unrelated checks. A missing poster is cheap.
            try:
                if self._poster_proc is not proc:
                    return
                self._poster_proc = None
                if dest.exists():
                    self._poster_ready(path, dest)
                proc.deleteLater()
                self._next_poster()
            except RuntimeError:
                pass

        proc.finished.connect(finished)
        # A tile is 210px at most, and a poster that fails is simply absent —
        # the delegate falls back to the play marker rather than showing a gap.
        proc.errorOccurred.connect(lambda *_: None)
        proc.start("ffmpeg", ["-nostdin", "-loglevel", "error", "-y", "-ss", "0",
                              "-i", path, "-frames:v", "1",
                              "-vf", "scale=420:-1", str(dest)])

    def _poster_ready(self, path, dest):
        for i, r in enumerate(self._rows):
            if r["path"] == path:
                r["poster"] = QUrl.fromLocalFile(str(dest)).toString()
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx, [self.PosterRole])
                return

    @Slot(int, result="QVariant")
    def paramsAt(self, i):
        if not (0 <= i < len(self._rows)):
            return None
        # Only a PNG carries painter's parameters. A video's own metadata holds
        # the ComfyUI graph, which is not the same thing and is not injectable.
        if self._rows[i]["is_video"]:
            return None
        try:
            return pngmeta.load_params(Path(self._rows[i]["path"]).read_bytes())
        except OSError:
            return None


# ---------------------------------------------------------------------------
# the controller QML talks to
# ---------------------------------------------------------------------------


class Painter(QObject):
    statusChanged = Signal()
    modelChanged = Signal()
    busyChanged = Signal()
    optionsChanged = Signal()
    inputImageChanged = Signal()
    toast = Signal(str, bool)          # message, isError

    def __init__(self, parent=None):
        super().__init__(parent)
        self.models = ModelList(self)
        self.loras = LoraStack(self)
        self.choices = LoraChoices(self)
        self.gallery = Gallery(self)

        self._status = "starting backend..."
        self._busy = False
        self._queue = 0
        self._progress = 0.0
        self._current = ""
        self._selected = -1
        self._enc_name = ""
        self._vae_name = ""
        self._fam_label = ""
        self._samplers = []
        self._schedulers = []
        self._curves = []
        self._windows = []
        self._object_info = None
        self._jobs = 0
        self._unit_state = "unknown"
        self._job_start = 0.0             # when the running job started, for the clock
        self._input_image = ""            # the first frame, as a local path
        self._uploaded = ("", "")         # (local path, the ref ComfyUI knows it by)

        self.reg = None
        self.client = C.ComfyClient()
        self.client.statusChanged.connect(self._on_queue)
        self.client.jobStarted.connect(self._on_started)
        self.client.jobProgress.connect(self._on_progress)
        self.client.jobNode.connect(self._on_node)
        self.client.jobFinished.connect(self._on_finished)
        self.client.jobFailed.connect(self._on_failed)
        self.client.connected.connect(self._on_ws_connected)

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        self.gallery.load_existing()

        self._procs = []                  # live QProcesses, so none is GC'd mid-run
        self._want_model = ""             # a remembered selection, until the rows land
        QTimer.singleShot(0, self.startBackend)
        # THE MODEL LIST DOES NOT NEED THE BACKEND. It used to be built only when
        # /object_info landed, so painter opened to an empty picker and sat there
        # until ComfyUI had finished loading — on a cold start, minutes of
        # looking at nothing. The registry reads model headers off disk (over
        # book's sshfs mount), so it can answer straight away; the backend still
        # fills in the sampler/scheduler lists when it arrives.
        QTimer.singleShot(0, self.rescan)
        # ...and again while it comes up empty, because on book the model root is
        # an sshfs mount the launcher may still be making (it no longer blocks the
        # window on it). Six tries over six seconds, then it stops asking: an
        # empty root really is empty, and a scan of one costs nothing.
        self._scan_tries = 0
        self._scan_retry = QTimer(self)
        self._scan_retry.setInterval(1000)
        self._scan_retry.timeout.connect(self._retry_scan)
        self._scan_retry.start()
        self._probe = QTimer(self)
        self._probe.setInterval(2000)
        self._probe.timeout.connect(self._poll_backend)

        # The unit can also be started or stopped from outside painter, so the
        # start/stop controls track it on a timer rather than only after a
        # click. It runs for the app's whole life: a control that is right only
        # while its drawer happens to be open is not a control that reflects
        # state.
        # A per-cent with no clock beside it says how far, never how long. The
        # tick only runs while something is running, and it drives the same
        # statusChanged everything else in the bar reads.
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self.statusChanged.emit)

        self._unit_poll = QTimer(self)
        self._unit_poll.setInterval(3000)
        self._unit_poll.timeout.connect(self._refresh_unit)
        self._unit_poll.start()
        self._refresh_unit()

    # -- properties --------------------------------------------------------

    def _get_status(self):
        return self._status

    def _set_status(self, s):
        if s != self._status:
            self._status = s
            self.statusChanged.emit()

    status = Property(str, _get_status, notify=statusChanged)
    queue = Property(int, lambda self: self._queue, notify=statusChanged)
    progress = Property(float, lambda self: self._progress, notify=statusChanged)
    currentNode = Property(str, lambda self: self._current, notify=statusChanged)
    busy = Property(bool, lambda self: self._busy, notify=busyChanged)
    # Seconds the running job has been going, so the bar can say how long as
    # well as how far. Zero when nothing is running.
    elapsed = Property(float, lambda self: (
        max(0.0, time.time() - self._job_start) if (self._busy and self._job_start) else 0.0),
        notify=statusChanged)
    ready = Property(bool, lambda self: self._object_info is not None, notify=statusChanged)
    # What systemd says about comfy-painter.service, so start/stop can be lit
    # from the world instead of from intent (docs/DESIGN.md §10).
    unitState = Property(str, lambda self: self._unit_state, notify=statusChanged)
    backendRunning = Property(bool, lambda self: self._unit_state in ("active", "activating"),
                              notify=statusChanged)
    samplers = Property("QStringList", lambda self: self._samplers, notify=optionsChanged)
    schedulers = Property("QStringList", lambda self: self._schedulers, notify=optionsChanged)
    curves = Property("QStringList", lambda self: self._curves, notify=optionsChanged)
    outsideWindows = Property("QStringList", lambda self: self._windows, notify=optionsChanged)
    selectedIndex = Property(int, lambda self: self._selected, notify=modelChanged)
    encoderName = Property(str, lambda self: self._enc_name, notify=modelChanged)
    vaeName = Property(str, lambda self: self._vae_name, notify=modelChanged)
    familyLabel = Property(str, lambda self: self._fam_label, notify=modelChanged)
    # The selected model's own name. The model panel collapses now, and collapsed
    # its header badge is the only thing left saying what will be generated with.
    selectedName = Property(str, lambda self: getattr(
        self.models.entry_at(self._selected), "name", ""), notify=modelChanged)
    # WHAT THE SELECTED MODEL MAKES. A video family has one prompt and no
    # negative, no CFG, a duration instead of a batch, and its frame size comes
    # from the dropped image when there is one — so the left column follows this
    # rather than offering controls the graph would ignore.
    isVideo = Property(bool, lambda self: self._family_kind() == "video",
                       notify=modelChanged)
    inputImage = Property(str, lambda self: self._input_image, notify=inputImageChanged)
    inputImageUrl = Property(str, lambda self: (
        QUrl.fromLocalFile(self._input_image).toString() if self._input_image else ""),
        notify=inputImageChanged)

    def _family_kind(self):
        entry = self.models.entry_at(self._selected)
        if entry is None or self.reg is None:
            return ""
        return (self.reg.family_of(entry) or {}).get("kind", "image")

    # -- the first frame ---------------------------------------------------

    @Slot(str, result=bool)
    def setInputImage(self, url):
        """Take a dropped file as the first frame, if it is one we can send."""
        path = QUrl(url).toLocalFile() if url.startswith("file:") else url
        if not path or not os.path.isfile(path):
            self.toast.emit("that is not a file painter can read", True)
            return False
        if Path(path).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            self.toast.emit("drop an image (png, jpg, webp)", True)
            return False
        self._input_image = path
        self._uploaded = ("", "")     # a new file has not been uploaded yet
        self.inputImageChanged.emit()
        return True

    @Slot(str)
    def restoreInputImage(self, path):
        """The remembered first frame, silently — a file that has since moved
        is not something to greet him with a toast about at launch."""
        if path and os.path.isfile(path):
            self._input_image = path
            self._uploaded = ("", "")
            self.inputImageChanged.emit()

    @Slot()
    def clearInputImage(self):
        self._input_image = ""
        self._uploaded = ("", "")
        self.inputImageChanged.emit()

    # -- backend -----------------------------------------------------------

    # The unit's real state, refreshed on a timer and after every action, so
    # the start/stop controls can be lit from what systemd says rather than
    # from what the last click intended. "activating" counts as running: the
    # unit is up, ComfyUI just has not finished loading.
    # NOTHING HERE MAY BLOCK THE GUI THREAD. These are `systemctl` calls, and on
    # book every one of them is an ssh round trip to top — run synchronously at
    # startup they held the window closed before it had painted a pixel, which
    # is most of what "painter takes a while to start" was. QProcess instead:
    # the window comes up immediately and the answer arrives when it arrives.
    def _run_async(self, argv, done=None):
        proc = QProcess(self)
        self._procs.append(proc)

        def finished(*_):
            # Defensive on both ends: a QProcess whose C++ side has already gone
            # (teardown, or a second emission after deleteLater) would otherwise
            # raise out of a signal handler, where nothing can catch it.
            if proc not in self._procs:
                return
            self._procs.remove(proc)
            try:
                out = (bytes(proc.readAllStandardOutput()).decode(errors="replace")
                       + bytes(proc.readAllStandardError()).decode(errors="replace"))
                rc = proc.exitCode()
            except RuntimeError:
                return
            if done:
                done(rc, out.strip())
            proc.deleteLater()

        proc.finished.connect(finished)
        proc.errorOccurred.connect(lambda *_: None)   # reported through finished
        proc.start(argv[0], argv[1:])
        return proc

    # The unit's real state, refreshed on a timer and after every action, so
    # the start/stop controls can be lit from what systemd says rather than
    # from what the last click intended. "activating" counts as running: the
    # unit is up, ComfyUI just has not finished loading.
    def _refresh_unit(self):
        def got(_rc, out):
            state = out.splitlines()[-1].strip() if out else "unknown"
            if state != self._unit_state:
                self._unit_state = state
                self.statusChanged.emit()

        self._run_async(unit_cmd("is-active"), got)

    @Slot()
    def startBackend(self):
        self._set_status("starting ComfyUI...")

        def done(rc, out):
            self._refresh_unit()
            if rc != 0:
                detail = out.splitlines()
                self._set_status("backend failed to start")
                self.toast.emit("systemctl start failed: "
                                + (detail[-1] if detail else f"exit {rc}"), True)
                return
            self._set_status("waiting for ComfyUI...")
            self._probe.start()
            self._poll_backend()

        self._run_async(unit_cmd("start"), done)

    @Slot()
    def stopBackend(self):
        def done(rc, out):
            self._refresh_unit()
            # Report what happened, not what was asked for: a non-zero exit with
            # a "backend stopped" label is the exact "reports a change that did
            # not happen" failure docs/DESIGN.md §10 forbids.
            if rc != 0:
                detail = out.splitlines()
                self.toast.emit("systemctl stop failed: "
                                + (detail[-1] if detail else f"exit {rc}"), True)
                return
            self._probe.stop()
            self._object_info = None
            self._set_status("backend stopped")

        self._run_async(unit_cmd("stop"), done)

    def _poll_backend(self):
        def got(doc):
            if not doc:
                return
            self._probe.stop()
            ver = (doc.get("system") or {}).get("comfyui_version", "?")
            self._set_status(f"ComfyUI {ver}")
            self.client.connect_ws()
            self.client.fetch_object_info(self._on_object_info)

        self.client.fetch_stats(got)

    def _on_ws_connected(self):
        if self._object_info is None:
            self.client.fetch_object_info(self._on_object_info)

    def _on_object_info(self, oi):
        if not oi:
            self._set_status("ComfyUI reachable but /object_info failed")
            return
        self._object_info = oi
        self._samplers = G.enum_values(oi, "KSamplerSelect", "sampler_name") or []
        self._schedulers = G.enum_values(oi, "BasicScheduler", "scheduler") or []
        self._curves = G.enum_values(oi, "ModelSamplingSD3Advanced", "curve") or []
        self._windows = G.enum_values(oi, "ModelSamplingSD3Advanced", "outside_window") or []
        self.optionsChanged.emit()
        # Only if the startup scan found nothing (an empty or unreadable model
        # root at launch): the list is normally already up by now, and rebuilding
        # it would throw away the selection.
        if self.models.rowCount() == 0:
            self.rescan()
        self.statusChanged.emit()

    # -- models ------------------------------------------------------------

    @Slot()
    def rescan(self):
        self.reg = R.Registry()
        rows = []
        for e in self.reg.base_models():
            pairing = self.reg.pair(e)
            fam = pairing["family"]
            if fam and pairing["encoder"]:
                desc = f"{pairing['encoder'].name}  +  {pairing['vae'].name}"
            elif fam:
                desc = "encoder and VAE bundled in the checkpoint"
            else:
                desc = "unrecognised - pick a family"
            rows.append({
                "entry": e, "name": e.name, "family": e.family or "unknown",
                "label": (fam or {}).get("label", e.family or "unknown"),
                "pairing": desc, "quant": e.quant or "",
                "size": _human(e.size),
                "problem": "; ".join(pairing["problems"]),
                "known": bool(fam) and not pairing["problems"],
                "path": e.path, "overridden": e.overridden,
            })
        rows.sort(key=lambda r: (not r["known"], r["label"].lower(), r["name"].lower()))
        self.models.set_rows(rows)
        want = getattr(self, "_want_model", "")
        if want:
            for i in range(self.models.rowCount()):
                e = self.models.entry_at(i)
                if e is not None and e.name == want:
                    self._want_model = ""
                    self.selectModel(i)
                    break
            else:
                self.selectModel(0 if rows else -1)
        elif self._selected < 0 and rows:
            self.selectModel(0)
        else:
            self.selectModel(min(self._selected, len(rows) - 1))
        self._set_status(f"{len(rows)} models")

    def _retry_scan(self):
        self._scan_tries += 1
        if self.models.rowCount() > 0 or self._scan_tries > 6:
            self._scan_retry.stop()
            return
        self.rescan()

    @Slot(str)
    def selectModelByName(self, name):
        """Restore a remembered selection.

        Called from Component.onCompleted, which runs BEFORE the scan has
        finished, so the wanted name is also remembered and applied when the rows
        land — otherwise the restore would be a silent no-op on every launch,
        which is the same as not remembering at all.
        """
        self._want_model = name or ""
        if not name:
            return
        for i in range(self.models.rowCount()):
            e = self.models.entry_at(i)
            if e is not None and e.name == name:
                self._want_model = ""
                if i != self._selected:
                    self.selectModel(i)
                return

    @Slot(int)
    def selectModel(self, i):
        self._selected = i
        entry = self.models.entry_at(i)
        if entry is None:
            return
        pairing = self.reg.pair(entry)
        self._enc_name = getattr(pairing["encoder"], "name", "")
        self._vae_name = getattr(pairing["vae"], "name", "")
        self._fam_label = (pairing["family"] or {}).get("label", entry.family or "")
        ok, bad = self.reg.compatible_loras(entry)
        rows = [{"name": e.name, "ok": True, "reason": v["reason"],
                 "score": v["score"], "patches_clip": e.patches_clip}
                for e, v in ok]
        rows += [{"name": e.name, "ok": False, "reason": v["reason"],
                  "score": v["score"], "patches_clip": e.patches_clip}
                 for e, v in bad]
        self.choices.set_rows(rows)
        self.loras.clear()
        self.modelChanged.emit()

    @Slot(result="QVariant")
    def modelDefaults(self):
        entry = self.models.entry_at(self._selected)
        if entry is None or self.reg is None:
            return {}
        fam = self.reg.family_of(entry) or {}
        d = dict(self.reg.defaults_for(entry))
        d["toggles"] = dict(fam.get("toggles") or {})
        d["model_sampling"] = dict(fam.get("model_sampling") or {})
        res = fam.get("resolution") or {}
        d["aspect"] = res.get("aspect", "1:1")
        d["megapixels"] = res.get("megapixels", 1.0)
        d["multiple"] = res.get("multiple", 64)
        d["promptTransform"] = fam.get("prompt_transform", "none")
        d["kind"] = fam.get("kind", "image")
        vid = fam.get("video") or {}
        d["duration"] = vid.get("duration", 5.0)
        d["fps"] = vid.get("fps", 24.0)
        d["clipTypeSignificant"] = ((fam.get("text_encoder") or {})
                                    .get("clip_type_significant", True))
        return d

    @Slot(str, float, int, result="QVariant")
    def dims(self, aspect, megapixels, multiple):
        w, h = R.calc_dims(aspect, megapixels, multiple)
        return {"width": w, "height": h}

    @Slot(int, str)
    def assignFamily(self, i, family):
        entry = self.models.entry_at(i)
        if entry is None:
            return
        role = "checkpoint" if family.endswith("_ckpt") else "diffusion"
        self.reg.overrides.set_file(entry.path, family=family, role=role)
        self.toast.emit(f"{os.path.basename(entry.path)} -> {family}", False)
        self.rescan()

    @Slot(result="QStringList")
    def familyIds(self):
        return sorted(self.reg.families) if self.reg else []

    @Slot(int, str)
    def overrideEncoder(self, i, name):
        entry = self.models.entry_at(i)
        if entry:
            self.reg.overrides.set_file(entry.path, encoder=name)
            self.rescan()

    @Slot(int, str)
    def overrideVae(self, i, name):
        entry = self.models.entry_at(i)
        if entry:
            self.reg.overrides.set_file(entry.path, vae=name)
            self.rescan()

    @Slot(result="QStringList")
    def encoderNames(self):
        return [e.name for e in self.reg.encoders()] if self.reg else []

    @Slot(result="QStringList")
    def vaeNames(self):
        return [v.name for v in self.reg.vaes()] if self.reg else []

    @Slot(str)
    def forceLora(self, name):
        entry = self.models.entry_at(self._selected)
        if entry is None:
            return
        lora = self.reg.find(name)
        if lora:
            fams = set(self.reg.overrides.forced_families(lora.path)) | {entry.family}
            self.reg.overrides.force_lora(lora.path, sorted(fams))
            self.selectModel(self._selected)

    # -- generating --------------------------------------------------------

    @Slot(float, result=int)
    def videoFrames(self, duration):
        """How many frames that many seconds becomes, for the panel to show."""
        entry = self.models.entry_at(self._selected)
        fam = (self.reg.family_of(entry) or {}) if (entry and self.reg) else {}
        spec = fam.get("video") or {}
        return R.video_frames(duration, spec.get("fps", 24.0),
                              int(spec.get("min_frames", 5)),
                              int(spec.get("frame_chunk", 17)))

    @Slot("QVariantMap", int)
    def generate(self, params, count):
        entry = self.models.entry_at(self._selected)
        if entry is None:
            self.toast.emit("no model selected", True)
            return
        if self._object_info is None:
            self.toast.emit("backend is not ready yet", True)
            return

        # A first frame lives on THIS machine and the graph names a file in
        # ComfyUI's input directory, so it has to be uploaded before the graph
        # that refers to it can be built. Uploading once per file, not once per
        # job: the same drop queued ten times is one upload.
        if params.get("use_input_image") and self._input_image:
            path = self._input_image
            if self._uploaded[0] == path and self._uploaded[1]:
                params = dict(params, input_image=self._uploaded[1])
            else:
                self._set_status("uploading the first frame...")

                def uploaded(ref, error):
                    if not ref:
                        self._set_status("ready")
                        self.toast.emit(f"could not send the first frame: {error}", True)
                        return
                    self._uploaded = (path, ref)
                    self._start_jobs(entry, dict(params, input_image=ref), count)

                self.client.upload_image(path, uploaded)
                return
        elif params.get("use_input_image"):
            self.toast.emit("drop an image first, or turn the first frame off", True)
            return

        self._start_jobs(entry, params, count)

    def _start_jobs(self, entry, params, count):
        base = dict(params)
        base["loras"] = self.loras.active()
        seed = int(base.get("seed", 0))
        randomise = bool(base.pop("randomSeed", False))

        for n in range(max(1, int(count))):
            p = dict(base)
            if randomise or seed < 0:
                import secrets

                p["seed"] = secrets.randbelow(2**53)
            else:
                p["seed"] = seed + n
            try:
                built = self.reg.build(entry, p, object_info=self._object_info)
            except G.ValidationError as exc:
                self.toast.emit(exc.problems[0], True)
                return
            except G.GraphError as exc:
                self.toast.emit(str(exc), True)
                return
            job = self.client.submit(built["prompt"], built["params"])
            job.meta = {"params": built["params"], "pairing": built["pairing"]}
            self._jobs += 1
        self._busy = True
        self.busyChanged.emit()

    @Slot()
    def cancel(self):
        self.client.cancel_all()
        self._jobs = 0
        self._busy = False
        self._clock.stop()
        self._progress = 0.0
        self.busyChanged.emit()
        self.statusChanged.emit()

    @Slot()
    def unloadModels(self):
        # Wait for the reply. POSTing /free at a backend that is not there is a
        # perfect silent no-op, and the old code toasted success either way.
        def done(ok, detail):
            if ok:
                self.toast.emit("ComfyUI unloaded its models", False)
            else:
                self.toast.emit(f"unload failed: {detail}", True)

        self.client.free(True, done)

    def _on_queue(self, remaining):
        self._queue = remaining
        self.statusChanged.emit()

    def _on_started(self, _job):
        self._busy = True
        self._job_start = time.time()
        self._clock.start()
        self.busyChanged.emit()

    def _on_progress(self, _job, value, maximum):
        self._progress = (value / maximum) if maximum else 0.0
        self.statusChanged.emit()

    def _on_node(self, _job, role):
        self._current = role
        self.statusChanged.emit()

    def _on_finished(self, job):
        pending = []
        for img in job.images:
            pending.append(img)

        def save_one(img):
            def got(data):
                if not data:
                    return
                # Only a PNG can carry the job that made it. A video goes down
                # verbatim — SaveVideo has already written ComfyUI's own graph
                # into its container metadata — and keeps the subfolder the
                # backend filed it under (video/), which is where the gallery
                # looks for it.
                if str(img["filename"]).lower().endswith(".png"):
                    try:
                        data = pngmeta.upsert_text(
                            data, pngmeta.describe(job.meta.get("params", {}),
                                                   job.meta.get("pairing")))
                    except ValueError:
                        pass
                dest = OUT_DIR / (img.get("subfolder") or "") / img["filename"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                self.gallery.add(str(dest))

            self.client.download(img, got)

        for img in pending:
            save_one(img)

        self._jobs = max(0, self._jobs - 1)
        if self._jobs == 0:
            self._busy = False
            self._clock.stop()
            self._progress = 0.0
            self._current = ""
            self.busyChanged.emit()
        took = f" in {job.duration:.1f}s" if job.duration else ""
        self.toast.emit(f"done{took}", False)
        self.statusChanged.emit()

    def _on_failed(self, _job, message):
        self._jobs = max(0, self._jobs - 1)
        if self._jobs == 0:
            self._busy = False
            self._clock.stop()
            self.busyChanged.emit()
        self.toast.emit(message.split("\n")[0][:200], True)
        self.statusChanged.emit()

    @Slot(str)
    def openExternally(self, path):
        p = path.replace("file://", "")
        try:
            subprocess.Popen(["viewer", p], start_new_session=True)
        except OSError:
            subprocess.Popen(["xdg-open", p], start_new_session=True)


def _human(n):
    for unit in ("B", "K", "M", "G"):
        if n < 1024 or unit == "G":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0
    return str(n)


# ---------------------------------------------------------------------------


class Titlebar(QObject):
    """Chrome lives in the hyprvtb titlebar, like the sibling apps."""

    clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = None
        if VtbClient is not None:
            try:
                self._client = VtbClient(on_click=self.clicked.emit)
            except Exception:  # noqa: BLE001 - running outside hyprvtb is fine
                self._client = None

    @Slot("QVariantList")
    def setButtons(self, buttons):
        if not self._client:
            return
        out = []
        for b in buttons:
            if isinstance(b, str):
                out.append("-")
            else:
                out.append((str(b["id"]), str(b["label"]), int(b.get("state", 0)),
                            str(b.get("tip", "")), False, bool(b.get("bottom", False))))
        try:
            self._client.set_buttons(out)
        except Exception:  # noqa: BLE001
            pass

    @Slot(str)
    def setFooter(self, text):
        if self._client:
            try:
                self._client.set_footer(text)
            except Exception:  # noqa: BLE001
                pass

    @Slot(bool)
    def setLoading(self, on):
        if self._client:
            try:
                self._client.set_loading(bool(on))
            except Exception:  # noqa: BLE001
                pass


def main():
    selftest = "--selftest" in sys.argv
    if selftest:
        # Hard, never setdefault, and with no display left to fall back to: an
        # exported QT_QPA_PLATFORM (his session's, or the wrapper's) used to win
        # here, and the selftest then opened a real painter window on his
        # screen. With no display Qt aborts instead — see apps/AGENTS.md.
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ.pop("WAYLAND_DISPLAY", None)
        os.environ.pop("DISPLAY", None)

    # Pin the Controls style: the system default resolves to KDE Breeze, whose
    # ToolTip pulls in kirigami and fails to load outside a Plasma session.
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

    app = QGuiApplication(sys.argv)
    if selftest and app.platformName() != "offscreen":
        raise SystemExit("selftest refuses to run on platform %r, not offscreen"
                         % app.platformName())
    app.setApplicationName("painter")
    app.setOrganizationName("painter")

    palette = Palette(PANEL_THEME)
    style = DeskStyle()
    prefs = Prefs()
    ctl = Painter()
    bar = Titlebar()
    spell = SpellCheck()

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    # Keep python-side references: context properties are not owned by QML.
    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("DeskStyle", style)
    ctx.setContextProperty("Prefs", prefs)
    ctx.setContextProperty("App", ctl)
    ctx.setContextProperty("Models", ctl.models)
    ctx.setContextProperty("Loras", ctl.loras)
    ctx.setContextProperty("LoraChoices", ctl.choices)
    ctx.setContextProperty("Gallery", ctl.gallery)
    ctx.setContextProperty("Titlebar", bar)
    ctx.setContextProperty("Spell", spell)

    # Theme.qml lives in qml/theme/ so it registers as a context property rather
    # than as a type that would shadow it (same arrangement as player/filer).
    theme_comp = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "theme" / "Theme.qml")))
    theme = theme_comp.create()
    if theme is None:
        print("Theme.qml failed:\n" + theme_comp.errorString(), file=sys.stderr)
        return 2
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)

    warnings = []
    engine.warnings.connect(lambda errs: warnings.extend(str(e.toString()) for e in errs))
    engine.load(QUrl.fromLocalFile(str(QML / "Main.qml")))
    if not engine.rootObjects():
        print("failed to load Main.qml", file=sys.stderr)
        for w in warnings:
            print(f"  {w}", file=sys.stderr)
        return 2

    if selftest:
        rc = [0]

        def finish():
            for w in warnings:
                print(f"QML WARNING: {w}", file=sys.stderr)
            if warnings:
                rc[0] = 1
            print(f"selftest: root loaded, {len(warnings)} QML warning(s)")
            app.quit()

        QTimer.singleShot(2500, finish)
        app.exec()
        return rc[0]

    app.exec()
    # Leave the backend running so weights stay warm for the next launch.
    return 0


if __name__ == "__main__":
    sys.exit(main())
