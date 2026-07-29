#!/usr/bin/env python3
"""player — standalone Qt/QML music player for the `top` desktop.

The fourth sibling of surfer/filer/viewer: a PySide6 + QML app themed by the
live wallpaper palette (parsed from the panel's Theme.qml and file-watched),
with its transport controls in the hyprvtb titlebar (play/pause/skip buttons +
the PLAYBAR scrub bar, same bridge viewer uses for video).

The library is the external SSD at /run/media/lam/SSD/aud (~11k mixed-format
files: FLAC/MP3/M4A/DSF, loose tracks and album folders in several layouts).
Organisation is tag-driven, never path-driven: a background mutagen scan mirrors
every file's tags into ~/.local/share/player/library.db (SQLite, WAL) and the
album grid / search / smart playlists are all DB queries — the SSD is never
touched just to browse. Ratings (FMPS_RATING 0..1), play counts
(FMPS_PLAYCOUNT) and favourites (FAVORITE=1) live IN the files' tags, like the
rest of this library's history (fooyin/Strawberry wrote the existing ones); the
DB is a queryable mirror, rebuilt from tags at any time. Tag writes go through
a journaling worker with a prefs kill-switch (tagWrites: off|log|on), and every
write to a library file — ratings here, lyrics in lyrics.py — is atomic (copy →
mutate → fsync → os.replace, see atomicsave.py), because an interrupted
in-place rewrite is the one way this app could damage the library and exFAT has
no snapshots to undo it.

Playback is libmpv (python-mpv): decodes everything including DSF/DSD (to PCM),
gapless-audio=weak joins compatible streams. The app owns the queue and mirrors
it into mpv's playlist so the next track is prefetched. MPRIS is exported so
the panel's MediaPanel widget controls this player like any other.

Lyrics: TIMESTAMPED embedded tags → sidecar .lrc → LRCLIB (lrclib.net), cached
in the DB (including negative results); synced [mm:ss.xx] lyrics scroll in the
UI. Plain unsynced lyrics never end the search — a synced version is a strict
upgrade — and anything fetched is written back into the file's own lyrics frame
so it outlives this DB. The matching rules live in lyrics.py, shared with
tools/lyrics-sync.py, which sweeps the whole library in one go.

ReplayGain: the scan mirrors each file's REPLAYGAIN_* / R128_* tags into the DB
and mpv applies the gain itself while decoding, so volume is levelled library
wide without touching the volume slider. Mode is off/track/album/auto (auto =
album gain inside an album, track gain for anything mixed); the ~4% of files
with no tags fall back to the library's own median gain.
"""
import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import sys
import threading
import time
import urllib.parse
from pathlib import Path

from PySide6.QtCore import (QObject, QProcess, Qt, QThread, QTimer, QUrl, Signal,
                            Slot, Property, QFileSystemWatcher)
from PySide6.QtCore import QAbstractListModel, QModelIndex
from PySide6.QtGui import QColor, QGuiApplication, QImage
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"

sys.path.insert(0, str(HERE.parent / "pylib"))
from vtbclient import VtbClient  # noqa: E402  (needs the path insert above)
from deskstyle import DeskStyle  # noqa: E402  (pylib; the desktop-wide font setting)

import atomicsave  # noqa: E402  (sibling module; also used by lyrics.py)
import lyrics as lyricslib  # noqa: E402  (sibling module; also used by tools/)
import trackmatch  # noqa: E402  (pylib; the one artist/title normaliser)
import mutagen  # noqa: E402
from mutagen.flac import FLAC, Picture  # noqa: E402
from mutagen.id3 import ID3, TXXX  # noqa: E402
from mutagen.mp4 import MP4, MP4FreeForm  # noqa: E402

# The library root. Overridable ONLY so the share can be tested against a
# second mount of itself without a second machine (docs/agents/air-library-share.md,
# A5.2) — air deliberately mounts the SMB share at this same absolute path, so
# that every tracks.path row from top's database is valid there verbatim.
LIBRARY_ROOT = Path(os.environ.get("PLAYER_LIBRARY_ROOT", "/run/media/lam/SSD/aud"))

AUDIO_EXTS = {".flac", ".mp3", ".m4a", ".dsf", ".ogg", ".opus", ".wv",
              ".ape", ".aiff", ".aif", ".wav", ".mpc", ".tta", ".dff"}

DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "player"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "player"
STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "player"
ART = CACHE / "art"
DB_PATH = DATA / "library.db"

# The panel's palette file, rewritten by wal-set.sh between the wal markers.
PANEL_THEME = Path.home() / ".config" / "quickshell" / "Theme.qml"
PALETTE_KEYS = ["bg", "bgAlt", "border", "accent", "dim", "text", "textDim",
                "highlight", "ok", "warn", "crit", "info"]
PALETTE_DEFAULTS = {
    "bg": "#000000", "bgAlt": "#120b08", "border": "#382216", "accent": "#cc4400",
    "dim": "#54382a", "text": "#cc4400", "textDim": "#8c5438", "highlight": "#21140d",
    "ok": "#e08e65", "warn": "#b86237", "crit": "#fa5c0c", "info": "#ad7457",
}


class Palette(QObject):
    """The live wallpaper palette, parsed from the panel's Theme.qml and kept in
    sync via a filesystem watch (mirrors viewer's Palette)."""

    changed = Signal()

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._path = str(path)
        self._colors = dict(PALETTE_DEFAULTS)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_change)
        self._watcher.directoryChanged.connect(self._on_change)
        d = os.path.dirname(self._path)
        if os.path.isdir(d):
            self._watcher.addPath(d)  # dir watch catches atomic replaces
        self._rewatch()
        self._load()

    def _rewatch(self):
        if os.path.exists(self._path) and self._path not in self._watcher.files():
            self._watcher.addPath(self._path)

    def _on_change(self, _):
        self._rewatch()
        self._load()

    def _load(self):
        try:
            txt = open(self._path, encoding="utf-8").read()
        except OSError:
            return
        colors = dict(self._colors)
        for m in re.finditer(r'property\s+color\s+(\w+)\s*:\s*"(#[0-9a-fA-F]{3,8})"', txt):
            name, val = m.group(1), m.group(2)
            if name in PALETTE_KEYS:
                colors[name] = val
        if colors != self._colors:
            self._colors = colors
            self.changed.emit()

    def _c(self, k):
        return QColor(self._colors.get(k, PALETTE_DEFAULTS[k]))

    @Property(QColor, notify=changed)
    def bg(self): return self._c("bg")
    @Property(QColor, notify=changed)
    def bgAlt(self): return self._c("bgAlt")
    @Property(QColor, notify=changed)
    def border(self): return self._c("border")
    @Property(QColor, notify=changed)
    def accent(self): return self._c("accent")
    @Property(QColor, notify=changed)
    def dim(self): return self._c("dim")
    @Property(QColor, notify=changed)
    def text(self): return self._c("text")
    @Property(QColor, notify=changed)
    def textDim(self): return self._c("textDim")
    @Property(QColor, notify=changed)
    def highlight(self): return self._c("highlight")
    @Property(QColor, notify=changed)
    def ok(self): return self._c("ok")
    @Property(QColor, notify=changed)
    def warn(self): return self._c("warn")
    @Property(QColor, notify=changed)
    def crit(self): return self._c("crit")
    @Property(QColor, notify=changed)
    def info(self): return self._c("info")


class Titlebar(QObject):
    """hyprvtb app-button bridge — transport controls (prev/play/next, shuffle,
    repeat, close) live in the compositor's inner titlebar column, and so does
    the seek bar (PLAYBAR/SEEK, exactly viewer's video scrubbing). The vtb
    callbacks fire on the client's I/O thread — the Signals hop them onto the
    GUI thread (queued)."""

    clicked = Signal(str)
    seek = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = VtbClient(on_click=self.clicked.emit,
                                 on_seek=self.seek.emit)

    @Slot("QVariantList")
    def setButtons(self, buttons):
        out = []
        for b in buttons:
            if isinstance(b, str):
                out.append("-")  # spacer
            else:
                out.append((str(b["id"]), str(b["label"]), int(b.get("state", 0)),
                            str(b.get("tip", "")), bool(b.get("drag", False)),
                            bool(b.get("bottom", False))))
        self._client.set_buttons(out)

    @Slot(str)
    def setFooter(self, text):
        self._client.set_footer(text)

    @Slot(bool)
    def setFooterBottom(self, on):
        self._client.set_footer_bottom(on)

    @Slot(bool, float)
    def setPlaybar(self, shown, pos):
        self._client.set_playbar(shown, pos)


