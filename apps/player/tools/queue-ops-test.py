#!/usr/bin/env python3
"""Regression test for Player.queueTracks / playNext / removeFromQueue — the
queue mutations behind the track context menu (qml/TrackMenu.qml).

Builds a Player WITHOUT running __init__ (which would open libmpv and take the
audio device) and drives the list arithmetic against a fake mpv playlist and a
fake library. The LIVE player is never touched — nothing here opens a socket,
a database or an MPRIS name.

What it is actually guarding: that `_orig_queue` (the pre-shuffle order) tracks
every mutation, so nothing added while shuffled disappears when shuffle goes
off; and that removing a row ABOVE the playing one shifts the index without
restarting the track, while removing the playing row itself hands its slot to
the row that slid into it.

Run it with the player's own interpreter (the wrapper's python has PySide6):

    QT_QPA_PLATFORM=offscreen python3 apps/player/tools/queue-ops-test.py
"""
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session: with no
os.environ.pop("DISPLAY", None)          # display Qt aborts, it cannot fall back
sys.path.insert(0, "/home/lam/nix/apps/player")
sys.path.insert(0, "/home/lam/nix/apps/pylib")

from PySide6.QtGui import QGuiApplication  # noqa: E402
app = QGuiApplication([])
if app.platformName() != "offscreen":   # a mapped window would be HIS screen
    raise SystemExit("refusing to run on platform %r, not offscreen"
                     % app.platformName())

import main as P  # noqa: E402

# every path "exists" for the duration of the test
P.os.path.exists = lambda p: True


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
            path, how = a[0], (a[1] if len(a) > 1 else "append")
            if how == "replace":
                self.pl = [path]
                self.playlist_pos = 0
            else:
                self.pl.append(path)
        elif verb == "playlist-remove":
            del self.pl[a[0]]
        elif verb == "stop":
            self.pl = []

    def __setitem__(self, k, v):
        pass


class FakeLib:
    def tracks_by_ids(self, ids):
        return [{"id": i, "path": f"/t/{i}.flac", "title": f"t{i}",
                 "duration": 100.0} for i in ids]

    def album_tracks(self, album_id):
        # two fixed albums, each 3 tracks in album order
        ids = {1: [10, 11, 12], 2: [20, 21, 22]}[album_id]
        return self.tracks_by_ids(ids)


def mk(queue_ids, index, shuffle=False, orig=None):
    p = P.Player.__new__(P.Player)
    P.QObject.__init__(p)
    p._library = FakeLib()
    p._queue = FakeLib().tracks_by_ids(queue_ids)
    p._orig_queue = FakeLib().tracks_by_ids(orig) if orig else None
    p._index = index
    p._mpv_base = 0
    p._position = 0.0
    p._duration = 0.0
    p._listened = 0.0
    p._counted = False
    p._playing = True
    p._shuffle = shuffle
    p._loop = 0
    p._seek_target = None
    p._seek_at = 0.0
    p._mpv = FakeMpv()
    p._mpv.pl = [t["path"] for t in p._queue]
    p._mpv.playlist_pos = max(0, index)
    p._prefs = type("Pf", (), {"get": lambda *a: None, "set": lambda *a: None})()
    p._rg_mode, p._rg_preamp, p._rg_fallback = "off", 0.0, 0.0
    return p


def ids(p):
    return [t["id"] for t in p._queue]


fails = []


def check(name, got, want):
    ok = got == want
    print(("  ok  " if ok else "  FAIL") + f"  {name}: {got}" + ("" if ok else f"  != {want}"))
    if not ok:
        fails.append(name)


print("queueTracks")
p = mk([1, 2, 3], 1)
p.queueTracks([7, 8])
check("appended", ids(p), [1, 2, 3, 7, 8])
check("mpv playlist", p._mpv.pl, ["/t/1.flac", "/t/2.flac", "/t/3.flac", "/t/7.flac", "/t/8.flac"])

