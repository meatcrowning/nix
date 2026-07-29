"""The fan-out: one sentence he typed -> an orchestrator -> several workers.

He asked for this in one sentence: *"a single box that i could type things into,
press enter, and have them sent to an inbox. then an agent figures out what
agents to assign to what (like how you used to orchestrate) and as agents
spawned, theyd show up as a little visual box that indicated what they were
doing, and each agent would be placed in sections based on what they were doing;
planning, researching, coding, testing, finishing touches"*.

`boardagents.py` already owned the INBOX half of that — the box, the three
directories, and the argument that nothing he types can be lost. This module
owns what happens after: who gets spawned, how many at once, what a card is
allowed to claim about them, and where the ones above the cap wait.

A CARD CARRIES TWO STATEMENTS, AND NEITHER IS THE OTHER
-------------------------------------------------------
What an agent SAYS it is doing, and what it is OBSERVED doing, are both drawn —
his call, in one sentence: *"i want both"*. `boardphase.py` owns the whole of
that and its docstring is the authority; what matters here is which one this
module sections the cards by. **It is the observed one, always.** A phase is
derived from the tool calls in the agent's live transcript and cannot be set by
the agent; the claim is drawn beside it and never promoted. A card that says
`testing` under a `coding` heading is this system working, not failing.

Three consequences that are rules:

  * **Neither one decides whether an agent is alive.** That is `boardmove._alive`
    (pid + kernel start time), the ONE liveness rule in this tree, exactly as
    `boardagents.py` says. `groups()` puts anything whose process is gone in
    `stopped`, whatever its transcript or its claim last said, and
    `boardagents.sweep()` deletes the sidecar on the next tick. Two layers, one
    immediate (the app polls liveness every 2.5s) and one durable.
  * **An agent that has done nothing gets no phase invented for it.** It lands
    in `unreported`, whose label says so — it does NOT inherit the phase it
    claimed. Sectioning by a claim would undo the whole point.
  * **The spawn passes `--session-id`,** so the transcript to observe is CHOSEN
    rather than guessed at. That flag is load-bearing; see `boardphase.py`.

THE CAP, and what happens above it
----------------------------------
An orchestrator that fans out without a bound is a real cost and a real risk on
a live desktop: every worker is a full model session with a shell in a SHARED
git checkout. `cap()` is 4 by default and is a FILE
(`~/.local/state/board/cap`), not a nix option — he can change it at 2am with
`boardctl.py cap 6` and no rebuild, the same reasoning board-watch's kill switch
is a file.

Work above the cap is **queued, never dropped**, and it is queued the same way
his own sentences are: a JSON file created by `os.replace()` into exactly one of

    work/pending/   dispatched, waiting for a slot
    work/taken/     promoted; a worker was spawned for it

and only ever moved between them by `os.replace()` again. `promote()` runs at
the top of every board-watch tick, so the worst case for a queued task is one
timer interval. It is drawn on his board in the `queued` group, because work
that exists and is not running is exactly the thing a control surface must not
hide.

A WORKER IS ITS OWN SYSTEMD UNIT, and that is not a nicety
----------------------------------------------------------
**A detached child stays in its spawner's cgroup, and `board-watch.service` is
a `oneshot`: when the orchestrator run finished, systemd killed everything left
in that cgroup — every worker it had just started.** Measured on `top`
2026-07-29, and it was live for a day: worker `we9f99c` registered at 22:49:16,
the orchestrator exited at 22:49:29, and the worker's transcript ends thirteen
seconds in, three tool calls deep, with `[Request interrupted by user]`. Nobody
interrupted it. The orchestrator honestly reported "dispatched one worker",
wrote a completion note, and **nothing was ever built** — the failure mode is
SILENT SUCCESS, which is the worst one this system can have.

`start_new_session=True` was never the fix: that detaches the process GROUP,
which is a terminal-signal concept, and says nothing about the cgroup systemd
kills by. So `_spawn_worker` asks the user manager for a transient unit instead:

    systemd-run --user --unit=board-worker-<id> --service-type=exec ...

Four things fall out of it, and all four are why this and not `KillMode=process`
on the parent (which also survives — both were measured — but is a `.nix` change
that only takes effect after a rebuild this system is not allowed to run):

  * **The worker outlives the tick, the orchestrator, and every later tick.**
    Its cgroup is its own and nothing sweeps it. `tools/board-watch-test.py`
    proves it end to end: a worker dispatched with a job of *sleep past the
    orchestrator's exit, then write a file* must have written that file.
  * **It is a genuine systemd unit**, which is what he asked for in the first
    place — *"a display on the board of currently active systemd claude agents"*.
  * **`WORKER_TIMEOUT_S` finally means something.** It was declared and never
    enforced: a detached `Popen` has no timeout. It is `RuntimeMaxSec` now.
  * **Nothing has to reap it.** The user manager is its parent, so the zombie
    window `boardmove._alive` guards against cannot open for a worker at all.
    That clause stays: it is the ONE liveness rule and other callers rely on it.

**Liveness is unchanged.** The unit writes its own pid into `work/pids/` before
`exec`, so `boardmove._alive` goes on deciding by pid and kernel start time and
there is still exactly one definition of "running" in this tree. `systemctl` is
not consulted — a second answer to "is it alive" is the thing that must not
appear here.

A DISPATCH IS A START, NEVER A RESULT
--------------------------------------
The bug above cost him the work twice over: it also produced a board that said
the work was done. So a worker's ending is now accounted for rather than
assumed. `mark_reported()` is stamped by `boardctl note|land|ask` whenever
`BOARD_AGENT_ID` names a worker, and `reap()` — at the top of every board-watch
tick, beside `reconcile()`, `sweep()` and `promote()` — closes out every worker
whose process is gone: one that recorded something is `done`, one that did not
is `failed` AND SAYS SO ON HIS BOARD. The orchestrator's prompt is the other
half: it may say what it handed out, never that anything landed.

NO TIME PRESSURE. Nothing here hands the UI an elapsed time, an age, a count or
an ordering by urgency. `at` stamps exist so `promote()` can take the oldest
pending task first; they never reach the screen. Same rule as the rest of the
app, and it is the app's founding requirement.
"""
import json
import os
import shutil
import subprocess
import time
import uuid

