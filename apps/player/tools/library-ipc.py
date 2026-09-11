#!/usr/bin/env python3
"""player's library and queue, for a program that is not player.

chatter's agents can already drive PLAYBACK over MPRIS (play, pause, skip,
seek, volume) but had no way to answer "what have I got" or "put that album
on": MPRIS carries the current track and nothing else, and `OpenUri` is a no-op
in this app's adapter [his, 2026-08-23]. This is that half — the library READ
(sqlite, read-only) and the two queue verbs (over the same
`player-queue.sock` a second launch hands its files to).

Same protocol as oracle's other executors: one JSON request object on stdin,
one JSON result object on stdout, an error is `{"error": …}` with exit 0.

    {"op": "search", "q": "boards of canada", "limit": 20}
    {"op": "albums", "artist": "aphex"}
    {"op": "play",  "paths": ["/run/media/lam/SSD/aud/…/01 x.flac"]}
    {"op": "queue", "paths": [...]}
    {"op": "stats"}

READ-ONLY on the database, always: the library is written by player (and by
`atomicsave.py` for the files themselves), and a second writer is how a library
loses ratings. Nothing here writes a tag, a rating or a play count.

Pure stdlib, because this runs on whichever host the library is on — reached
over ssh from a book window exactly like sandbox-fs.py.
"""
import json
import os
import socket
import sqlite3
import sys
import urllib.parse
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pylib"))
import trackmatch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import infostore
import artistalias

DB = os.path.expanduser(
    os.environ.get("PLAYER_DB", "~/.local/share/player/library.db"))
SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp",
                    "player-queue.sock")

#: A tool result is model context: cap the rows hard, and let the caller page
#: with `offset` rather than ask for a thousand.
MAX_ROWS = 60
DEFAULT_ROWS = 20

#: What one track row says. `path` is the important one — it is what `play` and
#: `queue` take back — and the rest is what a person would ask about.
TRACK_COLS = ("id", "title", "artist", "album", "album_artist", "track", "year",
              "duration", "rating", "favorite", "play_count", "path")

SORTS = {
    "artist": "artist COLLATE NOCASE, album COLLATE NOCASE, disc, track",
    "album": "album COLLATE NOCASE, disc, track",
    "title": "title COLLATE NOCASE",
    "rating": "rating DESC, play_count DESC",
    "plays": "play_count DESC, rating DESC",
    "recent": "COALESCE(added_at, 0) DESC",
    "played": "COALESCE(last_played, 0) DESC",
    "random": "RANDOM()",
}


def fail(reason):
    print(json.dumps({"error": reason}))
    sys.exit(0)


def db():
    if not os.path.exists(DB):
        fail("no library database at " + DB + " — has player ever run here?")
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=10)
    except sqlite3.Error as e:
        fail("cannot open the library: " + str(e))
    con.row_factory = sqlite3.Row
    return con


def alias_others(name):
    """The OTHER names of whoever `name` is, from the player's identity groups
    (`artistalias`) — so asking for Chuck Person here returns the Oneohtrix
    Point Never records too, exactly as the app's own search does. Read-only,
    and an empty list whenever nothing has been grouped.

    Like the app, these widen the ARTIST columns and never the title: an alias
    as ordinary as "Games" would otherwise answer a search for the person with
    every record that has a track called Games on it."""
    name = str(name or "").strip()
    if not name:
        return []
    try:
        return artistalias.load(db()).others(name)
    except sqlite3.Error:
        return []


def artist_or(names, cols=("artist", "album_artist")):
    """(sql, args) matching any of `names` in any of `cols`, or ("", [])."""
    if not names:
        return "", []
    parts, args = [], []
    for n in names:
        for col in cols:
            parts.append("%s LIKE ? ESCAPE '\\'" % col)
            args.append("%" + n.replace("%", r"\%") + "%")
    return " OR ".join(parts), args


def rows_of(cur, cols=TRACK_COLS):
    out = []
    for r in cur.fetchall():
        row = {}
        for c in cols:
            try:
                row[c] = r[c]
            except (IndexError, KeyError):
                continue
        out.append(row)
    return out


