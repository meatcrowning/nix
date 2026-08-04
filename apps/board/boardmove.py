"""Moving a board item as work starts, lands, or dies — the policy half.

`boardparse` owns the line edits; this owns WHEN they are made and WHAT the
item says on its way through. Two callers, one implementation on purpose:

  * `home/srvs/board-watch-files/board-watch.py` — moves the decision as it
    spawns its agent, and hands it back if that agent dies.
  * `tools/boardctl.py` — the same moves for a human, or for an orchestrating
    session that dispatched an agent itself. Work is not only started by the
    watcher, and the answer to "how do I move this" must never be "hand-edit the
    markdown".

WHAT LEAVES THE STORE WHEN WORK STARTS, and what does not
---------------------------------------------------------
**An answered decision is REMOVED from NEEDS YOU and nothing is written in its
place.** There was an `## IN FLIGHT` row until 2026-07-30; the section is gone
[his call — the note in `boardparse` where its writers were has the why] and
this module is what it was load-bearing FOR. What the row said is now either
somewhere better or nowhere:

  * that the item is being worked  -> the triangle, drawn from the agent's own
                                      process and transcript, which cannot go
                                      stale the way a hand-written row did
  * what landed                    -> LANDED, computed from the commit log
  * his answer, read back          -> the stash, and back onto his own decision
                                      verbatim if it has to be handed back

There is **no timestamp, no age, no "started at", nothing counting** anywhere he
can see. §"The no-pressure requirement is a design constraint" in `AGENTS.md`:
he asked for this board because a running log made him feel he had to act in the
moment. The stash records a start time, because reconciliation is machine
business; it never reaches the file.

STRANDING, and why an item cannot
---------------------------------
A decision that has left NEEDS YOU with nothing working on it is invisible: it
is not being asked and not being done. So `start()` STASHES its raw lines
outside the store, and there are three ways back:

  1. the agent finished       -> `land()`, and the stash is dropped
  2. the agent exited badly   -> `give_back()` from the watcher, same run: the
                                 block goes back into NEEDS YOU byte-for-byte
                                 and a bullet in WAITING ON YOU TO DO says so
  3. the whole watcher died   -> `reconcile()`, run at the top of every
                                 board-watch tick (so, within five minutes),
                                 finds stashes whose owning process is gone and
                                 does 2 for them

**There used to be a fourth, and losing the need for it is the point.** All
three above are keyed on the stash, and the stash is MACHINE-LOCAL state while
the board synced between the machines (one shared file, back then) — so a row
`top` started was, from `book`,
indistinguishable from a row nobody started. Add the rows written before the
stash existed and the rows added by hand, and IN FLIGHT could only ever grow:
`stall()` was the manual exit for the ones no mechanism here could reach, and he
read the result as *"doesnt update at all its still got old stuff in it"*.
Nothing accumulates now, because nothing is written. A stash the other machine
owns is simply not this host's business, which is what it always was.

Case 3 checks the pid AND its kernel start time, so a recycled pid cannot make a
dead agent look alive. A stash with no owner pid (an interactive session started
it) is never reclaimed automatically — nothing here can tell whether that
session is still thinking.

**THE OWNER IS THE AGENT, NOT THE TICK** (`adopt()`, and it is why that function
exists). `start()` is called before the agent process exists, so the only pid it
can stash is the caller's — and the caller is `board-watch.service`, a oneshot
that home-manager STOPS on every `switch`. Measured on top 2026-07-30: a rebuild
at 19:23:50 killed the tick working decision 1 seventy-seven seconds in, the
agent itself survived (`KillMode=process`), and the next tick's `reconcile()`
read the dead tick's pid, announced "its agent is gone" and put the decision back
in NEEDS YOU — where the answer read as newly answered and fired a SECOND agent
at 19:33:04. Two agents did one job. So the spawner calls `adopt()` the moment
the agent process exists and liveness follows THAT process for the rest of the
run.

`retire_finished()` closes the other end of the same window: an agent that
outlives its tick has nobody left to call `land()` or `forget()`, so when it
finally exits its stash still names a dead pid and case 3 would hand back work
that was done. An agent that recorded a result on the board (`boardwork.reported`
— the same fact `reap()` files a worker by) is retired instead of reclaimed.
"""
import datetime
import json
import os
import re
import socket
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(os.path.dirname(HERE), "pylib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import boardparse as bp                                            # noqa: E402
from boardparse import BoardError                                  # noqa: E402,F401


def state_dir(path=None):
    """Where this app keeps its own bookkeeping. NOT `stash_dir()`: every
    `.json` in there is read back as an in-flight item (see `_stashes`), so a
    file that is not one belongs here instead.

    `path` is the BOARD the state is ABOUT, and the default — None — means this
    host's own, which is what every existing caller wants. A board that is not
    it gets a scratch root instead (`boardparse.scratch_state_dir`), so a probe
    run against a `/tmp` board cannot leave a card on his.
    """
    d = bp.scratch_state_dir(path) if path is not None else None
    if d is None:
        base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
        d = os.path.join(base, "board")
    os.makedirs(d, exist_ok=True)
    return d


def stash_dir(path=None):
    d = os.path.join(state_dir(path), "inflight")
    os.makedirs(d, exist_ok=True)
    return d


def stash_file(key, path=None):
    return os.path.join(stash_dir(path), re.sub(r"[^a-z0-9-]", "_", key) + ".json")


def _stat_fields(pid):
    """`/proc/<pid>/stat` after the comm, which can itself contain spaces and
    brackets — hence the rsplit on `)`. Fields are 0-based from `state`."""
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[1].split()
    except (OSError, IndexError, ValueError):
        return None


def _proc_start(pid):
    """The kernel's start time for a pid, so a recycled one is not mistaken for
    the process we spawned. None if it cannot be read."""
    f = _stat_fields(pid)
    return f[19] if f and len(f) > 19 else None


def _alive(rec):
    """THE liveness rule for this whole tree. pid, kernel start time, and not a
    zombie.

    The zombie clause is not pedantry. Workers are spawned DETACHED and nobody
    waits on them (`boardwork._spawn_worker`), so between a worker exiting and
    its spawner exiting it sits as `Z` — `/proc/<pid>` still exists and the
    start time still matches, so without this a finished worker held a slot
    against the concurrency cap and kept a card on his board. Measured: two stub
    workers that ran for one second were still counted as running two and a half
    seconds later, and `promote()` refused to start the queued ones.
    """
    pid = rec.get("pid")
    if not pid:
        return True          # no owner recorded: not ours to reclaim
    f = _stat_fields(pid)
    if not f:
        return False
    if f[0] == "Z":
        return False
    want = rec.get("pidStart")
    return want is None or (len(f) > 19 and f[19] == want)


def _stashes():
    out = []
    for name in sorted(os.listdir(stash_dir())):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(stash_dir(), name)) as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        # A stash is identified by its `key` (`stash_file()` is named from it).
        # Anything else that ends up in this directory is not one, and drawing
        # it as an item in flight invents an agent out of a stray file — which
        # is exactly what the LANDED sweep's timestamp did until it moved to
        # `state_dir()`. Left as a guard so a stamp already on disk, on either
        # machine, stops being a card without anything having to delete it.
        if isinstance(rec, dict) and rec.get("key"):
            out.append(rec)
    return out


