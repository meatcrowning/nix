#!/usr/bin/env python3
"""tagtool — arbitrary tag and cover-art edits over the music library.

The half the curation pipeline deliberately does not cover. `curate/` decides
what a cluster of files SHOULD be called and converges it; this one does what
he asks for in a sentence: *"remove all the disc numbers from this album"*,
*"replace this album's cover with the one Last.fm has"*, *"set the genre on
these to ambient"*. Any key, any format, one selection at a time.

    tagtool.py show   --album "Geogaddi"
    tagtool.py set    --album "Geogaddi" genre=IDM date=2002 --apply
    tagtool.py remove --album "Geogaddi" disc disctotal --apply
    tagtool.py art    --album "Geogaddi" --source lastfm --apply
    tagtool.py art    --album "Geogaddi" --file ~/cover.png --apply
    tagtool.py undo   <token> --apply

    echo '{"op":"remove","album":"Geogaddi","keys":["disc"],"apply":true}' \
        | tagtool.py --json

Run with the player's wrapped python (it has mutagen):
  PY=$(grep -oE '/nix/store/[^" ]+-env/bin/python3[0-9.]*' "$(command -v player)" | head -1)

Five rules, each of which is a way this could destroy something:

1. **Dry run is the default.** Nothing writes without `--apply` / `"apply":
   true`. The dry run prints the exact per-file, per-key change list that the
   apply will make — it is the same code path, stopped one step early.
2. **Every write goes through `atomicsave.atomic_save`** — copy beside the
   original, mutate the copy, `os.replace()`. This library is exFAT with no
   snapshots (`no-btrfs-snapshots`); an interrupted in-place rewrite is a lost
   file. Never add a bare `mutagen.save()` here.
3. **The rating, the favourite and the play count are not tags this tool may
   touch.** They are the only metadata in the library that exists nowhere
   else — FMPS_Rating and friends are written by the player and merged between
   the two machines by dbsync. RESERVED refuses them by name, in `set` and in
   `remove`, including via a wildcard remove.
4. **Every apply writes an undo manifest** (`~/.cache/player-tagtool/`), old
   values and old cover bytes included, and `undo <token>` puts them back. A
   tool that edits 19,000 files' worth of library on one sentence needs a way
   back that does not depend on anyone having thought to make a backup.
5. **The library database is updated in place**, the same fields the player's
   own scan would have found, so the change shows without a rescan. The DB is
   a cache of the tags; the tags are the truth.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent                      # apps/player
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))

import mutagen                                          # noqa: E402
from mutagen.flac import FLAC, Picture                  # noqa: E402
from mutagen.id3 import ID3, APIC                       # noqa: E402
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm      # noqa: E402

import atomicsave                                       # noqa: E402

#: The three paths a harness has to be able to move, so a test never runs
#: against his library, his database or his undo manifests.
ROOT = Path(os.environ.get("AUD_ROOT") or "/run/media/lam/SSD/aud")
DB_PATH = Path(os.environ.get("PLAYER_DB")
               or Path.home() / ".local/share/player/library.db")
STATE = Path(os.environ.get("TAGTOOL_STATE")
             or Path.home() / ".cache" / "player-tagtool")
UA = "lam-tagtool/1.0 ( joelcvan@gmail.com )"

AUDIO_EXTS = {".flac", ".mp3", ".m4a", ".dsf", ".ogg", ".opus", ".wv",
              ".ape", ".aiff", ".aif", ".wav", ".mpc", ".tta", ".dff", ".mp4"}
COVER_NAMES = re.compile(r"^(cover|folder|front|albumart.*)\.(jpe?g|png|webp|gif|bmp)$", re.I)

#: Rule 3. Anything that folds to one of these is refused, whichever spelling
#: or container it arrives in — these carry the only library metadata that has
#: no second copy anywhere.
RESERVED = {"fmps_rating", "fmpsrating", "rating", "favorite", "favourite",
            "fmps_playcount", "playcount", "play_count", "fmps_rating_amarok_score"}


def fold(s):
    """Match the way a person names a record: case, accents and punctuation
    are noise. (trackmatch.fold's rule, kept local so this file imports only
    mutagen and atomicsave.)"""
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


# ---------------------------------------------------------------------------
# the key map: one friendly name, three container spellings
# ---------------------------------------------------------------------------
#: (id3 frame, mp4 atom, vorbis/APE key). A key that is NOT in here still
#: works — that is the whole point of "arbitrary" — it just lands in the
#: container's own extension slot: TXXX:<KEY>, ----:com.apple.iTunes:<KEY>,
#: or the Vorbis comment of that name. The map exists so that the six or
#: seven keys a person actually says out loud reach the frame the player and
#: every other tagger already read.
KEYMAP = {
    "title":          ("TIT2", "\xa9nam", "TITLE"),
    "artist":         ("TPE1", "\xa9ART", "ARTIST"),
    "album":          ("TALB", "\xa9alb", "ALBUM"),
    "album_artist":   ("TPE2", "aART", "ALBUMARTIST"),
    "track":          ("TRCK", "trkn", "TRACKNUMBER"),
    "tracktotal":     ("TRCK", "trkn", "TRACKTOTAL"),
    "disc":           ("TPOS", "disk", "DISCNUMBER"),
    "disctotal":      ("TPOS", "disk", "DISCTOTAL"),
    "date":           ("TDRC", "\xa9day", "DATE"),
    "genre":          ("TCON", "\xa9gen", "GENRE"),
    "comment":        ("COMM", "\xa9cmt", "COMMENT"),
    "composer":       ("TCOM", "\xa9wrt", "COMPOSER"),
    "grouping":       ("TIT1", "\xa9grp", "GROUPING"),
    "bpm":            ("TBPM", "tmpo", "BPM"),
    "compilation":    ("TCMP", "cpil", "COMPILATION"),
    "lyrics":         ("USLT", "\xa9lyr", "LYRICS"),
    "isrc":           ("TSRC", None, "ISRC"),
    "label":          ("TPUB", None, "LABEL"),
    "catalognumber":  (None, None, "CATALOGNUMBER"),
    "originaldate":   ("TDOR", None, "ORIGINALDATE"),
    "encodedby":      ("TENC", "\xa9too", "ENCODEDBY"),
}
#: What he is likely to say for a key that already has a name above.
ALIASES = {"albumartist": "album_artist", "album artist": "album_artist",
           "band": "album_artist", "year": "date", "tracknumber": "track",
           "track_number": "track", "trackno": "track", "discnumber": "disc",
           "disk": "disc", "disknumber": "disc", "disc_number": "disc",
           "disk_number": "disc", "disknum": "disc", "discno": "disc",
           "totaldiscs": "disctotal", "disctotals": "disctotal",
           "totaltracks": "tracktotal", "comments": "comment",
           "genres": "genre", "publisher": "label", "org": "label"}
#: The DB columns a change can move, so the player shows it without a rescan.
DB_FIELD = {"title": "title", "artist": "artist", "album": "album",
            "album_artist": "album_artist", "track": "track", "disc": "disc",
            "date": "date", "genre": "genre"}


def canon_key(k):
    k = str(k or "").strip()
    low = k.lower().replace("-", "_")
    return ALIASES.get(low, low if low in KEYMAP else k)


def _pairnum(v):
    """The (n, total) MP4 atoms trkn/disk take, from '3', 3 or '3/12'."""
    s = str(v).strip()
    m = re.match(r"\s*(\d+)\s*(?:/\s*(\d+))?", s)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2) or 0)


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------

def read_tags(path):
    """{friendly key: string} for one file — every key the file carries, not
    just the mapped ones, so `show` can answer "what IS on this file"."""
    try:
        a = mutagen.File(path)
    except Exception as e:                                   # noqa: BLE001
        return {"_error": repr(e)}
    if a is None:
        return {"_error": "mutagen cannot open"}
    out = {}
    t = a.tags
    if t is None:
        return out
    #: `track` and `tracktotal` (and disc/disctotal) live in ONE frame; the
    #: reverse map has to name the primary of the pair, not whichever came
    #: last in KEYMAP — reading TRCK as `tracktotal` hides the track number.
    rev_id3, rev_mp4 = {}, {}
    for k, v in KEYMAP.items():
        if k.endswith("total"):
            continue
        if v[0]:
            rev_id3.setdefault(v[0], k)
        if v[1]:
            rev_mp4.setdefault(v[1], k)
    if isinstance(t, ID3):
        for frame in t.values():
            fid = frame.FrameID if hasattr(frame, "FrameID") else str(frame)[:4]
            if fid == "APIC":
                out["_art"] = "embedded"
                continue
            if fid == "TXXX":
                out[str(frame.desc)] = "; ".join(str(x) for x in frame.text)
                continue
            name = rev_id3.get(fid, fid)
            try:
                val = "; ".join(str(x) for x in frame.text)
            except AttributeError:
                val = str(frame)
            out[name] = val
        trck = out.get("track")
        if trck and "/" in trck:
            out["track"], out["tracktotal"] = trck.split("/", 1)
        tpos = out.get("disc")
        if tpos and "/" in tpos:
            out["disc"], out["disctotal"] = tpos.split("/", 1)
    elif isinstance(a, MP4):
        for k, v in a.items():
            if k == "covr":
                out["_art"] = "embedded"
                continue
            if k in ("trkn", "disk"):
                if v and v[0]:
                    n, tot = (list(v[0]) + [0, 0])[:2]
                    out["track" if k == "trkn" else "disc"] = str(n)
                    if tot:
                        out["tracktotal" if k == "trkn" else "disctotal"] = str(tot)
                continue
            name = rev_mp4.get(k)
            if name is None and k.startswith("----:"):
                name = k.split(":")[-1]
            elif name is None:
                name = k
            try:
                if v and isinstance(v[0], bytes):
                    val = bytes(v[0]).decode("utf-8", "replace")
                else:
                    val = "; ".join(str(x) for x in v)
            except Exception:                                # noqa: BLE001
                val = str(v)
            out[name] = val
    else:                                        # Vorbis comment / APEv2
        rev_vc = {}
        for k, v in KEYMAP.items():
            if v[2]:
                rev_vc.setdefault(v[2].lower(), k)
        for k in t.keys():
            lk = str(k).lower()
            if lk == "metadata_block_picture":
                out["_art"] = "embedded"
                continue
            try:
                vals = t[k]
                val = "; ".join(str(x) for x in vals) if isinstance(vals, list) else str(vals)
            except Exception:                                # noqa: BLE001
                continue
            out[rev_vc.get(lk, lk)] = val
        if isinstance(a, FLAC) and a.pictures:
            out["_art"] = "embedded"
    return out


# ---------------------------------------------------------------------------
# writing one key into one container
# ---------------------------------------------------------------------------

def _id3_set(audio, key, value):
    from mutagen import id3
    tags = audio.tags
    frame_id = KEYMAP.get(key, (None,))[0]
    if key in ("track", "tracktotal", "disc", "disctotal"):
        fid = "TRCK" if key.startswith("track") else "TPOS"
        cur = tags.get(fid)
        cur = str(cur.text[0]) if cur and cur.text else ""
        n, _, tot = cur.partition("/")
        if key in ("track", "disc"):
            n = str(value)
        else:
            tot = str(value)
        text = n + ("/" + tot if tot else "")
        tags.setall(fid, [getattr(id3, fid)(encoding=3, text=[text])])
        return
    if key == "comment":
        tags.delall("COMM")
        tags.add(id3.COMM(encoding=3, lang="eng", desc="", text=[str(value)]))
        return
    if key == "lyrics":
        tags.delall("USLT")
        tags.add(id3.USLT(encoding=3, lang="eng", desc="", text=str(value)))
        return
    if frame_id and hasattr(id3, frame_id):
        tags.setall(frame_id, [getattr(id3, frame_id)(encoding=3, text=[str(value)])])
        return
    #: An unmapped key is a user-defined text frame, which is what TXXX is for.
    tags.delall("TXXX:" + key)
    tags.add(id3.TXXX(encoding=3, desc=key, text=[str(value)]))


def _id3_del(audio, key):
    tags = audio.tags
    if key in ("track", "tracktotal", "disc", "disctotal"):
        fid = "TRCK" if key.startswith("track") else "TPOS"
        cur = tags.get(fid)
        cur = str(cur.text[0]) if cur and cur.text else ""
        n, _, tot = cur.partition("/")
        if key in ("track", "disc"):
            tags.delall(fid)                # dropping the number drops the pair
        elif tot:
            from mutagen import id3
            tags.setall(fid, [getattr(id3, fid)(encoding=3, text=[n])])
        return
    fid = KEYMAP.get(key, (None,))[0]
    if fid:
        tags.delall(fid)
    tags.delall("TXXX:" + key)


def _mp4_set(audio, key, value):
    atom = KEYMAP.get(key, (None, None))[1]
    if key in ("track", "tracktotal", "disc", "disctotal"):
        a = "trkn" if key.startswith("track") else "disk"
        cur = audio.get(a)
        n, tot = (list(cur[0]) + [0, 0])[:2] if cur and cur[0] else (0, 0)
        if key in ("track", "disc"):
            n = _pairnum(value)[0]
        else:
            tot = _pairnum(value)[0]
        audio[a] = [(int(n), int(tot))]
        return
    if key == "bpm":
        audio["tmpo"] = [int(_pairnum(value)[0])]
        return
    if key == "compilation":
        audio["cpil"] = bool(str(value).strip().lower() in ("1", "true", "yes"))
        return
    if atom:
        audio[atom] = [str(value)]
        return
    audio["----:com.apple.iTunes:" + key] = [
        MP4FreeForm(str(value).encode("utf-8"))]


def _mp4_del(audio, key):
    if key in ("track", "tracktotal", "disc", "disctotal"):
        a = "trkn" if key.startswith("track") else "disk"
        cur = audio.get(a)
        if not cur or not cur[0]:
            return
        n, tot = (list(cur[0]) + [0, 0])[:2]
        if key in ("track", "disc"):
            audio.pop(a, None)
        else:
            audio[a] = [(int(n), 0)]
        return
    atom = KEYMAP.get(key, (None, None))[1]
    for k in [atom, "----:com.apple.iTunes:" + key, key]:
        if k:
            audio.pop(k, None)


def _vorbis_keys(tags, key):
    """Every spelling of `key` the file actually holds (Vorbis comments are
    case-insensitive by spec but stored as written)."""
    want = {key.lower(), (KEYMAP.get(key, (None, None, None))[2] or key).lower()}
    if key == "album_artist":
        want |= {"albumartist", "album artist", "album_artist"}
    return [k for k in list(tags.keys()) if str(k).lower() in want]


def _vorbis_set(audio, key, value):
    tags = audio.tags
    name = KEYMAP.get(key, (None, None, None))[2] or key.upper()
    for k in _vorbis_keys(tags, key):
        try:
            del tags[k]
        except (KeyError, TypeError):
            pass
    tags[name] = [str(value)]


def _vorbis_del(audio, key):
    tags = audio.tags
    for k in _vorbis_keys(tags, key):
        try:
            del tags[k]
        except (KeyError, TypeError):
            pass


def apply_change(audio, key, value):
    """Set (value not None) or delete (None) one key on an open mutagen
    object. Dispatches on the CONTAINER, never on the file extension."""
    if audio.tags is None:
        try:
            audio.add_tags()
        except Exception:                                    # noqa: BLE001
            pass
    setter, deleter = _vorbis_set, _vorbis_del
    if isinstance(audio.tags, ID3):
        setter, deleter = _id3_set, _id3_del
    elif isinstance(audio, MP4):
        setter, deleter = _mp4_set, _mp4_del
    if value is None:
        deleter(audio, key)
    else:
        setter(audio, key, value)


# ---------------------------------------------------------------------------
# cover art
# ---------------------------------------------------------------------------

def _dims(data):
    """(w, h) from the JPEG/PNG/WebP header itself — the number that says
    whether a cover is a 1200px front or a 300px thumbnail, without pulling
    Pillow in for it."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return (int.from_bytes(data[16:20], "big"),
                    int.from_bytes(data[20:24], "big"))
        if data[:2] == b"\xff\xd8":
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                m, ln = data[i + 1], int.from_bytes(data[i + 2:i + 4], "big")
                if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
                    return (int.from_bytes(data[i + 7:i + 9], "big"),
                            int.from_bytes(data[i + 5:i + 7], "big"))
                i += 2 + ln
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and data[12:16] == b"VP8 ":
            return (int.from_bytes(data[26:28], "little") & 0x3FFF,
                    int.from_bytes(data[28:30], "little") & 0x3FFF)
    except Exception:                                        # noqa: BLE001
        pass
    return None, None


