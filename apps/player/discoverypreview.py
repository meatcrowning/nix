"""A temporary preview queue on Player's existing mpv instance."""
from PySide6.QtCore import Property, Signal, Slot, QTimer
from discovery import preview_url


class PreviewMixin:
    previewChanged = Signal()
    _sigPreviewPath = Signal(str)

    @Property(bool, notify=previewChanged)
    def previewing(self):
        return getattr(self, "_preview_snapshot", None) is not None

    @Property(str, notify=previewChanged)
    def previewLabel(self):
        return getattr(self, "_preview_label", "") if self.previewing else ""

    def _preview_path(self, path):
        if self.previewing and any(t["path"] == path for t in self._queue):
            self._preview_started = True

    def startPreview(self, item, index=-1):
        tracks = item.get("tracks", [])
        if index >= 0:
            tracks = tracks[index:index + 1]
        tracks = [t for t in tracks if preview_url(t.get("preview", ""))]
        if not tracks:
            return
        if not self.previewing:
            self._preview_snapshot = {name: getattr(self, name) for name in (
                "_queue", "_orig_queue", "_index", "_position", "_duration", "_playing",
                "_shuffle", "_loop", "_listened", "_counted", "_started_at")}
        self._preview_started = False
        self._preview_generation = getattr(self, "_preview_generation", 0) + 1
        generation = self._preview_generation
        self._preview_label = item["artist"] + " — " + item["album"]
        self._queue = [{"id": -1000000 - i, "path": t["preview"], "title": t["title"],
                        "artist": t["artist"], "album": item["album"], "duration": 0,
                        "album_id": 0, "preview": True} for i, t in enumerate(tracks)]
        self._orig_queue = None
        self._shuffle = False
        self._loop = self.LOOP_NONE
        self._mpv["loop-file"] = "no"
        self._seek_target = None
        self._duration = 0
        self.queueChanged.emit()
        self.shuffleChanged.emit()
        self.loopChanged.emit()
        self.previewChanged.emit()
        try:
            self._sync_mpv(0)
            QTimer.singleShot(30000, lambda: self.endPreview() if self.previewing
                              and self._preview_generation == generation
                              and not self._preview_started else None)
        except Exception:
            self.endPreview()

    @Slot()
    def endPreview(self):
        self._restore_preview(True)

    def _restore_preview(self, load):
        saved = getattr(self, "_preview_snapshot", None)
        if saved is None:
            return
        self._preview_snapshot = None
        self._preview_started = False
        self._mpv_fill_token += 1
        self._mpv_fill_pending = False
        self._mpv.pause = True
        for name, value in saved.items():
            setattr(self, name, value)
        self._seek_target = None
        self._mpv["loop-file"] = "inf" if self._loop == self.LOOP_TRACK else "no"
        if load and 0 <= self._index < len(self._queue):
            # mpv's per-file start option applies before audio begins, including
            # slow network files. A fixed-delay seek can resume at the wrong spot.
            self._sync_mpv(self._index, paused=not saved["_playing"], position=saved["_position"])
            for name in ("_listened", "_counted", "_started_at", "_position", "_duration"):
                setattr(self, name, saved[name])
        else:
            self._mpv.command("stop")
            self._playing = False
        for signal in (self.queueChanged, self.indexChanged, self.currentChanged,
                       self.positionChanged, self.durationChanged, self.shuffleChanged,
                       self.loopChanged, self.playingChanged, self.previewChanged):
            signal.emit()
