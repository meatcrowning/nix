"""Shared bits for the one-shot reorg of /run/media/lam/SSD/aud.

Tag reading mirrors the player's main.py read_tags exactly (same field
precedence, same fallbacks) so the plan sees what the player will see.
Run everything with the player's wrapped python (has mutagen):
  PY=$(grep -oE '/nix/store/[^" ]+-env/bin/python3[0-9.]*' "$(command -v player)" | head -1)
"""
import csv
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

import mutagen
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.mp4 import MP4

ROOT = Path("/run/media/lam/SSD/aud")
REORG = ROOT / "_reorg"
QUARANTINE_REL = "_quarantine"
INBOX_REL = "_inbox"
SKIP_DIRS = {"_reorg", "_quarantine", "_inbox"}

DB_PATH = Path.home() / ".local/share/player/library.db"
STATE_DIR = Path.home() / ".local/state/player"

AUDIO_EXTS = {".flac", ".mp3", ".m4a", ".dsf", ".ogg", ".opus", ".wv",
              ".ape", ".aiff", ".aif", ".wav", ".mpc", ".tta", ".dff"}
# .mp4 albums exist in the collection; the player ignores them (AUDIO_EXTS
# in main.py) but we still file them by tags rather than quarantining.
REORG_AUDIO_EXTS = AUDIO_EXTS | {".mp4"}
COVER_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
SIDECAR_EXTS = {".cue", ".log", ".accurip", ".nfo", ".txt", ".m3u", ".m3u8",
                ".pdf", ".lrc"}
JUNK_NAMES = {"thumbs.db", ".ds_store", "desktop.ini"}
JUNK_EXTS = {".asd", ".url", ".ini"}


# --- tag reading (port of main.py:read_tags, minus rating clamp we don't use)

def _first(v):
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
    if v is None:
        return None
    return str(v).strip() or None


def _year_of(s):
    if not s:
        return None
    m = re.search(r"\d{4}", str(s))
    return int(m.group(0)) if m else None


def _int_of(s):
    if s is None:
        return None
    m = re.match(r"\s*(\d+)", str(s))
    return int(m.group(1)) if m else None


def _vorbis_get(tags, *keys):
    lower = {}
    for k in tags.keys():
        lower.setdefault(str(k).lower(), k)
    for want in keys:
        real = lower.get(want.lower())
        if real is not None:
            return _first(tags[real])
    return None


def read_tags(path):
    """→ dict(title, artist, album, album_artist, track, disc, date, year,
    orig_year, genre, has_art, title_from_stem) or None if unreadable."""
    try:
        audio = mutagen.File(path)
    except Exception:
        return None
    if audio is None:
        return None
    t = {"title": None, "artist": None, "album": None, "album_artist": None,
         "track": None, "disc": None, "date": None, "year": None,
         "orig_year": None, "genre": None, "has_art": False,
         "title_from_stem": False}
    tags = audio.tags
    if tags is None:
        pass
    elif isinstance(tags, ID3):
        g = lambda k: _first(tags.get(k))  # noqa: E731
        gx = lambda d: _first(tags.get("TXXX:" + d))  # noqa: E731
        t["title"] = g("TIT2")
        t["artist"] = g("TPE1")
        t["album"] = g("TALB")
        t["album_artist"] = g("TPE2")
        t["track"] = _int_of(g("TRCK"))
        t["disc"] = _int_of(g("TPOS"))
        t["date"] = g("TDRC")
        t["orig_year"] = _year_of(g("TDOR") or gx("ORIGINALYEAR") or gx("originalyear"))
        t["genre"] = g("TCON")
        t["has_art"] = bool(tags.getall("APIC"))
    elif isinstance(audio, MP4):
        g = lambda k: _first(audio.get(k))  # noqa: E731

        def gff(name):
            v = audio.get("----:com.apple.iTunes:" + name)
            if not v:
                return None
            return bytes(v[0]).decode("utf-8", "replace").strip() or None
        t["title"] = g("\xa9nam")
        t["artist"] = g("\xa9ART")
        t["album"] = g("\xa9alb")
        t["album_artist"] = g("aART")
        trkn = audio.get("trkn")
        t["track"] = int(trkn[0][0]) if trkn and trkn[0] else None
        disk = audio.get("disk")
        t["disc"] = int(disk[0][0]) if disk and disk[0] else None
        t["date"] = g("\xa9day")
        t["orig_year"] = _year_of(gff("ORIGINALDATE") or gff("ORIGINALYEAR"))
        t["genre"] = g("\xa9gen")
        t["has_art"] = bool(audio.get("covr"))
    else:  # Vorbis / APEv2
        v = lambda *k: _vorbis_get(tags, *k)  # noqa: E731
        t["title"] = v("title")
        t["artist"] = v("artist")
        t["album"] = v("album")
        t["album_artist"] = v("albumartist", "album artist", "album_artist")
        t["track"] = _int_of(v("tracknumber", "track"))
        t["disc"] = _int_of(v("discnumber", "disc"))
        t["date"] = v("date", "year")
        t["orig_year"] = _year_of(v("originaldate", "originalyear", "original date"))
        t["genre"] = v("genre")
        if isinstance(audio, FLAC):
            t["has_art"] = bool(audio.pictures)
        else:
            t["has_art"] = bool(v("metadata_block_picture"))
    t["year"] = _year_of(t["date"])
    t["date"] = _first(t["date"])
    if not t["title"]:
        t["title"] = Path(path).stem
        t["title_from_stem"] = True
    return t


# --- classification -------------------------------------------------------

def classify(name):
    low = name.lower()
    ext = os.path.splitext(low)[1]
    if low in JUNK_NAMES or ext in JUNK_EXTS:
        return "junk"
    if ext in REORG_AUDIO_EXTS:
        return "audio"
    if ext == ".lrc":
        return "lrc"
    if ext in COVER_EXTS:
        return "cover"
    if ext in SIDECAR_EXTS:
        return ext.lstrip(".")
    return "other"


def walk_root():
    """Yield (abspath, relpath) of every file under ROOT, skipping our own
    working dirs. Deterministic order."""
    for dirpath, dirnames, filenames in os.walk(ROOT):
        if Path(dirpath) == ROOT:
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        dirnames.sort()
        for name in sorted(filenames):
            p = os.path.join(dirpath, name)
            yield p, os.path.relpath(p, ROOT)


# --- path building ---------------------------------------------------------

def san(s, empty="Unknown"):
    """Sanitize one path component: NFC, no separators, no exFAT-reserved
    characters (the SSD is exFAT: : * ? " < > | are invalid), no trailing
    dots or spaces, ≤240 UTF-8 bytes, never empty. CJK passes through."""
    s = unicodedata.normalize("NFC", str(s or ""))
    s = re.sub(r'[/\\\x00-\x1f:*?"<>|]', "-", s)
    s = re.sub(r"\s+", " ", s).strip()
    while len(s.encode("utf-8")) > 240:
        s = s[:-1]
    s = s.rstrip(". ")
    if s in ("", ".", ".."):
        return empty
    return s


# --- small io helpers ------------------------------------------------------

def write_csv(path, header, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(header)
        w.writerows(rows)


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        header = next(r)
        return header, [row for row in r if row and any(c.strip() for c in row)]


def load_jsonl(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def die(msg):
    print("FATAL: " + msg, file=sys.stderr)
    sys.exit(1)
