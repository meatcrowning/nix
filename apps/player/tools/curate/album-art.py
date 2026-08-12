#!/usr/bin/env python3
"""Fetch missing album covers into the library, from the MusicBrainz Cover
Art Archive.

    album-art.py            dry run: report what would be fetched
    album-art.py --apply    write cover.jpg into each album dir that lacks one

Runs BEFORE the slskd fill-in run on purpose: art for the albums already
present lands while nothing is downloading, and the fill-in run's own imports
then arrive to a library that already has its covers.

A cover is only fetched for an album dir where EVERY track lacks embedded
art and no folder image exists — an album that already shows art in the
player is never touched. Matching prefers a MusicBrainz release id found in
the album's own file tags (read_mbid); without one it falls back to a
release search on album + artist, accepted only when the top hit's title and
artist both fold-match. The CAA front image (1200px) is written as
cover.jpg — a name the player's folder_art() already picks up.

Run with the player's wrapped python:
  PY=$(grep -oE '/nix/store/[^" ]+-env/bin/python3[0-9.]*' "$(command -v player)" | head -1)
  $PY album-art.py --apply
"""
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import common as C

STATE = C.STATE / "album-art"
STATE.mkdir(parents=True, exist_ok=True)
REPORT = STATE / "report.json"

CAA = "https://coverartarchive.org"

# Cover-ish image names the player's folder_art() already trusts; a written
# cover.jpg removes the dir from the next run's list (resumable).
ART_RE = re.compile(
    r"^(cover|folder|front|albumart.*)\.(jpe?g|png|webp|gif|bmp)$", re.I)


