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
#: names of demons in the lesser key of solomon"* — so the pool is the
#: Lemegeton's: the Ars Goetia's 72, plus the short names the Theurgia-Goetia
#: and the Ars Paulina supply.
#:
#: THE NAME IS PRESENTATION AND NOTHING IS KEYED ON IT. The id (`w1a2b3c`) is
#: still the key: the systemd unit, `~/.cache/board-work/<id>.log`, the
#: observation sidecar, the inbox directory and every record on disk are named
#: by it, and a message is addressed by it. Renaming any of those would orphan a
#: worker that is running right now.
#:
#: TWO RULES ON WHAT MAY GO IN, and both are about the row it is drawn in.
#: **Six characters at most**: the card draws the name in the same label column
#: as `says` and `doing`, 7 font cells wide, and `AgentRow` starts the title at
#: `7 * cellW` with no elide — a seventh character runs under the title. That is
#: what rules out `Focalor`, `Gremory`, `Bifrons` and the rest of the long
#: spellings. **ASCII only**: §2.3, a glyph the font lacks clips the whole row,
#: so `Belial` and never a diacritical spelling of it. Distinct
#: case-insensitively, because `boardctl inbox send --to` matches on the name.
NAMES = ["Agares", "Aim", "Amon", "Amy", "Anael", "Andras", "Bael", "Balam",
         "Bariel", "Bathin", "Beleth", "Belial", "Berith", "Bidiel", "Botis",
         "Buer", "Bune", "Caim", "Eligos", "Foras", "Furcas", "Furfur", "Gaap",
         "Gediel", "Glasya", "Gusion", "Haures", "Ipos", "Leraje", "Marax",
         "Marbas", "Murmur", "Orias", "Oriel", "Orobas", "Ose", "Paimon",
         "Phenex", "Purson", "Raum", "Ronove", "Sallos", "Samael", "Seere",
         "Shax", "Sitri", "Stolas", "Symiel", "Usiel", "Valac", "Vapula",
         "Vepar", "Vine", "Vual", "Zagan", "Zepar"]


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
             name=""):
    """`session` is the `--session-id` the spawner chose, and it is what makes
    the card able to say what the agent is really doing: `boardphase.py` finds
    `~/.claude/projects/*/<session>.jsonl` by it. An agent registered without
    one is simply not observable, and its card says exactly that.

    `name` is the human name he sees. It is PERSISTED here rather than derived
    on every read, so it cannot change under him when another agent takes the
    name this one would have been moved off; the spawner picks it beside the id
    (`boardwork._spawn_worker`), and a caller that does not is given one here.
    """
    rec = {"id": clean_id(agent_id), "title": title, "pid": pid,
           "name": name or pick_name(agent_id),
           "pidStart": bm._proc_start(pid) if pid else None, "kind": kind,
           "where": where, "session": session or "",
           "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    _write_json(os.path.join(agents_dir(), rec["id"] + ".json"), rec)
    return rec


def name_of(agent_id):
    """The name in one agent's record, or `""` for anything that has none — a
    decision he answered, an interactive session, a task with no worker yet.
    Reads the record rather than deriving, so what the UI says back to him is
    what the card beside it is drawing."""
    rec = _read_json(os.path.join(agents_dir(), clean_id(agent_id) + ".json"))
    return (rec or {}).get("name") or ""


def unregister(agent_id):
    try:
        os.unlink(os.path.join(agents_dir(), clean_id(agent_id) + ".json"))
        return True
    except OSError:
        return False


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
    return out


def _move(msg, dest_dir):
    """The only way a message ever changes state. A rename inside one
    filesystem, so it is in exactly one directory at every instant — that is the
    whole "nothing he typed is lost" argument."""
    dest = os.path.join(dest_dir, os.path.basename(msg["file"]))
    os.replace(msg["file"], dest)
    msg = dict(msg)
    msg["file"] = dest
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
           "text": text, "host": os.uname().nodename}
    d = inbox_dir("to", tid) if delivered else inbox_dir("queue")
    path = os.path.join(d, _msg_name())
    _write_json(path, msg)
    msg["file"] = path
    msg["state"] = "delivered" if delivered else "queued"
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
    return [_move(m, inbox_dir("taken")) for m in msgs]


