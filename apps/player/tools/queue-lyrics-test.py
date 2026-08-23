#!/usr/bin/env python3
"""Regression test for the queue socket's LYRICS subscription.

Headless and hermetic: it points XDG_RUNTIME_DIR at a temp directory before
importing anything, so `start_queue_server`'s `QLocalServer.removeServer()`
cannot unlink the LIVE player's socket and cut the user's panel off from their
running player. Do not "simplify" that away.

`Player` and `LyricsProvider` are faked — this tests the protocol and the
staleness guard, not mpv or lrclib. The fake provider answers on a timer, which
is what makes the "user skipped while a resolve was in flight" case real.

Run it with the player's own interpreter (the wrapper's python has PySide6):

    QT_QPA_PLATFORM=offscreen python3 apps/player/tools/queue-lyrics-test.py
"""
import json
import os
import pathlib
import sys
import tempfile
import time

RUN = tempfile.mkdtemp(prefix="qsrv-")
os.environ["XDG_RUNTIME_DIR"] = RUN
# It imports player's main.py, which imports QtGui: decide the platform here
# rather than trusting the caller to have typed the prefix in the usage line.
os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session: with no
os.environ.pop("DISPLAY", None)          # display Qt aborts, it cannot fall back
APP = str(pathlib.Path(__file__).resolve().parent.parent)
sys.path.insert(0, APP)
sys.path.insert(0, str(pathlib.Path(APP).parent / "pylib"))

from PySide6.QtCore import QObject, Signal, QTimer, QCoreApplication  # noqa: E402
from PySide6.QtNetwork import QLocalSocket  # noqa: E402

import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location("playermain", APP + "/main.py")
pm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pm)


# The queue server calls these on the object it is handed (main.py
# start_queue_server). The real bug this guards: the server was calling
# `player.setFavorite` on the REAL Player, which had no such method — the
# AttributeError was swallowed, the snapshot re-pushed unchanged, and the
# panel heart did nothing. The fake had a setFavorite, so the old test
# passed against the broken real path. Insist on the real shape here.
for _m in ("index", "queue_dicts", "currentTrackDict", "jumpTo", "setFavorite"):
    if not hasattr(pm.Player, _m):
        raise SystemExit(f"queue server contract broken: real Player lacks {_m!r}")


class FakeLibrary(QObject):
    """The DB+tags half of the real `Library`: owns the canonical row store and
    emits trackChanged when a write lands — exactly what the real Library does,
    so `FakePlayer` can mirror `Bridge._on_track_changed` -> `apply_track_update`."""

    trackChanged = Signal(int)

    def __init__(self, rows):
        super().__init__()
        # canonical store, keyed by id; the player's queue holds COPIES
        self._db = {r["id"]: dict(r) for r in rows}

    def setFavorite(self, tid, fav):
        self._db[tid]["favorite"] = 1 if fav else 0
        self.trackChanged.emit(tid)


class FakePlayer(QObject):
    queueChanged = Signal()
    indexChanged = Signal()
    currentChanged = Signal()

    def __init__(self):
        super().__init__()
        rows = [{"id": 11, "title": "One", "artist": "A", "duration": 100.0,
                 "favorite": 0},
                {"id": 22, "title": "Two", "artist": "B", "duration": 200.0,
                 "favorite": 1}]
        self._library = FakeLibrary(rows)
        self._q = [dict(r) for r in rows]
        self._i = 0
        self._library.trackChanged.connect(self._on_track_changed)
        self.opened = []
        self.queued = []

    @property
    def index(self):
        return self._i

    def queue_dicts(self):
        return self._q

    def currentTrackDict(self):
        return self._q[self._i]

    def jumpTo(self, i):
        self._i = i
        self.indexChanged.emit()
        self.currentChanged.emit()

    def _on_track_changed(self, tid):
        # mirror Bridge._on_track_changed -> Player.apply_track_update: patch
        # the cached queue dict in place so the NEXT snapshot reflects the write
        row = self._library._db[tid]
        for t in self._q:
            if t["id"] == tid:
                t.update(dict(row))
        self.currentChanged.emit()

    def setFavorite(self, tid, fav):
        # mirror the real Player: delegate to the library, let trackChanged
        # patch the cached queue dicts
        self._library.setFavorite(tid, bool(fav))

    # The two queue verbs, recorded rather than acted on: what this test checks
    # is that the socket parses them and calls the right one.
    def playPaths(self, paths):
        self.opened = list(paths)

    def queuePaths(self, paths):
        self.queued = list(paths)


