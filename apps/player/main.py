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
                            Slot, Property, QFileSystemWatcher, QMetaObject,
                            Q_ARG)
from PySide6.QtCore import QAbstractListModel, QModelIndex, QProcessEnvironment
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QImage
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
# Imported for its side effect as much as for the name: without QtQuick
# loaded, PySide has no binding for the `Window` QML root and wraps it as a
# bare QWindow — which has no `grabWindow`, so `--selftest`'s Hyprland shot
# failed, and re-wrapping the pointer could not fix it (shiboken caches one
# wrapper per pointer and the first one wins).
from PySide6.QtQuick import QQuickWindow  # noqa: F401

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"

sys.path.insert(0, str(HERE.parent / "pylib"))
from vtbclient import VtbClient  # noqa: E402  (needs the path insert above)
from deskstyle import DeskStyle  # noqa: E402  (pylib; the desktop-wide font setting)
from kdetheme import theme_source, is_plasma  # noqa: E402  (pylib; the KDE global theme in a Plasma session)
import kdeshell  # noqa: E402  (pylib; the Plasma session's real QtWidgets window)
from glyphs import Glyphs  # noqa: E402  (pylib; docs/DESIGN.md 2.3 display-site px())

import atomicsave  # noqa: E402  (sibling module; also used by lyrics.py)
import lyrics as lyricslib  # noqa: E402  (sibling module; also used by tools/)
from scrobble import Scrobbler  # noqa: E402  (sibling module; Last.fm, off the GUI thread)
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

# Filesystems where a read can block for hundreds of milliseconds. book streams
# the whole library from top over SMB, so this is its normal case.
REMOTE_FSTYPES = frozenset({"cifs", "smb3", "nfs", "nfs4", "fuse.sshfs",
                            "fuse.rclone", "sshfs", "afs", "9p"})


def library_is_remote(root=None):
    """Is LIBRARY_ROOT on a network filesystem? Longest mount-point prefix
    wins, and the LAST matching line wins with it: the share is an
    x-systemd.automount, so mountinfo carries both the autofs trigger and the
    cifs mount at the same path, in that order."""
    root = os.path.realpath(str(root or LIBRARY_ROOT))
    best, fstype = -1, ""
    try:
        with open("/proc/self/mountinfo") as f:
            for line in f:
                parts = line.split(" - ")
                if len(parts) < 2:
                    continue
                mp = parts[0].split()[4]
                if (root == mp or root.startswith(mp.rstrip("/") + "/")) \
                        and len(mp) >= best:
                    best, fstype = len(mp), parts[1].split()[0]
    except OSError:
        return False
    return fstype in REMOTE_FSTYPES


def library_mounted(root=None):
    """Is the library root really there — mounted, and with something in it?

    `is_dir()` alone is not enough: an unmounted mountpoint can linger as an
    empty directory, and anything that PRUNES on a missing file would then
    delete the whole library (ratings and all). One scandir, first entry only.
    """
    try:
        with os.scandir(str(root or LIBRARY_ROOT)) as it:
            return next(it, None) is not None
    except OSError:
        return False


_REMOTE_LIBRARY = None


def library_is_remote_cached():
    """`library_is_remote()` memoised for the process. The mount type does not
    change under a session, and the answer gates every per-track existence
    stat off the GUI thread — on book each `os.path.exists` on the cifs mount
    is 37ms at the median and up to 460ms cold (measured 2026-08-19), so a
    15-track album open or a play-all used to freeze the UI for whole seconds.
    On a network library the DB is authoritative (the whole library lives on
    top and does not vanish mid-session, unlike the local-USB case the checks
    were written for), and mpv skips a genuinely-missing file at play time, so
    the stat is pure cost there and is skipped."""
    global _REMOTE_LIBRARY
    if _REMOTE_LIBRARY is None:
        _REMOTE_LIBRARY = library_is_remote()
    return _REMOTE_LIBRARY

# Formats the ReplayGain scanner (tools/replaygain.py via `rsgain`) cannot tag
# — DSD, Musepack, TTA. They keep the player's median-gain fallback at play
# time. Single source of truth; the scan tool imports this too, so the auto
# hook and the scanner agree on what is worth scanning.
RG_UNSUPPORTED_EXTS = frozenset({".dsf", ".dff", ".mpc", ".tta"})

DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "player"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "player"
STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "player"
ART = CACHE / "art"
DB_PATH = DATA / "library.db"

