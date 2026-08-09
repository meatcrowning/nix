#!/usr/bin/env python3
"""Nudge onto this host's board when the package set has gone stale.

There is deliberately NO `system.autoUpgrade` on this box: it pins hyprland and
quickshell (flake.nix), and an unattended `nixos-rebuild switch` that ran
`nix flake update` would bump those pins — which can leave the session with no
titlebars or no panel — and roll nixpkgs unsupervised. So this does not upgrade
anything; it REMINDS. When the nixpkgs input in `~/nix/flake.lock` is older than
STALE_DAYS, it writes one board bullet telling the human to upgrade when they
choose. Raised as a finding by the 2026-08-08 security audit: a rolling
nixos-unstable box that only advances on a manual `--upgrade` has an unbounded
patch-exposure window (Chrome / QtWebEngine parse hostile web content daily).

RECURRING BY CONSTRUCTION, unlike board-reminder.py (which fires once ever and
drops a `.done` stamp): this re-derives staleness every tick and only ensures
the bullet exists while stale, keyed off a marker already in the board. So it
writes at most one bullet and never a duplicate, and once the lock refreshes the
age drops below the threshold and it stops on its own.

DISMISSING IT MEANS "NOT YET", AND THAT IS RECORDED. Until 2026-08-08 the board
was the only state, so a dismissal could not be represented at all: he answered
this bullet at 21:59 with "dont update yet, but give me a way to easily see what
packages can be upgraded" — which cleared it and dispatched two workers — and
the next tick wrote it straight back, because nixpkgs was still stale. The nudge
could be overridden but never answered, and would have returned every quarter
hour until he did the one thing he had just said not to do.

So a dismissal now defers, KEYED ON THE LOCKED REVISION it was dismissed at
(`STATE`). That keeps the property the stampless design existed to protect — a
deferral cannot outlive the thing it was about, because the moment `flake.lock`
moves the key no longer matches and the reminder re-arms itself — while letting
"not yet" mean something. DEFER_DAYS is the backstop for the other direction: a
lock that never moves re-arms on the horizon anyway, so a dismissal can delay
this warning but can never silence it for good. Staleness dropping below the
threshold clears the state outright.

The bullet is INFORMATION (not a question/decision), so board-watch never spawns
an agent on it.

BOTH MACHINES, EACH ITS OWN BOARD. This deploys via home/ to top and book; each
writes only its own `docs/board.<hostname>.md` (resolved by
`boardparse.ensure_board()`), and the host-appropriate upgrade command is
injected by the nix module as PATCH_REMINDER_UPGRADE_CMD. The state file is
machine-local (`~/.local/state`, not synced), which is correct: each host
dismisses its own board's bullet.

Overridable for tests (tools/patch-reminder-test.py):
PATCH_REMINDER_FLAKE_LOCK, PATCH_REMINDER_BOARD, PATCH_REMINDER_BOARDCTL,
PATCH_REMINDER_NOW (ISO-8601), PATCH_REMINDER_STALE_DAYS,
PATCH_REMINDER_UPGRADE_CMD, PATCH_REMINDER_STATE, PATCH_REMINDER_DEFER_DAYS.
"""

import datetime
import json
import os
import pathlib
import subprocess
import sys

HOME = pathlib.Path(os.path.expanduser("~"))

FLAKE_LOCK = pathlib.Path(os.environ.get(
    "PATCH_REMINDER_FLAKE_LOCK", HOME / "nix/flake.lock"))
BOARDCTL = pathlib.Path(os.environ.get(
    "PATCH_REMINDER_BOARDCTL", HOME / "nix/apps/board/tools/boardctl.py"))
STALE_DAYS = int(os.environ.get("PATCH_REMINDER_STALE_DAYS", "21"))
#: How long a dismissal holds while the lock sits still. Long enough that
#: "not yet" is respected across a working week, short enough that a box left
#: unpatched for a month is told again.
DEFER_DAYS = int(os.environ.get("PATCH_REMINDER_DEFER_DAYS", "7"))
STATE = pathlib.Path(os.environ.get(
    "PATCH_REMINDER_STATE",
    HOME / ".local/state/patch-reminder/state.json"))
# `update` is the upgrade alias on BOTH hosts (home/prog/zsh.nix): on top it is
# `sudo rebuild-top --upgrade`, on book `nix flake update && rebuild-air`. So the
# single host-neutral token is the correct instruction on either machine, and
# nothing host-specific needs to reach this script.
UPGRADE_CMD = os.environ.get("PATCH_REMINDER_UPGRADE_CMD", "update")

#: THIS HOST'S BOARD. Same rule board-reminder.py uses — stated once in
#: boardparse and imported, not restated. ensure_board() seeds an empty board on
#: a machine that has never had one.
sys.path[:0] = [str(HOME / "nix/apps/board"), str(HOME / "nix/apps/pylib")]
import boardparse as _bp                                          # noqa: E402

BOARD = pathlib.Path(os.environ.get("PATCH_REMINDER_BOARD")
                     or _bp.ensure_board())

#: N-independent so the idempotence check does not break when the age changes.
MARKER = "**Patch cadence**"


def now():
    override = os.environ.get("PATCH_REMINDER_NOW")
    if override:
        return datetime.datetime.fromisoformat(override.replace("Z", "+00:00"))
    return datetime.datetime.now(datetime.timezone.utc)


