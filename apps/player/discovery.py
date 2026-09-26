"""External music catalog. A single worker owns its private cache and receipts.

Catalog rows never enter library.db. Network/SQLite reads run off the GUI
thread; the importer remains the only path from a download to the library.
"""
import hashlib
import json
import math
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import lastfm
import trackmatch


def album_name(name):
    # Edition suffixes must not turn an owned record into a new discovery.
    name = re.sub(r"\s*[\[(].*?(?:remaster|deluxe|expanded|anniversary|edition).*?[\])]", "", name, flags=re.I)
    name = re.sub(r"\s*[-–]\s*(?:EP|Single|.*remaster.*|.*deluxe.*)$", "", name, flags=re.I)
    return trackmatch.fold(name)


def identity(artist, album):
    return trackmatch.fold(artist) + "\0" + album_name(album)


def rows(value):
    return value if isinstance(value, list) else [value] if isinstance(value, dict) else []


def https_url(url, suffixes):
    try:
        p = urllib.parse.urlsplit(str(url))
        host = (p.hostname or "").lower()
        return p.scheme == "https" and not p.username and not p.password and p.port in (None, 443) and any(
            host == s or host.endswith("." + s) for s in suffixes)
    except ValueError:
        return False


def preview_url(url):
    return https_url(url, ("mzstatic.com", "itunes.apple.com"))