# Where slskd drops completed downloads (home/prog/slskd.nix). They are not in
# the library root, so the player scan never sees them until tools/player-add.py
# moves them into aud/ and rescans — see AutoScanner, which makes that step
# automatic so a freshly downloaded track lands in "recently added" without a
# manual rescan. top-only in practice (air has no slskd), but guarded on
# existence so the same module is inert where the dir is absent.
SLSKD_DOWNLOADS = Path(os.path.expanduser("~/.local/share/slskd/downloads"))

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
    # THE PLASMA FACE'S ONLY NOTIFICATION THAT THE CHROME CHANGED. In that
    # session the vtb socket below is dead, but `Root.qml` still pushes its
    # whole button table through `setButtons` on every state change — so this
    # signal is what tells `kdeshell.bind_chrome` to re-read it. Without it the
    # menubar and both toolbars were built once and then FROZE: play never
    # became pause, the favourite never lit, and prev/play/next stayed greyed
    # for the whole session because they had been disabled by an empty queue at
    # startup. Nothing failed and nothing warned; the chrome was simply inert.
    buttonsChanged = Signal()

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
        self.buttonsChanged.emit()

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

        # A re-parsed file can carry NEW embedded art at the SAME path, and
        # _art_pass alone never sees that: it re-donates only when an album has
        # no thumb or its donor path is DEAD, so a cover replaced in place left
        # the grid frozen on the old one for ever (Millie & Andrea, 2026-08-25).
        # Anything whose tags we just re-read gives its album's cached art up.
        for i in range(0, len(todo), 500):
            chunk = todo[i:i + 500]
            con.execute(
                "UPDATE albums SET art_src=NULL, thumb=NULL, full_art=NULL "
                "WHERE id IN (SELECT DISTINCT album_id FROM tracks "
                " WHERE album_id IS NOT NULL AND path IN (%s))"
                % ",".join("?" * len(chunk)), chunk)
        if todo:
            con.commit()

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
        shared root lie) then folder art. Covers albums with no cached thumb
        AND albums whose cached art's donor path is dead (a file move orphans
        the donor; the thumb stays frozen from it). The donor is the MAJORITY
        embedded art among the album's tracks, so one stray track cannot bleed
        another album's cover in (the Tabu box set bug). An album with no
        current art gets its stale art cleared rather than left wrong."""
        rows = con.execute(
            "SELECT a.id, a.thumb, a.art_src FROM albums a").fetchall()

        def dead(src):
            p = src[9:] if src.startswith("embedded:") else (
                src[5:] if src.startswith("file:") else None)
            return p is not None and not os.path.exists(p)

        targets = [r for r in rows if r["thumb"] is None or dead(r["art_src"])]
        n = 0
        for r in targets:
            aid = r["id"]
            donors = con.execute(
                "SELECT path FROM tracks WHERE album_id=? AND has_art=1",
                (aid,)).fetchall()
            counts, first = {}, {}
            for d in donors:
                data = embedded_art(d["path"])
                if not data:
                    continue
                h = hashlib.sha1(data).hexdigest()
                counts[h] = counts.get(h, 0) + 1
                first.setdefault(h, (data, d["path"]))
            thumb = full = src = None
            if counts:
                h, _ = max(counts.items(), key=lambda kv: kv[1])
                data, p = first[h]
                src = "embedded:" + p
                thumb, full = cache_art(
                    data=data, src_id=hashlib.sha1(data).hexdigest())
            if not thumb:
                anyt = con.execute(
                    "SELECT path FROM tracks WHERE album_id=? LIMIT 1",
                    (aid,)).fetchone()
                if anyt:
                    fa = folder_art(os.path.dirname(anyt["path"]))
                    if fa:
                        src = "file:" + fa
                        thumb, full = cache_art(src_path=fa)
            if thumb:
                con.execute("UPDATE albums SET art_src=?, thumb=?, full_art=? WHERE id=?",
                            (src, thumb, full, aid))
                n += 1
            elif r["thumb"] is not None:
                # stale art and nothing to replace it with: show no art
                # honestly instead of a frozen thumb from a dead donor
                con.execute(
                    "UPDATE albums SET art_src=NULL, thumb=NULL, full_art=NULL WHERE id=?",
                    (aid,))
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


# ---------------------------------------------------------------------------
# Smart playlists — a rule language the user owns
# ---------------------------------------------------------------------------
#
# These were seven hard-coded (name, SQL, params) tuples until 2026-08-07, with
# a comment saying "one tuple to add another" — true for an agent editing this
# file, useless to the person using the app. They are now RULES: a spec is
# plain JSON, the SQL is built from it here, and the built-in seven are just
# the seed of the user's own file, editable and deletable like anything they
# add. Everything is re-queried on open, so a list is always live — there is no
# stored membership to go stale.
#
# Three rules for anything added below:
#
#   * A VALUE NEVER REACHES THE SQL AS TEXT. Every rule contributes a `?` and a
#     bound parameter; only the ORDER BY and the LIMIT are interpolated, and
#     both come from this file's own tables (a sort key is looked up, the limit
#     goes through int()). The specs are user-editable JSON, so treating one as
#     SQL would be an injection into the library's own database.
#   * A SPEC THAT MAKES NO SENSE IS SKIPPED, NEVER RAISED. The file can be
#     hand-edited, and can arrive from a future version of this app through the
#     docs/state syncs; an unknown field, op or sort key drops that one rule
#     rather than taking the playlists view down.
#   * TEXT COMPARES THROUGH cfold(), NOT lower(). SQLite's lower() is ASCII
#     only, and a good slice of this library is Japanese — Library registers
#     `cfold` (Python's str.casefold) on its connection for exactly this.

# Rating is stored FMPS 0..1 and shown as 0..5 stars. The epsilon is what makes
# "at least 4 stars" mean rating >= 0.79 rather than >= 0.8: ratings written by
# other taggers (fooyin, Strawberry) land on 0.79/0.99, and those files are the
# reason the old hard-coded thresholds were 0.79 and 0.99 in the first place.
_STAR_EPS = 0.01
_STAR_NEAR = 0.05          # "is 4 stars" — a quarter-star either side

# key → (label, kind). The kind picks the operators and how a value is read.
SMART_FIELDS = [
    ("anytext",      "any text",     "text"),
    ("title",        "title",        "text"),
    ("artist",       "artist",       "text"),
    ("album",        "album",        "text"),
    ("album_artist", "album artist", "text"),
    ("genre",        "genre",        "text"),
    ("codec",        "format",       "text"),
    ("rating",       "rating",       "stars"),
    ("favorite",     "liked",        "bool"),
    ("has_art",      "has cover",    "bool"),
    ("play_count",   "play count",   "count"),
    ("year",         "year",         "count"),
    ("duration",     "length",       "minutes"),
    ("added_at",     "date added",   "date"),
    ("last_played",  "last played",  "date"),
]
_FIELD_KIND = {k: kind for k, _, kind in SMART_FIELDS}

# The SQL expression a field compares against, where it is not just the column.
_FIELD_EXPR = {"year": "COALESCE(orig_year, year)"}

# The searchable haystack behind the "any text" field — the same four tags the
# header search box matches on, so a rule reads like typing in that box does.
_ANYTEXT = "(cfold(title)||' '||cfold(artist)||' '||cfold(album)||' '||cfold(album_artist))"

SMART_OPS = {
    "text":    ["contains", "does not contain", "is", "is not",
                "starts with", "ends with", "is set", "is unset"],
    "stars":   ["at least", "at most", "is", "is not", "is set", "is unset"],
    "count":   ["at least", "at most", "is", "is not"],
    "minutes": ["at least", "at most"],
    "bool":    ["is"],
    "date":    ["in the last", "not in the last", "is set", "is unset"],
}
# Operators that take no value at all — the editor draws no value box for these.
SMART_NULLARY_OPS = ("is set", "is unset")

# key → (label, ORDER BY columns). `desc` on the spec flips every column; the
# tie-breakers keep a one-column sort deterministic between two runs.
_TIEBREAK = ["artist", "album", "COALESCE(disc, 1)", "track"]
SMART_SORTS = [
    ("artist",   "artist",      ["artist", "album", "COALESCE(disc, 1)", "track"]),
    ("album",    "album",       ["album", "COALESCE(disc, 1)", "track"]),
    ("title",    "title",       ["title"]),
    ("year",     "year",        ["COALESCE(orig_year, year)"] + _TIEBREAK),
    ("rating",   "rating",      ["rating"] + _TIEBREAK),
    ("plays",    "play count",  ["play_count"] + _TIEBREAK),
    ("added",    "date added",  ["added_at"] + _TIEBREAK),
    ("played",   "last played", ["last_played"] + _TIEBREAK),
    ("duration", "length",      ["duration"] + _TIEBREAK),
    ("random",   "random",      ["RANDOM()"]),
]
_SORT_COLS = {k: cols for k, _, cols in SMART_SORTS}

DEFAULT_SMART_LISTS = [
    {"name": "5 starred", "match": "all", "sort": "artist",
     "rules": [{"field": "rating", "op": "at least", "value": 5}]},
    {"name": "4+ starred", "match": "all", "sort": "rating", "desc": True,
     "rules": [{"field": "rating", "op": "at least", "value": 4}]},
    # HIS request, 2026-08-07: the 4+ star list WITH the liked tracks in it —
    # so `any`, a union, not an intersection. Flipping it to `all` in the
    # editor turns it into "4+ stars AND liked", which is the whole point of
    # the rules being editable.
    {"name": "4+ starred & liked", "match": "any", "sort": "rating", "desc": True,
     "rules": [{"field": "rating", "op": "at least", "value": 4},
               {"field": "favorite", "op": "is", "value": True}]},
    {"name": "favorites", "match": "all", "sort": "artist",
     "rules": [{"field": "favorite", "op": "is", "value": True}]},
    {"name": "recently added", "match": "all", "sort": "added", "desc": True,
     "limit": 250, "rules": []},
    {"name": "most played", "match": "all", "sort": "plays", "desc": True,
     "limit": 250, "rules": [{"field": "play_count", "op": "at least", "value": 1}]},
    {"name": "recently played", "match": "all", "sort": "played", "desc": True,
     "limit": 250, "rules": [{"field": "last_played", "op": "is set"}]},
    {"name": "unrated", "match": "all", "sort": "artist",
     "rules": [{"field": "rating", "op": "is unset"}]},
]


#: ---- the finder's field filters ------------------------------------------
#: `genre:shoegaze`, `year:1997`, `year:1990-1999`, `year:>2010`, `year:<1980`.
#: Everything else in the box is free text and matches title/artist/album as it
#: always did, so an ordinary search is unchanged and a filter is opt-in by
#: typing a field name (his, 2026-08-23: search and filter by genre and year).
#:
#: Deliberately NOT a second query language: the same two fields the smart
#: playlists already own (`SMART_FIELDS`), spelled the way a person types into
#: a search box. A smart list is for a rule he keeps; this is for a question he
#: asks once. `year` is COALESCE(orig_year, year) here exactly as it is there
#: (`_FIELD_EXPR`), so a 2011 reissue of a 1979 record answers to 1979 in both.
_QUERY_TERM = re.compile(r'(genre|year):("[^"]*"|\S*)', re.IGNORECASE)
_YEAR_RANGE = re.compile(r'^(\d{4})?\s*(?:-|\.\.)\s*(\d{4})?$')


def parse_query(text):
    """`text` -> (words, genres, year_lo, year_hi).

    `words` are the free-text terms, casefolded, as before. `genres` are
    casefolded substrings, ALL of which must be present in a track's genre tag
    (so `genre:post genre:rock` narrows). The year bounds are inclusive and
    either may be None for an open end. A field with no value (`genre:`, a
    half-typed query) contributes nothing rather than matching nothing —
    filtering to zero rows on every keystroke while he types is worse than
    ignoring an incomplete term."""
    text = (text or "").strip()
    genres, lo, hi = [], None, None
    def take(m):
        field = m.group(1).lower()
        val = m.group(2).strip('"').strip()
        if not val:
            return " "
        if field == "genre":
            genres.append(val.casefold())
            return " "
        nonlocal lo, hi
        rng = _YEAR_RANGE.match(val)
        if rng and (rng.group(1) or rng.group(2)):
            lo = int(rng.group(1)) if rng.group(1) else None
            hi = int(rng.group(2)) if rng.group(2) else None
        elif val.startswith(">") and val[1:].isdigit():
            lo = int(val[1:]) + 1
        elif val.startswith(">=") and val[2:].isdigit():
            lo = int(val[2:])
        elif val.startswith("<") and val[1:].isdigit():
            hi = int(val[1:]) - 1
        elif val.startswith("<=") and val[2:].isdigit():
            hi = int(val[2:])
        elif val.isdigit():
            lo = hi = int(val)
        return " "
    # `>=` / `<=` are two characters, so test them before the one-character
    # forms above; simplest is to normalise here rather than order the branches.
    text = text.replace(">= ", ">=").replace("<= ", "<=")
    rest = _QUERY_TERM.sub(take, text)
    return rest.casefold().split(), genres, lo, hi


def query_has_filter(text):
    """Does this query carry a field filter at all? What the results header
    uses to say why nothing matched."""
    _, g, lo, hi = parse_query(text)
    return bool(g) or lo is not None or hi is not None


def year_in(value, lo, hi):
    """Inclusive bounds against a possibly-missing year. A track with no year
    matches only an unbounded query — a missing tag is not a 0."""
    if lo is None and hi is None:
        return True
    if not value:
        return False
    return (lo is None or value >= lo) and (hi is None or value <= hi)


def _cfold(s):
    """SQLite's `cfold` — Unicode-correct casefolding, registered by Library.

    NULL folds to '' rather than back to NULL, so "does not contain" is TRUE
    for a track with no genre tag instead of dropping it on a NULL comparison.
    """
    return "" if s is None else str(s).casefold()


def _like_escape(s):
    """A user's literal text, safe inside a LIKE pattern (ESCAPE '\\')."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _rule_sql(rule):
    """One rule → (sql fragment, params), or None if it cannot be honoured.

    None is not an error: specs are user-editable JSON and sync between the two
    machines, so an unreadable rule is dropped and the rest of the list stands.
    """
    if not isinstance(rule, dict):
        return None
    key = rule.get("field")
    op = rule.get("op")
    kind = _FIELD_KIND.get(key)
    if kind is None or op not in SMART_OPS.get(kind, ()):
        return None
    col = _FIELD_EXPR.get(key, key)
    val = rule.get("value")

    if kind == "text":
        expr = _ANYTEXT if key == "anytext" else f"cfold({col})"
        if op == "is set":
            return f"{expr} <> ''", ()
        if op == "is unset":
            return f"{expr} = ''", ()
        text = _cfold(val)
        if op == "is":
            return f"{expr} = ?", (text,)
        if op == "is not":
            return f"{expr} <> ?", (text,)
        pat = {"contains": "%{}%", "does not contain": "%{}%",
               "starts with": "{}%", "ends with": "%{}"}[op].format(_like_escape(text))
        neg = " NOT" if op == "does not contain" else ""
        return f"{expr}{neg} LIKE ? ESCAPE '\\'", (pat,)

    if kind == "bool":
        # `has_art`/`favorite` are 0/1 INTEGER columns that default to 0, but a
        # row written before the column existed can still be NULL.
        return f"IFNULL({col}, 0) = ?", (1 if val else 0,)

    if kind == "date":
        if op == "is set":
            return f"{col} IS NOT NULL", ()
        if op == "is unset":
            return f"{col} IS NULL", ()
        cutoff = time.time() - max(0.0, _num(val)) * 86400.0
        if op == "in the last":
            return f"{col} >= ?", (cutoff,)
        return f"IFNULL({col}, 0) < ?", (cutoff,)   # not in the last

    # Numeric kinds. `stars` is the user's 0..5 over the column's FMPS 0..1;
    # `minutes` is the user's minutes over the column's seconds.
    if op == "is set":
        return f"{col} IS NOT NULL", ()
    if op == "is unset":
        return f"{col} IS NULL", ()
    n = _num(val)
    if kind == "stars":
        n = max(0.0, min(5.0, n)) / 5.0
        lo, hi, near = n - _STAR_EPS, n + _STAR_EPS, _STAR_NEAR / 5.0
    elif kind == "minutes":
        n = n * 60.0
        lo = hi = n
        near = 30.0                      # "is 4 minutes" — within half a minute
    else:
        lo = hi = n
        near = 0.5
    if op == "at least":
        return f"{col} >= ?", (lo,)
    if op == "at most":
        return f"{col} <= ?", (hi,)
    if op == "is":
        return f"ABS({col} - ?) <= ?", (n, near)
    # "is not" — an unset column is not that value either, so it stays in.
    return f"({col} IS NULL OR ABS({col} - ?) > ?)", (n, near)


def normalize_smart(spec, name=""):
    """A stored/incoming spec, cleaned into the exact shape everything reads.

    Every consumer (SQL builder, editor, the JSON file) goes through this, so
    there is one definition of a valid spec and no caller has to defend itself.
    """
    spec = spec if isinstance(spec, dict) else {}
    rules = []
    for r in (spec.get("rules") if isinstance(spec.get("rules"), list) else []):
        if not isinstance(r, dict):
            continue
        key = r.get("field")
        kind = _FIELD_KIND.get(key)
        if kind is None:
            continue
        op = r.get("op")
        if op not in SMART_OPS[kind]:
            op = SMART_OPS[kind][0]
        out = {"field": key, "op": op}
        if op not in SMART_NULLARY_OPS:
            v = r.get("value")
            if kind == "text":
                out["value"] = "" if v is None else str(v)
            elif kind == "bool":
                out["value"] = bool(v)
            else:
                out["value"] = _num(v)
        rules.append(out)
    nm = str(spec.get("name") or name or "").strip() or "new playlist"
    return {"name": nm[:64],
            "match": "any" if spec.get("match") == "any" else "all",
            "rules": rules,
            "sort": spec.get("sort") if spec.get("sort") in _SORT_COLS else "artist",
            "desc": bool(spec.get("desc")),
            "limit": max(0, min(100000, int(_num(spec.get("limit"), 0))))}


def smart_sql(spec, select="*"):
    """A normalized spec → (SQL, params) returning full track rows, ordered."""
    frags, params = [], []
    for r in spec.get("rules") or []:
        got = _rule_sql(r)
        if got:
            frags.append("(" + got[0] + ")")
            params.extend(got[1])
    joiner = " OR " if spec.get("match") == "any" else " AND "
    where = (" WHERE " + joiner.join(frags)) if frags else ""
    # `desc` flips the FIRST column only; the tie-breakers stay ascending. That
    # is the difference between "best rated first, then alphabetically" and
    # "best rated first, then backwards alphabetically" — and it is what the
    # hard-coded "4+ starred" did (`ORDER BY rating DESC, artist, album`).
    cols = list(_SORT_COLS.get(spec.get("sort"), _SORT_COLS["artist"]))
    if spec.get("desc"):
        cols[0] += " DESC"
    order = " ORDER BY " + ", ".join(cols)
    limit = int(spec.get("limit") or 0)
    return (f"SELECT {select} FROM tracks{where}{order}"
            + (f" LIMIT {limit}" if limit > 0 else ""), tuple(params))