import boardagents as ba
import boardphase as bph

#: The repo a worker works in. Same env key board-watch uses, so a worker
#: spawned by `boardctl` from inside a board-watch run inherits the right one.
REPO = os.environ.get("BOARD_WATCH_REPO", os.path.expanduser("~/nix"))

#: How many workers may run at once when nothing says otherwise. Four is a
#: judgement call, not a measurement: it is the point where the shared git index
#: and one 16-thread desktop stop being comfortable, and it is trivially
#: changed. `BOARD_MAX_WORKERS` is for the harness; the file is for him.
DEFAULT_CAP = 4

#: A worker is capped like a decision agent is — the same 45 minutes, so one
#: wedged run cannot hold a slot for the rest of the day.
WORKER_TIMEOUT_S = int(os.environ.get("BOARD_WORK_TIMEOUT", "2700"))

# The phases, in the order work moves through them, and the exact words on the
# section heads. His five, plus three states that are REAL and must not be
# smuggled into one of them:
#   unreported — running, but nothing observed in its transcript yet
#   queued     — dispatched above the cap; no process exists for it
#   stopped    — its process is gone and it never said it finished
PHASES = ["unreported", "planning", "researching", "coding", "testing",
          "finishing", "queued", "stopped"]
PHASE_LABELS = {
    "unreported": "nothing observed yet",
    "planning": "planning",
    "researching": "researching",
    "coding": "coding",
    "testing": "testing",
    "finishing": "finishing touches",
    "queued": "not started yet",
    "stopped": "stopped",
}


# --------------------------------------------------------------- state layout
def _root():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "board")


def work_dir(*parts):
    d = os.path.join(_root(), "work", *parts)
    os.makedirs(d, exist_ok=True)
    return d


# ------------------------------------------------------------------- the cap
def cap_file():
    return os.path.join(_root(), "cap")


def cap():
    env = os.environ.get("BOARD_MAX_WORKERS")
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    try:
        with open(cap_file()) as f:
            return max(1, int(f.read().strip()))
    except (OSError, ValueError):
        return DEFAULT_CAP


def set_cap(n):
    n = max(1, int(n))
    os.makedirs(_root(), exist_ok=True)
    tmp = cap_file() + ".tmp"
    with open(tmp, "w") as f:
        f.write("%d\n" % n)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, cap_file())
    return n


