#!/usr/bin/env python3
"""board-watch — spawn one headless agent when he newly answers a board decision.

`~/nix/docs/board.<hostname>.md` is the per-host board. A newly answered
decision is the trigger: the watcher moves it out of NEEDS YOU and spawns one
agent to work it. The same loop also drains the inbox queue and orchestrates
typed requests.

The implementation is split on purpose:
`home/srvs/board-watch.nix` wires the units, `apps/board/boardmove.py` moves
items in and out of NEEDS YOU, `apps/board/boardwork.py` owns the
orchestrator/workers/cap, and `apps/board/boardagents.py` owns inboxes.

What matters here:

  * rebuild/reload is allowed at the agent's judgement under `~/nix/AGENTS.md`;
  * the watcher only fires while he is at the machine; away or locked is queued;
  * answers are host-stamped, typed inbox messages stay machine-local;
  * workers run in transient units; detached spawning is the no-user-manager
    fallback and does not survive this oneshot on the normal deployed path;
  * the orchestrator is waited on, workers are not;
  * one timer interval is the worst-case latency for reclaiming a dead run or
    an unread note.

The rest of the module comments below keep the exact gate, failure and retry
rules close to the code.
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
#: Which host this is. Since 2026-07-30 each machine watches its own board, so
#: the host stamp is belt-and-braces for restored copies rather than the
#: de-duplicator.
#:
#: The board app stamps the answer host, the fingerprint carries it, and
#: `owns()` is the filter.
HOST = os.environ.get("BOARD_WATCH_HOST") or os.uname().nodename

#: Unstamped answers default to top: hand edits and pre-stamp answers only.
DEFAULT_HOST = os.environ.get("BOARD_WATCH_DEFAULT_HOST", "top")

# The kill switch is a file so he can stop it with `touch` and no rebuild.
OFF = os.path.join(STATE, "off")

# Hard wall on one agent; the script records the failure instead of systemd.
AGENT_TIMEOUT_S = int(os.environ.get("BOARD_WATCH_TIMEOUT", "2700"))   # 45 min

sys.path[:0] = [os.path.join(REPO, "apps", "board"), os.path.join(REPO, "apps", "pylib")]
import boardagents as ba                                         # noqa: E402
import boardmove as bm                                           # noqa: E402
import boardparse as bp                                          # noqa: E402
import boardundo as bu                                           # noqa: E402
import boardwork as bw                                           # noqa: E402

#: This host's board path comes from `boardparse`; `ensure_board()` seeds a new
#: host and keeps old checkouts watching the pre-split file until migration
#: lands.
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
    """The answer signature: checked options, free text, and host stamp."""
    ticked = ",".join(str(o["index"]) for o in item["options"] if o["checked"])
    return ("idx:" + ticked + "|ans:" + " ".join(item["answer"].split())
            + "|on:" + (item.get("answerHost") or ""))


def owns(item):
    """Whether this host owns the stamped answer."""
    h = (item.get("answerHost") or "").strip()
    return h == HOST if h else HOST == DEFAULT_HOST


def working_keys():
    """Decision keys currently held by live processes on this machine."""
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
    """The decision's raw lines, from its heading to the next one."""
    start = item["titleLine"]
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^#{2,3}\s", lines[i]):
            end = i
            break
    return "".join(lines[start:end]).rstrip() + "\n"


# ------------------------------------------------------------------- the gate
# "Only while I'm at the machine": foreground session, lit display, unlocked.
def _run(cmd, env=None, timeout=10):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env=env)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except (OSError, subprocess.SubprocessError):
        return 127, "", "not runnable"


def _logind_session():
    rc, out, _ = _run(["loginctl", "show-user", str(os.getuid()), "-p", "Display",
                       "--value"])
    sid = out.strip()
    return sid if rc == 0 and sid else None


def _graphical_session_active():
    sid = _logind_session()
    if not sid:
        return False, "logind reports no graphical session"
    rc, out, _ = _run(["loginctl", "show-session", sid, "-p", "Active", "-p", "State"])
    if rc != 0:
        return False, "logind session %s unreadable" % sid
    d = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    if d.get("Active") != "yes" or d.get("State") != "active":
        return False, "session %s is %s/%s (another VT has the seat)" % (
            sid, d.get("Active"), d.get("State"))
    return True, ""


def _logind_gate():
    """Plasma fallback: logind provides the foreground-session and lock check."""
    sid = _logind_session()
    if not sid:
        return False, "logind reports no graphical session"
    _, desktop, _ = _run(["loginctl", "show-session", sid, "-p", "Desktop", "--value"])
    desktop = desktop.strip() or "a non-Hyprland session"
    rc, locked, _ = _run(["loginctl", "show-session", sid, "-p", "LockedHint",
                          "--value"])
    if rc == 0 and locked.strip() == "yes":
        return False, "%s is locked (logind)" % desktop
    return True, "at the machine (%s; no Hyprland, lock read from logind)" % desktop


