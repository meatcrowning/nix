#!/usr/bin/env python3
"""Offscreen scratch checks for cached contributor browsing."""

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# albuminfo reaches trackmatch through pylib; main.py is not imported here.
sys.path.insert(0, str(ROOT.parent / "pylib"))

from PySide6.QtGui import QGuiApplication  # noqa: E402
import infostore  # noqa: E402
from albuminfo import AlbumInformation  # noqa: E402


def check(ok, message):
    if not ok:
        raise AssertionError(message)


def run():
    app = QGuiApplication([])
    check(app.platformName() == "offscreen", "connection probe escaped offscreen")
    with tempfile.TemporaryDirectory(prefix="player-info-connection-") as td:
        path = Path(td) / "library.db"
        con = sqlite3.connect(path)
        con.execute("""CREATE TABLE tracks (
            id INTEGER PRIMARY KEY, path TEXT, title TEXT, artist TEXT, album TEXT,
            album_artist TEXT, track INTEGER, disc INTEGER, identity_json TEXT)""")
        con.execute("INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?,?)",
                    (1, "/music/Edition/01 Anchor.flac", "Anchor", "A", "Edition", "A", 1, 1, ""))
        con.execute("INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?,?)",
                    (2, "/music/Edition/02 Other.flac", "Other", "A", "Edition", "A", 2, 1, ""))
        con.execute("INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?,?)",
                    (3, "/music/Edition/01 Disc Two.flac", "Disc Two", "A", "Edition", "A", 1, 2, ""))
        con.execute("INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?,?)",
                    (4, "/music/Other/01 Anchor.flac", "Anchor", "A", "Other edition", "A", 1, 1,
                                 '{"releaseId":"rel-other"}'))
        infostore.ensure_schema(con)
        scope = infostore.scope_key({"path": "/music/Edition/01 Anchor.flac", "album": "Edition",
                                     "album_artist": "A", "artist": "A"})
        album = {
            "title": "Edition", "artist": "A", "musicbrainzReleaseId": "rel-edition",
            "credits": [
                {"id": "album-person", "name": "Album Person", "role": "producer", "scope": "album"},
                {"id": "track-person", "name": "Track Person", "role": "producer", "scope": "track",
                 "trackTitle": "Anchor", "trackPosition": 1, "disc": 1},
            ],
            "tracks": [],
        }
        other = {"title": "Other edition", "artist": "A", "musicbrainzReleaseId": "rel-other",
                 "credits": [{"id": "other-person", "name": "Other Person", "role": "producer", "scope": "album"}]}
        con.execute("INSERT INTO music_info_links VALUES (?,?,?,?)", (scope, "rel-edition", "group", 1))
        con.execute("INSERT INTO music_info_cache VALUES (?,?,?,?,?,?)",
                    ("release:rel-edition", "album", json.dumps(album), 1, 100, ""))
        con.execute("INSERT INTO music_info_cache VALUES (?,?,?,?,?,?)",
                    ("release:rel-other", "album", json.dumps(other), 1, 100, ""))
        con.commit(); con.close()

        provider = AlbumInformation(None, db_path=path, read_tags=None,
                                    fetch_json=lambda _url: {})
        state = provider._connection(1, "artist", "track-person", "Track Person")
        ids = [item["trackId"] for item in state["similar"]]
        check(ids == [1], state)

        # The row had no embedded release ID; _related_rows supplied the link,
        # allowing an album scoped credit to reach every track in that edition.
        state = provider._connection(1, "artist", "album-person", "Album Person")
        ids = [item["trackId"] for item in state["similar"]]
        check(ids == [1, 2, 3] and 4 not in ids, state)

        empty = provider._connection(1, "artist", "missing", "Missing")
        check(empty["similar"] == [] and empty["connection"] == "Missing", empty)
    print("info-connection-test: ok")


if __name__ == "__main__":
    run()
