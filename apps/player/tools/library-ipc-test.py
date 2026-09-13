#!/usr/bin/env python3
"""library-ipc.py against a MADE-UP library and a FAKE queue socket.

His library is 19,000 tracks he is listening to right now, and his player is
playing one of them — so this test builds its own sqlite database in a temp
directory ($PLAYER_DB) and its own socket in a temp $XDG_RUNTIME_DIR, and the
live player never hears from it (AGENTS.md: never drive the running player).

    python3 tools/library-ipc-test.py
"""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
IPC = str(HERE / "library-ipc.py")
TMP = Path(tempfile.mkdtemp(prefix="player-ipc-"))
DB = TMP / "library.db"
RUN = TMP / "run"
RUN.mkdir()
os.environ["PLAYER_DB"] = str(DB)
os.environ["XDG_RUNTIME_DIR"] = str(RUN)
SOCK = RUN / "player-queue.sock"

FAILS = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        FAILS.append(name)


# ---- a small library ------------------------------------------------------
con = sqlite3.connect(DB)
con.execute("""CREATE TABLE tracks (id INTEGER PRIMARY KEY, path TEXT,
    title TEXT, artist TEXT, album TEXT, album_artist TEXT, track INT, disc INT,
    year INT, genre TEXT, duration REAL, rating INT, favorite INT,
    play_count INT, added_at INT, last_played INT, has_art INT DEFAULT 0,
    album_id INT)""")
# player's own albums table (main.py's CREATE TABLE), because `art` reads the
# cover player actually resolved — the fixture has to carry the columns the
# real schema does or the test passes against a library that cannot exist.
con.execute("""CREATE TABLE albums (id INTEGER PRIMARY KEY, album TEXT,
    album_artist TEXT, year INT, orig_year INT, art_src TEXT, thumb TEXT,
    full_art TEXT)""")
con.execute("""CREATE TABLE web_metadata (cache_key TEXT, kind TEXT, source TEXT,
    body_json TEXT, fetched_at REAL, expires_at REAL, error TEXT)""")
con.execute("""CREATE TABLE web_metadata_overrides (cache_key TEXT, kind TEXT,
    body_json TEXT, edited_at REAL)""")
con.execute("""CREATE TABLE web_entity_matches (cache_key TEXT, entity_type TEXT,
    provider TEXT, entity_id TEXT, label TEXT, confidence REAL, status TEXT,
    candidates_json TEXT, manual INT, fetched_at REAL, error TEXT)""")
FILES = []
# The last two columns are the ART state: whether THAT FILE carries an
# embedded picture, and which albums row it belongs to. The four albums cover
# every answer `art` can give — player found art inside the files, player found
# a cover.jpg beside them, the files carry art player has not indexed yet, and
# nobody has one at all.
rows = [
    ("Roygbiv", "Boards of Canada", "Music Has the Right to Children", "Boards of Canada", 1, 1998, 5, 1, 12, 1, 10),
    ("Olson", "Boards of Canada", "Music Has the Right to Children", "Boards of Canada", 2, 1998, 4, 0, 3, 1, 10),
    ("Xtal", "Aphex Twin", "Selected Ambient Works 85-92", "Aphex Twin", 1, 1992, 5, 1, 40, 0, 11),
    ("Stone Age", "Machinedrum", "Psyconia", "Machinedrum", 2, 2021, None, 0, 0, 1, 12),
    # Album artist is not the complete contributor list. This is the shape
    # that must make Skrillex's Thistle appear when browsing Blawan.
    ("Thistle", "Skrillex, MC Dricka, Randomer & Blawan", "Thistle", "Skrillex", 1, 2026, 5, 0, 0, 0, 13),
    ("B-side", "Skrillex", "Thistle", "Skrillex", 2, 2026, None, 0, 0, 0, 13),
]
for i, (title, artist, album, album_artist, tno, year, rating, fav, plays,
        art, album_id) in enumerate(rows, 1):
    f = TMP / ("%02d %s.flac" % (tno, title))
    f.write_bytes(b"not really audio")
    FILES.append(str(f))
    con.execute("INSERT INTO tracks VALUES (?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?,?)",
                (i, str(f), title, artist, album, album_artist, tno, year, "electronic",
                 300.0, rating, fav, plays, 1000 + i, 2000 + i, art, album_id))
