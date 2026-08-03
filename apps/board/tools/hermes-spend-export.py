#!/usr/bin/env python3
"""Write THIS host's hermes minister spend to ~/nix/docs/spend.<host>.json.

[his answer, 2026-08-03] on combining the hermes spend rows across top and
book: *build the hermes per-host export and sum both*. The Claude side of the
board's spend section already combines — the transcripts sync through
`claude-state` — but `~/.hermes/state.db` does not, so until this file existed
each board only ever saw its own host's hermes ministers.

THE MECHANISM. Each host runs this writer quarterly-hourly (unit in
home/srvs/board-spend-export.nix). It reads the local ledger's `source='tool'`
sessions — exactly the filter `boardspend._hermes_rows` uses — and writes a
small JSON to `~/nix/docs/spend.<host>.json`, atomically (tmp + os.replace).
The existing docs sync (`home/srvs/nix-docs.nix`, every 5 min, `git add -A` +
commit + push) then carries that file to the other machine like any other doc,
and `boardspend` reads the OTHER host's file as if it were a second local
ledger. The writer never touches git itself — the sync owns that, so a write
here can never race a commit.

THE FORMAT is the reader's contract (boardspend.py, `_hermes_export_rows`):
one object with `host`, `written` (epoch) and `sessions`, each session being
the exact columns the local query selects. The reader folds the remote rows
through the SAME aggregation it uses for the local db, so the ranked list and
the per-day chart both sum the two hosts.

WHY UNCHANGED WRITES ARE SKIPPED. The docs sync commits whatever it finds, so
a writer that rewrote the file every tick would mint a commit every 15 minutes
forever. The export is only rewritten when its content actually changed; a
quiet host leaves the file — and the docs history — alone.

Env overrides, so a harness can point it at a scratch ledger and a scratch
output dir without touching his:
  BOARD_HERMES_DB        the ledger path (same redirect boardusage honours)
  BOARD_SPEND_EXPORT_DIR where spend.<host>.json is written (default
                         ~/nix/docs, the docs checkout on both machines)
"""
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import boardusage  # noqa: E402  (needs the path insert above)

#: The two recency windows the readout mirrors; the writer needs no window —
#: the export carries EVERY source='tool' session, and the reader applies its
#: own cutoffs. Kept out of here entirely; see boardspend.

DEFAULT_DIR = os.path.join(os.path.expanduser("~"), "nix", "docs")


def export_path():
    """The file this host writes, `~/nix/docs/spend.<hostname>.json`."""
    d = os.environ.get("BOARD_SPEND_EXPORT_DIR") or DEFAULT_DIR
    return os.path.join(d, "spend.%s.json" % os.uname().nodename)


def read_sessions():
    """`[{model, started_at, ...token columns..., estimated_cost_usd}]` for this
    host's board ministers (source='tool'), or None when the ledger cannot be
    read. None means UNKNOWN — the writer keeps the previous export rather than
    overwriting a good file with nothing."""
    path = boardusage._hermes_db_path()
    if not os.path.isfile(path):
        return None
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        rows = con.execute(
            "SELECT model, started_at, input_tokens, cache_read_tokens,"
            " cache_write_tokens, output_tokens, reasoning_tokens,"
            " estimated_cost_usd FROM sessions WHERE source=?",
            (boardusage.HERMES_SOURCE,)).fetchall()
        con.close()
    except sqlite3.Error:
        return None
    return [{
        "model": r[0],
        "started_at": r[1],
        "input_tokens": r[2],
        "cache_read_tokens": r[3],
        "cache_write_tokens": r[4],
        "output_tokens": r[5],
        "reasoning_tokens": r[6],
        "estimated_cost_usd": r[7],
    } for r in rows]


def write_export(now=None):
    """Refresh this host's export. Returns a short reason word for the unit's
    log: `ok` (written), `same` (sessions unchanged, file untouched), `unknown`
    (ledger unreadable — previous export kept), `unwritable` (could not write
    the file). Never raises.

    The unchanged check is on the SESSIONS, never the whole document: `written`
    is a timestamp and would differ on every tick, so comparing whole documents
    would rewrite the file — and therefore mint a docs commit — every 15
    minutes forever. The file is only touched when the ledger actually moved.
    """
    now = time.time() if now is None else now
    sessions = read_sessions()
    if sessions is None:
        return "unknown"
    out = export_path()
    try:
        with open(out, "r", encoding="utf-8") as f:
            old = json.load(f)
        if isinstance(old, dict) and old.get("sessions") == sessions \
                and old.get("host") == os.uname().nodename:
            return "same"
    except (OSError, ValueError):
        pass
    doc = {"host": os.uname().nodename, "written": now,
           "sessions": sessions}
    body = json.dumps(doc, sort_keys=True) + "\n"
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        tmp = out + ".new"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, out)
    except OSError:
        return "unwritable"
    return "ok"


if __name__ == "__main__":
    print(write_export())