def _mime_of(data):
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def read_art(path):
    """(bytes, mime) of the file's embedded front cover, or (None, None)."""
    try:
        a = mutagen.File(path)
    except Exception:                                        # noqa: BLE001
        return None, None
    if a is None or a.tags is None:
        return None, None
    if isinstance(a.tags, ID3):
        pics = a.tags.getall("APIC")
        if pics:
            return bytes(pics[0].data), pics[0].mime
    elif isinstance(a, MP4):
        covr = a.get("covr")
        if covr:
            return bytes(covr[0]), _mime_of(bytes(covr[0]))
    elif isinstance(a, FLAC) and a.pictures:
        return bytes(a.pictures[0].data), a.pictures[0].mime
    else:
        try:
            b64 = a.tags.get("metadata_block_picture")
        except Exception:                                    # noqa: BLE001
            b64 = None
        if b64:
            try:
                pic = Picture(base64.b64decode(b64[0]))
                return bytes(pic.data), pic.mime
            except Exception:                                # noqa: BLE001
                pass
    return None, None


def embed_art(audio, data, mime):
    """Replace the front cover on an open mutagen object. Returns False for a
    container that cannot carry one (WAV, some APE) — reported, not raised."""
    if audio.tags is None:
        try:
            audio.add_tags()
        except Exception:                                    # noqa: BLE001
            return False
    if isinstance(audio.tags, ID3):
        audio.tags.delall("APIC")
        if data:
            audio.tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover",
                                data=data))
        return True
    if isinstance(audio, MP4):
        if not data:
            audio.pop("covr", None)
            return True
        fmt = (MP4Cover.FORMAT_PNG if mime == "image/png"
               else MP4Cover.FORMAT_JPEG)
        audio["covr"] = [MP4Cover(data, imageformat=fmt)]
        return True
    if isinstance(audio, FLAC):
        audio.clear_pictures()
        if data:
            pic = Picture()
            pic.type, pic.mime, pic.data = 3, mime, data
            audio.add_picture(pic)
        return True
    try:                                        # Ogg Vorbis / Opus
        if not data:
            for k in ("metadata_block_picture", "coverart", "coverartmime"):
                try:
                    del audio.tags[k]
                except (KeyError, TypeError, ValueError):
                    pass
            return True
        pic = Picture()
        pic.type, pic.mime, pic.data = 3, mime, data
        audio.tags["metadata_block_picture"] = [
            base64.b64encode(pic.write()).decode("ascii")]
        return True
    except Exception:                                        # noqa: BLE001
        return False