def limit_of(req):
    try:
        n = int(req.get("limit") or DEFAULT_ROWS)
    except (TypeError, ValueError):
        n = DEFAULT_ROWS
    return max(1, min(n, MAX_ROWS))


def op_search(req):
    """Tracks matching a free-text query and/or an artist/album filter.

    The query is matched against title, artist, album and album artist at once,
    because that is how a person names music: "put on some boards of canada" and
    "play tomorrow's harvest" are the same kind of ask."""
    where, args = [], []
    q = str(req.get("q") or "").strip()
    if q:
        like = "%" + q.replace("%", r"\%") + "%"
        clause = ("title LIKE ? ESCAPE '\\' OR artist LIKE ? ESCAPE '\\' "
                  "OR album LIKE ? ESCAPE '\\' OR album_artist LIKE ? ESCAPE '\\'")
        alias_sql, alias_args = artist_or(alias_others(q))
        if alias_sql:
            clause += " OR " + alias_sql
        where.append("(" + clause + ")")
        args += [like] * 4 + alias_args
    for field in ("artist", "album", "genre"):
        val = str(req.get(field) or "").strip()
        if val:
            clause = "%s LIKE ? ESCAPE '\\'" % field
            args.append("%" + val + "%")
            if field == "artist":
                clause += " OR album_artist LIKE ? ESCAPE '\\'"
                args.append("%" + val + "%")
                alias_sql, alias_args = artist_or(alias_others(val))
                if alias_sql:
                    clause += " OR " + alias_sql
                    args += alias_args
            where.append("(" + clause + ")")
    if req.get("favorites_only"):
        where.append("favorite = 1")
    try:
        floor = int(req.get("min_rating") or 0)
    except (TypeError, ValueError):
        floor = 0
    if floor:
        where.append("rating >= ?")
        args.append(floor)
    sort = SORTS.get(str(req.get("sort") or "artist").lower(), SORTS["artist"])
    n = limit_of(req)
    try:
        offset = max(0, int(req.get("offset") or 0))
    except (TypeError, ValueError):
        offset = 0
    sql = ("SELECT %s FROM tracks%s ORDER BY %s LIMIT ? OFFSET ?"
           % (", ".join(TRACK_COLS),
              (" WHERE " + " AND ".join(where)) if where else "", sort))
    con = db()
    cur = con.execute(sql, args + [n, offset])
    tracks = rows_of(cur)
    total = con.execute("SELECT COUNT(*) FROM tracks%s"
                        % ((" WHERE " + " AND ".join(where)) if where else ""),
                        args).fetchone()[0]
    return {"ok": True, "count": len(tracks), "total": total,
            "offset": offset, "tracks": tracks}


def op_albums(req):
    """Albums, with their track count and total time — the shape of the library
    at the level people actually pick music. An artist match on any contained
    track includes its whole release: album_artist is not a complete contributor
    list."""
    where, args = [], []
    q = str(req.get("q") or "").strip()
    if q:
        like = "%" + q + "%"
        where.append("(album LIKE ? OR album_artist LIKE ? OR artist LIKE ?)")
        args += [like] * 3
    artist = str(req.get("artist") or "").strip()
    if artist:
        clause = "album_artist LIKE ? OR artist LIKE ?"
        args += ["%" + artist + "%"] * 2
        alias_sql, alias_args = artist_or(alias_others(artist))
        if alias_sql:
            clause += " OR " + alias_sql
            args += alias_args
        where.append("(" + clause + ")")
    n = limit_of(req)
    # Select candidate albums first, then aggregate every track in each one.
    # Filtering the aggregate itself reports only a guest's matching tracks.
    sql = ("WITH matched AS ("
           " SELECT DISTINCT album, COALESCE(NULLIF(album_artist,''), artist) AS group_artist"
           " FROM tracks%s"
           ") "
           "SELECT t.album, COALESCE(NULLIF(t.album_artist,''), t.artist) AS artist, "
           "COUNT(*) AS tracks, SUM(COALESCE(t.duration,0)) AS seconds, "
           "MAX(t.year) AS year, MIN(t.path) AS one_path "
           "FROM tracks t JOIN matched m "
           "ON m.album IS t.album "
           "AND m.group_artist IS COALESCE(NULLIF(t.album_artist,''), t.artist) "
           "GROUP BY t.album, COALESCE(NULLIF(t.album_artist,''), t.artist) "
           "ORDER BY artist COLLATE NOCASE, year, t.album COLLATE NOCASE LIMIT ?"
           % ((" WHERE " + " AND ".join(where)) if where else ""))
    con = db()
    cur = con.execute(sql, args + [n])
    albums = [dict(r) for r in cur.fetchall()]
    return {"ok": True, "count": len(albums), "albums": albums}