class Prefs(QObject):
    """Small persisted preferences (view/sort mode, volume, tag-write mode, the
    saved queue) in $XDG_STATE_HOME/player/prefs.json — surfer's Prefs shape."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = STATE / "prefs.json"
        self._d = {}
        try:
            d = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                self._d = d
        except (OSError, ValueError, TypeError):
            pass

    def _write(self):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._d), encoding="utf-8")
        except OSError:
            pass

    @Slot(str, "QVariant", result="QVariant")
    def get(self, key, fallback=None):
        return self._d.get(key, fallback)

    @Slot(str, "QVariant")
    def set(self, key, value):
        self._d[key] = value
        self._write()


# ---------------------------------------------------------------------------
# Tag reading (scan side). One mapping table, three tag families.
# ---------------------------------------------------------------------------

def _first(v):
    """Mutagen values are usually lists; unwrap to a clean str (or None)."""
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
    if v is None:
        return None
    return str(v).strip() or None


def _year_of(s):
    """First 4-digit run in a date-ish string ('1999', '1971-05-12', …)."""
    if not s:
        return None
    m = re.search(r"\d{4}", str(s))
    return int(m.group(0)) if m else None


def _int_of(s):
    """Leading integer of '3', '03', '3/12' — track/disc numbers."""
    if s is None:
        return None
    m = re.match(r"\s*(\d+)", str(s))
    return int(m.group(1)) if m else None


def _float_of(s):
    try:
        return float(str(s).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _vorbis_get(tags, *keys):
    """Case-insensitive multi-key lookup for Vorbis/APE-style dict tags."""
    lower = {}
    for k in tags.keys():
        lower.setdefault(str(k).lower(), k)
    for want in keys:
        real = lower.get(want.lower())
        if real is not None:
            return _first(tags[real])
    return None


def _gain_db(s):
    """'-7.53 dB' / '-7.53' → -7.53. ReplayGain gains are always in dB."""
    if s is None:
        return None
    m = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(s))
    if not m:
        return None
    try:
        v = float(m.group(0).replace(",", "."))
    except ValueError:
        return None
    # Junk guard: real album/track gains live within roughly ±30 dB.
    return v if -60.0 <= v <= 60.0 else None


def _peak(s):
    """Sample peak, normally 0..~1.5 linear. Some taggers write it in dB."""
    v = _float_of(s)
    if v is None or v <= 0:
        return None
    return v if v <= 4.0 else None


def read_replaygain(audio):
    """ReplayGain from any of the three tag families → dict of 4 floats (or
    Nones). ~96% of this library is already tagged (fooyin/Strawberry and the
    original rips wrote them), which is why the player can normalise volume
    without analysing anything itself.

    Opus/Ogg carry R128_*_GAIN instead: a Q7.8 fixed-point integer referenced
    to -23 LUFS, where ReplayGain 2.0 is referenced to -18 LUFS — hence the
    +5 dB shift when converting."""
    out = {"rg_track_gain": None, "rg_track_peak": None,
           "rg_album_gain": None, "rg_album_peak": None}
    tags = audio.tags
    if tags is None:
        return out

    def take(kind, gain, peak, r128=None):
        if out["rg_%s_gain" % kind] is None:
            if gain is not None:
                out["rg_%s_gain" % kind] = _gain_db(gain)
            elif r128 is not None:
                q = _int_of(r128)
                if q is not None:
                    out["rg_%s_gain" % kind] = round(q / 256.0 + 5.0, 2)
        if out["rg_%s_peak" % kind] is None and peak is not None:
            out["rg_%s_peak" % kind] = _peak(peak)

    try:
        if isinstance(tags, ID3):
            gx = lambda d: _first(tags.get("TXXX:" + d))  # noqa: E731
            # TXXX descriptions are case-sensitive and taggers disagree.
            byname = {}
            for k in tags.keys():
                if str(k).upper().startswith("TXXX:"):
                    byname[str(k)[5:].lower()] = _first(tags.get(k))
            take("track", byname.get("replaygain_track_gain") or gx("REPLAYGAIN_TRACK_GAIN"),
                 byname.get("replaygain_track_peak"))
            take("album", byname.get("replaygain_album_gain") or gx("REPLAYGAIN_ALBUM_GAIN"),
                 byname.get("replaygain_album_peak"))
        elif isinstance(audio, MP4):
            # Freeform atom names are case-sensitive keys but taggers disagree
            # on both halves ("com.apple.iTunes" vs "com.apple.itunes"), so
            # match on the trailing name, folded.
            byname = {}
            for k in audio.keys():
                ks = str(k)
                if ks.startswith("----:"):
                    v = audio.get(k)
                    if v:
                        try:
                            byname[ks.rsplit(":", 1)[-1].lower()] = \
                                bytes(v[0]).decode("utf-8", "replace").strip() or None
                        except Exception:
                            pass
            gff = byname.get
            take("track", gff("replaygain_track_gain"), gff("replaygain_track_peak"))
            take("album", gff("replaygain_album_gain"), gff("replaygain_album_peak"))
        else:  # Vorbis comments / APEv2
            v = lambda *k: _vorbis_get(tags, *k)  # noqa: E731
            take("track", v("replaygain_track_gain"), v("replaygain_track_peak"),
                 v("r128_track_gain"))
            take("album", v("replaygain_album_gain"), v("replaygain_album_peak"),
                 v("r128_album_gain"))
    except Exception:
        pass
    return out


def read_tags(path):
    """Parse one file with mutagen → dict of the columns the DB stores, plus
    has_art (bool, embedded art present — recorded so the album-art pass can
    find a donor track without re-parsing everything). None on unreadable."""
    try:
        audio = mutagen.File(path)
    except Exception:
        return None
    if audio is None:
        return None

    info = getattr(audio, "info", None)
    t = {
        "duration": float(getattr(info, "length", 0.0) or 0.0),
        "samplerate": int(getattr(info, "sample_rate", 0) or 0),
        "bitdepth": int(getattr(info, "bits_per_sample", 0) or 0),
        "codec": type(audio).__name__,
        "title": None, "artist": None, "album": None, "album_artist": None,
        "track": None, "disc": None, "date": None, "year": None,
        "orig_year": None, "genre": None, "rating": None, "favorite": 0,
        "play_count": 0, "has_art": False,
        "rg_track_gain": None, "rg_track_peak": None,
        "rg_album_gain": None, "rg_album_peak": None,
    }
    tags = audio.tags

    if tags is None:
        pass
    elif isinstance(tags, ID3):  # mp3 / dsf / aiff / wav
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
        t["rating"] = _float_of(gx("FMPS_Rating") or gx("FMPS_RATING"))
        t["play_count"] = _int_of(gx("FMPS_Playcount") or gx("FMPS_PLAYCOUNT")) or 0
        t["favorite"] = 1 if (gx("FAVORITE") or "") in ("1", "true") else 0
        t["has_art"] = bool(tags.getall("APIC"))
    elif isinstance(audio, MP4):
        g = lambda k: _first(audio.get(k))  # noqa: E731

        def gff(name):
            v = audio.get("----:com.apple.iTunes:" + name)
            if not v:
                return None
            b = v[0]
            return bytes(b).decode("utf-8", "replace").strip() or None
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
        t["rating"] = _float_of(gff("FMPS_Rating"))
        t["play_count"] = _int_of(gff("FMPS_Playcount")) or 0
        t["favorite"] = 1 if gff("FAVORITE") == "1" else 0
        t["has_art"] = bool(audio.get("covr"))
    else:  # Vorbis comments (flac/ogg/opus) and APEv2 (wv/ape/mpc) both walk like dicts
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
        t["rating"] = _float_of(v("fmps_rating"))
        t["play_count"] = _int_of(v("fmps_playcount")) or 0
        t["favorite"] = 1 if (v("favorite") or "") in ("1", "true") else 0
        if isinstance(audio, FLAC):
            t["has_art"] = bool(audio.pictures)
        else:
            t["has_art"] = bool(v("metadata_block_picture"))

    t.update(read_replaygain(audio))
    t["year"] = _year_of(t["date"])
    t["date"] = _first(t["date"])
    if not t["title"]:
        t["title"] = Path(path).stem
    # Clamp junk ratings (some taggers write 0..5 or 0..100 into FMPS fields).
    if t["rating"] is not None and t["rating"] > 1.0:
        t["rating"] = min(1.0, t["rating"] / (5.0 if t["rating"] <= 5 else 100.0))
    return t


def embedded_art(path):
    """Embedded front-cover bytes of one file, or None. Only called for the one
    donor track per album (and lazily for loose tracks), never in bulk."""
    try:
        audio = mutagen.File(path)
        if audio is None:
            return None
        if isinstance(audio, FLAC):
            pics = audio.pictures
            if not pics:
                return None
            front = [p for p in pics if p.type == 3]
            return (front or pics)[0].data
        tags = audio.tags
        if isinstance(tags, ID3):
            apics = tags.getall("APIC")
            if not apics:
                return None
            front = [p for p in apics if getattr(p, "type", 0) == 3]
            return (front or apics)[0].data
        if isinstance(audio, MP4):
            covr = audio.get("covr")
            return bytes(covr[0]) if covr else None
        # Ogg/Opus: base64 FLAC Picture block in metadata_block_picture
        b64 = _vorbis_get(tags, "metadata_block_picture") if tags else None
        if b64:
            import base64
            pic = Picture(base64.b64decode(b64))
            return pic.data
    except Exception:
        return None
    return None


FOLDER_ART_RE = re.compile(r"^(cover|folder|front|albumart.*)\.(jpe?g|png|webp|gif|bmp)$",
                           re.IGNORECASE)


def folder_art(dirpath):
    """First cover-ish image in a directory — only trusted for real album
    folders, never the library root (270 loose files share it with stray
    AlbumArt jpgs that belong to who-knows-what)."""
    try:
        if Path(dirpath) == LIBRARY_ROOT:
            return None
        for e in sorted(os.scandir(dirpath), key=lambda e: e.name.lower()):
            if e.is_file() and FOLDER_ART_RE.match(e.name):
                return e.path
    except OSError:
        pass
    return None


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS tracks (
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,
  mtime REAL NOT NULL, size INTEGER NOT NULL,
  title TEXT, artist TEXT, album TEXT, album_artist TEXT,
  track INTEGER, disc INTEGER,
  date TEXT, year INTEGER, orig_year INTEGER,
  genre TEXT, duration REAL, codec TEXT, samplerate INTEGER, bitdepth INTEGER,
  rating REAL, favorite INTEGER DEFAULT 0, play_count INTEGER DEFAULT 0,
  meta_mtime REAL,
  added_at REAL NOT NULL, last_played REAL,
  has_art INTEGER DEFAULT 0,
  album_id INTEGER,
  rg_track_gain REAL, rg_track_peak REAL,
  rg_album_gain REAL, rg_album_peak REAL
);
CREATE TABLE IF NOT EXISTS albums (
  id INTEGER PRIMARY KEY,
  album TEXT NOT NULL, album_artist TEXT NOT NULL,
  year INTEGER, orig_year INTEGER,
  art_src TEXT, thumb TEXT, full_art TEXT,
  UNIQUE(album, album_artist)
);
CREATE TABLE IF NOT EXISTS lyrics (
  track_id INTEGER PRIMARY KEY,
  source TEXT, synced INTEGER, body TEXT, fetched_at REAL
);
CREATE INDEX IF NOT EXISTS i_t_album  ON tracks(album_id, disc, track);
CREATE INDEX IF NOT EXISTS i_t_rating ON tracks(rating);
CREATE INDEX IF NOT EXISTS i_t_plays  ON tracks(play_count);
CREATE INDEX IF NOT EXISTS i_t_added  ON tracks(added_at);
"""


# Columns added after the first release. CREATE TABLE IF NOT EXISTS silently
# leaves an existing table alone, so new columns need an explicit ALTER against
# the DB that is already out there.
#
# (table, column, decl, rescan). `rescan` says the column can only be filled by
# re-reading the FILE — mutagen owns it — so open_db() has to clear the mtime
# cache and let the next scan re-parse the whole library. A column the APP
# writes must NOT set it: this used to be implicit ("any tracks column"), and
# left that way, adding meta_mtime would have made air's very first launch
# re-read 11k files across a 208 GB SMB share (docs/agents/air-library-share.md, A3).
MIGRATIONS = [
    ("tracks", "rg_track_gain", "REAL", True),
    ("tracks", "rg_track_peak", "REAL", True),
    ("tracks", "rg_album_gain", "REAL", True),
    ("tracks", "rg_album_peak", "REAL", True),
    # How many times we have asked the network about this track and come back
    # empty — drives the retry backoff in LyricsProvider.
    ("lyrics", "attempts", "INTEGER DEFAULT 0", False),
    # When rating/favorite were last written here. play_count merges by max()
    # and last_played by newest, but rating is a value with no natural
    # ordering, so cross-machine merges need an explicit "who wrote last".
    ("tracks", "meta_mtime", "REAL", False),
]


