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
import re
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

# A reissue tag on the TITLE ("And Dream of Sheep - 2018 Remaster", "In Your
# Eyes (2012 Remaster)") is the same recording as the plain title, but
# trackmatch keeps the suffix so the two never share a fold-key and the copy
# survives beside its original. Strip an edition suffix (parenthesised OR
# dash-tailed) so both forms produce the plain key too and dedupe against each
# other. Deliberately NARROW: remix / acoustic / live / instrumental / edit /
# version are DIFFERENT recordings and are NOT stripped (the >6s duration split
# below is the second guard).
_TITLE_EDITION_NOISE = re.compile(
    r"(\s*[-–—]\s*|\s*[\(\[]\s*)(\d{4}\s+)?"
    r"(remaster(?:ed)?|re-?master(?:ed)?|deluxe|expanded|anniversary|"
    r"reissue|bonus|mono|stereo)\b.*$",
    re.IGNORECASE)


def _dedupe_titles(title):
    """The raw title plus, if an edition suffix strips off, the bare title."""
    title = title or ""
    stripped = _TITLE_EDITION_NOISE.sub("", title).strip()
    if stripped and stripped != title:
        return (title, stripped)
    return (title,)


# A remix / live / acoustic / edit / instrumental / … is a DIFFERENT recording
# that must survive beside the plain track. trackmatch.keys() (used for the
# fold below, and rightly so for lyric lookup) strips these qualifiers, so a
# "(remix)" copy shares a fold-key with its original; the >6s duration split is
# the only backstop and it misses when the variant runs close to the original's
# length (a rated "Bamboo Houses" was lost to its "(remix)" 1.8s apart). So two
# copies only dedupe when their variant signatures MATCH. Deliberately WIDE and
# one-directional-safe: an over-included marker only makes dedup more
# conservative (keeps a copy), never removes one it should not. Edition noise
# (remaster/deluxe/…) is intentionally NOT here — those DO dedupe.
_VARIANT_MARKER = re.compile(
    r"\b(remix|live|acoustic|instrumental|reprise|dub|vip|bootleg|rework|"
    r"flip|demo|cover|edit|session|club|extended|radio|sped|slowed)\b",
    re.IGNORECASE)


def _variant_sig(title):
    return frozenset(m.group(1).lower()
                     for m in _VARIANT_MARKER.finditer(title or ""))