def drain():
    """Take the whole queue, for the run that is about to work it.

    Called by board-watch immediately BEFORE it spawns, never after: a message
    still in the queue when the process dies would be worked twice, and a
    message deleted after a crash would be worked never. Moving first and
    reporting the failure onto the board is the trade that loses nothing.
    """
    return [_move(m, inbox_dir("taken")) for m in pending()]


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
            moved.append(_move(msg, inbox_dir("queue")))
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
            moved.append(_move(msg, inbox_dir("queue")))
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
        # No human name: a decision agent is not a worker out of the box, its
        # card is headed by the decision he answered, and giving that a first
        # name would be this app inventing a person for one of HIS items.
        out.append({"id": clean_id(rec.get("key")), "kind": "decision", "name": "",
                    "title": rec.get("title") or rec.get("key") or "a decision",
                    "where": rec.get("where") or "", "pid": pid or 0,
                    "session": rec.get("session") or "", "state": state,
                    "born": born(rec, pid or 0)})
    return out


def agents(procs=None):
    """Everything that is running, one record each. Never raises: this is polled
    behind a window, and a /proc that will not answer is a dim line, not a
    traceback."""
    procs = procs if procs is not None else _procs()
    out = _stash_agents()
    for rec in _registrations():
        out.append({"id": clean_id(rec.get("id")), "kind": rec.get("kind") or "note",
                    "title": rec.get("title") or "an agent",
                    # Persisted at registration; derived only for a record
                    # written before names existed, so a worker that is running
                    # right now still gets one and keeps it.
                    "name": rec.get("name") or name_for(rec.get("id") or ""),
                    "where": rec.get("where") or "", "pid": rec.get("pid") or 0,
                    "session": rec.get("session") or "",
                    "state": "running" if bm._alive(rec) else "exited",
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
                    "born": _pid_born(pid)})
    # WHAT IT SAYS, AND WHAT IT IS DOING. Imported here rather than at the top:
    # `boardphase` imports this module, and the pair would not load otherwise.
    import boardphase as bph
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
        a["saysLine"] = bph.says_line(obs, who)
        a["doingLine"] = bph.doing_line(obs, who, a["state"] == "running")
        # `ok` / `quiet` / `none` / `unlinked` — which of the four honest
        # outcomes the observation is, so the card can label the line correctly
        # (`doing` while it runs, `last` once it has stopped) without
        # re-deriving it from the sentence.
        a["observed"] = obs.get("observed") or "unlinked"
        # HOW FULL IT IS: `62k/200k`, measured out of the transcript's own
        # `usage` stamps, and "" when nothing was measured. Formatted in
        # `boardphase` beside the two sentences, for the same reason they are.
        a["contextLine"] = bph.context_line(obs)
    # A STABLE order, so a row does not move under his cursor between two polls
    # — and it is not an urgency ordering (there is none in this app): the ones
    # that are working come first, the ones that have stopped last, and inside a
    # group it is the id, which does not change.
    rank = {"running": 0, "unowned": 1, "exited": 2}
    kind = {"decision": 0, "note": 1, "session": 2}
    out.sort(key=lambda a: (rank.get(a["state"], 3), kind.get(a["kind"], 3), a["id"]))
    return out


# ---------------------------------------------------------------- the watcher
def watcher_state(raw=None):
    """What `systemctl --user show board-watch.service` said, as one honest
    sentence. `raw` is the command's output; the caller runs it (the app does it
    off the GUI thread), because this module forks nothing."""
    d = {}
    for line in (raw or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    active = d.get("ActiveState")
    if not active:
        return {"state": "", "text": "board-watch could not be asked"}
    if active == "failed":
        return {"state": active,
                "text": "board-watch failed its last run - see ~/.cache/board-watch.log"}
    if active in ("activating", "active", "reloading"):
        return {"state": active, "text": "board-watch is running a tick now"}
    return {"state": active,
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
        return "not started yet - a worker starts when a slot frees"
    if a["state"] == "running":
        if a["kind"] == "session":
            return "running - board sees the process, not what it is doing"
        if a["unread"]:
            return "running - your note is in its inbox, unread"
        return "running - it reads its inbox between steps"
    if a["state"] == "exited":
        if a["kind"] == "decision":
            return "exited without finishing - the decision comes back on the next check"
        return "exited without finishing - nothing was committed on its behalf"
    return "started by hand - board cannot tell whether it is still running"
