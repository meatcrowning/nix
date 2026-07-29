#!/usr/bin/env python3
"""board-watch — spawn ONE headless agent when he newly answers a board decision.

`~/nix/docs/board.md` is where he answers the questions agents park for him
(`apps/board/AGENTS.md`). Until this existed, an answer sat there until he next
opened a terminal and told somebody about it. This closes that loop: the answer
itself is the trigger.

Deployed to ~/.config/scripts by home/srvs/board-watch.nix, which also carries
the systemd units and the reasoning for the mechanism. Read that file first.

WHAT IT WILL AND WILL NOT DO — his two decisions, and they are settled:

  * The agent WORKS, but never REBUILDS. It implements, tests, commits with a
    pathspec and pushes to main. It never runs `sudo rebuild-top`, never
    reloads the compositor and never touches the live panel. `apps/` runs live
    source, so most work is picked up on his next relaunch anyway; anything that
    genuinely needs a rebuild is left undone and SAID SO on the board. The
    machine must never change underneath him.
  * It fires only while he is AT the machine. Away, asleep or locked, the answer
    is QUEUED, not dropped — see gate() and the "no state update" trick below.

AND IT MOVES THE ITEM. Answering used to leave the decision sitting in NEEDS YOU
for the whole run, so the board went on asking him for something he had already
given. Now the decision is relocated into IN FLIGHT — his answer on the row, its
raw lines stashed — as the agent is spawned, and one of three things brings it
back out: the agent lands it (`boardctl land`, which the prompt below tells it
to use), the agent fails and `give_back()` puts the decision back byte-for-byte
with a bullet saying so, or this process is killed outright and the NEXT tick's
reconcile() sees a dead owner pid and does the same. An item cannot sit in IN
FLIGHT with nothing working on it for longer than one timer interval. All of
that mechanism is `apps/board/boardmove.py`; read its docstring.

Consequence worth knowing: an item that has been moved out of NEEDS YOU is no
longer fingerprinted, so **moving an item into IN FLIGHT by hand suppresses the
auto-spawn for it**. That is correct — work is already underway — but it means
whoever moves it owns doing the work.

THE THREE HAZARDS, and how each is defended:

  1. THE FEEDBACK LOOP. An agent that works a decision edits board.md itself
     (moving the item to LANDED), which fires the watcher again, forever. The
     defence is SEMANTIC, not authorship-based — do not try to work out who
     wrote the file, because the honest answer is often "a git merge". Instead
     fingerprint only the ANSWER-BEARING state of each decision (which options
     are ticked, plus his free text) and fire only when a decision that was
     already known becomes newly answered. An item moving to LANDED, a reworded
     paragraph, a new question, a new IN FLIGHT row: no new answer, no fire.
  2. THE SYNC ALSO WRITES. nix-docs-sync pulls book's copy every five minutes
     with no human in the loop. Same filter handles it — and note that an answer
     he typed on BOOK and that arrived here by `git pull` SHOULD fire. That is
     the same event, not a false positive, which is exactly why the filter looks
     at content and not at provenance.
  3. CONCURRENCY. Two rapid edits must not put two agents on one shared git
     index. flock() below, plus systemd's own refusal to run a oneshot twice.

FIRST RUN records the whole board and fires nothing: three of his decisions are
already answered, and waking up to three agents is not the feature.

TESTING. Every side effect is overridable by environment, so the trigger, the
filter, the queue and the dedupe can be exercised without spawning anything:

    BOARD_WATCH_BOARD       store to read (default ~/nix/docs/board.md)
    BOARD_WATCH_STATE       state dir    (default ~/.local/state/board-watch)
    BOARD_WATCH_LOG         log file     (default ~/.cache/board-watch.log)
    BOARD_WATCH_SPAWN       command run INSTEAD of `claude`; the prompt arrives
                            on stdin and $BOARD_WATCH_KEY names the decision
    BOARD_WATCH_GATE        force the at-the-machine gate: `open` or `closed`
    BOARD_WATCH_REPO        the checkout the agent works in (default ~/nix)

`tools/board-watch-test.py` drives all of them against a throwaway copy.
"""
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
REPO = os.environ.get("BOARD_WATCH_REPO", os.path.join(HOME, "nix"))
BOARD = os.environ.get("BOARD_WATCH_BOARD", os.path.join(REPO, "docs", "board.md"))
STATE = os.environ.get("BOARD_WATCH_STATE",
                       os.path.join(HOME, ".local", "state", "board-watch"))
LOG = os.environ.get("BOARD_WATCH_LOG", os.path.join(HOME, ".cache", "board-watch.log"))

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
import boardmove as bm                                           # noqa: E402
import boardparse as bp                                          # noqa: E402


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
    return "idx:" + ticked + "|ans:" + " ".join(item["answer"].split())


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
    try:
        with open(os.path.join(STATE, "state.json")) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {"version": 1, "answers": {}, "queued": [], "runs": []}
    d.setdefault("answers", {})
    d.setdefault("queued", [])
    d.setdefault("runs", [])
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
FAIL_TEMPLATE = (
    "- **board-watch tried decision {num} ({title}) and did not finish it** - "
    "the agent exited {how}. Nothing was committed on its behalf; the answer is "
    "still on record above. Log: `~/.cache/board-watch.log`\n")


