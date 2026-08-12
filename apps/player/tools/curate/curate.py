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
import unicodedata

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
    r"reissue|bonus(\s+track)?|mono|stereo)\b.*$",
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
    """Identity of a variant recording. Two copies dedupe only when these
    match. Markers alone are not enough: '(Jimmy Edgar Remix)' and '(remix)'
    both yield {'remix'} and would dedupe two DIFFERENT recordings that
    happen to sit in one duration bucket (measured 2026-08-09: Machine Drum
    'I Know Your Kind' pair, chromaprint 0.003, would have lost the Jimmy
    Edgar remix). Include the normalized containing parenthetical, so a
    variant is identified by its full label, not its category."""
    t = title or ""
    sig = set()
    for m in _VARIANT_MARKER.finditer(t):
        word = m.group(1).lower()
        sig.add(word)
        start = t.rfind("(", 0, m.start())
        end = t.find(")", m.end())
        if start != -1 and end != -1:
            phrase = re.sub(r"\s+", " ", t[start + 1:end].strip().lower())
            if phrase:
                sig.add(phrase)
    return frozenset(sig)


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

# CJK scripts. NFKD-fold treats kana as opaque \w tokens, so the SAME album
# titled in Japanese on one side and "English Name • 和名" on the other never
# shares a fold key (the Sekito split). Match on the two script planes
# separately instead.
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


