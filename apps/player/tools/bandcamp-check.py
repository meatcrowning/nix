#!/usr/bin/env python3
"""Find which tracks from missing.tsv are on Bandcamp as free or
name-your-price downloads.

Input : ~/.local/share/spotify-dump/missing.tsv (from spotify-missing.py)
Output: bandcamp-free.tsv  - FREE or name-your-price (you can enter $0)
        bandcamp-paid.tsv  - on Bandcamp, but costs money
        cache.jsonl        - one record per artist, so runs resume

This only READS public pages and reports URLs. It deliberately does not touch
the download flow: Bandcamp's free downloads are email-gated behind
/download_check, which robots.txt disallows, so the last step is a human
clicking a link.

Politeness, because this is someone else's server and the artist list is long:
  * robots.txt is respected - /search and /api are disallowed, so artist pages
    are reached by GUESSING the subdomain from the artist name and verifying
    the name on the page, never by searching.
  * one request at a time, fixed delay, exponential backoff on 429, and a hard
    stop if 429s persist.
  * every artist result is cached, so a re-run costs nothing.

Classification comes from the `data-tralbum` JSON each release page embeds:
  freeDownloadPage present            -> FREE      (a real free-download link)
  current.download_pref == 1          -> FREE
  download_pref == 2, minimum_price 0 -> NYP       (name your price, $0 valid)
  minimum_price > 0                   -> PAID
"""

import argparse
import collections
import csv
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "pylib"))
import trackmatch as tm  # noqa: E402

DUMP_DIR = os.path.expanduser("~/.local/share/spotify-dump")
CACHE_DIR = os.path.expanduser("~/.cache/bandcamp-check")
CACHE_FILE = os.path.join(CACHE_DIR, "cache.jsonl")

UA = ("Mozilla/5.0 (X11; Linux x86_64) spotify-gap-checker/1.0 "
      "(personal library gap check)")
DELAY = 1.5           # seconds between requests
MAX_RELEASES = 40     # per artist, so one huge discography can't dominate a run

_last_request = [0.0]
_consecutive_429 = [0]


def fetch(url):
    """Rate-limited GET. Returns page text, or None for 404/410."""
    wait = DELAY - (time.time() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=25) as f:
                _last_request[0] = time.time()
                _consecutive_429[0] = 0
                return f.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            _last_request[0] = time.time()
            if e.code in (404, 410):
                return None
            if e.code == 429:
                _consecutive_429[0] += 1
                if _consecutive_429[0] >= 5:
                    raise SystemExit(
                        "Bandcamp is rate limiting persistently - stopping. "
                        "Progress is cached; re-run later to continue.")
                back = 30 * (attempt + 1)
                print(f"    rate limited, backing off {back}s", flush=True)
                time.sleep(back)
                continue
            if 500 <= e.code < 600:
                time.sleep(5 * (attempt + 1))
                continue
            return None
        except Exception:
            _last_request[0] = time.time()
            time.sleep(3 * (attempt + 1))
    return None


def slug_candidates(artist):
    """Plausible Bandcamp subdomains for an artist name. Kept short - each
    one is a request, and most artists who are on Bandcamp use the obvious
    form."""
    base = tm.fold(artist)
    flat = re.sub(r"[^a-z0-9]", "", base)
    hyph = re.sub(r"\s+", "-", base.strip())
    out = []
    for c in (flat, hyph, flat + "music", flat + "official"):
        if c and len(c) >= 2 and c not in out:
            out.append(c)
    return out[:4]


def classify(d):
    cur = d.get("current") or {}
    if d.get("freeDownloadPage"):
        return "FREE"
    dp = cur.get("download_pref")
    mp = cur.get("minimum_price") or 0
    if dp == 1:
        return "FREE"
    if dp == 2 and mp == 0:
        return "NYP"
    if mp:
        return f"PAID:{mp:g}"
    return "?"


def parse_tralbum(page):
    m = re.search(r'data-tralbum="([^"]+)"', page)
    if not m:
        return None
    try:
        return json.loads(html.unescape(m.group(1)))
    except Exception:
        return None


def find_artist(artist):
    """Guess the subdomain and confirm the page really is this artist.
    Returns (host, [release paths]) or None."""
    for slug in slug_candidates(artist):
        page = fetch(f"https://{slug}.bandcamp.com/music")
        if not page:
            continue
        m = re.search(r'property="og:site_name" content="([^"]*)"', page)
        site = html.unescape(m.group(1)) if m else ""
        # Guard against a slug collision landing on a different artist.
        if not tm.artist_matches(artist, site):
            continue
        links = sorted(set(re.findall(r'href="(/(?:album|track)/[^"?#]+)"', page)))
        return slug, site, links[:MAX_RELEASES]
    return None