class Catalog:
    def __init__(self, db, state, fetch=None, lastfm_call=None):
        self.db = Path(db)
        self.path = Path(state) / "discovery.json"
        self.fetch = fetch or self._fetch
        self.fm = lastfm_call or lastfm.call
        self._next_request = 0
        try:
            self.state = json.loads(self.path.read_text())
            if not isinstance(self.state, dict):
                self.state = {}
        except (OSError, ValueError):
            self.state = {}
        for key in ("cache", "feedback", "requests", "settings"):
            if not isinstance(self.state.get(key), dict):
                self.state[key] = {}
        if not isinstance(self.state.get("items"), list):
            self.state["items"] = []
        self.settings = self.state["settings"]
        self.settings.setdefault("mode", "manual")
        self.settings.setdefault("weekly", 2)
        self.settings.setdefault("budget", 2)
        self.settings.setdefault("quality", "lossless")
        self.settings.setdefault("host", "")
        for key, allowed, default in (("mode", ("manual", "review", "automatic"), "manual"),
                                      ("weekly", (1, 2, 5, 10), 2), ("budget", (1, 2, 5, 10), 2),
                                      ("quality", ("lossless", "high", "any"), "lossless")):
            if self.settings[key] not in allowed:
                self.settings[key] = default

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.state, ensure_ascii=False))
        temp.chmod(0o600)
        temp.replace(self.path)

    def _fetch(self, url):
        delay = self._next_request - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._next_request = time.monotonic() + 3.1  # Apple: about 20 requests/min.
        req = urllib.request.Request(url, headers={"User-Agent": lastfm.USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.load(response)

    def cached(self, key, get, ttl=86400):
        item = self.state["cache"].get(key, {})
        if item.get("until", 0) > time.time():
            return item["value"]
        value = get()
        self.state["cache"][key] = {"value": value, "until": time.time() + ttl}
        # Bound artist/search snapshots without discarding user decisions.
        if len(self.state["cache"]) > 400:
            oldest = sorted(self.state["cache"], key=lambda k: self.state["cache"][k]["until"])
            for k in oldest[:100]:
                del self.state["cache"][k]
        return value

    def library(self):
        with sqlite3.connect(self.db.as_uri() + "?mode=ro", uri=True, timeout=2) as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute(
                "SELECT id,album_id,artist,album_artist,album,title,rating,favorite,play_count,last_played FROM tracks")]

    def owned(self, item, library):
        return [r for r in library if identity(r.get("album_artist") or r["artist"], r["album"]) ==
                identity(item["artist"], item["album"])]

    def visible(self, library=None):
        library = self.library() if library is None else library
        out = []
        for item in self.state["items"]:
            fb = self.state["feedback"].get(item["key"], {})
            req = self.state["requests"].get(item["key"], {})
            owned = self.owned(item, library)
            # Acquired recommendations remain actionable; pre-existing albums vanish.
            if (owned and not req) or fb.get("dismissed"):
                continue
            have = Counter(trackmatch.fold(r["title"]) for r in owned)
            expected = Counter(trackmatch.fold(t["title"]) for t in item.get("tracks", []))
            complete = bool(expected) and all(have[title] >= count for title, count in expected.items())
            status = "in library" if complete else "partly imported" if owned else req.get("status", "")
            out.append(dict(item, saved=bool(fb.get("saved")), liked=bool(fb.get("liked")),
                            status=status, detail=req.get("detail", ""), albumId=owned[0]["album_id"] if complete else 0))
        return out

    def refresh(self):
        library = self.library()
        seeds = defaultdict(float)
        artists = {}
        for r in library:
            a = r.get("album_artist") or r["artist"]
            if not a or trackmatch.fold(a) in ("various artists", "unknown artist"):
                continue
            k = trackmatch.fold(a)
            artists[k] = a
            seeds[k] += float(r.get("rating") or 0) * 5 + bool(r.get("favorite")) * 8 + math.log1p(r.get("play_count") or 0)
            if (r.get("last_played") or 0) > time.time() - 30 * 86400:
                seeds[k] += 2
        library_artists = set(artists)
        feedback_boost = max(seeds.values(), default=0) + 30
        for item in self.state["items"]:
            if self.state["feedback"].get(item["key"], {}).get("liked"):
                k = trackmatch.fold(item["artist"])
                artists[k] = item["artist"]
                seeds[k] += feedback_boost
        if not seeds:
            raise ValueError("Add music to your library to seed discovery.")
        candidate_artists = {}
        errors = 0
        for seed in sorted(seeds, key=seeds.get, reverse=True)[:4]:
            artist = artists[seed]
            candidate_artists.setdefault(artist, {"seeds": set(), "known": seed in library_artists, "chosen": seed not in library_artists, "score": 1})
            candidate_artists[artist]["seeds"].add(artist)
            try:
                data = self.cached("similar:" + seed, lambda: self.fm("artist.getSimilar", {"artist": artist, "limit": 6}), 7 * 86400)
                for related in rows((data.get("similarartists") or {}).get("artist")):
                    name = related.get("name", "")
                    if not name:
                        continue
                    c = candidate_artists.setdefault(name, {"seeds": set(), "known": trackmatch.fold(name) in library_artists, "score": 0})
                    c["seeds"].add(artist)
                    c["score"] += float(related.get("match") or .1)
            except (lastfm.LastfmError, OSError, ValueError):
                errors += 1
        found = {}
        for artist, evidence in sorted(candidate_artists.items(), key=lambda p: -p[1]["score"])[:12]:
            url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(
                {"term": artist, "entity": "album", "media": "music", "limit": 40, "country": "US"})
            try:
                data = self.cached("albums:" + trackmatch.fold(artist), lambda: self.fetch(url))
            except (OSError, ValueError):
                errors += 1
                continue
            albums = [r for r in data.get("results", []) if trackmatch.fold(r.get("artistName", "")) == trackmatch.fold(artist)]
            # Include recent releases and a few catalog results, with no popularity claim.
            albums = sorted(albums, key=lambda r: r.get("releaseDate", ""), reverse=True)[:3] + albums[:4]
            count = 0
            for r in albums:
                name = r.get("collectionName", "")
                key = hashlib.sha256(identity(artist, name).encode()).hexdigest()[:24]
                if key in found or not r.get("collectionId") or not name:
                    continue
                item = {"key": key, "artist": artist, "album": name, "catalogId": r["collectionId"],
                        "year": r.get("releaseDate", "")[:4], "date": r.get("releaseDate", ""),
                        "art": r.get("artworkUrl100", "") if https_url(r.get("artworkUrl100", ""), ("mzstatic.com",)) else "", "url": r.get("collectionViewUrl", ""),
                        "kind": "EP" if re.search(r"\bEP$", name, re.I) else "Single" if r.get("trackCount") == 1 or re.search(r"\bSingle$", name, re.I) else "Album",
                        "known": evidence["known"], "reason": ("More from an artist you liked in Discover" if evidence.get("chosen") else "More from an artist you listen to" if evidence["known"] else
                            "Similar to " + ", ".join(sorted(evidence["seeds"]))), "tracks": [],
                        "score": evidence["score"] + len(evidence["seeds"])}
                if self.owned(item, library) or self.state["feedback"].get(key, {}).get("dismissed"):
                    continue
                found[key] = item
                count += 1
                if count >= 3:
                    break
        if not found:
            raise ValueError("No new matches. Check your connection and Last.fm settings, then refresh.")
        old = {r["key"]: r for r in self.state["items"]}
        for k, r in found.items():
            if k in old and old[k].get("catalogId") == r["catalogId"]:
                r["tracks"] = old[k].get("tracks", [])
                r["resolved"] = old[k].get("resolved", False)
        for k, r in old.items():
            if k not in found and (k in self.state["requests"] or self.state["feedback"].get(k, {}).get("saved")):
                found[k] = r
        self.state["items"] = sorted(found.values(), key=lambda r: -r["score"])
        self.state["refreshed"] = time.time()
        self.save()
        if errors and not lastfm.has_keys(lastfm.load()):
            return "Connect Last.fm in Player settings for similar artists. Showing familiar artists for now."
        return "Some sources unavailable; showing available results." if errors else ""

    def item(self, key):
        return next(r for r in self.state["items"] if r["key"] == key)

    def resolve(self, key):
        item = self.item(key)
        url = "https://itunes.apple.com/lookup?" + urllib.parse.urlencode(
            {"id": item["catalogId"], "entity": "song", "limit": 200, "country": "US"})
        data = self.cached("tracks:" + str(item["catalogId"]), lambda: self.fetch(url), 3600)
        albums = [r for r in data.get("results", []) if r.get("wrapperType") == "collection"]
        if len(albums) != 1 or identity(albums[0].get("artistName", ""), albums[0].get("collectionName", "")) != identity(item["artist"], item["album"]):
            raise ValueError("Preview catalog identity could not be verified.")
        item["tracks"] = [{"title": r["trackName"], "artist": r.get("artistName", item["artist"]),
                           "disc": r.get("discNumber", 1), "track": r.get("trackNumber", 0),
                           "duration": float(r.get("trackTimeMillis") or 0) / 1000,
                           "preview": r.get("previewUrl", "") if preview_url(r.get("previewUrl", "")) else "",
                           "url": r.get("trackViewUrl", "")}
                          for r in data.get("results", []) if r.get("kind") == "song" and r.get("collectionId") == item["catalogId"]]
        item["tracks"].sort(key=lambda t: (t["disc"], t["track"]))
        item["resolved"] = bool(item["tracks"]) and len(item["tracks"]) == albums[0].get("trackCount")
        self.save()
        return item
