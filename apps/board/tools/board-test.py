#!/usr/bin/env python3
"""board's regression harness — offscreen, no window on anyone's screen.

Four layers, in the order a failure is cheapest to read:

  1. THE ROUND TRIP (pure Python, and the reason this file exists). His store is
     a markdown file he also edits by hand, so the contract is byte-level:
     parse -> write back with no change -> **the file is identical**; tick one
     box -> **exactly one line differs**, and it differs only inside its `[ ]`.
     Clearing an answer that was never given must also leave the file untouched,
     because the store ships `> ` with a trailing space.
  2. WHO IS RUNNING, AND THE BOX (`boardagents.py`). A running agent, a dead
     one and a hand-moved one are told apart by `boardmove`'s liveness rule and
     by nothing else. The box's claim is not "the message was sent" — an
     agent's stdin is closed — but that **a message he typed is never lost**, so
     every check is a CONSERVATION check: after each path it is on disk exactly
     once, in exactly one of `to/`, `queue/`, `taken/`.
  3. THE PARSE against the real `~/nix/docs/board.md`, so a change to the file's
     shape shows up here rather than as an empty section on screen.
  4. THE WINDOW: the real `qml/Main.qml` under QT_QPA_PLATFORM=offscreen, plus
     `grabWindow()` PNGs of the states worth looking at — everything populated,
     a decision with a chosen option and a typed answer, an EMPTY `NEEDS YOU`
     and an EMPTY agents section, which are the two states he will see most
     often, and the agents section with a running agent and a failed one in it.

Run it with board's own Qt env, not the bare system python:

    W=$(readlink -f "$(which board)"); sed '$d' "$W" > /tmp/brdenv.sh
    ( . /tmp/brdenv.sh; "$(tail -1 "$W" | grep -o '/nix/store/[^"]*/bin/python3')" \\
        apps/board/tools/board-test.py --shots /tmp/board-shots )

`XDG_STATE_HOME` is redirected into a scratch dir — a harness here must never
rewrite where the user's own app reopens — and every write test runs against a
COPY of the store in that scratch dir. This harness never writes board.md.
"""
import json
import os
import re
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"

BOARD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS = os.path.dirname(BOARD)
sys.path.insert(0, BOARD)
sys.path.insert(0, os.path.join(APPS, "pylib"))

FAILS = []
SHOTS = None


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def prop(obj, name):
    """A QML `property var` reaches PySide as a QJSValue, which has no length
    and compares equal to nothing. Unwrap it or the harness asserts on the wrong
    thing entirely."""
    v = obj.property(name)
    return v.toVariant() if hasattr(v, "toVariant") else v


FIXTURE = """# Board

Preamble prose that must survive every write, byte for byte.

---

## NEEDS YOU

Decisions only you can make. Each says what happens if you never answer.

### 1. First question?

Some context about the question.

- [ ] the first way
- [ ] the second way, whose label wraps
      onto a continuation line
- [ ] the third way

>

*If unanswered:* nothing happens and that is fine.

### 2. Second question?

- [ ] yes
- [ ] no

>

*If unanswered:* still nothing.

---

## IN FLIGHT

Running now. No action from you.

| What | Where | Notes |
|---|---|---|
| A thing being built | `apps/thing/**` | with a note |
| Another thing | panel | |

## WAITING ON YOU TO DO (not decide)

- **Relaunch `reader`** - live source, no hot reload.

## LANDED

Newest first. Append-only.

### 2026-07-28

| Commit | What |
|---|---|
| `abc1234` | did a thing |
| `def5678` | did another thing |

Also, not commits:

- **A finding** that is worth keeping around.
"""

EMPTY_FIXTURE = """# Board

## NEEDS YOU

Decisions only you can make. Each says what happens if you never answer.

## IN FLIGHT

Running now. No action from you.

| What | Where | Notes |
|---|---|---|
| A thing being built | `apps/thing/**` | with a note |

## LANDED

Newest first. Append-only.

### 2026-07-28

| Commit | What |
|---|---|
| `abc1234` | did a thing |
"""


# ------------------------------------------------------------ 1. the round trip
def test_roundtrip(tmp):
    import boardparse as B

    path = os.path.join(tmp, "fixture.md")
    open(path, "w").write(FIXTURE)
    src = B.read(path)
    doc = B.parse(src)

    check("a no-op write is byte-identical", "".join(doc["lines"]) == src)

    def lines_differing(a, b):
        la, lb = a.splitlines(True), b.splitlines(True)
        if len(la) != len(lb):
            return None
        return [i for i in range(len(la)) if la[i] != lb[i]]

    # tick one box
    item = doc["needs"][0]
    out = "".join(B.toggle_option(doc["lines"], item, 1, True))
    diff = lines_differing(src, out)
    check("ticking a box changes EXACTLY one line", diff is not None and len(diff) == 1, diff)
    if diff and len(diff) == 1:
        a = src.splitlines(True)[diff[0]]
        b = out.splitlines(True)[diff[0]]
        check("...and only the box inside it", a.replace("[ ]", "[x]", 1) == b, (a, b))

    # ...and the tick is what a re-parse reads back
    doc2 = B.parse(out)
    checked = [o["index"] for o in doc2["needs"][0]["options"] if o["checked"]]
    check("a re-parse sees the choice", checked == [1], checked)

    # the options are ALTERNATIVES: choosing another clears the first
    out2 = "".join(B.toggle_option(doc2["lines"], doc2["needs"][0], 2, True))
    doc3 = B.parse(out2)
    checked = [o["index"] for o in doc3["needs"][0]["options"] if o["checked"]]
    check("choosing another option clears the first (a radio, not flags)",
          checked == [2], checked)
    # ...and unticking the chosen one leaves the file as it started
    out3 = "".join(B.toggle_option(doc3["lines"], doc3["needs"][0], 2, False))
    check("unticking the chosen option restores the original bytes", out3 == src)

    # his own words
    out4 = "".join(B.set_answer(doc["lines"], item, "none of these, do X instead"))
    diff = lines_differing(src, out4)
    check("a one-line answer changes exactly one line",
          diff is not None and len(diff) == 1, diff)
    doc4 = B.parse(out4)
    check("...and it reads back as his answer",
          doc4["needs"][0]["answer"] == "none of these, do X instead",
          doc4["needs"][0]["answer"])
    check("...and the item is now answered", doc4["needs"][0]["answered"] is True)
    check("...while every other item is untouched",
          doc4["needs"][1]["answer"] == "" and doc4["needs"][1]["answered"] is False)

    # multi-line, and the trailing-space `> ` restored on clear
    multi = "".join(B.set_answer(doc["lines"], item, "line one\nline two"))
    docm = B.parse(multi)
    check("a multi-line answer round-trips as two quote lines",
          docm["needs"][0]["answer"] == "line one\nline two",
          docm["needs"][0]["answer"])
    # Clearing collapses the block back to ONE empty quote line, and the only
    # line in the file that may differ from the original is that one. (This
    # fixture spells it bare `>`; the marker comes back as `> `, which is the
    # store's own spelling — see the `> ` case below, which is byte-exact.)
    cleared = "".join(B.set_answer(docm["lines"], docm["needs"][0], ""))
    diff = lines_differing(src, cleared)
    check("clearing a multi-line answer touches only the answer line",
          diff is not None and len(diff) <= 1, diff)
    check("...and leaves it an empty quote", all(
        ln.strip() == ">" for ln in [cleared.splitlines()[i] for i in (diff or [])]),
        diff)
    check("clearing an answer that was never given writes nothing",
          "".join(B.set_answer(doc["lines"], item, "")) == src)

    # The real store spells the empty answer `> `, with a trailing space. Round
    # tripping must not normalise his punctuation either way, so the marker is
    # preserved rather than re-spelled.
    spaced = src.replace("\n>\n", "\n> " + "\n")
    ds = B.parse(spaced)
    written = "".join(B.set_answer(ds["lines"], ds["needs"][0], "something"))
    dw = B.parse(written)
    check("a `> ` store keeps its trailing space when the answer is cleared",
          "".join(B.set_answer(dw["lines"], dw["needs"][0], "")) == spaced)

    # the whole file, not just the item: nothing else may move
    check("the preamble, the tables and the LANDED prose are never rewritten",
          all(ln in out4 for ln in
              ("Preamble prose that must survive every write, byte for byte.\n",
               "| A thing being built | `apps/thing/**` | with a note |\n",
               "- **A finding** that is worth keeping around.\n")))

    # atomic write: the bytes on disk are the bytes we asked for, and the
    # original is intact if the write never happens
    B.write(path, out4)
    check("an atomic write lands exactly the bytes given", B.read(path) == out4)
    check("...and leaves no temp file behind",
          not [n for n in os.listdir(tmp) if n.startswith(".board-")],
          os.listdir(tmp))

    # ---- WHICH MACHINE he answered on -------------------------------------
    # board-watch runs on `top` AND `book` and this file syncs both ways, so an
    # unstamped answer would be worked twice. The stamp is what makes the host
    # he typed on the host that works it — and it is a line edit like every
    # other, invisible in his prose, and removed again when the answer goes.
    d0 = B.parse(src)
    it0 = d0["needs"][0]
    ticked = B.toggle_option(d0["lines"], it0, 1, True)
    d1 = B.parse("".join(ticked))
    stamped = "".join(B.set_answer_host(d1["lines"], d1["needs"][0], "book"))
    diff = lines_differing(src, stamped)
    check("stamping the host adds one line and rewrites none",
          diff is None and len(stamped.splitlines()) == len(src.splitlines()) + 1,
          diff)
    d2 = B.parse(stamped)
    it2 = d2["needs"][0]
    check("...which parses back as the host, not as prose",
          it2["answerHost"] == "book" and it2["hostLine"] >= 0
          and not any("answered-on" in (b.get("raw") or "")
                      for b in it2["body"]), repr(it2["answerHost"]))
    check("...and is not mistaken for his answer or his `if unanswered` line",
          it2["answer"] == it0["answer"]
          and it2["ifUnanswered"] == it0["ifUnanswered"])
    check("...restamping the same host is byte-identical",
          "".join(B.set_answer_host(d2["lines"], it2, "book")) == stamped)
    restamped = "".join(B.set_answer_host(d2["lines"], it2, "top"))
    check("...restamping the OTHER host changes exactly that one line",
          (lines_differing(stamped, restamped) or []) == [it2["hostLine"]])
    cleared = "".join(B.set_answer_host(d2["lines"], it2, ""))
    d3 = B.parse(cleared)
    check("...and clearing it restores the file byte-for-byte",
          "".join(B.toggle_option(d3["lines"], d3["needs"][0], 1, False)) == src)


