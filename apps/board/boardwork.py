"""The fan-out: one sentence he typed -> an orchestrator -> several workers.

He asked for this in one sentence: *"a single box that i could type things into,
press enter, and have them sent to an inbox. then an agent figures out what
agents to assign to what (like how you used to orchestrate) and as agents
spawned, theyd show up as a little visual box that indicated what they were
doing, and each agent would be placed in sections based on what they were doing;
planning, researching, coding, testing, finishing touches"*. (Those five are
still what the CLASSIFIER reads out of a transcript; what an agent may SAY of
itself is any single word — `boardphase.clean_phase_word`.)

`boardagents.py` already owned the INBOX half of that — the box, the three
directories, and the argument that nothing he types can be lost. This module
owns what happens after: who gets spawned, how many at once, what a card is
allowed to claim about them, and where the ones above the cap wait.

A CARD CARRIES TWO STATEMENTS, AND NEITHER IS THE OTHER
-------------------------------------------------------
What an agent SAYS it is doing, and what it is OBSERVED doing, are both drawn —
his call, in one sentence: *"i want both"*. `boardphase.py` owns the whole of
that and its docstring is the authority; what matters here is which one this
module builds the OBSERVED sentence from. **It is the observed one, always.** A
phase is derived from the tool calls in the agent's live transcript and cannot
be set by the agent; the claim is drawn on the line above it and never
promoted. A card saying it is `testing` while its transcript reads `coding` is
this system working, not failing.

The cards are drawn as ONE FLAT LIST, oldest first — `cards()`. The phase
headings his first sentence asked for are gone, at his second: a card that
jumped between sections as the agent picked up a different tool was harder to
read than no grouping at all.

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
that only takes effect after a rebuild, and at the time this system was not
allowed to run one at all):

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
an ordering by urgency. Same rule as the rest of the app, and it is the app's
founding requirement.

**The ONE exception is the working duration on an agent card, and it is his.**
A card first drew when its agent was spawned (an absolute `10:26 am`), then he
asked for the opposite the same day, 2026-07-29: show *"how long the agent has
been working"* — `boardphase.worked_line`, `4 minutes`, live. An
elapsed time, granted deliberately by the person the no-pressure rule
protects, because a running agent's clock counts against the AGENT and not
against him. It is scoped to exactly that: nothing else here may count —
`placed`, LANDED's `when`, the queue and the quiet threshold stay absolute or
stay words, and nothing may cite this exception as precedent for a second one.
"""
import json
import os
import re
import shutil
import signal
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

#: The memory floor under which `promote()` will NOT start another worker, in
#: MiB of MemAvailable. The cap counts heads; this counts what a head COSTS.
#: Measured on book 2026-08-02 (7.3 GB): five workers plus the orchestrator,
#: goetia, Hyprland and the panel OOM-killed the user slice — every worker
#: SIGKILLed mid-task, and the panel's whole cgroup with them before
#: `OOMPolicy=continue`. A Claude minister peaks near 2.8 GB, a deepseek
#: (hermes) one near 350 MB, and neither knows which it is until it grows — so
#: the floor leaves room for the desktop plus one more worker rather than
#: trying to price the spawn. Under it the task stays QUEUED, the same "a slot
#: frees" semantic it already has, and the next tick retries. `0` disables.
MEM_MIN_AVAILABLE_MB = int(os.environ.get("BOARD_MEM_MIN_MB", "1536"))