# ------------------------------------------------------------------ selectors
def find_needs(doc, sel):
    """A decision, by number (`4`), by key/slug, or by a bit of its title."""
    sel = (sel or "").strip()
    low = sel.lower()
    for it in doc["needs"]:
        if sel and (it["num"] == sel or it["key"] == low):
            return it
    low = _norm(sel)
    hits = [it for it in doc["needs"] if low and low in _norm(it["title"])]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise BoardError("'%s' matches %d decisions: %s"
                         % (sel, len(hits), ", ".join(h["title"] for h in hits)))
    raise BoardError("no decision in NEEDS YOU matches '%s'" % sel)


def _norm(s):
    """Compare a selector to what is drawn. The parsed cells are glyph-mapped
    and the stashed title is raw, so both sides go through the same map before
    they are matched — otherwise an em dash in a title makes the row it names
    unfindable."""
    return " ".join(bp.text(s or "").lower().split())


def said(lines, item):
    """His answer, read back: the option he ticked, his own sentence, or both.
    Empty if he answered by neither — the caller then writes nothing rather than
    inventing a note.

    Both come from the RAW lines. `item["label"]` has been glyph-mapped for
    drawing, and putting that back in the file would rewrite the store's prose
    into ASCII one move at a time.
    """
    parts = []
    chosen = [bp.raw_option(lines, o) for o in item["options"] if o["checked"]]
    if chosen:
        parts.append("you chose: " + "; ".join(chosen))
    if item["answer"].strip():
        parts.append("you said: " + " ".join(item["answer"].split()))
    return ". ".join(parts)


