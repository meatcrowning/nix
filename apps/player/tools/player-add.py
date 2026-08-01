#!/usr/bin/env python3
"""Import completed Soulseek downloads into the player library and rescan.

The final step of the spotify-missing pipeline. soulseek-missing.py queues
downloads through slskd; slskd drops the completed files under
~/.local/share/slskd/downloads/. That script only *queues* — the player never
sees a track until it is moved into the library (aud/Artist/Album/...) and
rescanned. This tool closes that gap: it moves each completed download into
aud/ following the player's folder convention, fills in missing tags from the
pipeline's own missing.tsv (a Soulseek file can arrive bare, as the 0181 mp3
did — no artist, no title), and runs the library rescan so the track lands in
library.db and plays.

Run under the player's python env (mutagen + PySide6, so it can reuse
`main.py`'s read_tags / open_db / rebuild_albums); soulseek-missing.py resolves
that interpreter from the `player` wrapper:

    PY=$(grep -oE '/nix/store/[^" ]+-env/bin/python3[0-9.]*' "$(command -v player)" | head -1)
    "$PY" apps/player/tools/player-add.py [--dry-run]

It writes the library.db directly (WAL-friendly, busy_timeout 60 s) like
tools/dbsync.py does, and never touches the running player's session.
"""

import argparse
import os
import re
import shutil
import sys
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PLAYER_DIR = TOOLS_DIR.parent                      # apps/player
sys.path.insert(0, str(PLAYER_DIR))
sys.path.insert(0, str(PLAYER_DIR.parent / "pylib"))

import mutagen  # noqa: E402
import main as P  # noqa: E402

DL_DIR = Path(os.path.expanduser("~/.local/share/slskd/downloads"))
META_DIR = Path(os.path.expanduser("~/.local/share/spotify-dump"))

# --- tag filling ------------------------------------------------------------

def _apply_tags(audio, meta):
    """Set title/artist/album/album_artist/year on `audio` from meta fields."""
    title, artist = meta.get("title"), meta.get("artists")
    album, year = meta.get("album"), meta.get("year")
    album_artist = meta.get("album_artist") or artist
    try:
        tags = audio.tags
        if tags is None:
            audio.add_tags()
            tags = audio.tags
    except Exception:
        return

    import mutagen.flac as _flac
    import mutagen.id3 as _id3
    import mutagen.mp4 as _mp4

    if isinstance(tags, _id3.ID3):
        def frame(cls, text):
            return [cls(encoding=3, text=[str(text or "")])]
        if title:
            tags.setall("TIT2", frame(_id3.TIT2, title))
        if artist:
            tags.setall("TPE1", frame(_id3.TPE1, artist))
        if album:
            tags.setall("TALB", frame(_id3.TALB, album))
        if album_artist:
            tags.setall("TPE2", frame(_id3.TPE2, album_artist))
        if year:
            tags.setall("TDRC", frame(_id3.TDRC, year))
    elif isinstance(audio, _mp4.MP4):
        def mp4(key, value):
            if value is not None:
                audio[key] = [value]
        mp4("\xa9nam", title)
        mp4("\xa9ART", artist)
        mp4("\xa9alb", album)
        mp4("aART", album_artist)
        if year:
            audio["\xa9day"] = [str(year)]
    elif isinstance(audio, _flac.FLAC) or hasattr(tags, "__setitem__"):
        for key, value in (("title", title), ("artist", artist),
                           ("album", album), ("albumartist", album_artist)):
            if value:
                tags[key] = [str(value)]
        if year:
            tags["date"] = [str(year)]
    # else: unsupported container; leave it alone (best effort)


def fill_tags(path, meta):
    """Write missing tags into a bare download, atomically (copy->replace)."""
    from atomicsave import atomic_save  # noqa: PLC0415

    def mutate(audio):
        _apply_tags(audio, meta)

    atomic_save(path, mutate)


# --- metadata from the pipeline --------------------------------------------

def load_meta(meta_dir):
    """Map a downloaded file's basename -> metadata row.

    A Soulseek file can arrive with no tags (the 0181 mp3 had none). The
    pipeline already knows what each queued download *is*: soulseek-state.tsv
    logs the peer filename + spotify_id, and missing.tsv maps that spotify_id
    to the artists/title/album/year that were missing. Keys are the basename
    of the peer filename, which is what lands on disk.
    """
    missing_path = meta_dir / "missing.tsv"
    state_path = meta_dir / "soulseek-state.tsv"
    by_id = {}
    if missing_path.is_file():
        with open(missing_path) as f:
            header = f.readline().rstrip("\n").split("\t")
            for line in f:
                parts = line.rstrip("\n").split("\t")
                fields = parts + [""] * (len(header) - len(parts))
                row = dict(zip(header, fields))
                if row.get("spotify_id"):
                    by_id[row["spotify_id"]] = row
    out = {}
    if state_path.is_file():
        with open(state_path) as f:
            header = f.readline().rstrip("\n").split("\t")
            for line in f:
                parts = line.rstrip("\n").split("\t")
                fields = parts + [""] * (len(header) - len(parts))
                row = dict(zip(header, fields))
                sid = row.get("spotify_id")
                meta = by_id.get(sid)
                if meta and row.get("filename"):
                    out[os.path.basename(row["filename"])] = meta
    return out


# --- folder naming ----------------------------------------------------------

_RESERVED = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(s, fallback):
    """One exFAT-legal, filesystem-usable directory segment from a tag."""
    s = _RESERVED.sub(" ", s or "").strip()
    s = re.sub(r"\s+", " ", s)
    if not s:
        return fallback
    return s[:150]


# --- the move ---------------------------------------------------------------