def memory_available_mb():
    """MemAvailable from /proc/meminfo, in MiB; `None` when it cannot be read,
    which must NEVER close the gate — a missing /proc is not a reason to stop
    spawning on a machine that was fine before the file vanished."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None

#: What the dropdown beside the model chooser OFFERS, in the order it draws
#: them. [his, 2026-07-29] *"between the model selector and the indicators, add
#: another drop down for the max number of agents available."*
#:
#: It lives here for the reason `ORCH_MODELS` does: `set_cap()` is the one
#: store, and a range written into the QML would be a second answer to "what
#: may he pick". It is not a ceiling — `boardctl.py cap <n>` still takes any
#: number ≥ 1, the way every typed selector here is more forgiving than the
#: control (`resolve_model`); this is the range a CONTROL can honestly offer on
#: a 16-thread desktop with one shared git index. A value of his that is off
#: the list is still drawn and still ticked as current, so the control cannot
#: disagree with the store.
CAP_CHOICES = [1, 2, 3, 4, 5, 6, 7, 8]

#: How many SUMMONERS may plan at once when nothing says otherwise. One, which
#: is what this system did before the control existed: a tick drained everything
#: he had typed into a single orchestrator prompt, so adding the dropdown moved
#: no behaviour on its own.
DEFAULT_SUMMONERS = 1

#: What the top dropdown offers. Small on purpose and for a different reason
#: than `CAP_CHOICES`: a summoner run is WAITED ON by the tick that started it
#: (`board-watch.work_the_queue`), so every one of them is a claude session held
#: open for up to `BOARD_ORCH_TIMEOUT` while the board's flock is held. Four is
#: as far as that is honest. Not a ceiling — `boardctl.py summoners <n>` takes
#: any n >= 1, the way every typed selector here is more forgiving than the
#: drawn one, and a value of his that is off the list is drawn and ticked rather
#: than hidden.
SUMMONER_CHOICES = [1, 2, 3, 4]

#: A worker is capped like a decision agent is — the same 45 minutes, so one
#: wedged run cannot hold a slot for the rest of the day.
WORKER_TIMEOUT_S = int(os.environ.get("BOARD_WORK_TIMEOUT", "2700"))

# The phases, in the order work moves through them, and the exact words for
# them. They no longer head sections on his board — `cards()` says why — and
# are `boardctl.py agents`' listing plus the vocabulary the observed sentence
# is built from. His five, plus three states that are REAL and must not be
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


# ------------------------------------------------------- how many summoners
#: [his, 2026-07-29] four dropdowns at the top of the window, in his order:
#: *"1. number of summoners 2. summoner model 3. number of ministers 4. minister
#: model"*. This is the first of them, and it is the only one of the four that
#: had no store at all before.
#:
#: What it MEANS, because a count is only honest if it names something real: it
#: is how many ways a tick's drained queue may be SPLIT
#: (`board-watch.work_the_queue` → `split_for_summoners`), each group getting its
#: own Solomon. At the default of 1 — and that is the default — a tick is always
#: one summoner however many sentences it drained, which is the behaviour that
#: predates this control. Raising it is the deliberate act of asking for several
#: concurrent fable-5 planners. [his, 2026-08-01, of a tick that ran three at
#: once: *"why the fuck are you running multiple solomons?????"* — so the number
#: he sets is the only thing that puts more than one up.]
def summoners_file():
    return os.path.join(_root(), "summoners")


def summoners():
    env = os.environ.get("BOARD_MAX_SUMMONERS")
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    try:
        with open(summoners_file()) as f:
            return max(1, int(f.read().strip()))
    except (OSError, ValueError):
        return DEFAULT_SUMMONERS


def set_summoners(n):
    n = max(1, int(n))
    os.makedirs(_root(), exist_ok=True)
    tmp = summoners_file() + ".tmp"
    with open(tmp, "w") as f:
        f.write("%d\n" % n)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, summoners_file())
    return n


def split_for_summoners(items, n=None):
    """`items` in at most `n` contiguous groups, longest first, none empty.

    Contiguous rather than round-robin so two sentences he typed one after the
    other about the same thing stay in one summoner's prompt where a human would
    read them together. With `n == 1` this is `[items]` — the whole point, since
    that is the behaviour that predates the control.
    """
    items = list(items)
    n = max(1, int(summoners() if n is None else n))
    n = min(n, len(items)) or 1
    if not items:
        return []
    size, extra = divmod(len(items), n)
    out, i = [], 0
    for k in range(n):
        take = size + (1 if k < extra else 0)
        out.append(items[i:i + take])
        i += take
    return out


# ------------------------------------------ which model, and how hard, summons
#: The summoner (Solomon) chooser beside the box, in the order it draws them.
#: [his, 2026-07-29] *"add a drop down to the right of the top prompt box that
#: allows the user to select which model they wish the orchestrator to be."* —
#: and, its thinking budget too, added when he asked to choose *"the reasoning
#: effort of the summoner agents"*. So this carries EFFORT now, exactly as the
#: minister chooser below does, rather than the model alone: model and effort are
#: one pick here, one control, one label.
#:
#: `(flag, effort, label)`. The flag is what `--model` gets, the effort what
#: `--effort` gets, the label what he reads — lowercase like every other string
#: this desktop authors (docs/DESIGN.md §7.2). **Full names, not the
#: `opus`/`sonnet` aliases** — an alias means "the latest of that family" and
#: would silently re-point his choice the day a new one ships, which is exactly
#: the thing a chooser exists to stop.
#:
#: Unlike the minister list this is NOT a ceiling: the summoner's judgement is
#: the whole of its job and he asked to be able to buy as much of it as he likes,
#: so the higher efforts (`xhigh`, `max`) are offered on the reasoning models and
#: there is no clamp at the spawn. It is a curated spread rather than the full
#: model×effort cross product, for the reason `MINISTER_MODELS` is: a dropdown is
#: a short list of sensible pairs, and `boardctl.py model` takes any of them.
ORCH_MODELS = [
    ("claude-fable-5", "high", "fable 5 high"),
    ("claude-fable-5", "max", "fable 5 max"),
    ("claude-opus-5", "high", "opus 5 high"),
    ("claude-opus-5", "xhigh", "opus 5 xhigh"),
    ("claude-opus-5", "max", "opus 5 max"),
    ("claude-opus-4-8", "high", "opus 4.8 high"),
    ("claude-opus-4-8", "medium", "opus 4.8 medium"),
    ("claude-sonnet-5", "high", "sonnet 5 high"),
    ("claude-haiku-4-5-20251001", "medium", "haiku 4.5 medium"),
    ("deepseek/deepseek-v4-flash-0731", "medium", "deepseek v4 flash"),
    ("deepseek/deepseek-v4-pro", "medium", "deepseek v4 pro"),
    ("z-ai/glm-5.2", "medium", "glm 5.2"),
    ("moonshotai/kimi-k3", "medium", "kimi k3"),
]

#: What summons when he has never chosen. `(flag, effort)`, stated once:
#: `claude-fable-5` was the hardcoded model default and `high` the effort `ROLES`
#: pinned before this chooser carried effort, so drawing it moved no behaviour on
#: its own.
DEFAULT_ORCH = ("claude-fable-5", "high")


def orch_model_file():
    return os.path.join(_root(), "orch-model")


def orch_choices():
    return {(f, e) for f, e, _ in ORCH_MODELS}


def orch_label(pair=None):
    """The prose for a `(flag, effort)` pair — what the closed control reads and
    what the footer reports. Never the wire values (docs/DESIGN.md §2)."""
    flag, effort = pair or orch_model()
    for f, e, lab in ORCH_MODELS:
        if (f, e) == (flag, effort):
            return lab
    return "%s %s" % (flag, effort)


def orch_model():
    """`(flag, effort)` the NEXT orchestrator spawns with.

    Read at spawn time, never cached, which is the whole of his rule for a
    change made mid-run: *"if this changes in the middle of the orchestrator
    working, simply change it to the defined model on the next prompt it
    recieves."* A running session keeps what it started with — nothing can
    change that from outside — and the next prompt off the queue reads this file
    again. No signal to plumb, no restart, and nothing to reconcile.

    A file that is unreadable or does not hold one of `ORCH_MODELS` falls back to
    `DEFAULT_ORCH`, rather than passing an unknown string to `--model`/`--effort`
    where the failure would be a spawn that dies with a CLI usage error and a
    FAILED bullet he has to decode.
    """
    try:
        with open(orch_model_file()) as f:
            parts = f.read().split()
    except OSError:
        return DEFAULT_ORCH
    pair = (parts[0], parts[1]) if len(parts) >= 2 else None
    return pair if pair in orch_choices() else DEFAULT_ORCH


def resolve_model(name):
    """A `(flag, effort)` from what somebody typed. Exact label, exact
    `<flag> <effort>`, or one unambiguous case-insensitive substring of either —
    the same forgiveness `boardctl`'s selectors give for the same reason (the
    caller is a person at a terminal or a language model holding a half-remembered
    name), and the same refusal: ambiguity is an error, never a guess.
    """
    want = " ".join((name or "").split()).lower()
    if not want:
        raise ValueError("no model named")
    rows = [("%s %s" % (f, e), lab, (f, e)) for f, e, lab in ORCH_MODELS]
    for wire, lab, pair in rows:
        if want in (wire.lower(), lab.lower()):
            return pair
    hits = [(lab, pair) for wire, lab, pair in rows
            if want in wire.lower() or want in lab.lower()]
    if len(hits) == 1:
        return hits[0][1]
    if hits:
        raise ValueError("%r matches %s - be more specific"
                         % (name, ", ".join(lab for lab, _ in hits)))
    raise ValueError("not a summoner this board offers: %r (have: %s)"
                     % (name, ", ".join(lab for _, _, lab in ORCH_MODELS)))


def set_orch_model(name):
    """Choose it. Same atomic write as `set_cap`: this file is read by a spawner
    that may fire at any moment, so a half-written one must be impossible."""
    flag, effort = resolve_model(name)
    os.makedirs(_root(), exist_ok=True)
    tmp = orch_model_file() + ".tmp"
    with open(tmp, "w") as f:
        f.write("%s %s\n" % (flag, effort))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, orch_model_file())
    return (flag, effort)


# --------------------------------------------- what the MINISTERS run on
#: The fourth dropdown, and the one with a hard ceiling on it. [his, 2026-07-29]
#: *"do not allow ministers to be anything higher than opus 5 medium
#: thinking."* So this list is the WHOLE of what a minister may ever be, and it
#: is an ALLOWLIST rather than an ordering: "higher" needs no definition if the
#: only reachable values are the ones written here.
#:
#: `(flag, effort, label)`, ceiling FIRST because the ceiling is the hard cap
#: this list exists to state — but the ceiling is no longer the default. [his,
#: 2026-08-02] the minister DEFAULT is `deepseek v4 flash`, the LAST row and
#: `MINISTER_DEFAULT` below: an unnamed dispatch runs cheap and Solomon tiers UP
#: from there only for work that needs it (rubric in `ORCHESTRATOR_PROMPT`).
#: Between the two: the same models thinking less, then the smaller families.
#: Effort never exceeds `medium` for ANY of them, because his sentence caps the
#: thinking budget as well as the family and a bigger budget on a smaller model
#: is still a tier he did not offer.
MINISTER_MODELS = [
    ("claude-opus-5", "medium", "opus 5 medium"),
    ("claude-opus-5", "low", "opus 5 low"),
    ("claude-opus-4-8", "medium", "opus 4.8 medium"),
    ("claude-opus-4-8", "low", "opus 4.8 low"),
    ("claude-sonnet-5", "medium", "sonnet 5 medium"),
    ("claude-sonnet-5", "low", "sonnet 5 low"),
    ("claude-haiku-4-5-20251001", "medium", "haiku 4.5 medium"),
    ("claude-haiku-4-5-20251001", "low", "haiku 4.5 low"),
    ("moonshotai/kimi-k3", "medium", "kimi k3"),
    ("deepseek/deepseek-v4-pro", "medium", "deepseek v4 pro"),
    ("minimax/minimax-m3", "medium", "minimax m3"),
    ("deepseek/deepseek-v4-flash-0731", "medium", "deepseek v4 flash"),
]

#: The ceiling, named once — the hard cap [his, 2026-07-29], the first row of the
#: list above and the value a stale or out-of-range file clamps DOWN to.
MINISTER_CEILING = (MINISTER_MODELS[0][0], MINISTER_MODELS[0][1])

#: The default, named once — [his, 2026-08-02] the minister DEFAULT is deepseek
#: v4, the LAST row above and what an unnamed dispatch (and a never-chosen dial)
#: gets. Solomon tiers UP from here per piece of work; the ceiling is where that
#: tiering stops without asking him first (rubric in `ORCHESTRATOR_PROMPT`).
MINISTER_DEFAULT = (MINISTER_MODELS[-1][0], MINISTER_MODELS[-1][1])


def tier_label(flag, effort=""):
    """The human tier label for a spawn's `(flag, effort)` — *"sonnet 5 medium"*,
    *"deepseek v4 flash"* — from the chooser tables the rest of this file reads,
    MINISTER first then ORCH (the summoner-only tiers `fable`/`xhigh`/`max` live
    only there). `""` for a spawn that named no model. An unofferable pair (an
    old record, a hermes id) falls back to the wire values with the deepseek
    path prefix stripped — never the raw `deepseek/...-0731` flag, which is a
    wire value and not for reading (docs/DESIGN.md §2).
    """
    flag = (flag or "").strip()
    if not flag:
        return ""
    effort = (effort or "").strip()
    for f, e, lab in MINISTER_MODELS + ORCH_MODELS:
        if f == flag and (not effort or e == effort):
            return lab
    return ("%s %s" % (flag.split("/")[-1], effort)).strip()


def minister_choices():
    return {(f, e) for f, e, _ in MINISTER_MODELS}


def minister_file():
    return os.path.join(_root(), "minister-model")


def minister_label(pair=None):
    """The prose for a `(flag, effort)` pair — what the closed control reads and
    what the footer reports. Never the wire values (docs/DESIGN.md §2)."""
    flag, effort = pair or minister_model()
    for f, e, lab in MINISTER_MODELS:
        if (f, e) == (flag, effort):
            return lab
    return "%s %s" % (flag, effort)


def minister_model():
    """`(flag, effort)` the NEXT minister spawns with, never above the ceiling.

    Read at spawn time and cached nowhere, so his choice reaches the next
    dispatch and no running minister is re-pointed — the same mechanism
    `orch_model()` is, and for the same reason.

    A never-chosen dial is `MINISTER_DEFAULT` — [his, 2026-08-02] the minister
    DEFAULT is deepseek v4, so an unnamed dispatch runs cheap and Solomon tiers
    UP from there. A value the file DOES hold that is not one of `MINISTER_MODELS`
    — stale, hand edited, or written by a version that offered more — clamps to
    the CEILING, not the file's value and not a spawn that dies on a CLI usage
    error: a chosen-but-unofferable value is the one place the hard cap, not the
    cheap default, is the safe fallback.
    """
    try:
        with open(minister_file()) as f:
            parts = f.read().split()
    except OSError:
        return MINISTER_DEFAULT
    pair = (parts[0], parts[1]) if len(parts) >= 2 else None
    return pair if pair in minister_choices() else MINISTER_CEILING


def resolve_minister(name):
    """A `(flag, effort)` from what somebody typed. Exact label, exact
    `<flag> <effort>`, or one unambiguous case-insensitive substring of either —
    `resolve_model`'s forgiveness, and its refusal: ambiguity is an error.

    A model this board offers a SUMMONER but not a minister (`fable 5`) is
    refused here with the reason, rather than silently becoming the ceiling: a
    typed selector that quietly does something else is worse than one that says
    no.
    """
    want = " ".join((name or "").split()).lower()
    if not want:
        raise ValueError("no minister model named")
    rows = [("%s %s" % (f, e), lab, (f, e)) for f, e, lab in MINISTER_MODELS]
    for wire, lab, pair in rows:
        if want in (wire.lower(), lab.lower()):
            return pair
    hits = [(lab, pair) for wire, lab, pair in rows
            if want in wire.lower() or want in lab.lower()]
    if len(hits) == 1:
        return hits[0][1]
    if hits:
        raise ValueError("%r matches %s - be more specific"
                         % (name, ", ".join(lab for lab, _ in hits)))
    raise ValueError("not a minister this board may run: %r - the ceiling is %s "
                     "and the choices are: %s"
                     % (name, minister_label(MINISTER_CEILING),
                        ", ".join(lab for _, _, lab in MINISTER_MODELS)))


def minister_tier(name=None):
    """The `(flag, effort)` ONE dispatch really runs on — his dial when it names
    nothing, and never anything the dial itself could not be set to.

    This is the per-task half of tiering the spend: the summoner dropdown tiers
    the PLANNER (~9% of the spend) and until now every minister — the
    43% — read one global dial, so a doc edit and a compositor C++ change
    spawned on the same model. `dispatch(model=…)` names a tier per piece of
    work, because the planner has just written the task sentence and the
    `--where` glob and is the only thing that knows what the piece IS.

    **His dial is the DEFAULT a dispatch tiers UP from**, not a ceiling: [his,
    2026-08-02] the dial defaults to deepseek v4, an unnamed dispatch gets it,
    and Solomon names a higher `--model` only for work that needs one — up to the
    opus 4.8 medium the rubric stops at without asking him first.

    **An unresolvable tier falls back to his dial, never to an invented one.**
    `resolve_minister` refuses what it cannot name unambiguously and this
    swallows that refusal upward to `minister_model()` — his configured default
    (deepseek v4 unless he has raised the dial), not a tier nobody chose. The
    clamp in `role_flags` still runs last and independently, so no route here can
    spawn a minister above the ceiling either.
    """
    if not (name or "").strip():
        return minister_model()
    try:
        return resolve_minister(name)
    except ValueError:
        return minister_model()


def set_minister_model(name):
    """Choose it. Same atomic write as `set_cap`, because a dispatch may fire at
    any moment and a half-written file must be impossible."""
    flag, effort = resolve_minister(name)
    os.makedirs(_root(), exist_ok=True)
    tmp = minister_file() + ".tmp"
    with open(tmp, "w") as f:
        f.write("%s %s\n" % (flag, effort))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, minister_file())
    return (flag, effort)


# -------------------------------------------------------------- the RELAY
#: How many turns one minister takes before it hands the rest to a fresh one.
#:
#: **A session's cost is quadratic in its turns** — everything already said is
#: re-read on every turn after it — and measured on `top` (2026-08-01, over the
#: week) a minister averaged 118 turns while cache-read per turn climbed from
#: 42k at 22 turns to 151k at 163. `WORKER_TIMEOUT_S` bounds the wall-clock and
#: nothing bounded the turns; "dispatch smaller" was doctrine in `RULES` and
#: unenforced. Three 100-turn hops cost about a third of one 300-turn session.
RELAY_TURNS = int(os.environ.get("BOARD_WORK_TURNS", "60"))

#: ...and how many hops one piece of work may take before it must report what
#: is left instead. A relay is a legitimate reason for a task to run twice —
#: `retried` is the other, and the two marks stay distinct because the CAUSES
#: are (a budget reached vs a platform death) and `reap()` reads them
#: differently. This is the backstop against a task that relays forever.
RELAY_MAX = int(os.environ.get("BOARD_WORK_RELAY_MAX", "4"))


def turns_used(session=None):
    """How many turns this minister has taken, or None if it cannot be known.

    Counted from the agent's OWN transcript — the file `boardphase` already
    tails to draw the observed line on its card — so nothing new is written and
    no runtime is asked to account for itself. None is the honest answer for a
    hermes minister (its run lives in hermes's store, not a `.jsonl` here) and
    for a transcript that has not appeared yet; `boardctl turns` says so rather
    than inventing a number, and a budget that cannot be read is not enforced.
    """
    session = session or os.environ.get("BOARD_WORK_SESSION") or ""
    path = bph.transcript(session)
    if not path:
        return None
    n = 0
    try:
        with open(path, "rb") as f:
            for line in f:
                if b'"type":"assistant"' in line:
                    n += 1
    except OSError:
        return None
    return n


def relay_state(session=None):
    """`(used, budget, depth, may_relay)` for the running minister.

    `used` is None when the transcript cannot be read (see `turns_used`), and
    then `may_relay` is False: an unknown count never triggers a hop, because
    relaying work that has barely started costs a whole startup context to
    save nothing.
    """
    used = turns_used(session)
    budget = int(os.environ.get("BOARD_WORK_TURNS") or RELAY_TURNS)
    depth = int(os.environ.get("BOARD_WORK_RELAY") or 0)
    may = used is not None and used >= budget and depth + 1 <= RELAY_MAX
    return used, budget, depth, may


def relay(brief, agent_id=None, where=None, model=None):
    """Hand what is LEFT of this task to a fresh minister. Returns the new
    record, or None with a reason on `ValueError`.

    **A relay is not a kill, and that is the whole design.** `--max-turns`
    would cut the session mid-edit and leave the tree half-written, and to
    `reap()` it would look exactly like a crash — filed `failed`, with a
    `FAILED:` bullet on his board for work that was going fine. Here the
    ENDING IS VOLUNTARY AND ACCOUNTED FOR: the successor is written to
    `pending/` before the minister exits, the hop is stamped `mark_reported`
    so `reap()` files the finished one under `done/`, and `promote()` starts
    the successor on the next tick exactly as it starts anything else that was
    over the cap.

    The successor inherits the tier, the `--where` and the depth+1. It does NOT
    inherit the original task text alone: `brief` is what the minister knows
    now and the next one would otherwise rediscover, and it is the reason one
    hop costs a brief rather than a re-run.
    """
    brief = " ".join((brief or "").split())
    if not brief:
        raise ValueError("a relay needs the brief - what is done, what is "
                         "left, and what you learned")
    aid = ba.clean_id(agent_id or os.environ.get("BOARD_AGENT_ID") or "")
    depth = int(os.environ.get("BOARD_WORK_RELAY") or 0)
    if depth + 1 > RELAY_MAX:
        raise ValueError("this task has already relayed %d times (the limit) - "
                         "report what is left as PARTIAL: instead" % depth)
    task = os.environ.get("BOARD_WORK_TASK") or ""
    rec = {"task": " ".join(("%s\n\nPICKING UP WHERE THE LAST MINISTER LEFT "
                             "OFF: %s" % (task, brief)).split()),
           "phase": "", "where": (where if where is not None
                                  else os.environ.get("BOARD_WORK_WHERE") or ""),
           "context": "", "relay": depth + 1, "relayFrom": aid,
           "turns": int(os.environ.get("BOARD_WORK_TURNS") or RELAY_TURNS),
           "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "sent": time.time(),
           "host": os.uname().nodename,
           "order": os.environ.get("BOARD_ORDER") or ""}
    flag, effort = minister_tier(model or " ".join(
        x for x in (os.environ.get("BOARD_WORK_MODEL") or "",
                    os.environ.get("BOARD_WORK_EFFORT") or "") if x))
    rec["model"], rec["effort"] = flag, effort
    path = os.path.join(work_dir("pending"), _task_name())
    ba._write_json(path, rec)
    rec["file"] = path
    rec["state"] = "queued"
    # The hop IS this minister's report. Without it `reap()` finds a worker
    # that recorded nothing, files it `failed` and writes a `FAILED:` bullet
    # for work that is in hand and queued — the exact confident lie the rest of
    # this module is built to refuse.
    mark_reported(aid, "relayed to a fresh minister: %s" % brief[:120])
    return rec


def relay_block(budget, depth):
    """Rule 14 as the worker sees it, or nothing at all.

    A budget of zero (or a task already at `RELAY_MAX`) prints NOTHING rather
    than a rule saying "you may not relay": a minister that cannot hop does not
    need to know the mechanism exists, and every line in that prompt is re-read
    on every turn of the session it is telling to be short.
    """
    if budget <= 0 or depth + 1 > RELAY_MAX:
        return ""
    return RELAY_RULE.format(budget=budget, hop=depth + 1, most=RELAY_MAX)


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
    "top": "x86_64 NixOS, flake attribute `top`. The rebuild here is "
           "`./tools/preflight.sh` then `sudo rebuild-top` (passwordless, no "
           "tty needed)",
    "book": "an aarch64 MacBook Air running Fedora Asahi with home-manager "
            "layered on top, flake attribute `air`. It is NOT NixOS: there is "
            "no `rebuild-top` and no `sys/` here, and the rebuild is "
            "`home-manager switch --flake ~/nix#air`, no root needed",
}


def host_line():
    """``top` (x86_64 NixOS, ...)`, for the top of every prompt."""
    return "`%s` (%s)" % (HOST, _HOSTS.get(
        HOST, "a machine this system has no description for - read "
              "`~/nix/AGENTS.md` before running anything that changes it"))


#: The rules every agent this system spawns runs under. They are HIS decisions,
#: already settled (see `home/srvs/board-watch-files/board-watch.py`), and every
#: spawner appends them VERBATIM to the system prompt (`--append-system-prompt`)
#: via `AgentBackend.system_blocks`, rather than paraphrasing — a constant block
#: appended to the identical cached system prompt, so RULES is a cache read (see
#: `docs/agents/minister-context.md`). This block is never interpolated into a
#: prompt body; the prompts point at it.
#:
#: Rule 1 was the reverse of this until 2026-07-29 — no rebuild, ever, work left
#: undone with a note. He lifted it himself, in these words: *"it should be any
#: time but should still adhere to the rule that's written down SOMEWHERE"*. So
#: the rule is no longer stated here: `~/nix/AGENTS.md` -> "When it is okay to
#: rebuild or hot-reload" is the single copy, and this points at it. A fifth
#: paraphrase in a prompt is how it came to be true nowhere.
RULES = """1. **You MAY rebuild and reload, at your own judgement, at any \
hour** — he is usually at the machine and decided this deliberately. It is \
standing behaviour, not something to ask about: a change here is done when it \
is APPLIED, not when it is pushed. **Read `AGENTS.md` -> "When it is okay to \
rebuild or hot-reload" before you run one** and stay inside it — preflight \
first, nothing staged across it, cheap reloads freely, the `hyprvtb` live \
hot-swap only on `top` (never `hyprctl plugin load`/`unload`, on either \
machine), and the Ask-first list still his. **Serialize the switch itself**: \
other agents rebuild too, and two at once must not race — use the host's own \
wrapper (`sudo rebuild-top` on top, `rebuild-air` on book), which takes the \
shared rebuild lock and runs preflight itself; only a RAW switch run outside \
the wrappers still needs the manual `mkdir -p /tmp/claude-1000/-home-lam-nix \
&& flock /tmp/claude-1000/-home-lam-nix/rebuild.lock <the rebuild command>`. **Getting an edit LIVE has a \
per-area ritual**: a seed-once file (`Theme.qml`, `hyprland.lua`) is edited in \
BOTH copies — nix source AND the live file — with `./tools/seed-drift.sh` run \
before and after (editing one side is the single most common way a change here \
appears to do nothing); panel QML goes live by rebuilding, then appending a \
comment line to `~/.config/quickshell/Theme.qml` and restoring the file; \
`hyprland.lua` needs `hyprctl reload`; hyprvtb C++ needs its `main.cpp` version \
bump, then rebuild + `hyprctl reload`. Never run bare `qs` — it launches a \
second panel — and never script hyprvtb Lua actions (`rollup`, \
`minimize_active`, ...) to probe behaviour: `hl.dsp.focuswindow` is nil, so \
they land on HIS active window. `apps/` is live source and needs \
none of this — a `.py`/`.qml` change there is picked up when he next relaunches. \
Whatever you do or deliberately do not, **say so in your note**; if you leave a \
rebuild pending, say why.
2. **Never open a window on his screen and never drive his running apps** — no \
screenshots, no GUI, no MPRIS, no launching a packaged app "just to check". \
Offscreen harnesses (`QT_QPA_PLATFORM=offscreen`) and `tools/sandbox.sh` only; \
he does every visual check himself. Your EVIDENCE is IPC, logs and traces, so \
verify with them rather than implying it works: `qs log | tail` (CUMULATIVE — \
snapshot the line count before your change), `qs ipc call view geom` / `state \
carried` / `wallpaper status`, `hyprctl clients|layers|plugin \
list|configerrors`, `./tools/seed-drift.sh`. And a `home/` change is for BOTH \
machines: say in your note what the other host must run (`sudo rebuild-top` on \
top / `home-manager switch --flake ~/nix#air` on book) and look at the branch \
you are not on — an x86-only package left ungated, or a path that exists on \
only one host, fails SILENTLY on the other.
3. **The git index here is SHARED** with him and with the other agents running \
right now. `git commit -m "msg" -- <explicit> <paths>`, always. `git add -N` a \
NEW file the moment you create it, before any rebuild — flake eval reads the \
working tree but does NOT see an untracked file, so the rebuild "succeeds" and \
the panel then throws `ReferenceError` at runtime. \
Never a bare `git commit`, never `-a`, never a destructive or \
reverting git command (`reset --hard`, `checkout --`, `restore`, `stash`, \
`clean`). **A pathspec is not enough when somebody else holds the same file**: \
`git commit -- x.py` takes the WORKING TREE copy of it, their half-finished \
edits and debug probes included. `git diff` what you are about to commit and \
confirm every hunk is yours; if it is not, narrow the pathspec or leave that \
file alone. And commit against HEAD as it is NOW, never a copy of the tree you \
read an hour ago — a stale pathspec silently reverts whatever landed while you \
worked, and has. **Strip your own instrumentation** — `console.warn` probes, \
temporary properties, debug files — before committing, and end every commit \
message with your `Co-Authored-By: Claude ... <noreply@anthropic.com>` trailer.
4. **Push to `main`** when it works. No branch, no PR — and **`git pull \
--rebase` immediately before you push.** This system now runs on BOTH of his \
machines, so another agent on the other host may have pushed since you started; \
a rejected push is normal and the answer is `git pull --rebase` and push again, \
never `--force` and never giving up. `~/nix` (public) and `docs/` (private, its \
own repo inside this checkout) are SEPARATE repos: pull and push each from its \
own directory.
5. Read `AGENTS.md` at the repo root, then the nested one closest to what you \
are editing, then `docs/DESIGN.md` if you put pixels on a screen. They outrank \
your instincts about this codebase — and when your change makes one of them \
wrong, UPDATE it in the same pass.
6. **Find things out cheaply: read before you measure, and read in SLICES.** \
`docs/HARDWARE.md` is the \
one reference for what these two machines physically are — cores, RAM, both \
GPUs, the sensor chip and the real fan layout, the disks, the display — and \
every fact in it names the command that established it; read it BEFORE you go \
measuring the metal, and add what you find that is not in it. `docs/DESIGN.md` \
is ~2,300 lines: read its Contents table and then the two or three sections \
your change actually touches, never the whole file, and grep a long \
`AGENTS.md` to the section rather than swallowing it — a nested guide is an \
index plus parts when it is big (`apps/board/AGENTS.md` -> `guide/*.md`), so \
open the part, not the set. **And a file you have already read is still in \
front of you**: re-read only the lines you changed, with `offset`/`limit`, \
never the whole file again. Budget your context \
deliberately — an agent that runs out mid-task leaves the tree half-edited, \
which here is worse than a slow one. And **never run `sudo -A` merely to prove \
that something works**: every one of those puts a real password dialog in front \
of him and asks for his root password while he is doing something else. One \
agent checking the askpass path that way burned three failed attempts of his. \
Use it when the task genuinely needs root, and verify that path offscreen \
(`apps/askpass/tools/askpass-selftest.py`) instead.
7. **A real bug next to your work is yours to DEAL WITH, not just to report.** \
He has standing approval for this: a setting that has silently never applied, a \
poisoned diagnostic channel, a binding loop, a control that does nothing. Do \
not ask him first. Dealing with it means FIXING it if you are the one doing the \
work — its own commit, its own pathspec — or dispatching it if you are the one \
who hands work out. Judgement, not licence: only if you can establish the cause \
and verify the fix as rigorously as your own task, and never if it turns into a \
re-architecture, lands in his Ask-first list, or would swallow the job you were \
actually given. Then say what you found, fixed or left.
8. **Write board text TO the person at the machine** — every bullet, note, \
question, option and `--if-unanswered` line you emit is read by him, so \
address them as "you", never "he" or "him". Internal prose — this prompt, \
your comments, commit messages — stays third person; only what lands on the \
board says "you"."""

WORKER_PROMPT = """You are running headless, with no human watching, on the \
machine {host}. Work in `{repo}`.

**You are {name}.** That is the name on your card on his board and the name the \
orchestrator used when it wrote down who was handed what, so it is the name he \
will use if he types something at you. Your id is `{aid}`; it is what your \
systemd unit, your log and your inbox are keyed on, and it is what the tools \
below want when one asks for an agent id.

An orchestrator, Solomon, split up something he asked for and bound you to one
piece of it. This is your whole job; another minister has the rest, and may be
editing other files in this same checkout right now.

When it is done you record it, and you are then at liberty to depart.

--- your task ---
{task}
--- end ---

{context}
RULES are in force for this session and not negotiable — the block is in your
system prompt.

9. **Say what you are working on.** He is looking at a card for this agent, and \
it shows two lines: what you SAY you are doing, and what you are OBSERVED doing \
(read from your own transcript — every tool call you make). From `{repo}`, at \
the start and whenever you move on:

       python3 apps/board/tools/boardctl.py phase researching --doing '<one \
short line, present tense, naming the THING>'

   **Pick the single word that best names what you are doing.** These are the \
ones worth reaching for first:

{phase_words}

   It is a MENU, not a whitelist: any other single word is accepted too, so \
long as it is one word, letters only, and TRUE of what you are actually doing. \
**Your words do not set the phase the card is filed under** — that is derived \
from what you actually do, and you cannot change it from here. Say it anyway: \
it is the only channel that carries WHAT you are working on rather than which \
verb you last used, and he reads the two side by side deliberately. Being \
honest costs you nothing; a claim that does not match your tool calls is \
visible to him and is not hidden.

10. **ONE BOARD ITEM PER ASK, and record each one AS IT FINISHES.** [his, \
2026-07-29] Two halves of one rule, and both are his.

   **Separated.** Every distinct thing you were asked is its own `note` call \
and its own bullet — never several folded into one message, not in the \
headline, not in the elaboration under it, not even when they all finish in the \
same minute. **Replying to a bullet CLEARS that bullet**, so an ask folded into \
another one is cleared by a reply that was never about it and survives nowhere \
he can see: a worker handed four asks wrote one bullet whose headline named the \
first, and asks 2-4 went with his reply to it. The tool enforces what it can \
reach — a second tag on a line, a second `**headline**`, a tagged or bulleted \
line in the elaboration, a phrase counting other work are all refused — and \
the rest is on you. Several tagged strings in one `note` call, or several \
unindented lines, land as several bullets, each with its own stamp, each \
clearable on its own.

   **As it finishes.** *"the board does not update as each task completes"* — \
so call `note` for a piece the moment that piece is done and pushed, rather \
than saving one report for the end. Each call is its own line edit under the \
lock and takes effect immediately; there is nothing to batch and nothing that \
batches for you. (LANDED needs no help here at all — it is read straight from \
the commit log, so a commit is on his board as soon as it is pushed, whether or \
not you get to `land`.)

   **Record it with the tool, never by hand.** If you COMMITTED anything, every \
commit gets a line in LANDED, one call each, and the right moment for that call \
is right after the push:

       python3 apps/board/tools/boardctl.py land --commit <hash> --what \
'<one line, imperative, like the commit subject>'

   That is what the LANDED section is: what actually reached his machine. It \
takes no selector — `land` simply records the commit, and reads its time out of \
git itself.

   **THE FINISH MESSAGE LANDS WITH THE PUSH, NOT AT THE END OF THE SESSION.** \
The whole reason this rule exists is the board not updating as each task \
completes, and the way that keeps happening is the finish message arriving long \
after the commits it describes: the code is committed and pushed, then a long \
tail of verification, a doc, a final review — and only then the `note`. So the \
order is: commit, push, `land`/`note` AT THAT MOMENT, then whatever teardown \
you still want. Post-push verification and docs are fine to keep doing, but the \
finish message is on his board seconds after the push, not minutes later.

   Then, commits or none, one line saying where it ended up:

       python3 apps/board/tools/boardctl.py note '<TAG>: **<what you were \
asked>** - <what you did, what you did not, and whether a rebuild is now \
pending and why>'

   ...one call per ask, never one call describing several. **It starts with a \
TAG, then a summary of AT MOST about a dozen words on that same first line — \
the tool refuses a longer one, and an untagged one** — that is his rule for \
this list, twice now: the prompts said "a SHORT description" and he came back \
with "still too long", so the length is mechanical. **Every elaboration or \
background goes on INDENTED continuation lines under the summary, and it is a \
sentence or two, not a paragraph** — *"it shouldnt really elaborate that much \
though"*. Pick the one that is true:
`ENACTED:` it is done and on his machine; `PARTIAL:` some of it landed and \
some did not, a rebuild being pending counts; `FAILED:` nothing landed; \
`INFORMATION:` a fact, nothing asked of him. **A question is NEVER a note \
bullet** — the ONLY place a question to him belongs is the decisions section, \
written with `boardctl.py ask '<the question>' --option '<a way>' \
--if-unanswered '<what stays undone>'`; a `QUESTION:` note is refused by the \
tool, which tells you to use `ask` instead.

   **Write board text TO the person at the machine** — every bullet, note, \
question, option and `--if-unanswered` line you emit is read by him, so \
address them as "you", never "he" or "him". Internal prose — this prompt, \
your comments, commit messages — stays third person; only what lands on the \
board says "you".

   **A completion note is AS SHORT as its result.** When nothing surprising
happened — it worked, nothing failed, you deviated from nothing, there is no
decision he needs to make — then the note for that ask IS one short line and
nothing under it: `ENACTED: done, no errors. pushed.` Detail (an indented
line, a second clause) earns its place only for what would otherwise surprise
him — something that did not work, a choice you made on his behalf, a rebuild
left pending, work deliberately left out. Never dress a plain success up.
Leaving another minister's work alone is implied, not news — a note never
says it.

   The board (`docs/board.<hostname>.md`, this host's own — the two machines \
no longer share one) is a store three programs parse and write concurrently; \
every edit is a targeted line edit under a lock. Do not open it in an editor. \
`docs/` is its own git repo inside this checkout, so commit from inside `docs/`.

   **Run it even if you finished nothing** — say what stopped you. A worker \
that ends without recording anything is reported on his board as having stopped \
without finishing, which is deliberate: he must never be told something landed \
when it did not. That report is the only thing you cannot leave behind.

11. **If you genuinely cannot decide something only he can decide, ASK — do not \
guess big:**

       python3 apps/board/tools/boardctl.py ask '<the question>' \\
           --context '<what you found that raises it>' \\
           --option '<one way>' --option '<another way>' \\
           --if-unanswered '<what you will do / what stays undone>'

   It appears in the questions list on his board and he answers at his leisure. \
Then finish the part you CAN do and stop; there is nobody to wait for.

12. **You can be reached WHILE you run. Check between steps:**

       python3 apps/board/tools/boardctl.py inbox take --quiet

   Your stdin is closed, so a file is the only channel there is. Run it after \
each meaningful step and once more before you write your final note. Two things \
arrive that way. **Him**, typing at you mid-flight — a correction, an extra \
idea — and that OUTRANKS this prompt where the two disagree. Or **the \
orchestrator**, handing you a further item because you are already in those \
files: that is part of your job now, and your final note says what you did with \
it. Take them either way — an unread note is handed to somebody else later.

13. **If you are a CLAUDE minister (or Solomon, the orchestrator), you may hand
a chunk of wide, mechanical work to a cheaper deepseek subminister.** Run a
bounded chunk in your shell and get back a COMPACT result, instead of burning
your own expensive context on it:

       python3 apps/board/tools/boardctl.py subminister \\
           'read apps/pylib/**/*.py and list every public function with file:line'

   Reach for it only when BOTH hold: **(a)** the work is wide or mechanical —
   many files at once, a bulk extract, a normalising transform — NOT a couple of
   quick greps you would finish in one tool call (do those yourself); and **(b)**
   the result you need back is genuinely SMALLER than the work — a summary, an
   inventory, the output of a transform you will fold in and move on. Keep the
   delegated chunk BOUNDED (a few minutes, not hours) so your shell command
   survives it. It is pinned to the deepseek flash model and costs a fraction of
   your own tokens, but it is a NEW hop with its own output, so do NOT use it
   for creative, discretionary or judgement work you would have to re-read the
   whole output of to trust — if you would ingest ALL of it to verify or redo it,
   doing the work yourself is still cheaper. And a caller ALREADY on deepseek —
   a minister or the orchestrator on a hermes model — never uses it (the tool
   refuses): it is not cheaper for one of those.
{relay}
There is nobody to ask. Finish, or write down why you did not.
"""

#: Rule 14, and it is only shown to a minister that can actually act on it
#: (`relay_block`). Written as a HANDOVER rather than a stop: the reason a long
#: session is expensive is not the work it does, it is that every turn re-reads
#: everything said before it, so what has to end is the SESSION and not the
#: task.
RELAY_RULE = """
14. **You have a turn budget of about {budget}, and when you reach it you hand \
the REST of this task to a fresh minister instead of pushing on.** Check it \
between steps, in the same breath as your inbox:

       python3 apps/board/tools/boardctl.py turns

   It answers with what you have used, the budget, and whether to hand on. When \
it says to:

   1. **Finish and push what is in your hands** — never relay mid-edit. Commit, \
push, and `land`/`note` what actually landed, exactly as rule 10 says.
   2. Then hand the rest on, in one call, and STOP:

       python3 apps/board/tools/boardctl.py relay '<what landed, what is still \\
left, and what you learned that the next minister would otherwise have to \\
rediscover>'

   The successor is queued the instant you call it and the next tick starts it, \
on the same tier and the same files, with your brief in its task. It is not a \
failure and it is not a re-run: your work is recorded, and `relay` is itself \
your report, so you do not need a second one.

   **Why, in a number.** A session's cost grows with the SQUARE of its turns — \
everything already said is re-read on every turn after it — so three 100-turn \
ministers cost about a THIRD of one 300-turn minister for the same work. The \
brief you write is the whole price of the hop; write it well and it is cheap.

   This is hop {hop} of at most {most}. On the last one there is no relay left: \
finish what you can and report the remainder as `PARTIAL:`.
"""

ORCHESTRATOR_PROMPT = """You are running headless, with no human watching, on \
the machine {host}. Work in `{repo}`.

**You are Solomon, the orchestrator, and you do not do the work.** That is \
the name on the card pinned to the top of his board and the name he will use \
if he types something at you; the workers you hand things to are named after \
the demons of the Lesser Key, and you are the king who binds them. He typed \
the following into the one box on his board. Your job is to work out what it \
implies, split it into pieces, and hand each piece to a worker agent — or, if \
what it implies is genuinely his to decide, to ask him instead.

--- what he wrote ---
{notes}
--- end ---

WHAT YOU MAY DO, and it is a short list:

    python3 apps/board/tools/boardctl.py dispatch '<the task, in full - the \\
worker sees only this>' --where '<the files it will touch>' \\
        --model '<the tier - see WHICH TIER below>'

    python3 apps/board/tools/boardctl.py ask '<the question>' \\
        --context '<what makes it a question>' \\
        --option '<one way>' --option '<another way>' \\
        --if-unanswered '<what happens if he never answers>'

    python3 apps/board/tools/boardctl.py note 'SUMMONED <Name> (`<id>`) \
for|to <a few words>'

    python3 apps/board/tools/boardctl.py cap <n>      # a SETTING, applied now

    python3 apps/board/tools/boardctl.py agents       # who is running, and on what

    python3 apps/board/tools/boardctl.py subminister '<a bounded chunk of \\
wide, mechanical reading you would otherwise do YOURSELF>'

    python3 apps/board/tools/boardctl.py phase reading --doing '<one short \\
line>'

**Write board text TO the person at the machine** — every note, question, option \
and `--if-unanswered` line you emit is read by him, so address them as "you", \
never "he" or "him". Internal prose — this prompt, your comments, commit \
messages — stays third person; only what lands on the board says "you".

SAY WHAT YOU ARE DOING, with that last one, before you read anything and again \
when you move on. Your card is pinned to the top of his board and its first \
line is built from this — without it the card names you nowhere on that line, \
which he has asked for by name. One word, letters only, true: `reading`, \
`planning`, `dispatching`, `waiting`.

    python3 apps/board/tools/boardctl.py inbox send '<the item, in full>' \\
--to <Name>                                           # hand it to one of them

SOMETIMES HE IS NOT ASKING FOR WORK, HE IS TURNING A KNOB. *"change the number \
of allowed agents to 5"* is not a task for a worker — it is this system's own \
setting, and dispatching an agent for it turns a one-second change into a \
model session, a commit and a wait. Apply it yourself with the tool above and \
say so in your note. The knobs you own: the worker cap (`cap`). Anything else \
that looks like a setting but has no tool here is a `dispatch` like any other, \
and say in the note that it needed one.

**DELEGATE FAST. Reading the repo yourself is the slow, wrong instinct** — \
[his, 2026-07-29] *"is there a way we can have it so solomon is more free to \
delegate so he is more apt to quickly attend to items in the inbox? it seems \
like solomon does a ton of work himself"*. Your run is WAITED ON and it holds \
the tick: every minute you spend reading is a minute the next thing he types, \
and the next decision he answers, sits there. So:

  * **Read at most enough to name a plausible `--where`.** A glob is a fine \
answer, and a `--where` that is slightly wrong costs a worker one `grep`.
  * **What you do not know goes into the TASK TEXT, as words.** *"find the \
file that draws the scrollbar arrows — the nested `AGENTS.md` nearest it is \
authoritative"* is a complete dispatch. A worker has the whole repo, the guides \
and far longer to read them than you do.
  * **Do not open `AGENTS.md`, a nested guide or `docs/DESIGN.md` to plan.** \
Every worker's own rules already send it to those, and reading them here buys \
nothing but delay. Name the one it should read if it is not obvious.
  * **When you genuinely must read WIDE, mechanical material to name a \
`--where` or see how many jobs an ask holds — many files at once, a bulk \
inventory — hand THAT to a deepseek `subminister` rather than reading it in \
your own waited-on session**, and fold the compact result back in. Same tool \
and same two rules a minister uses (rule 13): the chunk is wide/mechanical and \
what comes back is smaller than the work. It refuses if you are yourself on a \
deepseek/hermes model — then it is no cheaper and you read it yourself. Do not \
reach for it for the quick grep you would finish in one call, or to plan the \
split itself — that judgement is yours.
  * **Split on what he SAID, not on what the code turns out to be.** You are \
splitting a sentence into jobs; you are not scoping them.
  * **Do not edit any file, do not commit, and do not run a test.** A worker \
does that. If the whole thing is one indivisible job, dispatch one worker; that \
is a fine answer.

The one thing worth being slow about is the `agents` check below — handing an \
item to somebody already in those files is the mistake that costs a merge, and \
it is one command.

ONE MESSAGE IS OFTEN SEVERAL JOBS. Before you plan anything, read the input for \
how many DISTINCT asks it holds — unrelated requests, two features, a bug plus \
a feature, a knob plus a task — and treat each as its own item. Expect typos: \
infer the intent and dispatch on it, never bounce his sentence back for \
spelling.

  * **One worker per independent item**, all dispatched so they run at once. A \
worker handed two unrelated jobs half-finishes both and leaves one commit that \
is hard to undo.
  * **Genuinely coupled pieces stay in ONE worker** — same file, same \
behaviour, one change. Splitting those gives two agents conflicting edits to \
the same file, which is worse.
  * **Apply the rule below per item**, so one message can yield two dispatches, \
or a dispatch and a question. The two-question ceiling still binds the whole \
message, not each item.
  * **Two items that touch the same files are ONE dispatch**, even when he \
wrote them as two sentences. That is the same rule as the one above, read from \
the other end.
  * **What you were handed may be SEVERAL SEPARATE MESSAGES he typed minutes \
apart, and they are ONE planning problem.** They are given to you together on \
purpose: how he broke his thinking into box-fulls is not how the work divides. \
So group across the whole input by FILE SET before you dispatch anything — two \
messages that both land in `apps/player/` are one minister, not two racing to \
edit the same file — and treat a later message that corrects or extends an \
earlier one as the same item, not a second one.

...AND ONE ASK IS OFTEN SEVERAL JOBS TOO. Do not stop splitting when you run \
out of sentences. Read each item for the AREAS it lands in — the panel QML, the \
plugin C++, an app's Python, the window config, a doc — and **give each area \
that does not share files with another its own worker**, even though he wrote \
one sentence and even though they are all "the same feature". A change that \
spans four areas is four dispatches.

**Why, in a number, because this is the expensive shape and it does not look \
like one.** A session's cost grows with the SQUARE of how many turns it takes: \
everything already said is re-read on every turn after it, so a worker's own \
output is charged again and again. Measured here: a 200-turn worker cost ~50M \
input tokens; four 50-turn workers doing the same total work cost about a \
QUARTER of that, and finish in a quarter of the wall-clock because they run at \
once. **Starting more agents costs nothing extra** — each pays its startup \
context once per turn, so four workers of fifty turns and one worker of two \
hundred pay exactly the same startup bill. The saving is all in the squared \
part, which is why "one worker, it will get there" is the wrong instinct even \
when it is true.

  * **The axis is DISJOINT FILES, and that is not negotiable.** Everything \
above about two agents in one file still holds and outranks this: splitting one \
file two ways is worse than one long worker, every time. Split where the file \
sets do not intersect; when you cannot tell, `--where` a glob per worker that \
does not overlap another's.
  * **Sequential work is still two workers, not one.** If part B genuinely needs \
part A's commit first, say so in B's task text — *"Marbas is changing X; pull \
before you start"* — and dispatch both. B queues behind the cap anyway and a \
later tick starts it.
  * **THE CAP is not a reason to split less** — see below; over it a dispatch \
queues rather than fails, and a short worker frees its slot sooner than a long \
one ever would.
  * **Do not manufacture areas to split on.** A one-file change is one worker; \
that is a complete answer and always was. This rule is for the ask that really \
does span the tree, not a licence to shard a small job into five agents that \
each pay a startup bill to do nothing.

WHICH TIER EACH PIECE RUNS ON, and this is yours to say because you have just \
written the task and the `--where` and nothing downstream knows the piece \
better. [his, 2026-08-02] the DEFAULT is now `deepseek v4` — leave `--model` \
off and the piece runs there, off his weekly Claude window entirely. You tier \
UP from that default with `--model`, and only for a piece that is MORE than \
mechanical or beyond what deepseek can usually handle, graded by how hard it \
is. The ministers are most of what this system spends, so the cheap default is \
the point: name a Claude tier because the work needs it, not by habit.

  * `deepseek v4 flash` (the DEFAULT, leave `--model` off) — an inventory, a \
survey, a wide read, prose and doc edits, a mechanical rename, and anything \
else mechanical or within what deepseek usually handles. Off his Claude window \
entirely.
  * `haiku 4.5 medium`, then `sonnet 5 medium` — the lowest Claude tiers, up \
from the default for a change that needs Claude but whose SHAPE is already \
decided: one file, a stated edit, a `.nix` packaging change, a harness run, a \
test to repair.
  * `opus 4.8 medium` (the CEILING you may reach on your own) — for work that \
genuinely needs it: the plugin's C++, QML and anything visual, anything that \
reads `docs/DESIGN.md`, multi-file design work. Not for uncertainty.
  * **HIGHER than `opus 4.8 medium` — a stronger opus, more thinking — you ASK \
him first** (`ask`), you do not dispatch it. That one tier decision is his.

  * **WHEN IN DOUBT, TIER DOWN — stay on the default.** Unsure whether a piece \
needs more than deepseek? Prefer the default unless the piece is plainly more \
than mechanical; uncertainty is not a reason to spend. Before you reach for \
opus, consider SPLITTING the piece into simpler models working together on \
disjoint files — each cheap, running in parallel (the split rules above). Tier \
UP only when the work genuinely exceeds the cheap model: a minister on too \
small a model does not fail where he can see it — it half-lands the work and \
reports that it is done, which is the one thing nothing here may do. That guard \
is the reason to tier up to what the work NEEDS, not a licence to default to \
opus; no saving is worth a confident lie, and no uncertainty is worth an opus.

SOMEBODY MAY ALREADY BE IN THOSE FILES. Run `agents` before you dispatch \
anything. It lists what is running right now, each with the task it was given \
and the files it was dispatched against. When an item you are about to hand out \
is the same job as one already in flight, or lands in the same files, HAND IT \
TO THAT AGENT instead of starting a second one: two workers editing one file is \
the thing this system is built not to do. `dispatch` itself warns when the \
`--where` you pass overlaps a live worker's — that warning is this same check \
firing after the fact, never a refusal — so still run `agents` first rather \
than waiting to be warned.

  * **Only a WORKER may be handed anything.** In that listing a worker is a row \
with a NAME in front of its id and a path or glob in its last column. A row \
whose last column reads `board-watch` is YOU. A row with no name at all is \
either a decision agent, whose own prompt forbids it to pick up anything else, \
or his interactive session — never hand work to either.
  * **Write the item in FULL, the way you would write a `dispatch`.** Those \
words are all anybody downstream gets.
  * **`inbox send` prints what happened, and you must read that line.** \
`delivered` means it is sitting in that worker's inbox; the worker reads its \
inbox between steps, so nothing is interrupted and nothing is instant. \
`queued` means that worker had already gone, and the item is waiting for the \
next agent instead — which is why the words have to stand on their own. Neither \
outcome loses it; neither is immediate.
  * **A collision is never grounds for LEAVING THE ITEM ALONE.** His rule, \
2026-07-29: *"in the future instead of leaving it alone you should pass it to \
the minister holding the files"*. Noting that you left work undone to avoid a \
collision is not an outcome — hand it over. An agent had found the cause of \
goetia's flashing titlebar text, saw `apps/pylib/vtbclient.py` was held by \
another worker, and dropped the fix "rather than collide", losing it to save \
one handoff. And when `inbox send` answers `queued`, that worker has already \
gone — so the collision has too: re-check `agents` and `dispatch` it instead of \
leaving it waiting on an indeterminate next agent.
  * **Hand over only what is genuinely the same work.** An item that can stand \
on its own gets its own worker even if it is nearby, because a handoff waits on \
somebody else's pace. In two minds: dispatch.
  * A handoff takes no slot against the cap — a consequence, never a reason. Do \
not hand work over to get under the cap; `dispatch` queues what is over it and \
a later tick starts it.
  * **Report it with `COMMANDED`, NEVER `SUMMONED`** — one line, tagged with \
that word and nothing in front of it, naming the worker it went to: \
`COMMANDED Marbas (`wd690a4`) for the flashing titlebar`. The two words are \
the whole difference he reads off the board: `SUMMONED` is a NEW agent, \
`COMMANDED` is one already running that you gave more work to.

DISPATCH OR ASK — the rule, because guessing big is the expensive mistake:

  * **Dispatch** when the input names a thing and one honest change follows \
from it. "the scrollbar arrows feel sluggish" is a dispatchable task: a worker \
can find the stepper, measure it and change it.
  * **ASK** when it implies a choice between real alternatives he has not made, \
when it would change something desktop-wide (the design language, a shared \
component, every app at once), when it touches the Ask-first list in \
`AGENTS.md` (a pin bump, login/logout behaviour, re-architecting the panel or \
the plugin), or when "how much" is the actual question and only he knows. \
**Needing a rebuild or a reload is NOT a reason to ask** — a worker may run \
one now, under rule 1. A question costs \
him ten seconds whenever he feels like it. A wrong guess costs a worker, a \
commit and a change he has to notice and undo.
  * **ASK, too, when it changes what happens at login or logout, or reaches \
outside this repo into his home directory.** Those are his by standing rule, \
whatever else the input implies.
  * **A well-scoped improvement is NOT a question.** His words: *"honestly i \
might not [mind] if you just dispatch agents to do those sorts of things \
without asking me"*. If you can state the change in one sentence and it does \
not land in any of the above, dispatch it and say so in the note.
  * **At most two questions for one input.** A wall of questions is its own \
kind of pressure, and this board exists because he did not want that.
  * Every `ask` MUST carry `--if-unanswered`. That sentence is what makes it \
safe for him to walk away from the question, and the tool refuses without it.

THE CAP. There is a limit on how many workers run at once ({cap} right now). \
`dispatch` enforces it itself: over the cap it QUEUES the task and says so, and \
a later tick starts it when a slot frees. So dispatch everything the input \
genuinely implies and do not ration it yourself — but do not invent work either.

RULES bind you and every worker you dispatch — they are in your system prompt,
in force for this session, and not negotiable.

YOUR NOTE REPORTS A START, NOT A RESULT — AND IT IS TWO LINES, NOT A \
PARAGRAPH. Finish with one `note`, to this budget: **one line per task you \
handed out, one line per question you asked, about a dozen words each after \
the tag at the most, and no second paragraph.** Every line STARTS WITH A TAG, \
then that short summary, then nothing — his rule for this list, and the tool \
refuses a line without a tag or with a longer first line.

**A task you handed out is tagged `SUMMONED`, and NOTHING comes before it** — \
no `INFORMATION:`, no `**subject**`. The whole line is the tag, the worker's \
NAME, its coded id in parentheses, then **`for`** or **`to`** — whichever \
reads correctly — plus a few words saying what it went out for. It is still \
filed under `information` on his board; the tag does that by itself. \
**Never say that nothing has landed yet**; silence says it, and he does not \
want it written. Like:

    SUMMONED Marbas (`wd690a4`) to add commit times to the landed section

**`SUMMONED` is for a `dispatch` ONLY.** An item handed to a worker that was \
already running is **`COMMANDED`**, in exactly the same shape — \
`COMMANDED Marbas (`wd690a4`) for the flashing titlebar` — his rule, and the \
point of it is that he can tell at a glance whether a new agent was started or \
an existing one was given more work.

`INFORMATION:` is still yours for a fact that is NOT a summon (a knob you \
turned). A question you want answered is NEVER a note — go through \
`boardctl.py ask '<the question>' --option '<a way>' --if-unanswered \
'<what stays undone>'`, the only writer of a question on this board; a \
`QUESTION:` note is refused.

The dozen-word budget still binds, and the tail after the name spends most of \
what is left: keep it to a few words, not a sentence.

Every worker has a name and `dispatch` prints it; use it. **One \
identifier per line**: the name, and the coded id in parentheses after it only \
because that is what its log under `~/.cache/board-work/` is called.

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


# Allow the tools a working agent needs; deny the ones nothing here may ever
# do. board-watch imports these rather than keeping a second copy — one list, so
# a hole cannot be opened in one spawner and not the other. The prompt is the
# primary defence and this is the mechanical one; a prefix matcher is not a
# sandbox (see `docs/agents/board-watch.md`).
#
# THE REBUILD AND RELOAD ENTRIES ARE GONE (2026-07-29), by his decision on the
# board: an agent here may rebuild and reload at its own judgement, under
# `~/nix/AGENTS.md` -> "When it is okay to rebuild or hot-reload". What is left
# is what that rule itself forbids outright, so the two halves now agree instead
# of the list contradicting the prompt:
#
#   * `hyprctl plugin` — load/unload erases hyprvtb's config keys for good and
#     no reload repairs it. `hyprctl reload` and the rest are allowed.
#   * `loginctl` — ends or locks his session; never a step in doing work.
#   * the reverting git commands — he leaves real uncommitted work in this tree.
#
# `Bash(sudo:*)` had to go WITH them, and not as an oversight: a deny rule beats
# an allow rule, so keeping it while carving out `Bash(sudo rebuild-top:*)`
# would have left the rebuild blocked on `top` and the decision unimplemented.
# What guards root is sudo itself and it is a better gate than this list ever
# was — NOPASSWD covers exactly the one hardcoded `rebuild-top` wrapper
# (`sys/nixos-rebuild.nix`), and anything else is `sudo -A`, which puts a dialog
# in front of HIM. book has no such wrapper and needs no root to rebuild at all.
ALLOW = ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "Task", "TodoWrite",
         "NotebookEdit", "WebFetch", "WebSearch"]
DENY = ["Bash(hyprctl plugin:*)", "Bash(loginctl:*)",
        "Bash(git reset:*)", "Bash(git checkout:*)", "Bash(git restore:*)",
        "Bash(git stash:*)", "Bash(git clean:*)"]

# ------------------------------------------- what the STARTUP CONTEXT costs
#: `ALLOW` above is a PERMISSION filter — it decides what a tool call is allowed
#: to do, and the schema loads either way. `--tools` is the other axis: which
#: built-in tools EXIST for the session at all, i.e. how many schemas are in the
#: prompt before the agent has read a line. The two are not interchangeable and
#: this system needs both.
#:
#: Why it is worth a constant: measured on book 2026-07-29, the startup floor of
#: a spawn here is ~43k tokens, and it is re-read on EVERY turn of the session.
#: Across one day (215 sessions, 11,987 assistant turns) that floor alone
#: accounted for ~600M of the 1,510M input tokens processed — 40%. So a token cut
#: from the floor is paid back once per turn, and the long ministers run 150-350
#: turns each. Restricting the tool set is the single biggest lever: 43,442 ->
#: 32,865 tokens, -24%, because it drops the deferred-tool block, `Workflow`
#: (~6k of description on its own), `Artifact`, `ScheduleWakeup`, `ToolSearch`,
#: `AskUserQuestion`, `ReportFindings`, `Skill` and the Task/todo reminders that
#: fire every few turns.
#:
#: WHAT IS DELIBERATELY STILL HERE. `Task` is the subagent tool (the CLI answers
#: to that name and the session then reports it as `Agent`) — ministers use it,
#: 26 times across the last 40 sessions, and a minister that cannot fan out does
#: the reading serially in its own context, which is the expensive shape. The web
#: pair costs ~1k and has zero recorded uses, and is kept anyway: a minister sent
#: at an upstream API it cannot look up flounders for far more than 1k. `Skill`
#: and `TodoWrite` are NOT here — nothing in a minister's prompt reaches for
#: either, and every skill this machine has is unreachable from a headless run.
TOOLS = ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "Task",
         "WebFetch", "WebSearch"]