def open_db():
    DATA.mkdir(parents=True, exist_ok=True)
    # WAL lets readers and a writer coexist, but only ONE writer at a time, and
    # sqlite's default is to give up after 5s with "database is locked". The
    # scan and tools/lyrics-sync.py both write in bulk, so a long-running sweep
    # could take the app down at startup. Wait for the other writer instead.
    con = sqlite3.connect(DB_PATH, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    cols = {}
    added = False
    for table, col, decl, rescan in MIGRATIONS:
        if table not in cols:
            cols[table] = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
        if col not in cols[table]:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            cols[table].add(col)
            added = rescan or added
    if added:
        # The new columns are all NULL for already-scanned files; force the
        # next scan to re-read every file's tags by clearing the mtime cache
        # it compares against.
        con.execute("UPDATE tracks SET mtime = 0")
        con.commit()
    return con


def rebuild_albums(con):
    """(Re)derive the albums table from track tags: grouping key is
    (COALESCE(album_artist, artist), album), upserted so album ids stay stable
    across rescans. Tracks get album_id back-filled; album-less tracks stay
    NULL (reachable via search/playlists, not the grid)."""
    con.execute("""
        INSERT INTO albums (album, album_artist, year, orig_year)
        SELECT album, COALESCE(album_artist, artist, ''), MIN(year), MIN(orig_year)
          FROM tracks WHERE album IS NOT NULL
         GROUP BY album, COALESCE(album_artist, artist, '')
        ON CONFLICT(album, album_artist) DO UPDATE SET
          year=excluded.year, orig_year=excluded.orig_year
    """)
    con.execute("""
        UPDATE tracks SET album_id = (
          SELECT a.id FROM albums a
           WHERE a.album = tracks.album
             AND a.album_artist = COALESCE(tracks.album_artist, tracks.artist, ''))
    """)
    # Drop albums that lost all their tracks (files deleted/retagged).
    con.execute("DELETE FROM albums WHERE id NOT IN (SELECT DISTINCT album_id FROM tracks WHERE album_id IS NOT NULL)")
    con.commit()


def cache_art(data=None, src_path=None, src_id=""):
    """Write thumb (256px) + full (≤1024px) JPEGs into the art cache from raw
    bytes or an image file. Returns (thumb_name, full_name) or (None, None).
    Cache key hashes the source identity + mtime, so a changed cover re-caches
    and an unchanged one is a no-op (files already there)."""
    img = QImage()
    if data is not None:
        if not img.loadFromData(data):
            return None, None
    elif src_path:
        try:
            mt = os.stat(src_path).st_mtime
        except OSError:
            return None, None
        src_id = f"{src_path}:{mt}"
        if not img.load(src_path):
            return None, None
    else:
        return None, None
    key = hashlib.sha1(src_id.encode() if isinstance(src_id, str) else src_id).hexdigest()[:16]
    thumb_name, full_name = f"{key}-t.jpg", f"{key}-f.jpg"
    ART.mkdir(parents=True, exist_ok=True)
    tp, fp = ART / thumb_name, ART / full_name
    if not tp.exists():
        img.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(tp), "JPEG", 85)
    if not fp.exists():
        big = img
        if max(img.width(), img.height()) > 1024:
            big = img.scaled(1024, 1024, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        big.save(str(fp), "JPEG", 90)
    return thumb_name, full_name


class Scanner(QThread):
    """Background library scan: walk the SSD, mutagen-parse new/changed files
    (mtime+size compare), mirror tags into the DB in ~200-file transactions so
    the grid populates live, then rebuild albums and cache art for albums that
    lack it. Owns its own sqlite connection (sqlite objects aren't shareable
    across threads)."""

    progress = Signal(int, int)      # done, total (parse phase)
    batch = Signal()                 # a transaction landed — models may refresh
    summary = Signal("QVariantMap")  # scan stats at the end
    done = Signal()

    def run(self):
        t0 = time.time()
        con = open_db()
        try:
            self._run(con, t0)
        finally:
            con.close()

    def _run(self, con, t0):
        root = LIBRARY_ROOT
        if not root.is_dir():
            # SSD not mounted: never prune, just report and bail — the app
            # keeps browsing the existing DB with tracks greyed unavailable.
            self.summary.emit({"mounted": False, "secs": 0.0})
            self.done.emit()
            return

        seen = {}
        stack = [str(root)]
        while stack:
            d = stack.pop()
            try:
                for e in os.scandir(d):
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                    elif e.is_file() and os.path.splitext(e.name)[1].lower() in AUDIO_EXTS:
                        st = e.stat()
                        seen[e.path] = (st.st_mtime, st.st_size)
            except OSError:
                continue

        known = {r["path"]: (r["mtime"], r["size"])
                 for r in con.execute("SELECT path, mtime, size FROM tracks")}
        todo = [p for p, ms in seen.items()
                if p not in known or abs(known[p][0] - ms[0]) > 1 or known[p][1] != ms[1]]
        gone = [p for p in known if p not in seen]

        now = time.time()
        bad = 0
        for i, p in enumerate(todo):
            t = read_tags(p)
            if t is None:
                bad += 1
                continue
            mtime, size = seen[p]
            con.execute("""
                INSERT INTO tracks (path, mtime, size, title, artist, album, album_artist,
                                    track, disc, date, year, orig_year, genre, duration,
                                    codec, samplerate, bitdepth, rating, favorite,
                                    play_count, added_at, has_art,
                                    rg_track_gain, rg_track_peak, rg_album_gain, rg_album_peak)
                VALUES (:path,:mtime,:size,:title,:artist,:album,:album_artist,
                        :track,:disc,:date,:year,:orig_year,:genre,:duration,
                        :codec,:samplerate,:bitdepth,:rating,:favorite,:play_count,:added_at,:has_art,
                        :rg_track_gain,:rg_track_peak,:rg_album_gain,:rg_album_peak)
                ON CONFLICT(path) DO UPDATE SET
                    mtime=:mtime, size=:size, title=:title, artist=:artist, album=:album,
                    album_artist=:album_artist, track=:track, disc=:disc, date=:date,
                    year=:year, orig_year=:orig_year, genre=:genre, duration=:duration,
                    codec=:codec, samplerate=:samplerate, bitdepth=:bitdepth,
                    rating=:rating, favorite=:favorite, play_count=:play_count,
                    has_art=:has_art,
                    rg_track_gain=:rg_track_gain, rg_track_peak=:rg_track_peak,
                    rg_album_gain=:rg_album_gain, rg_album_peak=:rg_album_peak
            """, {**t, "path": p, "mtime": mtime, "size": size, "added_at": now})
            if (i + 1) % 200 == 0:
                con.commit()
                self.progress.emit(i + 1, len(todo))
                self.batch.emit()
        con.commit()

        # Prune vanished files — safe here: the root IS mounted and was walked.
        # (An empty walk of a mounted-but-hosed root still can't run: seen would
        # be empty AND known non-empty → require some survivors before pruning.)
        if gone and (len(gone) < len(known) or seen):
            con.executemany("DELETE FROM tracks WHERE path=?", [(p,) for p in gone])
            con.commit()

        rebuild_albums(con)
        self.batch.emit()
        self._art_pass(con)

        albums = con.execute("SELECT COUNT(*) c FROM albums").fetchone()["c"]
        total = con.execute("SELECT COUNT(*) c FROM tracks").fetchone()["c"]
        loose = con.execute("SELECT COUNT(*) c FROM tracks WHERE album_id IS NULL").fetchone()["c"]
        rated = con.execute("SELECT COUNT(*) c FROM tracks WHERE rating IS NOT NULL").fetchone()["c"]
        gained = con.execute("SELECT COUNT(rg_track_gain) c FROM tracks").fetchone()["c"]
        self.summary.emit({"mounted": True, "tracks": total, "albums": albums,
                           "albumless": loose, "rated": rated, "parsed": len(todo),
                           "unreadable": bad, "pruned": len(gone), "replaygain": gained,
                           "secs": round(time.time() - t0, 1)})
        self.done.emit()

    def _art_pass(self, con):
        """Give every album art: embedded (authoritative — folder images in the
        shared root lie) then folder art. Only albums with no cached thumb."""
        rows = con.execute("""
            SELECT a.id, a.thumb FROM albums a WHERE a.thumb IS NULL
        """).fetchall()
        n = 0
        for r in rows:
            aid = r["id"]
            donor = con.execute(
                "SELECT path FROM tracks WHERE album_id=? AND has_art=1 LIMIT 1",
                (aid,)).fetchone()
            thumb = full = src = None
            if donor:
                data = embedded_art(donor["path"])
                if data:
                    src = "embedded:" + donor["path"]
                    thumb, full = cache_art(data=data, src_id=hashlib.sha1(data).hexdigest())
            if not thumb:
                anyt = con.execute(
                    "SELECT path FROM tracks WHERE album_id=? LIMIT 1", (aid,)).fetchone()
                if anyt:
                    fa = folder_art(os.path.dirname(anyt["path"]))
                    if fa:
                        src = "file:" + fa
                        thumb, full = cache_art(src_path=fa)
            if thumb:
                con.execute("UPDATE albums SET art_src=?, thumb=?, full_art=? WHERE id=?",
                            (src, thumb, full, aid))
                n += 1
                if n % 25 == 0:
                    con.commit()
                    self.batch.emit()
        con.commit()
        self.batch.emit()


# ---------------------------------------------------------------------------
# Library — the GUI-thread query/write API everything binds to
# ---------------------------------------------------------------------------

def _artist_sortkey(s):
    s = (s or "").casefold()
    return s[4:] if s.startswith("the ") else s


# Smart playlists: name → (SQL, params). One tuple to add another. All return
# full track rows ordered for direct queueing.
_T = "SELECT * FROM tracks"
SMART_PLAYLISTS = [
    ("5 starred",      _T + " WHERE rating >= 0.99 ORDER BY artist, album, disc, track", ()),
    ("4+ starred",     _T + " WHERE rating >= 0.79 ORDER BY rating DESC, artist, album", ()),
    ("favorites",      _T + " WHERE favorite = 1 ORDER BY artist, album, disc, track", ()),
    ("recently added", _T + " ORDER BY added_at DESC, album, disc, track LIMIT 250", ()),
    ("most played",    _T + " WHERE play_count > 0 ORDER BY play_count DESC LIMIT 250", ()),
    ("recently played", _T + " WHERE last_played IS NOT NULL ORDER BY last_played DESC LIMIT 250", ()),
    ("unrated",        _T + " WHERE rating IS NULL ORDER BY artist, album, disc, track", ()),
]


class Library(QObject):
    """Owns the GUI-thread SQLite connection; the query API for the models and
    the write API for ratings/favourites/play counts (DB now, file tags via the
    TagWriter queue)."""

    changed = Signal()          # bulk data changed (scan batch) — models refresh
    trackChanged = Signal(int)  # one track's rating/favorite/counts changed
    scanProgress = Signal(int, int)
    scanSummary = Signal("QVariantMap")
    scanRunning = Signal(bool)

    def __init__(self, tagwriter, parent=None):
        super().__init__(parent)
        self._con = open_db()
        # Cache hygiene at startup: purge oversized bodies (scraped-webpage
        # tagger garbage) and STALE negative results, so "no lyrics found"
        # gets another go online eventually. The age check matters: a full
        # tools/lyrics-sync.py sweep records thousands of honest misses, and
        # dropping them on every launch would make the next sweep re-ask the
        # network for all of them. 'instrumental' is never purged — that is a
        # real answer about the track, not a failed lookup.
        self._con.execute(
            "DELETE FROM lyrics WHERE length(body) > 6000"
            "    OR (source='none' AND COALESCE(fetched_at, 0) < ?)",
            (time.time() - LyricsProvider.RETRY_NONE_AFTER,))
        self._con.commit()
        self._tagwriter = tagwriter
        self._scanner = None
        self._search_rows = None  # lazy [(casefolded haystack, id)]
        # Rows for files opened by path that the library has never scanned —
        # negative ids, memory only, never written to the DB. See ids_for_paths.
        self._transient = {}
        self._transient_by_path = {}
        self._transient_seq = 0
        self.changed.connect(lambda: setattr(self, "_search_rows", None))

    # ---- scanning ----

    @Slot()
    def rescan(self):
        if self._scanner and self._scanner.isRunning():
            return
        self._scanner = Scanner(self)
        self._scanner.progress.connect(self.scanProgress)
        self._scanner.batch.connect(self._on_batch)
        self._scanner.summary.connect(self._on_summary)
        self._scanner.done.connect(lambda: self.scanRunning.emit(False))
        self.scanRunning.emit(True)
        self._scanner.start()

    def _on_batch(self):
        self.changed.emit()

    def _on_summary(self, s):
        print("scan:", dict(s), flush=True)
        self.scanSummary.emit(s)

    # ---- queries (all return lists of plain dicts for the models) ----

    def _rows(self, sql, params=()):
        return [dict(r) for r in self._con.execute(sql, params)]

    def albums(self, sort="orig_year"):
        rows = self._rows("SELECT * FROM albums")
        if sort == "artist":
            rows.sort(key=lambda r: (_artist_sortkey(r["album_artist"]),
                                     r["orig_year"] or r["year"] or 9999))
        elif sort == "album":
            rows.sort(key=lambda r: (r["album"] or "").casefold())
        else:  # orig_year
            rows.sort(key=lambda r: (r["orig_year"] or r["year"] or 9999,
                                     _artist_sortkey(r["album_artist"]),
                                     (r["album"] or "").casefold()))
        return rows

    def album(self, album_id):
        r = self._con.execute("SELECT * FROM albums WHERE id=?", (album_id,)).fetchone()
        return dict(r) if r else {}

    def album_tracks(self, album_id):
        return self._rows(
            "SELECT * FROM tracks WHERE album_id=? ORDER BY disc, track, title",
            (album_id,))

    def artist_tracks(self, artist):
        """Everything by an artist, matched on EITHER tag — an album of theirs
        carries the name in album_artist, a one-off on a compilation only in
        artist.

        Matching is folded equality against `trackmatch.artist_variants` (the
        full tag and the PRIMARY name), so "Oneohtrix Point Never" also picks up
        "…feat. Iggy Pop" and "…& Alex G" — but asking for the guest returns
        nothing, since they are not primary anywhere. That's the deliberate
        trade: `artist_matches`' token-subset test would catch them and would
        also call "Air" a match for "Air France"."""
        want = {trackmatch.fold(v) for v in trackmatch.artist_variants(artist)}
        want.discard("")
        if not want:
            return []

        def hit(s):
            return any(trackmatch.fold(v) in want
                       for v in trackmatch.artist_variants(s or ""))

        return [r for r in self._rows(
                    "SELECT * FROM tracks ORDER BY album_id, disc, track, title")
                if hit(r["artist"]) or hit(r["album_artist"])]

    def smart_names(self):
        return [name for name, _, _ in SMART_PLAYLISTS]

    def smart_tracks(self, name):
        for n, sql, params in SMART_PLAYLISTS:
            if n == name:
                return self._rows(sql, params)
        return []

    def tracks_by_ids(self, ids):
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        rows = {r["id"]: r for r in self._rows(
            f"SELECT * FROM tracks WHERE id IN ({marks})", tuple(ids))}
        # Transient rows (a file opened from argv that the library has never
        # seen) carry NEGATIVE ids and live only in memory, so the DB query
        # above can never return them. See ids_for_paths.
        rows.update({i: self._transient[i] for i in ids if i in self._transient})
        return [rows[i] for i in ids if i in rows]

    # ---- opening a file by path (argv / the OPEN verb) ----

    def ids_for_paths(self, paths):
        """Track ids for arbitrary filesystem paths, in the order given.

        A path inside the library resolves to its real row, which is the whole
        point: a double-clicked track then behaves exactly like the same track
        clicked in the queue — ratings, play count, lyrics and the album it
        belongs to all work, because it IS that row.

        A path the library has never scanned gets a TRANSIENT row instead, held
        only in memory under a negative id. It has to be a row of the same shape
        (read_tags supplies every tag column) because the queue, the models and
        the QML all read one; and it has to be negative because every write path
        keys on the id and must miss:

          * `setRating`/`setFavorite`/`bump_playcount` all UPDATE ... WHERE id=?,
            which matches nothing, and then guard their tag write on `_track()`
            having found a row — so nothing is written to a file this library
            does not own.
          * `LyricsProvider._resolve_one` looks the id up and returns early.
          * `save_state` stores the id and `restore_state` resolves it through
            `tracks_by_ids` against a fresh process, where the transient map is
            empty — so a one-off file does not come back at the next launch,
            which is the behaviour we want anyway.

        Files that mutagen cannot read at all are dropped rather than queued as
        a row with no duration: mpv would skip them instantly and the user would
        see a queue entry blink past. Whatever survives is what gets played."""
        out = []
        for p in paths:
            try:
                path = str(Path(p).resolve())
            except OSError:
                continue
            if not os.path.isfile(path):
                continue
            row = self._con.execute(
                "SELECT * FROM tracks WHERE path=?", (path,)).fetchone()
            if row is not None:
                out.append(int(row["id"]))
                continue
            known = self._transient_by_path.get(path)
            if known is not None:
                out.append(known)
                continue
            t = read_tags(path)
            if t is None:
                print("open: unreadable:", path, flush=True)
                continue
            st = os.stat(path)
            self._transient_seq -= 1
            tid = self._transient_seq
            t.update({"id": tid, "path": path, "album_id": None,
                      "mtime": st.st_mtime, "size": st.st_size,
                      "added_at": time.time(), "last_played": None,
                      "meta_mtime": None})
            # A file outside the library often has no tags at all; the filename
            # is the only name there is, and an untitled row draws as a blank
            # line in every list that shows it.
            if not t.get("title"):
                t["title"] = Path(path).stem
            self._transient[tid] = t
            self._transient_by_path[path] = tid
            out.append(tid)
        return out

    def search(self, text):
        """Casefolded substring search over title/artist/album — Unicode-correct
        (the Japanese titles) and instant at 11k rows against a cached
        haystack."""
        text = (text or "").casefold().strip()
        if not text:
            return []
        if self._search_rows is None:
            self._search_rows = [
                ((f'{r["title"] or ""}\n{r["artist"] or ""}\n{r["album"] or ""}'
                  f'\n{r["album_artist"] or ""}').casefold(), r["id"])
                for r in self._con.execute(
                    "SELECT id, title, artist, album, album_artist FROM tracks")]
        words = text.split()
        ids = [tid for hay, tid in self._search_rows if all(w in hay for w in words)]
        return self.tracks_by_ids(ids[:400])

    @Slot(int, bool)
    def setInstrumental(self, track_id, yes):
        """Mark/unmark a track as having no words at all.

        The escape hatch for everything the network cannot settle: LRCLIB only
        flags instrumentals it knows about, and a large slice of this library
        it has never seen. Marking one is permanent (no retry, no lookup);
        unmarking clears the row so the next play resolves it afresh."""
        if yes:
            self._con.execute(
                "INSERT OR REPLACE INTO lyrics"
                " (track_id, source, synced, body, fetched_at, attempts)"
                " VALUES (?,?,?,?,?,?)",
                (track_id, "instrumental-user", 0, "", time.time(), 0))
        else:
            self._con.execute("DELETE FROM lyrics WHERE track_id=?", (track_id,))
        self._con.commit()
        self.trackChanged.emit(track_id)

    def median_rg_gain(self):
        """The library's median ReplayGain track gain, as the fallback for the
        minority of files that carry no tags. Derived rather than guessed: a
        constant would put untagged files at a different loudness from the
        collection they sit in, which is exactly what normalising is meant to
        stop. Falls back to a flat 0 (no change) if nothing is tagged yet."""
        try:
            row = self._con.execute(
                "SELECT rg_track_gain g FROM tracks WHERE rg_track_gain IS NOT NULL"
                " ORDER BY g LIMIT 1"
                " OFFSET (SELECT COUNT(*)/2 FROM tracks WHERE rg_track_gain IS NOT NULL)"
            ).fetchone()
        except sqlite3.Error:
            return 0.0
        return round(float(row["g"]), 2) if row and row["g"] is not None else 0.0

    def rg_coverage(self):
        """(tagged, total) — how much of the library can actually be levelled."""
        try:
            r = self._con.execute(
                "SELECT COUNT(*) t, COUNT(rg_track_gain) g FROM tracks").fetchone()
            return int(r["g"]), int(r["t"])
        except sqlite3.Error:
            return 0, 0

    # ---- writes (DB + tag queue) ----

    def _track(self, track_id):
        r = self._con.execute("SELECT * FROM tracks WHERE id=?", (track_id,)).fetchone()
        return dict(r) if r else None

    @Slot(int, float)
    def setRating(self, track_id, rating):
        """rating: FMPS 0..1 (UI passes stars/5); negative clears."""
        val = None if rating < 0 else max(0.0, min(1.0, rating))
        # meta_mtime: the tiebreaker tools/dbsync.py merges rating/favorite on.
        self._con.execute("UPDATE tracks SET rating=?, meta_mtime=? WHERE id=?",
                          (val, time.time(), track_id))
        self._con.commit()
        t = self._track(track_id)
        if t:
            self._tagwriter.enqueue(t["path"], rating=val)
        self.trackChanged.emit(track_id)

    @Slot(int, bool)
    def setFavorite(self, track_id, fav):
        self._con.execute("UPDATE tracks SET favorite=?, meta_mtime=? WHERE id=?",
                          (1 if fav else 0, time.time(), track_id))
        self._con.commit()
        t = self._track(track_id)
        if t:
            self._tagwriter.enqueue(t["path"], favorite=bool(fav))
        self.trackChanged.emit(track_id)

    def bump_playcount(self, track_id):
        self._con.execute(
            "UPDATE tracks SET play_count=play_count+1, last_played=? WHERE id=?",
            (time.time(), track_id))
        self._con.commit()
        t = self._track(track_id)
        if t:
            self._tagwriter.enqueue(t["path"], play_count=t["play_count"])
        self.trackChanged.emit(track_id)

    # ---- lyrics cache (used by LyricsProvider from its worker via own conn) ----

    def close(self):
        self._con.close()


# ---------------------------------------------------------------------------
# Tag writeback
# ---------------------------------------------------------------------------

class TagWriter(QObject):
    """Serialized FMPS/FAVORITE tag writeback. Every intended write is
    journaled to $XDG_STATE_HOME/player/tagwrites.log BEFORE touching the file;
    the prefs key tagWrites gates behaviour: "off" (drop), "log" (journal only
    — the shipped default until the journal has been eyeballed), "on" (journal
    + write). Only the specific FMPS/FAVORITE keys are ever touched, and the
    write is ATOMIC — copy, mutate the copy, fsync, os.replace (atomicsave.py).

    Because a copy is much heavier than the in-place save this replaces, the
    queue COALESCES: entries are given COALESCE_S to accumulate and every
    pending entry for the same path is merged into one write (last value wins
    per field). Five stars clicked in a row are one rewrite of the FLAC, not
    five."""

    # Long enough to swallow a burst of clicks, short enough that a rating is
    # in the file before the user could plausibly pull the SSD out.
    COALESCE_S = 1.5

    def __init__(self, prefs, parent=None):
        super().__init__(parent)
        self._prefs = prefs
        self._q = []
        self._cv = threading.Condition()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def mode(self):
        m = self._prefs.get("tagWrites", "log")
        return m if m in ("off", "log", "on") else "log"

    def enqueue(self, path, rating="keep", favorite="keep", play_count="keep"):
        if self.mode() == "off":
            return
        with self._cv:
            self._q.append({"path": path, "rating": rating, "favorite": favorite,
                            "play_count": play_count, "ts": time.time()})
            self._cv.notify()

    def _journal(self, entry, status):
        try:
            STATE.mkdir(parents=True, exist_ok=True)
            with open(STATE / "tagwrites.log", "a", encoding="utf-8") as f:
                f.write(json.dumps({**entry, "status": status}) + "\n")
        except OSError:
            pass

    def _drain_same_path(self, entry):
        """Merge every other queued entry for this path into `entry`, removing
        them from the queue. Called with the lock held."""
        keep = []
        for other in self._q:
            if other["path"] != entry["path"]:
                keep.append(other)
                continue
            for k in ("rating", "favorite", "play_count"):
                if other[k] != "keep":
                    entry[k] = other[k]
            entry["ts"] = other["ts"]
        self._q = keep
        return entry

    def _loop(self):
        while True:
            with self._cv:
                while not self._q:
                    self._cv.wait()
                entry = self._q.pop(0)
            # Let a burst land before paying for a whole-file copy.
            time.sleep(self.COALESCE_S)
            with self._cv:
                entry = self._drain_same_path(entry)
            path = entry["path"]
            if not os.path.exists(path):
                self._journal(entry, "missing-requeued")
                # SSD probably unplugged — park it at the back and idle a bit.
                time.sleep(30)
                with self._cv:
                    self._q.append(entry)
                continue
            if self.mode() != "on":
                self._journal(entry, "logged")
                continue
            try:
                self._write(path, entry)
                self._journal(entry, "written")
            except Exception as e:  # never kill the worker on one bad file
                self._journal(entry, f"error: {e}")

    @staticmethod
    def _write(path, entry):
        atomicsave.atomic_save(path, lambda audio: TagWriter._apply(audio, entry))

    @staticmethod
    def _apply(audio, entry):
        """The tag mutation only — handed a mutagen object for a temp copy by
        atomic_save, which owns opening it and calling save()."""
        rating, favorite, plays = entry["rating"], entry["favorite"], entry["play_count"]
        tags = audio.tags
        if isinstance(tags, ID3) or (tags is None and hasattr(audio, "add_tags")
                                     and not isinstance(audio, (MP4, FLAC))):
            if tags is None:
                audio.add_tags()
                tags = audio.tags

            def set_txxx(desc, val):
                if val is None:
                    tags.delall("TXXX:" + desc)
                else:
                    tags.setall("TXXX:" + desc,
                                [TXXX(encoding=3, desc=desc, text=[str(val)])])
            if rating != "keep":
                set_txxx("FMPS_Rating", None if rating is None else round(rating, 2))
            if favorite != "keep":
                set_txxx("FAVORITE", "1" if favorite else None)
            if plays != "keep":
                set_txxx("FMPS_Playcount", int(plays))
        elif isinstance(audio, MP4):
            def set_ff(name, val):
                key = "----:com.apple.iTunes:" + name
                if val is None:
                    audio.pop(key, None)
                else:
                    audio[key] = [MP4FreeForm(str(val).encode())]
            if rating != "keep":
                set_ff("FMPS_Rating", None if rating is None else round(rating, 2))
            if favorite != "keep":
                set_ff("FAVORITE", "1" if favorite else None)
            if plays != "keep":
                set_ff("FMPS_Playcount", int(plays))
        else:  # Vorbis-comment family
            def set_vc(key, val):
                if val is None:
                    audio.pop(key, None)
                else:
                    audio[key] = [str(val)]
            if rating != "keep":
                set_vc("FMPS_RATING", None if rating is None else round(rating, 2))
            if favorite != "keep":
                set_vc("FAVORITE", "1" if favorite else None)
            if plays != "keep":
                set_vc("FMPS_PLAYCOUNT", int(plays))


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------

class Player(QObject):
    """The queue + libmpv. The Python-side queue (list of track dicts) is the
    source of truth; it's mirrored into mpv's internal playlist from the
    current track onward so mpv prefetches the next file (gapless where the
    formats allow). mpv's event callbacks arrive on its own thread — the _sig*
    Signals bounce them onto the GUI thread before any state is touched."""

    queueChanged = Signal()
    indexChanged = Signal()
    currentChanged = Signal()
    playingChanged = Signal()
    positionChanged = Signal()
    durationChanged = Signal()
    shuffleChanged = Signal()
    loopChanged = Signal()
    volumeChanged = Signal()
    replayGainChanged = Signal()
    seeked = Signal(float)  # explicit seeks only (not per-tick) — MPRIS Seeked

    _sigPos = Signal(float)
    _sigDur = Signal(float)
    _sigPause = Signal(bool)
    _sigPlpos = Signal(int)
    _sigIdle = Signal(bool)

    LOOP_NONE, LOOP_TRACK, LOOP_ALL = 0, 1, 2

    def __init__(self, library, prefs, parent=None):
        super().__init__(parent)
        self._library = library
        self._prefs = prefs
        self._queue = []        # track dicts, in play order (shuffle reorders)
        self._orig_queue = None  # pre-shuffle order, to restore on unshuffle
        self._index = -1
        self._mpv_base = 0      # queue index of mpv playlist position 0
        self._position = 0.0
        # An explicit seek's target, until mpv's clock agrees with it (see
        # _on_pos): mpv keeps reporting the PRE-seek time for a tick or two.
        self._seek_target = None
        self._seek_at = 0.0
        self._duration = 0.0
        self._playing = False
        self._shuffle = False
        self._loop = self.LOOP_NONE
        self._listened = 0.0    # accumulated seconds actually heard, per track
        self._counted = False
        self._mpv_paused = False
        self._idle = True

        import mpv as libmpv
        self._mpv = libmpv.MPV(vid="no", audio_display="no",
                               gapless_audio="weak", ytdl=False)
        vol = self._prefs.get("volume", 100)
        try:
            self._mpv.volume = float(vol)
        except Exception:
            pass

        self._rg_mode = self._prefs.get("replayGain", "auto")
        if self._rg_mode not in self.RG_MODES:
            self._rg_mode = "auto"
        self._rg_preamp = float(self._prefs.get("rgPreamp", 0.0) or 0.0)
        self._rg_fallback = self._library.median_rg_gain()
        self._apply_rg("track")
        # The first scan after the schema migration is what fills the gain
        # columns in — recompute the fallback once it lands.
        self._library.scanSummary.connect(self._on_scan_for_rg)

        self._sigPos.connect(self._on_pos)
        self._sigDur.connect(self._on_dur)
        self._sigPause.connect(self._on_pause)
        self._sigPlpos.connect(self._on_plpos)
        self._sigIdle.connect(self._on_idle)

        @self._mpv.property_observer("time-pos")
        def _obs_pos(_name, value):  # mpv thread
            if value is not None:
                self._sigPos.emit(float(value))

        @self._mpv.property_observer("duration")
        def _obs_dur(_name, value):
            if value is not None:
                self._sigDur.emit(float(value))

        @self._mpv.property_observer("pause")
        def _obs_pause(_name, value):
            if value is not None:
                self._sigPause.emit(bool(value))

        @self._mpv.property_observer("playlist-pos")
        def _obs_plpos(_name, value):
            if value is not None:
                self._sigPlpos.emit(int(value))

        @self._mpv.property_observer("idle-active")
        def _obs_idle(_name, value):
            if value is not None:
                self._sigIdle.emit(bool(value))

    # ---- mpv event handlers (GUI thread) ----

    def _on_pos(self, pos):
        # Drop the stale samples that trail an explicit seek. mpv answers a seek
        # asynchronously and keeps reporting the old clock meanwhile, so taking
        # those would walk the position BACK to where the track was, then
        # forward again once the seek lands — once per stale sample. That is
        # what made the titlebar scrub bar bounce a few times after a click.
        if self._seek_target is not None:
            if abs(pos - self._seek_target) <= 1.0 or (time.monotonic() - self._seek_at) > 1.5:
                self._seek_target = None   # caught up (or mpv seeked elsewhere)
            else:
                return
        delta = pos - self._position
        if 0 < delta < 2.0:
            self._listened += delta
            self._maybe_count()
        if abs(pos - self._position) >= 0.2:
            self._position = pos
            self.positionChanged.emit()

    def _on_dur(self, dur):
        if dur != self._duration:
            self._duration = dur
            self.durationChanged.emit()

    def _update_playing(self):
        """`playing` is derived — mpv's pause flag alone misses the transitions
        where pause never changes (track start, playlist ran out)."""
        playing = self._index >= 0 and not self._mpv_paused and not self._idle
        if playing != self._playing:
            self._playing = playing
            self.playingChanged.emit()

    def _on_pause(self, paused):
        self._mpv_paused = paused
        self._update_playing()

    def _on_plpos(self, plpos):
        if plpos < 0:
            return
        idx = self._mpv_base + plpos
        if idx != self._index and 0 <= idx < len(self._queue):
            self._set_index(idx)

    def _on_idle(self, idle):
        self._idle = idle
        self._update_playing()
        if not idle or self._index < 0 or not self._queue:
            return
        # Whole mpv playlist ran out (our mirror only holds current→end).
        if self._loop == self.LOOP_ALL:
            self.jumpTo(0)

    def _maybe_count(self):
        t = self.currentTrackDict()
        if self._counted or not t:
            return
        dur = t.get("duration") or self._duration
        if dur and self._listened >= min(dur / 2.0, 240.0):
            self._counted = True
            self._library.bump_playcount(t["id"])

    # ---- queue plumbing ----

    def _set_index(self, idx):
        self._index = idx
        self._listened = 0.0
        self._counted = False
        self._position = 0.0
        self.indexChanged.emit()
        self.currentChanged.emit()
        self.positionChanged.emit()

    # ---- ReplayGain ----
    #
    # mpv applies the gain itself, from the file's own tags, in the decode
    # chain — independent of the `volume` property, so the volume slider keeps
    # meaning what it always did. We only choose the MODE and the preamp.
    #
    # ~96% of this library carries ReplayGain tags already, so nothing has to
    # be analysed; the ~4% that don't get `replaygain-fallback`, set to the
    # library's own median track gain (see Library.median_rg_gain) rather than
    # a made-up constant, so untagged files sit at the same loudness as the
    # rest instead of jumping out.

    RG_MODES = ("off", "track", "album", "auto")

    def _on_scan_for_rg(self, _summary):
        fb = self._library.median_rg_gain()
        if abs(fb - self._rg_fallback) > 0.01:
            self._rg_fallback = fb
            self._apply_rg(self._rg_effective(max(0, self._index)))
        self.replayGainChanged.emit()

    def _apply_rg(self, effective):
        """Push one of track/album/no to mpv. Takes effect per file as it is
        loaded, so changing it mid-track only shows on the next one."""
        try:
            self._mpv.replaygain = "no" if self._rg_mode == "off" else effective
            self._mpv.replaygain_preamp = float(self._rg_preamp)
            self._mpv.replaygain_fallback = float(self._rg_fallback)
            # Back the gain off rather than clip when the peak says it would.
            self._mpv.replaygain_clip = True
        except Exception as e:
            print("replaygain:", e, flush=True)

    def _rg_effective(self, start_idx=0):
        """'auto' = album gain when the upcoming queue is one album (keeps an
        album's intended quiet/loud contrast), track gain otherwise (levels a
        shuffled library, which is the point of normalising at all)."""
        if self._rg_mode != "auto":
            return self._rg_mode if self._rg_mode != "off" else "no"
        if self._shuffle:
            return "track"
        ids = {t.get("album_id") for t in self._queue[start_idx:]}
        ids.discard(None)
        ids.discard(0)
        one_album = len(ids) == 1 and len(self._queue) - start_idx > 1
        return "album" if one_album else "track"

    @Property(str, notify=replayGainChanged)
    def replayGain(self):
        return self._rg_mode

    @Property(float, notify=replayGainChanged)
    def rgPreamp(self):
        return self._rg_preamp

    @Property(str, notify=replayGainChanged)
    def rgStatus(self):
        """One line for the settings drawer: what is actually being applied."""
        if self._rg_mode == "off":
            return "off — files play at their tagged loudness"
        eff = self._rg_effective(max(0, self._index))
        pre = f", preamp {self._rg_preamp:+.1f} dB" if self._rg_preamp else ""
        return f"{eff} gain{pre} (untagged: {self._rg_fallback:+.1f} dB)"

    @Slot(str)
    def setReplayGain(self, mode):
        if mode not in self.RG_MODES or mode == self._rg_mode:
            return
        self._rg_mode = mode
        self._prefs.set("replayGain", mode)
        self._apply_rg(self._rg_effective(max(0, self._index)))
        self.replayGainChanged.emit()

    @Slot(float)
    def setRgPreamp(self, db):
        db = max(-15.0, min(15.0, float(db)))
        if abs(db - self._rg_preamp) < 0.01:
            return
        self._rg_preamp = db
        self._prefs.set("rgPreamp", db)
        self._apply_rg(self._rg_effective(max(0, self._index)))
        self.replayGainChanged.emit()

    def _sync_mpv(self, start_idx, paused=False):
        """Point mpv at queue[start_idx:] — replace starts playback, appends
        prefetch the rest for gapless auto-advance. _set_index runs first so a
        playlist-pos event from the replace resolves to the same index (no-op)
        instead of racing us."""
        paths = [t["path"] for t in self._queue[start_idx:]]
        if not paths:
            return
        self._mpv_base = start_idx
        self._set_index(start_idx)
        # Decide album-vs-track BEFORE the load: mpv reads the option when it
        # starts decoding each file.
        self._apply_rg(self._rg_effective(start_idx))
        self.replayGainChanged.emit()
        self._mpv.command("loadfile", paths[0], "replace")
        for p in paths[1:]:
            self._mpv.command("loadfile", p, "append")
        self._mpv.pause = paused

    def currentTrackDict(self):
        if 0 <= self._index < len(self._queue):
            return self._queue[self._index]
        return None

    def apply_track_update(self, track_id, row):
        """Patch the cached queue dicts after a DB write, then re-notify.

        `current` reads straight out of `self._queue`, which is a snapshot taken
        by `tracks_by_ids()` when the queue was built and never refreshed. So a
        rating/favourite write used to update the DB and every ListModel, emit
        currentChanged, and then have QML re-read the SAME stale dict — the
        now-playing stars and heart never moved, which looked like the click
        doing nothing at all. Patch the cache first, and only then notify.

        `_orig_queue` (the pre-shuffle order) is a shallow copy, so it holds the
        very same dict objects and comes along for free.
        """
        touched = False
        for t in self._queue:
            if t.get("id") == track_id:
                t.update(row)
                touched = True
        if touched:
            self.currentChanged.emit()

    # ---- properties for QML ----

    @Property("QVariant", notify=currentChanged)
    def current(self):
        t = self.currentTrackDict()
        if not t:
            return {}
        art = ""
        year = 0
        album_artist = ""
        if t.get("album_id"):
            a = self._library.album(t["album_id"])
            album_artist = a.get("album_artist") or ""
            if a.get("full_art"):
                art = str(ART / a["full_art"])
            # ORIGINAL release year, falling back to this pressing's — same
            # preference album_row() uses, so the now-playing readout and the
            # gallery never disagree about an album's date.
            year = a.get("orig_year") or a.get("year") or 0
        return {"id": t["id"], "title": t.get("title") or "", "artist": t.get("artist") or "",
                "album": t.get("album") or "", "rating": t.get("rating"),
                "favorite": t.get("favorite", 0), "duration": t.get("duration") or 0.0,
                "artPath": art, "albumId": t.get("album_id") or 0, "year": year,
                # the gallery's filter matches album_artist, so the cover's
                # context menu needs THAT name, not the per-track one.
                "albumArtist": album_artist}

    @Property(int, notify=indexChanged)
    def index(self): return self._index

    @Property(int, notify=queueChanged)
    def queueLength(self): return len(self._queue)

    @Property(bool, notify=playingChanged)
    def playing(self): return self._playing

    @Property(float, notify=positionChanged)
    def position(self): return self._position

    @Property(float, notify=durationChanged)
    def duration(self): return self._duration

    @Property(bool, notify=shuffleChanged)
    def shuffle(self): return self._shuffle

    @Property(int, notify=loopChanged)
    def loop(self): return self._loop

    @Property(float, notify=volumeChanged)
    def volume(self):
        try:
            return float(self._mpv.volume)
        except Exception:
            return 100.0

    @volume.setter
    def volume(self, v):
        v = max(0.0, min(130.0, float(v)))
        self._mpv.volume = v
        self._prefs.set("volume", v)
        self.volumeChanged.emit()

    # ---- slots (QML / titlebar / MPRIS) ----

    @Slot("QVariantList", int)
    def playTracks(self, ids, start=0):
        ids = [int(i) for i in ids]
        self._queue = self._library.tracks_by_ids(ids)
        self._queue = [t for t in self._queue if os.path.exists(t["path"])] or self._queue
        self._orig_queue = None
        if self._shuffle and self._queue:
            self._queue = self._shuffled(self._queue, keep_first=start)
            start = 0
        self.queueChanged.emit()
        if self._queue:
            self._sync_mpv(min(start, len(self._queue) - 1))

    @Slot("QVariantList")
    def playPaths(self, paths):
        """Replace the queue with files named by path and start playing.

        This is what `player /path/to/track.flac` and the desktop entry's `%F`
        land in — see `paths_from_argv` and the queue socket's OPEN verb. It
        REPLACES rather than appends, which is what every other player does with
        a file handed to it from the file manager, and is the only reading of
        "open this" that cannot leave the track buried behind an hour of queue.

        Empty is a no-op, deliberately: a launch whose arguments were all
        unreadable or all missing must leave a running player exactly as it
        was rather than stop the music."""
        ids = self._library.ids_for_paths([str(p) for p in paths])
        if ids:
            self.playTracks(ids, 0)

    @Slot(int, int)
    def playAlbum(self, album_id, start=0):
        rows = self._library.album_tracks(album_id)
        self.playTracks([r["id"] for r in rows], start)

    @Slot(int)
    def queueAlbum(self, album_id):
        rows = self._library.album_tracks(album_id)
        self.queueTracks([r["id"] for r in rows])

    def _fresh_rows(self, ids):
        """Library rows for `ids`, in the order given, minus anything whose file
        is gone (the library drive can be unplugged under a listing)."""
        rows = self._library.tracks_by_ids([int(i) for i in ids])
        return [r for r in rows if os.path.exists(r["path"])]

    @Slot("QVariantList")
    def queueTracks(self, ids):
        """Append tracks to the end of the queue — the right-click menu's "add
        to queue", and what queueAlbum is now built out of.

        An empty queue has no end to append to, so it becomes a plain play.
        `_orig_queue` (the pre-shuffle order, non-None only while shuffle is on)
        has to grow too: it is what unshuffling restores, so anything added
        while shuffled and NOT mirrored here silently disappears the moment the
        shuffle button is turned off."""
        fresh = self._fresh_rows(ids)
        if not fresh:
            return
        if not self._queue:
            self.playTracks([r["id"] for r in fresh], 0)
            return
        self._queue.extend(fresh)
        if self._orig_queue is not None:
            self._orig_queue.extend(fresh)
        for r in fresh:
            self._mpv.command("loadfile", r["path"], "append")
        self.queueChanged.emit()

    @Slot("QVariantList")
    def playNext(self, ids):
        """Insert tracks directly after the playing one, leaving it playing.

        With nothing playing there is no "next" to insert before — the menu
        disables the entry in that case, and this falls back to a plain play
        rather than dropping the request."""
        fresh = self._fresh_rows(ids)
        if not fresh:
            return
        if not self._queue or self._index < 0:
            self.playTracks([r["id"] for r in fresh], 0)
            return
        cur = self._queue[self._index]
        at = self._index + 1
        self._queue[at:at] = fresh
        if self._orig_queue is not None:
            try:
                oat = self._orig_queue.index(cur) + 1
            except ValueError:
                oat = len(self._orig_queue)
            self._orig_queue[oat:oat] = fresh
        self._resync_tail()          # rebuilds mpv's upcoming entries in place
        self.queueChanged.emit()

    @Slot("QVariantList")
    def removeFromQueue(self, indices):
        """Drop rows from the queue by their queue index (the queue's own
        right-click menu).

        Removing the PLAYING row is a real thing to ask for, so it is allowed
        and the row that slides into the gap starts playing — the alternative
        (refusing) would leave the one row you most want gone unremovable.
        Removing anything else must not interrupt playback: the index is
        shifted arithmetically rather than through `_set_index`, which would
        also zero the position readout and the play-count accumulator of a
        track that never stopped."""
        idxs = sorted({int(i) for i in indices if 0 <= int(i) < len(self._queue)},
                      reverse=True)
        if not idxs:
            return
        dropped = [self._queue[i] for i in idxs]
        removed_current = self._index in idxs
        for i in idxs:
            del self._queue[i]
        if self._orig_queue is not None:
            for t in dropped:
                try:
                    self._orig_queue.remove(t)
                except ValueError:
                    pass
        if not self._queue:
            self._orig_queue = None
            self._set_index(-1)
            try:
                self._mpv.command("stop")
            except Exception:
                pass
            self.queueChanged.emit()
            return
        if removed_current:
            self.queueChanged.emit()
            self._sync_mpv(min(idxs[-1], len(self._queue) - 1))
            return
        shift = sum(1 for i in idxs if i < self._index)
        if shift:
            self._index -= shift
            self.indexChanged.emit()
        self._resync_tail()
        self.queueChanged.emit()

    @Slot(str)
    def playArtistShuffled(self, artist):
        """Replace the queue with everything by an artist, in random order.

        The shuffle is baked into the queue rather than done by flipping
        `shuffle` on, so the order survives the mode being turned off and the
        user's own shuffle setting is left exactly as they had it."""
        rows = self._library.artist_tracks(artist)
        if not rows:
            return
        self.playTracks([r["id"] for r in self._shuffled(rows)], 0)

    @Slot(str)
    def playSmart(self, name):
        rows = self._library.smart_tracks(name)
        self.playTracks([r["id"] for r in rows], 0)

    @Slot(int)
    def jumpTo(self, idx):
        if 0 <= idx < len(self._queue):
            self._sync_mpv(idx)

    @Slot()
    def next(self):
        if self._index + 1 < len(self._queue):
            self.jumpTo(self._index + 1)
        elif self._loop == self.LOOP_ALL and self._queue:
            self.jumpTo(0)

    @Slot()
    def previous(self):
        # >3s in: restart the track (universal player convention); else go back.
        if self._position > 3.0:
            self.seek(0.0)
        elif self._index > 0:
            self.jumpTo(self._index - 1)
        else:
            self.seek(0.0)

    @Slot()
    def toggle(self):
        if self._index < 0 and self._queue:
            self.jumpTo(0)
            return
        try:
            self._mpv.pause = not self._mpv.pause
        except Exception:
            pass

    @Slot(float)
    def seek(self, secs):
        try:
            self._mpv.command("seek", secs, "absolute")
            self._seek_target = secs
            self._seek_at = time.monotonic()
            self._position = secs
            self.positionChanged.emit()
            self.seeked.emit(secs)
        except Exception:
            pass

    @Slot(float)
    def seekFrac(self, frac):
        if self._duration > 0:
            self.seek(max(0.0, min(1.0, frac)) * self._duration)

    @Slot(bool)
    def setShuffle(self, on):
        on = bool(on)
        if on == self._shuffle:
            return
        self._shuffle = on
        if on and self._queue:
            self._orig_queue = list(self._queue)
            self._queue = self._shuffled(self._queue, keep_first=self._index)
            self._set_index(0 if self._index >= 0 else -1)
            self._resync_tail()
        elif not on and self._orig_queue:
            cur = self.currentTrackDict()
            self._queue = self._orig_queue
            self._orig_queue = None
            if cur:
                try:
                    self._set_index(next(i for i, t in enumerate(self._queue)
                                         if t["id"] == cur["id"]))
                except StopIteration:
                    pass
            self._resync_tail()
        self.queueChanged.emit()
        self.shuffleChanged.emit()

    def _shuffled(self, queue, keep_first=-1):
        import random
        q = list(queue)
        first = []
        if 0 <= keep_first < len(q):
            first = [q.pop(keep_first)]
        random.shuffle(q)
        return first + q

    def _resync_tail(self):
        """Queue order changed under a playing track: rebuild mpv's upcoming
        entries without restarting the current file."""
        if self._index < 0:
            return
        try:
            # Drop everything after the playing entry, re-append the new tail.
            count = int(self._mpv.playlist_count or 1)
            pos = int(self._mpv.playlist_pos or 0)
            for i in range(count - 1, pos, -1):
                self._mpv.command("playlist-remove", i)
            for t in self._queue[self._index + 1:]:
                self._mpv.command("loadfile", t["path"], "append")
            self._mpv_base = self._index - pos
        except Exception:
            pass

    @Slot()
    def cycleLoop(self):
        self._loop = (self._loop + 1) % 3
        try:
            self._mpv["loop-file"] = "inf" if self._loop == self.LOOP_TRACK else "no"
        except Exception:
            pass
        self.loopChanged.emit()

    @Slot(int)
    def setLoop(self, mode):
        self._loop = mode % 3
        try:
            self._mpv["loop-file"] = "inf" if self._loop == self.LOOP_TRACK else "no"
        except Exception:
            pass
        self.loopChanged.emit()

    def queue_dicts(self):
        return self._queue

    # ---- session restore ----

    def save_state(self):
        self._prefs.set("queue", {
            "ids": [t["id"] for t in self._queue],
            "index": self._index, "position": self._position,
            "shuffle": self._shuffle, "loop": self._loop,
        })

    def restore_state(self, resume=True):
        """Bring back the saved queue. `resume=False` restores the queue and the
        shuffle/loop modes but does not touch mpv or the playhead — for a launch
        that is about to replace the queue with a file from the command line."""
        st = self._prefs.get("queue") or {}
        ids = st.get("ids") or []
        if not ids:
            return
        self._queue = self._library.tracks_by_ids([int(i) for i in ids])
        self._shuffle = bool(st.get("shuffle", False))
        self._loop = int(st.get("loop", 0))
        self.queueChanged.emit()
        self.shuffleChanged.emit()
        self.loopChanged.emit()
        idx = int(st.get("index", -1))
        if resume and 0 <= idx < len(self._queue):
            # Restore paused at the saved spot — don't blast audio on login.
            self._sync_mpv(idx, paused=True)
            pos = float(st.get("position", 0.0))
            if pos > 1.0:
                QTimer.singleShot(300, lambda: self.seek(pos))


# ---------------------------------------------------------------------------
# Lyrics
# ---------------------------------------------------------------------------

# Parsing/normalising/embedding all live in lyrics.py so tools/lyrics-sync.py
# can sweep the library with exactly the matching rules the app uses.
parse_lrc = lyricslib.parse_lrc
embedded_lyrics = lyricslib.read_embedded


class LyricsProvider(QObject):
    """Resolves lyrics for a track: DB cache → embedded tags → sidecar .lrc →
    LRCLIB, and EMBEDS what it finds back into the file. Runs on a worker
    thread (tag parse + network + tag write); results land back on the GUI
    thread via the ready signal. Negative results are cached too, with a 7-day
    retry window, so a library full of instrumentals doesn't hammer lrclib.net.

    Timestamped lyrics outrank everything. A plain-text lyrics tag is NOT
    allowed to end the search — roughly a fifth of this library has unsynced
    words sitting in its tags, and treating those as the answer is what kept
    the scrolling pane empty for them. Plain text is only used if the network
    has nothing synced either.

    Writeback is gated on the `lyricsEmbed` pref (default on). It goes through
    the same journal as the rating writer, and only ever touches the lyrics
    frame."""

    ready = Signal(int, "QVariantMap")  # trackId, {source, synced, lines, text}

    # Three distinct verdicts, because "we found nothing" and "this track has
    # no words" are NOT the same claim and only one of them is knowable:
    #
    #   instrumental       LRCLIB says the track is instrumental. Authoritative,
    #                      permanent, never re-asked.
    #   instrumental-user  You said so (a track can only be marked by hand from
    #                      the pane). Also permanent — for a library this niche
    #                      you are a better oracle than any online database.
    #   none               Nobody knows. Genuinely undetermined: the miss pile
    #                      holds both wordless ambient AND vocal tracks too
    #                      obscure to be indexed (Coaltar of the Deepers,
    #                      Astrid Sonne), and nothing in the tags can separate
    #                      them. Retried, but with a widening backoff.
    #
    # Nothing infers "instrumental" from titles or genre: an audit of this
    # library found only 163 titles with any marker at all, catching 11 of the
    # first 769 misses, and "Intro"/"Interlude"/"skit" turned out to have real
    # lyrics often enough to make guessing worse than admitting ignorance.
    INSTRUMENTAL = ("instrumental", "instrumental-user")

    RETRY_NONE_AFTER = 7 * 86400
    RETRY_MAX = 180 * 86400

    @classmethod
    def _retry_after(cls, attempts):
        """7d, 14d, 28d … capped. A track LRCLIB has never heard of is unlikely
        to appear next week, and this library has thousands of them."""
        return min(cls.RETRY_MAX, cls.RETRY_NONE_AFTER * (2 ** max(0, attempts - 1)))

    def __init__(self, prefs=None, parent=None):
        super().__init__(parent)
        self._prefs = prefs
        self._lrclib = lyricslib.Lrclib()
        self._jobs = []
        self._cv = threading.Condition()
        threading.Thread(target=self._loop, daemon=True).start()

    @Slot(int)
    def request(self, track_id):
        with self._cv:
            self._jobs.append(int(track_id))
            self._cv.notify()

    def _loop(self):
        con = open_db()
        while True:
            with self._cv:
                while not self._jobs:
                    self._cv.wait()
                tid = self._jobs.pop()   # newest first — user skipped ahead
                self._jobs.clear()       # older requests are stale
            try:
                self._resolve_one(con, tid)
            except Exception as e:
                print("lyrics:", e, flush=True)
                self.ready.emit(tid, {"source": "none", "synced": False,
                                      "lines": [], "text": ""})

    def _emit(self, tid, source, synced, text):
        lines = parse_lrc(text) if synced and text else []
        self.ready.emit(tid, {"source": source, "synced": bool(synced and lines),
                              "lines": lines, "text": text or ""})

    def _resolve_one(self, con, tid):
        row = con.execute("SELECT * FROM tracks WHERE id=?", (tid,)).fetchone()
        if row is None:
            self._emit(tid, "none", False, "")
            return
        cached = con.execute("SELECT * FROM lyrics WHERE track_id=?", (tid,)).fetchone()
        attempts = 0
        if cached is not None:
            src = cached["source"]
            if src in self.INSTRUMENTAL:
                self._emit(tid, src, False, "")      # settled — never re-asked
                return
            # A cached PLAIN result is not final: the network may since have
            # gained a synced version, and that is the whole point of the pane.
            if src != "none" and cached["synced"]:
                self._emit(tid, src, True, cached["body"])
                return
            attempts = (cached["attempts"] or 0) if "attempts" in cached.keys() else 0
            wait = self._retry_after(attempts) if src == "none" else self.RETRY_NONE_AFTER
            if time.time() - (cached["fetched_at"] or 0) < wait:
                if src == "none":
                    self._emit(tid, "none", False, "")
                    return
                self._emit(tid, src, False, cached["body"])
                return

        path = row["path"]
        exists = os.path.exists(path)
        text = synced = None
        source = "none"

        # 1. Timestamped lyrics already in the file win outright.
        emb_text, emb_synced = embedded_lyrics(path) if exists else (None, False)
        if emb_synced:
            text, synced, source = emb_text, True, "embedded"

        # 2. A sidecar .lrc beside the file (only trusted if actually stamped).
        if not text and exists:
            side = Path(path).with_suffix(".lrc")
            if side.exists():
                try:
                    body = side.read_text(encoding="utf-8", errors="replace")
                    if lyricslib.is_synced(body):
                        text, synced, source = body, True, "lrc"
                except OSError:
                    pass

        # 3. Ask LRCLIB — even when the file already holds PLAIN lyrics, since
        #    a synced version is a strict upgrade over them.
        if not text:
            got = self._fetch_lrclib(row)
            if got is None:                      # network failed: no verdict
                if emb_text:
                    self._emit(tid, "embedded", False, emb_text)
                else:
                    self._emit(tid, "none", False, "")
                return                           # nothing cached — retry later
            if got["instrumental"]:
                con.execute("INSERT OR REPLACE INTO lyrics"
                            " (track_id, source, synced, body, fetched_at)"
                            " VALUES (?,?,?,?,?)",
                            (tid, "instrumental", 0, "", time.time()))
                con.commit()
                self._emit(tid, "instrumental", False, "")
                return
            if got["text"] and got["synced"]:
                text, synced, source = got["text"], True, "lrclib"
                self._embed(row, text)           # put it in the file for good
            elif emb_text:                       # fall back on the file's plain text
                text, synced, source = emb_text, False, "embedded"
            elif got["text"]:
                text, synced, source = got["text"], False, "lrclib"

        # 4. Nothing anywhere, but the file had plain words after all.
        if not text and emb_text:
            text, synced, source = emb_text, False, "embedded"
        if not text:
            source = "none"

        con.execute("INSERT OR REPLACE INTO lyrics"
                    " (track_id, source, synced, body, fetched_at, attempts)"
                    " VALUES (?,?,?,?,?,?)",
                    (tid, source, 1 if synced else 0, text or "", time.time(),
                     attempts + 1 if source == "none" else 0))
        con.commit()
        self._emit(tid, source, synced, text)

    def _fetch_lrclib(self, row):
        """One LRCLIB resolution, or None if the NETWORK failed.

        The None is the point: a timeout must not be recorded as "this track
        has no lyrics", or a spell offline would poison the cache for a week."""
        try:
            return self._lrclib.lookup(row["artist"], row["title"],
                                       row["album"], row["duration"])
        except lyricslib.LookupError_ as e:
            print("lyrics: lrclib unreachable:", e, flush=True)
            return None

    def _embed(self, row, text):
        """Write freshly-fetched synced lyrics into the file itself, so they
        survive this DB and are visible to every other tool that reads tags.

        Journalled exactly like the rating writer, and skipped when the file
        is on an unmounted SSD or the pref is off."""
        if not self._prefs or not self._prefs.get("lyricsEmbed", True):
            return
        path = row["path"]
        if not os.path.exists(path):
            return
        entry = {"path": path, "lyrics": "synced", "chars": len(text),
                 "ts": time.time()}
        try:
            STATE.mkdir(parents=True, exist_ok=True)
            with open(STATE / "tagwrites.log", "a", encoding="utf-8") as f:
                f.write(json.dumps({**entry, "status": "writing"}) + "\n")
            lyricslib.write_embedded(path, text)
            with open(STATE / "tagwrites.log", "a", encoding="utf-8") as f:
                f.write(json.dumps({**entry, "status": "written"}) + "\n")
        except Exception as e:
            print("lyrics: embed failed:", path, e, flush=True)
            try:
                with open(STATE / "tagwrites.log", "a", encoding="utf-8") as f:
                    f.write(json.dumps({**entry, "status": f"error: {e}"}) + "\n")
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class DictListModel(QAbstractListModel):
    """A QML-friendly list-of-dicts model: every key of the row dicts becomes a
    role. Rows are replaced wholesale via setRows (cheap at our sizes)."""

    countChanged = Signal()

    def __init__(self, roles, parent=None):
        super().__init__(parent)
        self._role_names = {Qt.UserRole + i: r for i, r in enumerate(roles)}
        self._rows = []

    def roleNames(self):
        return {k: v.encode() for k, v in self._role_names.items()}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        return self._rows[index.row()].get(self._role_names.get(role, ""))

    def set_rows(self, rows):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
        self.countChanged.emit()

    def update_row(self, i, row):
        if 0 <= i < len(self._rows):
            self._rows[i] = row
            self.dataChanged.emit(self.index(i), self.index(i))

    @Property(int, notify=countChanged)
    def count(self):
        return len(self._rows)

    @Slot(int, result="QVariant")
    def get(self, i):
        return self._rows[i] if 0 <= i < len(self._rows) else {}


ALBUM_ROLES = ["albumId", "album", "artist", "year", "thumbPath"]
TRACK_ROLES = ["trackId", "title", "artist", "album", "albumId", "track", "disc",
               "duration", "rating", "favorite", "playCount", "available"]


def album_row(r):
    thumb = str(ART / r["thumb"]) if r.get("thumb") else ""
    return {"albumId": r["id"], "album": r["album"] or "",
            "artist": r["album_artist"] or "",
            "year": r.get("orig_year") or r.get("year") or 0,
            "thumbPath": thumb}


def track_row(r, check_exists=False):
    return {"trackId": r["id"], "title": r["title"] or "", "artist": r["artist"] or "",
            "album": r["album"] or "", "albumId": r.get("album_id") or 0,
            "track": r.get("track") or 0, "disc": r.get("disc") or 0,
            "duration": r.get("duration") or 0.0,
            "rating": -1.0 if r.get("rating") is None else float(r["rating"]),
            "favorite": bool(r.get("favorite")), "playCount": r.get("play_count") or 0,
            "available": os.path.exists(r["path"]) if check_exists else True}


class Bridge(QObject):
    """The QML-facing coordinator: owns the models and translates between the
    Library/Player and the views (which never see SQL or dicts-of-rows)."""

    scanStatus = Signal(str)
    scanRunning = Signal(bool)

    def __init__(self, library, player, lyrics, parent=None):
        super().__init__(parent)
        self._library = library
        self._player = player
        self._lyrics = lyrics
        self._sort = "orig_year"
        self._filter = ""
        self._album_rows = []

        self.albumsModel = DictListModel(ALBUM_ROLES, self)
        self.albumTracksModel = DictListModel(TRACK_ROLES, self)
        self.playlistModel = DictListModel(TRACK_ROLES, self)
        self.searchModel = DictListModel(TRACK_ROLES, self)
        self.queueModel = DictListModel(TRACK_ROLES, self)

        self._current_album = 0
        self._current_smart = ""

        library.changed.connect(self.refreshAlbums)
        library.changed.connect(self._refresh_current)
        library.trackChanged.connect(self._on_track_changed)
        player.queueChanged.connect(self._refresh_queue)
        library.scanProgress.connect(
            lambda done, total: self.scanStatus.emit(f"scanning {done}/{total}"))
        library.scanSummary.connect(self._on_summary)
        library.scanRunning.connect(self.scanRunning)

    def _on_summary(self, s):
        if not s.get("mounted", True):
            self.scanStatus.emit("library drive not mounted")
        else:
            self.scanStatus.emit("")

    @Slot()
    def rescan(self):
        self._library.rescan()

    # ---- albums grid ----

    @Slot()
    def refreshAlbums(self):
        self._album_rows = self._library.albums(self._sort)
        self._apply_album_filter()

    def _apply_album_filter(self):
        rows = self._album_rows
        f = self._filter.casefold().strip()
        if f:
            words = f.split()
            rows = [r for r in rows
                    if all(w in f'{(r["album"] or "").casefold()}\n'
                                f'{(r["album_artist"] or "").casefold()}' for w in words)]
        self.albumsModel.set_rows([album_row(r) for r in rows])

    @Slot(str)
    def setSort(self, sort):
        if sort in ("orig_year", "artist", "album") and sort != self._sort:
            self._sort = sort
            self.refreshAlbums()

    @Slot(str)
    def setAlbumFilter(self, text):
        self._filter = text or ""
        self._apply_album_filter()

    # ---- album detail ----

    @Slot(int)
    def openAlbum(self, album_id):
        self._current_album = album_id
        rows = self._library.album_tracks(album_id)
        self.albumTracksModel.set_rows([track_row(r, check_exists=True) for r in rows])

    @Slot(int, result="QVariant")
    def albumInfo(self, album_id):
        a = self._library.album(album_id)
        if not a:
            return {}
        return {**album_row(a),
                "fullArt": str(ART / a["full_art"]) if a.get("full_art") else "",
                "trackCount": len(self._library.album_tracks(album_id))}

    # ---- playlists / search ----

    @Slot(result="QVariantList")
    def smartNames(self):
        return self._library.smart_names()

    @Slot(str)
    def openSmart(self, name):
        self._current_smart = name
        rows = self._library.smart_tracks(name)
        self.playlistModel.set_rows([track_row(r, check_exists=True) for r in rows])

    @Slot(str)
    def search(self, text):
        rows = self._library.search(text)
        self.searchModel.set_rows([track_row(r, check_exists=True) for r in rows])

    # ---- play actions (ids resolved from whichever model the view used) ----

    @Slot("QVariant", int)
    def playFromModel(self, model, start):
        ids = [model.get(i)["trackId"] for i in range(model.count)]
        self._player.playTracks(ids, start)

    # ---- track writes (docs/DESIGN.md §10 — a drawn control has to work) ----
    #
    # QML's `Library` context property is THIS object, not the Library — the
    # views call `Library.setRating`/`setFavorite`/`setInstrumental` on the
    # Bridge, and until these existed each click raised
    # "TypeError: Property 'setRating' of object Bridge is not a function"
    # inside onClicked and died there: the stars and the heart were drawn,
    # hovered and clickable and wrote nothing. Anything QML calls on `Library`
    # has to be forwarded from here.

    @Slot(int, float)
    def setRating(self, track_id, rating):
        self._library.setRating(int(track_id), float(rating))

    @Slot(int, bool)
    def setFavorite(self, track_id, fav):
        self._library.setFavorite(int(track_id), bool(fav))

    @Slot(int, bool)
    def setInstrumental(self, track_id, yes):
        self._library.setInstrumental(int(track_id), bool(yes))

    # ---- reveal (the track menu's "open folder in filer") ----

    @Property(bool, constant=True)
    def canReveal(self):
        """Whether there is a filer to reveal into. The menu greys the entry
        out when there isn't, rather than offering an action that would do
        nothing at all (docs/DESIGN.md §7.2 — never offer an action that can
        silently fail). Resolved once: PATH does not change under a session."""
        return shutil.which("filer") is not None

    @Slot(int)
    def revealTrack(self, track_id):
        """Open the track's containing directory in filer.

        filer takes a DIRECTORY argument and has no select-this-file mode, so
        the menu entry says "open folder in filer" and not "show in filer" —
        the label promises exactly what happens."""
        rows = self._library.tracks_by_ids([int(track_id)])
        if not rows:
            return
        d = os.path.dirname(rows[0]["path"])
        exe = shutil.which("filer")
        if not exe or not os.path.isdir(d):
            return
        QProcess.startDetached(exe, [d])

    # ---- refresh plumbing ----

    def _refresh_current(self):
        if self._current_album:
            self.openAlbum(self._current_album)
        if self._current_smart:
            self.openSmart(self._current_smart)

    def _refresh_queue(self):
        self.queueModel.set_rows([track_row(t) for t in self._player.queue_dicts()])

    def _on_track_changed(self, track_id):
        # A rating/favourite/count changed: refresh any model showing the row.
        rows = self._library.tracks_by_ids([track_id])
        if not rows:
            return
        new = track_row(rows[0])
        for model in (self.albumTracksModel, self.playlistModel,
                      self.searchModel, self.queueModel):
            for i in range(model.count):
                if model.get(i).get("trackId") == track_id:
                    model.update_row(i, {**model.get(i), **new})
        # now-playing stars/heart: patch the player's own cached queue dict, not
        # just the models — a bare currentChanged re-reads the pre-write copy.
        self._player.apply_track_update(track_id, rows[0])

    @Slot(int)
    def requestLyrics(self, track_id):
        self._lyrics.request(track_id)


# ---------------------------------------------------------------------------
# MPRIS
# ---------------------------------------------------------------------------

def start_queue_server(player, app, lyrics=None):
    """Serve the play queue to the desktop panel's media widget.

    MPRIS carries the CURRENT track and nothing else — its TrackList interface
    is optional and Quickshell implements no client for it — so the panel's
    queue drawer needs its own channel. This is a line-based unix socket at
    $XDG_RUNTIME_DIR/player-queue.sock:

        server -> client   one JSON line, {"index": n, "tracks": [...],
                           "lyrics": {...}|null}, on connect and again on every
                           queue/index change
        client -> server   GOTO <index>
                           LYRICS <0|1>     — "I am showing a lyrics box"
                           OPEN <enc> [<enc> …]  — play these files now

    OPEN is not the panel's; it is how a SECOND launch hands its `%F` arguments
    to the player that is already running and exits (`handoff_paths`). It is
    answered with a snapshot line so the launcher knows it was taken rather than
    waiting out a timeout. Paths are percent-encoded because this protocol
    splits on whitespace and a filename may contain any byte but NUL and '/'.

    LYRICS is a SUBSCRIPTION, not a query, and it is opt-in for a reason.
    Resolving lyrics is not free: `LyricsProvider` reads tags, may hit
    lrclib.net, and (with the `lyricsEmbed` pref on, the default) writes what it
    finds back into the file. Doing that for every track the user plays merely
    because the panel exists would turn a widget nobody has opened into a
    library-wide sweep — `tools/lyrics-sync.py` is where that belongs. So the
    panel asks only while its drawer is actually showing the box, and the server
    resolves nothing until somebody has asked.

    Lyrics are pushed WHOLE, once per track — every timestamped line — and the
    panel follows them against its own MPRIS position. A per-line push would
    need a clock here and would put the panel's current line at the mercy of
    socket latency; the panel already knows where playback is.

    PUSH, not poll: the panel is drawing this at 60fps behind a slide animation
    and a file it had to re-read on a timer would be both later and more work.
    A stale socket file from a crash would make listen() fail, so it is removed
    first. That is safe precisely because this socket is also the singleton
    check: `handoff_paths` connects to it first, and a launch that gets an
    answer never reaches startup at all, so nothing that reaches here has a live
    player to steal the path from.

    Every failure here is caught and printed: the panel's queue drawer is a
    convenience, and nothing about it may take the music player down with it.
    """
    try:
        from PySide6.QtNetwork import QLocalServer, QLocalSocket
    except Exception as e:
        print("queue server: unavailable:", e, flush=True)
        return

    path = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "player-queue.sock")
    QLocalServer.removeServer(path)
    server = QLocalServer(app)
    if not server.listen(path):
        print("queue server: listen failed:", server.errorString(), flush=True)
        return

    clients = []
    # Which clients want lyrics, the track the cached answer belongs to, and the
    # answer itself. `lyr_tid` is the join key: a resolve is asynchronous, so by
    # the time one lands the user may already have skipped, and a payload sent
    # under the wrong track is the panel confidently scrolling another song's
    # words. Nothing is ever sent unless `lyr_tid` still equals what is playing.
    want = set()
    state = {"tid": None, "payload": None}

    def cur_id():
        t = player.currentTrackDict()
        return t.get("id") if t else None

    def snapshot(with_lyrics=False):
        # Only what the drawer draws. The panel has no library and no art cache,
        # so sending rows it cannot use would just be bytes per queue change.
        #
        # `with_lyrics` is PER CLIENT, because the subscription is. It read the
        # `want` set as a global "is anybody listening" first, which meant one
        # subscriber turned the lyrics on for every other connection — including
        # a panel predating this protocol, which would then be handed a few KB
        # of words it has no field for, on every push, forever.
        tracks = [{"title": t.get("title") or "",
                   "artist": t.get("artist") or "",
                   "dur": float(t.get("duration") or 0.0)}
                  for t in player.queue_dicts()]
        lyr = state["payload"] if (with_lyrics and state["tid"] == cur_id()) else None
        return (json.dumps({"index": player.index, "tracks": tracks,
                            "lyrics": lyr},
                           separators=(",", ":")) + "\n").encode()

    def resolve():
        """Ask for the current track's lyrics, if anyone is listening and we do
        not already hold them. Idempotent — the provider dedupes nothing, so the
        guard on `tid` is what keeps a burst of currentChanged to one job."""
        tid = cur_id()
        if not want or lyrics is None or tid is None:
            return
        if state["tid"] == tid:
            return
        state["tid"] = tid
        state["payload"] = None
        lyrics.request(tid)

    def on_lyrics(tid, result):
        if tid != state["tid"] or tid != cur_id():
            return
        # Mirror exactly what LyricsView draws, and nothing else: the verdicts
        # ("none", "instrumental") reach the panel as a payload with no words in
        # it, which is how it knows to collapse the column rather than draw an
        # empty box (docs/DESIGN.md 5.4 — permanent absence COLLAPSES).
        lines = [{"t": float(l.get("t") or 0.0), "line": l.get("line") or ""}
                 for l in (result.get("lines") or [])]
        state["payload"] = {"source": result.get("source") or "",
                            "synced": bool(result.get("synced")),
                            "lines": lines,
                            "text": result.get("text") or ""}
        push()

    def push():
        # At most two distinct lines per push — with lyrics and without — built
        # lazily, so a queue of hundreds is serialised once whatever the mix of
        # subscribers is.
        cache = {}
        for c in list(clients):
            if c.state() != QLocalSocket.LocalSocketState.ConnectedState:
                clients.remove(c)
                want.discard(c)
                continue
            k = c in want
            if k not in cache:
                cache[k] = snapshot(k)
            try:
                c.write(cache[k])
                c.flush()
            except Exception:
                pass

    def on_ready(c):
        while c.canReadLine():
            parts = bytes(c.readLine()).decode("utf-8", "replace").strip().split()
            if len(parts) == 2 and parts[0] == "GOTO":
                try:
                    player.jumpTo(int(parts[1]))
                except Exception as e:
                    print("queue server: bad GOTO:", e, flush=True)
            elif len(parts) >= 2 and parts[0] == "OPEN":
                # Percent-encoded because this protocol splits on whitespace and
                # a filename may hold any byte but NUL and '/'.
                try:
                    player.playPaths([urllib.parse.unquote(p) for p in parts[1:]])
                except Exception as e:
                    print("queue server: bad OPEN:", e, flush=True)
                # Answer, so the launcher that sent this knows it was taken and
                # can exit instead of guessing at a timeout.
                c.write(snapshot(c in want))
                c.flush()
            elif len(parts) == 2 and parts[0] == "LYRICS":
                on = parts[1] not in ("0", "false", "off")
                was = bool(want)
                want.add(c) if on else want.discard(c)
                if want and not was:
                    resolve()
                # Answer the subscription immediately: a client that has just
                # opened its box must not wait for the next track change to be
                # told there is nothing to draw.
                c.write(snapshot(c in want))
                c.flush()

    def on_gone(c):
        if c in clients:
            clients.remove(c)
        want.discard(c)

    def on_connection():
        while server.hasPendingConnections():
            c = server.nextPendingConnection()
            clients.append(c)
            c.readyRead.connect(lambda c=c: on_ready(c))
            c.disconnected.connect(lambda c=c: on_gone(c))
            # A fresh connection has not subscribed yet, by definition.
            c.write(snapshot(False))
            c.flush()

    def on_track():
        resolve()
        push()

    server.newConnection.connect(on_connection)
    # currentChanged as well as indexChanged: a track's own row can change under
    # a stationary index (a rating write patches the cached dict).
    player.queueChanged.connect(push)
    player.indexChanged.connect(push)
    player.currentChanged.connect(on_track)
    if lyrics is not None:
        lyrics.ready.connect(on_lyrics)
    print("queue server: listening on", path, flush=True)


