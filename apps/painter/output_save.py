"""Bounded result transfer and atomic publication, independent of the UI face."""
from collections import deque
from pathlib import Path
import os
import struct
import uuid

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

import pngmeta
import mp4meta


def _remove(path):
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def destination(root, image):
    name = str(image.get("filename") or "")
    subfolder = str(image.get("subfolder") or "")
    if not name or Path(name).name != name or name in (".", ".."):
        raise ValueError("invalid output filename")
    relative = Path(subfolder) / name
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("invalid output folder")
    dest = Path(root) / relative
    if not dest.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError("output path escapes the output directory")
    return dest


def publish(source, dest, meta, keep_before=None):
    """Keep original bytes if metadata is unsupported; publish only whole files."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tagged = dest.with_name("." + dest.name + "." + uuid.uuid4().hex + ".part")
    original = Path(source)
    described = pngmeta.describe(meta.get("params", {}), meta.get("pairing"))
    try:
        try:
            if dest.suffix.lower() == ".png":
                pngmeta.upsert_text_file(original, tagged, described)
            elif dest.suffix.lower() in (".mp4", ".webm", ".mkv"):
                mp4meta.upsert_tags_file(original, tagged, described)
            else:
                raise ValueError("unsupported metadata format")
        except (ValueError, struct.error, UnicodeError):
            tagged.unlink(missing_ok=True)
            tagged = original
        with open(tagged, "rb") as fh:
            os.fsync(fh.fileno())
        os.replace(tagged, dest)
        if keep_before:
            try:
                keep_before(dest, meta.get("params", {}))
            except OSError:
                pass  # A missing comparison source cannot invalidate a saved output.
        return str(dest)
    finally:
        _remove(tagged)
        _remove(original)


class _Signals(QObject):
    done = Signal(object, object, str, str)


class _Save(QRunnable):
    def __init__(self, job, image, source, dest, keep_before, raw=None):
        super().__init__()
        self.job, self.image, self.source, self.dest = job, image, source, dest
        self.keep_before, self.raw = keep_before, raw
        self.signals = _Signals()

    def run(self):
        path, error = "", ""
        try:
            if self.raw is not None:
                Path(self.source).write_bytes(self.raw)
            path = publish(self.source, self.dest, self.job.meta, self.keep_before)
        except Exception as exc:
            error = str(exc)
            _remove(self.source)
        self.signals.done.emit(self.job, self.image, path, error)


class OutputSaver(QObject):
    finished = Signal(object, object, str, str)

    def __init__(self, client, root, keep_before=None, parent=None):
        super().__init__(parent)
        self.client, self.root, self.keep_before = client, Path(root), keep_before
        self.queue = deque()
        self.active = 0
        self.workers = {}
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)

    def enqueue(self, job, image):
        self.queue.append((job, dict(image)))
        self._next()

    def _next(self):
        while self.active < 2 and self.queue:
            job, image = self.queue.popleft()
            self.active += 1
            try:
                dest = destination(self.root, image)
                scratch = self.root / ".downloads"
                scratch.mkdir(parents=True, exist_ok=True)
                source = scratch / (uuid.uuid4().hex + ".part")
            except Exception as exc:
                self._done(job, image, "", str(exc))
                continue
            self._download(job, image, source, dest)

    def _download(self, job, image, source, dest):
        def fetched(path, error="", raw=None):
            if error or (not path and raw is None):
                self._done(job, image, "", error or "download failed")
                return
            worker = _Save(job, image, source, dest, self.keep_before, raw)
            key = id(worker)
            self.workers[key] = worker
            worker.signals.done.connect(self._done)
            worker.signals.done.connect(lambda *_: self.workers.pop(key, None))
            self.pool.start(worker)

        if hasattr(self.client, "download_to_file"):
            self.client.download_to_file(image, source, fetched)
        else:
            # Old clients and isolated fixtures retain their byte callback.
            self.client.download(image, lambda data: fetched(None, "" if data else "download failed", data))

    def _done(self, job, image, path, error):
        self.active -= 1
        self.finished.emit(job, image, path, error)
        self._next()
