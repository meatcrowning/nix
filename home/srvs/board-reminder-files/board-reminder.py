#!/usr/bin/env python3
"""Put one bullet on this host's board once his weekly usage limit has reset.

He asked (2026-07-30) for a reminder that fires AFTER the weekly Claude usage
window rolls over, so the FOCUS-signal work can be picked up then rather than
being started against a 91%-spent week. That is the whole of this file: a list
of REMINDERS, each with a condition and a bullet, each fired at most once ever.

WHERE THE RESET TIME COMES FROM. Claude Code caches the account's own limit
state in `~/.claude.json` (NOT `~/.claude/`, so it does not sync between the
machines) under `cachedUsageUtilization.utilization`:

    limits[] -> {"kind": "weekly_all", "percent": 91,
                 "resets_at": "2026-08-02T03:00:00.346161+00:00"}
    seven_day -> {"utilization": 91, "resets_at": "..."}   # same instant

Read on top 2026-07-30. `weekly_all` is preferred and `seven_day` is the
fallback; both are ISO-8601 with an offset, so they are compared as absolute
instants and the local timezone never enters into it.

TWO WAYS TO OBSERVE THE RESET, because the cache is only refreshed when he
actually runs Claude Code:

  * the CLOCK. The first tick that can read a weekly `resets_at` records it as
    the target, and any later tick where `now >= target` fires. This is the one
    that works even if he never opens Claude Code again.
  * the CACHE MOVING. If a later tick reads a `resets_at` strictly after the
    recorded target, the window has rolled — Anthropic issued a new one — and
    that is a reset observed directly, whatever the clock says about drift or a
    window that ended early.

If neither is readable (no `~/.claude.json`, no cached utilization), the tick
does nothing and the timer tries again in fifteen minutes. That is also the
documented fallback: the mechanism IS the periodic re-check.

ONE BULLET PER BOARD, and each host writes its own. There is one board per
machine since 2026-07-30 (`docs/board.<hostname>.md`, resolved by
`boardparse.ensure_board()`); the files sync as files but nothing on top writes
book's board, so the host affinity and the 24h grace this used to carry — which
existed only because a bullet written on top appeared on book's board too — are
gone. The condition is per-machine anyway: the weekly window is read from
`~/.claude.json`, which does NOT sync.

IDEMPOTENCE still stands, and is now the only guard needed: before writing
anything, the marker (a substring of the bullet, e.g. the doc path) is looked
for in THIS host's current board. Found means it is already there — he moved it,
or a stamp was deleted — and this host disarms without writing a second copy.

SELF-DISARMING. A fired reminder drops a stamp in
`~/.local/state/board-reminder/<id>.done` and is skipped from then on. The
stamp is machine-local like every other bit of board state, which is exactly
what the idempotence check above is for. To re-arm one by hand, delete its
stamp; to stop the whole thing, `systemctl --user disable --now
board-reminder.timer`.

Everything is overridable by environment variable so it can be tested against
a scratch board and a scratch clock without touching his:
`BOARD_REMINDER_STATE`, `BOARD_REMINDER_CLAUDE_JSON`, `BOARD_REMINDER_BOARD`,
`BOARD_REMINDER_NOW` (ISO-8601), `BOARD_REMINDER_BOARDCTL`.
Harness: `tools/board-reminder-test.py`.
"""

import datetime
import json
import os
import pathlib
import subprocess
import sys

HOME = pathlib.Path(os.path.expanduser("~"))

STATE = pathlib.Path(os.environ.get(
    "BOARD_REMINDER_STATE", HOME / ".local/state/board-reminder"))
CLAUDE_JSON = pathlib.Path(os.environ.get(
    "BOARD_REMINDER_CLAUDE_JSON", HOME / ".claude.json"))
BOARDCTL = pathlib.Path(os.environ.get(
    "BOARD_REMINDER_BOARDCTL", HOME / "nix/apps/board/tools/boardctl.py"))

#: THIS HOST'S BOARD. The rule (`docs/board.<hostname>.md`, one per machine) is
#: stated once, in `boardparse`, and imported rather than restated here — which
#: is worth the coupling to `apps/board` that this file otherwise avoids.
#: `ensure_board()` also seeds an empty board on a machine that has never had
#: one, so book gets its board from whichever of the three board programs runs
#: there first, with nothing for him to run by hand.
sys.path[:0] = [str(HOME / "nix/apps/board"), str(HOME / "nix/apps/pylib")]
import boardparse as _bp                                          # noqa: E402

BOARD = pathlib.Path(os.environ.get("BOARD_REMINDER_BOARD")
                     or _bp.ensure_board())


# --------------------------------------------------------------- reminders

