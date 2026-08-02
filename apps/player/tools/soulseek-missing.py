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
import re
import shutil
import sqlite3
import subprocess
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
# Rejected-download transfer ids this pipeline has already re-sourced. Once a
# rejection is acted on it is recorded here so a transfer that lingers in
# slskd's list never re-triggers a re-source on every poll.
RESCUED_FILE = os.path.join(DUMP_DIR, "soulseek-rescued.json")
# slskd drops completed downloads here; this script queues them, player-add.py
# (the import step) moves them into the library and rescans.
DOWNLOAD_DIR = os.path.expanduser("~/.local/share/slskd/downloads")
PLAYER_ADD = str(Path(__file__).resolve().parent / "player-add.py")

# A Soulseek file whose length differs from the target by more than this is
# probably a different edit, not a source copy worth downloading.
DURATION_TOLERANCE = 12.0  # seconds, matches spotify-missing.py
# How long to wait (in seconds) for a search to finish. slskd always
# terminates a search on its own ("Completed, TimedOut"/"ResponseLimitReached"),
# so this is only a backstop against a hung search; a healthy one returns
# well inside it. Must exceed the slowest real search (measured 18-38s),
# which is why the old 20s default was wrong: it expired while /responses
# was still empty and recorded a false "no match".
DEFAULT_SEARCH_TIMEOUT = 90
# How many tracks to search per run, so a headless run can't spam the network
# with all 2,000+ missing tracks at once. Raise with --limit / --all.
DEFAULT_LIMIT = 5

# Bias against enqueueing many files from the SAME peer in one run. slskd
# serializes downloads from one peer over a single connection (the Soulseek
# protocol grants one upload slot per user), so a batch that piles several
# tracks on the same peer -- common when an album or single-artist set lives on
# one user's share -- lines them up behind that one slot instead of fanning out
# across distinct peers toward global.download.slots (pinned to 50). This caps
# how many files a single peer may carry from one run; a track that is only
# offered by an already-capped peer is still enqueued there, because the bias
# is a tiebreaker and never refuses the only source.
MAX_ENQUEUES_PER_PEER = 2

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


def load_rescued(path):
    """Rejected-download transfer ids this pipeline has already re-sourced,
    so a rejection lingering in slskd's list is only acted on once."""
    try:
        with open(path) as f:
            return set(json.load(f).get("handled", []))
    except (OSError, ValueError):
        return set()


def save_rescued(path, ids):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"handled": sorted(ids)}, f)
    os.replace(tmp, path)


def track_key(row):
    return row.get("spotify_id") or row.get("isrc") or (
        f"{row.get('artists','')}||{row.get('title','')}")


def player_python():
    """The player's python env (mutagen + PySide6), so the import step can
    import main.py's read_tags/open_db/rebuild_albums. Resolved the same way
    the runbook does: read the `player` wrapper and grep the env path out of
    it. Falls back to `python3` (book's system python has these dnf'd)."""
    p = shutil.which("player")
    if p:
        try:
            text = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            text = ""
        m = re.search(r"/nix/store/[^\" ]+-env/bin/python3[0-9.]*", text)
        if m:
            return m.group(0)
    return "python3"


def import_downloads(import_step):
    """Move completed slskd downloads into aud/ and rescan, via player-add.py.

    This is the step the trailing print used to describe but never take: the
    player only sees a track once it is moved into the library dir and
    rescanned. Best-effort — a failure here is reported, not fatal to the
    search/enqueue work already done."""
    if not import_step:
        print("  (--no-import: skipping the move-into-library step)")
        return
    if not os.path.isdir(DOWNLOAD_DIR):
        print("  (no slskd downloads dir yet; nothing to import)")
        return
    if not os.path.exists(PLAYER_ADD):
        print(f"  ! import step missing: {PLAYER_ADD}")
        return
    py = player_python()
    print(f"\nimporting completed downloads into the library via {os.path.basename(PLAYER_ADD)}:")
    try:
        r = subprocess.run(
            [py, PLAYER_ADD, "--downloads-dir", DOWNLOAD_DIR, "--meta-dir", DUMP_DIR],
            capture_output=True, text=True)
    except OSError as e:
        print(f"  ! could not run the import step: {e}")
        return
    sys.stdout.write("  " + r.stdout.replace("\n", "\n  "))
    if r.stdout:
        sys.stdout.write("\n")
    if r.returncode != 0:
        sys.stderr.write("  ! import step failed:\n")
        sys.stderr.write("  " + (r.stderr or "").replace("\n", "\n  ") + "\n")



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

