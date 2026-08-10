"""boardundo — Ctrl+Z: take back the last thing he typed into the box.

[his, 2026-07-29] *"before solomon summons a spirit, allow the user to crtl+z
to stop solomon from doing that (he should not send any messages he should just
stop doing that specific inbox item) and then insert the prompt back into the
prompt box for the user to edit. if the last prompt had to be placed in the
pending messages section ... then ctrl+z should remove it from the pending list
and insert it back into the prompt box"*.

TWO CASES, ONE PATH. He named them separately and they are the same act with the
item resting in a different place, so `cancel()` is one function and the caller
does not have to know which one it hit:

  * the order is still in `inbox/queue/` — nobody drained it, so nothing has
    happened and nothing has to be stopped. It moves to `cancelled/`.
  * the order has been drained and a SUMMONER RUN holds it — Solomon exists and
    is deciding. Nothing has gone out yet, so cancelling means Solomon must not
    be allowed to dispatch, hand over, ask or write a note for it.

...and the third case, which is the one this module exists to be honest about:
**the summon has already gone out**, and then Ctrl+Z does NOTHING and says so.
`docs/DESIGN.md` §10.2 — refuse visibly, never no-op, and never half-cancel a
thing that has already reached a spirit.

HOW A RUNNING SOLOMON IS ACTUALLY STOPPED. He is a `claude -p` process, so
nothing here can reason with him — but every act he is allowed to perform goes
through `boardctl.py`, and that is a program of ours. So:

  * `board-watch.work_the_queue` calls `begin_run()` with the drained items,
    immediately before it spawns, and `end_run()` after.
  * every WRITE verb in `boardctl.py` calls `claim()` first. It stamps the run
    as having ACTED and returns False — refusing the verb — if he cancelled it.
  * `cancel()` marks the run cancelled and then reads `acted` back.

The stamp and the mark take the same `flock` on the same file, in the opposite
order, which is what makes the answer never a guess: either the mark lands first
(nothing was dispatched, and nothing now can be) or the stamp did (something is
already out there, and `cancel()` reports it gone and changes nothing). There is
no interleaving that both dispatches a spirit and tells him it did not.

NOTHING IS DELETED. `cancelled/` is a fifth resting place beside `queue/`,
`to/`, `taken/`, `dropped/` and `editing/`, and the conservation property
`boardagents.py` argues for holds across it: an order is in exactly one
directory at every instant, moved only by `os.replace`, and what he wrote is
still on disk after he takes it back. The text is also handed BACK to him — that
is the whole point of the key — so the copy on disk is a record, not the only one.

ONE ITEM, NOT A RUN. A summoner run that carries SEVERAL of his orders cannot
have one of them cancelled: the gate is per-run, and refusing every verb would
abandon the others too. That case is reported as `shared` and does nothing — his
words were *"stop doing that specific inbox item"*, and taking two more with it
is the opposite of what the key is for.
"""

import fcntl
import json
import os
import re
import time

import boardagents as ba


def _root():
    #: The same state root every other board file lives under. `boardagents`
    #: owns it; this module adds two directories inside it and no new location.
    return ba._root()


def _orch_dir():
    """One file per LIVE summoner run: `orch/<aid>.json`.

    Per run, not one global file, because two orchestrators can overlap (two
    things typed close together) and they are both Solomon — see
    `boardagents.ORCHESTRATOR_NAME`. A cancel has to reach exactly the run that
    holds the order.
    """
    d = os.path.join(_root(), "orch")
    os.makedirs(d, exist_ok=True)
    return d


def _name(mid):
    """An order's file NAME from its id, or None. A name, never a path: an id
    that walks out of its directory is refused rather than sanitised into
    something else's file (the same rule as `boardagents._queued_file`)."""
    s = str(mid or "")
    if not s or s != os.path.basename(s) or s.startswith("."):
        return None
    if not re.fullmatch(r"[0-9A-Za-z._-]+", s):
        return None
    return s + ".json"


def _stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