# ---------------------------------------------------------------- the moves
def start(sel, where="agent", notes=None, pid=None, path=bp.BOARD_PATH,
          force=False, session="", model="", effort=""):
    """Lift an answered decision OUT of NEEDS YOU, verbatim, into the stash.
    Returns the stash record.

    It used to land a row in IN FLIGHT as well; that section is gone
    [2026-07-30, his call — see `boardparse`'s note where the writers were] and
    the move is now a removal. **What the section was load-bearing FOR is
    entirely here**: the decision leaves the questions list the moment work
    starts, so the board stops asking him something he has already answered,
    and `block`/`before` hold his own words byte-exact so `give_back()` can put
    the question back if the agent never finishes.

    `where` and `notes` are still recorded on the stash. Nothing draws them
    today, but they are what a hand-back and any future report are written
    from, and dropping facts on the floor at the one point they are known is
    not a saving.
    """
    rec = {}

    def go(doc):
        item = find_needs(doc, sel)
        if not item["answered"] and not force:
            raise BoardError("decision %s is not answered yet - nothing to work on"
                             % (item["num"] or item["key"]))
        title = bp.raw_title(doc["lines"], item)
        note = said(doc["lines"], item) if notes is None else notes
        a, b = bp.item_span(doc["lines"], item)
        after = doc["lines"][b].rstrip("\n") if b < len(doc["lines"]) else ""
        lines, block = bp.cut_item(doc["lines"], item)
        rec.update({"key": item["key"], "num": item["num"], "title": title,
                    "where": where, "notes": note, "block": block,
                    # the heading it sat above, so a hand-back is byte-exact
                    "before": after if after.startswith("###") else "",
                    "pid": pid, "pidStart": _proc_start(pid) if pid else None,
                    # The agent's `--session-id`, so its card can say what it is
                    # actually doing and not only that it is alive
                    # (`boardphase.py`). Empty for a hand-started item.
                    "session": session or "",
                    # The tier this decision runs on — `boardwork.role_tier`
                    # ("decision"), resolved by the spawner from the same
                    # precedence `role_flags` launches it with, so the card's
                    # model label can never disagree with the running model.
                    # Empty for a hand-moved item (`boardctl start`), which is
                    # nobody running a model at all.
                    "model": model or "", "effort": effort or "",
                    "host": socket.gethostname(),
                    "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "board": os.path.abspath(path)})
        return lines

    if not bp.edit(path, go):
        raise BoardError("nothing was written")
    # The stash is written AFTER the move, not before: a stash for an item still
    # sitting in NEEDS YOU would be reclaimed into a duplicate of itself.
    # ...and it is written for THIS board: a stash for a board that is not this
    # host's own goes to that board's scratch root, never into his `inflight/`
    # where it would draw a minister card nothing can ever reap.
    with open(stash_file(rec["key"], path), "w") as f:
        json.dump(rec, f, indent=1, sort_keys=True)
    return rec


def adopt(key, pid, board=None):
    """Hand a stash's ownership to the process that is actually doing the work.

    `start()` runs BEFORE the agent exists, so the pid it stashes is the
    spawner's — and a spawner is not what the item's liveness means. On `top`
    the spawner is `board-watch.service`, which home-manager stops on every
    `sudo rebuild-top`; the agent it started is a detached `claude` that
    survives (`KillMode=process`). Between those two facts, one rebuild made
    `reconcile()` declare a live agent gone and the decision fired twice (the
    module docstring has the timings). Called with the agent's own pid the
    moment `Popen` returns, so the window where the two disagree is the fork
    itself.

    Returns the updated record, or None if there is no stash for `key` — a
    caller whose `start()` failed still spawns the agent, and adopting nothing
    is not an error.

    `board` is the same board `start()` was given, and for the same reason: the
    stash it wrote is under that board's root. The default — this host's own —
    is what board-watch and every other caller passes by omission.
    """
    path = stash_file(key, board)
    try:
        with open(path) as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return None
    rec["pid"] = pid
    rec["pidStart"] = _proc_start(pid) if pid else None
    # What it was, kept: the only reader is a person working out why an item
    # was or was not reclaimed, and "the tick that started this is not the
    # process being watched" is the first thing they need to know.
    rec["spawnerPid"] = rec.get("spawnerPid") or rec.get("pid")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(rec, f, indent=1, sort_keys=True)
    os.replace(tmp, path)
    return rec


def retire_finished():
    """Drop the stash of every agent that finished and then exited unwatched.

    THE OTHER HALF OF `adopt()`. An agent whose tick was killed mid-run has
    nobody left to call `land()` or `forget()` for it, so its stash outlives it
    naming a dead pid — and `reconcile()` below would read that as a death and
    hand back work that is already done, which is the same duplicate by a
    slower route.

    The fact that tells them apart is `boardwork.reported()`: whether the agent
    put its result on the board with `note`, `land` or `ask`. It is the same
    fact `reap()` sorts a worker into done/ rather than failed/ by, so there is
    one definition of "it finished" in this tree and not two. Imported lazily —
    `boardwork` imports `boardagents`, which imports this module.

    Returns the records retired, for the caller to log.
    """
    try:
        import boardwork as bw
    except Exception:
        return []
    out = []
    for rec in _stashes():
        if not rec.get("pid") or _alive(rec):
            continue
        try:
            if not bw.reported(rec["key"]):
                continue
        except OSError:
            continue
        forget(rec["key"])
        out.append(rec)
    return out


def _stash_for(sel):
    """The stash a selector names — key, decision number, or part of the title.
    An agent that started an item with `4` must be able to land it with `4`."""
    sel = (sel or "").strip()
    for r in _stashes():
        if r.get("key") == sel.lower() or (r.get("num") and r["num"] == sel) \
                or (sel and _norm(sel) in _norm(r.get("title"))):
            return r
    return None


#: Where a commit hash might be. `~/nix` is the public repo and `docs/` is the
#: private one living inside it; a landed change is in one or the other, and
#: which one is not worth asking the caller for.
COMMIT_REPOS = (os.path.expanduser("~/nix"), os.path.expanduser("~/nix/docs"))


def commit_time(commit, repos=COMMIT_REPOS):
    """A commit's OWN local time, `3:42 pm`. Empty if the hash resolves nowhere.

    His words: *"each commit should include the time it happend"* — so it is
    read from git's committer date in the machine's local zone, and never from
    when the row happened to be written. Those two are minutes apart for an
    agent that tested before it recorded, and hours apart for a backfill.

    Empty is a normal answer, not a failure: half the rows in LANDED name no
    commit at all (`no change`, a decision settled), and a row with no time is
    written with two cells exactly as it always was.
    """
    c = (commit or "").strip().strip("`")
    if not re.fullmatch(r"[0-9a-fA-F]{4,40}", c):
        return ""
    for repo in repos:
        try:
            p = subprocess.run(
                ["git", "-C", repo, "show", "-s", "--format=%cd",
                 "--date=format:%I:%M %p", c + "^{commit}"],
                capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        out = p.stdout.strip()
        if p.returncode == 0 and out:
            # `%-I` is a GNU extension git's own strftime may not honour, so the
            # leading zero is stripped here where it can be relied on.
            return out.lstrip("0").lower()
    return ""


def land(sel, commit, what=None, date=None, when=None, path=bp.BOARD_PATH):
    """Record a commit in LANDED, under today's date, with its own time.

    **`what` is required and there is no row to take it from.** It used to be
    optional for the one caller that had an IN FLIGHT row — a decision agent —
    while a WORKER dispatched out of the box never had one, and for a day that
    meant every commit the fan-out produced was unrecordable: `land` needed a
    row it could not have, so a worker could only leave a bullet and LANDED
    silently stopped growing while the repo did not. He noticed. The row was
    made optional then and the section is gone now, so this takes the sentence
    from its caller, always. `sel` is still accepted and still names the STASH
    to forget, which is how a decision agent closes its own item out.

    **If LANDED already names this commit, the row is UPGRADED in place rather
    than added.** The sweep (`reconcile_landed`) fills a hole about two minutes
    after the push now, so a worker that takes longer than that to come back and
    `land` will regularly find its own commit already there under the raw commit
    subject. Dropping the call on the floor — which is what "skip a hash the doc
    already names" amounted to — threw away the sentence the agent chose, and
    that sentence is the whole reason `land` is still the primary path. So the
    What cell is rewritten: ONE line, in place, same commit and same time, which
    is a targeted line edit like every other write here and not a re-serialise.
    A `land` that would write the identical row changes nothing.
    """
    got = {}
    upgraded = []
    when = commit_time(commit) if when is None else when
    if not what:
        raise BoardError("no --what was given - there is no line to record")

    def existing(doc):
        c = (commit or "").strip().strip("`").lower()
        if not re.fullmatch(r"[0-9a-f]{4,40}", c):
            return None
        for grp in doc.get("landed") or []:
            for row in grp.get("rows") or []:
                h = (row.get("commit") or "").strip().strip("`").lower()
                if h and (h.startswith(c) or c.startswith(h)):
                    return row
        return None

    def go(doc):
        del upgraded[:]
        lines = doc["lines"]
        have = existing(doc)
        if have is not None:
            lines = lines[:have["line"]] \
                + [bp.landed_row(have["commit"], what, have["when"] or when)] \
                + lines[have["line"] + 1:]
            upgraded.append(True)
            return lines
        return bp.add_landed_row(lines, commit, what, date, when)

    # A `land` that re-states a row already reading exactly that way writes
    # nothing, and that is a SUCCESS: `bp.edit` returns False for "the bytes
    # would not change", which here means the record is already right.
    if not bp.edit(path, go) and not upgraded:
        raise BoardError("nothing was written")
    # A selector names a STASH, not a row: a decision agent closing its own item
    # out. It is optional and usually absent (a worker never had one), so a
    # selector that matches nothing is not an error — the commit is recorded
    # either way, which is the bug that made this optional in the first place.
    if sel:
        # `_stash_for` takes the same three selectors `start` did — the key, the
        # decision number, or part of the title — so `land 1` drops the stash
        # `start 1` wrote. `forget(sel)` alone would only ever match the key,
        # which is how a numbered decision stayed reclaimable after it landed.
        got.update(_stash_for(sel) or {})
        forget(got.get("key") or sel)
    return got


def give_back(sel, why=None, path=bp.BOARD_PATH):
    """The stash -> NEEDS YOU, verbatim, plus a bullet saying why.

    One edit, not two: the decision and the bullet explaining it land together,
    because this file syncs to the other machine and a half-applied hand-back
    reads there as a question that came back with nothing to say for itself.
    """
    rec = None
    sel = (sel or "").strip()
    for r in _stashes():
        # Same three selectors `start` took, so an agent can hand an item back
        # with the string it was started with.
        if r.get("key") == sel.lower() or (r.get("num") and r["num"] == sel) \
                or (sel and _norm(sel) in _norm(r.get("title"))):
            rec = r
            break
    if rec is None:
        raise BoardError(
            "no stashed decision matches '%s' - its original text is not "
            "recoverable, so it has to be moved by hand" % sel)
    # `block` is the decision's verbatim lines and the ONLY thing that can be
    # put back; a stash without one is unrestorable, not merely awkward. Say so
    # as a BoardError, the failure every caller already handles, rather than
    # letting a KeyError out of `go` — that one escaped `reconcile`'s except and
    # crash-looped board-watch for 8.5 hours on 2026-08-01, after a worker left
    # a hand-written probe record in the live stash dir.
    if not rec.get("block"):
        raise BoardError(
            "stashed decision '%s' has no saved block - its original text is "
            "not recoverable, so it has to be moved by hand" % rec["key"])

    def go(doc):
        lines = bp.add_needs_item(doc["lines"], rec["block"], rec.get("before"))
        if why:
            b = why.strip()
            lines = bp.add_todo_bullet(lines, bp.parse("".join(lines)),
                                       b if b.startswith("- ") else "- " + b,
                                       by=whoami()[1])
        return lines

    bp.edit(path, go)
    forget(rec["key"])
    return rec


def ask(question, context=None, options=None, if_unanswered=None, asked_by=None,
        path=bp.BOARD_PATH, by=None):
    """An agent asking him something: one new decision at the end of NEEDS YOU.

    THIS IS THE SAME MECHANISM AS EVERY OTHER QUESTION ON THE BOARD, and that is
    the point. He asked for "a section where questions for me to answer would be
    easily reachable in a list" — NEEDS YOU already is that list, so an
    agent-authored question is written as the same `### n. title` block, with the
    same options, the same `>` answer line and the same `*If unanswered:*`
    sentence. It draws identically, it is answered identically, and answering it
    fires board-watch identically. There is deliberately no second channel and
    no "asked by a robot" flag to sort on.

    `if_unanswered` is REQUIRED and the caller is refused without it. That
    sentence is what makes it safe for him to walk away from a question — the
    app draws it on every item, always, and an item that arrived without one
    would be the first thing on this board that quietly demands an answer.

    Returns the new item's key, so the caller can seed board-watch with it
    (`boardwork.seed_watch_state`) — see that function for why that matters.
    """
    q = " ".join((question or "").split())
    if not q:
        raise BoardError("a question needs a question in it")
    if not (if_unanswered or "").strip():
        raise BoardError(
            "every question needs --if-unanswered: what happens if he never "
            "answers. It is drawn on the item and it is what makes the question "
            "safe to ignore")
    key = {}

    def go(doc):
        # The numbering is the file's, so it continues the file's own sequence
        # rather than restarting. Items that have landed took their numbers with
        # them; reusing one is harmless (nothing selects on a number outside
        # NEEDS YOU) and is what he would have written by hand.
        nums = [int(it["num"]) for it in doc["needs"] if it["num"].isdigit()]
        num = (max(nums) + 1) if nums else 1
        title = "%d. %s" % (num, q)
        key["key"] = bp.slug(title)
        # WHEN it went up, on the line right under the title — his: *"mesages in
        # the needs you section should all have the time they were placed on the
        # board indicated on them."* An HTML comment, so the file still reads
        # cleanly for him; `boardparse._PLACED` owns the shape and the reasons.
        # ...and WHO put it there, on the line above the time (`boardparse._BY`).
        # `asked_by` is a different fact and stays where it is: it says what the
        # agent was WORKING ON, in his prose, and is not an attribution.
        block = [l for l in ("### %s\n" % title, bp.by_now(whoami()[1] or by),
                             bp.placed_now(), "\n") if l]
        for para in [p for p in (context or []) if (p or "").strip()]:
            block += [" ".join(para.split()) + "\n", "\n"]
        if asked_by:
            block += ["Asked by an agent while working on: %s\n"
                      % " ".join(str(asked_by).split()), "\n"]
        for opt in [o for o in (options or []) if (o or "").strip()]:
            block.append("- [ ] %s\n" % " ".join(opt.split()))
        if options:
            block.append("\n")
        block += [">\n", "\n",
                  "*If unanswered:* %s\n" % " ".join(if_unanswered.split()), "\n"]
        return bp.add_needs_item(doc["lines"], block)

    if not bp.edit(path, go):
        raise BoardError("nothing was written")
    return key.get("key", "")


def _blame_times(path):
    """`{line index: local ISO minute}` for the store, from `docs/`'s git log.

    `git blame --line-porcelain`, one call for the whole file. The store is
    committed and pushed by a five-minute timer, so "when the commit that put
    this line here was authored" is within a few minutes of when the item
    actually went up — close enough to be true, and the only record there is for
    an item written before the stamp existed.
    """
    p = os.path.abspath(path)
    try:
        r = subprocess.run(
            ["git", "-C", os.path.dirname(p), "blame", "--line-porcelain",
             "--", os.path.basename(p)],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return {}
    if r.returncode != 0:
        return {}
    out, n, when, tz = {}, -1, None, "+0000"
    for ln in r.stdout.splitlines():
        m = re.match(r"^[0-9a-f]{40}\s+\d+\s+(\d+)", ln)
        if m:
            n, when = int(m.group(1)) - 1, None
        elif ln.startswith("author-time "):
            when = int(ln.split()[1])
        elif ln.startswith("author-tz "):
            tz = ln.split()[1]
        elif ln.startswith("\t") and n >= 0 and when:
            off = int(tz[:3]) * 3600 + int(tz[0] + tz[3:]) * 60
            local = datetime.datetime.utcfromtimestamp(when + off)
            out[n] = local.strftime("%Y-%m-%dT%H:%M")
    return out


def backfill_placed(path=bp.BOARD_PATH):
    """Stamp the items that were already on the board when the stamp landed.

    A ONE-OFF migration, run by hand once (2026-07-29) and left here because it
    is the only honest way to date the items that predate `placed_now()`: every
    writer stamps from now on, so a second run finds nothing to do. It never
    touches an item that already has a stamp, and an item git cannot date is
    left alone rather than given a made-up time — the app draws no time for it,
    which is the graceful answer and not an empty box.

    Returns how many stamps it wrote.
    """
    times = _blame_times(path)
    if not times:
        return 0
    wrote = [0]

    def go(doc):
        ins = []
        for it in doc["needs"]:
            if not it["placedRaw"] and it["titleLine"] in times:
                ins.append((it["titleLine"], times[it["titleLine"]]))
        for t in doc["todo"]:
            if not t.get("placedRaw") and t["line"] in times:
                ins.append((t.get("endLine", t["line"]), times[t["line"]]))
        lines = list(doc["lines"])
        for at, stamp in sorted(ins, reverse=True):
            lines[at + 1:at + 1] = ["<!-- placed: %s -->\n" % stamp]
        wrote[0] = len(ins)
        return lines

    bp.edit(path, go)
    return wrote[0]


def whoami(agent_id=None):
    """`(id, name)` of the agent writing — from the argument, else the
    environment `boardwork.mark_reported` reads.

    `boardagents` is imported HERE and not at the top: it imports this module,
    so a module-level import would be a cycle.
    """
    import boardagents as ba
    aid = ba.clean_id(agent_id or os.environ.get("BOARD_AGENT_ID") or "")
    if not aid or aid == "agent":
        return "", ""
    return aid, ba.name_of(aid) or ba.name_for(aid)


def note(text, path=bp.BOARD_PATH, agent_id=None, by=None):
    """One bullet into WAITING ON YOU TO DO.

    **A RESULT retires the summon note that announced it** — his rule,
    2026-07-29 — in the same read-modify-write as the insert, so the board never
    holds *"summoned Marbas, nothing landed yet"* above the line saying what
    landed. `boardparse.drop_summon` decides which note that is and refuses to
    guess; `agent_id` names the agent the result is FROM, defaulting to
    `BOARD_AGENT_ID` — board-watch passes it explicitly, because there the
    process writing the failure is not the worker that failed.

    It must start with one of `boardparse.TODO_TAGS` — `INFORMATION:`,
    `ENACTED:`, `PARTIAL:`, `FAILED:`, or a colonless
    `SUMMONED`/`COMMANDED` — then a summary of AT
    MOST about a dozen words on that same line, then whatever background it
    needs on INDENTED continuation lines. **A `QUESTION:` bullet is refused ALWAYS**
    (`boardparse.check_no_question`, before any other check): a question to him
    belongs only in the decisions section, written with `boardctl.py ask`
    (`boardmove.ask`, with its options and its `--if-unanswered`) — a
    QUESTION-tagged note is a strictly worse duplicate, so the tool tells the
    caller to use `ask` instead. `add_todo_bullet` refuses an untagged
    one, and since 2026-07-29 an over-long first line too
    (`boardparse.check_short_summary`); this deliberately does not paper over
    either with a default or a truncation: the writer knows which of the four
    tags it is and what the summary is, and nothing downstream can either work out
    afterwards.

    The `- ` is added PER LINE, not once for the whole string. The orchestrator
    writes one line per task in one call, and prefixing only the first left the
    second as a bare paragraph glued onto the bullet above it — which is how
    *"**default handlers for every app we wrote** - handed to Sam"* came to be
    drawn as part of somebody else's message on 2026-07-29. An INDENTED line is
    a wrapped continuation and is left alone.

    **That per-line split is also how you post SEVERAL asks: one line each.**
    One bullet is one ask, and `add_todo_bullet` refuses a message that bundles
    (`boardparse.check_one_ask`) — because replying to a bullet clears it, so an
    ask folded into another one is cleared by a reply that was never about it.
    """
    if not text.strip():
        return False
    out = []
    for line in text.strip().split("\n"):
        if not line.strip():
            continue
        if line[:1].isspace() or line.lstrip().startswith("- "):
            out.append(line)
        else:
            out.append("- " + line)
    body = "\n".join(out)
    me = whoami(agent_id)
    aid, who = me if bp.is_result(body) else ("", "")
    # WHO wrote it, for the gutter — resolved from the ENVIRONMENT and never
    # from `agent_id`. The two are different questions: `agent_id` names the
    # agent a result is FROM (which is what retires its summon note above),
    # while the stamp says who put the line on the board. They are the same
    # process for a worker writing its own result, and they are NOT for
    # `board-watch`, which writes the failure note for a minister that died —
    # reading `agent_id` there stamped every one of those with the dead
    # minister's name, i.e. an entry attributed to the one process that
    # certainly did not write it, on a bullet whose own text says it recorded
    # nothing. `by` is the fallback for a caller with no agent identity at all,
    # which is the program's own name. Neither resolving means NO stamp:
    # `boardparse.by_now` refuses to invent an author, and the gutter draws
    # nothing for one.
    stamp_by = whoami()[1] or by

    def go(doc):
        lines = doc["lines"]
        if aid or who:
            # The removal goes FIRST, and the parse is redone if it took one
            # away: a bullet's index only means anything against the lines it
            # was read from, and doing it the other way round would also make
            # the result bullet a candidate to match itself.
            out = bp.drop_summon(lines, doc, aid, who)
            if out is not lines:
                lines, doc = out, bp.parse("".join(out))
        return bp.add_todo_bullet(lines, doc, body, by=stamp_by)

    return bp.edit(path, go)


def forget(key):
    try:
        os.unlink(stash_file(key))
        return True
    except OSError:
        return False


#: How long a stash that records NO owner pid may sit before `reconcile()`
#: reclaims it anyway.
#:
#: `_alive()` returns True for a pid-less record — "no owner recorded: not ours
#: to reclaim" — and that is the correct LIVENESS answer: `boardctl start` with
#: no `--pid` is a human or an orchestrating session moving the item, and
#: nothing here can tell whether that session is still thinking. But liveness
#: with no bound is a LIFETIME of forever, and that is what it meant in
#: practice: two decisions answered on 2026-07-28 still had pid-less stashes a
#: day later, so `reconcile()` skipped them on every tick and `boardagents`
#: drew two `unowned` agent cards that nothing in this tree could ever collect.
#: He saw them for what they were — *"it also seems to have some residual agents
#: left that should've been swept up"*.
#:
#: Hours rather than minutes, because the thing being waited on is a person or a
#: session at a terminal, not a spawned worker: board-watch caps its own agents
#: at 45 minutes and `ESCALATE_AFTER_S` is 30, so this sits well clear of both
#: and only ever fires on something that has plainly been abandoned.
UNOWNED_STRAND_S = int(os.environ.get("BOARD_UNOWNED_STRAND", str(4 * 3600)))


def _stash_age(rec):
    """Seconds since a stash was written, from its own stamp or, failing that,
    the file's mtime. Never negative and never a guess: a record with neither is
    treated as brand new, so an unreadable clock can only ever DELAY a reclaim.
    """
    for k in ("started", "at"):
        v = rec.get(k)
        if not v:
            continue
        try:
            return max(0.0, time.time()
                       - time.mktime(time.strptime(str(v)[:19], "%Y-%m-%dT%H:%M:%S")))
        except ValueError:
            pass
    try:
        return max(0.0, time.time() - os.path.getmtime(stash_file(rec["key"])))
    except OSError:
        return 0.0


def _abandoned(rec):
    """A pid-less stash that has sat past `UNOWNED_STRAND_S`.

    Deliberately NOT folded into `_alive()`. That function is THE liveness rule
    for this whole tree and there is exactly one definition of "running" on
    purpose; an age is not liveness, and answering "dead" for a record that
    simply never named an owner would make every other caller of `_alive()`
    lie. So the bound lives here, where the question being asked is the
    different one: has this been abandoned.
    """
    return not rec.get("pid") and _stash_age(rec) > UNOWNED_STRAND_S


def reconcile(path=bp.BOARD_PATH):
    """Give back every IN FLIGHT item whose owner is gone. Returns what moved.

    Run at the top of every board-watch tick. This is the guarantee that an item
    cannot sit in IN FLIGHT forever with nothing working on it: the worst case
    is one timer interval, and it costs a parse and a `/proc` stat.

    Two ways to qualify, and the second is why this is a guarantee rather than
    nearly one: an owner that is provably gone (`_alive`), or no owner at all
    for long enough that nobody is coming (`_abandoned`).
    """
    moved = []
    for rec in _stashes():
        if _alive(rec) and not _abandoned(rec):
            continue
        if rec.get("board") and os.path.abspath(rec["board"]) != os.path.abspath(path):
            continue
        title = bp.oneline(rec.get("title", rec["key"]), 120, code=True)
        # Two different things happened, so say the one that did. The pid-less
        # case never had an agent to exit, and telling him one "is gone" would
        # be inventing a death to explain a row.
        if rec.get("pid"):
            why = ("- FAILED: **the agent working %s is gone** - it exited "
                   "without finishing.\n"
                   "    It never said so; the decision is back above with your "
                   "answer intact. Nothing was committed on its behalf. "
                   "Log: `~/.cache/board-watch.log`" % title)
        else:
            why = ("- FAILED: **nothing was working %s**\n"
                   "    It was taken by a session that recorded no process, and "
                   "hours have passed with no result. The decision is back above "
                   "with your answer intact and nothing was committed on its "
                   "behalf." % title)
        try:
            give_back(rec["key"], why=why, path=path)
            moved.append(rec)
        except BoardError:
            forget(rec["key"])          # the board no longer has it either
        except Exception:
            # ONE malformed record MUST NOT wedge the sweep. This runs at the
            # top of every board-watch tick, so anything that escapes here stops
            # every answer being worked, not just this row's — which is exactly
            # what a stash missing `block` did on 2026-08-01, silently, for 8.5
            # hours. Drop the record (it is unusable by definition if it cannot
            # even be handed back) and keep going; the traceback goes to the
            # journal so the shape of the bad record is still recoverable.
            traceback.print_exc()
            forget(rec["key"])
    return moved


# ---------------------------------------------------- LANDED IS READ FROM GIT
# **The section is COMPUTED, every time it is drawn, from the commit log.**
# Nothing has to remember, nothing has to sweep, nothing has to be deployed for
# it to be current — which is the whole of his verdict on 2026-07-29, after the
# third time he found it hours stale: *"it should just read from the commit log
# of the repo itself. it shouldnt need an agent to do that"*.
#
# He was right about the shape of the bug, not just the bug. Twice the fix was
# to have SOMETHING WRITE the missing rows — `Board._catch_up` first, then
# `board-watch.py`'s tick — and both were correct code that could not reach him:
#
#   * `apps/` is live source with no hot reload, so the board window he had open
#     went on running the code from before the fix, for as long as he left it
#     open. Two correct fixes, one process that had never seen either.
#   * the watcher is a home-manager unit, so on `top` it needed a
#     `sudo rebuild-top` before the second fix existed at all on that machine.
#
# A derived view has neither failure mode, and that is the point: whichever
# build of this file is running, the answer it gives is read out of git at the
# moment of the read. There is no stamped state to be stale, so a stale writer
# cannot make it wrong.
#
# WHAT REMAINS OF THE FILE'S ROWS: a CACHE, and an override. `land --what` still
# writes a row, because the sentence an agent chose is usually better than the
# raw commit subject and there is nowhere else to keep it. A row whose hash git
# also knows supplies the What cell and nothing else; a row naming no commit at
# all (`no change`, a decision settled) is carried through verbatim, git having
# nothing to say about it. **The file is never the reason a commit does or does
# not appear.**

#: The repos LANDED is a record of. Both, because a change lands in one or the
#: other: `~/nix` is the public repo, `docs/` is the private one living inside
#: it, and he should not have to know which when he reads what happened.
#:
#: `BOARD_LANDED_REPO` replaces the pair with one repo, and NOTHING in the
#: running system sets it: it exists so a harness can point the view at a
#: throwaway git repo instead of this one's real history.
LANDED_REPO = os.path.expanduser(os.environ.get("BOARD_LANDED_REPO") or "~/nix")
LANDED_DOCS_REPO = os.path.join(LANDED_REPO, "docs")

#: Both refs, unioned. `HEAD` is what is actually on this machine and needs no
#: network at all — the old sweep read `origin/main` alone, so a commit made
#: here was invisible until a push moved the remote-tracking ref and the other
#: host's was invisible until somebody fetched. `origin/main` stays in the union
#: because the other machine's work has landed too, as soon as this one has
#: heard of it; hearing of it is `_fetch_origin` below, and it is a courtesy,
#: not a dependency.
LANDED_REFS = ("HEAD", "origin/main")

#: How far back LANDED reaches, in whole LOCAL CALENDAR days back from today —
#: so 1 is *today and yesterday*, and not a rolling 48 hours. His words,
#: 2026-07-29: LANDED is "today and yesterdays commit log". At midnight the
#: section loses the day before last; that is the intent, not drift.
#:
#: The bound is on the WHOLE section now, not only on the half derived from git:
#: an older date group in the file is dropped from the view as well. Nothing is
#: deleted — the file keeps every row it ever had, this is a view — and without
#: a bound the section grows without limit against a repo that takes ~80
#: commits a day.
LANDED_DAYS = 1

#: Ask git for at most this much. The window above is always well inside it;
#: this only bounds the cost of the call.
LANDED_LOG_LIMIT = 800

#: `git log` is asked again only when a ref has actually moved, so the view can
#: be recomputed on every repaint without shelling out on every repaint. This is
#: the floor under `landed_tips()` — the cheap question — not under the log.
LANDED_TIP_EVERY = 2.0

#: A fetch is the only thing that moves `origin/main`, and it is what decides
#: whether the OTHER host's commits are visible yet. Detached and unwaited: this
#: is called from the GUI thread and a fetch off-LAN blocks until DNS gives up.
#: Nothing waits for it — the view is already correct about this machine, and
#: gains the other one's commits whenever the ref arrives.
LANDED_FETCH_EVERY = 60

#: The docs repo commits itself every five minutes from the sync timer, ~40 a
#: day saying `sync(book): 1 doc(s)`. Those are the machinery moving the file
#: this board lives in, not work that landed, and they would bury the section.
_SYNC_SUBJECT = re.compile(r"^sync\([^)]*\)\s*:")

_LOG_FMT = "%H\x1f%ct\x1f%s"

_tip_cache = {"at": 0.0, "key": None, "tips": ""}
_log_cache = {"tips": None, "log": []}


def landed_repos():
    """The repos to read, existing ones only. One when `BOARD_LANDED_REPO` is
    set to something with no `docs/` inside it, which is every harness."""
    out = []
    for r in (LANDED_REPO, LANDED_DOCS_REPO):
        if os.path.isdir(os.path.join(r, ".git")) or os.path.isfile(
                os.path.join(r, ".git")):
            out.append(r)
    return tuple(out)


def _stamp_due(name, now, every):
    """True at most once every `every` seconds, and stamps that it said so.

    `state_dir()`, NOT `stash_dir()`: these are throttles, not items that are in
    flight, and `_stashes()` reads every `.json` under the stash dir as one.
    Parked there the fetch's stamp was drawn on his board as an unowned agent
    titled "a decision" — a card for a timestamp.
    """
    p = os.path.join(state_dir(), name)
    try:
        with open(p) as f:
            last = float(json.load(f).get("at") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        last = 0
    if now - last < every:
        return False
    try:
        with open(p, "w") as f:
            json.dump({"at": now}, f)
    except OSError:
        pass
    return True


def _fetch_origin(repos=None, now=None, every=LANDED_FETCH_EVERY, wait=False):
    """Ask git to move `origin/main`, in the background. True if asked.

    Pure freshness: the view is already complete about what is on THIS machine
    without it, and this is what eventually adds the other machine's. So it may
    fail, be throttled away or never finish, and the only consequence is that
    the other host's commits show up a little later — never that this host's do
    not show up at all, which is what the old `origin/main`-only sweep risked.

    Unwaited by default because the caller is usually the GUI thread. A repo
    with no `origin` is never dialled, so a harness repo never reaches the net.
    """
    now = time.time() if now is None else now
    if not _stamp_due("landed-fetch.json", now, every):
        return False
    asked = False
    for repo in (landed_repos() if repos is None else repos):
        try:
            p = subprocess.run(["git", "-C", repo, "config", "--get",
                                "remote.origin.url"],
                               capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        if p.returncode != 0 or not p.stdout.strip():
            continue
        cmd = ["git", "-C", repo, "fetch", "--quiet", "origin", "main"]
        try:
            if wait:
                subprocess.run(cmd, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=30)
            else:
                subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL,
                                 start_new_session=True)
            asked = True
        except (OSError, subprocess.SubprocessError):
            continue
    return asked


def landed_tips(repos=None):
    """A cheap token that changes when any watched ref moves. `""` on failure.

    This is what makes a computed section affordable: the board re-reads its
    file on every inotify event and agents write to it constantly, so the
    expensive question (`git log`) is asked only when this answer differs from
    the last one. `rev-parse` over two repos is about a millisecond.
    """
    now = time.time()
    repos = landed_repos() if repos is None else tuple(repos)
    if _tip_cache["key"] == repos and now - _tip_cache["at"] < LANDED_TIP_EVERY:
        return _tip_cache["tips"]
    out = []
    for repo in repos:
        try:
            p = subprocess.run(["git", "-C", repo, "rev-parse"] + list(LANDED_REFS),
                               capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        # `--` nothing: an unknown ref makes rev-parse exit non-zero while still
        # printing the ones it did resolve, and a repo with no `origin/main`
        # (every fresh harness repo) is the ordinary case, not a failure.
        for ln in p.stdout.split():
            if re.fullmatch(r"[0-9a-f]{40}", ln.strip()):
                out.append(ln.strip())
    _tip_cache["at"] = now
    _tip_cache["key"] = repos
    _tip_cache["tips"] = "|".join(out)
    return _tip_cache["tips"]


def _git_log(repo, refs=LANDED_REFS, limit=LANDED_LOG_LIMIT):
    """`[(full hash, committer epoch, subject)]` over the union of `refs`.

    Empty on any failure — a missing repo, git not on PATH, no ref that exists —
    because a view that cannot read git shows the file's rows, which is the
    honest answer rather than a guess.
    """
    try:
        p = subprocess.run(
            ["git", "-C", repo, "log", "--no-merges", "--format=" + _LOG_FMT,
             "-n", str(int(limit))] + list(refs) + ["--"],
            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return []
    if p.returncode != 0 and not p.stdout:
        # One of the refs does not exist here (a repo that has never fetched has
        # no `origin/main`). Ask again for each ref alone and keep what answers.
        out = []
        for ref in refs:
            out += _git_log(repo, (ref,), limit) if len(refs) > 1 else []
        return _dedupe_log(out)
    out = []
    for line in p.stdout.splitlines():
        parts = line.split("\x1f", 2)
        if len(parts) != 3:
            continue
        try:
            out.append((parts[0].lower(), int(parts[1]), parts[2].strip()))
        except ValueError:
            continue
    return out


def _dedupe_log(log):
    seen, out = set(), []
    for full, ts, subject in sorted(log, key=lambda r: -r[1]):
        if full in seen:
            continue
        seen.add(full)
        out.append((full, ts, subject))
    return out


def landed_log(repos=None, limit=LANDED_LOG_LIMIT):
    """Every commit in every watched repo, newest first, sync commits dropped.

    Cached against `landed_tips()`, so calling this on every repaint costs one
    `rev-parse` unless something actually moved.
    """
    repos = landed_repos() if repos is None else tuple(repos)
    tips = landed_tips(repos)
    key = (tips, repos, limit)
    if _log_cache["tips"] == key:
        return _log_cache["log"]
    out = []
    for repo in repos:
        for full, ts, subject in _git_log(repo, limit=limit):
            if _SYNC_SUBJECT.match(subject):
                continue
            out.append((full, ts, subject))
    out = _dedupe_log(out)
    _log_cache["tips"] = key
    _log_cache["log"] = out
    return out


def landed_commits(doc):
    """Every commit hash LANDED's cached rows already name, lowercased.

    They are SHORT hashes in the file, so matching is by prefix against a full
    one. A row with no commit (`no change`) contributes nothing.
    """
    out = []
    for grp in doc.get("landed") or []:
        for row in grp.get("rows") or []:
            c = (row.get("commit") or "").strip().strip("`").lower()
            if re.fullmatch(r"[0-9a-f]{4,40}", c):
                out.append(c)
    return out


def _local(ts):
    return datetime.datetime.fromtimestamp(ts)


def landed_when(ts):
    """A commit's own local time in LANDED's form — `1:28 am`. Same clock
    `commit_time()` writes, derived from the epoch we already have rather than
    by asking git a second time per commit."""
    return _local(ts).strftime("%I:%M %p").lstrip("0").lower()


def landed_view(doc, repos=None, now=None, days=LANDED_DAYS, log=None,
                fetch=True):
    """**LANDED as it should be DRAWN** — the file's rows, plus every commit git
    knows about that none of them names. Newest date group first.

    The same shape `bp.parse()` puts in `doc["landed"]`, so nothing downstream
    of it changes: a list of `{"date", "rows", "prose"}` with rows of
    `{"commit", "what", "when"}`. It is a pure read — it writes nothing, takes
    no lock, and can be called as often as the view is drawn.

    Three rules decide what it contains:

      * **A cached row wins on WORDING, never on existence.** If the file names
        a hash, its What cell is used (that is the sentence `land --what`
        chose); the commit is in the section either way.
      * **A row naming no commit is carried through verbatim** — `no change`, a
        decision settled, a hand-written line. Git has nothing to say about it
        and nothing here may drop it.
      * **It is TODAY AND YESTERDAY, by local calendar date** (`days`, 1).
        Older date groups are cut from the view, cached rows included — the
        file keeps them, this is only what is drawn. That bound is what keeps a
        repo at eighty commits a day from turning the section into the whole
        log.

    And rows come back **NEWEST FIRST, within a day as well as across days**,
    which is what the section's own standing line has always claimed. It read
    oldest-first inside a day until 2026-07-29, so the top of the section — all
    he can see without scrolling — was the FIRST commit of the day, and eleven
    hours and eighty-seven newer rows sat underneath it. He read that as the
    section being stale again, and he was reading it correctly: the newest thing
    it showed him was from 12:16 am.
    """
    now = time.time() if now is None else now
    if fetch:
        _fetch_origin(repos, now=now)
    log = landed_log(repos) if log is None else log

    when_of = {full: ts for full, ts, _s in log}

    def timed(rows):
        """Every cached row with the commit time git gives its hash, and a row
        git cannot time carried at its predecessor's — so it keeps its written
        position instead of falling to the top of the group. Without this a
        commit an agent DID `land` sorted above a newer one it did not, the
        cached half being appended in a different pass from the computed one."""
        out, last = [], 0
        for row in rows:
            c = (row.get("commit") or "").strip().strip("`").lower()
            ts = next((t for f, t in when_of.items() if f.startswith(c)), None) \
                if re.fullmatch(r"[0-9a-f]{4,40}", c) else None
            last = last if ts is None else ts
            out.append((last, dict(row)))
        return out

    groups = [dict(g) for g in (doc.get("landed") or [])]
    for g in groups:
        g["rows"] = timed(g.get("rows") or [])
        g["prose"] = list(g.get("prose") or [])
    by_date = {g.get("date", "").strip(): g for g in groups}
    have = landed_commits(doc)

    # LOCAL calendar dates, both sides: the floor is a date subtraction, never
    # `now - days*86400`, so "yesterday" means yesterday however long ago
    # midnight was. A group with a date this cannot read is kept — the cut is
    # only ever applied to a date we can prove is old.
    floor = (_local(now).date() - datetime.timedelta(days=days)).isoformat()
    groups = [g for g in groups
              if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", g.get("date", "").strip())
              or g.get("date", "").strip() >= floor]
    by_date = {g.get("date", "").strip(): g for g in groups}

    fresh = []
    for full, ts, subject in log:
        date = _local(ts).date().isoformat()
        if date < floor:
            continue
        if any(full.startswith(h) for h in have):
            continue
        fresh.append({"commit": full[:7], "what": bp.text(bp.cell(subject)),
                      "when": landed_when(ts), "date": date, "ts": ts})
    fresh.sort(key=lambda r: r["ts"])

    for r in fresh:
        g = by_date.get(r["date"])
        if g is None:
            g = {"date": r["date"], "rows": [], "prose": [], "line": -1}
            by_date[r["date"]] = g
            groups.append(g)
        g["rows"].append((r["ts"], {"commit": r["commit"], "what": r["what"],
                                    "when": r["when"], "line": -1}))

    # NEWEST FIRST, within a day exactly as across days — "Newest first." is the
    # section's own standing line and it was only ever true of the date groups.
    # Inside a day it read oldest-first, so the top of the section was the first
    # commit of the day and the newest was eighty rows below the fold: he read
    # the section as stale, correctly. A stable sort, so two rows sharing a
    # second keep the order they were written in.
    for g in groups:
        g["rows"].sort(key=lambda tr: -tr[0])
        g["rows"] = [row for _ts, row in g["rows"]]
    groups.sort(key=lambda g: g.get("date", ""), reverse=True)
    return groups


def status(path=bp.BOARD_PATH):
    """What is asked of him, and what this host has taken off him and is on."""
    doc = bp.parse(bp.read(path))
    return {"needs": doc["needs"], "stashed": _stashes()}
