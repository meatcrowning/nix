#!/usr/bin/env python3
"""Regression test for pruning tracks whose files are gone.

A copy deleted outside the player (a dedupe pass over the library) used to sit
in the album listing as a greyed row until the next full scan. `Library.
prune_missing` + `Bridge._track_rows` drop it instead — but ONLY when it is
safe to: an unplugged drive makes every path in the DB stat missing, and
pruning on that would erase the library. So the four cases here are the whole
feature: prune when mounted, keep greying when unmounted, never prune a remote
library, and take the album with the last track.

Nothing touches the live player: a scratch DB under an isolated XDG_DATA_HOME,
a scratch library root, and no Player or Bridge is ever constructed.

    QT_QPA_PLATFORM=offscreen python3 apps/player/tools/prune-missing-test.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session
os.environ.pop("DISPLAY", None)

SCRATCH = tempfile.mkdtemp(prefix="player-prune-test-")
LIB = os.path.join(SCRATCH, "lib")
os.makedirs(LIB)
os.environ["XDG_DATA_HOME"] = os.path.join(SCRATCH, "data")
os.environ["XDG_CACHE_HOME"] = os.path.join(SCRATCH, "cache")
os.environ["XDG_STATE_HOME"] = os.path.join(SCRATCH, "state")
os.environ["PLAYER_LIBRARY_ROOT"] = LIB

sys.path.insert(0, "/home/lam/nix/apps/player")
sys.path.insert(0, "/home/lam/nix/apps/pylib")

from PySide6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication([])
if app.platformName() != "offscreen":   # a mapped window would be HIS screen
    raise SystemExit("refusing to run on platform %r, not offscreen"
                     % app.platformName())

import main as P  # noqa: E402

fails = []


def check(label, ok):
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        fails.append(label)


class StubBridge:
    """Just enough of Bridge to run its real _track_rows."""
    _track_rows = P.Bridge._track_rows

    def __init__(self, library):
        self._library = library


def make_files(names, album="After EP 2"):
    paths = []
    for n in names:
        d = os.path.join(LIB, "Nowhere", album)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, n)
        Path(p).write_bytes(b"x")
        paths.append(p)
    return paths


def seed(lib, paths, album="After EP 2"):
    for i, p in enumerate(paths):
        st = os.stat(p)
        lib._con.execute(
            "INSERT OR REPLACE INTO tracks (path, mtime, size, title, artist,"
            " album, album_artist, track, added_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (p, st.st_mtime, st.st_size, Path(p).stem, "Nowhere",
             album, "Nowhere", i + 1, time.time()))
    lib._con.commit()
    P.rebuild_albums(lib._con)


lib = P.Library(None)
P._REMOTE_LIBRARY = False

print("a track whose file is gone")
paths = make_files(["01 keep.flac", "02 dupe.flac", "03 keep.flac"])
seed(lib, paths)
album_id = lib._con.execute("SELECT id FROM albums").fetchone()["id"]
os.unlink(paths[1])
rows = lib.album_tracks(album_id)
check("the DB still has all three before the listing", len(rows) == 3)
out = StubBridge(lib)._track_rows(rows)
check("the listing drops it", [r["title"] for r in out]
      == ["01 keep", "03 keep"])
check("nothing is left greyed", all(r["available"] for r in out))
check("the DB row is gone too",
      len(lib.album_tracks(album_id)) == 2)
check("a second listing is a no-op",
      len(StubBridge(lib)._track_rows(lib.album_tracks(album_id))) == 2)

print("the album loses its last track")
gone_album = make_files(["01 only.flac"], album="Vanished")
seed(lib, gone_album, album="Vanished")
vid = lib._con.execute("SELECT id FROM albums WHERE album='Vanished'").fetchone()["id"]
os.unlink(gone_album[0])
out = StubBridge(lib)._track_rows(lib.album_tracks(vid))
check("the listing is empty", out == [])
check("the album goes with it",
      lib._con.execute("SELECT COUNT(*) c FROM albums WHERE album='Vanished'"
                       ).fetchone()["c"] == 0)

print("the drive is unplugged")
rest = lib.album_tracks(album_id)
for p in [r["path"] for r in rest]:
    os.unlink(p)
for d in (os.path.join(LIB, "Nowhere", "After EP 2"),
          os.path.join(LIB, "Nowhere", "Vanished"), os.path.join(LIB, "Nowhere")):
    if os.path.isdir(d):
        os.rmdir(d)
check("an empty root does not read as mounted", not P.library_mounted())
check("nothing is pruned", lib.prune_missing([r["path"] for r in rest]) == 0)
out = StubBridge(lib)._track_rows(lib.album_tracks(album_id))
check("the rows stay, greyed", len(out) == 2 and not any(r["available"] for r in out))
check("the DB is intact", len(lib.album_tracks(album_id)) == 2)

print("a remote library")
os.makedirs(os.path.join(LIB, "Nowhere"), exist_ok=True)   # mounted again
Path(os.path.join(LIB, "Nowhere", "marker")).write_bytes(b"x")
P._REMOTE_LIBRARY = True
check("prune refuses", lib.prune_missing([r["path"] for r in rest]) == 0)
out = StubBridge(lib)._track_rows(lib.album_tracks(album_id))
check("and nothing is even stat'd (all available)",
      len(out) == 2 and all(r["available"] for r in out))
P._REMOTE_LIBRARY = False

print()
print("FAILED: " + ", ".join(fails) if fails else "all good")
sys.exit(1 if fails else 0)
