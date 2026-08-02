#!/usr/bin/env python3
"""Prove the work list is likes + saved albums ONLY -- never playlist tracks.

The library was over-collecting: `unique_spotify_tracks` folded every
playlist's tracks into the Soulseek work list, so a song that was neither a
like nor on a wanted album got downloaded merely because it sat in a playlist
("Light and Sound" by Luke Million was the reported case). The wanted library
is the liked tracks + the albums they come from (grown by soulseek-missing's
--albums pass) + explicitly saved albums; a playlist is a listening context,
not a collection. This locks that in.

Stdlib only, no Qt, no network, no live library -- imports the tool as a
module and drives unique_spotify_tracks with a synthetic dump.
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("spotify_missing", HERE / "spotify-missing.py")
sm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sm)


def track(title, artist, album, source=None, playlist=None):
    r = {"title": title, "artists": artist, "album": album,
         "album_artist": artist, "year": "2020", "duration_ms": 200000,
         "isrc": "", "spotify_id": f"id::{title}", "is_local": False}
    if source:
        r["source"] = source
    if playlist:
        r["playlist"] = playlist
    return r


def titles(rows):
    return {r["title"] for r in rows}


def run():
    data = {
        "saved_tracks": [
            track("Hero", "Pegboard Nerds", "Hero", source="saved"),
            # a like (its own saved row has no playlist tag, as the real dump)
            track("Faded", "Alan Walker", "Different World", source="saved"),
        ],
        "saved_albums": [
            {"name": "Random Access Memories", "artists": "Daft Punk",
             "tracks": [track("Get Lucky", "Daft Punk", "Random Access Memories",
                              source="Random Access Memories")]},
        ],
        "playlists": [
            {"name": "indiana academy of smh", "tracks": [
                # pure playlist track -- the exact bug -- must be EXCLUDED
                track("Light and Sound", "Luke Million", "Light & Sound - EP",
                      source="playlist", playlist="indiana academy of smh"),
                # the same song a like sits in a playlist too: must survive as a
                # like, tagged 'saved' -- never the playlist name
                track("Faded", "Alan Walker", "Different World",
                      source="playlist", playlist="roadtrip"),
            ]},
        ],
    }

    out = titles(sm.unique_spotify_tracks(data))
    fails = []

    if "Light and Sound" in out:
        fails.append("playlist-only track 'Light and Sound' leaked into the work list")
    for keep in ("Hero", "Get Lucky", "Faded"):
        if keep not in out:
            fails.append(f"wanted track {keep!r} missing from the work list")

    # a like present in a playlist must NOT be tagged with the playlist source,
    # or it stops looking like a pure 'saved' single and never gets fleshed out
    rows = sm.unique_spotify_tracks(data)
    faded = next(r for r in rows if r["title"] == "Faded")
    if faded.get("_sources", []) != ["saved"]:
        fails.append(f"liked-and-in-playlist track mis-tagged: {faded.get('_sources')}")

    if fails:
        for f in fails:
            print("FAIL:", f)
        print(f"\n{len(fails)} failure(s)")
        return 1
    print(f"ok: work list = {sorted(out)} (playlist-only 'Light and Sound' excluded)")
    print("4/4 passed")
    return 0


if __name__ == "__main__":
    sys.exit(run())