#: Turn the superpowers plugin OFF for a MINISTER, and only for a minister.
#: [his, 2026-07-29] *"def disable superpowers for ministers but solomon should
#: still have it enabled"*. `--settings` merges over `~/.claude/settings.json`
#: rather than replacing it, which is what this needs: the SessionStart host-id
#: hook and the PostToolUse inbox hook both still fire (verified — an inbox note
#: reaching a worker mid-flight is load-bearing for rule 11).
#:
#: It is worth doing for a minister and not for Solomon because of the shape of
#: the two runs, not because the skill is worse advice. The injection is ~2k
#: tokens and arrives TWICE (the hook's own stdout and the additionalContext it
#: asks for), plus ~2.2k of skill listing. Solomon runs 6-12 turns, so it costs
#: it ~50k a run; a minister runs 150-350, so it costs one of those ~1.2M. And
#: its first instruction — invoke a skill before answering, brainstorm before
#: building — is advice for somebody with a human to check with. A minister has
#: no human, has its whole task in one prompt, and has RULES that already say
#: what to read.
MINISTER_SETTINGS = json.dumps(
    {"enabledPlugins": {"superpowers@claude-plugins-official": False}})


# ---------------------------------------------- which agent runtime spawns
#: The seam that keeps goetia from hardening onto Claude Code / Anthropic.
#: Everything on the DATA layer (inbox, store, `BOARD_*` env, the unit
#: lifecycle, the paper trail) is backend-neutral by construction; this owns
#: the four things that are not — how the run is invoked (the argv), where its
#: live transcript lives, and the per-backend tool names. A second backend is
#: additive: subclass `AgentBackend`, register it, select it at spawn with the
#: `BOARD_BACKEND` env (a runtime knob like `cap`, no rebuild). See
#: `docs/agents/minister-context.md` for the invariants a backend must keep.
#
#: `context_flags` and `role_flags` below stay public module functions because
#: the prompt-argv tests call them by name; the backend COMPOSES them rather
#: than replacing them, so the seam is additive and the Claude path is
#: byte-identical except for RULES' relocation to the system prompt.
class AgentBackend:
    """One agent runtime goetia can spawn and observe. Abstract."""

    name = None

    def system_blocks(self, role):
        """Constant instruction blocks appended to the cached system prompt for
        `role`. Backend-neutral contract: EVERY spawn of a role must get
        byte-identical blocks, so they form a stable cache prefix across
        spawns, and must never be interpolated after variable content."""
        return []

    def args(self, *, prompt, session, role, label, model=None, effort=None):
        """The full argv for one headless run. THE only place a backend's CLI
        is named. `session` may be None (no observable transcript -> claim-only
        card); `label` is the human name bound to the run. `model`/`effort`, when
        given, are the caller's already-resolved pick and win over the role's
        env/default — how one spawn stays independent of another's running at
        the same time, with no process-global state between them."""
        raise NotImplementedError

    def transcript(self, session):  # type: (str | None) -> str | None
        """Path to this agent's live transcript, or None. None is the honest
        degradation: a card shows the claim only, with no observed line."""
        return None

    def arm(self, agent_id, argv):
        """Bind a spawn we have just built to whatever identifies it in this
        backend's OWN store, for the backends whose session id we cannot
        choose. Called with the final argv, at the spawn, by both spawners.
        Nothing to do for a backend that takes a `--session-id`."""
        return

    def history_hint(self, agent_id, session):
        """Where the whole run can be read, as a path or a command he can
        paste. `""` when there is nothing honest to name yet."""
        return ""