def op_album_tracks(req):
    """Every track of one album, in play order — what `play` is usually fed."""
    album = str(req.get("album") or "").strip()
    if not album:
        fail("album_tracks needs an `album`")
    args = ["%" + album + "%"]
    where = "album LIKE ?"
    artist = str(req.get("artist") or "").strip()
    if artist:
        where += " AND (album_artist LIKE ? OR artist LIKE ?)"
        args += ["%" + artist + "%"] * 2
    con = db()
    cur = con.execute("SELECT %s FROM tracks WHERE %s ORDER BY disc, track, path"
                      % (", ".join(TRACK_COLS), where), args)
    tracks = rows_of(cur)
    return {"ok": True, "count": len(tracks), "tracks": tracks}


def op_stats(_req):
    con = db()
    row = con.execute(
        "SELECT COUNT(*) AS tracks, COUNT(DISTINCT album) AS albums, "
        "COUNT(DISTINCT COALESCE(NULLIF(album_artist,''), artist)) AS artists, "
        "SUM(COALESCE(duration,0)) AS seconds, "
        "SUM(favorite = 1) AS favorites FROM tracks").fetchone()
    return {"ok": True, "library": dict(row), "database": DB}


def _cache_key(row):
    parts = (row["album_artist"] or row["artist"] or "", row["album"] or "",
             row["artist"] or "", row["title"] or "")
    return "|".join(trackmatch.fold(x) for x in parts)


def _decode(raw, fallback):
    try:
        value = json.loads(raw or "")
        return value if isinstance(value, type(fallback)) else fallback
    except (TypeError, ValueError):
        return fallback


def _has_table(con, name):
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                            (name,)).fetchone())


def _new_info(con, row):
    """Read the effective infostore view without creating or writing schema."""
    if not _has_table(con, "music_info_cache"):
        return None
    plain = dict(row)
    scope = infostore.scope_key(plain)
    users = {}
    edited = []
    if _has_table(con, "music_info_user"):
        for item in con.execute("SELECT * FROM music_info_user WHERE scope_key=?", (scope,)):
            if not item["deleted"]:
                users[item["kind"]] = _decode(item["body_json"], {})
                edited.append(item["kind"])

    cache = {}
    for item in con.execute("SELECT * FROM music_info_cache WHERE cache_key=?", (scope,)):
        cache[(item["cache_key"], item["kind"])] = item
    link = None
    if _has_table(con, "music_info_links"):
        link = con.execute("SELECT * FROM music_info_links WHERE scope_key=?", (scope,)).fetchone()
    release_id = link["release_id"] if link else ""
    if release_id:
        for item in con.execute("SELECT * FROM music_info_cache WHERE cache_key=?",
                                ("release:" + release_id,)):
            cache[(item["cache_key"], item["kind"])] = item
    album_row = cache.get(("release:" + release_id, "album")) if release_id else None
    if album_row is None:
        album_row = cache.get((scope, "album"))
    album = _decode(album_row["body_json"], {}) if album_row else {}
    if isinstance(album, dict):
        album = dict(album)
    else:
        album = {}
    if isinstance(users.get("album"), dict):
        album.update(users["album"])

    resolution = cache.get((scope, "resolution"))
    match_row = cache.get((scope, "match"))
    match_body = _decode((resolution or match_row)["body_json"], {}) if (resolution or match_row) else {}
    if not isinstance(match_body, dict):
        match_body = {}
    match = match_body.get("match") or match_body.get("result")
    if not match and match_row is not None:
        match = match_body
    if not isinstance(match, dict):
        match = {}
    if isinstance(users.get("match"), dict):
        match = {**match, **users["match"], "manual": True}

    similar_key = "track:" + hashlib.sha256(str(plain.get("path") or "").encode()).hexdigest()
    for item in con.execute("SELECT * FROM music_info_cache WHERE cache_key=?", (similar_key,)):
        cache[(item["cache_key"], item["kind"])] = item
    similar_row = cache.get((similar_key, "similar"))
    similar_body = _decode(similar_row["body_json"], {}) if similar_row else {}
    if isinstance(similar_body, dict):
        similar = similar_body.get("items", [])
    else:
        similar = similar_body if isinstance(similar_body, list) else []
    errors = {}
    provenance = {}
    for kind, item in (("album", album_row), ("match", resolution or match_row),
                       ("similar", similar_row)):
        if item is not None:
            provenance[kind] = "music_info_cache"
            if item["error"]:
                errors[kind] = item["error"]
    present = {"album": album_row is not None or "album" in users,
               "match": resolution is not None or match_row is not None or "match" in users,
               "similar": similar_row is not None}
    return {"scope": scope, "album": album, "match": match,
            "status": (match_body.get("status") if isinstance(match_body, dict) else "") or "uncached",
            "similar": similar, "present": present,
            "cache": {k: {"source": "music_info_cache", "fetched_at": v["fetched_at"],
                            "expires_at": v["expires_at"], "error": v["error"]}
                       for k, v in (("album", album_row), ("match", resolution or match_row),
                                    ("similar", similar_row)) if v is not None},
            "provenance": provenance, "errors": errors,
            "editedScopes": sorted(set(edited))}


