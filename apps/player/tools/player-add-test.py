#!/usr/bin/env python3
"""Offscreen tests for the album-aware import step in player-add.py.

Every test is synthetic -- no network, no live slskd, no real library. The
whole environment is isolated before the module is imported: a scratch
XDG_DATA_HOME (fresh library.db), a scratch PLAYER_LIBRARY_ROOT (fake aud/),
scratch downloads and meta dirs, and a patched tagscan. The live library, the
live downloads dir, the running player and the real state files are never
touched.

Run under the player's python env (player-add.py imports main.py, which needs
mutagen + PySide6), exactly like the tool itself:

    PY=$(grep -oE '/nix/store/[^" ]+-env/bin/python3[0-9.]*' "$(command -v player)" | head -1)
    "$PY" apps/player/tools/player-add-test.py

Covers the placement contract: a download matched to the pipeline's record
(state row carrying album_artist/album/album_ref) is placed into ITS album --
found by folded tags in the live DB, by the MusicBrainz ref via the tagscan,
or created per the aud/<AlbumArtist>/<Album>/ convention -- and tagged
consistently with that folder; a file with no pipeline record and no usable
tags is parked in downloads/needs-attention/ and never silently dropped into
aud/Unknown Artist/Unknown Album. Also covers the soulseek-state.tsv key
round-trip (an MB work-list row has no spotify_id; its state entry must not
collapse onto the key "").
"""

import importlib.util
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

# --- isolate BEFORE importing the target modules (their constants are read
# --- from the environment at import time)
SCRATCH = Path(tempfile.mkdtemp(prefix="player-add-test-"))
AUD = SCRATCH / "aud"
DATA = SCRATCH / "data"
CACHE = SCRATCH / "cache"
for d in (AUD, DATA, CACHE):
    d.mkdir()
os.environ["XDG_DATA_HOME"] = str(DATA)
os.environ["XDG_CACHE_HOME"] = str(CACHE)
os.environ["PLAYER_LIBRARY_ROOT"] = str(AUD)

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "player_add", HERE / "player-add.py")
PA = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PA)

S_SPEC = importlib.util.spec_from_file_location(
    "soulseek_missing", HERE / "soulseek-missing.py")
S = importlib.util.module_from_spec(S_SPEC)
S_SPEC.loader.exec_module(S)

# point the mbid index at a scratch tagscan
TAGSCAN = SCRATCH / "tagscan.json"
PA.TAGSCAN = TAGSCAN

MBID = "11111111-2222-3333-4444-555555555555"


def check(name, cond):
    if not cond:
        raise AssertionError(f"FAIL: {name}")
    print(f"  ok: {name}")


def make_flac(path, tags=None):
    """A real audio file (ffmpeg sine) with the given tags, if any."""
    import mutagen
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-c:a", "flac", str(path)], check=True)
    if tags:
        a = mutagen.File(str(path))
        for k, v in tags.items():
            a[k] = v
        a.save()
    return path


def write_tsv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write("\t".join(header) + "\n")
        for r in rows:
            f.write("\t".join(str(r.get(c, "")) for c in header) + "\n")


# --- load_meta ---------------------------------------------------------------

