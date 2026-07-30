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
import re
import time

import boardagents as ba
import boardparse as bp

#: How many recent tool calls decide the phase. Small enough that the card moves
#: with the work, large enough that one stray Read does not rename the phase.
WINDOW = 12

#: No tool call in this long and the card says so, in words. Machine business:
#: it never reaches the screen as a number (see the docstring).
QUIET_AFTER_S = int(os.environ.get("BOARD_QUIET_AFTER", "180"))

#: A session id is recorded but its transcript file has not appeared yet. For
#: this long that is STARTING UP, not "cannot see it" — the CLI writes the file
#: on its first turn, a second or two after the process exists.
#:
#: [his, 2026-07-29] *"when solomon first takes a request, his section very
#: briefly shows 'cannot see what solomon is doing' and then changes to 'Solomon
#: is getting ready' - it shouldnt show that breif initial 'dont know' text"*.
#: The two cases were collapsing into `unlinked`: no session id EVER recorded
#: (an interactive session this system did not spawn — the true unknown) and a
#: spawn of ours whose transcript is seconds away. Only the first is a thing the
#: board cannot see; the second it is simply early for.
#:
#: It is a GRACE, not a synonym: past it, a spawn whose transcript never
#: appeared is `unlinked` again and says so, because that is a real failure and
#: hiding it behind "nothing yet" forever is the §10 lie this app exists not to
#: tell.
START_GRACE_S = int(os.environ.get("BOARD_START_GRACE", "120"))

#: The context window an agent is assumed to have, in tokens, when nothing in
#: its transcript says otherwise. 200k is Claude Code's standing window for the
#: Claude models this desktop runs; the long-context variant is 1m. Nothing
#: here asks the network.
CONTEXT_WINDOW = 200_000
CONTEXT_WINDOW_1M = 1_000_000

#: Every window a Claude model on this desktop has, smallest first. The one
#: shown is the smallest of these that actually HOLDS the measured figure —
#: see `_fits`.
CONTEXT_TIERS = (CONTEXT_WINDOW, CONTEXT_WINDOW_1M)

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
        cmd0 = " ".join(str(inp.get("command") or "").split())
        # SUMMONED vs COMMANDED, on the OBSERVED line too — [his, 2026-07-29]
        # *"the `commanded` verb should also be used in solomons agent card,
        # instead of `hands`"*. It is the same distinction his notes carry
        # (`boardwork.ORCHESTRATOR_PROMPT`, `boardparse._SUMMONED`): a `dispatch`
        # starts a NEW agent, an `inbox send` gives one that is already running
        # more work. Read off the command itself and therefore ahead of the
        # tool's own `description`, which the agent writes and could word any way
        # it liked — this is the observed line, so the machine picks the words.
        if "boardctl.py dispatch" in cmd0:
            return "summoning a worker"
        if "boardctl.py inbox send" in cmd0:
            return "commanding a worker already in those files"
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
        # Same vocabulary: a `Task` call IS a new agent, so it is a summoning.
        # "handing part of it to another agent" is what this said, and `hands` is
        # the word he had replaced everywhere else.
        return "summoning another agent"
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
    """(new calls, new offset, last usage seen). Reads only the bytes since
    `offset`.

    Advances past complete lines ONLY: a transcript is appended to while this
    runs, so the final fragment is left for the next poll rather than parsed as
    a truncated object.

    The third value is the `{"model": ..., "usage": {...}}` of the LAST
    assistant entry in what was read, which is where the context tally comes
    from — it rides along here because this is already the one place the
    transcript is parsed, and re-reading the file for it would double the cost
    of every poll. `None` when the new bytes carried no assistant entry, which
    the caller reads as "keep whatever you knew".
    """
    calls = []
    try:
        size = os.path.getsize(path)
    except OSError:
        return calls, offset, None
    if size < offset:
        offset = 0                # rotated or replaced: start again
    if size == offset:
        return calls, offset, None
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            buf = f.read()
    except OSError:
        return calls, offset, None
    cut = buf.rfind(b"\n")
    if cut < 0:
        return calls, offset, None    # not one complete line yet
    last = None
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
        if isinstance(msg.get("usage"), dict):
            last = {"model": str(msg.get("model") or ""),
                    "usage": msg.get("usage")}
        for c in msg.get("content") or []:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                name = str(c.get("name") or "")
                calls.append({"name": name, "phase": classify(name, c.get("input")),
                              "doing": describe_call(name, c.get("input")),
                              "at": d.get("timestamp") or ""})
    return calls, offset + cut + 1, last


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


