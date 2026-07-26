#!/usr/bin/env python3
"""Sync surfer's user-generated browser state between `top` and `book`.

Scope is deliberately narrow: the only two things a Chromium profile holds
that can be MERGED losslessly.

  * Cookies  — SQLite. Merged row by row on Chromium's own unique index
               (host_key, top_frame_site_key, has_cross_site_ancestor, name,
               path, source_scheme, source_port); on a collision the row with
               the newer last_update_utc wins. Both machines' logins survive.
  * userscripts (~/.config/surfer/userscripts/*.user.js) — plain files,
               rsync --update in both directions: newest mtime per filename.

Everything else in the profile is deliberately NOT synced:

  * Local Storage / Session Storage / IndexedDB / WebStorage are LevelDB —
    log-structured, no merge exists. Syncing them means whole-directory
    last-writer-wins, i.e. silently discarding one machine's session. If a
    site keeps its auth in localStorage rather than a cookie, that login will
    NOT carry over; that is the accepted cost of never losing data.
  * Service Worker (150 MB+), GPUCache, Dawn*Cache, blob_storage,
    Shared Dictionary, the adblock filter cache — regenerable cache.
  * History / Favicons — mergeable in principle, but visit rows are FK-linked
    and the payoff is cosmetic. Left alone.

Two facts this rests on, both verified 2026-07-26 and worth re-checking if it
ever misbehaves:

  1. Cookies are stored in PLAINTEXT (`value`, with `encrypted_value` empty) on
     both machines — QtWebEngine found no OS keyring, so there is no
     machine-bound encryption key and the rows are portable. If a keyring ever
     appears, `encrypted_value` starts filling with v10/v11 blobs and rows
     copied to the other machine become undecryptable garbage. `status` warns.
  2. Both profiles are at Cookies schema version 24 with the same unique
     index. A Qt bump that moves either side to a new schema means this must
     be re-checked before it is trusted; `status` compares them and refuses.

Direction: book is ALWAYS the initiator — Fedora runs no sshd, so top cannot
reach book. Like player/tools/dbsync.py this is stdlib-only (it runs under
Fedora's bare python3 on book) and it is its own remote agent: it pipes
ITSELF to `python3 -` over ssh so the same code runs on both ends.

It never deletes: a cookie or userscript removed on one machine comes back
from the other. Clearing cookies for real means clearing them on both.

Safety interlock: a Chromium profile must not be read or written while the
browser owns it, so every command refuses to run if surfer is alive on either
end.

Usage:
    sync.py status          # what's where, and are the two schemas compatible
    sync.py pull            # top  -> book (merge)
    sync.py push            # book -> top  (merge)
    sync.py sync            # both, pull first  [what the launcher runs]
    sync.py --dry-run sync
"""

import argparse
import base64
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile

DEFAULT_HOST = os.environ.get("SURFER_SYNC_HOST", "top")

# NB `top`, not `top.local`: nix-built binaries on book cannot resolve mDNS
# (.local) at all, while plain DNS gives top.lan -> 192.168.40.202.

SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]

# Chromium's unique index on `cookies` — the merge key.
KEY_COLS = (
    "host_key",
    "top_frame_site_key",
    "has_cross_site_ancestor",
    "name",
    "path",
    "source_scheme",
    "source_port",
)
SCHEMA_VERSION = "24"  # what this tool was written against

# Chromium timestamps are microseconds since 1601-01-01 UTC.
EPOCH_DELTA_US = 11644473600 * 1_000_000


def profile_dir():
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "surfer", "surfer", "QtWebEngine", "surfer")


def cookies_path():
    return os.path.join(profile_dir(), "Cookies")


def userscripts_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "surfer", "userscripts")


def now_chromium():
    import time

    return int(time.time() * 1_000_000) + EPOCH_DELTA_US


# ---------------------------------------------------------------------------
# safety interlock
# ---------------------------------------------------------------------------


def surfer_running():
    """True if a surfer process owns the profile here.

    Scans /proc rather than shelling out to pgrep: a pgrep pattern would match
    the very ssh/python command line this tool is invoked through.
    """
    me = os.getpid()
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == me:
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                parts = f.read().split(b"\0")
        except (OSError, IOError):
            continue
        # the real thing is `<python> /path/to/surfer/main.py [...]`
        if any(p.endswith(b"surfer/main.py") for p in parts):
            exe = parts[0].rsplit(b"/", 1)[-1] if parts and parts[0] else b""
            if b"python" in exe:
                return True
    return False


# ---------------------------------------------------------------------------
# cookies
# ---------------------------------------------------------------------------


def snapshot(src, dst):
    """Consistent copy of a live-ish SQLite db (WAL-safe; `cp` is not)."""
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        d = sqlite3.connect(dst)
        try:
            s.backup(d)
        finally:
            d.close()
    finally:
        s.close()


