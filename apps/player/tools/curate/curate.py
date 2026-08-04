#!/usr/bin/env python3
"""Library curation pipeline for /run/media/lam/SSD/aud.

    scan     walk the library, read tags + audio quality -> ~/.cache/library-curate/scan.json
    dupes    find same-track copies (same normalized artist+title, matching
             duration) anywhere in the library; keep the best-quality copy,
             MOVE the rest to ~/Music-removed/duplicates/. Real work; not a
             dry run (there is no confirmation step downstream of this repo).
    groups   detect album-directory groups that are really ONE album split
             across several directories (same album, different folder — a
             literal reissue split, or an artist-credit variant) -> a report
             for the next stage to act on. Report only; does not move files.

Run with the player's wrapped python (has mutagen):
  PY=$(grep -oE '/nix/store/[^" ]+-env/bin/python3[0-9.]*' "$(command -v player)" | head -1)
  $PY curate.py scan
"""
import collections
import difflib
import json
import os
import sys
import time

import common as C
import trackmatch


def cmd_scan(_args):
    import mutagen  # noqa: F401  (only this step needs it)
    out = []
    n = 0
    t0 = time.time()
    for absp, rel in C.reorg.walk_root():
        ext = os.path.splitext(absp)[1].lower()
        if ext not in C.reorg.AUDIO_EXTS:
            continue
        n += 1
        tags = C.reorg.read_tags(absp)
        if tags is None:
            continue
        br, sr, dur = C.audio_info(absp)
        parts = rel.split(os.sep)
        out.append({
            "path": absp, "rel": rel,
            "album_artist_dir": parts[0] if len(parts) > 1 else None,
            "album_dir": parts[1] if len(parts) > 2 else None,
            "title": tags["title"], "artist": tags["artist"],
            "album": tags["album"], "album_artist": tags["album_artist"],
            "track": tags["track"], "disc": tags["disc"],
            "date": tags["date"], "year": tags["year"],
            "bitrate": br, "sample_rate": sr, "dur": round(dur, 2) if dur else None,
            "mtime": os.path.getmtime(absp),
        })
        if n % 2000 == 0:
            print(f"  {n} files scanned ({time.time()-t0:.0f}s)", flush=True)
    C.SCAN_JSON.write_text(json.dumps(out, ensure_ascii=False))
    print(f"scanned {n} audio files, {len(out)} readable -> {C.SCAN_JSON}")


def _load_scan():
    if not C.SCAN_JSON.exists():
        C.reorg.die("no scan.json yet - run `scan` first")
    return json.loads(C.SCAN_JSON.read_text())


# --- dupes -------------------------------------------------------------

def cmd_dupes(args):
    rows = _load_scan()
    by_path = {r["path"]: r for r in rows}
    groups = collections.defaultdict(list)
    for r in rows:
        artist = r["album_artist"] or r["artist"] or ""
        for k in trackmatch.keys(artist, r["title"] or ""):
            groups[k].append(r["path"])
    # union-find: a file can appear in several fold-keys, merge transitively
    parent = {p: p for p in by_path}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for members in groups.values():
        for m in members[1:]:
            union(members[0], m)
    clusters = collections.defaultdict(list)
    for p in by_path:
        clusters[find(p)].append(p)

    n_dupe_groups = n_moved = 0
    for root, paths in clusters.items():
        if len(paths) < 2:
            continue
        recs = [by_path[p] for p in paths]
        # split by duration: >6s apart is very likely a different
        # recording (live/remix/edit), not a duplicate - leave those alone.
        recs.sort(key=lambda r: r["dur"] or 0)
        bucket = [recs[0]]
        buckets = []
        for r in recs[1:]:
            if abs((r["dur"] or 0) - (bucket[-1]["dur"] or 0)) <= 6.0:
                bucket.append(r)
            else:
                buckets.append(bucket)
                bucket = [r]
        buckets.append(bucket)
        for b in buckets:
            if len(b) < 2:
                continue
            n_dupe_groups += 1
            ranked = sorted(
                b, key=lambda r: C.quality_of(r["path"], r["bitrate"], r["sample_rate"], r["dur"]),
                reverse=True)
            keep = ranked[0]
            for loser in ranked[1:]:
                reason = (f"duplicate of kept copy {keep['rel']!r} "
                          f"(quality {C.quality_of(loser['path'], loser['bitrate'], loser['sample_rate'], loser['dur'])} "
                          f"< {C.quality_of(keep['path'], keep['bitrate'], keep['sample_rate'], keep['dur'])})")
                if args.apply:
                    C.move_to_removed(loser["path"], "duplicates", reason)
                n_moved += 1
    if args.apply:
        C.flush_audit("Duplicate tracks removed")
    print(f"duplicate clusters: {n_dupe_groups}, files to move: {n_moved}"
          + ("" if args.apply else "  (dry run - pass --apply)"))


# --- groups (album-split / artist-variant detection) --------------------

def _album_dirs(rows):
    dirs = collections.defaultdict(list)
    for r in rows:
        if r["album_dir"] is None:
            continue
        key = (r["album_artist_dir"], r["album_dir"])
        dirs[key].append(r)
    return dirs


def cmd_groups(args):
    rows = _load_scan()
    dirs = _album_dirs(rows)
    # candidate identity for a directory: canonical (album_artist, album) as
    # TAGGED (fall back to folder names if tags are blank), folded.
    def identity(recs):
        aa = recs[0]["album_artist"] or recs[0]["album_artist_dir"]
        al = recs[0]["album"] or recs[0]["album_dir"]
        return aa, al

    items = []  # (dirkey, artist_raw, album_raw, artist_fold, album_fold, recs)
    for dirkey, recs in dirs.items():
        aa, al = identity(recs)
        items.append((dirkey, aa, al, C.fold(aa), C.fold(al), recs))

    # bucket by folded album title first (cheap), then fuzzy-match artist
    # within a bucket so "A, B & C" / "B, A, C" / "A feat. B, C" collapse.
    by_album = collections.defaultdict(list)
    for it in items:
        by_album[it[4]].append(it)

    report = []
    for album_fold, group in by_album.items():
        if len(group) < 2 or not album_fold:
            continue
        # cluster by artist similarity within this album-title bucket
        used = [False] * len(group)
        for i in range(len(group)):
            if used[i]:
                continue
            cluster = [group[i]]
            used[i] = True
            for j in range(i + 1, len(group)):
                if used[j]:
                    continue
                ai, aj = group[i][3], group[j][3]
                same = (ai == aj or trackmatch.artist_matches(group[i][1], group[j][1])
                        or difflib.SequenceMatcher(None, ai, aj).ratio() > 0.82)
                if same:
                    cluster.append(group[j])
                    used[j] = True
            if len(cluster) < 2:
                continue
            report.append({
                "album": cluster[0][2],
                "dirs": [{"path": f"{c[0][0]}/{c[0][1]}", "artist": c[1],
                          "n_tracks": len(c[5])} for c in cluster],
            })

    report.sort(key=lambda g: -len(g["dirs"]))
    out_path = C.STATE / "groups.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"{len(report)} album groups spread across >1 directory -> {out_path}")
    for g in report[:25]:
        print(f"  {g['album']!r}: " + " | ".join(f"{d['path']} ({d['n_tracks']}t)" for d in g["dirs"]))


CMDS = {"scan": cmd_scan, "dupes": cmd_dupes, "groups": cmd_groups}

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")
    dp = sub.add_parser("dupes")
    dp.add_argument("--apply", action="store_true")
    sub.add_parser("groups")
    a = p.parse_args()
    CMDS[a.cmd](a)