def _http(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as f:
        return f.read()


def _json_get(url, timeout=30):
    try:
        return json.loads(_http(url, timeout))
    except Exception:                                        # noqa: BLE001
        return None


def art_from_lastfm(artist, album):
    """The cover Last.fm shows for the record — what he means by 'the one
    from lastfm'. Uses the player's own API key (pylib/lastfm)."""
    try:
        import lastfm
        data = lastfm.call("album.getInfo", {"artist": artist, "album": album})
    except Exception as e:                                   # noqa: BLE001
        return None, "last.fm: " + str(e)
    imgs = ((data or {}).get("album") or {}).get("image") or []
    url = ""
    for img in imgs:                       # last non-empty = largest (mega)
        if (img.get("#text") or "").strip():
            url = img["#text"].strip()
    if not url:
        return None, "last.fm has no cover for that album"
    try:
        return _http(url), None
    except Exception as e:                                   # noqa: BLE001
        return None, "last.fm image fetch failed: " + str(e)


def _mbid_of(paths):
    for p in paths[:8]:
        try:
            m = mutagen.File(p)
        except Exception:                                    # noqa: BLE001
            continue
        if m is None or m.tags is None:
            continue
        for k in ("TXXX:MusicBrainz Album Id", "musicbrainz_albumid",
                  "MUSICBRAINZ_ALBUMID",
                  "----:com.apple.iTunes:MusicBrainz Album Id"):
            try:
                v = m.tags.get(k)
            except Exception:                                # noqa: BLE001
                v = None
            if v:
                v = v[0] if isinstance(v, list) else v
                s = (bytes(v).decode("utf-8", "replace")
                     if isinstance(v, (bytes, bytearray)) else str(v)).strip()
                if len(s) == 36:
                    return s
    return None


def art_from_caa(artist, album, paths):
    """MusicBrainz Cover Art Archive, by the release id in the files' own tags
    (~94% of this library carries one) or by a release search."""
    mbid = _mbid_of(paths)
    if not mbid:
        q = urllib.parse.quote(f'release:"{album}" AND artist:"{artist}"')
        data = _json_get(f"https://musicbrainz.org/ws/2/release?query={q}&fmt=json&limit=5")
        for rel in ((data or {}).get("releases") or []):
            if fold(rel.get("title")) == fold(album):
                mbid = rel.get("id")
                break
    if not mbid:
        return None, "no MusicBrainz release matched"
    data = _json_get(f"https://coverartarchive.org/release/{mbid}")
    for img in ((data or {}).get("images") or []):
        if img.get("front") and img.get("image"):
            try:
                return _http(img["image"], timeout=60), None
            except Exception as e:                           # noqa: BLE001
                return None, "cover art archive fetch failed: " + str(e)
    return None, "cover art archive has no front image for that release"


def art_from_discogs(artist, album):
    """Where the netlabel half of this library actually has art."""
    q = urllib.parse.quote(f"{artist} {album}".strip())
    data = _json_get("https://api.discogs.com/database/search"
                     f"?q={q}&type=release&per_page=10")
    for rel in ((data or {}).get("results") or []):
        title = fold(rel.get("title", ""))
        if "-" in (rel.get("title") or ""):
            title = fold((rel.get("title") or "").split("-")[-1])
        if title != fold(album):
            continue
        url = rel.get("cover_image") or rel.get("thumb")
        if url and "spacer.gif" not in url:
            try:
                return _http(url, timeout=60), None
            except Exception:                                # noqa: BLE001
                continue
    return None, "discogs had no matching release with art"


def art_from_itunes(artist, album):
    """The cover the iTunes/Apple Music store serves for the record, fetched
    at the source's full resolution. Keyless iTunes Search API.

    The Cover Art Archive and Discogs both fail a class this library actually
    has a lot of: Japanese/small-label records whose romanised title differs
    from the English one MusicBrainz prefers. A file tagged album="Tasogare"
    is release "Twilight" on MusicBrainz (which has no CAA art for it at
    all), while iTunes holds the release under ITS romanised title and returns
    it as an `entity=album` hit. mzstatic art URLs are size-capped only by the
    thumb token in the path, so asking for a large token returns the source's
    own full size (the Mai Yamane 1980 cover is 1400px at 3000x3000).
    """
    q = urllib.parse.quote(f"{artist} {album}".strip())
    data = _json_get("https://itunes.apple.com/search"
                     f"?term={q}&entity=album&limit=10")
    falb, fart = fold(album), fold(artist)
    for res in ((data or {}).get("results") or []):
        if fold(res.get("collectionName") or "") != falb:
            continue  # the "Tasogare - Single" / other-artist hits fall here
        rart = fold(res.get("artistName") or "")
        if fart and not (fart in rart or rart in fart):
            continue
        art = res.get("artworkUrl100") or ""
        if not art:
            continue
        big = art.replace("100x100bb", "3000x3000bb")
        try:
            return _http(big, timeout=60), None
        except Exception:                                   # noqa: BLE001
            continue
    return None, "iTunes had no matching album with art"


def fetch_art(spec, artist, album, paths):
    """(bytes, mime, source, error). `source: auto` is the Cover Art Archive,
    then iTunes, then Discogs, then last.fm — best-quality-first (CAA fronts
    are 1200px, iTunes mzstatic serves the source's own full size, Discogs
    ~600, Last.fm's largest is 300px)."""
    src = (spec.get("source") or "").strip().lower()
    if spec.get("file"):
        p = Path(os.path.expanduser(str(spec["file"])))
        if not p.is_file():
            return None, None, "file", "no such image: " + str(p)
        data = p.read_bytes()
        return data, _mime_of(data), "file", None
    if spec.get("url"):
        try:
            data = _http(str(spec["url"]), timeout=60)
        except Exception as e:                               # noqa: BLE001
            return None, None, "url", "fetch failed: " + str(e)
        return data, _mime_of(data), "url", None
    #: `auto` is BIGGEST-first, not alphabetical: the Cover Art Archive serves
    #: 1200px fronts, iTunes mzstatic the source's own full size (usually
    #: >=1400px), Discogs ~600, and Last.fm's largest is a 300px thumbnail (13
    #: KB, measured). Ask for last.fm by name and you get last.fm's — that is
    #: what "the one from lastfm" means — but nothing picks it by default.
    order = {"lastfm": ["lastfm"], "caa": ["caa"], "musicbrainz": ["caa"],
             "itunes": ["itunes"], "discogs": ["discogs"]}.get(
                 src, ["caa", "itunes", "discogs", "lastfm"])
    errs = []
    for s in order:
        if s == "lastfm":
            data, err = art_from_lastfm(artist, album)
        elif s == "caa":
            data, err = art_from_caa(artist, album, paths)
        elif s == "itunes":
            data, err = art_from_itunes(artist, album)
        else:
            data, err = art_from_discogs(artist, album)
        if data and len(data) > 2000:
            return data, _mime_of(data), s, None
        errs.append(f"{s}: {err or 'nothing usable'}")
    return None, None, src or "auto", "; ".join(errs)


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------

def _db_rows():
    if not DB_PATH.exists():
        return []
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB_PATH, uri=True, timeout=10)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT path, title, artist, album, album_artist, disc, track "
            "FROM tracks").fetchall()
        con.close()
    except sqlite3.Error:
        return []
    return [dict(r) for r in rows]


