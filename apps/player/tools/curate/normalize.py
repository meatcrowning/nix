#!/usr/bin/env python3
"""curate normalize — fix track numbers, disc numbers and release years so
every file in an album matches its canonical MusicBrainz release tracklist.

Why this stage exists: the fill-in pipeline lands Soulseek rips whose track
numbers came from the PEER's library — a compilation rip leaves "20/25" on a
4-track EP, a single's position in a box set leaves "80", and an untagged
single arrives with NO track number at all. None of that was wrong enough for
dupes/groups to catch, but all of it is wrong on the player's track-order axis.

How it decides the canonical value, per file:
  - the file's OWN MusicBrainz release id (C.read_mbid from its tags, so it is
    live, not the point-in-time tagscan) -> the release's tracklist from the
    audit mbcache (~/.cache/library-tag-audit/mbcache/<mbid>.json), fetched
    via C.mb_get into the curate cache if absent.
  - the file's ALBUM tag must fold-match the release's title (edition noise
    stripped) — this is the guard that keeps compilation members from being
    renumbered to their ORIGINAL album's positions (a file on a compilation
    carries an MB id pointing at the original album).
  - the file's title is then matched to a release track by folded key
    (trackmatch), requiring an unambiguous single match; its `position`
    becomes the canonical track, its medium `position` the disc.
  - the year is the release's release-group EARLIEST date (the Kate Bush rule:
    file as the original year, not the remaster's). The earliest is resolved
    only when the file's year differs from the EDITION's own year or is
    missing (the healthy majority never pays for the 2-request lookup).
Only unambiguous matches are acted on; a title that matches zero or two release
tracks is left alone (board-style: never guessed). A file with no MB id is
untouched — there is no authority to fix it against.

Writes via atomicsave (mtime-preserving), records every changed path to
<STATE>/normalize-changed.txt so `curate run` can bump their mtimes afterwards
(without which the player's mtime+size rescan never re-reads them — the stale
DB bug). Dry run by default; --apply writes.
"""
import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path

import common as C
import trackmatch

# The audit pipeline's mbcache is the populated one (2k+ releases with full
# tracklists); the curate cache is the fallback target for C.mb_get.
AUDIT_MBCACHE = Path.home() / ".cache" / "library-tag-audit" / "mbcache"
CHANGED_FILE = C.STATE / "normalize-changed.txt"

# Edition/remaster noise stripped before comparing an album tag to a release
# title, so a "2018 Remaster" of a 1985 album still matches its own release.
_EDITION_NOISE = re.compile(
    r"[\(\[][^)\]]*\b(remaster(?:ed)?|deluxe|edition|reissue|bonus|expanded|"
    r"anniversary|version|remix(?:ed)?|mono|stereo|ep|single)\b[^)\]]*[\)\]]",
    re.IGNORECASE)


def _load_release(mbid):
    """Release dict from audit mbcache, else fetched+cached via C.mb_get."""
    p = AUDIT_MBCACHE / (mbid + ".json")
    if p.is_file():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    data = C.mb_get(f"release/{mbid}", "inc=recordings+artist-credits+media")
    return data if data and not data.get("error") else None


def release_tracks(release):
    """[(disc, track_number, title)] flattened across media."""
    out = []
    for med in release.get("media", []):
        disc = med.get("position") or 1
        for t in med.get("tracks", []):
            title = t.get("title")
            if not title:
                continue
            out.append((disc, t.get("position") or t.get("number") or 0, title))
    return out


_EDITION_RE = _EDITION_NOISE


def _album_matches_release(album_tag, release):
    """True when the file's album tag is (a variant of) the release's title.

    The whole guard that keeps normalize from renumbering COMPILATION members:
    a file on a compilation carries an MB id pointing at the ORIGINAL album,
    so title-matching alone would renumber it to the original album's position
    (measured: '27 Phyllis Hyman - Don't Tell Me, Tell Her' -> 11, '57 Do Me
    Again' -> 2). Only a file whose ALBUM tag folds to the release's title is
    genuinely a member of that release."""
    fa = C.fold(_EDITION_RE.sub("", album_tag or ""))
    fr = C.fold(_EDITION_RE.sub("", release.get("title") or ""))
    if not fa or not fr:
        return False
    return fa == fr or (len(fa) >= 8 and (fa in fr or fr in fa))


def _match_index(tracks, title):
    """Canonical (disc, track) for a title, only on an unambiguous fold match.
    Returns None when zero or >1 tracks fold-match (never guessed)."""
    ft = trackmatch.fold(title)
    if not ft:
        return None
    hits = []
    for disc, trk, rt in tracks:
        if trackmatch.fold(rt) == ft:
            hits.append((disc, trk))
    if len(hits) == 1:
        return hits[0]
    return None


def _release_year(release):
    """The EDITION's own year (the release date), used only as a cheap
    heuristic to decide whether the expensive earliest-resolution is needed."""
    m = re.match(r"(\d{4})", str(release.get("date") or ""))
    return m.group(1) if m else ""


_EARLIEST_CACHE = {}