def start_mpris(player, app):
    """Export org.mpris.MediaPlayer2.player via mpris_server so the panel's
    MediaPanel widget (Quickshell.Services.Mpris) controls this app. pydbus
    publishes on the GLib main context, which Qt's default Linux event
    dispatcher pumps inside app.exec() — no extra loop needed. Failure here
    (no mpris_server, no session bus) must never kill the player."""
    try:
        from mpris_server.adapters import MprisAdapter
        from mpris_server.events import EventAdapter
        from mpris_server.server import Server
        from mpris_server.base import PlayState
    except Exception as e:
        print("mpris: unavailable:", e, flush=True)
        return None

    class Adapter(MprisAdapter):
        def get_uri_schemes(self): return ["file"]
        def get_mime_types(self): return ["audio/flac", "audio/mpeg", "audio/mp4"]
        def can_quit(self): return True
        def quit(self): app.quit()
        def can_raise(self): return False
        def can_fullscreen(self): return False
        def can_control(self): return True
        def can_play(self): return player.queueLength > 0
        def can_pause(self): return True
        def can_seek(self): return True
        def can_go_next(self): return True
        def can_go_previous(self): return True

        def metadata(self):
            t = player.current
            meta = {
                "mpris:trackid": "/org/mpris/MediaPlayer2/player/track/%d" % (t.get("id") or 0),
                "mpris:length": int((t.get("duration") or 0) * 1_000_000),
                "xesam:title": t.get("title") or "",
                "xesam:artist": [t.get("artist") or ""],
                "xesam:album": t.get("album") or "",
            }
            if t.get("artPath"):
                meta["mpris:artUrl"] = "file://" + t["artPath"]
            return meta

        def get_current_position(self): return int(player.position * 1_000_000)
        def get_playstate(self):
            if player.playing:
                return PlayState.PLAYING
            return PlayState.PAUSED if player.index >= 0 else PlayState.STOPPED

        def play(self):
            if not player.playing:
                player.toggle()
        def pause(self):
            if player.playing:
                player.toggle()
        def resume(self): self.play()
        def stop(self): pass
        def next(self): player.next()
        def previous(self): player.previous()
        def seek(self, time, track_id=None): player.seek(time / 1_000_000)
        def open_uri(self, uri): pass

        # mpris_server's LoopStatus getter: is_repeating = any repeat at all,
        # is_playlist then picks Playlist over Track.
        def get_shuffle(self): return player.shuffle
        def set_shuffle(self, val): player.setShuffle(bool(val))
        def is_repeating(self): return player.loop != Player.LOOP_NONE
        def is_playlist(self): return player.loop == Player.LOOP_ALL
        def set_repeating(self, val):
            player.setLoop(Player.LOOP_TRACK if val else Player.LOOP_NONE)
        def set_loop_status(self, val):
            v = str(val).rsplit(".", 1)[-1].lower()
            player.setLoop({"none": 0, "track": 1, "playlist": 2}.get(v, 0))
        def get_rate(self): return 1.0
        def set_rate(self, val): pass
        def get_volume(self): return player.volume / 100.0
        def set_volume(self, val):
            player.volume = float(val) * 100.0

        def get_stream_title(self): return ""
        def get_art_url(self, track=None):
            t = player.current
            return ("file://" + t["artPath"]) if t.get("artPath") else ""

    try:
        server = Server(name="player", adapter=Adapter())
        # Playlists/TrackList are optional per the MPRIS spec and our adapter
        # doesn't implement them — publishing them broken makes every
        # GetAll(org.mpris.MediaPlayer2.Playlists) call traceback.
        server.interfaces = (server.root, server.player)
        events = EventAdapter(root=server.root, player=server.player)
        player.playingChanged.connect(events.on_playpause)
        # on_title emits the Metadata PropertiesChanged consumers actually
        # watch — without it the panel widget shows a stale track (it never
        # re-polls; busctl-style fresh reads hid this).
        player.currentChanged.connect(events.on_title)
        player.currentChanged.connect(events.on_playback)
        player.shuffleChanged.connect(events.on_options)
        player.loopChanged.connect(events.on_options)
        player.volumeChanged.connect(events.on_volume)
        player.seeked.connect(lambda s: events.on_seek(int(s * 1_000_000)))
        server.publish()
        return server
    except Exception as e:
        print("mpris: failed to publish:", e, flush=True)
        return None


