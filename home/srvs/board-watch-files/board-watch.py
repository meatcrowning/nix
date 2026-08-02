#!/usr/bin/env python3
"""board-watch — spawn ONE headless agent when he newly answers a board decision.

`~/nix/docs/board.<hostname>.md` — one board per machine — is where he answers
the questions agents park for him
(`apps/board/AGENTS.md`). Until this existed, an answer sat there until he next
opened a terminal and told somebody about it. This closes that loop: the answer
itself is the trigger.

Deployed to ~/.config/scripts by home/srvs/board-watch.nix, which also carries
the systemd units and the reasoning for the mechanism. Read that file first.

WHAT IT WILL AND WILL NOT DO — his two decisions, and they are settled:

  * The agent WORKS, and since 2026-07-29 it MAY REBUILD AND RELOAD — at its
    own judgement, any hour, under `~/nix/AGENTS.md` -> "When it is okay to
    rebuild or hot-reload" and nothing looser. It used to be the reverse (never,
    work left undone with a note) and he lifted it himself: *"it should be any
    time but should still adhere to the rule that's written down SOMEWHERE"*.
    Two consequences worth stating: the rule lives in `AGENTS.md` and NOT in
    this prompt — a fifth paraphrase is how it came to be true nowhere — and
    what an agent runs or deliberately leaves pending still has to be SAID on
    the board, because he is at the machine while it happens.
  * It fires only while he is AT the machine. Away, asleep or locked, the answer
    is QUEUED, not dropped — see gate() and the "no state update" trick below.

AND IT TAKES THE ITEM OFF HIM. Answering used to leave the decision sitting in
NEEDS YOU for the whole run, so the board went on asking him for something he
had already given. Now the decision is lifted OUT of NEEDS YOU — raw lines
stashed, nothing written in its place — as the agent is spawned, and one of
three things brings it back: the agent lands it (`boardctl land`, which the
prompt below tells it to use), the agent fails and `give_back()` puts the
decision back byte-for-byte with a bullet saying so, or this process is killed
outright and the NEXT tick's reconcile() sees a dead owner pid and does the
same. A decision cannot be away from the board with nothing working on it for
longer than one timer interval. All of that mechanism is
`apps/board/boardmove.py`; read its docstring. (It wrote an `## IN FLIGHT` row
as well until 2026-07-30; the section is gone, the stash is not.)

Consequence worth knowing: an item that has been moved out of NEEDS YOU is no
longer fingerprinted, so **taking an item off NEEDS YOU by hand suppresses the
auto-spawn for it**. That is correct — work is already underway — but it means
whoever moves it owns doing the work.

AND HE CAN TALK TO IT WHILE IT RUNS. The board app draws a box against every
running agent, because he asked to be able to send "commands / new ideas /
fixes" to one mid-flight. An agent's stdin is closed, so a message is a FILE:
the prompt below tells every agent to run `boardctl.py inbox take` between
steps, `BOARD_AGENT_ID` names its inbox, and anything nobody reads is swept into
a queue that a run of this script works on its own (`work_the_queue`). The
mechanism, and the argument that nothing he types can be lost, are in
`apps/board/boardagents.py`'s docstring.

AND IT ORCHESTRATES. The board app now opens with ONE box — free text, enter,
into that same inbox — because he asked for a control surface: *"a single box
that i could type things into, press enter, and have them sent to an inbox. then
an agent figures out what agents to assign to what"*. So `work_the_queue` no
longer spawns an agent that does the job; it spawns an ORCHESTRATOR that splits
the input up and either `dispatch`es workers or `ask`s him a question in NEEDS
YOU. `apps/board/boardwork.py` owns the verbs, the concurrency cap and the
prompt; read its docstring before changing any of it. Three consequences here:

  * **This run is waited on; the workers it starts are not.** A worker runs as
    its OWN transient systemd unit, so four 45-minute runs cannot hold this
    script's flock — a decision he answers five minutes later still fires on
    time. It has to be a unit and not merely a detached child: this is a
    `oneshot`, and a detached child stays in the oneshot's cgroup, so every
    worker was being killed seconds after it started while the board reported
    the work as dispatched and in hand (`boardwork._spawn_worker`, 2026-07-29).
    The orchestrator IS waited on, at a much shorter timeout, because its
    failure has to put his own sentence back on the board and there is nobody
    else left to do it.
  * **A dispatch is a start, not a result.** `reap()` closes out every worker
    whose process has gone, and one that never recorded anything gets a bullet
    saying so. He must never be told something landed when it did not.
  * **A tick also PROMOTES work dispatched above the cap.** Same shape and same
    guarantee as `reconcile()` and `sweep()`: worst case one timer interval.
  * **Every spawn passes `--session-id`.** It is how his board says what an
    agent is actually doing rather than only that it is alive — see
    `apps/board/boardphase.py`. Losing that flag degrades every card silently.

THE THREE HAZARDS, and how each is defended:

  1. THE FEEDBACK LOOP. An agent that works a decision edits board.md itself
     (moving the item to LANDED), which fires the watcher again, forever. The
     defence is SEMANTIC, not authorship-based — do not try to work out who
     wrote the file, because the honest answer is often "a git merge". Instead
     fingerprint only the ANSWER-BEARING state of each decision (which options
     are ticked, plus his free text) and fire only when a decision that was
     already known becomes newly answered. An item moving to LANDED, a reworded
     paragraph, a new question, a decision taken off the list: no new answer, no fire.
  2. THE SYNC ALSO WRITES. nix-docs-sync pulls the other machine's copy every
     five minutes with no human in the loop. Same filter handles the rewordings
     and the moved rows — but an ANSWER that arrives that way is a special case,
     and it is the reason for hazard 4.
  4. TWO WATCHERS, ONE FILE. This unit runs on `top` and on `book` (it was
     `top`-only until 2026-07-29, which was simply wrong — an answer typed on
     book did nothing until he was next at the desktop). Both machines see the
     same `[x]`, so firing on content alone would put two agents on one job, on
     two checkouts of the same two repos, both committing and both pushing. The
     defence is HOST AFFINITY, and it is by construction rather than by
     agreement: the board app stamps the machine he answered on, `fingerprint()`
     carries the stamp and `owns()` fires only for this host. Nothing is
     claimed, nothing is negotiated, and neither machine ever has to know
     whether the other is switched on. See HOST/DEFAULT_HOST/owns() below.
  3. CONCURRENCY. Two rapid edits must not put two agents on one shared git
     index. flock() below, plus systemd's own refusal to run a oneshot twice.
     (Per machine — hazard 4 is the cross-machine half, and no lock can be.)

FIRST RUN records the whole board and fires nothing: three of his decisions are
already answered, and waking up to three agents is not the feature. Two things
that cost a live hot loop on 2026-07-28 and are now rules:

  * **"First" is an explicit marker in the state file, never an inference from
    the board being empty.** An empty NEEDS YOU is the resting state now.
  * **A first run still DRAINS THE QUEUE.** Seeding is about not acting on
    answers that predate this script; a sentence he typed into the box is not
    one of those, and the queue's trigger is level-triggered, so a run that
    leaves it full is a run that gets started again immediately.

AND IT WILL NOT SPIN. `spin_guard()` backs the whole tick off to one run a
minute once several in a row have ended with the queue no emptier than they
found it, whatever the cause; `board-watch.nix` sets a systemd start limit above
that as the net for a runaway that never reaches this code at all.

TESTING. Every side effect is overridable by environment, so the trigger, the
filter, the queue and the dedupe can be exercised without spawning anything:

    BOARD_WATCH_BOARD       store to read (default: this host's own board,
                            `boardparse.board_path()`)
    BOARD_WATCH_STATE       state dir    (default ~/.local/state/board-watch)
    BOARD_WATCH_LOG         log file     (default ~/.cache/board-watch.log)
    BOARD_WATCH_SPAWN       command run INSTEAD of `claude`; the prompt arrives
                            on stdin and $BOARD_WATCH_KEY names the decision
    BOARD_WATCH_GATE        force the at-the-machine gate: `open` or `closed`
    BOARD_WATCH_REPO        the checkout the agent works in (default ~/nix)
    BOARD_ORCH_TIMEOUT      seconds an orchestrator run may take (default 900)
    BOARD_ORCH_MODEL        `--model` for the orchestrator (default
    BOARD_ORCH_EFFORT       claude-fable-5 / high); the WORKER_ and DECISION_
                            pair are his minister choice and are CLAMPED to
                            `boardwork.MINISTER_CEILING` — they can lower a
                            minister, never raise one. See `boardwork.ROLES`.
    BOARD_WORK_SPAWN        command run INSTEAD of `claude` for a WORKER
    BOARD_MAX_WORKERS       the concurrency cap, overriding the file
    BOARD_MAX_SUMMONERS     how many orchestrators one tick may run at once,
                            overriding the file (default 1)
    BOARD_WATCH_SPIN_LIMIT  undrained runs in a row before the backoff (8)
    BOARD_WATCH_SPIN_WINDOW seconds the streak has to have started within (60)
    BOARD_WATCH_SPIN_BACKOFF  seconds a backed-off run sleeps for (60)
    BOARD_WATCH_HOST        pretend to be this machine (default: the hostname)
    BOARD_WATCH_DEFAULT_HOST  who works an UNSTAMPED answer (default `top`)

`tools/board-watch-test.py` drives all of them against a throwaway copy.
"""
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
REPO = os.environ.get("BOARD_WATCH_REPO", os.path.join(HOME, "nix"))
STATE = os.environ.get("BOARD_WATCH_STATE",
                       os.path.join(HOME, ".local", "state", "board-watch"))