class SmartLists:
    """The user's smart playlists, persisted whole to
    `$XDG_STATE_HOME/player/smartlists.json`.

    Seeded from DEFAULT_SMART_LISTS on a machine that has never had one, and
    the built-ins carry no flag afterwards: once seeded they are the user's,
    editable and deletable like any list they wrote. `restore_defaults()`
    puts back only the ones whose NAME is missing, so it can never overwrite an
    edit made to a list that is still there.
    """

    def __init__(self, path=None):
        self._path = Path(path) if path else (STATE / "smartlists.json")
        self._lists = []
        self._load()

    # ---- store ----

    def _load(self):
        raw = None
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            pass
        got = raw.get("lists") if isinstance(raw, dict) else None
        if not isinstance(got, list):
            self._lists = [normalize_smart(s) for s in DEFAULT_SMART_LISTS]
            self._write()
            return
        for s in got:
            if not isinstance(s, dict):
                continue          # a hand edit or a bad merge; not a playlist
            spec = normalize_smart(s)
            spec["name"] = self._unique(spec["name"])
            self._lists.append(spec)

    def _write(self):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"version": 1, "lists": self._lists}, indent=1),
                           encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as e:
            print("smartlists: save failed:", e, flush=True)

    def _unique(self, name, skip=-1):
        """`name`, suffixed until no OTHER list holds it. Names are the key the
        view, the queue's 'play all' and prefs all address a list by."""
        taken = {s["name"] for i, s in enumerate(self._lists) if i != skip}
        if name not in taken:
            return name
        n = 2
        while f"{name} {n}" in taken:
            n += 1
        return f"{name} {n}"

    # ---- read ----

    def names(self):
        return [s["name"] for s in self._lists]

    def specs(self):
        return [dict(s) for s in self._lists]

    def get(self, name):
        for s in self._lists:
            if s["name"] == name:
                return dict(s)
        return None

    def _index(self, name):
        for i, s in enumerate(self._lists):
            if s["name"] == name:
                return i
        return -1

    # ---- write ----

    def save(self, spec, old_name=""):
        """Create (old_name "") or replace (old_name = the list being edited);
        returns the name it was actually stored under.

        A NEW list whose name is taken is suffixed, never merged into the one
        already there — §10.2, never silently clobber. Only `old_name` says
        "replace this", and the name it carries is the one the view addresses
        the list by.
        """
        spec = normalize_smart(spec)
        i = self._index(old_name) if old_name else -1
        spec["name"] = self._unique(spec["name"], skip=i)
        if i >= 0:
            self._lists[i] = spec
        else:
            self._lists.append(spec)
        self._write()
        return spec["name"]

    def remove(self, name):
        i = self._index(name)
        if i < 0:
            return False
        del self._lists[i]
        self._write()
        return True

    def duplicate(self, name):
        i = self._index(name)
        if i < 0:
            return ""
        spec = dict(self._lists[i])
        spec["name"] = self._unique(spec["name"] + " copy")
        self._lists.insert(i + 1, spec)
        self._write()
        return spec["name"]

    def restore_defaults(self):
        """Put back every built-in the user has deleted, keeping their own and
        keeping any edit to a built-in they still have. Returns how many came
        back, so the caller can say nothing happened rather than nothing
        appearing to."""
        have = set(self.names())
        added = [normalize_smart(s) for s in DEFAULT_SMART_LISTS
                 if s["name"] not in have]
        if added:
            self._lists.extend(added)
            self._write()
        return len(added)


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
        self._scrobbler = None      # set by main.py; None everywhere else
        self._con = open_db()
        # Unicode-correct casefolding for the smart playlists' text rules.
        # SQLite's own lower()/upper() are ASCII-only, which in this library
        # means every Japanese title compares as if it were already folded.
        self._con.create_function("cfold", 1, _cfold, deterministic=True)
        self.smart = SmartLists()
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
        self._search_rows = None  # lazy [(haystack, id, genre, year)]
        self._album_meta = None   # lazy {album_id: (genre blob, year)}
        # Rows for files opened by path that the library has never scanned —
        # negative ids, memory only, never written to the DB. See ids_for_paths.
        self._transient = {}
        self._transient_by_path = {}
        self._transient_seq = 0
        self.changed.connect(lambda: setattr(self, "_search_rows", None))
        self.changed.connect(lambda: setattr(self, "_album_meta", None))

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
            "SELECT * FROM tracks WHERE album_id=? ORDER BY COALESCE(disc, 1), track, title",
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
                    "SELECT * FROM tracks ORDER BY album_id, COALESCE(disc, 1), track, title")
                if hit(r["artist"]) or hit(r["album_artist"])]

    def smart_names(self):
        return self.smart.names()

    def smart_tracks(self, name):
        """A smart playlist's tracks, re-queried now — membership is never
        stored, so a list is live by construction."""
        spec = self.smart.get(name)
        return self.smart_rows(spec) if spec else []

    def smart_rows(self, spec):
        """The rows an (unsaved) spec matches — what the editor previews."""
        sql, params = smart_sql(normalize_smart(spec))
        try:
            return self._rows(sql, params)
        except sqlite3.Error as e:
            # A rule this build cannot run must not take the view down; the
            # list reads empty and the reason is on stderr.
            print("smart playlist query failed:", sql, e, flush=True)
            return []

    def smart_count(self, spec):
        sql, params = smart_sql(normalize_smart(spec), select="id")
        try:
            row = self._con.execute(
                f"SELECT COUNT(*) c FROM ({sql})", params).fetchone()
        except sqlite3.Error:
            return 0
        return int(row["c"]) if row else 0

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

    def prune_missing(self, paths):
        """Forget tracks whose files are gone: the row DISAPPEARS instead of
        sitting greyed for ever. Returns how many rows went.

        Deleting copies of a track outside the player (a dedupe pass over the
        library) used to leave the rows behind until the next full scan pruned
        them, so the album still listed the extra copies, greyed out.

        The greying itself stays — it is what an UNPLUGGED drive looks like, and
        that case must never prune: with the drive gone every path in the DB
        stats missing and this would erase the library. Hence the two gates: a
        network library never prunes (its DB is authoritative, and the stat is
        skipped there anyway), and a local one prunes only while the root is
        mounted and non-empty. Then it re-stats, because the caller's stat and
        the mount check are not one atomic act.
        """
        if library_is_remote_cached():
            return 0
        paths = [p for p in dict.fromkeys(paths) if p]
        if not paths or not library_mounted():
            return 0
        paths = [p for p in paths if not os.path.exists(p)]
        if not paths:
            return 0
        self._con.executemany("DELETE FROM tracks WHERE path=?",
                              [(p,) for p in paths])
        self._con.commit()
        rebuild_albums(self._con)   # an album that lost its last track goes too
        # Queued, not emitted: `changed` drives the very refresh we are inside.
        QTimer.singleShot(0, self.changed.emit)
        return len(paths)

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
        """Casefolded substring search over title/artist/album, plus the
        `genre:` / `year:` field filters (`parse_query`) — Unicode-correct (the
        Japanese titles) and instant at 11k rows against a cached haystack.

        The genre and the year are held BESIDE the haystack rather than in it:
        folded into the same string, `year:1997` would also match a track
        called "1997" and `genre:rock` an album called Rock, which is the one
        thing a field filter exists to stop."""
        words, genres, lo, hi = parse_query(text)
        if not words and not genres and lo is None and hi is None:
            return []
        if self._search_rows is None:
            self._search_rows = [
                ((f'{r["title"] or ""}\n{r["artist"] or ""}\n{r["album"] or ""}'
                  f'\n{r["album_artist"] or ""}').casefold(), r["id"],
                 (r["genre"] or "").casefold(), r["orig_year"] or r["year"])
                for r in self._con.execute(
                    "SELECT id, title, artist, album, album_artist, genre,"
                    " year, orig_year FROM tracks")]
        ids = [tid for hay, tid, gen, yr in self._search_rows
               if all(w in hay for w in words)
               and all(g in gen for g in genres)
               and year_in(yr, lo, hi)]
        return self.tracks_by_ids(ids[:400])

    def album_meta(self):
        """{album_id: (folded genre blob, year)} — every genre any of an
        album's tracks carries, for the grid's `genre:` filter.

        The albums table has no genre column and should not grow one: a genre
        is a TRACK tag and a compilation has as many as it has tracks. Derived
        and cached beside the search haystack, invalidated by the same signal."""
        if self._album_meta is None:
            out = {}
            for r in self._con.execute(
                    "SELECT album_id, genre, year, orig_year FROM tracks"
                    " WHERE album_id IS NOT NULL"):
                gen, yr = out.get(r["album_id"], ("", None))
                g = (r["genre"] or "").casefold()
                if g and g not in gen:
                    gen = (gen + "\n" + g) if gen else g
                out[r["album_id"]] = (gen, yr or r["orig_year"] or r["year"])
            self._album_meta = out
        return self._album_meta

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

    def set_scrobbler(self, scrobbler):
        """Last.fm, wired in after construction by main.py. A heart here is a
        love there — but the DB and the tag are written first and
        unconditionally, so an outage costs the love, not the favourite."""
        self._scrobbler = scrobbler

    @Slot(int, bool)
    def setFavorite(self, track_id, fav):
        self._con.execute("UPDATE tracks SET favorite=?, meta_mtime=? WHERE id=?",
                          (1 if fav else 0, time.time(), track_id))
        self._con.commit()
        t = self._track(track_id)
        if t:
            self._tagwriter.enqueue(t["path"], favorite=bool(fav))
            if self._scrobbler is not None:
                self._scrobbler.setLoved(dict(t), bool(fav))
        self.trackChanged.emit(track_id)

    def merge_lastfm(self, payload):
        """Fold a Last.fm account's loves, play counts and last-played times
        into the local library. Returns a summary dict.

        **The local side always wins where it is richer** [his, 2026-08-23:
        *"if i have a track liked here that\'s not liked on lastfm keep the
        local like"*]. Every field merges one way only:

        - **favourite** — set, never cleared. A love on Last.fm hearts the
          track here; a local heart that Last.fm does not know about stays
          exactly as it is, and is counted into `local_only_loves` so the
          asymmetry is reported rather than silently reconciled.
        - **play_count** — `max(local, remote)`, never lowered. Last.fm has
          only counted since the account was linked and this library has been
          counting for longer; taking the larger is the only merge that cannot
          lose a play. (`tools/dbsync.py` merges the two machines by the same
          rule, for the same reason.)
        - **last_played** — moved forward only.
        - **rating** — untouched. Last.fm has no such thing, so there is
          nothing to merge and a "sync" that cleared one would be a bug.

        Matching is `trackmatch.keys` (the one artist/title normaliser, see
        `../pylib/trackmatch.py`), not raw tag equality: a scrobble carries
        whatever tag the file had when it played, decorations and featured
        artists included. Unmatched rows are counted, not guessed at.
        """
        rows = self._rows("SELECT id, artist, title, favorite, play_count,"
                          " last_played, path FROM tracks")
        index = {}
        for r in rows:
            for k in trackmatch.keys(r["artist"], r["title"]):
                index.setdefault(k, []).append(r)

        def hits(artist, title):
            seen, out = set(), []
            for k in trackmatch.keys(artist, title):
                for r in index.get(k, ()):
                    if r["id"] not in seen:
                        seen.add(r["id"])
                        out.append(r)
            return out

        loved = payload.get("loved") or []
        plays = payload.get("plays") or []
        recent = payload.get("recent") or []
        stats = {"loved": len(loved), "plays": len(plays),
                 "hearted": 0, "counts": 0, "played": 0, "unmatched": 0,
                 "local_only_loves": 0}
        # (id -> the columns to write), so a track named by several remote rows
        # is one UPDATE and one tag write.
        pending = {}

        def want(r, **fields):
            cur = pending.setdefault(r["id"], {"row": r})
            cur.update(fields)

        matched_love_ids = set()
        for e in loved:
            rs = hits(e.get("artist"), e.get("track"))
            if not rs:
                stats["unmatched"] += 1
                continue
            for r in rs:
                matched_love_ids.add(r["id"])
                if not r["favorite"]:
                    want(r, favorite=1)
                    stats["hearted"] += 1

        for e in plays:
            n = int(e.get("playcount") or 0)
            rs = hits(e.get("artist"), e.get("track"))
            if not rs:
                stats["unmatched"] += 1
                continue
            # Several local files can be the same recording (a single and the
            # album cut). Last.fm counts the RECORDING, so raising every copy
            # to the remote total would multiply his history; only the
            # most-played local copy takes it.
            r = max(rs, key=lambda x: x["play_count"] or 0)
            if n > (r["play_count"] or 0):
                want(r, play_count=n)
                stats["counts"] += 1

        for e in recent:
            uts = int(e.get("uts") or 0)
            if not uts:
                continue
            for r in hits(e.get("artist"), e.get("track")):
                if uts > (r["last_played"] or 0):
                    want(r, last_played=uts)
                    stats["played"] += 1
                break        # most recent first: the first match is the answer

        stats["local_only_loves"] = sum(
            1 for r in rows if r["favorite"] and r["id"] not in matched_love_ids)

        now = time.time()
        for tid, fields in pending.items():
            r = fields.pop("row")
            if not fields:
                continue
            sets = ", ".join(f"{k}=?" for k in fields)
            params = list(fields.values())
            if "favorite" in fields:      # the tiebreaker dbsync merges on
                sets += ", meta_mtime=?"
                params.append(now)
            self._con.execute(f"UPDATE tracks SET {sets} WHERE id=?",
                              params + [tid])
            self._tagwriter.enqueue(
                r["path"],
                favorite=bool(fields["favorite"]) if "favorite" in fields else "keep",
                play_count=fields.get("play_count", "keep"))
        self._con.commit()
        if pending:
            self.changed.emit()
        stats["changed"] = len(pending)
        return stats

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

    #: CLASS-level, not only instance: the harnesses build a Player without
    #: running `__init__` (it would open libmpv and take his audio device), and
    #: `_announce` reads this on the very first queue change — so a scrobbler
    #: that was never set has to be None rather than absent.
    _scrobbler = None

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
        self._started_at = 0.0  # wall clock this track began — a scrobble's timestamp
        self._scrobbler = None  # set by main.py; None everywhere else
        self._mpv_paused = False
        self._idle = True

        import mpv as libmpv
        opts = dict(vid="no", audio_display="no",
                    gapless_audio="weak", ytdl=False)
        # A file on a network mount looks local to mpv, so `cache=auto` leaves
        # the demuxer cache OFF and every decode reads straight off the wire.
        # Measured on book 2026-08-19, streaming from top over SMB on wifi:
        # 64 KiB reads are 0.01ms at the median but 5 in 300 exceed 50ms and
        # one hit 223ms — past the 0.2s audio buffer, i.e. an underrun and an
        # audible pop, ~22 a minute on mpv's PipeWire node. Forcing the cache
        # on puts 30s of decoded-ahead audio between the network and the sink,
        # so a stalled read is invisible.
        if library_is_remote():
            opts.update(cache="yes", cache_secs=30, demuxer_max_bytes="64MiB",
                        demuxer_readahead_secs=20, stream_buffer_size="4MiB",
                        audio_buffer=0.4)
        self._mpv = libmpv.MPV(**opts)
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

    def set_scrobbler(self, scrobbler):
        """Wire Last.fm in after construction (main.py). Set late and by
        hand so the player still builds with no account, no `scrobble.py` and
        no network — every harness in tools/ constructs it that way."""
        self._scrobbler = scrobbler

    def _announce(self):
        """Tell Last.fm what is playing. On every start AND every resume: a
        now-playing entry expires by itself, so an unpause has to re-assert it
        or the site shows him as listening to nothing."""
        if self._scrobbler is not None and self._playing:
            self._scrobbler.nowPlaying(self.currentTrackDict())

    def _update_playing(self):
        """`playing` is derived — mpv's pause flag alone misses the transitions
        where pause never changes (track start, playlist ran out)."""
        playing = self._index >= 0 and not self._mpv_paused and not self._idle
        if playing != self._playing:
            self._playing = playing
            self.playingChanged.emit()
            if playing:
                self._announce()

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
            self._wrap_to_start()

    def _maybe_count(self):
        t = self.currentTrackDict()
        if self._counted or not t:
            return
        dur = t.get("duration") or self._duration
        if dur and self._listened >= min(dur / 2.0, 240.0):
            self._counted = True
            self._library.bump_playcount(t["id"])
            # ONE listen, one of each. The library's play count and the Last.fm
            # scrobble are the same event, decided here once, so the two counts
            # cannot drift into telling him different stories about the same
            # play. The scrobble's timestamp is when the track STARTED, which
            # is what Last.fm orders a history by.
            if self._scrobbler is not None:
                self._scrobbler.submit(t, self._started_at)

    # ---- queue plumbing ----

    def _set_index(self, idx):
        self._index = idx
        self._listened = 0.0
        self._counted = False
        self._started_at = time.time()
        self._position = 0.0
        self.indexChanged.emit()
        self.currentChanged.emit()
        self.positionChanged.emit()
        self._announce()      # already playing: the transition never fires

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

    def setFavorite(self, track_id, fav):
        """Forward a favourite flip from the queue server (the panel heart).

        `Library.setFavorite` writes the DB + tag queue and emits trackChanged;
        `Bridge._on_track_changed` answers that by patching this queue's cached
        dicts (`apply_track_update`), so a TOGGLE_FAV is reflected in the next
        queue snapshot without a queue/index change. The server calls this on
        the Player, not the Library — both expose the same method names."""
        self._library.setFavorite(track_id, bool(fav))

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
        """`start` is the queue row to play first. -1 means "no chosen track"
        (a play-all): under shuffle it pins NOTHING, so a shuffled playlist or
        album no longer opens on the same first song every single time —
        `keep_first` is only for a track the user actually clicked."""
        ids = [int(i) for i in ids]
        self._queue = self._library.tracks_by_ids(ids)
        # Drop files whose path is gone (a local drive unplugged under a
        # listing) — but never stat a network library on the GUI thread: that
        # froze the UI for seconds per play-all on book. mpv skips a dead file.
        if not library_is_remote_cached():
            self._queue = [t for t in self._queue
                           if os.path.exists(t["path"])] or self._queue
        self._orig_queue = None
        if self._shuffle and self._queue:
            self._queue = self._shuffled(self._queue, keep_first=start)
            start = 0
        self.queueChanged.emit()
        if self._queue:
            self._sync_mpv(min(max(start, 0), len(self._queue) - 1))

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
            # An explicit ordered list handed to the player (OPEN — chatter's
            # play_these, the file manager, a second launch) is an ORDER
            # statement: play these in the order given. A standing shuffle mode
            # would reorder them (`playTracks` reshuffles whenever `_shuffle`
            # is on), so an explicit list turns shuffle off — "play shuffled"
            # stays a deliberate, separate action that sets shuffle on itself.
            if self._shuffle:
                self._shuffle = False
                self.shuffleChanged.emit()
            self.playTracks(ids, 0)

    def queuePaths(self, paths):
        """APPEND files named by path to the queue, playing nothing new.

        playPaths' counterpart, and the other half of what a caller outside this
        process can ask for (the queue socket's QUEUE verb, chatter's
        `control_player`). Same "empty is a no-op" rule: a request whose paths
        were all unknown to the library must leave the queue as it was."""
        ids = self._library.ids_for_paths([str(p) for p in paths])
        if ids:
            self.queueTracks(ids)

    @Slot(int, int)
    def playAlbum(self, album_id, start=0):
        rows = self._library.album_tracks(album_id)
        self.playTracks([r["id"] for r in rows], start)

    @Slot(int)
    def queueAlbum(self, album_id):
        rows = self._library.album_tracks(album_id)
        self.queueTracks([r["id"] for r in rows])

    @Slot(int)
    def playAlbumNext(self, album_id):
        """Insert every track of the album, in album order, directly after the
        playing one — the album cover's right-click "play next" (the track menu
        already had the single-track playNext; this is its whole-album twin)."""
        rows = self._library.album_tracks(album_id)
        self.playNext([r["id"] for r in rows])

    def _fresh_rows(self, ids):
        """Library rows for `ids`, in the order given, minus anything whose file
        is gone (the library drive can be unplugged under a listing)."""
        rows = self._library.tracks_by_ids([int(i) for i in ids])
        if library_is_remote_cached():   # never stat a network mount on the UI thread
            return rows
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
        self.playTracks([r["id"] for r in rows], -1)

    @Slot(int)
    def jumpTo(self, idx):
        if 0 <= idx < len(self._queue):
            self._sync_mpv(idx)

    def _wrap_to_start(self):
        """Loop-all ran off the end: start the queue over. With shuffle on,
        deal a FRESH order first — replaying the identical shuffled order every
        cycle is what made shuffle look like it never re-randomised — and keep
        the track that just finished out of slot 0, so the wrap never plays it
        twice in a row. `_orig_queue` is untouched: turning shuffle off still
        restores the real order."""
        if self._shuffle and len(self._queue) > 1:
            last_id = None
            if 0 <= self._index < len(self._queue):
                last_id = self._queue[self._index]["id"]
            self._queue = self._shuffled(self._queue)
            if last_id is not None and self._queue[0]["id"] == last_id:
                self._queue.append(self._queue.pop(0))
            self.queueChanged.emit()
        self.jumpTo(0)

    @Slot()
    def next(self):
        if self._index + 1 < len(self._queue):
            self.jumpTo(self._index + 1)
        elif self._loop == self.LOOP_ALL and self._queue:
            self._wrap_to_start()

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

    def __init__(self, roles, parent=None, key=None):
        super().__init__(parent)
        self._role_names = {Qt.UserRole + i: r for i, r in enumerate(roles)}
        self._rows = []
        # The role that identifies a row across a refresh (albumId / trackId).
        # merge() keys on it to turn "replace every row" into the minimal
        # insert/remove/change so a view keeps its scroll position. Defaults to
        # the first role, which is the id column for both ALBUM_ROLES and
        # TRACK_ROLES.
        self._key = key or (roles[0] if roles else None)

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

    def merge(self, rows):
        """Reconcile the current rows toward `rows` in place, keyed on `self._key`,
        emitting the minimal insert/remove/dataChanged instead of a full reset.

        A reset (set_rows) snaps every view bound to this model back to the top
        and drops its selection; a library scan/import/watcher refresh must not
        do that (docs/DESIGN.md — a refresh under the user keeps their place).
        This turns "the same view gained/lost a few rows" into row operations a
        ListView absorbs while holding its contentY. Falls back to set_rows when
        there is no usable key, or when keys collide, so correctness never rides
        on the diff. Keys are unique for albumId and for trackId within one
        listing; a queue can hold a track twice, so it stays on set_rows."""
        key = self._key
        if key is None:
            self.set_rows(rows)
            return
        new_keys = [r.get(key) for r in rows]
        if len(set(new_keys)) != len(new_keys) or None in new_keys:
            self.set_rows(rows)  # can't diff safely — replace wholesale
            return

        # Phase 1 — drop rows absent from the new set, bottom-up in runs.
        keep = set(new_keys)
        i = len(self._rows) - 1
        while i >= 0:
            if self._rows[i].get(key) not in keep:
                j = i
                while j >= 0 and self._rows[j].get(key) not in keep:
                    j -= 1
                self.beginRemoveRows(QModelIndex(), j + 1, i)
                del self._rows[j + 1:i + 1]
                self.endRemoveRows()
                i = j
            else:
                i -= 1

        # Phase 2 — walk the target order, inserting new rows, moving reordered
        # ones (as remove+insert), patching data in place where only fields moved.
        i = 0
        while i < len(rows):
            nk = new_keys[i]
            if i < len(self._rows) and self._rows[i].get(key) == nk:
                if self._rows[i] != rows[i]:
                    self._rows[i] = rows[i]
                    self.dataChanged.emit(self.index(i), self.index(i))
                i += 1
                continue
            pos = next((j for j in range(i + 1, len(self._rows))
                        if self._rows[j].get(key) == nk), None)
            if pos is None:
                self.beginInsertRows(QModelIndex(), i, i)
                self._rows.insert(i, rows[i])
                self.endInsertRows()
            else:
                self.beginRemoveRows(QModelIndex(), pos, pos)
                del self._rows[pos]
                self.endRemoveRows()
                self.beginInsertRows(QModelIndex(), i, i)
                self._rows.insert(i, rows[i])
                self.endInsertRows()
            i += 1

        # Any trailing leftovers (shouldn't happen — every key is in the new
        # set) get trimmed so the model matches the target exactly.
        if len(self._rows) > len(rows):
            self.beginRemoveRows(QModelIndex(), len(rows), len(self._rows) - 1)
            del self._rows[len(rows):]
            self.endRemoveRows()

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
            "available": (os.path.exists(r["path"])
                          if check_exists and not library_is_remote_cached()
                          else True)}


