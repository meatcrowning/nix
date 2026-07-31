#!/usr/bin/env python3
"""Harness for `home/srvs/board-reminder-files/board-reminder.py`.

Everything runs against a scratch board, a scratch `~/.claude.json` and a
scratch clock (`BOARD_REMINDER_NOW`) in a temp directory — his board, his
state and his real usage cache are never read or written. Run it after
touching the script or the reminder list:

    python3 tools/board-reminder-test.py

Covers: arming from the cached weekly reset; not firing early; firing on the
clock; firing because the cached window moved; firing at most once; the
idempotence check against a board that already carries the bullet; each host
writing its OWN board with no affinity or grace (one board per host since
2026-07-30); and a missing/garbage `~/.claude.json` being a no-op that retries
rather than an error.
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = HERE / "home/srvs/board-reminder-files/board-reminder.py"
BOARDCTL = HERE / "apps/board/tools/boardctl.py"

RESET = "2026-08-02T03:00:00+00:00"
BEFORE = "2026-08-01T12:00:00+00:00"
AFTER = "2026-08-02T04:00:00+00:00"
MUCH_LATER = "2026-08-04T04:00:00+00:00"

BOARD_SKELETON = """# Board

---

## NEEDS YOU

---

## WAITING ON YOU TO DO (not decide)


---

## LANDED

Newest first. Append-only.
"""

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (
        "" if cond else "\n         " + str(detail)))
    if not cond:
        fails.append(name)


class Scratch:
    def __init__(self, tmp, reset=RESET):
        self.dir = pathlib.Path(tmp)
        self.board = self.dir / "board.top.md"
        self.board.write_text(BOARD_SKELETON)
        self.state = self.dir / "state"
        self.claude = self.dir / "claude.json"
        self.set_reset(reset)

    def set_reset(self, reset):
        if reset is None:
            self.claude.write_text("{}")
            return
        self.claude.write_text(json.dumps({
            "cachedUsageUtilization": {"utilization": {
                "seven_day": {"utilization": 91, "resets_at": reset},
                "limits": [
                    {"kind": "session", "resets_at": "2026-07-31T10:00:00+00:00"},
                    {"kind": "weekly_all", "percent": 91, "resets_at": reset},
                ],
            }},
        }))

    def tick(self, now):
        env = dict(os.environ)
        env.update({
            "BOARD_REMINDER_STATE": str(self.state),
            "BOARD_REMINDER_CLAUDE_JSON": str(self.claude),
            "BOARD_REMINDER_BOARD": str(self.board),
            "BOARD_REMINDER_BOARDCTL": str(BOARDCTL),
            "BOARD_REMINDER_NOW": now,
        })
        # An agent id would make boardctl attribute the bullet to a card and
        # mark that agent as having reported; a timer is nobody.
        env.pop("BOARD_AGENT_ID", None)
        env.pop("BOARD_ORDER", None)
        return subprocess.run([sys.executable, str(SCRIPT)],
                              capture_output=True, text=True, env=env)

    def bullets(self):
        body = self.board.read_text()
        head = body.split("## WAITING ON YOU TO DO")[1].split("## LANDED")[0]
        return [ln for ln in head.splitlines() if ln.startswith("- ")]


def case(name, fn, reset=RESET):
    print(name)
    with tempfile.TemporaryDirectory() as tmp:
        fn(Scratch(tmp, reset))


def t_arm_then_fire(s):
    r = s.tick(BEFORE)
    check("first tick arms, writes nothing", not s.bullets(), r.stdout)
    check("first tick says so", "armed for" in r.stdout, r.stdout)
    check("target recorded", RESET in (
        s.state / "focus-signal-after-weekly-reset.json").read_text())

    r = s.tick(BEFORE)
    check("still nothing before the reset", not s.bullets(), r.stdout)

    r = s.tick(AFTER)
    check("fires once the clock passes the reset", len(s.bullets()) == 1,
          r.stdout + r.stderr)
    check("the bullet cites the write-up",
          "docs/focus-signal.md" in s.board.read_text())
    check("the bullet is tagged INFORMATION",
          s.bullets() and "INFORMATION:" in s.bullets()[0], s.bullets())
    check("disarmed", (s.state / "focus-signal-after-weekly-reset.done").exists())

    r = s.tick(MUCH_LATER)
    check("does not nag", len(s.bullets()) == 1, r.stdout)
    check("says it is done", "already done" in r.stdout, r.stdout)


def t_window_moved(s):
    s.tick(BEFORE)
    check("armed, nothing written", not s.bullets())
    # He kept working; the cache now names NEXT week's window. That is a reset
    # observed directly, even though this clock has not reached the old one.
    s.set_reset("2026-08-09T03:00:00+00:00")
    r = s.tick(BEFORE)
    check("fires when the cached window moves on", len(s.bullets()) == 1,
          r.stdout + r.stderr)
    check("and says why", "moved to" in r.stdout, r.stdout)


def t_no_cache(s):
    r = s.tick(BEFORE)
    check("no cached reset is a no-op", not s.bullets(), r.stdout)
    check("exit 0, not an error", r.returncode == 0, r.stderr)
    check("says it will retry", "no weekly reset" in r.stdout, r.stdout)
    s.set_reset(RESET)
    s.tick(BEFORE)
    check("arms once the cache appears",
          (s.state / "focus-signal-after-weekly-reset.json").exists())


def t_garbage_cache(s):
    s.claude.write_text("{ not json at all")
    r = s.tick(BEFORE)
    check("garbage cache is a no-op", not s.bullets() and r.returncode == 0,
          r.stdout + r.stderr)


def t_already_on_board(s):
    s.tick(BEFORE)
    # The bullet already sitting there — he moved it back, or a `.done` stamp
    # was deleted. Never a second copy.
    s.board.write_text(s.board.read_text().replace(
        "## WAITING ON YOU TO DO (not decide)\n",
        "## WAITING ON YOU TO DO (not decide)\n\n- INFORMATION: **FOCUS "
        "signal** - see `docs/focus-signal.md`\n"))
    before = len(s.bullets())
    r = s.tick(AFTER)
    check("does not write a second copy", len(s.bullets()) == before, r.stdout)
    check("disarms instead", "already on the board" in r.stdout, r.stdout)
    check("stamped done", (s.state / "focus-signal-after-weekly-reset.done").exists())


def t_no_affinity(s):
    """Every host writes its own board, at once. There is no owner and no
    grace: one board per host since 2026-07-30, so a bullet on top's board is
    not a bullet on book's and waiting for the other machine would just mean
    book never got told."""
    s.tick(BEFORE)
    r = s.tick(AFTER)
    check("writes immediately, whichever host this is",
          len(s.bullets()) == 1, r.stdout + r.stderr)
    check("nothing waits for another machine",
          "grace" not in r.stdout and "owns this" not in r.stdout, r.stdout)
    r = s.tick(MUCH_LATER)
    check("and only once", len(s.bullets()) == 1, r.stdout)


def main():
    case("arm, hold, fire, disarm", t_arm_then_fire)
    case("the cached window moving is a reset", t_window_moved)
    case("no cached reset yet", t_no_cache, reset=None)
    case("unreadable cache", t_garbage_cache)
    case("the bullet is already there", t_already_on_board)
    case("no affinity, no grace: this host writes its own board", t_no_affinity)
    print()
    if fails:
        print("FAILED: " + ", ".join(fails))
        return 1
    print("all good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
