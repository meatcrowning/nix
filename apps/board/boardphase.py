"""What an agent SAYS it is doing, and what it is ACTUALLY doing. Both.

A card on his board says which phase an agent is in — planning, researching,
coding, testing, finishing touches — and it carries two lines, on purpose. He
asked for it in one sentence: *"i want both. i want what its saying its doing and
what its actually doing"*.

  * **The claim.** The agent's own words, set by `boardctl.py phase`. It carries
    the OBJECT and the intent — *"wiring the FOCUS signal through vtbclient"* —
    which no amount of watching tool calls can tell you.
  * **The observation.** Derived from the tool calls in the agent's live
    transcript. It carries the VERB — *"editing vtbclient.py"* — and it cannot
    be faked, forgotten or left stale.

**They are never collapsed into one field and neither ever overwrites the
other.** Grouping into phase sections uses the OBSERVED phase alone; the claim
is drawn beside it. So an agent claiming `testing` whose every recent call is an
`Edit` appears under *coding*, saying *testing* — and that divergence is a
FEATURE, the exact thing he wants to be able to see. Nothing here hides it,
reconciles it away or warns about it: no warn/crit colour, no alarm, no badge.
Two true statements, drawn plainly, and he reads them.

**Each side can be missing, and says so on its own terms.** No claim yet is
silence, not a guess assembled from tool calls. No transcript, or nothing in it
recently, is stated plainly rather than quietly falling back to the claim and
passing it off as observation. And staleness differs between them: a claim just
gets old, silently — it is only ever text somebody typed — while an observation
going quiet MEANS something, namely that the agent has stopped doing anything.

WHERE THE OBSERVATION COMES FROM — measured on `top`, 2026-07-29, not assumed
---------------------------------------------------------------------------
Claude Code writes a live JSONL transcript per session at
`~/.claude/projects/<slug>/<session-uuid>.jsonl`. Three things were checked
before any of this was built:

  1. **A headless `claude -p` run gets one.** Verified by running one with a
     chosen id and finding its file, containing the `tool_use` entry for the one
     Bash command it was asked to make.
  2. **It is written LIVE, not at exit.** This module's own session's transcript
     grew by 1584 bytes between two `stat`s a few minutes apart, mid-run.
  3. **The linkage is CHOSEN, not guessed.** `claude --session-id <uuid>` takes
     the id, so a spawner picks the uuid, passes it, and knows the filename. The
     file is then found by globbing `projects/*/<uuid>.jsonl` — the *uuid* is the
     key, so the project-slug rule (path with every non-alphanumeric run turned
     into `-`) never has to be reimplemented here and cannot drift.

**Why the transcript and not `--output-format stream-json`.** stream-json is
real and would work, but a worker is spawned DETACHED on purpose (see
`boardwork._spawn_worker`) — there is no parent left alive to read its stdout, so
the stream would have to be redirected to a file and tailed, which is this same
problem in a format we would then own. The transcript is already on disk, already
structured, already written by the platform, and it works for agents this system
did not spawn. One spawn flag (`--session-id`) buys all of it.

THE CLASSIFIER, and it is meant to be TUNED
-------------------------------------------
`TOOL_PHASE` and `TEST_CMD` below are the whole thing; change them there. Each
tool call in a recent window (`WINDOW` calls) is classified, and then:

    walk the window NEWEST FIRST; the first call that classifies as
    coding / testing / finishing wins
    else, if anything in the window is planning (TodoWrite, Task, Agent)   -> planning
    else, if anything in the window is researching (Read/Grep/Glob/Web*)   -> researching
    else                                                                  -> unreported

Reading is the background noise of every phase — an agent greps constantly while
it edits — so `researching` is what an agent is doing when reading is *all* it is
doing, exactly as a person would judge it. `finishing` is the commit, the push
and the `AGENTS.md` edit. A window rather than the whole history is what makes
the card MOVE as the work moves.

A STALLED AGENT IS VISIBLE, WITHOUT A CLOCK ON SCREEN
-----------------------------------------------------
No new tool call for `QUIET_AFTER_S` sets `quiet`, and the card says *"nothing
recently"* — words, no number. That is deliberate: the app's founding
requirement is that nothing on it counts, ages or ramps (`AGENTS.md`), so the
threshold is machine business exactly as `boardagents.ESCALATE_AFTER_S` is. The
point is that a silent agent reads as silent instead of as a card frozen on a
confident claim.

**This does not replace `boardmove._alive`.** They answer different questions:
`_alive` (pid + kernel start time) is whether the process EXISTS, and it is
still the one liveness rule in this tree; this is what that process has been
doing. A dead agent is `stopped` whatever its transcript says, and a live agent
with a quiet transcript is running but idle. Both facts are drawn, and neither is
inferred from the other.

COST. Transcripts reach megabytes (this session's is 1.8 MB), so nothing here
ever reads one whole. Each agent's record keeps a byte OFFSET; a poll seeks
there, reads to EOF, and advances the offset only past the last complete line.
A poll on an idle agent is one `stat`.
"""
import json
import os
import time

