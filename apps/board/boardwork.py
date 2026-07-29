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

NO TIME PRESSURE. Nothing here hands the UI an elapsed time, an age, a count or
an ordering by urgency. `at` stamps exist so `promote()` can take the oldest
pending task first; they never reach the screen. Same rule as the rest of the
app, and it is the app's founding requirement.
"""
import json
import os
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
#: The rules every agent this system spawns runs under. They are HIS decisions,
#: already settled (see `home/srvs/board-watch-files/board-watch.py`), and the
#: two new prompts below quote them verbatim rather than paraphrasing: a worker
#: that rebuilds his machine while he is looking at something else is the one
#: failure this whole feature must not have.
RULES = """1. **NEVER rebuild and never change the running machine.** No `sudo \
rebuild-top`, `nixos-rebuild`, `hyprctl`, `qs ipc`, `systemctl`, `loginctl`. \
`apps/` runs live source, so a `.py`/`.qml` change is picked up when he next \
relaunches. If the work cannot land without a rebuild or a reload: **stop, \
leave that part undone**, and say so on the board.
2. **Never open a window on his screen and never drive his running apps.** \
Offscreen harnesses (`QT_QPA_PLATFORM=offscreen`) and `tools/sandbox.sh` only; \
he does every visual check himself.
3. **The git index here is SHARED** with him and with the other agents running \
right now. `git commit -m "msg" -- <explicit> <paths>`, always. `git add -N` \
for new files. Never a bare `git commit`, never `-a`, never a destructive or \
reverting git command (`reset --hard`, `checkout --`, `restore`, `stash`, \
`clean`).
4. **Push to `main`** when it works. No branch, no PR.
5. Read `AGENTS.md` at the repo root, then the nested one closest to what you \
are editing, then `docs/DESIGN.md` if you put pixels on a screen. They outrank \
your instincts about this codebase."""

WORKER_PROMPT = """You are running headless, with no human watching, on the \
machine `top` (x86_64 NixOS, flake attribute `top`). Work in `{repo}`.

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
the machine `top` (x86_64 NixOS, flake attribute `top`). Work in `{repo}`.

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

Finish by leaving one `note` saying what you dispatched and what you asked, so \
he can see what you did with his sentence without reading a log. Then stop.
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


def _spawn_worker(rec):
    """Start a worker DETACHED and register it. Returns {id, pid, session}.

    Detached on purpose: the orchestrator that calls this is itself running
    inside a board-watch tick, and a tick that waits on four 45-minute workers
    would hold board-watch's flock for the rest of the day — nothing else could
    fire, including the decision he answers in the meantime. So a worker is its
    own session, reparented to init, and the ONLY things that know it is alive
    are its registration and `boardmove._alive`. That is also why a worker can
    outlive the tick that started it and still draw a card.

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
        repo=REPO, task=rec["task"], rules=RULES,
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
    try:
        log = open(_log_path(aid), "ab", buffering=0)
    except OSError:
        log = subprocess.DEVNULL
    try:
        p = subprocess.Popen(cmd, cwd=REPO, env=env, stdin=subprocess.DEVNULL,
                             stdout=log, stderr=subprocess.STDOUT,
                             start_new_session=True)
    except OSError as e:
        return {"id": aid, "pid": 0, "state": "failed", "why": str(e)}
    finally:
        if log is not subprocess.DEVNULL:
            log.close()
    ba.register(aid, rec["task"][:70], p.pid, kind="worker",
                where=rec.get("where") or "", session=session)
    return {"id": aid, "pid": p.pid, "session": session, "state": "running"}


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
