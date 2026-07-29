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
    bm.note("PARTIAL: **Relaunch `thing`** - live source.", path=path)
    doc5 = B.parse(B.read(path))
    # TWO lines, not one: the bullet and the `<!-- placed: -->` stamp under it
    # that says when it went on the board.
    check("a note lands as one bullet in WAITING ON YOU TO DO",
          len(doc5["todo"]) == 2
          and len(B.read(path).splitlines()) == len(src.splitlines()) + 2,
          [t["text"] for t in doc5["todo"]])
    check("...and that bullet knows when it was placed",
          B.parse(B.read(path))["todo"][-1]["placed"] != "",
          [(t["text"][:24], t["placed"]) for t in doc5["todo"]])

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
    # Verbatim, checked by taking the bullet back OUT: it costs two lines now
    # (itself and its `placed` stamp), and `remove_todo` spans both — so if the
    # file with that one bullet removed is the file before it was written, the
    # reclaim touched nothing else.
    backdoc = B.parse(back)
    check("...verbatim, with only a bullet added to say so",
          "".join(B.remove_todo(backdoc["lines"], backdoc["todo"][-1])) == src,
          len(back.splitlines()) - len(src.splitlines()))
    check("...and the bullet says what happened",
          any("is gone" in t["text"] for t in B.parse(back)["todo"]),
          [t["text"] for t in B.parse(back)["todo"]])

    # ---- THE ROWS NOTHING OWNS: the section has to be able to shrink ----
    # `reconcile` only ever sees this host's stashes, so a row written by hand,
    # or by the other machine, or before the stash existed, had no exit at all
    # and IN FLIGHT could only grow. His words: it "doesnt update at all".
    src = reset()
    rows = [r["what"] for r in bm.unowned(path=path)]
    check("a row no stash on this host owns is reported",
          rows == ["A thing being built", "Another thing"], rows)

    got = bm.stall("A thing being built", path=path)
    doc6 = B.parse(B.read(path))
    check("stall takes the row out of IN FLIGHT",
          [r["what"] for r in doc6["flight"]] == ["Another thing"],
          [r["what"] for r in doc6["flight"]])
    check("...and it is MOVED, not dropped: the cells become one bullet",
          len(doc6["todo"]) == 2
          and "A thing being built" in doc6["todo"][-1]["text"]
          and "apps/thing/**" in doc6["todo"][-1]["text"]
          and "with a note" in doc6["todo"][-1]["text"],
          [t["text"] for t in doc6["todo"]])
    check("...one row out, one bullet in, and nothing else touched",
          # net +1: one table row leaves, and the bullet that replaces it costs
          # two lines — itself and the `placed` stamp under it.
          len(B.read(path).splitlines()) == len(src.splitlines()) + 1,
          lines_differing(src, B.read(path)))
    check("...and it says which row it moved", got["what"] == "A thing being built")

    # a row this host DOES own keeps its real exit: `back` restores his question
    src = reset()
    d = B.parse(src)
    B.write(path, "".join(B.set_answer(d["lines"], d["needs"][0], "do it")))
    bm.start("1", path=path)
    check("a stashed decision is NOT reported as unowned",
          "First question?" not in [r["what"] for r in bm.unowned(path=path)],
          [r["what"] for r in bm.unowned(path=path)])
    before = B.read(path)
    try:
        bm.stall("First question?", path=path)
        check("stall refuses a row whose decision is recoverable", False)
    except bm.BoardError as e:
        check("stall refuses a row whose decision is recoverable", "back" in str(e),
              str(e))
    check("...and the refusal wrote nothing", B.read(path) == before)

    # ---- the write is guarded against a racing writer ----
    reset()
    hits = {"n": 0}

    def racer(doc):
        hits["n"] += 1
        if hits["n"] == 1:                    # somebody else writes mid-edit
            open(path, "a").write("\nan agent appended this.\n")
        return B.add_todo_bullet(doc["lines"], doc, "- INFORMATION: late\n")

    B.edit(path, racer)
    txt = B.read(path)
    check("an edit computed from stale bytes is retried, not landed",
          hits["n"] == 2 and "an agent appended this." in txt
          and txt.count("- INFORMATION: late") == 1,
          (hits["n"], txt.count("- INFORMATION: late")))

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


# --------------------------------- 1b1. LANDED: recording a commit, and its time
def test_landed(tmp):
    """The section that stopped growing, and why.

    `land` used to need an IN FLIGHT row, and a WORKER dispatched out of the box
    never has one — only a decision agent does. So every commit the fan-out
    produced was unrecordable, `note` was all a worker could reach, and LANDED
    sat at the last day a decision agent had finished something while the repo
    ran on. Both halves are asserted here: a commit lands with no row at all, and
    it carries the commit's OWN time.

    The time is backward compatible IN BOTH DIRECTIONS, which is a real
    constraint and not a nicety: this file syncs between `top` and `book` and
    either machine may be running the older app. A two-cell row parses with no
    time; a three-cell row read by the old parser simply loses the third cell.
    """
    import subprocess

    import boardmove as bm
    import boardparse as B

    path = os.path.join(tmp, "board.md")

    def reset():
        open(path, "w").write(FIXTURE)
        return FIXTURE

    # ---- the old shape still parses, and gains nothing it was not given ----
    reset()
    doc = B.parse(B.read(path))
    check("a LANDED row written before `when` existed still parses",
          [r["commit"] for r in doc["landed"][0]["rows"]] == ["abc1234", "def5678"],
          [r["commit"] for r in doc["landed"][0]["rows"]])
    check("...with an empty time, invented for nobody",
          all(r["when"] == "" for r in doc["landed"][0]["rows"]))

    # ---- a commit with NO IN FLIGHT row: the whole point of the fix ----
    before = B.read(path)
    # ...into the group the fixture already has, which is the two-column shape
    # every existing group in the real store is in.
    got = bm.land("", "0badc0d", what="board: land with no row", when="3:42 pm",
                  date="2026-07-28", path=path)
    doc = B.parse(B.read(path))
    row = [r for g in doc["landed"] for r in g["rows"] if r["commit"] == "0badc0d"]
    check("a worker with no IN FLIGHT row can still record its commit",
          len(row) == 1 and row[0]["what"] == "board: land with no row",
          [(g["date"], [r["commit"] for r in g["rows"]]) for g in doc["landed"]])
    check("...and nothing was moved out of IN FLIGHT for it",
          got == {} and len(doc["flight"]) == len(B.parse(before)["flight"]))
    check("...carrying the time, 12-hour, on its own row",
          row and row[0]["when"] == "3:42 pm", row and row[0]["when"])

    # ---- ...and it is still a targeted line edit ----
    after = B.read(path)
    kept = [ln for ln in before.splitlines(True) if ln not in after.splitlines(True)]
    check("...leaving every line it did not name alone, except the widened head",
          all(ln.startswith("| Commit |") or ln.startswith("|---|") for ln in kept),
          kept[:3])
    check("a group that gains a timed row gains the `When` header with it",
          "| Commit | What | When |\n" in after and "| Commit | What |\n" not in after)
    check("...and the old rows in it are untouched",
          "| `abc1234` | did a thing |\n" in after)

    # ---- a row with no commit to read a time from stays two cells ----
    bm.land("", "no change", what="decision settled: nothing to build", when="",
            path=path)
    txt = B.read(path)
    check("a row with no time is written the old way, not with an empty cell",
          "| `no change` | decision settled: nothing to build |\n" in txt,
          [ln for ln in txt.splitlines() if "no change" in ln])

    # ---- the time comes from GIT, not from now ----
    head = subprocess.run(["git", "-C", os.path.expanduser("~/nix"),
                           "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    want = subprocess.run(["git", "-C", os.path.expanduser("~/nix"), "show", "-s",
                           "--format=%cd", "--date=format:%I:%M %p", head],
                          capture_output=True, text=True).stdout.strip()
    check("a commit's time is read from git, in local 12-hour form",
          bm.commit_time(head) == want.lstrip("0").lower(),
          (bm.commit_time(head), want))
    check("...and a hash that resolves nowhere is simply timeless",
          bm.commit_time("0000000") == "" and bm.commit_time("no change") == "")

    # ---- and the CLI reaches it with no selector at all ----
    reset()
    cli = os.path.join(BOARD, "tools", "boardctl.py")
    p = subprocess.run([sys.executable, cli, "--board", path, "land",
                        "--commit", "feedbee", "--what", "board: via the CLI"],
                       capture_output=True, text=True)
    check("boardctl land takes no selector",
          p.returncode == 0 and "nothing was moved" in p.stdout,
          (p.stdout.strip()[:120], p.stderr.strip()[:120]))
    p = subprocess.run([sys.executable, cli, "--board", path, "land", "nothing-here",
                        "--commit", "feedbee"], capture_output=True, text=True)
    check("...but a selector that matches nothing and no --what is refused",
          p.returncode == 1 and "no line to record" in p.stderr,
          p.stderr.strip()[:160])


