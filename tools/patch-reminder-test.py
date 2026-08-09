#!/usr/bin/env python3
"""Harness for home/srvs/patch-reminder-files/patch-reminder.py.

The thing under test is a NUDGE WITH A MEMORY, and both halves are load-bearing
in opposite directions: it must not nag about a decision he already made, and it
must not be silenceable for good. So the cases below are mostly about the seam
between those — a dismissal defers, a moved lock re-arms it instantly, and the
horizon re-arms it even if the lock never moves.

Everything is driven through the script's own env overrides against a scratch
board, a scratch lock and a scratch state file; nothing here touches his board,
his flake.lock or his real state dir. `boardctl` is stubbed by a script that
appends the note, so no board machinery is exercised — this is about WHEN it
writes, which is the part that was wrong.

Run it with the board's pyside6 python (patch-reminder imports boardparse):
    /etc/profiles/per-user/lam/bin/goetia is wrapped over that env; resolve it
    the way tools/board-test.py does, or just:
        $(sed -n 's/.*exec \\(.*python3\\) .*/\\1/p' $(readlink -f $(command -v goetia))) \\
            tools/patch-reminder-test.py
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE.parent / "home/srvs/patch-reminder-files/patch-reminder.py"
MARKER = "**Patch cadence**"

DAY = 86400
FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        FAILURES.append(name)


class Env:
    """One scratch world: a lock, a board, a state file and a stub boardctl."""

    def __init__(self, tmp, age_days=30, rev="rev-aaa"):
        self.tmp = pathlib.Path(tmp)
        self.lock = self.tmp / "flake.lock"
        self.board = self.tmp / "board.test.md"
        self.state = self.tmp / "state.json"
        self.boardctl = self.tmp / "stub-boardctl.py"
        self.boardctl.write_text(
            "import sys, pathlib\n"
            "# argv: --board <path> note <text>\n"
            "b = pathlib.Path(sys.argv[sys.argv.index('--board') + 1])\n"
            "text = sys.argv[-1]\n"
            "b.write_text(b.read_text() + '\\n' + text + '\\n')\n")
        self.board.write_text("## WAITING ON YOU TO DO (not decide)\n")
        self.set_age(age_days, rev)

    def set_age(self, days, rev="rev-aaa"):
        self.lock.write_text(json.dumps({"nodes": {"nixpkgs": {"locked": {
            "lastModified": int(time.time()) - days * DAY,
            "owner": "NixOS", "repo": "nixpkgs", "rev": rev}}}}))

    def run(self, now_iso=None):
        env = dict(os.environ)
        env.update({
            "PATCH_REMINDER_FLAKE_LOCK": str(self.lock),
            "PATCH_REMINDER_BOARD": str(self.board),
            "PATCH_REMINDER_BOARDCTL": str(self.boardctl),
            "PATCH_REMINDER_STATE": str(self.state),
            "PATCH_REMINDER_STALE_DAYS": "21",
            "PATCH_REMINDER_DEFER_DAYS": "7",
        })
        if now_iso:
            env["PATCH_REMINDER_NOW"] = now_iso
        return subprocess.run([sys.executable, str(SCRIPT)], env=env,
                              capture_output=True, text=True)

    @property
    def on_board(self):
        return MARKER in self.board.read_text()

    def dismiss(self):
        """What he does: take the bullet off the board."""
        kept = [ln for ln in self.board.read_text().splitlines()
                if MARKER not in ln]
        self.board.write_text("\n".join(kept) + "\n")

    def state_json(self):
        try:
            return json.loads(self.state.read_text())
        except (OSError, ValueError):
            return {}


def iso_in(days):
    import datetime
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(days=days)).isoformat()


def main():
    print("patch-reminder")

    # 1. fresh lock says nothing, and forgets any deferral it was holding
    with tempfile.TemporaryDirectory() as tmp:
        e = Env(tmp, age_days=3)
        e.state.write_text(json.dumps({"deferredKey": "rev-aaa",
                                       "deferredAt": iso_in(0)}))
        e.run()
        check("fresh lock writes nothing", not e.on_board)
        check("fresh lock clears the deferral", not e.state.exists())

    # 2. stale and unseen -> writes once, and records WHICH snapshot
    with tempfile.TemporaryDirectory() as tmp:
        e = Env(tmp)
        e.run()
        check("stale writes the bullet", e.on_board)
        check("records the snapshot it wrote for",
              e.state_json().get("wroteFor") == "rev-aaa",
              e.state_json())

        # 3. ...and never a duplicate
        e.run()
        check("no duplicate while it stands",
              e.board.read_text().count(MARKER) == 1)

        # 4. he dismisses it -> deferred, nothing rewritten
        e.dismiss()
        e.run()
        check("a dismissal is not rewritten", not e.on_board)
        check("the dismissal is recorded",
              e.state_json().get("deferredKey") == "rev-aaa", e.state_json())

        # 5. still quiet on later ticks while the lock sits still
        e.run()
        e.run()
        check("stays quiet across later ticks", not e.on_board)

        # 6. the horizon re-arms it even though the lock never moved
        e.run(now_iso=iso_in(8))
        check("re-arms after DEFER_DAYS", e.on_board)

    # 7. a MOVED lock re-arms it immediately, horizon or no horizon —
    #    the property the stampless design existed to protect
    with tempfile.TemporaryDirectory() as tmp:
        e = Env(tmp)
        e.run()
        e.dismiss()
        e.run()
        check("deferred before the lock moves", not e.on_board)
        e.set_age(30, rev="rev-bbb")        # still stale, but a DIFFERENT snapshot
        e.run()
        check("a moved lock re-arms at once", e.on_board)

    # 8. an unreadable lock is a no-op, never a false alarm
    with tempfile.TemporaryDirectory() as tmp:
        e = Env(tmp)
        e.lock.write_text("{not json")
        e.run()
        check("unreadable lock writes nothing", not e.on_board)

    # 9. an unreadable board is neither written to nor reasoned about
    with tempfile.TemporaryDirectory() as tmp:
        e = Env(tmp)
        e.run()
        e.dismiss()
        e.board.unlink()
        r = e.run()
        check("missing board is a clean no-op", r.returncode == 0)
        check("missing board records no deferral",
              e.state_json().get("deferredKey") is None, e.state_json())

    print()
    if FAILURES:
        print("FAILED: %s" % ", ".join(FAILURES))
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
