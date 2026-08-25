#!/usr/bin/env python3
"""Regression test for opening a track by path — the `%F` handler.

Three layers, matching the three pieces the feature is made of:

  1. `paths_from_argv` — what the desktop entry's arguments become (plain
     paths, `file://` URIs, Qt's own options, non-audio files, duplicates).
  2. `Library.ids_for_paths` + `Player.playPaths` — a path inside the library
     resolves to its REAL row (so ratings, play count and lyrics all still key
     on it), and a path outside it gets a transient negative-id row that every
     write path misses.
  3. `handoff_paths` ↔ the queue socket's OPEN verb — a second launch gives its
     arguments to the running player and exits, instead of starting a second
     one that fights it for MPRIS and the audio device.

Nothing here touches the live player: layer 2 runs against a scratch DB under
an isolated XDG_DATA_HOME, layer 3 against an isolated XDG_RUNTIME_DIR, and no
Player is ever constructed through __init__ (which would open libmpv and take
the audio device).

    QT_QPA_PLATFORM=offscreen python3 apps/player/tools/open-path-test.py
"""
import os
import shutil
import struct
import sys
import tempfile
import time
import wave
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session: with no
os.environ.pop("DISPLAY", None)          # display Qt aborts, it cannot fall back

SCRATCH = tempfile.mkdtemp(prefix="player-open-test-")
LIB = os.path.join(SCRATCH, "lib")
os.makedirs(LIB)
os.environ["XDG_DATA_HOME"] = os.path.join(SCRATCH, "data")
os.environ["XDG_CACHE_HOME"] = os.path.join(SCRATCH, "cache")
os.environ["XDG_STATE_HOME"] = os.path.join(SCRATCH, "state")
os.environ["XDG_RUNTIME_DIR"] = os.path.join(SCRATCH, "run")
os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700)
os.environ["PLAYER_LIBRARY_ROOT"] = LIB

sys.path.insert(0, "/home/lam/nix/apps/player")
sys.path.insert(0, "/home/lam/nix/apps/pylib")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication([])
if app.platformName() != "offscreen":   # a mapped window would be HIS screen
    raise SystemExit("refusing to run on platform %r, not offscreen"
                     % app.platformName())

import main as P  # noqa: E402

fails = []


def check(name, got, want):
    ok = got == want
    print(("  ok  " if ok else "  FAIL") + f"  {name}: {got!r}"
          + ("" if ok else f"  != {want!r}"))
    if not ok:
        fails.append(name)


