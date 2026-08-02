"""What a HERMES minister is doing, read out of hermes's own session store.

`boardphase` is written around Claude Code's live JSONL transcript: the spawner
CHOOSES the session uuid (`--session-id`), so the file to tail is known before
the agent exists, and every tool call is one `tool_use` entry in it. **A hermes
minister has neither half of that**, and until 2026-07-31 the board simply said
so — `HermesBackend.transcript()` returned None, the card was claim-only, and
the log header pointed at a `~/.claude/projects/*/<uuid>.jsonl` that was never
going to exist for that run. That last part is the one he saw: a card for a live
minister whose drawer had nothing in it and whose header named a file that is
not there.

WHAT HERMES ACTUALLY WRITES, measured on `top` 2026-07-31 against a live worker
------------------------------------------------------------------------------
One SQLite database, `~/.hermes/state.db`, with a `sessions` row per run and a
`messages` row per turn. Three things were checked before any of this was built,
the same three `boardphase`'s docstring records for the transcript:

  1. **A headless `hermes chat -q` run gets rows.** Worker `w1a5cc2` had a
     `sessions` row with `source='tool'` and 29 messages while it ran.
  2. **They are written LIVE.** `message_count` and the `messages` rows both
     grew between two reads a minute apart, mid-run.
  3. **The linkage is NOT choosable.** `hermes chat` has no `--session-id`; the
     id is `<stamp>_<6 hex>`, minted inside the process. `--source` would be an
     exact key, but hermes hides `source='tool'` sessions from his own
     `sessions list` by comparing that string LITERALLY
     (`hermes_state.py`: `COALESCE(source,'') != 'tool'`), so tagging our runs
     `board:<id>` would put every minister in his session list. So the id is
     DISCOVERED instead — see `resolve`.

THE BINDING, and why it is a hash of the query
----------------------------------------------
The spawner knows the exact text it passed to `-q`, and hermes stores that text
verbatim as the session's first `user` message. So the spawn records a SHA-1 of
it (`boardphase.arm`) and this module finds the one session, started at or after
the spawn, whose first user message hashes to it. Exact, not a guess by mtime:
two ministers spawned in the same second are two different task texts, and a
RE-SEND of a byte-identical prompt is disambiguated by the time floor (the
earlier run's session started before this spawn).

It stays a hash rather than the text because the query is ~16 kB of prompt and
RULES, and the sidecar holding it is read on every 2.5 s poll.

WHAT DOES NOT CARRY OVER, and is not faked
------------------------------------------
**The context tally.** `messages.token_count` is NULL for every row hermes
writes (527/527, measured), and the `sessions` counters are cumulative totals
for the whole run, not what is standing in the window. So a hermes card has no
`62k/200k` line. That is absence, drawn as absence — the alternative is a
number that means something else wearing the name of this one.
"""
import hashlib
import json
import os
import sqlite3
import time

import boardphase as bph

#: Hermes's own session store. `BOARD_HERMES_DB` redirects it so a harness can
#: hand this module a synthetic database instead of reading his real one — the
#: same courtesy `BOARD_TRANSCRIPTS` does for Claude transcripts.
def db_path():
    return os.environ.get("BOARD_HERMES_DB") or \
        os.path.join(os.path.expanduser("~"), ".hermes", "state.db")


#: How far after a spawn a session may start and still be that spawn's. Generous
#: — hermes opens the row within a second, and a slow import is not a reason to
#: lose the card's observed line for the whole run.
BIND_WINDOW_S = 900

#: ...and how far BEFORE. A second of slack for the clock between the spawner
#: stamping the arm and hermes stamping `started_at`; not more, because the
#: floor is what tells a re-sent identical prompt from the run it repeats.
BIND_SLACK_S = 2


def fingerprint(query):
    """The key a spawn is found by: SHA-1 of the exact `-q` text."""
    return hashlib.sha1(str(query or "").encode("utf-8", "replace")).hexdigest()


def _connect():
    """A READ-ONLY connection, or None. Read-only because a live minister is
    writing this database and nothing here may ever hold a write lock on it —
    `immutable` is deliberately NOT set, since the file is being appended to."""
    path = db_path()
    if not os.path.isfile(path):
        return None
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=0.5)
        con.row_factory = sqlite3.Row
        return con
    except sqlite3.Error:
        return None


def available():
    """Is there a hermes store on this host at all? A machine that has never
    run a hermes minister has none, and that is not an error."""
    return os.path.isfile(db_path())


