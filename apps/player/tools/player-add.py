#!/usr/bin/env python3
"""Import completed Soulseek downloads into the player library and rescan.

The final step of the spotify-missing / album-missing pipeline.
soulseek-missing.py queues downloads through slskd; slskd drops the completed
files under ~/.local/share/slskd/downloads/. That script only *queues* — the
player never sees a track until it is moved into the library (aud/Artist/Album/
...) and rescanned. This tool closes that gap: it moves each completed download
into aud/ following the player's folder convention, fills in missing tags from
the pipeline's own record (a Soulseek file can arrive bare, as the 0181 mp3
did — no artist, no title), and runs the library rescan so the track lands in
library.db and plays.

Placement: soulseek-missing.py records the album identity of every queued
download (album_artist, album, album_ref — the MusicBrainz release id / Spotify
album id the album-missing inventory worked from) into soulseek-state.tsv at
enqueue time. A download matched to that record is placed into ITS album:

  * the destination is the folder the library already groups the album under
    (matched on the live DB by folded album_artist+album, then by the
    MusicBrainz ref via the audit tagscan, then by a shared-artist-token), or
    a fresh aud/<AlbumArtist>/<Album>/ folder per the library convention when
    the album has no files yet;
  * the file's album/album_artist tags are written to match that folder (the
    player groups by TAG, not folder, so a track whose Soulseek tags name a
    different album would otherwise be invisible in the album it was
    downloaded for); title/artist are filled only when the file is bare.

A file that cannot be matched to any pipeline record AND has no usable tags is
parked in <downloads>/needs-attention/ and reported — it is NEVER silently
dropped into aud/Unknown Artist/Unknown Album.

Run under the player's python env (mutagen + PySide6, so it can reuse
`main.py`'s read_tags / open_db / rebuild_albums); soulseek-missing.py resolves
that interpreter from the `player` wrapper:

    PY=$(grep -oE '/nix/store/[^\" ]+-env/bin/python3[0-9.]*' "$(command -v player)" | head -1)
    "$PY" apps/player/tools/player-add.py [--dry-run]

It writes the library.db directly (WAL-friendly, busy_timeout 60 s) like
tools/dbsync.py does, and never touches the running player's session.
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PLAYER_DIR = TOOLS_DIR.parent                      # apps/player
sys.path.insert(0, str(PLAYER_DIR))
sys.path.insert(0, str(PLAYER_DIR.parent / "pylib"))

import mutagen  # noqa: E402
import main as P  # noqa: E402
import trackmatch  # noqa: E402

DL_DIR = Path(os.path.expanduser("~/.local/share/slskd/downloads"))
META_DIR = Path(os.path.expanduser("~/.local/share/spotify-dump"))
TAGSCAN = Path(os.path.expanduser("~/.cache/library-tag-audit/tagscan.json"))
# Unmatchable downloads (no pipeline record, no usable tags) are parked here,
# under the downloads dir, never moved into aud/ under a made-up identity.
NEEDS_ATTENTION = "needs-attention"

# --- tag filling ------------------------------------------------------------

def _apply_tags(audio, meta):
    """Set title/artist/album/album_artist/year on `audio` from meta fields.
    Only fields present in meta are written; empty values are left alone."""
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
    """Write `meta` (only the fields it carries) into a download, atomically
    (copy->replace)."""
    from atomicsave import atomic_save  # noqa: PLC0415

    def mutate(audio):
        _apply_tags(audio, meta)

    atomic_save(path, mutate)


def _fold(s):
    return trackmatch.fold(s or "")


# --- metadata from the pipeline --------------------------------------------

def load_meta(meta_dir):
    """Map a downloaded file's basename -> the pipeline's record of it.

    soulseek-state.tsv is the persistent record of what was queued. Rows
    written by the album-missing pipeline are self-contained: they carry the
    track's artists/title and the album identity (album_artist, album, year,
    album_ref) so the importer can place a bare or mis-tagged Soulseek file
    into the album it was downloaded for. Older rows (spotify_id only) are
    joined through spotify_id to missing.tsv, as before. Keys are the basename
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
                if not row.get("filename"):
                    continue
                # Soulseek peer paths use backslashes; normalize before taking
                # the basename, which is the name the file lands under in the
                # downloads dir (the same rule the rest of the pipeline uses).
                rec = dict(row)
                if not (rec.get("album_artist") or rec.get("album")):
                    # old-style row: join through spotify_id to missing.tsv
                    meta = by_id.get(row.get("spotify_id"))
                    if meta:
                        for k in ("artists", "title", "album",
                                  "album_artist", "year"):
                            rec[k] = meta.get(k, "")
                out[os.path.basename(
                    str(row["filename"]).replace("\\", "/"))] = rec
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