# ---------------------------------------------------------- the last thing sent
# The key acts on ONE order — the last he submitted through the box at the top —
# so that id has to survive the app being closed and opened again. It is a file
# for the same reason every message here is: the GUI is not the only writer, and
# in-memory state would make the key silently dead after a relaunch.
def _last_path():
    return os.path.join(_root(), "last-order.json")


def remember(msg):
    """Called by the app when what he typed went into the queue as an ORDER.

    Only the top box: a note addressed to a running spirit is a different act
    with its own row, its own menu and no summon to cancel.
    """
    if not msg or msg.get("to"):
        return None
    mid = ba.msg_id(msg)
    if not mid:
        return None
    rec = {"id": mid, "text": msg.get("text", ""), "at": _stamp()}
    try:
        ba._write_json(_last_path(), rec)
    except OSError:
        return None
    return rec


def last():
    return ba._read_json(_last_path())


def forget():
    try:
        os.unlink(_last_path())
    except OSError:
        pass


# ------------------------------------------------------------ the summoner runs
def _run_path(aid):
    n = _name(ba.clean_id(aid) if aid else "")
    return os.path.join(_orch_dir(), n) if n else None


def begin_run(aid, msgs):
    """A summoner run, and the orders it is about to be given.

    Written BEFORE the spawn, like `drain()` moves before the spawn: a run that
    exists and cannot be named is a run he cannot take anything back from.
    """
    path = _run_path(aid)
    if path is None:
        return None
    rec = {"aid": ba.clean_id(aid), "started": _stamp(), "acted": False,
           "cancelled": False,
           "items": [{"id": ba.msg_id(m), "text": m.get("text", "")}
                     for m in (msgs or [])]}
    try:
        ba._write_json(path, rec)
    except OSError:
        return None
    return rec


def end_run(aid):
    """The run is over. Returns True if he had cancelled it.

    The caller (board-watch) needs that answer to keep its own promise: a
    cancelled run's nonzero exit must NOT put his sentence back on the board as
    a failure, because it did not fail — he took it back.
    """
    path = _run_path(aid)
    if path is None:
        return False
    rec = ba._read_json(path) or {}
    try:
        os.unlink(path)
    except OSError:
        pass
    return bool(rec.get("cancelled"))


def _locked(path):
    """Open the run file for read/modify/write under an exclusive `flock`.

    Advisory, on the run file itself, and held across the read AND the write —
    that is what makes `claim()` and `cancel()` order themselves rather than
    race. Returns an open file, or None when there is no run (an ordinary
    spirit, a shell, a test) — in which case there is nothing to gate.
    """
    if path is None or not os.path.exists(path):
        return None
    try:
        fh = open(path, "r+")
    except OSError:
        return None
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    except OSError:
        fh.close()
        return None
    return fh


def _read(fh):
    try:
        fh.seek(0)
        d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(fh, rec):
    #: In place, under the lock, rather than through `_write_json`'s atomic
    #: replace: a replace would swap the inode out from under the other side's
    #: `flock`, and the lock is the whole mechanism here. The file is one small
    #: object written by one holder of the lock at a time.
    fh.seek(0)
    fh.truncate()
    json.dump(rec, fh, indent=1, sort_keys=True)
    fh.flush()
    os.fsync(fh.fileno())


def claim(aid=None):
    """May the caller act? Called by every WRITE verb in `boardctl.py`.

    True for anything that is not a summoner run at all — a spirit, his own
    shell, a test — which is most callers and must stay unaffected.

    False only for a run he has cancelled, and then the verb refuses. Acting is
    STAMPED before the act, so a `cancel()` arriving one instant later reads
    `acted` and reports the summon gone instead of claiming it stopped one.
    """
    fh = _locked(_run_path(aid or ba.self_id()))
    if fh is None:
        return True
    try:
        rec = _read(fh)
        if rec.get("cancelled"):
            return False
        if not rec.get("acted"):
            rec["acted"] = True
            rec["actedAt"] = _stamp()
            _write(fh, rec)
        return True
    finally:
        fh.close()


