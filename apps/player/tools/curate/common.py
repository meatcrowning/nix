"""Shared bits for the library-curation pipeline (dedupe / consolidate /
missing-tracks inventory) over /run/media/lam/SSD/aud.

Reuses the reorg toolkit's tag reader (same field precedence the player
uses) rather than growing a second copy. Run with the player's wrapped
python (has mutagen):
  PY=$(grep -oE '/nix/store/[^" ]+-env/bin/python3[0-9.]*' "$(command -v player)" | head -1)
"""
import json
import os
import shutil
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

import importlib.util as _ilu


def _load(name, path):
    spec = _ilu.spec_from_file_location(name, path)
    mod = _ilu.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# named distinctly from this module (both are called common.py) so the two
# don't collide in sys.modules and reimport each other's half-built self.
reorg = _load("reorg_common",
              Path(__file__).resolve().parent.parent / "reorg" / "common.py")

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "pylib"))
import trackmatch  # noqa: E402

ROOT = reorg.ROOT
# Everything this pipeline removes from the library goes here, never deleted.
# Chosen name: a sibling of ~/Music that makes clear it holds material pulled
# OUT of the library, not a second library.
REMOVED = Path.home() / "Music-removed"
STATE = Path.home() / ".cache" / "library-curate"
STATE.mkdir(parents=True, exist_ok=True)
SCAN_JSON = STATE / "scan.json"
MB_CACHE = STATE / "mbcache"
AUDIT_LOG = REMOVED / "audit-report.md"

UA = "lam-library-curate/1.0 ( joelcvan@gmail.com )"

# Quality ranking used to decide which copy of a duplicate track survives:
# lossless codecs always beat lossy ones; within a tier, bitrate breaks ties.
LOSSLESS_EXTS = {".flac", ".wv", ".ape", ".tta", ".aiff", ".aif", ".wav",
                  ".dsf", ".dff"}
CODEC_TIER = {".dsf": 6, ".dff": 6, ".flac": 5, ".wv": 5, ".ape": 5,
              ".tta": 5, ".aiff": 5, ".aif": 5, ".wav": 5,
              ".m4a": 3, ".mp4": 3, ".opus": 3, ".mpc": 2, ".ogg": 2,
              ".mp3": 1}


def quality_of(path, bitrate, sample_rate, dur):
    ext = Path(path).suffix.lower()
    return (CODEC_TIER.get(ext, 0), int(bitrate or 0), int(sample_rate or 0), dur or 0)


def audio_info(path):
    """(bitrate_bps, sample_rate, duration_s) from mutagen's .info, or
    (None, None, None) if unreadable."""
    import mutagen
    try:
        a = mutagen.File(path)
    except Exception:
        return None, None, None
    if a is None or a.info is None:
        return None, None, None
    br = getattr(a.info, "bitrate", None)
    sr = getattr(a.info, "sample_rate", None)
    dur = getattr(a.info, "length", None)
    return br, sr, dur


# --- MusicBrainz, rate-limited + cached (mirrors audit-tags-vs-mb.py) -----

def mb_get(url_path, params=""):
    MB_CACHE.mkdir(parents=True, exist_ok=True)
    key = (url_path + "?" + params).replace("/", "_")
    cache_file = MB_CACHE / (key[:180] + ".json")
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text())
        except Exception:
            pass
    url = f"https://musicbrainz.org/ws/2/{url_path}?{params}&fmt=json"
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as f:
                body = f.read()
            data = json.loads(body)
            cache_file.write_text(json.dumps(data, ensure_ascii=False))
            time.sleep(1.05)  # MB asks for <=1 req/s
            return data
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                cache_file.write_text(json.dumps({"error": e.code}))
                return {"error": e.code}
            time.sleep(1.5 * (attempt + 1))
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return None


# --- move-with-audit --------------------------------------------------------

_audit_rows = []


def move_to_removed(path, category, reason):
    """MOVE (never delete) a library file out to ~/Music-removed/<category>/
    <relpath-under-aud>, preserving the relative path so it can be found
    again. Cross-filesystem (exFAT SSD -> home), so this is copy+unlink, not
    a rename."""
    path = str(path)
    rel = os.path.relpath(path, ROOT)
    dest = REMOVED / category / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest = dest.with_name(dest.stem + ".dup" + str(int(time.time())) + dest.suffix)
    shutil.move(path, dest)
    _audit_rows.append((category, rel, str(dest), reason))
    return dest


def flush_audit(heading):
    if not _audit_rows:
        return
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(f"\n## {heading} ({time.strftime('%Y-%m-%d %H:%M')})\n\n")
        f.write(f"{len(_audit_rows)} files moved.\n\n")
        f.write("| category | from (under aud/) | reason |\n|---|---|---|\n")
        for cat, rel, dest, reason in _audit_rows:
            f.write(f"| {cat} | {rel} | {reason} |\n")
    _audit_rows.clear()


def fold(s):
    return trackmatch.fold(s)


# --- generic cross-format tag write (album / album_artist / date only) ----
# Mirrors reorg/common.py read_tags' per-format field map, in reverse. Used
# via apps/player/atomicsave.py's atomic_save (copy -> mutate copy -> replace)
# -- NEVER a bare mutagen.save() on a library file.

def set_common_tags(audio, album=None, album_artist=None, date=None):
    from mutagen.id3 import ID3, TALB, TPE2, TDRC
    from mutagen.mp4 import MP4
    tags = audio.tags
    if tags is None:
        return
    if isinstance(tags, ID3):
        if album is not None:
            tags.setall("TALB", [TALB(encoding=3, text=[album])])
        if album_artist is not None:
            tags.setall("TPE2", [TPE2(encoding=3, text=[album_artist])])
        if date is not None:
            tags.setall("TDRC", [TDRC(encoding=3, text=[date])])
    elif isinstance(audio, MP4):
        if album is not None:
            audio["\xa9alb"] = [album]
        if album_artist is not None:
            audio["aART"] = [album_artist]
        if date is not None:
            audio["\xa9day"] = [date]
    else:  # Vorbis comment / APEv2 (FLAC, OGG, WV, APE, ...)
        if album is not None:
            tags["album"] = [album]
        if album_artist is not None:
            tags["albumartist"] = [album_artist]
        if date is not None:
            tags["date"] = [date]


def read_mbid(path):
    """The album's MusicBrainz release id, from the file's own tags (~94% of
    this library carries one, per audit-tags-vs-mb.py)."""
    try:
        import mutagen
        m = mutagen.File(path)
    except Exception:
        return None
    if m is None or m.tags is None:
        return None
    t = m.tags
    for k in ("TXXX:MusicBrainz Album Id", "musicbrainz_albumid",
              "----:com.apple.iTunes:MusicBrainz Album Id"):
        try:
            v = t.get(k)
        except Exception:
            v = None
        if v:
            v = v[0] if isinstance(v, list) else v
            s = bytes(v).decode("utf-8", "replace") if isinstance(v, bytes) else str(v)
            s = s.strip()
            if len(s) == 36:
                return s
    return None