def test_load_meta_new_style_rows():
    print("load_meta: new-style state rows are self-contained")
    meta = SCRATCH / "meta1"
    # an album-missing (MB) row: no spotify_id, album identity carried inline
    state_rows = [
        {"spotify_id": "", "isrc": "", "status": "queued", "user": "peer",
         "filename": r"Music\Jorge Cafrune\Solo chacareras\05 La vieja.mp3",
         "when": "2026-08-03 10:00:00",
         "artists": "Jorge Cafrune", "title": "La vieja",
         "album_artist": "Jorge Cafrune", "album": "Solo chacareras",
         "year": "1972", "album_ref": MBID},
        # an old-style row: spotify_id only, joined through missing.tsv
        {"spotify_id": "S1", "isrc": "", "status": "queued", "user": "p2",
         "filename": "02 Together Forever.flac",
         "when": "2026-08-01 10:00:00"},
    ]
    write_tsv(meta / "soulseek-state.tsv",
              S.STATE_COLS, state_rows)
    write_tsv(meta / "missing.tsv",
              ["artists", "title", "album", "year", "duration_ms", "isrc",
               "spotify_id", "sources"],
              [{"artists": "Rick Astley", "title": "Together Forever",
                "album": "Whenever You Need Somebody", "year": "1987",
                "spotify_id": "S1"}])
    m = PA.load_meta(meta)
    r1 = m.get("05 La vieja.mp3")
    check("MB row maps by peer basename", r1 is not None)
    check("MB row carries the album identity",
          r1["album_artist"] == "Jorge Cafrune" and r1["album"] == "Solo chacareras")
    check("MB row carries the ref", r1["album_ref"] == MBID)
    check("MB row carries track fields", r1["artists"] == "Jorge Cafrune"
          and r1["title"] == "La vieja")
    r2 = m.get("02 Together Forever.flac")
    check("old-style row joins through missing.tsv",
          r2 is not None and r2["album"] == "Whenever You Need Somebody"
          and r2["artists"] == "Rick Astley")


# --- build_album_index / resolve_dest ---------------------------------------

def make_db(rows):
    con = sqlite3.connect(":memory:")
    con.execute("""CREATE TABLE tracks (path TEXT, artist TEXT, album TEXT,
                   album_artist TEXT)""")
    for r in rows:
        con.execute("INSERT INTO tracks VALUES (:path, :artist, :album, :album_artist)", r)
    return con


def test_build_album_index():
    print("build_album_index")
    con = make_db([
        {"path": str(AUD / "Jorge Cafrune" / "Solo chacareras" / "01 La telesita.flac"),
         "artist": "Jorge Cafrune", "album": "Solo chacareras",
         "album_artist": "Jorge Cafrune"},
        {"path": str(AUD / "Various Artists" / "Secret Selection" / "01 X.mp3"),
         "artist": "VentureX", "album": "Secret Selection",
         "album_artist": "Various Artists"},
    ])
    exact, token, dominant = PA.build_album_index(con)
    check("exact key maps to the album dir",
          str(AUD / "Jorge Cafrune" / "Solo chacareras")
          in exact[("jorge cafrune", "solo chacareras")])
    check("token key covers the compilation",
          str(AUD / "Various Artists" / "Secret Selection")
          in token[("various", "secret selection")])
    check("dominant identity per dir",
          dominant[str(AUD / "Jorge Cafrune" / "Solo chacareras")]
          == ("Jorge Cafrune", "Solo chacareras"))
    con.close()


