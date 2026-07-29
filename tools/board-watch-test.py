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
  prompt      what the spawned agent is actually told, including that his notes
              can arrive mid-flight
  notes       a note he typed into the board's agents section with nothing
              running: queued, held while the screen is locked, worked by ONE
              agent when the gate opens, drained so it cannot run twice, and —
              if that run fails — quoted verbatim onto the board
  the loop    the three defects behind 2026-07-28's 3,151 starts, kept apart
              because they are three: an EMPTY NEEDS YOU seeds once rather than
              forever (and an old state file is upgraded, not re-seeded); a
              first run still WORKS what he typed; and a run that leaves the
              queue full backs the next ones off — quietly for a shut gate,
              with one bullet on his board when the gate was open

TWO THINGS THIS HARNESS DOES ON HIS BEHALF, both of them the difference between
a green run and a lie:

  * **`XDG_STATE_HOME` is redirected into the rig.** `boardmove`'s stash and
    `boardagents`' inbox both live under it, and without this the run under test
    writes into his live `~/.local/state/board`, where the board app reads it.
  * **The relocation is undone after every run** (`Rig._unmove`). Since
    `boardmove.py`, firing MOVES the decision out of NEEDS YOU, and a stub agent
    that "succeeds" leaves it there — so every later step of this script, which
    goes on editing that decision where he wrote it, silently had nothing to
    edit. It crashed a third of the way in for exactly that reason. The move
    itself is not this file's subject: `apps/board/tools/board-test.py` owns it
    and asserts it byte-for-byte in both directions.
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

sys.path[:0] = [os.path.join(REPO, "apps", "board"), os.path.join(REPO, "apps", "pylib")]
import boardagents as ba                                          # noqa: E402
import boardmove as bm                                            # noqa: E402
import boardparse as bp                                           # noqa: E402

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


#: NEEDS YOU with nothing in it. The RESTING state since everything moved to IN
#: FLIGHT and LANDED, and the shape that made the watcher re-seed forever.
EMPTY_NEEDS = """# Board

Test fixture whose NEEDS YOU is empty - which is a resting state, not a fault.

---

## NEEDS YOU

---

## WAITING ON YOU TO DO

- **Relaunch `player`** - live source.

---

## IN FLIGHT

| What | Where | Notes |
|---|---|---|

## LANDED

### 2026-07-28

| Commit | What |
|---|---|
| `abc1234` | did a thing |
"""


