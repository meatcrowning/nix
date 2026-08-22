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

import collections
import hashlib
import json
import os
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QFileSystemWatcher, QModelIndex,
                            QObject, Property, QProcess, QSortFilterProxyModel, Qt,
                            QTimer, QUrl, Signal, Slot)
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QImage, QWindow
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuick import QQuickImageProvider

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"
# The clipboard holder (pylib, stdlib-only), run as a program rather than
# imported: it forks and stays alive owning the selection. See _clip_file.
CLIPFILE = HERE.parent / "pylib" / "clipfile.py"

sys.path.insert(0, str(HERE.parent / "pylib"))
try:
    from vtbclient import VtbClient  # noqa: E402
except Exception:  # noqa: BLE001 - the titlebar bridge is optional
    VtbClient = None
from deskstyle import DeskStyle  # noqa: E402  (pylib; the desktop-wide font setting)
from kdetheme import theme_source, is_plasma  # noqa: E402  (pylib; the KDE global theme in a Plasma session)
import kdeshell  # noqa: E402  (pylib; the Plasma session's real QtWidgets window)
from spellcheck import SpellCheck  # noqa: E402  (pylib; the prompt boxes' spelling)
# The QBuffer-safe encoder (see its docstring for the SEGV that shape avoids);
# collage.py already pulls it in, so this costs nothing new.
import imgfit  # noqa: E402
# The PNG text-chunk reader/writer. In pylib because filer's metadata filter
# reads the same chunks this app writes — one parser, not two.
import pngmeta  # noqa: E402
# The same, for the other half of the gallery: a clip carries its parameters as
# an MP4 metadata tag beside ComfyUI's own graph.
import mp4meta  # noqa: E402

sys.path.insert(0, str(HERE))
import collage as Collage  # noqa: E402
import comfy as C  # noqa: E402
import graph as G  # noqa: E402
import outmeta  # noqa: E402  (which of the three ways an output kept its job)
import registry as R  # noqa: E402

OUT_DIR = Path(os.environ.get("PAINTER_OUT", Path.home() / "Pictures" / "painter" / "out"))
# THE OTHER MACHINE'S OUTPUTS, read-only. book generates through top's backend,
# and that backend writes every result into TOP's output directory whoever asked
# for it — book keeps only the copy it downloaded. So top's history has always
# been both machines' and book's was a fraction of it. comfy-tunnel.sh mounts
# top's root over sshfs and names it here (colon-separated, like a PATH); on top
# there is nothing to add, and an unset or unmounted root costs nothing.
PEER_OUTS = [Path(p) for p in os.environ.get("PAINTER_PEER_OUT", "").split(":") if p]
STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "painter"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "painter"
PREFS = STATE / "prefs.json"
# What painter will send to the backend as a frame — the drop and the paste
# both go through App._usable_image, so there is one answer.
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
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

    # QML reads `Models.count` (the model-panel badge, the settings drawer).
    # A QAbstractListModel exposed as a context property has NO implicit
    # `count` the way a QML ListModel does — the binding silently evaluates to
    # `undefined`, which coerced into a string drew "undefined found" on the
    # panel header. Same shape on LoraStack and Gallery below.
    countChanged = Signal()

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

    count = Property(int, rowCount, notify=countChanged)

    def set_rows(self, rows):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
        self.countChanged.emit()

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
    # A single catch-all QML can debounce a Prefs save on, without listening
    # to add/remove/clear/dataChanged separately (see Main.qml saveState).
    stackChanged = Signal()

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

    # QML reads `Loras.count` (the stack badge, the empty hint, LoraRow's
    # move-down enable) — see ModelList.count for why this must be explicit.
    count = Property(int, rowCount, notify=countChanged)

    @Slot(str, bool)
    def add(self, name, patches_clip=False):
        if any(r["name"] == name for r in self._rows):
            return
        self.beginInsertRows(QModelIndex(), len(self._rows), len(self._rows))
        self._rows.append({"name": name, "strength": 1.0, "enabled": True,
                           "patches_clip": bool(patches_clip)})
        self.endInsertRows()
        self.countChanged.emit()
        self.stackChanged.emit()

    @Slot(int)
    def remove(self, i):
        if not (0 <= i < len(self._rows)):
            return
        self.beginRemoveRows(QModelIndex(), i, i)
        self._rows.pop(i)
        self.endRemoveRows()
        self.countChanged.emit()
        self.stackChanged.emit()

    @Slot()
    def clear(self):
        if not self._rows:
            return
        self.beginResetModel()
        self._rows = []
        self.endResetModel()
        self.countChanged.emit()
        self.stackChanged.emit()

    @Slot(int, float)
    def setStrength(self, i, value):
        if 0 <= i < len(self._rows):
            self._rows[i]["strength"] = float(value)
            idx = self.index(i, 0)
            self.dataChanged.emit(idx, idx, [self.StrengthRole])
            self.stackChanged.emit()

    @Slot(int, bool)
    def setEnabled(self, i, value):
        if 0 <= i < len(self._rows):
            self._rows[i]["enabled"] = bool(value)
            idx = self.index(i, 0)
            self.dataChanged.emit(idx, idx, [self.EnabledRole])
            self.stackChanged.emit()

    @Slot(int, int)
    def move(self, frm, to):
        if not (0 <= frm < len(self._rows) and 0 <= to < len(self._rows)) or frm == to:
            return
        self.beginResetModel()
        row = self._rows.pop(frm)
        self._rows.insert(to, row)
        self.endResetModel()
        self.stackChanged.emit()

    def active(self):
        return [dict(r) for r in self._rows if r["enabled"]]

    def snapshot(self):
        """Every row (enabled or not), for persisting the whole stack."""
        return [dict(r) for r in self._rows]


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
# A "<name>-muted.mp4" beside a clip is a DERIVATIVE, not an output: painter
# makes one when you ask for a soundless copy to paste somewhere. It stays out
# of the history, or every video would be there twice.
MUTED_TAG = "-muted"


def is_muted_copy(path) -> bool:
    p = Path(path)
    return p.suffix.lower() in VIDEO_SUFFIXES and p.stem.endswith(MUTED_TAG)