def _earliest_year(mbid):
    """Release-group EARLIEST year for a release id, cached per mbid.

    A release's OWN date is the EDITION's date (a 2021 reissue says 2021),
    which must never overwrite a track's correct original year (the Kate Bush
    rule: file as the original release year). Only the release-group's
    earliest release date is authoritative. Resolves exactly like
    merge._resolve_earliest_date (release -> release-group -> earliest), which
    is a 2-request MB lookup, so results are cached per mbid in-process and
    C.mb_get caches the HTTP responses to disk."""
    if mbid in _EARLIEST_CACHE:
        return _EARLIEST_CACHE[mbid]
    out = None
    rel = C.mb_get(f"release/{mbid}", "inc=release-groups")
    if rel and not rel.get("error"):
        rg = (rel.get("release-group") or {}).get("id")
        if rg:
            rgdata = C.mb_get(f"release-group/{rg}", "inc=releases")
            if rgdata and not rgdata.get("error"):
                dates = [r.get("date") for r in (rgdata.get("releases") or [])
                         if r.get("date")]
                earliest = min(dates) if dates else rgdata.get("first-release-date")
                m = re.match(r"(\d{4})", str(earliest or ""))
                if m:
                    out = m.group(1)
    _EARLIEST_CACHE[mbid] = out
    return out


def _write_track(path, track, disc):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import atomicsave as _a

    def mutate(audio):
        tags = audio.tags
        if tags is None:
            return
        from mutagen.id3 import ID3
        from mutagen.id3 import TRCK, TPOS
        from mutagen.mp4 import MP4
        if isinstance(tags, ID3):
            tags.setall("TRCK", [TRCK(encoding=3, text=[str(track)])])
            if disc:
                tags.setall("TPOS", [TPOS(encoding=3, text=[str(disc)])])
        elif isinstance(audio, MP4):
            audio["trkn"] = [(int(track), 0)]
            if disc:
                audio["disk"] = [(int(disc), 0)]
        else:
            tags["tracknumber"] = [str(track)]
            if disc:
                tags["discnumber"] = [str(disc)]

    _a.atomic_save(str(path), mutate)


def _write_year(path, year):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import atomicsave as _a
    _a.atomic_save(str(path), lambda audio: C.set_common_tags(audio, date=year))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--path-filter", default="",
                   help="only process paths containing this substring (trial)")
    ap.add_argument("--limit", type=int, default=0,
                   help="stop after N files (trial)")
    args = ap.parse_args()
    rows = json.loads(C.SCAN_JSON.read_text())
    if args.path_filter:
        rows = [r for r in rows if args.path_filter in r["path"]]
    changed = []
    n_checked = n_track = n_year = n_no_mbid = n_nomatch = 0
    releases = {}

    for n, r in enumerate(rows):
        if args.limit and n >= args.limit:
            break
        path = r["path"]
        mbid = C.read_mbid(path)
        if not mbid:
            n_no_mbid += 1
            continue
        n_checked += 1
        if mbid not in releases:
            releases[mbid] = _load_release(mbid)
        rel = releases[mbid]
        if not rel:
            continue
        # THE guard: file's album tag must be this release's title, else it is
        # a compilation member / mis-referenced and must not be renumbered.
        if not _album_matches_release(r.get("album") or Path(path).stem, rel):
            n_nomatch += 1
            continue
        tracks = release_tracks(rel)
        edition_year = _release_year(rel)
        cur_year = str(r.get("year") or "")[:4]
        year = None
        if not cur_year or (edition_year and cur_year != edition_year):
            year = _earliest_year(mbid)

        # --- track number ---
        cur_trk = r.get("track")
        idx = _match_index(tracks, r["title"] or Path(path).stem)
        if idx:
            disc, trk = idx
            if cur_trk != trk:
                n_track += 1
                changed.append(path)
                if args.apply:
                    _write_track(path, trk, disc if disc != 1 else None)
                print(f"  {'SET' if args.apply else 'would set'} track "
                      f"{cur_trk}->{trk} {Path(path).name}")
        else:
            n_nomatch += 1
        # --- year ---
        # A year is only ever moved EARLIER, never later. The point of year
        # normalization is fixing compilation-rip years that are too LATE
        # (a 2020 tag on a 2017 album); the Kate Bush rule files by the ORIGINAL
        # year. If the file's current year is already earlier than the resolved
        # earliest, the file is correct and the mbid points at a reissue group
        # (measured: A Flock of Seagulls 1982 files carry reissue mbids whose
        # group earliest is 1986 — pushing 1982->1986 would corrupt it).
        if (year and (not cur_year or int(year) < int(cur_year))):
            n_year += 1
            changed.append(path)
            if args.apply:
                _write_year(path, year)
            print(f"  {'SET' if args.apply else 'would set'} year "
                  f"{cur_year}->{year} {Path(path).name}")

    if args.apply:
        CHANGED_FILE.write_text("\n".join(dict.fromkeys(changed)) + "\n")
    print(f"\nchecked {n_checked} MB-referenced files; {n_no_mbid} no MB id "
          f"(untouched); {n_nomatch} ambiguous/compilation (untouched)")
    print(f"{n_track} track-number fix(es), {n_year} year fix(es) "
          f"{'APPLIED' if args.apply else 'would be applied'}")
    if args.apply:
        print(f"changed paths -> {CHANGED_FILE}")


if __name__ == "__main__":
    main()