def test_resolve_dest():
    print("resolve_dest")
    # the folders that count as "live on disk" for this test
    (AUD / "Jorge Cafrune" / "Solo chacareras").mkdir(parents=True, exist_ok=True)
    (AUD / "Jorge Cafrune" / "Solo chacareras (2016)").mkdir(parents=True, exist_ok=True)
    (AUD / "Jorge Cafrune & Marito" / "Que seas vos").mkdir(parents=True, exist_ok=True)
    con = make_db([
        {"path": str(AUD / "Jorge Cafrune" / "Solo chacareras" / "01 La telesita.flac"),
         "artist": "Jorge Cafrune", "album": "Solo chacareras",
         "album_artist": "Jorge Cafrune"},
    ])
    index = PA.build_album_index(con)
    con.close()
    # 1. exact folded match -> the existing folder, with its own identity
    d, fa, fal = PA.resolve_dest(AUD, "Jorge Cafrune", "solo chacareras",
                                 index, {}, MBID)
    check("exact match finds the album folder",
          d == AUD / "Jorge Cafrune" / "Solo chacareras")
    check("folder identity is the folder's own tags",
          (fa, fal) == ("Jorge Cafrune", "Solo chacareras"))
    # 1b. a stale DB path (folder renamed since the last rescan) must not win
    # over a live one: both candidates sort before/after each other, only one
    # exists on disk
    con1b = make_db([
        {"path": str(AUD / "Jorge Cafrune" / "solo chacareras" / "01 X.flac"),
         "artist": "Jorge Cafrune", "album": "solo chacareras",
         "album_artist": "Jorge Cafrune"},
        {"path": str(AUD / "Jorge Cafrune" / "Solo chacareras" / "01 Y.flac"),
         "artist": "Jorge Cafrune", "album": "Solo chacareras",
         "album_artist": "Jorge Cafrune"},
    ])
    idx1b = PA.build_album_index(con1b)
    con1b.close()
    check("a live folder beats a stale one",
          PA.resolve_dest(AUD, "Jorge Cafrune", "solo chacareras",
                          idx1b, {}, "")[0] == AUD / "Jorge Cafrune"
          / "Solo chacareras")
    # 2. tag spelling variant -> the MusicBrainz ref finds it via tagscan
    TAGSCAN.write_text(
        '[{"path": "%s", "album_mbid": "%s"}]'
        % (AUD / "Jorge Cafrune" / "Solo chacareras (2016)" / "01 La telesita.flac", MBID))
    mbid_dirs = PA.load_mbid_dirs()
    check("tagscan mbid index built", mbid_dirs.get(MBID) is not None)
    d2, fa2, fal2 = PA.resolve_dest(AUD, "Jorge Cafrune", "Solo Chacareras 2016",
                                    index, mbid_dirs, MBID)
    check("mbid match wins over the spelling gap",
          d2 == AUD / "Jorge Cafrune" / "Solo chacareras (2016)")
    # the mbid-matched folder has no DB rows here, so its identity falls back
    # to the pipeline record's (a real variant folder has DB rows and gets its
    # own tags from the dominant map instead)
    check("identity falls back to the record for an unknown folder",
          (fa2, fal2) == ("Jorge Cafrune", "Solo Chacareras 2016"))
    # 3. shared-artist-token fallback
    con2 = make_db([
        {"path": str(AUD / "Jorge Cafrune & Marito" / "Que seas vos" / "02 X.flac"),
         "artist": "Jorge Cafrune & Marito", "album": "Que seas vos",
         "album_artist": "Jorge Cafrune & Marito"},
    ])
    idx2 = PA.build_album_index(con2)
    con2.close()
    d3, _, _ = PA.resolve_dest(AUD, "Jorge Cafrune", "Que seas vos", idx2, {}, "")
    check("shared-token artist finds the folder",
          d3 == AUD / "Jorge Cafrune & Marito" / "Que seas vos")
    # 4. no files at all -> the convention folder is created
    d4, fa4, fal4 = PA.resolve_dest(AUD, "Twell", "Confero", index, {}, "")
    check("new album -> aud/<AlbumArtist>/<Album>",
          d4 == AUD / "Twell" / "Confero")
    check("new album keeps the record's identity",
          (fa4, fal4) == ("Twell", "Confero"))


# --- meta_for_file -----------------------------------------------------------

def test_meta_for_file():
    print("meta_for_file")
    m = {"artists": "Jorge Cafrune", "title": "La vieja",
         "album_artist": "Jorge Cafrune", "album": "Solo chacareras",
         "year": "1972"}
    bare = PA.meta_for_file({}, m, "Jorge Cafrune", "Solo chacareras")
    check("bare file gets title/artist/album identity/year",
          bare.get("title") == "La vieja" and bare.get("artists") == "Jorge Cafrune"
          and bare.get("album") == "Solo chacareras"
          and bare.get("album_artist") == "Jorge Cafrune"
          and bare.get("year") == "1972")
    # read_tags falls back to the filename stem as title when the tag is
    # missing; a stem-equal title is still bare, not a real tag
    stem_title = PA.meta_for_file(
        {"artist": None, "title": "05 La vieja"}, m, "Jorge Cafrune",
        "Solo chacareras", stem="05 La vieja")
    check("a stem-derived title is treated as bare",
          stem_title.get("title") == "La vieja"
          and stem_title.get("artists") == "Jorge Cafrune")
    agreeing = PA.meta_for_file(
        {"artist": "Jorge Cafrune", "title": "La vieja",
         "album": "Solo Chacareras", "album_artist": "Jorge Cafrune",
         "year": "1972"}, m, "Jorge Cafrune", "Solo chacareras")
    check("agreeing tags need no write", agreeing == {})
    disagree = PA.meta_for_file(
        {"artist": "Jorge Cafrune", "title": "La vieja",
         "album": "Some Other Album", "album_artist": "Someone Else"},
        m, "Jorge Cafrune", "Solo chacareras")
    check("mis-tagged file gets the album identity corrected",
          disagree.get("album") == "Solo chacareras"
          and disagree.get("album_artist") == "Jorge Cafrune")
    check("title/artist are not clobbered when present",
          "title" not in disagree and "artists" not in disagree)