_RESERVED_NAMES = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} \
    | {f"lpt{i}" for i in range(1, 10)}


def safe_file(name):
    """An exFAT-legal filename for the destination. Downloads keep the remote
    peer's filename, which is bound by the PEER's filesystem rules — a
    netlabel named '<_body>' makes the raw name unmovable into aud/ (exFAT
    rejects it with EINVAL, which used to abort the whole import cycle).
    Same sanitizer as safe_name, so '<_body> - Dial Up.flac' lands as
    'body - Dial Up.flac', the same way its album folder did. Also guards
    the reserved device names (CON/PRN/COM1/...) exFAT refuses outright."""
    stem, ext = os.path.splitext(name or "")
    stem = safe_name(stem, "track")
    if stem.lower() in _RESERVED_NAMES:
        stem = "_" + stem
    if not stem.strip("."):
        stem = "track"  # an all-dots stem is a '.'/'..' alias, unusable
    return stem + (ext.lower() or "")


# --- album placement ---------------------------------------------------------

def build_album_index(conn):
    """Album placement index from the live library DB.

    The player groups albums by TAG — (COALESCE(album_artist, artist), album),
    see main.py rebuild_albums — not by folder, so the folder a download
    belongs in is wherever the album's files' tags currently live. Returns
    (exact, token, dominant):

      exact[(folded_album_artist, folded_album)] -> {parent dirs}
      token[(folded_artist_token, folded_album)] -> {parent dirs}  (generous)
      dominant[dir] -> (album_artist, album) most common among the dir's files
    """
    exact, token, dominant = {}, {}, {}
    dir_counts = {}
    for album_artist, artist, album, path in conn.execute(
            "SELECT album_artist, artist, album, path FROM tracks"):
        aa = _fold(album_artist) or _fold(artist)
        fal = _fold(album)
        d = os.path.dirname(path)
        if aa and fal:
            exact.setdefault((aa, fal), set()).add(d)
            for t in aa.split():
                token.setdefault((t, fal), set()).add(d)
        if fal:
            dir_counts.setdefault(d, Counter())[
                (album_artist or artist, album)] += 1
    for d, c in dir_counts.items():
        dominant[d] = c.most_common(1)[0][0]
    return exact, token, dominant


def load_mbid_dirs():
    """{mbid: {parent dirs}} from the audit tag scan (tagscan.json).

    A file's MusicBrainz Album Id is the strongest album identity there is, so
    a release whose local folder carries a different album-tag spelling (e.g.
    "Get Rich or Die Tryin' (2012)" for release "Get Rich or Die Tryin'") is
    still found. Point-in-time, exactly like album-inventory.py uses it; a
    fresh `audit-tags-vs-mb.py scan` before a download run keeps it current.
    """
    out = {}
    try:
        with open(TAGSCAN) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return out
    for e in data or []:
        m = e.get("album_mbid")
        if m and e.get("path"):
            out.setdefault(m, set()).add(os.path.dirname(e["path"]))
    return out