#: The five the CLASSIFIER can produce from a transcript, and the vocabulary the
#: observed phase is filed under. An agent's own claim is NOT limited to these —
#: see `clean_phase_word` — but the machine's reading of it still is: nothing
#: derived from tool calls can say a word that is not in here.
CLAIMABLE = ["planning", "researching", "coding", "testing", "finishing"]

#: THE MENU AN AGENT IS SHOWN, and it is a menu and not a whitelist —
#: [his, 2026-07-29] *"create a larger list of words that could describe what an
#: agent is doing, i.e. more than just coding or planning - and allow agents to
#: select from this new larger list to indicate what they alledge they are
#: doing"*. `clean_phase_word` still takes ANY single word (his rule from the
#: same day, and the honesty check is the observed line, never a vocabulary), so
#: nothing here REFUSES a word that is not on it. What the list buys is that an
#: agent bisecting a regression reaches for `bisecting` instead of rounding
#: itself off to `coding` — the five were a menu by accident, and a menu of five
#: makes every card say one of five things.
#:
#: Every word FOLLOWS "is" as English, because that is the sentence the card
#: builds (`says_line` -> `predicate`) — gerunds throughout bar `blocked`, which
#: reads after "is" anyway; every word passes `clean_phase_word`
#: (lowercase letters, one word, at most `CLAIM_WORD_MAX`), which
#: `tools/board-test.py` asserts rather than trusting.
PHASE_WORDS = [
    # the classic five first: they are what most work still is
    "planning", "researching", "coding", "testing", "finishing",
    # finding out
    "reading", "exploring", "investigating", "debugging", "bisecting",
    "profiling", "measuring", "benchmarking", "tracing", "auditing",
    # making
    "designing", "drafting", "implementing", "refactoring", "porting",
    "packaging", "documenting", "cleaning",
    # checking
    "verifying", "reviewing", "reproducing",
    # landing
    "building", "rebuilding", "committing", "merging", "rebasing",
    # neither, and honest
    "waiting", "blocked",
]

#: THE ONE PLACE A PHASE WORD BECOMES WORDS ON A CARD — phase word -> the whole
#: PREDICATE that follows the agent's name.
#:
#: It is **`is <word>`**, and that is his call twice: it was the shape from the
#: start, it became the simple present for an hour on 2026-07-29 (*"it should
#: just say 'researches...' or 'codes...'"*) and he walked that back the same
#: evening — *"sorry, change the top line of an agents card back to 'is reading'
#: or 'is coding' etc"*. Every word in `PHASE_WORDS` is a gerund bar `blocked`,
#: which reads as English after "is" anyway, so one rule covers the list and an
#: off-list word (any single word is legal) as well.
#:
#: **It stays a function rather than a f-string at the call site**, because there
#: are two callers — a worker's card and Solomon's — and the verb form drifting
#: between them is exactly what the two rounds of this cost. Solomon's own two
#: phrases override it in `orch_says_line` and nothing else does.
def predicate(word):
    """A phase word -> the predicate the card draws after the agent's name."""
    w = " ".join(str(word or "").split()).lower()
    return "is %s" % w if w else ""


#: The phase words whose line does NOT end in an animated `...` — the dots are on
#: the claim's words (`says_detail`), and a stall is not motion: an animation over
#: a state where nothing is happening is the dishonest affordance
#: docs/DESIGN.md §10 forbids.
TICKLESS = ("blocked",)


#: A claimed word is drawn inside a sentence on a card that is one line high.
#: Long enough for `investigating`; short enough that nothing can shove the rest
#: of the line off the row.
CLAIM_WORD_MAX = 16