def _walk_rows():
    out = []
    for dirpath, dirnames, files in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if not d.startswith("_")]
        for f in files:
            if Path(f).suffix.lower() not in AUDIO_EXTS:
                continue
            d = Path(dirpath)
            out.append({"path": os.path.join(dirpath, f),
                        "album": d.name, "album_artist": d.parent.name,
                        "artist": d.parent.name, "title": Path(f).stem})
    return out


def select(req):
    """The files one request acts on, and why. Album/artist match by fold, so
    'geogaddi' finds 'Geogaddi'; an exact fold match wins over a substring, so
    naming a record precisely never drags in everything containing its name."""
    paths = [os.path.expanduser(str(p)) for p in (req.get("paths") or [])]
    if paths:
        missing = [p for p in paths if not os.path.isfile(p)]
        return sorted(p for p in paths if os.path.isfile(p)), (
            "%d path(s) do not exist" % len(missing) if missing else None)
    if req.get("dir"):
        d = Path(os.path.expanduser(str(req["dir"])))
        if not d.is_dir():
            return [], "no such directory: " + str(d)
        return sorted(str(p) for p in d.rglob("*")
                      if p.suffix.lower() in AUDIO_EXTS), None
    rows = _db_rows() or _walk_rows()
    album, artist = req.get("album"), req.get("artist") or req.get("album_artist")
    query = req.get("query")
    if not (album or artist or query):
        return [], "say which tracks: album, artist, paths, dir or query"
    fa, fr, fq = fold(album), fold(artist), fold(query)

    def hit(r, exact):
        if album:
            got = fold(r.get("album"))
            if not (got == fa if exact else (fa in got and got)):
                return False
        if artist:
            got = fold(r.get("album_artist")) or fold(r.get("artist"))
            other = fold(r.get("artist"))
            if exact:
                if fr not in (got, other):
                    return False
            elif fr not in got and fr not in other:
                return False
        if query:
            blob = " ".join(fold(r.get(k)) for k in
                            ("title", "artist", "album", "album_artist"))
            if fq not in blob:
                return False
        return True

    for exact in (True, False):
        got = [r["path"] for r in rows if hit(r, exact)]
        if got:
            return sorted(p for p in got if os.path.isfile(p)), None
    return [], "nothing in the library matched"