def resolve_dest(root, album_artist, album, index, mbid_dirs, album_ref):
    """The folder a download belongs in, plus the tags it should carry.

    An existing folder wins — the album's files already live there, in
    whatever spelling the library uses, and the new file must be tagged with
    that folder's own identity or the player will split the album into two
    groups. Then the MusicBrainz ref (via the tagscan) catches folders whose
    album tag is a variant of the release title; then a shared-artist-token
    match (the inventory's own generous rule); and only when the album has no
    files at all is a fresh aud/<AlbumArtist>/<Album>/ folder created per the
    library convention.

    Returns (dest_dir, folder_artist, folder_album): folder_* are the album
    identity the file should be tagged with (the folder's own when it exists,
    else the pipeline record's).
    """
    exact, token, dominant = index
    fa, fal = _fold(album_artist), _fold(album)
    dirs = set()
    if fal:
        dirs = exact.get((fa, fal), set())
        if not dirs and album_ref and mbid_dirs:
            dirs = mbid_dirs.get(album_ref, set())
        if not dirs:
            for t in (fa.split() if fa else ()):
                dirs |= token.get((t, fal), set())
    if dirs:
        # Prefer a candidate folder that actually exists on disk: the DB can
        # hold stale paths (a rename since the last rescan — the library
        # cleanup moves folders), and sorting would happily pick the dead one.
        live = [d for d in dirs if os.path.isdir(d)]
        d = sorted(live or dirs)[0]
        f_artist, f_album = dominant.get(d, (album_artist, album))
        return Path(d), f_artist, f_album
    return (root / safe_name(album_artist, "Unknown Artist")
            / safe_name(album, "Unknown Album")), album_artist, album


def meta_for_file(t, m, folder_artist, folder_album, stem=""):
    """The tag fields to write for a pipeline-tracked download.

    Returns only the fields that should change: title/artist when the file is
    bare (the downloader already matched them, so present values are kept),
    album/album_artist whenever the file's own identity disagrees with the
    folder it is going into (the pipeline record is authoritative for which
    album a download belongs to), and year when the file lacks one. `stem` is
    the file's basename without extension: main.py's read_tags falls back to
    it as the title when the tag is missing, so a title equal to the stem is
    treated as bare, not as a real tag.
    """
    out = {}
    t = t or {}
    title = t.get("title")
    if (not title or (stem and title == stem)) and m.get("title"):
        out["title"] = m["title"]
    if not t.get("artist") and m.get("artists"):
        out["artists"] = m["artists"]
    cur_aa = _fold(t.get("album_artist")) or _fold(t.get("artist"))
    if _fold(t.get("album")) != _fold(folder_album) or cur_aa != _fold(folder_artist):
        out["album"] = folder_album
        out["album_artist"] = folder_artist
    if not t.get("year") and m.get("year"):
        out["year"] = m["year"]
    return out


# --- the move ---------------------------------------------------------------

def find_download_files(dl_dir):
    """Yield every audio file under a completed slskd download, skipping the
    needs-attention dir (files parked there are not re-scanned every run)."""
    if not dl_dir.is_dir():
        return
    for root, _dirs, files in os.walk(dl_dir):
        if os.path.basename(root) == NEEDS_ATTENTION:
            continue
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


# Cover-ish names the player's folder_art()/FOLDER_ART_RE trusts, so a cover
# carried into an album dir is actually picked up by the player.
COVER_RE = re.compile(r"^(cover|folder|front|albumart.*)\.(jpe?g|png|webp|gif|bmp)$", re.I)