# ------------------------------------------------------------------ dispatch
# ------------------------------------------------------------- which machine
#: This system runs on BOTH machines now (`home/srvs/board-watch.nix`), so an
#: agent can no longer be told it is on `top`: it was, for a while, and a prompt
#: naming the wrong host is worse than one naming none — the rebuild command,
#: the architecture and the flake attribute are all different on book.
#:
#: `os.uname().nodename` is the OS hostname (`top` / `book`), which is not the
#: flake attribute (`top` / `air`); the table below is the one place that
#: mapping is written down outside `~/nix/AGENTS.md`.
HOST = os.environ.get("BOARD_WATCH_HOST") or os.uname().nodename

_HOSTS = {
    "top": "x86_64 NixOS, flake attribute `top`. A rebuild here would be "
           "`sudo rebuild-top` - which you are not allowed to run",
    "book": "an aarch64 MacBook Air running Fedora Asahi with home-manager "
            "layered on top, flake attribute `air`. It is NOT NixOS: there is "
            "no `rebuild-top` and no `sys/` here, and the equivalent of a "
            "rebuild is `home-manager switch --flake ~/nix#air` - which you "
            "are not allowed to run either",
}


def host_line():
    """``top` (x86_64 NixOS, ...)`, for the top of every prompt."""
    return "`%s` (%s)" % (HOST, _HOSTS.get(
        HOST, "a machine this system has no description for - read "
              "`~/nix/AGENTS.md` before running anything that changes it"))


#: The rules every agent this system spawns runs under. They are HIS decisions,
#: already settled (see `home/srvs/board-watch-files/board-watch.py`), and the
#: two new prompts below quote them verbatim rather than paraphrasing: a worker
#: that rebuilds his machine while he is looking at something else is the one
#: failure this whole feature must not have.
RULES = """1. **NEVER rebuild and never change the running machine.** No `sudo \
rebuild-top`, `nixos-rebuild`, `home-manager switch`, `hyprctl`, `qs ipc`, \
`systemctl`, `loginctl`. `apps/` runs live source, so a `.py`/`.qml` change is \
picked up when he next relaunches. If the work cannot land without a rebuild or \
a reload: **stop, leave that part undone**, and say so on the board.
2. **Never open a window on his screen and never drive his running apps.** \
Offscreen harnesses (`QT_QPA_PLATFORM=offscreen`) and `tools/sandbox.sh` only; \
he does every visual check himself.
3. **The git index here is SHARED** with him and with the other agents running \
right now. `git commit -m "msg" -- <explicit> <paths>`, always. `git add -N` \
for new files. Never a bare `git commit`, never `-a`, never a destructive or \
reverting git command (`reset --hard`, `checkout --`, `restore`, `stash`, \
`clean`).
4. **Push to `main`** when it works. No branch, no PR — and **`git pull \
--rebase` immediately before you push.** This system now runs on BOTH of his \
machines, so another agent on the other host may have pushed since you started; \
a rejected push is normal and the answer is `git pull --rebase` and push again, \
never `--force` and never giving up. `~/nix` (public) and `docs/` (private, its \
own repo inside this checkout) are SEPARATE repos: pull and push each from its \
own directory.
5. Read `AGENTS.md` at the repo root, then the nested one closest to what you \
are editing, then `docs/DESIGN.md` if you put pixels on a screen. They outrank \
your instincts about this codebase."""

