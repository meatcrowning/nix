#!/usr/bin/env python3
"""Sweep the library for TIMESTAMPED lyrics: find what is missing, look it up
on LRCLIB, and embed it in the files.

Same resolution logic the running player uses (player/lyrics.py), just applied
to every track at once instead of one-at-a-time as things play.

    tools/lyrics-sync.py                    # dry run over the whole library
    tools/lyrics-sync.py --write            # actually embed what it finds
    tools/lyrics-sync.py --write --limit 50 # a small first bite
    tools/lyrics-sync.py --report           # what's in the DB now, no network

DRY RUN IS THE DEFAULT. Nothing touches a file without --write, and every
intended write is appended to ~/.local/state/player/tagwrites.log first, the
same journal the app's rating/playcount writer uses.

Resumable: results are cached in the player DB's `lyrics` table, so a second
run skips everything already resolved and only retries the honest gaps.
`--retry-missing` re-asks for those too (use after fixing tags).

Tracks that already carry synced lyrics in their own tags are skipped outright
— this never overwrites lyrics that are already there unless --force.
"""
import argparse
import json
import os
import queue
import sqlite3
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lyrics as L  # noqa: E402

DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "player"
STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "player"
DB_PATH = DATA / "library.db"
JOURNAL = STATE / "tagwrites.log"