import boardagents as ba
import boardparse as bp

#: How many recent tool calls decide the phase. Small enough that the card moves
#: with the work, large enough that one stray Read does not rename the phase.
WINDOW = 12

#: No tool call in this long and the card says so, in words. Machine business:
#: it never reaches the screen as a number (see the docstring).
QUIET_AFTER_S = int(os.environ.get("BOARD_QUIET_AFTER", "180"))

def projects_dir():
    """Where Claude Code keeps transcripts. `BOARD_TRANSCRIPTS` redirects it, so
    a harness can hand this module a synthetic one instead of writing into his
    real `~/.claude` — which syncs to book (`home/srvs/claude-state.nix`)."""
    return os.environ.get("BOARD_TRANSCRIPTS") or \
        os.path.join(os.path.expanduser("~"), ".claude", "projects")

# ------------------------------------------------------------- the classifier
# Tune HERE. Everything above is machinery; this is the judgement.
TOOL_PHASE = {
    "Edit": "coding", "Write": "coding", "NotebookEdit": "coding",
    "Read": "researching", "Grep": "researching", "Glob": "researching",
    "WebFetch": "researching", "WebSearch": "researching",
    "TodoWrite": "planning", "Task": "planning", "Agent": "planning",
}

#: A `Bash` call is the ambiguous one — it is how an agent tests, commits and
#: reads a file alike — so it is classified by what it RUNS. Ordered: the first
#: match wins, and `finishing` is checked before `testing` so a run that tests
#: and then commits in one command reads as the later phase.
BASH_PHASE = [
    ("finishing", ("git commit", "git push", "boardctl.py note", "boardctl.py land",
                   "gh pr", "AGENTS.md")),
    ("testing", ("-test.py", "test.py", "pytest", "qmllint", "preflight.sh",
                 "nixos-rebuild build", "harness", "unittest", "seed-drift",
                 "-test.sh", "nix flake check")),
]


def classify(name, inp):
    """One tool call -> a phase, or None. `inp` is the call's own input dict."""
    if name == "Bash":
        cmd = " ".join(str((inp or {}).get("command", "")).split())
        for phase, needles in BASH_PHASE:
            if any(n in cmd for n in needles):
                return phase
        return None            # an ordinary shell command says nothing about phase
    return TOOL_PHASE.get(name)


def phase_of_window(recent):
    """The window (oldest first) -> the phase drawn on the card."""
    for call in reversed(recent):
        if call["phase"] in ("coding", "testing", "finishing"):
            return call["phase"]
    if any(c["phase"] == "planning" for c in recent):
        return "planning"
    if any(c["phase"] == "researching" for c in recent):
        return "researching"
    return "unreported"


# -------------------------------------------------------- what the card says
#: The activity line: a verb and the one thing the call was about. Not a log
#: line — he is reading a sentence about an agent, not a trace.
def describe_call(name, inp):
    inp = inp or {}

    def base(k):
        v = str(inp.get(k) or "")
        return os.path.basename(v.rstrip("/")) or v

    if name == "Bash":
        d = " ".join(str(inp.get("description") or "").split())
        if d:
            return d[0].lower() + d[1:] if d[:1].isupper() else d
        cmd = " ".join(str(inp.get("command") or "").split())
        return ("running " + cmd[:48]) if cmd else "running a command"
    if name in ("Read", "NotebookEdit"):
        return "reading " + base("file_path")
    if name == "Edit":
        return "editing " + base("file_path")
    if name == "Write":
        return "writing " + base("file_path")
    if name == "Grep":
        return "searching for " + str(inp.get("pattern") or "")[:40]
    if name == "Glob":
        return "looking for " + str(inp.get("pattern") or "")[:40]
    if name in ("WebFetch",):
        return "fetching " + str(inp.get("url") or "")[:48]
    if name == "WebSearch":
        return "searching the web for " + str(inp.get("query") or "")[:40]
    if name == "TodoWrite":
        return "working out the steps"
    if name in ("Task", "Agent"):
        return "handing part of it to another agent"
    return "using " + name


# ------------------------------------------------------------ the transcript
def transcript(session):
    """The file for one session uuid, or None.

    Globbed on the UUID, never assembled from the cwd: the project-slug rule is
    the platform's and would be one more thing to keep in step. One `listdir`
    per project directory, and the answer is cached in the agent's record.
    """
    if not session:
        return None
    name = str(session) + ".jsonl"
    root = projects_dir()
    try:
        dirs = os.listdir(root)
    except OSError:
        return None
    for d in dirs:
        p = os.path.join(root, d, name)
        if os.path.isfile(p):
            return p
    return None