# ---------------------------------------------------------------------------
# Opening a file from the command line
# ---------------------------------------------------------------------------
#
# `home/prog/player.nix` writes `Exec=…/bin/player %F`, so the desktop passes
# the double-clicked file(s) as plain arguments — and until this existed the app
# threw them away and opened the library at whatever it was last showing. That
# defect is the only reason `home/prog/mime-defaults.nix` held player back to
# nine of the fourteen extensions in AUDIO_EXTS (docs/agents/mime-defaults-audit.md).

QUEUE_SOCK = "player-queue.sock"


def paths_from_argv(argv):
    """The audio files named on the command line, absolute and de-duplicated.

    `%F` yields paths, but a caller that reads the desktop entry loosely may
    hand over `file://` URIs instead, so both are accepted. Anything starting
    with `-` is skipped: QGuiApplication owns the option namespace here (-style,
    -platform …) and this app defines no options of its own.

    Filtering on AUDIO_EXTS is deliberate — the MIME association is what makes
    this reachable, and honouring it for a `.pdf` somebody dropped on the icon
    would be the app claiming a type it never registered. Nothing is opened or
    stat'ed here; existence is settled by `Library.ids_for_paths`, which is also
    where the file is parsed."""
    out, seen = [], set()
    for a in argv:
        if a.startswith("-"):
            continue
        if a.startswith("file://"):
            a = urllib.parse.unquote(urllib.parse.urlparse(a).path)
        elif re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", a):
            continue  # some other scheme; not a local file, not ours to open
        p = os.path.abspath(os.path.expanduser(a))
        if os.path.splitext(p)[1].lower() not in AUDIO_EXTS:
            continue
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def handoff_paths(paths, timeout=2.0):
    """Give `paths` to a player that is already running; True if one took them.

    Two players must never run at once — they would fight over the MPRIS name,
    the queue socket and the same mpv-shaped hole in the audio device, and the
    user would hear both. Before this, a second launch did exactly that; the
    module used to claim the library lock prevented it, and there is no such
    lock (sqlite's WAL lets a second writer in after a 60s wait).

    The queue socket is the singleton check, because it already exists and is
    already only ever created by a live player. Plain stdlib sockets rather than
    QLocalSocket: this runs before QGuiApplication, on the path where the whole
    point is not to start Qt at all. A failure of ANY kind falls through to a
    normal startup — an unreachable socket means no player, which is exactly the
    case a normal startup handles."""
    if not paths:
        return False
    sock_path = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", QUEUE_SOCK)
    line = ("OPEN " + " ".join(urllib.parse.quote(p) for p in paths) + "\n").encode()
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(timeout)
        s.connect(sock_path)
        s.sendall(line)
        # The server answers OPEN with a snapshot line. It also writes one on
        # connect, so wait for the SECOND newline — the first proves only that
        # something is listening, not that it understood the verb.
        buf = b""
        while buf.count(b"\n") < 2:
            chunk = s.recv(65536)
            if not chunk:
                return False
            buf += chunk
        return True
    except OSError:
        return False
    finally:
        s.close()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    open_paths = paths_from_argv(sys.argv[1:])
    if handoff_paths(open_paths):
        return

    app = QGuiApplication(sys.argv)
    app.setApplicationName("player")
    app.setDesktopFileName("player")

    prefs = Prefs()
    tagwriter = TagWriter(prefs)
    library = Library(tagwriter)
    player = Player(library, prefs)
    lyrics = LyricsProvider(prefs)
    bridge = Bridge(library, player, lyrics)
    titlebar = Titlebar()
    palette = Palette(PANEL_THEME)
    style = DeskStyle()

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    # air (the MacBook, OS hostname "book") has a much smaller screen than
    # top: the QML lowers the window minimums and caps the now-playing cover
    # there. Keyed on hostname, not the launcher, so a bare `python3 main.py`
    # on air behaves the same as going through air-launch.sh.
    ctx.setContextProperty("OnAir", socket.gethostname().split(".")[0] == "book")
    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("DeskStyle", style)
    ctx.setContextProperty("Titlebar", titlebar)
    ctx.setContextProperty("Prefs", prefs)
    ctx.setContextProperty("Library", bridge)
    ctx.setContextProperty("Player", player)
    ctx.setContextProperty("Lyrics", lyrics)
    ctx.setContextProperty("AlbumsModel", bridge.albumsModel)
    ctx.setContextProperty("AlbumTracksModel", bridge.albumTracksModel)
    ctx.setContextProperty("PlaylistModel", bridge.playlistModel)
    ctx.setContextProperty("SearchModel", bridge.searchModel)
    ctx.setContextProperty("QueueModel", bridge.queueModel)

    theme_comp = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "theme" / "Theme.qml")))
    theme = theme_comp.create()
    if theme is None:
        print("Theme.qml failed:\n" + theme_comp.errorString(), file=sys.stderr)
        sys.exit(1)
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)

    engine.load(QUrl.fromLocalFile(str(QML / "Main.qml")))
    if not engine.rootObjects():
        sys.exit(1)

    bridge.refreshAlbums()
    # With files on the command line, restore the SESSION (shuffle, loop, the
    # saved queue) but not the playhead: `restore_state` re-syncs mpv and posts
    # a delayed seek to the saved position, which would land 300 ms later on the
    # queue playPaths has replaced by then and seek the wrong track.
    player.restore_state(resume=not open_paths)
    if open_paths:
        player.playPaths(open_paths)
    start_mpris(player, app)
    start_queue_server(player, app, lyrics)
    QTimer.singleShot(400, library.rescan)  # incremental; UI is already up

    app.aboutToQuit.connect(player.save_state)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
