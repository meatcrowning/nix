#!/usr/bin/env python3
"""ReplayGain scan for the player library.

The player's mechanism is already in place: mpv applies ReplayGain from the
file's own tags (main.py's _apply_rg / read_replaygain), leveling every track
to the same fixed loudness (ReplayGain 2.0, -18 LUFS reference) — Spotify-style
per-track normalization. ~93.5% of the library carries ReplayGain tags already;
this tool closes the remaining gap by COMPUTING and WRITING those tags for the
untagged tracks, and (via --auto) is the engine the new-track hook drives so any
track that lands in the library gets scanned automatically.

Uses `rsgain` (a packaged EBU-R128 / ReplayGain 2.0 scanner, on PATH) in
scan-only mode (`custom -s s`, which writes nothing) to compute gain+peak, then
writes the tags OURSELVES through atomicsave — the repo's fsynced
copy-then-replace path used by every other write into aud/ — so an interrupted
run can never leave a truncated file on exFAT. Dry-run is the default: nothing
is written unless --write is given, and a dry run reports coverage first.

Formats not representable in ReplayGain by rsgain (DSD .dsf/.dff, Musepack
.mpc, TTA) are skipped and reported; they keep using the player's median-gain
fallback at play time.

Usage:
  replaygain.py status                      coverage report (DB)
  replaygain.py scan [--write] [PATH...]    compute, or write when --write;
                                            with PATHS only those, else every
                                            untagged supported library track
  replaygain.py scan --write --auto         the new-track hook: write tags for
                                            untagged supported tracks, skipping
                                            any previously failed (idempotent)

Run under the player's python env (mutagen), like tools/player-add.py:

    PY=$(grep -oE '/nix/store/[^" ]+-env/bin/python3[0-9.]*' "$(command -v player)" | head -1)
    "$PY" apps/player/tools/replaygain.py scan          # dry run (default)
    "$PY" apps/player/tools/replaygain.py scan --write  # apply for real
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PLAYER_DIR = TOOLS_DIR.parent                       # apps/player
sys.path.insert(0, str(PLAYER_DIR))
sys.path.insert(0, str(PLAYER_DIR.parent / "pylib"))

import main as P     # noqa: E402  (LIBRARY_ROOT, AUDIO_EXTS, open_db, ...)
import atomicsave    # noqa: E402  (the safe copy-then-replace tag writer)

# Formats we skip: rsgain 3.7 cannot tag DSD/Musepack/TTA (main.py owns the
# list as RG_UNSUPPORTED_EXTS so the auto-hook and the scanner agree). They
# keep the player's median-gain fallback.
SUPPORTED_EXTS = frozenset(P.AUDIO_EXTS) - P.RG_UNSUPPORTED_EXTS

STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "player"
AUTO_STATE = STATE_DIR / "replaygain-auto.json"


# ---------------------------------------------------------------------------
# rsgain plumbing
# ---------------------------------------------------------------------------

def _rsgain():
    b = shutil.which("rsgain")
    if not b:
        raise SystemExit("rsgain not found on PATH; it ships in the nix profile")
    return b


def _f(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _gain(s):
    v = _f(s)
    return round(v, 2) if v is not None else None


def _scan_group(files):
    """Compute ReplayGain 2.0 for one album's files with rsgain in scan-only
    mode (writes nothing). Returns (per_file, album).

    per_file is a list aligned to `files`; an entry is None where rsgain could
    not produce a clean value for that file (missing, unreadable, or a
    basename collision we will not guess at). album is {"gain","peak"} from the
    trailing Album row, or None.
    """
    cmd = [_rsgain(), "custom", "-a", "-s", "s", "-O", *files]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        text = out.stdout
    except Exception as e:                       # timeout, missing binary, ...
        print("  rsgain failed for %d files: %s" % (len(files), e), flush=True)
        return [None] * len(files), None

    # Parse the tab-delimited output. Filename is just the basename, so match
    # files back by basename; a collision or a missing row means we cannot
    # attribute the value safely, and that file is left untouched (reported).
    byname = {}
    album = None
    for line in text.splitlines():
        r = line.rstrip("\n").split("\t")
        if not r:
            continue
        key = r[0]
        if key == "Filename":
            continue
        if key == "Album":
            if len(r) >= 4:
                album = {"gain": _gain(r[2]), "peak": _f(r[3])}
            continue
        byname.setdefault(key, []).append(r)

    per_file = []
    for f in files:
        rs = byname.get(os.path.basename(f))
        if rs and len(rs) == 1 and len(rs[0]) >= 4:
            g = _gain(rs[0][2])
            per_file.append({"track_gain": g, "track_peak": _f(rs[0][3])}
                            if g is not None else None)
        else:
            per_file.append(None)
    return per_file, album


# ---------------------------------------------------------------------------
# tag writing (through atomicsave — never in place)
# ---------------------------------------------------------------------------

def _set_rg(audio, tags):
    """Apply ReplayGain 2.0 tags (`{"track": (gain,peak), "album": (g,p)}`,
    numeric) to the mutagen object for the private copy. Called from within
    atomicsave.atomic_save; this must not call save()."""
    import mutagen.id3 as _id3
    from mutagen.flac import FLAC
    from mutagen.oggvorbis import OggVorbis
    from mutagen.oggopus import OggOpus
    from mutagen.oggflac import OggFLAC
    from mutagen.mp4 import MP4
    from mutagen.aiff import AIFF
    from mutagen.wave import WAVE

    td = {}
    for kind in ("track", "album"):
        t = tags.get(kind)
        if not t:
            continue
        g, p = t
        if g is not None:
            td["replaygain_%s_gain" % kind] = "%.2f dB" % g
        if p is not None:
            td["replaygain_%s_peak" % kind] = ("%.6f" % p).rstrip("0").rstrip(".")

    if isinstance(audio, (FLAC, OggVorbis, OggOpus, OggFLAC)):
        for k, v in td.items():
            if v is None:
                audio.tags.pop(k, None)
            else:
                audio.tags[k] = v

    elif isinstance(audio, MP4):
        for k, v in td.items():
            key = "----:com.apple.iTunes:" + k.upper()
            if v is None:
                audio.tags.pop(key, None)
            else:
                audio.tags[key] = [str(v).encode("utf-8")]

    else:  # ID3-based: MP3, AIFF, WAV
        t = audio if isinstance(audio, _id3.ID3) else audio.tags
        for k, v in td.items():
            desc = k.upper()
            # drop any existing RG frame with this desc, whatever its casing
            for key in [x for x in list(t.keys()) if str(x).upper() == "TXXX:" + desc]:
                t.delall(key)
            if v is not None:
                t.add(_id3.TXXX(encoding=3, desc=desc, text=[str(v)]))


def _write_one(path, rg, album):
    """Compute->write tags for one track and update the DB row. Returns the
    values written (for reporting) or None on failure (original untouched)."""
    tags = {}
    if rg:
        tags["track"] = (rg["track_gain"], rg["track_peak"])
    if album and album.get("gain") is not None:
        tags["album"] = (album["gain"], album.get("peak"))

    def mutate(audio):
        _set_rg(audio, tags)

    try:
        atomicsave.atomic_save(path, mutate)
    except Exception as e:
        print("  FAILED %s: %s" % (path, e), flush=True)
        return None

    con = P.open_db()
    try:
        con.execute(
            "UPDATE tracks SET rg_track_gain=?, rg_track_peak=?, "
            "rg_album_gain=?, rg_album_peak=? WHERE path=?",
            (tags["track"][0] if "track" in tags else None,
             tags["track"][1] if "track" in tags else None,
             tags["album"][0] if "album" in tags else None,
             tags["album"][1] if "album" in tags else None,
             path))
        con.commit()
    finally:
        con.close()
    return tags


# ---------------------------------------------------------------------------
# enumeration
# ---------------------------------------------------------------------------

def _untagged_supported():
    con = P.open_db()
    try:
        rows = con.execute(
            "SELECT path FROM tracks WHERE rg_track_gain IS NULL").fetchall()
    finally:
        con.close()
    return [r["path"] for r in rows
            if os.path.splitext(r["path"])[1].lower() in SUPPORTED_EXTS]


def _group_by_album(paths):
    albums = {}
    for p in paths:
        albums.setdefault(os.path.dirname(p), []).append(p)
    return albums


def _load_auto_skip():
    try:
        with open(AUTO_STATE) as f:
            return set(json.load(f))
    except Exception:
        return set()


def _save_auto_skip(failed):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(AUTO_STATE, "w") as f:
            json.dump(sorted(failed), f, indent=0)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_status(args):
    con = P.open_db()
    try:
        total = con.execute("SELECT COUNT(*) c FROM tracks").fetchone()["c"]
        gained = con.execute(
            "SELECT COUNT(rg_track_gain) c FROM tracks").fetchone()["c"]
    finally:
        con.close()
    untag = total - gained
    print("library: %d tracks, %d with ReplayGain tag, %d without (%.1f%%)"
          % (total, gained, untag, 100.0 * untag / total if total else 0.0))
    if total:
        print("untagged breakdown (supported = will be scanned):")


def cmd_scan(args):
    if args.paths:
        paths = [os.path.abspath(p) for p in args.paths]
    else:
        paths = _untagged_supported()
        if args.auto:
            skip = _load_auto_skip()
            paths = [p for p in paths if p not in skip]

    if not paths:
        print("nothing to do: every supported track already has a ReplayGain tag.")
        return 0

    album_map = _group_by_album(paths)
    total = len(paths)
    todo = sum(len(v) for v in album_map.values())
    print("%s %d supported track(s) in %d album(s)%s"
          % ("would tag" if not args.write else "tagging",
             todo, len(album_map),
             " (dry run — pass --write to apply)" if not args.write else ""))

    done = 0
    failed = []
    written = []
    for album_dir, files in sorted(album_map.items()):
        print("[%s]" % os.path.basename(album_dir) or album_dir)
        per_file, album = _scan_group(files)
        for path, rg in zip(files, per_file):
            if rg is None:
                failed.append(path)
                print("  SKIP  %s (rsgain produced no clean value)" % path)
                continue
            g = rg["track_gain"]
            if args.write:
                w = _write_one(path, rg, album)
                if w is None:
                    failed.append(path)
                else:
                    done += 1
                print("  %+6.2f dB  %s" % (g or 0.0, path))
            else:
                line = "  %+6.2f dB  %s" % (g or 0.0, path)
                if album and album.get("gain") is not None:
                    line += "  (album %+.2f dB)" % album["gain"]
                print(line)

    if args.auto and failed:
        skip = _load_auto_skip() | set(failed)
        _save_auto_skip(skip)
    if args.write and not args.auto:
        # a full manual run should see its failures again next time
        pass

    print("")
    print("dry-run summary: %d would be tagged, %d skipped/failed"
          % (todo, len(failed)) if not args.write else
          "write summary: %d tagged, %d skipped/failed" % (done, len(failed)))
    return 0 if not failed else 1


def main():
    ap = argparse.ArgumentParser(prog="replaygain.py",
                                 description="ReplayGain scan for the player library")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("status", help="library ReplayGain coverage report")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("scan", help="compute (or write) ReplayGain tags")
    p.add_argument("--write", action="store_true",
                   help="actually write tags (default is a dry run)")
    p.add_argument("--auto", action="store_true",
                   help="hook mode: only untagged supported tracks, skip prior failures")
    p.add_argument("paths", nargs="*", help="specific files to scan")
    p.set_defaults(fn=cmd_scan)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