def _latin_fold(s):
    """fold() of only the latin/cyrillic/etc. content, CJK stripped."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _CJK.sub(" ", s)
    return C.fold(s)


def _cjk_fold(s):
    """The CJK content only, NFKC-folded (ザ vs ザ compatibility forms),
    punctuation and latin stripped."""
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"[A-Za-z0-9]", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", "", s)

# A leading catalogue/chart/rank number is NOT part of the album title:
# "486 # Maggot Brain" is Maggot Brain, "[LM041] Feel Infinite" is Feel
# Infinite. Applied AFTER bracket stripping. Handles both bare prefixes
# ("486 # X") and bracketed catalogue ids ("[LM041] X").
_LEADING_NOISE = re.compile(
    r"^\s*(?:[\(\[]\s*[A-Za-z]*\s*\d+\s*[\)\]]|\d+\s*[#\-–—\.:]?)\s+")

# Identities that are legitimately shared by many unrelated real artists
# ("Various Artists" compilations, blank/placeholder tags) - never cluster
# these, or unrelated songs by unrelated artists get merged into one "album".
_NOT_AN_ARTIST = {"", "various artists", "various", "va", "unknown artist",
                  "unknown album", "unknown"}


def _album_title_fold(s):
    return C.fold(_LEADING_NOISE.sub("", _EDITION_NOISE.sub("", s or "")))


def _album_title_keys(s):
    """The set of comparison keys an album title can match on: the full fold
    (legacy), plus the latin and CJK planes separately so a bilingual title
    and its single-script sibling share at least one key."""
    base = _EDITION_NOISE.sub("", s or "")
    base = _LEADING_NOISE.sub("", base)
    keys = {C.fold(base)}
    lat, cjk = _latin_fold(base), _cjk_fold(base)
    if lat:
        keys.add("L:" + lat)
    if cjk:
        keys.add("C:" + cjk)
    return keys


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


# Sequel-ish tails that make a longer title a DIFFERENT record, not the same
# album with a suffix: "In Decay, Too" ≠ "In Decay". Checked before any
# containment match.
_SEQUEL_TAIL = re.compile(r"\btoo\s*$")


# Suffix classes that make a longer title a DIFFERENT release rather than
# the same album with decoration: remixes / instrumentals / sessions / demos
# are alternate-content versions, not the plain record. "Renaissance
# (Remixes)" must not fold into "Renaissance".
_VARIANT_SUFFIX = re.compile(
    r"\b(remix(?:es|ed)?|instrumentals?|sessions?|demos?|reworks?|versions|"
    r"unmixed|alternate|covers?|acoustics?|lost tracks?|outtakes?|bonus tracks?|"
    r"b[- ]sides?)\b", re.IGNORECASE)


def _same_album_title(bi, bj):
    if bi == bj:
        return True
    bi_v, bj_v = bool(_VARIANT_SUFFIX.search(bi)), bool(_VARIANT_SUFFIX.search(bj))
    if bi_v != bj_v:
        return False
    # One side's whole title nested in the other is a strong same-album
    # signal ONLY when the nested side is substantial — "AM" inside "Whatever
    # People Say I Am…" is coincidence, "Maggot Brain" inside "486 Maggot
    # Brain" (after the leading-noise strip they're equal anyway) is not.
    # Below the length floor, fall through to the similarity+numbers check.
    if (min(len(bi), len(bj)) >= 8 and (bi in bj or bj in bi)
            and not (_SEQUEL_TAIL.search(bi) or _SEQUEL_TAIL.search(bj))):
        di, ri = _distinguishing_numbers(bi)
        dj, rj = _distinguishing_numbers(bj)
        if di == dj and ri == rj:
            return True
    if difflib.SequenceMatcher(None, bi, bj).ratio() <= 0.88:
        return False
    di, ri = _distinguishing_numbers(bi)
    dj, rj = _distinguishing_numbers(bj)
    if di != dj or ri != rj:
        return False
    return True


def cmd_groups(args):
    """Cluster on the TAG axis (what the player groups by), via tagclusters.
    Writes groups.json with an `action` per cluster: retag / merge / board.
    Only `merge` clusters feed merge.py; retag is retag.py's input; board is
    for him, never auto-acted."""
    import tagclusters as TC
    rows = _load_scan()
    cl = TC.clusters(rows)
    report = []
    for c in cl:
        dirs = []
        for (aa, al), recs in c["variants"].items():
            for d in sorted({f"{r['album_artist_dir']}/{r['album_dir']}" for r in recs}):
                drecs = [r for r in recs
                         if f"{r['album_artist_dir']}/{r['album_dir']}" == d]
                dirs.append({"path": d, "artist": aa, "album_raw": al,
                             "n_tracks": len(drecs)})
        label = max(c["variants"].items(), key=lambda kv: len(kv[1]))[0][1]
        report.append({"album": label, "action": c["action"],
                       "reason": c["reason"], "dirs": dirs})
    report.sort(key=lambda g: (g["action"] != "merge", -len(g["dirs"])))
    out_path = C.STATE / "groups.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    import collections
    by = collections.Counter(g["action"] for g in report)
    print(f"{len(report)} tag-axis clusters -> {out_path}  "
          f"(merge {by.get('merge',0)}, retag {by.get('retag',0)}, "
          f"board {by.get('board',0)})")
    for g in report[:25]:
        print(f"  [{g['action']}] {g['album']!r}: "
              + " | ".join(f"{d['path']} ({d['n_tracks']}t)" for d in g["dirs"])[:100])
def cmd_touch(_args):
    """Bump the mtime of every audio file to NOW.

    Why this exists: every write in this pipeline goes through atomicsave,
    which PRESERVES mtime, and the player's rescan only re-reads a file whose
    (mtime, size) differs from its DB row. So after a retag/merge/normalize/
    art pass the player would never re-read the corrected files and the DB
    would stay stale — exactly the "I restarted and it's still split" bug. This
    is the player-owned fix: bump mtime so its next startup rescan re-reads
    everything, through its own machinery. Cheap and idempotent (~17k files,
    a few seconds)."""
    import time
    n = 0
    now = time.time()
    for absp, rel in C.reorg.walk_root():
        if os.path.splitext(absp)[1].lower() not in C.reorg.AUDIO_EXTS:
            continue
        try:
            os.utime(absp, (now, now))
            n += 1
        except OSError:
            pass
    print(f"bumped mtime on {n} audio files to now")
    print("the player's next startup rescan will re-read them (player-owned)")


def cmd_run(args):
    """scan -> dupes -> groups -> retag -> merge -> normalize -> album-art ->
    touch -> verify, idempotent.

    Every stage is a no-op when the library is already converged, so `run`
    is safe behind a timer: silent when clean, a work list when not. Board
    clusters are reported, never acted on. Without --apply the mutating
    stages (dupes/retag/merge/normalize/album-art) run dry. touch is the final
    step that makes the player re-read the corrected files on its next rescan.
    """
    import subprocess
    here = os.path.dirname(os.path.abspath(__file__))
    py = sys.executable

    def stage(name, argv):
        print(f"\n=== {name} ===", flush=True)
        script, rest = argv[0], argv[1:]
        r = subprocess.run([py, os.path.join(here, script)] + rest, check=False)
        if r.returncode not in (0, 1):  # verify exits 1 when dirty; that's data
            print(f"!! {name} failed ({r.returncode})", file=sys.stderr)
            sys.exit(r.returncode)

    stage("scan", ["curate.py", "scan"])
    stage("dupes", ["curate.py", "dupes"] + (["--apply"] if args.apply else []))
    stage("groups", ["curate.py", "groups"])
    stage("retag", ["retag.py"] + (["--apply"] if args.apply else []))
    stage("merge", ["merge.py"] + (["--apply"] if args.apply else []))
    stage("normalize", ["normalize.py"] + (["--apply"] if args.apply else []))
    stage("album-art", ["album-art.py"] + (["--apply"] if args.apply else []))
    if args.apply:
        # files moved/retagged/normalized: the scan is stale, refresh before
        # verifying AND before the mtime bump so verify sees current tags.
        stage("scan (post-apply)", ["curate.py", "scan"])
    stage("verify", ["verify.py"])
    if args.apply:
        # last: bump mtimes so the player re-reads everything the run changed.
        stage("touch", ["curate.py", "touch"])


CMDS = {"scan": cmd_scan, "dupes": cmd_dupes, "groups": cmd_groups,
        "touch": cmd_touch, "run": cmd_run}

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")
    dp = sub.add_parser("dupes")
    dp.add_argument("--apply", action="store_true")
    sub.add_parser("groups")
    sub.add_parser("touch")
    rp = sub.add_parser("run")
    rp.add_argument("--apply", action="store_true")
    a = p.parse_args()
    CMDS[a.cmd](a)