def schema_info(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        meta = dict(con.execute("select key, value from meta").fetchall())
        cols = [r[1] for r in con.execute("pragma table_info(cookies)")]
        n = con.execute("select count(*) from cookies").fetchone()[0]
        enc = con.execute(
            "select count(*) from cookies where length(encrypted_value) > 0"
        ).fetchone()[0]
        return {
            "version": meta.get("version"),
            "last_compatible_version": meta.get("last_compatible_version"),
            "columns": cols,
            "count": n,
            "encrypted": enc,
        }
    finally:
        con.close()


def dump_cookies(path):
    """All live cookie rows as JSON-safe dicts (blobs base64'd)."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        cols = [r[1] for r in con.execute("pragma table_info(cookies)")]
        rows = []
        now = now_chromium()
        for r in con.execute("select * from cookies"):
            # Don't resurrect dead cookies on the other machine.
            if r["has_expires"] and r["expires_utc"] and r["expires_utc"] < now:
                continue
            d = {}
            for c in cols:
                v = r[c]
                if isinstance(v, bytes):
                    v = {"__b64__": base64.b64encode(v).decode("ascii")}
                d[c] = v
            rows.append(d)
        return {"columns": cols, "rows": rows}
    finally:
        con.close()


def _unblob(v):
    if isinstance(v, dict) and "__b64__" in v:
        return base64.b64decode(v["__b64__"])
    return v


def merge_cookies(path, payload, dry_run=False):
    """Upsert `payload`'s rows into the db at `path`; newer last_update_utc wins.

    Returns (inserted, updated, skipped).
    """
    incoming = payload["rows"]
    if not incoming:
        return (0, 0, 0)

    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        cols = [r[1] for r in con.execute("pragma table_info(cookies)")]
        have = {c for c in cols}
        # Only carry columns both sides know about.
        use = [c for c in payload["columns"] if c in have]

        existing = {}
        for r in con.execute(
            "select %s, last_update_utc from cookies" % ", ".join(KEY_COLS)
        ):
            existing[tuple(r[c] for c in KEY_COLS)] = r["last_update_utc"] or 0

        ins = upd = skip = 0
        for row in incoming:
            key = tuple(row.get(c) for c in KEY_COLS)
            theirs = row.get("last_update_utc") or 0
            if key in existing:
                if theirs <= existing[key]:
                    skip += 1
                    continue
                upd += 1
            else:
                ins += 1
            if dry_run:
                continue
            vals = [_unblob(row.get(c)) for c in use]
            con.execute(
                "insert or replace into cookies (%s) values (%s)"
                % (", ".join(use), ", ".join("?" * len(use))),
                vals,
            )
        if not dry_run:
            con.commit()
        return (ins, upd, skip)
    finally:
        con.close()


# ---------------------------------------------------------------------------
# remote agent — pipe THIS script to `python3 -` on the far end
# ---------------------------------------------------------------------------


def _self_source():
    with open(os.path.abspath(__file__), "rb") as f:
        return f.read()


def _remote(host, argv, check=True):
    """Run THIS script on `host` via `python3 -`.

    Note stdin is NOT usable for data: `python3 -` reads stdin to EOF to get
    its program, so anything appended would be compiled as source. Bulk data
    goes over as a staged file — see _remote_put.
    """
    cmd = SSH + [host, "python3 - " + " ".join(shlex.quote(a) for a in argv)]
    p = subprocess.run(
        cmd, input=_self_source(), stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if check and p.returncode != 0:
        sys.stderr.write(p.stderr.decode("utf-8", "replace"))
        raise SystemExit(f"remote {argv} failed on {host} (rc={p.returncode})")
    return p


def _remote_put(host, data, path):
    """Stage `data` at `path` on the far end (stdin is free for plain `cat`)."""
    p = subprocess.run(
        SSH + [host, f"cat > {shlex.quote(path)}"],
        input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if p.returncode != 0:
        sys.stderr.write(p.stderr.decode("utf-8", "replace"))
        raise SystemExit(f"staging payload on {host} failed (rc={p.returncode})")


def _remote_rm(host, path):
    subprocess.run(SSH + [host, f"rm -f {shlex.quote(path)}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# userscripts
# ---------------------------------------------------------------------------


def sync_userscripts(host, dry_run=False):
    local = userscripts_dir()
    os.makedirs(local, exist_ok=True)
    flags = ["-a", "--update", "--itemize-changes"]
    if dry_run:
        flags.append("--dry-run")
    out = []
    # --update = never overwrite a file that is newer on the receiver, so
    # running it both ways is a union with newest-mtime-per-name winning.
    for src, dst, label in (
        (f"{host}:.config/surfer/userscripts/", local + "/", "pull"),
        (local + "/", f"{host}:.config/surfer/userscripts/", "push"),
    ):
        p = subprocess.run(
            ["rsync", *flags, src, dst], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if p.returncode != 0:
            sys.stderr.write(p.stderr.decode("utf-8", "replace"))
            raise SystemExit(f"rsync userscripts {label} failed (rc={p.returncode})")
        for line in p.stdout.decode("utf-8", "replace").splitlines():
            if line.strip() and not line.startswith("."):
                out.append(f"  {label}: {line}")
    return out


# ---------------------------------------------------------------------------
# guards
# ---------------------------------------------------------------------------


def guard_local():
    if surfer_running():
        raise SystemExit("surfer is running here — close it first (profile is locked)")


def guard_remote(host):
    p = _remote(host, ["is-running"], check=False)
    if p.returncode == 0 and p.stdout.strip() == b"RUNNING":
        raise SystemExit(f"surfer is running on {host} — close it there first")


def guard_schema(host):
    local = schema_info(cookies_path())
    remote = json.loads(_remote(host, ["schema"]).stdout.decode())
    if local["version"] != remote["version"]:
        raise SystemExit(
            f"Cookies schema mismatch: local v{local['version']} vs "
            f"{host} v{remote['version']} — re-verify the merge key before syncing"
        )
    if local["version"] != SCHEMA_VERSION:
        sys.stderr.write(
            f"warning: Cookies schema is v{local['version']}, this tool was "
            f"written for v{SCHEMA_VERSION} — verify the unique index still matches\n"
        )
    for side, info in (("local", local), (host, remote)):
        if info["encrypted"]:
            sys.stderr.write(
                f"warning: {info['encrypted']} cookies on {side} have an "
                "encrypted_value — a keyring appeared, and those rows will NOT "
                "decrypt on the other machine\n"
            )
    return local, remote


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_pull(args):
    guard_local()
    guard_remote(args.host)
    guard_schema(args.host)
    payload = json.loads(_remote(args.host, ["dump"]).stdout.decode())
    ins, upd, skip = merge_cookies(cookies_path(), payload, args.dry_run)
    print(f"cookies  pull: +{ins} new, {upd} updated, {skip} already current")
    return ins, upd


def cmd_push(args):
    guard_local()
    guard_remote(args.host)
    guard_schema(args.host)
    payload = json.dumps(dump_cookies(cookies_path())).encode()
    remote_tmp = f"/tmp/surfer-sync-push-{os.getpid()}.json"
    _remote_put(args.host, payload, remote_tmp)
    try:
        argv = ["merge", "--payload", remote_tmp] + (["--dry-run"] if args.dry_run else [])
        out = _remote(args.host, argv).stdout.decode().strip()
    finally:
        _remote_rm(args.host, remote_tmp)
    print(f"cookies  push: {out}")


def cmd_sync(args):
    cmd_pull(args)
    cmd_push(args)
    changes = sync_userscripts(args.host, args.dry_run)
    print(f"userscripts: {len(changes)} transferred" if changes else "userscripts: in sync")
    for c in changes:
        print(c)


def cmd_status(args):
    local = schema_info(cookies_path())
    print(f"local  : {local['count']:4d} cookies  schema v{local['version']}"
          f"  encrypted={local['encrypted']}")
    try:
        remote = json.loads(_remote(args.host, ["schema"]).stdout.decode())
        print(f"{args.host:7}: {remote['count']:4d} cookies  schema v{remote['version']}"
              f"  encrypted={remote['encrypted']}")
        print("schemas compatible" if local["version"] == remote["version"]
              else "!! SCHEMA MISMATCH — refusing to sync")
    except SystemExit as e:
        print(f"{args.host}: unreachable ({e})")
    print(f"surfer running here: {surfer_running()}")
    n = len([f for f in os.listdir(userscripts_dir())]) if os.path.isdir(userscripts_dir()) else 0
    print(f"userscripts here: {n}")


# --- remote-agent-only subcommands (run on the far end) --------------------


def cmd_dump(args):
    print(json.dumps(dump_cookies(cookies_path())))


def cmd_schema(args):
    print(json.dumps(schema_info(cookies_path())))


def cmd_is_running(args):
    print("RUNNING" if surfer_running() else "IDLE")


def cmd_merge(args):
    """Remote side of a push: merge the staged payload file into our db."""
    if surfer_running():
        raise SystemExit("surfer is running here — refusing to write the profile")
    with open(args.payload, "rb") as f:
        payload = json.loads(f.read().decode())
    ins, upd, skip = merge_cookies(cookies_path(), payload, args.dry_run)
    print(f"+{ins} new, {upd} updated, {skip} already current")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--dry-run", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (
        ("status", cmd_status), ("pull", cmd_pull), ("push", cmd_push),
        ("sync", cmd_sync),
        # remote agent entry points
        ("dump", cmd_dump), ("schema", cmd_schema),
        ("is-running", cmd_is_running), ("merge", cmd_merge),
    ):
        p = sub.add_parser(name)
        # default=SUPPRESS matters: with a normal store_true the subparser's
        # False would overwrite a --dry-run given BEFORE the subcommand, and
        # the "dry" run would silently write. (It did, once.)
        p.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS)
        if name == "merge":
            p.add_argument("--payload", required=True)
        p.set_defaults(func=fn)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
