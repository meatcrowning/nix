"""Moving a board item as work starts, lands, or dies — the policy half.

`boardparse` owns the line edits; this owns WHEN they are made and WHAT the
moved row says. Two callers, one implementation on purpose:

  * `home/srvs/board-watch-files/board-watch.py` — moves the decision as it
    spawns its agent, and hands it back if that agent dies.
  * `tools/boardctl.py` — the same moves for a human, or for an orchestrating
    session that dispatched an agent itself. Work is not only started by the
    watcher, and the answer to "how do I move this" must never be "hand-edit the
    markdown".

WHAT A MOVED ITEM SAYS, and what it deliberately does not
---------------------------------------------------------
The IN FLIGHT row is `| what | where | notes |`, drawn as the title with the
location dim on the right and the note wrapped underneath. A moved decision
fills them with the title, where the work is happening, and **his own answer
read back to him** — the ticked option, his sentence, or both.

His answer is there for three reasons and none of them is decoration: it is the
one thing in the item he wrote, it lets him catch a misread answer while the
work is still cheap to redirect, and LANDED will not carry it.

There is **no timestamp, no age, no "started at", nothing counting**. §"The
no-pressure requirement is a design constraint" in `AGENTS.md`: he asked for
this board because a running log made him feel he had to act in the moment. A
start time on a row is an elapsed time the moment he reads it. The stash below
records one, because reconciliation is machine business; it never reaches the
file.

STRANDING, and why an item cannot
---------------------------------
An item in IN FLIGHT with nothing working on it is worse than one still in NEEDS
YOU: it says "handled" and nothing is. So `start()` STASHES the decision's raw
lines outside the store, and there are four ways back:

  1. the agent finished       -> `land()`, and the stash is dropped
  2. the agent exited badly   -> `give_back()` from the watcher, same run: the
                                 block goes back into NEEDS YOU byte-for-byte
                                 and a bullet in WAITING ON YOU TO DO says so
  3. the whole watcher died   -> `reconcile()`, run at the top of every
                                 board-watch tick (so, within five minutes),
                                 finds stashes whose owning process is gone and
                                 does 2 for them
  4. there is no stash at all -> `stall()`, by hand. The row becomes one bullet
                                 in WAITING ON YOU TO DO

Case 3 checks the pid AND its kernel start time, so a recycled pid cannot make a
dead agent look alive. A stash with no owner pid (an interactive session started
it) is never reclaimed automatically — nothing here can tell whether that
session is still thinking.

**Case 4 is the one the first three do not cover, and it is bigger than it
sounds.** 1-3 are all keyed on the stash, and the stash is MACHINE-LOCAL state
while `board.md` syncs between the two machines — so from `book`, a row `top`
started is indistinguishable from a row nobody started, and vice versa. Add the
rows written before the stash existed and the rows added by hand, and the honest
statement is: **`reconcile()` covers only what this host started, and everything
else in IN FLIGHT can never leave it.** That is what he was looking at when he
said the section *"doesnt update at all"* — five rows, four of which no
mechanism here could remove. `unowned()` reports them and `stall()` is their
exit; neither is automatic, because a row this host does not own may be alive on
the other one.
"""
import datetime
import json
import os
import re
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(os.path.dirname(HERE), "pylib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import boardparse as bp                                            # noqa: E402
from boardparse import BoardError                                  # noqa: E402,F401


def state_dir():
    """Where this app keeps its own bookkeeping. NOT `stash_dir()`: every
    `.json` in there is read back as an in-flight item (see `_stashes`), so a
    file that is not one belongs here instead."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    d = os.path.join(base, "board")
    os.makedirs(d, exist_ok=True)
    return d


def stash_dir():
    d = os.path.join(state_dir(), "inflight")
    os.makedirs(d, exist_ok=True)
    return d


def stash_file(key):
    return os.path.join(stash_dir(), re.sub(r"[^a-z0-9-]", "_", key) + ".json")


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


def _where(s):
    """The `where` column is a code location and the store spells those in
    backticks. Callers pass a bare path far more often than not, so add them
    rather than let the section grow two conventions."""
    s = (s or "").strip()
    if s and "`" not in s and " " not in s and re.search(r"[/.]", s):
        return "`%s`" % s
    return s


def _norm(s):
    """Compare a selector to what is drawn. The parsed cells are glyph-mapped
    and the stashed title is raw, so both sides go through the same map before
    they are matched — otherwise an em dash in a title makes the row it names
    unfindable."""
    return " ".join(bp.text(s or "").lower().split())


def find_flight(doc, sel):
    """A row in IN FLIGHT, by a bit of its `what` (or its `where`)."""
    low = _norm(sel)
    hits = [r for r in doc["flight"]
            if low and (low in _norm(r["what"]) or low == _norm(r["where"]))]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise BoardError("'%s' matches %d rows in IN FLIGHT: %s"
                         % (sel, len(hits), "; ".join(h["what"] for h in hits)))
    raise BoardError("no row in IN FLIGHT matches '%s'" % sel)


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
          force=False, session=""):
    """NEEDS YOU -> IN FLIGHT, keeping his answer on the row and his words in
    the stash. Returns the stash record."""
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
        row = bp.flight_row(title, _where(where), note)
        rec.update({"key": item["key"], "num": item["num"], "title": title,
                    "where": where, "row": row, "block": block,
                    # the heading it sat above, so a hand-back is byte-exact
                    "before": after if after.startswith("###") else "",
                    "pid": pid, "pidStart": _proc_start(pid) if pid else None,
                    # The agent's `--session-id`, so its card can say what it is
                    # actually doing and not only that it is alive
                    # (`boardphase.py`). Empty for a hand-started item.
                    "session": session or "",
                    "host": socket.gethostname(),
                    "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "board": os.path.abspath(path)})
        return bp.add_flight_row(lines, row)

    if not bp.edit(path, go):
        raise BoardError("nothing was written")
    # The stash is written AFTER the move, not before: a stash for an item still
    # sitting in NEEDS YOU would be reclaimed into a duplicate of itself.
    with open(stash_file(rec["key"]), "w") as f:
        json.dump(rec, f, indent=1, sort_keys=True)
    return rec


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
    """IN FLIGHT -> LANDED, under today's date, carrying the commit and its time.

    **The IN FLIGHT row is optional, and that is the whole point of the
    section.** A decision agent has a row (`start()` made one); a WORKER
    dispatched out of the box never did, and for a day that meant every commit
    the fan-out produced was invisible here — `land` needed a row it could not
    have, so a worker could only leave a bullet and LANDED silently stopped
    growing while the repo did not. So: a selector that matches a row moves it,
    and no selector (or one that matches nothing) simply records the commit.
    `what` is then required, because there is no row to take it from.

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
    rec = _stash_for(sel) if sel else None
    row_sel = rec["title"] if rec else sel
    when = commit_time(commit) if when is None else when

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
        row = None
        if row_sel:
            try:
                row = find_flight(doc, row_sel)
            except BoardError:
                if not what:
                    raise BoardError(
                        "nothing in IN FLIGHT matches '%s' and no --what was "
                        "given - there is no line to record" % sel)
        lines = doc["lines"]
        if row is None and not what:
            raise BoardError(
                "nothing in IN FLIGHT matches '%s' and no --what was given - "
                "there is no line to record" % sel)
        said = what or row["what"]
        # The upgrade goes FIRST and replaces exactly one line, so the IN FLIGHT
        # row's index — measured on this same doc, and above LANDED — is still
        # the line it was.
        have = existing(doc)
        if have is not None:
            new = bp.landed_row(have["commit"], said, have["when"] or when)
            lines = lines[:have["line"]] + [new] + lines[have["line"] + 1:]
        if row is not None:
            got.update(row)
            lines = bp.remove_row(lines, row["line"])
        if have is not None:
            upgraded.append(True)
            return lines
        return bp.add_landed_row(lines, commit, said, date, when)

    # A `land` that re-states a row already reading exactly that way writes
    # nothing, and that is a SUCCESS: `bp.edit` returns False for "the bytes
    # would not change", which here means the record is already right.
    if not bp.edit(path, go) and not upgraded:
        raise BoardError("nothing was written")
    if sel:
        forget(sel)
    if got.get("what"):
        forget_by_title(got["what"])
    return got


def give_back(sel, why=None, path=bp.BOARD_PATH):
    """IN FLIGHT -> NEEDS YOU, verbatim, plus a bullet saying why.

    One edit, not three: the row must never be gone while the decision is not
    yet back, because that state syncs to book and reads as work he never asked
    for having silently vanished.
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

    def go(doc):
        lines = doc["lines"]
        try:
            row = find_flight(doc, rec["title"])
            lines = bp.remove_row(lines, row["line"])
        except BoardError:
            pass                  # already gone: still put the decision back
        lines = bp.add_needs_item(lines, rec["block"], rec.get("before"))
        if why:
            b = why.strip()
            lines = bp.add_todo_bullet(lines, bp.parse("".join(lines)),
                                       b if b.startswith("- ") else "- " + b)
        return lines

    bp.edit(path, go)
    forget(rec["key"])
    return rec


def unowned(path=bp.BOARD_PATH):
    """The IN FLIGHT rows no stash on THIS host accounts for.

    These are the rows `reconcile()` structurally cannot see, and there are more
    of them than the design assumed: every row written before the stash existed,
    every row an agent on the other machine started (the stash is machine-local
    state and `board.md` is not), and every row somebody added by hand. Nothing
    ages them out, so the section only ever grew — his words, reading it:
    *"it just seems like that section doesnt update at all its still got old
    stuff in it"*.

    It is a REPORT and not a rule. A row unowned here may be perfectly alive on
    the other machine, so nothing acts on this list automatically; `stall()`
    below is the manual exit, and `boardctl reconcile` prints it so the next
    thing to look at the board can see what has silted up.

    It lists **every** table under `## IN FLIGHT`, the store's `**Queued**` one
    included — `parse` has no case for a second table there and never has, so
    `find_flight` and `land` see those rows too. A queued row is unowned by
    design and is not something to stall; read the list, do not sweep it.
    """
    doc = bp.parse(bp.read(path))
    owned = {_norm(r.get("title")) for r in _stashes()}
    return [r for r in doc["flight"] if _norm(r["what"]) not in owned]


def stall(sel, path=bp.BOARD_PATH):
    """IN FLIGHT -> a bullet in WAITING ON YOU TO DO. The fourth way out.

    `land` needs a commit, `back` needs the stash it cannot have, and until this
    existed a row with no stash had no exit at all: the only way to remove one
    was to hand-edit the store, which nothing here is allowed to do. So a row
    that has outlived whatever was working on it sat there claiming to be
    handled, forever.

    **It moves the row, it does not delete it.** The three cells become one
    bullet under WAITING ON YOU TO DO — restarting it is his call, and a row
    quietly vanishing off the board would be the worse of the two failures. One
    edit, so the row is never gone while the bullet is not yet there.

    It REFUSES a row that a stash owns: that decision's own text is recoverable,
    so `give_back` is the honest move for it and would put his question back
    rather than flatten it into a to-do.
    """
    got = {}

    def go(doc):
        row = find_flight(doc, sel)
        titles = {_norm(r.get("title")) for r in _stashes()}
        if _norm(row["what"]) in titles or _stash_for(sel):
            raise BoardError(
                "'%s' is a decision this machine stashed - use `back` (which "
                "returns your question intact) or `land`" % row["what"])
        got.update(row)
        # The cells AS THEY ARE SPELLED IN THE FILE. `row["what"]` has been
        # through `text()` at ingest and putting that back would rewrite his
        # em dashes and backticks into ASCII, one move at a time — the same
        # trap `raw_title` exists for.
        cells = bp._table_cells(doc["lines"][row["line"]].rstrip("\n"))
        cells += [""] * (3 - len(cells))
        what, where, notes = (c.strip() for c in cells[:3])
        lines = bp.remove_row(doc["lines"], row["line"])
        # INFORMATION: the row moved and nothing was lost. It is not a FAILED —
        # nothing was attempted and dropped here; a row this host cannot account
        # for may well have finished on the other machine.
        return bp.add_todo_bullet(lines, bp.parse("".join(lines)),
                                  "- INFORMATION: **%s** - was sitting in IN FLIGHT with "
                                  "nothing working on it%s, so it is here "
                                  "instead of claiming to be handled.%s"
                                  % (what, (" (%s)" % where) if where else "",
                                     (" " + notes) if notes else ""))

    if not bp.edit(path, go):
        raise BoardError("nothing was written")
    return got


def ask(question, context=None, options=None, if_unanswered=None, asked_by=None,
        path=bp.BOARD_PATH):
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
        block = ["### %s\n" % title, bp.placed_now(), "\n"]
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


def note(text, path=bp.BOARD_PATH):
    """One bullet into WAITING ON YOU TO DO.

    It must start with one of `boardparse.TODO_TAGS` — `QUESTION:`,
    `INFORMATION:`, `COMPLETION:`, `PARTIAL:`, `FAILED:` — then a short
    description, then whatever background it needs. `add_todo_bullet` refuses an
    untagged one and this deliberately does not paper over that with a default:
    the writer knows which of the five it is and nothing downstream can work it
    out afterwards.

    The `- ` is added PER LINE, not once for the whole string. The orchestrator
    writes one line per task in one call, and prefixing only the first left the
    second as a bare paragraph glued onto the bullet above it — which is how
    *"**default handlers for every app we wrote** - handed to Sam"* came to be
    drawn as part of somebody else's message on 2026-07-29. An INDENTED line is
    a wrapped continuation and is left alone.
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
    return bp.edit(path, lambda doc: bp.add_todo_bullet(doc["lines"], doc, body))


def forget(key):
    try:
        os.unlink(stash_file(key))
        return True
    except OSError:
        return False


def forget_by_title(title):
    low = _norm(title)
    for r in _stashes():
        if low and _norm(r.get("title")) == low:
            forget(r["key"])


def reconcile(path=bp.BOARD_PATH):
    """Give back every IN FLIGHT item whose owner is gone. Returns what moved.

    Run at the top of every board-watch tick. This is the guarantee that an item
    cannot sit in IN FLIGHT forever with nothing working on it: the worst case
    is one timer interval, and it costs a parse and a `/proc` stat.
    """
    moved = []
    for rec in _stashes():
        if _alive(rec):
            continue
        if rec.get("board") and os.path.abspath(rec["board"]) != os.path.abspath(path):
            continue
        try:
            give_back(rec["key"], why=(
                "- FAILED: **the agent working \"%s\" is gone** - it exited without "
                "finishing or saying so, so the decision is back above with "
                "your answer intact. Nothing was committed on its behalf. "
                "Log: `~/.cache/board-watch.log`" % rec.get("title", rec["key"])),
                path=path)
            moved.append(rec)
        except BoardError:
            forget(rec["key"])          # the board no longer has it either
    return moved


# ------------------------------------------------- LANDED catches up by itself
# `land()` is a thing a worker has to REMEMBER, and the record of what reached
# his machine cannot rest on that. It already failed twice the same way: a
# worker that lands a commit under a pathspec and never comes back, one that is
# killed mid-run, one that simply is not told. He read the section on 2026-07-29
# and said *"the landed page it still is stuck with commits from an hour ago"* —
# three commits were on `origin/main` and none of them was in the file.
#
# So the section reconciles against git the same way IN FLIGHT reconciles
# against `/proc`: whatever is on `origin/main` and not in LANDED is a hole, and
# a hole gets filled. Append-only, in commit order, never a rewrite.

#: The repo LANDED is a record of. `docs/` is deliberately NOT swept: its
#: history is mostly the 5-minute sync timer's own commits, and a sweep over it
#: would bury his board in them. A docs commit worth recording is recorded by
#: hand, with `land`, exactly as it always was.
LANDED_REPO = os.path.expanduser("~/nix")

#: How far back the sweep may reach: never before the OLDEST commit LANDED
#: already names. Everything earlier predates the board and was never meant to
#: be in it — a fixed window would have appended 96 rows of history the first
#: time it ran. An empty LANDED has no floor and so sweeps nothing, which is the
#: safe answer rather than the whole repo.

#: A commit is left alone until it is this old — one sweep tick, no more. His
#: words: *"why is the wait time so absurdly high? it should just notice when a
#: new commit is added and append it to the list"*. It used to be 10 minutes,
#: bought as a courtesy to the worker that made the commit and is usually still
#: running and about to `land` it with its own better sentence; if the sweep got
#: there first, `land` wrote nothing at all. **That courtesy is bought a
#: different way now: `land` UPGRADES a sweep-written row's What cell in place**
#: (one targeted line edit, see `land`), so losing the race costs the agent's
#: sentence nothing and there is no reason left to wait ten minutes for it. What
#: this minute still buys is the ordinary case looking tidy — the worker's own
#: sentence usually arrives first and no row is ever rewritten.
LANDED_MIN_AGE = 60

#: `git log origin/main` reads a REMOTE-TRACKING ref, and nothing moves that ref
#: but a fetch. Pushing from this machine moves it as a side effect, so the
#: sweep saw this host's own commits and was blind to the other host's for as
#: long as nobody happened to pull — which on a freshly booted machine is
#: forever. So the sweep fetches, on EVERY tick: it is one detached process and
#: it is what decides whether the other host's commit is visible at all, so
#: throttling it to ten times the sweep's own period only ever bought a ten
#: minute hole. DETACHED and unwaited still, because `_catch_up` runs on the GUI
#: thread and a fetch off-LAN blocks until DNS gives up; the ref it lands is
#: read by the NEXT sweep, one tick later.
LANDED_FETCH_EVERY = 60

#: Don't shell out to git on every repaint. The board app refreshes on every
#: inotify event on the file, and agents write to it constantly — but its own
#: `_catch_up` timer is 60 s, so this is the floor that matters and a commit
#: shows up about two ticks after it is pushed (one to fetch, one to read).
LANDED_SWEEP_EVERY = 60

#: ...and `board.md` SYNCS between the machines, so both hosts can be looking at
#: the same hole at the same second with no lock between them. There WAS a
#: stagger here — `top` after 10 minutes, any other host after 20, the docs
#: sync's round trip — and it is gone, because it was 20 minutes of waiting to
#: prevent a duplicate row rather than 20 lines of code to remove one. **The
#: sweep now HEALS a duplicate instead of avoiding it**: it already reads every
#: hash in the section, so a second row for a hash the section already names is
#: dropped, ONE line edit, provided the row it drops says only what the sweep
#: itself would have written (`landed_duplicates`). That is the whole of the
#: cross-host answer, and it is strictly better than the stagger was: the
#: stagger only made the race unlikely, and a duplicate that did get through
#: stayed on his board for good.
#:
#: What it deliberately does NOT do is dedupe two DIFFERENT sentences for one
#: hash. Deleting a line a person or an agent wrote is not this function's to
#: do — union-merged prose is the one case a human should look at — so those
#: are left alone and only the mechanical repeat goes.
LANDED_HEAL_DUPLICATES = True

#: How much history to ask git for. The floor above is always inside this on any
#: board that is being used; it only bounds the cost of the call.
LANDED_LOG_LIMIT = 500

_LOG_FMT = "%H\x1f%ct\x1f%s"


def _stamp_due(name, now, every):
    """True at most once every `every` seconds, and stamps that it said so.

    `state_dir()`, NOT `stash_dir()`: these are throttles, not items that are in
    flight, and `_stashes()` reads every `.json` under the stash dir as one.
    Parked there the sweep's stamp was drawn on his board as an unowned agent
    titled "a decision" — a card for a timestamp — on any machine where the
    sweep had ever run.
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


def _sweep_stamp():
    return os.path.join(state_dir(), "landed-sweep.json")


def _sweep_due(now, every=LANDED_SWEEP_EVERY):
    return _stamp_due("landed-sweep.json", now, every)


def _fetch_origin(repo=LANDED_REPO, now=None, every=LANDED_FETCH_EVERY):
    """Ask git to move `origin/main`, and DO NOT WAIT for it. True if asked.

    The sweep reads a remote-tracking ref, and nothing moves one but a fetch.
    A push from this machine moves it as a side effect, so the sweep could see
    this host's own commits and was blind to the other host's until somebody
    happened to pull — on a freshly booted machine, never.

    Unwaited because `Board._catch_up` calls this on the GUI thread and a fetch
    off-LAN blocks until DNS gives up; `book` is off-LAN often. The ref it lands
    is read by the NEXT sweep, one tick later — which is why the throttle is the
    sweep's own period and not ten times it: this call is the only thing that
    decides whether the other host's commit is visible, so every tick it skips
    is a tick the hole stays. A repo with no `origin` is left alone entirely, so
    a test repo never reaches the network.
    """
    now = time.time() if now is None else now
    try:
        p = subprocess.run(["git", "-C", repo, "config", "--get",
                            "remote.origin.url"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    if p.returncode != 0 or not p.stdout.strip():
        return False
    if not _stamp_due("landed-fetch.json", now, every):
        return False
    try:
        subprocess.Popen(["git", "-C", repo, "fetch", "--quiet", "origin", "main"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def _git_log(repo=LANDED_REPO, ref="origin/main", limit=LANDED_LOG_LIMIT):
    """`[(full hash, committer epoch, subject)]`, newest first. Empty on any
    failure — a missing repo, no `origin/main`, git not on PATH — because a
    sweep that cannot read git must do nothing, not guess."""
    try:
        p = subprocess.run(
            ["git", "-C", repo, "log", ref, "--no-merges",
             "--format=" + _LOG_FMT, "-n", str(int(limit))],
            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return []
    if p.returncode != 0:
        return []
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


def landed_commits(doc):
    """Every commit hash LANDED already names, lowercased and unfenced.

    They are SHORT hashes in the file, so matching is by prefix against a full
    one. A row with no commit (`no change`, a decision settled) contributes
    nothing.
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
    `commit_time()` writes, derived here from the epoch we already have rather
    than by asking git a second time per commit."""
    return _local(ts).strftime("%I:%M %p").lstrip("0").lower()


def landed_subjects(log):
    """`{full hash: the What cell the sweep would write for it}`.

    Through `bp.cell` and back through `bp.text`, because that is what the
    subject looks like once it has been a row: comparing a raw `git log`
    subject against a parsed cell would read a round trip as a difference and
    call an ordinary sweep row somebody's sentence.
    """
    return {full: bp.text(bp.cell(subject)) for full, _ts, subject in log}


def landed_duplicates(doc, log):
    """Line indices of LANDED rows that repeat a hash the section already names
    AND say nothing that would be lost. Oldest-first order, safe to remove.

    This is the whole of the cross-host answer (see `LANDED_HEAL_DUPLICATES`):
    two hosts sweeping the same hole with no lock between them used to be
    prevented by making the second one wait twenty minutes, and is now simply
    undone. One row per hash survives, and it is chosen so that the surviving
    row is the one carrying the most:

      * a repeat whose What is exactly the commit SUBJECT is a sweep row and
        goes — the sweep can write it again from git any time;
      * a repeat identical to the row above it goes, for the same reason;
      * if the FIRST row is the sweep row and the later one is not, the first
        one goes instead and the sentence somebody chose stays.

    Two different sentences for one hash are left alone, both of them. Nothing
    here may delete a line a person wrote, and that case is a union merge of
    two people's prose — the one thing a human should look at.
    """
    subjects = landed_subjects(log)
    seen = {}
    drop = []
    for grp in doc.get("landed") or []:
        for row in grp.get("rows") or []:
            c = (row.get("commit") or "").strip().strip("`").lower()
            if not re.fullmatch(r"[0-9a-f]{4,40}", c):
                continue
            full = next((f for f in subjects
                         if f.startswith(c) or c.startswith(f)), None)
            key = full or c
            first = seen.get(key)
            if first is None:
                seen[key] = row
                continue
            subj = subjects.get(full)
            if row["what"] == first["what"] or (subj and row["what"] == subj):
                drop.append(row["line"])
            elif subj and first["what"] == subj:
                drop.append(first["line"])
                seen[key] = row
    return sorted(drop)


def landed_missing(path=bp.BOARD_PATH, repo=LANDED_REPO, min_age=None, now=None,
                   log=None):
    """What is on `origin/main` and not in LANDED. Oldest first, ready to append.

    Three bounds, and each one exists to stop this doing something he did not
    ask for:

      * the FLOOR — nothing older than the oldest commit LANDED already names.
      * the AGE — nothing younger than `min_age`, so a live worker gets to
        record its own commit first. One tick now, not ten minutes: `land`
        upgrades a row the sweep beat it to, so the wait no longer has to cover
        the worker's whole run.
      * the DATE — a commit only joins a `### <date>` group that already exists,
        or opens a new one if its date is newer than every group there. Never
        one wedged in the middle: LANDED is newest-group-first and this must not
        invent that structure from a commit's date.

    There is no longer a per-host bound. `log` is the `_git_log()` the caller
    already took, so one sweep shells out to git once.
    """
    now = time.time() if now is None else now
    if min_age is None:
        min_age = LANDED_MIN_AGE
    doc = bp.parse(bp.read(path))
    log = _git_log(repo) if log is None else log
    if not log:
        return []
    have = landed_commits(doc)
    if not have:
        return []

    def recorded(full):
        return any(full.startswith(h) for h in have)

    floor = min((ts for full, ts, _s in log if recorded(full)), default=None)
    if floor is None:
        return []                    # LANDED names nothing this repo knows

    dates = [g.get("date", "").strip() for g in doc.get("landed") or []]
    dates = [d for d in dates if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)]
    newest = max(dates) if dates else ""

    out = []
    for full, ts, subject in log:
        if ts <= floor or ts > now - min_age or recorded(full):
            continue
        date = _local(ts).date().isoformat()
        if dates and date not in dates and date < newest:
            continue
        out.append({"commit": full[:7], "what": subject, "date": date,
                    "when": landed_when(ts), "ts": ts})
    out.sort(key=lambda r: r["ts"])
    return out


def reconcile_landed(path=bp.BOARD_PATH, repo=LANDED_REPO, min_age=None,
                     now=None, force=False, fetch=True):
    """Append every missing commit to LANDED, and heal any duplicate row it
    finds on the way. Returns the rows it APPENDED (a heal is silent).

    Idempotent by construction: the second run finds those hashes in the file
    and has nothing to do, and the row it removed is not there to remove twice.
    One `bp.edit`, so the whole catch-up is one atomic write under the same lock
    every other writer takes, and a run with nothing to do does not write at
    all. Removals go FIRST and in descending line order, so no removal moves the
    line another one was measured against; the appends after them re-find their
    group in the mutated lines, as they always did.

    What there is to do is decided TWICE — once out here, to know whether to
    open the file for writing at all, and again inside `go`, against the very
    doc it is writing into. `bp.edit` re-runs `go` on a fresh read whenever the
    file moved under it, and that is exactly the moment a worker's own `land`
    lands: without the second check the retry appended a row that had just
    appeared, which is the one duplicate this must never create.
    """
    now = time.time() if now is None else now
    if not force and not _sweep_due(now):
        return []
    if fetch:
        _fetch_origin(repo, now=now)
    log = _git_log(repo)
    rows = landed_missing(path=path, repo=repo, min_age=min_age, now=now, log=log)

    def dups(doc):
        return landed_duplicates(doc, log) if LANDED_HEAL_DUPLICATES else []

    if not rows and not dups(bp.parse(bp.read(path))):
        return []
    wrote = []

    def go(doc):
        del wrote[:]
        lines = doc["lines"]
        for i in sorted(dups(doc), reverse=True):
            lines = bp.remove_row(lines, i)
        have = landed_commits(doc)
        for r in rows:
            c = r["commit"]
            if any(c.startswith(h) or h.startswith(c) for h in have):
                continue
            lines = bp.add_landed_row(lines, c, r["what"], r["date"], r["when"])
            wrote.append(r)
        return lines if lines is not doc["lines"] else None

    if not bp.edit(path, go):
        return []
    return list(wrote)


def status(path=bp.BOARD_PATH):
    doc = bp.parse(bp.read(path))
    owned = {_norm(r.get("title")): r for r in _stashes()}
    return {"needs": doc["needs"], "flight": doc["flight"], "stashed": owned}
