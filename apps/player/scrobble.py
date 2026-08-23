"""Last.fm for the player: now-playing, scrobbles, loves — off the GUI thread.

`pylib/lastfm.py` is the API and the credential file; this is the part that
knows about Qt. Every call goes on ONE background worker thread, because every
one of them is a blocking HTTPS round trip and the player is the window he is
looking at while it happens — a 15-second timeout on the GUI thread is a
15-second freeze mid-track.

Three things it is deliberately not:

- **It never decides that something was played.** `Player._maybe_count` already
  owns "this counts as a listen" for the library's own play counts, and one
  listen must be one of each — so it calls `submit()` at the same instant and
  nothing here re-derives a threshold. (`lastfm.scrobble_point` is the same
  rule, and is what refuses a track too short to scrobble at all.)
- **It never blocks a heart.** `Library.setFavorite` writes the DB and the tag
  as it always did, and posts the love here afterwards; a Last.fm outage costs
  the love, not the favourite.
- **It never raises at a caller.** A failed scrobble goes on
  `lastfm`'s disk queue and rides out with the next successful one; anything
  else lands in `lastError` and on the status line, and the app carries on.

**Nothing happens at all unless an account is linked** (docs/DESIGN.md §10 —
no affordance that is not there). With no `~/.config/lastfm/account.json`
every method returns immediately and the settings section says so, with the
one command that fixes it.
"""

import queue
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot

import lastfm