def pick_candidate(responses, artists, title, want_ms, skip_users=(),
                   avoid_users=()):
    """From slskd search responses, choose the best (user, filename, size).
    Keeps files whose name matches artist+title and whose length agrees with
    the target, then prefers the closest length and the highest bitrate.
    Files from a peer in `skip_users` (one that has just rejected/errored a
    download this run) are never chosen, so a re-sourced track lands on a
    different source rather than the one that refused it. Files from a peer in
    `avoid_users` (one already carrying MAX_ENQUEUES_PER_PEER files this run)
    are de-prioritized so a batch fans out across distinct peers -- but the
    bias only breaks ties, so a file offered solely by an already-capped peer
    is still picked rather than refused.
    """
    best = None
    best_score = None
    for resp in responses or []:
        user = resp.get("username", "")
        if user in skip_users:
            continue
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
            # lower (delta, -bitrate, avoid, not-free) is better
            #   avoid:   this peer is already carrying MAX_ENQUEUES_PER_PEER
            #            files this run -> prefer a fresh peer, so a batch does
            #            not serialize behind one peer's single upload slot
            #   not-free: a peer advertising a free upload slot starts now
            #            instead of sitting "Queued, Remotely"
            score = (delta, -bitrate,
                     0 if user not in avoid_users else 1,
                     0 if free else 1)
            if best_score is None or score < best_score:
                best_score = score
                best = (user, fn, f.get("size"))
    return best


# slskd's own "Failed" terminal set (TransferStateCategories.Failed): a
# download reached a terminal state but the file never arrived. Every one
# renders as a "Completed, <reason>" composite -- the familiar one being
# "Completed, Rejected", where the peer accepted the request then refused the
# actual transfer (often "Transfer rejected: Banned"), so the track never lands
# on disk. A state carrying any of these reason tokens is never a success.
FAILED_TRANSFER_TOKENS = ("Rejected", "Cancelled", "TimedOut", "Errored",
                          "Aborted")


def iter_transfers(dl):
    """Yield every file-level download transfer from a /transfers/downloads
    response, which nests as username -> directories -> files. Each file object
    already carries its own username, filename, state and (on failure)
    exception, so flattening the nesting is all that is needed to reach them."""
    for entry in dl or []:
        for directory in entry.get("directories") or []:
            for f in directory.get("files") or []:
                yield f


def transfer_failed(f):
    """True when a download ended in a state where the file never arrived
    (slskd's Failed set: rejected / cancelled / timed out / errored / aborted).
    These are the transfers that would otherwise leave a track silently
    missing while the poller kept counting it as queued."""
    st = f.get("state") or ""
    return any(tok in st for tok in FAILED_TRANSFER_TOKENS)


def alive_transfers(dl):
    """(user, filename) pairs still worth guarding against re-queueing.

    A transfer in a failed terminal state (rejected / errored / cancelled /
    timed out / aborted) never landed on disk and is exactly what the rescue
    re-sources -- leaving it in this set would make the never-re-queue guard
    re-mark the track "queued" pointing at the dead transfer without ever
    enqueueing a fresh one. So only transfers that might still produce a file
    (queued / in-progress / succeeded) belong here.
    """
    out = set()
    for tr in iter_transfers(dl):
        user, filename = tr.get("username"), tr.get("filename")
        if user and filename and not transfer_failed(tr):
            out.add((user, filename))
    return out