def open_db():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""CREATE TABLE IF NOT EXISTS lyrics (
                     track_id INTEGER PRIMARY KEY,
                     source TEXT, synced INTEGER, body TEXT, fetched_at REAL)""")
    return con


def journal(entry, status):
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        with open(JOURNAL, "a", encoding="utf-8") as f:
            f.write(json.dumps({**entry, "status": status}) + "\n")
    except OSError:
        pass


def player_running():
    try:
        import subprocess
        out = subprocess.run(["pgrep", "-af", "python3"], capture_output=True,
                             text=True).stdout
        return any("player/main.py" in ln for ln in out.splitlines())
    except Exception:
        return False


# ---------------------------------------------------------------------------

def report(con):
    total = con.execute("SELECT COUNT(*) c FROM tracks").fetchone()["c"]
    rows = con.execute("SELECT source, synced, COUNT(*) c FROM lyrics"
                       " GROUP BY source, synced").fetchall()
    print(f"library: {total} tracks")
    if not rows:
        print("  lyrics cache empty — nothing looked up yet")
        return
    print("  cached lyrics results:")
    for r in rows:
        kind = "synced" if r["synced"] else "plain "
        print(f"    {r['source']:<12} {kind}  {r['c']:>6}")
    n_sync = con.execute("SELECT COUNT(*) c FROM lyrics WHERE synced=1").fetchone()["c"]
    print(f"  timestamped: {n_sync} ({100.0 * n_sync / max(1, total):.1f}% of library)")


def embed_cached(con, args):
    """Second half of the two-phase run: take the synced lyrics already sitting
    in the DB and put them in the files, with no network at all.

    Why the split exists: looking 11k tracks up online is slow but completely
    harmless while music is playing, whereas rewriting tags under the running
    player is not. So the sweep can run any time, and this pass waits for the
    player to be closed."""
    if args.write and player_running() and not args.allow_running:
        sys.exit("player is running — close it first, or pass --allow-running.")

    sql = ("SELECT t.id, t.path, t.artist, t.title, l.body"
           "  FROM lyrics l JOIN tracks t ON t.id = l.track_id"
           " WHERE l.synced = 1 AND l.body != ''")
    params = []
    if args.album:
        sql += " AND t.album LIKE ?"
        params.append(args.album)
    rows = con.execute(sql, params).fetchall()

    todo = []
    for r in rows:
        if not os.path.exists(r["path"]):
            continue
        have, have_synced = L.read_embedded(r["path"])
        if have_synced and not args.force:
            continue                     # the file already has stamped lyrics
        todo.append(r)
    if args.limit:
        todo = todo[:args.limit]

    print(f"{len(rows)} tracks have synced lyrics cached; {len(todo)} files still lack them")
    if not args.write:
        print("MODE: dry run — pass --write to embed them")
        for r in todo[:20]:
            print(f"  would embed  {r['artist']} — {r['title']}")
        if len(todo) > 20:
            print(f"  … and {len(todo) - 20} more")
        return

    ok = fail = 0
    for i, r in enumerate(todo, 1):
        entry = {"path": r["path"], "lyrics": "synced", "chars": len(r["body"]),
                 "ts": time.time()}
        journal(entry, "writing")
        try:
            L.write_embedded(r["path"], r["body"])
            journal(entry, "written")
            ok += 1
        except Exception as e:
            journal(entry, f"error: {e}")
            fail += 1
            print(f"  !! {r['path']}: {e}", flush=True)
        if i % 100 == 0:
            print(f"  … {i}/{len(todo)} embedded", flush=True)
    print(f"\nembedded {ok} files" + (f", {fail} failed" if fail else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true",
                    help="embed found lyrics in the files (default: dry run)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N tracks")
    ap.add_argument("--jobs", type=int, default=4,
                    help="concurrent LRCLIB lookups (default 4; be kind, it's free)")
    ap.add_argument("--plain", action="store_true",
                    help="also embed unsynced lyrics when no synced version exists")
    ap.add_argument("--force", action="store_true",
                    help="re-resolve and overwrite even tracks that already have synced lyrics")
    ap.add_argument("--retry-missing", action="store_true",
                    help="re-ask LRCLIB for tracks previously cached as not-found")
    ap.add_argument("--embed-cached", action="store_true",
                    help="no network: embed synced lyrics already cached in the DB "
                         "into the files that still lack them")
    ap.add_argument("--report", action="store_true", help="print cache stats and exit")
    ap.add_argument("--allow-running", action="store_true",
                    help="proceed even if the player is running")
    ap.add_argument("--album", help="only tracks whose album matches this (SQL LIKE)")
    args = ap.parse_args()

    if not DB_PATH.exists():
        sys.exit(f"no library DB at {DB_PATH} — run the player once first")
    con = open_db()

    if args.report:
        report(con)
        return

    if args.embed_cached:
        embed_cached(con, args)
        return

    if args.write and player_running() and not args.allow_running:
        sys.exit("player is running — writing tags under it can disturb playback.\n"
                 "Close it, or pass --allow-running if you know the track being "
                 "played is not in scope.")

    # ---- pick the work ----
    sql = ("SELECT t.id, t.path, t.artist, t.title, t.album, t.duration,"
           "       l.source AS lsource, l.synced AS lsynced"
           "  FROM tracks t LEFT JOIN lyrics l ON l.track_id = t.id"
           " WHERE t.artist IS NOT NULL AND t.title IS NOT NULL")
    params = []
    if args.album:
        sql += " AND t.album LIKE ?"
        params.append(args.album)
    sql += " ORDER BY t.album_artist, t.album, t.disc, t.track"
    rows = con.execute(sql, params).fetchall()

    todo = []
    skipped_cached = 0
    for r in rows:
        if not args.force:
            src, syn = r["lsource"], r["lsynced"]
            if src and syn:                      # already have synced lyrics
                skipped_cached += 1
                continue
            if src == "instrumental":            # a real, permanent answer
                skipped_cached += 1
                continue
            if src == "none" and not args.retry_missing:
                skipped_cached += 1
                continue
        todo.append(r)
    if args.limit:
        todo = todo[:args.limit]

    print(f"{len(rows)} tracks in scope, {skipped_cached} already resolved, "
          f"{len(todo)} to check")
    if args.write:
        print("MODE: WRITE — found lyrics will be embedded in the files")
    else:
        print("MODE: dry run — nothing will be written (pass --write to embed)")
    if not todo:
        report(con)
        return

    # ---- resolve, concurrently ----
    q = queue.Queue()
    for r in todo:
        q.put(r)
    results = queue.Queue()
    stats = dict(synced=0, plain=0, instrumental=0, miss=0, error=0,
                 skipped_have=0, written=0, writefail=0, done=0)
    lock = threading.Lock()
    stop = threading.Event()

    def worker():
        cl = L.Lrclib(min_interval=0.12 * args.jobs)
        while not stop.is_set():
            try:
                r = q.get_nowait()
            except queue.Empty:
                return
            try:
                path = r["path"]
                # The file's own tags are the truth, not just the DB cache.
                have_text, have_synced = (L.read_embedded(path)
                                          if os.path.exists(path) else (None, False))
                if have_synced and not args.force:
                    results.put((r, {"source": "embedded", "synced": True,
                                     "text": have_text}, None))
                    continue
                # A sidecar .lrc beside the file is already timestamped.
                side = Path(path).with_suffix(".lrc")
                if side.exists():
                    try:
                        txt = side.read_text(encoding="utf-8", errors="replace")
                        if L.is_synced(txt):
                            results.put((r, {"source": "lrc", "synced": True,
                                             "text": txt}, None))
                            continue
                    except OSError:
                        pass
                got = cl.lookup(r["artist"], r["title"], r["album"], r["duration"])
                if got["instrumental"]:
                    results.put((r, {"source": "instrumental", "synced": False,
                                     "text": ""}, None))
                elif got["text"] and got["synced"]:
                    results.put((r, {"source": "lrclib", "synced": True,
                                     "text": got["text"]}, None))
                elif got["text"]:
                    results.put((r, {"source": "lrclib", "synced": False,
                                     "text": got["text"]}, None))
                else:
                    results.put((r, {"source": "none", "synced": False,
                                     "text": ""}, None))
            except L.LookupError_ as e:
                results.put((r, None, str(e)))
            except Exception as e:
                results.put((r, None, str(e)))
            finally:
                q.task_done()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, args.jobs))]
    for t in threads:
        t.start()

    t0 = time.time()
    pending = len(todo)
    try:
        while pending:
            try:
                r, got, err = results.get(timeout=1.0)
            except queue.Empty:
                if not any(t.is_alive() for t in threads):
                    break
                continue
            pending -= 1
            stats["done"] += 1
            if err is not None:
                # A network failure is NOT an answer — never cache it as one.
                stats["error"] += 1
                print(f"  !! {r['artist']} — {r['title']}: {err}", flush=True)
            else:
                src, syn, text = got["source"], got["synced"], got["text"]
                if src == "embedded":
                    stats["skipped_have"] += 1
                elif src == "instrumental":
                    stats["instrumental"] += 1
                elif src == "none":
                    stats["miss"] += 1
                elif syn:
                    stats["synced"] += 1
                else:
                    stats["plain"] += 1

                # Cache the verdict (including honest negatives).
                with lock:
                    con.execute("INSERT OR REPLACE INTO lyrics"
                                " (track_id, source, synced, body, fetched_at)"
                                " VALUES (?,?,?,?,?)",
                                (r["id"], src, 1 if syn else 0, text or "", time.time()))

                # Embed, if this is a fetched result worth putting in the file.
                worth = src == "lrclib" and text and (syn or args.plain)
                if worth:
                    entry = {"path": r["path"], "lyrics": "synced" if syn else "plain",
                             "chars": len(text), "ts": time.time()}
                    if not args.write:
                        journal(entry, "logged")
                    else:
                        journal(entry, "writing")
                        try:
                            L.write_embedded(r["path"], text)
                            journal(entry, "written")
                            stats["written"] += 1
                        except Exception as e:
                            journal(entry, f"error: {e}")
                            stats["writefail"] += 1
                            print(f"  !! write failed {r['path']}: {e}", flush=True)
                    mark = "W" if (args.write and syn) else "+"
                    print(f"  {mark} {'SYNCED' if syn else 'plain '} "
                          f"{r['artist']} — {r['title']}", flush=True)

            if stats["done"] % 50 == 0:
                with lock:
                    con.commit()
                rate = stats["done"] / max(0.001, time.time() - t0)
                eta = (len(todo) - stats["done"]) / max(0.001, rate)
                print(f"  … {stats['done']}/{len(todo)}  synced={stats['synced']} "
                      f"inst={stats['instrumental']} miss={stats['miss']} "
                      f"written={stats['written']}  {rate:.1f}/s  eta {eta / 60:.0f}m",
                      flush=True)
    except KeyboardInterrupt:
        print("\ninterrupted — committing what is done (safe to re-run)")
        stop.set()
    finally:
        with lock:
            con.commit()

    secs = time.time() - t0
    print(f"\nchecked {stats['done']} tracks in {secs / 60:.1f}m")
    print(f"  synced found     {stats['synced']}")
    print(f"  plain only       {stats['plain']}")
    print(f"  instrumental     {stats['instrumental']}  (permanent — not retried)")
    print(f"  no match         {stats['miss']}")
    print(f"  already had      {stats['skipped_have']}")
    print(f"  network errors   {stats['error']}  (not cached — retried next run)")
    if args.write:
        print(f"  EMBEDDED         {stats['written']}"
              + (f"   ({stats['writefail']} failed)" if stats["writefail"] else ""))
    else:
        print(f"  would embed      {stats['synced'] + (stats['plain'] if args.plain else 0)}"
              "   (re-run with --write)")
    print()
    report(con)
    con.close()


if __name__ == "__main__":
    main()
