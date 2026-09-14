#!/usr/bin/env python3
"""tagtool harness — every op, on files this script makes, in a temp dir.

It never touches /run/media/lam/SSD/aud, ~/.local/share/player/library.db or
~/.cache/player-tagtool: AUD_ROOT, PLAYER_DB and TAGTOOL_STATE are pointed at
the temp tree before tagtool is imported. The library the real tool edits has
no snapshots, so a harness that reached it once would be unrecoverable.

    /usr/bin/python3 tagtool-test.py          (needs mutagen + ffmpeg)

Covers the four containers the library actually holds (mp3/flac/m4a/ogg), the
set/remove round trip on a mapped key and an arbitrary one, the reserved-key
refusal, cover embed + cover.jpg, and undo for both a tag change and art.
"""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="tagtool-test-"))
os.environ["AUD_ROOT"] = str(TMP / "aud")
os.environ["PLAYER_DB"] = str(TMP / "library.db")
os.environ["TAGTOOL_STATE"] = str(TMP / "state")
# The player's ART CACHE is derived from this at import: point it at the temp
# tree too, or a cover test would rewrite entries his running player is drawing.
os.environ["XDG_CACHE_HOME"] = str(TMP / "cache")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import tagtool                                              # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (" — " + str(detail) if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def make_files():
    d = TMP / "aud" / "Test Artist" / "Test Album"
    d.mkdir(parents=True)
    paths = []
    for i, ext in enumerate((".mp3", ".flac", ".m4a", ".ogg"), start=1):
        p = d / ("0%d track%s" % (i, ext))
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
               "anullsrc=r=44100:cl=stereo", "-t", "1"]
        cmd += {".mp3": ["-c:a", "libmp3lame"], ".flac": ["-c:a", "flac"],
                ".m4a": ["-c:a", "aac"], ".ogg": ["-c:a", "libvorbis"]}[ext]
        cmd += ["-metadata", "title=Track %d" % i,
                "-metadata", "artist=Test Artist",
                "-metadata", "album=Test Album",
                "-metadata", "disc=1", "-metadata", "track=%d" % i, str(p)]
        subprocess.run(cmd, check=True)
        paths.append(str(p))
    return paths


def make_db(paths):
    """A minimal library.db in the player's shape, so the DB half of a write is
    exercised instead of silently skipped (tagtool no-ops when there is none)."""
    con = sqlite3.connect(os.environ["PLAYER_DB"])
    con.execute("CREATE TABLE tracks (id INTEGER PRIMARY KEY, path TEXT, "
                "title TEXT, artist TEXT, album TEXT, album_artist TEXT, "
                "track INT, disc INT, year INT, size INT, mtime REAL, "
                "has_art INT DEFAULT 0, album_id INT)")
    con.execute("CREATE TABLE albums (id INTEGER PRIMARY KEY, album TEXT, "
                "album_artist TEXT, art_src TEXT, thumb TEXT, full_art TEXT)")
    for i, p in enumerate(paths, 1):
        con.execute("INSERT INTO tracks (id, path, title, artist, album, "
                    "album_artist, album_id) VALUES (?,?,?,?,?,?,1)",
                    (i, p, "Track %d" % i, "Test Artist", "Test Album",
                     "Test Artist"))
    # Pre-loaded with art the player resolved EARLIER — the state that made the
    # stale-cover bug invisible.
    con.execute("INSERT INTO albums VALUES (1,'Test Album','Test Artist',"
                "'embedded:" + paths[0].replace("'", "''") + "','old-t.jpg','old-f.jpg')")
    con.commit()
    con.close()


def album_row():
    con = sqlite3.connect(os.environ["PLAYER_DB"])
    row = con.execute("SELECT art_src, thumb, full_art FROM albums "
                      "WHERE id=1").fetchone()
    con.close()
    return row


def png():
    p = TMP / "cover.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "color=c=red:s=64x64", "-frames:v", "1", str(p)],
                   check=True)
    return str(p)