# --------------------------------------------------- 1b. moving between sections
def test_moves(tmp):
    """An answered decision has to STOP asking him, and a failed agent has to
    leave no trace. Both are byte-level claims, so they are tested here beside
    the round trip rather than through the window.

    Everything runs on a copy in the scratch dir, with XDG_STATE_HOME already
    redirected (main() does it), so the stash these write is the harness's own.
    """
    import boardmove as bm
    import boardparse as B

    path = os.path.join(tmp, "board.md")

    def reset():
        open(path, "w").write(FIXTURE)
        for n in os.listdir(bm.stash_dir()):
            os.unlink(os.path.join(bm.stash_dir(), n))
        return B.read(path)

    def lines_differing(a, b):
        la, lb = a.splitlines(True), b.splitlines(True)
        common = [ln for ln in la if ln in lb]
        return len(la) - len(common), len(lb) - len([ln for ln in lb if ln in la])

    # ---- NEEDS YOU -> IN FLIGHT ----
    src = reset()
    doc = B.parse(src)
    B.write(path, "".join(B.toggle_option(doc["lines"], doc["needs"][0], 0, True)))
    src = B.read(path)
    span = B.item_span(B.parse(src)["lines"], B.parse(src)["needs"][0])
    kept = src.splitlines(True)[:span[0]] + src.splitlines(True)[span[1]:]
    rec = bm.start("1", where="apps/thing", path=path)
    out = B.read(path)
    doc2 = B.parse(out)
    check("starting a decision takes it out of NEEDS YOU",
          len(doc2["needs"]) == 1 and doc2["needs"][0]["num"] == "2",
          [d["num"] for d in doc2["needs"]])
    check("...and puts a row in IN FLIGHT carrying his answer",
          any(r["what"] == "First question?" and "the first way" in r["notes"]
              for r in doc2["flight"]),
          [(r["what"], r["notes"]) for r in doc2["flight"]])
    check("...in the section's OWN table, not the one below it",
          doc2["flight"][2]["what"] == "First question?",
          [r["what"] for r in doc2["flight"]])
    # Every line that was not part of the decision comes out in the same order,
    # untouched: the move is a relocation plus one inserted row, not a rewrite.
    left = [ln for ln in out.splitlines(True) if ln != rec["row"]]
    check("...and every other line of the file is untouched, in order",
          left == kept, [ln for ln in kept if ln not in left][:3])

    # ---- ...and back again, byte for byte ----
    bm.give_back("1", path=path)
    check("handing a decision back restores the file EXACTLY", B.read(path) == src,
          lines_differing(src, B.read(path)))

    # every decision, from wherever it sits in the section
    for num in ("1", "2"):
        src = reset()
        d = B.parse(src)
        it = [i for i in d["needs"] if i["num"] == num][0]
        B.write(path, "".join(B.set_answer(d["lines"], it, "do it")))
        src = B.read(path)
        bm.start(num, path=path)
        bm.give_back(num, path=path)
        check("decision %s: start -> back is byte-identical" % num,
              B.read(path) == src, lines_differing(src, B.read(path)))

    # ---- it is HIS to resolve: an unanswered one is refused ----
    reset()
    try:
        bm.start("1", path=path)
        check("an UNANSWERED decision is refused", False)
    except bm.BoardError:
        check("an UNANSWERED decision is refused", True)
    check("...and the refusal wrote nothing", B.read(path) == FIXTURE)

    # ---- IN FLIGHT -> LANDED ----
    src = reset()
    d = B.parse(src)
    B.write(path, "".join(B.set_answer(d["lines"], d["needs"][0], "do it")))
    bm.start("1", path=path)
    bm.land("1", "abc1234", what="thing: did the first way", path=path)
    doc3 = B.parse(B.read(path))
    check("landing removes the IN FLIGHT row",
          not any(r["what"] == "First question?" for r in doc3["flight"]),
          [r["what"] for r in doc3["flight"]])
    check("...and appends it under today's date with the commit",
          any(r["commit"] == "abc1234" and r["what"] == "thing: did the first way"
              for g in doc3["landed"] for r in g["rows"]),
          [(g["date"], [r["commit"] for r in g["rows"]]) for g in doc3["landed"]])
    check("...and the stash is dropped, so nothing reclaims it",
          not os.path.exists(bm.stash_file(rec["key"])))

    # a date the file has no group for gets one, at the TOP (newest first)
    bm.land("Another thing", "beef567", what="a later day", date="2026-09-09",
            path=path)
    doc4 = B.parse(B.read(path))
    check("a new date opens a new LANDED group, newest first",
          doc4["landed"][0]["date"] == "2026-09-09"
          and doc4["landed"][0]["rows"][0]["commit"] == "beef567",
          [g["date"] for g in doc4["landed"]])

    # ---- a bullet for him ----
    src = B.read(path)
    bm.note("**Relaunch `thing`** - live source.", path=path)
    doc5 = B.parse(B.read(path))
    check("a note lands as one bullet in WAITING ON YOU TO DO",
          len(doc5["todo"]) == 2
          and len(B.read(path).splitlines()) == len(src.splitlines()) + 1,
          [t["text"] for t in doc5["todo"]])

    # ---- NOTHING STAYS STRANDED: a dead owner is reclaimed ----
    src = reset()
    d = B.parse(src)
    B.write(path, "".join(B.set_answer(d["lines"], d["needs"][0], "do it")))
    src = B.read(path)
    bm.start("1", pid=os.getpid(), path=path)
    check("an item whose agent is still alive is left alone",
          bm.reconcile(path=path) == [])
    bm.give_back("1", path=path)

    dead = os.fork()
    if dead == 0:
        os._exit(0)
    os.waitpid(dead, 0)                       # a pid that is certainly gone
    bm.start("1", pid=dead, path=path)
    moved = bm.reconcile(path=path)
    check("an item whose agent DIED is returned to NEEDS YOU",
          len(moved) == 1 and moved[0]["num"] == "1", moved)
    back = B.read(path)
    check("...verbatim, with only a bullet added to say so",
          back.replace(back.splitlines(True)[-1], "") == src
          or len(back.splitlines()) == len(src.splitlines()) + 1,
          len(back.splitlines()) - len(src.splitlines()))
    check("...and the bullet says what happened",
          any("is gone" in t["text"] for t in B.parse(back)["todo"]),
          [t["text"] for t in B.parse(back)["todo"]])

    # ---- the write is guarded against a racing writer ----
    reset()
    hits = {"n": 0}

    def racer(doc):
        hits["n"] += 1
        if hits["n"] == 1:                    # somebody else writes mid-edit
            open(path, "a").write("\nan agent appended this.\n")
        return B.add_todo_bullet(doc["lines"], doc, "- late\n")

    B.edit(path, racer)
    txt = B.read(path)
    check("an edit computed from stale bytes is retried, not landed",
          hits["n"] == 2 and "an agent appended this." in txt
          and txt.count("- late") == 1, (hits["n"], txt.count("- late")))

    # ---- the CLI itself runs ----
    import subprocess
    cli = os.path.join(BOARD, "tools", "boardctl.py")
    p = subprocess.run([sys.executable, cli, "--board", path, "list"],
                       capture_output=True, text=True)
    check("boardctl list runs against a fixture",
          p.returncode == 0 and "IN FLIGHT" in p.stdout, p.stderr.strip()[:200])
    p = subprocess.run([sys.executable, cli, "--board", path, "start", "nope"],
                       capture_output=True, text=True)
    check("boardctl refuses a selector that matches nothing, and says so",
          p.returncode == 1 and "no decision" in p.stderr, p.stderr.strip()[:200])


# ------------------------------------- 1b2. clearing a chore off the TO DO list
TODO_FIXTURE = """# Board

Preamble prose that must survive every write, byte for byte.

---

## NEEDS YOU

### 1. A question?

- [ ] one

>

*If unanswered:* nothing happens.

---

## WAITING ON YOU TO DO (not decide)

- **Relaunch `reader`** - live source, no hot reload.
- **Relaunch `player`** - picks up the track menu, the working stars and the
  uncropped maximized art.
- **Rebuild to make the merged font live** - `sudo rebuild-top`.

---

## IN FLIGHT

| What | Where | Notes |
|---|---|---|
| A thing being built | `apps/thing/**` | with a note |

## LANDED

Newest first. Append-only.

### 2026-07-28

| Commit | What |
|---|---|
| `abc1234` | did a thing |
"""