# ---------------------------------------------------------------------------
# the undo manifest
# ---------------------------------------------------------------------------

def manifest_write(op, entries, art_blobs=None):
    STATE.mkdir(parents=True, exist_ok=True)
    token = time.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(2).hex()
    blobs = {}
    for h, data in (art_blobs or {}).items():
        p = STATE / ("art-%s.bin" % h)
        if not p.exists():
            p.write_bytes(data)
        blobs[h] = str(p)
    (STATE / (token + ".json")).write_text(json.dumps(
        {"token": token, "op": op, "when": time.time(),
         "entries": entries, "blobs": blobs}, ensure_ascii=False, indent=1))
    return token


def manifest_read(token):
    p = STATE / (str(token) + ".json")
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# the database, kept level with the tags
# ---------------------------------------------------------------------------

def db_update(path, fields, has_art=None):
    """Write the same values the player's own scan would have read, so the
    change shows without waiting for a rescan. Never touches rating,
    favourite or play count."""
    if not DB_PATH.exists():
        return
    sets, vals = [], []
    for k, v in (fields or {}).items():
        col = DB_FIELD.get(k)
        if not col:
            continue
        sets.append(col + "=?")
        if col in ("track", "disc"):
            try:
                v = int(re.match(r"\s*(\d+)", str(v)).group(1)) if v is not None else None
            except (AttributeError, ValueError):
                v = None
        vals.append(v)
    if "date" in (fields or {}):
        m = re.search(r"\d{4}", str(fields.get("date") or ""))
        sets.append("year=?")
        vals.append(int(m.group(0)) if m else None)
    if has_art is not None:
        sets.append("has_art=?")
        vals.append(1 if has_art else 0)
    try:
        st = os.stat(path)
        sets += ["size=?", "mtime=?"]
        vals += [st.st_size, st.st_mtime]
    except OSError:
        pass
    if not sets:
        return
    try:
        con = sqlite3.connect(DB_PATH, timeout=15)
        con.execute("UPDATE tracks SET %s WHERE path=?" % ", ".join(sets),
                    vals + [str(path)])
        con.commit()
        con.close()
    except sqlite3.Error:
        pass