#: Each: `id` names the stamp file; `marker` is the substring looked for in the
#: live board to decide "somebody already wrote this" (pick something that
#: cannot occur by accident — a doc path is ideal); `lines` is the bullet, first
#: line tagged and at most twelve words, the rest INDENTED continuation. See
#: `boardparse.check_short_summary` / `check_one_ask` for what is refused.
REMINDERS = [
    {
        "id": "focus-signal-after-weekly-reset",
        "when": "weekly-usage-reset",
        "marker": "docs/focus-signal.md",
        "lines": [
            "INFORMATION: **FOCUS signal** - your weekly usage has reset, "
            "pick this up",
            "  Two programs decide independently whether the same window is "
            "focused and nothing reconciles them, so a document greys while "
            "its titlebar stays lit.",
            "  FOCUS deletes the second source by pushing the compositor's "
            "answer down the vtb socket beside WAKE - about an afternoon. "
            "The write-up is `docs/focus-signal.md`.",
        ],
    },
]


# ------------------------------------------------------------------- clock

def now():
    override = os.environ.get("BOARD_REMINDER_NOW")
    if override:
        return parse_ts(override)
    return datetime.datetime.now(datetime.timezone.utc)


def parse_ts(text):
    """ISO-8601 with an offset -> an aware datetime, or None.

    Python's `fromisoformat` handles the `+00:00` these carry; it does not
    handle a trailing `Z`, which the API has not used here but might.
    """
    if not text:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


# ------------------------------------------------------- the weekly window

def weekly_reset():
    """When the weekly usage window next rolls, per Claude Code's own cache.

    None if the file is missing, unreadable, or carries no weekly entry — the
    caller then simply tries again on the next tick.
    """
    try:
        with CLAUDE_JSON.open() as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    util = (data.get("cachedUsageUtilization") or {}).get("utilization") or {}
    for lim in util.get("limits") or []:
        if isinstance(lim, dict) and lim.get("kind") == "weekly_all":
            got = parse_ts(lim.get("resets_at"))
            if got:
                return got
    return parse_ts((util.get("seven_day") or {}).get("resets_at"))


# ------------------------------------------------------------------- state

def state_file(rid):
    return STATE / (rid + ".json")


def load_state(rid):
    try:
        with state_file(rid).open() as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(rid, st):
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = state_file(rid).with_suffix(".tmp")
    with tmp.open("w") as fh:
        json.dump(st, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, state_file(rid))


def done_stamp(rid):
    return STATE / (rid + ".done")


def disarm(rid, why):
    STATE.mkdir(parents=True, exist_ok=True)
    done_stamp(rid).write_text(
        "%s %s\n" % (now().isoformat(timespec="seconds"), why))


# ------------------------------------------------------------------ firing

def already_on_board(marker):
    """Has this bullet already been written onto THIS host's board?"""
    try:
        return marker in BOARD.read_text()
    except OSError:
        # No board to read is not "not written": refuse to write into the dark.
        return True


def write_bullet(lines):
    proc = subprocess.run(
        [sys.executable, str(BOARDCTL), "--board", str(BOARD),
         "note", "\n".join(lines)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr or "boardctl note failed\n")
        return False
    return True


def due(rem, st):
    """(fire?, reason, updated state) for one reminder, this tick."""
    if rem.get("when") != "weekly-usage-reset":
        return False, "unknown condition %r" % rem.get("when"), st

    reset = weekly_reset()
    target = parse_ts(st.get("target"))

    if target is None:
        if reset is None:
            return False, "no weekly reset time cached yet", st
        st = dict(st, target=reset.isoformat())
        return False, "armed for %s" % reset.isoformat(), st

    if now() >= target:
        return True, "the clock passed %s" % target.isoformat(), st
    if reset is not None and reset > target:
        # The cache issued a new window: the old one ended, whatever the clock
        # thinks. Keep the newer instant on record so the log reads honestly.
        return True, "the cached window moved to %s" % reset.isoformat(), st
    return False, "waiting for %s" % target.isoformat(), st


def run_one(rem):
    rid = rem["id"]
    if done_stamp(rid).exists():
        return "%s: already done" % rid

    st = load_state(rid)
    fire, why, st = due(rem, st)
    save_state(rid, st)
    if not fire:
        return "%s: %s" % (rid, why)

    if already_on_board(rem["marker"]):
        disarm(rid, "already on the board")
        return "%s: already on the board, disarmed" % rid

    if not write_bullet(rem["lines"]):
        return "%s: boardctl refused it - left armed" % rid
    disarm(rid, why)
    return "%s: written (%s)" % (rid, why)


def main():
    for rem in REMINDERS:
        print(run_one(rem))
    return 0


if __name__ == "__main__":
    sys.exit(main())
