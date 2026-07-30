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
been working"* — `boardphase.worked_line`, `working for 4 minutes`, live. An
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


# ------------------------------------------------- which model orchestrates
#: The models the dropdown beside the box offers, in the order it draws them.
#: [his, 2026-07-29] *"add a drop down to the right of the top prompt box that
#: allows the user to select which model they wish the orchestrator to be."*
#:
#: `(flag, label)`. The flag is what `--model` gets; the label is what he reads,
#: lowercase like every other string this desktop authors (docs/DESIGN.md §7.2).
#: **Full names, not the `opus`/`sonnet` aliases** — an alias means "the latest
#: of that family" and would silently re-point his choice the day a new one
#: ships, which is exactly the thing a chooser exists to stop.
ORCH_MODELS = [
    ("claude-fable-5", "fable 5"),
    ("claude-opus-5", "opus 5"),
    ("claude-sonnet-5", "sonnet 5"),
    ("claude-haiku-4-5-20251001", "haiku 4.5"),
]

#: What orchestrates when he has never chosen. Unchanged from the value that was
#: hardcoded in `ROLES` before the chooser existed, so adding the control moved
#: no behaviour on its own.
DEFAULT_ORCH_MODEL = "claude-fable-5"


def orch_model_file():
    return os.path.join(_root(), "orch-model")


def orch_model():
    """The model the NEXT orchestrator spawns with.

    Read at spawn time, never cached, which is the whole of his rule for a
    change made mid-run: *"if this changes in the middle of the orchestrator
    working, simply change it to the defined model on the next prompt it
    recieves."* A running session keeps the model it started with — nothing can
    change that from outside — and the next prompt off the queue reads this file
    again. No signal to plumb, no restart, and nothing to reconcile.

    An unreadable or unrecognised file falls back to the default rather than
    passing an unknown string to `--model`, where the failure would be a spawn
    that dies with a CLI usage error and a FAILED bullet he has to decode.
    """
    try:
        with open(orch_model_file()) as f:
            got = f.read().strip()
    except OSError:
        return DEFAULT_ORCH_MODEL
    return got if got in {m for m, _ in ORCH_MODELS} else DEFAULT_ORCH_MODEL


def resolve_model(name):
    """A model from what somebody typed. Exact flag, exact label, or one
    unambiguous case-insensitive substring of either — the same forgiveness
    `boardctl`'s selectors give for the same reason (the caller is a person at a
    terminal or a language model holding a half-remembered name), and the same
    refusal: ambiguity is an error, never a guess.
    """
    want = (name or "").strip().lower()
    if not want:
        raise ValueError("no model named")
    for flag, label in ORCH_MODELS:
        if want in (flag.lower(), label.lower()):
            return flag
    hits = [f for f, lab in ORCH_MODELS
            if want in f.lower() or want in lab.lower()]
    if len(hits) == 1:
        return hits[0]
    if hits:
        raise ValueError("%r matches %s - be more specific"
                         % (name, ", ".join(hits)))
    raise ValueError("not a model this board offers: %r (have: %s)"
                     % (name, ", ".join(f for f, _ in ORCH_MODELS)))


def set_orch_model(flag):
    """Choose it. Same atomic write as `set_cap`: this file is read by a spawner
    that may fire at any moment, so a half-written one must be impossible."""
    flag = resolve_model(flag)
    os.makedirs(_root(), exist_ok=True)
    tmp = orch_model_file() + ".tmp"
    with open(tmp, "w") as f:
        f.write(flag + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, orch_model_file())
    return flag


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
#: already settled (see `home/srvs/board-watch-files/board-watch.py`), and the
#: two new prompts below quote them verbatim rather than paraphrasing.
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
`AGENTS.md` to the section rather than swallowing it. Budget your context \
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
actually given. Then say what you found, fixed or left."""

WORKER_PROMPT = """You are running headless, with no human watching, on the \
machine {host}. Work in `{repo}`.

**You are {name}.** That is the name on your card on his board and the name the \
orchestrator used when it wrote down who was handed what, so it is the name he \
will use if he types something at you. Your id is `{aid}`; it is what your \
systemd unit, your log and your inbox are keyed on, and it is what the tools \
below want when one asks for an agent id.

An orchestrator split up something he asked for and gave you one piece of it. \
This is your whole job; another agent has the rest, and may be editing other \
files in this same checkout right now.

--- your task ---
{task}
--- end ---

{context}
RULES, in force for this session, and not negotiable:

{rules}

8. **Say what you are working on.** He is looking at a card for this agent, and \
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