# ---------------------------------------------------------------------------
# the operations
# ---------------------------------------------------------------------------

def op_show(req):
    paths, why = select(req)
    if not paths:
        return {"ok": False, "error": why or "nothing selected"}
    limit = int(req.get("limit") or 40)
    out = []
    for p in paths[:limit]:
        t = read_tags(p)
        out.append({"path": p, "tags": t})
    return {"ok": True, "op": "show", "tracks": len(paths),
            "shown": len(out), "files": out}


def _reserved(keys):
    return sorted({k for k in keys if fold(k).replace(" ", "_") in RESERVED
                   or k.lower() in RESERVED})


def op_set(req, remove=False):
    paths, why = select(req)
    if not paths:
        return {"ok": False, "error": why or "nothing selected"}
    if remove:
        wanted = {canon_key(k): None for k in (req.get("keys") or [])}
    else:
        wanted = {canon_key(k): v for k, v in (req.get("tags") or {}).items()}
    if not wanted:
        return {"ok": False, "error": "no keys given"}
    bad = _reserved(wanted)
    if bad:
        return {"ok": False, "error":
                "refusing %s — the rating, the favourite and the play count are "
                "the player's, and exist nowhere else. Change them in the app."
                % ", ".join(bad)}
    apply_ = bool(req.get("apply"))
    changes, errors, entries = [], [], []
    for p in paths:
        cur = read_tags(p)
        if "_error" in cur:
            errors.append({"path": p, "error": cur["_error"]})
            continue
        todo = {}
        for k, v in wanted.items():
            old = cur.get(k)
            new = None if v is None else str(v)
            if (old or None) == (new or None):
                continue                        # already right: not a write
            todo[k] = new
            changes.append({"path": p, "key": k, "from": old, "to": new})
        if not todo or not apply_:
            continue
        try:
            atomicsave.atomic_save(
                p, lambda a, td=todo: [apply_change(a, k, v) for k, v in td.items()])
        except Exception as e:                               # noqa: BLE001
            errors.append({"path": p, "error": repr(e)})
            continue
        entries.append({"path": p,
                        "old": {k: cur.get(k) for k in todo},
                        "new": todo})
        db_update(p, todo)
    res = {"ok": True, "op": "remove" if remove else "set",
           "applied": apply_, "tracks": len(paths),
           "files_changed": len({c["path"] for c in changes}),
           "changes": changes[:60],
           "changes_total": len(changes)}
    if len(changes) > 60:
        res["note"] = "showing the first 60 of %d changes" % len(changes)
    if not apply_:
        res["dry_run"] = "nothing was written — say apply to make these changes"
    elif entries:
        res["undo_token"] = manifest_write("set", entries)
    if errors:
        res["errors"] = errors[:20]
    return res