def find_download_files(dl_dir):
    """Yield every audio file under a completed slskd download."""
    if not dl_dir.is_dir():
        return
    for root, _dirs, files in os.walk(dl_dir):
        for name in files:
            if os.path.splitext(name)[1].lower() in P.AUDIO_EXTS:
                yield Path(root) / name


def prune_empty_dirs(dl_dir, src):
    """Remove the now-empty source dirs a moved file left behind, up to (but
    not including) the downloads root. slskd drops one folder per grab; after
    its files are imported those folders are just litter."""
    removed = []
    d = Path(src).parent
    while d != dl_dir and dl_dir in d.parents:
        try:
            d.rmdir()  # only succeeds when empty
        except OSError:
            break
        removed.append(d)
        d = d.parent
    return removed



def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--downloads-dir", default=str(DL_DIR))
    ap.add_argument("--meta-dir", default=str(META_DIR))
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be moved; do not move, tag or rescan")
    args = ap.parse_args()

    root = P.LIBRARY_ROOT
    if not root.is_dir():
        raise SystemExit(f"library root {root} is not mounted; aborting")
    dl_dir = Path(args.downloads_dir)
    if not dl_dir.is_dir():
        raise SystemExit(f"no downloads dir at {args.downloads_dir}")

    meta = load_meta(Path(args.meta_dir))
    moved = 0
    skipped = 0

    for src in sorted(find_download_files(dl_dir)):
        t = P.read_tags(str(src))
        m = meta.get(os.path.basename(str(src)))
        need_tags = not (t and t.get("artist") and t.get("title"))
        if need_tags and m:
            if args.dry_run:
                print(f"  would tag       {src.name}")
            else:
                print(f"  tagged          {src.name}")
                try:
                    fill_tags(src, m)
                    t = P.read_tags(str(src))
                except Exception as e:
                    print(f"    ! tag failed: {e}")
        artist = (t or {}).get("artist") or (m or {}).get("artists") or "Unknown Artist"
        album = (t or {}).get("album") or (m or {}).get("album") or "Unknown Album"
        dest_dir = root / safe_name(artist, "Unknown Artist") / safe_name(album, "Unknown Album")
        dest = dest_dir / src.name
        if dest.exists():
            if not args.dry_run:
                print(f"  skip (exists)   {dest}")
            skipped += 1
            continue
        if args.dry_run:
            print(f"  would move      {src} -> {dest}")
        else:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            for p in prune_empty_dirs(dl_dir, src):
                print(f"  pruned empty    {dl_dir.name}/{p.relative_to(dl_dir)}")
            print(f"  moved           {src.name} -> {root.name}/{safe_name(artist, 'Unknown Artist')}/{safe_name(album, 'Unknown Album')}/")
        moved += 1

    print(f"\n{moved} download(s) imported into {root}" + ("" if args.dry_run else "; skipped {skipped} already present" if skipped else ""))
    if args.dry_run:
        print("(--dry-run: nothing changed)")
        return

    # --- rescan: mirror main.py's Scanner so the moved tracks land in library.db
    con = P.open_db()
    try:
        walked, parsed = rescan(con)
    finally:
        con.close()
    print(f"rescan: walked {walked} file(s), parsed {parsed} new/changed "
          f"(library.db updated in place; the running player picks them up on its next rescan)")


def rescan(con):
    """Incremental library rescan mirroring Scanner._run in main.py."""
    root = P.LIBRARY_ROOT
    seen = {}
    stack = [str(root)]
    while stack:
        d = stack.pop()
        try:
            for e in os.scandir(d):
                if e.is_dir(follow_symlinks=False):
                    stack.append(e.path)
                elif e.is_file() and os.path.splitext(e.name)[1].lower() in P.AUDIO_EXTS:
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
    for p in todo:
        t = P.read_tags(p)
        if t is None:
            bad += 1
            continue
        mtime, size = seen[p]
        con.execute(
            "INSERT INTO tracks (path, mtime, size, title, artist, album, album_artist,"
            " track, disc, date, year, orig_year, genre, duration, codec, samplerate,"
            " bitdepth, rating, favorite, play_count, added_at, has_art,"
            " rg_track_gain, rg_track_peak, rg_album_gain, rg_album_peak)"
            " VALUES (:path,:mtime,:size,:title,:artist,:album,:album_artist,"
            " :track,:disc,:date,:year,:orig_year,:genre,:duration,"
            " :codec,:samplerate,:bitdepth,:rating,:favorite,:play_count,:added_at,:has_art,"
            " :rg_track_gain,:rg_track_peak,:rg_album_gain,:rg_album_peak)"
            " ON CONFLICT(path) DO UPDATE SET"
            " mtime=:mtime, size=:size, title=:title, artist=:artist, album=:album,"
            " album_artist=:album_artist, track=:track, disc=:disc, date=:date,"
            " year=:year, orig_year=:orig_year, genre=:genre, duration=:duration,"
            " codec=:codec, samplerate=:samplerate, bitdepth=:bitdepth,"
            " rating=:rating, favorite=:favorite, play_count=:play_count,"
            " has_art=:has_art, rg_track_gain=:rg_track_gain, rg_track_peak=:rg_track_peak,"
            " rg_album_gain=:rg_album_gain, rg_album_peak=:rg_album_peak",
            {**t, "path": p, "mtime": mtime, "size": size, "added_at": now})
    con.commit()

    if gone and (len(gone) < len(known) or seen):
        con.executemany("DELETE FROM tracks WHERE path=?", [(p,) for p in gone])
        con.commit()

    P.rebuild_albums(con)
    if bad:
        print(f"  (unreadable during rescan: {bad})")
    return len(seen), len(todo)


if __name__ == "__main__":
    main()
