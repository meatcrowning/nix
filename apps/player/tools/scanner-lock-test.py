#!/usr/bin/env python3
"""Prove a slow library scan does not lock out foreground DB writes."""

import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import main  # noqa: E402


def track(path):
    return {
        "title": path.stem, "artist": "artist", "album": "album",
        "album_artist": "artist", "track": 1, "disc": 1,
        "date": "2026", "year": 2026, "orig_year": 2026,
        "genre": "test", "duration": 1.0, "codec": "fake",
        "samplerate": 44100, "bitdepth": 16, "rating": None,
        "favorite": 0, "play_count": 0, "has_art": False,
        "rg_track_gain": None, "rg_track_peak": None,
        "rg_album_gain": None, "rg_album_peak": None,
    }


with tempfile.TemporaryDirectory(prefix="player-scanner-lock-") as td:
    root = Path(td)
    db = root / "library.db"
    paths = [root / f"{n}.flac" for n in range(3)]
    for path in paths:
        path.touch()

    main.DATA = root
    main.DB_PATH = db
    main.LIBRARY_ROOT = root
    main.rebuild_albums = lambda con: con.commit()
    main.Scanner._art_pass = lambda self, con: None

    first_read = threading.Event()

    def slow_read(path):
        first_read.set()
        time.sleep(0.15)
        return track(Path(path))

    main.read_tags = slow_read
    setup = main.open_db()
    setup.execute("CREATE TABLE foreground (value TEXT)")
    setup.commit()
    setup.close()

    scan = main.Scanner()
    errors = []

    def run_scan():
        scan_con = main.open_db()
        try:
            scan._run(scan_con, time.time())
        except Exception as exc:  # surface worker failures in the main thread
            errors.append(exc)
        finally:
            scan_con.close()

    worker = threading.Thread(target=run_scan)
    worker.start()
    assert first_read.wait(1), "scanner never began parsing"

    foreground = sqlite3.connect(db, timeout=0.05)
    foreground.execute("PRAGMA busy_timeout=50")
    foreground.execute("INSERT INTO foreground VALUES ('responsive')")
    foreground.commit()
    foreground.close()

    worker.join(5)
    assert not worker.is_alive(), "scanner did not finish"
    assert not errors, errors
    check = sqlite3.connect(db)
    assert check.execute("SELECT value FROM foreground").fetchone()[0] == "responsive"
    assert check.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] == 3
    check.close()

print("scanner lock test: ok")
