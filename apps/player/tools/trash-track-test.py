#!/usr/bin/env python3
"""Offscreen regression for the track context menu's recoverable delete."""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

scratch = tempfile.mkdtemp(prefix="player-trash-test-")
library_root = Path(scratch) / "library"
library_root.mkdir()
os.environ["XDG_DATA_HOME"] = str(Path(scratch) / "data")
os.environ["XDG_CACHE_HOME"] = str(Path(scratch) / "cache")
os.environ["XDG_STATE_HOME"] = str(Path(scratch) / "state")
os.environ["PLAYER_LIBRARY_ROOT"] = str(library_root)

sys.path.insert(0, "/home/lam/nix/apps/player")
sys.path.insert(0, "/home/lam/nix/apps/pylib")

from PySide6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication([])
if app.platformName() != "offscreen":
    raise SystemExit("refusing to run outside offscreen")

import main as P  # noqa: E402

album_dir = library_root / "Artist" / "Album"
album_dir.mkdir(parents=True)
track = album_dir / "01 song.flac"
track.write_bytes(b"fixture")
st = track.stat()
lib = P.Library(None)
lib._con.execute(
    "INSERT INTO tracks (path, mtime, size, title, artist, album, album_artist, track, added_at) "
    "VALUES (?,?,?,?,?,?,?,?,?)",
    (str(track), st.st_mtime, st.st_size, "song", "Artist", "Album", "Artist", 1, time.time()))
lib._con.commit()
P.rebuild_albums(lib._con)
track_id = lib._con.execute("SELECT id FROM tracks").fetchone()["id"]

assert lib.trash_track(track_id)
assert not track.exists()
assert lib._con.execute("SELECT COUNT(*) c FROM tracks").fetchone()["c"] == 0
assert lib._con.execute("SELECT COUNT(*) c FROM albums").fetchone()["c"] == 0
assert not lib.trash_track(track_id)
print("ok: track moved to trash and disappeared from the library")