for album_id, album, album_artist, art_src in [
        (10, "Music Has the Right to Children", "Boards of Canada",
         "embedded:" + FILES[0]),
        (11, "Selected Ambient Works 85-92", "Aphex Twin",
         "file:" + str(TMP / "cover.jpg")),
        # Just imported: the file holds a picture, player has not resolved the
        # album row yet. This is the Structure case, and it must read as art.
        (12, "Psyconia", "Machinedrum", None),
        (13, "Thistle", "Skrillex", None)]:
    con.execute("INSERT INTO albums VALUES (?,?,?,?,?,?,?,?)",
                (album_id, album, album_artist, 2000, 2000, art_src, None, None))
cache_key = "boards of canada|music has the right to children|boards of canada|roygbiv"
con.execute("INSERT INTO web_metadata VALUES (?,?,?,?,?,?,?)",
            (cache_key, "album", "musicbrainz+wikipedia",
             json.dumps({"title": "Music Has the Right to Children",
                         "description": "original web description",
                         "artistInfo": {"name": "Boards of Canada"}}), 10, 20, None))
con.execute("INSERT INTO web_metadata_overrides VALUES (?,?,?,?)",
            (cache_key, "album", json.dumps({"description": "his correction"}), 11))
con.execute("INSERT INTO web_entity_matches VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (cache_key, "recording", "musicbrainz", "mbid-1", "Roygbiv", .98,
             "chosen", "[]", 1, 10, None))
con.commit()
con.close()


def call(req, timeout=20):
    out = subprocess.run([sys.executable, IPC], input=json.dumps(req).encode(),
                         capture_output=True, timeout=timeout)
    try:
        return json.loads(out.stdout.decode() or "{}")
    except ValueError:
        return {"error": "unparseable: " + out.stdout.decode()[:200]
                + out.stderr.decode()[:200]}


# ---- searching ------------------------------------------------------------
r = call({"op": "search", "q": "boards"})
check("free text matches the artist", r.get("count") == 2, json.dumps(r)[:200])
check("...and every row carries its path",
      all(t.get("path") for t in r.get("tracks", [])))
r = call({"op": "search", "q": "roygbiv"})
check("free text matches a title", r.get("count") == 1, json.dumps(r)[:160])
r = call({"op": "search", "favorites_only": True})
check("favourites only", r.get("count") == 2, json.dumps(r)[:160])
r = call({"op": "search", "min_rating": 5})
check("a rating floor", r.get("count") == 3, json.dumps(r)[:160])
r = call({"op": "search", "limit": 1})
check("a limit pages, and says the total",
      r.get("count") == 1 and r.get("total") == 6, json.dumps(r)[:160])
r = call({"op": "search", "q": "100%"})
check("a wildcard in the query is not one", r.get("count") == 0,
      json.dumps(r)[:160])
r = call({"op": "search", "q": "boards", "limit": 1})
check("a search says which RELEASES it matched, not just this page of tracks",
      r.get("album_count") == 1
      and [a["album"] for a in r.get("albums", [])] == ["Music Has the Right to Children"]
      and r["albums"][0]["tracks"] == 2, json.dumps(r)[:240])
r = call({"op": "search", "q": "blawan"})
check("...with the release's own track count, not the guest's one matching track",
      [(a["album"], a["tracks"]) for a in r.get("albums", [])] == [("Thistle", 2)],
      json.dumps(r)[:240])
# ---- art state: what a cover IS, not whether a cover.jpg is lying about ----
r = call({"op": "search", "q": "roygbiv"})
check("a track row says whether that FILE carries a picture",
      r["tracks"][0].get("has_art") == 1, json.dumps(r)[:200])
check("...and the album rollup says where the cover comes from",
      r["albums"][0].get("art") == "embedded", json.dumps(r["albums"])[:200])