class Rig:
    def __init__(self, d, fixture=FIXTURE):
        self.d = d
        self.board = os.path.join(d, "board.md")
        self.state = os.path.join(d, "state")
        self.log = os.path.join(d, "watch.log")
        self.fired = os.path.join(d, "fired")
        with open(self.board, "w") as f:
            f.write(fixture)

    def env(self, gate="open", spawn=None, **extra):
        e = dict(os.environ)
        e.update({k: str(v) for k, v in extra.items()})
        e.update(BOARD_WATCH_BOARD=self.board, BOARD_WATCH_STATE=self.state,
                 BOARD_WATCH_LOG=self.log, BOARD_WATCH_GATE=gate,
                 BOARD_WATCH_REPO=REPO,
                 # boardmove's stash and boardagents' inbox both live under
                 # XDG_STATE_HOME. Without this the run under test writes into
                 # HIS live `~/.local/state/board`, where the app reads it — a
                 # harness here must redirect it, exactly as board-test.py does.
                 XDG_STATE_HOME=os.path.join(self.d, "xdgstate"),
                 BOARD_WATCH_SPAWN=spawn if spawn is not None
                 else 'echo "$BOARD_WATCH_KEY" >> ' + self.fired)
        return e

    def run(self, gate="open", spawn=None, **extra):
        before = self.text()
        p = subprocess.run([sys.executable, WATCHER],
                           env=self.env(gate, spawn, **extra),
                           capture_output=True, text=True, timeout=120)
        if VERBOSE:
            print("    rc=%d %s" % (p.returncode, p.stderr.strip()[:200]))
        self._unmove(before)
        return p

    def _unmove(self, before):
        """Undo the watcher's RELOCATION of the decision it fired on.

        Since `boardmove.py`, firing moves the decision out of NEEDS YOU and
        into IN FLIGHT, and a stub agent that "succeeds" leaves it there — so
        every later step of this script, which goes on editing that decision
        where he wrote it, found nothing to edit and the whole file below this
        point stopped being exercised. THIS harness is about the trigger, the
        filter, the queue and the lock; `apps/board/tools/board-test.py` owns
        the move and asserts it byte-for-byte in both directions. So put the
        decision back the way `give_back()` does, and carry on.
        """
        after = self.text()
        db, da = bp.parse(before), bp.parse(after)
        keys = {it["key"] for it in da["needs"]}
        gone = [it for it in db["needs"] if it["key"] not in keys]
        if not gone:
            return
        lines = da["lines"]
        for it in gone:
            a, b = bp.item_span(db["lines"], it)
            block = db["lines"][a:b]
            below = db["lines"][b].rstrip("\n") if b < len(db["lines"]) else ""
            title = bp.raw_title(db["lines"], it)
            doc = bp.parse("".join(lines))
            for row in doc["flight"]:
                if bm._norm(row["what"]) == bm._norm(title):
                    lines = bp.remove_row(doc["lines"], row["line"])
                    break
            lines = bp.add_needs_item(lines, block,
                                      below if below.startswith("###") else "")
            # ...in the RIG's state dir. `bm` reads XDG_STATE_HOME on every
            # call, and an unwrapped forget() here would delete a stash out of
            # his live `~/.local/state/board` whenever a key happened to match.
            self.state_home(lambda k=it["key"]: bm.forget(k))
        bp.write(self.board, "".join(lines))

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

    def state_home(self, fn):
        """Run `fn` against the RIG's state dir, not his. `boardagents` reads
        XDG_STATE_HOME on every call, so swapping it round the call is enough
        and there is no module state to reset."""
        old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = os.path.join(self.d, "xdgstate")
        try:
            return fn()
        finally:
            if old is None:
                del os.environ["XDG_STATE_HOME"]
            else:
                os.environ["XDG_STATE_HOME"] = old

    def note(self, text):
        """What the board app's box does when nothing is running."""
        return self.state_home(lambda: ba.send(text))

    def queued(self):
        return self.state_home(lambda: [m["text"] for m in ba.pending()])

    def tail(self, n=1):
        with open(self.log) as f:
            return [l.rstrip() for l in f][-n:]


def check_session_id_is_passed(r):
    """`spawn()` must hand `claude` a `--session-id` it chose.

    That flag is the ONLY reason his board can say what an agent is actually
    doing rather than merely that it is alive: the transcript at
    `~/.claude/projects/*/<uuid>.jsonl` is found by that uuid and tailed by
    `apps/board/boardphase.py`. Lose the flag and every card silently degrades
    to "cannot see what it is doing" — a regression with no error anywhere.

    Checked by importing the watcher and intercepting `subprocess.run`, because
    the stub path (`BOARD_WATCH_SPAWN`) deliberately replaces the whole command
    line and so cannot see it.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("bw_under_test", WATCHER)
    mod = importlib.util.module_from_spec(spec)
    env = r.env()
    old = dict(os.environ)
    os.environ.update({k: v for k, v in env.items() if isinstance(v, str)})
    os.environ.pop("BOARD_WATCH_SPAWN", None)
    seen = {}
    try:
        spec.loader.exec_module(mod)

        class Done(Exception):
            pass

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            raise Done()

        real = mod.subprocess.run
        mod.subprocess.run = fake_run
        try:
            mod.spawn("a prompt", "k", "label", session="fixed-uuid-here")
        except Done:
            pass
        finally:
            mod.subprocess.run = real
    finally:
        os.environ.clear()
        os.environ.update(old)
    cmd = seen.get("cmd") or []
    ok = "--session-id" in cmd and cmd[cmd.index("--session-id") + 1] == "fixed-uuid-here"
    check("the spawn hands claude the session id its card is read from", ok, str(cmd[:8]))


def _load_watcher(env):
    """Import board-watch.py as a module under `env`, for the checks that have
    to reach inside it. Its paths are module constants read at import."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("bw_under_test", WATCHER)
    mod = importlib.util.module_from_spec(spec)
    old = dict(os.environ)
    os.environ.update({k: v for k, v in env.items() if isinstance(v, str)})
    try:
        spec.loader.exec_module(mod)
    finally:
        os.environ.clear()
        os.environ.update(old)
    return mod