def hypr_env():
    """Find the live Hyprland environment instead of trusting inheritance."""
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
    """Ask Quickshell whether the panel says locked; None means no answer."""
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
        return _logind_gate()
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
    """Load persisted state; `seeded` stays an explicit marker."""
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
    # Pre-marker files are already seeded because only a completed run writes one.
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
#: Failed bullets stay short enough for `boardparse` and use one code span only.
FAIL_TEMPLATE = (
    "- FAILED: **board-watch did not finish decision {num}** - nothing was "
    "committed.\n"
    "    It was {title}; the spirit exited {how}. The answer is still "
    "above. Log: `~/.cache/board-watch.log`\n")


#: A worker that recorded nothing must come back as a failure, not a result.
WORKER_FAIL = (
    "- FAILED: **a spirit stopped without finishing** - it was working on "
    "{task}.\n"
    "    Dispatched from something you typed into the box; it recorded "
    "nothing on this board, so nothing landed for it. Answer or type it "
    "again to have another go. {where}\n")


#: A worker capped at 45 minutes is still a failure, just with the cause named.
WORKER_CAP_FAIL = (
    "- FAILED: **the {cap}-minute cap cut the spirit off mid-work**\n"
    "    It was working on {task} when the cap SIGTERMed it; nothing landed, "
    "and a worker does not resume on its own. Answer or type it again to "
    "have another go. {where}\n")


#: Point at the log or transcript path on the failed record.
WHERE_LOG = "Log: `~/.cache/board-work/{aid}.log`"
WHERE_TRANSCRIPT = "Transcript: {transcript} (log: `~/.cache/board-work/{aid}.log`)"


def worker_fail_bullet(rec):
    """The FAILED bullet for a worker that recorded nothing."""
    aid = bp.oneline(rec.get("agent") or "?", 60) or "?"
    transcript = bp.oneline(rec.get("transcript") or "", 200, code=True)
    where = (WHERE_TRANSCRIPT.format(transcript=transcript, aid=aid)
             if transcript else WHERE_LOG.format(aid=aid))
    task = bp.oneline(rec.get("task", ""), 200, code=True)
    if rec.get("capped"):
        return WORKER_CAP_FAIL.format(cap=bw.WORKER_TIMEOUT_S // 60,
                                      task=task, where=where)
    return WORKER_FAIL.format(task=task, where=where)


def note_on_board(bullet, agent_id=None):
    """Add one failure bullet to WAITING ON YOU TO DO."""
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
          retry=True, on_start=None, detach=False, model=None, effort=None):
    """Run the agent and wait for it. Detached workers are the exception."""
    stub = os.environ.get("BOARD_WATCH_SPAWN")
    env = dict(os.environ, BOARD_WATCH_KEY=agent_id, BOARD_AGENT_ID=agent_id)
    # SAY SO, LOUDLY, rather than failing as a bare ENOENT. The CLI reaches this
    # unit through the PATH pinned in `board-watch.nix`, and that PATH has to
    # name two different profile layouts: NixOS's `/etc/profiles/per-user` on
    # top, and standalone home-manager's `~/.nix-profile/bin` on book. If it is
    # missing, every run fails identically and the board must say why.
    #
    # **It is the BACKEND'S binary, not `claude`.** [top, 2026-07-31] with the
    # spirit model set to a hermes one and no `hermes` on the box, every
    # dispatch died at `execve` with a bare `[Errno 2] 'hermes'` — while this
    # check, looking for a binary that run was never going to use, passed.
    backend = bw.get_backend_for_role(role, model=model)
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
                           role=role, label=label, model=model, effort=effort)
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
                     role=role, retry=False, on_start=on_start,
                     model=model, effort=effort)
    return p.returncode, "with status %d" % p.returncode, time.time() - t0


QUEUE_FAIL = (
    "- FAILED: **what you typed could not be worked** - nothing was "
    "dispatched.\n"
    "    Solomon exited {how}; nothing was committed either. What you wrote, "
    "so it is not lost: {text} Log: `~/.cache/board-watch.log`\n")


#: The orchestrator plans and dispatches; it does not do the work. So it is
#: capped far below a worker — fifteen minutes of reading and splitting, not
#: forty-five of building. That number is also how long a tick may hold the
#: flock, so it is the latency floor for a decision he answers meanwhile.
#: Overrunning it costs him nothing but the wait: the failure path below still
#: puts his own sentence back on the board, verbatim.
ORCH_TIMEOUT_S = int(os.environ.get("BOARD_ORCH_TIMEOUT", "900"))