def note_on_board(bullet):
    """Add one bullet to WAITING ON YOU TO DO.

    He must be able to see that something was attempted and failed WITHOUT
    reading a log, so a failure that only reached the log is a failure that did
    not happen. `boardmove.note` is the shared implementation — the same
    targeted line insert, advisory lock, digest re-check and atomic replace
    `boardctl` and the app use, so three writers cannot interleave into a
    half-written store.
    """
    try:
        return bm.note(bullet, path=BOARD)
    except (bm.BoardError, OSError) as e:
        log("could not add the failure note: %s" % e)
        return False


# ------------------------------------------------------------------ the agent
PROMPT = """You are running headless, with no human watching, on the machine \
`top` (x86_64 NixOS, flake attribute `top`). Work in `{repo}`.

He answered one decision on his board (`docs/board.md`, the store behind the \
`board` app). Your whole job is that ONE decision, below, verbatim from the \
file. Do not pick up any other item.

--- the decision, as it stands in the file ---
{item}
--- end ---

His answer: {answer}

RULES, in force for this session:

1. **NEVER rebuild and never change the running machine.** No `sudo \
rebuild-top`, `nixos-rebuild`, `hyprctl` (reload, plugin, dispatch or \
otherwise), `qs ipc`, `systemctl`, `loginctl`. `apps/` runs live source, so a \
`.py`/`.qml` change there is picked up when he next relaunches the app and \
needs nothing from you. If the work genuinely cannot land without a rebuild, a \
compositor reload or a panel hot-reload: **stop, leave that part undone**, and \
say so on the board (below). Half a change plus an honest note beats a machine \
that changed while he was not looking.
2. **Never open a window on his screen and never drive his running apps.** No \
screenshots, no GUI, no MPRIS, no launching a packaged app "just to check". \
Offscreen harnesses (`QT_QPA_PLATFORM=offscreen`) and `tools/sandbox.sh` only. \
He does every visual check himself.
3. **The git index in this checkout is SHARED** with him and with other \
agents. `git commit -m "msg" -- <explicit> <paths>`, always. Never a bare \
`git commit`, never `-a`, never `git add` on an already-tracked file. New \
files: `git add -N` only. Never run a destructive or reverting git command \
(`reset --hard`, `checkout --`, `restore`, `stash`, `clean`) — he leaves real \
uncommitted work here.
4. **Push to `main`** when it works. No branch, no PR.
5. Read `AGENTS.md` at the repo root, then the nested one closest to whatever \
you are editing, then `docs/DESIGN.md` if anything you do puts pixels on a \
screen. They outrank your instincts about this codebase.
6. **When you are done, record it on the board — with the tool, never by \
hand.** This decision has ALREADY been moved out of NEEDS YOU and into IN \
FLIGHT for you, carrying your answer, so he can see it is being worked. Close \
the loop from `{repo}` with exactly one of:

       python3 apps/board/tools/boardctl.py land {key} --commit <hash> \
--what '<one line, imperative, like a commit subject>'
       python3 apps/board/tools/boardctl.py note '**<title>** - <what is done, \
what is not, and whether a rebuild is now pending and why>'

   `land` when the work is complete: it removes the IN FLIGHT row and appends \
`| commit | what |` under today's date in LANDED. `note` when it is not: the \
row stays in flight and he gets a bullet in WAITING ON YOU TO DO. Run \
`boardctl.py --help` for the rest.

   **Do not edit `docs/board.md` in an editor.** It is a store three programs \
parse and write concurrently — the app he may have open right now, the \
five-minute sync, and this tool — and every one of those edits is a targeted \
line edit under a lock with a digest re-check. A hand-written table row or a \
reflowed section is a bug, and a half-written one syncs to the other machine. \
`boardctl` never touches a line it was not asked to. `docs/` is its own git \
repo inside this checkout, so commit the result from inside `docs/`.
7. If the answer is ambiguous or the work turns out to be much larger than the \
item implies, do the smallest honest thing and write what you found onto the \
board instead of guessing big.

There is nobody to ask. Finish, or write down why you did not.
"""

# Allow the tools a working agent needs; deny the ones that change the machine
# out from under him. The prompt is the primary defence and this is the
# mechanical one — belt and braces, because rule 1 is the whole point of the
# feature and a model that forgets it costs him his session.
ALLOW = ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "Task", "TodoWrite",
         "NotebookEdit", "WebFetch", "WebSearch"]
DENY = ["Bash(sudo:*)", "Bash(rebuild-top:*)", "Bash(nixos-rebuild:*)",
        "Bash(rbsys:*)", "Bash(rbhome:*)", "Bash(update:*)",
        "Bash(hyprctl:*)", "Bash(qs:*)", "Bash(systemctl:*)", "Bash(loginctl:*)",
        "Bash(git reset:*)", "Bash(git checkout:*)", "Bash(git restore:*)",
        "Bash(git stash:*)", "Bash(git clean:*)"]


