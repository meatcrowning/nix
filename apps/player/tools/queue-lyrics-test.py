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
APP = str(pathlib.Path(__file__).resolve().parent.parent)
sys.path.insert(0, APP)
sys.path.insert(0, str(pathlib.Path(APP).parent / "pylib"))

from PySide6.QtCore import QObject, Signal, QTimer, QCoreApplication  # noqa: E402
from PySide6.QtNetwork import QLocalSocket  # noqa: E402

import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location("playermain", APP + "/main.py")
pm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pm)


class FakePlayer(QObject):
    queueChanged = Signal()
    indexChanged = Signal()
    currentChanged = Signal()

    def __init__(self):
        super().__init__()
        self._q = [{"id": 11, "title": "One", "artist": "A", "duration": 100.0},
                   {"id": 22, "title": "Two", "artist": "B", "duration": 200.0}]
        self._i = 0

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

    # an unknown verb must not throw
    sock.write(b"BOGUS 1\n")
    sock.flush()
    check("unknown verb survived", True)

    app.quit()


QTimer.singleShot(50, step)
app.exec()
print("\n%d passed, %d failed" % (len(got), len(fails)))
sys.exit(1 if fails else 0)
