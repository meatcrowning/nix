"""Lyrics resolution shared by the player app and tools/lyrics-sync.py.

Deliberately Qt-free and side-effect-free at import: main.py imports it for the
LyricsProvider worker, and the batch tool imports it without dragging PySide6
into a headless run.

Two jobs live here:

  * read/write TIMESTAMPED lyrics in the files' own tags. The de-facto standard
    for embedded synced lyrics is LRC text ("[mm:ss.xx] line") in the ordinary
    lyrics frame — USLT (ID3), LYRICS (Vorbis), ©lyr (MP4) — not ID3's SYLT,
    which almost nothing reads. That is what this library's other tools
    (fooyin/Strawberry) would see too, so that is what we write.

  * look them up on LRCLIB. The matching here is deliberately STRICT. This is
    a write-to-file path: a fuzzy "closest result" that happens to be a
    different song would permanently put the wrong words in the user's tags.
    Every non-exact candidate must clear title AND artist AND duration checks
    before it is accepted (see _acceptable).

LRCLIB's `instrumental` flag is treated as a real, PERMANENT answer rather than
a miss: a large part of this library is vaporwave/electronic where "this track
has no words" is the correct result, and re-asking the network for it every
week is pure waste.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pylib"))
from trackmatch import (  # noqa: E402
    artist_variants,
    title_variants,
    fold as _fold,
    title_matches as _title_matches,
    artist_matches as _artist_matches,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atomicsave  # noqa: E402  (sibling module; also used by main.py)

import mutagen  # noqa: E402
from mutagen.flac import FLAC
from mutagen.id3 import ID3, USLT
from mutagen.mp4 import MP4

# A timestamp anywhere in the text is what makes lyrics "synced".
LRC_LINE = re.compile(r"\[(\d+):(\d{1,2}(?:[.:]\d{1,3})?)\]")

# Some taggers stuff whole scraped lyrics-site WEBPAGES (menus, ads, inline JS)
# into the lyrics tag. Real lyrics are a few KB at most.
MAX_LYRICS = 6000

USER_AGENT = "player/1.0 (https://github.com/meatcrowning; personal desktop player)"
LRCLIB = "https://lrclib.net/api/"


def is_synced(text):
    return bool(text and LRC_LINE.search(text))


def parse_lrc(text):
    """LRC → sorted [{t, line}]; a line may carry several timestamps."""
    out = []
    for raw in (text or "").splitlines():
        stamps = LRC_LINE.findall(raw)
        if not stamps:
            continue
        line = LRC_LINE.sub("", raw).strip()
        for mins, secs in stamps:
            out.append({"t": int(mins) * 60 + float(secs.replace(":", ".")),
                        "line": line})
    out.sort(key=lambda e: e["t"])
    return out


# ---------------------------------------------------------------------------
# Embedded lyrics: read + write
# ---------------------------------------------------------------------------

def _vorbis_key(tags, *names):
    lower = {str(k).lower(): k for k in tags.keys()}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def read_embedded(path):
    """(text, synced?) from the file's own tags, or (None, False)."""
    try:
        audio = mutagen.File(path)
    except Exception:
        return None, False
    if audio is None:
        return None, False
    text = None
    tags = audio.tags
    try:
        if isinstance(tags, ID3):
            uslt = tags.getall("USLT")
            if uslt:
                # Prefer a timestamped frame if several are present.
                text = next((str(f.text) for f in uslt if is_synced(str(f.text))),
                            str(uslt[0].text))
        elif isinstance(audio, MP4):
            v = audio.get("\xa9lyr")
            if v:
                text = str(v[0])
        elif tags is not None:
            k = _vorbis_key(tags, "lyrics", "syncedlyrics", "unsyncedlyrics",
                            "unsynced lyrics")
            if k is not None:
                v = tags[k]
                text = str(v[0] if isinstance(v, (list, tuple)) and v else v)
    except Exception:
        return None, False
    if not text or not text.strip():
        return None, False
    if len(text) > MAX_LYRICS:
        return None, False
    return text, is_synced(text)


def write_embedded(path, text):
    """Write `text` into the file's lyrics frame. Raises on failure.

    Only the lyrics frame is touched — nothing else in the file's tags is read,
    rewritten or reordered. The write itself is ATOMIC (copy → mutate → fsync →
    os.replace, see atomicsave.py): a synced LRC is several KB and routinely
    outgrows an MP3's tag padding, which makes an in-place save a rewrite of
    the audio data with no way back if it is interrupted.
    """
    if not text or not text.strip():
        raise ValueError("refusing to write empty lyrics")
    atomicsave.atomic_save(path, lambda audio: _apply_lyrics(audio, text))


def _apply_lyrics(audio, text):
    """The tag mutation only — handed a mutagen object for a temp copy by
    atomic_save, which owns opening it and calling save()."""
    tags = audio.tags
    if isinstance(audio, MP4):
        audio["\xa9lyr"] = [text]
    elif isinstance(tags, ID3) or (tags is None and hasattr(audio, "add_tags")
                                   and not isinstance(audio, FLAC)):
        if tags is None:
            audio.add_tags()
            tags = audio.tags
        # One unnamed English USLT frame, replacing any existing ones: two
        # frames with the same (lang, desc) is malformed, and leaving a stale
        # plain-text frame behind means some players show the old words.
        tags.delall("USLT")
        tags.add(USLT(encoding=3, lang="eng", desc="", text=text))
    else:  # Vorbis comments (flac/ogg/opus), APEv2 (wv/ape/mpc)
        if tags is None:
            audio.add_tags()
        for k in ("lyrics", "LYRICS", "unsyncedlyrics", "UNSYNCEDLYRICS",
                  "Lyrics", "UnsyncedLyrics", "syncedlyrics", "SYNCEDLYRICS"):
            audio.pop(k, None)
        audio["LYRICS"] = [text]


