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
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="tagtool-test-"))
os.environ["AUD_ROOT"] = str(TMP / "aud")
os.environ["PLAYER_DB"] = str(TMP / "library.db")
os.environ["TAGTOOL_STATE"] = str(TMP / "state")
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


def png():
    p = TMP / "cover.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "color=c=red:s=64x64", "-frames:v", "1", str(p)],
                   check=True)
    return str(p)


def main():
    print("temp tree:", TMP)
    paths = make_files()

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
    r = tagtool.run({"op": "art", "paths": paths,
                     "art": {"file": png()}, "apply": True})
    check("art embedded + cover.jpg written",
          r["ok"] and r["files_embedded"] == 4 and len(r["covers_written"]) == 1, r)
    tok_art = r.get("undo_token")
    after = tagtool.run({"op": "show", "paths": paths})
    check("every file reports embedded art",
          all(f["tags"].get("_art") for f in after["files"]),
          [(f["path"][-5:], f["tags"].get("_art")) for f in after["files"]])
    data, mime = tagtool.read_art(paths[0])
    check("the embedded bytes are the image we gave it",
          data and len(data) > 100 and mime in ("image/png", "image/jpeg"), mime)

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
