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
lines outside the store, and there are three ways back:

  1. the agent finished       -> `land()`, and the stash is dropped
  2. the agent exited badly   -> `give_back()` from the watcher, same run: the
                                 block goes back into NEEDS YOU byte-for-byte
                                 and a bullet in WAITING ON YOU TO DO says so
  3. the whole watcher died   -> `reconcile()`, run at the top of every
                                 board-watch tick (so, within five minutes),
                                 finds stashes whose owning process is gone and
                                 does 2 for them

Case 3 checks the pid AND its kernel start time, so a recycled pid cannot make a
dead agent look alive. A stash with no owner pid (an interactive session started
it) is never reclaimed automatically — nothing here can tell whether that
session is still thinking.
"""
import json
import os
import re
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(os.path.dirname(HERE), "pylib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import boardparse as bp                                            # noqa: E402
from boardparse import BoardError                                  # noqa: E402,F401


def stash_dir():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    d = os.path.join(base, "board", "inflight")
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
                out.append(json.load(f))
        except (OSError, ValueError):
            continue
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


def land(sel, commit, what=None, date=None, path=bp.BOARD_PATH):
    """IN FLIGHT -> LANDED, under today's date, carrying the commit."""
    got = {}
    rec = _stash_for(sel)
    row_sel = rec["title"] if rec else sel

    def go(doc):
        row = find_flight(doc, row_sel)
        got.update(row)
        lines = bp.remove_row(doc["lines"], row["line"])
        return bp.add_landed_row(lines, commit, what or row["what"], date)

    if not bp.edit(path, go):
        raise BoardError("nothing was written")
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
        block = ["### %s\n" % title, "\n"]
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


def note(text, path=bp.BOARD_PATH):
    """One bullet into WAITING ON YOU TO DO."""
    if not text.strip():
        return False
    body = text.strip()
    return bp.edit(path, lambda doc: bp.add_todo_bullet(
        doc["lines"], doc, body if body.startswith("- ") else "- " + body))


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
                "- **the agent working \"%s\" is gone** - it exited without "
                "finishing or saying so, so the decision is back above with "
                "your answer intact. Nothing was committed on its behalf. "
                "Log: `~/.cache/board-watch.log`" % rec.get("title", rec["key"])),
                path=path)
            moved.append(rec)
        except BoardError:
            forget(rec["key"])          # the board no longer has it either
    return moved


def status(path=bp.BOARD_PATH):
    doc = bp.parse(bp.read(path))
    owned = {_norm(r.get("title")): r for r in _stashes()}
    return {"needs": doc["needs"], "flight": doc["flight"], "stashed": owned}