WORKER_PROMPT = """You are running headless, with no human watching, on the \
machine {host}. Work in `{repo}`.

An orchestrator split up something he asked for and gave you one piece of it. \
This is your whole job; another agent has the rest, and may be editing other \
files in this same checkout right now.

--- your task ---
{task}
--- end ---

{context}
RULES, in force for this session, and not negotiable:

{rules}

6. **Say what you are working on.** He is looking at a card for this agent, and \
it shows two lines: what you SAY you are doing, and what you are OBSERVED doing \
(read from your own transcript — every tool call you make). From `{repo}`, at \
the start and whenever you move on:

       python3 apps/board/tools/boardctl.py phase researching --doing '<one \
short line, present tense, naming the THING>'

   The phases are `planning`, `researching`, `coding`, `testing`, `finishing`. \
**Your words do not set the phase the card is filed under** — that is derived \
from what you actually do, and you cannot change it from here. Say it anyway: \
it is the only channel that carries WHAT you are working on rather than which \
verb you last used, and he reads the two side by side deliberately. Being \
honest costs you nothing; a claim that does not match your tool calls is \
visible to him and is not hidden.

7. **When you are done, record it on the board — with the tool, never by \
hand:**

       python3 apps/board/tools/boardctl.py note '**<what you were asked>** - \
<what you did, what you did not, and whether a rebuild is now pending and why>'

   `docs/board.md` is a store three programs parse and write concurrently; \
every edit is a targeted line edit under a lock. Do not open it in an editor. \
`docs/` is its own git repo inside this checkout, so commit from inside `docs/`.

   **Run it even if you finished nothing** — say what stopped you. A worker \
that ends without recording anything is reported on his board as having stopped \
without finishing, which is deliberate: he must never be told something landed \
when it did not. That report is the only thing you cannot leave behind.

8. **If you genuinely cannot decide something only he can decide, ASK — do not \
guess big:**

       python3 apps/board/tools/boardctl.py ask '<the question>' \\
           --context '<what you found that raises it>' \\
           --option '<one way>' --option '<another way>' \\
           --if-unanswered '<what you will do / what stays undone>'

   It appears in the questions list on his board and he answers at his leisure. \
Then finish the part you CAN do and stop; there is nobody to wait for.

9. **He can reach you WHILE you run. Check between steps:**

       python3 apps/board/tools/boardctl.py inbox take --quiet

   Your stdin is closed, so a file is the only channel there is. Anything that \
prints is him typing at you mid-flight, and it OUTRANKS this prompt.

There is nobody to ask. Finish, or write down why you did not.
"""

ORCHESTRATOR_PROMPT = """You are running headless, with no human watching, on \
the machine {host}. Work in `{repo}`.

**You are the orchestrator, and you do not do the work.** He typed the \
following into the one box on his board. Your job is to work out what it \
implies, split it into pieces, and hand each piece to a worker agent — or, if \
what it implies is genuinely his to decide, to ask him instead.

--- what he wrote ---
{notes}
--- end ---

WHAT YOU MAY DO, and it is a short list:

    python3 apps/board/tools/boardctl.py dispatch '<the task, in full - the \\
worker sees only this>' --where '<the files it will touch>'

    python3 apps/board/tools/boardctl.py ask '<the question>' \\
        --context '<what makes it a question>' \\
        --option '<one way>' --option '<another way>' \\
        --if-unanswered '<what happens if he never answers>'

    python3 apps/board/tools/boardctl.py note '**<subject>** - <one line>'

    python3 apps/board/tools/boardctl.py cap <n>      # a SETTING, applied now

SOMETIMES HE IS NOT ASKING FOR WORK, HE IS TURNING A KNOB. *"change the number \
of allowed agents to 5"* is not a task for a worker — it is this system's own \
setting, and dispatching an agent for it turns a one-second change into a \
model session, a commit and a wait. Apply it yourself with the tool above and \
say so in your note. The knobs you own: the worker cap (`cap`). Anything else \
that looks like a setting but has no tool here is a `dispatch` like any other, \
and say in the note that it needed one.

Read enough of the repo to split the work sensibly — `AGENTS.md` at the root, \
the nested one nearest whatever he is talking about, `docs/DESIGN.md` if it is \
visual. **Do not edit any file, do not commit, and do not run a test.** A \
worker does that. If the whole thing is one indivisible job, dispatch one \
worker; that is a fine answer.

DISPATCH OR ASK — the rule, because guessing big is the expensive mistake:

  * **Dispatch** when the input names a thing and one honest change follows \
from it. "the scrollbar arrows feel sluggish" is a dispatchable task: a worker \
can find the stepper, measure it and change it.
  * **ASK** when it implies a choice between real alternatives he has not made, \
when it would change something desktop-wide (the design language, a shared \
component, every app at once), when it needs a rebuild or a compositor reload, \
or when "how much" is the actual question and only he knows. A question costs \
him ten seconds whenever he feels like it. A wrong guess costs a worker, a \
commit and a change he has to notice and undo.
  * **At most two questions for one input.** A wall of questions is its own \
kind of pressure, and this board exists because he did not want that.
  * Every `ask` MUST carry `--if-unanswered`. That sentence is what makes it \
safe for him to walk away from the question, and the tool refuses without it.

THE CAP. There is a limit on how many workers run at once ({cap} right now). \
`dispatch` enforces it itself: over the cap it QUEUES the task and says so, and \
a later tick starts it when a slot frees. So dispatch everything the input \
genuinely implies and do not ration it yourself — but do not invent work either.

RULES that bind you and every worker you dispatch:

{rules}

YOUR NOTE REPORTS A START, NOT A RESULT — AND IT IS TWO LINES, NOT A \
PARAGRAPH. Finish with one `note`, to this budget: **one line per task you \
handed out, one line per question you asked, 25 words each at the most, and no \
second paragraph.** A task line is the subject, the worker id, and that it was \
handed out with nothing landed yet — like:

    **landed section + commit times** - handed to `wd690a4`, nothing landed yet.

Leave these OUT, by name, because he wrote the input and does not need it read \
back: his own words or facts restated; your theory about what is causing it; \
why you split or grouped the work the way you did; and negative status — no \
"no question for you", no "nothing needed a rebuild". Silence says both.

The one thing that is not up for shortening: **never write that something is \
done, fixed, wired, implemented or working.** You started it and cannot see \
whether it worked; the worker records its own result here when it finishes. He \
was once told, in a note like the one you are about to write, that work was \
dispatched and in hand — when every worker had already been killed and nothing \
was built.
"""

