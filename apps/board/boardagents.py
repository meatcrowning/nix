"""Who is working right now, and how he reaches them mid-flight.

Two halves of one question he asked in one sentence: *"id like there to be a
display on the board of currently active systemd claude agents running and a
brief title / description and a text box for me to send commands / new ideas /
fixes to an agent"*.

THE HARD CONSTRAINT, and the whole reason this module is shaped the way it is
-----------------------------------------------------------------------------
**You cannot type into a running agent.** `board-watch` spawns `claude -p` with
its stdin closed; the interactive session's stdin belongs to his terminal. There
is no pipe to push a sentence down, and pretending otherwise would be the exact
dishonest control docs/DESIGN.md §10 forbids. So a message is a FILE, and there
are two ways it reaches somebody:

  1. **An inbox the agent polls.** Every agent `board-watch` spawns is told, in
     its prompt, to run `boardctl.py inbox take` between steps and fold in
     whatever it prints. That reaches an agent that is already running, within a
     step or two. (Only agents spawned AFTER this landed; an older one has no
     such line in its prompt and will never look.)
  2. **The queue, which is the guarantee.** A message nobody took does not
     evaporate: `sweep()` moves it to `queue/`, and the next `board-watch` tick
     spawns one agent whose whole job is what he wrote.

NOTHING IS EVER DELETED, AND NOTHING IS EVER IN TWO PLACES. A message file is
created by `os.replace()` into exactly one of three directories and only ever
moves between them by `os.replace()` again:

    inbox/to/<agent>/   left for a specific agent, not yet read
    inbox/queue/        waiting for the next agent (nobody read it, or nobody
                        was running when he wrote it)
    inbox/taken/        an agent read it. Kept, because "it was delivered" is a
                        claim the UI makes and a claim needs evidence.
    inbox/dropped/      HE took it back off the queue (`remove_queued`). Kept
                        for the same reason: removed from the queue is not the
                        same as never written, and this app deletes no prose.
    inbox/editing/      transient, and only ever for the length of three
                        syscalls: `edit_queued` claims a message here so a
                        concurrent drain cannot read it half-rewritten, then
                        puts it back. `sweep()` rescues anything stranded.

That is what makes "the box never loses what he typed" a property of the
filesystem rather than of anybody's care, and it is what `tools/board-test.py`
asserts: after every path through this module, the message is in exactly one of
the three.

LIVENESS: THERE IS ONLY ONE RULE, and it is `boardmove`'s
---------------------------------------------------------
A decision's agent is alive iff its stash's pid is alive AND the kernel start
time of that pid still matches — `boardmove._alive`, reused verbatim, not
reimplemented. A recycled pid cannot make a dead agent look alive, and there is
deliberately no second definition of "running" in this tree.

WHAT IT CAN AND CANNOT SEE, stated rather than papered over
------------------------------------------------------------
  * **A decision agent**: fully known. `board-watch` stashed its title, where it
    is working and its owning pid before it spawned.
  * **A note agent** (one spawned to work the queue): registered in
    `agents/<id>.json` by `board-watch` itself, same fields.
  * **An interactive Claude Code session**: NOT a systemd unit and not
    enumerable like one. What is real and measurable is the process — so it is
    listed as a process and described as one ("board sees the process, not what
    it is doing"). It gets no title it did not earn. Saying "one session,
    unknown state" is better than a confident lie about what it is doing.

NO TIME PRESSURE. Nothing here hands the UI an age, an elapsed time, a count of
minutes or anything that ramps. `started`/`at` stamps exist because escalation
is machine business, exactly as `boardmove`'s stash time is; they must not reach
the screen.
"""
import hashlib
import json
import os
import re
import time

import boardmove as bm

# A message nobody has taken is escalated to the queue this long after it was
# written, even if its agent is still alive. Machine business, never drawn: it
# is the bound that makes "it will reach somebody" true rather than hopeful, and
# it sits under board-watch's own 45-minute agent cap so a run that is going to
# read its inbox has already had every chance to.
ESCALATE_AFTER_S = int(os.environ.get("BOARD_INBOX_ESCALATE", "1800"))

# How long a message may sit CLAIMED by an in-place edit (`edit_queued`) before
# `sweep()` decides the process doing the editing is gone and puts it back in
# the queue. An edit is three syscalls, so anything this old is wreckage — and
# generous enough that a live edit is never yanked out from under itself.
EDIT_RESCUE_AFTER_S = 60

CLAUDE_COMMS = ("claude", ".claude-wrapped")

# ------------------------------------------------------- a summon is not a card
# HOW LONG A SPAWN MAY GO UNCONFIRMED before its card is drawn anyway. [his,
# 2026-07-30] *"a card should appear only once the summon has actually
# completed"* — a registration written the instant `systemd-run` returns is a
# claim that a spirit is working when all that has happened is an `execve`,
# and a `claude` that dies two seconds later on an API 500 left a card behind
# for an agent that never started. Measured on book 2026-07-30: `systemd-run
# --service-type=exec` returns 19 ms after the call, i.e. at the exec and not at
# the agent.
#
# So a worker's record is written UNCONFIRMED and the card is withheld until
# there is evidence the process is really up — its transcript, which only the
# running agent writes (`boardphase.transcript`). Confirmation is STICKY: a
# transcript that later rotates away does not un-draw a live card.
#
# ...and this is a bound, not a gate. Past it a live registration is drawn
# whatever the transcript says, because hiding work that genuinely exists is the
# worse failure of the two and the observed line already says honestly that it
# cannot see the agent (`unlinked`). Well under `boardphase.START_GRACE_S`,
# which is how long the CARD is allowed to say `starting`.
CONFIRM_GRACE_S = float(os.environ.get("BOARD_CONFIRM_GRACE", "20"))


# ------------------------------------------------------------ when it was born
# ORDERING ONLY, AND IT NEVER REACHES THE SCREEN. The cards are drawn oldest
# first so a new agent appends at the bottom and the rows above it do not move
# — his reason for asking for one flat list: *"just keep agents ordered by
# birth/age so they dont move around so much"*. That is the same use `promote()`
# already makes of a stamp, and it is why the no-time rule (this module's
# docstring, `boardwork.py`'s) is not bent by it: an ordering is not an age, and
# nothing derived from these numbers is drawn, counted or ramped.
def _boot_epoch():
    try:
        with open("/proc/stat") as f:
            for line in f:
                if line.startswith("btime "):
                    return float(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def _pid_born(pid):
    """A process's own start time as an epoch, for the one kind of agent that
    carries no stamp of ours: an interactive session nothing here spawned."""
    ticks = bm._proc_start(pid) if pid else None
    if ticks is None:
        return 0.0
    try:
        return _boot_epoch() + float(ticks) / os.sysconf("SC_CLK_TCK")
    except (ValueError, OSError):
        return 0.0


def born(rec, pid=0):
    """Epoch seconds for a record, from whichever stamp it carries. `0.0` when
    there is none at all, which sorts oldest — stable, and never a guess drawn
    as a fact."""
    for k in ("started", "at"):
        v = (rec or {}).get(k)
        if v:
            try:
                return time.mktime(time.strptime(str(v)[:19], "%Y-%m-%dT%H:%M:%S"))
            except ValueError:
                pass
    return _pid_born(pid)


# --------------------------------------------------------------- state layout
def _root():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "board")