# ------------------- 1b1b. everything in NEEDS YOU says WHEN it was put there
def test_placed(tmp):
    """*"mesages in the needs you section should all have the time they were
    placed on the board indicated on them."*

    Both shapes drawn under that heading carry it — a decision and a WAITING
    bullet — and the four claims that keep it honest are:

      * the stamp is written by the WRITER, at the moment the item goes up, so
        it is a fact and not a guess at read time;
      * it is OPTIONAL, in both directions. The store is full of items that
        predate it and `board.md` syncs between two machines that may be running
        different copies of this app, so a missing one draws NO time — never an
        empty box and never an invented one;
      * it is inside the span the bullet is removed and restored by, so clearing
        a chore does not leave its stamp behind as an orphan comment;
      * it is ABSOLUTE. No age, no "3 days ago" — the no-pressure requirement
        (`AGENTS.md`) forbids a clock running against him.
    """
    import boardparse as B
    import boardmove as bm

    check("an unreadable or absent stamp is no time at all, never a wrong one",
          (B.format_placed(""), B.format_placed("   "), B.format_placed("soon"),
           B.format_placed("2026-13-99T99:99")) == ("", "", "", ""))
    check("...and a readable one is the clock LANDED already uses: 12-hour, lower",
          (B.format_placed("2026-07-29T15:42"), B.format_placed("2026-07-04T09:05"),
           B.format_placed("2026-07-04")) == ("jul 29 3:42 pm", "jul 4 9:05 am",
                                              "jul 4"),
          B.format_placed("2026-07-29T15:42"))
    # The DATE is what makes it different from a LANDED row's `when`: that one
    # sits under a `### <date>` heading and this one can sit for a week with
    # nothing around it to say which day. And it fits the width the QML reserves.
    check("...and it never outgrows the column the QML reserves for it",
          max(len(B.format_placed("2026-%02d-%02dT23:04" % (m, 28)))
              for m in range(1, 13)) <= 15,
          sorted({B.format_placed("2026-%02d-28T23:04" % m) for m in range(1, 13)}))

    path = os.path.join(tmp, "board.md")
    B.write(path, FIXTURE)
    doc = B.parse(B.read(path))
    check("an item written before any of this draws no time, and parses fine",
          [d["placed"] for d in doc["needs"]] == ["", ""]
          and [t["placed"] for t in doc["todo"]] == [""],
          [d["placed"] for d in doc["needs"]])

    # ---- a decision: the stamp goes under its own `###` line ----
    src = B.read(path)
    key = bm.ask("How far should the fade reach?", options=["apps only", "both"],
                 if_unanswered="the apps get it", path=path)
    after = B.read(path)
    doc = B.parse(after)
    new = [d for d in doc["needs"] if d["key"] == key][0]
    check("a question an agent asks says when it was asked",
          new["placed"] != "" and new["placedLine"] == new["titleLine"] + 1,
          (new["placedRaw"], new["placed"]))
    check("...as an HTML comment, so the file still reads cleanly for him",
          after.splitlines()[new["placedLine"]].startswith("<!-- placed:"),
          after.splitlines()[new["placedLine"]])
    check("...and it is not prose: nothing of it reaches what gets drawn",
          "placed" not in new["title"]
          and all("placed" not in b["text"] for b in new["body"]),
          new["title"])
    check("...and the file still round-trips byte for byte", "".join(doc["lines"]) == after)

    # It travels with the item. A relocation cuts the decision's RAW lines, so
    # the stamp goes into IN FLIGHT's stash with them and comes back with them.
    d = B.parse(B.read(path))
    B.write(path, "".join(B.set_answer(d["lines"], d["needs"][0], "the first way")))
    src = B.read(path)
    bm.start("1", path=path)
    bm.give_back("1", path=path)
    check("a stamp survives IN FLIGHT and back, like every other line of the item",
          B.read(path) == src,
          [ln for ln in B.read(path).splitlines() if ln not in src.splitlines()][:4])

    # ---- a bullet: the stamp goes under its LAST line ----
    B.write(path, FIXTURE)
    bm.note("INFORMATION: one\nCOMPLETION: two", path=path)
    doc = B.parse(B.read(path))
    check("EVERY bullet of a multi-bullet note is stamped, not just the last",
          [t["placed"] != "" for t in doc["todo"]] == [False, True, True],
          [(t["text"][:14], t["placed"]) for t in doc["todo"]])
    check("...and the stamp is not drawn as part of the message",
          all("placed" not in t["text"] for t in doc["todo"]),
          [t["text"][-30:] for t in doc["todo"]])
    check("...and the bullet's span covers it, so removal takes both",
          all(t["endLine"] == t["line"] + 1 for t in doc["todo"][1:]),
          [(t["line"], t["endLine"]) for t in doc["todo"]])
    stamped = doc["todo"][1]
    block = doc["lines"][stamped["line"]:stamped["endLine"] + 1]
    gone = B.remove_todo(doc["lines"], stamped)
    check("...leaving no orphan comment behind",
          "".join(gone).count("<!-- placed:")
          == "".join(doc["lines"]).count("<!-- placed:") - 1
          and len(B.parse("".join(gone))["todo"]) == 2,
          [(t["text"][:14], t["placed"]) for t in B.parse("".join(gone))["todo"]])
    back = B.parse("".join(gone))
    check("...and the undo puts the bullet AND its time back",
          [t["placed"] != "" for t in
           B.parse("".join(B.add_todo_block(back["lines"], back, block)))["todo"]]
          == [False, True, True],
          [t["placed"] for t in
           B.parse("".join(B.add_todo_block(back["lines"], back, block)))["todo"]])

    # A bullet that wraps: the new one must land AFTER the continuation line and
    # after the stamp, not inside either. This is what `endLine` buys.
    B.write(path, FIXTURE.replace(
        "- **Relaunch `reader`** - live source, no hot reload.",
        "- **Relaunch `reader`** - live source,\n  no hot reload."))
    bm.note("QUESTION: after the wrap, please", path=path)
    doc = B.parse(B.read(path))
    check("a new bullet lands after a wrapped one, never inside it",
          [t["text"] for t in doc["todo"]]
          == ["Relaunch reader - live source, no hot reload.",
              "QUESTION: after the wrap, please"],
          [t["text"] for t in doc["todo"]])

    # ---- nothing here is a clock running against him ----
    # The same stamp, read a day apart, must draw the same words: an item that
    # aged overnight is not allowed to say so (`AGENTS.md`, the no-pressure
    # requirement). That is what makes this an absolute time and not an age.
    import inspect
    body = inspect.getsource(B.format_placed).split('"""')[-1]
    check("what draws the time cannot see the clock, so it cannot become an age",
          "now(" not in body and "today(" not in body and "time.time" not in body,
          [ln.strip() for ln in body.splitlines() if "now" in ln][:3])