def test_todo_remove(tmp):
    """*"i should be able to remove items from the 'to do, when you feel like
    it' section"*.

    Byte-level, like the round trip above, because this is the first thing in
    the app that DELETES his prose. Three claims: what goes is exactly the
    bullet (continuation lines included, nothing else on any line), the undo
    puts it back byte-for-byte wherever it sat, and a section that empties
    completely is still a section.
    """
    import boardparse as B

    src = TODO_FIXTURE
    doc = B.parse(src)
    todo = doc["todo"]
    check("the three chores parse", len(todo) == 3, [t["text"] for t in todo])
    check("a wrapped bullet knows where it ENDS, not just where it starts",
          todo[1]["endLine"] == todo[1]["line"] + 1
          and todo[0]["endLine"] == todo[0]["line"],
          [(t["line"], t["endLine"]) for t in todo])

    def removed(i, d=None):
        d = d or B.parse(src)
        return "".join(B.remove_todo(d["lines"], d["todo"][i]))

    # ---- the wrapped one in the middle ----
    out = removed(1)
    gone = [ln for ln in src.splitlines(True) if ln not in out.splitlines(True)]
    check("removing a wrapped bullet takes BOTH of its lines", len(gone) == 2, gone)
    check("...and every other line is byte-identical",
          [ln for ln in src.splitlines(True) if ln not in gone]
          == out.splitlines(True))
    d2 = B.parse(out)
    check("...and the other two chores are still there, unchanged",
          [t["text"] for t in d2["todo"]]
          == [todo[0]["text"], todo[2]["text"]], [t["text"] for t in d2["todo"]])
    check("...and nothing outside the section moved",
          all(s in out for s in ("Preamble prose that must survive",
                                 "| A thing being built | `apps/thing/**` | with a note |",
                                 "*If unanswered:* nothing happens.")))

    # ---- the undo, for each position, byte-for-byte ----
    for i, where in ((0, "the first"), (1, "a middle"), (2, "the last")):
        d = B.parse(src)
        t = d["todo"][i]
        a, b = B.todo_span(d["lines"], t)
        block, after = d["lines"][a:b], (d["lines"][b] if b < len(d["lines"]) else "")
        out = B.remove_todo(d["lines"], t)
        back = B.parse("".join(out))
        put = "".join(B.add_todo_block(back["lines"], back, block, after))
        check("putting %s chore back restores the file exactly" % where,
              put == src, "%d vs %d chars" % (len(put), len(src)))

    # ---- it empties out completely, and that is a resting state ----
    cur = src
    for _ in range(3):
        d = B.parse(cur)
        cur = "".join(B.remove_todo(d["lines"], d["todo"][0]))
    empty = B.parse(cur)
    check("the section can empty completely", empty["todo"] == [],
          [t["text"] for t in empty["todo"]])
    check("...with its heading and everything around it untouched",
          "## WAITING ON YOU TO DO (not decide)\n" in cur
          and "## IN FLIGHT\n" in cur and "| `abc1234` | did a thing |\n" in cur)
    check("...and only the three bullets' four lines are gone",
          len(src.splitlines()) - len(cur.splitlines()) == 4,
          len(src.splitlines()) - len(cur.splitlines()))
    # ...and an agent can still add one afterwards, into a section with no
    # bullets left to append after.
    d = B.parse(cur)
    again = "".join(B.add_todo_bullet(d["lines"], d, "- something new\n"))
    check("...and a new chore still lands inside the section",
          B.parse(again)["todo"][0]["text"] == "something new"
          and again.index("- something new")
          > again.index("## WAITING ON YOU TO DO"),
          [t["text"] for t in B.parse(again)["todo"]])

    # ---- a stale index REFUSES rather than deleting somebody's line ----
    d = B.parse(src)
    stale = dict(d["todo"][0])
    stale["line"] = stale["endLine"] = 0        # the `# Board` heading
    try:
        B.remove_todo(d["lines"], stale)
        check("a stale line index is refused, not obeyed", False, "it deleted line 0")
    except B.BoardError:
        check("a stale line index is refused, not obeyed", True)

    # ---- and it goes through the ONE write path, under the lock ----
    path = os.path.join(tmp, "todo.md")
    open(path, "w").write(src)
    B.edit(path, lambda d: B.remove_todo(d["lines"], d["todo"][2]))
    check("removal lands through boardparse.edit(), atomically",
          len(B.parse(B.read(path))["todo"]) == 2
          and not [n for n in os.listdir(tmp) if n.startswith(".board-")],
          os.listdir(tmp))


# ------------------------------------------------- 1c. who is running, and the box
def _stash(bm, key, title, pid, pid_start=None, where="apps/x/**"):
    """A stash exactly as `boardmove.start()` writes one. The harness fakes the
    RECORD, never the liveness rule: `_alive()` still decides, off a real pid and
    a real /proc start time."""
    import json
    rec = {"key": key, "num": "1", "title": title, "where": where, "row": "",
           "block": [], "before": "", "pid": pid,
           "pidStart": pid_start if pid_start is not None
           else (bm._proc_start(pid) if pid else None),
           "host": "top", "started": "now", "board": "/tmp/nowhere.md"}
    with open(bm.stash_file(key), "w") as f:
        json.dump(rec, f)
    return rec