def inbox_dir(*parts):
    d = os.path.join(_root(), "inbox", *parts)
    os.makedirs(d, exist_ok=True)
    return d


def agents_dir():
    d = os.path.join(_root(), "agents")
    os.makedirs(d, exist_ok=True)
    return d


def clean_id(s):
    return re.sub(r"[^a-z0-9._-]+", "-", str(s or "").lower()).strip("-") or "agent"


# ------------------------------------------------------------------- the names
#: **An agent has a name, and that is what he is shown.** His words:
#: *"can you give the workers regular human names? you can still keep the coded
#: names if you'd like but i think itd be interesting to have them referred to
#: by regular names"*, then: *"i want the names of agents to be taken from the
#: names of demons in the lesser key of solomon"* — so the pool is the Ars
#: Goetia's 72, complete and in the traditional order, 1 Bael ... 72
#: Andromalius (the Lemegeton's list as Wikipedia gives it, fetched
#: 2026-07-29). It ran 56 for a while — the short Goetia spellings padded out
#: with Theurgia-Goetia / Ars Paulina names — until he asked for the full
#: seventy-two.
#:
#: THE NAME IS PRESENTATION AND NOTHING IS KEYED ON IT. The id (`w1a2b3c`) is
#: still the key: the systemd unit, `~/.cache/board-work/<id>.log`, the
#: observation sidecar, the inbox directory and every record on disk are named
#: by it, and a message is addressed by it. Renaming any of those would orphan a
#: worker that is running right now.
#:
#: TWO RULES ON WHAT MAY GO IN. **ASCII only**: §2.3, a glyph the font lacks
#: clips the whole row, so `Bune`, `Ronove`, `Vine`, `Raum`, `Gaap` and never
#: the diacritical spellings. **Distinct case-insensitively**, because
#: `boardctl inbox send --to` matches on the name. Length is deliberately NOT
#: one any more: `AgentRow.nameW` measures per card (minimum 7 cells), so
#: `Andromalius` at eleven costs its own card a few title cells and the rest
#: of the list nothing. Where the pre-72 pool already had a spelling it is
#: KEPT — `Marax` (not Morax), `Haures` (not Flauros), `Glasya` (for
#: Glasya-Labolas, and what keeps the pool `isalpha`) — so a worker running
#: under one of those still matches its own name.
NAMES = ["Bael", "Agares", "Vassago", "Samigina", "Marbas", "Valefor", "Amon",
         "Barbatos", "Paimon", "Buer", "Gusion", "Sitri", "Beleth", "Leraje",
         "Eligos", "Zepar", "Botis", "Bathin", "Sallos", "Purson", "Marax",
         "Ipos", "Aim", "Naberius", "Glasya", "Bune", "Ronove", "Berith",
         "Astaroth", "Forneus", "Foras", "Asmodeus", "Gaap", "Furfur",
         "Marchosias", "Stolas", "Phenex", "Halphas", "Malphas", "Raum",
         "Focalor", "Vepar", "Sabnock", "Shax", "Vine", "Bifrons", "Vual",
         "Haagenti", "Crocell", "Furcas", "Balam", "Alloces", "Caim",
         "Murmur", "Orobas", "Gremory", "Ose", "Amy", "Orias", "Vapula",
         "Zagan", "Valac", "Andras", "Haures", "Andrealphus", "Kimaris",
         "Amdusias", "Belial", "Decarabia", "Seere", "Dantalion",
         "Andromalius"]

#: **The orchestrator is Solomon, always, and he is not in the pool.** [his,
#: 2026-07-29] *"make the main orchestrators name Solomon. he should always be
#: kept on the top of the agent list and should basically indicate like he's
#: there and ready to go at all times when hes not doing something."* The pool
#: above is the Lemegeton's demons; Solomon is the king who binds them, so the
#: one role that hands out the work is the one name that is never drawn from
#: the bag and never shuffled by `pick_name` — the orchestrator is a ROLE, and
#: a role that renamed itself per run would be a stranger every time.
#:
#: Seven characters — what first pushed `AgentRow.nameW` from an assumed 7
#: cells to a measurement, before the pool itself grew names past six. He is
#: not truncated: the whole point is that he is recognisable.
#:
#: If two orchestrators ever overlap — successive things typed close together —
#: they are BOTH Solomon. That is the honest reading (one role, briefly doing
#: two things) and it costs nothing: `boardctl inbox send --to Solomon` resolves
#: to a live one, `boardwork.cards()` pins them together at the top, and every
#: id underneath is still distinct.
ORCHESTRATOR_NAME = "Solomon"

#: The `kind` the orchestrator is registered under (`board-watch.py`).
ORCHESTRATOR_KIND = "orchestrator"


def name_for(agent_id):
    """The name an id maps to, with nothing else on the machine consulted.

    DERIVED, never drawn from a bag: the same id is the same name in every
    process that reads the record — the app polling behind his window,
    `boardctl`, the agent itself — and a record written before names existed
    (there is a worker running under one right now) gets a stable name rather
    than a new one on every poll. `hashlib` and not `hash()`, which is salted
    per process and would give the app and the CLI different answers.
    """
    aid = clean_id(agent_id)
    n = int(hashlib.sha1(aid.encode("utf-8")).hexdigest()[:8], 16)
    return NAMES[n % len(NAMES)]


def _live_names():
    """The names currently spoken for. Registrations only, and no /proc walk:
    this is called at spawn time, which is inside a board-watch tick."""
    out = set()
    for rec in _registrations():
        if bm._alive(rec):
            out.add(rec.get("name") or name_for(rec.get("id") or ""))
    return out


def pick_name(agent_id, taken=None):
    """`name_for`, moved along while a LIVE agent already answers to it.

    Two agents called Marbas on one board would make a note he addresses to
    Marbas ambiguous at the one moment it matters, so the name is chosen ONCE —
    at the instant the id is minted — and written into the record. Above
    `len(NAMES)` live agents there is nothing left to move to and a name
    repeats; the cap is four, and saying that plainly beats `Marbas 2`.
    """
    taken = _live_names() if taken is None else taken
    base = NAMES.index(name_for(agent_id))
    for i in range(len(NAMES)):
        cand = NAMES[(base + i) % len(NAMES)]
        if cand not in taken:
            return cand
    return NAMES[base]


# ------------------------------------------------------------------- /proc
def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return b""