def clean_phase_word(word):
    """One lowercase word, or "" if that is not what was handed in.

    *"allow agents more freedom to indicate what they are doing, but it should
    still only be a single word - and still actually related to what they say
    they are doing. enhancing the existing coding/testing etc"* — so the fixed
    five stopped being a whitelist and became a starting set.

    What is still enforced is only what protects the card: ONE word, letters
    (a hyphen inside is a word), lowercase, and short. Multi-word is REFUSED
    rather than silently truncated to its first word — an agent that meant
    *"code review"* and got `code` would be misreported, and refusing is
    something it can read and correct in one call (§10.2: refuse visibly,
    never no-op).

    The honesty check is NOT here and is not a vocabulary: it is the observed
    line under the claim, which the agent cannot write. That is the whole reason
    a free word is safe to allow.
    """
    w = " ".join(str(word or "").split()).lower()
    if not w or len(w) > CLAIM_WORD_MAX:
        return ""
    if not re.fullmatch(r"[a-z]+(?:-[a-z]+)*", w):
        return ""
    return w


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
    # ANY single word, not the five (`clean_phase_word`). A word that cannot be
    # drawn is refused loudly rather than dropped: silently recording nothing is
    # how the old fixed list left an agent believing it had said something.
    word = clean_phase_word(phase)
    if str(phase or "").strip() and not word:
        raise ValueError(
            "a phase is ONE word, letters only, at most %d characters"
            % CLAIM_WORD_MAX)
    with bp.locked(sidecar(aid), timeout=5.0):
        rec = read_sidecar(aid)
        rec["id"] = aid
        if word:
            rec["claimPhase"] = word
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
    # `starting` reads the same as `none`, and means the same thing: it is
    # linked, or about to be, and it has not acted. The difference between the
    # two is machine business (whether the transcript file exists yet) and never
    # reaches the screen.
    if state in ("none", "starting"):
        return "nothing yet"
    # Unlinked: no session id was ever recorded, so there is no transcript to
    # find. One sentence that is both halves of the truth — we cannot see the
    # work, and we CAN see the process — rather than two lines saying it twice.
    return "cannot see what it is doing - only that the process is there"


# --------------------------------------------- the same two, as the CARD LINES
# His words: *"in the agents tab it should read: [agent name] is [what the agent
# says its doing] and then the line below should be the [agent name] is actually
# [what it is actualy doing]"*. So the card no longer draws the bare words
# `says` and `doing` in a label column beside the two texts — the CLAIM is a
# plain sentence led by the agent's name, and these build both lines.
#
# **The second line dropped its opener** [his, 2026-07-29]: *"actually just take
# out the [agent] is actually and just display the text after it"*. So the
# observation is now the description ALONE — `editing Main.qml`, not *"Marbas is
# actually editing Main.qml"*. The name is already the subject of the line
# above it, and saying it twice was the redundancy §9.1 rules out.
#
# **The joining is chosen for the REAL strings, not assumed.** `says()` is
# `"<phase> - <words>"`, and the phase word reaches the card through
# `predicate` as *"is <word>"* — his wording, twice (see `predicate`). The words
# on their own may be a noun phrase —
# `boardctl.py phase` takes the phase as OPTIONAL and its `--doing` is *"one
# short line"*, so *"the vtbclient parser"* is a legal claim — and *"Marbas the
# vtbclient parser"* is not a sentence. That case gets `says:` instead.
#
# The observation still needs a shape per state, for the same reason: only the
# `ok` state is a bare verb phrase. `nothing recently`, `nothing yet` and the
# unlinked sentence each say their own thing — and a STOPPED agent goes to
# `last seen ...`, because with no subject on the line the tense has nowhere
# else to live, and the present tense is false about a process that is gone.
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
    if phase:
        # *"<name> is <word>"*, from the one place (`predicate`), and NOTHING
        # ELSE ON THIS LINE. What it said it is doing is `says_detail`, drawn
        # under this one — [his, 2026-07-29] the card is two lines, the verb and
        # then the words that used to follow a hyphen on this one.
        #
        # **The ticking `...` belongs to that lower line, not this one** — [his,
        # 2026-07-29] *"take the animated elipsies out of the top line"*. It
        # marks the END of what the card is saying, and with two lines the end is
        # the second one.
        return "%s %s" % (subj, predicate(phase))
    if doing:
        # No phase word to lean on, so the words are quoted rather than forced
        # into a sentence they may not fit.
        return "%s says: %s" % (subj, doing)
    return ""