def _clock_text(seconds) -> str:
    """m:ss — the queue bar's own clock, so the completion toast reports a run
    in the same shape the window does ("took 1:23" / "completed in 1:23")."""
    s = max(0, int(seconds))
    return "%d:%02d" % (s // 60, s % 60)


class LivePreview(QQuickImageProvider):
    """The sampler's own preview frames, handed to QML without touching disk.

    ComfyUI pushes a JPEG/PNG down the websocket every few steps (with
    `--preview-method` on). They are transient — the next one replaces this one
    — so they are held as one QImage and addressed by a counter, because an
    Image whose `source` never changes never reloads.
    """

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.image = QImage()

    def requestImage(self, _id, size, _requested):
        if size is not None:
            size.setWidth(self.image.width())
            size.setHeight(self.image.height())
        return self.image


class Gallery(QAbstractListModel):
    PathRole = Qt.UserRole + 1
    UrlRole = Qt.UserRole + 2
    NameRole = Qt.UserRole + 3
    VideoRole = Qt.UserRole + 4
    PosterRole = Qt.UserRole + 5

    countChanged = Signal()
    # A clip's poster frame landed: (the clip, the .jpg). The completion toast
    # waits on this — QML cannot decode an mp4, so a clip's toast thumbnails the
    # poster and points the click at the video (docs/DESIGN.md §8.1).
    posterReady = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # TWO LISTS. `_all` is every output; `_rows` is what the view shows,
        # which is `_all` unless a filter is typed in the toolbar. They hold the
        # SAME dicts, so a poster landing in one lands in both.
        self._all = []
        self._rows = []
        self._filter = ""
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

    # QML reads `Gallery.count` (the outputs tally, the empty-state hint,
    # PreviewPane's click-through) — see ModelList.count for why.
    count = Property(int, rowCount, notify=countChanged)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r = self._rows[index.row()]
        return {self.PathRole: r["path"], self.UrlRole: r["url"],
                self.NameRole: r["name"], self.VideoRole: r["is_video"],
                self.PosterRole: r["poster"]}.get(role)

    def has_path(self, path):
        return any(r["path"] == str(path) for r in self._all)

    # ------------------------------------------------------------- filtering
    @Slot(str)
    def setFilter(self, text):
        """Show only the outputs whose FILENAME or PROMPT contains `text`.

        Case-insensitive, every word must match, and the prompt is read out of
        the file the first time it is needed and then kept — sixty PNG chunks is
        a few milliseconds once, and nothing at all on the next keystroke."""
        text = str(text or "").strip().lower()
        if text == self._filter:
            return
        self._filter = text
        self._refilter()

    filterText = Property(str, lambda self: self._filter, notify=countChanged)

    def _haystack(self, r):
        if "hay" not in r:
            bits = [r["name"]]
            try:
                p = outmeta.params_for(r["path"]) or {}
                for k in ("positive", "negative", "model", "family"):
                    v = p.get(k)
                    if v:
                        bits.append(str(v))
            except Exception:  # noqa: BLE001  — an unreadable file still matches its name
                pass
            r["hay"] = " ".join(bits).lower()
        return r["hay"]

    def _matches(self, r):
        if not self._filter:
            return True
        hay = self._haystack(r)
        return all(w in hay for w in self._filter.split())

    def _refilter(self):
        self.beginResetModel()
        self._rows = [r for r in self._all if self._matches(r)]
        self.endResetModel()
        self.countChanged.emit()

    @staticmethod
    def _dedup_key(path):
        """What makes the same output on both machines ONE row.

        The NAME, because the backend that numbers it is top's whoever asked —
        book cannot mint a colliding `painter_00042_.png` of its own. Not the
        size: book writes painter's parameters into the copy it downloads and
        top's has none, so the identical output is a few hundred bytes bigger
        here — a still since always (the PNG chunk), a clip since 2026-08-21
        (the MP4 tag), which is what makes the local-copy-wins rule below matter
        for clips too.
        """
        return Path(path).name

    def _row_for(self, path):
        p = Path(path)
        is_video = p.suffix.lower() in VIDEO_SUFFIXES
        return {"path": str(p), "url": QUrl.fromLocalFile(str(p)).toString(),
                "name": p.name, "is_video": is_video, "poster": "",
                "key": self._dedup_key(p)}

    def _drop_key(self, key):
        for j, r in enumerate(self._all):
            if r["key"] != key:
                continue
            self._all.pop(j)
            for i, vr in enumerate(self._rows):
                if vr is r:
                    self.beginRemoveRows(QModelIndex(), i, i)
                    self._rows.pop(i)
                    self.endRemoveRows()
                    break
            return

    def add(self, path):
        if is_muted_copy(path) or self.has_path(path):
            return
        # The peer root holds top's copy of this very output, and the scan at
        # startup may already be showing it. The local one replaces it: it is
        # the copy with the parameters written into it.
        self._drop_key(self._dedup_key(path))
        row = self._row_for(path)
        self._all.insert(0, row)
        if self._matches(row):
            self.beginInsertRows(QModelIndex(), 0, 0)
            self._rows.insert(0, row)
            self.endInsertRows()
        self.countChanged.emit()
        if row["is_video"]:
            self._want_poster(row["path"])

    def load_existing(self, limit=0):
        # Videos land in a subdirectory of their own, because that is where
        # SaveVideo's filename_prefix puts them — a gallery that only globbed
        # *.png here would show nothing at all for a video model.
        #
        # THE LOCAL ROOT IS SCANNED FIRST, and that ordering is load-bearing
        # rather than tidiness: a still book generated carries painter's
        # parameters only in the copy book wrote, so "inject" reads the local
        # one and would find nothing at all in top's.
        found = []
        seen = set()
        for root in [OUT_DIR, *PEER_OUTS]:
            try:
                paths = list(root.glob("*.png"))
                for suffix in VIDEO_SUFFIXES:
                    paths += list(root.glob(f"video/*{suffix}"))
            except OSError:
                # A peer root that is not mounted — the tunnel is down, or the
                # sshfs went away mid-session — must not cost the local scan.
                continue
            for p in paths:
                key = self._dedup_key(p)
                if is_muted_copy(p) or key in seen:
                    continue
                try:
                    mtime = p.stat().st_mtime
                except OSError:
                    continue   # deleted between the glob and the stat
                seen.add(key)
                found.append((mtime, p))
        # ALL OF THEM, newest first. This was capped at 60 — a number from when
        # the grid was a strip — so the history simply stopped partway with
        # nothing saying so. The view is a GridView and only builds the
        # delegates it can see, so the cost of the rest is one small dict each;
        # `limit` survives for a caller that wants a slice.
        ordered = sorted(found, key=lambda t: t[0], reverse=True)
        files = [p for _m, p in (ordered[:limit] if limit else ordered)]
        self._all = [self._row_for(p) for p in files]
        self._refilter()
        # The first screenful eagerly, the rest on demand (`requestPoster`).
        eager = 0
        for r in self._all:
            if not r["is_video"]:
                continue
            self._want_poster(r["path"])
            eager += 1
            if eager >= 24:
                break

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
        if any(p == path for p, _d in self._poster_queue):
            return          # already waiting; a delegate rebuilt is not a job
        self._poster_queue.append((path, dest))
        self._next_poster()

    @Slot(str)
    def requestPoster(self, path):
        """A clip's delegate, asking for its own poster frame.

        The gallery shows EVERY output now, and this library is a few hundred
        clips — extracting a frame from all of them at startup would be a few
        hundred ffmpeg runs for thumbnails nobody has scrolled to yet. The first
        screenful is queued eagerly (`load_existing`) so the top of the grid is
        never blank; everything after it asks on the way past."""
        self._want_poster(str(path))

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

    def poster_ready(self, path):
        """The poster frame this clip ALREADY has, or "" while one is still
        being made (or cannot be). Never starts an extraction — the caller is
        asking what exists, not asking for one; `_want_poster` is that."""
        try:
            dest = self._poster_path(path)
        except OSError:
            return ""
        return str(dest) if dest.exists() else ""

    def _poster_ready(self, path, dest):
        self.posterReady.emit(str(path), str(dest))
        for r in self._all:
            if r["path"] != path:
                continue
            # `_rows` holds the same dict, so this reaches both lists; only the
            # VISIBLE list has a row index to report a change for.
            r["poster"] = QUrl.fromLocalFile(str(dest)).toString()
            for i, vr in enumerate(self._rows):
                if vr is r:
                    idx = self.index(i, 0)
                    self.dataChanged.emit(idx, idx, [self.PosterRole])
                    break
            return

    @Slot(int, result=str)
    def pathAt(self, i):
        return self._rows[i]["path"] if 0 <= i < len(self._rows) else ""

    @Slot(int, result=bool)
    def isVideoAt(self, i):
        return bool(self._rows[i]["is_video"]) if 0 <= i < len(self._rows) else False

    @Slot(str, result=int)
    def indexOf(self, path):
        """Row of a path, or -1. The gallery's selection is kept as PATHS (a
        new output inserts at row 0 and would renumber a set of indices under
        him), so extending a range needs the model to say where they sit."""
        path = str(path)
        for i, r in enumerate(self._rows):
            if r["path"] == path:
                return i
        return -1

    @Slot(str, result=str)
    def stillFor(self, path):
        """The picture that stands for this output — itself, or a clip's poster
        frame. "" when a video has no poster yet."""
        path = str(path)
        for r in self._rows:
            if r["path"] == path:
                if not r["is_video"]:
                    return path
                return QUrl(r["poster"]).toLocalFile() if r["poster"] else ""
        return ""

    @Slot(int, result="QVariant")
    def paramsAt(self, i):
        if not (0 <= i < len(self._rows)):
            return None
        # A still and a clip keep the job in different places, and a clip from
        # before painter wrote its own tag keeps it only as ComfyUI's graph.
        # outmeta answers all three (see its docstring).
        return outmeta.params_for(self._rows[i]["path"])


# ---------------------------------------------------------------------------
# the controller QML talks to
# ---------------------------------------------------------------------------


class Painter(QObject):
    statusChanged = Signal()
    modelChanged = Signal()
    busyChanged = Signal()
    optionsChanged = Signal()
    inputImageChanged = Signal()
    lastImageChanged = Signal()
    lastSeedChanged = Signal()
    editExtraChanged = Signal()
    modeChanged = Signal()
    previewChanged = Signal()
    toast = Signal(str, bool)          # message, isError
    logChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.models = ModelList(self)
        self.loras = LoraStack(self)
        self.choices = LoraChoices(self)
        self.gallery = Gallery(self)

        # What comfy.py's ComfyClient.logged has said, newest last, for a small
        # live panel in the settings drawer — bounded so a long session cannot
        # grow this without limit.
        self._log = collections.deque(maxlen=200)

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
        self._last_elapsed = 0.0          # ...and how long the last one took, which
                                          # the bar keeps showing once it is over
        # Sampling throughput, the it/s a diffusion sampler reports. Anchored at
        # the FIRST progress callback of a run — not `_job_start`, which includes
        # model load — so the rate reads the steps as they are counted, over the
        # seconds spent counting them.
        self._step = 0                    # steps reported so far this run
        self._sample_start = 0.0          # when sampling began (first progress)
        self._sample_start_step = 0       # the step count at that anchor
        self.preview = None               # the live-preview image provider, set in main()
        self._preview_tick = 0            # an Image reloads on a CHANGED url, so count
        self._input_image = ""            # the first frame, as a local path
        self._last_image = ""             # the frame to end on, likewise
        self._uploaded = ("", "")         # (local path, the ref ComfyUI knows it by)
        self._uploaded_last = ("", "")    # the same, for the last frame
        self._edit_extra = []             # edit mode's ADDITIONAL reference images,
                                          # as local paths (the primary is _input_image)
        self._edit_uploads = {}           # {local path: ref} for those extras
        self._mode = ""                   # anime / real / edit / video, or "" for the list
        self._want_mode = ""              # a remembered mode, until the rows land
        # Collages built for a dragged selection, keyed by the files that went
        # into them. The work is on a thread; the dict is what stops two presses
        # building the same picture twice.
        self._collage_lock = threading.Lock()
        self._collage_jobs = {}

        # A batch he is not watching finishes as a desktop toast (see
        # `_maybe_notify`). The window is what decides that, so main() hands it
        # over once it exists; None means "no window yet", and a run with no
        # window toasts nothing at all — which is also what keeps every harness
        # off his screen.
        self.window = None
        self._batch_start = 0.0           # when the batch in flight was asked for
        self._batch_elapsed = 0.0         # ...and what it took, once it is over
        self._batch_saved = []            # the outputs it has written so far
        self._batch_pending = 0           # downloads still in the air
        self._batch_toasted = False       # this batch has had its one toast
        self._pending_toast = None        # a clip toast waiting on its poster
        self._last_seed = -1              # the base seed the last batch actually
                                          # ran at, for "reuse last seed"; -1 = none
                                          # yet (persisted across a relaunch)

        self.reg = None
        self.client = C.ComfyClient()
        self.client.statusChanged.connect(self._on_queue)
        self.client.jobStarted.connect(self._on_started)
        self.client.jobProgress.connect(self._on_progress)
        self.client.jobNode.connect(self._on_node)
        self.client.jobPreview.connect(self._on_preview)
        self.client.jobFinished.connect(self._on_finished)
        self.client.jobFailed.connect(self._on_failed)
        self.client.connected.connect(self._on_ws_connected)
        self.client.logged.connect(self._on_log)
        self.gallery.posterReady.connect(self._on_poster)

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
    # The live preview: a counter QML puts in the image URL, and whether one has
    # arrived at all for the job that is running (a backend started without
    # --preview-method never sends any, and the pane must not sit on a stale
    # frame from an hour ago claiming to be this job).
    previewTick = Property(int, lambda self: self._preview_tick, notify=previewChanged)
    hasPreview = Property(bool, lambda self: bool(self._busy and self._preview_tick),
                          notify=previewChanged)
    elapsed = Property(float, lambda self: (
        max(0.0, time.time() - self._job_start) if (self._busy and self._job_start) else 0.0),
        notify=statusChanged)
    # `elapsed` is zero the moment the run ends, so the bar's clock had nothing
    # left to draw and the one number worth keeping — how long that took —
    # survived only in a toast that fades. This is that number, and it stays.
    lastElapsed = Property(float, lambda self: self._last_elapsed,
                           notify=statusChanged)
    # Sampling throughput in iterations per second, the same number tqdm prints
    # beside a diffusion sampler. Steps counted since the anchor over the seconds
    # since it; zero (nothing drawn) until a second callback gives it a span to
    # divide. The clock timer re-emits statusChanged each second, so it ticks
    # live even between callbacks. The QML decides it/s vs s/it.
    def _rate(self):
        if not self._busy or self._sample_start <= 0.0:
            return 0.0
        dt = time.time() - self._sample_start
        dsteps = self._step - self._sample_start_step
        if dt <= 0.0 or dsteps <= 0:
            return 0.0
        return dsteps / dt
    rate = Property(float, _rate, notify=statusChanged)
    ready = Property(bool, lambda self: self._object_info is not None, notify=statusChanged)
    # What systemd says about comfy-painter.service, so start/stop can be lit
    # from the world instead of from intent (docs/DESIGN.md §10).
    unitState = Property(str, lambda self: self._unit_state, notify=statusChanged)
    # Recent comfy.py websocket activity (queued/started/running/finished/error),
    # newest last, for the settings drawer's live log panel.
    logLines = Property("QStringList", lambda self: list(self._log), notify=logChanged)
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
    # WHICH MODE BUTTON IS LIT, or "" when the model list is in charge. A mode
    # is a shortcut to one model (registry.MODES), so it also decides whether
    # the list is greyed out — and `edit` decides which pipeline is built.
    mode = Property(str, lambda self: self._mode, notify=modeChanged)
    isEdit = Property(bool, lambda self: self._mode == "edit", notify=modeChanged)
    inputImage = Property(str, lambda self: self._input_image, notify=inputImageChanged)
    inputImageUrl = Property(str, lambda self: (
        QUrl.fromLocalFile(self._input_image).toString() if self._input_image else ""),
        notify=inputImageChanged)
    editExtraImages = Property("QStringList", lambda self: list(self._edit_extra),
                               notify=editExtraChanged)
    lastImage = Property(str, lambda self: self._last_image, notify=lastImageChanged)
    lastImageUrl = Property(str, lambda self: (
        QUrl.fromLocalFile(self._last_image).toString() if self._last_image else ""),
        notify=lastImageChanged)
    # The base seed of the most recent batch, so the UI can offer to re-run at
    # it. -1 until the first generation of this session (or a restored one).
    lastSeed = Property("QVariant", lambda self: self._last_seed,
                        notify=lastSeedChanged)

    def _family_kind(self):
        entry = self.models.entry_at(self._selected)
        if entry is None or self.reg is None:
            return ""
        return (self.reg.family_of(entry) or {}).get("kind", "image")

    # -- the dropped (and pasted) frames -------------------------------------

    def _usable_image(self, path, verb):
        """(path, "") if painter can send that file to the backend, else
        ("", why). One rule for the drop and the paste, so the two cannot come
        to disagree about what counts as an image; `verb` only words it."""
        if not path or not os.path.isfile(path):
            return "", "that is not a file painter can read"
        if Path(path).suffix.lower() not in IMAGE_SUFFIXES:
            return "", "%s an image (png, jpg, webp)" % verb
        return path, ""

    def _dropped_path(self, url):
        """A dropped url as a local image path, or "" with the reason said."""
        path, why = self._usable_image(
            QUrl(url).toLocalFile() if url.startswith("file:") else url, "drop")
        if why:
            self.toast.emit(why, True)
        return path

    def _clipboard_offer(self):
        """What a paste would mean, WITHOUT writing anything:
        `("file", path)`, `("pixels", QImage)`, or `("", why)`.

        Three shapes, in the order a paste can mean them:

          FILES  — a copy out of filer, viewer or a browser (`text/uri-list`,
                   which is what `pylib/clipfile.py` puts there). The picture is
                   already on disk under its own name, so nothing is written and
                   the well shows the name he knows it by.
          PIXELS — a screenshot tool, a browser's "copy image", an editor. There
                   is no file, so `_paste_target` has to make one.
          TEXT   — a path someone copied as a string (filer's "copy path").

        Reading the clipboard needs painter to have keyboard focus on Wayland —
        the selection is offered to the focused client — which both paste routes
        do have: a click on `[ paste ]` and a Ctrl+V over a well are both in a
        focused window. That is also why the button is not greyed out from this:
        an offer that has not arrived yet would grey a button that is about to
        work, and a paste with nothing behind it says so out loud anyway."""
        md = QGuiApplication.clipboard().mimeData()
        if md is None:
            return "", "there is nothing on the clipboard"
        if md.hasUrls():
            why = "there is no image file on the clipboard"
            decoded = None
            for u in md.urls():
                local = u.toLocalFile()
                if not local:
                    continue
                path, why = self._usable_image(local, "paste")
                if path:
                    return "file", path
                # A file whose suffix painter cannot send to the backend (an
                # svg, an ico, a ppm — anything viewer opens but IMAGE_SUFFIXES
                # omits) but that Qt CAN decode from disk: read it ourselves and
                # paste it as pixels, so everything viewer can copy pastes here.
                # The clipboard's own image offer covers formats with a
                # QImageIO plugin (gif/tiff/avif); this covers the rest.
                if decoded is None and os.path.isfile(local):
                    img = QImage(local)
                    if not img.isNull():
                        decoded = img
            if decoded is not None:
                return "pixels", decoded
            # The file's own suffix is outside IMAGE_SUFFIXES and we could not
            # decode it either — fall through to the clipboard's pixel offer
            # rather than refusing a paste whose bytes we can actually read.
            if not md.hasImage():
                return "", why
        if md.hasImage():
            img = QGuiApplication.clipboard().image()
            if img is None or img.isNull():
                return "", "the clipboard's image could not be read"
            return "pixels", img
        if md.hasText():
            path, why = self._usable_image(md.text().strip(), "paste")
            return ("file", path) if path else ("", why)
        return "", "there is no image on the clipboard"

    def _paste_target(self):
        """`_clipboard_offer()` resolved to a path on disk, or "" with the
        reason said. Pixels are written into the cache, named by CONTENT: paste
        the same screenshot twice and it is one file — and, because the upload
        cache is keyed on the path, one upload to the backend as well."""
        kind, val = self._clipboard_offer()
        if kind == "file":
            return val
        if kind != "pixels":
            self.toast.emit(val, True)
            return ""
        data = imgfit.encode(val, "png", 50)
        if not data:
            self.toast.emit("could not encode what is on the clipboard", True)
            return ""
        dest = CACHE / "pasted" / ("pasted-%s.png" % hashlib.sha1(data).hexdigest()[:12])
        try:
            if not (dest.exists() and dest.stat().st_size == len(data)):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
            self._prune_pasted(dest.parent)
        except OSError as e:
            self.toast.emit("could not save the pasted image: %s" % e, True)
            return ""
        return str(dest)

    @staticmethod
    def _prune_pasted(d, keep=20):
        """A pasted screenshot is scratch, but the file has to outlive the paste
        (the backend uploads it at generate time, and prefs remember it across a
        launch). So they accumulate; keep the newest few and drop the rest."""
        try:
            old = sorted(d.glob("pasted-*.png"), key=lambda p: p.stat().st_mtime,
                         reverse=True)[keep:]
        except OSError:
            return
        for p in old:
            try:
                p.unlink()
            except OSError:
                pass

    @Slot(result=bool)
    def pasteInputImage(self):
        """The clipboard as the first frame / the image to edit."""
        path = self._paste_target()
        return self.setInputImage(path) if path else False

    @Slot(result=bool)
    def pasteLastImage(self):
        path = self._paste_target()
        return self.setLastImage(path) if path else False

    @Slot(str, result=bool)
    def setInputImage(self, url):
        """Take a dropped file as the first frame, if it is one we can send."""
        path = self._dropped_path(url)
        if not path:
            return False
        self._input_image = path
        self._uploaded = ("", "")     # a new file has not been uploaded yet
        self.inputImageChanged.emit()
        return True

    @Slot(str, result=bool)
    def setLastImage(self, url):
        """The same, for the frame the clip is made to end on."""
        path = self._dropped_path(url)
        if not path:
            return False
        self._last_image = path
        self._uploaded_last = ("", "")
        self.lastImageChanged.emit()
        return True

    @Slot(str, result=bool)
    def restoreInputImage(self, path):
        """The remembered first frame, silently — a file that has since moved
        is not something to greet him with a toast about at launch.

        Returns whether it landed, which is what lets injecting a clip's
        settings leave the first-frame toggle OFF when the picture is gone."""
        if path and os.path.isfile(path):
            self._input_image = path
            self._uploaded = ("", "")
            self.inputImageChanged.emit()
            return True
        return False

    @Slot(str, result=bool)
    def restoreLastImage(self, path):
        if path and os.path.isfile(path):
            self._last_image = path
            self._uploaded_last = ("", "")
            self.lastImageChanged.emit()
            return True
        return False

    @Slot("QVariant")
    def restoreLastSeed(self, value):
        """Put back the last-used seed a previous session remembered."""
        try:
            seed = int(value)
        except (TypeError, ValueError):
            return
        if seed >= 0 and seed != self._last_seed:
            self._last_seed = seed
            self.lastSeedChanged.emit()

    # -- edit mode's additional reference images ---------------------------
    # The primary image (the one that sizes the output) is _input_image, shared
    # with the video first frame. These are the extra references Flux 2 Klein
    # attaches alongside it — kept as a separate list so the video path and every
    # existing single-image behaviour are untouched.
    @Slot(str, result=bool)
    def addEditImage(self, url):
        path = self._dropped_path(url)
        if not path:
            return False
        if path not in self._edit_extra:
            self._edit_extra.append(path)
            self.editExtraChanged.emit()
        return True

    @Slot(result=bool)
    def pasteEditImage(self):
        path = self._paste_target()
        if not path:
            return False
        if path not in self._edit_extra:
            self._edit_extra.append(path)
            self.editExtraChanged.emit()
        return True

    @Slot(int)
    def removeEditImage(self, idx):
        if 0 <= idx < len(self._edit_extra):
            del self._edit_extra[idx]
            self.editExtraChanged.emit()

    @Slot()
    def clearEditImages(self):
        if self._edit_extra:
            self._edit_extra = []
            self.editExtraChanged.emit()

    @Slot("QStringList")
    def restoreEditImages(self, paths):
        kept = [p for p in paths if p and os.path.isfile(p)]
        if kept:
            self._edit_extra = kept
            self.editExtraChanged.emit()

    @Slot(str, result=str)
    def fileUrl(self, path):
        return QUrl.fromLocalFile(path).toString() if path else ""

    @Slot()
    def clearInputImage(self):
        self._input_image = ""
        self._uploaded = ("", "")
        self.inputImageChanged.emit()

    @Slot()
    def clearLastImage(self):
        self._last_image = ""
        self._uploaded_last = ("", "")
        self.lastImageChanged.emit()

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

    def _on_log(self, line):
        self._log.append(time.strftime("%H:%M:%S") + "  " + line)
        self.logChanged.emit()

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
        # A mode outranks the remembered selection, because it IS one — and it
        # can only be applied once there are rows to select from, which is why
        # a restore at startup is deferred to here (same shape as _want_model).
        want_mode = self._want_mode or self._mode
        if want_mode:
            self._want_mode = ""
            entry = self.models.entry_at(self._selected)
            spec = R.mode_spec(want_mode) or {}
            # The selection above (the `want` branch) already landed on the
            # remembered model. If that model is already OF this mode's family,
            # just light the button — calling setMode() would re-resolve the
            # mode to its own CANONICAL pick (mode_model()'s exact/substring/
            # first-of-family order, `is entry` in mode_of()) and, with more
            # than one checkpoint in the family (two MiniMax quants, say),
            # silently swap the restored selection for a DIFFERENT one, firing
            # modelChanged -> applyDefaults() and overwriting the
            # just-restored video sampling settings (steps, sampler,
            # scheduler) with that other checkpoint's defaults.
            in_family = (entry is not None and entry.family == spec.get("family")
                         and (spec.get("needs") != "edit"
                              or (self.reg.family_of(entry) or {}).get("edit")))
            if in_family:
                if self._mode != want_mode:
                    self._mode = want_mode
                    self.modeChanged.emit()
            else:
                self.setMode(want_mode)
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

    @Slot("QVariant")
    def restoreLoras(self, rows):
        """The remembered LoRA chain for the model `selectModel` just landed
        on. Called once, right after startup's restored selection settles —
        `selectModel` always clears the stack, so this is what puts it back.
        Names no longer on disk (`choices`, just populated for this model) are
        dropped rather than referencing a file that has since moved."""
        known = {r["name"] for r in self.choices._rows}
        # QML hands an untyped Slot its array as a QJSValue, which is not
        # iterable in Python: this loop raised TypeError on every startup and
        # the remembered chain was silently never restored.
        if hasattr(rows, "toVariant"):
            rows = rows.toVariant()
        for r in (rows or []):
            name = r.get("name") if isinstance(r, dict) else None
            if not name or name not in known:
                continue
            self.loras.add(name, bool(r.get("patchesClip", False)))
            i = self.loras.rowCount() - 1
            self.loras.setStrength(i, float(r.get("strength", 1.0)))
            self.loras.setEnabled(i, bool(r.get("enabled", True)))

    @Slot(result="QVariant")
    def lorasSnapshot(self):
        """The whole stack (enabled or not) — what `restoreLoras` needs back,
        unlike `_start_jobs`' `loras.active()`, which is enabled-only."""
        rows = self.loras.snapshot()
        return [{"name": r["name"], "strength": r["strength"],
                  "enabled": r["enabled"], "patchesClip": r["patches_clip"]}
                 for r in rows]

    # -- modes -------------------------------------------------------------

    @Slot(result="QVariantList")
    def modes(self):
        """The switcher's buttons: what each one is, and whether it can be had.

        A mode whose model is not on this machine is offered DISABLED with the
        reason on it rather than silently missing — the row of four is the same
        four everywhere, and a button that vanished would read as a bug
        (docs/DESIGN.md §10).
        """
        out = []
        for spec in R.MODES:
            entry = self.reg.mode_model(spec["id"]) if self.reg else None
            out.append({
                "id": spec["id"], "label": spec["label"],
                "available": entry is not None,
                "model": getattr(entry, "name", ""),
                "tip": spec["tip"] if entry is not None
                       else f"no {spec['family']} model found",
            })
        return out

    @Slot(str)
    def setMode(self, mode_id):
        """Turn a mode on (selecting its model), or off with "".

        Off does NOT change the selection: he came to this model through the
        button, and dropping him back onto whatever was selected before would
        undo a choice he did not make. It only hands the list back.
        """
        mode_id = mode_id or ""
        if not mode_id:
            if self._mode:
                self._mode = ""
                self.modeChanged.emit()
            return
        if self.reg is None or self.models.rowCount() == 0:
            # The scan has not landed yet (startup restore) — remember it.
            self._want_mode = mode_id
            return
        entry = self.reg.mode_model(mode_id)
        if entry is None:
            spec = R.mode_spec(mode_id) or {}
            self.toast.emit(f"no {spec.get('family', mode_id)} model found here", True)
            # A mode whose model has gone (a rescan of a mount that dropped out)
            # must not stay lit over a list it is also greying out.
            if self._mode == mode_id:
                self._mode = ""
                self.modeChanged.emit()
            return
        i = self.models.index_of_name(entry.name)
        if i < 0:
            self.toast.emit(f"{entry.name} is not in the list", True)
            return
        self._mode = mode_id
        self._want_mode = ""
        if i != self._selected:
            self.selectModel(i)
        self.modeChanged.emit()

    @Slot(str)
    def restoreMode(self, mode_id):
        """The remembered mode, applied when the rows land (like the model)."""
        self._want_mode = mode_id or ""
        if mode_id:
            self.setMode(mode_id)

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

        # EDITING NEEDS THE PICTURE, and it is the one input with no default —
        # so it is checked before anything is uploaded rather than failing as a
        # node error with an empty filename in it.
        if params.get("edit"):
            if not self._input_image:
                self.toast.emit("drop an image to edit first", True)
                return
            paths = [self._input_image] + [p for p in self._edit_extra if p]
            self._upload_edit_then_start(entry, params, count, paths)
            return

        # A dropped frame lives on THIS machine and the graph names a file in
        # ComfyUI's input directory, so it has to be uploaded before the graph
        # that refers to it can be built. Uploading once per file, not once per
        # job: the same drop queued ten times is one upload.
        if params.get("use_input_image") and not self._input_image:
            self.toast.emit("drop an image first, or turn the first frame off", True)
            return
        if params.get("use_last_frame") and not self._last_image:
            self.toast.emit("drop a last frame, or turn the last frame off", True)
            return

        pending = []
        if params.get("use_input_image"):
            pending.append(("input_image", self._input_image, "_uploaded", "first frame"))
        if params.get("use_last_frame"):
            pending.append(("last_image", self._last_image, "_uploaded_last", "last frame"))
        # The LOCAL path of each frame, alongside the uploaded ref the graph
        # takes — the same pair an edit job records. Injecting a clip's settings
        # puts its frames back with them, and a toggle whose file has since gone
        # comes back off rather than arming a generate that can only refuse.
        params = dict(params)
        if params.get("use_input_image"):
            params["input_image_local"] = self._input_image
        if params.get("use_last_frame"):
            params["last_image_local"] = self._last_image
        self._upload_then_start(entry, params, count, pending)

    def _upload_edit_then_start(self, entry, params, count, paths, refs=None):
        """Upload an edit job's images — primary plus every reference — then go.

        Same re-entrant walk as `_upload_then_start`, but over a LIST of edit
        images rather than the two fixed frame slots. The primary (index 0)
        reuses the shared single-image cache so a picture already sent for a
        video first frame is not sent again; extras cache in `_edit_uploads`.
        Passes both `input_image` (the primary ref) and `input_images` (all of
        them, in order) so the graph can chain a ReferenceLatent per image.
        """
        refs = refs or []
        i = len(refs)
        if i == len(paths):
            # `input_image_local` records the primary's LOCAL path (as opposed
            # to `input_image`, the uploaded "subfolder/name" ref a LoadImage
            # takes): the output PNG keeps it so opening an edit result can show
            # the before/after in the viewer's compare mode. It never reaches
            # the graph — no node reads it — only the recorded parameters.
            self._start_jobs(
                entry,
                dict(params, input_image=refs[0], input_images=list(refs),
                     input_image_local=paths[0]),
                count)
            return
        path = paths[i]
        if i == 0 and self._uploaded[0] == path and self._uploaded[1]:
            cached = self._uploaded[1]
        else:
            cached = self._edit_uploads.get(path)
        if cached:
            self._upload_edit_then_start(entry, params, count, paths, refs + [cached])
            return
        label = "image" if len(paths) == 1 else f"image {i + 1} of {len(paths)}"
        self._set_status(f"uploading the {label}...")

        def uploaded(ref, error):
            if not ref:
                self._set_status("ready")
                self.toast.emit(f"could not send the {label}: {error}", True)
                return
            if i == 0:
                self._uploaded = (path, ref)
            else:
                self._edit_uploads[path] = ref
            self._upload_edit_then_start(entry, params, count, paths, refs + [ref])

        self.client.upload_image(path, uploaded)

    def _upload_then_start(self, entry, params, count, pending):
        """Send whatever dropped frames this job needs, one at a time, then go.

        Uploads are async, so this walks the list by re-entering itself from the
        callback rather than waiting on each one.
        """
        if not pending:
            self._start_jobs(entry, params, count)
            return
        key, path, slot, label = pending[0]
        cached = getattr(self, slot)
        if cached[0] == path and cached[1]:
            self._upload_then_start(entry, dict(params, **{key: cached[1]}),
                                    count, pending[1:])
            return
        self._set_status(f"uploading the {label}...")

        def uploaded(ref, error):
            if not ref:
                self._set_status("ready")
                self.toast.emit(f"could not send the {label}: {error}", True)
                return
            setattr(self, slot, (path, ref))
            self._upload_then_start(entry, dict(params, **{key: ref}),
                                    count, pending[1:])

        self.client.upload_image(path, uploaded)

    def _start_jobs(self, entry, params, count):
        if self._jobs == 0:
            # A fresh batch. Its clock starts HERE and not at the last job's own
            # start: four images asked for in one press are one wait to the
            # person who pressed it, and the toast at the end reports that wait.
            self._batch_start = time.time()
            self._batch_saved = []
            self._batch_pending = 0
            self._batch_toasted = False
        base = dict(params)
        base["loras"] = self.loras.active()
        seed = int(base.get("seed", 0))
        randomise = bool(base.pop("randomSeed", False))
        # "reuse last seed": re-run at the exact base seed the previous batch
        # used (captured below), so an image can be reproduced. It wins over a
        # random/negative seed. `reuse_base` is read before the loop rewrites it.
        reuse = bool(base.pop("reuseSeed", False)) and self._last_seed >= 0
        reuse_base = self._last_seed

        for n in range(max(1, int(count))):
            p = dict(base)
            if reuse:
                p["seed"] = reuse_base + n
            elif randomise or seed < 0:
                import secrets

                p["seed"] = secrets.randbelow(2**53)
            else:
                p["seed"] = seed + n
            # Remember the base seed this batch ran at, so the UI can offer to
            # reproduce it. The first job's seed IS the base; the rest walk from
            # it (or are independently random, in which case only the base is
            # recoverable — which is what "reuse" then reproduces).
            if n == 0 and p["seed"] != self._last_seed:
                self._last_seed = p["seed"]
                self.lastSeedChanged.emit()
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
        # A cancelled batch has nothing to announce, and nothing of its may
        # leak into the next one's toast.
        self._batch_toasted = True
        self._batch_saved = []
        self._batch_pending = 0
        self._pending_toast = None
        self._busy = False
        self._clock.stop()
        self._progress = 0.0
        self.previewChanged.emit()
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
        self._step = 0
        self._sample_start = 0.0
        self._sample_start_step = 0
        self._clock.start()
        # A new job has no preview frame yet; the pane must not show the last
        # job's while this one warms up.
        self._preview_tick = 0
        self.previewChanged.emit()
        self.busyChanged.emit()

    def _on_progress(self, _job, value, maximum):
        self._progress = (value / maximum) if maximum else 0.0
        self._step = value
        # Anchor the rate on the first callback: its step is already done by the
        # time we hear of it, so counting from here measures the steps AFTER it
        # against the seconds after it, not a first step against a zero clock.
        if self._sample_start <= 0.0:
            self._sample_start = time.time()
            self._sample_start_step = value
        self.statusChanged.emit()

    def _on_preview(self, _job, data, fmt):
        """A sampler preview frame off the websocket, into the image provider.

        Silently ignored if the backend was started without `--preview-method`
        — then none of these ever arrive and the pane simply shows the last
        output instead.
        """
        if self.preview is None:
            return
        img = QImage()
        if not img.loadFromData(data, fmt.upper()):
            return
        self.preview.image = img
        self._preview_tick += 1
        self.previewChanged.emit()

    def _on_node(self, _job, role):
        self._current = role
        self.statusChanged.emit()

    def _on_finished(self, job):
        pending = []
        for img in job.images:
            pending.append(img)

        def save_one(img):
            def got(data):
                # The toast at the end of the batch carries a thumbnail, so it
                # cannot be sent until the file it points at is on disk. Every
                # exit from here — no data, a write that failed — decrements,
                # or a batch that lost one download would never toast at all.
                try:
                    if not data:
                        return
                    # BOTH shapes carry the job that made them, in the place
                    # their own format keeps text: a PNG in a tEXt chunk, an MP4
                    # as an `mdta` tag beside the graph SaveVideo already wrote
                    # there. A clip keeps the subfolder the backend filed it
                    # under (video/), which is where the gallery looks for it.
                    #
                    # A file that cannot take the tag is written VERBATIM rather
                    # than not written: an output on disk without its parameters
                    # beats a finished generation lost to a metadata writer.
                    name = str(img["filename"]).lower()
                    described = pngmeta.describe(job.meta.get("params", {}),
                                                 job.meta.get("pairing"))
                    try:
                        if name.endswith(".png"):
                            data = pngmeta.upsert_text(data, described)
                        elif Path(name).suffix in VIDEO_SUFFIXES:
                            data = mp4meta.upsert_tags(data, described)
                    except (ValueError, struct.error):
                        pass
                    dest = OUT_DIR / (img.get("subfolder") or "") / img["filename"]
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
                    self.gallery.add(str(dest))
                    self._batch_saved.append(str(dest))
                finally:
                    self._batch_pending = max(0, self._batch_pending - 1)
                    self._maybe_notify()

            self.client.download(img, got)

        self._batch_pending += len(pending)
        for img in pending:
            save_one(img)

        self._jobs = max(0, self._jobs - 1)
        if self._jobs == 0:
            self._busy = False
            self._clock.stop()
            self._progress = 0.0
            self._current = ""
            # The backend's own start/finish stamps where it has them; the bar's
            # own clock otherwise, so a job that never reported a start still
            # leaves a time behind rather than a blank.
            wall = max(0.0, time.time() - self._job_start) if self._job_start else 0.0
            self._last_elapsed = job.duration or wall
            # What the TOAST reports: the whole batch, measured from the press.
            self._batch_elapsed = (max(0.0, time.time() - self._batch_start)
                                   if self._batch_start else self._last_elapsed)
            self.previewChanged.emit()
            self.busyChanged.emit()
        took = f" in {job.duration:.1f}s" if job.duration else ""
        self.toast.emit(f"done{took}", False)
        self.statusChanged.emit()
        # A job with no images at all reaches zero here rather than in a
        # download callback, so the last word on the batch is asked for twice.
        self._maybe_notify()

    def _on_failed(self, _job, message):
        self._jobs = max(0, self._jobs - 1)
        if self._jobs == 0:
            self._busy = False
            self._clock.stop()
            self.previewChanged.emit()
            self.busyChanged.emit()
            # One toast per batch, and a failure is the one it gets: the
            # outputs that DID land are still in the gallery, but "generation
            # failed" is the thing he needs to come back for.
            if not self._batch_toasted:
                self._batch_toasted = True
                self._batch_saved = []
                self._post_toast("", "", "generation failed",
                                 message.split("\n")[0][:200], urgent=True)
        self.toast.emit(message.split("\n")[0][:200], True)
        self.statusChanged.emit()

    # -- the toast for a batch he is not watching ---------------------------

    # How long a finished CLIP waits for its poster frame before its toast goes
    # out without a thumbnail. The gallery starts extracting one the moment it
    # takes the clip; ffmpeg pulling a single frame is fast, and a toast that
    # arrives late is worse than one that arrives plain.
    POSTER_WAIT_MS = 8000

    def _onscreen(self):
        """Can he see this window right now?

        Two states say he cannot, and each is his own doing: another window has
        the keyboard (unfocused), or the surface is not on screen at all —
        `isExposed()` is false for a window rolled up, minimised or on another
        workspace, because a compositor sends no frame callbacks to a surface
        nobody can see. That is the same test viewer refuses a handoff on
        (pylib/handoff.py), and the only one hyprvtb's roll-up is visible
        through: the plugin tells an app when it is UN-hidden (vtbclient's
        WAKE), never when it is rolled away.

        No window means no toast — a headless run has nobody to interrupt.
        """
        win = self.window
        if win is None:
            return True
        try:
            return bool(win.isActive() and win.isExposed())
        except (RuntimeError, AttributeError):
            return True

    def _maybe_notify(self):
        """One toast per batch, once every job is done AND every output it made
        is on disk. Called from both ends — the last download to land and the
        last job to finish — because either can be the one that finishes it."""
        if self._batch_toasted or self._jobs or self._batch_pending:
            return
        if not self._batch_saved:
            return
        paths, self._batch_saved = self._batch_saved, []
        self._batch_toasted = True
        newest = paths[-1]
        name = Path(newest).name
        summary = "completed in " + _clock_text(self._batch_elapsed)
        body = name if len(paths) == 1 else "%d outputs, newest %s" % (len(paths), name)
        if Path(newest).suffix.lower() in VIDEO_SUFFIXES:
            # A clip thumbnails its poster frame and opens the video itself
            # (docs/DESIGN.md §8.1). The gallery is already extracting one.
            poster = self.gallery.poster_ready(newest)
            if poster:
                self._post_toast(poster, newest, summary, body)
                return
            self._pending_toast = (newest, summary, body)
            QTimer.singleShot(self.POSTER_WAIT_MS, lambda: self._flush_toast(""))
            return
        self._post_toast(newest, newest, summary, body)

    def _on_poster(self, path, dest):
        if self._pending_toast and self._pending_toast[0] == path:
            self._flush_toast(dest)

    def _flush_toast(self, poster):
        """Send the clip toast that was waiting on a poster frame — with the
        thumbnail if it landed, without it if the wait ran out. Whichever
        arrives first takes the pending toast with it, so it goes out once."""
        wait, self._pending_toast = self._pending_toast, None
        if wait is None:
            return
        path, summary, body = wait
        self._post_toast(poster, path, summary, body)

    def _post_toast(self, thumb, open_path, summary, body, urgent=False):
        """Put one toast on the panel's notification server — and only if he is
        still elsewhere. The check is here rather than at the call sites so it
        is made at the last possible moment: a clip's toast can be a few seconds
        behind its batch, and coming back to the window in the meantime is
        exactly the case that should cancel it."""
        if self._onscreen():
            return
        args = ["notify-send", "-a", "painter"]
        if thumb:
            args += ["-h", "string:x-download-image:" + str(thumb)]
        if open_path and str(open_path) != str(thumb):
            args += ["-h", "string:x-open-path:" + str(open_path)]
        if urgent:
            args += ["-u", "critical"]
        args += [summary, body]
        try:
            subprocess.run(args, capture_output=True, timeout=2)
        except (OSError, subprocess.SubprocessError):
            pass   # no notification daemon, or no notify-send: nothing to say

    # -- the words that made it, on the clipboard ---------------------------

    @Slot(str)
    def copyPrompt(self, path):
        """Put this output's own prompt on the clipboard.

        Read out of the FILE, not out of the boxes — so an output from three
        sessions ago hands back what IT was asked for, whatever is typed now.
        A clip answers the same way a still does (`outmeta.params_for`): its own
        `painter` tag when it has one, ComfyUI's graph when it predates it.

        `wl-copy`, not Qt's clipboard, for the reason spelled out in
        `_clip_file`: a Wayland selection dies with the process that offered it,
        so a prompt copied out of painter would stop pasting the moment painter
        closed. wl-copy forks a holder that outlives it. `-n` because it appends
        a newline to argv content otherwise, and a prompt pasted into a text box
        should not arrive with a blank line after it.
        """
        params = outmeta.params_for(path)
        text = ((params or {}).get("positive") or "").strip()
        if not text:
            self.toast.emit("no prompt stored in this file", True)
            return

        def done(rc, out):
            if rc != 0:
                detail = (out.splitlines() or [f"exit {rc}"])[-1]
                self.toast.emit(f"could not copy it: {detail}", True)
                return
            self.toast.emit("prompt copied", False)

        self._run_async(["wl-copy", "-n", "--", text], done)

    # -- a soundless copy, on the clipboard ---------------------------------

    @Slot(str)
    def copyMuted(self, path):
        """Put a silent copy of this clip on the clipboard, making one if needed.

        The model generates sound with the picture, which is not always what a
        clip is wanted for. The copy is `<name>-muted.mp4` beside the original
        and is REUSED when it is already there and not older than the source —
        asking twice must not leave three files behind. Nothing is re-encoded
        (`-c copy`, audio subtracted), so it runs at IO speed and the video is
        the same video.

        The clipboard gets a `text/uri-list` file:// URI, which is how this
        desktop passes a video around (docs/DESIGN.md §11 — raw video is not
        pasteable).
        """
        src = Path(path.replace("file://", ""))
        if not src.exists():
            self.toast.emit("that file is gone", True)
            return
        if is_muted_copy(src):
            self._clip_file(src)
            return
        dest = self._muted_dest(src)
        if self._muted_fresh(src, dest):
            self._clip_file(dest)
            return

        self._set_status("muting a copy...")

        def done(rc, out):
            if rc != 0 or not dest.exists():
                detail = (out.splitlines() or [f"exit {rc}"])[-1]
                self.toast.emit(f"could not mute it: {detail}", True)
                self._set_status("ready")
                return
            self._clip_file(dest)
            self._set_status("ready")

        self._run_async(self._mute_argv(src, dest), done)

    # The muted copy, in the three places that need it: the clipboard action
    # above, the drag payload below, and the freshness rule both share.
    def _muted_dest(self, src: Path) -> Path:
        return src.with_name(f"{src.stem}{MUTED_TAG}{src.suffix}")

    def _muted_fresh(self, src: Path, dest: Path) -> bool:
        try:
            return dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime
        except OSError:
            return False

    @staticmethod
    def _mute_argv(src: Path, dest: Path) -> list:
        # -map 0 -map -0:a keeps everything that is not audio; -dn drops the
        # data streams an mp4 copy otherwise refuses. Same command filer's
        # videoconv uses for "copy without audio" — a remux, not a re-encode,
        # so it runs at IO speed and the picture is bit-identical.
        return ["ffmpeg", "-hide_banner", "-nostdin", "-y",
                "-loglevel", "error", "-i", str(src),
                "-map", "0", "-map", "-0:a", "-c", "copy", "-dn",
                "-movflags", "+faststart", str(dest)]

    # -- dragging an output out of the window -------------------------------

    @Slot(str, bool, result=str)
    def dragUriList(self, path, original=False):
        """The `text/uri-list` payload for dragging one output to another app.

        A CLIP GOES OUT MUTED, unless the drag was started with Shift held
        ([his] choice, 2026-08-06): the model generates sound with the picture,
        and dropping a clip into surfer — the case he named — is a page that
        starts playing it. The silent copy is the same `<name>-muted.mp4` the
        right-click action makes, reused when it is already there.

        Wayland cannot tell what is under the cursor, so the choice is made
        HERE, at the press, and the file has to exist by then: a payload naming
        a file that is still being written is a drop that lands on nothing.
        Hence the one synchronous ffmpeg in this app — a `-c copy` remux of a
        clip this size is tens of milliseconds, it happens only on a press on a
        video tile, and it is bounded so a pathological file cannot wedge the
        window. If it fails at all, the original goes out with its sound and
        the toast says so rather than the drag quietly doing nothing.

        CRLF-terminated per RFC 2483, and percent-encoded by QUrl — never by
        hand in QML (docs/DESIGN.md §13).
        """
        src = Path(str(path).replace("file://", ""))
        if not src.exists():
            return ""
        out = src
        if (src.suffix.lower() in VIDEO_SUFFIXES and not original
                and not is_muted_copy(src)):
            out = self._mute_for_drag(src)
        return QUrl.fromLocalFile(str(out)).toString() + "\r\n"

    # -- dragging SEVERAL outputs: one collage ------------------------------

    @Slot("QVariantList", bool, result=str)
    def dragUriListFor(self, paths, original=False):
        """The payload for dragging a SELECTION out: one file, always.

        One output drags as itself (a clip muted — `dragUriList`). Two or more
        drag as a COLLAGE of them, under 4MB, because five files land five
        different ways depending on what catches them while one picture lands
        the same way everywhere ([his] ask, 2026-08-06).

        The collage is normally already built: `prepareCollage` starts it on a
        thread the moment the selection changes, which is seconds before any
        press. This joins that thread rather than racing it, and builds
        synchronously if the press somehow got there first.
        """
        paths = [str(p) for p in paths if str(p)]
        if len(paths) <= 1:
            return self.dragUriList(paths[0] if paths else "", original)
        path = self._collage_for(paths, wait=True)
        if not path:
            return self.dragUriList(paths[0], original)
        return QUrl.fromLocalFile(path).toString() + "\r\n"

    @Slot("QVariantList")
    def prepareCollage(self, paths):
        """Start building the collage for this selection, off the GUI thread.

        Called on every selection change. Two or more outputs is a few hundred
        milliseconds of decoding and half a dozen JPEG encodes — nothing to do
        at the press, where the payload has to be ready in the same event.
        """
        paths = [str(p) for p in paths if str(p)]
        if len(paths) > 1:
            self._collage_for(paths, wait=False)

    def _collage_key(self, paths):
        """Identity of a selection AND of its files: a re-generated output at
        the same path must not be served from the old collage."""
        h = hashlib.sha1()
        for p in paths:
            try:
                st = os.stat(p)
                h.update(("%s|%d|%d\0" % (p, st.st_mtime_ns, st.st_size)).encode())
            except OSError:
                h.update((p + "|missing\0").encode())
        return h.hexdigest()[:16]

    def _collage_for(self, paths, wait):
        """The collage file for `paths`, building it if need be.

        `wait=False` starts the work and returns "" — the caller is warming the
        cache. `wait=True` blocks on whatever is in flight (bounded) and
        returns the path, or "" if it could not be made.
        """
        key = self._collage_key(paths)
        dest = CACHE / "collage" / key / ("painter-collage-%d.jpg" % len(paths))
        if dest.exists():
            return str(dest)
        with self._collage_lock:
            thread = self._collage_jobs.get(key)
            if thread is None:
                thread = threading.Thread(target=self._build_collage,
                                          args=(list(paths), dest, key), daemon=True)
                self._collage_jobs[key] = thread
                thread.start()
        if not wait:
            return ""
        # Bounded: a drag must not be able to hang the window on a pathological
        # set of files. Past it the caller falls back to the single-file path.
        thread.join(timeout=25)
        return str(dest) if dest.exists() else ""

    def _build_collage(self, paths, dest, key):
        """Decode, lay out, fit under the budget, write. Worker thread only.

        A clip contributes its POSTER frame — the picture the tile shows — and
        the frame is extracted here if the gallery has not got to it yet, since
        this is the one place that can afford to wait for ffmpeg.
        """
        try:
            stills = []
            for p in paths:
                still = self.gallery.stillFor(p)
                if not still and Path(p).suffix.lower() in VIDEO_SUFFIXES:
                    still = self._poster_now(p)
                if still:
                    stills.append(still)
            images, problems = Collage.read_all(stills)
            if problems:
                self.toast.emit("skipped %d output(s) that would not decode"
                                % len(problems), True)
            res = Collage.encode(images)
            if not res.get("ok"):
                self.toast.emit("could not make the collage: %s"
                                % res.get("reason", "?"), True)
                return
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(res["bytes"])
            os.replace(tmp, dest)       # never a half-written file for a drag
        except Exception as exc:        # noqa: BLE001 - a thread that raises is silent
            self.toast.emit("could not make the collage: %s" % exc, True)
        finally:
            with self._collage_lock:
                self._collage_jobs.pop(key, None)

    def _poster_now(self, path):
        """A clip's poster frame, extracted synchronously (worker thread)."""
        try:
            dest = self.gallery._poster_path(path)
        except OSError:
            return ""
        if dest.exists():
            return str(dest)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            rc = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y",
                                 "-ss", "0", "-i", str(path), "-frames:v", "1",
                                 "-vf", "scale=1280:-1", str(dest)],
                                capture_output=True, timeout=60).returncode
        except (OSError, subprocess.SubprocessError):
            return ""
        return str(dest) if rc == 0 and dest.exists() else ""

    def _mute_for_drag(self, src: Path) -> Path:
        """A silent copy of `src` to hand to the drag, made now if need be.

        The clipboard's copy sits BESIDE the original because he asked for a
        file; this one is plumbing, so a fresh sibling is reused when there is
        one and otherwise the copy goes in the CACHE, keeping its name (the
        receiving app shows it) without leaving a second file in the gallery
        folder for every clip he happens to drag.
        """
        sibling = self._muted_dest(src)
        if self._muted_fresh(src, sibling):
            return sibling
        try:
            st = src.stat()
            dest = (CACHE / "muted" / f"{int(st.st_mtime)}-{st.st_size}"
                    / sibling.name)
        except OSError:
            return src
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            rc = subprocess.run(self._mute_argv(src, dest),
                                capture_output=True, timeout=60).returncode
        except (OSError, subprocess.SubprocessError):
            rc = 1
        if rc != 0 or not dest.exists():
            self.toast.emit("could not mute it - dragging the original", True)
            return src
        return dest

    def _clip_file(self, path):
        """Put `path` on the clipboard as a FILE, via `pylib/clipfile.py`.

        NOT Qt's clipboard: a Wayland selection dies with the process that
        offered it, so a file copied out of painter would stop being pasteable
        the moment painter closed, and `QClipboard.setMimeData` takes ownership
        of a Python-built QMimeData that PySide still has a wrapper for — Qt's
        clipboard is a global static destroyed AFTER the interpreter, so it
        frees an object whose type is gone and the process dies in
        `__run_exit_handlers`. That was a SIGSEGV on exit from any run that had
        copied something, and how the UI harness exited 139 with every check
        passing.

        And no longer `wl-copy --type text/uri-list` either — the same idea one
        MIME type short. GTK, and Chromium/Electron behind it (a browser, a chat
        client), decide a paste is a FILE from `x-special/gnome-copied-files`,
        which wl-copy cannot offer alongside anything else; without it the paste
        arrived as the path in TEXT. `clipfile` owns the selection itself and
        offers both, forks a holder that outlives painter exactly as wl-copy's
        did, and its exit code means the selection is ours.
        """
        name = Path(path).name

        def done(rc, out):
            if rc != 0:
                self.toast.emit(f"could not copy it: {out.splitlines()[-1] if out else rc}",
                                True)
                return
            self.toast.emit(f"{name} copied — paste it as a file", False)

        self._run_async([sys.executable, str(CLIPFILE), str(path)], done)

    fullScreenChanged = Signal()

    @Property(bool, notify=fullScreenChanged)
    def fullScreen(self):
        w = self.window
        try:
            return w is not None and w.visibility() == QWindow.FullScreen
        except (AttributeError, RuntimeError):
            return False

    @Slot()
    def toggleFullScreen(self):
        """One implementation for both roofs: `self.window` is a QWindow either
        way — the QML `Window` under Hyprland, the QMainWindow's window handle
        under Plasma — and QWindow.setVisibility fullscreens whichever it is."""
        w = self.window
        if w is None:
            return
        try:
            w.setVisibility(QWindow.Windowed
                            if w.visibility() == QWindow.FullScreen
                            else QWindow.FullScreen)
        except (AttributeError, RuntimeError):
            return
        self.fullScreenChanged.emit()

    @Slot()
    def openFolder(self):
        """The output directory, in the desktop's file manager — KDE's "Open
        Containing Folder", which every one of those programs has.

        `xdg-open` rather than `filer`, which takes no path argument: under
        Plasma this lands in Dolphin, which is where a File menu row saying
        this is expected to land.
        """
        try:
            subprocess.Popen(["xdg-open", str(OUT_DIR)], start_new_session=True)
        except OSError as e:
            self.toast.emit("cannot open %s: %s" % (OUT_DIR, e), True)

    @Slot(str)
    def openExternally(self, path):
        p = path.replace("file://", "")
        # An EDITING model's output (a family with an `edit` block — Flux 2
        # Klein and its kin, identified by tensor header, never by filename)
        # opens as a before/after: the source image fed to the edit graph
        # against the result. The recorded parameters carry both — `edit`/`kind`
        # marks the pipeline, `input_image_local` the primary source's local
        # path — so the viewer is launched in compare mode when the source is
        # still on disk. A plain text-to-image output opens as it always has.
        before = self._compare_source(p)
        try:
            if before:
                subprocess.Popen(["viewer", "--compare", before, p],
                                 start_new_session=True)
            else:
                subprocess.Popen(["viewer", p], start_new_session=True)
        except OSError:
            subprocess.Popen(["xdg-open", p], start_new_session=True)

    @staticmethod
    def _compare_source(png_path):
        """The local source image an edit output should be compared against, or
        "" — an editing-model result whose input file is still on disk. Anything
        else (a t2i output, a missing source) returns "" and opens normally."""
        params = outmeta.params_for(png_path)
        if not params or not (params.get("edit") or params.get("kind") == "edit"):
            return ""
        src = params.get("input_image_local") or ""
        return src if src and os.path.exists(src) else ""