def _tool_calls(path, offset):
    """(new calls, new offset). Reads only the bytes since `offset`.

    Advances past complete lines ONLY: a transcript is appended to while this
    runs, so the final fragment is left for the next poll rather than parsed as
    a truncated object.
    """
    calls = []
    try:
        size = os.path.getsize(path)
    except OSError:
        return calls, offset
    if size < offset:
        offset = 0                # rotated or replaced: start again
    if size == offset:
        return calls, offset
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            buf = f.read()
    except OSError:
        return calls, offset
    cut = buf.rfind(b"\n")
    if cut < 0:
        return calls, offset      # not one complete line yet
    for raw in buf[:cut].split(b"\n"):
        if not raw.strip():
            continue
        try:
            d = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        if d.get("type") != "assistant":
            continue
        msg = d.get("message") or {}
        for c in msg.get("content") or []:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                name = str(c.get("name") or "")
                calls.append({"name": name, "phase": classify(name, c.get("input")),
                              "doing": describe_call(name, c.get("input")),
                              "at": d.get("timestamp") or ""})
    return calls, offset + cut + 1


# --------------------------------------------------------------- the sidecar
def _root():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "board")


def sidecar_dir():
    d = os.path.join(_root(), "phase")
    os.makedirs(d, exist_ok=True)
    return d


def sidecar(agent_id):
    return os.path.join(sidecar_dir(), ba.clean_id(agent_id) + ".json")


def read_sidecar(agent_id):
    try:
        with open(sidecar(agent_id)) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


CLAIMABLE = ["planning", "researching", "coding", "testing", "finishing"]