# ------------------------------------------------- SOLOMON'S OWN VOCABULARY
# The orchestrator's card is the one that speaks in his own voice — [his,
# 2026-07-29] *"Solomon wields the ring..."*, *"Solomon etches the triangle..."*,
# *"Solomon summons"*, *"Solomon awaits <agent>..."*. His exact wordings, so do
# not smooth them into the generic `<subj> is <word>` shape the workers use.
#
# **Two of them are the STARTUP pair, and the order is the point.** `starting`
# (his spawn exists, its transcript is a second away) leads, then `none` (the
# transcript is there and nothing has been done in it yet) follows. That
# ordering is what 481b524 flattened: it collapsed the two states onto one
# sentence, so the brief initial line stopped LEADING and only reappeared past
# `START_GRACE_S`, i.e. AFTER the getting-ready line. Restored here [his,
# 2026-07-29] with the initial line first and worded as he wants it.
#
# His original complaint that produced 481b524 is unaffected: what he objected
# to was a *"dont know"* text flashing first, and `starting` no longer reaches
# the unlinked sentence at all — it has a line of its own that says he is
# starting. The unlinked branch (no session id EVER recorded) still says it
# cannot see, because that is a real failure.
#
# **They stay §10.6-honest for the same reason the idle row is.** Every word is
# written HERE, promoted from nothing, as the placeholder for an absence of
# observation — never derived from an observation, which stays forbidden.
#
# The trailing `...` is three ASCII periods, never U+2026: the font has no
# single-glyph ellipsis and a fallback glyph drops the whole line ~5px and clips
# it (docs/DESIGN.md §2.3). `AgentRow.qml` ANIMATES those three cells (they cycle
# `.`, `..`, `...` on the desktop's own slide duration) — presentation, so it is
# QML's, and the sentence a test asserts on does not change four times a second.
def orch_doing_line(state, who=""):
    """Solomon's placeholder for the absence of observation, or "" if the state
    is one where something has actually been seen. `state` is
    `observe()`'s outcome."""
    subj = who or ba.ORCHESTRATOR_NAME
    if state == "starting":
        return "%s wields the ring..." % subj
    if state == "none":
        return "%s etches the triangle..." % subj
    return ""


def orch_says_line(rec, who="", awaits=""):
    """His CLAIM as a sentence, in his own voice for the words he actually uses.

    `awaits` is who he is waiting on, and the caller supplies it because only
    the caller can see the other cards (`boardagents.agents()`). Empty means no
    single agent is identifiable, and the line then names nobody rather than
    printing a blank or the literal word "agent".

    Anything outside his vocabulary falls through to the ordinary `says_line`:
    this is a translation of three words, not a second sentence builder.
    """
    rec = rec or {}
    phase = rec.get("claimPhase") or ""
    subj = _subject(who) if who else ba.ORCHESTRATOR_NAME
    if phase == "dispatching":
        # No ellipsis on this one — his wording, and it is an act rather than a
        # wait, so there is nothing for the dots to say is still going on.
        return "%s summons" % subj
    if phase == "waiting":
        # The object here is WHOM, not what he said he is doing, so it belongs on
        # this line: it is part of the verb phrase. His own words go under it on
        # `says_detail`'s line, like every other card's.
        return ("%s awaits %s..." % (subj, awaits)) if awaits \
            else "%s awaits..." % subj
    return says_line(rec, who)