def resolve(probe, since, exclude=()):
    """The hermes session id for a spawn armed with `probe`, or `""`.

    Candidates are the `source='tool'` sessions started at or after the spawn,
    oldest first; the answer is the first whose FIRST user message hashes to
    `probe`. `""` means not yet — the row appears a moment after `execve` — and
    the caller keeps asking, exactly as `boardphase` keeps looking for a
    transcript file that has not been written yet.

    `exclude` is the sessions this agent id has already been bound to. A RETRY
    re-runs a byte-identical prompt seconds after the run that died, so its
    fingerprint and (within `BIND_SLACK_S`) its time floor both still match the
    dead session — naming it is the one thing the clock cannot rule out, and
    the caller knows it by name.
    """
    if not probe:
        return ""
    con = _connect()
    if con is None:
        return ""
    try:
        lo = float(since or 0) - BIND_SLACK_S
        hi = float(since or 0) + BIND_WINDOW_S
        rows = con.execute(
            "SELECT id FROM sessions WHERE source = 'tool'"
            "  AND started_at >= ? AND started_at <= ?"
            " ORDER BY started_at ASC LIMIT 40", (lo, hi)).fetchall()
        skip = set(exclude or ())
        for r in rows:
            if r["id"] in skip:
                continue
            first = con.execute(
                "SELECT content FROM messages WHERE session_id = ?"
                "  AND role = 'user' ORDER BY id ASC LIMIT 1",
                (r["id"],)).fetchone()
            if first and fingerprint(first["content"]) == probe:
                return str(r["id"])
    except sqlite3.Error:
        return ""
    finally:
        con.close()
    return ""


def exists(session):
    """Is this session in the store? The hermes half of the proof
    `boardagents._confirmed` wants: a row means the process got as far as
    opening its session, which is what confirmation has always meant here."""
    if not session:
        return False
    con = _connect()
    if con is None:
        return False
    try:
        return con.execute("SELECT 1 FROM sessions WHERE id = ?",
                           (session,)).fetchone() is not None
    except sqlite3.Error:
        return False
    finally:
        con.close()


def hint(session):
    """Where to read the whole run, as a command he can paste. The hermes
    analogue of a transcript path — there is no file to name, so it names the
    tool that prints one."""
    return ("hermes sessions export %s" % session) if session else ""


# ----------------------------------------------------- hermes tools -> ours
#: Hermes's tool names, translated into the ones `boardphase.classify` and
#: `boardphase.describe_call` already speak, with the argument each carries
#: under its hermes key. Taken from hermes's own `agent/display.py`
#: (`primary_args`, `_TOOL_VERBS`) and confirmed against a real run's argument
#: census, not guessed from the names.
#:
#: **Translation rather than a second classifier**: the phase vocabulary and the
#: wording of the observed line are judgements this desktop has already made
#: once (`boardphase`'s TOOL_PHASE / BASH_PHASE / describe_call, and his rules
#: about the words on a card). A minister on a different runtime must not get a
#: different sentence for the same act.
TRANSLATE = {
    "terminal":      ("Bash",      {"command": "command"}),
    # Code run through the interpreter tool is still a command being run, and
    # `BASH_PHASE` reading a `pytest` in it as testing is the right answer.
    "execute_code":  ("Bash",      {"command": "code"}),
    "read_file":     ("Read",      {"file_path": "path"}),
    "write_file":    ("Write",     {"file_path": "path", "content": "content"}),
    "patch":         ("Edit",      {"file_path": "path",
                                    "old_string": "old_string",
                                    "new_string": "new_string"}),
    "search_files":  ("Grep",      {"pattern": "pattern"}),
    "web_extract":   ("WebFetch",  {"url": "urls"}),
    "web_search":    ("WebSearch", {"query": "query"}),
    "todo":          ("TodoWrite", {}),
    "delegate_task": ("Task",      {}),
    "skill_view":    ("Read",      {"file_path": "name"}),
}

#: The phase for a hermes tool with no equivalent of ours. It keeps its own
#: name on the card (`describe_call` says *"using process"*), and this only says
#: what phase, if any, that act is evidence of. `None` — the default — is
#: "says nothing about the phase", which is what an ordinary shell command
#: already means here.
EXTRA_PHASE = {
    "session_search": "researching",
    "skills_list": "researching",
    "memory": "researching",
}


def _tool_call(call):
    """One hermes `tool_calls` entry -> `(our name, our input dict)`."""
    fn = (call or {}).get("function") or {}
    name = str(fn.get("name") or "")
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except (TypeError, ValueError):
        args = {}
    if not isinstance(args, dict):
        args = {}
    ours, keys = TRANSLATE.get(name, (name, None))
    if keys is None:
        return name, args
    inp = {}
    for mine, theirs in keys.items():
        v = args.get(theirs)
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        if v is not None:
            inp[mine] = v
    return ours, inp


def _calls_of(row):
    """The tool calls on one assistant row, as `boardphase` wants them."""
    out = []
    try:
        calls = json.loads(row["tool_calls"] or "[]")
    except (TypeError, ValueError):
        return out
    at = ""
    try:
        at = time.strftime("%Y-%m-%dT%H:%M:%S%z",
                           time.localtime(float(row["timestamp"] or 0)))
    except (TypeError, ValueError):
        pass
    for c in calls if isinstance(calls, list) else []:
        if not isinstance(c, dict):
            continue
        raw = ((c.get("function") or {}).get("name")) or ""
        name, inp = _tool_call(c)
        phase = bph.classify(name, inp)
        if phase is None and raw in EXTRA_PHASE:
            phase = EXTRA_PHASE[raw]
        out.append({"name": name, "phase": phase,
                    "doing": bph.describe_call(name, inp), "at": at})
    return out