def rescue_rejected(rows, state, rescued_ids, dl, dry_run):
    """Re-source every missing track whose enqueued download ended failed
    (rejected / cancelled / errored / aborted -- slskd reports these as a
    "Completed, <reason>" state with bytesTransferred 0).

    For each failed transfer that maps back to a track still on the work list
    (matched by the same artist/title folding the search uses, since the
    recorded source for a track often diverges from a stale rejected one), we:

      - remember its peer's username so this run's searches never pick another
        file from a peer that just refused us, and
      - drop the "queued" marker for the matching track(s) so the normal pass
        re-searches them and re-enqueues the same missing track from a
        different source.

    Each failed transfer is acted on once per its stable `id` (recorded in
    `rescued_ids`, persisted across runs) -- that is what keeps a rejected
    transfer that lingers in slskd's list from re-triggering on every poll.

    Never mutates `state` under --dry-run (a preview must not unqueue a real
    download); the returned count still reports what a real run would
    re-source, and the peer blocklist always applies.

    Returns (blocked_user_set, n_would_resource). Mutates `state` and
    `rescued_ids`; the caller persists `rescued_ids` only for a real run."""
    blocked = set()
    resourced = 0
    for f in iter_transfers(dl):
        if not transfer_failed(f):
            continue
        user = f.get("username")
        filename = f.get("filename")
        if not (user and filename):
            continue
        # a transfer is keyed by its stable id, falling back to user+filename
        # for the (unlikely) transfer that has none
        key = f.get("id") or f"{user}\x00{filename}"
        if key in rescued_ids:
            continue  # already acted on this exact rejection
        # does this failed transfer map to a track still on the work list?
        base = os.path.basename(filename)
        matches = [r for r in rows
                   if file_matches(base, r.get("artists", ""),
                                   r.get("title", ""))]
        if not matches:
            continue
        # Re-source each currently-queued track this failed transfer maps to.
        # Only count the rejection as HANDLED (and only block the refusing
        # peer) once at least one queued track was actually re-sourced --
        # recording the dedup for a transfer whose matching track is not
        # currently "queued" (nofind/error, no state entry, already dropped)
        # would burn the id and the peer permanently with nothing re-sourced,
        # and every later poll would skip the same lingering transfer before
        # it could ever act once the track is queued again.
        acted = 0
        for row in matches:
            sid = track_key(row)
            rec = state.get(sid)
            if rec and rec.get("status") == "queued":
                acted += 1
                resourced += 1
                if not dry_run:
                    del state[sid]
        if acted:
            blocked.add(user)
            rescued_ids.add(key)
    return blocked, resourced


def scan_downloaded_names():
    """Set of folded basenames of files sitting in the slskd downloads dir.

    A completed download sits here only until the import step (player-add.py)
    moves it into aud/ and rescans. Before that it is a real file that must not
    be re-downloaded, so it counts as "handled" for reconciliation.
    """
    out = set()
    if not os.path.isdir(DOWNLOAD_DIR):
        return out
    for root, _dirs, files in os.walk(DOWNLOAD_DIR):
        for fn in files:
            f = trackmatch.fold(fn)
            if f:
                out.add(f)
    return out


def reconcile_orphaned_queued(state, alive, present, rows, downloaded,
                              dry_run):
    """Drop the 'queued' marker from tracks that state says are queued but that
    no longer have a working transfer and have not landed, so the normal pass
    re-searches and re-queues them.

    A track is marked 'queued' the moment it is enqueued, but slskd keeps its
    transfer list in memory: a daemon restart, or a failed transfer that
    rescue_rejected could not act on before clear_handled_failures removed it,
    leaves the transfer gone while state still says 'queued'. wanted() then
    skips the track forever, so it is never re-searched or re-downloaded even
    though it is still missing -- a class of silently lost tracks that
    accumulates over runs. Reconciliation re-queues exactly those: the track is
    still on the work list, is not in the live library, has no live transfer,
    and has no completed file waiting in the downloads dir. Idempotent: a live
    transfer, a landed file, or a landed library row always keeps its marker.

    Never mutates state under --dry-run (a preview must not unqueue a real
    download). Returns the number that would be re-queued.
    """
    rows_by_id = {r.get("spotify_id"): r for r in rows if r.get("spotify_id")}
    reconciled = 0
    for sid, rec in list(state.items()):
        if rec.get("status") != "queued":
            continue
        if (rec.get("user"), rec.get("filename")) in alive:
            continue  # a transfer is still working on it
        row = rows_by_id.get(sid)
        if row is None:
            continue  # no longer on the work list; nothing to re-queue
        if present and any(k in present for k in
                           trackmatch.keys(row.get("artists", ""),
                                           row.get("title", ""))):
            rec["status"] = "have"  # landed; state was just stale
            continue
        # Soulseek peer paths use backslashes; os.path.basename on Linux only
        # splits on "/", so normalize separators first to reach the file name
        # before comparing against the slskd downloads dir.
        fn = str(rec.get("filename", "")).replace("\\", "/")
        base = trackmatch.fold(os.path.basename(fn))
        if base and base in downloaded:
            continue  # completed file awaiting import; do not re-download
        if not dry_run:
            del state[sid]
        reconciled += 1
    return reconciled