#: The separators an agent actually puts between its phase word and its words,
#: in the `--doing` string it hands `boardctl.py phase`. Hyphen, colon, en and em
#: dash, with or without the space — nothing here assumes one shape, because the
#: whole point is that the writer chose it and not us.
_VERB_SEP = re.compile(r"^\s*(?:[-:–—]+\s*)?")


def _drop_repeated_verb(phase, words):
    """The claim's words, without the phase word if they open by repeating it.

    [his, 2026-07-29] *"if the verb at the end of the top line is the same as the
    verb at the start of the second line, then hide the verb (or just dont use it)
    in the second line"*. The card's first line ends in that word — *"Barbatos is
    coding"* — so *"coding - writing highlight.py"* under it says it twice, which
    is §9.1's repeated metadata.

    Case-insensitive, and only ever the LEADING word: a different verb is left
    exactly as written, and so is one that merely occurs later in the sentence.
    If dropping it would leave nothing at all, the words stay — a blank second
    line under a card is worse than a repeated word.
    """
    w = (phase or "").strip().lower()
    if not w or not words:
        return words
    if words[:len(w)].lower() != w:
        return words
    rest = words[len(w):]
    # It has to be a WORD boundary: `coding` must not eat the front of
    # `codingstyle`, and `read` must not eat `reading the parser`.
    if rest[:1].isalnum() or rest[:1] == "_":
        return words
    rest = _VERB_SEP.sub("", rest, count=1).strip()
    return rest or words


def says_detail(rec):
    """The claim's SECOND line: the words the agent gave for what it is doing,
    verbatim and on their own line.

    [his, 2026-07-29] the card reads *"Marbas researches"* and then *"the
    vtbclient parser..."* under it, where the two used to share one hyphenated
    line. Verbatim is the point — this is his agent's own sentence, so it is split
    off and never reformatted; the only thing added is the trailing `...`, which
    is HERE and not on the verb line above because the dots mark the end of what
    the card is saying ([his, 2026-07-29] *"take the animated elipsies out of the
    top line"*). ASCII, and `AgentRow.qml` cycles the three cells.

    "" when it named no words, and "" when it named no PHASE either: with no verb
    line to sit under, `says_line` quotes the words itself and repeating them here
    would draw the same sentence twice (§9.1).
    """
    rec = rec or {}
    phase = rec.get("claimPhase") or ""
    if not phase:
        return ""
    words = " ".join((rec.get("claimDoing") or "").split())
    words = _drop_repeated_verb(phase, words)
    if not words:
        return ""
    return words if phase.lower() in TICKLESS else words + "..."


def doing_line(rec, who="", running=True):
    """The observation as the card's second line: the description ALONE, with no
    subject and no *"is actually"* opener. Never the claim, and never present
    tense about a process that has stopped.

    `who` is still taken because the one state that cannot be said without a
    subject — nothing observable at all — names the agent instead.

    "" only when there is nothing honest to say about a stopped agent — it was
    never seen doing anything, and inventing a past for it is worse than the
    card's own `exited without finishing` line saying all there is.
    """
    rec = rec or {}
    subj = _subject(who)
    state = rec.get("observed")
    last = rec.get("doing") or ""
    if not running:
        # PAST TENSE, and only about something actually seen. `last seen` is
        # what carries the tense now that the subject is gone from the line.
        return ("last seen %s" % last) if last and \
            state in ("ok", "quiet") else ""
    if state == "ok":
        return last or "working"
    if state == "quiet":
        # Words, never a duration — the threshold is machine business.
        return ("nothing recently - last seen %s" % last) if last else \
            "nothing recently"
    # Same line for both, for the reason `actually()` gives: a spawn whose
    # transcript is seconds away has not done anything yet, which is exactly
    # what `none` says. It is the branch below — the true unknown — that his
    # complaint was about, and it must not be reached by a run that is two
    # seconds old.
    if state in ("none", "starting"):
        return "nothing yet"
    return "board cannot see what %s is doing - only that the process is there" \
        % subj