def test_agents(tmp):
    """The agents display and the box he types into it.

    The claim under test is not "a message is sent" — there is nothing to send
    to, an agent's stdin is closed — but **a message he typed is never lost**.
    So every check here is a conservation check: after each path, the message is
    in exactly ONE of the three directories, and the count never drops.
    """
    import glob
    import boardagents as ba
    import boardmove as bm

    def where_is(text):
        found = []
        for name in ("to", "queue", "taken"):
            for p in glob.glob(os.path.join(ba._root(), "inbox", name, "**", "*.json"),
                               recursive=True):
                if text in open(p).read():
                    found.append(name)
        return found

    def total():
        return len(glob.glob(os.path.join(ba._root(), "inbox", "**", "*.json"),
                             recursive=True))

    for n in os.listdir(bm.stash_dir()):
        os.unlink(os.path.join(bm.stash_dir(), n))

    # a pid that is certainly gone, and one that certainly is not
    dead = os.fork()
    if dead == 0:
        os._exit(0)
    os.waitpid(dead, 0)
    _stash(bm, "live-one", "A decision being worked", os.getpid())
    _stash(bm, "dead-one", "A decision whose agent died", dead, pid_start="1")
    _stash(bm, "hand-one", "A decision moved by hand", None)

    seen = {a["id"]: a for a in ba.agents() if a["kind"] != "session"}
    check("a running agent is listed as running",
          seen.get("live-one", {}).get("state") == "running", seen.get("live-one"))
    check("...and a dead one is listed as EXITED, not as running",
          seen.get("dead-one", {}).get("state") == "exited", seen.get("dead-one"))
    check("...and says so in words, not in a colour",
          "exited" in ba.describe(seen["dead-one"])
          and "running" in ba.describe(seen["live-one"]),
          (ba.describe(seen["dead-one"]), ba.describe(seen["live-one"])))
    check("...and an item moved by hand admits it cannot be known",
          seen.get("hand-one", {}).get("state") == "unowned"
          and "cannot tell" in ba.describe(seen["hand-one"]),
          seen.get("hand-one"))
    check("a recycled pid cannot fake a live agent",
          bm._alive({"pid": os.getpid(), "pidStart": "1"}) is False)
    check("nothing in the display is an age, a count or a time",
          not any(k in seen["live-one"] for k in ("started", "at", "seconds", "age")),
          sorted(seen["live-one"]))

    # ---- the box: a LIVE agent ----
    m = ba.send("also fix the tooltip", to="live-one", to_title="A decision")
    check("a note to a running agent is DELIVERED to its inbox",
          m["state"] == "delivered" and where_is("also fix the tooltip") == ["to"],
          (m["state"], where_is("also fix the tooltip")))
    check("...and shows on its row until it is read, not before",
          [x["text"] for x in ba.for_agent("live-one")] == ["also fix the tooltip"])
    os.environ["BOARD_AGENT_ID"] = "live-one"
    got = ba.take()
    del os.environ["BOARD_AGENT_ID"]
    check("...and `inbox take` is what actually reads it",
          [g["text"] for g in got] == ["also fix the tooltip"]
          and where_is("also fix the tooltip") == ["taken"],
          where_is("also fix the tooltip"))
    check("...leaving nothing unread on that row", ba.for_agent("live-one") == [])

    # ---- the box: an agent that has ALREADY FINISHED ----
    m = ba.send("try the other approach", to="dead-one")
    check("a note to an agent that has gone is QUEUED, never dropped",
          m["state"] == "queued" and where_is("try the other approach") == ["queue"],
          (m["state"], where_is("try the other approach")))

    # ---- the box: NOTHING running at all ----
    m = ba.send("look at the panel spacing")
    check("a note with no agent named is queued for the next one",
          m["state"] == "queued" and where_is("look at the panel spacing") == ["queue"],
          m["state"])

    # ---- an agent that never reads it: the guarantee ----
    ba.send("this one is never read", to="live-one")
    check("a note left for a live agent waits in its inbox",
          where_is("this one is never read") == ["to"])
    _stash(bm, "live-one", "A decision being worked", os.getpid(), pid_start="1")
    moved, dropped = ba.sweep()
    check("...and is escalated to the queue when that agent goes",
          [m["text"] for m in moved] == ["this one is never read"]
          and where_is("this one is never read") == ["queue"],
          (moved, where_is("this one is never read")))

    # ...and the same happens on time alone, so a silent agent cannot sit on it
    _stash(bm, "live-one", "A decision being worked", os.getpid())
    ba.send("this one is sat on", to="live-one")
    old = ba.ESCALATE_AFTER_S
    ba.ESCALATE_AFTER_S = -1
    moved, _ = ba.sweep()
    ba.ESCALATE_AFTER_S = old
    check("a note a LIVE agent never picks up is escalated too",
          [m["text"] for m in moved] == ["this one is sat on"]
          and where_is("this one is sat on") == ["queue"], moved)

    # ---- the queue is somebody's job ----
    before = [m["text"] for m in ba.pending()]
    drained = ba.drain()
    check("board-watch drains the whole queue before it spawns",
          [m["text"] for m in drained] == before and ba.pending() == [], before)
    check("...and every message is still on disk, exactly once",
          total() == 5 and all(where_is(t) == ["taken"] for t in before), total())

    # ---- a dead registration does not sit there claiming to work ----
    ba.register("note-x", "a note you sent", dead, kind="note")
    check("a registered run is listed while its process lives",
          any(a["id"] == "note-x" for a in ba.agents()))
    moved, gone = ba.sweep()
    check("...and is dropped by the sweep once it is not",
          [g["id"] for g in gone] == ["note-x"]
          and not any(a["id"] == "note-x" for a in ba.agents()), gone)

    # ---- an agent is listed ONCE, however it was spawned ----
    # The dedupe against interactive sessions has to hold for both shapes of
    # agent, and they are opposites. A decision/note agent's registered pid is
    # board-watch's tick process, with the `claude` as its CHILD — only ancestry
    # catches that. A WORKER gets its own systemd unit, so the pid registered
    # for it IS the `claude` process, which appears in nobody's ancestor list
    # but its own — and it was drawn a second time as an anonymous session
    # until the dedupe considered the pid itself as well.
    fake = {
        900001: (1, "claude", ["claude", "-p"]),        # a worker, unit-spawned
        900002: (1, "claude", ["claude"]),              # his terminal: nobody's
        900003: (1, "python3", ["python3", "board-watch.py"]),
        900004: (900003, "claude", ["claude", "-p"]),   # ...its child
    }
    ba.register("unit-worker", "a worker in its own unit", 900001, kind="worker")
    ba.register("tick-agent", "an agent under the tick", 900003, kind="note")
    got = ba.agents(procs=fake)
    check("a worker whose OWN pid is the claude process is listed once",
          [a["kind"] for a in got if a["pid"] == 900001] == ["worker"],
          [(a["id"], a["kind"]) for a in got if a["pid"] == 900001])
    check("...and an agent whose claude is a CHILD is still listed once",
          [a["kind"] for a in got if a["pid"] in (900003, 900004)] == ["note"],
          [(a["id"], a["kind"], a["pid"]) for a in got if a["pid"] in (900003, 900004)])
    check("...while a session nobody here spawned is still listed as a session",
          [(a["id"], a["kind"], a["title"]) for a in got if a["pid"] == 900002]
          == [("s900002", "session", "an interactive Claude Code session")],
          [(a["id"], a["kind"]) for a in got if a["pid"] == 900002])
    for aid in ("unit-worker", "tick-agent"):
        p = os.path.join(ba.agents_dir(), "%s.json" % aid)
        if os.path.exists(p):
            os.unlink(p)

    # ---- the watcher's own state, said honestly ----
    check("an unaskable watcher says so rather than looking healthy",
          "could not be asked" in ba.watcher_state("")["text"])
    check("a failed watcher is reported as failed",
          "failed" in ba.watcher_state("ActiveState=failed\n")["text"])
    check("an idle watcher reads as armed, not as broken",
          "armed" in ba.watcher_state("ActiveState=inactive\n")["text"])

    # ---- and the CLI half an agent actually uses ----
    import subprocess
    cli = os.path.join(BOARD, "tools", "boardctl.py")
    env = dict(os.environ, BOARD_AGENT_ID="live-one")
    p = subprocess.run([sys.executable, cli, "inbox", "send", "from the cli",
                        "--to", "live-one"], capture_output=True, text=True, env=env)
    q = subprocess.run([sys.executable, cli, "inbox", "take"],
                       capture_output=True, text=True, env=env)
    check("boardctl inbox send/take is the agent's half of the box",
          p.returncode == 0 and q.returncode == 0 and "from the cli" in q.stdout,
          (p.stderr.strip()[:120], q.stdout.strip()[:120]))
    p = subprocess.run([sys.executable, cli, "agents"], capture_output=True, text=True)
    check("boardctl agents lists who is running",
          p.returncode == 0 and "A decision being worked" in p.stdout,
          p.stderr.strip()[:200])

    for n in os.listdir(bm.stash_dir()):
        os.unlink(os.path.join(bm.stash_dir(), n))


# ------------------------------------- 1d. what an agent SAYS vs what it DOES
def _tsc(tmp, uuid_, calls):
    """A synthetic transcript, in the shape the real ones have. Written under
    `BOARD_TRANSCRIPTS`, never into his `~/.claude` — that syncs to book."""
    d = os.path.join(tmp, "transcripts", "-proj")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, uuid_ + ".jsonl")
    with open(p, "a") as f:
        for name, inp in calls:
            f.write(json.dumps({"type": "assistant", "timestamp": "2026-07-29T00:00:00Z",
                                "message": {"content": [{"type": "tool_use",
                                                         "name": name, "input": inp}]}})
                    + "\n")
    return p


def test_phase(tmp):
    """The observed half, which is the half that cannot be faked.

    The claim and the observation are two fields and neither is ever the other:
    that is the whole design, so it is asserted rather than trusted.
    """
    os.environ["BOARD_TRANSCRIPTS"] = os.path.join(tmp, "transcripts")
    import boardphase as bph

    check("an Edit reads as coding", bph.classify("Edit", {}) == "coding")
    check("a Read reads as researching", bph.classify("Read", {}) == "researching")
    check("a test run reads as testing",
          bph.classify("Bash", {"command": "python3 tools/board-test.py"}) == "testing")
    check("a commit reads as finishing touches",
          bph.classify("Bash", {"command": "git commit -m x -- a"}) == "finishing")
    check("an ordinary shell command claims no phase at all",
          bph.classify("Bash", {"command": "ls -la"}) is None)
    check("reading is the background noise of every phase, not a phase of its own",
          bph.phase_of_window([{"phase": "coding"}, {"phase": "researching"},
                               {"phase": "researching"}]) == "coding")

    u = "11111111-2222-3333-4444-555555555555"
    _tsc(tmp, u, [])
    r = bph.observe("ph-a", session=u)
    check("a linked agent that has done nothing says exactly that",
          r["observed"] == "none" and bph.actually(r) == "nothing yet", r)
    check("...and is not filed under a phase it has not reached",
          r["phase"] == "unreported", r["phase"])
    r = bph.observe("ph-none")
    check("an agent with NO session says it cannot be observed, and never guesses",
          r["observed"] == "unlinked" and "cannot see what it is doing"
          in bph.actually(r), bph.actually(r))

    _tsc(tmp, u, [("Read", {"file_path": "/x/boardparse.py"}),
                  ("Grep", {"pattern": "edit"})])
    r = bph.observe("ph-a")
    off = r["offset"]
    check("tool calls in the transcript become the phase",
          r["phase"] == "researching", r["phase"])
    check("...and the activity line names the thing, not the tool",
          bph.actually(r) == "searching for edit", bph.actually(r))
    _tsc(tmp, u, [("Edit", {"file_path": "/x/Main.qml"})])
    r = bph.observe("ph-a")
    check("an edit moves the card to coding, with no relaunch and no report",
          r["phase"] == "coding" and bph.actually(r) == "editing Main.qml", r["phase"])
    check("...having read ONLY the new bytes (a transcript reaches megabytes)",
          r["offset"] > off, (off, r["offset"]))

    # THE DIVERGENCE. This is the thing he asked to be able to see.
    check("an agent that has said nothing shows no claim, rather than a guess",
          bph.says(bph.observe("ph-a")) == "")
    bph.claim("ph-a", "testing", "the parser round-trips")
    r = bph.observe("ph-a")
    check("a claim is recorded and drawn in the agent's own words",
          bph.says(r) == "testing - the parser round-trips", bph.says(r))
    check("...and does NOT move the card: the phase stays the observed one",
          r["phase"] == "coding", r["phase"])
    check("...and the observation is never replaced by the claim",
          bph.actually(r) == "editing Main.qml", bph.actually(r))

    # A transcript is appended to WHILE this reads it.
    with open(_tsc(tmp, u, []), "a") as f:
        f.write('{"type":"assis')
    r = bph.observe("ph-a")
    check("half a line at the end of a live transcript is left for the next poll",
          r["phase"] == "coding", r)

    old = bph.QUIET_AFTER_S
    try:
        bph.QUIET_AFTER_S = 0
        r = bph.observe("ph-a")
        check("an agent that has stopped doing anything says so",
              r["observed"] == "quiet" and "nothing recently" in bph.actually(r),
              bph.actually(r))
        check("...in words, with no elapsed time anywhere in it",
              not re.search(r"\d+\s*(s|m|h|sec|min|hour)", bph.actually(r)),
              bph.actually(r))
        check("...while its own claim is left standing, unmarked",
              bph.says(r) == "testing - the parser round-trips")
    finally:
        bph.QUIET_AFTER_S = old


