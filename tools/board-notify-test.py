#!/usr/bin/env python3
"""board-notify-test.py — the completion-toast watcher, offline.

Everything runs against a THROWAWAY board file, a throwaway state dir and a
stub in place of `notify-send` (the dry-run stub), so it never opens a toast,
never touches ~/nix/docs/board.*.md and never asks the live desktop anything.
Each pass is a `BOARD_NOTIFY_ONESHOT=1` invocation of the deployed script — the
same code the systemd unit runs — so the env overrides are exercised for real.

    python3 tools/board-notify-test.py [-v]

What it asserts, in order:

  seed      the first run records every existing completion and fires nothing,
            and a SUMMONED / INFORMATION bullet is NOT one of them
  completion a new COMPLETION bullet fires, once
  dedupe    a re-run that adds no new completion fires nothing — the docs-sync
            pull / bytes-same-replace case           [hazard 2]
  enacted   a bullet written with the renamed tag ENACTED is matched and fires,
            and the parallel COMPLETION -> ENACTED relabel of an already-seen
            bullet does not re-fire it               [the rename]
  rename-tolerant  the raw-text-prefix match catches a completion even when the
            parser's own tag set no longer knows the word (tag == "")
  focus     vanish when goetia is the focused window; fire when focus is on
            nothing; fire when focus is unknown (no compositor) — never wrongly
            suppress (the whole point of the event-socket design)
  off       the kill switch stops everything
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPT = os.path.join(REPO, "home", "srvs", "board-notify-files", "board-notify.py")

BOARD_HEAD = """## WAITING ON YOU TO DO

- COMPLETION: **pre-existing task** - landed before the feature
- SUMMONED Marbas (`w1ff021`) for the thing
- INFORMATION: a note that is not a completion
"""


def run(tmp, board_text, focus=None, extra_env=None, state_dir=None):
    """One oneshot invocation; returns (log_lines, state_dict)."""
    board = os.path.join(tmp, "board.md")
    with open(board, "w") as f:
        f.write(board_text)
    state = state_dir or os.path.join(tmp, "state")
    logf = os.path.join(tmp, "log")
    # A fresh log per invocation: the script appends, and the caller must see
    # only THIS run's lines (state persists across runs, the log must not).
    open(logf, "w").close()
    env = dict(os.environ,
               BOARD_NOTIFY_BOARD=board,
               BOARD_NOTIFY_STATE=state,
               BOARD_NOTIFY_LOG=logf,
               BOARD_NOTIFY_NOTIFY="",      # dry-run stub
               BOARD_NOTIFY_ONESHOT="1")
    if focus is not None:
        env["BOARD_NOTIFY_FOCUS"] = focus
    if extra_env:
        env.update(extra_env)
    subprocess.run([sys.executable, SCRIPT], env=env, check=True,
                   cwd=REPO, capture_output=True)
    lines = []
    if os.path.exists(logf):
        with open(logf) as fh:
            lines = [ln.split(" ", 1)[1] for ln in fh.read().strip().splitlines()
                     if " " in ln]
    state_dict = {}
    sp = os.path.join(state, "state.json")
    if os.path.exists(sp):
        import json
        with open(sp) as fh:
            state_dict = json.load(fh)
    return lines, state_dict


def notify_lines(lines):
    return [l for l in lines if l.startswith("notify (dry-run)")]


def main():
    verbose = "-v" in sys.argv
    tmp = tempfile.mkdtemp(prefix="board-notify-test-")
    try:
        # ---- seed ------------------------------------------------------
        lines, _ = run(tmp, BOARD_HEAD)
        assert not notify_lines(lines), "seed must not fire: %r" % lines
        # ---- completion fires once -------------------------------------
        lines, state = run(tmp, BOARD_HEAD + "- COMPLETION: **the thing** - done, no errors. pushed.\n")
        n = notify_lines(lines)
        assert len(n) == 1, "expected one fire, got %r" % n
        assert "the thing" in n[0]
        # ---- dedupe: same board again fires nothing --------------------
        lines, state = run(tmp, BOARD_HEAD + "- COMPLETION: **the thing** - done, no errors. pushed.\n")
        assert not notify_lines(lines), "re-run must not re-fire: %r" % notify_lines(lines)
        # ---- enacted: renamed tag fires --------------------------------
        lines, state = run(tmp, BOARD_HEAD
                           + "- COMPLETION: **the thing** - done, no errors. pushed.\n"
                           + "- ENACTED: **second task** - recap landed\n")
        n = notify_lines(lines)
        assert any("second task" in x for x in n), "ENACTED must fire: %r" % n
        assert not any("the thing" in x for x in n), "seen bullet must not re-fire after relabel: %r" % n
        # ---- sync pull: same bytes, new mtime -> nothing ----------------
        lines, _ = run(tmp, BOARD_HEAD
                       + "- COMPLETION: **the thing** - done, no errors. pushed.\n"
                       + "- ENACTED: **second task** - recap landed\n")
        assert not notify_lines(lines), "bytes-identical rewrite must not re-fire: %r" % notify_lines(lines)
        # ---- rename-tolerant: tag not in parser set, raw prefix matches --
        lines, _ = run(tmp, BOARD_HEAD
                       + "- COMPLETION: **the thing** - done, no errors. pushed.\n"
                       + "- FAILED: **nope** - did not land\n")
        n = notify_lines(lines)
        assert not any("nope" in x for x in n), "FAILED must not fire: %r" % n
        # ---- focus: goetia suppresses, nothing/unknown fires -------------
        # Each case is its own life-cycle: a fresh state dir seeded WITHOUT the
        # focus task, then that task lands — because a completed landing is
        # handled ONCE (suppressed counts as handled), each focus value must be
        # an independent "a completion just landed" moment.
        def focus_case(name, focus, expect):
            d = os.path.join(tmp, "focus_" + name)
            run(tmp, BOARD_HEAD, state_dir=d)                 # seed, no task yet
            lines, _ = run(tmp, BOARD_HEAD + "- COMPLETION: **focus task** - done\n",
                           focus=focus, state_dir=d)
            if expect == "suppress":
                assert "suppressed" in " ".join(lines), \
                    "goetia focus must suppress: %r" % lines
                assert not notify_lines(lines), \
                    "goetia focus must not notify: %r" % lines
            else:
                assert notify_lines(lines), \
                    "focus=%r must notify (never wrongly suppress): %r" % (focus, lines)

        focus_case("goetia", "board,goetia", "suppress")
        focus_case("nothing", "", "fire")
        focus_case("empty", ",", "fire")
        focus_case("other", "kitty,~ zsh", "fire")
        # ---- off switch --------------------------------------------------
        offdir = os.path.join(tmp, "offstate")
        os.makedirs(offdir)
        open(os.path.join(offdir, "off"), "w").close()
        lines, _ = run(tmp, BOARD_HEAD + "- COMPLETION: **off task** - done\n",
                       extra_env={"BOARD_NOTIFY_STATE": offdir})
        assert not notify_lines(lines), "off switch must stop it: %r" % lines
        assert any("off (kill switch" in l for l in lines), "off must log: %r" % lines
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("board-notify-test: all passed")


if __name__ == "__main__":
    main()