# --- soulseek-state.tsv key round-trip (the MB collision fix) ----------------

def test_state_key_roundtrip():
    print("soulseek-state key round-trip for MB rows")
    meta = SCRATCH / "meta2"
    meta.mkdir(exist_ok=True)
    state_path = str(meta / "soulseek-state.tsv")
    rows = [
        {"spotify_id": "", "isrc": "", "status": "queued", "user": "p1",
         "filename": r"a\01 X.mp3", "when": "t",
         "artists": "Jorge Cafrune", "title": "La vieja",
         "album_artist": "Jorge Cafrune", "album": "Solo chacareras",
         "year": "1972", "album_ref": MBID},
        {"spotify_id": "", "isrc": "", "status": "nofind", "user": "",
         "filename": "", "when": "t",
         "artists": "Rick Astley", "title": "Never Gonna Give You Up",
         "album_artist": "Rick Astley", "album": "Whenever You Need Somebody",
         "year": "1987", "album_ref": ""},
        {"spotify_id": "S1", "isrc": "", "status": "queued", "user": "p2",
         "filename": "02 B.mp3", "when": "t"},
    ]
    state = {S.track_key(r): r for r in rows}
    S.save_state(state_path, state)
    loaded = S.load_state(state_path)
    check("two MB rows stay distinct keys",
          len(loaded) == 3 and "" not in loaded)
    check("MB row round-trips its album identity",
          loaded["Jorge Cafrune||La vieja"]["album"] == "Solo chacareras"
          and loaded["Jorge Cafrune||La vieja"]["album_ref"] == MBID)
    check("nofind MB row round-trips its status",
          loaded["Rick Astley||Never Gonna Give You Up"]["status"] == "nofind")
    check("spotify-keyed row round-trips",
          loaded["S1"]["filename"] == "02 B.mp3")


# --- end to end: main() against a scratch library ----------------------------

