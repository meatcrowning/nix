#!/usr/bin/env python3
"""Consolidation stage: fold each groups.json entry (an album split across
several directories - a reissue-tag split or an artist-credit variant, see
curate.py groups) into ONE directory.

    merge --apply    fold every group, retag album/album_artist to one
                      canonical string, resolve the album's original release
                      date from MusicBrainz where a release id is on file.

Per group:
  - the directory with the most tracks is PRIMARY.
  - every other directory's tracks either fill a gap (moved in, nothing lost)
    or duplicate a track already in PRIMARY (the worse-quality copy is moved
    to ~/Music-removed/consolidated-dupes/, never deleted).
  - leftover non-audio files (cover art, .nfo) move into PRIMARY too.
  - emptied source directories are rmdir'd (never force-removed - if one is
    not empty after the merge, it is left in place and logged).
  - PRIMARY's files are retagged to one canonical album / album_artist, and
    PRIMARY's own directory is renamed to the noise-stripped album title.
  - if any file carries a MusicBrainz release id, its release-group's
    EARLIEST release supplies the canonical date (his Kate Bush "Hounds of
    Love" example: file as 1985 even though the files are the 2018
    remaster) - not the tracklist/titles, which stay as tagged; that is
    covered by the missing-tracks inventory (missing_inventory.py) instead.

Dry run by default; --apply actually moves/retags/renames.
"""
import json
import os
import shutil
import sys
from pathlib import Path

import common as C
import curate as curmod  # for _EDITION_NOISE / _album_title_fold / trackmatch
import trackmatch

GROUPS_JSON = C.STATE / "groups.json"

# Titles too generic to trust as one real album across directories - always
# left for manual review rather than auto-merged.
_GENERIC_ALBUM = {"unknown album", ""}


def _load_scan_by_dir():
    rows = json.loads(C.SCAN_JSON.read_text())
    by_dir = {}
    for r in rows:
        if r["album_dir"] is None:
            continue
        key = f"{r['album_artist_dir']}/{r['album_dir']}"
        by_dir.setdefault(key, []).append(r)
    return by_dir


def _canonical_artist(dirs):
    """The shortest artist string that every other dir's artist string is a
    superset-match of (curate.py's own subset/prefix rule) - the real primary
    credit a feature-heavy variant was built from ('Kid Cudi' out of 'Kid
    Cudi; Trippie Redd', 'SebastiAn' out of 'SebastiAn Mayer Hawthorne')."""
    cands = sorted({d["artist"] for d in dirs}, key=len)
    for c in cands:
        if all(trackmatch.artist_matches(c, d["artist"]) or C.fold(c) == C.fold(d["artist"])
               for d in dirs):
            return c
    # no clean hub - fall back to the primary dir's own credit
    return dirs[0]["artist"]


def _canonical_album(label):
    """Base the canonical title on the PRIMARY (most-tracks) directory's own
    raw title, edition-noise stripped - not the group's longest label, which
    can coincidentally be a typo'd sibling ('ROY PABLO' vs the correct 'Soy
    Pablo') rather than the real title."""
    stripped = curmod._EDITION_NOISE.sub("", label).strip()
    stripped = stripped.rstrip("-‐‑‒–— ").strip()
    return stripped or label


def _safe_move_into(src_path, dest_dir):
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(src_path).name
    stem, ext = dest.stem, dest.suffix
    n = 1
    while dest.exists():
        dest = dest_dir / f"{stem} ({n}){ext}"
        n += 1
    shutil.move(str(src_path), str(dest))
    return dest


def _resolve_earliest_date(mbid):
    """release/{mbid} -> its release-group -> the earliest release's date."""
    rel = C.mb_get(f"release/{mbid}", "inc=release-groups")
    if not rel or rel.get("error"):
        return None
    rg = (rel.get("release-group") or {}).get("id")
    if not rg:
        return None
    rgdata = C.mb_get(f"release-group/{rg}", "inc=releases")
    if not rgdata or rgdata.get("error"):
        return None
    dates = [r.get("date") for r in (rgdata.get("releases") or []) if r.get("date")]
    if not dates:
        return rgdata.get("first-release-date") or None
    return min(dates)  # ISO-ish "YYYY", "YYYY-MM", "YYYY-MM-DD" sort correctly as strings of equal-ish shape


