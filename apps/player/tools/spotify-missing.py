#!/usr/bin/env python3
"""Diff a Spotify library dump against the local player library, so a
Soulseek hunt only targets what is actually missing.

Input : ~/.local/share/spotify-dump/library.json  (from spotify-dump.py)
Local : ~/.local/share/player/library.db          (snapshotted, never read live)
Output: missing.tsv, matched.tsv, suspect.tsv in the dump dir.

Matching is normalised artist+title, reusing player/lyrics.py's variant and
folding logic rather than growing a second copy that drifts from it. The local
db has no ISRC column, so ISRC (which spotify-dump.py does collect) cannot be
used here - duration is the only corroborating signal, and it is used to flag
rather than to reject:

  matched.tsv  - found locally, durations agree within tolerance
  suspect.tsv  - found locally by name, duration differs a lot (likely a
                 different edit/live/remaster - worth a look, not a redownload)
  missing.tsv  - no local match at all; this is the Soulseek work list

Stdlib only, same rationale as dbsync.py / spotify-dump.py.
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "pylib"))
import trackmatch  # noqa: E402

DUMP_DIR = os.path.expanduser("~/.local/share/spotify-dump")
LIBRARY_DB = os.path.expanduser("~/.local/share/player/library.db")

# Durations that differ by more than this are probably not the same recording.
DURATION_TOLERANCE = 12.0  # seconds


def snapshot_db(src, dest):
    """Copy the library with sqlite's backup API. Never `cp` - the db is WAL
    and the player may be running against it."""
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    if os.path.exists(dest):
        os.remove(dest)
    dst_conn = sqlite3.connect(dest)
    with dst_conn:
        src_conn.backup(dst_conn)
    src_conn.close()
    dst_conn.close()


keys_for = trackmatch.keys


def load_local(db_path):
    """key -> list of (artist, title, album, duration, path)"""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    index = {}
    n = 0
    for artist, title, album, dur, path in conn.execute(
        "SELECT artist, title, album, duration, path FROM tracks"
    ):
        n += 1
        rec = (artist or "", title or "", album or "", dur or 0.0, path or "")
        for k in keys_for(artist, title):
            index.setdefault(k, []).append(rec)
    conn.close()
    return index, n


def unique_spotify_tracks(data):
    """Dedupe across saved tracks + every playlist, remembering where each
    one came from."""
    rows = list(data.get("saved_tracks", []))
    for pl in data.get("playlists", []):
        rows.extend(pl.get("tracks", []))

    uniq = {}
    for r in rows:
        if r.get("is_local"):
            continue  # a local file already on the user's machine, not a fetch target
        key = r.get("isrc") or (r["artists"].lower(), r["title"].lower())
        if key in uniq:
            src = uniq[key]["_sources"]
            tag = r.get("playlist") or r.get("source", "")
            if tag and tag not in src:
                src.append(tag)
            continue
        r = dict(r)
        tag = r.get("playlist") or r.get("source", "")
        r["_sources"] = [tag] if tag else []
        uniq[key] = r
    return list(uniq.values())


COLS = ["artists", "title", "album", "year", "duration_ms", "isrc",
        "spotify_id", "sources"]


def clean(v):
    return str(v).replace("\t", " ").replace("\n", " ").replace("\r", " ")


def write_tsv(path, rows, extra_cols=()):
    cols = COLS + list(extra_cols)
    with open(path, "w") as f:
        f.write("\t".join(cols) + "\n")
        for r in rows:
            f.write("\t".join(clean(r.get(c, "")) for c in cols) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump-dir", default=DUMP_DIR)
    ap.add_argument("--db", default=LIBRARY_DB)
    args = ap.parse_args()

    jpath = os.path.join(args.dump_dir, "library.json")
    if not os.path.exists(jpath):
        raise SystemExit(f"no dump at {jpath} - run spotify-dump.py first")
    with open(jpath) as f:
        data = json.load(f)

    snap = os.path.join(args.dump_dir, "library-snapshot.db")
    print("Snapshotting the local library...")
    snapshot_db(args.db, snap)
    index, n_local = load_local(snap)
    print(f"  {n_local} local tracks, {len(index)} lookup keys")

    tracks = unique_spotify_tracks(data)
    print(f"  {len(tracks)} unique Spotify tracks")

    missing, matched, suspect = [], [], []
    for t in tracks:
        row = {c: t.get(c, "") for c in COLS if c != "sources"}
        row["sources"] = "; ".join(t.get("_sources", []))

        hits = []
        for k in keys_for(t.get("artists", ""), t.get("title", "")):
            hits.extend(index.get(k, []))
        if not hits:
            missing.append(row)
            continue

        want = (t.get("duration_ms") or 0) / 1000.0
        best = min(hits, key=lambda h: abs((h[3] or 0.0) - want))
        delta = abs((best[3] or 0.0) - want)
        row["local_path"] = best[4]
        row["local_duration"] = f"{best[3]:.0f}"
        row["delta_s"] = f"{delta:.0f}"
        if want and delta > DURATION_TOLERANCE:
            suspect.append(row)
        else:
            matched.append(row)

    extra = ("local_path", "local_duration", "delta_s")
    write_tsv(os.path.join(args.dump_dir, "missing.tsv"), missing)
    write_tsv(os.path.join(args.dump_dir, "matched.tsv"), matched, extra)
    write_tsv(os.path.join(args.dump_dir, "suspect.tsv"), suspect, extra)

    print()
    print(f"matched : {len(matched)}")
    print(f"suspect : {len(suspect)}   (name match, duration off > {DURATION_TOLERANCE:.0f}s)")
    print(f"missing : {len(missing)}   <- the Soulseek work list")
    print()
    print(f"  {os.path.join(args.dump_dir, 'missing.tsv')}")


if __name__ == "__main__":
    main()
