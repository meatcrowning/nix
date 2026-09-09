#!/usr/bin/env python3
"""Scratch-only preference failures and SQLite contention; no player or audio."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

with tempfile.TemporaryDirectory(prefix="player-state-write-") as scratch:
    root = Path(scratch)
    for key in ("XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        os.environ[key] = str(root / key)
    os.environ["PLAYER_LIBRARY_ROOT"] = str(root / "library")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from PySide6.QtCore import QCoreApplication, QTimer
    import main as P

    app = QCoreApplication([])
    prefs = P.Prefs()
    errors = []
    prefs.saveFailed.connect(errors.append)
    prefs.set("volume", 40)
    saved = prefs._path.read_bytes()
    with patch.object(P.os, "replace", side_effect=OSError("fixture full disk")):
        prefs.set("volume", 50)
    assert prefs._path.read_bytes() == saved
    assert prefs.get("volume") == 40 and errors
    assert not list(prefs._path.parent.glob(".prefs-*.tmp"))
    with patch.object(P.os, "fsync", side_effect=OSError("fixture I/O failure")):
        prefs.set("volume", 60)
    assert prefs._path.read_bytes() == saved
    assert not list(prefs._path.parent.glob(".prefs-*.tmp"))
    with patch.object(prefs, "_write", side_effect=AssertionError("redundant write")):
        prefs.set("volume", 40)
    prefs.set("queue", {"ids": [1], "index": 0, "position": 42})
    assert json.loads(prefs._path.read_text())["queue"]["position"] == 42

    class TagWriter:
        def __init__(self): self.calls = []
        def enqueue(self, path, **fields): self.calls.append((path, fields))

    class Scrobbler:
        def __init__(self): self.calls = []
        def setLoved(self, row, value): self.calls.append(value)

    tags, lastfm = TagWriter(), Scrobbler()
    lib = P.Library(tags)
    lib.set_scrobbler(lastfm)
    lib._con.execute("INSERT INTO tracks (id,path,mtime,size,added_at,title,play_count,favorite,rating)"
                     " VALUES (1,?,0,0,0, 'fixture',4,0,0.2)", (str(root / "track.flac"),))
    lib._con.commit()
    blocker = sqlite3.connect(P.DB_PATH)
    failures, ticks = [], []
    lib.writeFailed.connect(failures.append)
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start()

    def pump_until(predicate, seconds=2):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.001)
        assert predicate(), "worker did not finish"

    blocker.execute("BEGIN IMMEDIATE")
    start = time.monotonic()
    lib.setRating(1, 0.8)
    lib.setFavorite(1, True)
    assert lib.tracks_by_ids([1])[0]["favorite"] == 1
    lib.setFavorite(1, False)
    lib.bump_playcount(1)
    lib.bump_playcount(1)
    assert time.monotonic() - start < 0.1, "UI blocked on SQLite writer"
    assert lib.tracks_by_ids([1])[0]["play_count"] == 6
    pump_until(lambda: len(ticks) >= 8)
    assert not tags.calls and not lastfm.calls
    assert blocker.execute("SELECT rating FROM tracks WHERE id=1").fetchone()[0] == 0.2
    blocker.rollback()
    pump_until(lambda: not lib._pending_metadata)
    row = dict(lib._con.execute("SELECT * FROM tracks WHERE id=1").fetchone())
    assert row["rating"] == 0.8 and row["favorite"] == 0 and row["play_count"] == 6
    assert len(tags.calls) == 5 and lastfm.calls == [True, False]

    # An exhausted lock timeout rolls the optimistic UI back and reports it.
    lib._metadata_writes._timeout = 0.05
    blocker.execute("BEGIN IMMEDIATE")
    lib.setRating(1, 0.4)
    assert lib.tracks_by_ids([1])[0]["rating"] == 0.4
    pump_until(lambda: not lib._pending_metadata)
    assert failures == ["couldn't save rating"]
    assert lib.tracks_by_ids([1])[0]["rating"] == 0.8
    assert len(tags.calls) == 5
    blocker.rollback()
    lib.setRating(1, 1.0)
    pump_until(lambda: not lib._pending_metadata)
    assert lib.tracks_by_ids([1])[0]["rating"] == 1.0
    # Closing drains successful completions even after the Qt loop stops.
    lib.setFavorite(1, True)
    lib.close()
    assert lastfm.calls == [True, False, True]
    timer.stop()
    blocker.close()
    print(f"state writes: atomic failures, queue persistence, contention, rollback, "
          f"ordered metadata and shutdown passed ({len(ticks)} UI heartbeats)")