def claim(agent_id, phase="", doing=""):
    """The agent's own account of itself. Recorded, drawn, and never believed.

    It is stored under its own keys and is **not** what `groups()` sections the
    card by — that is the observed phase, always. A claim that disagrees with
    the observation is left standing exactly as it was written: the divergence
    is the information.
    """
    aid = ba.clean_id(agent_id or ba.self_id() or "")
    if not aid:
        return None
    phase = (phase or "").strip().lower()
    with bp.locked(sidecar(aid), timeout=5.0):
        rec = read_sidecar(aid)
        rec["id"] = aid
        if phase in CLAIMABLE:
            rec["claimPhase"] = phase
        # A claim that names no words keeps the last ones rather than blanking
        # the line: he is reading a sentence, and an agent moving from one
        # phase to the next should not wipe what it said it was on.
        if " ".join((doing or "").split()):
            rec["claimDoing"] = " ".join(doing.split())
        rec["claimAt"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        ba._write_json(sidecar(aid), rec)
    return rec


def says(rec):
    """The claim, as one line, or "" if the agent has not said anything.

    Silence is silence. Nothing here manufactures a claim out of the
    observation — that would make the two lines agree by construction and throw
    away the only thing having two of them buys.
    """
    rec = rec or {}
    phase, doing = rec.get("claimPhase") or "", rec.get("claimDoing") or ""
    if phase and doing:
        return "%s - %s" % (phase, doing)
    return phase or doing or ""


def actually(rec):
    """The observation, as one line. Always says something, and never a claim.

    Four honest outcomes, and the two failure ones are stated rather than
    papered over with the claim (§10): a card that showed his agent's own words
    under the heading "what it is actually doing" would be the dishonest control
    this desktop's design language exists to forbid.
    """
    rec = rec or {}
    state = rec.get("observed")
    if state == "ok":
        return rec.get("doing") or "working"
    if state == "quiet":
        # Words, never a duration. The threshold is machine business; a number
        # here would be an elapsed time the moment he read it.
        last = rec.get("doing")
        return ("nothing recently - last seen " + last) if last else "nothing recently"
    if state == "none":
        return "nothing yet"
    # Unlinked: no session id was ever recorded, so there is no transcript to
    # find. One sentence that is both halves of the truth — we cannot see the
    # work, and we CAN see the process — rather than two lines saying it twice.
    return "cannot see what it is doing - only that the process is there"


# ------------------------------------------------- the same two, as SENTENCES
# His words: *"in the agents tab it should read: [agent name] is [what the agent
# says its doing] and then the line below should be the [agent name] is actually
# [what it is actualy doing]"*. So the card no longer draws the bare words
# `says` and `doing` in a label column beside the two texts — it draws two
# plain sentences, and these build them.
#
# **The joining is chosen for the REAL strings, not assumed.** `says()` is
# `"<phase> - <words>"` and every phase word is a gerund (`planning`,
# `researching`, `coding`, `testing`, `finishing`), so it follows "is" as
# English. The words on their own may be a noun phrase — `boardctl.py phase`
# takes the phase as OPTIONAL and its `--doing` is *"one short line"*, so
# *"the vtbclient parser"* is a legal claim — and *"Marbas is the vtbclient
# parser"* is not a sentence. That case gets `says:` instead of `is`.
#
# The observation is joined the same way and for the same reason: only the `ok`
# state is a verb phrase. `nothing recently`, `nothing yet` and the unlinked
# sentence each need their own shape, and a STOPPED agent needs the past tense
# — *"Marbas is actually ..."* is false about a process that is gone.
def _subject(who):
    """`it` for anything with no name — a decision he answered, an interactive
    session. Same fallback the card's box already uses; nothing invents one."""
    return who or "it"


def says_line(rec, who=""):
    """The claim as a sentence, or "" when the agent has said nothing.

    Silence stays silence: this never falls back to the observation, for the
    reason `says()` gives.
    """
    rec = rec or {}
    phase, doing = rec.get("claimPhase") or "", rec.get("claimDoing") or ""
    subj = _subject(who)
    if phase and doing:
        return "%s is %s - %s" % (subj, phase, doing)
    if phase:
        return "%s is %s" % (subj, phase)
    if doing:
        # No phase word to lean on, so the words are quoted rather than forced
        # into a sentence they may not fit.
        return "%s says: %s" % (subj, doing)
    return ""


def doing_line(rec, who="", running=True):
    """The observation as a sentence. Never the claim, and never present tense
    about a process that has stopped.

    "" only when there is nothing honest to say about a stopped agent — it was
    never seen doing anything, and inventing a past for it is worse than the
    card's own `exited without finishing` line saying all there is.
    """
    rec = rec or {}
    subj = _subject(who)
    state = rec.get("observed")
    last = rec.get("doing") or ""
    if not running:
        # PAST TENSE, and only about something actually seen. This is the
        # `doing`/`last` split the label column used to carry.
        return ("%s was last seen %s" % (subj, last)) if last and \
            state in ("ok", "quiet") else ""
    if state == "ok":
        return "%s is actually %s" % (subj, last or "working")
    if state == "quiet":
        # Words, never a duration — the threshold is machine business.
        return ("%s has actually done nothing recently - last seen %s"
                % (subj, last)) if last else \
            "%s has actually done nothing recently" % subj
    if state == "none":
        return "%s has not done anything yet" % subj
    return "board cannot see what %s is doing - only that the process is there" \
        % subj


def forget(agent_id):
    try:
        os.unlink(sidecar(agent_id))
        return True
    except OSError:
        return False


def observe(agent_id, session=None):
    """Read whatever is new in this agent's transcript and update its record.

    Returns the record: `phase`, `doing`, `quiet`, `label`. Cheap on an idle
    agent (one `stat`) and never reads a transcript whole.

    Two processes can call this at once — his window polls every 2.5s while
    board-watch runs a tick — so it takes the advisory lock `boardparse` already
    provides. If a race still slips through, the cost is a few skipped tool
    calls and therefore a slightly stale phase, which the next poll corrects:
    this is a recent-window heuristic, not a ledger.
    """
    aid = ba.clean_id(agent_id)
    with bp.locked(sidecar(aid), timeout=2.0):
        rec = read_sidecar(aid)
        rec["id"] = aid
        if session:
            rec["session"] = str(session)
        path = rec.get("path")
        if not path or not os.path.isfile(path):
            path = transcript(rec.get("session"))
            rec["path"] = path
        if not path:
            # Nothing to observe: no session id was ever recorded for this
            # agent (an interactive session this system did not spawn), or its
            # transcript is not where the platform puts one. SAY THAT. Falling
            # back to the claim here is the one thing this module must not do.
            rec["observed"] = "unlinked"
            rec["phase"] = "unreported"
            rec.setdefault("recent", [])
            ba._write_json(sidecar(aid), rec)
            return rec
        calls, offset = _tool_calls(path, int(rec.get("offset") or 0))
        rec["offset"] = offset
        if calls:
            rec["recent"] = (list(rec.get("recent") or []) + calls)[-WINDOW:]
            rec["seen"] = time.time()
        recent = list(rec.get("recent") or [])
        rec["phase"] = phase_of_window(recent)
        rec["doing"] = recent[-1]["doing"] if recent else ""
        rec["lastTool"] = recent[-1]["name"] if recent else ""
        if not recent:
            rec["observed"] = "none"        # linked, but it has not acted yet
        elif time.time() - float(rec.get("seen") or 0) > QUIET_AFTER_S:
            rec["observed"] = "quiet"       # it has stopped doing anything
        else:
            rec["observed"] = "ok"
        ba._write_json(sidecar(aid), rec)
        return rec