def op_info(req):
    """Return local tags plus player's cached and corrected web knowledge."""
    con = db()
    where, args = [], []
    try:
        track_id = int(req.get("track_id") or 0)
    except (TypeError, ValueError):
        track_id = 0
    if track_id:
        where.append("id = ?")
        args.append(track_id)
    for field in ("title", "artist", "album"):
        value = str(req.get("track" if field == "title" else field) or "").strip()
        if value:
            if field == "artist":
                where.append("(artist LIKE ? OR album_artist LIKE ?)")
                args.extend(["%" + value + "%"] * 2)
            else:
                where.append(field + " LIKE ?")
                args.append("%" + value + "%")
    query = str(req.get("q") or "").strip()
    if query:
        where.append("(title LIKE ? OR artist LIKE ? OR album LIKE ? OR album_artist LIKE ?)")
        args.extend(["%" + query + "%"] * 4)
    if not where:
        fail("info needs track_id, query, track, artist or album")
    found = con.execute("SELECT * FROM tracks WHERE " + " AND ".join(where)
                        + " ORDER BY artist COLLATE NOCASE, album COLLATE NOCASE, disc, track LIMIT 12",
                        args).fetchall()
    if not found:
        return {"ok": True, "status": "not_found", "matches": []}
    identities = {(r["title"], r["artist"], r["album"]) for r in found}
    if len(identities) > 1 and not track_id:
        return {"ok": True, "status": "ambiguous",
                "matches": [{c: r[c] for c in TRACK_COLS} for r in found]}
    row = found[0]
    key = _cache_key(row)
    new = _new_info(con, row)
    metadata = ({r["kind"]: r for r in con.execute(
        "SELECT * FROM web_metadata WHERE cache_key=?", (key,))}
                if _has_table(con, "web_metadata") else {})
    overrides = ({r["kind"]: _decode(r["body_json"], {}) for r in con.execute(
        "SELECT * FROM web_metadata_overrides WHERE cache_key=?", (key,))}
                 if _has_table(con, "web_metadata_overrides") else {})
    legacy_match = (con.execute(
        "SELECT * FROM web_entity_matches WHERE cache_key=?", (key,)).fetchone()
                   if _has_table(con, "web_entity_matches") else None)

    legacy_album = _decode(metadata.get("album")["body_json"], {}) if metadata.get("album") else {}
    album = dict((new or {}).get("album") if (new and new.get("present", {}).get("album"))
                 else legacy_album)
    album.update(overrides.get("album", {}))
    legacy_similar = _decode(metadata.get("similar")["body_json"], []) if metadata.get("similar") else []
    if "similar" in overrides:
        legacy_similar = overrides["similar"].get("items", legacy_similar)
    similar = (new["similar"] if (new and new.get("present", {}).get("similar")) else legacy_similar)

    if new is not None and new.get("present", {}).get("match"):
        effective_match = dict(new["match"])
        status = new.get("status") or ("ready" if effective_match.get("id") else "uncached")
    else:
        effective_match = ({"provider": legacy_match["provider"], "entity_id": legacy_match["entity_id"],
                            "label": legacy_match["label"], "confidence": legacy_match["confidence"],
                            "manual": bool(legacy_match["manual"]),
                            "candidates": _decode(legacy_match["candidates_json"], [])}
                           if legacy_match else None)
        status = legacy_match["status"] if legacy_match else "uncached"
    cache = {kind: {"source": r["source"], "fetched_at": r["fetched_at"],
                    "expires_at": r["expires_at"], "error": r["error"]}
             for kind, r in metadata.items()}
    if new is not None:
        cache.update(new["cache"])
    errors = dict((new or {}).get("errors") or {})
    errors.update({kind: r["error"] for kind, r in metadata.items()
                   if r["error"] and kind not in (new or {}).get("provenance", {})})
    corrected = set(overrides)
    corrected.update((new or {}).get("editedScopes") or [])
    return {"ok": True, "status": status,
            "local": {c: row[c] for c in TRACK_COLS},
            "match": effective_match, "album": album, "similar": similar,
            "cache": cache, "corrected": sorted(corrected),
            "provenance": (new or {}).get("provenance", {}) | {
                kind: "legacy" for kind in cache if kind not in (new or {}).get("provenance", {})},
            "errors": errors, "editedScopes": sorted(corrected)}