class Bridge(QObject):
    """The QML-facing coordinator: owns the models and translates between the
    Library/Player and the views (which never see SQL or dicts-of-rows)."""

    scanStatus = Signal(str)
    scanRunning = Signal(bool)
    smartListsChanged = Signal()
    # systheme creation surfaces as a TOAST with a progress bar (SysthemeToast.qml),
    # not as in-window status text. The map carries {active, fraction, label,
    # outcome}: `active` toggles the toast, `fraction` (0..1) drives the bar,
    # `label` names the current phase, `outcome` is "" while running and
    # "ok"/"partial"/"fail" once done (so the toast can tint + linger the result
    # instead of vanishing — the no-silent-failure rule, docs/DESIGN.md §7.2).
    systhemeProgress = Signal("QVariantMap")

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
        self._systheme_proc = None
        # Progress-bar state for the systheme toast. `_frac` is what the bar
        # shows; `_target` is the ceiling the current phase eases it toward on a
        # timer, so the bar creeps forward during the long (unknown-length) comfy
        # render instead of freezing, and never reaches 1.0 until the run truly
        # ends — a bar that reads "done" before it is would be a silent lie.
        self._systheme_frac = 0.0
        self._systheme_target = 0.0
        self._systheme_label = ""
        self._systheme_last_err = ""
        self._systheme_ease = QTimer(self)
        self._systheme_ease.setInterval(120)
        self._systheme_ease.timeout.connect(self._systheme_tick)

        # A library scan/import/watcher refresh must keep the user's place: the
        # grid, the open album section and the open playlist all reconcile in
        # place rather than resetting to the top (see DictListModel.merge).
        library.changed.connect(lambda: self.refreshAlbums(merge=True))
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
    def refreshAlbums(self, merge=False):
        self._album_rows = self._library.albums(self._sort)
        self._apply_album_filter(merge=merge)

    def _apply_album_filter(self, merge=False):
        rows = self._album_rows
        words, genres, lo, hi = parse_query(self._filter)
        if words or genres or lo is not None or hi is not None:
            # An album's genre is whatever its tracks carry (Library.album_meta);
            # its year is the album row's own, which is already COALESCEd.
            meta = self._library.album_meta() if genres else {}
            rows = [r for r in rows
                    if all(w in f'{(r["album"] or "").casefold()}\n'
                                f'{(r["album_artist"] or "").casefold()}' for w in words)
                    and all(g in meta.get(r["id"], ("", None))[0] for g in genres)
                    and year_in(r["orig_year"] or r["year"], lo, hi)]
        out = [album_row(r) for r in rows]
        if merge:
            self.albumsModel.merge(out)
        else:
            self.albumsModel.set_rows(out)

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
    def openAlbum(self, album_id, merge=False):
        self._current_album = album_id
        rows = self._library.album_tracks(album_id)
        out = self._track_rows(rows)
        if merge:
            self.albumTracksModel.merge(out)
        else:
            self.albumTracksModel.set_rows(out)

    @Slot(int, result="QVariant")
    def albumInfo(self, album_id):
        a = self._library.album(album_id)
        if not a:
            return {}
        return {**album_row(a),
                "fullArt": str(ART / a["full_art"]) if a.get("full_art") else "",
                "trackCount": len(self._library.album_tracks(album_id))}

    # ---- systheme ("create systheme" on an album's right-click menu) ----

    @Property(bool, constant=True)
    def canSystheme(self):
        """Whether the cemented album-cover -> systheme entry point is present.
        Gates the menu entry so a missing script greys out rather than the
        action silently doing nothing (docs/DESIGN.md §7.2)."""
        return (HERE.parent / "pylib" / "systheme.py").is_file()

    # systheme.py logs its phases to stderr as `systheme: <msg>` lines. Each
    # recognised phase moves the bar to a milestone and renames the toast; the
    # long comfy render sits between two milestones and the ease timer creeps
    # the bar across the gap. Reusing systheme's own progress output (streamed
    # live) rather than inventing a second one — the same state that used to
    # print as in-window text, now driving a progress bar.
    _SYSTHEME_PHASES = (
        ("background uniformity", 0.15, "analysing cover"),
        ("subject ", 0.30, "composing layout"),
        ("edit graph built", 0.40, "preparing render"),
        ("submitted; waiting", 0.90, "rendering"),
        ("falling back to flat", 0.60, "rendering (flat)"),
        ("using flat route", 0.60, "rendering (flat)"),
        ("applying theme", 0.95, "applying theme"),
    )

    def _systheme_emit(self, active, outcome=""):
        self.systhemeProgress.emit({
            "active": active,
            "fraction": round(self._systheme_frac, 4),
            "label": self._systheme_label,
            "outcome": outcome,
        })

    def _systheme_tick(self):
        # Ease the shown fraction a fraction of the way to the phase ceiling.
        gap = self._systheme_target - self._systheme_frac
        if gap <= 0.001:
            return
        self._systheme_frac += gap * 0.06
        self._systheme_emit(True)

    def _systheme_phase(self, frac, label):
        self._systheme_target = max(self._systheme_target, frac)
        if label:
            self._systheme_label = label
        self._systheme_emit(True)

    def _on_systheme_stderr(self):
        proc = self._systheme_proc
        if proc is None:
            return
        chunk = bytes(proc.readAllStandardError()).decode("utf-8", "replace")
        for raw in chunk.splitlines():
            line = raw.strip()
            if not line:
                continue
            self._systheme_last_err = line
            for needle, frac, label in self._SYSTHEME_PHASES:
                if needle in line:
                    self._systheme_phase(frac, label)
                    break

    @Slot(int)
    def createSysthemeFromAlbum(self, album_id):
        """Turn this album's cover into the desktop systheme.

        Shells out to the one cemented entry point (apps/pylib/systheme.py)
        rather than reimplementing any of its crop/outpaint/apply pipeline.
        Runs async so the UI never blocks; progress and the final result are
        surfaced on `systhemeProgress` (the toast), success or failure alike,
        per the no-silent-failure rule (docs/DESIGN.md §7.2)."""
        if self._systheme_proc is not None:
            self._systheme_label = "already creating a systheme"
            self._systheme_emit(True, "partial")
            return
        info = self.albumInfo(album_id)
        art = info.get("fullArt") if info else ""
        if not art or not os.path.isfile(art):
            self._systheme_frac = 0.0
            self._systheme_label = "no cover art for this album"
            self._systheme_emit(True, "fail")
            return
        script = HERE.parent / "pylib" / "systheme.py"
        if not script.is_file():
            self._systheme_frac = 0.0
            self._systheme_label = "entry point not installed"
            self._systheme_emit(True, "fail")
            return
        self._systheme_last_err = ""
        self._systheme_frac = 0.03
        self._systheme_target = 0.08
        self._systheme_label = "creating systheme…"
        self._systheme_emit(True)
        self._systheme_ease.start()
        self._systheme_proc = QProcess(self)
        self._systheme_proc.finished.connect(self._on_systheme_done)
        self._systheme_proc.readyReadStandardError.connect(self._on_systheme_stderr)

        # On book there is no local GPU: the preferred generative (comfy) route
        # runs on top's ComfyUI, reached over the same ssh tunnel painter uses.
        # Route the render through comfy-tunnel.sh so the forward, the model
        # mount (PAINTER_MODELS, needed because the registry fingerprints tensor
        # headers) and a scoped temporary backend all come up around it and tear
        # down after — and force --method comfy, since the whole point of going
        # to top is the generative pass. On top the backend and models are local,
        # so run the entry point directly, method auto. Same book test as OnAir.
        on_book = socket.gethostname().split(".")[0] == "book"
        if on_book:
            tunnel = HERE.parent / "painter" / "tools" / "comfy-tunnel.sh"
            env = QProcessEnvironment.systemEnvironment()
            env.insert("COMFY_ENSURE_BACKEND", "1")
            self._systheme_proc.setProcessEnvironment(env)
            self._systheme_proc.start(
                "bash",
                [str(tunnel), "--", "/usr/bin/python3", str(script),
                 art, "--method", "comfy", "--json"],
            )
        else:
            self._systheme_proc.start(sys.executable, [str(script), art, "--json"])

    def _on_systheme_done(self, code, _status):
        proc = self._systheme_proc
        self._systheme_ease.stop()
        if proc is None:
            return
        # Drain any final stderr (the phase parser tracks the last line as the
        # failure reason) BEFORE nulling the handle it reads through.
        self._on_systheme_stderr()
        self._systheme_proc = None
        out = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
        err_last = getattr(self, "_systheme_last_err", "")
        self._systheme_frac = 1.0
        self._systheme_target = 1.0
        if code == 0 and out.strip():
            try:
                result = json.loads(out.strip().splitlines()[-1])
            except Exception:
                result = {}
            if result.get("applied"):
                self._systheme_label = f"systheme applied ({result.get('method', '?')})"
                self._systheme_emit(False, "ok")
            else:
                self._systheme_label = "systheme created but not applied"
                self._systheme_emit(False, "partial")
        else:
            reason = err_last or f"exit {code}"
            self._systheme_label = f"systheme failed: {reason}"
            self._systheme_emit(False, "fail")

    # ---- smart playlists ----
    #
    # The view binds to `smartLists` (a property, so the sidebar redraws when
    # one is added, renamed or deleted) and calls the rest as slots. The editor
    # holds a plain JS object of exactly the shape normalize_smart() returns and
    # hands it back whole — nothing here keeps a half-edited spec, so cancelling
    # is free and there is no draft to get out of step with the store.

    @Property("QVariantList", notify=smartListsChanged)
    def smartLists(self):
        return self._library.smart.specs()

    @Slot(result="QVariantList")
    def smartNames(self):
        return self._library.smart_names()

    @Slot(str, result="QVariant")
    def smartSpec(self, name):
        return self._library.smart.get(name) or {}

    @Slot(result="QVariant")
    def newSmartSpec(self):
        """The spec the "+ new" button starts from — one rule already there,
        because an empty rule list means "every track" and reads as broken."""
        return normalize_smart({"name": "new playlist",
                                "rules": [{"field": "artist", "op": "contains",
                                           "value": ""}]})

    @Slot(result="QVariantList")
    def smartFields(self):
        return [{"key": k, "label": lab, "kind": kind} for k, lab, kind in SMART_FIELDS]

    @Slot(str, result="QVariantList")
    def smartOps(self, field):
        return list(SMART_OPS.get(_FIELD_KIND.get(field, ""), ()))

    @Slot(result="QVariantList")
    def smartSorts(self):
        return [{"key": k, "label": lab} for k, lab, _ in SMART_SORTS]

    @Slot(str, result=str)
    def smartFieldKind(self, field):
        return _FIELD_KIND.get(field, "")

    @Slot(str, result=bool)
    def smartOpTakesValue(self, op):
        return op not in SMART_NULLARY_OPS

    @Slot("QVariantMap", result=int)
    def smartPreviewCount(self, spec):
        """How many tracks the spec being edited matches, right now — the
        editor's one honest readout that the rules do something."""
        return self._library.smart_count(spec)

    @Slot("QVariantMap", str, result=str)
    def saveSmart(self, spec, oldName=""):
        name = self._library.smart.save(spec, oldName)
        self.smartListsChanged.emit()
        # Renaming or re-ruling the list that is open must land in the view it
        # was edited from, not the next time it is selected.
        if self._current_smart in (oldName, name):
            self.openSmart(name)
        return name

    @Slot(str, result=bool)
    def deleteSmart(self, name):
        if not self._library.smart.remove(name):
            return False
        if self._current_smart == name:
            self._current_smart = ""
            self.playlistModel.set_rows([])
        self.smartListsChanged.emit()
        return True

    @Slot(str, result=str)
    def duplicateSmart(self, name):
        made = self._library.smart.duplicate(name)
        if made:
            self.smartListsChanged.emit()
        return made

    @Slot(result=int)
    def restoreSmartDefaults(self):
        n = self._library.smart.restore_defaults()
        if n:
            self.smartListsChanged.emit()
        return n

    @Slot(str)
    def openSmart(self, name, merge=False):
        self._current_smart = name
        rows = self._library.smart_tracks(name)
        out = self._track_rows(rows)
        if merge:
            self.playlistModel.merge(out)
        else:
            self.playlistModel.set_rows(out)

    @Slot()
    def refreshSmart(self):
        """Re-open the current smart playlist WITHOUT scrolling to the top —
        used when returning to the playlists view (counts may have moved).
        Selecting a different list (openSmart) still resets, as new content
        should."""
        if self._current_smart:
            self.openSmart(self._current_smart, merge=True)

    @Slot(str)
    def search(self, text):
        rows = self._library.search(text)
        self.searchModel.set_rows(self._track_rows(rows))

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

    # ---- listing rows ----

    def _track_rows(self, rows):
        """Library rows -> model rows for a listing that stats its files.

        A file that is gone is dropped AND pruned from the DB, so a track
        deleted outside the player leaves the album rather than lingering as a
        greyed row. `prune_missing` refuses when the drive is unplugged or the
        library is remote; then nothing is dropped and the rows stay greyed,
        which is what `available` is for."""
        out = [track_row(r, check_exists=True) for r in rows]
        gone = [r["path"] for r, o in zip(rows, out)
                if not o["available"] and int(r["id"]) > 0]
        if gone and self._library.prune_missing(gone):
            out = [o for o in out if o["available"]]
        return out

    # ---- refresh plumbing ----

    def _refresh_current(self):
        # Driven by library.changed — the open album section and playlist keep
        # their scroll (merge), unlike a user navigating to a new one.
        if self._current_album:
            self.openAlbum(self._current_album, merge=True)
        if self._current_smart:
            self.openSmart(self._current_smart, merge=True)

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

