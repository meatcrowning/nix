#!/usr/bin/env python3
"""Drive Soulseek downloads of the tracks missing from the local player
library, via the slskd HTTP API.

Reads the Soulseek work list -- ~/.local/share/spotify-dump/missing.tsv, from
spotify-missing.py -- and, for each track still not in the live player library,
submits one slskd search, picks the best matching file a peer offers, and
queues it for download.

Why not nicotine: slskd is already installed and *configured* here
(home/prog/slskd.nix pins the web API to loopback and reads the key from
~/.secrets/slskd-api-key), and its HTTP/JSON surface is a clean fit for a
one-shot script. It is meant to run as a daemon; this tool talks to it over
the loopback API and needs it running.

Every normalised-key decision here reuses ../pylib/trackmatch.py (the same
artist/title folding spotify-missing.py uses) so the "is this the same song"
question never drifts from the rest of the library code.

Requirements
  - slskd running and listening at --host (default http://127.0.0.1:5030).
  - slskd logged in to the Soulseek network (the generated slskd.yml only
    carries the web API key; the Soulseek username/password are a secret this
    repo does not hold, so a login must be configured before any actual
    download can start -- see home/prog/slskd.nix).
  - The local library db, snapshotted via sqlite's backup API (WAL-safe), to
    skip anything that has since arrived -- never re-download what the player
    already has.

Stdlib only (urllib), same rationale as dbsync.py / spotify-missing.py, so it
runs under a bare python3 on both hosts and adds no runtime dependency.
"""

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "pylib"))
import trackmatch  # noqa: E402

DUMP_DIR = os.path.expanduser("~/.local/share/spotify-dump")
LIBRARY_DB = os.path.expanduser("~/.local/share/player/library.db")
DEFAULT_TSV = os.path.join(DUMP_DIR, "missing.tsv")
DEFAULT_KEY_FILE = os.path.expanduser("~/.secrets/slskd-api-key")
DEFAULT_HOST = "http://127.0.0.1:5030"
STATE_FILE = os.path.join(DUMP_DIR, "soulseek-state.tsv")

# A Soulseek file whose length differs from the target by more than this is
# probably a different edit, not a source copy worth downloading.
DURATION_TOLERANCE = 12.0  # seconds, matches spotify-missing.py
# How long to wait (in seconds) for a search's responses to come back.
DEFAULT_SEARCH_TIMEOUT = 20
# How many tracks to search per run, so a headless run can't spam the network
# with all 2,000+ missing tracks at once. Raise with --limit / --all.
DEFAULT_LIMIT = 5

STATE_COLS = ["spotify_id", "isrc", "status", "user", "filename", "when"]
# status: have (already in library) / queued (search found + enqueued) /
#         picked (dry-run: would have queued) / nofind (search returned no match)
#         error (search/API failed)


class SlskdError(Exception):
    pass