# ------------------------------------------ 1e. the fan-out: the cap and asking
def test_work(tmp):
    import boardagents as ba
    import boardmove as bm
    import boardparse as B
    import boardwork as bw

    os.environ["BOARD_WORK_SPAWN"] = "sleep 30"
    os.environ["BOARD_MAX_WORKERS"] = "2"

    dispatched = ["task one", "task two", "task three", "task four"]
    states = [bw.dispatch(t, where="apps/x/**")["state"] for t in dispatched]
    check("dispatch runs up to the cap and QUEUES the rest, never drops one",
          states == ["running", "running", "queued", "queued"], states)

    def filed():
        out = []
        for sub in ("pending", "taken"):
            for name in os.listdir(bw.work_dir(sub)):
                if name.endswith(".json") and not name.startswith("."):
                    with open(os.path.join(bw.work_dir(sub), name)) as f:
                        out.append((sub, json.load(f)["task"]))
        return out

    everywhere = filed()
    check("every dispatched task is on disk EXACTLY once, in exactly one place",
          sorted(t for _, t in everywhere) == sorted(dispatched)
          and len(everywhere) == len(dispatched), everywhere)

    g = {x["phase"]: [r["title"] for r in x["rows"]] for x in bw.groups()}
    check("work above the cap is DRAWN as waiting, not hidden",
          sorted(g.get("queued", [])) == ["task four", "task three"], g.get("queued"))
    check("...and it is not offered an inbox, having no process to reach",
          all(r["id"] == "" for x in bw.groups() if x["phase"] == "queued"
              for r in x["rows"]))

    for a in bw.live_workers():
        os.kill(a["pid"], 9)
    time.sleep(0.4)
    check("a worker whose process is gone stops holding a slot",
          len(bw.live_workers()) == 0, bw.live_workers())
    started = bw.promote()
    check("...and the queued work starts, oldest first",
          [r["task"] for r in started] == ["task three", "task four"],
          [r["task"] for r in started])
    check("...leaving nothing queued and still nothing lost",
          bw.pending() == []
          and sorted(t for _, t in filed()) == sorted(dispatched), filed())
    for a in bw.live_workers():
        os.kill(a["pid"], 9)
    time.sleep(0.4)

    # A DEAD AGENT'S CARD DOES NOT GO ON CLAIMING A PHASE. Two layers: the
    # group is decided by liveness, and the sweep drops the record entirely.
    import boardphase as bph
    _stash(bm, "gone-one", "Something being built", os.getpid(),
           where="apps/thing/**")
    ba.register("gone-two", "A worker that died", 999999, kind="worker",
                where="apps/x/**")
    bph.claim("gone-two", "coding", "wiring it up")
    g = {x["phase"]: [r["title"] for r in x["rows"]] for x in bw.groups()}
    check("a dead agent is filed under `stopped`, whatever it last claimed",
          "A worker that died" in g.get("stopped", [])
          and "A worker that died" not in g.get("coding", []), g)
    check("...and its claim is still readable rather than deleted out from under him",
          bph.says(bph.read_sidecar("gone-two")) == "coding - wiring it up")
    ba.sweep()
    check("...and the sweep then drops it from the list entirely",
          "gone-two" not in [a["id"] for a in ba.agents()])
    check("...taking its observation record with it, not leaving one per agent ever run",
          not os.path.exists(bph.sidecar("gone-two")))
    bm.forget("gone-one")

    check("the cap is a file he can change without a rebuild",
          bw.set_cap(6) == 6 and open(bw.cap_file()).read().strip() == "6")
    os.environ["BOARD_MAX_WORKERS"] = "2"

    # ---- asking him something: the SAME list his own questions are in ----
    path = os.path.join(tmp, "ask.md")
    open(path, "w").write(FIXTURE)
    src = B.read(path)
    try:
        bm.ask("Something?", path=path)
        check("a question with no `if unanswered` sentence is refused", False)
    except bm.BoardError as e:
        check("a question with no `if unanswered` sentence is refused",
              "if-unanswered" in str(e), str(e)[:60])
    check("...and the refusal wrote nothing", B.read(path) == src)

    key = bm.ask("How far should the fade reach?",
                 context=["The titlebar and the body disagree."],
                 options=["apps only", "apps and panel"],
                 if_unanswered="the apps get it and nothing else does",
                 asked_by="the FOCUS signal task", path=path)
    doc = B.parse(B.read(path))
    asked = [it for it in doc["needs"] if it["key"] == key]
    check("an agent's question lands in NEEDS YOU as an ordinary decision",
          len(asked) == 1, [it["key"] for it in doc["needs"]])
    if asked:
        it = asked[0]
        check("...numbered on from his own, with options, an answer line and the "
              "sentence that makes it safe to ignore",
              it["num"] == "3" and len(it["options"]) == 2
              and it["answerFrom"] >= 0 and it["ifUnanswered"] != "",
              (it["num"], len(it["options"]), it["answerFrom"], it["ifUnanswered"]))
        check("...and it is indistinguishable from one he wrote: no robot flag",
              "agent" not in it["title"].lower())
    check("...and nothing else in the file moved",
          B.read(path).startswith(src[:src.index("### 2.")]),
          B.read(path)[:60])

    # board-watch would otherwise record this key on its next tick and never
    # fire on it — see boardwork.seed_watch_state.
    st = os.path.join(tmp, "watchstate")
    os.makedirs(st, exist_ok=True)
    os.environ["BOARD_WATCH_STATE"] = st
    check("with no board-watch state yet, seeding is a no-op rather than a crash",
          bw.seed_watch_state(key) is False)
    with open(os.path.join(st, "state.json"), "w") as f:
        json.dump({"answers": {"first-question": "idx:|ans:"}}, f)
    check("a brand-new question is seeded into board-watch as UNANSWERED",
          bw.seed_watch_state(key) is True)
    with open(os.path.join(st, "state.json")) as f:
        answers = json.load(f)["answers"]
    check("...so his answer to it is an ordinary change to a known decision",
          answers.get(key) == "idx:|ans:", answers)
    del os.environ["BOARD_WATCH_STATE"]
    del os.environ["BOARD_WORK_SPAWN"]


# ----------------------------------------------------------------- 2. the store
def test_real_store():
    import boardparse as B

    if not os.path.isfile(B.BOARD_PATH):
        check("the store exists", False, B.BOARD_PATH)
        return
    src = B.read(B.BOARD_PATH)
    doc = B.parse(src)
    check("the real board.md round-trips unchanged", "".join(doc["lines"]) == src)
    # NEEDS YOU is deliberately NOT required to be non-empty: with the moves in
    # `boardmove.py` an answered decision leaves it, so an empty section is the
    # resting state (and the one he sees most often), not a parse regression.
    check("...and the sections that have content parsed",
          bool(doc["flight"]) and bool(doc["landed"]),
          (len(doc["needs"]), len(doc["todo"]), len(doc["flight"]), len(doc["landed"])))
    check("every decision has a title and an `if unanswered` line",
          all(d["title"] and d["ifUnanswered"] for d in doc["needs"]),
          [(d["key"], bool(d["ifUnanswered"])) for d in doc["needs"]])
    check("every decision has somewhere to write a free-text answer",
          all(d["answerFrom"] >= 0 for d in doc["needs"]),
          [(d["key"], d["answerFrom"]) for d in doc["needs"]])

    # §2.3: a character the pixel font lacks CLIPS the row it is drawn in, so
    # everything drawable must have been mapped at ingest.
    from PySide6.QtGui import QRawFont
    from glyphs import is_mappable
    fpath = os.path.expanduser("~/.local/share/fonts/MorePerfectDOSVGA.ttf")
    if not os.path.isfile(fpath):
        check("the pixel font is installed", False, fpath)
        return
    font = QRawFont(fpath, 15)

    def missing(s):
        out = set()
        for ch in set(s):
            if ch in "\n\t":
                continue
            idx = font.glyphIndexesForString(ch)
            if not idx or idx[0] == 0:
                out.add(ch)
        return out

    drawn = []
    for d in doc["needs"]:
        drawn += [d["title"], d["ifUnanswered"]] + [o["label"] for o in d["options"]]
        drawn += [b["text"] for b in d["body"]]
    drawn += [t["text"] for t in doc["todo"]]
    for f in doc["flight"]:
        drawn += [f["what"], f["where"], f["notes"]]
    for g in doc["landed"]:
        drawn += [g["date"]] + [r["commit"] for r in g["rows"]] \
                 + [r["what"] for r in g["rows"]] + [p["text"] for p in g["prose"]]
    for k in doc["intro"]:
        drawn += [p["text"] for p in doc["intro"][k]]
    # The recorded limit, so a real regression is not lost in it: the shared
    # table (`pylib/glyphs.py` + the panel's `Glyphs.qml` twin — two roofs, both
    # retuned together) has no entry for the Latin-1 accented CAPITALS, and
    # board.md quotes them by name because the open decision in it is about
    # exactly that gap in the font. Extending the table is a desktop-wide change
    # that belongs to that decision, not to this app.
    KNOWN = set("ÀÁÂÃÈÊËÌÍÎÏÐÒÓÔÕØÙÚÛÝÞ")
    bad = {c for c in missing("".join(drawn)) if is_mappable(c)}
    check("no mappable character survives ingest (a missing glyph clips its row)",
          not (bad - KNOWN), sorted(bad - KNOWN))
    if bad & KNOWN:
        print("NOTE  the store quotes %d characters the font lacks and the shared "
              "table does not map (%s) - a recorded limit, see AGENTS.md"
              % (len(bad & KNOWN), "".join(sorted(bad & KNOWN))))


