#!/usr/bin/env python3
"""Offscreen tests for the whole-album fleshing of single liked tracks in
soulseek-missing.py.

Every test is synthetic -- no network, no live slskd, no player. It builds
fake /searches responses in the exact shape slskd returns (a list of
{username, files:[{filename,size,...}]}) and drives the pure helpers:
liked_single, album_key, _primary_artist, _album_match, _title_from_leaf,
best_album_folder, and one mocked-search run of do_album_flesh.

Runs under a bare python3 on either host; imports the target module via
importlib because its filename (soulseek-missing.py) is not a valid identifier.

    python3 apps/player/tools/soulseek-album-flesh-test.py
"""

import importlib.util
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "soulseek_missing", HERE / "soulseek-missing.py")
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


def check(name, cond):
    if not cond:
        raise AssertionError(f"FAIL: {name}")
    print(f"  ok: {name}")


def liked(sid, title, sources="saved", album="Whenever You Need Somebody"):
    return {"spotify_id": sid, "isrc": "", "artists": "Rick Astley",
            "title": title, "album": album, "album_artist": "Rick Astley",
            "year": "1987", "duration_ms": "213000", "sources": sources}


def album_response(user, files, **extra):
    return {"username": user, "files": [{"filename": fn, "size": sz}
                                        for fn, sz in files], **extra}


def test_liked_single():
    print("liked_single")
    check("a pure liked track is a flesh candidate",
          S.liked_single(liked("S1", "Never Gonna Give You Up")))
    check("a liked track also in a saved album is not (already expanded)",
          not S.liked_single(liked("S1", "T", sources="saved; Whenever You "
                                        "Need Somebody")))
    check("a liked track also in a playlist is not",
          not S.liked_single(liked("S1", "T", sources="saved; my playlist")))
    check("an album-expansion row is not",
          not S.liked_single(liked("S1", "T", sources="Whenever You Need "
                                                     "Somebody")))
    check("a blank sources row is not",
          not S.liked_single(liked("S1", "T", sources="")))
    check("surrounding whitespace is tolerated",
          S.liked_single({"sources": "  saved  "}))


def test_primary_artist():
    print("_primary_artist")
    check("prefers album_artist",
          S._primary_artist({"album_artist": "Rick Astley",
                             "artists": "Rick Astley, X"}) == "Rick Astley")
    check("falls back to the full artist string (album lives under the duo)",
          S._primary_artist({"album_artist": "",
                             "artists": "A & B"}) == "A & B")
    check("empty falls back to empty", S._primary_artist({}) == "")


def test_album_key():
    print("album_key")
    check("groups by folded artist + album",
          S.album_key(liked("S1", "Never Gonna Give You Up"))
          == S.album_key(liked("S9", "together forever")))
    check("a different album is a different group",
          S.album_key(liked("S1", "T", album="Other"))
          != S.album_key(liked("S1", "T", album="Whenever You Need Somebody")))


def test_album_match():
    print("_album_match")
    check("matches the album folder", S._album_match("Whenever You Need Somebody",
                                                     "Whenever You Need Somebody"))
    check("matches a substring folder", S._album_match("Whenever You Need Somebody",
                                                       "Whenever You Need Somebody "
                                                       "(2019)"))
    check("rejects a short/common word", not S._album_match("hit",
                                                            "Whenever You Need Somebody"))
    check("rejects an unrelated folder", not S._album_match("Nevermind",
                                                            "Whenever You Need Somebody"))


def test_title_from_leaf():
    print("_title_from_leaf")
    check("strips the leading track number",
          S._title_from_leaf("02 - Harder, Better.mp3") == "harder better")
    check("handles '01 Never...' with no dash",
          S._title_from_leaf("01 Never Gonna Give You Up.flac")
          == "never gonna give you up")
    check("handles a bare title", S._title_from_leaf("Rock Me.mp3") == "rock me")


def _folder_response():
    base = "Music\\Rick Astley\\Whenever You Need Somebody"
    return album_response(
        "albumpeer",
        [(f"{base}\\01 Never Gonna Give You Up.mp3", 100),
         (f"{base}\\02 Together Forever.flac", 200),
         (f"{base}\\03 Some Deep Cut.mp3", 300),
         (f"{base}\\folder.jpg", 50)])


def test_best_album_folder_finds_and_dedups():
    print("best_album_folder: finds the album, dedups library/downloaded/queued")
    resp = _folder_response()
    album = "Whenever You Need Somebody"
    art = "Rick Astley"
    # nothing already owned -> all three audio files wanted (folder.jpg skipped)
    cand = S.best_album_folder([resp], album, art, set(), set(), set())
    check("picks the album peer", cand is not None and cand[0] == "albumpeer")
    check("folder_artist is the album's parent dir",
          cand[1] == "Rick Astley")
    check("three audio files wanted, the jpg skipped", len(cand[2]) == 3)

    # a library entry covering track 02 -> it is dropped
    present = set(S.trackmatch.keys("Rick Astley", "Together Forever"))
    cand2 = S.best_album_folder([resp], album, art, present, set(), set())
    check("library dedup drops the owned track", len(cand2[2]) == 2)
    check("the owned track is not among the grabs",
          all("Together Forever" not in fn for fn, _ in cand2[2]))

    # a completed file awaiting import -> dropped by folded basename
    downloaded = {S.trackmatch.fold("03 Some Deep Cut.mp3")}
    cand3 = S.best_album_folder([resp], album, art, set(), downloaded, set())
    check("downloads-dir dedup drops the awaiting-import file",
          len(cand3[2]) == 2)
    check("the awaiting file is not among the grabs",
          all("Some Deep Cut" not in fn for fn, _ in cand3[2]))

    # already queued from this peer -> dropped
    queued = {( "albumpeer",
                f"Music\\Rick Astley\\Whenever You Need Somebody\\"
                f"01 Never Gonna Give You Up.mp3")}
    cand4 = S.best_album_folder([resp], album, art, set(), set(), queued)
    check("already-queued file is dropped", len(cand4[2]) == 2)