def cmd_dupes(args):
    rows = _load_scan()
    by_path = {r["path"]: r for r in rows}
    groups = collections.defaultdict(list)
    for r in rows:
        # Key on BOTH the album_artist and the track artist, dropping
        # compilation placeholders ("Various Artists"). album_artist used to
        # win a single-candidate pick, so a remaster/comp copy tagged
        # album_artist="Various Artists" never shared a fold-key with its
        # studio-album twin and escaped dedup (433 files carry that tag). The
        # real per-track credit lives on `artist`; never key on the
        # placeholder itself, or unrelated same-title songs across comps fold
        # together.
        artists = [a for a in (r["album_artist"], r["artist"])
                   if a and C.fold(a) not in _NOT_AN_ARTIST]
        if not artists:
            artists = [r["album_artist"] or r["artist"] or ""]
        seen = set()
        for artist in artists:
            for t in _dedupe_titles(r["title"]):
                for k in trackmatch.keys(artist, t):
                    if k not in seen:
                        seen.add(k)
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
            # within a duration bucket, only copies with the SAME variant
            # signature are true duplicates: a remix/live/acoustic/edit copy
            # that folded in via trackmatch stays beside its plain original.
            byvar = collections.defaultdict(list)
            for r in b:
                byvar[_variant_sig(r["title"])].append(r)
            for vb in byvar.values():
                if len(vb) < 2:
                    continue
                n_dupe_groups += 1
                ranked = sorted(
                    vb, key=lambda r: C.quality_of(r["path"], r["bitrate"], r["sample_rate"], r["dur"]),
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


# Edition/remaster noise that must not stop two directories of the same
# release from folding together ("Hounds of Love" vs "Hounds Of Love (2018
# Remaster)" are the same album, split by a reissue tag in the folder name).
_EDITION_NOISE = re.compile(
    r"[\(\[][^)\]]*\b(remaster(?:ed)?|deluxe|edition|reissue|bonus|expanded|"
    r"anniversary|version|remix(?:ed)?|mono|stereo|ep|single)\b[^)\]]*[\)\]]",
    re.IGNORECASE)

# Identities that are legitimately shared by many unrelated real artists
# ("Various Artists" compilations, blank/placeholder tags) - never cluster
# these, or unrelated songs by unrelated artists get merged into one "album".
_NOT_AN_ARTIST = {"", "various artists", "various", "va", "unknown artist",
                  "unknown album", "unknown"}


def _album_title_fold(s):
    return C.fold(_EDITION_NOISE.sub("", s or ""))


_NUMERAL = re.compile(r"\d+")
_ROMAN_TOKEN = re.compile(r"^(i{1,3}|iv|vi{0,3}|ix|x)$")


def _distinguishing_numbers(folded):
    """Volume/part numbers that must NOT be folded away: 'vol 1' vs 'vol 2',
    'ep i' vs 'ep ii', 'l a ep 1 x 3' vs '... 2 x 3' are different real
    releases, not one release split by tagging noise - a high text-similarity
    ratio alone would wrongly merge them."""
    digits = set(_NUMERAL.findall(folded))
    romans = {t for t in folded.split() if _ROMAN_TOKEN.match(t)}
    return digits, romans


def _same_album_title(bi, bj):
    if bi == bj:
        return True
    if difflib.SequenceMatcher(None, bi, bj).ratio() <= 0.88:
        return False
    di, ri = _distinguishing_numbers(bi)
    dj, rj = _distinguishing_numbers(bj)
    if di != dj or ri != rj:
        return False
    return True


def cmd_groups(args):
    rows = _load_scan()
    dirs = _album_dirs(rows)
    # candidate identity for a directory: canonical (album_artist, album) as
    # TAGGED (fall back to folder names if tags are blank), folded.
    def identity(recs):
        # The FOLDER name, not the album_artist tag, is the artist identity to
        # cluster on: a compilation/blog brand ("BIRP!", "Various Artists")
        # is often the tag on many directories of genuinely unrelated real
        # artists, while the folder itself already carries the real name
        # (this library is organised AlbumArtist/Album/). Falling back to the
        # tag only when there is no folder keeps a same-artist split (folder
        # names identical or near-identical) matching while a compilation tag
        # shared across unrelated folders no longer does.
        aa = recs[0]["album_artist_dir"] or recs[0]["album_artist"]
        al = recs[0]["album"] or recs[0]["album_dir"]
        return aa, al

    items = []  # (dirkey, artist_raw, album_raw, artist_fold, album_fold, recs)
    for dirkey, recs in dirs.items():
        aa, al = identity(recs)
        af = C.fold(aa)
        if af in _NOT_AN_ARTIST:
            continue  # compilation / unlabeled - never a same-artist split
        items.append((dirkey, aa, al, af, _album_title_fold(al), recs))

    # bucket by ARTIST first (fuzzy - "A, B & C" vs "B, A & C" vs "A feat. B,
    # C" collapse via trackmatch.artist_matches), THEN fuzzy-match album title
    # within an artist's own releases so an edition/remaster suffix in one
    # folder's tag doesn't stop it folding into its sibling.
    artist_keys = []  # representative fold per cluster
    by_artist = collections.defaultdict(list)
    for it in items:
        placed = False
        for k in artist_keys:
            if (it[3] == k or trackmatch.artist_matches(it[1], k)
                    or difflib.SequenceMatcher(None, it[3], k).ratio() > 0.9):
                by_artist[k].append(it)
                placed = True
                break
        if not placed:
            artist_keys.append(it[3])
            by_artist[it[3]].append(it)

    report = []
    for _artist_key, group in by_artist.items():
        if len(group) < 2:
            continue
        used = [False] * len(group)
        for i in range(len(group)):
            if used[i]:
                continue
            cluster = [group[i]]
            used[i] = True
            for j in range(i + 1, len(group)):
                if used[j] or not group[j][4]:
                    continue
                bi, bj = group[i][4], group[j][4]
                if _same_album_title(bi, bj):
                    cluster.append(group[j])
                    used[j] = True
            if len(cluster) < 2:
                continue
            # pick the longest raw album title as the report label
            label = max((c[2] for c in cluster), key=len)
            report.append({
                "album": label,
                "dirs": [{"path": f"{c[0][0]}/{c[0][1]}", "artist": c[1],
                          "album_raw": c[2], "n_tracks": len(c[5])} for c in cluster],
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