LOG = os.environ.get("BOARD_WATCH_LOG", os.path.join(HOME, ".cache", "board-watch.log"))

# ------------------------------------------------------------ HOST AFFINITY
#: WHICH MACHINE THIS IS. This unit runs on `top` AND on `book`. Since
#: 2026-07-30 each watches its OWN board — `docs/board.top.md` /
#: `docs/board.book.md`, resolved by `boardparse.board_path()` below — so the
#: `[x]` this one reads was typed on this machine by construction and no answer
#: can be seen twice.
#:
#: The stamp below is therefore belt-and-braces now, not the de-duplicator it
#: was when there was one shared file. It is kept: it costs nothing, and it is
#: what makes a board restored from the other host's synced copy harmless.
#:
#: **The host an answer was typed on works it.** The board app stamps it
#: (`boardparse.set_answer_host`, an HTML comment the parser owns), the
#: fingerprint below carries it, and `owns()` is the whole filter. Race-free by
#: construction: nothing is claimed, nothing is negotiated, and no decision
#: depends on what the other machine is doing or whether it is even switched on.
HOST = os.environ.get("BOARD_WATCH_HOST") or os.uname().nodename

#: ...and who works an answer with NO stamp. Only a hand edit in a text editor
#: produces one now (the app always stamps), plus every answer that predates the
#: stamp. `top` is the desktop that is always on, so it is the default owner;
#: book is shut for days at a time and an unstamped answer would sit unworked.
#: A stated default, not a race: both machines apply the same rule to the same
#: bytes and exactly one of them says yes.
DEFAULT_HOST = os.environ.get("BOARD_WATCH_DEFAULT_HOST", "top")

# The kill switch, and it is deliberately a FILE rather than a nix option or a
# systemd `disable`: he can stop this at 2am with `touch` and no rebuild, and
# home-manager cannot quietly re-enable it on the next switch the way it would
# re-enable a unit he disabled by hand.
OFF = os.path.join(STATE, "off")

# Hard wall on one agent. systemd's TimeoutStartSec sits above it as the outer
# guard; this one is inside the script so the failure is OURS to record on the
# board rather than a silent SIGKILL from the service manager.
AGENT_TIMEOUT_S = int(os.environ.get("BOARD_WATCH_TIMEOUT", "2700"))   # 45 min

sys.path[:0] = [os.path.join(REPO, "apps", "board"), os.path.join(REPO, "apps", "pylib")]
import boardagents as ba                                         # noqa: E402
import boardmove as bm                                           # noqa: E402
import boardparse as bp                                          # noqa: E402
import boardundo as bu                                           # noqa: E402
import boardwork as bw                                           # noqa: E402

#: THIS HOST'S STORE, and it has to be resolved after the imports because the
#: rule lives in `boardparse` — one board per host (`docs/board.<hostname>.md`),
#: stated once there and restated nowhere. `ensure_board()` seeds an empty one
#: on a machine that has never had a board (book's first tick) and hands back
#: the pre-split `board.md` on a checkout where the migration has not landed
#: yet, so this can never end up watching a file he cannot see.
BOARD = os.environ.get("BOARD_WATCH_BOARD") or bp.ensure_board()


# ------------------------------------------------------------------------ log
def _rotate():
    try:
        if os.path.getsize(LOG) > 262144:
            with open(LOG, "rb") as f:
                f.seek(-131072, os.SEEK_END)
                tail = f.read()
            with open(LOG, "wb") as f:
                f.write(tail)
    except OSError:
        pass


def log(msg):
    """Same shape as claude-memory-sync.sh's: `date -Is` then the sentence."""
    line = datetime.now().astimezone().isoformat(timespec="seconds") + " " + msg
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass
    if sys.stderr.isatty() or os.environ.get("BOARD_WATCH_ECHO"):
        print(line, file=sys.stderr)


# ---------------------------------------------------------------- the fingerprint
def fingerprint(item):
    """What "he has answered this" MEANS, reduced to one comparable string.

    Only two things count: which options are ticked, and his free text. Not the
    title, not the prose, not the option labels, not the `if unanswered` line —
    an agent rewording any of those is not an answer, and including them would
    make every editorial pass look like one.

    Option INDEX rather than label for the same reason: a typo fix in an option
    he already chose must not read as him changing his mind.
    """
    ticked = ",".join(str(o["index"]) for o in item["options"] if o["checked"])
    return ("idx:" + ticked + "|ans:" + " ".join(item["answer"].split())
            + "|on:" + (item.get("answerHost") or ""))


def owns(item):
    """Is this answer THIS machine's to work? See HOST above.

    The stamp is part of the fingerprint on purpose, so it is also the HAND-OFF:
    re-answering an item on the other machine restamps it, which reads as a new
    answer there and as an already-recorded one here. That is the whole takeover
    story today — deliberate, one gesture, and it cannot double-fire, because
    only one host is ever named. There is no automatic takeover: a claim would
    have to live in a file that syncs every five minutes, and a five-minute
    window in which both machines believe they own an item is exactly the
    duplicate this exists to prevent.
    """
    h = (item.get("answerHost") or "").strip()
    return h == HOST if h else HOST == DEFAULT_HOST


def working_keys():
    """The decision keys a process on this machine is working RIGHT NOW.

    THE LAST GUARD AGAINST FIRING TWICE, and deliberately the one that depends
    on nothing this system wrote down. Every agent this file spawns carries
    `BOARD_WATCH_KEY=<key>` in its environment (`spawn()`), so a live process
    with that variable set IS the decision being worked — no stash to be stale,
    no registration to have been dropped, no fingerprint to have been rewritten
    by a sync.

    It exists because on 2026-07-30 every one of those bookkeeping routes was
    intact and the decision still fired twice: a rebuild killed the tick, the
    agent lived on, and the stash was the only thing anyone asked. `adopt()`
    and `retire_finished()` fix that path; this one is what catches the next
    path nobody has thought of, and the cost is one pass over `/proc`.

    Own processes only — `/proc/<pid>/environ` is mode 0400 and unreadable for
    anyone else's, which is exactly the right scope: another user's agent is
    not working his board.
    """
    keys = set()
    try:
        pids = [n for n in os.listdir("/proc") if n.isdigit()]
    except OSError:
        return keys
    for n in pids:
        try:
            with open("/proc/%s/environ" % n, "rb") as f:
                blob = f.read(64 * 1024)
        except OSError:
            continue                      # gone, or not ours: neither is a key
        for var in blob.split(b"\0"):
            if var.startswith(b"BOARD_WATCH_KEY="):
                keys.add(var[len(b"BOARD_WATCH_KEY="):].decode("utf-8", "replace"))
                break
    return keys


def item_span(lines, item):
    """The decision's raw lines, `### n. title` to just before the next heading.

    boardparse hands back indices into the raw line list rather than a span, and
    the agent needs the whole item as he wrote it — the prose, the options, the
    `if unanswered` sentence — not a reconstruction.
    """
    start = item["titleLine"]
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^#{2,3}\s", lines[i]):
            end = i
            break
    return "".join(lines[start:end]).rstrip() + "\n"


# ------------------------------------------------------------------- the gate
# "Only while I'm at the machine." Three independent facts, none of them
# guessed: logind says the graphical session is the foreground one, the
# compositor answers and has a lit display, and the panel says it is not locked.
def _run(cmd, env=None, timeout=10):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env=env)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except (OSError, subprocess.SubprocessError):
        return 127, "", "not runnable"