# ------------------------------------------------- HOW FULL IT IS, on one line
# His: *"on the very right of the top row of the agent's information box it
# should keep a running tally of how much context that agent has vs how much it
# can handle"*. So a card's top row ends in `62k/200k`, and that is the whole
# feature — standing metadata about the process, drawn quietly at the trailing
# edge like every other badge (§9.1).
#
# **It is MEASURED, never estimated.** Claude Code stamps a `usage` object on
# every assistant entry of the transcript, and the standing context is
# `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` of the
# LAST one — the cached parts are the bulk of it, so leaving them out would draw
# a number an order of magnitude too small.
#
# **So is the DENOMINATOR.** The model id is supposed to name the window and
# almost never does (`_window_for`), so the window shown is the smallest one
# that can actually hold what was measured (`_fits`). A card must never draw
# `452k/200k` — it did, and he read it as context going missing.
#
# **It degrades to ABSENCE.** No session, no transcript, no assistant turn yet,
# or a usage object with nothing readable in it: the card draws nothing there,
# the way it draws every other thing it cannot see. A zero would be a claim that
# the agent is empty, and an assumed window would be a claim about a model
# nothing established.
#
# **No ramp, no colour.** A nearly-full context is not a machine fault, and
# warn/crit on this desktop means exactly that (§8.1, §9.3). It is one dim
# string, and it says its own denominator so it needs no legend (§10.5).
def _window_for(model):
    """The window a model id CLAIMS, or 0 when it claims nothing.

    The long-context variants are supposed to carry it in the name
    (`claude-opus-5[1m]`). In practice that suffix reaches the transcript
    almost never — measured 2026-07-29 across 188 transcripts under
    `~/.claude/projects`: **not one** of ~38k assistant entries stamped `[1m]`,
    while the sessions themselves plainly ran the 1m window (see `_fits`). So
    this is a hint that is usually absent, never a statement to rely on.
    """
    m = str(model or "").lower()
    return CONTEXT_WINDOW_1M if "[1m]" in m or "-1m" in m else 0


def _fits(used, claimed=0):
    """The smallest window that HOLDS `used`, or 0 when none does.

    **The transcript proves its own window.** An agent that stood in 450k
    tokens without the API refusing the call was on a 1m model, whatever its
    model id said — and the model id, above, mostly says nothing. So the
    denominator is derived from the measurement rather than from the stamp:
    the smallest tier that both holds the figure and is at least what the id
    claimed.

    This is the affordance-honesty rule (§10) applied to a number. `452k/200k`
    was drawn for real and states something that cannot happen; his reading of
    it — *"is some context getting lost"* — is exactly the wrong conclusion an
    impossible display invites, and no context was ever lost. Past the largest
    window any Claude model has there is nothing honest left to draw, so this
    returns 0 and the line degrades to absence like every other thing this
    module cannot see.
    """
    for tier in CONTEXT_TIERS:
        if tier >= used and tier >= claimed:
            return tier
    return 0


def _context_of(last, peak=0):
    """(tokens standing in the window, window) from one transcript entry, or
    (0, 0) if it does not say.

    `peak` is the largest figure this agent has ever shown, carried in its
    record: a session that has once proved itself 1m stays 1m, so the
    denominator does not shrink back after Claude Code compacts.
    """
    if not isinstance(last, dict):
        return 0, 0
    u = last.get("usage")
    if not isinstance(u, dict):
        return 0, 0
    total = 0
    for k in ("input_tokens", "cache_read_input_tokens",
              "cache_creation_input_tokens"):
        try:
            total += int(u.get(k) or 0)
        except (TypeError, ValueError):
            continue
    if total <= 0:
        return 0, 0
    try:
        peak = int(peak or 0)
    except (TypeError, ValueError):
        peak = 0
    return total, _fits(max(total, peak), _window_for(last.get("model")))


def _k(n):
    """A token count in the shortest honest form: `812`, `62k`, `1.2m`."""
    if n >= 1_000_000:
        s = "%.1fm" % (n / 1_000_000.0)
        return s.replace(".0m", "m")
    if n >= 1000:
        return "%dk" % round(n / 1000.0)
    return str(int(n))


