#!/usr/bin/env python3
"""Recommendation ranking with a scratch DB, state file and Last.fm stub."""
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent.parent / "pylib")]
import recommend

TMP = Path(tempfile.mkdtemp(prefix="player-recommend-"))
recommend.STATE = TMP / "state.json"
fails = []


def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


con = sqlite3.connect(":memory:")
con.row_factory = sqlite3.Row
con.execute("""CREATE TABLE tracks (path TEXT,title TEXT,artist TEXT,album TEXT,
 album_artist TEXT,track INT,disc INT,year INT,orig_year INT,genre TEXT,
 rating REAL,favorite INT,play_count INT,last_played REAL)""")
now = time.time()
rows = [
    ("/a1", "A one", "Anchor", "Old Favourite", "Anchor", 1, 1, 1999, None,
     "ambient", 1.0, 1, 20, now - 220 * 86400),
    ("/a2", "A two", "Anchor", "Old Favourite", "Anchor", 2, 1, 1999, None,
     "ambient", 1.0, 1, 20, now - 220 * 86400),
    ("/b1", "B one", "Rotation", "Too Much", "Rotation", 1, 1, 2020, None,
     "ambient", .8, 0, 40, now - 86400),
    ("/c1", "C one", "Nearby", "New Thing", "Nearby", 1, 1, 2024, None,
     "ambient", .7, 0, 0, None),
]
con.executemany("INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)

recommend.lastfm.load = lambda: {"api_key": "x", "username": "me"}
recommend.lastfm.has_keys = lambda _cfg: True
recommend.lastfm.username = lambda _cfg: "me"
recommend.lastfm.recent_tracks = lambda **_kw: [
    {"artist": "Rotation", "track": "B one", "uts": int(now - 100)},
    {"artist": "Rotation", "track": "Other", "uts": int(now - 200)},
]
def call(method, params, **_kw):
    if method == "user.getTopTracks":
        return {"toptracks": {"track": [{"name": "A one", "artist": {"name": "Anchor"}, "playcount": "30"}]}}
    if method == "artist.getSimilar":
        return {"similarartists": {"artist": [{"name": "Nearby"}]}}
    raise AssertionError(method)
recommend.lastfm.call = call

r = recommend.recommend(con, "familiar", 3)
check("uses dated Last.fm history", r["history"] == "lastfm")
check("returns album-aware picks with reasons", r["albums"] and r["albums"][0]["album"]
      and r["albums"][0]["reason"])
check("saturates the recently played artist", all(x["artist"] != "Rotation" for x in r["albums"][:2]))
check("album paths retain play order", r["albums"][0]["paths"] == ["/a1", "/a2"])
check("feedback is persisted", recommend.feedback(r["recommendation_id"], "not_now").get("ok"))
r2 = recommend.recommend(con, "rediscover", 3)
check("not-now feedback removes that recommendation", all(x["album"] != "Old Favourite" for x in r2["albums"]))
check("explore is a supported deliberate mode", recommend.recommend(con, "explore", 1).get("mode") == "explore")
print("\n%d checks failed" % len(fails))
raise SystemExit(bool(fails))