def _human(n):
    for unit in ("B", "K", "M", "G"):
        if n < 1024 or unit == "G":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0
    return str(n)


# ---------------------------------------------------------------------------


class Titlebar(QObject):
    """Chrome lives in the hyprvtb titlebar, like the sibling apps.

    In a Plasma session the socket is dead and every method here is a no-op —
    but the QML still calls them on every state change, so the three signals
    below are exactly the "the chrome moved" notification the KDE shell needs
    to keep its menubar, toolbar and statusbar in step (pylib/kdeshell.py).
    One source, two roofs: no second push path, no polling.
    """

    clicked = Signal(str)
    buttonsChanged = Signal()
    footerChanged = Signal(str)
    loadingChanged = Signal(bool)

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
        self.buttonsChanged.emit()
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
        self.footerChanged.emit(str(text))
        if self._client:
            try:
                self._client.set_footer(text)
            except Exception:  # noqa: BLE001
                pass

    @Slot(bool)
    def setLoading(self, on):
        self.loadingChanged.emit(bool(on))
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

    # The Controls style, and with it the whole face: `Basic` in the Hyprland
    # session (the system default resolves to Breeze, whose ToolTip pulls in
    # kirigami and fails to load where there is none), `org.kde.desktop` under
    # Plasma — which is not an imitation of the KDE style but a renderer THROUGH
    # it, so a Button here is drawn by Oxygen's own code. pylib/kdeshell.py.
    kdeshell.pin_controls_style()

    # A QApplication under Plasma, the QGuiApplication we have always used
    # otherwise: QStyle is a QtWidgets class, and without it there is no system
    # style to paint with. See kdeshell.make_app.
    app = kdeshell.make_app(sys.argv, "painter")
    if selftest and app.platformName() != "offscreen":
        raise SystemExit("selftest refuses to run on platform %r, not offscreen"
                         % app.platformName())

    palette = Palette(theme_source(PANEL_THEME))
    style = DeskStyle()
    prefs = Prefs()
    ctl = Painter()
    bar = Titlebar()
    spell = SpellCheck()

    # TWO ROOFS, ONE APP (docs/DESIGN.md §7.6). Under Hyprland the QML tree IS
    # the window. Under Plasma it is the central widget of a real QMainWindow,
    # so the menubar/toolbar/statusbar are KDE widgets and the window background
    # is the system style's — the single gradient surface that runs from the
    # titlebar down through the chrome and behind this content.
    plasma = is_plasma()
    shell = kdeshell.shell("painter", size=(1280, 900), min_size=(720, 560)) if plasma else None
    engine = shell.engine() if plasma else QQmlApplicationEngine()
    if plasma:
        # THE SELECTOR IS HOW THE CONTENT CHANGES CLOTHES WITHOUT CHANGING CODE.
        # With "plasma" set, `qml/+plasma/Foo.qml` transparently replaces
        # `qml/Foo.qml` for every call site — so the panels, buttons, spinners
        # and dropdowns in this session are QtQuick.Controls painted through the
        # KDE style, while the Hyprland tree keeps ours, and not one caller has
        # a branch in it. Same API, two implementations (apps/AGENTS.md).
        kdeshell.select_plasma_files(engine)
    # The sampler's preview frames, addressed as image://livepreview/<tick>.
    # Ownership passes to the engine, so the controller keeps only a reference.
    preview = LivePreview()
    ctl.preview = preview
    engine.addImageProvider("livepreview", preview)
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

    if plasma:
        # Root.qml, not Main.qml: the Window wrapper is the Hyprland roof, and
        # a QQuickWidget hosts an Item.
        if not shell.load(QML / "Root.qml"):
            print("failed to load Root.qml", file=sys.stderr)
            for w in shell.errors() + warnings:
                print(f"  {w}", file=sys.stderr)
            return 2
        # THE PARAMETERS COLUMN IS NOT A DOCK. It was one for a day — a real
        # QDockWidget, floatable and tabbable — and a dock is a second
        # QQuickWidget, which is a second scene graph rendered on the GUI thread
        # every frame (a QQuickWidget cannot use the threaded render loop). His
        # verdict, 2026-08-22: the detaching was not wanted, the dock's header
        # was not wanted, and the whole window felt slower for it. So the column
        # is back inside the one scene, beside the results, behind the same
        # draggable splitter the Hyprland roof uses, and F7 puts it away.
        # `kdeshell.dock` stays — it is general and tested; painter just does
        # not need it.

        # The chrome, built from the same tbButtons array the titlebar column
        # uses and calling the same tbAction(id) — one source, two roofs.
        # No menu_order here: the order comes from the QML root's own
        # `menuOrder`, and kdeshell keeps File first and Settings/Help last
        # whatever an app says (pylib/kdeshell.py MENU_ORDER).
        shell.bind_chrome(bar)
        shell.bind_status()      # statusLine / statusProgress / statusRight
        # Settings → Configure painter… opens a real dialog here, not the
        # slide-out drawer, which is shaped for a titlebar cell that this
        # session does not have (qml/SettingsDrawer.qml `asDialog`).
        def open_settings():
            return shell.show_dialog(
                "settings", "Configure painter", QML / "SettingsPage.qml",
                size=(480, 430), props={"app": shell.root})

        shell.on_action("set", open_settings)
        # The filter field at the right-hand end of the toolbar, where every KDE
        # program keeps one. It filters the gallery by filename and prompt.
        # Right-aligned with the RESULTS pane rather than with the window: it
        # filters the outputs, so it belongs over them and not over the
        # parameter column. `paneLeadW` is where that pane ends (the splitter).
        shell.toolbar_search(ctl.gallery.setFilter, placeholder="Filter outputs",
                             align_right_to="paneLeadW")
        # The window is how the controller knows whether he is watching: a batch
        # that finishes behind a rolled-up or unfocused painter says so with a
        # desktop toast instead (Painter._onscreen).
        ctl.window = shell.show()
    else:
        engine.load(QUrl.fromLocalFile(str(QML / "Main.qml")))
        if not engine.rootObjects():
            print("failed to load Main.qml", file=sys.stderr)
            for w in warnings:
                print(f"  {w}", file=sys.stderr)
            return 2
        ctl.window = engine.rootObjects()[0]

    if not selftest and ctl.window is not None:
        from winstate import WinState
        win_state = WinState(ctl.window, "painter")  # keep ref: persists geometry

    if selftest:
        rc = [0]

        def finish():
            # PAINTER_SHOT: write what the selftest actually rendered to a PNG.
            # The Plasma face is chrome we do not draw — the menubar, the
            # toolbar, the statusbar and the window background all come from the
            # KDE style — so the only way to check it is to look at the pixels
            # (the offscreen-render rule, apps/AGENTS.md; never his screen).
            # PAINTER_TREE: the item tree with its real geometry, which is the
            # only way to tell a component that is mis-sized from one that is
            # merely drawn oddly — a rendered PNG shows the symptom, this shows
            # which item owns it.
            # PAINTER_MENUS: the menubar/toolbar as text. A menu is not on
            # screen until it is opened, so no render can show what is in one —
            # this is the only check the KDE menu structure gets.
            # PAINTER_DIALOG: build and grab the settings dialog, which no
            # shot of the main window can contain — it is its own window.
            if plasma and os.environ.get("PAINTER_DIALOG"):
                dlg = open_settings()
                dlg.grab().save(os.environ["PAINTER_DIALOG"])
                print(f"selftest: wrote {os.environ['PAINTER_DIALOG']}")
            # PAINTER_ABOUT: trigger Help → About. Its own window, and the one
            # that used to take the whole app down with it (kdeshell's
            # `_about_action` records the crash), so it is worth a check that
            # costs one line.
            if plasma and os.environ.get("PAINTER_ABOUT"):
                shell._actions["__about"].trigger()
                app.processEvents()
                shell._about_box.grab().save(os.environ["PAINTER_ABOUT"])
                print(f"selftest: wrote {os.environ['PAINTER_ABOUT']}")
                shell._about_box.hide()
            if plasma and os.environ.get("PAINTER_MENUS"):
                print(shell.dump_chrome())
            if os.environ.get("PAINTER_TREE"):
                # What the WIDGET half is wearing — the half a QML-only dump
                # cannot see, and the half that goes wrong when the KDE platform
                # theme is missing (kdeshell.apply_palette).
                try:
                    print(f"style={app.style().objectName()} "
                          f"window={app.palette().window().color().name()} "
                          f"text={app.palette().windowText().color().name()} "
                          f"icons={QIcon.themeName()}")
                except Exception:  # noqa: BLE001
                    pass
                root_item = shell.root if shell is not None else ctl.window
                want = os.environ.get("PAINTER_TREE")

                def walk(it, depth=0):
                    if depth > 12 or it is None:
                        return
                    # VISUAL children, not QObject children. A Repeater's
                    # delegates and anything a view reparents into its
                    # contentItem keep their QObject parent where it was, so a
                    # QObject walk went straight past the whole parameter
                    # column — the tree said it was not there while the render
                    # showed it plainly.
                    kids = (it.childItems() if hasattr(it, "childItems")
                            else it.children())
                    for ch in kids:
                        try:
                            cls = ch.metaObject().className()
                            # QML-DEFINED TYPES ARE THE ONES WORTH SEEING, and
                            # their className is `Panel_QMLTYPE_42`, not
                            # `QQuick…` — filtering on that prefix hid exactly
                            # the components being debugged.
                            if ch.property("height") is None:
                                walk(ch, depth)
                                continue
                            name = ch.property("title") or ch.property("label") or ""
                            if want == "1" or want.lower() in (cls + " " + str(name)).lower():
                                pad = ch.property("topPadding")
                                print("  " * depth + f"{cls} {name!r} "
                                      f"y={ch.property('y')} h={ch.property('height')} "
                                      f"ih={ch.property('implicitHeight')} "
                                      f"vis={ch.property('visible')}"
                                      + (f" topPad={pad} botPad={ch.property('bottomPadding')}"
                                         f" collapsed={ch.property('collapsed')}" if pad is not None else ""))
                        except Exception:  # noqa: BLE001
                            pass
                        walk(ch, depth + 1)

                walk(root_item)
                # ...and the docks, which are scenes of their own and therefore
                # invisible to a walk from the central widget's root.
                for ident, (_dw, _v, _bg, item, _c) in getattr(
                        shell, "_docks", {}).items():
                    print(f"[dock {ident}]")
                    walk(item)

            shot = os.environ.get("PAINTER_SHOT")
            if shot:
                try:
                    if shell is not None:
                        shell.window.grab().save(shot)
                    elif ctl.window is not None:
                        ctl.window.grabWindow().save(shot)
                    print(f"selftest: wrote {shot}")
                except Exception as exc:  # noqa: BLE001
                    print(f"selftest: shot failed: {exc}", file=sys.stderr)
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