9. **ONE BOARD ITEM PER ASK, and record each one AS IT FINISHES.** [his, \
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

   That is what the LANDED section is: what actually reached his machine. You \
have no IN FLIGHT row and you do not need one — `land` with no selector simply \
records the commit, and reads its time out of git itself.

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
`COMPLETION:` it is done and on his machine; `PARTIAL:` some of it landed and \
some did not, a rebuild being pending counts; `FAILED:` nothing landed; \
`QUESTION:` you need a word from him before anything else moves; \
`INFORMATION:` a fact, nothing asked of him.

   `docs/board.md` is a store three programs parse and write concurrently; \
every edit is a targeted line edit under a lock. Do not open it in an editor. \
`docs/` is its own git repo inside this checkout, so commit from inside `docs/`.

   **Run it even if you finished nothing** — say what stopped you. A worker \
that ends without recording anything is reported on his board as having stopped \
without finishing, which is deliberate: he must never be told something landed \
when it did not. That report is the only thing you cannot leave behind.

10. **If you genuinely cannot decide something only he can decide, ASK — do not \
guess big:**

       python3 apps/board/tools/boardctl.py ask '<the question>' \\
           --context '<what you found that raises it>' \\
           --option '<one way>' --option '<another way>' \\
           --if-unanswered '<what you will do / what stays undone>'

   It appears in the questions list on his board and he answers at his leisure. \
Then finish the part you CAN do and stop; there is nobody to wait for.

11. **You can be reached WHILE you run. Check between steps:**

       python3 apps/board/tools/boardctl.py inbox take --quiet

   Your stdin is closed, so a file is the only channel there is. Run it after \
each meaningful step and once more before you write your final note. Two things \
arrive that way. **Him**, typing at you mid-flight — a correction, an extra \
idea — and that OUTRANKS this prompt where the two disagree. Or **the \
orchestrator**, handing you a further item because you are already in those \
files: that is part of your job now, and your final note says what you did with \
it. Take them either way — an unread note is handed to somebody else later.

There is nobody to ask. Finish, or write down why you did not.
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
worker sees only this>' --where '<the files it will touch>'

    python3 apps/board/tools/boardctl.py ask '<the question>' \\
        --context '<what makes it a question>' \\
        --option '<one way>' --option '<another way>' \\
        --if-unanswered '<what happens if he never answers>'

    python3 apps/board/tools/boardctl.py note 'INFORMATION: **<subject>** - \
<one line>'

    python3 apps/board/tools/boardctl.py cap <n>      # a SETTING, applied now

    python3 apps/board/tools/boardctl.py agents       # who is running, and on what

    python3 apps/board/tools/boardctl.py phase reading --doing '<one short \\
line>'

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
  * **Hand over only what is genuinely the same work.** An item that can stand \
on its own gets its own worker even if it is nearby, because a handoff waits on \
somebody else's pace. In two minds: dispatch.
  * A handoff takes no slot against the cap — a consequence, never a reason. Do \
not hand work over to get under the cap; `dispatch` queues what is over it and \
a later tick starts it.
  * **Report it exactly like a dispatch** — one line, `INFORMATION:`, naming \
the worker it went to: `handed to Marbas (`wd690a4`), already in those files`.

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

RULES that bind you and every worker you dispatch:

{rules}

YOUR NOTE REPORTS A START, NOT A RESULT — AND IT IS TWO LINES, NOT A \
PARAGRAPH. Finish with one `note`, to this budget: **one line per task you \
handed out, one line per question you asked, about a dozen words each after \
the tag at the most, and no second paragraph.** Every line STARTS WITH A TAG, \
then that short summary, then nothing — his rule for this list, and the tool \
refuses a line without a tag or with a longer first line. Yours are `INFORMATION:` for a task you handed out or a knob you \
turned, and `QUESTION:` for one you asked him. A task line is then the subject, \
the worker's NAME, and that it was handed out with nothing landed yet — like:

    INFORMATION: **landed section + commit times** - handed to Marbas \
(`wd690a4`), nothing landed yet.

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
#: The orchestrator's model is HIS, chosen in the dropdown beside the box and
#: read out of `orch_model()` at spawn — the `""` here is not "inherit", it is
#: "ask the file", and `role_flags` does. Its EFFORT stays pinned high: he chose
#: a model, not a thinking budget, and the argument above for buying the
#: orchestrator's judgement is about the run's shape, not about which family it
#: belongs to.
ROLES = {
    "orchestrator": ("", "high"),
    "worker": ("claude-opus-5", "medium"),
    "decision": ("claude-opus-5", "medium"),
}


def role_flags(role):
    """argv fragment selecting the model and effort for `role`.

    Overridable per role by environment, following the `BOARD_*` convention the
    spawn stubs already use, so a harness can re-point or neutralise it:
    `BOARD_ORCH_MODEL` / `BOARD_ORCH_EFFORT`, `BOARD_WORKER_MODEL` /
    `BOARD_WORKER_EFFORT`, `BOARD_DECISION_MODEL` / `BOARD_DECISION_EFFORT`.
    Set one to the empty string to drop the flag and inherit the default.
    """
    model, effort = ROLES.get(role, ("", ""))
    if role == "orchestrator":
        model = orch_model()          # his choice, re-read on every spawn
    prefix = "BOARD_" + ("ORCH" if role == "orchestrator" else role.upper())
    model = os.environ.get(prefix + "_MODEL", model).strip()
    effort = os.environ.get(prefix + "_EFFORT", effort).strip()
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


def dispatch(task, phase="", where="", context="", cap_=None):
    """One piece of work -> one worker, or -> the pending queue if we are full.

    Returns the task record with `state` in `running` / `queued`. It never
    raises on a full board and never silently drops: the two outcomes are the
    two directories, and `promote()` is what moves between them.

    `rec["overlaps"]` carries the live workers whose `--where` overlaps this
    one (`overlaps()` above) — computed before the spawn, so the new worker
    is never its own hit. WARN ONLY: it changes nothing about what was
    dispatched; `boardctl dispatch` prints it and the caller decides.
    """
    task = " ".join((task or "").split())
    if not task:
        return None
    rec = {"task": task, "phase": (phase or "").strip().lower(),
           "where": (where or "").strip(), "context": (context or "").strip(),
           "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "sent": time.time(),
           "host": os.uname().nodename}
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
    # ...and its NAME, at the same instant, because he asked to be able to refer
    # to a worker as a person rather than as a hex string. It is chosen once and
    # stored in the record (`boardagents.register`), never re-derived on a read,
    # so a card cannot rename itself between two polls. Nothing on disk is keyed
    # on it: the unit, the log and the sidecar below all stay on `aid`.
    name = ba.pick_name(aid)
    session = str(uuid.uuid4())
    prompt = WORKER_PROMPT.format(
        repo=REPO, host=host_line(), task=rec["task"], rules=RULES,
        name=name, aid=aid, phase_words=phase_word_menu(),
        context=("--- what the orchestrator knows that you do not ---\n%s\n--- end ---\n\n"
                 % rec["context"]) if rec.get("context") else "")
    stub = os.environ.get("BOARD_WORK_SPAWN")
    if stub:
        cmd = ["/bin/sh", "-c", stub]
    else:
        cmd = ["claude", "-p", prompt,
               "--session-id", session,
               *role_flags("worker"),
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
        return {"id": aid, "name": name, "pid": 0, "state": "failed",
                "why": "neither systemd-run nor a plain spawn would start it"}
    ba.register(aid, rec["task"][:70], pid, kind="worker",
                where=rec.get("where") or "", session=session, name=name)
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
            rec = dict(rec, retried=True, agent="", unit="")
            moved = ba._move(rec, work_dir("pending"),
                             state="requeued", by=aid)
            moved["notesBack"] = ba.requeue_taken(aid)
            requeued.append(moved)
        else:
            moved = ba._move(rec, work_dir("done" if ok else "failed"))
            if not ok:
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
        "actually": "not started - a worker starts when a slot frees",
        # No working duration either: nothing has been spawned, so nothing is
        # working. The sentence above says so in words, which is truer than a
        # counter at zero would be.
        "doingLine": "", "workedLine": "",
        "detail": "not started - a worker starts when a slot frees"}


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

    **It leads with `Solomon is ready`**, like every other card leads with its
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
        "title": "hands out what you type, and does none of the work himself",
        "where": "", "state": "idle", "running": False,
        # NO observation, deliberately — this row is not a process and there is
        # nothing to observe. The top line is the ONE sentence that is true of
        # him while nothing is happening, in the shape every other card uses.
        # (The LIVE orchestrator's card gets its top line the way every worker
        # does, by claiming a phase, which `ORCHESTRATOR_PROMPT` tells him to.)
        "phase": "ready", "says": "ready",
        "saysLine": "%s is ready" % ba.ORCHESTRATOR_NAME,
        "actually": "", "doingLine": "", "observed": "unlinked",
        "contextLine": "", "workedLine": "", "unread": 0, "waiting": [],
        "born": 0.0,
        # The detail line no longer repeats `ready` — the line above it says so
        # now, and §9.1 suppresses metadata a card has already stated.
        "detail": "what you type at the top of this window goes to him"}


def _is_orchestrator(a):
    return (a.get("kind") or "") == ba.ORCHESTRATOR_KIND


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
    rows = ba.agents() if agents is None else agents
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