def test_the_loop():
    """The 2026-07-28 hot loop, as three separate defects.

    He typed two sentences into the board's box; neither ran, both were still in
    `inbox/queue/`, and `board-watch.service` had started 3,151 times. One chain,
    three independent things wrong with it, so three regressions:

      1. `first_run` was inferred from `state["answers"]` being empty. His NEEDS
         YOU had just emptied out — the resting state — so every run was a first
         run, forever.
      2. the first-run branch returned BEFORE the queue was drained, so typed
         input was never worked under that condition.
      3. `board-inbox.path` is level-triggered, so an undrained queue restarts
         the service the instant it exits. Nothing bounded that.
    """
    print("the hot loop - three defects")

    # ---- 1. an empty NEEDS YOU is a resting state, not "never seeded" --------
    d = tempfile.mkdtemp(prefix="board-watch-seed-")
    try:
        r = Rig(d, EMPTY_NEEDS)
        r.run()
        r.run()
        r.run()
        firsts = [l for l in open(r.log) if "first run:" in l]
        check("an empty NEEDS YOU seeds ONCE, not on every run", len(firsts) == 1,
              "%d first-run lines" % len(firsts))
        st = json.load(open(os.path.join(r.state, "state.json")))
        check("...because the marker is explicit, not inferred from emptiness",
              st.get("seeded") is True and st["answers"] == {}, str(st.get("seeded")))
        check("...and the later runs say so plainly",
              any("no new answer" in l for l in open(r.log)))
        # and the marker did not cost the real behaviour it guards
        r.edit("## NEEDS YOU\n",
               "## NEEDS YOU\n\n### 1. A late question?\n\n- [ ] one\n- [ ] two\n"
               "\n>\n\n*If unanswered:* nothing.\n")
        r.run()
        check("a decision added after the seed still does not fire on arrival",
              r.fires() == [], str(r.fires()))
        r.edit("- [ ] one", "- [x] one")
        r.run()
        check("...and answering it afterwards fires exactly once",
              r.fires() == ["a-late-question"], str(r.fires()))

        # an OLD state file, from before the marker existed, must not re-seed
        p = os.path.join(r.state, "state.json")
        st = json.load(open(p))
        st.pop("seeded")
        json.dump(st, open(p, "w"))
        r.clear()
        r.run()
        check("a state file written before the marker is treated as seeded",
              not any("first run:" in l for l in r.tail(3)), str(r.tail(3)))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # ---- 2. a first run still works what he typed ---------------------------
    d = tempfile.mkdtemp(prefix="board-watch-first-")
    try:
        r = Rig(d, EMPTY_NEEDS)
        m = r.note("clear the to-do list, i cannot remove anything")
        check("(setup) the box queued it", m["state"] == "queued", m)
        r.run(spawn="cat > " + os.path.join(d, "orch.txt")
              + '; echo "$BOARD_WATCH_KEY" >> ' + r.fired)
        check("a note typed BEFORE the first run is worked ON the first run",
              len(r.fires()) == 1 and r.fires()[0].startswith("orch-"), str(r.fires()))
        check("...carrying his sentence, not a seeded-past version of it",
              "cannot remove anything" in open(os.path.join(d, "orch.txt")).read())
        check("...and the queue is empty afterwards, so nothing re-triggers",
              r.queued() == [], r.queued())
        check("...and it was still a first run for the ANSWERS",
              any("first run:" in l for l in open(r.log)))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # ---- 3. it cannot spin ---------------------------------------------------
    d = tempfile.mkdtemp(prefix="board-watch-spin-")
    try:
        r = Rig(d, EMPTY_NEEDS)
        r.note("something to leave sitting in the queue")
        # A shut gate is the one LEGITIMATE way a run ends with the queue full,
        # so it is what the end-to-end check uses: same level trigger, same
        # loop, and it must be bounded without anything being called a fault.
        spin = dict(BOARD_WATCH_SPIN_LIMIT=2, BOARD_WATCH_SPIN_WINDOW=600,
                    BOARD_WATCH_SPIN_BACKOFF=1)
        for _ in range(3):
            r.run(gate="closed", **spin)
        check("runs that leave the queue full are counted",
              json.load(open(os.path.join(r.state, "state.json")))["spin"]
              .get("count", 0) >= 3)
        check("...and past the limit the run backs off instead of returning at once",
              any("backing off" in l for l in open(r.log)))
        check("...quietly: a locked screen is not a fault and gets no bullet",
              "caught itself looping" not in r.text())
        check("...and his sentence is still queued, not dropped",
              r.queued() == ["something to leave sitting in the queue"], r.queued())
        # self-healing: the moment a run drains, the streak is gone
        r.run(**spin)
        check("a run that drains the queue clears the streak",
              json.load(open(os.path.join(r.state, "state.json")))["spin"] == {},
              json.load(open(os.path.join(r.state, "state.json")))["spin"])

        # ...and when the queue stayed full with the GATE OPEN, that is a bug,
        # and he is told on the board rather than only in a log.
        mod = _load_watcher(r.env())
        before = r.text()
        st = mod.load_state()
        st["spin"] = {"count": 9, "first": __import__("time").time(),
                      "defect": True, "noted": False}
        mod.save_state(st)
        mod.SPIN_BACKOFF_S = 0
        mod.spin_guard(mod.load_state())
        bullet = [l for l in r.text().splitlines() if "caught itself looping" in l]
        check("a queue left full with the gate OPEN leaves one bullet on the board",
              len(bullet) == 1, str(bullet))
        check("...in WAITING ON YOU TO DO",
              bool(bullet) and r.text().index(bullet[0])
              > r.text().index("## WAITING ON YOU TO DO"))
        mod.spin_guard(mod.load_state())
        again = [l for l in r.text().splitlines() if "caught itself looping" in l]
        check("...once per streak, never once per run", len(again) == 1, str(again))
        check("...and nothing else in the file moved",
              "\n".join(l for l in r.text().splitlines()
                        if "caught itself looping" not in l).rstrip("\n")
              == before.rstrip("\n"))
    finally:
        shutil.rmtree(d, ignore_errors=True)


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
        check("prompt tells the agent his notes can arrive mid-flight",
              "inbox take" in prompt, prompt[-400:])

        print("a note he typed into the board's agents section")
        # Settle the store so nothing is newly answered: the queue is worked on
        # a quiet tick, and a decision always outranks a note.
        r.edit("- [x] Do it the short way (chosen)", "- [ ] Do it the short way (chosen)")
        r.run()
        r.clear()

        m = r.note("have another look at the panel spacing")
        check("with nothing running, the box queues it", m["state"] == "queued", m)
        r.run(gate="closed")
        check("a locked screen does not work it", r.fires() == [], str(r.fires()))
        check("...and it is still queued, not lost",
              r.queued() == ["have another look at the panel spacing"], r.queued())

        r.run(spawn="cat > " + os.path.join(d, "note.txt")
              + '; echo "$BOARD_WATCH_KEY" >> ' + r.fired)
        note_prompt = open(os.path.join(d, "note.txt")).read()
        check("an open gate spawns ONE agent for it",
              len(r.fires()) == 1 and r.fires()[0].startswith("orch-"), str(r.fires()))
        check("...carrying what he wrote, verbatim",
              "have another look at the panel spacing" in note_prompt)
        check("...under the same rules a decision run gets",
              "NEVER rebuild" in note_prompt and "-- <explicit> <paths>" in note_prompt
              and "Push to `main`" in note_prompt)
        # WHAT THAT AGENT IS NOW FOR. It used to do the work itself; since he
        # asked for a control surface it ORCHESTRATES — it splits the input up,
        # dispatches workers and asks him when only he can decide. The prompt is
        # the whole mechanism, so assert it says so rather than trusting it.
        check("...and it is an ORCHESTRATOR: it plans and dispatches, it does not build",
              "you do not do the work" in note_prompt
              and "boardctl.py dispatch" in note_prompt, note_prompt[:200])
        check("...told to ASK rather than guess big, with the cheap/expensive trade named",
              "boardctl.py ask" in note_prompt and "--if-unanswered" in note_prompt
              and "wrong guess" in note_prompt)
        check("...and told the cap, so it neither rations nor floods",
              re.search(r"limit on how many workers run at once \(\d+", note_prompt)
              is not None)
        check_session_id_is_passed(r)
        check("...and the queue is drained, so it cannot run twice",
              r.queued() == [], r.queued())
        r.clear()
        r.run()
        check("a drained queue fires nothing on the next tick", r.fires() == [],
              str(r.fires()))

        print("...and a note whose agent fails still reaches him")
        before = r.text()
        r.note("check whether the clock is off by a pixel")
        r.run(spawn="exit 3")
        after = r.text()
        bullet = [l for l in after.splitlines() if "what you typed into the board" in l]
        check("a failed orchestrator run leaves a bullet on the board", len(bullet) == 1,
              str(bullet))
        check("...quoting what he wrote, so it is not lost with the run",
              bool(bullet) and "off by a pixel" in bullet[0], str(bullet))
        check("...and moves nothing else in the file",
              "\n".join(l for l in after.splitlines()
                        if "what you typed into the board" not in l
                        ).rstrip("\n") == before.rstrip("\n"))
        print("work above the concurrency cap waits for a slot, on a tick")
        # The orchestrator fans out through `boardctl dispatch`, which refuses
        # to exceed the cap and files the rest instead. Somebody has to start
        # those, and it is a tick of this script — the same place `reconcile()`
        # un-strands an item and `sweep()` rescues a note. Asserted here because
        # a task that is queued and never promoted is work he asked for that
        # silently never happens.
        import boardwork as bw
        os.environ["BOARD_WORK_SPAWN"] = "sleep 30"
        os.environ["BOARD_MAX_WORKERS"] = "1"
        try:
            states = r.state_home(
                lambda: [bw.dispatch("piece %d" % i)["state"] for i in range(3)])
            check("dispatch runs one and queues the rest, never dropping one",
                  states == ["running", "queued", "queued"], str(states))
            live = r.state_home(bw.live_workers)
            for a in live:
                os.kill(a["pid"], 9)
            r.run()
            left = r.state_home(lambda: [t["task"] for t in bw.pending()])
            check("a tick starts queued work once a slot frees",
                  left == ["piece 2"], str(left))
            check("...and says so in the log",
                  any("started queued work" in l for l in open(r.log)))
            for a in r.state_home(bw.live_workers):
                os.kill(a["pid"], 9)
        finally:
            os.environ.pop("BOARD_WORK_SPAWN", None)
            os.environ.pop("BOARD_MAX_WORKERS", None)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    test_the_loop()

    print()
    if fails:
        print("FAILED: " + ", ".join(fails))
        return 1
    print("all board-watch assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