def clear_handled_failures(base, api_key, dl, dry_run):
    """DELETE every failed-terminal download from slskd, so errored rows stop
    lingering in the download list the webapp reads.

    rescue_rejected() re-sources failed tracks (drops the queued marker so the
    normal pass enqueues a fresh download from a different peer) - but the
    errored *row* itself never leaves slskd, because slskd keeps
    completed/failed transfers until explicitly removed. A transfer in a failed
    terminal state can never produce a file, so removing its row is pure
    cleanup: the re-source (not the lingering row) is what recovers the track.

    Every failed-terminal transfer is cleared, not just the ones the rescue
    handled this run. A failure whose track is currently nofind/error, or whose
    recorded source has since diverged, is exactly the row that would otherwise
    accumulate in the downloads view forever -- and clearing it loses nothing,
    because the track's recovery is driven by the work list and the state file,
    not by this row. This runs AFTER rescue_rejected(), so the same run has
    already seen every failed transfer it needed to re-source before their rows
    are cleared.

    slskd's DELETE downloads/{username}/{id} only removes the row from the
    tracked store (what the webapp reads) when ?remove=true is passed; without
    it the call merely "cancels" an already-failed transfer (a no-op) and the
    row stays visible -- which is why this used to clear nothing.

    Best-effort: a failed DELETE is reported, not fatal. No-op under --dry-run
    (a preview must not mutate the live daemon). Returns the number cleared."""
    cleared = 0
    for f in iter_transfers(dl or []):
        if not transfer_failed(f):
            continue
        user = f.get("username")
        tid = f.get("id")
        if not (user and tid):
            continue
        if dry_run:
            cleared += 1
            continue
        try:
            http("DELETE",
                 f"{base}/api/v0/transfers/downloads/"
                 f"{urllib.parse.quote(str(user), safe='')}/"
                 f"{urllib.parse.quote(str(tid), safe='')}?remove=true",
                 api_key)
            cleared += 1
        except SlskdError as e:
            print(f"    ! could not clear handled failed transfer {tid}: {e}")
    return cleared


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
    ap.add_argument("--no-import", dest="import_step", action="store_false",
                    default=True,
                    help="skip the move-into-library + rescan import step "
                         "(default: run it)")
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
    rescued_ids = load_rescued(os.path.join(args.dump_dir,
                                            os.path.basename(RESCUED_FILE)))

    # --- 1.5 re-source downloads the peer rejected/cancelled/errored ---------
    # The /transfers/downloads response nests (username -> directories ->
    # files); flatten it into every individual download so we can both rebuild
    # the never-re-queue guard (which previously walked only the top level,
    # saw no `filename`, and silently matched nothing) and notice transfers
    # that ended failed. Both are best-effort: a failed API call degrades to
    # no re-queue protection and no rescue, never a crash.
    dl = None
    try:
        dl = http("GET", f"{base}/api/v0/transfers/downloads", api_key)
    except SlskdError:
        pass
    queued_files = alive_transfers(dl)
    blocked_users, resourced = rescue_rejected(rows, state, rescued_ids, dl,
                                               args.dry_run)
    if resourced:
        print(f"  re-sourcing {resourced} track(s) whose download ended "
              f"rejected/cancelled/errored")
        if not args.dry_run:
            save_state(state_path, state)
            save_rescued(os.path.join(args.dump_dir,
                                      os.path.basename(RESCUED_FILE)),
                         rescued_ids)
    if blocked_users:
        print(f"  avoiding {len(blocked_users)} peer(s) that refused a download "
              f"this run")

    # Now every errored/failed row can be cleared from slskd itself, so an
    # errored transfer does not linger in the downloads view forever (see
    # clear_handled_failures). Runs after rescue_rejected so the same run has
    # already seen the failures it needed to re-source before they are removed.
    cleared = clear_handled_failures(base, api_key, dl, args.dry_run)
    if cleared:
        print(f"  cleared {cleared} errored transfer(s) from slskd"
              + (" [dry-run]" if args.dry_run else ""))

    # A track marked "queued" whose transfer has since vanished (daemon
    # restart, or a failure cleared before rescue could act) would otherwise
    # be skipped forever by wanted(). Re-queue exactly those still-missing
    # orphans so the normal pass re-searches them (see
    # reconcile_orphaned_queued). Runs after rescue + clear so this only
    # catches tracks neither pass already recovered.
    downloaded = scan_downloaded_names()
    reconciled = reconcile_orphaned_queued(
        state, queued_files, present, rows, downloaded, args.dry_run)
    if reconciled:
        print(f"  re-queued {reconciled} track(s) marked 'queued' with no "
              f"live transfer"
              + (" [dry-run]" if args.dry_run else ""))
        if not args.dry_run:
            save_state(state_path, state)

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

    # --- 2. search and enqueue ----------------------------------------------
    changed = False
    processed = 0
    # How many files each peer has been enqueued this run, so pick_candidate can
    # de-prioritize a peer that is already carrying MAX_ENQUEUES_PER_PEER and
    # keep a batch fanned out across distinct peers instead of piled on one.
    run_user_counts = {}
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

            # Wait for the search to finish, then read its responses.
            # slskd's /responses endpoint stays EMPTY until the search
            # reaches a Completed state, so polling it against a wall-clock
            # deadline records a slow-but-successful search as a false
            # "no match" (measured: Daft Punk fills at 9s, obscure tracks at
            # 18-38s, all beyond the old 20s window). Poll the search
            # object's own state instead; slskd terminates every search on
            # its own, so search_timeout is only a backstop, not the wait.
            sstate = ""
            deadline = time.time() + args.search_timeout
            while time.time() < deadline:
                try:
                    obj = http("GET", f"{base}/api/v0/searches/{sid_search}",
                               api_key) or {}
                    sstate = obj.get("state", "") or ""
                except SlskdError:
                    break
                if "Completed" in sstate:
                    break
                time.sleep(2)
            responses = []
            if "Completed" in sstate:
                # The search is over; everything it found is now visible.
                try:
                    responses = http("GET",
                                     f"{base}/api/v0/searches/{sid_search}/responses",
                                     api_key) or []
                except SlskdError:
                    responses = responses or []

            cand = pick_candidate(responses, artists, title, want_ms,
                                  blocked_users,
                                  {u for u, c in run_user_counts.items()
                                   if c >= MAX_ENQUEUES_PER_PEER})
        except SlskdError as e:
            print(f"    ! search failed: {e}")
            state[sid] = {"spotify_id": row.get("spotify_id", ""),
                          "isrc": row.get("isrc", ""), "status": "error",
                          "user": "", "filename": f"ERR {e}", "when": time.strftime("%Y-%m-%d %H:%M:%S")}
            changed = True
            save_state(state_path, state)
            continue

        if not cand:
            print("    no matching file found")
            state[sid] = {"spotify_id": row.get("spotify_id", ""),
                          "isrc": row.get("isrc", ""), "status": "nofind",
                          "user": "", "filename": "", "when": time.strftime("%Y-%m-%d %H:%M:%S")}
            changed = True
            save_state(state_path, state)
            continue

        user, filename, size = cand
        if already_handled(user, filename):
            print(f"    already queued from {user}: {filename}")
            state[sid] = {"spotify_id": row.get("spotify_id", ""),
                          "isrc": row.get("isrc", ""), "status": "queued",
                          "user": user, "filename": filename,
                          "when": time.strftime("%Y-%m-%d %H:%M:%S")}
            changed = True
            save_state(state_path, state)
            continue

        if args.dry_run:
            print(f"    [dry-run] would queue from {user}: {filename}"
                  f" (size {size or '?'})")
            state[sid] = {"spotify_id": row.get("spotify_id", ""),
                          "isrc": row.get("isrc", ""), "status": "picked",
                          "user": user, "filename": filename,
                          "when": time.strftime("%Y-%m-%d %H:%M:%S")}
            run_user_counts[user] = run_user_counts.get(user, 0) + 1
        else:
            try:
                http("POST", f"{base}/api/v0/transfers/downloads/{urllib.parse.quote(user, safe='')}",
                     api_key, [{"filename": filename, "size": size}])
                print(f"    queued from {user}: {filename}")
                queued_files.add((user, filename))
                run_user_counts[user] = run_user_counts.get(user, 0) + 1
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
        save_state(state_path, state)

        # be polite to the network between searches
        time.sleep(1)

    if changed:
        save_state(state_path, state)

    print(f"\ndone. {budget} track(s) processed this run.")
    print(f"  state -> {state_path}")

    # The player only sees a track once it is moved into aud/ and rescanned —
    # previously this was a note for a human to do by hand; now the import step
    # does it. Skipped in --dry-run, which must not touch the filesystem.
    if not args.dry_run:
        import_downloads(args.import_step)


if __name__ == "__main__":
    main()