# --------------------------------------------------------------- 3. the window
def build(app, path):
    from PySide6.QtCore import QUrl, QObject, Slot
    from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
    import PySide6.QtQuick  # noqa: F401  (registers the QQuickItem converter)
    from deskstyle import DeskStyle
    import main as brd

    class StubTitlebar(QObject):
        clicks = []

        @Slot("QVariantList")
        def setButtons(self, b): pass

        @Slot(str)
        def setFooter(self, t): pass

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    keep = (brd.Palette(brd.PANEL_THEME), DeskStyle(parent=engine), StubTitlebar(),
            brd.Board(path), brd.Settings(), brd.Agents())
    ctx.setContextProperty("WalPalette", keep[0])
    ctx.setContextProperty("DeskStyle", keep[1])
    ctx.setContextProperty("Titlebar", keep[2])
    ctx.setContextProperty("Board", keep[3])
    ctx.setContextProperty("Settings", keep[4])
    ctx.setContextProperty("Agents", keep[5])
    comp = QQmlComponent(engine, QUrl.fromLocalFile(os.path.join(BOARD, "qml/theme/Theme.qml")))
    theme = comp.create()
    if theme is None:
        raise SystemExit("Theme.qml failed: " + comp.errorString())
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)
    engine.load(QUrl.fromLocalFile(os.path.join(BOARD, "qml/Main.qml")))
    roots = engine.rootObjects()
    if not roots:
        raise SystemExit("Main.qml failed to load")
    return engine, roots[0], keep + (theme,)


def spin(ms=150):
    from PySide6.QtGui import QGuiApplication
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QGuiApplication.processEvents()
        time.sleep(0.005)


def descendants(item):
    out = []
    stack = list(item.childItems())
    while stack:
        it = stack.pop()
        out.append(it)
        stack.extend(it.childItems())
    return out


def shot(win, name):
    """A PNG of the real window. The agent that writes this app looks at these;
    the user does the real visual check, as always."""
    if SHOTS is None:
        return
    spin(250)
    img = win.grabWindow()
    out = os.path.join(SHOTS, name + ".png")
    ok = (not img.isNull()) and img.save(out)
    check("grabbed %s (%dx%d)" % (name, img.width(), img.height()), ok, out)


def test_real_window(app):
    """The real store, drawn. READ ONLY — nothing here calls a write slot, and
    board writes only when one is called. This is the layout check that matters,
    because his document is the one with 200-character option labels, wrapped
    continuations and a LANDED section of prose."""
    import boardparse as B
    if not os.path.isfile(B.BOARD_PATH):
        return
    engine, win, keep = build(app, B.BOARD_PATH)
    spin(500)
    # Not "there is a decision": there may legitimately be none (`boardmove.py`
    # takes answered ones out). What must hold is that his real document draws.
    check("the real store draws",
          len(prop(win, "flight")) > 0 and len(prop(win, "landed")) > 0,
          (len(prop(win, "needs")), len(prop(win, "flight")),
           len(prop(win, "landed"))))
    shot(win, "00-real-store")
    # ...and with the two live sections folded away, which is how LANDED gets
    # onto one screen — the collapse is persisted state, so this is a real
    # state, not a harness trick.
    win.setProperty("collapsed", {"needs": True, "flight": True})
    spin(300)
    shot(win, "00b-real-store-collapsed")
    win.setProperty("collapsed", {})
    spin(200)