class ClaudeBackend(AgentBackend):
    """The Claude Code CLI. `--append-system-prompt` merges RULES into the
    default system prompt that `--exclude-dynamic-system-prompt-sections` has
    already made identical across spawns, so the whole constant prefix is one
    cache entry (see the Phase 1 note in `docs/agents/minister-context.md`)."""
    name = "claude"

    def system_blocks(self, role):
        return [RULES]

    def args(self, *, prompt, session, role, label, model=None, effort=None):
        argv = ["claude", "-p", prompt]
        if session:
            argv += ["--session-id", session]
        argv += role_flags(role, model=model, effort=effort)  # his choice, capped
        argv += context_flags(role)         # cache prefix + trimmed tools (NO superpowers)
        for block in self.system_blocks(role):
            argv += ["--append-system-prompt", block]
        argv += ["--permission-mode", "acceptEdits",
                 "--allowedTools", *ALLOW,
                 "--disallowedTools", *DENY,
                 "--output-format", "text",
                 "-n", label]
        return argv

    def transcript(self, session):
        return bph.transcript(session)

    def history_hint(self, agent_id, session):
        if not session:
            return ""
        found = bph.transcript(session)
        # Not there yet (or the project directory was renamed) — a glob is still
        # an answer he can paste into a shell, and it is honest about what is
        # known.
        return found or os.path.join(bph.projects_dir(), "*",
                                     "%s.jsonl" % session)


