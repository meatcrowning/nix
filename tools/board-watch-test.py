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
  outlive     THE one that fails silently: a worker dispatched inside a tick is
              still running after that tick exits, after a SUBSEQUENT tick, and
              lives long enough to do its job — run inside a real transient
              oneshot unit, because that is the only place the bug exists. And
              a worker that ends without recording anything is reported to him
              as a failure rather than passing for success
  rebuild     THE 2026-07-30 DOUBLE-FIRE: a `sudo rebuild-top` stops this unit,
              so a tick is killed mid-agent while the agent lives on. The
              decision must not be handed back (the stash follows the AGENT),
              must not be handed back when that agent later finishes either,
              and must not fire a second time even if it is back in NEEDS YOU
              and he answers it again — while an agent that dies recording
              nothing is still handed back, as it always was
  affinity    THE ANSWER STAMP: an answer stamped for the other machine must
              NOT fire here, one stamped for this machine must, an UNSTAMPED
              one (a hand edit) is worked by exactly one of them, and
              re-answering on the other machine is the hand-off. Belt-and-
              braces since the boards went per-host on 2026-07-30 — kept
              because a board restored from the other host's synced copy must
              still be harmless
  ctrl+z      a summoner he TOOK BACK leaves nothing behind: no dispatch, no
              note, and — although it exits nonzero — not his own sentence
  transcript  the bullet for a worker that recorded nothing names its
              TRANSCRIPT when the failed record carries one, and falls back to
              the log-only wording when it does not — both shapes placed
              through the real checks
              returned to him as a failure. `boardundo.py`; the gate that
              refuses the run's verbs is `board-test.py`'s half
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
import time

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

#: A bullet's OWN metadata comments. Writing ANY bullet into a section stamps
#: the bullets already there with the time they were placed (`boardparse`, so
#: the board can draw how long something has been waiting), and since
#: 2026-07-30 a bullet also carries `<!-- by: -->`, the agent that put it there,
#: and `<!-- for: -->`, the ask it was written for — so a fixture nobody touched
#: legitimately gains a line, and the three "nothing else in the file moved"
#: checks below read that as the watcher rewriting his board. None of that is
#: what any of them is about, so all three come off both sides.
#:
#: EVERY new bullet-metadata comment has to be added here. `by:` was missed when
#: attribution landed and all three checks failed for a day with nothing wrong
#: in the watcher; `for:` was missed the same way and did it again.
PLACED = re.compile(r"^\s*<!--\s*(placed|by|for):")


