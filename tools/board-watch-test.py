#!/usr/bin/env python3
"""board-watch-test.py — the watcher's filter, queue and lock logic, offline.

Everything here runs against a THROWAWAY copy of the store, a throwaway state
directory and a STUB in place of `claude`, so it never spawns an agent, never
touches ~/nix/docs/board.md and never asks the live desktop anything. The one
thing it therefore cannot exercise is the agent itself — that is stated in the
report rather than pretended away.

    python3 tools/board-watch-test.py [-v]

What it asserts, in order:

  seed        a first run records the board and fires nothing (three of his
              decisions are already answered; waking up to three agents is the
              exact opposite of the feature)
  tick        a run with nothing new fires nothing
  answer      ticking a box fires, once, with the right decision
  free text   writing under `> ` fires
  change      changing an existing answer fires again (he is allowed to change
              his mind); clearing one does NOT
  landed      an agent moving the item to LANDED does NOT fire        [hazard 1]
  prose       a pulled edit that rewords the item does NOT fire       [hazard 2]
  new item    a decision that ARRIVES already answered does NOT fire
  queue       with the gate closed nothing fires, and the answer is still there
              two ticks later; opening the gate fires it then          [locked]
  one         two answers at once fire ONE agent, and the second stays queued
  order       ...and the second fires on the next run
  lock        a held flock makes a concurrent run a no-op             [hazard 3]
  kill        the off switch stops everything
  fail        a non-zero agent leaves a note in WAITING ON YOU TO DO, and the
              rest of the file is byte-identical
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
WATCHER = os.path.join(REPO, "home", "srvs", "board-watch-files", "board-watch.py")
VERBOSE = "-v" in sys.argv

FIXTURE = """# Board

Test fixture. Same shape as the real store.

---

## NEEDS YOU

### 1. First question?

Some prose about the first question.

- [ ] Do it the short way
- [ ] Do it the long way

>

*If unanswered:* nothing happens.

### 2. Second question?

- [ ] Yes
- [ ] No

>

*If unanswered:* nothing happens.

---

## WAITING ON YOU TO DO

- **Relaunch `player`** - live source.

---

## IN FLIGHT

| What | Where | Notes |
|---|---|---|
| something | `apps/x` | ongoing |

## LANDED

### 2026-07-28