# Allow the tools a working agent needs; deny the ones that change the machine
# out from under him. board-watch imports these rather than keeping a second
# copy — one list, so a hole cannot be opened in one spawner and not the other.
# The prompt is the primary defence and this is the mechanical one; a prefix
# matcher is not a sandbox (see `docs/agents/board-watch.md`).
ALLOW = ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "Task", "TodoWrite",
         "NotebookEdit", "WebFetch", "WebSearch"]
DENY = ["Bash(sudo:*)", "Bash(rebuild-top:*)", "Bash(nixos-rebuild:*)",
        "Bash(rbsys:*)", "Bash(rbhome:*)", "Bash(update:*)",
        "Bash(home-manager:*)",
        "Bash(hyprctl:*)", "Bash(qs:*)", "Bash(systemctl:*)", "Bash(loginctl:*)",
        "Bash(git reset:*)", "Bash(git checkout:*)", "Bash(git restore:*)",
        "Bash(git stash:*)", "Bash(git clean:*)"]


def _task_name():
    return "%s-%s.json" % (time.strftime("%Y%m%dT%H%M%S"), os.urandom(3).hex())


def _log_path(agent_id):
    d = os.path.join(os.path.expanduser("~/.cache"), "board-work")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, ba.clean_id(agent_id) + ".log")


def live_workers():
    return [a for a in ba.agents() if a["kind"] == "worker" and a["state"] == "running"]


def pending():
    """Tasks dispatched above the cap, OLDEST FIRST — that is the order
    `promote()` starts them in, so a task cannot be overtaken indefinitely.

    Sorted on `sent` (a float) rather than `at` (a string with one-second
    resolution): an orchestrator dispatches its whole plan inside one second, so
    the string collapses to a tie and the tiebreak becomes the random hex in the
    filename. Measured — four tasks dispatched in a loop came back 3, 2.

    Never drawn as a count. The queue is drawn as its items or not at all.
    """
    return sorted(ba._list(work_dir("pending")),
                  key=lambda t: (float(t.get("sent") or 0), t.get("file", "")))


def dispatch(task, phase="", where="", context="", cap_=None):
    """One piece of work -> one worker, or -> the pending queue if we are full.

    Returns the task record with `state` in `running` / `queued`. It never
    raises on a full board and never silently drops: the two outcomes are the
    two directories, and `promote()` is what moves between them.
    """
    task = " ".join((task or "").split())
    if not task:
        return None
    rec = {"task": task, "phase": (phase or "").strip().lower(),
           "where": (where or "").strip(), "context": (context or "").strip(),
           "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "sent": time.time(),
           "host": os.uname().nodename}
    limit = cap() if cap_ is None else cap_
    if len(live_workers()) >= limit:
        path = os.path.join(work_dir("pending"), _task_name())
        ba._write_json(path, rec)
        rec["file"] = path
        rec["state"] = "queued"
        return rec
    # Written to `taken/` BEFORE the spawn, exactly as `boardagents.drain()` is:
    # a task file still in `pending/` when the process dies would be worked
    # twice, and one deleted after a crash would be worked never.
    path = os.path.join(work_dir("taken"), _task_name())
    ba._write_json(path, rec)
    rec["file"] = path
    rec.update(_spawn_worker(rec))
    return rec