def _summon(notes, index, total):
    """One summoner run: register a card, spawn, wait, unregister.

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
    # THE TIER THIS RUN SPAWNS ON, resolved ONCE here — same shape as
    # `boardwork._spawn_worker`'s `spirit_tier` resolution — so the record and
    # the actual `--model`/`--effort` this run is launched with can never
    # disagree: his choice (`boardwork.orch_model()`), overridable by the same
    # `BOARD_ORCH_MODEL`/`BOARD_ORCH_EFFORT` env `role_flags` already honours.
    flag, effort = bw.orch_model()
    flag = os.environ.get("BOARD_ORCH_MODEL", flag).strip()
    effort = os.environ.get("BOARD_ORCH_EFFORT", effort).strip()
    # Registered so it shows up on his board as a running agent with his own
    # words as its title — the same card, the same box, so he can add to it
    # while it is still deciding. `kind="orchestrator"` is also what names it:
    # `ba.register` gives that kind `Solomon`, always, and `boardwork.cards()`
    # pins the row to the top of the list whether or not this run exists. Two
    # of them are two Solomons, both pinned, in birth order — which `cards()`
    # already said it did.
    #
    # `model=`/`effort=` stamped here too — [his, 2026-08-02] the same tier a
    # spirit's card names beside it now names Solomon's, dynamically: change
    # his choice of orchestrator model and the very next summon's card reads
    # the new one, with nothing to touch in `boardagents.py`.
    ba.register(aid, notes[0]["text"][:70], os.getpid(), kind="orchestrator",
                where="board-watch", session=session, model=flag, effort=effort)
    # HE CAN TAKE IT BACK UNTIL THIS RUN ACTS. Written before the spawn, like
    # the drain above it: `boardundo.py` is what ctrl+z reaches, and a run that
    # exists without a record of the orders it was given is a run he cannot
    # cancel. Removed by `end_run()` below, which also answers whether he did.
    bu.begin_run(aid, notes)
    text = "\n\n".join(m["text"] for m in notes)
    try:
        rc, how, secs = spawn(
            bw.ORCHESTRATOR_PROMPT.format(repo=REPO, host=bw.host_line(),
                                          notes=text,
                                          cap=bw.cap()),
            aid, "board: orchestrating", session=session, timeout=ORCH_TIMEOUT_S,
            role="orchestrator", model=flag, effort=effort)
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
    return QUEUE_FAIL.format(how=how, text=bp.oneline(text, 300, code=True))


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
    log("orchestrating %d thing(s) he typed across %d summoner(s)"
        % (len(msgs), len(groups)))
    if len(groups) == 1:
        fails = [_summon(groups[0], 0, 1)]
    else:
        out = {}

        def one(i, group):
            out[i] = _summon(group, i, len(groups))

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


#: How long the queue must be QUIET before a burst is planned as one batch.
#:
#: [his, 2026-08-01] *"being able to send a multitude of requests in either a
#: single or multitude of prompts"* — how he broke his thinking into box-fulls
#: is not how the work divides, so a sentence typed 40 seconds after another
#: must not be planned by a second summoner that cannot see the first. The
#: whole batch reaches ONE planner (the summoner dial defaults to 1) and is
#: grouped by file set there.
#:
#: **A LONE SENTENCE WAITS FOR NOTHING.** This started as a flat 75s and he
#: felt it within the hour — *"why does it take seemingly minutes for prompts
#: to get picked up and acted upon"* — then at 10s and he felt that too:
#: *"it still took like a few seconds even though no summoners were busy"*.
#: Both are correct readings. Measured: the path unit starts the tick ~100ms
#: after the queue file appears, so ANY hold here is the whole of the delay he
#: can see before a summoner starts thinking, and for one sentence it buys
#: nothing — there is no second item to batch it with.
#:
#: So the default is ZERO: one thing queued is planned at once, exactly as it
#: was before any of this existed. The batching this feature exists for happens
#: on the path where it costs nothing (below).
COALESCE_QUIET_S = float(os.environ.get("BOARD_COALESCE_QUIET", "0"))

#: ...and the window once TWO OR MORE things are already queued, which is the
#: only state that PROVES a burst rather than guessing at one. Nothing waits on
#: a guess: by the time this applies he has already sent more than one thing.
#:
#: The other half of the batching is free and needs no window at all: this
#: script holds the flock while it waits on a summoner, so everything typed
#: during a run is drained together by the next tick whatever these are set to.
COALESCE_BURST_S = float(os.environ.get("BOARD_COALESCE_BURST", "40"))


def coalescing(waiting, now=None):
    """Seconds to keep waiting for the rest of the burst, or 0 to plan it now.

    The window is `COALESCE_QUIET_S` for ONE queued item (zero by default) and
    `COALESCE_BURST_S` for several. It is bounded from BOTH ends, which is what
    keeps a hold from ever becoming a stall: it ends when the newest item has
    sat quiet for the window, and unconditionally once the OLDEST has waited
    one window — so a batch is planned at most `window` seconds after its first
    sentence however fast he keeps typing, and a queue that has been sitting
    (blocked behind a running summoner, say) is planned at once, being already
    coalesced by definition.

    Zero, too, if anything in the queue carries no timestamp: an unstamped item
    is one this cannot reason about, and the safe answer for a message of his
    is to work it, not to hold it.
    """
    now = time.time() if now is None else now
    stamps = [float(m.get("sent") or 0) for m in waiting]
    if not stamps or not all(stamps):
        return 0.0
    window = COALESCE_BURST_S if len(stamps) > 1 else COALESCE_QUIET_S
    if window <= 0:
        return 0.0
    oldest_left = window - (now - min(stamps))
    quiet_left = window - (now - max(stamps))
    if oldest_left <= 0 or quiet_left <= 0:
        return 0.0
    return max(0.0, min(oldest_left, quiet_left))


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
    # A BURST IS ONE PLANNING PROBLEM. Wait out the rest of what he is typing
    # before planning any of it, so two sentences a minute apart reach ONE
    # summoner that can group them by file set, instead of two that each
    # dispatch a spirit into the same files.
    #
    # It SLEEPS here rather than returning and being re-triggered, and that is
    # deliberate twice over: `board-inbox.path` is level-triggered, so returning
    # with the queue still full is a respawn every few hundred milliseconds for
    # the length of the hold — and this run holds the flock, so every trigger
    # arriving meanwhile is already a no-op. It is the same shape as waiting on
    # a summoner (up to 15 min, `ORCH_TIMEOUT_S`) and much shorter. The queue is
    # re-read after each sleep, so a sentence typed DURING the hold joins the
    # same batch and pushes the window out, up to the hard ceiling.
    while True:
        hold = coalescing(waiting)
        if not hold:
            break
        log("%d note(s) queued - holding %ds for the rest of the burst"
            % (len(waiting), round(hold)))
        time.sleep(hold)
        try:
            waiting = ba.pending()
        except OSError as e:
            log("could not look at the queue: %s" % e)
            return False
        if not waiting:     # taken by a concurrent drain - nothing to do
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
        def capped(rec):
            """Was this stash's death the cap's doing, not a crash's?

            The unit name is the decision's key and is REUSED by every
            session of the same decision, so only a journal marker at or
            after the stash's own start counts — an older marker belongs to
            a session that already handed back. `reconcile()` asks only for
            a stash that HAD an owner, so the pid check is belt-and-braces.
            """
            key = rec.get("key") or ""
            return bool(rec.get("pid")) and bool(key) and bw.unit_capped(
                bw.DECISION_PREFIX + key, since=rec.get("started"))

        for rec in bm.reconcile(path=BOARD, capped=capped):
            # Say which of reconcile's cases it was. A cap cut is a CAUSE —
            # the work is handed on, not lost — and the log must not be the
            # one place that still reads it as a death. A pid-less stash
            # never had an agent to lose, and the bullet it writes is
            # careful about that; the log must not invent a death either.
            if rec.get("capped"):
                log("returned decision %s to NEEDS YOU: its agent was cut off "
                    "by the cap - it resumes automatically"
                    % (rec.get("num") or rec.get("key")))
            elif rec.get("pid"):
                log("returned decision %s to NEEDS YOU: its agent is gone"
                    % (rec.get("num") or rec.get("key")))
            else:
                log("returned decision %s to NEEDS YOU: nothing was ever "
                    "working it" % (rec.get("num") or rec.get("key")))
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
    # THE TIER THIS DECISION SPAWNS ON, resolved ONCE here and both stamped on
    # the card and handed to `spawn` — the same shape the orchestrator branch
    # above uses, so the model the card names can never disagree with the model
    # the run launches with. Left unstamped, the decision card drew no tier at
    # all (`spawn` defaulted model=None -> `role_flags` still launched on the
    # decision default, but the stash carried nothing for `AgentRow` to read).
    dflag, deffort = bw.role_tier("decision")
    try:
        rec = bm.start(item["key"], where="board-watch", pid=os.getpid(),
                       path=BOARD, session=session, model=dflag, effort=deffort)
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
                          session=session, model=dflag, effort=deffort,
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
