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
        where.append("(title LIKE ? ESCAPE '\\' OR artist LIKE ? ESCAPE '\\' "
                     "OR album LIKE ? ESCAPE '\\' OR album_artist LIKE ? ESCAPE '\\')")
        args += [like] * 4
    for field in ("artist", "album", "genre"):
        val = str(req.get(field) or "").strip()
        if val:
            where.append("(%s LIKE ? ESCAPE '\\' %s)"
                         % (field, "OR album_artist LIKE ? ESCAPE '\\'"
                            if field == "artist" else ""))
            args.append("%" + val + "%")
            if field == "artist":
                args.append("%" + val + "%")
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
    at the level people actually pick music."""
    where, args = [], []
    q = str(req.get("q") or "").strip()
    if q:
        like = "%" + q + "%"
        where.append("(album LIKE ? OR album_artist LIKE ? OR artist LIKE ?)")
        args += [like] * 3
    artist = str(req.get("artist") or "").strip()
    if artist:
        where.append("(album_artist LIKE ? OR artist LIKE ?)")
        args += ["%" + artist + "%"] * 2
    n = limit_of(req)
    sql = ("SELECT album, COALESCE(NULLIF(album_artist,''), artist) AS artist, "
           "COUNT(*) AS tracks, SUM(COALESCE(duration,0)) AS seconds, "
           "MAX(year) AS year, MIN(path) AS one_path "
           "FROM tracks%s GROUP BY album, artist "
           "ORDER BY artist COLLATE NOCASE, year, album COLLATE NOCASE LIMIT ?"
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