def tool_calls(session, offset):
    """`(new calls, new offset)` — the hermes half of `boardphase._tool_calls`.

    The offset is a message ROWID rather than a byte offset: rows are appended
    with increasing ids, so `id > offset` is the same "only what is new" the
    byte seek buys, and there is no half-written row to guard against because
    SQLite hands out whole ones or nothing.
    """
    calls = []
    if not session:
        return calls, offset
    con = _connect()
    if con is None:
        return calls, offset
    try:
        try:
            off = int(offset or 0)
        except (TypeError, ValueError):
            off = 0
        top = con.execute("SELECT MAX(id) FROM messages WHERE session_id = ?",
                          (session,)).fetchone()
        newest = int((top and top[0]) or 0)
        if newest <= off:
            return calls, off
        rows = con.execute(
            "SELECT id, tool_calls, timestamp FROM messages"
            "  WHERE session_id = ? AND id > ? AND role = 'assistant'"
            "    AND tool_calls IS NOT NULL ORDER BY id ASC", (session, off))
        for row in rows:
            calls.extend(_calls_of(row))
        return calls, newest
    except sqlite3.Error:
        return calls, offset
    finally:
        con.close()


# ---------------------------------------------------------------- the drawer
#: How many of the newest rows one drawer poll reads. The drawer draws three
#: lines; a row can be a 16 kB tool result, so this is the hermes analogue of
#: `main.Agents.TRANSCRIPT_TAIL` — the end of the run, never the whole of it.
TAIL_ROWS = 12


def _tool_lines(call):
    """A hermes tool CALL as its literal arguments — the same shape
    `main.Agents._tool_use_lines` builds for a Claude one, on purpose: the
    drawer is one surface and a minister's runtime is not something he should
    have to read differently."""
    fn = (call or {}).get("function") or {}
    name = str(fn.get("name") or "tool")
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except (TypeError, ValueError):
        args = {}
    if not isinstance(args, dict):
        args = {}
    lead = ("command", "code", "path", "pattern", "urls", "query", "name",
            "question", "goal", "action")
    first = ""
    for k in lead:
        v = args.get(k)
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        if v not in (None, ""):
            first = str(v)
            break
    out = ["$ " + " ".join(first.split()) if name in ("terminal", "execute_code")
           and first else (name + " " + first).rstrip()]
    for k in ("old_string", "new_string", "content"):
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            out.append(k + ":")
            out.extend(v.split("\n"))
    return out


def _result_lines(content):
    """A hermes tool RESULT as its own text. The store carries it as a JSON
    object (`{"output": ..., "exit_code": ..., "error": ...}` for the terminal
    tool) or as plain text; both are the same lines to him, and the plain-text
    fallback is what keeps a tool this does not know about readable."""
    body = str(content or "")
    try:
        o = json.loads(body)
    except ValueError:
        return body.split("\n")
    if not isinstance(o, dict):
        return body.split("\n")
    out = []
    for k in ("output", "error", "content", "stdout", "stderr", "result"):
        v = o.get(k)
        if isinstance(v, str) and v.strip():
            out.extend(v.split("\n"))
    return out or body.split("\n")


def lines(session, tail=TAIL_ROWS, tools_only=False):
    """THE MINISTER'S LITERAL OUTPUT, live, newest at the tail.

    The hermes half of `main.Agents._transcript_lines`, and the same rule for
    what belongs in it: every assistant turn's reasoning and text, every tool
    call's own arguments, every tool result's own output — and never his own
    prompt read back at him.

    With `tools_only`, ONLY the tool calls — for the shell band, which shows the
    tools a minister uses and not its prose, reasoning or a tool's own output.
    """
    if not session:
        return []
    con = _connect()
    if con is None:
        return []
    try:
        rows = con.execute(
            "SELECT id, role, content, tool_calls, reasoning_content"
            "  FROM messages WHERE session_id = ?"
            " ORDER BY id DESC LIMIT ?", (session, int(tail))).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    out = []
    for row in reversed(rows):
        role = row["role"]
        if role == "user":
            continue                     # his prompt, not the agent's output
        if role == "tool":
            if not tools_only:           # a tool's output is not an invocation
                out.extend(_result_lines(row["content"]))
            continue
        if role != "assistant":
            continue
        if not tools_only:
            think = row["reasoning_content"] if "reasoning_content" in row.keys() \
                else ""
            if isinstance(think, str) and think.strip():
                out.extend(think.split("\n"))
            body = row["content"]
            if isinstance(body, str) and body.strip():
                out.extend(body.split("\n"))
        try:
            calls = json.loads(row["tool_calls"] or "[]")
        except (TypeError, ValueError):
            calls = []
        for c in calls if isinstance(calls, list) else []:
            if isinstance(c, dict):
                out.extend(_tool_lines(c))
    return [x.rstrip() for x in out if x.strip()]