def test_window(app, tmp):
    import boardparse as B

    path = os.path.join(tmp, "board.md")
    open(path, "w").write(FIXTURE)
    engine, win, keep = build(app, path)
    board = keep[3]
    spin(400)

    check("the window opened", win.isVisible() is not False)
    check("it drew a default size that fits beside the panel",
          win.width() == 880 and win.height() == 880, (win.width(), win.height()))
    check("all three sections parsed into the view",
          len(prop(win, "needs")) == 2 and len(prop(win, "flight")) == 2
          and len(prop(win, "landed")) == 1,
          (len(prop(win, "needs")), len(prop(win, "flight")), len(prop(win, "landed"))))
    check("the to-do list is drawn with the things that need him",
          len(prop(win, "todo")) == 1, prop(win, "todo"))
    shot(win, "01-populated")

    # ---- answering, through the same path the click takes ----
    key = prop(win, "needs")[0]["key"]
    check("choosing an option is written back", board.choose(key, 1, True) is True)
    spin(200)
    check("...and the view shows it chosen",
          prop(win, "needs")[0]["options"][1]["checked"] is True,
          prop(win, "needs")[0]["options"])
    check("free text is written back",
          board.answer(key, "none of these - do the third thing") is True)
    spin(200)
    check("...and the view shows it, with the item marked answered",
          prop(win, "needs")[0]["answer"] == "none of these - do the third thing"
          and prop(win, "needs")[0]["answered"] is True,
          prop(win, "needs")[0]["answer"])
    # ...and it recorded WHICH MACHINE, in the same write. board-watch runs on
    # `top` and on `book` and this file syncs both ways, so an answer with no
    # stamp is one two agents work. The app is the only thing that writes it.
    check("answering stamps the machine he answered on",
          prop(win, "needs")[0]["answerHost"] == os.uname().nodename,
          prop(win, "needs")[0]["answerHost"])
    check("...and the stamp is not drawn anywhere in the item",
          not any("answered-on" in (b.get("text") or "")
                  for b in prop(win, "needs")[0]["body"]))
    check("...and clearing the answer takes the stamp with it",
          board.answer(key, "") is True
          and board.choose(key, 1, False) is True
          and not prop(win, "needs")[0]["answerHost"],
          prop(win, "needs")[0]["answerHost"])
    board.choose(key, 1, True)
    board.answer(key, "none of these - do the third thing")
    spin(200)
    shot(win, "02-answered")

    # ---- the answer editor, open ----
    cards = [it for it in descendants(win.contentItem())
             if it.property("decision") is not None]
    check("the decisions are drawn as cards", len(cards) >= 2, len(cards))
    if cards:
        cards[1].setProperty("editing", True)
        spin(200)
        check("an item with a `>` line can be answered in the app",
              cards[1].property("canAnswer") is True)
        shot(win, "02b-editing")
        cards[1].setProperty("editing", False)
        spin(120)

    # ---- the clobber guard: someone else edits the file under us ----
    stale = board.property("doc")
    src = B.read(path)
    open(path, "w").write(src.replace("Some context about the question.",
                                      "Some context, edited by an agent."))
    # ...but board has not noticed yet (its watcher settles), so this write is
    # computed from a stale parse. It must REFUSE rather than land a stale line
    # number in someone else's paragraph.
    before = B.read(path)
    ok = board.choose(key, 0, True)
    check("a write computed from a stale parse is REFUSED", ok is False)
    check("...and the file on disk is untouched", B.read(path) == before)
    spin(400)
    check("...and the app reloaded the newer file",
          any("edited by an agent" in b["text"]
              for b in prop(win, "needs")[0]["body"]),
          prop(win, "needs")[0]["body"])
    check("...so the same click now works", board.choose(key, 0, True) is True)
    del stale

    # ---- an external edit reloads in place ----
    src = B.read(path)
    open(path, "w").write(src.replace(
        "---\n\n## IN FLIGHT",
        "### 3. A third question?\n\n- [ ] sure\n\n>\n\n"
        "*If unanswered:* nothing.\n\n---\n\n## IN FLIGHT", 1))
    spin(500)
    check("an item added underneath us appears without a relaunch",
          len(prop(win, "needs")) == 3, len(prop(win, "needs")))

    # ---- EVERY section is live, not just NEEDS YOU ----
    # An agent moving an item out from under him is the ordinary case now
    # (`boardmove.py`), and it changes two sections at once. Both must redraw
    # with no relaunch, and his place in the document must not move.
    import boardmove as bm
    scrollers = [it for it in descendants(win.contentItem())
                 if it.property("contentHeight") is not None
                 and it.property("contentX") is not None
                 and it.property("originY") is not None]
    check("the page is one scroll region", len(scrollers) == 1, len(scrollers))
    scroller = scrollers[0] if scrollers else None
    if scroller is not None:
        # A real scroll position needs real overflow: at 880x880 this fixture
        # fits, and a contentY nothing could have produced is not a test.
        win.setHeight(320)
        spin(200)
        scroller.setProperty("contentY", 120)
        spin(150)
    win.setProperty("drafts", {"second-question": "half a sentence he is typing"})
    before_needs, before_flight = len(prop(win, "needs")), len(prop(win, "flight"))

    B.write(path, "".join(B.set_answer(B.parse(B.read(path))["lines"],
                                       B.parse(B.read(path))["needs"][1], "go on")))
    spin(400)
    rec = bm.start("2", where="apps/thing", path=path)
    spin(500)
    check("an item moved to IN FLIGHT leaves NEEDS YOU on screen, no relaunch",
          len(prop(win, "needs")) == before_needs - 1,
          (before_needs, len(prop(win, "needs"))))
    check("...and arrives in IN FLIGHT in the same reload",
          len(prop(win, "flight")) == before_flight + 1
          and any("Second question?" == r["what"] for r in prop(win, "flight")),
          [r["what"] for r in prop(win, "flight")])
    check("...carrying his answer back to him, and no time or count",
          any(r["notes"] == "you said: go on" for r in prop(win, "flight")),
          [r["notes"] for r in prop(win, "flight")])
    if scroller is not None:
        check("...without moving his place in the document",
              abs(scroller.property("contentY") - 120) < 1,
              (scroller.property("contentY"), scroller.property("contentHeight"),
               scroller.property("height")))
        win.setHeight(880)
        spin(150)
    check("...and without losing the answer he was half-way through typing",
          prop(win, "drafts").get("second-question") == "half a sentence he is typing",
          prop(win, "drafts"))

    # LANDED is the third section, and it is live too
    before_landed = len(prop(win, "landed"))
    bm.land("Second question?", "aa11bb2", what="thing: went on", date="2026-09-09",
            path=path)
    spin(500)
    check("landing redraws IN FLIGHT and LANDED together",
          len(prop(win, "flight")) == before_flight
          and len(prop(win, "landed")) == before_landed + 1,
          (len(prop(win, "flight")), len(prop(win, "landed"))))

    # ---- the file REPLACED wholesale, the way a git checkout or a sync does ----
    # An atomic save swaps the inode, so a watch on the file alone stops firing.
    # This is the case the directory watch exists for; assert it rather than
    # trust it.
    B.write(path, "".join(B.add_needs_item(
        B.parse(B.read(path))["lines"],
        ["### 9. A question from the other machine?\n", "\n", "- [ ] sure\n",
         "\n", ">\n", "\n", "*If unanswered:* nothing.\n", "\n"])))
    spin(500)
    check("a file REPLACED by rename (a sync, a git checkout) still reloads",
          any(d["num"] == "9" for d in prop(win, "needs")),
          [d["num"] for d in prop(win, "needs")])

    # ---- a section emptying out entirely still redraws ----
    doc = B.parse(B.read(path))
    lines = doc["lines"]
    for it in reversed(doc["needs"]):
        lines, _ = B.cut_item(lines, it)
    B.write(path, "".join(lines))
    spin(500)
    check("NEEDS YOU emptying completely redraws to the empty state",
          len(prop(win, "needs")) == 0, len(prop(win, "needs")))
    check("...and the other two sections are still there",
          len(prop(win, "flight")) > 0 and len(prop(win, "landed")) > 0,
          (len(prop(win, "flight")), len(prop(win, "landed"))))

    # ---- the agents section: the machine, drawn beside the store ----
    # It is not part of board.md, so it is checked through the same window but
    # against `boardagents`' own state. What matters on screen: a running agent
    # is there, a dead one is TOLD APART, a finished one leaves, and a note he
    # types is visible in whichever of the two places it went.
    import boardagents as ba
    agents = keep[5]
    for n in os.listdir(bm.stash_dir()):
        os.unlink(os.path.join(bm.stash_dir(), n))
    # A pid that is certainly gone. `subprocess`, not `os.fork()`: by here the
    # Qt application object exists and forking a multi-threaded process is a
    # deadlock waiting to be flaky.
    import subprocess
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    dead = dead.pid
    _stash(bm, "drawn-live", "Dim the cover art when unfocused", os.getpid(),
           where="apps/player/qml/**")
    _stash(bm, "drawn-dead", "Widen the panel's clock", dead, pid_start="1",
           where="panel")
    agents.refresh()
    spin(250)
    rows = {a["id"]: a for a in prop(win, "agents") if a["kind"] != "session"}
    check("the agents section draws what is running",
          rows.get("drawn-live", {}).get("running") is True, rows.get("drawn-live"))
    check("...and draws a failed agent differently, in words",
          rows.get("drawn-dead", {}).get("running") is False
          and "exited" in rows.get("drawn-dead", {}).get("detail", ""),
          rows.get("drawn-dead"))
    said = agents.send("drawn-live", "Dim the cover art", "decision",
                       "also dim the tracklist")
    agents.refresh()
    spin(250)
    rows = {a["id"]: a for a in prop(win, "agents")}
    check("a note to a running agent reports delivery honestly",
          "inbox" in said and "read" in said, said)
    check("...and stays visible on its row until it is read",
          rows.get("drawn-live", {}).get("waiting") == ["also dim the tracklist"],
          rows.get("drawn-live", {}).get("waiting"))
    said = agents.send("drawn-dead", "Widen the clock", "decision", "never mind")
    agents.refresh()
    spin(250)
    check("a note to an agent that has finished goes to the inbox instead",
          "inbox" in said and "never mind" in prop(win, "queuedNotes"),
          (said, prop(win, "queuedNotes")))
    # ---- THE ONE BOX, and the conservation of what he types into it ----
    # It is the control surface: free text, enter, into the inbox. The claim it
    # makes is not "sent" but "never lost", so this is a conservation check like
    # every other path through the box — the sentence is on disk exactly once,
    # in exactly one of the three directories, and it is the same write path a
    # note to a running agent takes rather than a second one.
    boxes = [it for it in descendants(win.contentItem())
             if it.property("placeholder") is not None]
    # "Not attached" is the point: every OTHER box on the page belongs to
    # something — a running agent's card, or (since he asked to be able to
    # answer a chore where it sits) one `to do` bullet's own reply. There is
    # exactly one that belongs to nothing and starts work from scratch.
    unattached = [b for b in boxes
                  if str(b.property("placeholder")).startswith("type anything")]
    check("the page has ONE box that is not attached to any agent",
          len(unattached) == 1,
          [str(b.property("placeholder")) for b in boxes])
    check("...and every other box says what it IS attached to",
          all("reply to this one" in str(b.property("placeholder"))
              or "send it a command" in str(b.property("placeholder"))
              or "leave a note" in str(b.property("placeholder"))
              for b in boxes if b not in unattached),
          [str(b.property("placeholder")) for b in boxes])
    typed = "the scrollbar arrows feel sluggish"
    said = keep[5].send("", "", "", typed)
    spin(200)
    check("what he types with nothing named goes to the inbox, and says only that",
          "inbox" in said and "orchestrator" in said, said)
    where = [(d, n) for d in ("queue", "taken")
             for n in os.listdir(ba.inbox_dir(d))
             if n.endswith(".json") and typed in open(
                 os.path.join(ba.inbox_dir(d), n)).read()]
    check("...and it is on disk exactly once, in exactly one directory",
          len(where) == 1 and where[0][0] == "queue", where)
    check("...and appears on the board as waiting, so it is never invisible",
          typed in prop(win, "queuedNotes"), prop(win, "queuedNotes"))

    # ---- the cards, grouped by what each agent is OBSERVED doing ----
    import boardphase as bph
    import boardwork as bw
    os.environ["BOARD_TRANSCRIPTS"] = os.path.join(tmp, "transcripts")
    u = "22222222-3333-4444-5555-666666666666"
    _tsc(tmp, u, [("Read", {"file_path": "/x/vtbclient.py"}),
                  ("Edit", {"file_path": "/x/vtbclient.py"})])
    ba.register("w-code", "Wire FOCUS through vtbclient", os.getpid(),
                kind="worker", where="apps/pylib/**", session=u)
    bph.claim("w-code", "testing", "the vtbclient parser")
    u2 = "33333333-4444-5555-6666-777777777777"
    _tsc(tmp, u2, [("Grep", {"pattern": "activewindow"})])
    ba.register("w-read", "Find where focus is decided", os.getpid(),
                kind="worker", where="hyprvtb", session=u2)
    agents.refresh()
    spin(300)
    groups = {g["label"]: [r["title"] for r in g["rows"]]
              for g in prop(win, "agentGroups")}
    check("cards are grouped by phase, under his own words",
          "coding" in groups and "researching" in groups, list(groups))
    check("...by what the agent is OBSERVED doing, not by what it says",
          "Wire FOCUS through vtbclient" in groups.get("coding", []), groups)
    rows = {r["title"]: r for g in prop(win, "agentGroups") for r in g["rows"]}
    card = rows.get("Wire FOCUS through vtbclient", {})
    check("...and the card carries BOTH statements, neither standing in for the other",
          card.get("says") == "testing - the vtbclient parser"
          and card.get("actually") == "editing vtbclient.py",
          (card.get("says"), card.get("actually")))
    check("an agent that has said nothing shows no claim at all",
          rows.get("Find where focus is decided", {}).get("says") == "",
          rows.get("Find where focus is decided"))
    check("no card carries a time, an age or a count",
          not any(re.search(r"\b\d+\s*(s|m|h|min|sec|hour|ago)\b",
                            str(r.get("says", "")) + " " + str(r.get("actually", ""))
                            + " " + str(r.get("detail", "")))
                  for r in rows.values()), list(rows.values())[:1])

    # ...with the store's own sections folded away, so the shot is of THIS
    # section rather than of whatever happens to be above it.
    win.setProperty("collapsed", {"needs": True, "flight": True, "landed": True})
    spin(300)
    shot(win, "06-agents")
    win.setProperty("collapsed", {})
    spin(200)
    ba.unregister("w-code")
    ba.unregister("w-read")
    # ...and a finished agent leaves the list rather than rotting in it
    os.unlink(bm.stash_file("drawn-dead"))
    os.unlink(bm.stash_file("drawn-live"))
    agents.refresh()
    spin(250)
    check("an agent that is done leaves the list",
          not [a for a in prop(win, "agents") if a["kind"] != "session"],
          prop(win, "agents"))
    check("...and what he wrote is still on the board's queue, not lost",
          len(prop(win, "queuedNotes")) >= 1, prop(win, "queuedNotes"))

    # ---- the empty NEEDS YOU state, the one he will see most often ----
    empty = os.path.join(tmp, "empty.md")
    open(empty, "w").write(EMPTY_FIXTURE)
    engine2, win2, keep2 = build(app, empty)
    spin(400)
    check("an empty board has nothing needing him",
          len(prop(win2, "needs")) == 0 and len(prop(win2, "todo")) == 0)
    check("...and still shows what is moving and what landed",
          len(prop(win2, "flight")) == 1 and len(prop(win2, "landed")) == 1)
    shot(win2, "03-empty-needs-you")

    # NOTHING RUNNING is the resting state of the agents section, and the one he
    # will see most often — it has to read as finished, not as broken. The
    # harness stubs /proc away entirely (a machine with no agent and no session
    # on it), because the process that runs this test is itself under a Claude
    # session and would otherwise be in the list.
    real_procs = ba._procs
    ba._procs = lambda: {}
    try:
        keep2[5].refresh()
        spin(250)
        check("with nothing running the agents section is empty, not broken",
              prop(win2, "agents") == [], prop(win2, "agents"))
        win2.setProperty("collapsed", {"needs": True, "flight": True, "landed": True})
        spin(300)
        shot(win2, "03b-agents-empty")
        win2.setProperty("collapsed", {})
        spin(200)
    finally:
        ba._procs = real_procs

    # ---- clearing a chore, and putting it back (§10.3) ----
    # Through the same slots the menu entries call, in the real window, against
    # a real store: he asked for this because the section only ever grew.
    line = prop(win, "todo")[0]["line"]
    text = prop(win, "todo")[0]["text"]
    check("nothing is offered as an undo before anything is removed",
          board.property("undoText") == "", board.property("undoText"))
    check("removing a chore is written back", board.removeTodo(line) is True)
    spin(200)
    check("...and it leaves the drawn list, which is now empty",
          len(prop(win, "todo")) == 0, prop(win, "todo"))
    check("...and it is out of the file, with the section still there",
          "- **Relaunch `reader`**" not in B.read(path)
          and "## WAITING ON YOU TO DO" in B.read(path))
    check("...and the undo now names what it would put back",
          board.property("undoText") == text, board.property("undoText"))
    check("putting it back works", board.undoRemove() is True)
    spin(200)
    check("...restoring the drawn row",
          len(prop(win, "todo")) == 1 and prop(win, "todo")[0]["text"] == text,
          prop(win, "todo"))
    check("...and taking the undo away with it, so it is not offered twice",
          board.property("undoText") == "", board.property("undoText"))
    check("a line that is no longer there is refused, not obeyed",
          board.removeTodo(9999) is False)

    # ---- and a DOUBLE click does it too, which is how he asked to do it ----
    # *"i should be able to just double click on stuff in the to do when you
    # feel like it section to remove them"*. It did nothing for a day: the
    # row's MouseArea was `acceptedButtons: Qt.RightButton`, so the left button
    # never reached it at all. Driven with real QMouseEvents against the real
    # delegate, because that is the only thing that would have caught it — the
    # slot behind it was always fine.
    # QTest, not hand-built QMouseEvents: Qt Quick derives a double click from
    # its own press bookkeeping, so a MouseButtonDblClick posted straight at the
    # window is silently dropped and every version of this test passes. Measured
    # — a hand-built sequence reached `onClicked` and never `onDoubleClicked`.
    from PySide6.QtCore import QPointF, Qt                             # noqa: E402
    from PySide6.QtTest import QTest                                   # noqa: E402

    def at(item, dy=8):
        return item.mapToScene(QPointF(item.width() / 2, dy)).toPoint()

    rows = [it for it in descendants(win.contentItem())
            if it.property("replying") is not None]
    check("every `to do` bullet is drawn as a row that can be replied to",
          len(rows) == len(prop(win, "todo")) == 1, len(rows))
    if rows:
        QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, at(rows[0]))
        spin(200)
        check("a single left click leaves the chore exactly where it was",
              len(prop(win, "todo")) == 1, prop(win, "todo"))
        QTest.mouseDClick(win, Qt.LeftButton, Qt.NoModifier, at(rows[0]))
        spin(250)
        check("...and a DOUBLE click removes it", len(prop(win, "todo")) == 0,
              prop(win, "todo"))
        check("...through the same one-level undo the menu offers",
              board.property("undoText") == text, board.property("undoText"))
        board.undoRemove()
        spin(200)

    # ---- `reply`, the top entry on a chore's own menu ----
    # *"the top item on the right click menu for to do items should be `reply`
    # that lets me reply directly to it instead of typing in the top box like i
    # am doing now"*. It is not a second write path: `boardagents.send()` with
    # nothing named, exactly as the top box does, with the chore QUOTED so
    # whoever reads it half an hour later knows which one he meant.
    chore = prop(win, "todo")[0]
    # Re-found: the Repeater rebuilt its delegates when the chore came back, so
    # the item captured above is a dangling pointer (it segfaults, promptly).
    rows = [it for it in descendants(win.contentItem())
            if it.property("replying") is not None]
    win.todoMenu(chore, 20, 20, rows[0] if rows else None)
    spin(150)
    menus = [it for it in descendants(win.contentItem())
             if it.property("items") is not None and it.isVisible()]
    labels = [str(i.get("label", ""))
              for i in menus[0].property("items").toVariant()] if menus else []
    check("`reply` is the TOP entry on a chore's right-click menu",
          labels[:1] == ["reply"], labels)
    check("...and the one destructive entry is still LAST, behind a separator",
          labels[-1:] == ["remove this from the list"], labels)
    if menus:
        menus[0].close()
    spin(100)
    boxed = [it for it in descendants(rows[0])
             if "reply to this one" in str(it.property("placeholder"))]
    check("...and the chore has a reply box of its own, closed until he asks",
          len(boxed) == 1 and not boxed[0].isVisible(),
          [b.isVisible() for b in boxed])
    rows[0].beginReply()
    spin(200)
    check("...which `reply` opens in place, rather than sending him to the top box",
          bool(boxed) and boxed[0].isVisible() and rows[0].property("replying") is True,
          [b.isVisible() for b in boxed])
    before = len(ba.pending())
    ok = win.replyToTodo(chore, "yes, that one, and make it dim")
    check("replying to a chore goes somewhere and says so", ok is True, ok)
    q = [m["text"] for m in ba.pending()]
    check("...on disk exactly once, in the same queue the top box writes to",
          len(q) == before + 1, q)
    check("...quoting the chore, so the reply is not context-free",
          any(chore["text"] in t and "make it dim" in t for t in q), q)
    check("an empty reply writes nothing at all",
          win.replyToTodo(chore, "   ") is False
          and len(ba.pending()) == before + 1)

    # ---- it survives the small screen (§5.6) ----
    win2.setWidth(420)
    win2.setHeight(600)
    spin(250)
    shot(win2, "04-narrow")
    win2.setWidth(880)
    win2.setHeight(880)

    # ---- an unreadable store says so rather than drawing an empty board ----
    engine3, win3, keep3 = build(app, os.path.join(tmp, "nope.md"))
    spin(250)
    check("a missing store reports the reason", keep3[3].property("error") != "",
          keep3[3].property("error"))
    shot(win3, "05-missing-store")


def main():
    from PySide6.QtGui import QGuiApplication
    global SHOTS
    if "--shots" in sys.argv:
        SHOTS = os.path.abspath(sys.argv[sys.argv.index("--shots") + 1])
        os.makedirs(SHOTS, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["XDG_STATE_HOME"] = os.path.join(tmp, "state")
        os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp, "config")
        os.makedirs(os.path.join(tmp, "rt"))
        os.makedirs(os.path.join(tmp, "mv"))
        os.makedirs(os.path.join(tmp, "win"))
        test_roundtrip(os.path.join(tmp, "rt"))
        test_moves(os.path.join(tmp, "mv"))
        os.makedirs(os.path.join(tmp, "td"))
        test_todo_remove(os.path.join(tmp, "td"))
        test_agents(tmp)
        test_phase(tmp)
        os.makedirs(os.path.join(tmp, "work"))
        test_work(os.path.join(tmp, "work"))
        app = QGuiApplication(sys.argv)
        test_real_store()
        test_real_window(app)
        test_window(app, os.path.join(tmp, "win"))
    print()
    if FAILS:
        print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