def test_best_album_folder_parent_matches_artist_wins():
    print("best_album_folder: an artist-parented folder beats a nameless one")
    album = "Whenever You Need Somebody"
    art = "Rick Astley"
    parented = album_response(
        "peerA",
        [(f"Music\\Rick Astley\\Whenever You Need Somebody\\01 X.mp3", 1)])
    nameless = album_response(
        "peerB",
        [(f"Whenever You Need Somebody\\02 Y.mp3", 1)])
    cand = S.best_album_folder([parented, nameless], album, art, set(), set(), set())
    check("the artist-parented folder wins over a bare album folder",
          cand is not None and cand[0] == "peerA")
    # flip the order; the parented folder still wins
    cand2 = S.best_album_folder([nameless, parented], album, art, set(), set(), set())
    check("order-independent", cand2 is not None and cand2[0] == "peerA")
    # if the parented peer is skipped, the nameless one is still used (bias, not refusal)
    cand3 = S.best_album_folder([parented, nameless], album, art, set(), set(),
                                set(), skip_users={"peerA"})
    check("with the good peer blocked, the remaining folder is used",
          cand3 is not None and cand3[0] == "peerB")


def test_best_album_folder_no_match():
    print("best_album_folder: no album folder returns None")
    other = album_response("peerX", [(r"Music\Different\NotTheAlbum\01 Z.mp3", 1)])
    check("an unrelated folder is not picked",
          S.best_album_folder([other], "Whenever You Need Somebody", "Rick Astley",
                              set(), set(), set()) is None)
    check("empty responses return None",
          S.best_album_folder([], "Whenever You Need Somebody", "Rick Astley",
                              set(), set(), set()) is None)


def test_do_album_flesh_claims_and_enqueues(tmp_path):
    print("do_album_flesh: one search, enqueues the folder, claims the rows")
    row1 = liked("S1", "Never Gonna Give You Up")
    row2 = liked("S2", "Together Forever")
    row3 = {**liked("S3", "Other Song", sources="playlist:mine"), "album": "Other"}
    net = [row1, row2, row3]

    os.makedirs(tmp_path, exist_ok=True)
    state_path = str(tmp_path / "soulseek-state.tsv")
    S.save_state(state_path, {})  # seed a valid file (empty)

    base = "http://x"; api_key = "k"
    downloaded = set(); queued_files = set()
    present = set(); blocked = set(); stall_avoid = {}
    run_user_counts = {}
    requested = set()
    state = {}
    enqueued_calls = []

    def fake_http(method, url, key, body=None):
        if method == "POST" and "/searches" in url:
            return {"id": "s1"}
        if method == "GET" and url.endswith("/responses"):
            base_dir = "Music\\Rick Astley\\Whenever You Need Somebody"
            return [{"username": "albumpeer",
                     "files": [{"filename": f"{base_dir}\\01 Never Gonna Give You Up.mp3", "size": 100},
                               {"filename": f"{base_dir}\\02 Together Forever.flac", "size": 200}]}]
        if method == "GET" and "/searches/s1" in url:
            return {"state": "Completed"}
        if method == "POST" and "/transfers/downloads/" in url:
            enqueued_calls.append((url, body))
            return None
        raise AssertionError(f"unexpected call: {method} {url}")

    orig_http = S.http
    S.http = fake_http
    try:
        args = type("A", (), {"albums": 3, "all": False, "search_timeout": 5,
                              "dry_run": False})()
        new_net = S.do_album_flesh(args, api_key, base, state_path, state,
                                   present, requested, net, queued_files,
                                   downloaded, blocked, stall_avoid,
                                   run_user_counts)
    finally:
        S.http = orig_http

    check("the two liked rows were claimed (state marked queued)",
          state.get("S1", {}).get("status") == "queued"
          and state.get("S2", {}).get("status") == "queued")
    check("the two liked rows were claimed and removed",
          all("S1" != r["spotify_id"] and "S2" != r["spotify_id"] for r in new_net))
    check("the non-liked row stays", any(r["spotify_id"] == "S3" for r in new_net))
    check("both album files were enqueued", len(enqueued_calls) == 2)
    check("enqueue targeted the album peer",
          all("albumpeer" in u for u, _ in enqueued_calls))
    check("queued_files reflects the enqueues", len(queued_files) == 2)


def main():
    import tempfile
    test_liked_single()
    test_primary_artist()
    test_album_key()
    test_album_match()
    test_title_from_leaf()
    test_best_album_folder_finds_and_dedups()
    test_best_album_folder_parent_matches_artist_wins()
    test_best_album_folder_no_match()
    test_do_album_flesh_claims_and_enqueues(Path(tempfile.mkdtemp(prefix="soulseek-album-test-")))
    print("\nPASS: album-flesh suite")


if __name__ == "__main__":
    main()