p = mk([], -1)
p.queueTracks([4, 5])
check("empty queue becomes a play", ids(p), [4, 5])
check("...and starts it", p._index, 0)

p = mk([2, 1, 3], 0, shuffle=True, orig=[1, 2, 3])
p.queueTracks([9])
check("shuffled: queue", ids(p), [2, 1, 3, 9])
check("shuffled: orig order grew too", [t["id"] for t in p._orig_queue], [1, 2, 3, 9])

print("playNext")
p = mk([1, 2, 3], 1)
p.playNext([9])
check("inserted after current", ids(p), [1, 2, 9, 3])
check("current index untouched", p._index, 1)
check("mpv tail rebuilt", p._mpv.pl, ["/t/1.flac", "/t/2.flac", "/t/9.flac", "/t/3.flac"])

p = mk([2, 1, 3], 0, shuffle=True, orig=[1, 2, 3])
p.playNext([9])
check("shuffled: queue", ids(p), [2, 9, 1, 3])
check("shuffled: orig gets it after the same track",
      [t["id"] for t in p._orig_queue], [1, 2, 9, 3])

p = mk([], -1)
p.playNext([4])
check("nothing playing -> plain play", ids(p), [4])

print("playAlbumNext")
p = mk([1, 2, 3], 1)
p.playAlbumNext(1)
check("album tracks inserted after current, in album order", ids(p), [1, 2, 10, 11, 12, 3])
check("current index untouched", p._index, 1)
check("mpv tail rebuilt", p._mpv.pl,
      ["/t/1.flac", "/t/2.flac", "/t/10.flac", "/t/11.flac", "/t/12.flac", "/t/3.flac"])

p = mk([2, 1, 3], 0, shuffle=True, orig=[1, 2, 3])
p.playAlbumNext(2)
check("shuffled: album after the same track", ids(p), [2, 20, 21, 22, 1, 3])
check("shuffled: orig got it after the same track",
      [t["id"] for t in p._orig_queue], [1, 2, 20, 21, 22, 3])

p = mk([], -1)
p.playAlbumNext(1)
check("nothing playing -> plain play of the album", ids(p), [10, 11, 12])

print("removeFromQueue")
p = mk([1, 2, 3, 4], 2)
p.removeFromQueue([0])
check("removed above current", ids(p), [2, 3, 4])
check("index shifted down", p._index, 1)
check("still the same track", p._queue[p._index]["id"], 3)

p = mk([1, 2, 3, 4], 1)
p.removeFromQueue([3])
check("removed below current", ids(p), [1, 2, 3])
check("index unchanged", p._index, 1)

p = mk([1, 2, 3, 4], 1)
p.removeFromQueue([1])
check("removed the PLAYING row", ids(p), [1, 3, 4])
check("...next one takes its place", p._index, 1)
check("...and is what mpv plays", p._mpv.pl[0], "/t/3.flac")

p = mk([1, 2, 3], 2)
p.removeFromQueue([2])
check("removed the LAST, playing row", ids(p), [1, 2])
check("...clamps to the new end", p._index, 1)

p = mk([1, 2, 3], 1)
p.removeFromQueue([0, 1, 2])
check("removed everything", ids(p), [])
check("...index cleared", p._index, -1)

p = mk([1, 2, 3, 4, 5], 4)
p.removeFromQueue([0, 2])
check("multi-remove above current", ids(p), [2, 4, 5])
check("...index shifted by 2", p._index, 2)

p = mk([1, 2, 3], 1)
p.removeFromQueue([9, -1])
check("out-of-range ignored", ids(p), [1, 2, 3])

p = mk([2, 1, 3], 0, shuffle=True, orig=[1, 2, 3])
p.removeFromQueue([2])
check("shuffled: orig loses it too", [t["id"] for t in p._orig_queue], [1, 2])

print("\nFAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
