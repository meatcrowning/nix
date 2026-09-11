"""Release information coordinator: worker-only I/O, reusable entities, edits.

The Qt thread only submits commands and receives generation-checked results.
Network calls never run inside a SQLite write transaction. Local corrections
are independent of cached downloads, with tombstones for cross-host reverts.
"""
from collections import deque
from contextlib import contextmanager
import hashlib
import json
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
import urllib.error

from PySide6.QtCore import QCoreApplication, QObject, Signal, Slot

import perftrace
import infostore as store
from releaseinfo import ReleaseInfo
from albumprose import (lastfm_description, lastfm_artist_description,
                        bandcamp_description)
import artistinfo
from relatedmusic import related_tracks
related_tracks = perftrace.timed("albuminfo.related_tracks")(related_tracks)
import trackmatch
import lastfm


class Superseded(Exception):
    pass


class AlbumInformation(QObject):
    changed = Signal("QVariantMap")
    _resultReady = Signal(int, object)
    CACHE_AGE = 30 * 86400
    RETRY_AGE = 300
    NO_MATCH_AGE = 86400
    USER_AGENT = "player/2.0 (+https://github.com/meatcrowning/nix)"
    # A compilation's credit is not a person, and a biography fetched for one
    # would be filed against every unrelated album sharing the tag.
    NOT_A_PERSON = {"various artists", "various", "va", "unknown", "unknown artist",
                    "no artist", "soundtrack", "compilation"}

    def __init__(self, library, parent=None, *, db_path, read_tags=None,
                 fetch_json=None, lastfm_call=None):
        super().__init__(parent)
        self._db_path = str(db_path)
        self._read_tags = read_tags
        self._fetch_json_fn = fetch_json
        self._lastfm_call = lastfm_call or lastfm.call
        self._state = self._empty()
        self._cv = threading.Condition()
        self._closed = False
        self._command_lock = threading.Lock()
        self._pending_command = None
        self._jobs = deque()
        self._generation = 0
        self._active_generation = None
        self._last_mb_request = 0.0
        self._force_fetch = False
        self._index_generation = 0
        self._indexed_generation = -1
        self._tracks = []
        self._album_rows = {}
        self._resultReady.connect(self._deliver)
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.close)
        if library is not None:
            library.changed.connect(self.invalidate_library)
        self._worker = threading.Thread(target=self._loop, daemon=True,
                                        name="player-album-info")
        self._worker.start()

    @staticmethod
    def _empty(status="idle", track_id=0):
        return {"trackId": int(track_id), "status": status, "error": "",
                "albumError": "", "similarError": "", "album": {},
                "similar": [], "discoveries": [], "candidates": [], "match": {},
                "fetchedAt": 0.0, "stale": False, "similarFallback": True,
                "connection": "", "connectionEmpty": False, "recordingId": ""}

    @property
    def state(self):
        return dict(self._state)

    @Slot()
    def invalidate_library(self):
        self._index_generation += 1

    @Slot(int, object)
    @perftrace.timed("albuminfo._deliver")
    def _deliver(self, generation, state):
        if generation == self._generation:
            self._state = dict(state)
            self.changed.emit(self.state)

    def _submit(self, tid, command="request", payload=None):
        if self._closed:
            return False
        tid = int(tid or 0)
        self._generation += 1
        generation = self._generation
        if tid <= 0:
            self._deliver(generation, self._empty())
            return False
        state = self.state if self._state["trackId"] == tid else self._empty(track_id=tid)
        if command == "clear":
            state = self._empty(track_id=tid)
        state.update(status="loading", error="", albumError="", similarError="",
                     connection="", connectionEmpty=False)
        self._deliver(generation, state)
        with self._cv:
            # Keep explicit corrections, discard obsolete browsing requests.
            self._jobs = deque(j for j in self._jobs if j[2] != "request")
            self._jobs.append((generation, tid, command, payload))
            self._cv.notify()
        return True

    def request(self, track_id, force=False):
        return self._submit(track_id, payload=bool(force))

    def refresh(self, track_id):
        return self.request(track_id, True)

    def clear(self, track_id):
        return self._submit(track_id, "clear")

    def choose(self, track_id, entity_id):
        if self._state.get("trackId") != int(track_id) or not any(
                c.get("id") == entity_id for c in self._state.get("candidates", [])):
            return False
        return self._submit(track_id, "choose", str(entity_id))

    def edit(self, track_id, kind, values):
        if kind != "album" or not isinstance(values, dict):
            return False
        allowed = {k: str(v) for k, v in values.items()
                   if k in ("title", "artist", "description")}
        return self._submit(track_id, "edit", allowed)

    def revert(self, track_id, kind):
        if kind not in ("album", "match"):
            return False
        return self._submit(track_id, "revert", kind)

    def browse_connection(self, track_id, kind, entity_id, name):
        if kind not in ("artist", "label") or not entity_id:
            return False
        return self._submit(track_id, "connection", (kind, entity_id, name))

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self._db_path, timeout=5)
        con.row_factory = sqlite3.Row
        try:
            yield con
        finally:
            con.close()

    def _check_current(self):
        if self._active_generation is not None and self._active_generation != self._generation:
            raise Superseded()

    def _network_wait(self, delay):
        deadline = time.monotonic() + delay
        with self._cv:
            while True:
                self._check_current()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                self._cv.wait(remaining)

    def _publish(self, state):
        if self._active_generation is not None:
            self._resultReady.emit(self._active_generation, dict(state))

    def _loop(self):
        while True:
            with self._cv:
                while not self._jobs and not self._closed:
                    self._cv.wait()
                if self._closed:
                    return
                generation, tid, command, payload = self._jobs.popleft()
                mutating = command not in ("request", "connection")
                if mutating:
                    self._pending_command = (tid, command, payload)
            command_error = None
            if mutating:
                with self._command_lock:
                    if not self._closed:
                        try:
                            self._apply_command(tid, command, payload)
                        except Exception as exc:
                            command_error = exc
                    with self._cv:
                        self._pending_command = None
            self._active_generation = generation
            try:
                if command_error is not None:
                    raise command_error
                self._check_current()
                if command == "clear":
                    state = self._cached_state(tid) or self._empty(track_id=tid)
                elif command == "connection":
                    state = self._connection(tid, *payload)
                else:
                    state = self._resolve(tid, bool(payload) if command == "request"
                                          else command in ("choose", "revert"))
                self._publish(state)
            except Superseded:
                pass
            except Exception as exc:
                try:
                    state = self._cached_state(tid) or self._empty("error", tid)
                except Exception:
                    state = self._empty("error", tid)
                state.update(status="error", error=str(exc), albumError=str(exc))
                self._publish(state)
            finally:
                self._active_generation = None

    @Slot()
    def close(self):
        # Do not wait on the network worker when the window closes. Preserve
        # already accepted corrections before Python discards daemon threads.
        with self._command_lock:
            with self._cv:
                if self._closed:
                    return
                self._closed = True
                self._generation += 1
                pending = [self._pending_command] if self._pending_command else []
                pending.extend((tid, command, payload) for _, tid, command, payload in self._jobs
                               if command not in ("request", "connection"))
                self._pending_command = None
                self._jobs.clear()
                self._cv.notify_all()
            for tid, command, payload in pending:
                try:
                    self._apply_command(tid, command, payload)
                except Exception as exc:
                    print(f"album information: pending {command} failed: {exc}", flush=True)

    @staticmethod
    def _cache_key(row):
        # Legacy cache lookup only; new releases share entity-keyed downloads.
        return "|".join(trackmatch.fold(x) for x in
                        (row["album_artist"] or row["artist"] or "", row["album"] or "",
                         row["artist"] or "", row["title"] or ""))

    def _legacy(self, con, row, scope):
        # Preserve existing corrections without promoting old guessed releases.
        oldkey = self._cache_key(row)
        for old in con.execute("SELECT * FROM web_metadata_overrides WHERE cache_key=?",
                               (oldkey,)):
            exists = con.execute("SELECT updated_at FROM music_info_user WHERE scope_key=? AND kind=?",
                                 (scope, old["kind"])).fetchone()
            if not exists or (old["edited_at"] or 0) > exists[0]:
                con.execute("INSERT OR REPLACE INTO music_info_user VALUES (?,?,?,?,0)",
                            (scope, old["kind"], old["body_json"], old["edited_at"]))
        old = con.execute("SELECT * FROM web_entity_matches WHERE cache_key=? AND manual=1",
                          (oldkey,)).fetchone()
        exists = con.execute("SELECT 1 FROM music_info_user WHERE scope_key=? AND kind='legacy_match'",
                             ("track:" + row["path"],)).fetchone()
        if old and not exists:
            body = {"recordingId": old["entity_id"], "label": old["label"],
                    "candidates": store.decode(old["candidates_json"], [])}
            con.execute("INSERT INTO music_info_user VALUES (?,'legacy_match',?,?,0)",
                        ("track:" + row["path"], json.dumps(body), old["fetched_at"] or time.time()))
        con.commit()

    def _apply_command(self, tid, command, payload):
        with self._connect() as con:
            row = con.execute("SELECT * FROM tracks WHERE id=?", (tid,)).fetchone()
            if row is None:
                raise ValueError("track no longer in library")
            scope = store.scope_key(dict(row))
            if command == "choose":
                cached = store.cache_get(con, scope, "resolution")
                candidate = next((c for c in (cached or {}).get("body", {}).get("candidates", [])
                                  if c.get("id") == payload), None)
                if not candidate:
                    raise ValueError("release choice no longer available")
                store.user_put(con, scope, "match", candidate)
            elif command == "edit":
                store.user_put(con, scope, "album", payload)
            elif command == "revert":
                store.user_put(con, scope, payload)
                if payload == "match":
                    store.user_put(con, "track:" + row["path"], "legacy_match")
            elif command == "clear":
                link = con.execute("SELECT release_id FROM music_info_links WHERE scope_key=?",
                                   (scope,)).fetchone()
                con.execute("DELETE FROM music_info_cache WHERE cache_key=?", (scope,))
                related_key = "track:" + hashlib.sha256(row["path"].encode()).hexdigest()
                con.execute("DELETE FROM music_info_cache WHERE cache_key=?", (related_key,))
                artist_key = self._artist_key(self._artist_name(row))
                if artist_key:
                    match = store.cache_get(con, artist_key, "artist-match")
                    artist_id = (match or {}).get("body", {}).get("id", "")
                    con.execute("DELETE FROM music_info_cache WHERE cache_key=?", (artist_key,))
                    if artist_id:
                        con.execute("DELETE FROM music_info_cache WHERE cache_key=?",
                                    ("artist:" + artist_id,))
                if link:
                    con.execute("DELETE FROM music_info_cache WHERE cache_key=?",
                                ("release:" + link[0],))
                con.commit()

    def _cached_state(self, tid):
        with self._connect() as con:
            got = con.execute("SELECT * FROM tracks WHERE id=?", (tid,)).fetchone()
            if got is None:
                return None
            row = dict(got)
            scope = store.scope_key(row)
            state = self._empty(track_id=tid)
            if self._state.get("trackId") == tid:
                for key in ("similar", "discoveries", "similarFallback"):
                    state[key] = self._state.get(key, state[key])
            resolution = store.cache_get(con, scope, "resolution")
            state["album"] = {"title": row["album"] or "", "artist": row["album_artist"] or row["artist"] or ""}
            state["album"].update(store.effective_album(con, scope))
            state["recordingId"] = store.identity(row).get("recordingId", "")
            if not state["recordingId"]:
                for item in state["album"].get("tracks", []):
                    if (item.get("disc") == (row.get("disc") or 1)
                            and item.get("position") == row.get("track")
                            and trackmatch.fold(item.get("title") or "") == trackmatch.fold(row.get("title") or "")):
                        state["recordingId"] = item.get("recordingId", "")
                        break
            if resolution:
                body = resolution["body"]
                state.update(status=body.get("status", "ready"),
                             candidates=body.get("candidates", []),
                             match=body.get("match", {}), fetchedAt=resolution["fetched_at"],
                             stale=resolution["stale"] or bool(resolution["error"]), albumError=resolution["error"],
                             error=resolution["error"])
            artist = self._cached_artist(con, self._artist_name(row))
            if artist:
                state["album"]["artistInfo"] = artist
            manual = store.user_get(con, scope, "match")
            if manual:
                state["match"] = {**manual, "manual": True}
            return state

    @staticmethod
    def _artist_name(row):
        """The album's credited artist as tagged — the key stays the same
        whether or not the release itself could be identified."""
        return str((row["album_artist"] or row["artist"] or "")).strip()

    @classmethod
    def _artist_key(cls, name):
        folded = trackmatch.fold(name)
        if not folded or folded in cls.NOT_A_PERSON:
            return ""
        return "artist-name:" + hashlib.sha256(folded.encode()).hexdigest()

    @staticmethod
    def _cached_artist(con, name):
        """Facts for a name from the shared artist entity, or an empty mapping.
        Every album by one artist reads the same download."""
        key = AlbumInformation._artist_key(name)
        match = store.cache_get(con, key, "artist-match") if key else None
        artist_id = (match or {}).get("body", {}).get("id", "")
        entity = store.cache_get(con, "artist:" + artist_id, "artist") if artist_id else None
        return dict(entity["body"]) if entity and entity["body"] else {}

    @perftrace.timed("albuminfo._fetch_json")
    def _fetch_json(self, url):
        self._check_current()
        key = "url:" + hashlib.sha256(url.encode()).hexdigest()
        search = "query" in urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        ttl = self.NO_MATCH_AGE if search else self.CACHE_AGE
        with self._connect() as con:
            cached = store.cache_get(con, key, "http")
        if (cached and not cached["stale"] and not self._force_fetch
                and time.time() - cached["fetched_at"] < ttl):
            return cached["body"]
        if self._fetch_json_fn:
            result = self._fetch_json_fn(url)
        else:
            request = urllib.request.Request(url, headers={"User-Agent": self.USER_AGENT,
                                                           "Accept": "application/json"})
            for attempt in range(2):
                if urllib.parse.urlsplit(url).hostname == "musicbrainz.org":
                    delay = 1.05 - (time.monotonic() - self._last_mb_request)
                    if delay > 0:
                        self._network_wait(delay)
                    self._check_current()
                    self._last_mb_request = time.monotonic()
                try:
                    with urllib.request.urlopen(request, timeout=15) as response:
                        result = json.loads(response.read(4 * 1024 * 1024))
                    break
                except urllib.error.HTTPError as exc:
                    if attempt or exc.code not in (502, 503, 504):
                        raise
                    # One bounded retry for temporary service failures. Keep
                    # cancellation responsive and respect server backoff.
                    try:
                        delay = max(1.05, float(exc.headers.get("Retry-After", "1.05")))
                    except (ValueError, TypeError):
                        raise exc
                    if delay > 5:
                        raise
                    self._network_wait(delay)
                    self._check_current()
        self._check_current()
        with self._connect() as con:
            store.cache_put(con, key, "http", result, ttl)
        return result

    @perftrace.timed("albuminfo._load_identity")
    def _load_identity(self, con, row):
        if store.identity(row).get("scanned") or self._read_tags is None:
            return row
        tags = self._read_tags(row["path"])
        if tags is not None:
            ids = store.decode(tags.get("identity_json"), {})
            ids["scanned"] = True
            row["identity_json"] = json.dumps(ids)
            con.execute("UPDATE tracks SET identity_json=? WHERE id=? AND path=?",
                        (row["identity_json"], row["id"], row["path"]))
            con.commit()
            self._index_generation += 1
        return row

    @perftrace.timed("albuminfo._library_tracks")
    def _library_tracks(self, con):
        if self._indexed_generation != self._index_generation:
            self._tracks = [dict(r) for r in con.execute("SELECT * FROM tracks")]
            self._album_rows = {}
            for row in self._tracks:
                row["_info_scope"] = store.scope_key(row)
                self._album_rows.setdefault(row["_info_scope"], []).append(row)
            self._indexed_generation = self._index_generation
        return self._tracks

    def _related_rows(self, con, tracks):
        links = {r["scope_key"]: r for r in con.execute("SELECT * FROM music_info_links")}
        result = []
        for row in tracks:
            link = links.get(row.get("_info_scope") or store.scope_key(row))
            if link:
                ids = dict(store.identity(row))
                ids.update(releaseId=link["release_id"], releaseGroupId=link["release_group_id"])
                row = {**row, "identity_json": ids}
            result.append(row)
        return result

    def _known_albums(self, con):
        return [store.decode(r[0], {}) for r in con.execute(
            "SELECT body_json FROM music_info_cache WHERE kind='album'")]

    @perftrace.timed("albuminfo._resolve")
    def _resolve(self, tid, force=False):
        self._force_fetch = force
        # Show saved facts before tag reads (possibly over SMB), library
        # indexing, or unrelated Last.fm requests can delay this album.
        state = self._cached_state(tid)
        if state is not None:
            self._publish(state)
        with self._connect() as con:
            got = con.execute("SELECT * FROM tracks WHERE id=?", (tid,)).fetchone()
            if got is None:
                return self._empty("error", tid) | {"error": "track not found"}
            row = dict(got)
            scope = store.scope_key(row)
            self._legacy(con, row, scope)
            row = self._load_identity(con, row)
            tracks = self._library_tracks(con)
            album_tracks = self._album_rows.get(scope, [])
            album_tracks = [row if t["id"] == tid else t for t in album_tracks]
            cached = store.cache_get(con, scope, "resolution")
            manual = store.user_get(con, scope, "match")
            legacy = store.user_get(con, "track:" + row["path"], "legacy_match")
        state = self._cached_state(tid)
        self._publish(state)
        missing_entity = cached and cached["body"].get("status") == "ready" and not state["album"].get("musicbrainzReleaseId")
        if force or cached is None or cached["stale"] or missing_entity:
            self._publish({**state, "status": "loading"})
            self._check_current()
            try:
                if legacy and not manual:
                    ids = store.identity(row)
                    ids.setdefault("recordingId", legacy.get("recordingId", ""))
                    row["identity_json"] = json.dumps(ids)
                    album_tracks = [row if t["id"] == tid else t for t in album_tracks]
                result = ReleaseInfo(self._fetch_json).resolve(row, album_tracks, manual.get("id", ""))
                self._check_current()
                album = result.get("album") or {}
                rid = album.get("musicbrainzReleaseId", "")
                status = result.get("status", "no_match")
                partial_error = album.get("error", "")
                ttl = self.RETRY_AGE if partial_error else (self.CACHE_AGE if status == "ready" else self.NO_MATCH_AGE)
                match = {"id": rid, "label": album.get("title", ""), "manual": bool(manual)}
                resolution = {"status": status, "candidates": result.get("candidates", []),
                              "match": match, "recordingId": result.get("recordingId", "")}
                with self._connect() as con:
                    if rid:
                        previous = store.cache_get(con, "release:" + rid, "album")
                        if previous and previous["body"].get("description"):
                            for field in ("description", "descriptionSource", "descriptionUrl"):
                                album[field] = previous["body"].get(field, "")
                            album["sources"] = list(dict.fromkeys([
                                *album.get("sources", []), album["descriptionSource"]]))
                        store.cache_put(con, "release:" + rid, "album", album, ttl, error=partial_error)
                        con.execute("INSERT OR REPLACE INTO music_info_links VALUES (?,?,?,?)",
                                    (scope, rid, album.get("musicbrainzReleaseGroupId", ""), time.time()))
                        con.commit()
                    store.cache_put(con, scope, "resolution", resolution,
                                    ttl, error=partial_error)
            except Superseded:
                raise
            except Exception as exc:
                with self._connect() as con:
                    store.cache_put(con, scope, "resolution", {"status": "error"},
                                    self.RETRY_AGE, error=str(exc), preserve=True)
            state = self._cached_state(tid)
            self._publish(state)
        # The artist is not the release. A bootleg, a rip, a private edition or
        # a MusicBrainz outage can leave the album unidentified while the person
        # who made it is perfectly well known, so this stage never depends on
        # the resolution above and publishes on its own.
        self._check_current()
        state = self._artist_stage(row, state)
        # Similarity is independent of MusicBrainz success and never shares its
        # error label. Re-rank against the local library on every visit.
        self._check_current()
        related_key = "track:" + hashlib.sha256(row["path"].encode()).hexdigest()
        with self._connect() as con:
            remote = store.cache_get(con, related_key, "similar")
        if force or remote is None or remote["stale"]:
            try:
                answer = self._lastfm_call("track.getSimilar", {
                    "artist": row["artist"], "track": row["title"], "limit": 100})
                self._check_current()
                items = ((answer or {}).get("similartracks") or {}).get("track") or []
                if isinstance(items, dict):
                    items = [items]
                with self._connect() as con:
                    store.cache_put(con, related_key, "similar", {"items": items}, 7 * 86400)
            except Superseded:
                raise
            except Exception as exc:
                with self._connect() as con:
                    store.cache_put(con, related_key, "similar", {"items": []},
                                    self.RETRY_AGE, error=str(exc), preserve=True)
            with self._connect() as con:
                remote = store.cache_get(con, related_key, "similar")
        self._check_current()
        with self._connect() as con:
            rank_tracks = self._related_rows(con, tracks)
            rank_row = next((r for r in rank_tracks if r["id"] == tid), row)
            related = related_tracks(rank_row, rank_tracks, remote["body"].get("items", []),
                                     state["album"], self._known_albums(con))
        state.update(similar=related["owned"], discoveries=related["discoveries"],
                     similarError=remote["error"], similarFallback=not remote["body"].get("items"))
        self._publish(state)
        # Prose is optional and runs only after details and recommendations are
        # already delivered. A missing article does not invalidate either.
        album = state["album"]
        if (force or not album.get("description")) and album.get("musicbrainzReleaseId"):
            try:
                with self._connect() as con:
                    raw = store.cache_get(con, "release:" + album["musicbrainzReleaseId"], "album")
                    # Version the lookup policy: old empty Wikipedia-only
                    # results must not suppress the new fallbacks for a month.
                    prose_attempt = store.cache_get(con, "release:" + album["musicbrainzReleaseId"], "prose-v2")
                album = dict(raw["body"]) if raw else album
                if prose_attempt and not prose_attempt["stale"] and not force:
                    return state
                try:
                    summary = self._album_prose(album)
                except Superseded:
                    raise
                except Exception as exc:
                    with self._connect() as con:
                        store.cache_put(con, "release:" + album["musicbrainzReleaseId"],
                                        "prose-v2", {}, self.RETRY_AGE, error=str(exc))
                    return state
                with self._connect() as con:
                    store.cache_put(con, "release:" + album["musicbrainzReleaseId"],
                                    "prose-v2", summary, self.CACHE_AGE if summary else self.NO_MATCH_AGE)
                if summary:
                    album = {**album, **summary}
                    album["sources"] = list(dict.fromkeys([*album.get("sources", []), summary["descriptionSource"]]))
                    with self._connect() as con:
                        store.cache_put(con, "release:" + album["musicbrainzReleaseId"],
                                        "album", album, max(0, raw["expires_at"] - time.time()) if raw else self.CACHE_AGE,
                                        error=raw["error"] if raw else "")
                        merged = store.effective_album(con, scope)
                        # Keep the artist facts this run already published:
                        # they are not part of the release's cache entry.
                        if state["album"].get("artistInfo"):
                            merged["artistInfo"] = state["album"]["artistInfo"]
                        state["album"] = merged
            except Superseded:
                raise
            except Exception:
                pass
        return state

    @perftrace.timed("albuminfo._artist_stage")
    def _artist_stage(self, row, state):
        name = self._artist_name(row)
        key = self._artist_key(name)
        if not key:
            return state
        with self._connect() as con:
            match = store.cache_get(con, key, "artist-match")
        if self._force_fetch or match is None or match["stale"]:
            identity = store.identity(row)
            # Tagged IDs first: they name the exact person even when two
            # artists share a name, and cost no search.
            ids = [*(identity.get("albumArtistIds") or []),
                   *(state["album"].get("artistIds") or []),
                   *(identity.get("artistIds") or [])]
            try:
                facts = artistinfo.ArtistInfo(self._fetch_json).resolve(name, ids)
                self._check_current()
                with self._connect() as con:
                    if facts.get("id"):
                        store.cache_put(con, "artist:" + facts["id"], "artist", facts, self.CACHE_AGE)
                    store.cache_put(con, key, "artist-match", {"id": facts.get("id", "")},
                                    self.CACHE_AGE if facts.get("id") else self.NO_MATCH_AGE)
            except Superseded:
                raise
            except Exception as exc:
                with self._connect() as con:
                    store.cache_put(con, key, "artist-match", {}, self.RETRY_AGE,
                                    error=str(exc), preserve=True)
        with self._connect() as con:
            artist = self._cached_artist(con, name)
        if not artist.get("id"):
            return state
        state["album"] = {**state["album"], "artistInfo": artist}
        self._publish(state)
        # The biography is optional and separately cached, exactly like the
        # album write-up: a linked Wikipedia article first, Last.fm second.
        with self._connect() as con:
            attempt = store.cache_get(con, "artist:" + artist["id"], "artist-prose")
        if attempt and not attempt["stale"] and not self._force_fetch:
            return state
        try:
            summary = self._artist_prose(artist)
        except Superseded:
            raise
        except Exception as exc:
            with self._connect() as con:
                store.cache_put(con, "artist:" + artist["id"], "artist-prose", {},
                                self.RETRY_AGE, error=str(exc))
            return state
        with self._connect() as con:
            store.cache_put(con, "artist:" + artist["id"], "artist-prose", summary,
                            self.CACHE_AGE if summary else self.NO_MATCH_AGE)
            if summary:
                artist = {**artist, **summary}
                artist["sources"] = list(dict.fromkeys([*artist.get("sources", []),
                                                        summary["descriptionSource"]]))
                store.cache_put(con, "artist:" + artist["id"], "artist", artist, self.CACHE_AGE)
                state["album"] = {**state["album"], "artistInfo": artist}
        return state

    def _artist_prose(self, artist):
        errors = []
        try:
            summary = self._prose(artist.get("links", []))
            if summary:
                return summary
        except Superseded:
            raise
        except Exception as exc:
            errors.append(exc)
        self._check_current()
        try:
            answer = self._lastfm_call("artist.getInfo", {
                "artist": artist.get("name", ""), "autocorrect": 0, "lang": "en"})
            self._check_current()
            summary = lastfm_artist_description(answer, artist.get("name", ""))
            if summary:
                return summary
        except Superseded:
            raise
        except Exception as exc:
            errors.append(exc)
        if errors:
            raise errors[0]
        return {}

    def _album_prose(self, album):
        errors = []
        try:
            summary = self._prose(album.get("links", []))
            if summary:
                return summary
        except Superseded:
            raise
        except Exception as exc:
            errors.append(exc)
        self._check_current()
        try:
            answer = self._lastfm_call("album.getInfo", {
                "artist": album.get("artist", ""), "album": album.get("title", ""),
                "autocorrect": 0, "lang": "en"})
            self._check_current()
            summary = lastfm_description(answer, album)
            if summary:
                return summary
        except Superseded:
            raise
        except Exception as exc:
            errors.append(exc)
        # Only album pages explicitly linked by the resolved MusicBrainz
        # entity; never guess a Bandcamp subdomain or scrape search results.
        urls = list(dict.fromkeys(link.get("url", "") for link in album.get("links", [])))
        for url in [u for u in urls if urllib.parse.urlsplit(u).scheme == "https"
                    and (urllib.parse.urlsplit(u).hostname or "").endswith(".bandcamp.com")
                    and urllib.parse.urlsplit(u).path.startswith("/album/")][:2]:
            self._check_current()
            try:
                summary = bandcamp_description(self._fetch_page(url), album, url)
                if summary:
                    return summary
            except Superseded:
                raise
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise errors[0]
        return {}

    def _fetch_page(self, url):
        key = "page:" + hashlib.sha256(url.encode()).hexdigest()
        with self._connect() as con:
            cached = store.cache_get(con, key, "http")
        if cached and not cached["stale"] and not self._force_fetch:
            return cached["body"].get("text", "")
        self._check_current()
        request = urllib.request.Request(url, headers={"User-Agent": self.USER_AGENT})
        with urllib.request.urlopen(request, timeout=8) as response:
            page = response.read(2 * 1024 * 1024 + 1)
            if len(page) > 2 * 1024 * 1024:
                raise ValueError("album page too large")
            page = page.decode("utf-8", "replace")
        self._check_current()
        with self._connect() as con:
            store.cache_put(con, key, "http", {"text": page}, self.NO_MATCH_AGE)
        return page

    def _prose(self, links):
        errors, seen = [], set()
        # A direct article link saves the Wikidata round trip. One broken
        # relationship must not hide another usable article on the album.
        for link in sorted(links, key=lambda item: item.get("type") != "wikipedia"):
            key = (link.get("type"), link.get("url"))
            if key in seen:
                continue
            seen.add(key)
            try:
                summary = self._wiki_prose(link)
                if summary:
                    return summary
            except Superseded:
                raise
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise errors[0]
        return {}

    def _wiki_prose(self, link):
        kind, url = link.get("type"), link.get("url", "")
        if kind == "wikidata":
            qid = url.rstrip("/").split("/")[-1]
            entity = self._fetch_json(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")
            title = entity.get("entities", {}).get(qid, {}).get("sitelinks", {}).get("enwiki", {}).get("title")
        elif kind == "wikipedia" and urllib.parse.urlsplit(url).hostname == "en.wikipedia.org":
            title = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])
        else:
            return {}
        if not title:
            return {}
        page = self._fetch_json("https://en.wikipedia.org/api/rest_v1/page/summary/" +
                                urllib.parse.quote(title, safe=""))
        if page.get("extract") and page.get("type") != "disambiguation":
            return {"description": page["extract"], "descriptionSource": "wikipedia",
                    "descriptionUrl": page.get("content_urls", {}).get("desktop", {}).get("page", "")}
        return {}

    def _connection(self, tid, kind, entity_id, name):
        state = self._cached_state(tid) or self._empty(track_id=tid)
        with self._connect() as con:
            albums = self._known_albums(con)
            tracks = self._related_rows(con, self._library_tracks(con))
        matches = {}
        for album in albums:
            entries = album.get("labels", []) if kind == "label" else album.get("credits", [])
            entries = [e for e in entries if e.get("id") == entity_id]
            if entries and album.get("musicbrainzReleaseId"):
                matches[album["musicbrainzReleaseId"]] = entries
        selected = []
        for row in tracks:
            # Group identity alone cannot establish an edition's credits.
            for credit in matches.get(store.identity(row).get("releaseId"), []):
                active = kind == "label" or credit.get("scope") == "album"
                if kind != "label" and credit.get("scope") == "track":
                    active = False
                    wanted_title = str(credit.get("trackTitle") or "").strip()
                    wanted_pos = credit.get("trackPosition")
                    wanted_disc = credit.get("disc")
                    if wanted_title or wanted_pos:
                        active = True
                        for expected, actual in ((wanted_disc, row.get("disc")),
                                                 (wanted_pos, row.get("track"))):
                            if expected not in (None, ""):
                                try:
                                    active = active and int(str(expected).split("/", 1)[0]) == int(actual or 0)
                                except (TypeError, ValueError):
                                    active = False
                        if wanted_title:
                            active = active and trackmatch.fold(wanted_title) == trackmatch.fold(row.get("title") or "")
                if active:
                    selected.append({"trackId": row["id"], "title": row["title"] or "",
                                     "artist": row["artist"] or "", "album": row["album"] or "",
                                     "reason": name, "owned": True, "score": 1})
                    break
            if len(selected) >= 60:
                break
        state.update(similar=selected, discoveries=[], connection=name,
                     status="ready", similarError="", similarFallback=True,
                     connectionEmpty=not selected)
        return state