def _mpris_user_rating(track):
    """The xesam:userRating (0..1 float) for a track's MPRIS Metadata, or None
    to omit the key.

    xesam:userRating is the ONLY rating/favourite field the MPRIS spec gives
    us, and it is read-only display — no MPRIS verb writes it back, and stock
    Plasma's media controller shows neither a rating nor a like button, so the
    favourite cannot round-trip through Plasma. So map it to the real 0..1 star
    rating, NOT the favourite bool (which would misreport a rated-but-unliked
    track as 0). The favourite stays reachable through the in-app surfaces —
    the playbar/header/row hearts, the track menu and the L shortcut — all of
    which call Library.setFavorite and re-render off one trackChanged signal.
    currentChanged already re-emits Metadata, so a rating flip on the current
    track propagates a fresh userRating here."""
    r = track.get("rating")
    return float(r) if r is not None else None


def start_queue_server(player, app, lyrics=None, raise_window=None):
    """Serve the play queue to the desktop panel's media widget.

    MPRIS carries the CURRENT track and nothing else — its TrackList interface
    is optional and Quickshell implements no client for it — so the panel's
    queue drawer needs its own channel. This is a line-based unix socket at
    $XDG_RUNTIME_DIR/player-queue.sock:

        server -> client   one JSON line, {"index": n, "tracks": [...],
                           "lyrics": {...}|null}, on connect and again on every
                           queue/index change. Each track carries its
                           `favorite` flag (the panel's media widget draws the
                           heart from the current one).
        client -> server   GOTO <index>
                           TOGGLE_FAV  — flip favourite on the current track
                           LYRICS <0|1>     — "I am showing a lyrics box"
                           OPEN <enc> [<enc> …]  — play these files now
                           QUEUE <enc> [<enc> …] — append them to the queue
                           RAISE            — "somebody launched me again":
                                              come forward, they are exiting

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
                   "dur": float(t.get("duration") or 0.0),
                   "favorite": bool(t.get("favorite"))}
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
            elif parts and parts[0] == "TOGGLE_FAV":
                # Flip favourite on the current track (the panel's media widget
                # heart). setFavorite writes DB + tag queue and emits
                # trackChanged, which is not one of the server's push triggers,
                # so push() is explicit here — the heart must re-light from the
                # fresh snapshot, not from a later queue/index change.
                t = player.currentTrackDict()
                if t and t.get("id") is not None:
                    try:
                        player.setFavorite(t["id"], not bool(t.get("favorite")))
                    except Exception as e:
                        print("queue server: bad TOGGLE_FAV:", e, flush=True)
                push()
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
            elif len(parts) >= 2 and parts[0] == "QUEUE":
                # OPEN's counterpart: append, play nothing. This is what an
                # agent asking for "put this album on after what's playing"
                # lands in (apps/oracle: control_player queue_these).
                try:
                    player.queuePaths([urllib.parse.unquote(p) for p in parts[1:]])
                except Exception as e:
                    print("queue server: bad QUEUE:", e, flush=True)
                c.write(snapshot(c in want))
                c.flush()
            elif parts and parts[0] == "RAISE":
                # A SECOND LAUNCH WITH NO FILES. `handoff_paths` sends this
                # instead of starting a second player (which would take this
                # one's socket and its MPRIS name); presenting the window is
                # what clicking the icon meant. Answered with a snapshot like
                # OPEN, because that answer is how the launcher knows it was
                # heard and can exit rather than waiting out its timeout.
                if raise_window is not None:
                    try:
                        raise_window()
                    except Exception as e:
                        print("queue server: bad RAISE:", e, flush=True)
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


#: The bus name this app owns when MPRIS is up — `mpris_server` builds it from
#: the Server's name, and `start_mpris` checks the bus for it rather than
#: assuming the request succeeded.
MPRIS_NAME = "org.mpris.MediaPlayer2.player"


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
            ur = _mpris_user_rating(t)
            if ur is not None:
                meta["xesam:userRating"] = ur
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
        # PUBLISHING IS NOT OWNING. `publish()` only ASKS for the name, on
        # GLib's main context, and the answer arrives later — so a player that
        # lost the race to another instance sat there for an hour with no MPRIS
        # name at all and said nothing, while the panel, Plasma's applet and
        # chatter's control_media all reported no player [2026-08-24, on book].
        # Check once the loop has turned, and SAY so (docs/DESIGN.md §10).
        def check_name():
            try:
                from pydbus import SessionBus
                names = SessionBus().get(".DBus").ListNames()
            except Exception as e:
                print("mpris: cannot check the bus name:", e, flush=True)
                return
            if MPRIS_NAME in names:
                print("mpris: published as", MPRIS_NAME, flush=True)
            else:
                print("mpris: NOT on the bus as " + MPRIS_NAME + " — another "
                      "player instance is probably holding the name; this "
                      "window will be invisible to the panel, to Plasma's "
                      "media applet and to chatter", flush=True)
        QTimer.singleShot(1500, check_name)
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
    """Hand this launch to a player that is already running; True if one took it.

    Two players must never run at once — they would fight over the MPRIS name,
    the queue socket and the same mpv-shaped hole in the audio device, and the
    user would hear both. Before this, a second launch did exactly that; the
    module used to claim the library lock prevented it, and there is no such
    lock (sqlite's WAL lets a second writer in after a 60s wait).

    **A launch with NO files is a launch too** [2026-08-24]. This returned False
    on the spot when `paths` was empty, so the singleton check simply did not
    run for a bare `player` — and a bare `player` is the common one: the runner,
    the desktop entry, an agent with a shell. The second instance then took the
    queue socket off the first (the server unlinks a stale path before it
    listens), lost the race for the MPRIS name and kept running silently
    without one — which is a player the panel, Plasma's applet and chatter's
    control_media can all no longer see, playing its own restored queue over
    the top of his. With no files it sends RAISE instead: the running window
    comes forward and this launch exits, which is what clicking the icon meant.

    The queue socket is the singleton check, because it already exists and is
    already only ever created by a live player. Plain stdlib sockets rather than
    QLocalSocket: this runs before QGuiApplication, on the path where the whole
    point is not to start Qt at all. A failure of ANY kind falls through to a
    normal startup — an unreachable socket means no player, which is exactly the
    case a normal startup handles."""
    sock_path = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", QUEUE_SOCK)
    line = (("OPEN " + " ".join(urllib.parse.quote(p) for p in paths))
            if paths else "RAISE") + "\n"
    line = line.encode()
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


class AutoScanner(QObject):
    """Pick newly-downloaded tracks up without a manual rescan.

    Two paths feed the library and neither is watched:

      * slskd drops completed downloads into ~/.local/share/slskd/downloads,
        which is NOT under LIBRARY_ROOT, so the scan (which walks aud/) never
        sees them until tools/player-add.py moves them into aud/ and rescans.
        That tool only ran as the tail of a soulseek-missing.py pass, so a
        download that completed afterwards sat in downloads/ invisible to the
        player — clicking Rescan could not help, because there was nothing new
        under the scanned root. This watches the downloads dir and runs the
        import when it changes (and once at startup for any backlog).
      * files dropped straight into aud/ (a manual copy, a ripper) were only
        seen on the next launch's one-shot scan or a manual Rescan. This
        watches LIBRARY_ROOT too and rescans when it changes.

    Both are debounced and both converge on Library.rescan(), whose `changed`
    signal re-opens the open smart playlist — so a freshly added track appears
    in "recently added" without the button. player-add.py is run as a child of
    this process (sys.executable is the player's python env, which it needs);
    the module is never reimplemented here — see AGENTS.md's atomicsave rule.
    """

    RESCAN_DEBOUNCE_MS = 2000
    IMPORT_DEBOUNCE_MS = 3000
    REWATCH_S = 30

    def __init__(self, library, parent=None):
        super().__init__(parent)
        self._library = library
        self._proc = None
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_dir_changed)
        # Debounce: a download or copy writes a burst of filesystem events.
        self._rescan_timer = QTimer(self)
        self._rescan_timer.setSingleShot(True)
        self._rescan_timer.timeout.connect(self._library.rescan)
        self._import_timer = QTimer(self)
        self._import_timer.setSingleShot(True)
        self._import_timer.timeout.connect(self._run_import)
        # Low-frequency re-arm so a dir that appears later (SSD remount, slskd
        # first started after the app) starts being watched.
        self._rewatch_timer = QTimer(self)
        self._rewatch_timer.timeout.connect(self._watch_dirs)
        self._rewatch_timer.start(self.REWATCH_S * 1000)
        self._watch_dirs()
        # New-track hook: whenever a rescan finishes, compute+write ReplayGain
        # tags for any supported track that landed without them, as a child
        # (mirrors player-add.py). Debounced so a burst of scan completions
        # collapses into one child; only spawns when untagged supported tracks
        # actually exist, so a fully-tagged library never pays for it.
        self._rg_proc = None
        self._rg_timer = QTimer(self)
        self._rg_timer.setSingleShot(True)
        self._rg_timer.timeout.connect(self._maybe_rg_scan)
        self._library.scanRunning.connect(self._on_scan_running)
        # Catch up anything already sitting in downloads/ from a previous session.
        if SLSKD_DOWNLOADS.is_dir() and _has_audio(SLSKD_DOWNLOADS):
            self._import_timer.start(500)

    def _watch_dirs(self):
        dirs = [str(SLSKD_DOWNLOADS)]
        # Never stat or watch the library root when it is a network mount: this
        # runs on the GUI thread at startup and every REWATCH_S, and a stat on
        # book's cifs mount (//top/aud over Tailscale) blocks the whole event
        # loop for the CIFS timeout on any tailnet blip — the random freeze.
        # inotify does not propagate over cifs anyway, so the watch never fired
        # there; a manual Rescan still works. Local library (top's SSD): watch.
        if not library_is_remote_cached():
            dirs.insert(0, str(LIBRARY_ROOT))
        for p in dirs:
            if os.path.isdir(p) and p not in self._watcher.directories():
                self._watcher.addPath(p)

    def _on_dir_changed(self, path):
        self._watch_dirs()  # in case the dir structure changed under us
        if path == str(LIBRARY_ROOT):
            self._rescan_timer.start(self.RESCAN_DEBOUNCE_MS)
        elif path == str(SLSKD_DOWNLOADS):
            self._import_timer.start(self.IMPORT_DEBOUNCE_MS)

    def _run_import(self):
        if self._proc is not None:
            return  # an import is already moving the current batch
        self._proc = QProcess(self)
        self._proc.finished.connect(self._on_import_done)
        self._proc.start(sys.executable, [str(HERE / "tools" / "player-add.py")])

    def _on_import_done(self, _code, _status):
        self._proc = None
        # player-add rescans the DB itself, but out-of-process: this app's
        # models are untouched, so re-scan in-process to refresh the open smart
        # playlist ("recently added" included). The scan is incremental and
        # emits `changed`, which re-opens the current smart playlist.
        self._library.rescan()

    def _on_scan_running(self, running):
        # scanRunning(True) at scan start, (False) at done. Debounce so a burst
        # of consecutive scan completions collapses into one ReplayGain child.
        if not running:
            self._rg_timer.start(250)

    def _maybe_rg_scan(self):
        if self._proc is not None or self._rg_proc is not None:
            return  # an import is mid-move, or a gain scan is already running
        if not self._untagged_pending():
            return
        self._rg_proc = QProcess(self)
        self._rg_proc.finished.connect(self._on_rg_done)
        self._rg_proc.start(sys.executable,
                            [str(HERE / "tools" / "replaygain.py"),
                             "scan", "--write", "--auto"])

    def _on_rg_done(self, _code, _status):
        self._rg_proc = None

    def _untagged_pending(self):
        """True if any supported-format track lacks a ReplayGain tag and has
        not already been recorded as failed by the scanner's auto mode."""
        try:
            skip = set()
            try:
                with open(STATE / "replaygain-auto.json") as f:
                    skip = set(json.load(f))
            except Exception:
                pass
            con = open_db()
            try:
                rows = con.execute(
                    "SELECT path FROM tracks WHERE rg_track_gain IS NULL").fetchall()
            finally:
                con.close()
        except Exception:
            return False
        for r in rows:
            p = r["path"]
            if p in skip:
                continue
            if os.path.splitext(p)[1].lower() not in RG_UNSUPPORTED_EXTS:
                return True
        return False


def _has_audio(d):
    """True if `d` or any descendant holds an audio file (cheap, early out)."""
    try:
        for e in os.scandir(d):
            if e.is_dir(follow_symlinks=False):
                if _has_audio(e.path):
                    return True
            elif os.path.splitext(e.name)[1].lower() in AUDIO_EXTS:
                return True
    except OSError:
        return False
    return False


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    # --selftest: build the whole app OFFSCREEN, look at it, and quit. It is the
    # only way to check the Plasma face, which is chrome we do not draw — the
    # menubar, the two toolbars, the status bar and the window background all
    # come from the KDE style — and the offscreen-render rule (apps/AGENTS.md)
    # forbids putting a test window on his screen to find out.
    selftest = "--selftest" in sys.argv
    if selftest:
        # Hard, never setdefault, and with no display left to fall back to: an
        # exported QT_QPA_PLATFORM (his session's, or the wrapper's) would
        # otherwise win and the selftest would open a real player window on his
        # screen. With no display Qt aborts instead.
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ.pop("WAYLAND_DISPLAY", None)
        os.environ.pop("DISPLAY", None)

    open_paths = paths_from_argv(sys.argv[1:])
    if handoff_paths(open_paths):
        return

    # The Controls style, and with it the whole face: `Basic` in the Hyprland
    # session, `org.kde.desktop` under Plasma — which is not an imitation of the
    # KDE style but a renderer THROUGH it, so a Slider here is drawn by Oxygen's
    # own code. pylib/kdeshell.py.
    kdeshell.pin_controls_style()

    # A QApplication under Plasma, the QGuiApplication we have always used
    # otherwise: QStyle is a QtWidgets class, and without it there is no system
    # style to paint with. See kdeshell.make_app.
    app = kdeshell.make_app(sys.argv, "player")
    if selftest and app.platformName() != "offscreen":
        raise SystemExit("selftest refuses to run on platform %r, not offscreen"
                         % app.platformName())
    app.setApplicationName("player")
    app.setDesktopFileName("player")

    prefs = Prefs()
    tagwriter = TagWriter(prefs)
    library = Library(tagwriter)
    player = Player(library, prefs)
    # Last.fm. Wired in rather than constructed into either, so both still
    # build with no account and every harness in tools/ is unaffected. A
    # scrobble is decided by Player._maybe_count (one listen, one play count,
    # one scrobble) and a love by Library.setFavorite.
    scrobbler = Scrobbler(prefs)
    player.set_scrobbler(scrobbler)
    library.set_scrobbler(scrobbler)
    # The fetch is the scrobbler's (network, its own thread); the merge is the
    # library's, on the GUI thread with the library's own connection.
    scrobbler.set_merger(library.merge_lastfm)
    # The approval page opens in his browser — the one moment this app opens
    # anything, and only because he clicked `connect` a moment before.
    scrobbler.authUrlReady.connect(lambda u: QDesktopServices.openUrl(QUrl(u)))
    lyrics = LyricsProvider(prefs)
    bridge = Bridge(library, player, lyrics)
    autoscan = AutoScanner(library, app)
    titlebar = Titlebar()
    palette = Palette(theme_source(PANEL_THEME))
    style = DeskStyle()

    # TWO ROOFS, ONE APP (docs/DESIGN.md §7.6). Under Hyprland the QML tree IS
    # the window and all the chrome is the hyprvtb titlebar. Under Plasma the
    # same `Root.qml` is the central widget of a real QMainWindow, so the
    # menubar, the view toolbar, the transport toolbar along the bottom and the
    # status bar are KDE widgets and the window background is the system style's
    # — the single gradient surface that runs from the titlebar down through the
    # chrome and behind this content.
    plasma = is_plasma()
    shell = kdeshell.shell("player", size=(1080, 720),
                           min_size=(480, 320)) if plasma else None
    engine = shell.engine() if plasma else QQmlApplicationEngine()
    if plasma:
        # THE SELECTOR IS HOW THE CONTENT CHANGES CLOTHES WITHOUT CHANGING CODE.
        # With "plasma" set, `qml/+plasma/Foo.qml` transparently replaces
        # `qml/Foo.qml` for every call site — so the buttons, sliders and menus
        # in this session are QtQuick.Controls painted through the KDE style,
        # while the Hyprland tree keeps ours, and not one caller has a branch in
        # it. Same API, two implementations (apps/AGENTS.md).
        kdeshell.select_plasma_files(engine)
    ctx = engine.rootContext()
    # air (the MacBook, OS hostname "book") has a much smaller screen than
    # top: the QML lowers the window minimums and caps the now-playing cover
    # there. Keyed on hostname, not the launcher, so a bare `python3 main.py`
    # on air behaves the same as going through air-launch.sh.
    ctx.setContextProperty("OnAir", socket.gethostname().split(".")[0] == "book")
    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("DeskStyle", style)
    glyphs = Glyphs()          # keep the ref: a GC'd context property nulls its bindings
    ctx.setContextProperty("GlyphMap", glyphs)   # qmlcommon/Glyphs.qml wraps it
    ctx.setContextProperty("Titlebar", titlebar)
    ctx.setContextProperty("Prefs", prefs)
    ctx.setContextProperty("Library", bridge)
    ctx.setContextProperty("Player", player)
    ctx.setContextProperty("Lyrics", lyrics)
    ctx.setContextProperty("Lastfm", scrobbler)
    ctx.setContextProperty("AlbumsModel", bridge.albumsModel)
    ctx.setContextProperty("AlbumTracksModel", bridge.albumTracksModel)
    ctx.setContextProperty("PlaylistModel", bridge.playlistModel)
    ctx.setContextProperty("SearchModel", bridge.searchModel)
    ctx.setContextProperty("QueueModel", bridge.queueModel)

    warnings = []
    engine.warnings.connect(
        lambda errs: warnings.extend(e.toString() for e in errs))

    theme_comp = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "theme" / "Theme.qml")))
    theme = theme_comp.create()
    if theme is None:
        print("Theme.qml failed:\n" + theme_comp.errorString(), file=sys.stderr)
        sys.exit(1)
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)

    win = None
    if plasma:
        # Root.qml, not Main.qml: the Window wrapper is the Hyprland roof, and
        # a QQuickWidget hosts an Item.
        if not shell.load(QML / "Root.qml"):
            print("failed to load Root.qml", file=sys.stderr)
            for w in shell.errors() + warnings:
                print(f"  {w}", file=sys.stderr)
            sys.exit(1)
        root = shell.root
        # The menubar, the view toolbar and their shortcuts, out of `tbButtons`.
        # `titlebar` is the vtb bridge: its socket is dead in this session, but
        # every state change still runs `pushButtons()` through it, so its
        # signals are exactly the "the chrome changed" notification this face
        # needs — no second source and no polling.
        shell.bind_chrome(titlebar)
        # Konsole's toolbar names its buttons; so does this one [his,
        # 2026-08-24]. The sort row keeps its own `barText` words.
        shell.bar_labels()
        shell.bind_status()      # statusLine / statusProgress / statusRight
        shell.bind_title("windowTitle")   # "artist — title", as under Hyprland

        # ---- the finder, where KDE keeps it -----------------------------
        # A real QLineEdit at the right-hand end of the toolbar. The QML
        # `searchInput` stays the window's ONE source of search truth (filter vs
        # full results, Escape, the click-out unfocus are all decided there), so
        # this is a view onto it in both directions — guarded against the loop
        # a two-way mirror would otherwise make.
        mirroring = []

        def on_typed(text):
            if mirroring:
                return
            mirroring.append(1)
            try:
                QMetaObject.invokeMethod(root, "setSearchText",
                                         Q_ARG("QVariant", text))
            finally:
                mirroring.pop()

        field = shell.toolbar_search(on_typed, placeholder="Search the library")

        def on_qml_text():
            if mirroring:
                return
            mirroring.append(1)
            try:
                text = str(root.property("searchText") or "")
                if field.text() != text:
                    field.setText(text)
            finally:
                mirroring.pop()

        sig = getattr(root, "searchTextChanged", None)
        if sig is not None and hasattr(sig, "connect"):
            sig.connect(on_qml_text)
        field.returnPressed.connect(
            lambda: QMetaObject.invokeMethod(root, "submitSearch"))
        # SPACE AND L ARE PLAY/PAUSE AND FAVOURITE in this session, on QActions
        # — and a QAction shortcut is matched before the key reaches the focused
        # widget, so without this the search field could not be typed a space
        # into. They stand down while it has the keyboard.
        shell.guard_typing(field)
        shell.on_action("search", field.setFocus)

        # ---- the transport, along the bottom ----------------------------
        # A real QToolBar in the bottom area, filled from the same table by
        # `bar: "transport"`, with the seek slider and its two clocks as the one
        # widget that takes the room the buttons leave.
        shell.toolbar("transport", "Transport Bar", area=Qt.BottomToolBarArea)
        from transport import TransportSeek
        seek = TransportSeek(player)
        shell.toolbar_widget("transport", seek, stretch=True)

        # ---- settings: a dialog, not a drawer ---------------------------
        # There is no titlebar edge for a drawer to slide out of here, and a KDE
        # program's settings are a dialog. Same `SettingsPage.qml` either way.
        page_holder = []

        def build_settings():
            dlg = shell.dialog("settings", "Configure player",
                               QML / "SettingsPage.qml", size=(420, 420),
                               props={"pad": 12})
            if not page_holder:
                page = shell._dialogs["settings"][3]
                page.setProperty("columns", int(root.property("albumCols") or 7))
                page.columnsRequested.connect(
                    lambda n: QMetaObject.invokeMethod(
                        root, "setAlbumCols", Q_ARG("QVariant", int(n))))
                page.rescanRequested.connect(bridge.rescan)
                page.replayGainRequested.connect(player.setReplayGain)
                page.rgPreampRequested.connect(player.setRgPreamp)
                page_holder.append(page)
            # `columns` and the scan line are bindings onto the window's values
            # under Hyprland; the dialog is a separate scene, so they are pushed.
            page_holder[0].setProperty("columns", int(root.property("albumCols") or 7))
            page_holder[0].setProperty("scanStatus", str(root.property("scanStatus") or ""))
            page_holder[0].setProperty("scanning", bool(root.property("scanning")))
            return dlg

        def show_settings():
            build_settings()
            return shell.show_dialog("settings")

        shell.on_action("settings", show_settings)

        win = shell.show()
    else:
        engine.load(QUrl.fromLocalFile(str(QML / "Main.qml")))
        if not engine.rootObjects():
            for w in warnings:
                print(f"  {w}", file=sys.stderr)
            sys.exit(1)
        win = engine.rootObjects()[0]

    if not selftest:
        from winstate import WinState
        win_state = WinState(win, "player")  # keep ref: geometry

    if selftest:
        # The album models, so a shot shows a library rather than "no albums —
        # is the library drive mounted?". A read of the DB and nothing else: no
        # scan, no writes.
        bridge.refreshAlbums()
        return _selftest(app, shell, win, plasma, warnings, player, library, bridge)

    bridge.refreshAlbums()
    # With files on the command line, restore the SESSION (shuffle, loop, the
    # saved queue) but not the playhead: `restore_state` re-syncs mpv and posts
    # a delayed seek to the saved position, which would land 300 ms later on the
    # queue playPaths has replaced by then and seek the wrong track.
    player.restore_state(resume=not open_paths)
    if open_paths:
        player.playPaths(open_paths)
    start_mpris(player, app)

    def present():
        """Bring the window forward for a second launch (RAISE). `show()`
        first: it may be minimised, in which case activating alone leaves it
        exactly where it was."""
        win.show()
        if hasattr(win, "raise_"):
            win.raise_()
        if hasattr(win, "requestActivate"):
            win.requestActivate()
        elif hasattr(win, "activateWindow"):
            win.activateWindow()

    start_queue_server(player, app, lyrics, raise_window=present)
    QTimer.singleShot(400, library.rescan)  # incremental; UI is already up

    app.aboutToQuit.connect(player.save_state)
    sys.exit(app.exec())