# ------------------------- 1b1a. every WAITING bullet says WHAT IT IS, in a word
def test_todo_tags(tmp):
    """*"messages in the to do section should start with either QUESTION:
    INFORMATION: COMPLETION: or something like those [...] so that the user can
    easily know what that message is about. any sort of elaboration or background
    should go after the short description"*.

    Three claims, and the first is the one that keeps it true a month from now:

      * **a writer that emits an untagged bullet FAILS.** Not "is defaulted to
        INFORMATION:" — a failure quietly filed as information is exactly what
        the tag exists to prevent — and not "is caught in review": the check is
        in `add_todo_bullet`, the one function every writer of this section goes
        through, so a new writer cannot be added that forgets.
      * **every tag has a writer.** A vocabulary with a word nothing can say is
        a vocabulary he has to learn twice.
      * **READING is untouched.** The store is full of untagged bullets written
        before this existed, and it is HIS file: they parse, they draw, and
        nothing rewrites them.
    """
    import boardmove as bm
    import boardparse as B

    path = os.path.join(tmp, "board.md")
    open(path, "w").write(FIXTURE)

    check("the tag set is short and is his three plus the two the machine needs",
          B.TODO_TAGS == ("QUESTION", "INFORMATION", "COMPLETION", "PARTIAL",
                          "FAILED"), B.TODO_TAGS)

    # ---- an untagged bullet is REFUSED, and nothing is written ----
    before = B.read(path)
    for bad in ("**Relaunch `board`** - live source.",
                "- **Relaunch `board`** - live source.",
                "- relaunch: it is live source",        # not one of the tags
                "- completion: **it** - lowercase is not a tag",
                "- COMPLETION:**it** - no space after the tag",
                "- COMPLETION:"):                       # tag and nothing else
        try:
            bm.note(bad, path=path)
            wrote = B.read(path) != before
            check("an untagged bullet is refused: %r" % bad[:34], False,
                  "it was written" if wrote else "it returned quietly")
        except B.BoardError as e:
            check("an untagged bullet is refused: %r" % bad[:34],
                  B.read(path) == before, str(e)[:90])

    check("an empty note writes nothing and says so",
          bm.note("", path=path) is False and B.read(path) == before)

    # ...and a TAGGED one lands, with his ordering intact: tag, short
    # description, then the elaboration.
    check("a tagged bullet lands",
          bm.note("COMPLETION: **the tag rule** - every writer emits one now, "
                  "and this sentence is the background that comes after.",
                  path=path))
    doc = B.parse(B.read(path))
    check("...and it reads tag first, description second",
          doc["todo"][-1]["text"].startswith("COMPLETION: the tag rule - "),
          doc["todo"][-1]["text"][:60])

    # ---- the orchestrator writes one line per task IN ONE CALL ----
    # Its note is several bullets in one string, and on 2026-07-29 the second
    # line went in without its `- ` and was drawn as part of the bullet above it.
    # Every line is checked, so that shape is refused rather than landed.
    before = B.read(path)
    try:
        bm.note("INFORMATION: **one** - handed out.\n"
                "**two** - handed out.", path=path)
        check("a multi-line note with an untagged second line is refused", False,
              "it was written")
    except B.BoardError:
        check("a multi-line note with an untagged second line is refused",
              B.read(path) == before)
    check("...while every line tagged is fine, and lands as separate bullets",
          bm.note("INFORMATION: **one** - handed to Marbas, nothing landed yet.\n"
                  "INFORMATION: **two** - handed to Zepar, nothing landed yet.",
                  path=path)
          and len(B.parse(B.read(path))["todo"]) == 4,
          [t["text"] for t in B.parse(B.read(path))["todo"]])
    check("...and an INDENTED continuation line needs no tag of its own",
          bm.note("PARTIAL: **a wrapped one** - the first line,\n"
                  "  and the background wrapped onto a second.", path=path))

    # ---- READING an old bullet is untouched ----
    d = B.parse(FIXTURE)
    old = d["todo"]
    check("an untagged bullet written before this still parses and draws",
          len(old) == 1 and old[0]["text"].startswith("Relaunch reader - live"),
          [t["text"] for t in old])
    # ...and the two paths that handle an OLD bullet do not run the new check:
    # removing one and putting it back are a restore, not a write, and validating
    # them would make his own untagged lines unremovable and unrestorable.
    block = d["lines"][old[0]["line"]:old[0]["endLine"] + 1]
    gone = B.remove_todo(d["lines"], old[0])
    back = "".join(B.add_todo_block(gone, B.parse("".join(gone)), block))
    check("...and it can still be removed, and put back verbatim",
          not [l for l in gone if "Relaunch `reader`" in l]
          and back.count(block[0]) == 1
          and sorted(back.splitlines()) == sorted(FIXTURE.splitlines()),
          block[0].strip())

    # ---- every MECHANICAL writer emits one ----
    open(path, "w").write(FIXTURE)
    got = bm.stall("A thing being built", path=path)
    check("stall's bullet carries a tag",
          B.parse(B.read(path))["todo"][-1]["text"].startswith("INFORMATION: "),
          [t["text"][:40] for t in B.parse(B.read(path))["todo"]])
    check("...and it is the row it says it is", got["what"] == "A thing being built")

    open(path, "w").write(FIXTURE)
    d = B.parse(B.read(path))
    B.write(path, "".join(B.set_answer(d["lines"], d["needs"][0], "do it")))
    dead = os.fork()
    if dead == 0:
        os._exit(0)
    os.waitpid(dead, 0)
    bm.start("1", pid=dead, path=path)
    bm.reconcile(path=path)
    check("reconcile's dead-agent bullet carries a tag, and it is FAILED",
          B.parse(B.read(path))["todo"][-1]["text"].startswith("FAILED: "),
          [t["text"][:40] for t in B.parse(B.read(path))["todo"]])

    # board-watch is DEPLOYED by home-manager, so it is checked as SOURCE rather
    # than imported: on `book` the copy that runs is the last one a rebuild put
    # in the store, and this harness must fail on the source it can see.
    watch = os.path.join(os.path.dirname(APPS), "home", "srvs",
                         "board-watch-files", "board-watch.py")
    src = open(watch).read() if os.path.exists(watch) else ""
    tmpl = re.findall(r'^\s*"- (.*?)\*\*', src, re.M)
    check("every board-watch failure template starts with FAILED:",
          bool(tmpl) and all(t.strip() == "FAILED:" for t in tmpl), tmpl)

    # ---- and every tag in the set has a writer that can emit it ----
    prompts = src + open(os.path.join(BOARD, "boardwork.py")).read() \
        + open(os.path.join(BOARD, "boardmove.py")).read()
    missing = [t for t in B.TODO_TAGS if ("%s:" % t) not in prompts]
    check("no tag exists that no writer can emit", not missing, missing)

    # ---- ...and the READ side groups by that same word, for the view ----
    # *"the information, completion, partial etc of a message should be used to
    # organize them on the board. under the needs you section there should be
    # sub sections for each of these headers"*. A VIEW change: the store keeps
    # one flat list, `parse()` buckets it, and a bullet in a group is the same
    # dict (same `line`) the flat list holds, so removing and restoring one is
    # the edit it always was.
    open(path, "w").write(FIXTURE)
    for b in ("INFORMATION: a fact.", "COMPLETION: it landed.",
              "FAILED: nothing landed.", "QUESTION: say the word?",
              "PARTIAL: half of it.", "COMPLETION: this one too."):
        bm.note(b, path=path)
    d = B.parse(B.read(path))
    groups = d["todoGroups"]
    check("the WAITING bullets are grouped by their tag, in TODO_ORDER",
          [g["tag"] for g in groups]
          == ["", "QUESTION", "FAILED", "PARTIAL", "COMPLETION", "INFORMATION"],
          [g["tag"] for g in groups])
    check("...QUESTION first, because nothing moves until he says a word",
          groups[1]["tag"] == "QUESTION" and groups[1]["label"] == "question")
    check("...and FAILED is not buried under the good news",
          [g["tag"] for g in groups].index("FAILED")
          < [g["tag"] for g in groups].index("COMPLETION"))
    check("...an untagged bullet is first and gets NO heading",
          groups[0]["tag"] == "" and groups[0]["label"] == ""
          and len(groups[0]["items"]) == 1, groups[0]["items"])
    check("...a tag with two bullets is one group, in file order",
          [t["line"] for t in groups[-2]["items"]]
          == sorted(t["line"] for t in groups[-2]["items"])
          and len(groups[-2]["items"]) == 2,
          [t["text"] for t in groups[-2]["items"]])
    flat = [t for g in groups for t in g["items"]]
    check("...every bullet is in exactly one group and none is invented",
          sorted(t["line"] for t in flat)
          == sorted(t["line"] for t in d["todo"]),
          (len(flat), len(d["todo"])))
    check("...and a tag with no bullets gets no group, so no empty heading",
          "QUESTION" not in [g["tag"] for g in B.parse(FIXTURE)["todoGroups"]],
          [g["tag"] for g in B.parse(FIXTURE)["todoGroups"]])
    # The grouping is a read, and a read must not touch the file.
    before = B.read(path)
    B.parse(before)
    check("...and grouping writes nothing", B.read(path) == before)


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
    again = "".join(B.add_todo_bullet(d["lines"], d,
                                      "- INFORMATION: something new\n"))
    check("...and a new chore still lands inside the section",
          B.parse(again)["todo"][0]["text"] == "INFORMATION: something new"
          and again.index("- INFORMATION: something new")
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
        for name in ("to", "queue", "taken", "dropped", "editing"):
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
    # ---- ...and he can change his mind while it is still queued ----
    # *"allow the user to remove queued waiting for next agent items or edit
    # them in place"*. Both act on a message board-watch may be draining at
    # this instant, so both are `os.replace` claims like every other move here:
    # they win, or they report the message gone. The conservation check is the
    # same one — after each path it is on disk exactly once.
    was = total()
    ba.send("rename the buttons")
    ba.send("look again at the fan curve")
    mid = ba.msg_id([m for m in ba.pending() if m["text"] == "rename the buttons"][0])
    edited = ba.edit_queued(mid, "rename the buttons, and the tooltips")
    check("he can rewrite a queued message in place",
          edited["text"] == "rename the buttons, and the tooltips"
          and [m["text"] for m in ba.pending()
               if ba.msg_id(m) == mid] == ["rename the buttons, and the tooltips"],
          edited)
    check("...under its own name, so it keeps its place in the queue",
          ba.msg_id(edited) == mid and total() == was + 2,
          (ba.msg_id(edited), total()))
    check("...and nothing is left claimed by the edit",
          os.listdir(ba.inbox_dir("editing")) == [],
          os.listdir(ba.inbox_dir("editing")))
    check("...and the message is still on disk exactly once",
          where_is("rename the buttons, and the tooltips") == ["queue"],
          where_is("rename the buttons, and the tooltips"))

    gone = ba.remove_queued(mid)
    check("he can take a queued message off the queue",
          gone is not None
          and mid not in [ba.msg_id(m) for m in ba.pending()],
          [ba.msg_id(m) for m in ba.pending()])
    check("...and it is kept, not deleted - this app destroys no prose",
          where_is("rename the buttons, and the tooltips") == ["dropped"]
          and total() == was + 2,
          (where_is("rename the buttons, and the tooltips"), total()))

    # THE RACE, which is the whole reason these are file moves. board-watch
    # drains the queue on its own clock; between the menu opening and his click
    # the message can be somebody's job already.
    other = ba.msg_id(ba.pending()[0])
    ba.drain()
    check("removing one board-watch has already drained REFUSES, honestly",
          ba.remove_queued(other) is None)
    check("...and so does editing it - the agent got the old wording",
          ba.edit_queued(other, "too late") is None)
    check("...and neither resurrected it into the queue",
          ba.pending() == [] and where_is("look again at the fan curve") == ["taken"],
          where_is("look again at the fan curve"))
    check("...and an id that was never in the queue is refused the same way",
          ba.remove_queued("no-such-message") is None
          and ba.edit_queued("no-such-message", "hello") is None)
    check("...as is an id that tries to walk out of the queue directory",
          ba._queued_file("../agents/w1") is None
          and ba._queued_file("") is None and ba._queued_file(".hidden") is None)
    check("an edit to nothing at all is refused rather than blanking a message",
          ba.edit_queued(other, "   ") is None)

    # ...and a message stranded by a process that died mid-edit comes back.
    ba.send("stranded by a crash")
    sid = ba.msg_id([m for m in ba.pending()
                     if m["text"] == "stranded by a crash"][0])
    held = os.path.join(ba.inbox_dir("editing"), sid + ".json")
    os.replace(os.path.join(ba.inbox_dir("queue"), sid + ".json"), held)
    os.utime(held, (0, 0))
    ba.sweep()
    check("a message stranded by an interrupted edit is put back on the queue",
          [m["text"] for m in ba.pending()] == ["stranded by a crash"]
          and os.listdir(ba.inbox_dir("editing")) == [],
          ([m["text"] for m in ba.pending()], os.listdir(ba.inbox_dir("editing"))))
    ba.drain()


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
        check("...and the quiet line says it with no subject and no opener",
              bph.doing_line(r, "Marbas").startswith("nothing recently"),
              bph.doing_line(r, "Marbas"))
    finally:
        bph.QUIET_AFTER_S = old

    # ---- the same two, as the LINES the card draws ----
    # *"[agent name] is [what the agent says its doing]"* on the first line, and
    # on the second the observation ALONE — *"actually just take out the [agent]
    # is actually and just display the text after it"*. What is asserted here is
    # the JOINING: the claim has to read as English for the real strings, the
    # observation must carry no subject, and a stopped agent must not be
    # described in the present tense.
    r = bph.observe("ph-a")
    check("a card's first sentence is the agent's own claim, led by its name",
          bph.says_line(r, "Marbas") == "Marbas is testing - the parser round-trips",
          bph.says_line(r, "Marbas"))
    check("...and its second line is the observation ALONE, with no opener",
          bph.doing_line(r, "Marbas") == "editing Main.qml",
          bph.doing_line(r, "Marbas"))
    check("a STOPPED agent is put in the PAST tense, and still gets no subject",
          bph.doing_line(r, "Marbas", running=False)
          == "last seen editing Main.qml",
          bph.doing_line(r, "Marbas", running=False))
    check("...and one that was never seen doing anything says nothing at all",
          bph.doing_line({"observed": "none"}, "Marbas", running=False) == "",
          bph.doing_line({"observed": "none"}, "Marbas", running=False))
    check("an agent with no name is `it` in the CLAIM, and nothing invents one",
          bph.says_line(r) == "it is testing - the parser round-trips"
          and bph.doing_line(r) == "editing Main.qml",
          (bph.says_line(r), bph.doing_line(r)))
    check("a claim with no phase word is QUOTED, not forced after `is`",
          bph.says_line({"claimDoing": "the vtbclient parser"}, "Marbas")
          == "Marbas says: the vtbclient parser",
          bph.says_line({"claimDoing": "the vtbclient parser"}, "Marbas"))
    check("an agent that has said nothing gets no sentence at all",
          bph.says_line({}, "Marbas") == "")
    check("an unobservable agent says THAT, and never the claim",
          bph.doing_line({"observed": "unlinked"}, "Marbas")
          == "board cannot see what Marbas is doing - only that the process is there")
    check("nothing seen yet is stated as itself",
          bph.doing_line({"observed": "none"}, "Marbas") == "nothing yet",
          bph.doing_line({"observed": "none"}, "Marbas"))


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

    # ---- ONE FLAT LIST, OLDEST FIRST ----
    # *"just keep agents ordered by birth/age so they dont move around so
    # much"*. The order is birth and nothing else, so a card stays where it is
    # for the whole life of its agent — through every phase it goes through and
    # through it stopping.
    cards = bw.cards()
    check("the cards are one flat list, with no phase sections in it",
          all("rows" not in c and "label" not in c for c in cards),
          [list(c)[:4] for c in cards[:2]])
    live_cards = [c for c in cards if c["state"] != "queued"]
    check("...ordered oldest first, so a new agent appends at the bottom",
          [c["id"] for c in live_cards]
          == [c["id"] for c in sorted(live_cards,
                                      key=lambda c: (c.get("born") or 0, c["id"]))],
          [(c["id"], c.get("born")) for c in live_cards])
    check("...with queued work after the live agents, having no birth yet",
          [c["state"] == "queued" for c in cards]
          == sorted(c["state"] == "queued" for c in cards),
          [c["state"] for c in cards])
    check("...and the same order on the next poll, so nothing moves under him",
          [c["id"] for c in bw.cards()] == [c["id"] for c in cards])

    # ---- the names: shown everywhere, keyed on nowhere ----
    # *"can you give the workers regular human names?"* — the id goes on being
    # the key (the unit, the log, the sidecar, the inbox), so what is asserted
    # here is that the name is STABLE and UNIQUE among the living, not that
    # anything on disk moved to it.
    live = bw.live_workers()
    check("every worker gets a name beside its coded id",
          live and all(a.get("name") in ba.NAMES for a in live),
          [(a["id"], a.get("name")) for a in live])
    check("...no two LIVE workers answer to the same name",
          len({a["name"] for a in live}) == len(live), [a["name"] for a in live])
    check("...and it is the same name on the next read, not a new one per poll",
          [(a["id"], a["name"]) for a in bw.live_workers()]
          == [(a["id"], a["name"]) for a in live])
    rec = json.load(open(os.path.join(ba.agents_dir(), live[0]["id"] + ".json")))
    check("...persisted in the record, so a board reload does not rename anybody",
          rec.get("name") == live[0]["name"], rec)
    check("...derived from the id when a record predates names, and derived the "
          "same way in every process",
          ba.name_for("w1a2b3c") == ba.name_for("w1a2b3c")
          and ba.name_for("w1a2b3c") in ba.NAMES)
    check("...a name a live agent already answers to is moved along, not reused",
          ba.pick_name("wcollide", taken=set(ba.NAMES[:-1])) == ba.NAMES[-1])
    check("...and every drawn name is ASCII, which the font can draw (2.3)",
          all(n.isascii() and n.isalpha() for n in ba.NAMES), ba.NAMES)
    check("...and fits the card's 7-cell label column, so it cannot run under "
          "the title",
          all(len(n) <= 6 for n in ba.NAMES), [n for n in ba.NAMES if len(n) > 6])
    check("...and no two collide, since `inbox send --to` matches on the name",
          len({n.lower() for n in ba.NAMES}) == len(ba.NAMES))
    check("...with room in the pool to walk past every live agent",
          len(ba.NAMES) >= 24, len(ba.NAMES))
    check("a task queued above the cap is given no name, having nobody on it",
          all(r["name"] == "" for x in bw.groups() if x["phase"] == "queued"
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

    # ---- ...in sub-sections, one per tag that HAS bullets ----
    # A heading is a heading and not a count: the band is the same SectionHead
    # the sections use, one rung quieter (no accent, `interactive: false`, so no
    # `[-]` and no click), and a tag nothing carries draws nothing at all.
    def heads():
        # Top to bottom, not in traversal order: `descendants()` walks the tree
        # and the order it yields siblings in is not the order they are drawn
        # in, so the ORDER of the sub-sections has to be read off the geometry.
        from PySide6.QtCore import QPointF                              # noqa: E402
        got = [(it.mapToItem(win.contentItem(), QPointF(0, 0)).y(),
                it.property("label"))
               for it in descendants(win.contentItem())
               if it.property("interactive") is not None
               and it.property("accented") is not None]
        return [lab for _y, lab in sorted(got, key=lambda p: p[0])]

    check("an untagged chore alone draws NO sub-heading over it",
          not [h for h in heads() if h in [t.lower() for t in B.TODO_TAGS]],
          heads())
    for b in ("- COMPLETION: it landed.\n", "- QUESTION: say the word?\n",
              "- FAILED: nothing landed.\n"):
        B.edit(path, lambda d, b=b: B.add_todo_bullet(d["lines"], d, b))
    spin(400)
    drawn = [h for h in heads() if h in [t.lower() for t in B.TODO_TAGS]]
    check("each tag that has bullets draws its own sub-heading, in order",
          drawn == ["question", "failed", "completion"], drawn)
    check("...and the ones nothing carries draw none",
          "partial" not in drawn and "information" not in drawn, drawn)
    rows = [it for it in descendants(win.contentItem())
            if it.property("replying") is not None]
    check("...with every bullet still drawn exactly once, under one of them",
          len(rows) == len(prop(win, "todo")) == 4, (len(rows), len(prop(win, "todo"))))
    open(path, "w").write(FIXTURE)
    spin(400)
    check("...and the section goes back to one bare bullet when they go",
          len(prop(win, "todo")) == 1
          and not [h for h in heads() if h in [t.lower() for t in B.TODO_TAGS]],
          heads())

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
            when="3:42 pm", path=path)
    spin(500)
    check("landing redraws IN FLIGHT and LANDED together",
          len(prop(win, "flight")) == before_flight
          and len(prop(win, "landed")) == before_landed + 1,
          (len(prop(win, "flight")), len(prop(win, "landed"))))
    # ...and the time reaches the row, while the rows that never had one carry
    # an empty string rather than an invented time or an undefined.
    groups = prop(win, "landed")
    check("a landed row carries WHEN it happened to the window",
          any(r["commit"] == "aa11bb2" and r["when"] == "3:42 pm"
              for g in groups for r in g["rows"]),
          [[(r["commit"], r["when"]) for r in g["rows"]] for g in groups])
    check("...and an older row has an empty one, not a made-up one",
          all(isinstance(r["when"], str) for g in groups for r in g["rows"])
          and any(r["when"] == "" for g in groups for r in g["rows"]))

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

    # ---- ...on ONE line, however much he typed ----
    # He types paragraphs into that box, and wrapped in full they buried the
    # three lines the card is for. The cut is marked with ASCII "..." — a
    # hardcoded UI string is ASCII by rule (docs/DESIGN.md §2.3), which is also
    # why Qt's own `elide` (it draws U+2026) is not what does it.
    agents.send("drawn-live", "Dim the cover art", "decision", "z" * 400)
    agents.refresh()
    spin(250)
    waits = []
    for it in descendants(win.contentItem()):
        s = it.property("text")
        if isinstance(s, str) and "waiting in its inbox" in s and it.isVisible():
            waits.append((s, it))
    longNote = [(s, t) for s, t in waits if "zzz" in s]
    check("a long note waiting in an inbox is cut to ONE line",
          len(longNote) == 1 and longNote[0][1].property("lineCount") == 1,
          [(len(s), s[:40]) for s, _ in waits])
    check("...marked with ASCII `...`, never the unicode ellipsis (S2.3)",
          bool(longNote) and longNote[0][0].endswith("...")
          and "…" not in longNote[0][0],
          [s[-8:] for s, _ in waits])
    check("...with the label left whole, and only the message body shortened",
          bool(longNote)
          and longNote[0][0].startswith("  waiting in its inbox: ")
          and len(longNote[0][0]) < 400,
          [len(s) for s, _ in waits])
    check("...and a note that already fits is not cut at all",
          any(s.endswith("also dim the tracklist") for s, _ in waits),
          [s[-30:] for s, _ in waits])
    said = agents.send("drawn-dead", "Widen the clock", "decision", "never mind")
    agents.refresh()
    spin(250)
    # The queued rows carry an id as well as the text now — he can right-click
    # one to rewrite or remove it, and neither the text (two identical
    # sentences are two messages) nor the position (the next drain shifts every
    # index) is a name for the message it acts on.
    def queued_texts():
        return [q["text"] for q in prop(win, "queuedNotes")]

    check("a note to an agent that has finished goes to the inbox instead",
          "inbox" in said and "never mind" in queued_texts(),
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
              or "rewrite this queued note" in str(b.property("placeholder"))
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
          typed in queued_texts(), prop(win, "queuedNotes"))
    # ---- ...and he can change his mind about one that is still queued ----
    # *"allow the user to remove queued waiting for next agent items or edit
    # them in place"*. Both go through the same `Agents` bridge his messages do,
    # and both have to say what happened — including when the answer is that
    # board-watch got there first.
    qrows = [it for it in descendants(win.contentItem())
             if it.property("note") is not None]
    qrows[0].openMenu(20, 20)
    spin(150)
    qmenus = [it for it in descendants(win.contentItem())
              if it.property("items") is not None and it.isVisible()]
    qlabels = [str(i.get("label", ""))
               for i in qmenus[0].property("items").toVariant()] if qmenus else []
    check("a queued note offers both second thoughts, editing first",
          qlabels[:2] == ["edit what it says", "copy line"], qlabels)
    check("...and the one he cannot take back is LAST, behind a separator",
          qlabels[-1] == "remove it from the queue" and qlabels[-2] == "", qlabels)
    if qmenus:
        qmenus[0].close()
    spin(100)

    qid = [q["id"] for q in prop(win, "queuedNotes") if q["text"] == typed][0]
    said = keep[5].editQueued(qid, "the scrollbar arrows feel too slow")
    spin(200)
    check("he can rewrite a queued note in place, and the row shows the new text",
          "rewritten" in said
          and "the scrollbar arrows feel too slow" in queued_texts()
          and typed not in queued_texts(), (said, queued_texts()))
    said = keep[5].removeQueued(qid)
    spin(200)
    check("...and he can take one off the queue entirely",
          "kept" in said
          and "the scrollbar arrows feel too slow" not in queued_texts(),
          (said, queued_texts()))
    said = keep[5].removeQueued(qid)
    check("...and a second removal SAYS it is gone rather than looking like it worked",
          "already gone" in said, said)
    said = keep[5].editQueued(qid, "too late for this")
    check("...as does an edit of one an agent has already been handed",
          "already gone" in said and "old wording" in said, said)


    # ---- the cards: two sentences each, one flat list, oldest first ----
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
    # The one card NEITHER sentence names: a worker that stopped without ever
    # saying anything and without a transcript to observe. It is what the
    # 7-cell name column exists for, and with the sentences now ABOVE the title
    # row it is also the only card whose top line is that row.
    ba.register("w-mute", "Fold VScroll into qmlcommon", dead,
                kind="worker", where="apps/qmlcommon/**")
    agents.refresh()
    spin(300)
    cards = prop(win, "agentCards")
    rows = {r["title"]: r for r in cards}
    card = rows.get("Wire FOCUS through vtbclient", {})
    check("the section is ONE flat list - no phase headings over the cards",
          all(isinstance(c, dict) and "rows" not in c for c in cards),
          [list(c)[:3] for c in cards[:2]])
    check("a card leads with the claim as a sentence, then the observation alone",
          card.get("saysLine") == card.get("name") + " is testing - the vtbclient parser"
          and card.get("doingLine") == "editing vtbclient.py",
          (card.get("saysLine"), card.get("doingLine")))
    check("...and it still carries BOTH statements, neither standing in for the other",
          card.get("says") == "testing - the vtbclient parser"
          and card.get("actually") == "editing vtbclient.py",
          (card.get("says"), card.get("actually")))
    check("...so what it SAYS and what it DOES can still disagree on screen",
          "testing" in card.get("saysLine", "")
          and "editing" in card.get("doingLine", ""),
          (card.get("saysLine"), card.get("doingLine")))
    check("...and it is drawn as a PERSON: the card carries a first name",
          card.get("name") in ba.NAMES, card.get("name"))
    check("an agent that has said nothing shows no claim at all",
          rows.get("Find where focus is decided", {}).get("says") == ""
          and rows.get("Find where focus is decided", {}).get("saysLine") == "",
          rows.get("Find where focus is decided"))
    check("a STOPPED agent is never described in the present tense",
          all(r.get("doingLine", "") == ""
              or r.get("doingLine", "").startswith("last seen ")
              for r in cards if not r.get("running")),
          [r.get("doingLine") for r in cards if not r.get("running")])
    check("...and no card repeats its own name on the observed line",
          all(not r.get("name") or not r.get("doingLine", "")
              .startswith(r.get("name")) for r in cards),
          [(r.get("name"), r.get("doingLine")) for r in cards])
    check("...and the birth the order comes from never reaches the window",
          all("born" not in r for r in cards), list(rows.values())[:1])
    check("no card carries a time, an age or a count",
          not any(re.search(r"\b\d+\s*(s|m|h|min|sec|hour|ago)\b",
                            str(r.get("saysLine", "")) + " "
                            + str(r.get("doingLine", ""))
                            + " " + str(r.get("detail", "")))
                  for r in rows.values()), list(rows.values())[:1])

    # ---- and the ORDER those three lines are DRAWN in ----
    # His: *"the very first line of an agent in the agent section should be the
    # [name] is [what the agent says theyre doing]. the second line should be
    # [name] is actually doing XYZ. the third line should be what the current
    # first line is"*. Nothing in the model above says anything about order —
    # only the drawn item does, so this is checked on screen and not on a dict.
    def _absy(it, root):
        y, p = 0.0, it
        while p is not None and p is not root:
            y += p.y()
            p = p.parentItem()
        return y

    def _texts(it):
        """Every non-empty visible text on one agent's card, top line first."""
        out = []
        for t in descendants(it):
            s = t.property("text")
            if isinstance(s, str) and s.strip() and t.isVisible():
                out.append((round(_absy(t, it), 1), s, t))
        return sorted(out, key=lambda r: r[0])

    # An AgentRow is the item that publishes both sentences; key them by the
    # card's own title, which is the one string that is unique per card here.
    drawnCards = {}
    for it in descendants(win.contentItem()):
        if it.property("doingLine") is None or it.property("nameNeeded") is None:
            continue
        a = prop(it, "agent")
        if isinstance(a, dict) and a.get("title"):
            drawnCards[str(a["title"])] = it

    cardItem = drawnCards.get("Wire FOCUS through vtbclient")
    lines = _texts(cardItem) if cardItem is not None else []
    ys = {s: y for y, s, _ in lines}
    check("the card's FIRST line is what the agent SAYS it is doing",
          bool(lines) and lines[0][1] == card.get("saysLine"),
          [(y, s) for y, s, _ in lines])
    check("...its SECOND is what it is OBSERVED doing, still under the claim",
          ys.get(card.get("doingLine"), -1) > ys.get(card.get("saysLine"), 1e9),
          [(y, s) for y, s, _ in lines])
    check("...and the title row it used to open with is now the THIRD",
          ys.get("Wire FOCUS through vtbclient", -1)
          > ys.get(card.get("doingLine"), 1e9),
          [(y, s) for y, s, _ in lines])
    check("...with `where` still on the title's own line, right-aligned",
          ys.get("apps/pylib/**") == ys.get("Wire FOCUS through vtbclient"),
          [(y, s) for y, s, _ in lines])
    # The tone ladder, retuned for the new order (docs/DESIGN.md §10.6): the
    # LEAD tone goes to whichever line is drawn first, so a card never opens on
    # its quietest text. It is position, not trust, that picks it.
    tone = {s: t.property("color") for _, s, t in lines}
    check("...and the top line takes the lead tone, not the quietest one",
          tone.get(card.get("saysLine")) == keep[-1].property("text")
          and tone.get("Wire FOCUS through vtbclient") == keep[-1].property("dim"),
          (tone.get(card.get("saysLine")), tone.get("Wire FOCUS through vtbclient")))
    # NOTHING ON THIS LIST IS ANONYMOUS, and the name is never drawn twice over.
    # The 7-cell name column exists for exactly the card whose CLAIM does not
    # name the agent — the observed line no longer carries a subject at all — and
    # it leads the card whenever the title row is that card's own top line.
    check("a card whose claim names the agent draws no separate name column",
          cardItem is not None and cardItem.property("nameNeeded") is False,
          cardItem and cardItem.property("nameNeeded"))
    anon = []
    for c in cards:
        it = drawnCards.get(c.get("title"))
        nm = c.get("name") or ""
        if it is None or not nm:
            continue
        drawn = _texts(it)
        if not any(nm in s for _, s, _ in drawn):
            anon.append(c.get("title"))
        elif it.property("nameNeeded") and it.property("titleFirst") and drawn \
                and nm not in [s for y, s, _ in drawn if y == drawn[0][0]]:
            # the column is the ONLY place the name can be on such a card, and
            # when nothing is drawn above the title row it shares, that row is
            # the card's own top line
            anon.append(c.get("title") + " (name column not on the top line)")
    check("...and no card is anonymous, whichever of the three lines it has",
          anon == [], anon)
    mute = drawnCards.get("Fold VScroll into qmlcommon")
    muteLines = _texts(mute) if mute is not None else []
    # The name column and the title share one line, so compare the whole top
    # line rather than an order between two items at the same y.
    top = [s for y, s, _ in muteLines if muteLines and y == muteLines[0][0]]
    check("a card NO sentence names gets the name column back, leading the card",
          mute is not None and mute.property("nameNeeded") is True
          and rows.get("Fold VScroll into qmlcommon", {}).get("name") in top
          and "Fold VScroll into qmlcommon" in top,
          [(y, s) for y, s, _ in muteLines])
    check("...and that title row, being this card's top line, takes the lead tone",
          bool(muteLines) and {s: t.property("color") for _, s, t in muteLines}
          .get("Fold VScroll into qmlcommon") == keep[-1].property("textDim"),
          [(s, t.property("color").name()) for _, s, t in muteLines])

    # ...with the store's own sections folded away, so the shot is of THIS
    # section rather than of whatever happens to be above it.
    win.setProperty("collapsed", {"needs": True, "flight": True, "landed": True})
    spin(300)
    shot(win, "06-agents")
    win.setProperty("collapsed", {})
    spin(200)
    ba.unregister("w-code")
    ba.unregister("w-read")
    ba.unregister("w-mute")
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

    # *"the resulting agent created should indicate the reply from the user
    # rather than the original message"*. Everything downstream reads the HEAD
    # of this one string — the queue line drawn in the agents section, and
    # `board-watch`'s `msgs[0]["text"][:70]` card title for the orchestrator it
    # spawns — so the assertion is about what the first 70 characters SAY.
    mine = [t for t in q if "make it dim" in t][0]
    check("...leading with HIS reply, not with the chore he replied to",
          mine.startswith("yes, that one, and make it dim"), mine)
    check("...so the card an agent is given is his sentence, not the bullet",
          "make it dim" in mine[:70] and not mine[:70].startswith("about the"),
          mine[:70])

    # *"when the user replies to something in the to do section it should then
    # remove the entry from the to do section"* — and only once the message is
    # actually on disk, which the send above returned.
    spin(250)
    check("...and replying CLEARS the chore off the list",
          len(prop(win, "todo")) == 0, prop(win, "todo"))
    check("...out of the file itself, section left standing",
          B.parse(B.read(path))["todo"] == []
          and "## WAITING ON YOU TO DO" in B.read(path))
    check("...through the same one-level undo, so a misdirected reply is cheap",
          board.property("undoText") == chore["text"],
          board.property("undoText"))
    board.undoRemove()
    spin(250)
    check("...which puts the bullet back byte-for-byte",
          [t["text"] for t in prop(win, "todo")] == [chore["text"]],
          prop(win, "todo"))

    check("an empty reply writes nothing at all",
          win.replyToTodo(prop(win, "todo")[0], "   ") is False
          and len(ba.pending()) == before + 1)
    check("...and leaves the chore exactly where it was",
          len(prop(win, "todo")) == 1, prop(win, "todo"))

    # A bullet whose line has MOVED since the row was drawn is still the bullet
    # that goes: the reply re-resolves it against the doc as it is now. Modelled
    # by handing `replyToTodo` a stale index for a chore that is really there.
    live = dict(prop(win, "todo")[0])
    stale = dict(live)
    stale["line"] = live["line"] + 500
    ok = win.replyToTodo(stale, "this one, please")
    check("a reply against a stale line still removes the right chore",
          ok is True and len(prop(win, "todo")) == 0, prop(win, "todo"))
    board.undoRemove()
    spin(250)
    check("...and that one is restorable too",
          len(prop(win, "todo")) == 1, prop(win, "todo"))

    # A chore that has genuinely gone (an agent cleared it, the sync brought a
    # new file) must not take an unrelated bullet with it — the reply still
    # goes, nothing is removed.
    gone = dict(prop(win, "todo")[0])
    gone["text"] = "a chore that is no longer in the store at all"
    n = len(ba.pending())
    ok = win.replyToTodo(gone, "sure")
    check("replying to a chore that has gone sends, and removes nothing",
          ok is True and len(ba.pending()) == n + 1
          and len(prop(win, "todo")) == 1, prop(win, "todo"))

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


def test_placed_window(app, tmp):
    """The time reaches the screen, on both shapes, and costs the message nothing.

    Two claims the store-level test cannot make: that it is DRAWN at all, and
    that the question text is laid out identically whether or not the item has a
    stamp — an item written before this existed must not wrap differently from
    one written after it (§5.4: reserve the space, drop the label).
    """
    import boardparse as B
    import boardmove as bm

    path = os.path.join(tmp, "board.md")
    B.write(path, FIXTURE)
    engine0, win0, keep0 = build(app, path)
    spin(300)
    def title_width(root):
        """(the card's own width, the width its TITLE text was given).

        By title, not by index: `descendants()` walks a stack and hands the
        cards back in no particular order.
        """
        for it in descendants(root):
            if it.property("decision") is None:
                continue
            for t in descendants(it):
                if "1. First question?" == str(t.property("text")):
                    return it.property("width"), t.property("width")
        return 0, 0

    bare, titles0 = title_width(win0.contentItem())

    bm.note("INFORMATION: a stamped chore", path=path)
    bm.ask("A stamped question?", if_unanswered="nothing happens", path=path)
    doc = B.parse(B.read(path))
    stamp = [d["placed"] for d in doc["needs"] if d["placed"]][0]

    engine, win, keep = build(app, path)
    spin(400)
    texts = [str(it.property("text")) for it in descendants(win.contentItem())
             if it.property("text") is not None]
    check("a decision draws the time it was placed on the board",
          texts.count(stamp) >= 1, [t for t in texts if ":" in t and " " in t][:6])
    check("...and so does a `to do` bullet, in the same words",
          texts.count(stamp) >= 2, texts.count(stamp))
    # Exactly the two that HAVE a stamp: the fixture's own two decisions and its
    # chore predate it, and they draw no time rather than a made-up one.
    check("...and only the items that have one - the older ones draw nothing",
          texts.count(stamp) == 2, [t for t in texts if t == stamp])

    # The reservation is unconditional, so nothing reflows as the board fills.
    cardW, titles = title_width(win.contentItem())
    check("...and the question text is the same width stamped or not",
          titles0 > 0 and titles0 == titles, (titles0, titles))
    check("...having given up the column whether it uses it or not",
          titles > 0 and titles < bare - 100, (titles, bare))
    shot(win, "06-placed")


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
        os.makedirs(os.path.join(tmp, "ld"))
        test_landed(os.path.join(tmp, "ld"))
        os.makedirs(os.path.join(tmp, "tg"))
        test_todo_tags(os.path.join(tmp, "tg"))
        os.makedirs(os.path.join(tmp, "pl"))
        test_placed(os.path.join(tmp, "pl"))
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
        os.makedirs(os.path.join(tmp, "plw"))
        test_placed_window(app, os.path.join(tmp, "plw"))
    print()
    if FAILS:
        print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