# ------------------------------------------------------- the hermes backend
#: The models that live on the Hermes runtime rather than Claude Code, and the
#: provider they run under on this machine. A model in `HERMES_MODELS` routes a
#: spawn to `HermesBackend`; everything else stays on Claude. [his, 2026-07-31]
#: the summoner and minister dropdowns should offer `deepseek-v4-flash-0731`
#: via hermes.
#:
#: `deepseek-v4-pro` rides it too — a stronger, still-far-cheaper-than-Claude
#: step up, offered in the summoner dropdown for a run that should stay off the
#: weekly Claude window without dropping all the way to flash. `kimi-k3`
#: (Moonshot) is a third hermes model — a strong, large-context coding family
#: offered in both dropdowns, same nous provider.
#:
#: [docs/agents/hermes-paid-models.md, 2026-08-03] three more rungs fill gaps in
#: the ladder: `minimax-m3` (a mid step between the deepseek default and
#: kimi/haiku) and `deepseek-v4-pro` as MINISTER rungs, and `z-ai/glm-5.2` — the
#: portal's own silent default, a strong planner below the fable summoner — as a
#: summoner option. All route through the same nous provider.
HERMES_MODELS = {"deepseek/deepseek-v4-flash-0731",
                 "deepseek/deepseek-v4-pro",
                 "minimax/minimax-m3",
                 "z-ai/glm-5.2",
                 "moonshotai/kimi-k3"}
HERMES_PROVIDER = os.environ.get("BOARD_HERMES_PROVIDER", "nous")
#: The Hermes toolsets a minister may reach. Mirrors the Claude `TOOLS` idea:
#: a minister gets the shell, the file tools and the web pair — nothing bigger.
HERMES_TOOLSETS = os.environ.get("BOARD_HERMES_TOOLSETS",
                                 "file,terminal,web,search")
#: Cap on tool-calling iterations, the Hermes analog of the 45-minute unit cap.
HERMES_MAX_TURNS = int(os.environ.get("BOARD_HERMES_MAX_TURNS", "150"))


class HermesBackend(AgentBackend):
    """The Hermes Agent CLI (`hermes chat -q ...`). Everything a Claude run
    gets through a flag, a hermes run gets through the same surfaces with the
    hermes names: the model+provider, the toolsets, and RULES (which hermes has
    no `--append-system-prompt` for, so they ride in the query body — same
    verbatim block, different channel).

    **There is no `--session-id`, so the run is bound by its QUERY instead**
    (`arm` -> `boardphase.arm` -> `boardhermes.resolve`): hermes stores the
    `-q` text verbatim as its session's first user message, so a hash of what
    we sent finds the session in `~/.hermes/state.db`, and the card's observed
    line and the drawer read from there. `transcript()` stays None — there is
    no file — and that is now a statement about the SHAPE of the history, not
    about whether it can be seen.
    """
    name = "hermes"

    def system_blocks(self, role):
        return [RULES]

    def args(self, *, prompt, session, role, label, model=None, effort=None):
        q = prompt
        for b in self.system_blocks(role):
            q += "\n\n" + b
        return ["hermes", "chat", "-q", q, "-Q",
                "--source", "tool",
                "-m", _role_model(role, model), "--provider", HERMES_PROVIDER,
                "-t", HERMES_TOOLSETS,
                "--max-turns", str(HERMES_MAX_TURNS),
                "--yolo"]

    def transcript(self, session):
        return None

    @staticmethod
    def _query(argv):
        """The `-q` text out of an argv we built ourselves."""
        try:
            return argv[list(argv).index("-q") + 1]
        except (ValueError, IndexError):
            return ""

    def arm(self, agent_id, argv):
        q = self._query(argv)
        if agent_id and q:
            bph.arm(agent_id, q)

    def history_hint(self, agent_id, session):
        import boardhermes as bhx
        found = bph.hermes_session(agent_id) if agent_id else ""
        if found:
            return bhx.hint(found)
        # Armed and not yet bound. Naming the store and how to list it is the
        # honest answer; naming the `--session-id` uuid we minted would be a
        # path that will never exist, which is the bug this replaced.
        return "hermes sessions list (its session is bound once it opens)"


_BACKENDS = {"claude": ClaudeBackend(), "hermes": HermesBackend()}


def get_backend(name=None):
    """The spawner backend for this run — `BOARD_BACKEND` env, default claude.
    Read at spawn time, like `cap()`, so a runtime switch needs no rebuild."""
    want = (name or os.environ.get("BOARD_BACKEND") or "claude").strip().lower()
    try:
        return _BACKENDS[want]
    except KeyError:
        raise ValueError("no board backend %r (have: %s)"
                         % (want, ", ".join(sorted(_BACKENDS))))


def _role_model(role, model=None):
    """The model string the NEXT `role` spawn runs on — the same source
    `role_flags` reads, so a spawn and its flags (and the backend that hosts
    them) never disagree. An EXPLICIT `model` wins, the same precedence
    `role_flags` gives it, so a caller that resolved its own pair picks its own
    backend."""
    if model:
        return model.strip()
    if role in MINISTER_ROLES:
        return minister_model()[0]
    if role == "orchestrator":
        # Honour the same `BOARD_ORCH_MODEL` override `role_flags` reads, so the
        # BACKEND a run rides (hermes vs claude) never disagrees with the
        # `--model` flag it is launched with — a deepseek pick must reach the
        # hermes backend, not claude with a deepseek flag.
        return os.environ.get("BOARD_ORCH_MODEL", orch_model()[0]).strip()
    return ""


def get_backend_for_model(model):
    """Which backend hosts `model` — hermes for `HERMES_MODELS`, else claude."""
    return get_backend("hermes" if model in HERMES_MODELS else "claude")


def get_backend_for_role(role, model=None):
    """The backend the NEXT `role` spawn runs on, from its chosen model — the
    explicit `model` when a caller resolved it, else the role's own source."""
    return get_backend_for_model(_role_model(role, model))


# --------------------------------------------------- the deepseek subminister
#: A Claude minister may hand a chunk of wide, mechanical work to a cheaper
#: deepseek "subminister" instead of doing it in its own expensive context —
#: the whole point of the feature. THE MODEL IS PINNED: whatever the minister's
#: own dropdown says, a subminister ALWAYS runs on the deepseek flash model,
#: and it rides the hermes backend because that model is in `HERMES_MODELS`.
DEEPSEEK_SUBMINISTER_MODEL = "deepseek/deepseek-v4-flash-0731"
DEEPSEEK_SUBMINISTER_TURNS = int(
    os.environ.get("BOARD_SUBMINISTER_MAX_TURNS", str(HERMES_MAX_TURNS)))
#: Backstop only. A bounded subminister chunk should finish in minutes; this
#: stops a wedged hermes run from hanging the calling minister's shell forever
#: (the calling tool's own timeout usually bites first, which is why the guide
#: tells a minister to keep a delegated chunk bounded).
SUBMINISTER_TIMEOUT_S = int(os.environ.get("BOARD_SUBMINISTER_TIMEOUT", "2700"))


def calling_backend():
    """Which agent runtime the CALLING process is running under, if any.

    The gate for `subminister`, and it treats a Claude MINISTER and Solomon the
    ORCHESTRATOR identically — both are `claude` processes, both may delegate,
    and the refusal is on the RUNTIME (already on deepseek), never on the role.
    Walks this process's ancestors and takes the NEAREST one that is an agent
    runtime — `hermes` or claude — because the nearest is the one we are actually
    running under: a deepseek subminister spawned by a Claude caller has FIRST a
    `hermes` ancestor and then a claude one beyond it, and it is hermes. Env is
    deliberately NOT consulted (except as a fallback when no agent ancestor is
    found): `BOARD_WORKER_BACKEND` would be inherited by a subminister from its
    claude parent and lie.

    Returns `'claude'` | `'hermes'` | `'shell'` (no agent runtime in the chain).
    """
    procs = ba._procs()
    for pid in ba._ancestors(os.getpid(), procs):
        ent = procs.get(pid)
        if not ent:
            continue
        comm, cmd = ent[1], ent[2]
        if comm == "hermes" or (cmd and os.path.basename(cmd[0]) == "hermes"):
            return "hermes"
        if comm in ba.CLAUDE_COMMS or (cmd and os.path.basename(cmd[0])
                                       in ba.CLAUDE_COMMS):
            return "claude"
    env = os.environ.get("BOARD_WORKER_BACKEND", "").strip().lower()
    return env if env in ("claude", "hermes") else "shell"