class Scrobbler(QObject):
    """The player's Last.fm side. Exposed to QML as `Lastfm`."""

    statusChanged = Signal()
    #: The approval page for a connect in progress — main.py opens it.
    authUrlReady = Signal(str)
    #: A human line for the settings section: "" while nothing has gone wrong.
    errorChanged = Signal()

    _sigStatus = Signal()          # worker thread -> GUI thread
    _sigError = Signal(str)
    _sigUrl = Signal(str)

    def __init__(self, prefs, parent=None):
        super().__init__(parent)
        self._prefs = prefs
        self._error = ""
        self._st = lastfm.status()
        self._connecting = False
        self._q = queue.Queue()
        self._sigStatus.connect(self._refresh)
        self._sigError.connect(self._set_error)
        self._sigUrl.connect(self.authUrlReady)
        self._thread = threading.Thread(target=self._run, name="lastfm",
                                        daemon=True)
        self._thread.start()
        # Anything the last session could not send goes out now, if there is
        # an account to send it to.
        if self._st["connected"]:
            self._post(self._flush)

    # ---- the worker ----

    def _run(self):
        while True:
            job = self._q.get()
            if job is None:
                return
            try:
                job()
            except lastfm.LastfmError as e:
                self._sigError.emit(str(e))
            except Exception as e:                      # never take the thread down
                self._sigError.emit("%s: %s" % (type(e).__name__, e))
            finally:
                self._sigStatus.emit()

    def _post(self, fn):
        self._q.put(fn)

    def _flush(self):
        lastfm.flush_queue()

    # ---- state, for QML ----

    def _refresh(self):
        self._st = lastfm.status()
        self.statusChanged.emit()

    def _set_error(self, msg):
        self._error = msg
        self.errorChanged.emit()

    @Property(bool, notify=statusChanged)
    def connected(self):
        return bool(self._st.get("connected"))

    @Property(bool, notify=statusChanged)
    def hasKeys(self):
        return bool(self._st.get("keys"))

    @Property(str, notify=statusChanged)
    def username(self):
        return str(self._st.get("username") or "")

    @Property(int, notify=statusChanged)
    def queued(self):
        return int(self._st.get("queued") or 0)

    @Property(bool, notify=statusChanged)
    def connecting(self):
        return self._connecting

    @Property(str, notify=errorChanged)
    def lastError(self):
        return self._error

    @Property(str, constant=True)
    def configPath(self):
        return str(lastfm.CONFIG_PATH)

    @Property(str, constant=True)
    def connectCommand(self):
        """The one command that gets the API key in place — the settings
        section prints it verbatim rather than describing it."""
        return str(Path(__file__).resolve().parent / "tools" / "lastfm-connect.py")

    #: prefs, not credentials: whether a linked account is actually used.
    @Property(bool, notify=statusChanged)
    def scrobbling(self):
        return bool(self._prefs.get("scrobble", True))

    @Property(bool, notify=statusChanged)
    def loveOnFavorite(self):
        return bool(self._prefs.get("scrobbleLove", True))

    @Slot(bool)
    def setScrobbling(self, on):
        self._prefs.set("scrobble", bool(on))
        self.statusChanged.emit()

    @Slot(bool)
    def setLoveOnFavorite(self, on):
        self._prefs.set("scrobbleLove", bool(on))
        self.statusChanged.emit()

    # ---- what the player calls ----

    def _live(self):
        return self._st.get("connected") and self._prefs.get("scrobble", True)

    @staticmethod
    def _fields(track):
        """A library row -> the four fields Last.fm wants, or None when the
        row cannot identify a recording (a scrobble with no artist is junk in
        his history that only he can delete)."""
        if not track:
            return None
        artist = str(track.get("artist") or "").strip()
        title = str(track.get("title") or "").strip()
        if not artist or not title:
            return None
        return {"artist": artist, "track": title,
                "album": str(track.get("album") or "").strip(),
                "album_artist": str(track.get("album_artist")
                                    or track.get("albumArtist") or "").strip(),
                "duration": float(track.get("duration") or 0.0)}

    @Slot("QVariant")
    def nowPlaying(self, track):
        f = self._fields(track)
        if not f or not self._live():
            return
        if lastfm.scrobble_point(f["duration"]) <= 0 and f["duration"]:
            return                       # too short to scrobble, so don't announce
        self._post(lambda: lastfm.now_playing(**f))

    @Slot("QVariant", float)
    def submit(self, track, started_at=0.0):
        """One play, at the moment the player decided it counted."""
        f = self._fields(track)
        if not f or not self._live():
            return
        if lastfm.scrobble_point(f["duration"]) <= 0 and f["duration"]:
            return
        when = int(started_at or time.time())
        self._post(lambda: lastfm.scrobble(when=when, **f))

    @Slot("QVariant", bool)
    def setLoved(self, track, loved):
        f = self._fields(track)
        if not f or not self._st.get("connected"):
            return
        if not self._prefs.get("scrobbleLove", True):
            return
        fn = lastfm.love if loved else lastfm.unlove
        self._post(lambda: fn(f["artist"], f["track"]))

    # ---- connect / disconnect, from the settings page ----

    @Slot()
    def beginConnect(self):
        """Whole desktop flow on the worker: token, then the approval page
        (emitted for main.py to open), then poll until he says yes.

        Polling rather than a second "I've approved it" button: Last.fm
        answers `auth.getSession` with error 14 until the token is authorized,
        so the flow can finish by itself and there is no way to click the
        button too early."""
        if self._connecting or not self._st.get("keys"):
            if not self._st.get("keys"):
                self._set_error("no API key yet — run tools/lastfm-connect.py "
                                "--keys KEY SECRET")
            return
        self._connecting = True
        self._set_error("")
        self.statusChanged.emit()
        self._post(self._do_connect)

    def _do_connect(self):
        try:
            token = lastfm.get_token()
            self._sigUrl.emit(lastfm.auth_url(token))
            deadline = time.time() + 180
            while time.time() < deadline:
                try:
                    key, name = lastfm.get_session(token)
                except lastfm.LastfmError as e:
                    if e.code == 14:
                        time.sleep(3)
                        continue
                    raise
                lastfm.save(session_key=key, username=name)
                self._sigError.emit("")
                return
            self._sigError.emit("timed out waiting for the approval")
        finally:
            self._connecting = False

    @Slot()
    def disconnectAccount(self):
        lastfm.forget_session()
        self._set_error("")
        self._refresh()

    @Slot()
    def retryQueue(self):
        if self._st.get("connected"):
            self._post(self._flush)