def _send(verb, paths):
    """One line to player's queue socket, and its answer.

    Percent-encoded per the protocol (it splits on whitespace and a filename may
    hold any byte but NUL and '/'). A refused connection means the player is not
    running, which is a real answer and not an error to swallow."""
    real = []
    for p in paths:
        p = os.path.expanduser(str(p))
        if not os.path.exists(p):
            fail("no such file: " + p)
        real.append(p)
    if not real:
        fail("no paths given")
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect(SOCK)
    except OSError:
        fail("the music player is not running (nothing is listening on "
             + SOCK + ")")
    line = verb + " " + " ".join(urllib.parse.quote(p) for p in real) + "\n"
    try:
        s.sendall(line.encode("utf-8"))
        reply = s.recv(1 << 20).decode("utf-8", "replace")
    except OSError as e:
        fail("the player did not answer: " + str(e))
    finally:
        s.close()
    try:
        snap = json.loads(reply.splitlines()[0] or "{}")
    except (ValueError, IndexError):
        snap = {}
    tracks = snap.get("tracks") or []
    idx = snap.get("index")
    now = tracks[idx] if isinstance(idx, int) and 0 <= idx < len(tracks) else None
    return {"ok": True, "sent": len(real), "queue_length": len(tracks),
            "now_playing": now}


def op_play(req):
    return _send("OPEN", req.get("paths") or [])


def op_queue(req):
    return _send("QUEUE", req.get("paths") or [])


OPS = {"search": op_search, "albums": op_albums, "album_tracks": op_album_tracks,
       "info": op_info,
       "stats": op_stats, "play": op_play, "queue": op_queue}


def main():
    try:
        req = json.loads(sys.stdin.read() or "{}")
        if not isinstance(req, dict):
            raise ValueError
    except ValueError:
        fail("bad request")
    op = OPS.get(str(req.get("op") or ""))
    if op is None:
        fail("unknown op: %r (want one of %s)"
             % (req.get("op"), ", ".join(sorted(OPS))))
    try:
        print(json.dumps(op(req)))
    except SystemExit:
        raise
    except Exception as e:                      # never crash into the model
        fail("library error: " + str(e))


if __name__ == "__main__":
    main()