def unmoved(after, before, *drop):
    """True when `after` is `before` apart from the lines `drop` names."""
    def keep(t):
        return "\n".join(l for l in t.splitlines()
                         if not PLACED.match(l)
                         and not any(d in l for d in drop)).rstrip("\n")
    return keep(after) == keep(before)


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
        # HOST AFFINITY, which every step of this file that is NOT about host
        # affinity has to opt out of: an answer with no host stamp belongs to
        # `top` (a hand edit), so a watcher that believes it is `book` fires on
        # none of them and two thirds of this harness reported FAIL on the
        # laptop while passing on the desktop. Pretend to be `top` by default;
        # the affinity section passes its own value and keeps it.
        e.setdefault("BOARD_WATCH_HOST", "top")
        # COALESCING OFF by default, for the same reason the host is pinned:
        # every step here queues a sentence and expects the very next run to
        # work it, and the real 75-second hold would add 75 seconds to each of
        # them. `test_coalescing` passes its own values and keeps them.
        e.setdefault("BOARD_COALESCE_QUIET", "0")
        e.setdefault("BOARD_COALESCE_BURST", "0")
        e.update(BOARD_WATCH_BOARD=self.board, BOARD_WATCH_STATE=self.state,
                 BOARD_WATCH_LOG=self.log, BOARD_WATCH_GATE=gate,
                 BOARD_WATCH_REPO=REPO,
                 # boardmove's stash and boardagents' inbox both live under
                 # XDG_STATE_HOME. Without this the run under test writes into
                 # HIS live `~/.local/state/board`, where the app reads it — a
                 # harness here must redirect it, exactly as board-test.py does.
                 XDG_STATE_HOME=os.path.join(self.d, "xdgstate"),
                 # ...and the same for the WORKER LOGS (`boardwork._log_path`).
                 # Without it every fixture worker this harness spawns — `task
                 # one`, `task two`, ... — wrote an empty log into his real
                 # `~/.cache/board-work/`, where an agent reads that directory
                 # as evidence of what ran. 682 of the 714 files there were this
                 # harness's debris, and a dozen of them were read as real
                 # dispatches that had produced nothing (2026-07-29).
                 XDG_CACHE_HOME=os.path.join(self.d, "xdgcache"),
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

        Since `boardmove.py`, firing takes the decision out of NEEDS YOU and
        into the stash, and a stub agent that "succeeds" leaves it there — so
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
        """Run `fn` against the RIG's state and cache dirs, not his.

        `boardagents` reads XDG_STATE_HOME and `boardwork._log_path` reads
        XDG_CACHE_HOME on every call, so swapping them round the call is enough
        and there is no module state to reset. **Both**, because `fn` here is
        sometimes `bw.dispatch`, which spawns a real worker: with the cache dir
        left alone that worker's log landed in his live `~/.cache/board-work/`
        even though everything else about the run was contained.
        """
        old = {k: os.environ.get(k)
               for k in ("XDG_STATE_HOME", "XDG_CACHE_HOME")}
        os.environ["XDG_STATE_HOME"] = os.path.join(self.d, "xdgstate")
        os.environ["XDG_CACHE_HOME"] = os.path.join(self.d, "xdgcache")
        try:
            return fn()
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

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

    Checked by importing the watcher and intercepting `subprocess.Popen`,
    because the stub path (`BOARD_WATCH_SPAWN`) deliberately replaces the whole
    command line and so cannot see it. `Popen` and not `run`: `spawn()` has to
    know the agent's own pid while the run is still going, so that the stash
    can follow the AGENT rather than the tick a rebuild kills
    (`test_a_rebuild_kills_the_tick`).
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

        def fake_popen(cmd, **kw):
            seen["cmd"] = cmd
            raise Done()

        real = mod.subprocess.Popen
        mod.subprocess.Popen = fake_popen
        try:
            mod.spawn("a prompt", "k", "label", session="fixed-uuid-here")
        except Done:
            pass
        finally:
            mod.subprocess.Popen = real
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


def test_worker_outlives_the_tick():
    """THE most important assertion in this system, because it fails SILENTLY.

    `board-watch.service` is a `Type=oneshot`, and a oneshot's default
    `KillMode=control-group` kills everything left in its cgroup when the main
    process exits. A child spawned with `start_new_session=True` is STILL IN
    THAT CGROUP — that call detaches the process *group*, a terminal-signal
    concept, and says nothing about cgroups. So for a day, every worker an
    orchestrator dispatched was killed seconds after it started, while the board
    reported the work as dispatched and in hand and nothing was ever built:
    worker `we9f99c` registered at 22:49:16, the orchestrator exited at 22:49:29
    and the worker's transcript ends three tool calls in.

    Nothing about that is visible from a test that runs the watcher as an
    ordinary child of this process — there is no oneshot, so there is no cgroup
    to be killed by, and the broken version passes. **So this test runs the
    watcher inside a real transient oneshot unit**, exactly as systemd runs it,
    and asserts that a worker dispatched from inside that run is still alive
    after the run has exited AND after a second tick, and that it goes on to do
    the thing it was dispatched to do.
    """
    print("a worker OUTLIVES the tick that spawned it")
    if not shutil.which("systemd-run"):
        check("systemd-run is available to spawn workers into their own unit",
              False, "not on PATH - the fix cannot be verified or used")
        return
    d = tempfile.mkdtemp(prefix="board-watch-live-")
    unit = "board-watch-test-%d" % os.getpid()
    survivor = os.path.join(d, "survivor")
    try:
        r = Rig(d, EMPTY_NEEDS)
        r.note("please do the long thing")

        env = r.env(gate="open")
        # The orchestrator's whole job here is to dispatch ONE worker; the
        # worker's whole job is to outlive everything and then write a file.
        env["BOARD_WATCH_SPAWN"] = (
            "%s %s/apps/board/tools/boardctl.py dispatch 'outlive the tick'"
            " --where 'nowhere'" % (sys.executable, REPO))
        env["BOARD_WORK_SPAWN"] = "sleep 12; echo alive > %s" % survivor

        run = ["systemd-run", "--user", "--quiet", "--collect", "--wait",
               "--unit", unit, "--service-type=oneshot",
               "--working-directory", REPO]
        for k in sorted(env):
            v = env[k]
            if isinstance(v, str) and "\n" not in v and "\0" not in v:
                run.append("--setenv=%s=%s" % (k, v))
        run += [sys.executable, WATCHER]

        t0 = time.time()
        p = subprocess.run(run, capture_output=True, text=True, timeout=180)
        check("the tick itself succeeds inside a real oneshot unit",
              p.returncode == 0, p.stderr.strip()[-300:])
        check("...and it returns long before the worker could have finished",
              time.time() - t0 < 10, "%.1fs" % (time.time() - t0))

        def live():
            return r.state_home(lambda: [a["id"] for a in _bw().live_workers()])

        alive_after_tick = live()
        check("a worker dispatched inside the tick is STILL RUNNING after it exits",
              len(alive_after_tick) == 1, str(alive_after_tick))

        # ...and a LATER tick does not take it out either: `promote()`,
        # `sweep()` and `reap()` all run over a worker that is still going.
        subprocess.run(run, capture_output=True, text=True, timeout=180)
        check("...and after a SUBSEQUENT tick as well", live() == alive_after_tick,
              str(live()))

        for _ in range(300):
            if os.path.exists(survivor):
                break
            time.sleep(0.1)
        check("...and it lives long enough to actually do the work",
              os.path.exists(survivor), "never wrote %s" % survivor)

        # A worker that ends without recording anything on the board is a
        # FAILURE he can see, not a silence. This is the other half of the same
        # bug: the orchestrator claimed completion for work that never happened.
        for _ in range(100):
            if not live():
                break
            time.sleep(0.1)
        subprocess.run(run, capture_output=True, text=True, timeout=180)
        bullets = [l for l in r.text().splitlines()
                   if "a minister stopped without finishing" in l]
        check("a minister that records nothing is reported as a FAILURE, in words",
              len(bullets) == 1, str(bullets))
        check("...quoting the task, since its card has already left the board",
              bool(bullets) and "outlive the tick" in bullets[0], str(bullets))
        left = r.state_home(lambda: [t["task"] for t in
                                     ba._list(_bw().work_dir("failed"))])
        check("...and the task is filed under `failed`, not left looking taken",
              left == ["outlive the tick"], str(left))
    finally:
        subprocess.run(["systemctl", "--user", "reset-failed", unit + ".service"],
                       capture_output=True)
        shutil.rmtree(d, ignore_errors=True)


def _bw():
    import boardwork
    return boardwork


def _agent_pids(key):
    """Live processes carrying `BOARD_WATCH_KEY=<key>` — the stub agents this
    file spawns, found the same way `working_keys()` finds real ones."""
    out = []
    try:
        names = [n for n in os.listdir("/proc") if n.isdigit()]
    except OSError:
        return out
    for n in names:
        try:
            with open("/proc/%s/environ" % n, "rb") as f:
                blob = f.read(64 * 1024)
        except OSError:
            continue
        if any(v == b"BOARD_WATCH_KEY=" + key.encode() for v in blob.split(b"\0")):
            out.append(int(n))
    return out


def _kill(key):
    """Kill every stub agent carrying `key` and wait for /proc to agree."""
    for pid in _agent_pids(key):
        try:
            os.kill(pid, 9)
        except OSError:
            pass
    for _ in range(100):
        if not _agent_pids(key):
            return
        time.sleep(0.1)


def _wait_for(path, text, secs=60):
    """Wait for a line to appear in the watcher's log. Returns whether it did."""
    for _ in range(int(secs * 10)):
        try:
            with open(path) as f:
                if text in f.read():
                    return True
        except OSError:
            pass
        time.sleep(0.1)
    return False


def test_a_rebuild_kills_the_tick():
    """A DECISION ALREADY BEING WORKED CANNOT BE PICKED UP A SECOND TIME.

    The 2026-07-30 double-fire, reproduced. Decision 1 fired at 19:23:08; a
    `sudo rebuild-top` at 19:23:50 reached home-manager's `reloadSystemd`,
    which STOPS the units it manages — `board-watch.service: Main process
    exited, code=killed, status=15/TERM` at 19:24:25, with the agent itself
    surviving because the unit is `KillMode=process`. One second later the
    restarted tick ran `reconcile()`, read the dead TICK's pid off the stash,
    logged "returned decision 1 to NEEDS YOU: its agent is gone" and put the
    decision back in front of him with his answer on it — so he answered it
    again, in his own words this time, and 19:33:04 fired a second agent while
    the first was still running. Two agents did one job and both wrote a LANDED
    row for it.

    Every mechanism was working as designed; the design asked the wrong
    process. So this asserts the three things that make the sequence
    impossible, in the order they would fail:

      1. the stash follows the AGENT (`boardmove.adopt`), so a killed tick
         strands nothing;
      2. an agent that finished after its tick died is RETIRED rather than
         reclaimed (`boardmove.retire_finished`) — the same duplicate by a
         slower route;
      3. and whatever the bookkeeping says, a key a live process still carries
         does not fire (`working_keys`) — with his answer QUEUED, not dropped.

    Plus the guarantee none of that may cost: an agent that dies without
    recording anything still hands its decision back.
    """
    print("a rebuild that kills the tick mid-agent")
    d = tempfile.mkdtemp(prefix="board-watch-kill-")
    stub = None
    try:
        r = Rig(d)
        r.run()                                   # seed
        # Two stubs: one that hangs around like a real agent (so a tick can be
        # killed out from under it), and one that is over before the tick is —
        # a `tick()` here is waited on, so the sleeper cannot be used for a run
        # that is expected to fire.
        sleeper = 'echo "$BOARD_WATCH_KEY" >> %s; exec sleep 300' % r.fired
        quick = 'echo "$BOARD_WATCH_KEY" >> %s' % r.fired

        def tick(spawn=quick, **kw):
            return subprocess.run([sys.executable, WATCHER],
                                  env=r.env(gate="open", spawn=spawn, **kw),
                                  capture_output=True, text=True, timeout=120)

        def needs():
            return [i["key"] for i in bp.parse(r.text())["needs"]]

        # --- the fire, then the rebuild that kills the tick under it
        r.edit("- [ ] Do it the short way", "- [x] Do it the short way")
        held = subprocess.Popen([sys.executable, WATCHER],
                                env=r.env(gate="open", spawn=sleeper),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        check("the tick fires and takes the decision off NEEDS YOU",
              _wait_for(r.log, "took decision 1 off NEEDS YOU"),
              open(r.log).read()[-300:])
        stub = _agent_pids("first-question")
        check("...and the agent it spawned carries the decision's key",
              len(stub) == 1, str(stub))
        held.terminate()                          # what sd-switch does, verbatim
        held.wait(timeout=30)
        check("the agent survives the tick being killed",
              _agent_pids("first-question") == stub, str(_agent_pids("first-question")))

        # --- the tick that used to hand it back
        tick()
        log = open(r.log).read()
        check("the next tick does NOT hand the decision back",
              "returned decision" not in log, log[-300:])
        check("...it is still off the board, not back in front of him",
              "first-question" not in needs(), str(needs()))
        check("...and no second agent was fired", r.fires() == ["first-question"],
              str(r.fires()))

        # --- ...and it is not handed back once the agent finishes, either
        r.state_home(lambda: _bw().mark_reported("first-question", "done"))
        _kill("first-question")
        tick()
        log = open(r.log).read()
        check("an agent that finished after its tick died is retired, not reclaimed",
              "finished after its tick was killed" in log
              and "returned decision" not in log, log[-300:])
        check("...so the decision stays out of NEEDS YOU",
              "first-question" not in needs(), str(needs()))
        check("...and its stash is gone rather than left to be reclaimed later",
              r.state_home(lambda: bm._stash_for("first-question")) is None)

        # --- THE LAST GUARD: he re-answers an item that is being worked
        r.clear()
        r.edit("- [ ] Yes\n- [ ] No", "- [x] Yes\n- [ ] No")
        held = subprocess.Popen([sys.executable, WATCHER],
                                env=r.env(gate="open", spawn=sleeper),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        check("a second decision fires its own agent",
              _wait_for(r.log, "took decision 2 off NEEDS YOU"),
              open(r.log).read()[-300:])
        stub = _agent_pids("second-question")
        held.terminate()
        held.wait(timeout=30)
        # Put it back the way the BUG did, with the agent still running, and
        # let him answer it a second time — which is exactly what he did at
        # 19:32 after finding it in NEEDS YOU again.
        r.state_home(lambda: bm.give_back("second-question", path=r.board))
        r.edit(">\n\n*If unanswered:* nothing happens.\n\n---",
               "> fetch the microfilm scans\n\n*If unanswered:* nothing happens.\n\n---")
        tick()
        check("re-answering a decision an agent is still working fires nothing",
              r.fires() == ["second-question"], str(r.fires()))
        check("...and says why", "already being worked" in open(r.log).read())

        # ...QUEUED, not dropped: the answer is his and it is still there.
        _kill("second-question")
        tick()
        check("...and it fires once the agent is really gone",
              r.fires() == ["second-question", "second-question"], str(r.fires()))

        # --- the guarantee none of this may cost: a DEATH is still a death.
        # Its own decision, so the log line it is asserted on cannot be an
        # earlier one, and it is the whole of case 3 — killed tick, killed
        # agent, nothing recorded.
        r.edit("---\n\n## WAITING ON YOU TO DO",
               "### 3. Third question?\n\n- [ ] Left\n- [ ] Right\n\n>\n\n"
               "*If unanswered:* nothing.\n\n---\n\n## WAITING ON YOU TO DO")
        tick()                                    # record it; a new item never fires
        r.clear()
        r.edit("- [ ] Left\n- [ ] Right", "- [x] Left\n- [ ] Right")
        held = subprocess.Popen([sys.executable, WATCHER],
                                env=r.env(gate="open", spawn=sleeper),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        check("a third decision fires its own agent",
              _wait_for(r.log, "took decision 3 off NEEDS YOU"),
              open(r.log).read()[-300:])
        held.terminate()
        held.wait(timeout=30)
        _kill("third-question")
        tick()
        check("an agent that dies recording NOTHING still hands its decision back",
              "returned decision 3 to NEEDS YOU: its agent is gone"
              in open(r.log).read(), open(r.log).read()[-300:])
        check("...and the decision is back in front of him",
              "third-question" in needs(), str(needs()))
        check("...without the hand-back itself reading as a new answer",
              r.fires() == ["third-question"], str(r.fires()))
    finally:
        for key in ("first-question", "second-question"):
            for pid in _agent_pids(key):
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
        shutil.rmtree(d, ignore_errors=True)


def test_summoner_fanout():
    """ONE summoner per operator, not per sentence.

    [his, 2026-08-01, of a tick that ran three concurrent Solomons for three
    things he typed: *"why the fuck are you running multiple solomons?????"*] So
    the split axis is the OPERATOR each item routes to, not the sentence count:
    items that want the same operator share one summoner handed the whole list,
    and only genuinely different operators get their own session. The top
    dropdown is now a ceiling on how many run AT ONCE, not on how many start.
    """
    print("the summoner grouping - one session per operator, not per sentence")
    d = tempfile.mkdtemp(prefix="board-watch-summon-")
    try:
        r = Rig(d, EMPTY_NEEDS)
        # One prompt file per run, named by the key, so the grouping itself is
        # visible rather than inferred from a count.
        stub = ('cat > "%s/prompt-$BOARD_WATCH_KEY"; echo "$BOARD_WATCH_KEY" >> %s'
                % (d, r.fired))

        # Three plain phrases all route to the SAME operator (Weyer), so however
        # high the count, they become ONE summoner holding all three - the exact
        # thing the incident was about.
        for s in ("the first thing", "the second thing", "the third thing"):
            r.note(s)
        r.run(spawn=stub, BOARD_MAX_SUMMONERS=3)
        keys = r.fires()
        check("three same-operator things are ONE summoner, not three",
              len(keys) == 1, str(keys))
        body = open(os.path.join(d, "prompt-" + keys[0])).read()
        for s in ("the first thing", "the second thing", "the third thing"):
            check("...and %r is in that one run" % s, s in body, body[:80])
        check("...and the queue is empty, so nothing re-triggers",
              r.queued() == [], r.queued())

        # Two items that route to DIFFERENT operators DO get their own sessions:
        # a plan word summons Solomon, a bare factual question summons Weyer.
        r.clear()
        r.note("build a new settings page")     # -> Solomon (plan)
        r.note("what time is it")               # -> Weyer (quick)
        r.run(spawn=stub, BOARD_MAX_SUMMONERS=2)
        keys = r.fires()
        check("two different operators are two sessions", len(keys) == 2, str(keys))
        bodies = [open(os.path.join(d, "prompt-" + k)).read() for k in keys]
        for s in ("build a new settings page", "what time is it"):
            hits = [b for b in bodies if s in b]
            check("...and %r reached exactly one of them" % s, len(hits) == 1,
                  str(len(hits)))

        # SHORTNESS IS NOT A QUESTION. The router briefly sent everything under
        # 120 characters to Weyer, whose flavour ANSWERS and never dispatches —
        # so a short work order was quietly answered instead of worked, which is
        # the exact failure `route_operator`'s own bar is written against.
        import boardwork as bw
        for short_order in ("have another look at the panel spacing",
                            "the scrollbar arrows feel sluggish",
                            "goetia's titlebar text flickers"):
            check("a short WORK ORDER still routes to the planner: %r"
                  % short_order[:34],
                  bw.route_operator(short_order).flavour == "plan",
                  bw.route_operator(short_order).name)
        check("...while a short QUESTION still reaches the cheap operator",
              bw.route_operator("what time is it").name == "Weyer")

        r.clear()
        r.note("something on its own")
        r.run(spawn=stub, BOARD_MAX_SUMMONERS=4)
        check("one sentence is one summoner, whatever the number says",
              len(r.fires()) == 1, str(r.fires()))

        r.clear()
        r.note("one of two"), r.note("two of two")
        r.run(spawn=stub, BOARD_MAX_SUMMONERS=1)
        one = r.fires()
        check("...and same-operator work at any cap is one run",
              len(one) == 1
              and "one of two" in open(os.path.join(d, "prompt-" + one[0])).read()
              and "two of two" in open(os.path.join(d, "prompt-" + one[0])).read(),
              str(one))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_coalescing():
    """A BURST IS ONE PLANNING PROBLEM.

    [his, 2026-08-01] *"being able to send a multitude of requests in either a
    single or multitude of prompts"* — how he split his thinking into box-fulls
    is not how the work divides, so the tick waits out the rest of a burst and
    hands the whole of it to one summoner rather than planning the first
    sentence while he is still typing the second. Bounded twice: by the quiet
    window, and by a hard ceiling on the OLDEST item so a hold can never become
    a stall. Nothing is ever dropped — the queue is left exactly as it was.
    """
    print("the coalescing window - a burst is planned as one batch")
    d = tempfile.mkdtemp(prefix="board-watch-coal-")
    try:
        r = Rig(d, EMPTY_NEEDS)
        stub = ('cat > "%s/prompt-$BOARD_WATCH_KEY"; echo "$BOARD_WATCH_KEY" >> %s'
                % (d, r.fired))

        # THE HOLD IS INSIDE THE RUN, holding the flock, rather than a return
        # that leaves the queue full - `board-inbox.path` is level-triggered, so
        # returning would respawn this every few hundred milliseconds for the
        # length of the window.
        r.note("the first half of the thought")
        t0 = time.time()
        r.run(spawn=stub, BOARD_COALESCE_QUIET=3, BOARD_COALESCE_BURST=90,
              BOARD_COALESCE_MAX=600)
        took = time.time() - t0
        check("a just-typed sentence is waited out, not planned at once",
              took >= 3, "%.1fs" % took)
        check("...on the SHORT window - one item is not yet a burst, and a "
              "flat wait is paid by the common case",
              took < 90, "%.1fs" % took)
        check("...and the run SAYS it is holding rather than going quiet",
              "holding" in open(r.log).read(), open(r.log).read()[-200:])
        check("...and it is planned when the window closes, never dropped",
              len(r.fires()) == 1 and r.queued() == [],
              (r.fires(), r.queued()))

        # A SENTENCE TYPED DURING THE HOLD JOINS THE SAME BATCH - the whole
        # point: how he split his thinking into box-fulls is not how the work
        # divides.
        r.clear()
        r.note("the first half of the thought")
        proc = subprocess.Popen([sys.executable, WATCHER],
                                env=r.env("open", stub,
                                          BOARD_COALESCE_QUIET=4,
                                          BOARD_COALESCE_BURST=4,
                                          BOARD_COALESCE_MAX=600),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(1.5)
        r.note("and the second half")
        proc.communicate(timeout=120)
        keys = r.fires()
        check("a sentence typed DURING the hold joins the same batch",
              len(keys) == 1, str(keys))
        body = open(os.path.join(d, "prompt-" + keys[0])).read() if keys else ""
        check("...so both halves reach ONE summoner, not two",
              "the first half of the thought" in body
              and "and the second half" in body, body[:120])
        check("...and the queue is empty afterwards", r.queued() == [], r.queued())

        # THE CEILING: a queue whose oldest item is past the hard bound is
        # planned now, however recently he typed the newest.
        r.clear()
        r.note("typed a while ago")
        for msg in r.state_home(lambda: ba.pending()):
            rec = json.load(open(msg["file"]))
            rec["sent"] = time.time() - 3600
            with open(msg["file"], "w") as f:
                json.dump(rec, f)
        r.note("typed just now")
        t0 = time.time()
        r.run(spawn=stub, BOARD_COALESCE_QUIET=600, BOARD_COALESCE_BURST=600,
              BOARD_COALESCE_MAX=60)
        took = time.time() - t0
        check("the hard ceiling plans the batch even mid-burst",
              len(r.fires()) == 1 and took < 30, (r.fires(), "%.1fs" % took))
        check("...and it took the WHOLE queue with it", r.queued() == [],
              r.queued())
    finally:
        shutil.rmtree(d, ignore_errors=True)


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
              unmoved(r.text(), before, "caught itself looping",
                      "Something typed into the board's box"))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_host_affinity():
    """TWO WATCHERS, ONE FILE — the hazard that came with running on book.

    Each machine now reads its OWN board (`docs/board.<hostname>.md`, since
    2026-07-30), so this is no longer the only thing standing between one `[x]`
    and two agents. It is still asserted, and the rule still holds: the boards
    sync as files, so the other host's board — and anything restored from it —
    is sitting right there, and a watcher that fired on content alone would put
    two agents on one job the day somebody copied one back.

    The defence is the stamp the board app writes beside his answer
    (`boardparse.set_answer_host`): the machine he typed it on works it. This
    asserts all three cases against ONE store, which is the point — the same
    bytes, read by two hosts, must fire exactly once between them.
    """
    print("host affinity - the answer stamp, read by two hosts")
    d = tempfile.mkdtemp(prefix="board-watch-host-")
    try:
        r = Rig(d)
        r.run(BOARD_WATCH_HOST="top")                     # seed
        r.clear()

        # He answers on BOOK. The app stamps it as it writes.
        r.edit("- [ ] Do it the short way\n- [ ] Do it the long way\n\n>\n",
               "- [x] Do it the short way\n- [ ] Do it the long way\n\n>\n"
               "<!-- answered-on: book -->\n")
        doc = bp.parse(r.text())
        it = [i for i in doc["needs"] if i["key"] == "first-question"][0]
        check("the stamp parses, and is not drawn as prose",
              it["answerHost"] == "book" and it["answered"]
              and not any("answered-on" in (b.get("raw") or "")
                          for b in it["body"]), repr(it["answerHost"]))

        r.run(BOARD_WATCH_HOST="top")
        check("an answer stamped for the OTHER machine does not fire here",
              r.fires() == [], str(r.fires()))
        check("...and says whose it is, once", any(
            "answered on book" in l for l in open(r.log)))
        r.run(BOARD_WATCH_HOST="top")
        check("...and it is recorded, so it is not re-considered every tick",
              r.fires() == [] and sum("answered on book" in l
                                      for l in open(r.log)) == 1)

        # The same bytes, on book.
        os.makedirs(os.path.join(d, "book"), exist_ok=True)
        r2 = Rig(os.path.join(d, "book"))
        r2.run(BOARD_WATCH_HOST="book")                   # seed
        r2.clear()
        r2.edit("- [ ] Do it the short way\n- [ ] Do it the long way\n\n>\n",
                "- [x] Do it the short way\n- [ ] Do it the long way\n\n>\n"
                "<!-- answered-on: book -->\n")
        r2.run(BOARD_WATCH_HOST="book")
        check("...while the machine it was typed on DOES fire",
              r2.fires() == ["first-question"], str(r2.fires()))

        # The hand-off: re-answering on top restamps, which reads as new HERE
        # and as already-recorded THERE. It is the whole takeover story, and it
        # cannot double-fire, because only one host is ever named.
        r.clear()
        r.edit("<!-- answered-on: book -->", "<!-- answered-on: top -->")
        r.run(BOARD_WATCH_HOST="top")
        check("re-answering on this machine hands the item over",
              r.fires() == ["first-question"], str(r.fires()))

        # An UNSTAMPED answer — a hand edit, or one predating the stamp — has a
        # stated owner rather than a race. Both hosts apply the same rule to the
        # same bytes and exactly one says yes.
        # Two rigs again, because each machine keeps its OWN fingerprints
        # (`~/.local/state/board-watch/` syncs nowhere) — which is also why a
        # tick on one machine can never suppress the other's.
        legacy = []
        for name, host in (("legacy-book", "book"), ("legacy-top", "top")):
            os.makedirs(os.path.join(d, name), exist_ok=True)
            rg = Rig(os.path.join(d, name))
            rg.run(BOARD_WATCH_HOST=host)                 # seed
            rg.clear()
            rg.edit("- [ ] Yes", "- [x] Yes")             # a HAND edit: no stamp
            rg.run(BOARD_WATCH_HOST=host)
            legacy.append(rg.fires())
        check("an UNSTAMPED answer is not worked by book", legacy[0] == [],
              str(legacy[0]))
        check("...and is worked by top, the default owner",
              legacy[1] == ["second-question"], str(legacy[1]))
        check("...so exactly one machine works it, which is the whole rule",
              len(legacy[0]) + len(legacy[1]) == 1)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_stamped_answer_on_first_sight():
    """A new-to-seen decision that is ALREADY answered fires when it wears
    THIS host's stamp.

    The `not in seen` guard swallows a decision that arrives already answered
    on the assumption that only an agent writes one that way. That is true for
    an UNSTAMPED one (a restored board, a hand edit), but not for one stamped
    `answered-on: <this-host>`: the board app writes that stamp in the SAME
    write as the user's answer (`boardparse.set_answer_host`), so an answer
    stamped for this machine is the user's, whatever state the bookkeeping was
    in when the key first showed up. That is the real gap on 2026-08-01: the
    user answered Asmodeus's fresh question while a long orchestrator run held
    the tick, so the first sighting was already answered and it was swallowed.
    """
    print("a stamped answer seen for the first time already-answered")
    d = tempfile.mkdtemp(prefix="board-watch-firstsight-")
    try:
        r = Rig(d)
        r.run(BOARD_WATCH_HOST="top")                     # seed
        r.clear()

        # He answers a NEW question about to hit the board for the first time;
        # the app stamps it `top` in the same write as the answer.
        r.edit("---\n\n## WAITING ON YOU TO DO",
               "### 2. Brand new stamped?\n\n> a brand new stamped answer\n"
               "<!-- answered-on: top -->\n\n*If unanswered:* nothing.\n\n"
               "---\n\n## WAITING ON YOU TO DO")
        r.run(BOARD_WATCH_HOST="top")
        check("the new stamped answer DOES fire",
              r.fires() == ["brand-new-stamped"], str(r.fires()))
        r.clear()

        # The contrast: the same shape WITHOUT a stamp is still an agent's own
        # write and must stay silent (hazard 2).
        r.edit("---\n\n## WAITING ON YOU TO DO",
               "### 3. Unstamped brand new?\n\n> an unstamped new answer\n\n"
               "*If unanswered:* nothing.\n\n---\n\n## WAITING ON YOU TO DO")
        r.run(BOARD_WATCH_HOST="top")
        check("an unstamped new answer still does NOT fire",
              r.fires() == [], str(r.fires()))
        r.clear()

        # And a stamp for the OTHER machine is not this host's to work.
        r.edit("---\n\n## WAITING ON YOU TO DO",
               "### 4. Answered elsewhere?\n\n> answered elsewhere\n"
               "<!-- answered-on: book -->\n\n*If unanswered:* nothing.\n\n"
               "---\n\n## WAITING ON YOU TO DO")
        r.run(BOARD_WATCH_HOST="top")
        check("an answer stamped for the other machine does NOT fire here",
              r.fires() == [], str(r.fires()))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_seed_guards_a_fresh_question_on_a_resting_board():
    """2026-08-01: an agent's `ask` places a question while NEEDS YOU is EMPTY,
    so board-watch's `answers` dict is `{}` (the resting state — it only ever
    holds the decisions currently in NEEDS YOU). The asker is supposed to seed
    the new key so the watcher knows it, but `seed_watch_state` bailed on an
    empty `answers` ("first run pending") and WROTE NOTHING. The question then
    stayed an UNKNOWN key through its first sighting, so if any answer-state
    touched it in that window, board-watch's "answered before its first
    sighting" path fired a decision agent on a question he had not genuinely
    answered. The resting-state conflation (empty `answers` == "never run") is
    the bug: `seeded` is the explicit "never run" marker, an empty `answers`
    is just the board at rest.
    """
    print("\na fresh question asked on a resting board is seeded as known-unanswered")
    d = tempfile.mkdtemp(prefix="board-watch-seedguard-")
    try:
        r = Rig(d, EMPTY_NEEDS)
        r.run(BOARD_WATCH_HOST="top")          # resting board -> answers {}
        r.clear()
        st = os.path.join(d, "state", "state.json")
        s0 = json.load(open(st))
        check("a resting board leaves the watcher's answers empty",
              s0["answers"] == {}, str(s0["answers"]))

        import boardwork as bw
        saved = os.environ.get("BOARD_WATCH_STATE")
        os.environ["BOARD_WATCH_STATE"] = os.path.join(d, "state")
        try:
            ok = bw.seed_watch_state("brand-new-question")
            # The seeded key is now a KNOWN-unanswered item, so a second seed is
            # a no-op and the watcher can no longer see it as brand-new.
            again = bw.seed_watch_state("brand-new-question")
        finally:
            if saved is None:
                os.environ.pop("BOARD_WATCH_STATE", None)
            else:
                os.environ["BOARD_WATCH_STATE"] = saved
        check("ask seeds the fresh question even on a resting board",
              ok is True)
        check("the seeded question is known, so a second seed is a no-op",
              again is False)

        s1 = json.load(open(st))
        check("the seed records the unanswered fingerprint (idx:|ans:|on:)",
              s1["answers"].get("brand-new-question") == "idx:|ans:|on:",
              str(s1.get("answers")))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_landed_needs_no_tick():
    """**The watcher no longer touches LANDED, and that is the fix.**

    He reported the same hole four times against two correct fixes, because
    both of them made something WRITE the missing rows and a writer has to be
    deployed: the board window is live source with no hot reload, so the one he
    had open never ran the first fix, and this watcher is a home-manager unit,
    so on `top` the second one needed a `sudo rebuild-top` before it existed
    there at all. His verdict was to stop writing them — *"it should just read
    from the commit log of the repo itself. it shouldnt need an agent to do
    that"*.

    So the two claims here are the inverse of the ones this test used to make:
    a tick appends NOTHING to LANDED, and the commit nobody recorded is in the
    section anyway, derived by `bm.landed_view()` from `git log` with no watcher
    involved at all. That is what makes a stale watcher harmless.
    """
    print("\nLANDED is derived from git, so a tick does not have to write it")
    d = tempfile.mkdtemp(prefix="board-watch-landed-")
    try:
        repo = os.path.join(d, "repo")
        os.makedirs(os.path.join(repo, "docs"))
        base = dict(os.environ, GIT_CONFIG_GLOBAL=os.path.join(d, "gitconfig"),
                    GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
                    GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                    GIT_COMMITTER_EMAIL="t@t")

        def git(*a):
            return subprocess.run(["git", "-C", repo] + list(a), env=base,
                                  capture_output=True, text=True)

        git("init", "-q", "-b", "main")
        made = []
        for age, subject in ((240, "the one LANDED already names"),
                             (120, "the one nobody landed")):
            open(os.path.join(repo, str(age)), "w").write("x")
            git("add", "--", str(age))
            when = "@%d +0000" % int(time.time() - age)
            base["GIT_AUTHOR_DATE"] = base["GIT_COMMITTER_DATE"] = when
            git("commit", "-q", "-m", subject)
            made.append(git("rev-parse", "--short", "HEAD").stdout.strip())
        # NO `origin/main` is created. The old sweep read that ref alone and was
        # blind to anything this machine had not pushed; the view reads HEAD.

        r = Rig(d)
        r.board = os.path.join(repo, "docs", "board.md")
        day = time.strftime("%Y-%m-%d")
        with open(r.board, "w") as f:
            f.write(FIXTURE.replace("### 2026-07-28", "### " + day)
                           .replace("| `abc1234` | did a thing |",
                                    "| `%s` | the one LANDED already names |"
                                    % made[0]))
        before = open(r.board).read()
        env = dict(BOARD_LANDED_REPO=repo)
        p = subprocess.run([sys.executable, WATCHER], env=r.env(**env),
                           capture_output=True, text=True, timeout=120)
        if VERBOSE:
            print("    rc=%d %s" % (p.returncode, p.stderr.strip()[:300]))
        check("a tick appends NOTHING to LANDED - nothing has to be deployed "
              "for the section to be current", open(r.board).read() == before,
              open(r.board).read()[:400])

        sys.path.insert(0, os.path.join(REPO, "apps", "board"))
        sys.path.insert(0, os.path.join(REPO, "apps", "pylib"))
        import boardparse as B
        import boardmove as bm
        old_repo, old_docs = bm.LANDED_REPO, bm.LANDED_DOCS_REPO
        bm.LANDED_REPO, bm.LANDED_DOCS_REPO = repo, os.path.join(repo, "docs")
        bm._tip_cache["key"] = None
        try:
            view = bm.landed_view(B.parse(B.read(r.board)), fetch=False)
        finally:
            bm.LANDED_REPO, bm.LANDED_DOCS_REPO = old_repo, old_docs
            bm._tip_cache["key"] = None
        whats = [row["what"] for g in view for row in g["rows"]]
        check("...and the commit nobody landed is in the section regardless, "
              "read straight out of git", "the one nobody landed" in whats,
              whats)
        check("...with the row somebody DID record still saying his sentence",
              "the one LANDED already names" in whats, whats)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_cancelled_summoner():
    """CTRL+Z, from this side of the hand-off: a summoner he took back leaves
    NOTHING behind — no dispatch, no note, and not his own sentence returned as
    a failure.

    [his, 2026-07-29] *"he should not send any messages he should just stop doing
    that specific inbox item"*. The gate itself lives in `boardctl` and is
    checked by `board-test.py`; what this covers is the half only a real tick can
    show — a summoner that exits NONZERO after being cancelled must not take the
    `QUEUE_FAIL` path, because it did not fail.
    """
    print("\nctrl+z - a summoner he took back")
    d = tempfile.mkdtemp(prefix="board-watch-cancel-")
    try:
        r = Rig(d, EMPTY_NEEDS)
        r.note("build the thing I have changed my mind about")
        # The stub IS him pressing ctrl+z: it cancels the order this run was
        # given, the way the window does, and then dies nonzero.
        cancel = (
            '%s -c "import os,sys;'
            "sys.path[:0]=[os.path.join(%r,'apps','board')];"
            "import boardundo as bu, json;"
            "p=os.path.join(os.environ['XDG_STATE_HOME'],'board','orch',"
            "os.environ['BOARD_WATCH_KEY']+'.json');"
            "print(bu.cancel(json.load(open(p))['items'][0]['id']))\";"
            'echo "$BOARD_WATCH_KEY" >> %s; exit 1'
            % (sys.executable, REPO, r.fired))
        r.run(spawn=cancel)
        check("the summoner ran", len(r.fires()) == 1, str(r.fires()))
        check("...and NOTHING about it was written on the board",
              "changed my mind about" not in r.text(), r.text()[-400:])
        check("...not even the failure note its exit code would normally earn",
              "Solomon exited" not in r.text())
        check("...the log says he took it back",
              "cancelled with ctrl+z" in open(r.log).read(),
              open(r.log).read()[-300:])
        check("...and the queue is empty, so nothing re-triggers",
              r.queued() == [], r.queued())
        rest = os.path.join(d, "xdgstate", "board", "inbox", "cancelled")
        check("...while his words are still on disk, cancelled, not deleted",
              len(os.listdir(rest)) == 1, os.listdir(rest))
        check("...and no run record is left behind for the next tick",
              os.listdir(os.path.join(d, "xdgstate", "board", "orch")) == [])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_dead_worker_names_its_transcript():
    """A worker that recorded nothing leaves a bullet that says WHERE TO READ
    what it did — and since 2026-07-30 that is the transcript, in one hop.

    `claude -p` writes its stdout once, at exit, so a killed worker's
    `~/.cache/board-work/<id>.log` used to be zero bytes. `boardwork` now writes
    that file a header and a post-mortem and hands the failed record a
    `transcript` key (commit f3d5b4d); the bullet quotes it when it is there and
    falls back to the log-only wording when it is not, because older records and
    any spawn that recorded no session have neither.

    Both shapes are asserted through the REAL `note_on_board`, not by reading
    the template: the bullet goes through `boardparse`'s tag, separation and
    dozen-word checks, and a failure note that is refused is the one failure
    this file exists to prevent.
    """
    print("\na dead worker's bullet points at its transcript")
    d = tempfile.mkdtemp(prefix="board-watch-transcript-")
    try:
        r = Rig(d, EMPTY_NEEDS)
        mod = _load_watcher(r.env())
        tx = "/home/lam/.claude/projects/-home-lam-nix/deadbeef.jsonl"

        with_tx = mod.worker_fail_bullet(
            {"agent": "we12345", "task": "outlive the tick", "transcript": tx})
        check("the bullet names the transcript when the record carries one",
              tx in with_tx, with_tx)
        check("...and still says which log, so both hops are on the line",
              "board-work/we12345.log" in with_tx, with_tx)
        check("...on the indented continuation line, not the summary",
              tx not in with_tx.splitlines()[0]
              and with_tx.splitlines()[1].startswith("    "), with_tx)

        without = mod.worker_fail_bullet(
            {"agent": "we12345", "task": "outlive the tick"})
        check("a record with no transcript keeps the log-only wording",
              "board-work/we12345.log" in without
              and "Transcript" not in without, without)
        check("...and never trails an empty span for the path it does not have",
              without.rstrip().endswith("board-work/we12345.log`"), without)

        # Nothing either shape adds may read as a bullet, a tag or a second ask
        # to the checks in `add_todo_bullet` — assert by actually placing them.
        for label, bullet in (("with a transcript", with_tx),
                              ("without one", without)):
            ok = r.state_home(lambda b=bullet: mod.note_on_board(b))
            why = open(r.log).read()[-300:] if os.path.exists(r.log) else ""
            check("the board accepts the bullet %s" % label, bool(ok), why)
        placed = [l for l in r.text().splitlines()
                  if "a minister stopped without finishing" in l]
        check("...both landing as their own FAILED bullet", len(placed) == 2,
              str(placed))
        check("...and the transcript path reaches the file intact",
              tx in r.text(), r.text()[-400:])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_decision_does_not_hold_the_tick():
    """A DECISION RUNS IN ITS OWN UNIT, and the tick goes on without it.

    [his, 2026-08-01] *"why is there currently a pending order for solomon yet
    he is sitting there doing nothing"* — a decision run held `board-watch.service`
    for its whole life (five minutes, that time), and the sentence he typed at
    00:03 sat in the queue because the only unit that could summon Solomon was
    busy being a decision agent. `systemctl --user list-jobs` showed exactly one
    job, waiting on itself.

    Asserted at the seam rather than by starting a real agent: `_start_unit` is
    intercepted, so what is checked is that `spawn(detach=True)` goes through
    it, hands back `rc=None` (nothing to report — the close-out moves to the
    next tick's `retire_finished`/`reconcile`), adopts the AGENT's pid onto the
    stash, and never reaches the `Popen` that would have made this tick wait.
    """
    print("\na decision does not hold the tick")
    d = tempfile.mkdtemp(prefix="board-watch-detach-")
    try:
        r = Rig(d, EMPTY_NEEDS)
        env = r.env()
        old = dict(os.environ)
        os.environ.update({k: v for k, v in env.items() if isinstance(v, str)})
        os.environ.pop("BOARD_WATCH_SPAWN", None)      # the stub never detaches
        try:
            mod = _load_watcher(env)
            seen, waited, adopted = {}, [], []

            def fake_unit(aid, cmd, env_, logpath, title, **kw):
                seen.update(dict(kw, aid=aid, cmd=cmd, log=logpath, env=env_))
                return 4242

            def fake_popen(cmd, **kw):
                waited.append(cmd)
                raise AssertionError("a detached decision must not be waited on")

            real_unit, real_popen = mod.bw._start_unit, mod.subprocess.Popen
            mod.bw._start_unit, mod.subprocess.Popen = fake_unit, fake_popen
            try:
                rc, how, _ = mod.spawn("a prompt", "some-key", "board: decision 1",
                                       session="fixed-uuid-here", detach=True,
                                       on_start=adopted.append)
            finally:
                mod.bw._start_unit, mod.subprocess.Popen = real_unit, real_popen

            check("a detached decision is started through a transient unit",
                  bool(seen) and not waited, str(waited[:1]))
            check("...in its OWN namespace, not the workers'",
                  seen.get("prefix") == mod.bw.DECISION_PREFIX
                  and seen.get("kind") == "decision", str(seen.get("prefix")))
            check("...with the run cap systemd can enforce and a wait cannot",
                  seen.get("runtime") == mod.AGENT_TIMEOUT_S, str(seen.get("runtime")))
            check("...carrying the key every guard against firing twice reads",
                  (seen.get("env") or {}).get("BOARD_WATCH_KEY") == "some-key")
            check("...and the session id its card is read from",
                  "--session-id" in (seen.get("cmd") or [])
                  and seen["cmd"][seen["cmd"].index("--session-id") + 1]
                  == "fixed-uuid-here", str((seen.get("cmd") or [])[:6]))
            check("the stash follows the AGENT's pid, not the watcher's",
                  adopted == [4242], str(adopted))
            check("...and the caller is told there is nothing to report yet",
                  rc is None and "board-decision-" in how, (rc, how))
        finally:
            os.environ.clear()
            os.environ.update(old)
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
        note = [l for l in after.splitlines()
                if "board-watch did not finish" in l]
        check("a failure note is on the board", len(note) == 1, str(note))
        check("...in WAITING ON YOU TO DO",
              after.index(note[0]) > after.index("## WAITING ON YOU TO DO")
              and after.index(note[0]) < after.index("## IN FLIGHT")
              if note else False)
        # The decision's title is interpolated data of unknown length, so it
        # sits on the bullet's INDENTED continuation line, not the summary.
        lines = after.splitlines()
        cont = lines[lines.index(note[0]) + 1] if note else ""
        check("...naming the decision, on the continuation line under it",
              "First question" in cont, cont[:80])
        rest_before = before.replace("- [ ] Do it the short way",
                                     "- [x] Do it the short way")
        check("...and nothing else in the file moved",
              unmoved(after, rest_before, "board-watch did not finish",
                      "the minister exited"),
              "%d vs %d chars" % (len(after), len(rest_before)))
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
        # "When it is okay to rebuild or hot-reload" replaced "NEVER rebuild"
        # here on 2026-07-29: an agent may rebuild now, and what the prompt must
        # still carry is the POINTER to the one written rule (`~/nix/AGENTS.md`)
        # rather than a paraphrase of it. Since 2026-07-31 the rules THEMSELVES
        # live in the appended system prompt (see the `..and that rules block is
        # the same one` check below, which proves a decision run gets `bw.RULES`
        # verbatim), so this body is asserted for the pointer and the decision
        # content, not for RULES prose that moved out of it.
        for want in ("`top`",
                     "RULES are in force for this session and not negotiable",
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
              "RULES bind you and every worker you dispatch" in note_prompt
              and "they are in your system prompt" in note_prompt)
        # The rules themselves now live in the appended SYSTEM prompt, not the
        # `-p` body (see docs/agents/minister-context.md), so the channel that
        # carries them to the agent is the spawn argv, and "the same rules a
        # decision run gets" means: the same RULES block is appended for the
        # orchestrator as for a decision agent.
        import boardwork as bw
        def _appended(argv):
            return argv[argv.index("--append-system-prompt") + 1]
        orch = bw.get_backend().args(prompt="x", session=None,
                                     role="orchestrator", label="l")
        dec = bw.get_backend().args(prompt="x", session=None,
                                    role="decision", label="l")
        check("..and that rules block is the same one a decision run gets, verbatim",
              "When it is okay to rebuild or hot-reload" in _appended(orch)
              and "-- <explicit> <paths>" in _appended(orch)
              and "Push to `main`" in _appended(orch)
              and _appended(orch) == _appended(dec) == bw.RULES)
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
        bullet = [l for l in after.splitlines()
                  if "what you typed could not be worked" in l]
        check("a failed orchestrator run leaves a bullet on the board", len(bullet) == 1,
              str(bullet))
        # His sentence is data of unknown length, so it is quoted on the
        # bullet's indented continuation line, under the dozen-word summary.
        lines = after.splitlines()
        cont = lines[lines.index(bullet[0]) + 1] if bullet else ""
        check("...quoting what he wrote, so it is not lost with the run",
              "off by a pixel" in cont, cont[:80])
        check("...and moves nothing else in the file",
              unmoved(after, before, "what you typed could not be worked",
                      "Solomon exited"))
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

    test_worker_outlives_the_tick()
    test_a_rebuild_kills_the_tick()
    test_summoner_fanout()
    test_cancelled_summoner()
    test_coalescing()
    test_the_loop()
    test_host_affinity()
    test_stamped_answer_on_first_sight()
    test_seed_guards_a_fresh_question_on_a_resting_board()
    test_landed_needs_no_tick()
    test_dead_worker_names_its_transcript()
    test_decision_does_not_hold_the_tick()

    print()
    if fails:
        print("FAILED: " + ", ".join(fails))
        return 1
    print("all board-watch assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