def _selftest(app, shell, win, plasma, warnings, player=None, library=None,
              bridge=None):
    """Look at the window without opening one, and quit.

    Deliberately NOT reached by the normal path: no MPRIS name, no queue socket
    (both are singletons a running player already holds), no library rescan and
    no `save_state` on the way out — a harness must not hand him back a queue or
    a window the size of a test (~/nix/AGENTS.md).
    """
    rc = [0]
    # PLAYER_VIEW: which page the shot shows. Written straight onto the property
    # rather than through `setView`, so it persists nothing — a harness must not
    # hand him back a different page than the one he left the app on.
    want_view = os.environ.get("PLAYER_VIEW")
    # Under Hyprland `win` is Main.qml's Window and `view` belongs to the Root
    # INSIDE it, so setting the property on the window only invented a new one
    # that nothing read — the flag silently did nothing in that session and
    # every shot came out on whichever page the app was left on.
    view_owner = shell.root if shell is not None else (
        win.property("contentItem").childItems()[0] if win is not None else None)
    if want_view and view_owner is not None:
        view_owner.setProperty("view", want_view)

    # PLAYER_STATEPOKE: put a queue under the app WITHOUT playing anything, so
    # a harness can see the chrome follow the app's state. This is the case that
    # was silently broken for a day — the menubar and both toolbars were built
    # once and then froze, because `Titlebar` published no `buttonsChanged` for
    # `kdeshell.bind_chrome` to hear (see that class). Nothing decodes a byte:
    # the queue is set directly and the change signals are emitted by hand,
    # because mpv is his audio device and a harness does not get to touch it.
    def poke():
        if not os.environ.get("PLAYER_STATEPOKE") or player is None:
            return
        ids = [int(i) for i in os.environ["PLAYER_STATEPOKE"].split(",")
               if i.strip().isdigit()]
        player._queue = library.tracks_by_ids(ids or [1, 2, 3])
        player._index = 0
        player.queueChanged.emit()
        player.indexChanged.emit()
        player.currentChanged.emit()
        if os.environ.get("PLAYER_STATEPOKE_PLAYING"):
            player._playing = True
            player.playingChanged.emit()
        # PLAYER_STATEPOKE_LOOP: 0/1/2, so a harness can see the repeat row
        # take the mode's own icon. Set directly for the same reason as the
        # queue — `setLoop` talks to mpv, which is his audio device.
        if os.environ.get("PLAYER_STATEPOKE_LOOP"):
            player._loop = int(os.environ["PLAYER_STATEPOKE_LOOP"]) % 3
            player.loopChanged.emit()
        for _ in range(4):
            app.processEvents()

    def finish():
        # LAST, not before `app.exec()`: mpv's own idle/pause observers fire
        # during the wait and would put `_playing` back to False under us — the
        # queue survives (nothing else writes `_queue`), the playing flag does
        # not.
        poke()
        # PLAYER_MENUS: the menubar and both toolbars as text. A menu is not on
        # screen until it is opened, so no render can show what is in one —
        # this is the only check the KDE menu structure gets.
        if plasma and os.environ.get("PLAYER_MENUS"):
            print(shell.dump_chrome())
        # PLAYER_SMARTEDIT: open the smart-playlist editor over the playlists
        # page. Unlike Configure player… it is an in-window sheet, so
        # PLAYER_SHOT does contain it — there was simply no way to ask for it
        # open, and it is the one surface in this app a Plasma face is easy to
        # get wrong on (SmartEditor.qml). The value is a list name to EDIT, or
        # `1` for a new one.
        if os.environ.get("PLAYER_SMARTEDIT"):
            root_item = shell.root if shell is not None else win
            ed = root_item.findChild(QObject, "smartEditor") if root_item else None
            want = os.environ["PLAYER_SMARTEDIT"]
            if ed is not None:
                from PySide6.QtCore import QMetaObject, Q_ARG
                # invokeMethod, not `ed.createNew()`: a QML-declared function is
                # a meta-method on the item, and calling it as a Python
                # attribute is a silent no-op — the editor simply never opened
                # and nothing said so.
                if want in ("1", "new", ""):
                    QMetaObject.invokeMethod(ed, "createNew")
                else:
                    QMetaObject.invokeMethod(ed, "edit", Q_ARG("QVariant", want))
                # A GENEROUS SETTLE. The sheet is a Repeater of rule rows over
                # a Flickable, and at six passes it was `visible` and still
                # unpainted — a shot of a window with nothing in it, which reads
                # as the feature being broken rather than the harness being
                # early.
                for _ in range(40):
                    app.processEvents()
            else:
                print("selftest: no smart editor in the tree", file=sys.stderr)
        # PLAYER_DIALOG: build and grab Configure player…, which no shot of the
        # main window can contain — it is its own window.
        if plasma and os.environ.get("PLAYER_DIALOG"):
            shell._actions["settings"].trigger()
            app.processEvents()
            shell._dialogs["settings"][0].grab().save(os.environ["PLAYER_DIALOG"])
            print(f"selftest: wrote {os.environ['PLAYER_DIALOG']}")
            shell._dialogs["settings"][0].hide()
        if os.environ.get("PLAYER_TREE"):
            # What the WIDGET half is wearing — the half a QML-only dump cannot
            # see, and the half that goes wrong when the KDE platform theme is
            # missing (kdeshell.apply_palette).
            try:
                from PySide6.QtGui import QIcon
                print(f"style={app.style().objectName()} "
                      f"window={app.palette().window().color().name()} "
                      f"text={app.palette().windowText().color().name()} "
                      f"icons={QIcon.themeName()}")
            except Exception:  # noqa: BLE001
                pass
            root_item = shell.root if shell is not None else win
            want = os.environ.get("PLAYER_TREE")

            def walk(it, depth=0):
                if depth > 12 or it is None:
                    return
                # VISUAL children, not QObject children: a Repeater's delegates
                # and anything a view reparents into its contentItem keep their
                # QObject parent where it was.
                kids = (it.childItems() if hasattr(it, "childItems")
                        else it.children())
                for ch in kids:
                    try:
                        cls = ch.metaObject().className()
                        if ch.property("height") is None:
                            walk(ch, depth)
                            continue
                        name = ch.property("label") or ch.property("text") or ""
                        if want == "1" or want.lower() in (cls + " " + str(name)).lower():
                            print("  " * depth + f"{cls} {name!r} "
                                  f"x={ch.property('x')} w={ch.property('width')} "
                                  f"y={ch.property('y')} h={ch.property('height')} "
                                  f"vis={ch.property('visible')}")
                    except Exception:  # noqa: BLE001
                        pass
                    walk(ch, depth + 1)

            walk(root_item)
        # PLAYER_FACES: which components the file selector actually swapped.
        # Each `+plasma` variant carries `property string face: "plasma"`, and
        # this is the only way to prove the swap happened — a selector that
        # failed to take (an unowned QQmlFileSelector is collected moments after
        # it is made) loads the unselected file SILENTLY, with no error and no
        # warning (kdeshell.select_plasma_files).
        if os.environ.get("PLAYER_FACES"):
            seen = {}

            def faces(it, depth=0):
                if depth > 14 or it is None:
                    return
                for ch in (it.childItems() if hasattr(it, "childItems") else []):
                    f = ch.property("face")
                    # A STRING, specifically: `qmlcommon/VScroll.qml` has a
                    # `color face` of its own (the bevel's lit edge) and would
                    # otherwise report itself as swapped in both sessions.
                    if isinstance(f, str) and f:
                        cls = ch.metaObject().className().split("_QMLTYPE")[0]
                        seen[cls] = str(f)
                    faces(ch, depth + 1)

            faces(shell.root if shell is not None else win)
            for cls in sorted(seen):
                print(f"face {cls} = {seen[cls]}")
            if not seen:
                print("face: none found")
        # PLAYER_SEARCH: type a query into the finder and press Return, then
        # say what the window did with it. The finder is two halves that mirror
        # each other (a real QLineEdit under Plasma, `searchInput` in the QML),
        # and every way it can break — a mirror that does not fire, a Return
        # that reaches nobody, an overlay that stays hidden — is invisible to a
        # query the Library answers correctly. This drives the half the SESSION
        # owns and prints the other end.
        if os.environ.get("PLAYER_SEARCH"):
            from PySide6.QtCore import QMetaObject
            from PySide6.QtGui import QKeyEvent
            from PySide6.QtCore import QEvent
            q = os.environ["PLAYER_SEARCH"]
            root_item = shell.root if shell is not None else win
            if plasma and shell is not None and shell._search is not None:
                shell._search.setFocus()
                for ch in q:
                    ev = QKeyEvent(QEvent.KeyPress, 0, Qt.NoModifier, ch)
                    app.sendEvent(shell._search, ev)
                app.processEvents()
                app.sendEvent(shell._search,
                              QKeyEvent(QEvent.KeyPress, Qt.Key_Return,
                                        Qt.NoModifier, "\r"))
            else:
                QMetaObject.invokeMethod(root_item, "setSearchText",
                                         Q_ARG("QVariant", q))
                app.processEvents()
                QMetaObject.invokeMethod(root_item, "submitSearch")
            for _ in range(8):
                app.processEvents()
            item = root_item if shell is not None else (
                win.property("contentItem").childItems()[0])
            print(f"search: typed={q!r} "
                  f"searchText={item.property('searchText')!r} "
                  f"searching={item.property('searching')} "
                  f"results={bridge.searchModel.count if bridge else -1}")
            # ...and WHERE the overlay landed. A result set the model holds
            # and the window draws nowhere is the same thing to him as no
            # results at all.
            def _find(it, cls, depth=0):
                if it is None or depth > 14:
                    return None
                for ch in (it.childItems() if hasattr(it, "childItems") else []):
                    if ch.metaObject().className().startswith(cls):
                        return ch
                    got = _find(ch, cls, depth + 1)
                    if got is not None:
                        return got
                return None
            ov = _find(item, "SearchOverlay")
            if ov is None:
                print("search: NO SearchOverlay in the tree")
            else:
                print(f"search: overlay vis={ov.property('visible')} "
                      f"x={ov.property('x')} y={ov.property('y')} "
                      f"w={ov.property('width')} h={ov.property('height')} "
                      f"z={ov.property('z')} opacity={ov.property('opacity')}")
        shot = os.environ.get("PLAYER_SHOT")
        if shot:
            try:
                if shell is not None:
                    shell.window.grab().save(shot)
                elif win is not None:
                    win.grabWindow().save(shot)
                print(f"selftest: wrote {shot}")
            except Exception as exc:  # noqa: BLE001
                print(f"selftest: shot failed: {exc}", file=sys.stderr)
        for w in warnings:
            print(f"QML WARNING: {w}", file=sys.stderr)
        if warnings:
            rc[0] = 1
        print(f"selftest: root loaded, {len(warnings)} QML warning(s)")
        app.quit()

    QTimer.singleShot(1500, finish)
    app.exec()
    sys.exit(rc[0])


if __name__ == "__main__":
    main()