def subminister(prompt, max_turns=None):
    """Run `prompt` to completion on the deepseek flash subminister, synchronously.

    Returns its stdout text. The calling Claude minister (or Solomon, the
    orchestrator) runs this in its shell and the result is captured as a tool
    result and folded into its own context — so the subminister is told, in the
    framing below, to return something COMPACT relative to the work it did. That
    compactness is what makes the hop a saving rather than a large bill.

    Refuses unless the CALLER genuinely runs on a Claude model — a minister or
    the orchestrator already on the deepseek/hermes runtime spending another
    hermes run to spawn one is pure waste (see `calling_backend`; the gate is on
    the runtime, not the role).

    **It DOES get a card.** [his follow-up, 2026-08-01] a subminister is given
    its own demon name from the Lesser Key and a registration record keyed on a
    minted `sub…` id, so the board can draw an inset card under its parent while
    it runs (`Murmur` renders it in `main.py`/`qml` off the fields this writes:
    `kind="subminister"`, `name`, `parent`, `parentName`). It is NOT a board
    worker: it takes no unit, writes no bullet, counts against no cap
    (`live_workers` filters on `kind=="worker"`), is never reaped
    (`reap` reads task files it never creates) and is not in the flat `cards()`
    list. The record is dropped in the `finally`; a killed run leaks nothing that
    `boardagents.sweep()` does not clean on the next tick (dead pid).
    """
    want = " ".join((prompt or "").split())
    if not want:
        raise ValueError("no prompt for the subminister")
    if calling_backend() == "hermes":
        raise ValueError(
            "you are ALREADY on the deepseek/hermes runtime, so a deepseek "
            "subminister is just another cheap run - do this chunk yourself; "
            "the tool refuses a caller (minister or orchestrator) already on "
            "deepseek spawning another")
    q = SUBMINISTER_FRAME.format(prompt=want)
    cmd = ["hermes", "chat", "-q", q, "-Q",
           "--source", "tool",
           "-m", DEEPSEEK_SUBMINISTER_MODEL,
           "--provider", HERMES_PROVIDER,
           "-t", HERMES_TOOLSETS,
           "--max-turns", str(int(max_turns or DEEPSEEK_SUBMINISTER_TURNS)),
           "--yolo"]
    # The id/name/record exist only for the duration of the run, purely so the
    # UI can draw the inset card. `parent` is the CALLER's inbox id — a minister's
    # `BOARD_AGENT_ID`, or the orchestrator's — so `Murmur` can place the card
    # directly under the row that spawned it (`boardagents.self_id`).
    aid = "sub%s" % os.urandom(3).hex()
    name = ba.pick_name(aid)
    parent = ba.self_id() or ""
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, cwd=REPO)
    except (OSError, ValueError) as e:
        raise ValueError("the deepseek subminister could not run: %s" % e)
    ba.register(aid, want[:70], p.pid, kind="subminister", where="",
                session="", name=name, parent=parent,
                # It always runs on deepseek flash; name that tier on its card
                # like every other agent's, from the offerable flag (not the raw
                # hermes id) so `tier_label` reads *"deepseek v4 flash"*.
                model=MINISTER_DEFAULT[0], effort=MINISTER_DEFAULT[1])
    try:
        out, err = p.communicate(timeout=SUBMINISTER_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        raise ValueError("the deepseek subminister timed out after %ss"
                         % SUBMINISTER_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as e:
        raise ValueError("the deepseek subminister could not run: %s" % e)
    finally:
        ba.unregister(aid)
    if p.returncode != 0:
        raise ValueError("the deepseek subminister failed (exit %s): %s"
                         % (p.returncode, (err or out or "").strip()[:600]))
    return out


#: The framing a subminister starts with. It is the subminister's WHOLE
#: instruction set — deliberately a self-contained block, NOT the board-worker
#: `RULES` (which speaks of committing, rebuilding and writing to the board, all
#: things a bounded mechanical subagent must NOT do). Its job is to return a
#: COMPACT result and get out of the way; the calling Claude minister quotes
#: what comes back, so the leaner it is the more the hop saves.
SUBMINISTER_FRAME = (
    "You are a deepseek subminister working FOR a Claude minister (or the "
    "orchestrator) on this machine. You get one bounded chunk of wide, "
    "mechanical work (bulk reading, "
    "wide greps, a normalising/mechanical transform). DO it in your own cheap "
    "context, and return a COMPACT result the calling minister can fold straight "
    "into its own context: a summary, an inventory, a list, or the transformed "
    "output it asked for. Do NOT write to any board, do NOT commit, do NOT use "
    "boardctl note/land/ask, and do NOT spawn any further agent. Do the work "
    "entirely on files in the repo: never touch the user's display, focus, "
    "audio, running apps or a rebuild, and never run a GUI. Keep your final "
    "answer lean - the calling minister will quote it wholesale.\n\n"
    "--- the chunk ---\n{prompt}\n--- end ---")


def context_flags(role):
    """argv fragment trimming the startup context for `role`.

    Both spawners call this for the same reason they share `ALLOW`/`DENY`: a
    flag set in one and not the other is invisible until the day the numbers
    stop matching. Measured floors, cold, on book 2026-07-29:

        today's flags                43,442
        + --disable-slash-commands   41,147
        + superpowers off            42,068
        + --tools (restricted)       32,915
        all of it                    32,865   (-24%)

    `--exclude-dynamic-system-prompt-sections` shows up in none of those
    numbers and is the reason the flag is here anyway: it moves cwd, env, memory
    paths and git status out of the system prompt, so the ~32k prefix is
    IDENTICAL across spawns and every one of them is a pure cache READ. Measured
    back-to-back: with it, `read 31,873 + write 0` twice over; without it,
    `read 14,736 + write 17,292` on a prefix that any other agent's differing
    git status would have broken anyway. Cache writes cost 1.25x and reads 0.1x,
    against ~200 spawns a day.

    SOLOMON GETS ONLY THAT ONE. It is the only entry with no behavioural half:
    keeping the skills and the plugin for the orchestrator is his call, and
    passing `--tools` without `Skill` would have taken them away by the back
    door while the injected text still told it to use them — a prompt at war
    with its own tool list.
    """
    argv = ["--exclude-dynamic-system-prompt-sections"]
    if role in MINISTER_ROLES:
        argv += ["--tools", *TOOLS,
                 "--disable-slash-commands",
                 "--settings", MINISTER_SETTINGS]
    return argv


# ------------------------------------------------ what model does which job
#: Per-ROLE model and reasoning effort, the one table for both spawners
#: (`_spawn_worker` below and `board-watch.py`'s `spawn`, which imports it from
#: here for the same reason it imports ALLOW/DENY: a knob set in one spawner and
#: not the other is invisible until it matters).
#:
#: `""` means SAY NOTHING — pass no flag and inherit whatever
#: `~/.claude/settings.json` is set to. That used to be the default for the two
#: roles that DO the work, on the reading that nobody had asked for them to
#: change and that pinning a model would silently outrank the setting he edits
#: by hand. **He asked, on 2026-07-29**: *"the other agents should all be opus 5
#: medium thinking"* — so both are pinned now, and the argument above is kept
#: only to say what changed and why it is no longer the reason.
#:
#: The ORCHESTRATOR is the exception he asked for. Its session is short and it
#: writes no code — read what he typed, work out how many jobs it is, run
#: `boardctl dispatch`/`ask`, write one note — so the cost of a bigger model and
#: more thinking is bounded by a run that is capped at fifteen minutes anyway,
#: while the mistakes it can make (splitting one job into three conflicting
#: workers, dispatching what should have been a question) each cost a worker, a
#: commit and something he has to notice and undo. Judgement is the entire job;
#: buy it.
#:
#: Flags verified against the installed CLI (`claude --help`, 2026-07-29):
#: `--model <model>` takes an alias or a full name, `--effort <level>` takes
#: low|medium|high|xhigh|max.
#: The orchestrator's model AND effort are HIS, chosen as one pick in the
#: dropdown beside the box and read out of `orch_model()` at spawn — the pair
#: written below is dead for this role (`role_flags` overwrites both from the
#: file) and is kept only so the table has a row and a fallback shape. He asked
#: to choose *"the reasoning effort of the summoner agents"* on top of the model,
#: so the effort is no longer pinned; `DEFAULT_ORCH` (`high`) is what a summoner
#: runs at until he picks otherwise, which is the value it was pinned to before.
#: Unlike a minister the summoner has NO ceiling — its judgement is the whole of
#: its job and he asked to be able to buy as much of it as he likes.
#:
#: A MINISTER's pair is his too — the fourth dropdown, read out of
#: `minister_model()` at spawn (which `role_flags` overwrites the pair below
#: with), so like the orchestrator's the value here is a dead fallback shape. It
#: is `MINISTER_DEFAULT` — [his, 2026-08-02] the minister default is deepseek v4
#: — named through the constant so it cannot drift from what `minister_model()`
#: returns when he has never chosen.
#:
#: The two MINISTER roles. Both are drawn on his board as ministers and both are
#: bound by the same ceiling, so the dropdown writes one store and this names who
#: reads it — a decision agent that could be re-pointed while a worker could not
#: would be the same control disagreeing with itself.
MINISTER_ROLES = ("worker", "decision")

ROLES = {
    "orchestrator": ("", "high"),
    "worker": MINISTER_DEFAULT,
    "decision": MINISTER_DEFAULT,
}


def role_flags(role, model=None, effort=None):
    """argv fragment selecting the model and effort for `role`.

    An EXPLICIT `model`/`effort` (passed by a caller that already resolved the
    pair, e.g. one concurrent summoner thread) wins over everything below and
    needs no process-global state — which is what lets two summoners spawn at
    once without racing the shared `BOARD_ORCH_*` env. Left as `None`, each
    falls back to the environment.

    Overridable per role by environment, following the `BOARD_*` convention the
    spawn stubs already use, so a harness can re-point or neutralise it:
    `BOARD_ORCH_MODEL` / `BOARD_ORCH_EFFORT`, `BOARD_WORKER_MODEL` /
    `BOARD_WORKER_EFFORT`, `BOARD_DECISION_MODEL` / `BOARD_DECISION_EFFORT`.
    Set one to the empty string to drop the flag and inherit the default.

    **A MINISTER role is clamped after all of that**, environment included. [his,
    2026-07-29] *"do not allow ministers to be anything higher than opus 5 medium
    thinking"* — so the pair either is one of `MINISTER_MODELS` or becomes
    `MINISTER_CEILING`, and there is no reachable route (stale file, hand-edited
    file, exported variable, dropped flag inheriting whatever
    `~/.claude/settings.json` says) by which a minister spawns above it. The
    variables can still LOWER a minister, which is all a harness ever wanted.
    """
    m, e = ROLES.get(role, ("", ""))
    if role == "orchestrator":
        m, e = orch_model()  # his choice of model AND effort, re-read
    elif role in MINISTER_ROLES:
        m, e = minister_model()   # his choice, capped, re-read likewise
    prefix = "BOARD_" + ("ORCH" if role == "orchestrator" else role.upper())
    # explicit arg > BOARD_* env > the role default, resolved independently for
    # model and effort so a caller can pin one and leave the other.
    model = (os.environ.get(prefix + "_MODEL", m) if model is None else model).strip()
    effort = (os.environ.get(prefix + "_EFFORT", e) if effort is None else effort).strip()
    if role in MINISTER_ROLES and (model, effort) not in minister_choices():
        model, effort = MINISTER_CEILING
    argv = []
    if model:
        argv += ["--model", model]
    if effort:
        argv += ["--effort", effort]
    return argv


def phase_word_menu(per_line=6, indent="       "):
    """`boardphase.PHASE_WORDS` as the block a prompt shows an agent.

    Wrapped rather than one word a line: thirty-odd single lines in the middle
    of rule 8 would read as more important than the rule, and the point of the
    list is that it is glanceable. It is generated, never typed out beside the
    constant — a menu that drifts from what the code accepts is worse than no
    menu.
    """
    words = list(bph.PHASE_WORDS)
    rows = [words[i:i + per_line] for i in range(0, len(words), per_line)]
    return "\n".join(indent + "  ".join("`%s`" % w for w in r) for r in rows)


def _task_name():
    return "%s-%s.json" % (time.strftime("%Y%m%dT%H%M%S"), os.urandom(3).hex())


def _log_path(agent_id):
    """`$XDG_CACHE_HOME/board-work/<id>.log`, and the variable is the point.

    This was a hardcoded `~/.cache` while every harness in the tree redirects
    `XDG_STATE_HOME` into a scratch dir — so a harness's fixture workers (`task
    one`, `task two`, ...) wrote their logs into HIS real cache and their units
    into his real journal. Measured 2026-07-29: 682 of the 714 files in
    `~/.cache/board-work/` were empty test debris from harness workers killed at
    teardown, and a dozen of them were mistaken for real dispatches that had
    silently produced nothing. A harness must never write outside its rig, and
    an agent reading that directory as evidence must be able to trust it.
    """
    d = os.path.join(os.environ.get("XDG_CACHE_HOME")
                     or os.path.expanduser("~/.cache"), "board-work")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, ba.clean_id(agent_id) + ".log")


# ------------------------------------------------- a log that survives a kill
# **A worker's `.log` is empty for the whole run, and empty forever if it is
# killed.** `claude -p` with no tty writes its result ONCE, at exit, so there is
# nothing to line-buffer and nothing to flush: a worker that is SIGKILLed, OOMed,
# reaped at `RuntimeMaxSec` or cut off mid-sentence leaves a zero-byte file, and
# the one case where the log matters most is the one case it is guaranteed to
# say nothing. [his, 2026-07-30, of the bullet that reported Foras killed
# mid-verification with an empty log:] *"i doubt you have no idea what happened
# to foras as this message implies"*.
#
# The full history DOES exist — the agent's own transcript, written live, the
# same file `boardphase` tails for the observed line — and we know its exact
# path because the spawn CHOOSES the session uuid. So the log stops being the
# record and becomes the POINTER: a header at spawn (so it is never zero bytes
# and always names the transcript) and a post-mortem footer when the worker is
# reaped without having reported.
#
# Header and footer are both `- ` prefixed and dated so nothing mistakes them
# for the agent's own voice — the card drawer prefers the transcript anyway and
# falls back to this file (`main.py`), and `_died_transiently` reads the tail,
# which neither of these lines can match.
def _log_line(aid, text):
    """Append one board-written line to a worker's log. Never raises."""
    try:
        with open(_log_path(aid), "a") as f:
            f.write("- [board %s] %s\n" % (time.strftime("%H:%M:%S"), text))
    except OSError:
        pass


def transcript_hint(session, aid=""):
    """Where a worker's full history is — a path before the file exists (the
    header is written before the agent has opened it), or the command that
    prints it on a runtime that keeps its history in a database. Routed through
    the backend, which is the only thing that knows the shape of its own
    store."""
    return get_backend_for_role("worker").history_hint(aid, session)


def log_header(aid, name, task, session):
    """Written BEFORE the worker starts, so even a kill at second one leaves a
    log that says who this was and where to read what it did. How it was
    started is appended by the caller, which is the only thing that knows.

    **What it names depends on the runtime, and it never names a file that
    cannot exist.** A Claude worker's history is the transcript at the uuid we
    chose; a hermes worker's is a row in `~/.hermes/state.db` whose id nobody
    knows yet, so the header says how to reach it and `boardphase._bind_hermes`
    appends the exact id the moment the session is bound. [2026-07-31: the
    header pointed every hermes minister at a `~/.claude/projects/*.jsonl` that
    was never written.]
    """
    _log_line(aid, "worker %s (%s) starting: %s" % (aid, name or "?",
                                                    " ".join((task or "").split())[:120]))
    backend = get_backend_for_role("worker")
    if backend.name == "claude":
        if session:
            _log_line(aid, "session %s - LIVE HISTORY IS THE TRANSCRIPT, this "
                           "file gets stdout only at exit: %s"
                      % (session, backend.history_hint(aid, session)))
    else:
        _log_line(aid, "LIVE HISTORY IS THE %s SESSION STORE, this file gets "
                       "stdout only at exit: %s"
                  % (backend.name.upper(), backend.history_hint(aid, session)))


_LOGGED_SESSION = re.compile(
    r"session ([0-9a-fA-F-]{36}) - LIVE HISTORY")


def _session_of(aid, rec=None):
    """The session uuid of a worker that is already gone.

    Three places, in order of how long they survive it: the task record, its
    registration (`sweep()` drops that soon after death), and finally the log
    HEADER this module wrote at spawn — which outlives both, which is the whole
    reason the header carries it.
    """
    if rec and rec.get("session"):
        return rec["session"]
    for a in ba.agents():
        if a.get("id") == aid and a.get("session"):
            return a["session"]
    try:
        with open(_log_path(aid), "r", errors="replace") as f:
            head = f.read(4000)
    except OSError:
        return ""
    m = _LOGGED_SESSION.search(head)
    return m.group(1) if m else ""


def log_postmortem(aid, session=None, why=""):
    """Written when a worker is closed out without having reported. This is the
    line that stops a killed worker reading as `log empty`."""
    _log_line(aid, "worker stopped without reporting%s"
              % ((" - " + why) if why else ""))
    hint = transcript_hint(session, aid)
    if hint:
        _log_line(aid, "what it actually did is in its history: " + hint)
    else:
        _log_line(aid, "no session id was recorded for it, so there is no "
                       "history to point at")


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


def _where_prefixes(where):
    """A `--where` glob as the literal path prefixes it names: split on
    whitespace, each token cut at its first glob character, empties dropped.
    `apps/board/** tools/board-watch-test.py` -> `apps/board/`, `tools/...`."""
    out = []
    for tok in str(where or "").split():
        for ch in "*?[":
            i = tok.find(ch)
            if i != -1:
                tok = tok[:i]
        if tok:
            out.append(tok)
    return out


def overlaps(where, workers=None):
    """The LIVE workers whose `--where` plausibly reaches the same files.

    Two prefixes overlap when one startswith the other, case-sensitively —
    `apps/board/` is inside `apps/**` and the other way around. It is a
    heuristic for a WARNING, never a gate: the orchestrator's prose rule
    (run `agents`, hand overlapping work to the worker already in those
    files) existed before this and still binds; this is the tool itself
    noticing, so a miss on the human step no longer passes silently. A
    near-miss must not block real work, so nothing reads this to refuse.
    """
    mine = _where_prefixes(where)
    if not mine:
        return []
    hits = []
    for a in (live_workers() if workers is None else workers):
        theirs = _where_prefixes(a.get("where"))
        if any(m.startswith(t) or t.startswith(m)
               for m in mine for t in theirs):
            hits.append(a)
    return hits


def _order_now():
    """HIS OWN SENTENCE, for the task about to be dispatched — or `""`.

    [his, 2026-07-30] *"information messages should display a truncated version
    of the original user prompt that spawned the message"*. This is where that
    text is picked up: `dispatch()` runs inside the summoner, and the summoner
    was registered under the words he typed into the box (`board-watch`'s
    `work_the_queue` -> `boardagents.register`). So the order is read off the
    caller's OWN card rather than threaded through a prompt an agent could
    forget to fill in — nothing an agent writes decides what he is quoted as
    having asked.

    `$BOARD_ORDER` wins when it is already set: a worker that dispatches more
    work is carrying the order it was given, and the chain must not restart at
    that worker's own task. Empty for an interactive session, a harness or a
    hand-run `boardctl dispatch` — nobody typed an order, so nothing is quoted.
    """
    return order_of(os.environ.get("BOARD_AGENT_ID", ""))


def order_of(agent_id):
    """The order behind `agent_id`'s run: `$BOARD_ORDER`, else the SUMMONER's
    own card title.

    The kind check is the whole of it. A summoner is registered under what he
    typed, so its title is his sentence; a WORKER is registered under the task
    it was handed, which is an agent's words about his words and must never be
    quoted back at him as the thing he asked for. A worker gets its order from
    the environment or not at all.
    """
    env = " ".join(os.environ.get("BOARD_ORDER", "").split())
    if env:
        return env
    rec = ba.record(agent_id) or {}
    if rec.get("kind") != "orchestrator":
        return ""
    return " ".join(str(rec.get("title") or "").split())


def dispatch(task, phase="", where="", context="", cap_=None, model=""):
    """One piece of work -> one worker, or -> the pending queue if we are full.

    Returns the task record with `state` in `running` / `queued`. It never
    raises on a full board and never silently drops: the two outcomes are the
    two directories, and `promote()` is what moves between them.

    `rec["overlaps"]` carries the live workers whose `--where` overlaps this
    one (`overlaps()` above) — computed before the spawn, so the new worker
    is never its own hit. WARN ONLY: it changes nothing about what was
    dispatched; `boardctl dispatch` prints it and the caller decides.

    `model` names the TIER this piece runs on (`minister_tier`) — a label, a
    wire pair, or anything `resolve_minister` can name; empty is his dial. It
    is resolved HERE and stored on the record, not read at spawn time, so a
    task that queues behind the cap runs on the tier it was planned with rather
    than on whatever the dial says whenever a slot happens to free.

    """
    task = " ".join((task or "").split())
    if not task:
        return None
    flag, effort = minister_tier(model)
    rec = {"task": task, "phase": (phase or "").strip().lower(),
           "where": (where or "").strip(), "context": (context or "").strip(),
           "model": flag, "effort": effort, "turns": RELAY_TURNS, "relay": 0,
           "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "sent": time.time(),
           "host": os.uname().nodename,
           "order": _order_now()}
    over = [{"id": a["id"], "name": a.get("name") or "",
             "where": a.get("where") or ""} for a in overlaps(rec["where"])]
    limit = cap() if cap_ is None else cap_
    if len(live_workers()) >= limit:
        path = os.path.join(work_dir("pending"), _task_name())
        ba._write_json(path, rec)
        rec["file"] = path
        rec["state"] = "queued"
        rec["overlaps"] = over
        return rec
    # Written to `taken/` BEFORE the spawn, exactly as `boardagents.drain()` is:
    # a task file still in `pending/` when the process dies would be worked
    # twice, and one deleted after a crash would be worked never.
    path = os.path.join(work_dir("taken"), _task_name())
    ba._write_json(path, rec)
    rec["file"] = path
    rec.update(_spawn_worker(rec))
    rec["overlaps"] = over
    return rec


#: The transient unit a worker runs as, `board-worker-<agent id>.service`. It is
#: also what he sees when he asks systemd what claude agents are running, which
#: is the shape he asked for the agents section in.
UNIT_PREFIX = "board-worker-"

#: ...and the one a DECISION runs as. Same mechanism, its own namespace: a
#: decision is not a worker — nothing counts it against the cap, `reap()` never
#: looks at it, and its liveness is its stash — so sharing the worker prefix
#: would put it in front of every `board-worker-*` glob in this tree.
DECISION_PREFIX = "board-decision-"

#: Set to `1` to force the old detached-`Popen` path. For a machine with no
#: systemd user manager only — a worker started that way DIES WITH THE TICK when
#: the caller is `board-watch.service`, which is the bug this replaced.
NO_UNIT = os.environ.get("BOARD_WORK_NO_UNIT") == "1"

def unit_name(agent_id, prefix=UNIT_PREFIX):
    return prefix + ba.clean_id(agent_id)


def _start_unit(aid, cmd, env, logpath, title, prefix=UNIT_PREFIX,
                kind="worker", runtime=None):
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
    unit = unit_name(aid, prefix)
    run = ["systemd-run", "--user", "--quiet", "--collect",
           "--unit", unit, "--service-type=exec",
           "--working-directory", REPO,
           "--description", "board %s: %s" % (kind, title[:60]),
           # The 45 minutes `WORKER_TIMEOUT_S` always claimed and a detached
           # Popen could never enforce. One wedged worker must not hold a slot
           # against the cap for the rest of the day.
           "--property=RuntimeMaxSec=%d" % (runtime or WORKER_TIMEOUT_S),
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
    # ...and its NAME, at the same instant, because he asked to be able to refer
    # to a worker as a person rather than as a hex string. It is chosen once and
    # stored in the record (`boardagents.register`), never re-derived on a read,
    # so a card cannot rename itself between two polls. Nothing on disk is keyed
    # on it: the unit, the log and the sidecar below all stay on `aid`.
    name = ba.pick_name(aid)
    session = str(uuid.uuid4())
    # THE TIER THIS ONE RUNS ON, resolved once here so the backend, the flags
    # and the record can never disagree: `dispatch` stored what the planner
    # asked for and `minister_tier` clamps it to something the dial itself
    # could hold. An older record (dispatched before tiering existed, or
    # requeued from `pending/`) names nothing and gets his dial, unchanged.
    flag, effort = minister_tier(" ".join(
        x for x in (rec.get("model") or "", rec.get("effort") or "") if x))
    budget = int(rec.get("turns") or RELAY_TURNS)
    prompt = WORKER_PROMPT.format(
        repo=REPO, host=host_line(), task=rec["task"],
        name=name, aid=aid, phase_words=phase_word_menu(),
        relay=relay_block(budget, int(rec.get("relay") or 0)),
        context=("--- what the orchestrator knows that you do not ---\n%s\n--- end ---\n\n"
                 % rec["context"]) if rec.get("context") else "")
    stub = os.environ.get("BOARD_WORK_SPAWN")
    if stub:
        cmd = ["/bin/sh", "-c", stub]
    else:
        # All the Claude-isms — the model/effort, the cache flags, the trimmed
        # tools, the allowed/denied sets, and the appended RULES system-prompt
        # block — live in the backend. Which backend this task runs on follows
        # THIS TASK'S tier rather than the dial (`get_backend_for_model` on the
        # pair resolved above); a deepseek-tiered minister must reach the hermes
        # backend, not claude carrying a deepseek flag.
        backend = get_backend_for_model(flag)
        cmd = backend.args(
            prompt=prompt, session=session, role="worker",
            label="board: " + rec["task"][:50], model=flag, effort=effort)
        # BEFORE the spawn, and before the header that names it: a backend whose
        # session id we cannot choose is bound by the query instead, and the
        # binding has to be on disk before the run it identifies can appear in
        # that backend's store.
        backend.arm(aid, cmd)
    # `BOARD_ORDER` is HIS sentence, and it rides the environment for the same
    # reason `BOARD_AGENT_ID` does: every `boardctl` this worker runs inherits
    # it, so the bullet it eventually writes can say which of his own asks it
    # came out of without anything having to remember to pass it along
    # (`boardparse.for_now`). Absent when nobody typed an order.
    env = dict(os.environ, BOARD_AGENT_ID=aid, BOARD_WATCH_KEY=aid,
               BOARD_WORK_TASK=rec["task"], BOARD_WORK_SESSION=session,
               BOARD_ORDER=rec.get("order") or "",
               # The relay's own state, on the environment for the reason
               # everything else here is: `boardctl turns` and `boardctl relay`
               # are run by the minister itself, in a shell that inherits this,
               # so neither has to be told which task it is a hop of.
               BOARD_WORK_TURNS=str(budget),
               BOARD_WORK_RELAY=str(int(rec.get("relay") or 0)),
               BOARD_WORK_WHERE=rec.get("where") or "",
               BOARD_WORK_MODEL=flag, BOARD_WORK_EFFORT=effort)
    logpath = _log_path(aid)
    # BEFORE the spawn, so a worker killed at second one still leaves a log that
    # names it and points at its transcript. See "a log that survives a kill".
    log_header(aid, name, rec["task"], session)
    pid = _start_unit(aid, cmd, env, logpath, rec["task"])
    how = "unit"
    if pid is None:
        pid = _start_detached(cmd, env, logpath)
        how = "detached"
    if pid is not None:
        _log_line(aid, ("unit: %s (journalctl --user -u %s)"
                        % (unit_name(aid), unit_name(aid))) if how == "unit"
                  else "started detached, pid %s - no unit" % pid)
    if pid is None:
        # NOTHING STARTED, so no card is registered — and the task must not be
        # left orphaned either. It is already in `taken/` (`dispatch()` writes
        # it there before the spawn, so a crash cannot lose it), and `reap()`
        # skips a `taken/` record with no `agent`: it would have sat there
        # forever, unworked and unreported. Stamping the id we minted is enough
        # for the next tick to file it under `failed/` and put a `FAILED:`
        # bullet quoting his task on the board.
        if rec.get("file"):
            try:
                ba._write_json(rec["file"],
                               {k: v for k, v in dict(rec, agent=aid,
                                                      unit="").items()
                                if k != "file"})
            except OSError:
                pass
        return {"id": aid, "name": name, "pid": 0, "state": "failed",
                "why": "neither systemd-run nor a plain spawn would start it"}
    # UNCONFIRMED: `systemd-run --service-type=exec` returns at the `execve` and
    # not at a running agent (19 ms, measured on book 2026-07-30), so this is a
    # record of a summon in progress and not yet a card. `boardagents._confirmed`
    # publishes it once the agent's own transcript proves it is up; everything
    # that counts workers sees it immediately, which is what stops a starting
    # worker being double-started or reaped as dead.
    ba.register(aid, rec["task"][:70], pid, kind="worker",
                where=rec.get("where") or "", session=session, name=name,
                confirmed=False, model=flag, effort=effort)
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
    return {"id": aid, "name": name, "pid": pid, "session": session,
            "state": "running", "agent": aid, "spawned": how}


# ------------------------------------- a dispatch is a START, never a RESULT
def reported_file(agent_id):
    return os.path.join(work_dir("reported"), ba.clean_id(agent_id) + ".json")


def reported(agent_id):
    """Did this worker put its result on the board before it stopped?

    THE FACT THE CARD WAS MISSING. `reap()` has always known it — it is what
    sorts a worker into `done/` rather than `failed/` — but it only runs on a
    board-watch tick, and until then `boardagents.describe()` called every
    stopped worker `exited without finishing - nothing was committed on its
    behalf`. So a worker that had just committed and reported was drawn as
    abandoned for up to five minutes. [his, 2026-07-30] about exactly that card.

    Two places, because `reap()` deletes the stamp as it files the record: the
    live stamp for a worker that has stopped but not been reaped, and `done/`
    for one that has.
    """
    aid = ba.clean_id(agent_id or "")
    if not aid or aid == "agent":
        return False
    if os.path.exists(reported_file(aid)):
        return True
    try:
        return any(r.get("agent") == aid for r in ba._list(work_dir("done")))
    except OSError:
        return False


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


#: What a TRANSIENT platform death looks like in a worker's log: the CLI
#: printing an API 5xx / overload error and exiting before the first tool call.
#: Board-watch's `spawn` matches the same pattern for the two runs it waits on.
#: Written after 2026-07-29, when an Anthropic outage killed two workers at
#: launch (their whole logs were one line, `API Error: 500` / `529 Overloaded`)
#: and each was reported as FAILED with "type it again to have another go" —
#: asking him to re-type a sentence the system still held verbatim.
TRANSIENT_RE = re.compile(
    r"API Error: (?:5\d\d|Connection closed)|Overloaded", re.I)


def _died_transiently(aid):
    """Did this worker's log END on a transient API error?

    The tail only: a worker that hit a 500 mid-run and kept going died of
    whatever it eventually died of, not of the 500.
    """
    try:
        with open(_log_path(aid), "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 1000))
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return False
    return bool(TRANSIENT_RE.search(tail))


# ------------------------------------- force-stopping ONE bound minister
def _stop_unit(unit):
    """SIGKILL one transient unit's whole cgroup, synchronously. (ok, detail).

    `systemctl --user kill --signal=KILL` signals every process in the unit's
    control group at once and returns at once, so a minister that would ignore
    SIGTERM dies anyway, and `--collect` (set at `systemd-run` time) reaps the
    unit afterwards. `ok` is None when systemctl could not be RUN at all — no
    user manager — which the caller must NOT read as "stopped": it falls back to
    the pid. A non-zero exit for a unit that is already gone is not an error
    here either. Liveness, re-read by `force_stop`, is the only verdict.
    """
    if not shutil.which("systemctl"):
        return None, "no systemctl"
    try:
        p = subprocess.run(
            ["systemctl", "--user", "kill", "--signal=KILL", unit],
            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return None, str(e)
    return (p.returncode == 0), (p.stderr or "").strip()


def _kill_pid(pid):
    """Last-resort SIGKILL for a minister with no unit — the detached fallback
    on a box with no user manager. The process group first (a detached worker
    leads its own session, `start_new_session=True`), then the pid itself in
    case it is not a leader. Best effort: `force_stop` verifies liveness after,
    whatever this reached."""
    if not pid:
        return
    for send in (lambda: os.killpg(pid, signal.SIGKILL),
                 lambda: os.kill(pid, signal.SIGKILL)):
        try:
            send()
        except OSError:
            pass


def force_stop(agent_id):
    """Force-stop ONE bound minister, and report what is ACTUALLY true after.

    docs/DESIGN.md §10 forbids OFFERING an action that can silently fail, and
    §10.3 makes a SIGKILL a menu entry rather than a click for the reason that
    it cannot be undone. So this never reports success off a command's own exit
    code: it stops the minister's own transient systemd unit (or, with no user
    manager, SIGKILLs its process group), then RE-READS the one liveness rule
    (`boardagents.agents()` -> `boardmove._alive`) and answers from that.
    Returns {"ok": bool, "msg": <one line for him, addressed as "you">}.

    Only a worker or a decision minister is force-stoppable (`MINISTER_ROLES`):
    each runs as its own unit, so the kill is a real, reportable act. Solomon is
    refused — the orchestrator is a brief planning burst that holds the
    board-watch tick and then delegates, its resting card has no process at all
    to stop, and killing it mid-plan would abandon a dispatch you asked for. A
    deepseek subminister has no unit of its own: it lives inside its parent
    minister's cgroup, so force-stopping that parent takes it down with it.
    """
    aid = ba.clean_id(agent_id)

    def find():
        return next((a for a in ba.agents() if a.get("id") == aid), None)

    rec = find()
    if rec is None:
        return {"ok": False,
                "msg": "no such minister - it may have already gone"}
    name = rec.get("name") or aid
    kind = rec.get("kind") or ""
    if kind == ba.ORCHESTRATOR_KIND:
        return {"ok": False, "msg": "Solomon is not force-stopped from here"}
    if kind not in MINISTER_ROLES:
        return {"ok": False,
                "msg": "%s runs inside its minister - stop that one" % name}
    if rec.get("state") != "running":
        return {"ok": True, "msg": "%s had already stopped" % name}

    prefix = DECISION_PREFIX if kind == "decision" else UNIT_PREFIX
    ok, _detail = _stop_unit(unit_name(aid, prefix))
    if ok is not True:
        _kill_pid(rec.get("pid") or 0)

    # THE ONLY VERDICT is whether it is really gone. A SIGKILL leaves the process
    # a zombie until systemd reaps it, and `_alive` reads a zombie as dead, so
    # the very next read is already true — the short poll only covers the reap.
    for _ in range(10):
        after = find()
        if after is None or after.get("state") != "running":
            return {"ok": True, "msg": "%s force-stopped" % name}
        time.sleep(0.03)
    return {"ok": False,
            "msg": "could not stop %s - it is still running" % name}


def reap():
    """Close out every worker whose process has gone.
    Returns (done, failed, requeued).

    Run at the top of every board-watch tick, beside `reconcile()`, `sweep()`
    and `promote()` — same shape, same worst case of one timer interval.

    A `failed` record is not bookkeeping: **the caller puts it on his board**. A
    worker that stops without recording anything did not do the work, and the
    one thing this system must never do is let that read as done. It is also the
    only trace such a worker leaves, since its registration is dropped by
    `sweep()` and its card leaves the list the moment it dies.

    ...with ONE exception: a worker that recorded nothing AND whose log ends on
    a transient API error is REQUEUED once instead of failed — its task goes
    back to `pending/` carrying a `retried` mark, and `promote()` (same tick)
    spawns a fresh worker for it. The second death is final, whatever its
    cause, so this cannot loop; and a worker that reported anything at all is
    `done` as before, never re-run — re-running half-landed work would commit
    it twice.

    A dead worker's TAKEN inbox notes go back to the queue too
    (`boardagents.requeue_taken`), for every worker filed as failed and every
    one requeued on a transient death — a note it `take`-d would otherwise die
    with it, exactly as one did on 2026-07-29. The rescued notes ride on the
    moved record as `rec["notesBack"]` rather than widening the return tuple:
    a board-watch deployed before this change still unpacks three values.
    A worker reaped as DONE keeps its taken notes, on purpose: it reported,
    so it is presumed to have handled what it took.
    """
    live = {a["id"] for a in ba.agents() if a["state"] == "running"}
    done, failed, requeued = [], [], []
    for rec in ba._list(work_dir("taken")):
        aid = rec.get("agent")
        if not aid or aid in live:
            continue          # still working, or dispatched before this existed
        ok = os.path.exists(reported_file(aid))
        if not ok and not rec.get("retried") and _died_transiently(aid):
            _log_line(aid, "requeued after a transient platform error")
            rec = dict(rec, retried=True, agent="", unit="")
            moved = ba._move(rec, work_dir("pending"),
                             state="requeued", by=aid)
            moved["notesBack"] = ba.requeue_taken(aid)
            requeued.append(moved)
        else:
            moved = ba._move(rec, work_dir("done" if ok else "failed"))
            if not ok:
                # It reported NOTHING, which is the case its log is guaranteed
                # to be empty for, so say where the history is — in the log
                # itself, and on the record, so the bullet can quote it rather
                # than tell him nobody knows what happened.
                session = _session_of(aid, rec)
                log_postmortem(aid, session, rec.get("why") or "")
                moved["transcript"] = transcript_hint(session, aid)
                moved["notesBack"] = ba.requeue_taken(aid)
            (done if ok else failed).append(moved)
        try:
            os.unlink(reported_file(aid))
        except OSError:
            pass
    return done, failed, requeued


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
        # The cap counts heads; the FLOOR counts what a head costs. A spawn
        # into memory the machine does not have is not a start — the kernel
        # OOM-kills the slice and the worker dies mid-task, unrecorded. Under
        # the floor the task stays queued and the next tick retries, exactly
        # the "a slot frees" path it already has. `None` (unreadable) opens
        # the gate: a missing /proc must never stop a healthy machine.
        avail = memory_available_mb()
        low = (MEM_MIN_AVAILABLE_MB and avail is not None
               and avail < MEM_MIN_AVAILABLE_MB)
        if low:
            break
        moved = ba._move(rec, work_dir("taken"))
        moved.update(_spawn_worker(moved))
        started.append(moved)
    return started


# ------------------------------------------------------------ what he sees
def _queued_row(t):
    """A dispatched task with no worker on it yet. It is drawn — work that
    exists and is not running is the last thing a control surface may hide —
    and with the phase headings gone its own sentence is what says so."""
    return {
        # No name either, and for the same reason it is offered no inbox:
        # nobody has been spawned for it yet, and naming a worker that does
        # not exist would be the card claiming somebody is on it.
        "id": "", "name": "", "kind": "pending", "title": t.get("task", ""),
        "where": t.get("where", ""), "state": "queued", "running": False,
        "phase": "queued", "says": "", "saysLine": "", "unread": 0,
        "waiting": [],
        # A task with no process has nothing to observe and says so, rather
        # than borrowing the sentence a running card would use.
        "actually": "not started - a minister starts when a slot frees",
        # No working duration either: nothing has been spawned, so nothing is
        # working. The sentence above says so in words, which is truer than a
        # counter at zero would be.
        "doingLine": "", "workedLine": "",
        "detail": "not started - a minister starts when a slot frees"}


def _idle_orchestrator_row():
    """Solomon, standing by. The one row on this list that is not a process.

    [his, 2026-07-29] *"make the main orchestrators name Solomon. he should
    always be kept on the top of the agent list and should basically indicate
    like he's there and ready to go at all times when hes not doing
    something."* So the row is PERSISTENT: it is drawn whenever no orchestrator
    is registered, and the moment board-watch spawns one the real card takes
    the same place at the top with the same name on it.

    It says `ready` and NOTHING ELSE, because that is all that is true. No
    observed line and no inbox of its own — a message left for an orchestrator
    that does not exist would have nobody to read it, and the queue (the box at
    the top of the window) is where such a message already goes. `id` is empty
    for exactly that reason: `AgentRow.addressable` is what draws the box, and
    an unaddressable row does not offer one.

    **It leads with `Solomon awaits`**, like every other card leads with its
    own name — [his, 2026-07-29] the orchestrator's card should read *"Solomon
    is ..."* like the rest, and he said so twice. Putting the name in the name
    column instead was the first answer and it was not what he asked for.

    This is NOT §10.6's forbidden manufactured claim. That rule exists so a
    claim is never derived from an observation, making the two agree by
    construction — and there is no observation here, and no process to observe:
    this row is a placeholder for the absence of an agent, and every word on it
    is written by this function. `doingLine` stays empty, which is the half of
    §10.6 that does bind: nothing pretends to have seen him do anything.
    """
    return {
        "id": "", "name": ba.ORCHESTRATOR_NAME, "kind": ba.ORCHESTRATOR_KIND,
        # [his, 2026-07-29] `hands` is gone from his card: an item goes to a NEW
        # agent as `summoned` and to one already running as `commanded`, the same
        # pair his notes carry. This line used to say "hands out what you type".
        # Then, verbatim and with the full stop, *"summons a minister to do your
        # bidding."* — the whole card is now TWO lines, and the clause about who
        # does the work went with the third one.
        "title": "summons a minister to do your bidding.",
        "where": "", "state": "idle", "running": False,
        # NO observation, deliberately — this row is not a process and there is
        # nothing to observe. The top line is the ONE sentence that is true of
        # him while nothing is happening, in the shape every other card uses.
        # (The LIVE orchestrator's card gets its top line the way every worker
        # does, by claiming a phase, which `ORCHESTRATOR_PROMPT` tells him to.)
        "phase": "ready", "says": "ready",
        # [his, 2026-07-29] *"Solomon awaits"*, not *"Solomon is ready"* - the
        # same verb his `waiting` line uses, so the standing row and the live
        # card say the same thing about the same state. No `...`: nothing is
        # happening on this row and §10 does not let an animation claim there is.
        "saysLine": "%s awaits" % ba.ORCHESTRATOR_NAME,
        "actually": "", "doingLine": "", "observed": "unlinked",
        "contextLine": "", "workedLine": "", "unread": 0, "waiting": [],
        "born": 0.0,
        # NO detail line at all — [his, 2026-07-29] the resting card is two
        # lines and that is all of them. `boardagents.describe()` is what the
        # window actually draws here and it returns "" for `idle`; this stays
        # empty so the two cannot disagree.
        "detail": ""}


def _is_orchestrator(a):
    return (a.get("kind") or "") == ba.ORCHESTRATOR_KIND


def _drawable(rows):
    """The rows that may be DRAWN, i.e. everything whose summon has completed.

    [his, 2026-07-30] A minister's card was appearing while Solomon was still
    summoning it, because the registration is written the instant the spawn
    call returns and that is an `execve`, not a running agent. So the filter
    lives HERE, at the one point that draws — `boardagents.agents()` goes on
    returning every record, which is what keeps the concurrency cap, `reap()`,
    `sweep()` and the inbox seeing a worker that is starting up.
    `boardagents.CONFIRM_GRACE_S` carries the rest of the argument.

    **...and a minister that FINISHED leaves at once, rather than when he next
    touches the board.** [his, 2026-07-30] *"are ministers sometimes staying in
    the triangle unfocused colored until the user clears their completion
    message?"* — they were, and the "sometimes" was a race. A card is only
    deleted from disk by `boardagents.sweep()`, which runs on a board-watch
    tick; the tick that a worker's own final `note` triggers usually runs while
    that worker is still alive, and nothing writes the board again until HE
    replies to the bullet — so clearing the message looked like what removed
    the card, and the 5-minute timer was the only other way out. Liveness is
    polled here every second, so the drawing already knows: a row that is
    `exited` AND `finished` is drawn by nobody, and the reap that follows is
    bookkeeping he does not have to watch.

    A worker that stopped WITHOUT reporting keeps its card, deliberately. Until
    the next tick files it as failed and puts the bullet on his board, that
    dimmed row saying `exited without finishing` is the only visible trace that
    anything was lost.
    """
    return [a for a in rows
            if a.get("confirmed", True)
            and not (a.get("state") == "exited" and a.get("finished"))]


def cards(agents=None, pend=None):
    """Every card the window draws, ONE FLAT LIST, oldest first.

    **Solomon is pinned to the top, always** — [his, 2026-07-29] *"he should
    always be kept on the top of the agent list"*. The orchestrator is not one
    more worker: it is the thing that read what he typed and decided who got
    what, so it is the row he looks at first and it may not slide down the list
    as workers are born. Birth-order governs everything BELOW it, unchanged.
    And when no orchestrator is running at all, `_idle_orchestrator_row()`
    holds that place rather than leaving a gap — so the top of this list says
    the same thing whether or not anything is happening.

    His call, and the reason is the moving: *"maybe for now take out the
    'coding' 'Testing' 'finishing touches' text and just keep agents ordered by
    birth/age so they dont move around so much"*. A card used to jump between
    phase sections every time the agent picked up a different tool, which made
    the list unreadable while it was working. Ordered by birth, a new agent
    appends at the BOTTOM and nothing above it moves for the rest of its life —
    not when it changes phase, and not when it stops.

    The phase itself did not go anywhere: `boardphase.py` still derives it from
    the transcript, it still cannot be set by the agent, and it is still what
    the observed sentence on the card is built from. What went is the grouping.

    **Ordering is not an age.** `born` never reaches the screen (see
    `boardagents.born`), nothing here counts, and queued tasks sit after the
    live ones because they have no birth yet — not because they are less
    urgent. There is no urgency in this app.
    """
    rows = _drawable(ba.agents() if agents is None else agents)
    # HIS OWN SESSIONS ARE NOT BOARD WORK — [his, 2026-07-31] *"agents started
    # by the user can be hidden from the triangle"*. The anonymous `session`
    # rows that `boardagents.agents()` walks out of /proc — bare interactive
    # Claude Code sessions with no name and no `--where`, e.g. "s831183 an
    # interactive Claude Code session" — are HIS terminals, not summoned
    # ministers, so they are dropped here at the one surface that draws the
    # triangle. Deliberately NOT in `_drawable()`: `groups()` (which is what
    # `boardctl.py agents` lists) keeps showing them, because that is an
    # agent-facing collision check where a live session of his still matters.
    # Board-dispatched workers (named rows) and Solomon are unaffected —
    # neither is ever a `session`.
    rows = [a for a in rows if a.get("kind") != "session"]
    # A SUBMINISTER IS NOT A TOP-LEVEL CARD. It is a transient deepseek run a
    # minister (or Solomon) delegated a chunk to; the board draws it INSET under
    # its parent's row, not as one more card in the flat list. `main.py`/`qml`
    # (Murmur) reads it off the `boardagents.agents()` walk by `kind`/`parent`
    # and interleaves it — so it is dropped here, exactly like a `session`.
    rows = [a for a in rows if a.get("kind") != "subminister"]
    pend = pending() if pend is None else pend
    out = sorted(rows, key=lambda a: (float(a.get("born") or 0.0), a["id"]))
    orch = [a for a in out if _is_orchestrator(a)]
    rest = [a for a in out if not _is_orchestrator(a)]
    # Two overlapping orchestrators are both Solomon and both pinned, in birth
    # order — one role, briefly doing two things, and saying so beats hiding
    # the second one (`boardagents.ORCHESTRATOR_NAME`).
    return (orch or [_idle_orchestrator_row()]) + rest \
        + [_queued_row(t) for t in pend]


def groups(agents=None, pend=None):
    """The same cards bucketed by phase — `boardctl.py agents`' listing, and no
    longer what the window draws (`cards()` is, flat and birth-ordered).

    A terminal listing has no cursor to move under and no rows to keep still,
    so the phase sections are still the useful shape there. Empty phases are
    not returned.
    """
    rows = _drawable(ba.agents() if agents is None else agents)
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
        buckets["queued"].append(_queued_row(t))
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
    if key in d["answers"]:
        return False                 # already known (answered or not)
    # An empty `answers` is the RESTING state (NEEDS YOU empty), not "first run
    # pending" — `answers` only ever holds the DECISIONS CURRENTLY in NEEDS YOU,
    # so it is empty whenever the list is empty, which is now the resting state.
    # Bailing on it meant a question asked on a resting board was NEVER seeded,
    # so its first sighting was an unknown key and, if the answer landed in the
    # same window, board-watch's "answered before its first sighting" path fired
    # a decision agent on it (see board-watch.py tick() hazard 2 / commit 1016f38).
    # The explicit `seeded` flag owns the "board-watch has never run" distinction,
    # not a non-empty `answers`; a watcher with no state file at all fails the
    # `open` above and is recorded by its own first run.
    # `fingerprint()` of an unanswered item carries the `|on:` host suffix since
    # host-affinity landed; the old literal here ("idx:|ans:") never matched it,
    # so even a question that DID get seeded still looked fingerprint-changed on
    # its first real sighting. Keep this string in lockstep with board-watch's
    # `fingerprint()` (apps/srvs/board-watch.py) — it is the same canonical shape.
    d["answers"][key] = "idx:|ans:|on:"
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
