"""Serialized rating/favourite/play-count writes on a private SQLite connection.

The worker exists only while jobs are queued. UI callers receive completion on
their Qt thread; file tags and Last.fm must follow successful commits only.
"""
from collections import deque
import sqlite3
import threading
import time

from PySide6.QtCore import QObject, Signal


class MetadataWrites(QObject):
    completed = Signal()

    def __init__(self, path, parent=None, timeout=5.0):
        super().__init__(parent)
        self._path = str(path)
        self._timeout = timeout
        self._lock = threading.Lock()
        self._jobs = deque()
        self._results = deque()
        self._thread = None

    def submit(self, job):
        with self._lock:
            # Queue time counts toward the lock budget: a burst of clicks
            # behind one external writer must not multiply shutdown's wait.
            self._jobs.append((job, time.monotonic() + self._timeout))
            if self._thread is None:
                self._thread = threading.Thread(target=self._run,
                                                name="player-metadata")
                self._thread.start()

    def wait(self):
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join()

    def results(self):
        with self._lock:
            results = list(self._results)
            self._results.clear()
        return results

    def _run(self):
        while True:
            with self._lock:
                if not self._jobs:
                    self._thread = None
                    return
                job, deadline = self._jobs.popleft()
            row, error = None, ""
            con = None
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise sqlite3.OperationalError("metadata write timed out")
                con = sqlite3.connect(self._path, timeout=remaining)
                con.row_factory = sqlite3.Row
                field = job["field"]
                if field == "play_count":
                    con.execute(
                        "UPDATE tracks SET play_count=COALESCE(play_count,0)+1,"
                        " last_played=? WHERE id=? AND path=?",
                        (job["time"], job["id"], job["path"]))
                elif field in ("rating", "favorite"):
                    con.execute(f"UPDATE tracks SET {field}=?, meta_mtime=?"
                                " WHERE id=? AND path=?",
                                (job["value"], job["time"], job["id"], job["path"]))
                else:
                    raise ValueError("unsupported metadata field")
                saved = con.execute("SELECT * FROM tracks WHERE id=? AND path=?",
                                    (job["id"], job["path"])).fetchone()
                if saved is None:
                    raise ValueError("track no longer in library")
                con.commit()
                row = dict(saved)
            except (sqlite3.Error, ValueError) as exc:
                error = str(exc)
            finally:
                if con is not None:
                    con.close()
            with self._lock:
                self._results.append((job, row, error))
            self.completed.emit()