| Commit | What |
|---|---|
| `abc1234` | did a thing |
"""

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -- " + detail) if
                                                       (detail and not cond) else ""))
    if not cond:
        fails.append(name)


class Rig:
    def __init__(self, d):
        self.d = d
        self.board = os.path.join(d, "board.md")
        self.state = os.path.join(d, "state")
        self.log = os.path.join(d, "watch.log")
        self.fired = os.path.join(d, "fired")
        with open(self.board, "w") as f:
            f.write(FIXTURE)

    def env(self, gate="open", spawn=None):
        e = dict(os.environ)
        e.update(BOARD_WATCH_BOARD=self.board, BOARD_WATCH_STATE=self.state,
                 BOARD_WATCH_LOG=self.log, BOARD_WATCH_GATE=gate,
                 BOARD_WATCH_REPO=REPO,
                 BOARD_WATCH_SPAWN=spawn if spawn is not None
                 else 'echo "$BOARD_WATCH_KEY" >> ' + self.fired)
        return e

    def run(self, gate="open", spawn=None):
        p = subprocess.run([sys.executable, WATCHER], env=self.env(gate, spawn),
                           capture_output=True, text=True, timeout=120)
        if VERBOSE:
            print("    rc=%d %s" % (p.returncode, p.stderr.strip()[:200]))
        return p

    def fires(self):
        try:
            with open(self.fired) as f:
                return [l.strip() for l in f if l.strip()]
        except OSError:
            return []

    def clear(self):
        if os.path.exists(self.fired):
            os.unlink(self.fired)

    def text(self):
        with open(self.board) as f:
            return f.read()

    def edit(self, old, new, count=1):
        """Rewrite the store the way the app does: temp file, then rename."""
        src = self.text()
        assert old in src, "fixture edit did not match: " + old[:40]
        src = src.replace(old, new, count)
        fd, tmp = tempfile.mkstemp(dir=self.d, prefix=".board-", suffix=".md")
        with os.fdopen(fd, "w") as f:
            f.write(src)
        os.replace(tmp, self.board)

    def tail(self, n=1):
        with open(self.log) as f:
            return [l.rstrip() for l in f][-n:]


def main():
    d = tempfile.mkdtemp(prefix="board-watch-test-")
    try:
        r = Rig(d)

        print("seed + quiet ticks")
        r.run()
        check("first run fires nothing", r.fires() == [], str(r.fires()))
        check("first run recorded the board",
              len(json.load(open(os.path.join(r.state, "state.json")))["answers"]) == 2)
        r.run()
        check("a tick with no change fires nothing", r.fires() == [])

        print("a real answer")
        r.edit("- [ ] Do it the short way", "- [x] Do it the short way")
        r.run()
        check("ticking a box fires once", len(r.fires()) == 1, str(r.fires()))
        check("...on the right decision",
              r.fires()[:1] == ["first-question"], str(r.fires()))
        r.clear()
        r.run()
        check("and does not fire again", r.fires() == [])

        print("free text, changes of mind, and clearing")
        r.edit("### 2. Second question?\n\n- [ ] Yes\n- [ ] No\n\n>\n",
               "### 2. Second question?\n\n- [ ] Yes\n- [ ] No\n\n> none of these, do X\n")
        r.run()
        check("free text fires", r.fires() == ["second-question"], str(r.fires()))
        r.clear()
        r.edit("> none of these, do X", "> actually, do Y")
        r.run()
        check("changing his mind fires again", r.fires() == ["second-question"],
              str(r.fires()))
        r.clear()
        r.edit("> actually, do Y", ">")
        r.run()
        check("clearing an answer fires nothing", r.fires() == [])

        print("hazard 1 - the agent's own edits")
        r.clear()
        r.edit("| `abc1234` | did a thing |",
               "| `abc1234` | did a thing |\n| `def5678` | first question, done |")
        r.run()
        check("a new LANDED row fires nothing", r.fires() == [], str(r.fires()))
        r.edit("Some prose about the first question.",
               "Some prose about the first question. Landed in `def5678`; see the\n"
               "note under LANDED.")
        r.run()
        check("an agent rewording the item fires nothing", r.fires() == [],
              str(r.fires()))
        r.edit("- [x] Do it the short way", "- [x] Do it the short way (chosen)")
        r.run()
        check("relabelling the chosen option fires nothing", r.fires() == [],
              str(r.fires()))

        print("hazard 2 - a decision that arrives already answered")
        r.edit("---\n\n## WAITING ON YOU TO DO",
               "### 3. Third question, written and answered in one go?\n\n"
               "- [x] Already decided by an agent\n- [ ] Other\n\n>\n\n"
               "*If unanswered:* nothing.\n\n---\n\n## WAITING ON YOU TO DO")
        r.run()
        check("a new pre-answered decision fires nothing", r.fires() == [],
              str(r.fires()))
        r.edit("- [x] Already decided by an agent\n- [ ] Other",
               "- [ ] Already decided by an agent\n- [x] Other")
        r.run()
        check("...but answering it afterwards does",
              r.fires() == ["third-question-written-and-answered-in-one-go"],
              str(r.fires()))
        r.clear()

        print("the queue - locked, then unlocked")
        r.edit("- [ ] Do it the long way", "- [x] Do it the long way")
        r.run(gate="closed")
        check("a closed gate fires nothing", r.fires() == [])
        check("...and says so once", any("queued" in l for l in r.tail(2)),
              str(r.tail(2)))
        r.run(gate="closed")
        check("still nothing on the next tick", r.fires() == [])
        r.run(gate="open")
        check("and it fires when the gate opens",
              r.fires() == ["first-question"], str(r.fires()))
        r.clear()

        print("one decision per invocation")
        r.edit("- [ ] Yes\n- [ ] No", "- [x] Yes\n- [ ] No")
        r.edit("- [ ] Already decided by an agent\n- [x] Other",
               "- [x] Already decided by an agent\n- [ ] Other")
        r.run()
        check("two answers fire exactly one agent", len(r.fires()) == 1,
              str(r.fires()))
        first = r.fires()[0]
        check("...the first in file order", first == "second-question", first)
        r.run()
        check("the second fires on the next run", len(r.fires()) == 2,
              str(r.fires()))
        check("...and it is the other one",
              r.fires()[1] == "third-question-written-and-answered-in-one-go",
              str(r.fires()))
        r.clear()

        print("hazard 3 - concurrency")
        r.edit("- [x] Yes\n- [ ] No", "- [ ] Yes\n- [x] No")
        import fcntl
        held = open(os.path.join(r.state, "lock"), "w")
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r.run()
        check("a held lock makes the run a no-op", r.fires() == [], str(r.fires()))
        check("...and says why", any("holds the lock" in l for l in r.tail(1)),
              str(r.tail(1)))
        held.close()
        r.run()
        check("and it runs once the lock is free", len(r.fires()) == 1,
              str(r.fires()))
        r.clear()

        print("the kill switch")
        open(os.path.join(r.state, "off"), "w").close()
        r.edit("- [x] Do it the long way", "- [ ] Do it the long way")
        r.edit("- [x] Do it the short way (chosen)",
               "- [ ] Do it the short way (chosen)")
        r.run()
        check("nothing runs while the off switch is there", r.fires() == [])
        os.unlink(os.path.join(r.state, "off"))

        print("a failing agent tells him on the board")
        r.run()                                   # absorb the un-answering above
        r.clear()
        before = r.text()
        r.edit("- [ ] Do it the short way", "- [x] Do it the short way")
        p = r.run(spawn="exit 3")
        check("the watcher itself still exits 0", p.returncode == 0)
        after = r.text()
        note = [l for l in after.splitlines() if "board-watch tried" in l]
        check("a failure note is on the board", len(note) == 1, str(note))
        check("...in WAITING ON YOU TO DO",
              after.index(note[0]) > after.index("## WAITING ON YOU TO DO")
              and after.index(note[0]) < after.index("## IN FLIGHT")
              if note else False)
        check("...naming the decision", bool(note) and "First question" in note[0],
              str(note))
        rest_before = before.replace("- [ ] Do it the short way",
                                     "- [x] Do it the short way")
        rest_after = "\n".join(l for l in after.splitlines()
                               if "board-watch tried" not in l)
        check("...and nothing else in the file moved",
              rest_after.rstrip("\n") == rest_before.rstrip("\n"),
              "%d vs %d chars" % (len(rest_after), len(rest_before)))
        r.clear()
        r.run()
        check("the failure note does not itself fire", r.fires() == [],
              str(r.fires()))

        print("the prompt the agent would get")
        r.edit("- [x] Do it the short way (chosen)", "- [ ] Do it the short way (chosen)")
        r.run()
        r.clear()
        r.edit("- [ ] Do it the short way", "- [x] Do it the short way")
        r.run(spawn="cat > " + os.path.join(d, "prompt.txt"))
        prompt = open(os.path.join(d, "prompt.txt")).read()
        for want in ("`top`", "NEVER rebuild", "-- <explicit> <paths>",
                     "Push to `main`", "never drive his running apps",
                     "First question?", "Do it the short way"):
            check("prompt carries %r" % want, want in prompt)
        check("prompt names only the answered decision",
              "Second question" not in prompt)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print()
    if fails:
        print("FAILED: " + ", ".join(fails))
        return 1
    print("all board-watch assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
