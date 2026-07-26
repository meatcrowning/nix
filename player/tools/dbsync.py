#!/usr/bin/env python3
"""Two-way merge of the player's metadata database between `top` and `air`.

    dbsync.py pull [--host top.local]     bring top's ratings/plays/lyrics here
    dbsync.py push [--host top.local]     send this machine's back
    dbsync.py sync [--host top.local]     pull, then push
    dbsync.py status [--host top.local]   what each side holds, no writes

Why this exists: air plays top's library over SMB (docs/air-library-share.md)
and the two machines each keep their own copy of the database. The audio and
the tags are shared; the *metadata the app writes* — play counts, ratings,
favourites, cached lyrics — is not, so it has to be reconciled.

Three rules the whole thing is built on:

1. **stdlib only.** This has to run under Fedora's system python on air, which
   has no PySide6 and no nix. `import sqlite3` and nothing else. It is also
   why this file is its own remote agent: both directions pipe THIS script to
   `python3 -` over ssh, so the same merge logic runs on both ends and neither
   machine has to have a matching checkout.

2. **Snapshot with sqlite's backup API, never `cp`.** The database is in WAL
   mode. Copying the file without its -wal sidecar is a torn read, and the
   player is usually running while this is.

3. **The merge key is `tracks.path`, never `id`.** ids are insertion-ordered
   rowids: the same track has different ids on the two machines the moment
   either scans anything the other hasn't. Paths are identical by construction
   — that is the entire point of mounting the share at the same absolute path.

And one rule about deletion: there is none. A row missing from one side means
"that machine has not seen this track", never "this track was removed". A
prune only ever happens in the app, against a mounted root it just walked.
"""
import argparse
import os
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_HOST = os.environ.get("PLAYER_SYNC_HOST", "top.local")


def db_path():
    data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data / "player" / "library.db"


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------

def ensure_columns(con):
    """Add the sync-only columns if this database predates them.

    Deliberately NOT a copy of main.py's open_db(): that clears the mtime cache
    when a `rescan` migration fires, and a tool has no business triggering an
    11k-file re-read of a library it may be reaching across SMB.
    """
    for table, col, decl in (("tracks", "meta_mtime", "REAL"),
                             ("lyrics", "attempts", "INTEGER DEFAULT 0")):
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        if not have:
            continue  # table itself missing — an empty/fresh db, nothing to merge
        if col not in have:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    con.commit()


def snapshot(src, dst):
    """Consistent copy of a live WAL database (sqlite's own backup API)."""
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=60)
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------

# Columns copied verbatim when a track is NEW to the destination. album_id is
# excluded on purpose: album ids are per-database rowids, and the app re-derives
# them from tags in rebuild_albums() on every scan.
NEW_TRACK_COLS = [
    "path", "mtime", "size", "title", "artist", "album", "album_artist",
    "track", "disc", "date", "year", "orig_year", "genre", "duration",
    "codec", "samplerate", "bitdepth", "rating", "favorite", "play_count",
    "meta_mtime", "added_at", "last_played", "has_art",
    "rg_track_gain", "rg_track_peak", "rg_album_gain", "rg_album_peak",
]

# A cached lyrics row's authority, high wins. "none" is the weakest thing that
# is still a result (nobody has them indexed, retry later); anything else is an
# answer. A row with a body outranks a verdict with none.
LYRIC_RANK = {"none": 1, "instrumental": 3, "instrumental-user": 3}


def _lyric_rank(row):
    if row["synced"]:
        return 4
    if row["body"]:
        return 2
    return LYRIC_RANK.get(row["source"] or "", 0)


def _num(v):
    return v if v is not None else -1.0