def worked_line(ts, running=True):
    """HOW LONG the agent has been working — `working for 4 minutes` — or "".

    This REPLACED the absolute spawn stamp `born_line` drew (`10:26 am`,
    itself his 2026-07-29 ask), by his own later words the same day: the card
    should show *"how long the agent has been working: 'has been working for X
    minutes'"* — a duration, not an instant. That makes it the ONE elapsed
    time this app draws, a deliberate exception to the no-pressure
    requirement, granted by the person the requirement protects: a running
    agent's clock counts against the AGENT, not against him. Nothing else may
    cite this as precedent — `placed`, LANDED's `when` and the quiet-agent
    threshold stay absolute or unsaid.

    It reads naturally at every age: under a minute in words (never seconds —
    a ticking seconds counter is exactly the pressure the rule forbids
    elsewhere), then minutes, then hours with the minute remainder, then days.
    Recomputed on every read, so the app's ordinary agent poll keeps it
    current; nothing extra refreshes it.

    "" for a STOPPED agent, deliberately: `born` to now is not how long a dead
    process worked, and the card's own `exited ...` line already carries the
    past tense. "" too when nothing recorded a birth — nothing is invented.
    """
    try:
        ts = float(ts or 0)
    except (TypeError, ValueError):
        return ""
    if ts <= 0 or not running:
        return ""
    m = max(0, int(time.time() - ts)) // 60
    if m < 1:
        return "working for under a minute"
    if m < 60:
        return "working for %d minute%s" % (m, "" if m == 1 else "s")
    h, m = m // 60, m % 60
    if h < 24:
        who = "%d hour%s" % (h, "" if h == 1 else "s")
        if m:
            who += " %d minute%s" % (m, "" if m == 1 else "s")
        return "working for " + who
    d = h // 24
    return "working for %d day%s" % (d, "" if d == 1 else "s")


def context_line(rec):
    """`62k/200k`, or "" when nothing was measured. Both halves or neither.

    It re-checks the pair rather than trusting it: a record written before
    `_fits` existed can hold an impossible `452k/200k`, and it would survive
    every poll that reads no new assistant entry. Nothing here may draw a
    number standing in a window that cannot hold it.
    """
    rec = rec or {}
    try:
        used, window = int(rec.get("ctxUsed") or 0), int(rec.get("ctxWindow") or 0)
    except (TypeError, ValueError):
        return ""
    if used <= 0 or window <= 0:
        return ""
    if used > window:
        window = _fits(used)
        if window <= 0:
            return ""
    return "%s/%s" % (_k(used), _k(window))


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
            # Nothing to observe — but WHICH nothing. No session id was ever
            # recorded (an interactive session this system did not spawn) is the
            # real unknown; a session id we chose ourselves whose transcript has
            # not been written yet is a spawn that is a second old. `linkedAt`
            # is stamped the first time the id is seen so the second cannot
            # quietly become the first: past `START_GRACE_S` it is `unlinked`
            # again. Falling back to the CLAIM in either case stays the one
            # thing this module must not do.
            if str(rec.get("session") or ""):
                if not rec.get("linkedAt"):
                    rec["linkedAt"] = time.time()
                young = time.time() - float(rec.get("linkedAt") or 0) \
                    <= START_GRACE_S
                rec["observed"] = "starting" if young else "unlinked"
            else:
                rec["observed"] = "unlinked"
            rec["phase"] = "unreported"
            rec.setdefault("recent", [])
            ba._write_json(sidecar(aid), rec)
            return rec
        calls, offset, last = _tool_calls(path, int(rec.get("offset") or 0))
        rec["offset"] = offset
        # The tally is carried in the record like everything else here, so a
        # poll that reads no new assistant entry keeps the last MEASURED
        # figure rather than dropping the line off the card and back on.
        used, window = _context_of(last, rec.get("ctxPeak"))
        if used:
            try:
                was = int(rec.get("ctxPeak") or 0)
            except (TypeError, ValueError):
                was = 0
            rec["ctxPeak"] = max(was, used)
            rec["ctxUsed"], rec["ctxWindow"] = used, window
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
