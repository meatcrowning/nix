#!/usr/bin/env python3
"""Scratch two-way infostore/dbsync and read-only IPC checks."""

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
spec = importlib.util.spec_from_file_location("dbsync", HERE / "dbsync.py")
dbsync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dbsync)


def check(ok, message):
    if not ok:
        raise AssertionError(message)


TRACK_COLS = ["path", "mtime", "size", "title", "artist", "album", "album_artist",
              "track", "disc", "date", "year", "orig_year", "genre", "duration",
              "codec", "samplerate", "bitdepth", "rating", "favorite", "play_count",
              "meta_mtime", "added_at", "last_played", "has_art", "rg_track_gain",
              "rg_track_peak", "rg_album_gain", "rg_album_peak"]


def make_db(path, identity=True, info=True):
    con = sqlite3.connect(path)
    cols = ["id INTEGER PRIMARY KEY"] + [c + (" REAL" if c in ("mtime", "duration", "added_at", "last_played",
                                                                  "rg_track_gain", "rg_track_peak", "rg_album_gain",
                                                                  "rg_album_peak", "meta_mtime") else " TEXT")
            for c in TRACK_COLS]
    # The integer-ish columns need not be typed precisely for this merge probe.
    con.execute("CREATE TABLE tracks (%s)" % ",".join(cols))
    con.execute("CREATE TABLE lyrics (track_id INTEGER, source TEXT, synced TEXT, body TEXT, fetched_at REAL, attempts INTEGER)")
    if info:
        con.executescript(dbsync.INFO_SCHEMA)
    if identity:
        con.execute("ALTER TABLE tracks ADD COLUMN identity_json TEXT")
    con.commit()
    return con


def add_track(con, tid, path, identity=None, mtime=1):
    values = [path, mtime, 1, "Song", "Artist", "Album", "Artist", 1, 1, "2020", 2020,
              2020, "ambient", 100.0, "flac", 44100, 16, None, 0, 0, None, 10, None,
              0, None, None, None, None]
    cols = list(TRACK_COLS)
    if "identity_json" in {r[1] for r in con.execute("PRAGMA table_info(tracks)")}:
        cols.append("identity_json")
        values.append(identity)
    con.execute("INSERT INTO tracks (id,%s) VALUES (?,%s)" % (','.join(cols), ','.join('?' * len(cols))),
                [tid] + values)