#: comms whose CMDLINE is worth reading. Everything needs its comm (to spot the
#: agent) and its ppid (to walk ancestry), but reading `cmdline` for all ~1000
#: processes on this box doubled the cost of a poll for nothing: the wrapper is
#: called `.claude-wrapped`, and the cmdline check is only a fallback for a
#: launcher that execs it under a runtime's name.
CMDLINE_COMMS = CLAUDE_COMMS + ("node", "bun", "deno", "sh", "bash", "zsh")


def _procs():
    """{pid: (ppid, comm, cmdline)} for every process we can read. One pass, no
    forks — this is polled while his window is open."""
    out = {}
    try:
        names = os.listdir("/proc")
    except OSError:
        return out
    for n in names:
        if not n.isdigit():
            continue
        comm = _read("/proc/%s/comm" % n).decode("utf-8", "replace").strip()
        if not comm:
            continue
        stat = _read("/proc/%s/stat" % n).decode("utf-8", "replace")
        try:
            ppid = int(stat.rsplit(")", 1)[1].split()[1])
        except (IndexError, ValueError):
            continue
        cmd = []
        if comm in CMDLINE_COMMS:
            cmd = [c for c in _read("/proc/%s/cmdline" % n)
                   .decode("utf-8", "replace").split("\0") if c]
        out[int(n)] = (ppid, comm, cmd)
    return out


def _is_claude(comm, cmd):
    if comm in CLAUDE_COMMS:
        return True
    return bool(cmd) and os.path.basename(cmd[0]) in CLAUDE_COMMS


def _ancestors(pid, procs, limit=40):
    seen = []
    while pid and pid > 1 and len(seen) < limit:
        ent = procs.get(pid)
        if not ent:
            break
        pid = ent[0]
        seen.append(pid)
    return seen


def session_pid(procs=None):
    """The interactive Claude Code session THIS process is running under, if it
    is running under one. That is how an agent with no `BOARD_AGENT_ID` (an
    interactive session, or a subagent of one) finds out which inbox is its
    own — by walking its own ancestry, not by guessing."""
    procs = procs if procs is not None else _procs()
    for pid in [os.getpid()] + _ancestors(os.getpid(), procs):
        ent = procs.get(pid)
        if ent and _is_claude(ent[1], ent[2]):
            return pid
    return None


def self_id():
    """The inbox id the CALLER should read. `BOARD_AGENT_ID` when board-watch
    set one (a decision or note agent); otherwise this session's own."""
    env = os.environ.get("BOARD_AGENT_ID")
    if env:
        return clean_id(env)
    pid = session_pid()
    return "s%d" % pid if pid else None