def carry_cover(dl_dir, dest_dir, dry_run=False):
    """Move a cover image downloaded beside the audio into the album dir, if
    the album lacks one and the downloads folder holds one.

    player-add.py moves only AUDIO files, so a cover.jpg slskd grabbed with the
    album is otherwise orphaned in the downloads dir and the player shows no
    art. Call after the move loop for each album's dest_dir."""
    if dest_dir is None or not dest_dir.is_dir():
        return False
    # Already has a cover the player would trust? nothing to do.
    if any(f.is_file() and COVER_RE.match(f.name)
           for f in dest_dir.iterdir()):
        return False
    # Look for an orphaned cover in the downloads dir (same relative folder).
    d = str(dest_dir)
    for root, _dirs, files in os.walk(dl_dir):
        if os.path.basename(root) == NEEDS_ATTENTION:
            continue
        for name in files:
            if COVER_RE.match(name):
                src = Path(root) / name
                dest = dest_dir / safe_file(name)
                if dry_run:
                    print(f"  would carry cover {name} -> {dest}")
                    return True
                try:
                    shutil.move(str(src), str(dest))
                    print(f"  carried cover    {name} -> {dest_dir.name}/")
                    return True
                except OSError:
                    pass
    return False



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

    con = P.open_db()
    index = build_album_index(con)
    mbid_dirs = load_mbid_dirs()
    meta = load_meta(Path(args.meta_dir))
    moved = 0
    skipped = 0
    parked = 0
    failed = 0
    moved_dest_dirs = set()

    for src in sorted(find_download_files(dl_dir)):
        t = P.read_tags(str(src))
        m = meta.get(os.path.basename(str(src)))
        tracked = bool(m and (m.get("album_artist") or m.get("album")))

        if tracked and m is not None:
            # The pipeline knows which album this download was queued for.
            aa = m.get("album_artist") or m.get("artists") or "Unknown Artist"
            alb = m.get("album") or "Unknown Album"
            dest_dir, folder_artist, folder_album = resolve_dest(
                root, aa, alb, index, mbid_dirs, m.get("album_ref", ""))
            to_write = meta_for_file(t, m, folder_artist, folder_album,
                                     stem=src.stem)
            if to_write:
                if args.dry_run:
                    print(f"  would tag       {src.name} "
                          f"({', '.join(sorted(to_write))})")
                else:
                    print(f"  tagged          {src.name} "
                          f"({', '.join(sorted(to_write))})")
                    try:
                        fill_tags(src, to_write)
                        t = P.read_tags(str(src))
                    except Exception as e:
                        print(f"    ! tag failed: {e}")
            artist = folder_artist or aa
            album = folder_album or alb
        elif t and t.get("artist") and t.get("title") and t.get("album"):
            # Not from this pipeline (a hand drop / the slsk app) but the file
            # can place itself by its own tags, as always.
            artist = t.get("artist")
            album = t.get("album")
            dest_dir = root / safe_name(artist, "Unknown Artist") \
                / safe_name(album, "Unknown Album")
            folder_artist = folder_album = None
        else:
            # No pipeline record and no usable tags: the file's album is not
            # knowable. Park it where it is visible instead of silently
            # inventing "Unknown Artist/Unknown Album" in the library.
            parked += 1
            if args.dry_run:
                print(f"  would park      {src} -> {dl_dir.name}/"
                      f"{NEEDS_ATTENTION}/ (no pipeline record, no usable tags)")
            else:
                dest = dl_dir / NEEDS_ATTENTION / src.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    dest = dest.with_name(dest.stem + ".dup" + src.suffix)
                shutil.move(str(src), str(dest))
                for p in prune_empty_dirs(dl_dir, src):
                    print(f"  pruned empty    {dl_dir.name}/{p.relative_to(dl_dir)}")
                print(f"  parked          {src.name} -> {dl_dir.name}/"
                      f"{NEEDS_ATTENTION}/ (no pipeline record, no usable tags)")
            continue

        dest = dest_dir / safe_file(src.name)
        if dest.exists():
            if not args.dry_run:
                print(f"  skip (exists)   {dest}")
            skipped += 1
            continue
        if args.dry_run:
            print(f"  would move      {src} -> {dest}")
        else:
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dest))
                moved_dest_dirs.add(dest_dir)
            except OSError as e:
                # one unmovable file must not starve the rest of the batch
                failed += 1
                print(f"  ! move failed   {src.name} -> {dest}: {e}")
                continue
            for p in prune_empty_dirs(dl_dir, src):
                print(f"  pruned empty    {dl_dir.name}/{p.relative_to(dl_dir)}")
            print(f"  moved           {src.name} -> {root.name}/{safe_name(artist, 'Unknown Artist')}/{safe_name(album, 'Unknown Album')}/")
        moved += 1

    # Carry each album's cover art into place — audio moves but the cover.jpg
    # slskd grabbed beside it is otherwise orphaned (and the player shows no art).
    for dest_dir in sorted(moved_dest_dirs):
        carry_cover(dl_dir, dest_dir, dry_run=args.dry_run)

    print(f"\n{moved} download(s) imported into {root}" + ("" if args.dry_run else f"; skipped {skipped} already present" if skipped else "") + (f"; {failed} failed" if failed else ""))
    if parked:
        print(f"  {parked} file(s) parked in {dl_dir.name}/{NEEDS_ATTENTION}/ "
              f"-- no pipeline record and no usable tags; fix by hand")
    if args.dry_run:
        print("(--dry-run: nothing changed)")
        return

    # --- rescan: mirror main.py's Scanner so the moved tracks land in library.db
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