def spawn(item, prompt):
    """Run the agent. Returns (exit code, how it ended, seconds)."""
    stub = os.environ.get("BOARD_WATCH_SPAWN")
    env = dict(os.environ, BOARD_WATCH_KEY=item["key"])
    if stub:
        cmd = ["/bin/sh", "-c", stub]
    else:
        cmd = ["claude", "-p", prompt,
               "--permission-mode", "acceptEdits",
               "--allowedTools", *ALLOW,
               "--disallowedTools", *DENY,
               "--output-format", "text",
               "-n", "board: decision %s" % (item["num"] or item["key"])]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=REPO, env=env, timeout=AGENT_TIMEOUT_S,
                           input=prompt if stub else None,
                           capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        return 124, "after %d minutes without finishing" % (AGENT_TIMEOUT_S // 60), \
            time.time() - t0
    except OSError as e:
        return 127, "without starting at all (%s)" % e, time.time() - t0
    if p.stdout:
        log("agent said: " + " ".join(p.stdout.split())[:400])
    if p.returncode != 0 and p.stderr:
        log("agent stderr: " + " ".join(p.stderr.split())[:400])
    return p.returncode, "with status %d" % p.returncode, time.time() - t0


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

    # NOTHING STAYS STRANDED. If a previous run was killed outright — OOM,
    # reboot, systemd's TimeoutStartSec — its decision is sitting in IN FLIGHT
    # with nothing working on it. Hand back every item whose owning process is
    # gone, before deciding what to fire on. Worst case is one timer interval.
    try:
        for rec in bm.reconcile(path=BOARD):
            log("returned decision %s to NEEDS YOU: its agent is gone"
                % (rec.get("num") or rec.get("key")))
    except (bm.BoardError, OSError) as e:
        log("could not reconcile stranded items: %s" % e)

    try:
        src = bp.read(BOARD)
    except OSError as e:
        log("cannot read %s: %s" % (BOARD, e))
        return 0
    doc = bp.parse(src)
    state = load_state()
    seen = state["answers"]
    first_run = not seen

    fresh = {}
    fired_candidates = []
    for item in doc["needs"]:
        fp = fingerprint(item)
        fresh[item["key"]] = fp
        if first_run:
            continue
        if item["key"] not in seen:
            # A decision that arrives already answered was written that way by
            # an agent, not answered by him. Record it; do not act on it.
            continue
        if fp != seen[item["key"]] and item["answered"]:
            fired_candidates.append(item)

    if first_run:
        state["answers"] = fresh
        save_state(state)
        log("first run: recorded %d decisions, fired nothing" % len(fresh))
        return 0

    if not fired_candidates:
        # Everything else — LANDED rows, reworded prose, a pulled merge, our own
        # failure note — updates the record and stops here. HAZARDS 1 and 2.
        if fresh != seen or state["queued"]:
            state["answers"] = fresh
            state["queued"] = []
            save_state(state)
        log("no new answer")
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
    prompt = PROMPT.format(repo=REPO, item=item_span(doc["lines"], item),
                           answer=said, key=item["key"])

    # MOVE IT BEFORE THE AGENT RUNS. An answered decision that sits in NEEDS YOU
    # while an agent works it is the board asking him for something he has
    # already given — the whole reason this exists. The move carries his answer
    # onto the row and stashes the decision verbatim, so the failure paths below
    # can put it back exactly as he wrote it. `pid` is OURS: if this process is
    # killed outright, the next tick's reconcile() sees a dead owner and hands
    # the item back on its own.
    moved = False
    try:
        rec = bm.start(item["key"], where="board-watch", pid=os.getpid(),
                       path=BOARD)
        moved = True
        log("moved decision %s into IN FLIGHT" % (item["num"] or "?"))
    except (bm.BoardError, OSError) as e:
        # Bookkeeping must never cost him the work. Spawn anyway and say so.
        log("could not move decision %s into IN FLIGHT (%s) - working it anyway"
            % (item["num"] or "?", e))

    rc, how, secs = spawn(item, prompt)
    state = load_state()
    state["runs"] = (state["runs"] + [{
        "key": item["key"], "num": item["num"], "rc": rc,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(secs)}])[-20:]
    save_state(state)

    if rc == 0:
        log("decision %s finished in %dm%02ds" % (item["num"] or "?",
                                                  secs // 60, secs % 60))
        # It worked: whatever the agent did with the row (landed it, or left it
        # in flight because a rebuild is pending), the item is not stranded and
        # must not be yanked back into NEEDS YOU by the next reconcile().
        bm.forget(item["key"])
        return 0

    log("decision %s FAILED %s after %dm%02ds" % (item["num"] or "?", how,
                                                  secs // 60, secs % 60))
    # HAND IT BACK. An item left in IN FLIGHT with nothing working on it reads
    # as handled, which is worse than it still being open — so the decision goes
    # back where it was, byte for byte, and the bullet says what happened. One
    # edit, so the row is never gone while the decision is not yet back.
    bullet = FAIL_TEMPLATE.format(num=item["num"] or "?", title=item["title"],
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