class FakeLyrics(QObject):
    ready = Signal(int, "QVariantMap")

    def __init__(self):
        super().__init__()
        self.asked = []

    def request(self, tid):
        self.asked.append(tid)
        # asynchronous, like the real worker thread
        QTimer.singleShot(30, lambda: self.ready.emit(tid, {
            "source": "lrclib", "synced": True,
            "lines": [{"t": 0.0, "line": "first"}, {"t": 5.0, "line": "second"}],
            "text": "first\nsecond"}))


app = QCoreApplication([])
player = FakePlayer()
lyr = FakeLyrics()
pm.start_queue_server(player, app, lyr)

sock = QLocalSocket()
got = []
fails = []


def check(name, cond, extra=""):
    (got if cond else fails).append(name)
    print(("PASS " if cond else "FAIL ") + name + (" " + extra if extra else ""))


def readline(ms=2000):
    """Spin the shared event loop: the SERVER lives in this process too, so a
    blocking waitForReadyRead starves the very code that would answer us."""
    import time
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        if sock.canReadLine():
            return json.loads(bytes(sock.readLine()).decode())
        app.processEvents()
        time.sleep(0.002)
    return None


def step():
    import time
    sock.connectToServer(os.path.join(RUN, "player-queue.sock"))
    end = time.monotonic() + 2
    while sock.state() != QLocalSocket.LocalSocketState.ConnectedState and time.monotonic() < end:
        app.processEvents(); time.sleep(0.002)
    assert sock.state() == QLocalSocket.LocalSocketState.ConnectedState, "connect failed"

    d = readline()
    check("connect snapshot has tracks", len(d["tracks"]) == 2)
    check("track carries its favorite flag", d["tracks"][0]["favorite"] is False
          and d["tracks"][1]["favorite"] is True,
          str(d["tracks"]))
    check("no lyrics before subscribing", d["lyrics"] is None)
    check("no resolve before subscribing", lyr.asked == [], str(lyr.asked))

    sock.write(b"LYRICS 1\n")
    sock.flush()
    d = readline()                       # immediate ack snapshot, still empty
    check("ack snapshot is immediate", d is not None and d["lyrics"] is None)
    check("subscribing resolves current", lyr.asked == [11], str(lyr.asked))

    d = readline()                       # the resolve landing
    check("lyrics arrive after resolve",
          d["lyrics"] is not None and d["lyrics"]["synced"] is True)
    check("lines carry timestamps",
          d["lyrics"]["lines"] == [{"t": 0.0, "line": "first"},
                                   {"t": 5.0, "line": "second"}])

    # track change -> lyrics cleared, then re-resolved for the NEW id
    player.jumpTo(1)
    seen = []
    for _ in range(4):
        d = readline()
        if d is None:
            break
        seen.append(d)
    check("track change re-resolves", lyr.asked == [11, 22], str(lyr.asked))
    check("first push after skip carries NO stale lyrics",
          seen and seen[0]["lyrics"] is None,
          str(seen[0]["lyrics"]) if seen else "no push")
    check("new track's lyrics land",
          any(s["lyrics"] is not None for s in seen))

    # unsubscribe -> back to the pre-existing behaviour exactly
    sock.write(b"LYRICS 0\n")
    sock.flush()
    d = readline()
    check("unsubscribe clears the field", d["lyrics"] is None)
    n = len(lyr.asked)
    player.jumpTo(0)
    for _ in range(2):
        readline()
    check("no resolve while unsubscribed", len(lyr.asked) == n, str(lyr.asked))

    # A client that NEVER says LYRICS is a pre-subscription panel — the shape
    # the field was added under, and the one that has to keep working forever.
    # It must see `"lyrics": null` on every push, including while ANOTHER client
    # is subscribed and lyrics are cached, and it must trigger no resolve.
    sock.write(b"LYRICS 1\n")
    sock.flush()
    readline()
    old = QLocalSocket()
    old.connectToServer(os.path.join(RUN, "player-queue.sock"))
    end = time.monotonic() + 2
    while old.state() != QLocalSocket.LocalSocketState.ConnectedState \
            and time.monotonic() < end:
        app.processEvents(); time.sleep(0.002)

    def old_read(ms=2000):
        e = time.monotonic() + ms / 1000.0
        while time.monotonic() < e:
            if old.canReadLine():
                return json.loads(bytes(old.readLine()).decode())
            app.processEvents(); time.sleep(0.002)
        return None

    d = old_read()
    check("pre-LYRICS client: field present", d is not None and "lyrics" in d)
    check("pre-LYRICS client: field null", d is not None and d["lyrics"] is None)
    check("pre-LYRICS client: sees the queue", d is not None and len(d["tracks"]) == 2)
    player.jumpTo(1)
    seen_old, seen_new = [], []
    for _ in range(4):
        o = old_read(400)
        if o is not None:
            seen_old.append(o)
        n2 = readline(400)
        if n2 is not None:
            seen_new.append(n2)
    check("pre-LYRICS client never gets lyrics",
          bool(seen_old) and all(s["lyrics"] is None for s in seen_old),
          str([s["lyrics"] for s in seen_old]))
    check("subscribed client still does",
          any(s["lyrics"] is not None for s in seen_new))
    old.disconnectFromServer()
    app.processEvents()
    sock.write(b"LYRICS 0\n")
    sock.flush()
    readline()

    # GOTO still works
    sock.write(b"GOTO 1\n")
    sock.flush()
    d = readline()
    check("GOTO still moves the index", player.index == 1)

    # TOGGLE_FAV flips the current track (index 1 = id 22, favourite on) and
    # re-pushes a fresh snapshot so the panel heart re-lights immediately.
    # Drain first: GOTO fires indexChanged AND currentChanged, so the last
    # readline above may have left a stale snapshot buffered.
    while readline(120) is not None:
        pass
    sock.write(b"TOGGLE_FAV\n")
    sock.flush()
    d = readline()
    check("TOGGLE_FAV flips the current track's favourite off",
          d is not None and d["tracks"][1]["favorite"] is False,
          str(d["tracks"]) if d else "no push")
    # TOGGLE_FAV pushes TWICE in the real architecture: the cache patch
    # (setFavorite -> trackChanged -> apply_track_update) emits currentChanged
    # -> on_track -> push, then the handler's own push(). Drain the leftover so
    # the read below sees the second toggle's outcome, not a stale copy of the
    # first.
    while readline(120) is not None:
        pass
    sock.write(b"TOGGLE_FAV\n")
    sock.flush()
    d = readline()
    check("TOGGLE_FAV toggles, it does not set",
          d is not None and d["tracks"][1]["favorite"] is True,
          str(d["tracks"]) if d else "no push")

    # QUEUE appends and plays nothing — OPEN's counterpart, and what an agent
    # asking to "put this album on after this one" lands in (apps/oracle).
    while readline(120) is not None:
        pass
    sock.write(b"QUEUE /tmp/one.flac /tmp/two%20b.flac\n")
    sock.flush()
    readline()
    check("QUEUE appends the paths it was given",
          player.queued == ["/tmp/one.flac", "/tmp/two b.flac"],
          str(player.queued))
    check("...and starts nothing", player.opened == [])

    # an unknown verb must not throw
    sock.write(b"BOGUS 1\n")
    sock.flush()
    check("unknown verb survived", True)

    app.quit()


QTimer.singleShot(50, step)
app.exec()
print("\n%d passed, %d failed" % (len(got), len(fails)))
sys.exit(1 if fails else 0)