def mk_wav(path, seconds=1, tone=440):
    """A real, mutagen-readable file — read_tags parses it for duration, so a
    zero-byte stub would be dropped as unreadable and prove nothing."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"".join(struct.pack("<h", (i * tone) % 4000 - 2000)
                               for i in range(8000 * seconds)))
    return path


# ---------------------------------------------------------------------------
print("paths_from_argv")

check("plain path", P.paths_from_argv(["/a/b.flac"]), ["/a/b.flac"])
check("file:// URI", P.paths_from_argv(["file:///a/b%20c.mp3"]), ["/a/b c.mp3"])
check("Qt options skipped", P.paths_from_argv(["-platform", "offscreen"]), [])
check("non-audio dropped", P.paths_from_argv(["/a/b.pdf", "/a/c.opus"]), ["/a/c.opus"])
check("case-insensitive extension", P.paths_from_argv(["/a/B.FLAC"]), ["/a/B.FLAC"])
check("duplicates collapse", P.paths_from_argv(["/a/b.wav", "/a/b.wav"]), ["/a/b.wav"])
check("relative made absolute",
      P.paths_from_argv(["x.mp3"]), [os.path.join(os.getcwd(), "x.mp3")])
check("other schemes ignored", P.paths_from_argv(["https://x/y.mp3"]), [])
check("nothing at all", P.paths_from_argv([]), [])
# The six extensions this whole change exists to unblock.
check("the six formerly-unregistered extensions",
      P.paths_from_argv(["/a/1.aiff", "/a/2.aif", "/a/3.wav", "/a/4.mpc",
                         "/a/5.tta", "/a/6.dff"]),
      ["/a/1.aiff", "/a/2.aif", "/a/3.wav", "/a/4.mpc", "/a/5.tta", "/a/6.dff"])

# ---------------------------------------------------------------------------
print("\nids_for_paths")

in_lib = mk_wav(os.path.join(LIB, "Artist", "Album", "01 known.wav"))
outside = mk_wav(os.path.join(SCRATCH, "downloads", "stray one.wav"), tone=220)

tagwriter = type("TW", (), {"enqueue": lambda *a, **k: None})()
library = P.Library(tagwriter)

# Put the in-library file in the DB the way a scan would, so "resolves to the
# real row" is a claim about a row that actually exists.
t = P.read_tags(in_lib)
st = os.stat(in_lib)
cols = ["path", "mtime", "size", "added_at"] + sorted(t)
vals = [in_lib, st.st_mtime, st.st_size, 0.0] + [t[k] for k in sorted(t)]
library._con.execute(
    f"INSERT INTO tracks ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
    vals)
library._con.commit()
real_id = library._con.execute("SELECT id FROM tracks").fetchone()["id"]

check("known file -> its real row id", library.ids_for_paths([in_lib]), [real_id])
check("unknown file -> a negative id",
      [i < 0 for i in library.ids_for_paths([outside])], [True])
check("same unknown file twice -> the SAME id",
      library.ids_for_paths([outside]) == library.ids_for_paths([outside]), True)
check("missing file dropped", library.ids_for_paths(["/nope/gone.flac"]), [])
check("a directory is not a track", library.ids_for_paths([LIB]), [])

tid = library.ids_for_paths([outside])[0]
rows = library.tracks_by_ids([real_id, tid])
check("tracks_by_ids returns both, in order", [r["id"] for r in rows], [real_id, tid])
check("transient row has a path", rows[1]["path"], outside)
check("transient row has a duration", round(rows[1]["duration"]), 1)
check("untagged transient row is titled from the filename",
      rows[1]["title"], "stray one")
check("transient row carries every DB column the real one does",
      sorted(set(rows[0]) - set(rows[1])), [])

# The negative id must MISS every write path — that is the whole safety
# argument for letting a file outside the library into the queue at all.
library.setRating(tid, 0.8)
library.setFavorite(tid, True)
library.bump_playcount(tid)
check("no row was created by writing to a transient id",
      library._con.execute("SELECT COUNT(*) c FROM tracks").fetchone()["c"], 1)
check("the real row was left alone",
      library._con.execute("SELECT rating, play_count FROM tracks"
                           ).fetchone()["play_count"], 0)
check("transient survives in memory", library.tracks_by_ids([tid])[0]["id"], tid)

# ---------------------------------------------------------------------------
print("\nplayPaths")


class FakeMpv:
    def __init__(self):
        self.pl = []
        self.playlist_pos = 0
        self.pause = False

    @property
    def playlist_count(self):
        return len(self.pl)

    def command(self, verb, *a):
        if verb == "loadfile":
            if len(a) > 1 and a[1] == "replace":
                self.pl = [a[0]]
                self.playlist_pos = 0
            else:
                self.pl.append(a[0])
        elif verb == "stop":
            self.pl = []

    def __setitem__(self, k, v):
        pass


def mk_player(lib):
    p = P.Player.__new__(P.Player)
    P.QObject.__init__(p)
    p._library = lib
    p._queue = []
    p._orig_queue = None
    p._index = -1
    p._mpv_base = 0
    p._position = p._duration = p._listened = 0.0
    p._counted = False
    p._playing = True
    p._shuffle = False
    p._loop = 0
    p._seek_target = None
    p._seek_at = 0.0
    p._mpv = FakeMpv()
    p._prefs = type("Pf", (), {"get": lambda *a: None, "set": lambda *a: None})()
    p._rg_mode, p._rg_preamp, p._rg_fallback = "off", 0.0, 0.0
    return p


pl = mk_player(library)
pl.playPaths([in_lib, outside])
check("both files queued", [t["path"] for t in pl._queue], [in_lib, outside])
check("the library one is its real row", pl._queue[0]["id"], real_id)
check("playing the first", pl._index, 0)
check("mpv was pointed at it", pl._mpv.pl, [in_lib, outside])

pl2 = mk_player(library)
pl2.playPaths([in_lib])
pl2.playPaths(["/nope/gone.flac"])
check("an all-unreadable open leaves the queue alone",
      [t["path"] for t in pl2._queue], [in_lib])

# ---------------------------------------------------------------------------
print("\nhandoff_paths <-> OPEN")

# A BARE LAUNCH IS A LAUNCH TOO. This used to return False without even
# looking — so `player` with no arguments never ran the singleton check, and a
# second instance took the running one's queue socket, lost the race for the
# MPRIS name and played its own restored queue over the top of his
# [2026-08-24, on book].
check("no player listening, no files -> False", P.handoff_paths([], timeout=0.5),
      False)
check("no player listening -> False", P.handoff_paths([in_lib], timeout=0.5), False)

srv_player = mk_player(library)
raised = []
P.start_queue_server(srv_player, app, None,
                     raise_window=lambda: raised.append(1))


def handoff(paths, timeout=5.0):
    """`handoff_paths` blocks on stdlib sockets, and the server it is talking to
    is driven by Qt's event loop — which in the real second launch belongs to a
    different PROCESS. Here they share one, so the client runs on a thread and
    the loop is pumped until it answers."""
    import threading
    out = {}
    th = threading.Thread(
        target=lambda: out.setdefault("r", P.handoff_paths(paths, timeout)))
    th.start()
    deadline = time.monotonic() + timeout + 2.0
    while th.is_alive() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    th.join(1.0)
    app.processEvents()
    return out.get("r")


# A filename with a space and a percent sign — the reason OPEN is encoded.
awkward = mk_wav(os.path.join(SCRATCH, "downloads", "a b 100% c.wav"), tone=330)

took = handoff([awkward, in_lib])
check("running player took the paths", took, True)
check("...and plays them, in order, undamaged",
      [t["path"] for t in srv_player._queue], [awkward, in_lib])
check("...starting at the first", srv_player._index, 0)

# A second handoff replaces rather than appends — "open this" means this.
check("second handoff", handoff([in_lib]), True)
check("...replaced the queue", [t["path"] for t in srv_player._queue], [in_lib])

# An OPEN naming nothing openable is answered (so the launcher exits) and
# leaves the music playing.
check("unopenable handoff still answers",
      handoff([os.path.join(SCRATCH, "ghost.flac")]), True)
check("...and did not stop the music",
      [t["path"] for t in srv_player._queue], [in_lib])

# ...and a bare second launch RAISES the running window instead of becoming a
# second player.
check("a bare second launch is taken by the running player", handoff([]), True)
check("...and asked it to come forward", len(raised), 1)
check("...without touching the queue",
      [t["path"] for t in srv_player._queue], [in_lib])

# ---------------------------------------------------------------------------
QTimer.singleShot(0, app.quit)
app.exec()
library.close()
shutil.rmtree(SCRATCH, ignore_errors=True)

print("\nFAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
