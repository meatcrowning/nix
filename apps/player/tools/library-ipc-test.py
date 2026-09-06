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
    play_count INT, added_at INT, last_played INT)""")
FILES = []
rows = [
    ("Roygbiv", "Boards of Canada", "Music Has the Right to Children", "Boards of Canada", 1, 1998, 5, 1, 12),
    ("Olson", "Boards of Canada", "Music Has the Right to Children", "Boards of Canada", 2, 1998, 4, 0, 3),
    ("Xtal", "Aphex Twin", "Selected Ambient Works 85-92", "Aphex Twin", 1, 1992, 5, 1, 40),
    ("Stone Age", "Machinedrum", "Psyconia", "Machinedrum", 2, 2021, None, 0, 0),
    # Album artist is not the complete contributor list. This is the shape
    # that must make Skrillex's Thistle appear when browsing Blawan.
    ("Thistle", "Skrillex, MC Dricka, Randomer & Blawan", "Thistle", "Skrillex", 1, 2026, 5, 0, 0),
    ("B-side", "Skrillex", "Thistle", "Skrillex", 2, 2026, None, 0, 0),
]
for i, (title, artist, album, album_artist, tno, year, rating, fav, plays) in enumerate(rows, 1):
    f = TMP / ("%02d %s.flac" % (tno, title))
    f.write_bytes(b"not really audio")
    FILES.append(str(f))
    con.execute("INSERT INTO tracks VALUES (?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?)",
                (i, str(f), title, artist, album, album_artist, tno, year, "electronic",
                 300.0, rating, fav, plays, 1000 + i, 2000 + i))
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