def nixpkgs_locked():
    """`(lastModified, key)` for the locked nixpkgs input, or `(None, None)`.

    `key` identifies WHICH snapshot is locked, so a deferral can be pinned to it
    and expire the instant the lock moves. The revision is the honest answer;
    `lastModified` is the fallback for a lock node that carries no rev, and is
    just as good a key here since any update changes it too.

    Prefer the node literally named `nixpkgs`; fall back to any node whose
    locked source is the NixOS/nixpkgs repo, so an aliased input still resolves.
    """
    try:
        with FLAKE_LOCK.open() as fh:
            lock = json.load(fh)
    except (OSError, ValueError):
        return None, None
    nodes = lock.get("nodes") or {}
    node = nodes.get("nixpkgs")
    if not (isinstance(node, dict) and "locked" in node):
        for cand in nodes.values():
            loc = cand.get("locked") if isinstance(cand, dict) else None
            if isinstance(loc, dict) and loc.get("repo") == "nixpkgs" \
                    and loc.get("owner") in ("NixOS", "nixos"):
                node = cand
                break
    loc = node.get("locked") if isinstance(node, dict) else None
    if not isinstance(loc, dict):
        return None, None
    lm = loc.get("lastModified")
    if not isinstance(lm, (int, float)):
        return None, None
    rev = loc.get("rev")
    return lm, (rev if isinstance(rev, str) and rev else "lm:%d" % int(lm))


def board_text():
    """This host's board, or None if it cannot be read.

    None is NOT "the bullet is absent": a board we cannot read is one we must
    neither write into nor draw conclusions from, and the two callers below both
    need to tell those apart.
    """
    try:
        return BOARD.read_text()
    except OSError:
        return None


def load_state():
    try:
        with STATE.open() as fh:
            st = json.load(fh)
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(st):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".tmp")
        with tmp.open("w") as fh:
            json.dump(st, fh, indent=1, sort_keys=True)
        os.replace(tmp, STATE)
    except OSError as exc:
        # Unwritable state degrades to the old always-renag behaviour rather
        # than to silence: never suppress the warning on a write we did not make.
        sys.stderr.write("patch-reminder: cannot write %s: %s\n" % (STATE, exc))


def clear_state():
    try:
        STATE.unlink()
    except OSError:
        pass


def write_bullet(lines):
    proc = subprocess.run(
        [sys.executable, str(BOARDCTL), "--board", str(BOARD),
         "note", "\n".join(lines)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr or "boardctl note failed\n")
        return False
    return True


def main():
    lm, key = nixpkgs_locked()
    if lm is None:
        # Unreadable lock is a no-op that retries next tick, never a false alarm.
        return 0
    locked = datetime.datetime.fromtimestamp(lm, datetime.timezone.utc)
    age = (now() - locked).days
    if age < STALE_DAYS:
        # Fresh again: forget any deferral, so the NEXT time it goes stale is
        # judged on its own merits.
        clear_state()
        return 0

    text = board_text()
    if text is None:
        return 0                       # refuse to write, or reason, in the dark

    st = load_state()
    if MARKER in text:
        # Standing on the board. Remember which snapshot it is about, so a later
        # tick can tell "he dismissed it" from "it was never written".
        if st.get("wroteFor") != key:
            save_state({"wroteFor": key})
        return 0

    # Not on the board. Either we have never written it for this snapshot, or he
    # took it off — and only the state file can say which.
    if st.get("deferredKey") == key:
        deferred_at = st.get("deferredAt")
        try:
            since = (now() - datetime.datetime.fromisoformat(deferred_at)).days
        except (TypeError, ValueError):
            since = DEFER_DAYS         # unparseable stamp re-arms, never silences
        if since < DEFER_DAYS:
            return 0
        sys.stderr.write("patch-reminder: deferral expired after %d days, "
                         "re-arming\n" % since)
    elif st.get("wroteFor") == key:
        # We put it there, it is gone, and the lock has not moved: a dismissal.
        save_state({"wroteFor": key, "deferredKey": key,
                    "deferredAt": now().isoformat()})
        sys.stderr.write("patch-reminder: dismissed at %s - deferring up to "
                         "%d days or until the lock moves\n" % (key[:12],
                                                                DEFER_DAYS))
        return 0

    lines = [
        "INFORMATION: **Patch cadence** - nixpkgs snapshot is stale, "
        "upgrade when convenient",
        "  The nixpkgs input in ~/nix/flake.lock is %d days old (locked %s). "
        "This is a rolling-unstable box with no auto-upgrade, so kernel, mesa, "
        "Chrome and QtWebEngine only advance when you run an upgrade."
        % (age, locked.date().isoformat()),
        "  Run your upgrade alias `%s` when convenient (its own commit; bumps "
        "flake inputs). Clear this bullet and it stays quiet until the lock "
        "actually moves, or %d days pass." % (UPGRADE_CMD, DEFER_DAYS),
    ]
    if write_bullet(lines):
        save_state({"wroteFor": key})
        sys.stderr.write("patch-reminder: wrote stale-packages bullet "
                         "(%d days)\n" % age)
    return 0


if __name__ == "__main__":
    sys.exit(main())