def cancelled(aid=None):
    """Read-only: has this run been taken back? (`claim()` is the gate.)"""
    rec = ba._read_json(_run_path(aid or ba.self_id()) or "") or {}
    return bool(rec.get("cancelled"))


def _run_holding(mid):
    """The path of the live run that was given this order, or None."""
    try:
        names = sorted(os.listdir(_orch_dir()))
    except OSError:
        return None
    for n in names:
        if not n.endswith(".json") or n.startswith("."):
            continue
        p = os.path.join(_orch_dir(), n)
        rec = ba._read_json(p) or {}
        if any(str(i.get("id")) == str(mid) for i in rec.get("items") or []):
            return p
    return None


# --------------------------------------------------------------- the one path
def _rest(name, text=""):
    """Move an order to `cancelled/` from wherever it is resting.

    `queue/` is the case where nothing has happened; `taken/` is the case where
    a drain moved it and the run has been stopped. Moving it out of `taken/`
    also takes it out of `requeue_taken()`'s reach, so a run that dies holding a
    cancelled order does not hand it to the next one.
    """
    dest = os.path.join(ba.inbox_dir("cancelled"), name)
    for src in (os.path.join(ba.inbox_dir("queue"), name),
                os.path.join(ba.inbox_dir("taken"), name)):
        try:
            os.replace(src, dest)
        except OSError:
            continue
        rec = ba._read_json(dest) or {}
        rec["state"] = "cancelled"
        rec["cancelledAt"] = _stamp()
        try:
            ba._write_json(dest, rec)
        except OSError:
            pass
        return rec.get("text", text)
    return None


def cancel(mid):
    """Take one order back. THE one path, for both of the cases he named.

    Returns `{"state": ..., "text": ...}`, and `text` is his own words back —
    non-empty only when something really was cancelled, because the caller puts
    it into the prompt box and a box filled from a cancel that did not happen
    would be the worst lie this app could tell.

        queued    it was still in the pending list; nothing had gone out
        stopped   a summoner had it and has been stopped; nothing went out
        shared    that run carries other orders too - nothing done
        summoned  Solomon already acted on it - nothing done
        gone      no such order anywhere - nothing done
    """
    name = _name(mid)
    if name is None:
        return {"state": "gone", "text": "", "others": 0}

    # 1. STILL IN THE QUEUE. The claim is `os.replace`, exactly like every other
    #    move here: either we get the file (and a drain running this instant does
    #    not) or it raises and we fall through to the run that took it.
    text = _rest(name) if os.path.exists(
        os.path.join(ba.inbox_dir("queue"), name)) else None
    if text is not None:
        forget()
        return {"state": "queued", "text": text, "others": 0}

    # 2. A SUMMONER HAS IT.
    path = _run_holding(mid)
    fh = _locked(path)
    if fh is None:
        return {"state": "gone", "text": "", "others": 0}
    try:
        rec = _read(fh)
        items = rec.get("items") or []
        if len(items) > 1:
            return {"state": "shared", "text": "", "others": len(items) - 1}
        if rec.get("acted"):
            return {"state": "summoned", "text": "", "others": 0}
        rec["cancelled"] = True
        rec["cancelledAt"] = _stamp()
        _write(fh, rec)
    finally:
        fh.close()
    said = items[0].get("text", "") if items else ""
    _rest(name, said)
    forget()
    return {"state": "stopped", "text": said, "others": 0}


def undoable():
    """The order Ctrl+Z would take back, or None — so the key is only OFFERED
    while it can honestly do something (§10, §10.2).

    Deliberately the same three questions `cancel()` asks, in the same order,
    and it changes nothing. A stale True is possible (he pressed the key in the
    same instant Solomon dispatched); that lands on `summoned` and is SAID.
    """
    rec = last()
    name = _name((rec or {}).get("id"))
    if name is None:
        return None
    if os.path.exists(os.path.join(ba.inbox_dir("queue"), name)):
        return rec
    run = ba._read_json(_run_holding(rec["id"]) or "") or {}
    items = run.get("items") or []
    if len(items) == 1 and not run.get("acted") and not run.get("cancelled"):
        return rec
    return None