# ---------------------------------------------------------------------------
# Query normalisation lives in pylib/trackmatch.py (imported at the top of this
# file under its historical private names) so that tools which must not pull in
# mutagen can share exactly this logic rather than keep a copy that drifts.
# ---------------------------------------------------------------------------
# LRCLIB
# ---------------------------------------------------------------------------

class LookupError_(Exception):
    """Network/HTTP trouble, as opposed to an honest 'not found'."""


class Lrclib:
    """LRCLIB client with strict acceptance and polite pacing.

    Returns a dict: {"text": str|None, "synced": bool, "instrumental": bool,
                     "matched": "artist - title"|None}
    `text` None with instrumental False means "not found".
    """

    def __init__(self, min_interval=0.12, timeout=12, retries=2):
        self.min_interval = min_interval
        self.timeout = timeout
        self.retries = retries
        self._last = 0.0
        self.requests = 0

    def _get(self, url):
        gap = self.min_interval - (time.monotonic() - self._last)
        if gap > 0:
            time.sleep(gap)
        last_err = None
        for attempt in range(self.retries + 1):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    self.requests += 1
                    self._last = time.monotonic()
                    return json.loads(r.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                self._last = time.monotonic()
                if e.code == 404:
                    return None
                if e.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(1.5 * (attempt + 1))
                    last_err = e
                    continue
                raise LookupError_(f"HTTP {e.code}") from e
            except Exception as e:  # URLError, timeout, bad JSON
                self._last = time.monotonic()
                if attempt < self.retries:
                    time.sleep(1.0 * (attempt + 1))
                    last_err = e
                    continue
                raise LookupError_(str(e)) from e
        raise LookupError_(str(last_err))

    @staticmethod
    def _acceptable(rec, artist, title, duration):
        """Gate for /api/search hits, which are ranked guesses, not matches."""
        if not rec:
            return False
        if not _title_matches(title, rec.get("trackName") or ""):
            return False
        if not _artist_matches(artist, rec.get("artistName") or ""):
            return False
        if duration:
            rd = rec.get("duration") or 0
            if rd and abs(rd - duration) > 4:
                return False
        return True

    @staticmethod
    def _pack(rec):
        if rec.get("instrumental"):
            return {"text": None, "synced": False, "instrumental": True,
                    "matched": f"{rec.get('artistName')} - {rec.get('trackName')}"}
        synced, plain = rec.get("syncedLyrics"), rec.get("plainLyrics")
        if synced and synced.strip():
            return {"text": synced, "synced": True, "instrumental": False,
                    "matched": f"{rec.get('artistName')} - {rec.get('trackName')}"}
        if plain and plain.strip():
            return {"text": plain, "synced": False, "instrumental": False,
                    "matched": f"{rec.get('artistName')} - {rec.get('trackName')}"}
        return None

    NOT_FOUND = {"text": None, "synced": False, "instrumental": False, "matched": None}

    def lookup(self, artist, title, album=None, duration=None, want_synced=True):
        """Resolve one track. Raises LookupError_ if the network was the
        problem (so callers can retry later instead of caching a false 'none')."""
        if not artist or not title:
            return dict(self.NOT_FOUND)
        duration = int(duration or 0)
        best = None

        for a, t in self._pairs(artist, title):
            # 1. Exact endpoint: LRCLIB matched all four fields itself.
            q = {"artist_name": a, "track_name": t}
            if album:
                q["album_name"] = album
            if duration:
                q["duration"] = duration
            rec = self._get(LRCLIB + "get?" + urllib.parse.urlencode(q))
            got = self._pack(rec) if rec else None
            if got and (got["synced"] or got["instrumental"]):
                return got
            best = best or got

            # 2. Ranked search, strictly filtered.
            results = self._get(LRCLIB + "search?" + urllib.parse.urlencode(
                {"artist_name": a, "track_name": t})) or []
            cands = [r for r in results if self._acceptable(r, artist, title, duration)]
            # Prefer a synced hit, then an explicit instrumental.
            for pick in (lambda r: r.get("syncedLyrics"),
                         lambda r: r.get("instrumental"),
                         lambda r: r.get("plainLyrics")):
                for r in cands:
                    if not pick(r):
                        continue
                    got = self._pack(r)
                    if got and (got["synced"] or got["instrumental"]):
                        return got
                    best = best or got
                    break
            if best and not want_synced:
                return best
        return best or dict(self.NOT_FOUND)

    MAX_PAIRS = 4

    @classmethod
    def _pairs(cls, artist, title):
        """The (artist, title) ladder to try, most specific first and CAPPED.

        The full cross-product of variants is up to 15 pairs / 30 requests per
        track, which is indefensible across an 11k-track library. Ordering the
        undecorated forms first and stopping at MAX_PAIRS keeps the common case
        at one or two requests while still catching the decorated titles that
        cause most misses here."""
        arts, tits = artist_variants(artist), title_variants(title)
        seen, out = set(), []
        # Vary the title first: a stale decoration hurts far more than a
        # secondary artist does.
        for a in arts[:2]:
            for t in tits[:3]:
                if (a, t) not in seen:
                    seen.add((a, t))
                    out.append((a, t))
        return out[:cls.MAX_PAIRS]