def test_main_end_to_end():
    print("main(): placement end to end")
    dl = SCRATCH / "dl"
    meta = SCRATCH / "meta3"
    dl.mkdir()
    meta.mkdir()
    os.makedirs(AUD / "Jorge Cafrune" / "Solo chacareras", exist_ok=True)

    # the album already has one track in the library (its folder exists)
    make_flac(AUD / "Jorge Cafrune" / "Solo chacareras" / "01 La telesita.flac",
              {"artist": "Jorge Cafrune", "title": "La telesita",
               "album": "Solo chacareras", "albumartist": "Jorge Cafrune"})
    con = PA.P.open_db()
    now = 1000.0
    con.execute(
        "INSERT INTO tracks (path, mtime, size, title, artist, album,"
        " album_artist, added_at) VALUES (?,?,?,?,?,?,?,?)",
        (str(AUD / "Jorge Cafrune" / "Solo chacareras" / "01 La telesita.flac"),
         now, 100, "La telesita", "Jorge Cafrune", "Solo chacareras",
         "Jorge Cafrune", now))
    con.commit()
    con.close()

    # downloads: one bare MB-tracked file, one mis-tagged tracked file, one
    # bare untracked file, one tagged untracked file
    make_flac(dl / "05 La vieja.flac")  # bare, tracked -> album folder + tagged
    make_flac(dl / "03 La olvidada.flac",
              {"artist": "Jorge Cafrune", "title": "La olvidada",
               "album": "Wrong Album", "albumartist": "Wrong Artist"})
    make_flac(dl / "mystery-tune.flac")  # bare, untracked -> needs-attention
    make_flac(dl / "Hand Drop.flac",
              {"artist": "Some Artist", "title": "Some Title",
               "album": "Some Album", "albumartist": "Some Artist"})

    state_rows = [
        {"spotify_id": "", "isrc": "", "status": "queued", "user": "peer",
         "filename": r"Music\Jorge Cafrune\Solo chacareras\05 La vieja.flac",
         "when": "2026-08-03 10:00:00",
         "artists": "Jorge Cafrune", "title": "La vieja",
         "album_artist": "Jorge Cafrune", "album": "Solo chacareras",
         "year": "1972", "album_ref": MBID},
        {"spotify_id": "", "isrc": "", "status": "queued", "user": "peer",
         "filename": r"Music\Jorge Cafrune\Solo chacareras\03 La olvidada.flac",
         "when": "2026-08-03 10:00:00",
         "artists": "Jorge Cafrune", "title": "La olvidada",
         "album_artist": "Jorge Cafrune", "album": "Solo chacareras",
         "year": "1972", "album_ref": MBID},
    ]
    write_tsv(meta / "soulseek-state.tsv", S.STATE_COLS, state_rows)
    write_tsv(meta / "missing.tsv",
              ["artists", "title", "album", "year", "duration_ms", "isrc",
               "spotify_id", "sources"], [])

    args = ["--downloads-dir", str(dl), "--meta-dir", str(meta)]
    # run main() with argv patched
    old_argv = sys.argv
    sys.argv = ["player-add.py"] + args
    try:
        PA.main()
    finally:
        sys.argv = old_argv

    dest = AUD / "Jorge Cafrune" / "Solo chacareras"
    check("bare tracked file moved into the album folder",
          (dest / "05 La vieja.flac").is_file()
          and not (dl / "05 La vieja.flac").exists())
    check("mis-tagged tracked file moved into the album folder",
          (dest / "03 La olvidada.flac").is_file())
    check("bare untracked file parked, not in aud/",
          (dl / "needs-attention" / "mystery-tune.flac").is_file()
          and not list(AUD.glob("Unknown Artist/*")))
    check("tagged untracked file placed by its own tags",
          (AUD / "Some Artist" / "Some Album" / "Hand Drop.flac").is_file())

    t5 = PA.P.read_tags(str(dest / "05 La vieja.flac"))
    check("bare file was tagged from the pipeline record",
          t5.get("artist") == "Jorge Cafrune" and t5.get("title") == "La vieja"
          and t5.get("album") == "Solo chacareras"
          and t5.get("album_artist") == "Jorge Cafrune")
    t3 = PA.P.read_tags(str(dest / "03 La olvidada.flac"))
    check("mis-tagged file's album identity corrected to the folder's",
          t3.get("album") == "Solo chacareras"
          and t3.get("album_artist") == "Jorge Cafrune")
    check("mis-tagged file's title/artist kept",
          t3.get("title") == "La olvidada" and t3.get("artist") == "Jorge Cafrune")

    # the DB now groups the album with three tracks
    con = PA.P.open_db()
    n = con.execute(
        "SELECT COUNT(*) FROM tracks WHERE album='Solo chacareras'").fetchone()[0]
    con.close()
    check("rescan added the new tracks to the album", n == 3)

    # a second run does not re-park or re-move anything (needs-attention is
    # excluded from the walk, and imports are idempotent)
    sys.argv = ["player-add.py"] + args
    try:
        PA.main()
    finally:
        sys.argv = old_argv
    check("needs-attention file not re-scanned",
          len(list((dl / "needs-attention").iterdir())) == 1)
    check("already-imported files not re-moved",
          (dest / "05 La vieja.flac").is_file())


def main():
    test_load_meta_new_style_rows()
    test_build_album_index()
    test_resolve_dest()
    test_meta_for_file()
    test_state_key_roundtrip()
    test_main_end_to_end()
    print("\nPASS: player-add album-placement suite")


if __name__ == "__main__":
    main()
