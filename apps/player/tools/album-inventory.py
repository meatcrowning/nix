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
     `--ref-lookup` does that lookup inside the inventory: a guarded
     MusicBrainz search (title/artist agreement, track-count >= owned, a
     single release-group, >=80% of owned titles on the release) resolves the
     album to a release and feeds its missing tracks into the work list;
     anything that fails the guards stays no-ref rather than being guessed.

Outputs (--dump-dir, default the spotify dump dir):
  album-inventory.tsv  per-album summary: artist, album, reference, ref id,
                       total tracks on the reference, present in the library,
                       missing, status, missing titles.
  album-missing-mb.tsv the missing tracks as a work list in soulseek-missing.py's
                       TSV format (COLS from spotify-missing.py, plus
                       album_artist + album_ref), so the downloader can be
                       pointed straight at it and the import step can place
                       each download into its album:
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

# soulseek-missing.py's work-list columns (spotify-missing.py COLS), plus the
# album identity the placement step needs: album_artist (the folder artist,
# NOT the track artist) and album_ref (the MusicBrainz release id / Spotify
# album id the row's track list came from). soulseek-missing.py records them
# into soulseek-state.tsv at enqueue, and player-add.py places each download
# into its album folder from that record.
COLS = ["artists", "title", "album", "year", "duration_ms", "isrc",
        "spotify_id", "sources", "album_artist", "album_ref"]


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
    ap.add_argument("--ref-lookup", action="store_true",
                    help="resolve no-ref albums against MusicBrainz (search + "
                         "guarded match, ~1 req/s, cached; several minutes for "
                         "a library this size)")
    ap.add_argument("--ref-lookup-limit", type=int, default=0,
                    help="stop the ref-lookup pass after N albums (0 = all)")
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
    # folded title variant -> set of folded artist variants, for the generous
    # "elsewhere" match (a track under 'Jorge Cafrune & Marito' counts for an
    # album by 'Jorge Cafrune')
    title_artists = {}
    # (folded artist, folded album) -> set of folded title variants, for the
    # album view
    album_titles = {}
    # (folded artist variant, folded title variant) -> None — the exact key
    # set soulseek-missing.py builds at queue time (trackmatch.keys against
    # the live DB), so a track the downloader would skip as already-owned is
    # never listed as missing in the first place
    lib_keys = set()
    # (folded artist, folded album) -> [folded filename token lists], for the
    # on-disk check: a file named "06 - String Quartet no. 3 Mishima - II.
    # November 25 - Ichigaya.flac" IS the reference track even when its title
    # tag disagrees (the import-time 'skip (exists)' class)
    album_stems = {}
    # (folded artist, folded album) -> number of tracks on disk (album_titles
    # holds VARIANTS, so its len overcounts)
    album_n = {}
    for t in tracks:
        art = t.get("artist") or ""
        title = t.get("title") or ""
        alb = t.get("album") or ""
        fa = trackmatch.fold(art)
        ft = trackmatch.fold(title)
        falb = trackmatch.fold(alb)
        for a in trackmatch.artist_variants(art):
            fa2 = trackmatch.fold(a)
            if not fa2:
                continue
            for tt in trackmatch.title_variants(title):
                ft2 = trackmatch.fold(tt)
                if ft2:
                    title_artists.setdefault(ft2, set()).add(fa2)
                    lib_keys.add((fa2, ft2))
        if fa and falb:
            album_titles.setdefault((fa, falb), set()).update(
                trackmatch.fold(v) for v in trackmatch.title_variants(title))
            album_n[(fa, falb)] = album_n.get((fa, falb), 0) + 1
            stem = os.path.splitext(os.path.basename(t.get("path") or ""))[0]
            album_stems.setdefault((fa, falb), []).append(
                trackmatch.fold(stem).split())

    def present_in_library(artist, title, in_album, stems=()):
        """A reference track is present if any of its artist/title variants
        sits in the library under the exact key the queue-time guard uses, in
        its album's own files, as a filename on disk in the album's dirs, or
        anywhere in the library under a shared-artist token."""
        ft = trackmatch.fold(title)
        if not ft:
            return True  # no title signal; nothing to fetch
        # the album's own files, variants included
        if any(tv in in_album
               for tv in (ft, *[trackmatch.fold(v)
                                for v in trackmatch.title_variants(title)])):
            return True
        # exact mirror of soulseek-missing's queue-time dedup
        for a in trackmatch.artist_variants(artist or ""):
            fa = trackmatch.fold(a)
            if not fa:
                continue
            if any((fa, trackmatch.fold(v)) in lib_keys
                   for v in trackmatch.title_variants(title)):
                return True
        # on disk in this album's dirs: folded title tokens, in order, inside
        # a filename stem ('II. November 25 - Ichigaya' in '06 - String
        # Quartet no. 3 Mishima - II. November 25 - Ichigaya.flac'). Single-
        # token titles are not name-confirmable ('Love' vs 'Love Me Tender').
        toks = ft.split()
        if len(toks) >= 2:
            for stem in stems:
                if all(t in iter(stem) for t in toks):
                    return True
        # elsewhere in the library under a shared artist token
        arts = title_artists.get(ft, set())
        if not arts:
            return False
        if not artist:
            return True  # no artist signal; any title match counts
        return any(shared_artist_token(artist, a) for a in arts)

    summary = []
    work_rows = []
    seen_work = set()  # dedup identical missing tracks across references

    def add_work(artists, title, album, year, duration_ms, isrc, spotify_id,
                 album_artist, album_ref):
        key = trackmatch.fold(artists) + "||" + trackmatch.fold(title)
        if key in seen_work:
            return
        seen_work.add(key)
        work_rows.append({"artists": artists, "title": title, "album": album,
                          "year": year, "duration_ms": duration_ms,
                          "isrc": isrc, "spotify_id": spotify_id,
                          "sources": album, "album_artist": album_artist,
                          "album_ref": album_ref})

    # --- pass 1: MusicBrainz releases --------------------------------------
    by_mbid = {}
    for i, t in enumerate(tracks):
        mbid = mbid_by_path.get(t.get("path") or "")
        if mbid:
            by_mbid.setdefault(mbid, []).append(t)

    for mbid, local in by_mbid.items():
        release = load_release(mbid)
        local_titles = {trackmatch.fold(v) for t in local
                        for v in trackmatch.title_variants(t.get("title") or "")}
        local_stems = [trackmatch.fold(
            os.path.splitext(os.path.basename(t.get("path") or ""))[0]).split()
            for t in local]
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
            if not present_in_library(tarts, title, local_titles, local_stems):
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
                         length if length else "", isrc or "", "",
                         artist, mbid)

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
                if not present_in_library(hint, t.get("title") or "", in_album,
                                          album_stems.get(key, [])):
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
                             t.get("spotify_id") or "", alb_artist,
                             alb.get("spotify_id", ""))

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
        count = album_n.get((art, alb), 0)
        summary.append({"artist": art_d, "album": alb_d, "reference": "none",
                        "ref_id": "", "total": count, "present": count,
                        "missing": 0, "status": "no-ref",
                        "missing_titles": "track list unknown - lookup at run time"})

    # --- pass 3b: no-ref albums looked up on MusicBrainz (--ref-lookup) ------
    # The albums above have no reference at all: no MusicBrainz release id in
    # their tags, no Spotify saved-album match. With --ref-lookup, each is
    # searched on MusicBrainz (artist + album title), and a match is only
    # trusted when it passes every guard: title/artist agreement, a release
    # track count >= what the library already has, a single release-group
    # among the candidates (editions of one album are fine; two different
    # albums with the same name are not), and -- after the tracklist is
    # fetched into the shared mbcache -- at least 80% of the on-disk titles
    # actually present on the release. Anything less stays no-ref: never
    # guessed. Results are cached in <dump-dir>/album-ref-lookup.json so a
    # re-run (or one killed halfway) pays for each search at most once.
    if args.ref_lookup:
        import time as _time
        import urllib.parse
        import urllib.request

        UA = "lam-library-album-inventory/1.0 ( joelcvan@gmail.com )"
        cache_path = os.path.join(args.dump_dir, "album-ref-lookup.json")
        lcache = {}
        if os.path.isfile(cache_path):
            with open(cache_path) as f:
                lcache = json.load(f)
        noref_rows = [r for r in summary if r["status"] == "no-ref"]
        print(f"\nref-lookup: {len(noref_rows)} no-ref albums, ~1 req/s "
              f"(search + fetch for the resolved ones)", flush=True)
        done = 0

        def mb_get(url):
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            for attempt in range(4):
                try:
                    with urllib.request.urlopen(req, timeout=30) as f:
                        return json.load(f)
                except Exception:
                    _time.sleep(1.5 * (attempt + 1))
            raise  # give up after 4 attempts

        for row in sorted(noref_rows, key=lambda r: int(r["total"] or 0)):
            fa, falb = trackmatch.fold(row["artist"]), trackmatch.fold(row["album"])
            key = fa + "\t" + falb
            if key in lcache:
                row["_mbid"] = lcache[key].get("mbid")
            else:
                try:
                    q = 'artist:"%s" AND release:"%s"' % (row["artist"],
                                                          row["album"])
                    data = mb_get("https://musicbrainz.org/ws/2/release/?query="
                                  + urllib.parse.quote(q) + "&fmt=json&limit=5")
                    _time.sleep(1.05)
                except Exception:
                    print(f"  lookup error on {row['artist']} - {row['album']}; "
                          f"not cached, will retry next run", flush=True)
                    continue
                cands = []
                for rel in data.get("releases") or []:
                    if not (trackmatch.title_matches(rel.get("title") or "",
                                                     row["album"])
                            and shared_artist_token(row["artist"],
                                                    primary_artist(rel))):
                        continue
                    total = sum((m.get("track-count") or 0)
                                for m in rel.get("media") or [])
                    if total >= int(row["total"] or 0):
                        cands.append(rel)
                # one release-group among the candidates = editions of one
                # album: pick the fullest. Two different albums, same name:
                # not confident, leave no-ref.
                groups = {}
                for rel in cands:
                    rg = (rel.get("release-group") or {}).get("id") or rel["id"]
                    groups.setdefault(rg, []).append(rel)
                if len(groups) == 1:
                    rel = max(groups[list(groups)[0]],
                              key=lambda r: sum((m.get("track-count") or 0)
                                                for m in r.get("media") or []))
                    row["_mbid"] = rel["id"]
                else:
                    row["_mbid"] = None
                lcache[key] = {"mbid": row["_mbid"]}
            done += 1
            if args.ref_lookup_limit and done >= args.ref_lookup_limit:
                break
            if row.get("_mbid"):
                release = load_release(row["_mbid"])
                if not release:
                    try:
                        release = mb_get(
                            f"https://musicbrainz.org/ws/2/release/{row['_mbid']}"
                            "?fmt=json&inc=recordings+artist-credits")
                        os.makedirs(MBCACHE, exist_ok=True)
                        with open(os.path.join(MBCACHE,
                                               row["_mbid"] + ".json"),
                                  "w") as f:
                            json.dump(release, f)
                        _time.sleep(1.05)
                    except Exception:
                        print(f"  fetch error on {row['_mbid']} "
                              f"({row['artist']} - {row['album']}); "
                              f"will retry next run", flush=True)
                        continue
                rtracks = release_tracks(release)
                on_disk = album_titles.get((fa, falb), set())
                rt_folds = {trackmatch.fold(t) for _, t, _, _, _ in rtracks}
                if on_disk:
                    hit = sum(1 for t in on_disk if t in rt_folds)
                    if hit / len(on_disk) < 0.8:
                        # a different edition, not this album
                        row["_mbid"] = None
                        lcache[key] = {"mbid": None}
                        continue
                missing = []
                for num, title, length, isrc, tarts in rtracks:
                    if not title:
                        continue
                    if not present_in_library(tarts, title, on_disk,
                                              album_stems.get((fa, falb), [])):
                        missing.append((num, title, length, isrc, tarts))
                total = len(rtracks)
                row.update({"reference": "mb", "ref_id": row["_mbid"],
                            "total": total, "present": total - len(missing),
                            "missing": len(missing),
                            "status": "complete" if not missing else "missing",
                            "missing_titles": " | ".join(
                                f"{n} {t}" for n, t, _, _, _ in missing)})
                if missing:
                    year = (release.get("date") or "")[:4]
                    for num, title, length, isrc, tarts in missing:
                        add_work(tarts, title, row["album"], year,
                                 length if length else "", isrc or "", "",
                                 row["artist"], row["_mbid"])
            if done % 50 == 0:
                with open(cache_path, "w") as f:
                    json.dump(lcache, f)
                print(f"  {done}/{len(noref_rows)} looked up", flush=True)
        with open(cache_path, "w") as f:
            json.dump(lcache, f)
        n_found = sum(1 for r in noref_rows if r["status"] != "no-ref")
        print(f"ref-lookup done: {n_found} resolved, "
              f"{len(noref_rows) - n_found} still no-ref")

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
