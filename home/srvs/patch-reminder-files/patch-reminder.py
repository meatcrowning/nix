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
writes at most one bullet, never a duplicate; if you dismiss it while still
stale it comes back next tick; and once you upgrade and flake.lock refreshes,
the age drops below the threshold and it stops re-appearing on its own. The
board is the only state — there is no stamp file to clear.

The bullet is INFORMATION (not a question/decision), so board-watch never spawns
an agent on it.

BOTH MACHINES, EACH ITS OWN BOARD. This deploys via home/ to top and book; each
writes only its own `docs/board.<hostname>.md` (resolved by
`boardparse.ensure_board()`), and the host-appropriate upgrade command is
injected by the nix module as PATCH_REMINDER_UPGRADE_CMD.

Overridable for tests (tools/patch-reminder-test.py):
PATCH_REMINDER_FLAKE_LOCK, PATCH_REMINDER_BOARD, PATCH_REMINDER_BOARDCTL,
PATCH_REMINDER_NOW (ISO-8601), PATCH_REMINDER_STALE_DAYS,
PATCH_REMINDER_UPGRADE_CMD.
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


def nixpkgs_last_modified():
    """Unix timestamp of the locked nixpkgs input, or None if unreadable.

    Prefer the node literally named `nixpkgs`; fall back to any node whose
    locked source is the NixOS/nixpkgs repo, so an aliased input still resolves.
    """
    try:
        with FLAKE_LOCK.open() as fh:
            lock = json.load(fh)
    except (OSError, ValueError):
        return None
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
    lm = loc.get("lastModified") if isinstance(loc, dict) else None
    return lm if isinstance(lm, (int, float)) else None


def already_on_board():
    """Has a patch-cadence bullet already been written onto this host's board?"""
    try:
        return MARKER in BOARD.read_text()
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


def main():
    lm = nixpkgs_last_modified()
    if lm is None:
        # Unreadable lock is a no-op that retries next tick, never a false alarm.
        return 0
    locked = datetime.datetime.fromtimestamp(lm, datetime.timezone.utc)
    age = (now() - locked).days
    if age < STALE_DAYS:
        return 0
    if already_on_board():
        return 0
    lines = [
        "INFORMATION: **Patch cadence** - nixpkgs snapshot is stale, "
        "upgrade when convenient",
        "  The nixpkgs input in ~/nix/flake.lock is %d days old (locked %s). "
        "This is a rolling-unstable box with no auto-upgrade, so kernel, mesa, "
        "Chrome and QtWebEngine only advance when you run an upgrade."
        % (age, locked.date().isoformat()),
        "  Run your upgrade alias `%s` when convenient (its own commit; bumps "
        "flake inputs). This bullet stops on its own once the snapshot is fresh "
        "again; it is only re-written if removed while still stale." % UPGRADE_CMD,
    ]
    if write_bullet(lines):
        sys.stderr.write("patch-reminder: wrote stale-packages bullet "
                         "(%d days)\n" % age)
    return 0


if __name__ == "__main__":
    sys.exit(main())