def http(method, url, api_key, body=None, timeout=15):
    """Minimal urllib wrapper; returns parsed JSON (or raw text if not JSON)."""
    req = urllib.request.Request(url, method=method)
    req.add_header("X-API-Key", api_key)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:500]
        raise SlskdError(f"{method} {url} -> HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise SlskdError(f"{method} {url} -> {e.reason}") from None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return raw


def read_api_key(path):
    if not os.path.isfile(path):
        raise SlskdError(f"no API key at {path} -- run the slskd activation first")
    with open(path) as f:
        key = f.read().strip()
    if not key:
        raise SlskdError(f"empty API key at {path}")
    return key


def snapshot_db(src, dest):
    """Copy the library with sqlite's backup API. Never `cp` - the db is WAL
    and the player may be running against it."""
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    if os.path.exists(dest):
        os.remove(dest)
    dst_conn = sqlite3.connect(dest)
    with dst_conn:
        src_conn.backup(dst_conn)
    src_conn.close()
    dst_conn.close()


def library_keys(db_path):
    """Every (artist, title) folded key present in the live player library, so
    a track that has arrived since missing.tsv was written is never queued.
    The WAL-safe snapshot is transient: it lives in the dump dir for the
    duration of the run and is removed afterwards, so a run never drops a
    17 MB copy next to the live library."""
    import tempfile
    fd, snap = tempfile.mkstemp(prefix="soulseek-lib-", suffix=".db",
                                dir=DUMP_DIR)
    os.close(fd)
    try:
        snapshot_db(db_path, snap)
        conn = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
        keys = set()
        for artist, title in conn.execute("SELECT artist, title FROM tracks"):
            keys |= trackmatch.keys(artist, title)
        conn.close()
    finally:
        for p in (snap, snap + "-wal", snap + "-shm"):
            if os.path.exists(p):
                os.remove(p)
    return keys


def load_missing(tsv_path):
    """missing.tsv -> list of row dicts. Columns are the COLS from
    spotify-missing.py: artists, title, album, year, duration_ms, isrc,
    spotify_id, sources. The header is trusted; a shorter row pads to blanks
    rather than failing, so a hand-edited line degrades, not crashes."""
    with open(tsv_path) as f:
        header = f.readline().rstrip("\n").split("\t")
    rows = []
    with open(tsv_path) as f:
        next(f)
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t")
            fields = parts + [""] * (len(header) - len(parts))
            rows.append(dict(zip(header, fields)))
    return rows


def load_state(state_path):
    """state file -> {spotify_id: row}. Missing file is an empty dict."""
    if not os.path.isfile(state_path):
        return {}
    state = {}
    try:
        with open(state_path) as f:
            header = f.readline().rstrip("\n").split("\t")
            for line in f:
                parts = line.rstrip("\n").split("\t")
                fields = parts + [""] * (len(header) - len(parts))
                state[parts[0]] = dict(zip(header, fields))
    except (OSError, IndexError):
        return {}
    return state


def save_state(state_path, state):
    tmp = state_path + ".tmp"
    with open(tmp, "w") as f:
        f.write("\t".join(STATE_COLS) + "\n")
        for row in state.values():
            f.write("\t".join(str(row.get(c, "")) for c in STATE_COLS) + "\n")
    os.replace(tmp, state_path)


def track_key(row):
    return row.get("spotify_id") or row.get("isrc") or (
        f"{row.get('artists','')}||{row.get('title','')}")


def file_matches(basename, artists, title):
    """Does this peer file look like the track we want (artist + title)?

    A Soulseek filename is a *concatenated* string ("Artist - Title.mp3",
    "02 - Title.flac", "Title (Remix).mp3"), not a pair of aligned tag fields,
    so this is a folded substring test, not trackmatch's aligned _matches. A
    title must be substantial (>=4 folded chars) to avoid matching on a common
    word; the artist substring requirement pins it to the right recording.
    """
    if not basename:
        return False
    fb = trackmatch.fold(os.path.basename(str(basename)))
    if not fb:
        return False
    title_ok = any(
        (ft := trackmatch.fold(t)) and len(ft) >= 4 and ft in fb
        for t in trackmatch.title_variants(title)
    )
    if not title_ok:
        return False
    return any(
        (fa := trackmatch.fold(a)) and len(fa) >= 2 and fa in fb
        for a in trackmatch.artist_variants(artists)
    )


def duration_ok(file_len, want_ms):
    if not want_ms:
        return True  # no duration to compare; name match stands
    want = float(want_ms) / 1000.0
    got = file_len or 0.0
    if not got:
        return True
    return abs(got - want) <= DURATION_TOLERANCE


def pick_candidate(responses, artists, title, want_ms):
    """From slskd search responses, choose the best (user, filename, size).
    Keeps files whose name matches artist+title and whose length agrees with
    the target, then prefers the closest length and the highest bitrate."""
    best = None
    best_score = None
    for resp in responses or []:
        user = resp.get("username", "")
        free = bool(resp.get("hasFreeUploadSlot", False))
        for f in resp.get("files", []):
            fn = f.get("filename", "")
            base = os.path.basename(fn)
            if not file_matches(base, artists, title):
                continue
            if not duration_ok(f.get("length"), want_ms):
                continue
            length = f.get("length") or 0
            delta = abs(length - (float(want_ms or 0) / 1000.0)) if want_ms else 0
            bitrate = f.get("bitRate") or 0
            # lower (delta, -bitrate, not-free) is better
            score = (delta, -bitrate, 0 if free else 1)
            if best_score is None or score < best_score:
                best_score = score
                best = (user, fn, f.get("size"))
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tsv", default=DEFAULT_TSV, help="missing.tsv input")
    ap.add_argument("--db", default=LIBRARY_DB, help="live player library.db")
    ap.add_argument("--dump-dir", default=DUMP_DIR)
    ap.add_argument("--host", default=DEFAULT_HOST, help="slskd API base URL")
    ap.add_argument("--key-file", default=DEFAULT_KEY_FILE)
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                    help="max tracks searched this run (default %(default)s)")
    ap.add_argument("--all", action="store_true",
                    help="process every missing track (overrides --limit)")
    ap.add_argument("--retry", action="store_true",
                    help="ignore recorded handler state and re-search everything")
    ap.add_argument("--dry-run", action="store_true",
                    help="search but do not enqueue downloads")
    ap.add_argument("--search-timeout", type=int, default=DEFAULT_SEARCH_TIMEOUT,
                    help="seconds to wait for each search (default %(default)s)")
    ap.add_argument("--library-skip/--no-library-skip",
                    dest="library_skip", action="store_true", default=True,
                    help="re-check the live library and skip what is present")
    args = ap.parse_args()

    api_key = read_api_key(args.key_file)
    base = args.host.rstrip("/")
    state_path = os.path.join(args.dump_dir, "soulseek-state.tsv")

    # --- 0. is slskd up, and is it logged in? -------------------------------
    try:
        app = http("GET", f"{base}/api/v0/application", api_key)
    except SlskdError as e:
        raise SystemExit(
            f"slskd is not responding at {base}: {e}\n"
            "Start the daemon first (e.g. `slskd --no-logo` or via its service);"
            " downloads are driven through its API.") from None
    server = (app or {}).get("server", {})
    if not server.get("isLoggedIn"):
        raise SystemExit(
            "slskd is up but not logged in to the Soulseek network.\n"
            "Your Soulseek login is a secret this repo does not hold; add it as\n"
            "two one-line files ~/.secrets/slskd-username and\n"
            "~/.secrets/slskd-password (mode 600), then `sudo rebuild-top` (the\n"
            "slskd activation regenerates slskd.yml from them) and\n"
            "`systemctl --user restart slskd`, or the searches below would 409.")

    # --- 1. load the work list and skip what the live library now has --------
    rows = load_missing(args.tsv)
    print(f"{len(rows)} tracks in {args.tsv}")

    present = set()
    if args.library_skip:
        present = library_keys(args.db)
        print(f"  live library has {len(present)} lookup keys (skipping those)")
    else:
        print("  (--no-library-skip: not checking the live library)")

    state = {} if args.retry else load_state(state_path)

    def wanted(row):
        if row.get("spotify_id") not in state or args.retry:
            return True
        return False

    todo = [r for r in rows if wanted(r)]
    print(f"  {len(todo)} not yet handled by a previous run")

    already_have = 0
    net = []
    for r in todo:
        if present and any(k in present for k in
                           trackmatch.keys(r.get("artists", ""), r.get("title", ""))):
            already_have += 1
            state.setdefault(track_key(r), {
                "spotify_id": r.get("spotify_id", ""), "isrc": r.get("isrc", ""),
                "status": "have", "user": "", "filename": "-already-in-library-",
                "when": time.strftime("%Y-%m-%d %H:%M:%S")})
            continue
        net.append(r)
    if already_have:
        print(f"  {already_have} now in the library already; skipped\n")

    budget = len(net) if args.all else min(args.limit, len(net))
    if budget == 0:
        print("nothing to do.")
        return
    print(f"searching {budget} track(s); --dry-run is "
          f"{'ON' if args.dry_run else 'OFF'}\n")

    # --- 2. known slskd downloads, so we never re-queue the same file --------
    queued_files = set()
    try:
        dl = http("GET", f"{base}/api/v0/transfers/downloads", api_key)
        for t in dl or []:
            if t.get("username") and t.get("filename"):
                queued_files.add((t["username"], t["filename"]))
                if t.get("state") in ("Completed", "Succeeded"):
                    queued_files.add(("/grab/", t["filename"]))  # already grabbed
    except SlskdError:
        pass  # non-fatal; re-queue protection is best-effort

    changed = False
    processed = 0
    for row in net[:budget]:
        processed += 1
        sid = track_key(row)
        artists, title = row.get("artists", ""), row.get("title", "")
        want_ms = row.get("duration_ms")
        desc = f"({processed}/{budget}) {artists} - {title}"
        print(f"  {desc}")

        # Skip if this exact peer file is already queued / completed in slskd.
        def already_handled(user, filename):
            return (user, filename) in queued_files

        try:
            search_text = f"{artists} {title}".strip()[:512]
            resp = http("POST", f"{base}/api/v0/searches", api_key,
                        {"searchText": search_text})
            # slskd returns the search id; it can be a bare string or a dict.
            if isinstance(resp, dict):
                sid_search = resp.get("id", "")
            elif resp is None:
                raise SlskdError("search returned no id")
            else:
                sid_search = str(resp).strip('"')
            if not sid_search:
                raise SlskdError("search returned an empty id")

            # Collect responses until the search completes or we time out.
            responses = []
            deadline = time.time() + args.search_timeout
            while time.time() < deadline:
                try:
                    responses = http("GET",
                                     f"{base}/api/v0/searches/{sid_search}/responses",
                                     api_key) or []
                except SlskdError:
                    responses = responses or []
                    break
                if responses:
                    # got something; give it a moment to accumulate, then stop
                    time.sleep(2)
                    responses = http("GET",
                                     f"{base}/api/v0/searches/{sid_search}/responses",
                                     api_key) or []
                    break
                time.sleep(2)

            cand = pick_candidate(responses, artists, title, want_ms)
        except SlskdError as e:
            print(f"    ! search failed: {e}")
            state[sid] = {"spotify_id": row.get("spotify_id", ""),
                          "isrc": row.get("isrc", ""), "status": "error",
                          "user": "", "filename": f"ERR {e}", "when": time.strftime("%Y-%m-%d %H:%M:%S")}
            changed = True
            continue

        if not cand:
            print("    no matching file found")
            state[sid] = {"spotify_id": row.get("spotify_id", ""),
                          "isrc": row.get("isrc", ""), "status": "nofind",
                          "user": "", "filename": "", "when": time.strftime("%Y-%m-%d %H:%M:%S")}
            changed = True
            continue

        user, filename, size = cand
        if already_handled(user, filename):
            print(f"    already queued from {user}: {filename}")
            state[sid] = {"spotify_id": row.get("spotify_id", ""),
                          "isrc": row.get("isrc", ""), "status": "queued",
                          "user": user, "filename": filename,
                          "when": time.strftime("%Y-%m-%d %H:%M:%S")}
            changed = True
            continue

        if args.dry_run:
            print(f"    [dry-run] would queue from {user}: {filename}"
                  f" (size {size or '?'})")
            state[sid] = {"spotify_id": row.get("spotify_id", ""),
                          "isrc": row.get("isrc", ""), "status": "picked",
                          "user": user, "filename": filename,
                          "when": time.strftime("%Y-%m-%d %H:%M:%S")}
        else:
            try:
                http("POST", f"{base}/api/v0/transfers/downloads/{urllib.parse.quote(user, safe='')}",
                     api_key, [{"filename": filename, "size": size}])
                print(f"    queued from {user}: {filename}")
                queued_files.add((user, filename))
                state[sid] = {"spotify_id": row.get("spotify_id", ""),
                              "isrc": row.get("isrc", ""), "status": "queued",
                              "user": user, "filename": filename,
                              "when": time.strftime("%Y-%m-%d %H:%M:%S")}
            except SlskdError as e:
                print(f"    ! enqueue failed: {e}")
                state[sid] = {"spotify_id": row.get("spotify_id", ""),
                              "isrc": row.get("isrc", ""), "status": "error",
                              "user": user, "filename": f"ERR {e}",
                              "when": time.strftime("%Y-%m-%d %H:%M:%S")}
        changed = True

        # be polite to the network between searches
        time.sleep(1)

    if changed:
        save_state(state_path, state)

    print(f"\ndone. {budget} track(s) processed this run.")
    print(f"  state -> {state_path}")
    print("  downloads land in slskd's download dir"
          " (~/.local/share/slskd/downloads); the player only sees them once"
          " they are moved into aud/ and rescanned.")


if __name__ == "__main__":
    main()