r = call({"op": "albums"})
art = {a["album"]: a.get("art") for a in r["albums"]}
check("a cover player found inside the files reads embedded",
      art.get("Music Has the Right to Children") == "embedded", str(art))
check("...a cover.jpg beside them reads folder",
      art.get("Selected Ambient Works 85-92") == "folder", str(art))
check("...files with art player has not indexed yet still read as art",
      art.get("Psyconia") == "embedded", str(art))
check("...and only a record nobody has a cover for reads none",
      art.get("Thistle") == "none", str(art))
r = call({"op": "album_tracks", "album": "Psyconia"})
check("album_tracks states the album's art in one word", r.get("art") == "embedded",
      json.dumps(r)[:200])
r = call({"op": "stats"})
check("stats counts the albums drawing blank in the player",
      r["library"].get("albums_without_art") == 2, json.dumps(r)[:200])

r = call({"op": "albums"})
check("albums group with their track counts",
      r.get("count") == 4 and any(a["tracks"] == 2 for a in r["albums"]),
      json.dumps(r)[:200])
r = call({"op": "albums", "artist": "blawan"})
check("artist album search includes a track collaborator's release",
      r.get("count") == 1 and r["albums"][0]["album"] == "Thistle"
      and r["albums"][0]["tracks"] == 2, json.dumps(r)[:200])
r = call({"op": "album_tracks", "album": "Music Has the Right"})
check("an album comes back in play order",
      [t["title"] for t in r.get("tracks", [])] == ["Roygbiv", "Olson"],
      json.dumps(r)[:200])
r = call({"op": "stats"})
check("stats size the library", r.get("library", {}).get("tracks") == 6,
      json.dumps(r)[:160])
r = call({"op": "info", "track_id": 1})
check("info returns cached web facts and manual corrections",
      r.get("album", {}).get("description") == "his correction"
      and r.get("match", {}).get("entity_id") == "mbid-1"
      and r.get("local", {}).get("play_count") == 12,
      json.dumps(r)[:240])
r = call({"op": "info", "artist": "Boards of Canada"})
check("a broad info match asks the agent to choose",
      r.get("status") == "ambiguous" and len(r.get("matches", [])) == 2,
      json.dumps(r)[:200])

# ---- the database is opened READ-ONLY ------------------------------------
before = DB.stat().st_mtime
call({"op": "search", "q": "x"})
check("searching never writes to the library", DB.stat().st_mtime == before)

# ---- play / queue, against a FAKE player ---------------------------------
heard = []


def fake_player():
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(SOCK))
    srv.listen(4)
    while True:
        c, _ = srv.accept()
        line = c.recv(1 << 16).decode("utf-8", "replace").strip()
        heard.append(line)
        c.sendall((json.dumps({"index": 0, "tracks": [
            {"title": "Roygbiv", "artist": "Boards of Canada", "dur": 300}]})
            + "\n").encode())
        c.close()


threading.Thread(target=fake_player, daemon=True).start()

r = call({"op": "play", "paths": FILES[:2]})
check("play sends OPEN with both paths",
      heard and heard[-1].startswith("OPEN ")
      and urllib.parse.unquote(heard[-1].split()[1]) == FILES[0],
      (heard[-1] if heard else "")[:120])
check("...and answers with what is playing now",
      r.get("ok") and (r.get("now_playing") or {}).get("title") == "Roygbiv",
      json.dumps(r)[:160])
r = call({"op": "queue", "paths": FILES[2:]})
check("queue sends QUEUE", heard[-1].startswith("QUEUE "),
      heard[-1][:80])
r = call({"op": "play", "paths": [str(TMP / "not-here.flac")]})
check("a path that is not there is refused before the socket",
      "error" in r and "no such file" in r["error"], json.dumps(r)[:160])

os.unlink(SOCK)
r = call({"op": "play", "paths": FILES[:1]})
check("no player running is said plainly",
      "error" in r and "not running" in r["error"], json.dumps(r)[:160])

r = call({"op": "nonsense"})
check("an unknown op names what it wanted", "error" in r, json.dumps(r)[:120])

print("\n%d checks failed" % len(FAILS))
sys.exit(1 if FAILS else 0)