def main():
    print("temp tree:", TMP)
    paths = make_files()
    make_db(paths)

    r = tagtool.run({"op": "show", "paths": paths})
    check("show reads every container", r["ok"] and r["shown"] == 4)
    check("show sees the disc tag",
          all(f["tags"].get("disc") == "1" for f in r["files"]),
          [f["tags"].get("disc") for f in r["files"]])

    # --- dry run writes nothing ---------------------------------------
    r = tagtool.run({"op": "set", "paths": paths, "tags": {"genre": "IDM"}})
    check("dry run is the default", r["ok"] and not r["applied"] and r["changes_total"] == 4)
    after = tagtool.run({"op": "show", "paths": paths})
    check("dry run left the files alone",
          all(not f["tags"].get("genre") for f in after["files"]))

    # --- set: a mapped key and an arbitrary one ------------------------
    r = tagtool.run({"op": "set", "paths": paths, "apply": True,
                     "tags": {"genre": "IDM", "mood": "cold"}})
    check("set applied", r["ok"] and r["applied"] and r["files_changed"] == 4, r)
    tok_set = r.get("undo_token")
    after = tagtool.run({"op": "show", "paths": paths})
    check("mapped key landed in every container",
          all(f["tags"].get("genre") == "IDM" for f in after["files"]),
          [(f["path"][-5:], f["tags"].get("genre")) for f in after["files"]])
    check("arbitrary key landed in every container",
          all(f["tags"].get("mood") == "cold" for f in after["files"]),
          [(f["path"][-5:], sorted(f["tags"])) for f in after["files"]])

    # A malformed lyrics tag must not be able to consume the caller's entire
    # context when it asks `show` to inspect a file.
    tagtool.run({"op": "set", "paths": [paths[0]], "apply": True,
                 "tags": {"lyrics": "x" * (tagtool.SHOW_TAG_VALUE_MAX + 200)}})
    shown = tagtool.run({"op": "show", "paths": [paths[0]]})["files"][0]
    check("show bounds oversized tag values",
          len(shown["tags"].get("lyrics", "")) == tagtool.SHOW_TAG_VALUE_MAX + 1
          and shown.get("truncated_tags", {}).get("lyrics", 0) > tagtool.SHOW_TAG_VALUE_MAX,
          shown.get("truncated_tags"))

    r = tagtool.run({"op": "set", "paths": paths, "apply": True,
                     "tags": {"genre": "IDM"}})
    check("a no-op change is not a write", r["changes_total"] == 0)

    # --- remove: the disc-number case he named -------------------------
    r = tagtool.run({"op": "remove", "paths": paths, "keys": ["disc"],
                     "apply": True})
    check("remove applied", r["ok"] and r["files_changed"] == 4, r)
    tok_rm = r.get("undo_token")
    after = tagtool.run({"op": "show", "paths": paths})
    check("disc is gone from every container",
          all(not f["tags"].get("disc") for f in after["files"]),
          [(f["path"][-5:], f["tags"].get("disc")) for f in after["files"]])
    check("removing disc left the track number alone",
          all(f["tags"].get("track") for f in after["files"]),
          [(f["path"][-5:], f["tags"].get("track")) for f in after["files"]])
    check("alias: 'disk number' means disc", tagtool.canon_key("disk number") == "disc"
          or tagtool.canon_key("disknumber") == "disc")

    # --- the rating is not this tool's to touch ------------------------
    for req in ({"op": "set", "paths": paths, "tags": {"FMPS_Rating": "1.0"}, "apply": True},
                {"op": "remove", "paths": paths, "keys": ["rating"], "apply": True}):
        r = tagtool.run(req)
        check("refuses %s on the rating" % req["op"], not r["ok"] and "refusing" in r["error"], r)

    # --- cover art -----------------------------------------------------
    cover = png()
    planned = tagtool.run({"op": "art", "paths": paths,
                           "art": {"file": cover}})
    check("art dry run returns a source-bound plan token",
          planned["ok"] and planned.get("source") == "file"
          and planned.get("plan_token"), planned)
    r = tagtool.run({"op": "art", "paths": paths,
                     "art": {"source": "auto"}, "apply": True})
    check("art apply refuses a reconstructed request", not r["ok"]
          and "plan_token" in r.get("error", ""), r)
    r = tagtool.run({"op": "art", "apply": True,
                     "plan_token": planned.get("plan_token")})
    check("art embedded + cover.jpg written",
          r["ok"] and r["files_embedded"] == 4 and len(r["covers_written"]) == 1, r)
    check("art apply reports the player cache as refreshed immediately",
          r.get("player_refresh", {}).get("state") == "immediate", r)
    tok_art = r.get("undo_token")
    after = tagtool.run({"op": "show", "paths": paths})
    check("every file reports embedded art",
          all(f["tags"].get("_art") for f in after["files"]),
          [(f["path"][-5:], f["tags"].get("_art")) for f in after["files"]])
    data, mime = tagtool.read_art(paths[0])
    check("the embedded bytes are the planned image, not a refetch",
          data == Path(cover).read_bytes() and mime == "image/png", mime)
    check("the plan token cannot be replayed",
          not tagtool.run({"op": "art", "apply": True,
                           "plan_token": planned.get("plan_token")})["ok"])

    # --- the PLAYER's album row has to follow the cover -----------------
    # Without this the file changes and the player keeps drawing the old art:
    # its own art pass re-resolves only a missing thumb or a dead donor path,
    # and a cover swapped in place is neither.
    row = album_row()
    key = hashlib.sha1(hashlib.sha1(data).hexdigest().encode()).hexdigest()[:16]
    check("the album row points at the NEW cover, under the player's own key",
          row and row[1] == key + "-t.jpg" and row[2] == key + "-f.jpg", row)
    check("...with art_src naming a file that carries it",
          row and row[0] == "embedded:" + paths[0], row)
    check("...and both cache files were actually rendered",
          (tagtool.ART_CACHE / (key + "-t.jpg")).exists()
          and (tagtool.ART_CACHE / (key + "-f.jpg")).exists(),
          sorted(p.name for p in tagtool.ART_CACHE.glob("*")))

    r = tagtool.run({"op": "art_remove", "paths": paths, "apply": True})
    check("art_remove clears the album row rather than leaving it wrong",
          r["ok"] and album_row() == (None, None, None), (r, album_row()))
    r = tagtool.run({"op": "undo", "token": r.get("undo_token"), "apply": True})
    check("...and undoing it puts the row back on the restored cover",
          r["ok"] and album_row()[1] == key + "-t.jpg", album_row())

    # --- undo ----------------------------------------------------------
    r = tagtool.run({"op": "undo", "token": tok_art, "apply": True})
    check("undo art", r["ok"] and r["files_restored"] >= 4, r)
    after = tagtool.run({"op": "show", "paths": paths})
    check("art is gone again after undo",
          all(not f["tags"].get("_art") for f in after["files"]),
          [(f["path"][-5:], f["tags"].get("_art")) for f in after["files"]])
    check("cover.jpg removed by undo",
          not (Path(paths[0]).parent / "cover.jpg").exists())

    r = tagtool.run({"op": "undo", "token": tok_rm, "apply": True})
    check("undo remove", r["ok"], r)
    after = tagtool.run({"op": "show", "paths": paths})
    check("disc is back", all(f["tags"].get("disc") == "1" for f in after["files"]),
          [(f["path"][-5:], f["tags"].get("disc")) for f in after["files"]])

    r = tagtool.run({"op": "undo", "token": tok_set, "apply": True})
    after = tagtool.run({"op": "show", "paths": paths})
    check("undo set clears a key that was not there before",
          all(not f["tags"].get("genre") and not f["tags"].get("mood")
              for f in after["files"]),
          [(f["path"][-5:], f["tags"].get("genre"), f["tags"].get("mood"))
           for f in after["files"]])

    r = tagtool.run({"op": "list_undo"})
    check("undo manifests are listed", r["ok"] and len(r["undos"]) >= 3)

    # --- selection -----------------------------------------------------
    r = tagtool.run({"op": "show", "dir": str(Path(paths[0]).parent)})
    check("dir selection", r["ok"] and r["tracks"] == 4)
    r = tagtool.run({"op": "show", "album": "test album"})
    check("album selection folds case (walk fallback, no db)",
          r["ok"] and r["tracks"] == 4, r)
    r = tagtool.run({"op": "set", "album": "nothing at all", "tags": {"genre": "x"}})
    check("an empty selection is an error, not a no-op write", not r["ok"])

    print()
    if FAILED:
        print("%d FAILED: %s" % (len(FAILED), ", ".join(FAILED)))
    else:
        print("all checks passed")
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