#: The transient unit a worker runs as, `board-worker-<agent id>.service`. It is
#: also what he sees when he asks systemd what claude agents are running, which
#: is the shape he asked for the agents section in.
UNIT_PREFIX = "board-worker-"

#: Set to `1` to force the old detached-`Popen` path. For a machine with no
#: systemd user manager only — a worker started that way DIES WITH THE TICK when
#: the caller is `board-watch.service`, which is the bug this replaced.
NO_UNIT = os.environ.get("BOARD_WORK_NO_UNIT") == "1"

def unit_name(agent_id):
    return UNIT_PREFIX + ba.clean_id(agent_id)


def _start_unit(aid, cmd, env, logpath, title):
    """Ask the user manager for one transient unit. Returns a pid, or None.

    None means "nothing was started" — the caller may safely fall back. A pid of
    -1 means "it started and is already gone", which `boardmove._alive` reads as
    dead; 0 must never be returned, because `_alive` reads 0 as *unowned* and
    would leave a phantom card running forever.

    `--service-type=exec` is what makes the pid knowable: it does not return
    until the unit's process has `exec`ed, so `MainPID` is the agent itself and
    is read exactly once, here, to fill in the registration. **That is a
    recording, not a liveness rule** — `boardmove._alive` goes on being the only
    answer to "is it running", by pid and kernel start time, and nothing in this
    tree asks systemd that question. A worker that manages to exit inside that
    window has no MainPID left to read and is recorded as already gone, which is
    true.

    (A pid file written by a shell shim was tried first and is a trap: systemd
    expands `$` in `ExecStart`, so `echo $$` reaches the shell as a bare `$` and
    every worker looked like it had exited immediately. Measured.)
    """
    if NO_UNIT or not shutil.which("systemd-run"):
        return None
    unit = unit_name(aid)
    run = ["systemd-run", "--user", "--quiet", "--collect",
           "--unit", unit, "--service-type=exec",
           "--working-directory", REPO,
           "--description", "board worker: " + title[:60],
           # The 45 minutes `WORKER_TIMEOUT_S` always claimed and a detached
           # Popen could never enforce. One wedged worker must not hold a slot
           # against the cap for the rest of the day.
           "--property=RuntimeMaxSec=%d" % WORKER_TIMEOUT_S,
           "--property=StandardInput=null",
           "--property=StandardOutput=append:%s" % logpath,
           "--property=StandardError=append:%s" % logpath]
    # A transient unit starts in the MANAGER's environment, not ours, so
    # everything the worker needs has to be carried across explicitly — PATH to
    # find `claude`, HOME, and the BOARD_* overrides a harness sets. Same set the
    # `Popen` path passed; a newline cannot go through `--setenv` and nothing we
    # pass has one.
    for k in sorted(env):
        v = env[k]
        if isinstance(v, str) and "\n" not in v and "\0" not in v:
            run.append("--setenv=%s=%s" % (k, v))
    run += ["--"] + cmd
    try:
        p = subprocess.run(run, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    try:
        q = subprocess.run(["systemctl", "--user", "show", unit,
                            "-p", "MainPID", "--value"],
                           capture_output=True, text=True, timeout=30)
        return int(q.stdout.strip() or 0) or -1
    except (OSError, ValueError, subprocess.SubprocessError):
        return -1           # it ran; we could not see which pid. Not "unowned".


def _start_detached(cmd, env, logpath):
    """The fallback, for a machine with no user manager. Returns a pid or None.

    **Under `board-watch.service` this does not survive the tick** — a detached
    child stays in the unit's cgroup and a `oneshot` takes its cgroup with it.
    Kept only so `boardctl dispatch` still works from an ordinary shell where
    there is nothing to be killed by.
    """
    try:
        log = open(logpath, "ab", buffering=0)
    except OSError:
        log = subprocess.DEVNULL
    try:
        p = subprocess.Popen(cmd, cwd=REPO, env=env, stdin=subprocess.DEVNULL,
                             stdout=log, stderr=subprocess.STDOUT,
                             start_new_session=True)
    except OSError:
        return None
    finally:
        if log is not subprocess.DEVNULL:
            log.close()
    return p.pid


def _spawn_worker(rec):
    """Start a worker in ITS OWN UNIT and register it. Returns {id, pid, session}.

    Not waited on, on purpose: the orchestrator that calls this is itself running
    inside a board-watch tick, and a tick that waits on four 45-minute workers
    would hold board-watch's flock for the rest of the day — nothing else could
    fire, including the decision he answers in the meantime.

    But "not waited on" is not "detached", and conflating the two is what cost
    him a day of silently-killed workers: see the module docstring. The worker
    gets a transient systemd unit, so its cgroup is its own and the oneshot that
    started it takes nothing with it when it exits.

    **`--session-id` is why the card can say what the worker is really doing.**
    We choose the uuid, so we know exactly which transcript under
    `~/.claude/projects/*/` is this agent's — no matching by mtime, no guessing
    a filename. `boardphase.observe()` tails it. Verified on top 2026-07-29: a
    headless `-p` run with a chosen id writes `<uuid>.jsonl` there and appends to
    it live.
    """
    aid = "w%s" % os.urandom(3).hex()
    session = str(uuid.uuid4())
    prompt = WORKER_PROMPT.format(
        repo=REPO, host=host_line(), task=rec["task"], rules=RULES,
        context=("--- what the orchestrator knows that you do not ---\n%s\n--- end ---\n\n"
                 % rec["context"]) if rec.get("context") else "")
    stub = os.environ.get("BOARD_WORK_SPAWN")
    if stub:
        cmd = ["/bin/sh", "-c", stub]
    else:
        cmd = ["claude", "-p", prompt,
               "--session-id", session,
               "--permission-mode", "acceptEdits",
               "--allowedTools", *ALLOW,
               "--disallowedTools", *DENY,
               "--output-format", "text",
               "-n", "board: " + rec["task"][:50]]
    env = dict(os.environ, BOARD_AGENT_ID=aid, BOARD_WATCH_KEY=aid,
               BOARD_WORK_TASK=rec["task"], BOARD_WORK_SESSION=session)
    logpath = _log_path(aid)
    pid = _start_unit(aid, cmd, env, logpath, rec["task"])
    how = "unit"
    if pid is None:
        pid = _start_detached(cmd, env, logpath)
        how = "detached"
    if pid is None:
        return {"id": aid, "pid": 0, "state": "failed",
                "why": "neither systemd-run nor a plain spawn would start it"}
    ba.register(aid, rec["task"][:70], pid, kind="worker",
                where=rec.get("where") or "", session=session)
    # The task file learns which agent owns it, so `reap()` can tell a worker
    # that finished and said so from one that vanished mid-sentence. Written
    # after the spawn: before it there is no id, and a task with an id but no
    # process would be reaped as a failure on the very next tick.
    if rec.get("file"):
        rec = dict(rec, agent=aid, unit=(UNIT_PREFIX + ba.clean_id(aid))
                   if how == "unit" else "")
        try:
            ba._write_json(rec["file"], {k: v for k, v in rec.items()
                                         if k != "file"})
        except OSError:
            pass
    return {"id": aid, "pid": pid, "session": session, "state": "running",
            "agent": aid, "spawned": how}


# ------------------------------------- a dispatch is a START, never a RESULT
def reported_file(agent_id):
    return os.path.join(work_dir("reported"), ba.clean_id(agent_id) + ".json")


def mark_reported(agent_id=None, what=""):
    """Record that this agent put its result on the board.

    Called by `boardctl note|land|ask`, which are the three ways a worker is
    allowed to say anything at all. It is what makes `reap()` able to tell a
    worker that finished from one that stopped mid-sentence — and that
    distinction is the whole reason it exists, because before it a worker that
    was killed thirteen seconds in was indistinguishable, on his board, from one
    that did the job.
    """
    aid = ba.clean_id(agent_id or os.environ.get("BOARD_AGENT_ID") or "")
    if not aid or aid == "agent":
        return False
    try:
        ba._write_json(reported_file(aid),
                       {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        "what": " ".join((what or "").split())[:300]})
    except OSError:
        return False
    return True


def reap():
    """Close out every worker whose process has gone. Returns (done, failed).

    Run at the top of every board-watch tick, beside `reconcile()`, `sweep()`
    and `promote()` — same shape, same worst case of one timer interval.

    A `failed` record is not bookkeeping: **the caller puts it on his board**. A
    worker that stops without recording anything did not do the work, and the
    one thing this system must never do is let that read as done. It is also the
    only trace such a worker leaves, since its registration is dropped by
    `sweep()` and its card leaves the list the moment it dies.
    """
    live = {a["id"] for a in ba.agents() if a["state"] == "running"}
    done, failed = [], []
    for rec in ba._list(work_dir("taken")):
        aid = rec.get("agent")
        if not aid or aid in live:
            continue          # still working, or dispatched before this existed
        ok = os.path.exists(reported_file(aid))
        moved = ba._move(rec, work_dir("done" if ok else "failed"))
        (done if ok else failed).append(moved)
        try:
            os.unlink(reported_file(aid))
        except OSError:
            pass
    return done, failed


def promote(cap_=None):
    """Start pending tasks while there is room. Returns what was started.

    Run at the top of every board-watch tick, beside `reconcile()` and
    `sweep()` — same shape, same guarantee: a task cannot sit queued for longer
    than one timer interval once a slot exists.
    """
    started = []
    limit = cap() if cap_ is None else cap_
    for rec in pending():
        if len(live_workers()) >= limit:
            break
        moved = ba._move(rec, work_dir("taken"))
        moved.update(_spawn_worker(moved))
        started.append(moved)
    return started


# ------------------------------------------------------------ what he sees
def groups(agents=None, pend=None):
    """The agent cards, in phase sections, in the order work moves through them.

    Empty phases are NOT returned — §5.2, dead space is a defect, and a column
    of empty headings would be this app inventing structure the machine does not
    have. Nothing here is a count, an age or an ordering by urgency: within a
    phase the order is `boardagents.agents()`' own stable one.
    """
    rows = ba.agents() if agents is None else agents
    pend = pending() if pend is None else pend
    buckets = {p: [] for p in PHASES}
    for a in rows:
        # LIVENESS DECIDES FIRST, and the OBSERVATION decides second. Neither is
        # the claim. A dead agent's last words — its own or its transcript's —
        # do not keep its card in `coding`: `boardmove._alive` already put it in
        # `exited`, and this is where that becomes what he reads.
        if a["state"] == "exited":
            buckets["stopped"].append(a)
        elif a.get("phase") in bph.CLAIMABLE:
            buckets[a["phase"]].append(a)
        else:
            buckets["unreported"].append(a)
    for t in pend:
        buckets["queued"].append({
            "id": "", "kind": "pending", "title": t.get("task", ""),
            "where": t.get("where", ""), "state": "queued", "running": False,
            "phase": "queued", "says": "", "unread": 0, "waiting": [],
            # A task with no process has nothing to observe and says so, rather
            # than borrowing the sentence a running card would use.
            "actually": "not started - a worker starts when a slot frees",
            "detail": "not started - a worker starts when a slot frees"})
    return [{"phase": p, "label": PHASE_LABELS[p], "rows": buckets[p]}
            for p in PHASES if buckets[p]]


# ------------------------------------------- telling board-watch about a question
def watch_state_path():
    """board-watch's own state file. Same env override it reads."""
    state = os.environ.get(
        "BOARD_WATCH_STATE",
        os.path.join(os.path.expanduser("~"), ".local", "state", "board-watch"))
    return os.path.join(state, "state.json")


def seed_watch_state(key):
    """Record a brand-new, UNANSWERED question in board-watch's fingerprints.

    This module is the one thing outside board-watch that writes that file, and
    it has to be. board-watch deliberately does not fire on a decision key it
    has never seen before — an item that arrives already answered was written
    that way by an agent, not answered by him. But a question an agent asks is
    born unanswered, and if he answers it BEFORE the next tick records it, the
    tick sees an unknown key that is answered and files it under exactly that
    rule: recorded, never worked. Measured, not reasoned about — it is a five
    minute window that opens every single time an agent asks something while a
    tick holds the lock.

    So the asker seeds the key with its empty fingerprint at the instant it
    writes it, and his answer is then an ordinary change to a known decision.
    Best effort: a board-watch that has never run has no state to seed, and the
    question is simply recorded by its own first run instead.
    """
    path = watch_state_path()
    try:
        with open(path) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return False
    if not isinstance(d, dict) or not isinstance(d.get("answers"), dict):
        return False
    if not d["answers"] or key in d["answers"]:
        return False                 # first run pending, or already known
    d["answers"][key] = "idx:|ans:"  # `fingerprint()` of an unanswered item
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(d, f, indent=1, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError:
        return False
    return True