# ------------------------------------------------------------- registrations
# board-watch registers a run that has no stash of its own (a note agent). A
# decision agent needs no registration: boardmove already stashed it, with the
# same pid and the same start time, and a second record would be a second
# definition of "running".
def register(agent_id, title, pid, kind="note", where="board-watch", session="",
             name="", confirmed=True, parent="", model="", effort=""):
    """`session` is the `--session-id` the spawner chose, and it is what makes
    the card able to say what the agent is really doing: `boardphase.py` finds
    `~/.claude/projects/*/<session>.jsonl` by it. An agent registered without
    one is simply not observable, and its card says exactly that.

    `name` is the human name he sees. It is PERSISTED here rather than derived
    on every read, so it cannot change under him when another agent takes the
    name this one would have been moved off; the spawner picks it beside the id
    (`boardwork._spawn_worker`), and a caller that does not is given one here.

    The one name that is NOT picked is the orchestrator's: `kind` decides it,
    here, so every path that registers one — board-watch, a test, a hand call —
    gets `Solomon` without having to know to ask for it.

    `confirmed=False` says THE SUMMON IS NOT FINISHED YET: the record exists so
    that `reap()`, `sweep()` and the concurrency cap can all see the work, and
    `boardwork.cards()` withholds its card until `_confirmed()` below finds
    evidence the agent is really running. A caller that knows its process is up
    — board-watch registering itself, a stash, a test — leaves it True and
    nothing changes for it.

    `parent` is set only for a **deepseek subspirit** (`kind="subspirit"`,
    `boardwork.subspirit`): it is the inbox id of the Claude spirit or
    orchestrator that delegated the chunk, so the UI can draw the subspirit's
    card INSET under the row that spawned it. `parentName` is resolved beside it
    (best-effort, the parent's own record) so a reader need not re-derive it.
    Both keys are ABSENT for every other kind, which is what marks a record as a
    subspirit as much as `kind` does.
    """
    rec = {"id": clean_id(agent_id), "title": title, "pid": pid,
           "confirmed": bool(confirmed),
           "name": (ORCHESTRATOR_NAME if kind == ORCHESTRATOR_KIND
                    else name or pick_name(agent_id)),
           "pidStart": bm._proc_start(pid) if pid else None, "kind": kind,
           "where": where, "session": session or "",
           "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if parent:
        rec["parent"] = clean_id(parent)
        rec["parentName"] = name_of(parent) or name_for(parent)
    # THE TIER IT RUNS ON, stamped at the spawn so the card can name it beside
    # the agent — [his, 2026-08-02] *"Balam (ds v4 flash)"*. The spawner
    # (`boardwork._spawn_worker`) has just resolved the exact `(flag, effort)`
    # this one runs on; persisting it here means the label never has to be
    # re-derived on a read and cannot change under him between two polls. Absent
    # for a record that named no model (a hand call, a pre-tiering worker), which
    # `boardwork.tier_label` reads back as "" — no parenthesis at all.
    if model:
        rec["model"] = model
    if effort:
        rec["effort"] = effort
    _write_json(os.path.join(agents_dir(), rec["id"] + ".json"), rec)
    return rec


def _reported(agent_id):
    """`boardwork.reported`, imported LAZILY — `boardwork` imports this module,
    so a top-level import here would be a cycle. Returns False if that module
    cannot be reached at all, which is the honest answer: no evidence it
    finished."""
    try:
        import boardwork as bw
        return bool(bw.reported(agent_id))
    except Exception:
        return False


def record(agent_id):
    """One agent's registration as it sits on disk, or `None`.

    The whole record, because callers want different fields of it — the name for
    a sentence he reads, the `session` uuid for the transcript the card's drawer
    tails.
    """
    if not (agent_id or "").strip():
        return None
    return _read_json(os.path.join(agents_dir(), clean_id(agent_id) + ".json"))


def name_of(agent_id):
    """The name in one agent's record, or `""` for anything that has none — a
    decision he answered, an interactive session, a task with no worker yet.
    Reads the record rather than deriving, so what the UI says back to him is
    what the card beside it is drawing."""
    return (record(agent_id) or {}).get("name") or ""


def unregister(agent_id):
    try:
        os.unlink(os.path.join(agents_dir(), clean_id(agent_id) + ".json"))
        return True
    except OSError:
        return False


def _confirmed(rec, alive):
    """Has this registration's summon actually completed? Promotes and PERSISTS.

    Three answers, and each of them is a fact rather than a guess:

    - a record written without the flag at all is confirmed — every caller that
      does not opt in knows its own process is up, and a record written before
      this existed must not vanish off his board;
    - a transcript at the session id WE chose is proof the agent process exists
      and got as far as opening its session (`boardphase.transcript`) — and on
      a runtime whose session id we cannot choose, the same proof is its run
      turning up in that runtime's own store (`boardphase.hermes_session`);
    - otherwise `CONFIRM_GRACE_S` from the registration, after which a LIVE
      record is drawn regardless — the bound, not a gate.

    A record that is dead and still unconfirmed is never confirmed, so a spawn
    that execed and immediately died leaves no card at any point. What it does
    leave is its task file, which `boardwork.reap()` files as FAILED — the loss
    is reported, never silent.
    """
    if rec.get("confirmed", True):
        return True
    import boardphase as bph
    if rec.get("session") and bph.transcript(rec.get("session")):
        pass
    elif bph.hermes_session(rec.get("id") or ""):
        pass
    elif alive and time.time() - born(rec, rec.get("pid") or 0) > CONFIRM_GRACE_S:
        pass
    else:
        return False
    try:                     # sticky: never re-derived, never withdrawn
        _write_json(os.path.join(agents_dir(), clean_id(rec["id"]) + ".json"),
                    dict(rec, confirmed=True))
    except OSError:
        pass
    return True


def _registrations():
    out = []
    for name in sorted(os.listdir(agents_dir())):
        if name.endswith(".json"):
            rec = _read_json(os.path.join(agents_dir(), name))
            if rec:
                out.append(rec)
    return out


# ------------------------------------------------------------------ messages
def _write_json(path, obj):
    """Atomically, into the target's own directory. Same rules as
    `boardparse.write` — half a message is not a message."""
    d = os.path.dirname(path)
    tmp = os.path.join(d, ".%s.tmp" % os.path.basename(path))
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _read_json(path):
    try:
        with open(path) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _msg_name():
    return "%s-%s.json" % (time.strftime("%Y%m%dT%H%M%S"),
                           os.urandom(3).hex())


def _list(d):
    out = []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for name in names:
        if not name.endswith(".json") or name.startswith("."):
            continue
        rec = _read_json(os.path.join(d, name))
        if rec:
            rec["file"] = os.path.join(d, name)
            out.append(rec)
    # OLDEST FIRST, by the stamp `send()` wrote and not by the filename. The
    # name is second-resolution plus three random bytes, so two things he typed
    # inside the same second sorted by coin toss — which is the order they are
    # then handed to an agent in, and the order the queue is joined in for the
    # orchestrator. His second thought arriving before his first is a real
    # misreading, and it costs one key to remove.
    out.sort(key=lambda r: (float(r.get("sent") or 0), os.path.basename(r["file"])))
    return out


def _move(msg, dest_dir, state=None, by=None):
    """The only way a message ever changes state. A rename inside one
    filesystem, so it is in exactly one directory at every instant — that is the
    whole "nothing he typed is lost" argument.

    The rename happens FIRST and alone; `state`/`by` are then written back into
    the file at its new home, best effort. That order is deliberate — the
    "exactly one directory" invariant must not depend on a second write
    succeeding, so a failed stamp costs a provenance line and nothing else.

    Why stamp at all: `taken/` is the resting place of BOTH "its agent read it"
    and "nobody read it, sweep escalated it and some later run drained it", and
    for its first months the two were indistinguishable on disk — `send()`
    computed a `state` and never persisted it, and `_move` recorded nothing. So
    the one question actually asked of this store — *why did my worker never act
    on the note I sent it?* — could only be answered by reading `ctime` and
    guessing. Now the file says who moved it, when, and out of which state.
    """
    dest = os.path.join(dest_dir, os.path.basename(msg["file"]))
    os.replace(msg["file"], dest)
    msg = dict(msg)
    msg["file"] = dest
    if state:
        msg["state"] = state
        msg["movedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        if by:
            msg["movedBy"] = clean_id(by)
        try:
            rec = {k: v for k, v in msg.items() if k != "file"}
            _write_json(dest, rec)
        except OSError:
            pass
    return msg


def send(text, to=None, to_title="", to_kind=""):
    """His words, filed. Returns the message, with `state`:

      `delivered` — left in a running agent's inbox. NOT "it read it": that is
                    what `taken` means, and the UI must keep the two apart.
      `queued`    — nobody was running (or the named agent has gone), so it
                    waits for the next agent board-watch spawns.
    """
    text = " ".join((text or "").split("\n"))  # keep it one prompt-shaped block
    text = (text or "").strip()
    if not text:
        return None
    live = {a["id"] for a in agents() if a["state"] == "running"}
    tid = clean_id(to) if to else None
    delivered = bool(tid and tid in live)
    msg = {"to": tid or "", "toTitle": to_title, "toKind": to_kind,
           "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "sent": time.time(),
           "text": text, "host": os.uname().nodename,
           # Persisted, not only returned: the state is the one thing anybody
           # asks this file afterwards, and a value that lives only in the
           # caller's return value is a value nobody can look up. See `_move`.
           "state": "delivered" if delivered else "queued"}
    d = inbox_dir("to", tid) if delivered else inbox_dir("queue")
    path = os.path.join(d, _msg_name())
    _write_json(path, msg)
    msg["file"] = path
    return msg


def for_agent(agent_id):
    """What is sitting unread in one agent's inbox.

    Reads without creating: this is called once per agent per poll while his
    window is open, and an inbox directory per pid of every session that ever
    ran would be litter nobody asked for.
    """
    return _list(os.path.join(_root(), "inbox", "to", clean_id(agent_id)))


def pending():
    """What is waiting for the NEXT agent — the queue, drained by board-watch."""
    return _list(inbox_dir("queue"))


def taken():
    return _list(inbox_dir("taken"))


# ---- his second thoughts about a queued message -------------------------
# *"allow the user to remove queued waiting for next agent items or edit them
# in place"*. Both act on a message that a board-watch tick may be draining at
# this exact instant, so neither is allowed to invent a second way of moving a
# file: the claim is always `os.replace`, which either wins or raises, and a
# message that has already gone is REPORTED gone rather than quietly recreated.
# Recreating it is the failure that matters — an in-place rewrite of the queue
# path would resurrect a message the drain had just taken, so the agent already
# working it would find it queued again and do it twice.

def msg_id(msg):
    """The handle the UI holds a queued message by: its file's stem.

    Not the text — two identical sentences are two messages — and not an index,
    which the next drain would shift out from under his cursor.
    """
    return os.path.splitext(os.path.basename(msg.get("file") or ""))[0]


def _queued_file(mid):
    """The queue path for an id, or None if the id is not one we wrote.

    A name, never a path: an id that walks out of the queue directory is
    refused rather than sanitised into something else's file.
    """
    name = str(mid or "")
    if not name or name != os.path.basename(name) or name.startswith("."):
        return None
    if not re.fullmatch(r"[0-9A-Za-z._-]+", name):
        return None
    return os.path.join(inbox_dir("queue"), name + ".json")


def remove_queued(mid):
    """He takes a queued message back. Returns it, or None if it has gone.

    Gone means a board-watch tick drained it between the menu opening and his
    click, and the honest answer is that nothing was removed — the run that
    took it is already working the sentence.

    It is not unlinked. `dropped/` is a fourth resting place, and the
    conservation property holds across it: the message is in exactly one
    directory at every instant, and what he wrote is still on disk.
    """
    path = _queued_file(mid)
    if path is None:
        return None
    rec = _read_json(path) or {}
    dest = os.path.join(inbox_dir("dropped"), os.path.basename(path))
    try:
        os.replace(path, dest)
    except OSError:
        return None            # drained (or never there): nothing was removed
    rec["file"] = dest
    return rec


def edit_queued(mid, text):
    """Rewrite a queued message's body. Returns it, or None if it has gone.

    CLAIM, WRITE, PUT BACK — in that order, and the claim is the same
    `os.replace` every other move here is. Moving it out of `queue/` first is
    what makes this safe against a concurrent drain: either we get the file and
    the drain does not see it, or the drain got it and our claim raises. The
    alternative — writing the queue path in place — would either be read torn
    by a drain mid-write or recreate a message that had just been taken.

    While it is claimed the message sits in `editing/`, so it is still in
    exactly one directory. `sweep()` puts back anything left there by a process
    that died mid-edit.
    """
    text = " ".join((text or "").split("\n")).strip()
    if not text:
        return None
    path = _queued_file(mid)
    if path is None:
        return None
    name = os.path.basename(path)
    held = os.path.join(inbox_dir("editing"), name)
    try:
        os.replace(path, held)
    except OSError:
        return None            # drained: the old text is what the agent got
    rec = _read_json(held) or {}
    rec["text"] = text
    rec["editedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _write_json(held, rec)
    os.replace(held, path)     # back into the queue, under its own name
    rec["file"] = path
    return rec


def take(agent_id=None, include_queue=False):
    """Consume this agent's messages. Returns them; they move to `taken/`.

    `include_queue` is board-watch draining the queue into the run it is about
    to spawn — an ordinary agent never takes another agent's mail.
    """
    aid = clean_id(agent_id) if agent_id else self_id()
    msgs = for_agent(aid) if aid else []
    if include_queue:
        msgs += pending()
    return [_move(m, inbox_dir("taken"), state="taken", by=aid) for m in msgs]


def drain():
    """Take the whole queue, for the run that is about to work it.

    Called by board-watch immediately BEFORE it spawns, never after: a message
    still in the queue when the process dies would be worked twice, and a
    message deleted after a crash would be worked never. Moving first and
    reporting the failure onto the board is the trade that loses nothing.
    """
    return [_move(m, inbox_dir("taken"), state="drained",
                  by=os.environ.get("BOARD_AGENT_ID") or "board-watch")
            for m in pending()]


def requeue_taken(agent_id):
    """A dead worker's TAKEN notes, back to the queue.

    `sweep()` rescues a note nobody READ; this is its twin for the note a
    worker `take`-d and then died holding. `taken/` is a resting place only
    because "an agent read it" normally becomes "an agent acted on it" — a
    worker reaped as FAILED reported nothing, so whatever it took died with it
    (2026-07-29: worker Vual took a handed-over item at 11:27, died on an API
    500, and the item sat in `taken/` with nothing flagging it). Back in
    `queue/` the next tick drains it into a fresh orchestrator, dispatched
    from its own words — which is why a handoff is written in full. The move
    is the same `os.replace` every other one is: exactly one directory at
    every instant, nothing lost, nothing doubled.

    Called by `boardwork.reap()` for every worker it files as FAILED and every
    one whose task it requeues on a transient death — deliberately NOT for a
    worker reaped as done, which is presumed to have handled what it took.
    (The residual gap that leaves — report, then take, then die — is stated in
    `AGENTS.md` rather than papered over.)
    """
    aid = clean_id(agent_id)
    if not aid or aid == "agent":
        return []
    return [_move(m, inbox_dir("queue"), state="requeued-from-dead-worker",
                  by=aid)
            for m in taken() if m.get("movedBy") == aid]


def sweep():
    """The guarantee, run at the top of every board-watch tick.

    A message addressed to an agent that has gone — or that has been sitting
    unread long enough that its agent is plainly not going to look — is moved to
    the queue, where the next run picks it up. Also drops registrations whose
    process is gone, so a killed run does not sit in his list claiming to work.

    Returns (escalated messages, dropped registrations).
    """
    live = {a["id"] for a in agents() if a["state"] == "running"}
    moved = []
    root = inbox_dir("to")
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if not os.path.isdir(d):
            continue
        for msg in _list(d):
            stale = (time.time() - float(msg.get("sent") or 0)) > ESCALATE_AFTER_S
            if name in live and not stale:
                continue
            moved.append(_move(msg, inbox_dir("queue"),
                               state="unread-its-agent-went" if name not in live
                               else "unread-too-long", by=name))
        try:
            os.rmdir(d)          # empty and its agent is gone: nothing to keep
        except OSError:
            pass
    # A message claimed by an in-place edit whose process died before it could
    # put it back. It is not lost — it is in `editing/` — but nobody is coming
    # for it there, so the queue gets it back with whatever text it holds.
    for msg in _list(inbox_dir("editing")):
        try:
            age = time.time() - os.path.getmtime(msg["file"])
        except OSError:
            continue
        if age > EDIT_RESCUE_AFTER_S:
            moved.append(_move(msg, inbox_dir("queue"), state="rescued-from-edit"))
    dropped = []
    for rec in _registrations():
        if not bm._alive(rec):
            unregister(rec["id"])
            dropped.append(rec)
    # ...and the observation sidecars of agents that no longer exist at all.
    # This is the DURABLE half of "a dead agent's card does not go on claiming
    # `coding`"; the immediate half is that liveness, not the sidecar, decides
    # the group (`boardwork.groups`). Left alone, these would accumulate one
    # file per agent that ever ran.
    import boardphase as bph
    alive_ids = {a["id"] for a in agents()}
    try:
        names = os.listdir(bph.sidecar_dir())
    except OSError:
        names = []
    for name in names:
        if name.endswith(".json") and name[:-5] not in alive_ids:
            bph.forget(name[:-5])
    return moved, dropped


# ------------------------------------------------------------- who is running
def _stash_agents():
    out = []
    for rec in bm._stashes():
        pid = rec.get("pid")
        if pid:
            state = "running" if bm._alive(rec) else "exited"
        else:
            # `boardctl start` with no --pid: a human or an orchestrating
            # session moved it. Nothing here can tell whether that session is
            # still thinking, and boardmove refuses to reclaim it for the same
            # reason. Say so rather than pick a side.
            state = "unowned"
        # A decision agent HAS a name — [his, 2026-08-01] two cards (an answered
        # decision each) sat in the triangle with no name on them while the
        # spirit board-watch had spawned worked on, and he came back to have
        # it fixed. There IS somebody on it: `boardmove.start()` has already
        # stashed a live process. So the "a name is a claim that somebody is on
        # it" rule is satisfied, unlike a queued task or an interactive session,
        # which stay nameless. Derived off the stable stash key exactly like a
        # record written before names existed, so the app, `boardctl` and the
        # agent all agree with nothing persisted, and the name never changes
        # between two polls.
        # Confirmed by construction: `boardmove.start()` stashes a pid whose
        # process the caller already has in hand — there is no summon to wait on.
        out.append({"id": clean_id(rec.get("key")), "kind": "decision",
                    "name": name_for(rec.get("key") or rec.get("id") or ""),
                    "confirmed": True,
                    "title": rec.get("title") or rec.get("key") or "a decision",
                    "where": rec.get("where") or "", "pid": pid or 0,
                    "session": rec.get("session") or "", "state": state,
                    # The tier board-watch stamped on the stash (`boardmove.start
                    # (model=,effort=)`), raw here and turned into the readable
                    # label in `agents()` — a decision card drew no tier because
                    # this pair was never carried across.
                    "model": rec.get("model") or "",
                    "effort": rec.get("effort") or "",
                    # ...and WHETHER IT FINISHED, on the same fact and the same
                    # terms as a registration's (above), so `_drawable()` has
                    # one rule to apply and not two. Computed only for a stash
                    # whose process is gone: for a live one it is both false by
                    # definition and a directory listing per poll.
                    "finished": (state == "exited"
                                 and _reported(clean_id(rec.get("key")))),
                    "born": born(rec, pid or 0)})
    return out


def agents(procs=None):
    """Everything that is running, one record each. Never raises: this is polled
    behind a window, and a /proc that will not answer is a dim line, not a
    traceback."""
    procs = procs if procs is not None else _procs()
    out = _stash_agents()
    for rec in _registrations():
        alive = bm._alive(rec)
        out.append({"id": clean_id(rec.get("id")), "kind": rec.get("kind") or "note",
                    "title": rec.get("title") or "an agent",
                    # Persisted at registration; derived only for a record
                    # written before names existed, so a worker that is running
                    # right now still gets one and keeps it.
                    "name": rec.get("name") or name_for(rec.get("id") or ""),
                    "where": rec.get("where") or "", "pid": rec.get("pid") or 0,
                    "session": rec.get("session") or "",
                    # For a deepseek subspirit only (else ""): the id and name
                    # of the spirit/orchestrator that delegated the chunk, so
                    # the UI can inset its card under that parent's row. Every
                    # other kind carries "" here.
                    "parent": rec.get("parent") or "",
                    "parentName": rec.get("parentName") or "",
                    # The tier it was spawned on (`register(model=,effort=)`),
                    # raw here and turned into the readable label below.
                    "model": rec.get("model") or "",
                    "effort": rec.get("effort") or "",
                    "state": "running" if alive else "exited",
                    # ...and, for one that has stopped, WHETHER IT FINISHED.
                    # `describe()` used to call every stopped worker abandoned;
                    # `boardwork.reported` is the fact that tells the two apart,
                    # and it is the same one `reap()` files them by.
                    "finished": (not alive) and _reported(rec.get("id") or ""),
                    # A SUMMON IS NOT A CARD until it is confirmed. Everything
                    # here still SEES the row — the cap, `reap()`, `sweep()`,
                    # the inbox — and only `boardwork.cards()`/`groups()` skip
                    # it, so a worker cannot be double-started or reaped early
                    # while it is starting up.
                    "confirmed": _confirmed(rec, alive),
                    "born": born(rec, rec.get("pid") or 0)})

    # Interactive sessions: the honest half. A `claude` process that IS one of
    # the agents above, or that descends from one, is already listed; anything
    # else is a session nobody here spawned and is listed as the process it is.
    #
    # BOTH halves are needed, and which one catches an agent depends on how it
    # was spawned. A decision/note agent's registered pid is board-watch's own
    # tick process and the `claude` is its CHILD — ancestry catches that. But a
    # worker gets its own systemd unit now, so the pid registered for it is the
    # `claude` process itself, which is in nobody's ancestor list but its own
    # — and it was being drawn a second time as an anonymous session until the
    # `pid in owners` half was added.
    owners = {a["pid"] for a in out if a["pid"]}
    for pid, (ppid, comm, cmd) in sorted(procs.items()):
        if not _is_claude(comm, cmd):
            continue
        if pid in owners or owners & set(_ancestors(pid, procs)):
            continue
        out.append({"id": "s%d" % pid, "kind": "session", "name": "",
                    "title": "an interactive Claude Code session",
                    "where": "", "pid": pid, "session": "", "state": "running",
                    # Nothing to confirm: this row IS the process, observed.
                    "confirmed": True,
                    "born": _pid_born(pid)})
    # WHAT IT SAYS, AND WHAT IT IS DOING. Imported here rather than at the top:
    # `boardphase` imports this module, and the pair would not load otherwise.
    import boardphase as bph
    # ...and `boardwork` for the tier label (`tier_label`/`orch_label`). Lazy for
    # the same reason `boardphase` is: `boardwork` imports THIS module at its top,
    # so a top-level import here would be circular; by the time `agents()` runs
    # both are loaded and this returns the cached module.
    import boardwork as bw
    # WHO SOLOMON IS WAITING ON, for his own card's `awaits` line — [his,
    # 2026-07-29] *"Solomon awaits <agent>..."*, and it NAMES the agent. Only
    # this function can see the other cards, so the name is resolved here and
    # handed to `boardphase.orch_says_line`; a running worker with a name is the
    # only thing he can honestly be said to be waiting on. Two or more and there
    # is no single one to name, none and there is nobody — both get a wording
    # that names nobody rather than an empty cell or the literal word "agent".
    # ...and it is one of the CARDS, so an unconfirmed summon does not put a
    # name in Solomon's mouth for a spirit that is not on the board yet.
    # THE TIER A WORKER RUNS ON, for a record written before the tier was stamped
    # at registration (`register(model=)`) — an agent already running when that
    # landed. The dispatch record in `taken/` is the authoritative per-task tier
    # (`boardwork.dispatch`), joined by agent id here so an in-flight spirit
    # shows its model at once rather than only once its successor is spawned.
    # Bounded: `taken/` holds only unreaped tasks, `reap()` moving the rest out.
    taken_tier = {}
    try:
        for r in _list(bw.work_dir("taken")):
            taid = clean_id(r.get("agent") or "")
            if taid and r.get("model"):
                taken_tier[taid] = (r.get("model"), r.get("effort") or "")
    except OSError:
        pass
    peers = [a.get("name") or "" for a in out
             if a.get("kind") != ORCHESTRATOR_KIND and a.get("state") == "running"
             and a.get("confirmed", True)]
    peers = [p for p in peers if p]
    awaits = peers[0] if len(peers) == 1 else ("his spirits" if peers else "")
    for a in out:
        a["unread"] = len(for_agent(a["id"]))
        obs = bph.observe(a["id"], session=a.get("session"))
        # The phase the card is FILED under is the observed one, never the
        # claim — `boardwork.groups()` reads exactly this key.
        a["phase"] = obs.get("phase") or "unreported"
        a["says"] = bph.says(obs)            # its own words, or "" for silence
        a["actually"] = bph.actually(obs)    # observed, and never the claim
        # The same two, as the SENTENCES the card draws — *"[agent name] is
        # [what the agent says its doing]"* and *"[agent name] is actually
        # [what it is actualy doing]"*. Built in `boardphase` because the
        # joining is a judgement about the real strings (a stopped agent goes
        # into the past tense, a claim with no phase word is quoted), and one
        # place to get that right beats one per surface.
        who = a.get("name") or ""
        orch = a["kind"] == ORCHESTRATOR_KIND
        # THE MODEL TIER RIDES THE NAME — [his, 2026-08-02] the card's leading
        # line reads *"[agent] ([model])"*: *"Balam (deepseek v4 flash)"*,
        # *"Bael (sonnet 5 medium)"*, and — same treatment, [his, 2026-08-02] —
        # *"Solomon (deepseek v4 flash)"*. The label is the same one the chooser
        # draws (`boardwork.tier_label`), off the `(flag, effort)` the spawner
        # stamped on the record (`register(model=)`) — or, for a worker already
        # running when that landed, the authoritative dispatch record in `taken/`
        # joined above. `a["model"]` is overwritten from the raw pair to this
        # readable label so the card (`AgentRow` name cell) binds it.
        #
        # SOLOMON reads the same way, off the same field: `_summon` resolves his
        # `(flag, effort)` once (env override, else `boardwork.orch_model()`) and
        # stamps it with `register(model=,effort=)` exactly like a worker's
        # spawner does, so a future run on a different model shows that model
        # with no code change here. A record with no model (a hand call, a test)
        # falls back to the currently-configured orchestrator pair rather than
        # showing nothing, since there is no `taken/`-style dispatch record for
        # an orchestrator to join against. He still speaks in his own VOICE
        # (*"Solomon wields the ring..."*) — only the tier joins the name.
        tier = bw.tier_label(a.get("model") or "", a.get("effort") or "")
        if not tier and orch:
            tier = bw.orch_label()
        if not tier and not orch:
            m, e = taken_tier.get(clean_id(a["id"]), ("", ""))
            tier = bw.tier_label(m, e)
        # A DECISION whose stash predates the tier stamp still shows one, off the
        # same decision resolver its spawn used — but not a hand-moved item
        # (`unowned`), which is nobody running a model and honestly has none.
        if not tier and a.get("kind") == "decision" and a.get("state") != "unowned":
            tier = bw.tier_label(*bw.role_tier("decision"))
        a["model"] = tier
        # The subject the sentence lines lead with. Only when BOTH a name and a
        # tier are known — Solomon, an unnamed session, or a pre-tiering record
        # keeps the bare name, and nothing invents a parenthesis around nothing.
        who_disp = "%s (%s)" % (who, tier) if (who and tier) else who
        # SOLOMON SPEAKS IN HIS OWN VOICE for the two words he actually uses —
        # `dispatching` -> *"Solomon is summoning..."*, `waiting` -> *"Solomon awaits
        # <agent>..."*, both his exact wordings. Everything else, his card
        # included, goes through the one shared `boardphase.predicate`, so the
        # verb form cannot drift between his card and a worker's.
        a["saysLine"] = bph.orch_says_line(obs, who_disp, awaits) if orch \
            else bph.says_line(obs, who_disp)
        # ...and its SECOND line: what it said it is doing, on its own line
        # rather than after a hyphen on the first one (his call — see
        # `boardphase.says_detail`).
        a["saysDetail"] = bph.says_detail(obs)
        # The observed line LEADS the card — is its own top line — when there
        # is no claim above it. [his, 2026-08-01] the name must stay on the top
        # line by name, so when it leads it opens with the name; under a claim
        # it is the bare description. `saysLine` is already resolved above, so
        # its emptiness is exactly "will this line be first".
        a["doingLine"] = bph.doing_line(obs, who_disp, a["state"] == "running",
                                        lead=a["saysLine"] == "")
        # SOLOMON ONLY: a live orchestrator with nothing observed yet gets his
        # own two-line startup pair instead of the bare `nothing yet` — [his,
        # 2026-07-29] *"Solomon wields the ring..."* while his transcript is
        # still a second away (`starting`), then *"Solomon etches the
        # circle..."* once it is there and nothing has happened in it yet
        # (`none`). Scoped to the orchestrator card so ordinary workers keep the
        # honest bare placeholder; the wordings and the ORDER are
        # `boardphase.orch_doing_line`, which carries the argument for both.
        orch_line = ""
        if orch and a["state"] == "running":
            orch_line = bph.orch_doing_line(obs.get("observed") or "",
                                            who_disp or ORCHESTRATOR_NAME)
            if orch_line:
                a["doingLine"] = orch_line
        # A CARD IS ALWAYS DRAWN, AND ONE WITH NOTHING TO SAY YET SAYS THAT.
        # [his, 2026-07-31] *"instead of hiding the card until it shows the name
        # on the top line etc, can we just put a card in there that reads
        # '[agent] awakens...' with an animated elipsies ... the card should just
        # show the rising text and nothing else until the agent card actually
        # starts producing stuff like before"* — the word is AWAKENS, not
        # arises: [his, 2026-08-01] *"have it just say like '[agent] awakens...'
        # with an animated elipsies"*.
        #
        # THE CONDITION IS THE OLD GATE'S, INVERTED — the same set of cards,
        # drawn instead of withheld. What it replaced (`speaks`) held a card back
        # until its top line was a real sentence [his, 2026-07-30], which was
        # right for the two seconds a healthy spawn takes and was also why a
        # wedged spirit was invisible for 45 minutes while burning a core
        # [top, 2026-07-31]: one that never reached its first API call is
        # registered, linked and has genuinely done nothing — precisely the
        # withheld state. A placeholder that is ALWAYS drawn has no such hole,
        # and there is now no state in which a running agent has no card.
        #
        # It is the observation STATE, never the words: matching the sentences
        # would break the moment either is reworded. Solomon is excluded because
        # `orch_line` already gives him a real line in exactly these states.
        a["arising"] = a["state"] == "running" \
            and not a["saysLine"] and not orch_line \
            and (obs.get("observed") or "") in ("none", "starting")
        if a["arising"]:
            # ...AND NOTHING ELSE ON THE CARD — his words, and not decoration.
            # The observation under it could only say `nothing yet`, which is
            # the placeholder this line exists to replace, so drawing both says
            # the same absence twice. `AgentRow` drops the title row and the
            # trailing metadata off this same flag.
            a["saysLine"] = bph.arises_line(who_disp)
            a["saysDetail"] = ""
            a["doingLine"] = ""
        # `ok` / `quiet` / `none` / `starting` / `unlinked` — which of the honest
        # outcomes the observation is, so the card can label the line correctly
        # (`doing` while it runs, `last` once it has stopped) without
        # re-deriving it from the sentence.
        a["observed"] = obs.get("observed") or "unlinked"
        # HOW FULL IT IS: `62k/200k`, measured out of the transcript's own
        # `usage` stamps, and "" when nothing was measured. Formatted in
        # `boardphase` beside the two sentences, for the same reason they are.
        a["contextLine"] = bph.context_line(obs)
        # HOW LONG IT HAS BEEN WORKING, beside that tally — his, 2026-07-29,
        # replacing the absolute spawn stamp he asked for that morning. The one
        # elapsed time this app draws; `boardphase.worked_line` carries the
        # whole argument. Recomputed here on every poll, which is what keeps it
        # current on screen.
        a["workedLine"] = bph.worked_line(a.get("born"), a["state"] == "running")
    # A STABLE order, so a row does not move under his cursor between two polls
    # — and it is not an urgency ordering (there is none in this app): the ones
    # that are working come first, the ones that have stopped last, and inside a
    # group it is the id, which does not change.
    rank = {"running": 0, "unowned": 1, "exited": 2}
    kind = {"decision": 0, "note": 1, "session": 2}
    out.sort(key=lambda a: (rank.get(a["state"], 3), kind.get(a["kind"], 3), a["id"]))
    return out


# ---------------------------------------------------------------- the watcher
def watch_kill_switch():
    """The watcher's own kill switch file. Resolved the way `board-watch.py`
    resolves it and not the way THIS module resolves its own state — that one
    honours `$XDG_STATE_HOME` and the watcher does not, so copying `_root()`
    here would make the app report on a file the watcher never reads. Makes no
    directory: its absence is the answer."""
    base = os.environ.get("BOARD_WATCH_STATE",
                          os.path.join(os.path.expanduser("~"),
                                       ".local", "state", "board-watch"))
    return os.path.join(base, "off")


def watcher_state(raw=None):
    """What `systemctl --user show` said about the watcher, as one honest
    sentence plus an `armed` verdict. `raw` is the command's output; the caller
    runs it (the app does it off the GUI thread), because this module forks
    nothing.

    Two units, in this order: `board-watch.service` (is a tick running, did the
    last one fail) and `board-watch.path` (is anything going to START one).
    `systemctl show` prints one property block per unit, separated by a blank
    line. Asking only the service was not enough to say "armed": its resting
    ActiveState is `inactive`, which is indistinguishable from a path unit that
    is stopped, so the sentence used to claim armed for a watcher that could
    never fire.

    **`armed` is a THREE-valued answer** — True, False, or None for "could not
    be asked". §10: an unknown is not a no, and the caller must not draw a claim
    about his machine out of a systemctl we never got to run.

    The kill switch (`~/.local/state/board-watch/off`) is a file and this module
    forks nothing, so it is the one thing checked here directly; it is read on
    the caller's ten-second unit poll, never per repaint.
    """
    blocks, d = [], {}
    for line in (raw or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
        elif not line.strip() and d:
            blocks.append(d)
            d = {}
    if d:
        blocks.append(d)
    svc = blocks[0] if blocks else {}
    pathu = blocks[1] if len(blocks) > 1 else {}

    if os.path.exists(watch_kill_switch()):
        return {"state": "off", "armed": False,
                "text": "board-watch is switched off - its kill switch file exists"}
    active = svc.get("ActiveState")
    if not active:
        return {"state": "", "armed": None, "text": "board-watch could not be asked"}
    # NOT INSTALLED IS ITS OWN ANSWER, and it is the one that cost him a whole
    # order. `home/` is shared by both hosts but only reaches one of them when
    # that host's own switch runs, so a machine that has not been switched since
    # the watcher was written has no `board-watch.service` at all — and
    # `systemctl show` answers for a unit that does not exist with a perfectly
    # ordinary `ActiveState=inactive`, which used to be reported as merely "not
    # armed - its path unit is inactive". Same words for "it is stopped" and for
    # "it was never deployed here", and only the second one tells him what to
    # run. So ask for `LoadState` too (main.py does) and say which it is.
    if "not-found" in (svc.get("LoadState", ""), pathu.get("LoadState", "")):
        return {"state": "not-installed", "armed": False,
                "text": "board-watch is not installed on %s - it needs that "
                        "host's own rebuild/home-manager switch" % os.uname().nodename}
    if active == "failed":
        return {"state": active, "armed": False,
                "text": "board-watch failed its last run - see ~/.cache/board-watch.log"}
    if active in ("activating", "active", "reloading"):
        return {"state": active, "armed": True,
                "text": "board-watch is running a tick now"}
    parmed = pathu.get("ActiveState")
    if parmed and parmed != "active":
        return {"state": active, "armed": False,
                "text": "board-watch is not armed - its path unit is " + parmed}
    return {"state": active, "armed": True,
            "text": "board-watch is armed - it picks up the box and your answers"}


# ------------------------------------------------------ what the row says
def describe(a):
    """The one line under an agent's two statements. Words, not colour (§3.5) —
    this is what tells a failed agent from a running one without touching the
    warn/crit ramp, which on this desktop means a machine fault and not a dead
    subprocess.

    It no longer carries what the agent is doing: that is now TWO lines, `says`
    and `actually`, which `boardphase.py` owns and the card draws separately.
    What is left here is the process-level fact — alive, gone, or not ours —
    plus the one thing about the inbox he needs to see.
    """
    if a["state"] == "queued":
        return "not started yet - a spirit starts when a slot frees"
    # The one row on this list that is not a process: Solomon standing by, and
    # he gets NO detail line. [his, 2026-07-29] his resting card is two lines —
    # `Solomon awaits` and `summons a spirit to do your bidding.` — and the
    # third, which said what you type at the top of the window goes to him, is
    # gone. The box it described is directly above the card and says so itself.
    if a["state"] == "idle":
        return ""
    if a["state"] == "running":
        if a["kind"] == "session":
            return "running - board sees the process, not what it is doing"
        if a["unread"]:
            return "running - your note is in its inbox, unread"
        return "running - it reads its inbox between steps"
    if a["state"] == "exited":
        # IT REPORTED, so it is finished and not abandoned — the claim that
        # nothing was committed on its behalf is false about this one, and it
        # was being made about every stopped worker until 2026-07-30.
        if a.get("finished"):
            return "finished - it recorded its result on the board"
        if a["kind"] == "decision":
            return "exited without finishing - the decision comes back on the next check"
        return "exited without finishing - nothing was committed on its behalf"
    return "started by hand - board cannot tell whether it is still running"