def op_art(req):
    paths, why = select(req)
    if not paths:
        return {"ok": False, "error": why or "nothing selected"}
    spec = req.get("art") or {}
    apply_ = bool(req.get("apply"))
    embed = spec.get("embed", True)
    folder = spec.get("folder", True)
    first = read_tags(paths[0])
    artist = (req.get("artist") or req.get("album_artist")
              or first.get("album_artist") or first.get("artist") or "")
    album = req.get("album") or first.get("album") or ""
    data, mime, source, err = fetch_art(spec, artist, album, paths)
    if not data:
        return {"ok": False, "error": err or "no cover found",
                "artist": artist, "album": album}
    digest = hashlib.sha256(data).hexdigest()[:16]
    dirs = sorted({str(Path(p).parent) for p in paths})
    w, h = _dims(data)
    plan = {"ok": True, "op": "art", "applied": apply_, "source": source,
            "artist": artist, "album": album,
            "image": {"bytes": len(data), "mime": mime, "sha256": digest,
                      "width": w, "height": h},
            "tracks": len(paths), "dirs": dirs}
    if not apply_:
        plan["dry_run"] = ("would %s%s%s — say apply to write it"
                           % ("embed into %d file(s)" % len(paths) if embed else "",
                              " and " if embed and folder else "",
                              "write cover.jpg into %d dir(s)" % len(dirs) if folder else ""))
        return plan
    entries, blobs, errors, wrote = [], {}, [], 0
    if embed:
        for p in paths:
            old, old_mime = read_art(p)
            ok = {"done": True}

            def mutate(a, d=data, m=mime, ok=ok):
                ok["done"] = embed_art(a, d, m)
            try:
                atomicsave.atomic_save(p, mutate)
            except Exception as e:                           # noqa: BLE001
                errors.append({"path": p, "error": repr(e)})
                continue
            if not ok["done"]:
                errors.append({"path": p, "error": "this container cannot carry a cover"})
                continue
            wrote += 1
            oh = None
            if old:
                oh = hashlib.sha256(old).hexdigest()[:16]
                blobs[oh] = old
            entries.append({"path": p, "art_old": oh, "art_mime": old_mime})
            db_update(p, {}, has_art=True)
    covers = []
    if folder:
        for d in dirs:
            dest = Path(d) / "cover.jpg"
            prev = dest.read_bytes() if dest.is_file() else None
            ph = None
            if prev:
                ph = hashlib.sha256(prev).hexdigest()[:16]
                blobs[ph] = prev
            try:
                tmp = dest.with_name(".player-tagtool-cover.tmp")
                tmp.write_bytes(data)
                os.replace(tmp, dest)
            except OSError as e:
                errors.append({"path": str(dest), "error": str(e)})
                continue
            covers.append(str(dest))
            entries.append({"path": str(dest), "cover_old": ph, "is_cover": True})
    plan.update({"files_embedded": wrote, "covers_written": covers})
    if entries:
        plan["undo_token"] = manifest_write("art", entries, blobs)
    if errors:
        plan["errors"] = errors[:20]
    return plan


