#!/usr/bin/env python3
"""Synthetic, read-only throughput check for apps/player/relatedmusic.py."""

import argparse
import sys
import time
from pathlib import Path


def track(number):
    return {
        "id": number, "title": f"Song {number % 1000}",
        "artist": f"Artist {number % 500}", "album": f"Album{number % 2000}",
        "album_artist": f"Artist {number % 500}", "genre": "electronic",
        "year": 2000 + number % 20, "track": number % 12 + 1,
        "disc": number % 2 + 1,
        "identity_json": {"releaseId": f"rel-{number % 2000}",
                          "recordingId": f"rec-{number}",
                          "releaseTrackId": f"rt-{number}"},
    }


def album(number):
    return {
        "musicbrainzReleaseId": f"rel-{number}", "title": f"Album{number}",
        "artist": f"Artist {number % 500}", "credits": [{
            "id": f"p-{number % 50}", "name": f"P{number % 50}",
            "role": "producer", "scope": "track", "disc": 1,
            "trackPosition": 1, "trackTitle": "Song 1",
        }], "labels": [],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracks", type=int, default=20_000)
    parser.add_argument("--albums", type=int, default=1_000)
    parser.add_argument("--remote", type=int, default=100)
    args = parser.parse_args()
    if args.tracks < 1 or args.albums < 0 or args.remote < 0:
        parser.error("tracks must be positive; albums and remote must be nonnegative")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from relatedmusic import related_tracks

    tracks = [track(number) for number in range(args.tracks)]
    target = dict(tracks[0])
    target["identity_json"] = {"releaseId": "rel-0", "recordingId": "target",
                                "releaseTrackId": "targetrt"}
    tracks[0] = target
    albums = [album(number) for number in range(args.albums)]
    remote = [{"name": f"Song {number % 1000}",
               "artist": {"name": f"Artist {number % 500}"}, "match": "0.8"}
              for number in range(args.remote)]
    started = time.perf_counter()
    result = related_tracks(target, tracks, remote, albums[0] if albums else {}, albums, 20)
    elapsed = time.perf_counter() - started
    print(f"tracks={args.tracks} albums={args.albums} remote={args.remote} "
          f"seconds={elapsed:.3f} owned={len(result['owned'])}")


if __name__ == "__main__":
    main()