def _graphical_session_active():
    rc, out, _ = _run(["loginctl", "show-user", str(os.getuid()), "-p", "Display",
                       "--value"])
    sid = out.strip()
    if rc != 0 or not sid:
        return False, "logind reports no graphical session"
    rc, out, _ = _run(["loginctl", "show-session", sid, "-p", "Active", "-p", "State"])
    if rc != 0:
        return False, "logind session %s unreadable" % sid
    d = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    if d.get("Active") != "yes" or d.get("State") != "active":
        return False, "session %s is %s/%s (another VT has the seat)" % (
            sid, d.get("Active"), d.get("State"))
    return True, ""


def hypr_env():
    """The env `hyprctl` needs, DISCOVERED rather than inherited.

    The systemd user manager's HYPRLAND_INSTANCE_SIGNATURE is imported once by
    hyprland.lua at compositor start and is then whatever the last thing to run
    `systemctl --user import-environment` said — measured on top 2026-07-28, it
    pointed at a dead nested sandbox instance while the real session ran under a
    different signature entirely. So find the instance whose socket actually
    answers, newest first, and ignore what we were handed.
    """
    xdg = os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
    root = os.path.join(xdg, "hypr")
    try:
        sigs = sorted(os.listdir(root), reverse=True)
    except OSError:
        return None
    for sig in sigs:
        if not os.path.exists(os.path.join(root, sig, ".socket.sock")):
            continue
        env = dict(os.environ, HYPRLAND_INSTANCE_SIGNATURE=sig, XDG_RUNTIME_DIR=xdg)
        rc, _, _ = _run(["hyprctl", "version"], env=env, timeout=5)
        if rc == 0:
            return env
    return None


def _display_lit(env):
    rc, out, _ = _run(["hyprctl", "monitors", "-j"], env=env)
    if rc != 0:
        return False, "hyprctl monitors failed"
    try:
        mons = json.loads(out)
    except ValueError:
        return False, "hyprctl monitors returned nothing parseable"
    lit = [m for m in mons if m.get("dpmsStatus") and not m.get("disabled")]
    if not lit:
        return False, "every display is blanked (dpms off)"
    return True, ""


def _panel_says_locked(env):
    """`qs ipc call lock status` -> "locked" / "unlocked" / None if it cannot ask.

    The lock is the panel's own (Lock.qml, ext-session-lock via Quickshell), not
    hyprlock: `qs ipc call lock activate` is what Super+L and hypridle both run.
    Nothing on this desktop sets logind's LockedHint — checked, neither hypridle
    nor quickshell contains the string — so logind cannot answer this and asking
    it would be a confident lie.

    None (the panel is not running, or is running a build without `lock status`)
    is NOT treated as locked. Blanking on it would mean a panel that failed to
    reload silently switches the whole feature off; the display test above still
    catches the away case within 30s of the auto-lock, since hypridle blanks at
    5m30 and the panel locks at 5m00.
    """
    xdg = env.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
    for disp in sorted(n for n in os.listdir(xdg) if re.fullmatch(r"wayland-\d+", n)):
        e = dict(env, WAYLAND_DISPLAY=disp)
        rc, out, _ = _run(["qs", "ipc", "call", "lock", "status"], env=e, timeout=8)
        if rc == 0 and out in ("locked", "unlocked"):
            return out == "locked"
    return None


def gate():
    """(may_fire, reason). The reason is logged whichever way it goes."""
    forced = os.environ.get("BOARD_WATCH_GATE")
    if forced == "open":
        return True, "gate forced open"
    if forced == "closed":
        return False, "gate forced closed"

    ok, why = _graphical_session_active()
    if not ok:
        return False, why
    env = hypr_env()
    if env is None:
        return False, "no Hyprland instance is answering"
    ok, why = _display_lit(env)
    if not ok:
        return False, why
    locked = _panel_says_locked(env)
    if locked is True:
        return False, "the session is locked"
    if locked is None:
        return True, "at the machine (panel could not be asked about the lock)"
    return True, "at the machine"


# ------------------------------------------------------------------ the state
def load_state():
    """The record. `seeded` is EXPLICIT, and that is the whole point of it.

    It used to be inferred — `first_run = not state["answers"]` — which is the
    same thing only for as long as NEEDS YOU is never empty. An empty NEEDS YOU
    is now the RESTING state (`apps/board/AGENTS.md`), and on 2026-07-28 it
    became the actual one: everything moved off the list or into LANDED, saved
    as `{}`, and from then on every single run decided it was the first. 3,151 of
    them logged `first run: recorded 0 decisions, fired nothing` in a few
    minutes, each returning before the queue was drained and each re-arming the
    level-triggered `board-inbox.path` the instant it exited. Two of his
    sentences sat in the queue through all of it.

    Emptiness is not evidence of anything. Only the marker is.
    """
    try:
        with open(os.path.join(STATE, "state.json")) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {"version": 1, "answers": {}, "queued": [], "runs": [],
                "seeded": False, "spin": {}}
    d.setdefault("answers", {})
    d.setdefault("queued", [])
    d.setdefault("runs", [])
    d.setdefault("spin", {})
    # UPGRADE, for a state file written before the marker existed: the file's
    # EXISTENCE is the evidence, because only a completed run writes one. So it
    # has been seeded, whatever `answers` happens to hold today.
    d.setdefault("seeded", True)
    return d


def save_state(d):
    """Atomically, for the same reason boardparse.write() is: this file is what
    stops a re-fire, and a truncated one would re-fire everything."""
    os.makedirs(STATE, exist_ok=True)
    tmp = os.path.join(STATE, ".state.json.tmp")
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, os.path.join(STATE, "state.json"))


# -------------------------------------------------- telling him it went wrong
#: Every bullet this file writes is `FAILED:` — the tag `boardparse.TODO_TAGS`
#: keeps for "it was attempted and nothing landed". That is the whole reason the
#: tag set is not just his three: these four templates exist so a failure cannot
#: read as information, and the tag now says so in the first word.
#: The first line of each template fits `boardparse.SUMMARY_MAX_WORDS` — about
#: a dozen words after the tag — with the story on indented continuation lines,
#: because these go through the same `add_todo_bullet` checks as everything
#: else and a refused failure note is the one failure this file must not have.
#: `{how}` and the interpolated titles stay OFF the first line for that reason:
#: their length is not this file's to choose.
#:
#: **`oneline(code=True)` brings its OWN backticks — the template must not add
#: a second pair.** A doubled span (``x``) is not a span at all: the empty pair
#: at each end is what `boardparse._CODE` matches, and everything between them
#: reverts to countable prose. That is what refused the dead-worker note below
#: on 2026-07-31 (35 words against a cap of 12), so Halphas died leaving nothing
#: on his board at all — the exact failure this file exists to prevent.
FAIL_TEMPLATE = (
    "- FAILED: **board-watch did not finish decision {num}** - nothing was "
    "committed.\n"
    "    It was {title}; the minister exited {how}. The answer is still "
    "above. Log: `~/.cache/board-watch.log`\n")


#: A worker's process is gone and it never used `note`, `land` or `ask`. It did
#: not finish, and the one thing this system must never do is let that read as
#: done — so it lands in WAITING ON YOU TO DO in words, quoting the task, since
#: by the time this runs the worker's card has already left his board.
#:
#: **What he typed goes in a code span, and through `bp.oneline`.** It is DATA,
#: not prose: the separation checks (`boardparse.check_one_ask`) read `**`, a
#: tag and a phrase counting other work as structure, and a newline in it used
#: to make the template's second line an untagged bullet — either way the note
#: saying a worker died would be refused, which is the one failure this file
#: exists to prevent. Same for `{title}` and `{text}` below.
#:
#: ...and the span is the FORMATTER'S, never the template's — see FAIL_TEMPLATE
#: above for what the doubled pair cost.
WORKER_FAIL = (
    "- FAILED: **a minister stopped without finishing** - it was working on "
    "{task}.\n"
    "    Dispatched from something you typed into the box; it recorded "
    "nothing on this board, so nothing landed for it. Answer or type it "
    "again to have another go. {where}\n")