def process_group(g, by_dir, apply_):
    notes = []
    key_label = g["album"]
    if C.fold(key_label) in _GENERIC_ALBUM:
        return {"album": key_label, "skipped": "generic album title"}
    dir_recs = []
    for d in g["dirs"]:
        recs = by_dir.get(d["path"])
        if not recs:
            continue
        dir_recs.append((d, recs))
    if len(dir_recs) < 2:
        return {"album": key_label, "skipped": "fewer than 2 dirs had scan rows"}

    dir_recs.sort(key=lambda dr: -len(dr[1]))
    primary_d, primary_recs = dir_recs[0]
    primary_path = C.ROOT / primary_d["path"]
    canonical_artist = _canonical_artist([d for d, _ in dir_recs])
    canonical_album = _canonical_album(primary_d["album_raw"])

    # index primary's existing tracks by fold(title) for gap/dup detection
    def title_key(r):
        return C.fold(r["title"] or Path(r["path"]).stem)

    primary_by_title = {}
    for r in primary_recs:
        primary_by_title.setdefault(title_key(r), []).append(r)

    moved_in = replaced = discarded = 0
    for d, recs in dir_recs[1:]:
        src_dir = C.ROOT / d["path"]
        for r in recs:
            # the scan can be older than a previous partial run: a file
            # already moved (by us, or by an earlier --apply that died
            # mid-group) is skipped, not crashed on.
            if apply_ and not Path(r["path"]).exists():
                notes.append(("already gone (stale scan row)", r["rel"], ""))
                continue
            tk = title_key(r)
            existing = primary_by_title.get(tk)
            if not existing:
                # gap filler - move straight into primary, nothing lost
                if apply_:
                    dest = _safe_move_into(r["path"], primary_path)
                    notes.append(("filled gap", r["rel"], str(dest)))
                moved_in += 1
                primary_by_title.setdefault(tk, []).append(r)
                continue
            keep = existing[0]
            q_new = C.quality_of(r["path"], r["bitrate"], r["sample_rate"], r["dur"])
            q_keep = C.quality_of(keep["path"], keep["bitrate"], keep["sample_rate"], keep["dur"])
            if q_new > q_keep:
                # incoming copy is better - it takes the slot, the old
                # primary copy becomes the discard
                if apply_:
                    C.move_to_removed(keep["path"], "consolidated-dupes",
                                       f"replaced by higher-quality copy from {d['path']!r} "
                                       f"during {canonical_album!r} consolidation "
                                       f"(quality {q_keep} < {q_new})")
                    dest = _safe_move_into(r["path"], primary_path)
                    notes.append(("replaced with better copy", r["rel"], str(dest)))
                existing[0] = r
                replaced += 1
            else:
                if apply_:
                    C.move_to_removed(r["path"], "consolidated-dupes",
                                       f"duplicate of {keep['rel']!r} kept in primary "
                                       f"during {canonical_album!r} consolidation "
                                       f"(quality {q_new} <= {q_keep})")
                discarded += 1
        if apply_:
            # non-audio leftovers (art, nfo) - fold into primary too
            for extra in src_dir.glob("*"):
                if extra.is_file():
                    _safe_move_into(extra, primary_path)
            try:
                src_dir.rmdir()
                notes.append(("removed emptied source dir", d["path"], ""))
            except OSError as e:
                notes.append(("could not remove source dir (not empty)", d["path"], str(e)))

    date = None
    if apply_:
        for r in primary_recs:
            mbid = C.read_mbid(r["path"])
            if mbid:
                date = _resolve_earliest_date(mbid)
                if date:
                    break
        _retag_dir(primary_path, canonical_album, canonical_artist, date)
        new_dir_name = C.reorg.san(canonical_album)
        if new_dir_name != Path(primary_d["path"]).name:
            new_path = primary_path.parent / new_dir_name
            if not new_path.exists():
                primary_path.rename(new_path)
                notes.append(("renamed primary dir", primary_d["path"], str(new_path)))

    return {
        "album": key_label, "canonical_album": canonical_album,
        "canonical_artist": canonical_artist, "primary": primary_d["path"],
        "moved_in": moved_in, "replaced": replaced, "discarded": discarded,
        "date": date, "notes": notes,
    }


ATOMICSAVE = None


def _retag_dir(dirpath, album, album_artist, date):
    global ATOMICSAVE
    if ATOMICSAVE is None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        import atomicsave as _a
        ATOMICSAVE = _a
    for f in sorted(dirpath.iterdir()):
        if f.suffix.lower() not in C.reorg.AUDIO_EXTS:
            continue

        def mutate(audio, _album=album, _aa=album_artist, _date=date):
            C.set_common_tags(audio, album=_album, album_artist=_aa, date=_date)

        try:
            ATOMICSAVE.atomic_save(str(f), mutate)
        except Exception as e:
            print(f"  ! retag failed on {f}: {e}", file=sys.stderr)


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()

    if not GROUPS_JSON.exists():
        C.reorg.die("no groups.json - run `curate.py groups` first")
    groups = json.loads(GROUPS_JSON.read_text())
    # tag-axis groups.json carries retag/board clusters too; merge only acts
    # on dir-splits. Entries without an `action` key predate the tag axis —
    # treat them as merge (they were all dir-splits by construction).
    groups = [g for g in groups if g.get("action", "merge") == "merge"]
    by_dir = _load_scan_by_dir()

    results = []
    for g in groups[: args.limit]:
        res = process_group(g, by_dir, args.apply)
        results.append(res)
        if res.get("skipped"):
            print(f"SKIP {res['album']!r}: {res['skipped']}")
        else:
            print(f"{'MERGED' if args.apply else 'would merge'} {res['album']!r} -> "
                  f"{res['canonical_artist']!r} / {res['canonical_album']!r} "
                  f"(primary={res['primary']}, +{res['moved_in']} gap, "
                  f"{res['replaced']} replaced, {res['discarded']} discarded"
                  + (f", date={res['date']}" if res.get("date") else "") + ")")
        if args.apply:
            # flush after EVERY group, not just at the end - a run that dies or
            # times out partway through (a real timeout, once) must not lose the
            # audit rows for groups it already finished moving files for.
            C.flush_audit(f"Album consolidation (groups merge) - {res['album']!r}")

    if args.apply:
        out = C.STATE / "merge-results.json"
        out.write_text(json.dumps(results, ensure_ascii=False, indent=1))
        print(f"-> {out}")


if __name__ == "__main__":
    main()
