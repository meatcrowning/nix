"""Painter's gallery model, cached previews, and live generation row."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QModelIndex, QObject, QProcess,
                            QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl,
                            Signal, Slot, Property)
from PySide6.QtGui import QImageReader

import outmeta

# Book downloads its own copy of each result, but also sees top's backend output
# over the read-only sshfs peer root. Local stays first in `load_existing`: its
# copy carries Painter's injected metadata and therefore wins every duplicate.
OUT_DIR = Path(os.environ.get(
    "PAINTER_OUT", Path.home() / "Pictures" / "painter" / "out"))
PEER_OUTS = [Path(p) for p in os.environ.get("PAINTER_PEER_OUT", "").split(":") if p]
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "painter"

VIDEO_SUFFIXES = (".mp4", ".webm", ".mkv")

#: THE ROW A JOB OCCUPIES WHILE IT IS STILL SAMPLING. Not a file and never on
#: disk: a sentinel path, so every lookup that goes by path (`indexOf`,
#: `has_path`, the selection, the thumbnail cache) simply never matches it
#: rather than needing to know it exists [his, 2026-08-28] — "the preview of the
#: current step of the currently processing generation get added to the history
#: section and then get replaced with the full output when its finished".
LIVE_PATH = "live://generating"
# A "<name>-muted.mp4" beside a clip is a DERIVATIVE, not an output: painter
# makes one when you ask for a soundless copy to paste somewhere. It stays out
# of the history, or every video would be there twice.
MUTED_TAG = "-muted"


def is_muted_copy(path) -> bool:
    p = Path(path)
    return p.suffix.lower() in VIDEO_SUFFIXES and p.stem.endswith(MUTED_TAG)

THUMB_PX = 560


class _ThumbJob(QRunnable):
    """One output -> one small JPEG in ~/.cache/painter/thumbs, off the GUI thread.

    WHY THIS EXISTS AT ALL, and why it is not "Qt already caches decoded
    images": on book most of the history is TOP's output directory, mounted
    read-only over sshfs (`tools/comfy-tunnel.sh`), and a tile bound straight at
    the original re-read a 1.2 MB PNG **over the network** every time its
    delegate was rebuilt — measured 0.70 s for one file. A GridView destroys a
    delegate the moment it leaves the viewport, and QQuickPixmapCache only holds
    a couple of unreferenced 420px thumbnails, so scrolling back over a row paid
    that again. That is the whole of the scroll lag, and it is also why toggling
    the preview pane stutters: closing it reveals another row and a half, i.e.
    another handful of network reads at once.

    A thumbnail is keyed by mtime+size, so a regenerated file with the same name
    gets a new one and nothing is ever stale.
    """

    class _Sig(QObject):
        done = Signal(str, str)      # (source path, thumbnail path or "")

    def __init__(self, path, dest):
        super().__init__()
        self.setAutoDelete(False)   # the model holds it; see _next_thumb
        self.path, self.dest = str(path), dest
        self.sig = _ThumbJob._Sig()

    def run(self):
        out = ""
        try:
            rd = QImageReader(self.path)
            rd.setAutoTransform(True)
            dims = rd.size()
            if dims.isValid() and max(dims.width(), dims.height()) > THUMB_PX:
                k = THUMB_PX / max(dims.width(), dims.height())
                rd.setScaledSize(QSize(max(1, round(dims.width() * k)),
                                       max(1, round(dims.height() * k))))
            img = rd.read()
            if not img.isNull():
                self.dest.parent.mkdir(parents=True, exist_ok=True)
                # Written aside and renamed: a half-written JPEG that a later
                # run finds by name would be a permanently broken tile.
                tmp = self.dest.with_name(self.dest.name + f".{os.getpid()}.part")
                if img.save(str(tmp), "JPG", 86):
                    os.replace(tmp, self.dest)
                    out = str(self.dest)
                else:
                    tmp.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001 - a missing thumbnail is cheap
            out = ""
        self.sig.done.emit(self.path, out)


class Gallery(QAbstractListModel):
    PathRole = Qt.UserRole + 1
    UrlRole = Qt.UserRole + 2
    NameRole = Qt.UserRole + 3
    VideoRole = Qt.UserRole + 4
    PosterRole = Qt.UserRole + 5
    ThumbRole = Qt.UserRole + 6
    LiveRole = Qt.UserRole + 7

    countChanged = Signal()
    #: The running job's row appeared or went. Separate from `countChanged`
    #: because what follows it is a SELECTION move, not a relayout.
    liveChanged = Signal()
    #: ...and it was replaced by the output it produced, which is the path the
    #: view moves the selection onto when it was following the job.
    liveReplaced = Signal(str)
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
        # The running job's row, while there is one — held here as well as in
        # the lists so a rescan can put it back (`load_existing` rebuilds
        # `_all` from the directory, and a job in flight is not in a directory).
        self._live = None
        self._filter = ""
        # Poster frames are extracted one at a time, off the GUI thread. A
        # gallery of 60 videos would otherwise fork 60 ffmpegs at once on a
        # machine that is already busy sampling.
        self._poster_queue = []
        self._poster_proc = None
        # Thumbnails, likewise off the GUI thread but several at a time: each
        # one is mostly a blocking read over sshfs, so three in flight overlap
        # the waiting. The queue is a STACK — the newest request is the row he
        # has just scrolled to, and the oldest is somewhere off screen.
        self._thumb_pool = QThreadPool(self)
        self._thumb_pool.setMaxThreadCount(3)
        self._thumb_queue = []
        self._thumb_busy = {}
        # path -> the mtime-size stamp its cache entries are named with, so
        # nothing on the scroll path ever stats a network mount.
        self._ck = {}

    def roleNames(self):
        return {self.PathRole: b"path", self.UrlRole: b"url", self.NameRole: b"name",
                self.VideoRole: b"isVideo", self.PosterRole: b"poster",
                self.ThumbRole: b"thumb", self.LiveRole: b"isLive"}

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
                self.PosterRole: r["poster"],
                self.ThumbRole: r["thumb"],
                self.LiveRole: bool(r.get("live"))}.get(role)

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
        # THE RUNNING JOB IS NEVER FILTERED OUT. It has no filename and no
        # prompt on disk to match against, and a filter typed while something is
        # generating must not take the thing that is generating off the screen.
        if r.get("live"):
            return True
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

    def _row_for(self, path, st=None):
        """One gallery row. `st` is the (mtime, size) the caller already read.

        IT IS TAKEN RATHER THAN RE-STATTED because half these files live on
        top's output directory over sshfs, where a stat is a network round trip
        — and the cache keys below are needed on the GUI thread, from the
        scroll path. `load_existing` stats every file exactly once anyway.
        """
        p = Path(path)
        is_video = p.suffix.lower() in VIDEO_SUFFIXES
        if st is None:
            try:
                s = os.stat(p)
                st = (s.st_mtime, s.st_size)
            except OSError:
                st = None
        return {"path": str(p), "url": QUrl.fromLocalFile(str(p)).toString(),
                "name": p.name, "is_video": is_video, "poster": "",
                "key": self._dedup_key(p),
                # What makes a cache entry this file and not a later one of the
                # same name. "" when the file could not be statted, which means
                # nothing is cached for it rather than something wrong.
                "ck": self._note_ck(p, st),
                # Already cached from an earlier session? Then the row knows its
                # picture before any delegate exists, which is the whole point:
                # no first pass over the history that decodes originals.
                "thumb": self._cached_thumb(p, is_video)}

    def cache_stamp(self, path):
        """The mtime-size stamp this row was scanned with, or "" if unknown.

        Public so the collage key can identify a file without stat-ing it: a
        shift-range over two hundred of top's outputs is two hundred sshfs
        round trips on the GUI thread, and that is a visible freeze.
        """
        return self._ck.get(str(path), "")

    def _cached_thumb(self, path, is_video):
        if is_video:
            return ""
        dest = self._thumb_path(path)
        try:
            if dest is not None and dest.exists():
                return QUrl.fromLocalFile(str(dest)).toString()
        except OSError:
            pass
        return ""

    def _note_ck(self, path, st):
        ck = "" if st is None else f"{int(st[0])}-{int(st[1])}"
        self._ck[str(path)] = ck
        return ck

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

    def add(self, path, job=""):
        if is_muted_copy(path) or self.has_path(path):
            return
        # The peer root holds top's copy of this very output, and the scan at
        # startup may already be showing it. The local one replaces it: it is
        # the copy with the parameters written into it.
        self._drop_key(self._dedup_key(path))
        row = self._row_for(path)
        # UNDER THE JOB'S OWN ROW, which is then dropped — so the new output is
        # already in the model when anything hears that the job ended.
        #
        # THE OTHER ORDER FLASHES. Ending the row first tells the preview pane
        # the selection is no longer a running job while its replacement does
        # not exist yet, so the pane falls back to "the newest output" — the
        # PREVIOUS generation — for the frame or two before the new one lands
        # [his, 2026-08-28: "when a gen finishes, it briefly flashes the
        # previous gen before showing the new output"].
        #
        # It also stays under a job that is still sampling, when the batch has
        # moved on to its next one: that file is finished and this one is not.
        at = 1 if self._live is not None else 0
        self._all.insert(at, row)
        if self._matches(row):
            self.beginInsertRows(QModelIndex(), at, at)
            self._rows.insert(at, row)
            self.endInsertRows()
        self.countChanged.emit()
        # The row the job occupied becomes the output it produced — the whole
        # point of putting it there.
        self.end_live(job, replaced_by=str(path))
        if row["is_video"]:
            self._want_poster(row["path"])
        else:
            self._want_thumb(row)

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
                    st = p.stat()
                    mtime = st.st_mtime
                except OSError:
                    continue   # deleted between the glob and the stat
                seen.add(key)
                found.append((mtime, p, st.st_size))
        # ALL OF THEM, newest first. This was capped at 60 — a number from when
        # the grid was a strip — so the history simply stopped partway with
        # nothing saying so. The view is a GridView and only builds the
        # delegates it can see, so the cost of the rest is one small dict each;
        # `limit` survives for a caller that wants a slice.
        ordered = sorted(found, key=lambda t: t[0], reverse=True)
        files = [(p, (m, sz)) for m, p, sz in (ordered[:limit] if limit else ordered)]
        self._all = [self._row_for(p, st) for p, st in files]
        # A rescan rebuilds the history from the directory; a job in flight is
        # not in the directory, and it must not vanish because something asked
        # for a rescan while it was sampling.
        if self._live is not None:
            self._all.insert(0, self._live)
        self._refilter()
        # Delegates request only the rows Qt actually realises. Starting 24
        # still decodes plus 24 video extractions here made a newly shown
        # window spend about 27 CPU-seconds preparing off-screen history before
        # it felt usable. The view's cacheBuffer already realises a few rows
        # beyond the viewport, so those requests are the right warm-up set.

    # -- poster frames -----------------------------------------------------

    def _cache_key(self, path):
        """The mtime-size stamp this file's cache entries are named with.

        Read off the row when there is one (see `_row_for`), so the scroll path
        never stats an sshfs mount; only a caller holding a path we have never
        seen pays for one.
        """
        path = str(path)
        ck = self._ck.get(path)
        if ck is not None:
            return ck
        st = os.stat(path)
        return self._note_ck(path, (st.st_mtime, st.st_size))

    def _poster_path(self, path):
        ck = self._cache_key(path)
        if not ck:
            raise OSError("no cache key")
        return CACHE / "posters" / f"{Path(path).stem}-{ck}.jpg"

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
        # A BOUNDED QUEUE. Scrolling fast still enqueues faster than ffmpeg can
        # drain, and the oldest requests are for rows long gone off screen — so
        # the queue keeps the newest and drops the rest. Nothing is lost: a row
        # that comes back asks again.
        if len(self._poster_queue) > 12:
            del self._poster_queue[:-12]
        self._poster_queue.append((path, dest))
        self._next_poster()

    @Slot(str)
    def requestPoster(self, path):
        """A clip's delegate, asking for its own poster frame.

        The gallery shows EVERY output now, and this library is a few hundred
        clips — extracting a frame from all of them at startup would be a few
        hundred ffmpeg runs for thumbnails nobody has scrolled to yet. A tile
        asks only after it has remained realised for 250ms."""
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

    # -- grid thumbnails ---------------------------------------------------
    #
    # Same shape as the poster half above and for the same reason: the picture
    # a tile draws is made once, small, and kept on local disk. See `_ThumbJob`
    # for the measurement that made it necessary.

    def _thumb_path(self, path):
        ck = self._ck.get(str(path), "")
        if not ck:
            return None
        return CACHE / "thumbs" / f"{Path(path).stem}-{ck}.jpg"

    def _want_thumb(self, row):
        if row["is_video"] or row["thumb"]:
            return
        dest = self._thumb_path(row["path"])
        if dest is None:
            return
        if dest.exists():
            # One turn of the event loop later: `requestThumb` is called from a
            # delegate being built, and a dataChanged into a view mid-creation
            # is not something to hand it.
            QTimer.singleShot(0, lambda p=row["path"], d=dest: self._thumb_ready(p, d))
            return
        path = row["path"]
        if path in self._thumb_busy:
            return
        q = self._thumb_queue
        if path in q:
            q.remove(path)
        q.append(path)
        # A flick builds and destroys hundreds of delegates; only the ones he
        # stopped on are worth decoding, and they are the newest requests.
        del q[:-24]
        self._next_thumb()

    def _next_thumb(self):
        while self._thumb_queue and len(self._thumb_busy) < 3:
            path = self._thumb_queue.pop()
            dest = self._thumb_path(path)
            if dest is None or path in self._thumb_busy:
                continue
            job = _ThumbJob(path, dest)
            # HELD, because the signal is delivered a queued event later than
            # the emit: an auto-deleting QRunnable would already have taken its
            # signal object with it and the result would simply never arrive.
            self._thumb_busy[path] = job
            job.sig.done.connect(self._thumb_done)
            self._thumb_pool.start(job)

    @Slot(str, str)
    def _thumb_done(self, path, dest):
        self._thumb_busy.pop(path, None)
        if dest:
            self._thumb_ready(path, Path(dest))
        self._next_thumb()

    @Slot(str)
    def requestThumb(self, path):
        """A still's delegate, asking for its own grid thumbnail.

        Answered from disk on the spot when there is one — that is the common
        case after the first pass over the history — and queued otherwise."""
        path = str(path)
        for r in self._all:
            if r["path"] == path:
                self._want_thumb(r)
                return

    def _thumb_ready(self, path, dest):
        url = QUrl.fromLocalFile(str(dest)).toString()
        for r in self._all:
            if r["path"] != path:
                continue
            if r["thumb"] == url:
                return
            # `_rows` holds the same dict, so this reaches both lists.
            r["thumb"] = url
            for i, vr in enumerate(self._rows):
                if vr is r:
                    idx = self.index(i, 0)
                    self.dataChanged.emit(idx, idx, [self.ThumbRole])
                    break
            return

    # ------------------------------------------------------- the running job
    def _live_row(self):
        return {"path": LIVE_PATH, "url": "", "name": "generating",
                "is_video": False, "poster": "", "key": LIVE_PATH, "ck": "",
                "thumb": "", "live": True, "job": "", "grab": False}

    def begin_live(self, job="", grab=False):
        """A job was queued or started: put its row at the top of the history.

        The row draws the sampler's own preview frames (GalleryView reads
        `App.previewTick`), so the generation is a thing in the grid that can be
        SELECTED — which is what lets the preview viewport follow the selection
        without losing the way back to the job in flight.
        """
        if self._live is not None:
            # Only ever NAMED, never un-named: the row is created at submit with
            # no prompt id (there is none yet) and `_on_started` fills it in, so
            # an empty key here must not wipe the id of the job now running.
            if job:
                self._live["job"] = str(job)
            if grab:
                self._live["grab"] = True
                self.liveChanged.emit()
            return
        self._live = self._live_row()
        self._live["job"] = str(job)
        self._live["grab"] = bool(grab)
        self._all.insert(0, self._live)
        self.beginInsertRows(QModelIndex(), 0, 0)
        self._rows.insert(0, self._live)
        self.endInsertRows()
        self.countChanged.emit()
        self.liveChanged.emit()

    def end_live(self, job="", replaced_by=""):
        """The job ended — landed, failed or cancelled. Its row goes.

        `job` is the prompt id: a batch is several jobs and the NEXT one may
        already have started by the time the last one's file finishes
        downloading, so a stale completion must not take the row of the job that
        is currently sampling.
        """
        if self._live is None:
            return
        if job and self._live.get("job") and str(job) != self._live["job"]:
            return
        row = self._live
        self._live = None
        try:
            self._all.remove(row)
        except ValueError:
            pass
        for i, vr in enumerate(self._rows):
            if vr is row:
                self.beginRemoveRows(QModelIndex(), i, i)
                self._rows.pop(i)
                self.endRemoveRows()
                break
        self.countChanged.emit()
        self.liveChanged.emit()
        if replaced_by:
            self.liveReplaced.emit(str(replaced_by))

    livePath = Property(str, lambda self: LIVE_PATH if self._live else "",
                        notify=liveChanged)
    #: Whether THIS row is a newly queued batch, which takes the preview over
    #: whatever was being looked at. False for the later jobs of one batch.
    liveGrab = Property(bool, lambda self: bool(self._live and self._live.get("grab")),
                        notify=liveChanged)

    @Slot(int, result=bool)
    def isLiveAt(self, i):
        return bool(self._rows[i].get("live")) if 0 <= i < len(self._rows) else False

    @Slot(str, result=bool)
    def isLive(self, path):
        return bool(self._live) and str(path) == LIVE_PATH

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