#: Where to READ what it did, on that same continuation line — one path, not a
#: paragraph. `claude -p` writes its stdout ONCE, at exit, so the `.log` of a
#: worker that was killed is a POINTER rather than a record: since 2026-07-30
#: `boardwork` writes it a header at spawn and a post-mortem at reap, and puts
#: the transcript path on the failed record as `rec["transcript"]`
#: (commit f3d5b4d). Naming that path here saves the hop through the log, which
#: is the hop he has to take at exactly the moment he wants an answer fastest.
#: Older records — and any path where the spawn never recorded a session —
#: carry no such key, so the log-only wording stays as the fallback rather than
#: printing an empty span.
#: The path goes through `bp.oneline(code=True)` for the same reason `{task}`
#: does: it is DATA. A glob (`transcript_hint` returns one when the file is not
#: there yet) must not read as `**` structure, and the span keeps the
#: separation checks off it.
WHERE_LOG = "Log: `~/.cache/board-work/{aid}.log`"
WHERE_TRANSCRIPT = "Transcript: {transcript} (log: `~/.cache/board-work/{aid}.log`)"


def worker_fail_bullet(rec):
    """The FAILED bullet for a worker that recorded nothing."""
    aid = bp.oneline(rec.get("agent") or "?", 60) or "?"
    transcript = bp.oneline(rec.get("transcript") or "", 200, code=True)
    where = (WHERE_TRANSCRIPT.format(transcript=transcript, aid=aid)
             if transcript else WHERE_LOG.format(aid=aid))
    return WORKER_FAIL.format(
        task=bp.oneline(rec.get("task", ""), 200, code=True), where=where)


def note_on_board(bullet, agent_id=None):
    """Add one bullet to WAITING ON YOU TO DO.

    He must be able to see that something was attempted and failed WITHOUT
    reading a log, so a failure that only reached the log is a failure that did
    not happen. `boardmove.note` is the shared implementation — the same
    targeted line insert, advisory lock, digest re-check and atomic replace
    `boardctl` and the app use, so three writers cannot interleave into a
    half-written store.

    `agent_id` names the agent the bullet is a RESULT for, so the summon note
    that announced it goes with it (`boardparse.drop_summon`). It has to be
    passed explicitly here: this process is the watcher, not the worker that
    died, so `BOARD_AGENT_ID` would name the wrong one or nobody.

    ...and for exactly that reason the gutter's `by=` is **this program**, not
    that agent. The bullet says the minister recorded nothing; an attribution
    naming it would be the same sentence claiming it did. `boardmove.note`
    resolves the author from the environment, which here names nobody, so this
    is the fallback and it is an honest one — the watcher genuinely is what put
    the line on the board.
    """
    try:
        return bm.note(bullet, path=BOARD, agent_id=agent_id, by="board-watch")
    except (bm.BoardError, OSError) as e:
        log("could not add the failure note: %s" % e)
        return False


# ------------------------------------------------------------------ the agent
PROMPT = """You are running headless, with no human watching, on the machine \
{host}. Work in `{repo}`.

He answered one decision on this machine's board (the store behind the \
`board` app; one file per host, `docs/board.<hostname>.md`). Your whole job is that ONE decision, below, verbatim from the \
file. Do not pick up any other item.

--- the decision, as it stands in the file ---
{item}
--- end ---

His answer: {answer}

RULES are in force for this session and not negotiable — the SAME block every
board worker gets (`boardwork.RULES`, appended verbatim to the system prompt by
the spawner, never paraphrased — a hand-written paraphrase is how a rule comes
to be true nowhere).

8. **When you are done, record it on the board — with the tool, never by \
hand.** This decision has ALREADY been moved out of NEEDS YOU and into IN \
FLIGHT for you, carrying your answer, so he can see it is being worked. Close \
the loop from `{repo}` with exactly one of:

       python3 apps/board/tools/boardctl.py land {key} --commit <hash> \
--what '<one line, imperative, like a commit subject>'
       python3 apps/board/tools/boardctl.py note '<TAG>: **<title>** - <what \
is done, what is not, and whether a rebuild is now pending and why>'

   **A note STARTS WITH A TAG, then a summary of AT MOST about a dozen words \
on that same first line — the tool refuses more.** Every elaboration or \
background goes on INDENTED continuation lines under it, a sentence or two, \
not a paragraph. The tag is one of `ENACTED:` (it is done and on his \
machine), `PARTIAL:` (some of it landed, some did not — including "it needs a \
rebuild, which you may not run"), `FAILED:` (nothing landed) or `INFORMATION:` \
(a fact, nothing asked of him). **A question is NEVER a note bullet** — it \
belongs only in the decisions section, written with `boardctl.py ask '<the \
question>' --option '<a way>' --if-unanswered '<what stays undone>'`; a \
`QUESTION:` note is refused, the tool telling you to use `ask`. The tool refuses \
an untagged bullet too; tag and short \
summary are how he tells at a glance what a line on that list is about.

   **Write board text TO the person at the machine** — every note, question, \
option and if-unanswered line you emit is read by the user, so address them \
as "you", never "he" or "him". Internal prose — this prompt, your comments, \
commit messages — stays third person; only what lands on the board says "you".

   **A completion note is AS SHORT as its result.** When nothing surprising \
happened — it worked, nothing failed, you deviated from nothing, there is no \
decision he needs — then the note IS `ENACTED: done, no errors. pushed.` \
and nothing under it. Detail (an indented line, a second clause) earns its \
place only for what would otherwise surprise him — something that did not \
work, a choice you made on his behalf, work left undone. Never dress a plain \
success up.

   **ONE BOARD ITEM PER ASK.** If you have more than one thing to report, that \
is more than one `note` call — never several folded into one message, in the \
headline or in the elaboration under it. **Replying to a bullet CLEARS that \
bullet**, so an ask folded into another one is cleared by a reply that was \
never about it and survives nowhere he can see. The tool refuses the shapes it \
can recognise (a second tag on a line, a second `**headline**`, a tagged or \
bulleted line in the elaboration); the rest is on you. Several tagged strings \
in one call, or several unindented lines, land as several bullets, each \
clearable on its own.

   `land` when the work is complete: it appends `| commit | what | when |` \
under today's date in LANDED. `note` when it is not, and he gets a bullet in \
WAITING ON YOU TO DO. Run `boardctl.py --help` for the rest.

   **Do not edit the board in an editor.** It is a store three programs \
parse and write concurrently — the app he may have open right now, the \
five-minute sync, and this tool — and every one of those edits is a targeted \
line edit under a lock with a digest re-check. A hand-written table row or a \
reflowed section is a bug, and a half-written one syncs to the other machine. \
`boardctl` never touches a line it was not asked to. `docs/` is its own git \
repo inside this checkout, so commit the result from inside `docs/`.
9. If the answer is ambiguous or the work turns out to be much larger than the \
item implies, do the smallest honest thing and write what you found onto the \
board instead of guessing big.
10. **He can reach you WHILE you run. Check for it between steps:**

       python3 apps/board/tools/boardctl.py inbox take --quiet

   The board app has a box against your row; your stdin is closed, so a file is \
the only channel there is. Anything that command prints is him, typing at you \
mid-flight — a correction, an extra idea, a fix — and it OUTRANKS this prompt \
where the two disagree. Run it after each meaningful step and once before you \
finish. Taking a note is also what stops the watcher handing it to a second \
agent later, so take them even if you decide not to act, and say on the board \
what you did with them.

There is nobody to ask. Finish, or write down why you did not.
"""

# Allow the tools a working agent needs; deny the ones that change the machine
# out from under him. ONE copy, in `apps/board/boardwork.py`, because workers are
# now spawned from there too and a hole opened in one spawner and not the other
# would be invisible. The prompt is the primary defence and this is the
# mechanical one — belt and braces, because rule 1 is the whole point of the
# feature and a model that forgets it costs him his session.
ALLOW = bw.ALLOW
DENY = bw.DENY


