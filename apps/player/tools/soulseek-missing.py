#!/usr/bin/env python3
"""Drive Soulseek downloads of the tracks missing from the local player
library, via the slskd HTTP API.

Reads the Soulseek work list -- ~/.local/share/spotify-dump/missing.tsv, from
spotify-missing.py -- and, for each track still not in the live player library,
submits one slskd search, picks the best matching file a peer offers, and
queues it for download.

Two modes:
  * default -- one pass over a fixed batch (--limit / --all), then exit.
  * --watch -- keep the download pipe fed: poll slskd for how many transfers
    are still live and, whenever that falls below --low-water, search+enqueue
    up to --target, until the missing list is drained or the process is stopped
    (SIGINT/SIGTERM). Searching stays serialized (slskd 429s a second
    concurrent search); slskd's own 50 slots pull the transfers in parallel.

Duplicate downloads are guarded three ways: a single-instance flock so two
sweeps (timer + a manual run) never race and double-enqueue; a normalized
(caseless/unaccented, via trackmatch) dedup so the same recording is not grabbed
twice under a different spotify id, filename or peer; and a grab-time re-check of
the live library DB and slskd's downloads dir so a file that landed WHILE the
sweep ran is not re-fetched.

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
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
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
#
# This is also the real lever on download concurrency. The parallel transfer
# is slskd's (global.download.slots, pinned to 50): it pulls many downloads
# from distinct peers at once, and slskd rejects concurrent SEARCHES outright
# (HTTP 429 "Only one concurrent operation is permitted" -- measured
# 2026-08-01), so this loop must search one track at a time and the batch size
# is the only thing the sweep controls. The old default of 5 fed the 50-slot
# downloader a trickle, so a few same-peer tracks serialized behind that peer's
# single upload slot and it read as "only one download at a time". A real batch
# (this default, or --limit / --all) fills the parallel downloader with tracks
# spread across distinct peers, so several transfer at once.
DEFAULT_LIMIT = 40

# --- continuous ("keep the pipe fed") mode -------------------------------
# A single run searches a fixed batch and exits; unattended, the pool then
# drains to nothing while thousands of tracks stay missing (2026-08-02: 5
# frozen "Queued, Remotely" transfers, 0 in flight, ~3.5k still missing). The
# --watch loop instead holds the download pipe topped up: it polls slskd for
# how many transfers are still live (queued or downloading, per transfer_in_pipe)
# and, whenever that falls below WATCH_LOW_WATER, searches and enqueues fresh
# tracks until the live count reaches WATCH_TARGET again -- never running more
# than one search at a time (slskd 429s a second concurrent search), so
# searching stays serialized while slskd's own 50 slots pull transfers in
# parallel. It ends when the missing list is drained (nothing left to search
# and nothing left in flight) or on SIGINT/SIGTERM.
#
# WATCH_TARGET is set below slskd's global.download.slots (50) so the pool has
# distinct-peer headroom rather than being packed with same-peer queue-waiters.
WATCH_TARGET = 45
# Top the pool back up only once it has drained past this, so the loop enqueues
# in worthwhile bursts (each search costs 10-40s, serialized) instead of one
# track at a time.
WATCH_LOW_WATER = 20
# How often (seconds) the watch loop re-checks the live transfer count when the
# pool is full enough to need no topping up. The downloads GET is ~5ms, so this
# is only about not busy-looping; a real top-up pass takes minutes on its own.
WATCH_POLL_SECONDS = 30
# Re-snapshot the live library (the WAL-safe DB copy) at most this often in a
# long watch run, so a track that finished and was imported mid-run stops being
# re-queued without paying for a 17 MB snapshot on every top-up.
WATCH_LIB_REFRESH_SECONDS = 300

# Set by SIGINT/SIGTERM so an unattended watch run (e.g. under a systemd timer)
# stops cleanly: the current search finishes, state is saved, and the loop exits
# rather than being killed mid-enqueue.
STOP = False


def _request_stop(signum, _frame):
    global STOP
    STOP = True


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

# State a download is in while it waits on the REMOTE peer for an upload slot.
# A transfer in one of these states has produced no bytes and can't start until
# that peer serves it -- if the peer never grants a slot (offline, leecher, or a
# queue tens of thousands deep), it sits here forever with zero progress. These
# are the "queued but frozen" transfers a sweep must notice and re-source.
STALLED_CANDIDATE_STATES = ("Queued, Remotely", "Queued, Locally", "Requested")
# A "Queued, Remotely" transfer at or above this placeInQueue position is not
# going to be served in any sane horizon (measured 2026-08-01: a peer had us
# 45,603rd in line). Re-source it rather than leaving it frozen. A position of
# 0 (the peer never reported one) is not caught by this -- only the time bar.
QUEUE_PLACE_STALL_LIMIT = 1000
# A transfer stuck in a candidate state past this many hours with no progress
# (bytesTransferred still 0 / never left the state) is treated as dead rather
# than merely slow. Generous on purpose: Soulseek peers routinely take hours to
# serve a queue, and rotation must not be rude. Catches the place-0 unknowns the
# position bar above cannot.
QUEUED_STALL_HOURS = 24
# How long a "Queued, Remotely" transfer whose peer reported NO placeInQueue
# (None) may sit before it is treated as stalled. This is the silent-freeze
# case: with no position reported, neither QUEUE_PLACE_STALL_LIMIT nor the
# position-aware judgement can apply, so absent this bar a peer that never
# serves and never reports where we are parks us indefinitely (measured
# 2026-08-02: five "Queued, Remotely" transfers sat frozen behind exactly such
# peers). Shorter than QUEUED_STALL_HOURS on purpose - a position-less queue is
# the signature of the recurring freeze, not a healthy-but-slow queue.
NOPLACE_STALL_HOURS = 8
# A peer at or above this search-response queueLength counts as roundly
# congested for the quick-alternate fallback: picking its "best" version means
# waiting weeks in line (one track measured 45,603rd). A peer with a free upload
# slot, or a shorter queue than this, wins over the most exact version on a
# peer this deep, so a lesser-but-faster copy downloads instead of parking.
QUICK_QUEUE_LIMIT = 200
# Persistent per-track avoid of peers we've re-sourced a track away from because
# they were congested (huge queue / stalled). Kept across runs so a re-sourced
# track is never immediately re-enqueued from the same peer -- the loop that
# would otherwise make the sweep churn forever on the one peer that offers it.
STALLED_AVOID_FILENAME = "soulseek-stall-avoid.json"

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


def load_stall_avoid(path):
    """Persistent {track_key: {peer, ...}} blocked peers, one per track.

    When a track is re-sourced away from a congested peer (huge queue / never
    progressing), that peer is recorded here so a later run never immediately
    re-enqueues the same track from the same peer -- the cross-run churn that
    would otherwise make a stalled transfer loop forever. Fresh/missing file is
    an empty dict; a peer leaving the network or returning with a short queue
    merely means the track stays wanted until a new, non-blocked peer offers it.
    """
    try:
        with open(path) as f:
            data = json.load(f)
        return {k: set(v) for k, v in (data or {}).items()}
    except (OSError, ValueError, TypeError):
        return {}


def save_stall_avoid(path, avoid):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({k: sorted(v) for k, v in sorted(avoid.items())}, f,
                  indent=1)
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

def expected_wait(resp):
    """Rank a peer by how soon it would start a download, lower is faster.

    A peer advertising a free upload slot starts an accepted transfer
    immediately (0). A peer with a short or unreported queue waits a plausible
    while (1) -- Soulseek peers report queueLength when they can, and its
    absence (as in most search responses) should not guess "congested". A peer
    whose own upload queue is already QUICK_QUEUE_LIMIT deep and offers no free
    slot is the roundly-congested case (2): accepting its "best" file means
    sitting weeks in line, which is precisely the freeze this fallback exists to
    dodge. This is the "expected wait" trigger for the quick-alternate rule --
    a peer with a free slot or a short queue wins over the most exact version
    on a peer this deep, so a lesser-but-faster copy downloads instead.
    """
    if resp.get("hasFreeUploadSlot"):
        return 0
    ql = resp.get("queueLength")
    if isinstance(ql, (int, float)) and ql >= QUICK_QUEUE_LIMIT:
        return 2
    return 1


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

    The quick-alternate fallback lives here: whatever the exactness of its
    file, a peer that will START the download now or soon (expected_wait 0/1 --
    free upload slot, or a queue shorter than QUICK_QUEUE_LIMIT) beats the
    most exact version parked behind a roundly-congested peer (expected_wait
    2). So a track whose best match lives on a peer with, say, 45,000 queued
    ahead of it downloads a lesser version from a peer that will serve it now
    instead of waiting weeks for the perfect copy. The wait class is the
    primary key; only among peers in the same class does file exactness
    (length, then bitrate) decide.
    """
    best = None
    best_score = None
    for resp in responses or []:
        user = resp.get("username", "")
        if user in skip_users:
            continue
        wait = expected_wait(resp)
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
            # lower (wait, delta, -bitrate, avoid) is better
            #   wait:    a peer that will start now/soon beats one that parks us
            #            behind a huge queue (the quick-alternate fallback)
            #   delta:   closest length to the target wins within a wait class
            #   bitrate: then the richest copy
            #   avoid:   a peer already carrying MAX_ENQUEUES_PER_PEER files
            #            this run loses ties, so a batch spreads across peers
            score = (wait, delta, -bitrate,
                     0 if user not in avoid_users else 1)
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
    (slskd's Failed set: rejected / cancelled / timed out / errored / aborted),
    OR completed "successfully" with zero bytes -- the peer reported success but
    no data landed, so the track is still missing on disk. These are the
    transfers that would otherwise leave a track silently missing while the
    poller kept counting it as queued."""
    st = f.get("state") or ""
    if any(tok in st for tok in FAILED_TRANSFER_TOKENS):
        return True
    # completed-but-zero-bytes: a "Completed, Succeeded" transfer whose peer
    # advertised a non-empty file but sent nothing. bytesTransferred==0 against
    # a positive size means an empty/aborted stream that never produced the
    # file -- re-source it exactly like a rejection. (A file genuinely of size 0
    # is not a track worth having either, but we only flag size>0 so a healthy
    # succeeded transfer, whose bytes equal its size, is never touched.)
    if "Succeeded" in st and (f.get("size") or 0) and not (
            f.get("bytesTransferred") or 0):
        return True
    return False


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


def transfer_in_pipe(f):
    """True when a transfer still occupies the download pipe: it is queued or
    downloading and has neither failed nor finished. This is what the --watch
    loop counts to decide whether the pool needs topping up -- a failed/zero-byte
    terminal (transfer_failed) is not feeding anything, and a genuinely
    succeeded one has already produced its file, so neither counts as live."""
    if transfer_failed(f):
        return False
    st = f.get("state") or ""
    # "Completed"/"Succeeded" is finished; everything else in slskd's download
    # list (Queued, Remotely/Locally, Requested, Initializing, InProgress) is
    # still on its way and worth counting as an occupied slot.
    if "Completed" in st or "Succeeded" in st:
        return False
    return True


def count_in_pipe(dl):
    """How many download transfers are still live (queued or downloading)."""
    return sum(1 for tr in iter_transfers(dl) if transfer_in_pipe(tr))


# Held for the whole process so the single-instance lock (acquire_lock) is not
# released until this run exits.
_LOCK_FH = None


def acquire_lock(dump_dir):
    """Take an exclusive, non-blocking lock so two sweeps never run at once.

    A single missing-track sweep can run for hours in --watch; a systemd timer
    firing a second one, or a hand-run overlapping it, would each load the same
    state, both see a track as not-yet-queued, and both enqueue it -- a duplicate
    download slskd cannot dedupe (distinct search -> distinct transfer). The
    guard lives in the SCRIPT rather than the timer unit on purpose: a unit-level
    guard only serializes the timer, not a manual `python3 soulseek-missing.py`
    racing it. Returns True if we hold the lock (caller proceeds), False if
    another sweep owns it (caller should exit cleanly). The fd is kept in a
    module global so it stays open -- and the lock held -- for the process."""
    global _LOCK_FH
    import fcntl
    path = os.path.join(dump_dir, "soulseek-missing.lock")
    fh = open(path, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False
    fh.truncate(0)
    fh.write(str(os.getpid()))
    fh.flush()
    _LOCK_FH = fh
    return True


def requested_keys(rows, state):
    """Folded (artist, title) keys for every track state currently marks
    'queued' -- i.e. already requested from a peer this run or a previous one.

    state.tsv IS the persistent record of what has been requested; this reads it
    into the same folded key space trackmatch/library_keys use (caseless,
    unaccented, punctuation-free -- so a name differing only in case or a
    reserved exFAT char folds together). Its purpose is the duplicate state.tsv's
    per-spotify_id status does NOT catch: two missing.tsv rows that are the SAME
    recording under different spotify ids, or the same recording arriving from a
    second peer / under a slightly different filename in a later sweep. A row
    whose key set intersects this one is a duplicate of something already
    requested and must not be enqueued again. A track a rescue pass releases
    (its 'queued' state dropped) leaves this set automatically, so a genuine
    re-source is never blocked."""
    rows_by_id = {r.get("spotify_id"): r for r in rows if r.get("spotify_id")}
    out = set()
    for sid, rec in state.items():
        if rec.get("status") != "queued":
            continue
        row = rows_by_id.get(sid)
        if row is None:
            continue
        out |= trackmatch.keys(row.get("artists", ""), row.get("title", ""))
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


def stalled_transfer(f, now, place_limit, stall_hours, no_place_hours=None):
    """True when a transfer is stuck waiting on the remote peer, not just slow.

    A download in one of STALLED_CANDIDATE_STATES (queued remotely / requested)
    has produced no bytes and cannot start until the remote peer grants it an
    upload slot. It is frozen when that peer never will: it is past `place_limit`
    in the peer's queue, or it has sat in that state past `stall_hours` without a
    byte moving. Either way the transfer is effectively dead and the sweep should
    re-source it instead of leaving it to occupy the queue forever.

    The silent-freeze case is a peer that reports NO placeInQueue at all (None,
    so `or 0` here would read it as "at the front"). With no position reported,
    neither the position bar nor a position-aware time judgement applies; the
    peer keeps us "Queued, Remotely" with no progress and no information until
    the (daily) `stall_hours` bar finally trips. `no_place_hours` is a shorter,
    dedicated bar for exactly that state -- measured 2026-08-02, five transfers
    sat frozen this way for hours -- so a position-less queue is judged by time
    alone, and sooner.

    Non-candidates (in-progress, succeeded, failed) are excluded by the state
    whitelist; a peer that has actually started us (or finished, or refused us)
    is being handled elsewhere.
    """
    st = f.get("state") or ""
    if st not in STALLED_CANDIDATE_STATES:
        return False
    place = f.get("placeInQueue")
    if place is not None and place >= place_limit:
        return True  # the peer has thousands ahead of us; never served
    pushed = f.get("enqueuedAt") or f.get("requestedAt")
    if not pushed:
        return False  # no timestamp; give it the benefit of the doubt
    try:
        pushed_dt = datetime.fromisoformat(str(pushed).replace("Z", "+00:00"))
    except ValueError:
        return False
    if pushed_dt.tzinfo is None:
        pushed_dt = pushed_dt.replace(tzinfo=timezone.utc)  # slskd timestamps are UTC
    elapsed_h = (now - pushed_dt).total_seconds() / 3600.0
    if place is None:
        # No queue position reported: a short dedicated bar catches the freeze
        # a position-aware peer would have been flagged for by place_limit.
        bar = no_place_hours if no_place_hours is not None else stall_hours
        return elapsed_h >= bar
    return elapsed_h >= stall_hours


def rescue_stalled(rows, state, rescued_ids, stall_avoid, dl, now, base,
                   api_key, dry_run, place_limit, stall_hours,
                   no_place_hours=None):
    """Re-source every transfer stuck waiting on a congested remote peer.

    This is the half of the pipeline rescue_rejected cannot reach: a transfer
    that is NOT terminally failed (so rescue_rejected skips it) and NOT vanished
    (so reconcile_orphaned_queued skips it) but is parked "Queued, Remotely"
    behind a peer's upload queue at a position that will never serve us (or that
    never progressed past a time bar). It is present, alive, and frozen -- the
    exact "queued but never advancing" symptom that the failed-transfer and
    vanished-transfer fixes each missed.

    For each stalled transfer that maps to a work-list track still marked
    "queued" we:
      - cancel the stuck transfer in slskd (it can never produce a file in any
        sane horizon), and
      - drop the track's queued marker so the normal pass re-searches it, and
      - record the congested peer in the persistent per-track `stall_avoid` set
        so a later run never re-enqueues this track from that same peer (no
        cross-run churn), and
      - remember the transfer id in rescued_ids so it is acted on once.

    The peer is blocked for THIS run's re-source too (the returned set feeds
    pick_candidate), so a re-search lands on a healthier peer immediately when
    one exists -- or, if the congested peer was the only offerer, the track just
    stays wanted (its marker already dropped) until a new peer offers it.

    Never mutates `state` or `stall_avoid` and never cancels anything under
    --dry-run (a preview must not unqueue a real download, and a block it has
    not acted on must not be recorded); `rescued_ids` may gain entries that a
    preview does not persist, exactly like rescue_rejected. The returned count
    still reports what a real run would re-source, and the blocklist always
    applies. Cancels via the same ?remove=true DELETE clear_handled_failures
    uses -- best-effort, a failure is reported not fatal.

    Returns (blocked_user_set, n_would_resource, resourced_track_keys).
    Mutates `state`, `rescued_ids` and `stall_avoid`; the caller persists the
    latter two for a real run (and should put the returned track keys first in
    the search pass so a re-sourced track finds its healthier peer promptly,
    instead of waiting out the whole work-list budget).
    """
    blocked = set()
    resourced = 0
    resourced_keys = set()
    for f in iter_transfers(dl):
        if not stalled_transfer(f, now, place_limit, stall_hours, no_place_hours):
            continue
        user = f.get("username")
        filename = f.get("filename")
        if not (user and filename):
            continue
        key = f.get("id") or f"{user}\x00{filename}"
        if key in rescued_ids:
            continue  # already acted on this exact stuck transfer
        # Match like rescue_rejected: os.path.basename on a Soulseek path (which
        # uses backslashes, not "/") returns the WHOLE path, and file_matches
        # folds it -- a track whose artist lives in the album directory rather
        # than the filename ("Rick Astley\\...\\01 Never Gonna Give You Up.mp3")
        # still matches through the folded directory. Do NOT split backslashes
        # here; normalizing would shrink the match to the bare leaf and miss it.
        full = os.path.basename(filename)
        matches = [r for r in rows
                   if file_matches(full, r.get("artists", ""),
                                   r.get("title", ""))]
        if not matches:
            continue
        # Re-source each currently-queued track this stuck transfer maps to.
        # Only count the transfer as HANDLED (and only block the congested
        # peer) once at least one queued track was actually released -- mirroring
        # rescue_rejected, so a transfer whose matching track is not currently
        # "queued" does not burn the id and the peer permanently.
        acted = 0
        for row in matches:
            sid = track_key(row)
            rec = state.get(sid)
            if rec and rec.get("status") == "queued":
                acted += 1
                resourced += 1
                resourced_keys.add(sid)
                if not dry_run:
                    del state[sid]
                    # persist the per-track avoid only on a real run; a preview
                    # must not accumulate blocks it has not actually acted on.
                    stall_avoid.setdefault(sid, set()).add(user)
        if acted:
            blocked.add(user)
            rescued_ids.add(key)
            if not dry_run:
                try:
                    http("DELETE",
                         f"{base}/api/v0/transfers/downloads/"
                         f"{urllib.parse.quote(str(user), safe='')}/"
                         f"{urllib.parse.quote(str(key), safe='')}?remove=true",
                         api_key)
                except SlskdError as e:
                    print(f"    ! could not cancel stalled transfer {key}: {e}")
    return blocked, resourced, resourced_keys


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
    ap.add_argument("--stall-place", type=int, default=QUEUE_PLACE_STALL_LIMIT,
                    help="re-source a queued-remotely transfer at or above this "
                         "placeInQueue (default %(default)s)")
    ap.add_argument("--stall-hours", type=float, default=QUEUED_STALL_HOURS,
                    help="re-source a queued transfer stuck this many hours "
                         "with no progress (default %(default)s)")
    ap.add_argument("--stall-no-place-hours", type=float,
                    default=NOPLACE_STALL_HOURS,
                    help="re-source a queued-remotely transfer whose peer "
                         "reported NO queue position and has not progressed "
                         "this many hours (default %(default)s)")
    ap.add_argument("--library-skip/--no-library-skip",
                    dest="library_skip", action="store_true", default=True,
                    help="re-check the live library and skip what is present")
    ap.add_argument("--no-import", dest="import_step", action="store_false",
                    default=True,
                    help="skip the move-into-library + rescan import step "
                         "(default: run it)")
    ap.add_argument("--watch", action="store_true",
                    help="continuous 'keep the pipe fed' mode: instead of one "
                         "fixed batch, keep the download pool topped up (search "
                         "and enqueue whenever live transfers fall below "
                         "--low-water) until the missing list is drained or the "
                         "process is stopped (SIGINT/SIGTERM)")
    ap.add_argument("--target", type=int, default=WATCH_TARGET,
                    help="--watch: top the pool back up to this many live "
                         "transfers (default %(default)s)")
    ap.add_argument("--low-water", type=int, default=WATCH_LOW_WATER,
                    help="--watch: only top up once live transfers fall below "
                         "this (default %(default)s)")
    ap.add_argument("--poll-interval", type=float, default=WATCH_POLL_SECONDS,
                    help="--watch: seconds between transfer-count checks when "
                         "the pool needs no topping up (default %(default)s)")
    args = ap.parse_args()

    api_key = read_api_key(args.key_file)
    base = args.host.rstrip("/")
    state_path = os.path.join(args.dump_dir, "soulseek-state.tsv")

    if not acquire_lock(args.dump_dir):
        print("another soulseek-missing sweep is already running "
              f"({os.path.join(args.dump_dir, 'soulseek-missing.lock')}); "
              "exiting so the two do not enqueue duplicates.")
        return

    check_slskd(base, api_key)

    if args.watch:
        watch_loop(args, api_key, base, state_path)
    else:
        session = {"deferred": set(), "present": None, "present_at": 0.0}
        sweep_once(args, api_key, base, state_path, session)


def check_slskd(base, api_key):
    """Fail fast unless slskd is up and logged in to the Soulseek network.
    Both are SystemExit conditions -- there is nothing to search against
    otherwise -- so the watch loop calls this once, before it starts."""
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


def fetch_downloads(base, api_key):
    """Best-effort GET of the download list; None on any API error, so a blip
    never crashes an unattended watch run."""
    try:
        return http("GET", f"{base}/api/v0/transfers/downloads", api_key)
    except SlskdError:
        return None


def interruptible_sleep(seconds):
    """Sleep in short steps so a SIGINT/SIGTERM (which sets STOP) is noticed
    within ~1s rather than blocking out the whole poll interval."""
    end = time.time() + seconds
    while not STOP and time.time() < end:
        time.sleep(min(1.0, end - time.time()))


def watch_loop(args, api_key, base, state_path):
    """Keep the download pipe fed until the missing list is drained or stopped.

    One search at a time (slskd 429s a second concurrent search), transfers in
    parallel (slskd's own 50 slots). Whenever the count of live transfers
    (transfer_in_pipe) falls below --low-water, run one sweep that searches and
    enqueues up to --target - live tracks -- each sweep also runs the full rescue
    pass (rejected / zero-byte / stalled-forever / vanished), so tracks that
    would otherwise strand are re-sourced as it goes. Ends when a sweep finds
    nothing left to search AND nothing is in flight, or on SIGINT/SIGTERM."""
    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)
    # session state persists ACROSS sweeps so the loop terminates and stays
    # cheap: `deferred` holds tracks offered only by an avoided/congested peer
    # this session (so they are not re-searched every sweep forever), and the
    # cached library keys are re-snapshotted at most every WATCH_LIB_REFRESH_S.
    session = {"deferred": set(), "present": None, "present_at": 0.0}
    print(f"watch: target {args.target} live transfers, top up below "
          f"{args.low_water}, poll every {args.poll_interval:g}s. "
          f"Ctrl-C / SIGTERM to stop.\n")
    while not STOP:
        dl = fetch_downloads(base, api_key)
        in_pipe = count_in_pipe(dl)
        if in_pipe >= args.low_water:
            print(f"watch: {in_pipe} live transfer(s) (>= {args.low_water}); "
                  f"waiting {args.poll_interval:g}s")
            interruptible_sleep(args.poll_interval)
            continue
        print(f"\nwatch: {in_pipe} live transfer(s) (< {args.low_water}); "
              f"topping up toward {args.target}")
        budget = max(1, args.target - in_pipe)
        summary = sweep_once(args, api_key, base, state_path, session,
                             budget_override=budget)
        if STOP:
            break
        if summary["wanted"] == 0:
            post = count_in_pipe(fetch_downloads(base, api_key))
            if post == 0:
                print("\nwatch: missing list drained and nothing in flight. "
                      "done.")
                break
            # Nothing left to enqueue, but transfers are still finishing. Wait
            # for them (a rescue pass may free a stalled one) rather than
            # busy-looping the sweep.
            print(f"watch: nothing left to search; {post} still finishing. "
                  f"waiting {args.poll_interval:g}s")
            interruptible_sleep(args.poll_interval)
    if STOP:
        print("\nwatch: stopped.")


def library_present(args, session):
    """Live-library lookup keys, cached on `session` and re-snapshotted only
    once per WATCH_LIB_REFRESH_SECONDS, so a long watch run does not pay for a
    17 MB DB copy on every top-up. A single run always computes it fresh (the
    cache starts empty). --no-library-skip returns an empty set, as before."""
    if not args.library_skip:
        return set()
    now = time.time()
    if (session.get("present") is not None
            and now - session.get("present_at", 0.0) < WATCH_LIB_REFRESH_SECONDS):
        return session["present"]
    present = library_keys(args.db)
    session["present"] = present
    session["present_at"] = now
    print(f"  live library has {len(present)} lookup keys (skipping those)")
    return present


def sweep_once(args, api_key, base, state_path, session, budget_override=None):
    """One pass: rescue the strandable transfers, then search+enqueue tracks.

    `budget_override` caps how many tracks this pass searches (watch mode sets it
    to the pool deficit); when None the single-run --limit / --all rule applies.
    Returns a summary dict: `enqueued` (new downloads queued this pass),
    `processed` (tracks searched), `wanted` (tracks still needing a search after
    this pass excludes handled + deferred ones -- 0 means the list is drained),
    `in_pipe` (live transfers seen at the start of the pass)."""
    deferred = session["deferred"]

    # --- 1. load the work list and skip what the live library now has --------
    rows = load_missing(args.tsv)
    print(f"{len(rows)} tracks in {args.tsv}")

    present = library_present(args, session)
    if not args.library_skip:
        print("  (--no-library-skip: not checking the live library)")

    state = {} if args.retry else load_state(state_path)
    rescued_ids = load_rescued(os.path.join(args.dump_dir,
                                            os.path.basename(RESCUED_FILE)))
    stall_avoid = load_stall_avoid(os.path.join(args.dump_dir,
                                                STALLED_AVOID_FILENAME))

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
    in_pipe = count_in_pipe(dl)
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

    # A transfer parked "Queued, Remotely" behind a congested peer's upload
    # queue (or never progressing past a time bar) is present and alive -- so
    # neither rescue_rejected (failed terminals) nor reconcile_orphaned_queued
    # (vanished transfers) touches it, yet it can never produce a file. Re-source
    # exactly those stalled transfers: cancel the frozen row, release the track's
    # queued marker, and remember the congested peer per-track so a later run
    # never re-enqueues it there (no cross-run churn). Its returned peer set is
    # folded into blocked_users so the re-search of the same run avoids it.
    stalled_blocked, n_stalled, resourced_stall_keys = set(), 0, set()
    try:
        (stalled_blocked, n_stalled,
         resourced_stall_keys) = rescue_stalled(
            rows, state, rescued_ids, stall_avoid, dl,
            now=datetime.now(timezone.utc), base=base, api_key=api_key,
            dry_run=args.dry_run, place_limit=args.stall_place,
            stall_hours=args.stall_hours,
            no_place_hours=args.stall_no_place_hours)
    except SlskdError as e:
        print(f"  ! stall re-source degraded: {e}")
    if n_stalled:
        print(f"  re-sourcing {n_stalled} track(s) stuck queued behind a "
              f"congested peer")
        if not args.dry_run:
            save_state(state_path, state)
    if stalled_blocked:
        blocked_users |= stalled_blocked
        print(f"  avoiding {len(stalled_blocked)} peer(s) with a frozen "
              f"download queue this run")
    if (n_stalled and not args.dry_run):
        save_rescued(os.path.join(args.dump_dir,
                                  os.path.basename(RESCUED_FILE)), rescued_ids)
        save_stall_avoid(os.path.join(args.dump_dir, STALLED_AVOID_FILENAME),
                         stall_avoid)

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
        # A track deferred this session (offered only by an avoided/congested
        # peer -- see the search loop) is not re-searched every sweep; a fresh
        # invocation clears `deferred` and probes it again.
        if track_key(row) in deferred:
            return False
        if args.retry:
            return True
        rec = state.get(row.get("spotify_id"))
        if rec is None:
            return True
        # A transient search/enqueue failure must be retried on a later run,
        # not abandoned forever. The `error` status records an HTTP 429
        # "only one concurrent operation" blip or a peer going offline mid-
        # enqueue -- evidence the transfer bounced, not that the track is
        # unavailable. Only `nofind` is genuinely terminal (no peer offers it).
        # Without this, one transient failure permanently dropped a track from
        # the work list, one of the reasons the download pool read as "only one
        # going" while it drained.
        if rec.get("status") == "error":
            return True
        return False

    todo = [r for r in rows if wanted(r)]
    print(f"  {len(todo)} not yet handled by a previous run")

    # Everything already requested (state marks 'queued') in the folded key
    # space, so a DIFFERENT missing.tsv row that is the same recording -- or the
    # same recording offered by a second peer / filename in a later sweep -- is
    # recognised as a duplicate and not enqueued again. Grows as this sweep
    # enqueues, so two same-recording rows within one budget are also caught.
    requested = requested_keys(rows, state)
    already_have = 0
    dup_skipped = 0
    net = []
    for r in todo:
        ks = trackmatch.keys(r.get("artists", ""), r.get("title", ""))
        if present and any(k in present for k in ks):
            already_have += 1
            state.setdefault(track_key(r), {
                "spotify_id": r.get("spotify_id", ""), "isrc": r.get("isrc", ""),
                "status": "have", "user": "", "filename": "-already-in-library-",
                "when": time.strftime("%Y-%m-%d %H:%M:%S")})
            continue
        if requested and any(k in requested for k in ks):
            dup_skipped += 1  # a sibling row / earlier run already requested it
            continue
        net.append(r)
    if already_have:
        print(f"  {already_have} now in the library already; skipped")
    if dup_skipped:
        print(f"  {dup_skipped} already requested under another entry; skipped")
    if already_have or dup_skipped:
        print()

    # A track just re-sourced from a frozen/congested peer must find its
    # healthier peer NOW, not after the whole (potentially thousands-long) work
    # list has had its turn. Put re-sourced tracks first in the search budget so
    # the re-source pays off in the next run rather than hundreds of runs away.
    if resourced_stall_keys:
        net.sort(key=lambda r: track_key(r) not in resourced_stall_keys)

    if budget_override is not None:
        budget = min(budget_override, len(net))
    elif args.all:
        budget = len(net)
    else:
        budget = min(args.limit, len(net))
    if budget == 0:
        print("nothing to do.")
        return {"enqueued": 0, "processed": 0, "wanted": len(net),
                "in_pipe": in_pipe}
    print(f"searching {budget} track(s); --dry-run is "
          f"{'ON' if args.dry_run else 'OFF'}\n")

    # --- 2. search and enqueue ----------------------------------------------
    # The parallel transfer itself is slskd's: global.download.slots (pinned to
    # 50) lets it pull many downloads from distinct peers at once. This loop's
    # only job is to feed that pipeline, and it has no concurrency of its own to
    # tune: slskd rejects concurrent searches outright (HTTP 429 "Only one
    # concurrent operation is permitted" -- measured 2026-08-01), so the search
    # MUST be one at a time. What turned "several downloads in parallel" into
    # "only one going" is therefore not this loop's internal parallelism but the
    # size of the batch it feeds slskd: a run that enqueues a handful of tracks
    # (the old --limit default of 5) gives the 50-slot downloader almost nothing
    # to pull, so a few same-peer tracks serialize behind that peer's single
    # upload slot and it reads as sequential. Enqueue a real batch across
    # distinct peers (--limit / --all) and slskd downloads them in parallel.
    changed = False
    processed = 0
    enqueued = 0
    # How many files each peer has been enqueued this run, so pick_candidate can
    # de-prioritize a peer that is already carrying MAX_ENQUEUES_PER_PEER and
    # keep a batch fanned out across distinct peers instead of piled on one.
    run_user_counts = {}
    for row in net[:budget]:
        # A stop signal (SIGINT/SIGTERM in --watch) ends the pass cleanly after
        # the current track's state is saved, rather than mid-enqueue.
        if STOP:
            print("  (stop requested; ending this pass)")
            break
        processed += 1
        sid = track_key(row)
        artists, title = row.get("artists", ""), row.get("title", "")
        want_ms = row.get("duration_ms")
        desc = f"({processed}/{budget}) {artists} - {title}"
        print(f"  {desc}")

        # Duplicate guard: a sibling row enqueued earlier THIS budget (or a peer
        # that started serving between the net build and here) already covers
        # this recording. Skip before spending the one serialized search on it.
        ks = trackmatch.keys(artists, title)
        if requested and any(k in requested for k in ks):
            print("    already requested this recording this run; skipped")
            continue

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
                                  set(blocked_users)
                                  | set(stall_avoid.get(sid, ())),
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
            # Not picked. The track is genuinely unavailable only if NO peer at
            # all offered it; when the only offers come from a peer we are
            # avoiding (this run's refused/congested set, or a persistently-
            # avoided peer this track was re-sourced away from), the track still
            # exists on the network -- just not from a source we'll use. Leave it
            # wanted (no state entry) so a later run probes again once a healthy
            # peer offers it, rather than recording nofind, which would stop us
            # ever trying.
            any_offer = pick_candidate(responses, artists, title, want_ms,
                                       set(), set()) is not None
            if any_offer:
                print("    only available from an avoided/congested peer; "
                      "left for a later run")
                # In --watch this would otherwise be re-searched every sweep
                # forever (it records no state); defer it for the rest of this
                # session so the loop can drain. A fresh invocation clears it.
                deferred.add(sid)
            else:
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
            requested |= ks
            changed = True
            save_state(state_path, state)
            continue

        # Grab-time existence check: this exact file may already sit COMPLETED in
        # slskd's downloads dir, waiting for the import step to move it into aud/
        # and rescan (so it is not in the library DB yet). Re-grabbing it would
        # be a straight duplicate. Soulseek paths use backslashes; normalize
        # before basename, then fold to the same caseless key the dir scan uses.
        cand_base = trackmatch.fold(
            os.path.basename(str(filename).replace("\\", "/")))
        if cand_base and cand_base in downloaded:
            print(f"    already downloaded (awaiting import); skipped: {filename}")
            state[sid] = {"spotify_id": row.get("spotify_id", ""),
                          "isrc": row.get("isrc", ""), "status": "queued",
                          "user": user, "filename": filename,
                          "when": time.strftime("%Y-%m-%d %H:%M:%S")}
            requested |= ks
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
            requested |= ks
            run_user_counts[user] = run_user_counts.get(user, 0) + 1
        else:
            try:
                http("POST", f"{base}/api/v0/transfers/downloads/{urllib.parse.quote(user, safe='')}",
                     api_key, [{"filename": filename, "size": size}])
                print(f"    queued from {user}: {filename}")
                queued_files.add((user, filename))
                requested |= ks
                enqueued += 1
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

    print(f"\ndone. {processed} track(s) processed this pass.")
    print(f"  state -> {state_path}")

    # The player only sees a track once it is moved into aud/ and rescanned —
    # previously this was a note for a human to do by hand; now the import step
    # does it. Skipped in --dry-run, which must not touch the filesystem.
    if not args.dry_run:
        import_downloads(args.import_step)

    # Tracks still needing a search after this pass (untouched budget tail,
    # transient errors to retry, orphans just re-queued) -- excludes handled,
    # in-library, already-requested (dedup) and deferred tracks. 0 means the
    # missing list is drained as far as this run can take it, which is how the
    # watch loop knows to stop rather than spinning on rows it will always skip.
    def still_searchable(r):
        if not wanted(r):
            return False
        ks_r = trackmatch.keys(r.get("artists", ""), r.get("title", ""))
        if present and any(k in present for k in ks_r):
            return False
        if requested and any(k in requested for k in ks_r):
            return False
        return True

    remaining = sum(1 for r in rows if still_searchable(r))
    return {"enqueued": enqueued, "processed": processed, "wanted": remaining,
            "in_pipe": in_pipe}


if __name__ == "__main__":
    main()