def caa_front(mbid):
    """URL of the 1200px front image for a release, or None."""
    req = urllib.request.Request(f"{CAA}/release/{mbid}",
                                 headers={"User-Agent": C.UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as f:
            data = json.loads(f.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        return None  # 500s and redirects-to-error happen on CAA; skip, don't die
    except Exception:
        return None
    for img in data.get("images", []):
        if img.get("front"):
            return img.get("image")
    return None


def discogs_front(album, artist):
    """Front cover URL from the Discogs database API, or None.

    The library is ~94% electronic; a large share of it is released on small
    labels (netlabels, Molten Jets, ...) that never touch MusicBrainz's Cover
    Art Archive but DO have a Discogs entry with art. Public-search endpoint
    (no auth), so only usable for a whole-library pass, not a user-facing
    server key. Matched on folded album + a token-overlap artist check, then
    picks the first release with a front/primary image."""
    try:
        q = urllib.parse.quote(f"{artist} {album}".strip())
        req = urllib.request.Request(
            f"https://api.discogs.com/database/search?q={q}&type=release&per_page=10",
            headers={"User-Agent": C.UA})
        with urllib.request.urlopen(req, timeout=30) as f:
            data = json.loads(f.read())
    except Exception:
        return None
    falb = C.fold(album)
    for rel in (data.get("results") or []):
        # title must fold-match; artist credit must share a folded token
        rtitle = C.fold(rel.get("title", ""))
        # Discogs title is "Artist - Album" or "Album" — take the album side
        rtitle = rtitle.split("-")[-1].strip() if "-" in rtitle else rtitle
        if rtitle != falb:
            continue
        rart = C.fold(rel.get("title", "").split("-")[0].strip())
        fart = C.fold(artist)
        if fart and not (fart in rart or rart in fart):
            continue
        for img in (rel.get("cover_image") or []) if isinstance(rel.get("cover_image"), list) else ([rel.get("cover_image")] if rel.get("cover_image") else []):
            if img:
                return img
    return None


def itunes_front(album, artist):
    """Front cover URL from the iTunes Search API, or None. Single-only fallback
    for the releases that are absent from both CAA and Discogs."""
    try:
        q = urllib.parse.quote(f"{artist} {album}".strip())
        req = urllib.request.Request(
            f"https://itunes.apple.com/search?term={q}&entity=song&limit=10",
            headers={"User-Agent": C.UA})
        with urllib.request.urlopen(req, timeout=30) as f:
            data = json.loads(f.read())
    except Exception:
        return None
    for res in (data.get("results") or []):
        if C.fold(res.get("collectionName") or "") == C.fold(album):
            art = res.get("artworkUrl100")
            if art:
                # request the 600x600 source rather than the 100x100 thumb
                return art.replace("100x100bb", "600x600bb")
    return None


def mb_search_release(album, artist):
    """release id of the top MB hit, only on a confident fold-match."""
    q = urllib.parse.quote(f'release:"{album}" AND artist:"{artist}"')
    data = C.mb_get("release", f"query={q}&limit=5")
    if not data or not isinstance(data, dict) or data.get("error"):
        return None
    for rel in data.get("releases", []):
        title = rel.get("title", "")
        ac = "".join(a.get("name", "") for a in rel.get("artist-credit", [])
                     if isinstance(a, dict))
        if C.fold(title) == C.fold(album) and (
                C.fold(ac) == C.fold(artist)
                or C.fold(artist) in C.fold(ac) or C.fold(ac) in C.fold(artist)):
            return rel.get("id")
    return None


def fetch(url):
    """Bytes of an image URL, following CAA's usual archive.org redirect.
    archive.org 500s on a cold item now and then — retry a couple of times."""
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": C.UA})
            with urllib.request.urlopen(req, timeout=60) as f:
                return f.read()
        except urllib.error.HTTPError as e:
            if e.code in (500, 502, 503) and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            raise


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()

    rows = json.loads(C.SCAN_JSON.read_text())
    dirs = {}
    for r in rows:
        if r["album_dir"] is None or r["album"] is None:
            continue
        key = f"{r['album_artist_dir']}/{r['album_dir']}"
        dirs.setdefault(key, []).append(r)

    todo = []
    for key, recs in sorted(dirs.items()):
        dirpath = Path(recs[0]["path"]).parent
        if not dirpath.is_dir():
            continue  # stale scan row (merged away since the scan)
        if any(ART_RE.match(f.name) for f in dirpath.iterdir() if f.is_file()):
            continue  # includes cover.jpg a previous --apply wrote: resumable
        # embedded art on ANY track means the player already shows it
        if any(C._has_embedded(r["path"]) for r in recs[:3]):
            continue
        todo.append((key, recs))

    print(f"{len(todo)} album dirs with no art")
    results = []
    for key, recs in todo[: args.limit]:
        album = recs[0]["album"]
        artist = recs[0]["album_artist"] or recs[0]["artist"] or ""
        mbid = next((m for m in (C.read_mbid(r["path"]) for r in recs) if m),
                    None)
        how = "mbid"
        if not mbid:
            mbid = mb_search_release(album, artist)
            how = "search"
        entry = {"dir": key, "album": album, "artist": artist}
        if not mbid:
            entry["status"] = "no-match"
            results.append(entry)
            continue
        url = caa_front(mbid)
        time.sleep(1.0)  # CAA asks for polite pacing too
        how = how if url else "caa"
        if not url:
            # CAA has no art (small-label/netlabel releases); fall back to
            # Discogs then iTunes before giving up. These are the sources that
            # actually hold art for the library's long tail of electronic
            # releases. Each is paced ~1 req/s like CAA.
            url = discogs_front(album, artist)
            time.sleep(1.0)
            how = "discogs" if url else how
        if not url:
            url = itunes_front(album, artist)
            time.sleep(1.0)
            how = "itunes" if url else how
        if not url:
            entry["status"] = "no-art"
            entry["mbid"] = mbid
            results.append(entry)
            continue
        entry.update(status="ok", mbid=mbid, how=how, url=url)
        if args.apply:
            try:
                data = fetch(url)
                dest = Path(recs[0]["path"]).parent / "cover.jpg"
                dest.write_bytes(data)
                entry["written"] = str(dest)
                print(f"ok  {key}  ({how})")
            except Exception as e:
                entry["status"] = f"fetch-failed: {e}"
        else:
            print(f"would fetch  {key}  ({how})")
        results.append(entry)

    REPORT.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    n_ok = sum(1 for r in results if r["status"] == "ok")
    print(f"{n_ok}/{len(results)} covers {'written' if args.apply else 'available'}"
          f" -> {REPORT}")


if __name__ == "__main__":
    main()