def run():
    with tempfile.TemporaryDirectory(prefix="player-info-sync-") as td:
        td = Path(td)
        src_path, dst_path = td / "src.db", td / "dst.db"
        src = make_db(src_path, identity=True)
        dst = make_db(dst_path, identity=True)
        add_track(src, 1, "/music/a.flac", '{"recordingId":"new"}', mtime=2)
        add_track(src, 2, "/music/new.flac", '{"releaseId":"rel-new"}')
        add_track(dst, 99, "/music/a.flac", '{"recordingId":"old"}', mtime=1)
        add_track(dst, 77, "/music/local.flac", '{"recordingId":"local"}')
        src.execute("INSERT INTO music_info_user VALUES (?,?,?,?,?)",
                    ("album:scope", "album", '{"title":"remote"}', 20, 0))
        dst.execute("INSERT INTO music_info_user VALUES (?,?,?,?,?)",
                    ("album:scope", "album", '{"title":"local"}', 10, 0))
        src.execute("INSERT INTO music_info_user VALUES (?,?,?,?,?)",
                    ("album:scope", "match", '{}', 30, 1))
        dst.execute("INSERT INTO music_info_user VALUES (?,?,?,?,?)",
                    ("album:scope", "match", '{"id":"old"}', 1, 0))
        dst.execute("INSERT INTO music_info_cache VALUES (?,?,?,?,?,?)",
                    ("release:rel", "album", '{"title":"good"}', 100, 200, ""))
        src.execute("INSERT INTO music_info_cache VALUES (?,?,?,?,?,?)",
                    ("release:rel", "album", '{}', 200, 300, "offline"))
        src.execute("INSERT INTO music_info_cache VALUES (?,?,?,?,?,?)",
                    ("release:new", "album", '{"title":"new"}', 200, 300, ""))
        dst.execute("INSERT INTO music_info_links VALUES (?,?,?,?)", ("album:scope", "rel", "group", 4))
        src.execute("INSERT INTO music_info_links VALUES (?,?,?,?)", ("album:scope", "rel-new", "group-new", 5))
        src.commit(); dst.commit(); src.close(); dst.close()

        stats = dbsync.merge(str(src_path), str(dst_path), quiet=True)
        con = sqlite3.connect(dst_path); con.row_factory = sqlite3.Row
        check(con.execute("SELECT identity_json FROM tracks WHERE id=99").fetchone()[0] == '{"recordingId":"new"}',
              "newer meaningful source identity updated destination")
        merged_id = con.execute("SELECT id FROM tracks WHERE path='/music/new.flac'").fetchone()[0]
        check(merged_id and merged_id != 2, "new track merged without trusting source rowid")
        check(con.execute("SELECT body_json FROM music_info_user WHERE kind='album'").fetchone()[0] == '{"title":"remote"}',
              "latest manual choice won")
        check(con.execute("SELECT deleted FROM music_info_user WHERE kind='match'").fetchone()[0] == 1,
              "newer tombstone persisted")
        check(con.execute("SELECT body_json FROM music_info_cache WHERE cache_key='release:rel'").fetchone()[0] == '{"title":"good"}',
              "failure did not replace successful cache")
        check(con.execute("SELECT release_id FROM music_info_links WHERE scope_key='album:scope'").fetchone()[0] == "rel-new",
              "newer link won")
        con.close()

        # An older source without identity_json is accepted and cannot clear a
        # useful destination value.  Dry-run also leaves schema and rows alone.
        old_path = td / "old.db"
        old = make_db(old_path, identity=False, info=False)
        add_track(old, 1, "/music/a.flac", mtime=9); old.commit(); old.close()
        before = sqlite3.connect(dst_path).execute("SELECT identity_json FROM tracks WHERE id=99").fetchone()[0]
        dbsync.merge(str(old_path), str(dst_path), dry_run=True, quiet=True)
        after = sqlite3.connect(dst_path).execute("SELECT identity_json FROM tracks WHERE id=99").fetchone()[0]
        check(before == after, "dry-run changed identity")
        old_cols = {r[1] for r in sqlite3.connect(old_path).execute("PRAGMA table_info(tracks)")}
        check("identity_json" not in old_cols, "old fixture unexpectedly gained identity")

        # Read-only IPC prefers new effective facts, including a scoped edit,
        # and does not require legacy web tables to exist.
        ipc_db = td / "ipc.db"
        ipc = make_db(ipc_db, identity=True, info=True)
        add_track(ipc, 1, "/music/ipc.flac", '{"recordingId":"rec"}')
        import hashlib
        import re
        scope = "album:" + hashlib.sha256(json.dumps(["Artist", "Album", "/music"], ensure_ascii=False).encode()).hexdigest()
        ipc.execute("INSERT INTO music_info_links VALUES (?,?,?,?)", (scope, "rel-ipc", "group", 1))
        ipc.execute("INSERT INTO music_info_cache VALUES (?,?,?,?,?,?)", ("release:rel-ipc", "album",
                      '{"title":"Cached album","artist":"Artist"}', 2, 100, ""))
        ipc.execute("INSERT INTO music_info_cache VALUES (?,?,?,?,?,?)", (scope, "resolution",
                      '{"status":"ready","match":{"id":"rec","label":"Song"}}', 2, 100, ""))
        track_key = "track:" + hashlib.sha256("/music/ipc.flac".encode()).hexdigest()
        ipc.execute("INSERT INTO music_info_cache VALUES (?,?,?,?,?,?)", (track_key, "similar",
                      '{"items":[{"title":"Related"}]}', 2, 100, ""))
        ipc.execute("INSERT INTO music_info_user VALUES (?,?,?,?,?)", (scope, "album",
                      '{"description":"corrected"}', 3, 0))
        ipc.commit(); ipc.close()
        env = dict(os.environ, PLAYER_DB=str(ipc_db))
        out = subprocess.check_output([sys.executable, str(HERE / "library-ipc.py")],
                                      input=json.dumps({"op": "info", "track_id": 1}).encode(), env=env)
        answer = json.loads(out)
        check(answer["album"]["description"] == "corrected" and answer["provenance"]["album"] == "music_info_cache",
              answer)
        check(answer["match"]["id"] == "rec" and answer["similar"][0]["title"] == "Related", answer)
        check("album" in answer["editedScopes"], answer)

    print("info-sync-test: ok")


if __name__ == "__main__":
    run()
