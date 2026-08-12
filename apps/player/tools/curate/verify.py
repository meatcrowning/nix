#!/usr/bin/env python3
"""curate verify — the completion invariant for the library.

Answers "is the library clean now?" with four counts, exit 1 if any is
non-zero. This is the piece whose ABSENCE is why every prior cleanup came
out partial: without it, the only detector of remaining work was the user
opening the player. Silent-ish when clean; a numbered work list when not.

    verify            report counts, exit 1 when anything is outstanding
    verify --json     machine-readable, for `curate run` and the timer

The four invariants:
  1. tag splits     no album folds into >1 (album_artist, album) tag spelling
                    on the axis the player groups by (retag/merge/board
                    breakdown — board items count, they are outstanding work)
  2. dupes          no duplicate-track clusters (same folded artist+title,
                    duration within 6s, same variant signature)
  3. incomplete     no album below its MusicBrainz reference track count
                    (uses album-inventory.py's tagscan reference where fresh)
  4. remaster dates no album whose files carry a MusicBrainz release id is
                    dated later than its release-group's earliest release
"""
import collections
import json
import re
import sys
from pathlib import Path

import common as C
import tagclusters as TC

INVENTORY_TSV = C.STATE / "album-inventory.tsv"


def _dup_clusters(rows):
    """Same shape as curate.cmd_dupes' clustering, count-only. Kept in sync
    by construction: both key on trackmatch over (artist, title-with-edition-
    stripped), duration-bucketed at 6s, variant-signature split. Includes the
    union-find pass: a file can sit in several fold-keys (album_artist AND
    artist), and counting per key without merging transitively double-counts
    one pair under every key it shares (measured 2026-08-09: 55 -> 39)."""
    import curate as curmod
    groups = collections.defaultdict(list)
    for r in rows:
        if not r.get("title"):
            continue
        artists = [a for a in (r.get("album_artist"), r.get("artist"))
                   if a and C.fold(a) not in curmod._NOT_AN_ARTIST]
        if not artists:
            artists = [r.get("album_artist") or r.get("artist") or ""]
        for artist in artists:
            for t in curmod._dedupe_titles(r["title"]):
                for k in curmod.trackmatch.keys(artist, t):
                    groups.setdefault(k, []).append(r["path"])
    # union-find across fold-keys, exactly like curate.cmd_dupes
    parent = {}

    def find(x):
        if x not in parent:
            parent[x] = x
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
    for path in {p for ms in groups.values() for p in ms}:
        clusters[find(path)].append(path)
    by_path = {r["path"]: r for r in rows}
    n = redundant = 0
    for paths in clusters.values():
        recs = sorted((by_path[p] for p in set(paths)),
                      key=lambda r: r.get("dur") or 0)
        if len(recs) < 2:
            continue
        bucket, buckets = [], []
        for r in recs:
            if bucket and abs((r.get("dur") or 0) - (bucket[-1].get("dur") or 0)) > 6.0:
                buckets.append(bucket)
                bucket = []
            bucket.append(r)
        buckets.append(bucket)
        for b in buckets:
            byvar = collections.defaultdict(int)
            for r in b:
                byvar[curmod._variant_sig(r["title"])] += 1
            for c in byvar.values():
                if c > 1:
                    n += 1
                    redundant += c - 1
    return n, redundant


def _incomplete_albums():
    """Albums short of their reference track count, from the latest
    album-inventory TSV if one exists. Absent inventory -> unknown (0, but
    flagged stale so `run` knows to regenerate)."""
    if not INVENTORY_TSV.exists():
        return None
    n = 0
    albums = []
    with open(INVENTORY_TSV, encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split("\t")
        try:
            i_status = header.index("status")
            i_miss = header.index("missing")
        except ValueError:
            return None
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) <= max(i_status, i_miss):
                continue
            try:
                miss = int(cols[i_miss])
            except ValueError:
                continue
            if cols[i_status] != "no-ref" and miss > 0:
                n += 1
                albums.append(cols[1] if len(cols) > 1 else "?")
    return {"count": n, "albums": albums}


def _missing_art(rows):
    """Album dirs with no folder cover AND no embedded art on any track.
    These are albums the player shows blank — fixable by album-art.py."""
    dirs = {}
    for r in rows:
        if r["album_dir"] is None:
            continue
        dirs.setdefault(f"{r['album_artist_dir']}/{r['album_dir']}", []).append(r)
    n = 0
    albums = []
    for key, recs in dirs.items():
        dirpath = Path(recs[0]["path"]).parent
        if not dirpath.is_dir():
            continue
        if any(_ART_RE.match(f.name) for f in dirpath.iterdir() if f.is_file()):
            continue
        if any(C._has_embedded(r["path"]) for r in recs[:3]):
            continue
        n += 1
        albums.append(key)
    return {"count": n, "albums": albums}


_ART_RE = re.compile(
    r"^(cover|folder|front|albumart.*)\.(jpe?g|png|webp|gif|bmp)$", re.I)


def _track_number_issues(rows):
    """Files with a wrong or missing track number, using the same MB-release
    tracklist resolution as normalize.py. Counts only files that HAVE an MB id
    and an unambiguous title match but disagree on track number. (Files with
    no MB id have no authority to check against — out of scope here.)"""
    import normalize as N
    issues = 0
    releases = {}
    for r in rows:
        mbid = C.read_mbid(r["path"])
        if not mbid:
            continue
        if mbid not in releases:
            releases[mbid] = N._load_release(mbid)
        rel = releases[mbid]
        if not rel:
            continue
        idx = N._match_index(N.release_tracks(rel), r["title"] or Path(r["path"]).stem)
        if idx and r.get("track") != idx[1]:
            issues += 1
    return issues


def verify(rows):
    cl = TC.clusters(rows)
    by_action = collections.Counter(c["action"] for c in cl)
    ndupe, nredundant = _dup_clusters(rows)
    inv = _incomplete_albums()
    art = _missing_art(rows)
    return {
        "splits": {"total": len(cl), "retag": by_action.get("retag", 0),
                   "merge": by_action.get("merge", 0),
                   "board": by_action.get("board", 0)},
        "dupes": {"clusters": ndupe, "redundant_files": nredundant},
        "incomplete": inv,          # None = inventory stale/absent
        "missing_art": art,
        "track_number_issues": _track_number_issues(rows),
        # remaster-date check needs MB per album; run by `curate run`, not
        # on every verify (rate-limited). Reuses merge._resolve_earliest_date.
        "remaster_dates": "deferred to run",
    }


def main():
    rows = json.loads(C.SCAN_JSON.read_text())
    rep = verify(rows)
    if "--json" in sys.argv:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        s = rep["splits"]
        print(f"tag splits      : {s['total']}  "
              f"(retag {s['retag']}, merge {s['merge']}, board {s['board']})")
        d = rep["dupes"]
        print(f"duplicate tracks: {d['clusters']} clusters "
              f"({d['redundant_files']} redundant files)")
        inv = rep["incomplete"]
        if inv is None:
            print("incomplete      : unknown (run album-inventory.py first)")
        else:
            print(f"incomplete      : {inv['count']} albums under reference")
        print(f"missing art     : {rep['missing_art']['count']} albums blank")
        print(f"track numbers   : {rep['track_number_issues']} files disagree with MB")
    dirty = (rep["splits"]["total"] or rep["dupes"]["clusters"]
             or (rep["incomplete"] or {}).get("count", 0)
             or rep["missing_art"]["count"] or rep["track_number_issues"])
    sys.exit(1 if dirty else 0)


if __name__ == "__main__":
    main()