def load_cache():
    seen = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    seen[rec["artist"]] = rec
                except Exception:
                    pass
    return seen


def append_cache(rec):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(CACHE_FILE, "a") as f:
        f.write(json.dumps(rec) + "\n")


COLS = ["status", "artist", "title", "release", "tracks_on_release", "url"]


def write_tsv(path, rows):
    with open(path, "w") as f:
        f.write("\t".join(COLS) + "\n")
        for r in rows:
            f.write("\t".join(str(r.get(c, "")).replace("\t", " ") for c in COLS) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump-dir", default=DUMP_DIR)
    ap.add_argument("--min-tracks", type=int, default=1,
                    help="only artists with at least this many missing tracks")
    ap.add_argument("--limit", type=int, help="stop after N artists this run")
    args = ap.parse_args()

    rows = list(csv.DictReader(
        open(os.path.join(args.dump_dir, "missing.tsv")), delimiter="\t"))
    by_artist = collections.defaultdict(list)
    for r in rows:
        by_artist[tm.artist_variants(r["artists"])[-1]].append(r["title"])

    order = sorted(by_artist.items(), key=lambda kv: -len(kv[1]))
    order = [(a, t) for a, t in order if len(t) >= args.min_tracks]

    cache = load_cache()
    todo = [(a, t) for a, t in order if a not in cache]
    if args.limit:
        todo = todo[:args.limit]

    print(f"{len(order)} artists in scope, {len(cache)} already cached, "
          f"{len(todo)} to check this run", flush=True)

    for n, (artist, titles) in enumerate(todo, 1):
        print(f"[{n}/{len(todo)}] {artist} ({len(titles)} missing)", flush=True)
        rec = {"artist": artist, "found": False, "releases": []}
        try:
            hit = find_artist(artist)
        except SystemExit:
            raise
        except Exception as e:
            print(f"    error: {type(e).__name__}", flush=True)
            hit = None
        if hit:
            slug, site, links = hit
            rec.update(found=True, slug=slug, site=site)
            print(f"    -> {slug}.bandcamp.com ({len(links)} releases)", flush=True)
            for path in links:
                page = fetch(f"https://{slug}.bandcamp.com{path}")
                if not page:
                    continue
                d = parse_tralbum(page)
                if not d:
                    continue
                cur = d.get("current") or {}
                rec["releases"].append({
                    "title": cur.get("title") or "",
                    "status": classify(d),
                    "url": f"https://{slug}.bandcamp.com{path}",
                    "tracks": [t.get("title") or ""
                               for t in (d.get("trackinfo") or [])],
                })
            free = sum(1 for r in rec["releases"] if r["status"] in ("FREE", "NYP"))
            print(f"    {len(rec['releases'])} releases, {free} free/NYP", flush=True)
        append_cache(rec)
        cache[artist] = rec

    # Build the report from the whole cache, not just this run.
    free_rows, paid_rows = [], []
    for artist, titles in order:
        rec = cache.get(artist)
        if not rec or not rec.get("found"):
            continue
        for want in titles:
            for rel in rec["releases"]:
                match = any(tm.title_matches(want, t) for t in rel["tracks"])
                if not match:
                    continue
                row = {"status": rel["status"], "artist": artist, "title": want,
                       "release": rel["title"], "url": rel["url"],
                       "tracks_on_release": len(rel["tracks"])}
                (free_rows if rel["status"] in ("FREE", "NYP") else paid_rows).append(row)
                break

    fp = os.path.join(args.dump_dir, "bandcamp-free.tsv")
    pp = os.path.join(args.dump_dir, "bandcamp-paid.tsv")
    write_tsv(fp, free_rows)
    write_tsv(pp, paid_rows)

    checked = sum(1 for a, _ in order if a in cache)
    found = sum(1 for a, _ in order if cache.get(a, {}).get("found"))
    print(f"\nartists checked  : {checked}/{len(order)}")
    print(f"found on Bandcamp: {found}")
    print(f"free / NYP tracks: {len(free_rows)}   -> {fp}")
    print(f"paid tracks      : {len(paid_rows)}   -> {pp}")


if __name__ == "__main__":
    main()