def merge(src_path, dst_path, dry_run=False, quiet=False):
    """Merge src INTO dst. Returns a stats dict. Never deletes."""
    con = sqlite3.connect(dst_path, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    con.row_factory = sqlite3.Row
    ensure_columns(con)

    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True, timeout=60)
    src.row_factory = sqlite3.Row
    has_meta = "meta_mtime" in {r[1] for r in src.execute("PRAGMA table_info(tracks)")}

    st = {"tracks_new": 0, "plays": 0, "rating": 0, "favorite": 0,
          "lyrics_new": 0, "lyrics_upd": 0}

    dst_tracks = {r["path"]: r for r in con.execute("SELECT * FROM tracks")}

    for s in src.execute("SELECT * FROM tracks"):
        d = dst_tracks.get(s["path"])
        if d is None:
            vals = []
            for c in NEW_TRACK_COLS:
                vals.append(s[c] if (c != "meta_mtime" or has_meta) else None)
            con.execute(
                f"INSERT INTO tracks ({','.join(NEW_TRACK_COLS)}) "
                f"VALUES ({','.join('?' * len(NEW_TRACK_COLS))})", vals)
            st["tracks_new"] += 1
            continue

        sets, args = [], []

        # play_count: max. Two machines each playing a track five times is ten
        # plays of it, but we cannot tell that from two numbers, and max() at
        # least never invents plays or loses a whole machine's history.
        if (s["play_count"] or 0) > (d["play_count"] or 0):
            sets.append("play_count=?")
            args.append(s["play_count"])
            st["plays"] += 1
        if _num(s["last_played"]) > _num(d["last_played"]):
            sets.append("last_played=?")
            args.append(s["last_played"])

        # rating/favorite: last writer wins, by meta_mtime. A NULL meta_mtime
        # is a value written before this column existed (or by a scan, from the
        # file's own tags) — it loses to any real timestamp, and when NEITHER
        # side has one we only fill in what the destination is missing rather
        # than guess.
        sm = s["meta_mtime"] if has_meta else None
        dm = d["meta_mtime"]
        if sm is not None and (dm is None or sm > dm):
            take_rating = s["rating"] != d["rating"]
            take_fav = bool(s["favorite"]) != bool(d["favorite"])
            if take_rating:
                sets.append("rating=?")
                args.append(s["rating"])
                st["rating"] += 1
            if take_fav:
                sets.append("favorite=?")
                args.append(1 if s["favorite"] else 0)
                st["favorite"] += 1
            if take_rating or take_fav:
                sets.append("meta_mtime=?")
                args.append(sm)
        elif sm is None and dm is None:
            if d["rating"] is None and s["rating"] is not None:
                sets.append("rating=?")
                args.append(s["rating"])
                st["rating"] += 1
            if not d["favorite"] and s["favorite"]:
                sets.append("favorite=?")
                args.append(1)
                st["favorite"] += 1

        if sets:
            args.append(d["id"])
            con.execute(f"UPDATE tracks SET {','.join(sets)} WHERE id=?", args)

    # ---- lyrics: keyed through the track path, since track ids differ ----
    try:
        src_lyr = list(src.execute(
            "SELECT t.path AS path, l.* FROM lyrics l JOIN tracks t ON t.id = l.track_id"))
    except sqlite3.Error:
        src_lyr = []
    if src_lyr:
        dst_ids = {r["path"]: r["id"] for r in con.execute("SELECT id, path FROM tracks")}
        dst_lyr = {r["track_id"]: r for r in con.execute("SELECT * FROM lyrics")}
        for s in src_lyr:
            tid = dst_ids.get(s["path"])
            if tid is None:
                continue  # track itself didn't merge (shouldn't happen; be safe)
            d = dst_lyr.get(tid)
            if d is None:
                con.execute(
                    "INSERT INTO lyrics (track_id, source, synced, body, fetched_at, attempts) "
                    "VALUES (?,?,?,?,?,?)",
                    (tid, s["source"], s["synced"], s["body"], s["fetched_at"],
                     s["attempts"] if "attempts" in s.keys() else 0))
                st["lyrics_new"] += 1
                continue
            sr, dr = _lyric_rank(s), _lyric_rank(d)
            better = sr > dr or (sr == dr and _num(s["fetched_at"]) > _num(d["fetched_at"]))
            if better:
                con.execute(
                    "UPDATE lyrics SET source=?, synced=?, body=?, fetched_at=? WHERE track_id=?",
                    (s["source"], s["synced"], s["body"], s["fetched_at"], tid))
                st["lyrics_upd"] += 1
            # attempts is a retry counter, so the bigger one is the true one
            # either way — never let a merge reset somebody's backoff.
            sa = (s["attempts"] if "attempts" in s.keys() else 0) or 0
            da = (d["attempts"] if "attempts" in d.keys() else 0) or 0
            if sa > da:
                con.execute("UPDATE lyrics SET attempts=? WHERE track_id=?", (sa, tid))

    if dry_run:
        con.rollback()
    else:
        con.commit()
    src.close()
    con.close()
    if not quiet:
        print(("dry-run: " if dry_run else "") + " ".join(f"{k}={v}" for k, v in st.items()),
              flush=True)
    return st


# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------

SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
REMOTE_TMP = "/tmp/player-dbsync-{}.db"


def _self_source():
    return Path(__file__).read_bytes()


def _remote(host, argv, stdin=None, check=True):
    """Run THIS script on `host` via `python3 -`, with argv appended."""
    cmd = SSH + [host, "python3 - " + " ".join(shlex.quote(a) for a in argv)]
    return subprocess.run(cmd, input=stdin if stdin is not None else _self_source(),
                          check=check, capture_output=True)


def _rsync(src, dst):
    subprocess.run(["rsync", "-z", "--inplace", "--partial", "-e", " ".join(SSH), src, dst],
                   check=True)


def _seedable(db):
    """True if the local database is absent or has no tracks table yet."""
    if not Path(db).exists() or Path(db).stat().st_size == 0:
        return True
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='tracks'"
        ).fetchone()[0] == 0
    finally:
        con.close()


def cmd_pull(args):
    remote_tmp = REMOTE_TMP.format("pull")
    _remote(args.host, ["snapshot", remote_tmp])
    with tempfile.TemporaryDirectory() as td:
        local = str(Path(td) / "remote.db")
        _rsync(f"{args.host}:{remote_tmp}", local)
        # First pull on a fresh machine SEEDS rather than merges. air must
        # never build its own database from scratch: the saved queue in
        # prefs.json is a list of track ids — insertion-ordered rowids — so a
        # locally-scanned database renumbers everything and the restored queue
        # silently points at different songs.
        if _seedable(args.db):
            if args.dry_run:
                print("dry-run: would seed local database from remote")
                return
            Path(args.db).parent.mkdir(parents=True, exist_ok=True)
            snapshot(local, str(args.db))
            print(f"seeded {args.db} from {args.host}", flush=True)
            return
        merge(local, str(args.db), dry_run=args.dry_run)


def cmd_push(args):
    remote_tmp = REMOTE_TMP.format("push")
    with tempfile.TemporaryDirectory() as td:
        local = str(Path(td) / "local.db")
        snapshot(str(args.db), local)
        _rsync(local, f"{args.host}:{remote_tmp}")
    # global flags go BEFORE the subcommand (argparse subparsers)
    out = _remote(args.host, (["--dry-run"] if args.dry_run else []) + ["merge", remote_tmp])
    sys.stdout.write(out.stdout.decode())


def cmd_sync(args):
    cmd_pull(args)
    cmd_push(args)


def _counts(con):
    q = lambda s: con.execute(s).fetchone()[0]  # noqa: E731
    return {
        "tracks": q("SELECT COUNT(*) FROM tracks"),
        "rated": q("SELECT COUNT(*) FROM tracks WHERE rating IS NOT NULL"),
        "faves": q("SELECT COUNT(*) FROM tracks WHERE favorite"),
        "plays": q("SELECT COALESCE(SUM(play_count),0) FROM tracks"),
        "lyrics": q("SELECT COUNT(*) FROM lyrics WHERE body IS NOT NULL AND body <> ''"),
    }


def cmd_status(args):
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    print("local ", _counts(con))
    con.close()
    try:
        out = _remote(args.host, ["counts"])
        print("remote", out.stdout.decode().strip())
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        err = getattr(e, "stderr", b"").decode().strip()
        print(f"remote unreachable ({args.host}){': ' + err if err else ''}")


def cmd_counts(args):
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    print(_counts(con))
    con.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--db", type=Path, default=None, help="local database (default: XDG)")
    ap.add_argument("--dry-run", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("pull", "push", "sync", "status", "counts"):
        sub.add_parser(name)
    p = sub.add_parser("snapshot")
    p.add_argument("out")
    p = sub.add_parser("merge")
    p.add_argument("src")
    p.add_argument("dst", nargs="?", default=None)

    args = ap.parse_args()
    if args.db is None:
        args.db = db_path()

    if args.cmd == "snapshot":
        snapshot(str(args.db), args.out)
        return
    if args.cmd == "merge":
        merge(args.src, args.dst or str(args.db), dry_run=args.dry_run)
        return
    {"pull": cmd_pull, "push": cmd_push, "sync": cmd_sync,
     "status": cmd_status, "counts": cmd_counts}[args.cmd](args)


if __name__ == "__main__":
    main()