def spawn(prompt, agent_id, label, session=None, timeout=None, role="decision",
          retry=True, on_start=None, detach=False):
    """Run the agent, and WAIT for it. Returns (exit code, how it ended, seconds).

    **`detach=True` starts it in its OWN transient unit and returns at once**,
    with `rc = None` — the caller then has nothing to report and must not
    pretend otherwise. That is how a DECISION runs (see `tick`): waiting for one
    held this unit for the whole run, and a sentence he typed in the meantime
    sat in the queue until it returned. [his, 2026-08-01, of an order queued
    behind a five-minute decision run: *"why is there currently a pending order
    for solomon yet he is sitting there doing nothing"*.] The close-out is not
    lost, it MOVES: `boardmove.retire_finished()` drops the stash of an agent
    that reported and exited, and `reconcile()` hands the decision back if it
    exited without reporting — both already run at the top of every tick, for
    exactly this shape (an agent whose tick was killed under it).

    What detaching gives up, and it is stated rather than papered over: the
    immediate `rc`, the `agent said:` line in this log (its stdout goes to
    `~/.cache/board-work/<key>.log`, which is also where the card's drawer
    looks), and the one-shot retry on a transient API error below. A decision
    that dies that way is handed back with his answer intact and he sees the
    FAILED bullet, which is the same outcome the retry was avoiding one round
    of. Orchestrator runs are still WAITED on: they are short by design and the
    tick has nothing else to do while one plans.

    A run that dies on a TRANSIENT platform error — the CLI printing an API
    5xx / overload line and exiting nonzero (`boardwork.TRANSIENT_RE`, the same
    pattern `reap()` requeues a worker on) — is retried ONCE, immediately. The
    2026-07-29 Anthropic outage is why: an orchestrator that dies at launch
    costs him his own sentence back as a FAILED bullet asking him to type it
    again, when the system still holds it verbatim. The retry passes no
    `--session-id` (the first run consumed it; the card's observed line
    degrades for the retry, which is the honest trade), and `retry=False` on
    the recursive call is what makes a second transient death final.

    `BOARD_AGENT_ID` is what makes his mid-flight notes reachable: it is the
    inbox `boardctl.py inbox take` reads with no argument, and the same id the
    board app addresses the box on this agent's row to.

    `session` is the `--session-id` uuid, and it is what lets his board say what
    this agent is actually doing rather than only that it is alive: the
    transcript at `~/.claude/projects/*/<uuid>.jsonl` is written live and
    `apps/board/boardphase.py` tails it. Chosen here, never guessed at.

    Contrast `boardwork._spawn_worker`, which does NOT wait: a worker is
    detached so a tick cannot be held open by it. The two runs this function
    starts — a decision and an orchestrator — are waited on deliberately,
    because a failure has to be reported onto the board in his own words and
    there is nobody else left to do it.

    `on_start(pid)` is called with the agent's own pid as soon as it exists,
    and it is why this uses `Popen` rather than `subprocess.run`. WAITING FOR
    IT IS NOT OWNING IT: this process is a oneshot systemd stops on every
    `home-manager switch`, the agent is not, and something has to be able to
    say which of the two the item's liveness follows (`boardmove.adopt`).
    Called for the retry too, which is a different process.
    """
    stub = os.environ.get("BOARD_WATCH_SPAWN")
    env = dict(os.environ, BOARD_WATCH_KEY=agent_id, BOARD_AGENT_ID=agent_id)
    # SAY SO, LOUDLY, rather than failing as a bare ENOENT. The CLI reaches this
    # unit through the PATH pinned in `board-watch.nix`, and that PATH has to
    # name two different profile layouts: NixOS's `/etc/profiles/per-user` on
    # top, and standalone home-manager's `~/.nix-profile/bin` on book. If it is
    # missing, every run fails identically and the board must say why.
    #
    # **It is the BACKEND'S binary, not `claude`.** [top, 2026-07-31] with the
    # minister model set to a hermes one and no `hermes` on the box, every
    # dispatch died at `execve` with a bare `[Errno 2] 'hermes'` — while this
    # check, looking for a binary that run was never going to use, passed.
    backend = bw.get_backend_for_role(role)
    if not stub and not shutil.which(backend.name, path=env.get("PATH")):
        why = ("without starting at all (`%s` is not on this unit's PATH "
               "on %s; PATH=%s)" % (backend.name, HOST, env.get("PATH", "")))
        log("cannot spawn: " + why)
        return 127, why, 0.0
    if stub:
        cmd = ["/bin/sh", "-c", stub]
    else:
        # All the Claude-isms — model/effort, cache flags, trimmed tools, the
        # allowed/denied sets, and the appended RULES system-prompt block —
        # live in `boardwork.AgentBackend`. Which backend follows the chosen
        # model: hermes models spawn via `hermes`, everything else via `claude`.
        cmd = backend.args(prompt=prompt, session=session,
                           role=role, label=label)
        # ...and a backend whose session id we cannot choose is bound to its run
        # by the query text instead (`boardphase.arm`), so the card for a
        # decision or an orchestrator can say what it is doing on either
        # runtime. No-op for claude, which took our `--session-id`.
        backend.arm(agent_id, cmd)
    t0 = time.time()
    cap = timeout or AGENT_TIMEOUT_S
    if detach and not stub:
        # ITS OWN UNIT, so nothing about this run is in this tick's cgroup and
        # the tick is free the moment it has exec'd. `--service-type=exec`
        # returns at the exec, which is what makes the pid knowable — and that
        # pid is what the stash is adopted onto, so the item's liveness follows
        # the AGENT rather than the watcher (`boardmove.adopt`). `RuntimeMaxSec`
        # is the cap this path could not otherwise enforce: the timeout below
        # belongs to a wait that no longer happens.
        logpath = bw._log_path(agent_id)
        bw._log_line(agent_id, "decision agent starting: %s" % label)
        hint = backend.history_hint(agent_id, session)
        if hint:
            bw._log_line(agent_id, "live history: %s" % hint)
        pid = bw._start_unit(agent_id, cmd, env, logpath, label,
                             prefix=bw.DECISION_PREFIX, kind="decision",
                             runtime=cap)
        if pid is not None:
            if on_start:
                try:
                    on_start(pid)
                except Exception as e:                         # noqa: BLE001
                    log("could not record the agent's pid: %s" % e)
            return None, ("as %s" % bw.unit_name(agent_id, bw.DECISION_PREFIX)), \
                time.time() - t0
        # No systemd-run, or it refused. Falling through to the waiting path is
        # the honest degradation: the tick is held, which is what it always did,
        # rather than the decision not being worked at all.
        log("could not start the decision in its own unit - waiting on it "
            "instead, which holds this tick")
    try:
        p = subprocess.Popen(cmd, cwd=REPO, env=env,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    except OSError as e:
        return 127, "without starting at all (%s)" % e, time.time() - t0
    if on_start:
        # BEFORE the wait, and before anything that can raise: the whole point
        # is that this holds even if this process never reaches the line below.
        try:
            on_start(p.pid)
        except Exception as e:                                # noqa: BLE001
            log("could not record the agent's pid: %s" % e)
    try:
        out, err = p.communicate(input=prompt if stub else None, timeout=cap)
    except subprocess.TimeoutExpired:
        # `subprocess.run` did this for us; `Popen` does not, and an agent left
        # running past its cap would go on editing the tree with nothing
        # watching it.
        p.kill()
        p.communicate()
        return 124, "after %d minutes without finishing" % (cap // 60), \
            time.time() - t0
    if out:
        log("agent said: " + " ".join(out.split())[:400])
    if p.returncode != 0 and err:
        log("agent stderr: " + " ".join(err.split())[:400])
    if (p.returncode != 0 and retry and not stub
            and bw.TRANSIENT_RE.search((out or "") + "\n" + (err or ""))):
        log("that was a transient API error - trying the run once more")
        return spawn(prompt, agent_id, label, session=None, timeout=timeout,
                     role=role, retry=False, on_start=on_start)
    return p.returncode, "with status %d" % p.returncode, time.time() - t0


QUEUE_FAIL = (
    "- FAILED: **what you typed could not be worked** - nothing was "
    "dispatched.\n"
    "    {who} exited {how}; nothing was committed either. What you wrote, "
    "so it is not lost: {text} Log: `~/.cache/board-watch.log`\n")


#: The orchestrator plans and dispatches; it does not do the work. So it is
#: capped far below a worker — fifteen minutes of reading and splitting, not
#: forty-five of building. That number is also how long a tick may hold the
#: flock, so it is the latency floor for a decision he answers meanwhile.
#: Overrunning it costs him nothing but the wait: the failure path below still
#: puts his own sentence back on the board, verbatim.
ORCH_TIMEOUT_S = int(os.environ.get("BOARD_ORCH_TIMEOUT", "900"))


def _summon(notes, index, total, op=None):
    """One summoner run: register a card, spawn, wait, unregister.

    `op` is the `boardwork.Operator` this tick routed to (Solomon by default) —
    it names the card and picks the prompt flavour. Its model/effort reach the
    spawn through `BOARD_ORCH_MODEL`/`_EFFORT`, set once by the caller.

    Returns the QUEUE_FAIL text for it or None. It does NOT write to the board
    itself — several of these run in threads and `note_on_board` is a
    read-modify-write of one file, so the caller does that part serially once
    everybody is home.
    """
    # UNIQUE per run, and it used to be `orch-<pid>` alone: two summoners in one
    # tick share a pid, so one id would have been one card, one inbox and one
    # `unregister` racing itself.
    aid = "orch-%d" % os.getpid() if total == 1 else "orch-%d-%d" % (os.getpid(), index)
    session = str(uuid.uuid4())
    # Registered so it shows up on his board as a running agent with his own
    # words as its title — the same card, the same box, so he can add to it
    # while it is still deciding. `kind="orchestrator"` is also what names it:
    # `ba.register` gives that kind `Solomon`, always, and `boardwork.cards()`
    # pins the row to the top of the list whether or not this run exists. Two
    # of them are two Solomons, both pinned, in birth order — which `cards()`
    # already said it did.
    op = op or bw.default_operator()
    ba.register(aid, notes[0]["text"][:70], os.getpid(), kind="orchestrator",
                where="board-watch", session=session, name=op.name)
    # HE CAN TAKE IT BACK UNTIL THIS RUN ACTS. Written before the spawn, like
    # the drain above it: `boardundo.py` is what ctrl+z reaches, and a run that
    # exists without a record of the orders it was given is a run he cannot
    # cancel. Removed by `end_run()` below, which also answers whether he did.
    bu.begin_run(aid, notes)
    text = "\n\n".join(m["text"] for m in notes)
    try:
        rc, how, secs = spawn(
            bw.orchestrator_prompt(op, repo=REPO, host=bw.host_line(),
                                   notes=text, cap=bw.cap()),
            aid, "board: orchestrating", session=session, timeout=ORCH_TIMEOUT_S,
            role="orchestrator")
    finally:
        ba.unregister(aid)
        took_back = bu.end_run(aid)
    # CTRL+Z. He stopped this one, and every verb it tried after that was refused
    # by `boardctl` — so nothing was dispatched, nobody was handed anything and
    # no note was written. Its exit code is therefore not a failure and must not
    # put his own sentence back on the board as one: he has it in the prompt box,
    # which is where he asked for it.
    if took_back:
        log("a summoner was cancelled with ctrl+z after %dm%02ds - nothing "
            "dispatched" % (secs // 60, secs % 60))
        return None
    if rc == 0:
        log("a summoner finished in %dm%02ds" % (secs // 60, secs % 60))
        return None
    log("a summoner FAILED %s after %dm%02ds" % (how, secs // 60, secs % 60))
    # The last stop. He must never have to wonder where a sentence he typed
    # went, so the failure carries the text itself onto the board.
    return QUEUE_FAIL.format(how=how, who=op.name,
                             text=bp.oneline(text, 300, code=True))


def work_the_queue():
    """Spawn ONE ORCHESTRATOR for the sentences he typed into the board's box.

    This is the other half of `boardagents.py`'s promise. The box files what he
    typed either in a running agent's inbox or in the queue; the queue has to be
    somebody's job or the promise is a lie, and this is the somebody.

    What changed when he asked for the control surface — *"an agent figures out
    what agents to assign to what (like how you used to orchestrate)"* — is what
    that somebody DOES. It used to be one agent that did the work itself. It is
    now an orchestrator that reads the input, works out what it implies, and
    either `dispatch`es workers (detached, capped, drawn as cards) or `ask`s him
    (a question in NEEDS YOU, answered at his leisure). `boardwork.py` owns both
    verbs and the prompt.

    THESE RUNS ARE WAITED ON, and the workers they start are not. That is the
    whole concurrency design: the tick blocks only for the short planning runs, so
    its flock is released long before the workers finish — a decision he answers
    five minutes from now still fires on time.

    HOW MANY of them is his, in the top dropdown. [his, 2026-07-29] *"number of
    summoners"* — `boardwork.summoners()`, read here and cached nowhere, so a
    change takes effect on the next tick with nothing restarted. What he typed is
    split across up to that many runs (`boardwork.split_for_summoners`,
    contiguous, none empty), and one queued sentence is one summoner however high
    the number is: the count is a ceiling on the fan-out, not a quota to fill.
    They run TOGETHER in threads, because the point of asking for more than one is
    that two unrelated things he typed do not have to take turns; the tick is held
    for the slowest of them rather than the sum.

    Returns True if a run happened.
    """
    msgs = ba.drain()          # BEFORE the spawn: see boardagents.drain()
    if not msgs:
        return False
    groups = bw.split_for_summoners(msgs)
    # WHICH OPERATOR summons this tick — his explicit pick if he made one, else
    # the auto-route from what he typed (`bw.tick_operator`). One operator for
    # the whole tick, chosen HERE at the single-threaded top, then pinned into
    # the environment the concurrent summoner threads all read: `role_flags`
    # and `_role_model` honour `BOARD_ORCH_MODEL`/`_EFFORT`, so the run's
    # `--model`, its effort and its backend (hermes vs claude) all follow the
    # routed operator with no per-thread state to race. Per-GROUP routing is the
    # roster doc's follow-up. [his, 2026-08-01: "build auto-routing for the start"]
    op = bw.tick_operator("\n\n".join(m["text"] for m in msgs))
    os.environ["BOARD_ORCH_MODEL"] = op.model
    os.environ["BOARD_ORCH_EFFORT"] = op.effort
    log("orchestrating %d thing(s) he typed across %d summoner(s) as %s (%s %s)"
        % (len(msgs), len(groups), op.name, op.model, op.effort))
    if len(groups) == 1:
        fails = [_summon(groups[0], 0, 1, op)]
    else:
        out = {}

        def one(i, group):
            out[i] = _summon(group, i, len(groups), op)

        pool = [threading.Thread(target=one, args=(i, g), daemon=True)
                for i, g in enumerate(groups)]
        for t in pool:
            t.start()
        for t in pool:
            t.join()
        fails = [out.get(i) for i in range(len(groups))]
    # Serially, and after the join: every one of these is a read-modify-write of
    # `board.md` under its own lock, and a failed summoner's sentence has to reach
    # him whole rather than interleaved with another's.
    for text in fails:
        if text:
            note_on_board(text)
    return True


#: Set by drain_queue() when there IS something queued and the gate said no. A
#: run that ends that way leaves the queue full on purpose and will be
#: re-triggered at once — see spin_guard(), which needs to tell that apart from
#: a defect.
_held_by_gate = False


def mark_gate_hold():
    """A path that could not drain because the gate is shut, and says so here so
    the spin guard does not read a locked screen as a bug."""
    global _held_by_gate
    _held_by_gate = True


def drain_queue():
    """Work whatever he typed into the box, if the gate lets us.

    Called from EVERY path that reaches the end of a tick, first run included.
    That last part is the fix for the second half of the 3,151-run loop: seeding
    is about not acting on answers that were already in the file before this
    existed, and it has nothing whatever to do with typed input. A sentence he
    types is his, now, and the run that notices it is the run that must work it
    — otherwise `board-inbox.path` is level-triggered at a queue nobody drains,
    which is exactly the loop.
    """
    global _held_by_gate
    _held_by_gate = False
    try:
        waiting = ba.pending()
    except OSError as e:
        log("could not look at the queue: %s" % e)
        return False
    if not waiting:
        return False
    may, why = gate()
    if not may:
        _held_by_gate = True
        log("%d note(s) waiting for the gate - %s" % (len(waiting), why))
        return False
    return work_the_queue()


# ------------------------------------------------------------- the spin guard
#: A run that ends with the queue no emptier than it found it WILL be started
#: again the moment it exits: `board-inbox.path` is `PathExistsGlob`, which is
#: level-triggered on purpose (that is what stops a sentence typed during a run
#: being lost). The whole design rests on the queue being drained before the run
#: ends, and on 2026-07-28 a bug meant it never was: 3,151 starts in a few
#: minutes, on the machine he was sitting at.
#:
#: So the script refuses to be part of a loop, whatever the reason. After this
#: many consecutive undrained runs inside the window, every further run sleeps
#: first — holding the flock, so triggers arriving meanwhile are already no-ops.
#: An unbounded loop becomes one run a minute, and it self-heals: the moment a
#: run does drain the queue the streak resets to nothing.
SPIN_LIMIT = int(os.environ.get("BOARD_WATCH_SPIN_LIMIT", "8"))
SPIN_WINDOW_S = float(os.environ.get("BOARD_WATCH_SPIN_WINDOW", "60"))
SPIN_BACKOFF_S = float(os.environ.get("BOARD_WATCH_SPIN_BACKOFF", "60"))

SPIN_NOTE = (
    "- FAILED: **board-watch caught itself looping and slowed down**\n"
    "    Something typed into the board's box could not be worked, so the "
    "inbox queue never emptied and the watcher was re-triggered over and "
    "over. It is now backing off to one run a minute and will pick the work "
    "up by itself once the cause is fixed. Nothing was lost: it is still in "
    "`~/.local/state/board/inbox/queue/`. Log: `~/.cache/board-watch.log`\n")


def spin_guard(state):
    """Sleep if the last several runs all ended with the queue still full.

    NOT `StartLimitBurst` on its own, deliberately. A start limit puts the unit
    in `failed` and keeps it there, which takes the timer and board.md's own
    path unit down with it — the feature silently off is a worse failure than a
    slow loop, and this exact case (a locked screen with something queued) is
    a legitimate one that must not wedge anything. The limit IS still set, in
    `board-watch.nix`, as the outer net for a runaway this code cannot see: a
    crash before this line runs would loop just as hard and reach none of it.

    Visible, not silent, and the two causes are told apart because only one is a
    bug: the gate being shut is normal and gets a log line, while a queue that
    stayed full with the gate OPEN gets one bullet on his board, once per streak.
    """
    sp = state.get("spin") or {}
    n = int(sp.get("count", 0))
    if n < SPIN_LIMIT or (time.time() - float(sp.get("first", 0))) > SPIN_WINDOW_S * 8:
        return
    log("backing off %ds: %d runs in a row left the queue undrained"
        % (SPIN_BACKOFF_S, n))
    if sp.get("defect") and not sp.get("noted"):
        note_on_board(SPIN_NOTE)
        sp["noted"] = True
        state["spin"] = sp
        save_state(state)
    time.sleep(SPIN_BACKOFF_S)


def spin_record():
    """Update the streak from what this run actually left behind.

    Re-reads the state file rather than reusing the caller's copy: the tick has
    saved it several times by now, and clobbering that with a stale dict would
    lose the very fingerprints that stop a re-fire.
    """
    try:
        empty = not ba.pending()
    except OSError:
        empty = True
    st = load_state()
    sp = st.get("spin") or {}
    if empty:
        sp = {}
    else:
        if not sp.get("count"):
            sp = {"count": 0, "first": time.time(), "noted": False, "defect": False}
        sp["count"] = int(sp.get("count", 0)) + 1
        if not _held_by_gate:
            sp["defect"] = True          # nothing stopped us, and it is still there
    st["spin"] = sp
    save_state(st)


# ------------------------------------------------------------------------ run
def main():
    os.makedirs(STATE, exist_ok=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    _rotate()

    if os.path.exists(OFF):
        log("off (kill switch %s exists; rm it to re-enable)" % OFF)
        return 0

    # HAZARD 3. `flock -n`, not a wait: a second trigger that arrives mid-run
    # has nothing to add, and the timer will look again in five minutes.
    lockf = open(os.path.join(STATE, "lock"), "w")
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("skipped: another board-watch run holds the lock")
        return 0

    # NEVER SPIN. Inside the lock, so the sleep it may do turns every trigger
    # that arrives meanwhile into a no-op rather than a second sleeping process.
    spin_guard(load_state())
    try:
        return tick()
    finally:
        spin_record()


def tick():
    # ...BUT WORK THAT WAS DONE IS NOT STRANDED WORK, and this runs first
    # because `reconcile()` below cannot tell the two apart on its own. An agent
    # whose tick was killed mid-run (a rebuild restarts this unit; the agent
    # survives it) finishes with nobody left to close its stash out, so the
    # stash outlives it naming a dead pid. Retire the ones that recorded a
    # result on his board; only what is left is a death.
    try:
        for rec in bm.retire_finished():
            log("decision %s finished after its tick was killed - not handing "
                "it back" % (rec.get("num") or rec.get("key")))
    except (bm.BoardError, OSError) as e:
        log("could not retire finished decisions: %s" % e)

    # NOTHING STAYS STRANDED. If a previous run was killed outright — OOM,
    # reboot, systemd's TimeoutStartSec — its decision is off the board, stashed
    # with nothing working on it. Hand back every item whose owning process is
    # gone, before deciding what to fire on. Worst case is one timer interval.
    try:
        for rec in bm.reconcile(path=BOARD):
            # Say which of reconcile's two cases it was. A pid-less stash never
            # had an agent to lose, and the bullet it writes on his board is
            # careful about that — the log must not be the one place that
            # invents a death to explain a row.
            log("returned decision %s to NEEDS YOU: %s"
                % (rec.get("num") or rec.get("key"),
                   "its agent is gone" if rec.get("pid")
                   else "nothing was ever working it"))
    except (bm.BoardError, OSError) as e:
        log("could not reconcile stranded items: %s" % e)

    # THERE IS NO LANDED SWEEP HERE ANY MORE, AND THAT IS THE FIX, not an
    # omission. This tick used to call `bm.reconcile_landed()` to APPEND the
    # commits nobody had recorded, because the app's own sweep only ran while
    # the board window was open. Both were correct code and neither could reach
    # him: the window he had open was running the live source from before the
    # first fix, and this file is a home-manager unit, so on `top` the second
    # one needed a `sudo rebuild-top` before it existed there at all. He was
    # blunt about the shape of it — *"it should just read from the commit log of
    # the repo itself. it shouldnt need an agent to do that"* — and he was
    # right: `bm.landed_view()` DERIVES the section from `git log` at the moment
    # it is drawn, so there is no stamped state left to be stale and a watcher
    # that is three rebuilds behind cannot make LANDED wrong.
    #
    # NOTHING IS ADDED HERE, so nothing here needs deploying to keep it current.

    # AND NOTHING HE TYPED IS LOST EITHER. A note he wrote to an agent that has
    # since gone — or that never read it — is moved to the queue here, and the
    # queue is drained at the bottom of this function by a run of its own. Same
    # shape as reconcile above: a guarantee that costs a directory listing.
    try:
        escalated, dropped = ba.sweep()
        if escalated:
            log("%d note(s) nobody read moved to the queue" % len(escalated))
        for rec in dropped:
            log("dropped a registration whose process is gone: %s"
                % rec.get("title"))
    except OSError as e:
        log("could not sweep the inbox: %s" % e)

    # AND A WORKER THAT DIED MID-SENTENCE IS SAID SO, rather than being
    # indistinguishable from one that did the job. The orchestrator can only
    # ever report what it HANDED OUT; the result of each piece is the worker's
    # own `note`/`land`/`ask`, and a worker whose process is gone without one is
    # a failure he has to be able to see. On 2026-07-29 every worker was being
    # killed seconds after it started (a detached child stays in the oneshot's
    # cgroup — `boardwork._spawn_worker`), and his board said the work was
    # dispatched and in hand. Nothing was ever built. This is the half of that
    # fix which does not depend on the spawn being right.
    try:
        _, failed, requeued = bw.reap()
        # A note the dead worker had TAKEN went back to the queue with it
        # (`boardagents.requeue_taken`, riding on the record as `notesBack` so
        # the tuple above keeps its shape) — the handed-over item worker Vual
        # took at 11:27 on 2026-07-29 and died holding, generalized.
        back = sum(len(r.get("notesBack") or []) for r in failed + requeued)
        if back:
            log("%d note(s) a dead worker had taken went back to the queue"
                % back)
        for rec in requeued:
            # Died at launch on a transient API error (its whole log is the
            # CLI printing a 5xx) — the task is back in `pending/` and
            # promote() below starts it again. Once: a second death is final.
            log("a worker died on a transient API error - requeued its task: %s"
                % rec.get("task", "")[:80])
        for rec in failed:
            log("a worker stopped without recording anything: %s"
                % rec.get("task", "")[:80])
            note_on_board(worker_fail_bullet(rec),
                          agent_id=rec.get("agent") or "")
    except (OSError, bm.BoardError) as e:
        log("could not reap finished workers: %s" % e)

    # AND NO DISPATCHED WORK SITS QUEUED ONCE THERE IS ROOM FOR IT. Work above
    # the concurrency cap is a file in `work/pending/`, not a dropped task
    # (`apps/board/boardwork.py`); this is what starts it when a slot frees.
    # Same shape as the two guarantees above, same worst case: one tick.
    try:
        for rec in bw.promote():
            log("started queued work now that a slot is free: %s"
                % rec.get("task", "")[:80])
    except OSError as e:
        log("could not start queued work: %s" % e)

    try:
        src = bp.read(BOARD)
    except OSError as e:
        log("cannot read %s: %s" % (BOARD, e))
        return 0
    doc = bp.parse(src)
    state = load_state()
    seen = state["answers"]
    first_run = not state.get("seeded")

    fresh = {}
    fired_candidates = []
    # Read at most once per tick, and only if something would otherwise fire:
    # it is a pass over /proc, and the overwhelmingly common tick has no
    # candidate at all.
    _busy = {}

    def busy():
        if "keys" not in _busy:
            _busy["keys"] = working_keys()
        return _busy["keys"]

    for item in doc["needs"]:
        fp = fingerprint(item)
        fresh[item["key"]] = fp
        if first_run:
            continue
        if item["key"] not in seen:
            # A decision that ARRIVES already answered was, by default, written
            # that way by an agent (`ask()` places an UNANSWERED item; a
            # restored or re-synced board carries stale answered copies).
            # Record it; do not act on it.
            #
            # THE ONE EXCEPTION is an answer stamped for THIS machine. The
            # stamp is written only by the board app at the instant the user
            # answers (`boardparse.set_answer_host`, called from main.py's
            # answer path) — an item that is new to us, answered, and stamped
            # `top` is therefore HIM, answering while a long orchestrator run
            # held this tick so the first sighting was already answered. That
            # is a genuine user answer and must be worked, not swallowed.
            if item["answered"] and item.get("answerHost") == HOST:
                if item["key"] in busy():
                    log("decision %s is already being worked - not firing a "
                        "second agent on it" % (item["num"] or item["key"]))
                    continue
                fired_candidates.append(item)
            continue
        if fp != seen[item["key"]] and item["answered"]:
            if owns(item):
                # ONE AGENT PER DECISION, whatever the bookkeeping says. A key
                # a live process still carries is a decision being worked, so
                # it is left at its OLD fingerprint — untouched, not recorded —
                # and looked at again when that process is gone. Same shape as
                # the gate's queue below, and the same reason: a skip that
                # recorded the answer would lose it.
                if item["key"] in busy():
                    fresh[item["key"]] = seen[item["key"]]
                    log("decision %s is already being worked - not firing a "
                        "second agent on it" % (item["num"] or item["key"]))
                    continue
                fired_candidates.append(item)
            else:
                # Answered on the OTHER machine, which is the one that works it.
                # Recorded (below) rather than queued, so this is said once and
                # not on every tick for the rest of the file's life.
                log("decision %s was answered on %s - %s works it, not %s"
                    % (item["num"] or item["key"],
                       item.get("answerHost") or DEFAULT_HOST,
                       item.get("answerHost") or DEFAULT_HOST, HOST))

    if first_run:
        state["answers"] = fresh
        state["seeded"] = True
        save_state(state)
        log("first run: recorded %d decisions, fired nothing" % len(fresh))
        # ...but a sentence he typed is not an answer that predates us, and it
        # is not seeded past. It is worked on the very first tick after he types
        # it, exactly as on any other tick.
        drain_queue()
        return 0

    if not fired_candidates:
        # Everything else — LANDED rows, reworded prose, a pulled merge, our own
        # failure note — updates the record and stops here. HAZARDS 1 and 2.
        if fresh != seen or state["queued"]:
            state["answers"] = fresh
            state["queued"] = []
            save_state(state)
        log("no new answer")
        # A tick with no new answer is when his notes get worked: one agent per
        # invocation still holds, and a decision always outranks a note.
        drain_queue()
        return 0

    keys = [i["key"] for i in fired_candidates]
    may, why = gate()
    if not may:
        # THE QUEUE, and it is the absence of a write rather than a queue file:
        # leaving these keys at their OLD fingerprint means the next tick sees
        # them as newly answered all over again. Nothing to drain, nothing to
        # lose, and no second source of truth to go stale.
        state["answers"] = {k: v for k, v in fresh.items() if k not in keys}
        for k in keys:
            state["answers"].setdefault(k, seen.get(k, ""))
        if sorted(state["queued"]) != sorted(keys):
            log("queued %d answer(s) - %s: %s" % (len(keys), why, ", ".join(keys)))
        state["queued"] = keys
        save_state(state)
        mark_gate_hold()          # his notes cannot be worked either, same reason
        return 0

    # ONE decision per invocation, in file order. The rest stay queued at their
    # old fingerprint and get their own run, with their own commit.
    item = fired_candidates[0]
    state["answers"] = {k: v for k, v in fresh.items()
                        if k == item["key"] or k not in keys}
    for k in keys:
        if k != item["key"]:
            state["answers"].setdefault(k, seen.get(k, ""))
    state["queued"] = [k for k in keys if k != item["key"]]
    # Written BEFORE the spawn: a crash, a reboot or an OOM kill mid-agent must
    # not leave the same decision firing forever.
    save_state(state)

    chosen = [o["label"] for o in item["options"] if o["checked"]]
    answer = item["answer"].strip()
    parts = []
    if answer:
        parts.append("his own words: " + answer)
    if chosen:
        parts.append("he ticked: " + "; ".join(chosen))
    said = ". ".join(parts) if parts else "(answered, but the text is empty)"

    log("firing on decision %s (%s) - %s" % (item["num"] or "?", item["key"], why))
    prompt = PROMPT.format(repo=REPO, host=bw.host_line(),
                           item=item_span(doc["lines"], item),
                           answer=said, key=item["key"])

    # MOVE IT BEFORE THE AGENT RUNS. An answered decision that sits in NEEDS YOU
    # while an agent works it is the board asking him for something he has
    # already given — the whole reason this exists. The move carries his answer
    # onto the row and stashes the decision verbatim, so the failure paths below
    # can put it back exactly as he wrote it. `pid` is OURS: if this process is
    # killed outright, the next tick's reconcile() sees a dead owner and hands
    # the item back on its own.
    moved = False
    session = str(uuid.uuid4())
    try:
        rec = bm.start(item["key"], where="board-watch", pid=os.getpid(),
                       path=BOARD, session=session)
        moved = True
        log("took decision %s off NEEDS YOU" % (item["num"] or "?"))
    except (bm.BoardError, OSError) as e:
        # Bookkeeping must never cost him the work. Spawn anyway and say so.
        log("could not take decision %s off NEEDS YOU (%s) - working it anyway"
            % (item["num"] or "?", e))

    # ...AND THE STASH FOLLOWS THE AGENT FROM HERE ON, not this process. A
    # `sudo rebuild-top` stops this unit mid-run (home-manager restarts the
    # units it manages), the agent survives it, and until `adopt()` existed the
    # next tick read our dead pid as a dead agent and handed the decision back
    # — where it read as newly answered and fired a second agent nine minutes
    # later. Two agents, one job, 2026-07-30. `boardmove.adopt` has the timings.
    rc, how, secs = spawn(prompt, item["key"],
                          "board: decision %s" % (item["num"] or item["key"]),
                          session=session,
                          on_start=(lambda pid: bm.adopt(item["key"], pid))
                          if moved else None,
                          detach=True)
    state = load_state()
    state["runs"] = (state["runs"] + [{
        "key": item["key"], "num": item["num"], "rc": rc,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(secs)}])[-20:]
    save_state(state)

    if rc is None:
        # STARTED, NOT FINISHED — and this tick is not going to hear how it
        # went. The next one closes it out either way (`retire_finished` if it
        # reported, `reconcile` if it died), and the whole point of getting here
        # without waiting is that HIS TYPED INPUT IS WORKED NOW rather than
        # after it. A decision and an order are two different agents; they
        # stopped taking turns on 2026-08-01.
        log("decision %s started %s - not waiting on it"
            % (item["num"] or "?", how))
        drain_queue()
        return 0

    if rc == 0:
        log("decision %s finished in %dm%02ds" % (item["num"] or "?",
                                                  secs // 60, secs % 60))
        # It worked: whatever the agent did with the row (landed it, or left it
        # away because a rebuild is pending), the item is not stranded and
        # must not be yanked back into NEEDS YOU by the next reconcile().
        bm.forget(item["key"])
        return 0

    log("decision %s FAILED %s after %dm%02ds" % (item["num"] or "?", how,
                                                  secs // 60, secs % 60))
    # HAND IT BACK. A decision off the board with nothing working on it reads
    # as handled, which is worse than it still being open — so the decision goes
    # back where it was, byte for byte, and the bullet says what happened. One
    # edit, so the row is never gone while the decision is not yet back.
    bullet = FAIL_TEMPLATE.format(num=item["num"] or "?",
                                  title=bp.oneline(item["title"], 120,
                                                   code=True),
                                  how=how)
    if moved:
        try:
            bm.give_back(item["key"], why=bullet, path=BOARD)
            return 0
        except (bm.BoardError, OSError) as e:
            log("could not hand decision %s back: %s" % (item["num"] or "?", e))
    note_on_board(bullet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