def op_art_remove(req):
    paths, why = select(req)
    if not paths:
        return {"ok": False, "error": why or "nothing selected"}
    apply_ = bool(req.get("apply"))
    have = [p for p in paths if read_tags(p).get("_art")]
    if not apply_:
        return {"ok": True, "op": "art_remove", "applied": False,
                "tracks": len(paths), "with_art": len(have),
                "dry_run": "would strip the embedded cover from %d file(s)" % len(have)}
    entries, blobs, errors, done = [], {}, [], 0
    for p in have:
        old, old_mime = read_art(p)
        try:
            atomicsave.atomic_save(p, lambda a: embed_art(a, None, ""))
        except Exception as e:                               # noqa: BLE001
            errors.append({"path": p, "error": repr(e)})
            continue
        done += 1
        oh = None
        if old:
            oh = hashlib.sha256(old).hexdigest()[:16]
            blobs[oh] = old
        entries.append({"path": p, "art_old": oh, "art_mime": old_mime})
        db_update(p, {}, has_art=False)
    out = {"ok": True, "op": "art_remove", "applied": True,
           "files_changed": done, "tracks": len(paths)}
    if entries:
        out["undo_token"] = manifest_write("art", entries, blobs)
    if errors:
        out["errors"] = errors[:20]
    return out


def op_undo(req):
    man = manifest_read(req.get("token"))
    if not man:
        return {"ok": False, "error": "no such undo token",
                "available": sorted(p.stem for p in STATE.glob("*.json"))[-10:]}
    apply_ = bool(req.get("apply"))
    if not apply_:
        return {"ok": True, "op": "undo", "applied": False,
                "token": man["token"], "of": man["op"],
                "files": len(man["entries"]),
                "dry_run": "would put %d file(s) back" % len(man["entries"])}
    errors, done = [], 0
    for e in man["entries"]:
        p = e["path"]
        try:
            if e.get("is_cover"):
                h = e.get("cover_old")
                if h and h in man["blobs"]:
                    Path(p).write_bytes(Path(man["blobs"][h]).read_bytes())
                elif os.path.isfile(p):
                    os.unlink(p)
            elif "art_old" in e:
                h = e.get("art_old")
                data = (Path(man["blobs"][h]).read_bytes()
                        if h and h in man["blobs"] else None)
                atomicsave.atomic_save(
                    p, lambda a, d=data, m=e.get("art_mime") or "image/jpeg":
                    embed_art(a, d, m))
                db_update(p, {}, has_art=bool(data))
            else:
                old = e["old"]
                atomicsave.atomic_save(
                    p, lambda a, o=old: [apply_change(a, k, v) for k, v in o.items()])
                db_update(p, old)
            done += 1
        except Exception as ex:                              # noqa: BLE001
            errors.append({"path": p, "error": repr(ex)})
    out = {"ok": True, "op": "undo", "applied": True, "token": man["token"],
           "files_restored": done}
    if errors:
        out["errors"] = errors[:20]
    return out


def op_list_undo(_req):
    items = []
    for p in sorted(STATE.glob("*.json"), reverse=True)[:20]:
        try:
            m = json.loads(p.read_text())
        except ValueError:
            continue
        items.append({"token": m.get("token"), "op": m.get("op"),
                      "when": time.strftime("%Y-%m-%d %H:%M",
                                            time.localtime(m.get("when") or 0)),
                      "files": len(m.get("entries") or [])})
    return {"ok": True, "op": "list_undo", "undos": items}


OPS = {"show": op_show, "set": op_set,
       "remove": lambda r: op_set(r, remove=True),
       "art": op_art, "art_remove": op_art_remove,
       "undo": op_undo, "list_undo": op_list_undo}


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------

def run(req):
    op = str(req.get("op") or "show")
    fn = OPS.get(op)
    if not fn:
        return {"ok": False, "error": "unknown op %r; have: %s"
                % (op, ", ".join(sorted(OPS)))}
    try:
        return fn(req)
    except Exception as e:                                   # noqa: BLE001
        return {"ok": False, "error": repr(e)}


def main():
    if "--json" in sys.argv:
        try:
            req = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            print(json.dumps({"ok": False, "error": "bad request json"}))
            return 2
        out = run(req if isinstance(req, dict) else {})
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out.get("ok") else 1

    ap = argparse.ArgumentParser(description="arbitrary tag + cover-art edits")
    ap.add_argument("op", choices=sorted(OPS))
    ap.add_argument("rest", nargs="*", help="key=value (set), keys (remove), token (undo)")
    ap.add_argument("--album")
    ap.add_argument("--artist")
    ap.add_argument("--query")
    ap.add_argument("--dir")
    ap.add_argument("--path", action="append", default=[])
    ap.add_argument("--source", default="auto",
                    help="art: auto | lastfm | caa | itunes | discogs")
    ap.add_argument("--url", help="art: fetch the cover from this URL")
    ap.add_argument("--file", help="art: use this local image")
    ap.add_argument("--no-embed", action="store_true")
    ap.add_argument("--no-folder", action="store_true")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    req = {"op": a.op, "album": a.album, "artist": a.artist, "query": a.query,
           "dir": a.dir, "paths": a.path, "apply": a.apply, "limit": a.limit,
           "art": {"source": a.source, "url": a.url, "file": a.file,
                   "embed": not a.no_embed, "folder": not a.no_folder}}
    if a.op == "set":
        req["tags"] = dict(kv.split("=", 1) for kv in a.rest if "=" in kv)
    elif a.op == "remove":
        req["keys"] = a.rest
    elif a.op == "undo":
        req["token"] = a.rest[0] if a.rest else None
    out = run(req)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
