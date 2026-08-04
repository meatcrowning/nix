#!/usr/bin/env python3
"""Per-album missing-track inventory: which albums in the library are short of
their full track list, and what the missing tracks are.

The user's ask (2026-08-03): "Jorge Cafrune has several albums with only one
or two songs; find the rest of each album tracks and download them. Do this
for ALL albums missing tracks." spotify-missing.py / album-missing.py already
cover albums SAVED on Spotify. This tool adds the other half of the library:
albums whose full track list is known from MusicBrainz, via the release id
most files carry in their own tags (~94% per audit-tags-vs-mb.py).

References, in order of preference per album:
  1. MusicBrainz release id (from the file tags, read out of
     ~/.cache/library-tag-audit/tagscan.json) -> release track list from
     ~/.cache/library-tag-audit/mbcache/<mbid>.json.
  2. Spotify saved album (library.json saved_albums[].tracks) for albums
     without a MusicBrainz tag.
  3. Neither -> the album is listed with status no-ref; its full track list
     has to be looked up (MusicBrainz search by artist+album) at download time.

Outputs (--dump-dir, default the spotify dump dir):
  album-inventory.tsv  per-album summary: artist, album, reference, ref id,
                       total tracks on the reference, present in the library,
                       missing, status, missing titles.
  album-missing-mb.tsv the missing tracks as a work list in soulseek-missing.py's
                       exact TSV format (COLS from spotify-missing.py), so the
                       downloader can be pointed straight at it:
                       soulseek-missing.py --tsv album-missing-mb.tsv

Matching is generous on purpose: a reference track counts as present if its
folded title (trackmatch) appears among the album's own files, or anywhere in
the library under an artist sharing a folded token with the album artist (a
track the user owns under a different album tag, e.g. "Que seas vos" on both
its album and a Viento del Pueblo volume, is not re-downloaded). The
downloader's own duration check re-validates at fetch time.

Caveat: tagscan.json is a point-in-time scan (the audit tool re-runs it); files
added after the scan carry no mbid here and fall through to the Spotify or
no-ref passes. Re-run audit-tags-vs-mb.py scan before a full download run after
the library cleanup.

Stdlib only, same rationale as the rest of the player tools.
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
TAGSCAN = os.path.expanduser("~/.cache/library-tag-audit/tagscan.json")
MBCACHE = os.path.expanduser("~/.cache/library-tag-audit/mbcache")

# soulseek-missing.py's work-list columns (spotify-missing.py COLS).
COLS = ["artists", "title", "album", "year", "duration_ms", "isrc",
        "spotify_id", "sources"]


def clean(v):
    return str(v).replace("\t", " ").replace("\n", " ").replace("\r", " ")


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


def load_release(mbid):
    p = os.path.join(MBCACHE, mbid + ".json")
    if not os.path.isfile(p):
        return None
    with open(p) as f:
        return json.load(f)


def release_tracks(release):
    """Flatten every medium's tracks into (number, title, length_ms, isrc,
    artists). artists is the track's own artist-credit (the real performer on
    a compilation), falling back to the release artist."""
    rel_artist = primary_artist(release)
    out = []
    for med in release.get("media", []):
        for t in med.get("tracks", []):
            ac = t.get("artist-credit") or []
            arts = " ".join(str(c.get("name", "")) for c in ac
                            if isinstance(c, dict) and c.get("name")) or rel_artist
            out.append((t.get("number", ""), t.get("title", ""),
                        t.get("length"), t.get("isrc", ""), arts))
    return out


def primary_artist(release):
    ac = release.get("artist-credit") or []
    return " ".join(str(c.get("name", "")) for c in ac
                    if isinstance(c, dict) and c.get("name"))


def shared_artist_token(a, b):
    """True when two artist strings share a folded token (a track under
    'Jorge Cafrune & Marito' counts for an album by 'Jorge Cafrune')."""
    ta = set(trackmatch.fold(a).split())
    tb = set(trackmatch.fold(b).split())
    return bool(ta & tb)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump-dir", default=DUMP_DIR)
    ap.add_argument("--db", default=LIBRARY_DB)
    ap.add_argument("--min-missing", type=int, default=1,
                    help="summary rows with at least this many missing (default 1)")
    args = ap.parse_args()

    snap = os.path.join(args.dump_dir, "library-snapshot.db")
    print("Snapshotting the local library...")
    snapshot_db(args.db, snap)
    conn = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
    cols = ["artist", "album", "title", "path"]
    tracks = [dict(zip(cols, r)) for r in conn.execute(
        "SELECT artist, album, title, path FROM tracks")]
    conn.close()
    print(f"  {len(tracks)} local tracks")

    # path -> album_mbid from the audit tag scan (point-in-time; see docstring)
    mbid_by_path = {}
    if os.path.isfile(TAGSCAN):
        with open(TAGSCAN) as f:
            for e in json.load(f):
                if e.get("album_mbid"):
                    mbid_by_path[e.get("path")] = e["album_mbid"]
    print(f"  {len(mbid_by_path)} files with a MusicBrainz release id in the scan")

    # --- library structures ------------------------------------------------
    # folded title -> set of folded artists, for the generous "elsewhere" match
    title_artists = {}
    # (folded artist, folded album) -> set of folded titles, for the album view
    album_titles = {}
    for t in tracks:
        art = trackmatch.fold(t.get("artist") or "")
        title = trackmatch.fold(t.get("title") or "")
        alb = trackmatch.fold(t.get("album") or "")
        title_artists.setdefault(title, set()).add(art)
        if art and alb:
            album_titles.setdefault((art, alb), set()).add(title)

    def present_in_library(title, artist_hint, in_album):
        """A reference track is present if it is in its album's own files or
        anywhere in the library under a shared-artist token."""
        if title in in_album:
            return True
        arts = title_artists.get(title, set())
        if not arts:
            return False
        if not artist_hint:
            return True  # no artist signal; any title match counts
        return any(shared_artist_token(artist_hint, a) for a in arts)

    summary = []
    work_rows = []
    seen_work = set()  # dedup identical missing tracks across references

    def add_work(artists, title, album, year, duration_ms, isrc, spotify_id):
        key = trackmatch.fold(artists) + "||" + trackmatch.fold(title)
        if key in seen_work:
            return
        seen_work.add(key)
        work_rows.append({"artists": artists, "title": title, "album": album,
                          "year": year, "duration_ms": duration_ms,
                          "isrc": isrc, "spotify_id": spotify_id,
                          "sources": album})

    # --- pass 1: MusicBrainz releases --------------------------------------
    by_mbid = {}
    for i, t in enumerate(tracks):
        mbid = mbid_by_path.get(t.get("path") or "")
        if mbid:
            by_mbid.setdefault(mbid, []).append(t)

    for mbid, local in by_mbid.items():
        release = load_release(mbid)
        local_titles = {trackmatch.fold(t.get("title") or "") for t in local}
        if not release:
            artist = max({t.get("artist") or "" for t in local}, key=len) or ""
            album = max({t.get("album") or "" for t in local}, key=len) or ""
            summary.append({"artist": artist, "album": album, "reference": "mb",
                            "ref_id": mbid, "total": len(local),
                            "present": len(local), "missing": 0,
                            "status": "no-cache",
                            "missing_titles": "release not in mbcache"})
            continue
        artist = primary_artist(release)
        album = release.get("title") or (
            max({t.get("album") or "" for t in local}, key=len) or "")
        rtracks = release_tracks(release)
        missing = []
        for num, title, length, isrc, tarts in rtracks:
            if not title:
                continue
            if not present_in_library(trackmatch.fold(title), tarts, local_titles):
                missing.append((num, title, length, isrc, tarts))
        total = len(rtracks)
        present = total - len(missing)
        status = "complete" if not missing else "missing"
        mt = " | ".join(f"{n} {t}" for n, t, _, _, _ in missing)
        summary.append({"artist": artist, "album": album, "reference": "mb",
                        "ref_id": mbid, "total": total, "present": present,
                        "missing": len(missing), "status": status,
                        "missing_titles": mt})
        if missing:
            year = (release.get("date") or "")[:4]
            for num, title, length, isrc, tarts in missing:
                add_work(tarts, title, album, year,
                         length if length else "", isrc or "", "")

    # --- pass 2: Spotify saved albums (no MB id) ----------------------------
    jpath = os.path.join(args.dump_dir, "library.json")
    saved = []
    if os.path.isfile(jpath):
        with open(jpath) as f:
            data = json.load(f)
        saved = data.get("saved_albums", [])
    else:
        data = None

    if data is not None:
        for alb in saved:
            name = alb.get("name") or ""
            alb_artist = alb.get("artists") or ""
            key = (trackmatch.fold(alb_artist), trackmatch.fold(name))
            in_album = album_titles.get(key, set())
            rtracks = alb.get("tracks") or []
            missing = []
            for t in rtracks:
                if t.get("is_local"):
                    continue
                hint = t.get("artists") or alb_artist
                if not present_in_library(trackmatch.fold(t.get("title") or ""),
                                          hint, in_album):
                    missing.append(t)
            total = alb.get("total_tracks") or len(rtracks)
            present = total - len(missing)
            status = "complete" if not missing else "missing"
            mt = " | ".join(f"{t.get('track_number','')} {t.get('title','')}"
                            for t in missing)
            summary.append({"artist": alb_artist, "album": name,
                            "reference": "spotify", "ref_id": alb.get("spotify_id", ""),
                            "total": total, "present": present,
                            "missing": len(missing), "status": status,
                            "missing_titles": mt})
            if missing:
                for t in missing:
                    add_work(t.get("artists") or alb_artist, t.get("title") or "",
                             name, str(alb.get("year") or ""),
                             t.get("duration_ms") or "", t.get("isrc") or "",
                             t.get("spotify_id") or "")

    # --- pass 3: library albums with neither reference -----------------------
    # (artist, album) groups whose files carry no mbid and which match no saved
    # album. Their full track lists are unknown without a lookup; list them so
    # the download pass knows what to look up.
    display_name = {}
    for t in tracks:
        art = t.get("artist") or ""
        alb = t.get("album") or ""
        display_name[(trackmatch.fold(art), trackmatch.fold(alb))] = (art, alb)
    saved_keys = {(trackmatch.fold(s.get("artists") or ""),
                   trackmatch.fold(s.get("name") or "")) for s in saved}
    keyed = set()
    for t in tracks:
        mbid = mbid_by_path.get(t.get("path") or "")
        art = trackmatch.fold(t.get("artist") or "")
        alb = trackmatch.fold(t.get("album") or "")
        if not mbid and art and alb:
            keyed.add((art, alb))
    for (art, alb) in sorted(keyed):
        if (art, alb) in saved_keys:
            continue
        art_d, alb_d = display_name.get((art, alb), (art, alb))
        count = len(album_titles.get((art, alb), set()))
        summary.append({"artist": art_d, "album": alb_d, "reference": "none",
                        "ref_id": "", "total": count, "present": count,
                        "missing": 0, "status": "no-ref",
                        "missing_titles": "track list unknown - lookup at run time"})

    # --- write outputs -------------------------------------------------------
    inv_path = os.path.join(args.dump_dir, "album-inventory.tsv")
    inv_cols = ["artist", "album", "reference", "ref_id", "total", "present",
                "missing", "status", "missing_titles"]
    with open(inv_path, "w") as f:
        f.write("\t".join(inv_cols) + "\n")
        for r in sorted(summary, key=lambda r: (-int(r["missing"] or 0),
                                                (r["artist"] or "").lower(),
                                                (r["album"] or "").lower())):
            f.write("\t".join(clean(str(r.get(c, ""))) for c in inv_cols) + "\n")

    wl_path = os.path.join(args.dump_dir, "album-missing-mb.tsv")
    with open(wl_path, "w") as f:
        f.write("\t".join(COLS) + "\n")
        for r in sorted(work_rows, key=lambda r: (r["artists"].lower(),
                                                  r["album"].lower(),
                                                  r["title"].lower())):
            f.write("\t".join(clean(str(r.get(c, ""))) for c in COLS) + "\n")

    n_mb = sum(1 for r in summary if r["reference"] == "mb"
               and r["status"] == "missing")
    n_sp = sum(1 for r in summary if r["reference"] == "spotify"
               and r["status"] == "missing")
    n_nocache = sum(1 for r in summary if r["status"] == "no-cache")
    n_noref = sum(1 for r in summary if r["status"] == "no-ref")
    tot_missing = sum(int(r["missing"]) for r in summary
                      if r["status"] == "missing")
    print()
    print(f"albums missing tracks : {n_mb + n_sp} "
          f"({n_mb} MusicBrainz, {n_sp} Spotify-saved)")
    print(f"missing tracks total  : {tot_missing}")
    print(f"MB id, release not in : {n_nocache}   (fetch at run time)")
    print(f"no reference at all   : {n_noref}   (lookup at run time)")
    print()
    print(f"inventory : {inv_path}")
    print(f"work list : {wl_path}")


if __name__ == "__main__":
    main()
