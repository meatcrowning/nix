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

Run it with goetia's own Qt env, not the bare system python:

    W=$(readlink -f "$(which goetia)"); sed '$d' "$W" > /tmp/brdenv.sh
    ( . /tmp/brdenv.sh; "$(tail -1 "$W" | grep -o '/nix/store/[^"]*/bin/python3')" \\
        apps/board/tools/board-test.py --shots /tmp/board-shots )

`XDG_STATE_HOME` is redirected into a scratch dir — a harness here must never
rewrite where the user's own app reopens — and every write test runs against a
COPY of the store in that scratch dir. This harness never writes board.md.
"""
import importlib.util
import json
import os
import re
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
# `Usage` fetches the account's live figures on a worker thread. A test must
# neither reach the network nor write his real `~/.local/state/board/usage.json`,
# so every fetch and nudge is a no-op here; the fetch path is exercised
# explicitly, against a stub, in `test_usage_fetch`.
os.environ["BOARD_USAGE_OFFLINE"] = "1"
# A summon is only a card once it is CONFIRMED (`boardagents.CONFIRM_GRACE_S`),
# and a stubbed worker writes no transcript to be confirmed by — so every test
# but `test_summon_confirmed`, which sets its own, runs with the grace already
# elapsed and sees the old behaviour. Negative rather than 0: the registration
# stamp has one-second resolution, so an exact tie is reachable.
os.environ["BOARD_CONFIRM_GRACE"] = "-1"
# ...and NOBODY is writing as an agent unless a test says so. This harness is
# usually run BY an agent, whose systemd unit exports `BOARD_AGENT_ID` — and
# `boardmove.whoami` reads it, so every `note()` and `ask()` in here was
# attributed to whichever worker happened to be running the tests, which moved
# the `<!-- placed: -->` stamp down a line and failed three checks that had
# nothing to do with the change. Tests that want an author set it themselves.
os.environ.pop("BOARD_AGENT_ID", None)
# ...and the WATCHER'S state is the harness's own, never the live one. The kill
# switch is a FILE (`~/.local/state/board-watch/off`), so a suite that does not
# scope this reads whether board-watch happens to be switched off on the machine
# it is running on: `test_send_box` asserts the message for a typed note names
# the summoner, and with the switch on it says "board-watch is switched off"
# instead and the check fails. Found the hard way on `top` 2026-07-31, while the
# watcher was deliberately off — a green suite must not depend on that. Two
# tests scope it themselves to a scratch dir and still do; this is the floor
# under everything else, and it points at a directory that cannot exist.
WATCH_STATE = os.environ.setdefault(
    "BOARD_WATCH_STATE",
    os.path.join(tempfile.gettempdir(), "board-test-watch-%d" % os.getpid()))
# ...and the other half of the same answer. `watcher_state` reads the kill
# switch off the filesystem (above) AND a `systemctl show` of the two units, so
# scoping only the file still left the suite asking the live service manager
# whether board-watch is running here. A stub that prints the armed pair — the
# service idle between ticks, the path unit active — makes it a constant.
_SYSTEMCTL_STUB = os.path.join(tempfile.gettempdir(),
                               "board-test-systemctl-%d" % os.getpid())
with open(_SYSTEMCTL_STUB, "w") as _f:
    _f.write("#!/bin/sh\nprintf 'ActiveState=inactive\\nLoadState=loaded\\n\\n"
             "ActiveState=active\\nLoadState=loaded\\n'\n")
os.chmod(_SYSTEMCTL_STUB, 0o755)
os.environ.setdefault("BOARD_SYSTEMCTL", _SYSTEMCTL_STUB)

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

    # ---- NEEDS YOU -> the stash ----
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
    check("...and writes NOTHING in its place - no row, nowhere",
          out.splitlines(True) == kept,
          lines_differing("".join(kept), out))
    check("...and his answer is on the stash, for the hand-back to carry",
          "the first way" in (rec.get("notes") or ""), rec.get("notes"))

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

    # ---- the stash -> LANDED ----
    src = reset()
    d = B.parse(src)
    B.write(path, "".join(B.set_answer(d["lines"], d["needs"][0], "do it")))
    bm.start("1", path=path)
    bm.land("1", "abc1234", what="thing: did the first way", path=path)
    doc3 = B.parse(B.read(path))
    check("landing appends it under today's date with the commit",
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

    # ---- ...AND SO IS AN OWNER THAT WAS NEVER RECORDED AT ALL ----
    # `boardctl start` with no --pid (a human, or an orchestrating session).
    # `_alive` says True for it forever — correctly, as liveness — so with no age
    # bound the stash was IMMORTAL and `boardagents` drew an `unowned` card that
    # nothing could collect. Two of them survived a day on `top` before he
    # noticed: "some residual agents left that should've been swept up".
    src = reset()
    d = B.parse(src)
    B.write(path, "".join(B.set_answer(d["lines"], d["needs"][0], "do it")))
    src = B.read(path)
    bm.start("1", path=path)                  # no pid at all
    check("a pid-less item is left alone while it is still young",
          bm.reconcile(path=path) == [])
    check("...and it is NOT reported dead - liveness has one definition",
          all(bm._alive(r) for r in bm._stashes()),
          [(r["key"], r.get("pid")) for r in bm._stashes()])

    # Age its own stamp, which is what `_stash_age` reads first — `start()`
    # writes `started`, and only a stash carrying neither falls back to mtime.
    old = time.strftime("%Y-%m-%dT%H:%M:%S%z",
                        time.localtime(time.time() - bm.UNOWNED_STRAND_S - 60))
    for rec in bm._stashes():                 # keyed by the item's key, not "1"
        f = bm.stash_file(rec["key"])
        rec["started"] = old
        with open(f, "w") as fh:
            json.dump(rec, fh)
    check("...but past the bound it counts as abandoned",
          [bm._abandoned(r) for r in bm._stashes()] == [True],
          [(r["key"], round(bm._stash_age(r))) for r in bm._stashes()])
    moved = bm.reconcile(path=path)
    check("...and reconcile gives it back like any other stranded item",
          len(moved) == 1 and moved[0]["num"] == "1", moved)
    back = B.parse(B.read(path))
    # It never had an agent, so it must not be told one died: an invented death
    # to explain a row is exactly the confident lie this tree refuses elsewhere.
    check("...saying nothing was working it, NOT that an agent is gone",
          any("nothing was working" in t["text"] for t in back["todo"])
          and not any("is gone" in t["text"] for t in back["todo"]),
          [t["text"][:70] for t in back["todo"]])
    new = [t for t in back["todo"] if "nothing was working" in t["text"]][0]
    check("...and that bullet passes the same short-summary cap as any other",
          new["tag"] == "FAILED"
          and len(new["summary"].split()) <= B.SUMMARY_MAX_WORDS,
          (new["tag"], len(new["summary"].split()), new["summary"]))

    # ---- AN OLD `## IN FLIGHT` SECTION IS READ AND NEVER WRITTEN ----
    # The section is gone [2026-07-30]. `parse` still reads one, because the
    # store outlives any one version of this app — his own hand edits, an older
    # copy still running — and a store this parser could not read is one
    # neither program could write — but nothing appends to it, and
    # a store that still carries one comes out of a whole start/land/back cycle
    # byte-identical in that section. That is what makes it unable to silt up:
    # `reconcile` only ever saw this host's stashes, so a row written by hand,
    # or by the other machine, or before the stash existed, had no exit at all
    # and IN FLIGHT could only grow. His words: it "doesnt update at all".
    src = reset()
    old = B.parse(src)
    before = [r["what"] for r in old["flight"]]
    check("the fixture still has an IN FLIGHT section, and it parses",
          before == ["A thing being built", "Another thing"], before)
    B.write(path, "".join(B.set_answer(B.parse(src)["lines"],
                                       B.parse(src)["needs"][0], "do it")))
    src = B.read(path)
    flight_lines = [ln for ln in src.splitlines(True) if ln.startswith("| A thing")
                    or ln.startswith("| Another thing")]
    bm.start("1", path=path)
    bm.land("1", "abc1234", what="thing: did the first way", path=path)
    after = B.read(path)
    check("a start and a land add NOTHING to it and take nothing out of it",
          [r["what"] for r in B.parse(after)["flight"]] == before,
          [r["what"] for r in B.parse(after)["flight"]])
    check("...and its rows are the same bytes, in the same order",
          [ln for ln in after.splitlines(True)
           if ln.startswith("| A thing") or ln.startswith("| Another thing")]
          == flight_lines)
    check("...and no writer for it is left in the tree",
          not hasattr(B, "add_flight_row") and not hasattr(B, "flight_row")
          and not hasattr(bm, "stall") and not hasattr(bm, "unowned")
          and not hasattr(bm, "find_flight"),
          [n for n in ("add_flight_row", "flight_row") if hasattr(B, n)]
          + [n for n in ("stall", "unowned", "find_flight") if hasattr(bm, n)])

    # `land` has no row to take a sentence from, so it insists on one
    src = reset()
    d = B.parse(src)
    B.write(path, "".join(B.set_answer(d["lines"], d["needs"][0], "do it")))
    before = B.read(path)
    try:
        bm.land("1", "abc1234", path=path)
        check("land refuses a commit with no --what", False)
    except bm.BoardError as e:
        check("land refuses a commit with no --what", "what" in str(e), str(e))
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
          p.returncode == 0 and "NEEDS YOU" in p.stdout, p.stderr.strip()[:200])
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
    check("a worker with no selector at all can still record its commit",
          len(row) == 1 and row[0]["what"] == "board: land with no row",
          [(g["date"], [r["commit"] for r in g["rows"]]) for g in doc["landed"]])
    check("...and it closed nothing out, there being no stash to close",
          got == {}, got)
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
          p.returncode == 0 and "board: via the CLI" in p.stdout,
          (p.stdout.strip()[:120], p.stderr.strip()[:120]))
    p = subprocess.run([sys.executable, cli, "--board", path, "land", "nothing-here",
                        "--commit", "feedbee"], capture_output=True, text=True)
    check("...but a commit with no --what is refused by the parser itself",
          p.returncode != 0 and "--what" in p.stderr, p.stderr.strip()[:160])


# ------------------- 1a1a. LANDED IS READ FROM THE COMMIT LOG, every time
def test_landed_view(tmp):
    """*"it should just read from the commit log of the repo itself. it
    shouldnt need an agent to do that"* — 2026-07-29, after the third time he
    found the section hours stale.

    Both earlier fixes made something WRITE the missing rows, and a writer has
    to be DEPLOYED: the board window is live source with no hot reload, so the
    one he had open never ran the first fix, and the watcher is a home-manager
    unit, so on `top` the second one needed a rebuild before it existed there.
    `boardmove.landed_view()` derives the section instead, so there is nothing
    stamped left to go stale.

    Six claims, and together they are the whole contract:

      * a commit NOBODY recorded is in the section anyway, from `git log`;
      * it is found on **local HEAD**, with no fetch and no `origin/main` — the
        old sweep read the remote-tracking ref alone, so a commit made on this
        machine was invisible until somebody pushed;
      * **both repos**: `~/nix` and the separate `docs/` repo inside it;
      * the docs sync timer's own `sync(host): n doc(s)` commits are dropped,
        or forty a day of them would bury the section;
      * a cached row wins on WORDING and never on existence — the sentence
        `land --what` chose survives, and the hash is not listed twice;
      * **it writes NOTHING.** The file is byte-identical afterwards, which is
        what makes it safe to call on every repaint.
    """
    import subprocess

    import boardmove as bm
    import boardparse as B

    repo = os.path.join(tmp, "repo")
    docs = os.path.join(repo, "docs")
    os.makedirs(docs)
    base = dict(os.environ, GIT_CONFIG_GLOBAL=os.path.join(tmp, "gitconfig"),
                GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
                GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                GIT_COMMITTER_EMAIL="t@t")

    def git(where, *a):
        return subprocess.run(["git", "-C", where] + list(a), env=base,
                              capture_output=True, text=True)

    def commit(where, subject, ago):
        name = subject.replace("/", "_")[:40]
        open(os.path.join(where, name), "w").write("x")
        # By NAME, not `-A`: `docs/` is a nested repo with no commit of its own
        # yet, and `git add -A` in the outer one fails outright on that.
        git(where, "add", "--", name)
        when = "@%d +0000" % int(time.time() - ago)
        base["GIT_AUTHOR_DATE"] = base["GIT_COMMITTER_DATE"] = when
        git(where, "commit", "-q", "-m", subject)
        return git(where, "rev-parse", "--short", "HEAD").stdout.strip()

    for where in (repo, docs):
        git(where, "init", "-q", "-b", "main")
    # Minutes ago, so every one of them falls on TODAY — the date group the
    # fixture below opens. NOTHING is pushed and no `origin/main` ref is ever
    # created: reading local HEAD is the point.
    landed_by_hand = commit(repo, "the one an agent recorded", 600)
    nobody = commit(repo, "the one NOBODY recorded", 400)
    doc_side = commit(docs, "a docs commit, the other repo", 300)
    commit(docs, "sync(book): 1 doc(s)", 200)

    path = os.path.join(tmp, "board.md")
    day = time.strftime("%Y-%m-%d")
    open(path, "w").write(
        FIXTURE.replace("### 2026-07-28", "### " + day)
               .replace("| `abc1234` | did a thing |",
                        "| `%s` | the sentence the agent chose |"
                        % landed_by_hand))
    before = B.read(path)

    old_repo, old_docs = bm.LANDED_REPO, bm.LANDED_DOCS_REPO
    bm.LANDED_REPO, bm.LANDED_DOCS_REPO = repo, docs
    bm._tip_cache["key"] = None                 # the fixture is a new pair
    try:
        doc = B.parse(B.read(path))
        view = bm.landed_view(doc, fetch=False)
    finally:
        bm.LANDED_REPO, bm.LANDED_DOCS_REPO = old_repo, old_docs
        bm._tip_cache["key"] = None

    rows = [(r["commit"], r["what"]) for g in view for r in g["rows"]]
    whats = [w for _c, w in rows]
    check("a commit NOBODY recorded is in the section, straight from git log",
          (nobody, "the one NOBODY recorded") in rows, rows)
    check("...found on local HEAD, with no fetch and no origin/main at all",
          not os.path.exists(os.path.join(repo, ".git", "refs", "remotes")))
    check("...and the separate docs/ repo is read too, it being where half the "
          "work lands", (doc_side, "a docs commit, the other repo") in rows,
          rows)
    check("the docs sync timer's own commits are dropped, not drawn",
          not any(w.startswith("sync(") for w in whats), whats)
    check("a cached row wins on WORDING: the agent's sentence survives",
          (landed_by_hand, "the sentence the agent chose") in rows, rows)
    check("...and never on existence: its hash is listed once, not twice",
          len([c for c, _w in rows if c == landed_by_hand]) == 1, rows)
    check("the rows a git-less fixture already had are all still there",
          "did another thing" in whats, whats)
    check("IT WRITES NOTHING — that is what makes it safe on every repaint",
          B.read(path) == before)


# ------------------- 1a1b. ...and the window it derives over is BOUNDED
def test_landed_window(tmp):
    """A repo takes ~80 commits a day. Unbounded, the section would become the
    whole log, so LANDED is **today and yesterday by local calendar date** and
    nothing else — a date group older than that is cut from the VIEW as well,
    the file keeping every row it ever had.

    And it reads **newest first inside a day**, not only across days. It read
    oldest-first until 2026-07-29, which is the whole of why he found the
    section stale for the fourth time: the top row under today's date was the
    day's FIRST commit, at 12:16 am, with eighty-seven newer ones below the
    fold. Nothing was missing and nothing was late; he simply could not see it.

    Five claims: today arrives, yesterday arrives, forty days ago does not, an
    old group in the file is not drawn, and a day reads newest first.
    """
    import subprocess

    import boardmove as bm
    import boardparse as B

    repo = os.path.join(tmp, "repo")
    os.makedirs(repo)
    base = dict(os.environ, GIT_CONFIG_GLOBAL=os.path.join(tmp, "gitconfig"),
                GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
                GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                GIT_COMMITTER_EMAIL="t@t")

    def git(*a):
        return subprocess.run(["git", "-C", repo] + list(a), env=base,
                              capture_output=True, text=True)

    git("init", "-q", "-b", "main")
    made = {}
    for label, ago in (("ancient", 40 * 86400), ("yesterday", 86400),
                       ("earlier", 4 * 3600), ("today", 300)):
        open(os.path.join(repo, label), "w").write("x")
        git("add", "-A")
        when = "@%d +0000" % int(time.time() - ago)
        base["GIT_AUTHOR_DATE"] = base["GIT_COMMITTER_DATE"] = when
        git("commit", "-q", "-m", "the %s one" % label)
        made[label] = git("rev-parse", "--short", "HEAD").stdout.strip()

    path = os.path.join(tmp, "board.md")
    day = time.strftime("%Y-%m-%d")
    # ...and one date group from a fortnight ago, written by hand the way the
    # real store's older groups were, to prove the cut reaches the FILE's rows
    # and not only the ones derived from git.
    open(path, "w").write(FIXTURE.replace(
        "### 2026-07-28",
        "### 2026-07-14\n\n| Commit | What |\n|---|---|\n"
        "| `0ldc0de` | a fortnight ago |\n\n### " + day))

    old_repo, old_docs = bm.LANDED_REPO, bm.LANDED_DOCS_REPO
    bm.LANDED_REPO, bm.LANDED_DOCS_REPO = repo, os.path.join(repo, "nope")
    bm._tip_cache["key"] = None
    try:
        view = bm.landed_view(B.parse(B.read(path)), fetch=False)
    finally:
        bm.LANDED_REPO, bm.LANDED_DOCS_REPO = old_repo, old_docs
        bm._tip_cache["key"] = None

    whats = [r["what"] for g in view for r in g["rows"]]
    check("a commit inside the window is derived into the section",
          "the today one" in whats, whats)
    check("...and so is one from yesterday: LANDED is today AND yesterday",
          "the yesterday one" in whats, whats)
    check("...and one from forty days ago is NOT: the window is what keeps "
          "eighty commits a day from becoming the section",
          "the ancient one" not in whats, whats)
    check("...nor is a date group the FILE holds from a fortnight ago - the "
          "cut is on what is DRAWN, and the file keeps its rows",
          "a fortnight ago" not in whats and "0ldc0de" in B.read(path), whats)
    check("...while the rows the file already had for today are untouched",
          "did a thing" in whats and "did another thing" in whats, whats)
    check("a day reads NEWEST FIRST, which is the whole of why he read the "
          "section as stale: the newest row was below the fold",
          whats.index("the today one") < whats.index("the earlier one")
          < whats.index("the yesterday one"), whats)


# ------------------- 1a1d. ...and `land` upgrades the row the sweep beat it to
def test_landed_upgrade(tmp):
    """The sweep fills a hole about two minutes after the push now, so a worker
    that takes longer than that to come back and `land` will regularly find its
    own commit already recorded — under the raw commit subject.

    `land` used to be dropped on the floor there ("skip a hash the doc already
    names"), which threw away the sentence the agent chose. It now rewrites that
    one What cell in place: same line, same commit, same time, one targeted line
    edit like every other write in this store. Four claims — the cell changes,
    no row is added, the time and every other line survive, and re-stating a row
    that already reads that way is a no-op and not an error.
    """
    import boardmove as bm
    import boardparse as B

    path = os.path.join(tmp, "board.md")
    open(path, "w").write(
        FIXTURE.replace("| `def5678` | did another thing |",
                        "| `def5678` | board: swept subject | 3:42 pm |"))
    before = B.read(path)

    bm.land(None, "def5678", what="board: the sentence the agent chose",
            path=path)
    doc = B.parse(B.read(path))
    got = [(r["commit"], r["what"], r["when"])
           for g in doc["landed"] for r in g["rows"]]
    check("`land` on a hash LANDED already names rewrites that row's What",
          got == [("abc1234", "did a thing", ""),
                  ("def5678", "board: the sentence the agent chose", "3:42 pm")],
          got)
    check("...in place: no row was added, the file is the same length",
          len(B.read(path).splitlines()) == len(before.splitlines()))
    check("...and it kept the commit's own time rather than re-reading git",
          "3:42 pm" in B.read(path))
    after = B.read(path)
    bm.land(None, "def5678", what="board: the sentence the agent chose",
            path=path)
    check("...and saying it a second time is a no-op, not a refusal",
          B.read(path) == after)

    # ---- a selector that matches no stash is not an error ----
    bm.land("nothing this host ever started", "def5678",
            what="board: upgraded again", path=path)
    doc = B.parse(B.read(path))
    check("a selector matching no stash still records the commit",
          any(r["what"] == "board: upgraded again"
              for g in doc["landed"] for r in g["rows"]),
          [r["what"] for g in doc["landed"] for r in g["rows"]])


# ------------------- 1b1b. everything in NEEDS YOU says WHEN it was put there
def test_placed(tmp):
    """*"mesages in the needs you section should all have the time they were
    placed on the board indicated on them."*

    Both shapes drawn under that heading carry it — a decision and a WAITING
    bullet — and the four claims that keep it honest are:

      * the stamp is written by the WRITER, at the moment the item goes up, so
        it is a fact and not a guess at read time;
      * it is OPTIONAL, in both directions. The store is full of items that
        predate it, and the two machines' boards may be written by different
        copies of this app, so a missing one draws NO time — never an
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
    # ---- a summary line, a gap, then the elaboration ----
    # *"it should show the PARTIAL INFORMATION whatever text, then a single line
    # summarizing, a new line, and THEN the elaboration if needed."* A VIEW/parse
    # split only: `text` stays the joined string every other consumer reads.
    B.write(path, FIXTURE.replace(
        "- **Relaunch `reader`** - live source, no hot reload.",
        "- COMPLETION: **the thing** - it works now\n"
        "  Why it did not before, and what to watch.\n"
        "- INFORMATION: nothing under this one"))
    src = B.read(path)
    doc = B.parse(src)
    check("the store still round-trips byte for byte", "".join(doc["lines"]) == src)
    long_, short = doc["todo"]
    check("a bullet with continuations splits into a summary and its elaboration",
          long_["summary"] == "COMPLETION: the thing - it works now"
          and long_["detail"] == "Why it did not before, and what to watch.",
          (long_["summary"], long_["detail"]))
    check("...with the joined text left exactly as every other consumer reads it",
          long_["text"] == "COMPLETION: the thing - it works now Why it did not "
                           "before, and what to watch.", long_["text"])
    check("...and a bullet with nothing under it grows no empty second block",
          short["summary"] == short["text"] and short["detail"] == "",
          (short["summary"], short["detail"]))
    check("...and the tag is still read off the whole line, as it always was",
          [t["tag"] for t in doc["todo"]] == ["COMPLETION", "INFORMATION"],
          [t["tag"] for t in doc["todo"]])

    import inspect
    body = inspect.getsource(B.format_placed).split('"""')[-1]
    check("what draws the time cannot see the clock, so it cannot become an age",
          "now(" not in body and "today(" not in body and "time.time" not in body,
          [ln.strip() for ln in body.splitlines() if "now" in ln][:3])


# ----------------------------- 1b1c. every entry says WHO put it on the board
def test_by(tmp):
    """*"every entry on the board should record WHO wrote it - which program or
    agent put it there"*, drawn in the gutter above the time.

    The stamp is `<!-- by: ... -->`, the twin of `placed:` in every respect, and
    the claims that keep it safe are all about its ABSENCE. Three programs write
    this file concurrently, one of them lives outside this tree
    (`home/srvs/board-watch-files/`) and does not emit it yet, the store syncs
    between two machines that may run different copies of this app, and every
    entry written before today has none. So the failure to design against is not
    a wrong attribution — it is a parser that drops or mangles an UNSTAMPED
    entry. Every check below is either that, or the ordering rule that keeps the
    stamp inside the span a bullet is removed by.
    """
    import boardparse as B
    import boardmove as bm

    check("a writer that cannot say who it is writes NO stamp, never `unknown`",
          (B.by_now(""), B.by_now(None), B.by_now("   ")) == ("", "", ""))
    check("...and a name it cannot spell in the stamp is dropped, not mangled",
          (B.by_now("two words"), B.by_now("<!-- nested -->"),
           B.by_now("a:b")) == ("", "", ""),
          (B.by_now("two words"), B.by_now("a:b")))
    check("...while a name, an id and a program all pass through as they are",
          (B.by_now("Marbas"), B.by_now("w2502ad"), B.by_now("board-watch"))
          == ("<!-- by: Marbas -->\n", "<!-- by: w2502ad -->\n",
              "<!-- by: board-watch -->\n"), B.by_now("board-watch"))

    # ---- the store as it is today: nothing carries one, and nothing breaks ----
    path = os.path.join(tmp, "board.md")
    B.write(path, FIXTURE)
    src = B.read(path)
    doc = B.parse(src)
    check("an entry written before this existed says nothing, and parses fine",
          [d["by"] for d in doc["needs"]] == ["", ""]
          and [t["by"] for t in doc["todo"]] == [""],
          ([d["by"] for d in doc["needs"]], [t["by"] for t in doc["todo"]]))
    check("...and the file still round-trips byte for byte", "".join(doc["lines"]) == src)

    # ---- a bullet an AGENT wrote ----
    # `whoami` reads `BOARD_AGENT_ID`, which is what every worker's boardctl run
    # carries and what board-watch passes explicitly on behalf of a dead one — so
    # neither writer needs a second channel to say who it is.
    B.write(path, FIXTURE)
    os.environ["BOARD_AGENT_ID"] = "w2502ad"
    try:
        who = bm.whoami()[1]
        bm.note("INFORMATION: an agent wrote this", path=path)
    finally:
        del os.environ["BOARD_AGENT_ID"]
    after = B.read(path)
    doc = B.parse(after)
    mine = doc["todo"][-1]
    check("a bullet an agent writes is attributed to that agent, by NAME",
          who and mine["by"] == who, (who, mine["by"]))
    check("...as an HTML comment, so the file still reads cleanly for him",
          after.splitlines()[mine["line"] + 1].startswith("<!-- by:"),
          after.splitlines()[mine["line"] + 1])
    check("...on the line ABOVE the time, which is what the gutter draws",
          after.splitlines()[mine["line"] + 2].startswith("<!-- placed:")
          and mine["placed"] != "", after.splitlines()[mine["line"]:mine["line"] + 3])
    check("...and it is not prose: nothing of it reaches what gets drawn",
          "by:" not in mine["text"] and "by:" not in mine["summary"], mine["text"])
    check("...and the file still round-trips byte for byte", "".join(doc["lines"]) == after)

    # ---- ...and a bullet written ON BEHALF of an agent is NOT that agent's ----
    # `agent_id` says which agent a result is FROM, so its summon note goes with
    # it. It is NOT authorship, and reading it as authorship stamped every
    # board-watch failure note with the dead minister's name — a bullet whose own
    # text says that minister recorded nothing, attributed to it. The author is
    # resolved from the environment (the writing process) and nothing else; a
    # caller that is nobody falls back to `by=`, which is how board-watch says
    # `board-watch`.
    B.write(path, FIXTURE)
    bm.note("FAILED: a minister stopped without finishing", path=path,
            agent_id="w2502ad")
    onbehalf = B.parse(B.read(path))["todo"][-1]
    check("a bullet written on behalf of an agent is not attributed to it",
          onbehalf["by"] == "", onbehalf["by"])
    B.write(path, FIXTURE)
    bm.note("FAILED: a minister stopped without finishing", path=path,
            agent_id="w2502ad", by="board-watch")
    onbehalf = B.parse(B.read(path))["todo"][-1]
    check("...it is attributed to the program that wrote it, when it says so",
          onbehalf["by"] == "board-watch", onbehalf["by"])

    # ---- ...and WHICH OF HIS ASKS the entry came out of ----
    # *"information messages should display a truncated version of the original
    # user prompt that spawned the message"*. `$BOARD_ORDER` is the channel: the
    # summoner is registered under his sentence, `boardwork` puts it in every
    # worker's environment, and the bullet stamps it. Optional in exactly the
    # way `by:` is — an entry nobody dispatched quotes nothing.
    B.write(path, FIXTURE)
    bm.note("INFORMATION: an undispatched chore", path=path)
    check("a bullet nobody dispatched quotes no order, and says nothing",
          B.parse(B.read(path))["todo"][-1]["order"] == ""
          and "<!-- for:" not in B.read(path), B.read(path))
    B.write(path, FIXTURE)
    HIS = "make the titlebar stop flashing, and check the other apps too"
    os.environ["BOARD_ORDER"] = HIS
    try:
        bm.note("INFORMATION: **a dispatched chore** - it is done.\n"
                "    And this is the background under it.", path=path)
    finally:
        del os.environ["BOARD_ORDER"]
    ordraw = B.read(path)
    orddoc = B.parse(ordraw)
    got = orddoc["todo"][-1]
    check("a bullet a dispatched agent writes quotes the order behind it",
          got["order"] == HIS, got["order"])
    check("...as a comment, so it is metadata and not prose in his file",
          "<!-- for: %s -->" % HIS in ordraw and "for:" not in got["text"],
          got["text"])
    check("...ABOVE the author and the time, inside the bullet's own span",
          ordraw.splitlines()[got["line"] + 2].startswith("<!-- for:")
          and ordraw.splitlines()[got["line"] + 3].startswith("<!-- placed:"),
          ordraw.splitlines()[got["line"]:got["line"] + 4])
    check("...and the file still round-trips byte for byte",
          "".join(orddoc["lines"]) == ordraw)
    check("...and removing the bullet takes the quote with it, no orphan",
          "<!-- for:" not in "".join(B.remove_todo(orddoc["lines"], got)),
          "".join(B.remove_todo(orddoc["lines"], got)))
    # His sentence is his: a paragraph is capped at the WRITE so the store stays
    # one line per stamp, and `-->` in it cannot end the comment early.
    long_one = "x" * 400 + " -->" + " and more"
    check("a long order is cut in the store, with an ASCII marker",
          len(B.for_now(long_one)) < 260 and B.for_now(long_one).endswith("-->\n")
          and "..." in B.for_now(long_one), B.for_now(long_one)[:80])
    check("...and nothing he types can close the comment early",
          B.for_now("all done --> now what").count("-->") == 1,
          B.for_now("all done --> now what"))
    check("...and an empty order writes no line at all", B.for_now("") == "")

    # The ORDER is why `by:` goes first: `placed:` is the line that closes the
    # bullet's span, so a stamp under it would fall outside `todo_span` and be
    # left behind by a removal as an orphan comment.
    check("the bullet's span covers BOTH stamps, so removal takes all three lines",
          mine["endLine"] == mine["line"] + 2, (mine["line"], mine["endLine"]))
    block = doc["lines"][mine["line"]:mine["endLine"] + 1]
    gone = B.remove_todo(doc["lines"], mine)
    check("...leaving no orphan comment of either kind behind",
          "".join(gone).count("<!-- by:") == 0
          and "".join(gone).count("<!-- placed:") == 0
          and len(B.parse("".join(gone))["todo"]) == 1,
          "".join(gone).count("<!-- by:"))
    back = B.parse("".join(gone))
    check("...and the undo puts the bullet, its time AND its author back",
          [t["by"] for t in
           B.parse("".join(B.add_todo_block(back["lines"], back, block)))["todo"]]
          == ["", who],
          [t["by"] for t in
           B.parse("".join(B.add_todo_block(back["lines"], back, block)))["todo"]])

    # ---- ...and one nobody can name ----
    # `by=` is the program's own name, and it is a FALLBACK: an agent writing
    # through the same call is named by its id, because the name is the word he
    # reads on this board.
    B.write(path, FIXTURE)
    bm.note("COMPLETION: he ran it himself", path=path, by="boardctl")
    check("a bullet with no agent behind it names the PROGRAM that wrote it",
          B.parse(B.read(path))["todo"][-1]["by"] == "boardctl",
          B.parse(B.read(path))["todo"][-1]["by"])
    B.write(path, FIXTURE)
    os.environ["BOARD_AGENT_ID"] = "w2502ad"
    try:
        bm.note("COMPLETION: an agent ran it", path=path, by="boardctl")
    finally:
        del os.environ["BOARD_AGENT_ID"]
    check("...and an agent behind the same call outranks that fallback",
          B.parse(B.read(path))["todo"][-1]["by"] == who,
          B.parse(B.read(path))["todo"][-1]["by"])
    B.write(path, FIXTURE)
    bm.note("INFORMATION: nobody at all", path=path)
    check("...and a caller that offers neither writes no stamp, not an empty one",
          B.parse(B.read(path))["todo"][-1]["by"] == ""
          and "<!-- by:" not in B.read(path), B.read(path).count("<!-- by:"))

    # ---- a decision an agent asks ----
    B.write(path, FIXTURE)
    os.environ["BOARD_AGENT_ID"] = "w2502ad"
    try:
        key = bm.ask("Which way should this go?", if_unanswered="nothing moves",
                     path=path, by="boardctl")
    finally:
        del os.environ["BOARD_AGENT_ID"]
    after = B.read(path)
    doc = B.parse(after)
    asked = [d for d in doc["needs"] if d["key"] == key][0]
    check("a question an agent asks is attributed the same way",
          asked["by"] == who and asked["byLine"] == asked["titleLine"] + 1,
          (asked["by"], asked["byLine"], asked["titleLine"]))
    check("...above its time, with the answer line and the options untouched",
          asked["placedLine"] == asked["byLine"] + 1 and asked["placed"] != ""
          and asked["ifUnanswered"] == "nothing moves",
          (asked["placedLine"], asked["byLine"]))
    check("...and the file still round-trips byte for byte", "".join(doc["lines"]) == after)

    # ...and it travels with the item, like every other line of it: a relocation
    # cuts the decision's RAW lines into IN FLIGHT's stash and back.
    d = B.parse(B.read(path))
    B.write(path, "".join(B.set_answer(d["lines"], d["needs"][0], "the first way")))
    src = B.read(path)
    bm.start("1", path=path)
    bm.give_back("1", path=path)
    check("an attribution survives IN FLIGHT and back, untouched",
          B.read(path) == src,
          [ln for ln in B.read(path).splitlines() if ln not in src.splitlines()][:4])

    # ---- a store somebody ELSE stamped, by hand or from the other machine ----
    # The parser must not care who wrote the line or what shape the item was in
    # when it did — including the one case that has no `placed:` under it at all,
    # which is what a hand edit or a half-upgraded writer produces.
    hand = FIXTURE.replace(
        "- **Relaunch `reader`** - live source, no hot reload.",
        "- **Relaunch `reader`** - live source, no hot reload.\n<!-- by: Botis -->")
    B.write(path, hand)
    doc = B.parse(B.read(path))
    check("a bullet stamped by hand, with no time under it, still parses",
          [t["by"] for t in doc["todo"]] == ["Botis"]
          and doc["todo"][0]["text"] == "Relaunch reader - live source, no hot reload."
          and doc["todo"][0]["placed"] == "",
          [(t["by"], t["placed"], t["text"][:20]) for t in doc["todo"]])
    check("...and that file round-trips byte for byte too",
          "".join(doc["lines"]) == hand)
    check("...and the span still covers the stamp",
          doc["todo"][0]["endLine"] == doc["todo"][0]["line"] + 1,
          (doc["todo"][0]["line"], doc["todo"][0]["endLine"]))


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

    check("the tag set is short and is his three plus what the machine needs",
          B.TODO_TAGS == ("QUESTION", "INFORMATION", "COMPLETION", "PARTIAL",
                          "FAILED", "SUMMONED", "COMMANDED"), B.TODO_TAGS)
    check("...and only the two summon words are written without a colon",
          B.BARE_TAGS == ("SUMMONED", "COMMANDED"), B.BARE_TAGS)
    check("...both of which share a sub-section of their own, as he asked",
          [B.section_of(t) for t in B.BARE_TAGS] == ["SUMMONED"] * 2)

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
          bm.note("COMPLETION: **the tag rule** - every writer emits one now.\n"
                  "    This sentence is the background, on its own line.",
                  path=path))
    doc = B.parse(B.read(path))
    check("...and it reads tag first, description second",
          doc["todo"][-1]["text"].startswith("COMPLETION: the tag rule - "),
          doc["todo"][-1]["text"][:60])

    # ---- the first line is AT MOST about a dozen words, mechanically ----
    # His second complaint (2026-07-29): "still too long", after "a SHORT
    # description" in the prompts did not hold. So the length is enforced at
    # the same choke point as the tag, and the elaboration lives on the
    # indented lines, which are not measured.
    before = B.read(path)
    try:
        bm.note("COMPLETION: **the cap** - " + " ".join(["word"] * 13),
                path=path)
        check("a first line past about a dozen words is refused", False,
              "it was written")
    except B.BoardError as e:
        check("a first line past about a dozen words is refused",
              B.read(path) == before and "dozen" in str(e), str(e)[:80])
    check("...a dozen exactly still lands (the headline's words count too)",
          bm.note("COMPLETION: **the cap** - " + " ".join(["w"] * 10),
                  path=path))
    check("...a code span is ONE word, so interpolated data cannot refuse a "
          "mechanical note",
          bm.note("FAILED: **a worker is gone** - it was working on `%s`."
                  % " ".join(["his", "own", "words"] * 10), path=path))
    check("...and the INDENTED elaboration under it is not measured at all",
          bm.note("PARTIAL: **the long story** - the summary fits.\n"
                  "    " + " ".join(["detail"] * 40), path=path))

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
    n = len(B.parse(B.read(path))["todo"])
    check("...while every line tagged is fine, and lands as separate bullets",
          bm.note("INFORMATION: **one** - summoned Marbas, nothing landed yet.\n"
                  "INFORMATION: **two** - summoned Zepar, nothing landed yet.",
                  path=path)
          and len(B.parse(B.read(path))["todo"]) == n + 2,
          [t["text"] for t in B.parse(B.read(path))["todo"]])
    check("...and an INDENTED continuation line needs no tag of its own",
          bm.note("PARTIAL: **a wrapped one** - the first line,\n"
                  "  and the background wrapped onto a second.", path=path))

    # ---- ONE BOARD ITEM PER ASK ----
    # His, 2026-07-29: a message reports ONE thing. Replying to a bullet CLEARS
    # that bullet (bc1454d), so an ask folded into another one is cleared by a
    # reply that was never about it: worker Purson was handed four and wrote one
    # bullet whose headline named the first, and 2-4 went with his reply to it.
    # `check_one_ask` cannot read intent, so it refuses the SHAPES a second ask
    # arrives in — each of these landed silently before it existed.
    before = B.read(path)
    for bad, why in (
            ("COMPLETION: **a** - landed. PARTIAL: **b** - not yet.",
             "a second tag further along the line"),
            ("COMPLETION: **a** - landed, and also **b** - landed",
             "a second **headline** on one line"),
            ("PARTIAL: **a** - landed.\n  COMPLETION: **b** - this one too",
             "an ask tagged but INDENTED, hiding in the elaboration"),
            ("PARTIAL: **a** - two of them.\n  - one\n  - two",
             "a list under a bullet"),
            ("PARTIAL: **times on needs you** - landed, plus two more items "
             "you sent while I was in there.",
             "prose counting other work into this item - Purson's own bullet")):
        try:
            bm.note(bad, path=path)
            check("a bundled message is refused: %s" % why, False,
                  "it was written")
        except B.BoardError as e:
            check("a bundled message is refused: %s" % why,
                  B.read(path) == before, str(e)[:70])

    check("...while a headline that merely NAMES one is fine",
          bm.note("INFORMATION: **the third item** - the other two are Zepar's.",
                  path=path))
    n = len(B.parse(B.read(path))["todo"])
    stamps = B.read(path).count("<!-- placed:")
    check("...and the sanctioned way to report several is several bullets",
          bm.note("COMPLETION: **the fade** - landed.\n"
                  "PARTIAL: **the tooltip** - a rebuild is pending.",
                  path=path)
          and len(B.parse(B.read(path))["todo"]) == n + 2,
          [t["text"][:40] for t in B.parse(B.read(path))["todo"]])
    check("...each with its OWN stamp, so each is his to clear on its own",
          B.read(path).count("<!-- placed:") == stamps + 2,
          (stamps, B.read(path).count("<!-- placed:")))

    # `boardctl note 'A: x' 'B: y'` is TWO messages: joining its argv with a
    # space used to land one bullet claiming to be both.
    import subprocess
    n = len(B.parse(B.read(path))["todo"])
    p = subprocess.run([sys.executable, os.path.join(BOARD, "tools",
                                                     "boardctl.py"),
                        "--board", path, "note",
                        "COMPLETION: **argv one**", "-", "landed",
                        "PARTIAL: **argv two** - pending"],
                       capture_output=True, text=True)
    texts = [t["text"] for t in B.parse(B.read(path))["todo"]]
    check("boardctl splits its argv at each tag, and only there",
          p.returncode == 0 and len(texts) == n + 2
          and texts[-2].startswith("COMPLETION: argv one - landed")
          and texts[-1].startswith("PARTIAL: argv two - pending"),
          (p.stderr.strip()[:120], texts[-2:]))

    # ---- HIS WORDS ARE DATA, NOT PROSE THE CHECKS READ ----
    # The mechanical templates interpolate what he typed into the box. A note
    # that says a worker DIED must never be refused for how he phrased the thing
    # it died on — and before `oneline`, a newline in it made the template's
    # second line an untagged bullet and the whole failure note was refused.
    hostile = ("do the **thing**\nand COMPLETION: the other,\nplus two more "
               "items while you are there")
    check("a bullet quoting his words survives every one of those",
          bm.note("FAILED: **a worker stopped without finishing** - it was "
                  "working on %s." % B.oneline(hostile, 200, code=True),
                  path=path))
    check("...with what he typed intact inside the code span, on one line",
          "`do the **thing** and COMPLETION: the other, plus two more items "
          "while you are there`" in B.read(path),
          B.parse(B.read(path))["todo"][-1]["text"][:120])
    check("...and a glob keeps its `**`, which a blanket strip ate",
          B.oneline("apps/**/qml", code=True) == "`apps/**/qml`",
          B.oneline("apps/**/qml", code=True))

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

    # ...and it is RENDERED and run through the real write-path checks, not just
    # regexed. Reading the tag off the source proved the template was tagged and
    # nothing else: `WORKER_FAIL` wrapped `{task}` in backticks the formatter had
    # already added, and a DOUBLED span is not a span — `boardparse._CODE` matches
    # the empty pair at each end and the whole task reverts to countable prose. On
    # 2026-07-31 that refused the note for a worker killed on its runtime limit
    # (35 words against a cap of 12) and Halphas left his board with no trace at
    # all, which is the single failure this file exists to prevent. So every
    # failure bullet is now built from a HOSTILE record — a task carrying
    # backticks, `**`, a tag word and a newline, which is what his own typed
    # orders look like — and put through the checks `add_todo_bullet` applies.
    watch_mod = None
    if src:
        # Import-time, board-watch resolves its store as
        # `$BOARD_WATCH_BOARD or bp.ensure_board()` — and the fallback SEEDS a
        # board on a machine that has none. Point it at a scratch path (it is
        # only bound to a name here, never read) so importing the module cannot
        # reach his own store.
        old = os.environ.get("BOARD_WATCH_BOARD")
        os.environ["BOARD_WATCH_BOARD"] = os.path.join(
            tempfile.gettempdir(), "board-test-watchboard-%d.md" % os.getpid())
        try:
            spec = importlib.util.spec_from_file_location("board_watch", watch)
            watch_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(watch_mod)
        except Exception as e:                     # noqa: BLE001 - reported below
            check("board-watch imports for template rendering", False, e)
        finally:
            if old is None:
                os.environ.pop("BOARD_WATCH_BOARD", None)
            else:
                os.environ["BOARD_WATCH_BOARD"] = old

    if watch_mod is not None:
        hostile = ("In the `reader` app - add **two** viewport interactions\n"
                   "COMPLETION: and do not fold this into another ask")
        rendered = {
            "the dead-worker note": watch_mod.worker_fail_bullet(
                {"agent": "wa5844f", "task": hostile,
                 "transcript": "`~/.claude/projects/*/a05125*.jsonl`"}),
            # ...and the same one with no transcript recorded, which takes the
            # other branch of `where` and is what an older record looks like.
            "the dead-worker note with only a log": watch_mod.worker_fail_bullet(
                {"agent": "wa5844f", "task": hostile}),
            "the unfinished-decision note": watch_mod.FAIL_TEMPLATE.format(
                num=1, how="on a `timeout`",
                title=B.oneline(hostile, 120, code=True)),
            "the undispatched-order note": watch_mod.QUEUE_FAIL.format(
                how="on a `timeout`", text=B.oneline(hostile, 300, code=True)),
        }
        for label, bullet in rendered.items():
            try:
                B.check_todo_tag(bullet)
                B.check_one_ask(bullet)
                B.check_short_summary(bullet)
                ok, why = True, ""
            except B.BoardError as e:
                ok, why = False, str(e)[:120]
            check("%s survives the checks that would refuse it" % label, ok, why)
        # The defect itself, named. Read off the template VALUES, not the file:
        # the prose above them cites `{task}` and `{title}` in spans on purpose,
        # and a source regex only saw those. The four placeholders below are the
        # ones fed `oneline(code=True)`; `{aid}` is fed the plain form and its
        # backticks in `WHERE_LOG` are correct.
        doubled = [n for n, v in vars(watch_mod).items()
                   if isinstance(v, str)
                   and re.search(r"`\{(task|title|text|transcript)\}`", v)]
        check("no board-watch template doubles a code span", not doubled, doubled)

    # ---- and every tag in the set has a writer that can emit it ----
    prompts = src + open(os.path.join(BOARD, "boardwork.py")).read() \
        + open(os.path.join(BOARD, "boardmove.py")).read()
    # The two summon words are written WITHOUT a colon, so that is how a prompt
    # spells them (`boardparse.BARE_TAGS`).
    missing = [t for t in B.TODO_TAGS
               if (t if t in B.BARE_TAGS else "%s:" % t) not in prompts]
    check("no tag exists that no writer can emit", not missing, missing)

    # ...and every prompt that tells an agent to report SAYS the separation rule
    # in the same words the refusal does. The checks above cannot read intent —
    # two asks written as two plain sentences pass — so the prompt is the other
    # half of the rule, not a restatement of it.
    import boardwork as bwk
    for name, text in (("the worker prompt", bwk.WORKER_PROMPT),
                       # board-watch is read as SOURCE (it is deployed, so the
                       # copy that runs may be older); its prompt is one string
                       # split over lines with `\`, so join it back first.
                       ("the decision-agent prompt", src.replace("\\\n", ""))):
        check("%s carries ONE BOARD ITEM PER ASK" % name,
              "ONE BOARD ITEM PER ASK" in text and "CLEARS that bullet" in text,
              text[:0])

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
    check("...and the summon group is LAST when there is one, after the facts",
          B.TODO_ORDER[-1] == "SUMMONED", B.TODO_ORDER)
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


# ------------------------- 1b1. a summon note dies when its result arrives
def test_summon_cleared(tmp):
    """*"once an agent give the board a completed, partial, etc message - its
    related summon information message should be removed since the user would
    already know that part."* [his, 2026-07-29]

    So the board holds ONE line about one piece of work. The two halves worth a
    harness are opposite failures: the note that must GO, and every note that
    must not. A wrong deletion loses something he cannot get back, so the
    matcher refuses to act on ambiguity — that refusal is checked here too,
    because it is the part a later "improvement" would tidy away.
    """
    import boardmove as bm
    import boardparse as B

    path = os.path.join(tmp, "board.md")

    def board(*bullets):
        open(path, "w").write(FIXTURE)
        for b in bullets:
            bm.note(b, path=path)

    def texts():
        return [t["text"] for t in B.parse(B.read(path))["todo"]]

    # [his, 2026-07-29] the announcement is an uppercase TAG before the name and
    # then what the worker went out for — never a trailing "nothing landed yet",
    # which he does not want said at all. The lowercase verb it replaced is still
    # read (below), because the store holds notes written the old way.
    SUM_A = ("INFORMATION: **the landed section** - SUMMONED: Marbas "
             "(`wd690a4`) to read the commit log")
    SUM_B = ("INFORMATION: **the commit times** - SUMMONED: Zepar "
             "(`w4f82de`) to add commit times")

    # ---- the note goes, and only that note ----
    board(SUM_A, SUM_B, "QUESTION: **how far?** - say the word.")
    n = len(texts())
    bm.note("COMPLETION: **the landed section** - it reads the commit log.",
            path=path, agent_id="wd690a4")
    left = texts()
    check("a worker's COMPLETION takes its own summon note with it",
          not [t for t in left if "SUMMONED: Marbas" in t], left)
    check("...and the OTHER worker's summon note is untouched",
          any("SUMMONED: Zepar" in t for t in left), left)
    check("...and his QUESTION is untouched",
          any(t.startswith("QUESTION:") for t in left), left)
    check("...one out, one in: the section is the same length",
          len(left) == n, (len(left), n))
    check("...and the preamble survives byte for byte",
          B.read(path).startswith(FIXTURE.split("## NEEDS YOU")[0]))
    check("...and the note's `placed` stamp goes with it, leaving no orphan",
          B.read(path).count("<!-- placed:") == len([t for t in left
                                                     if t.startswith(("QUESTION",
                                                                      "INFORMATION",
                                                                      "COMPLETION"))]),
          B.read(path).count("<!-- placed:"))

    # A summon note that WRAPPED is removed whole — a bullet is its first line
    # plus whatever ran on under it, and leaving half of one behind would put an
    # orphan paragraph where the note used to be.
    board(SUM_A + "\n    It is already in those files.")
    bm.note("COMPLETION: **the landed section** - done.", path=path,
            agent_id="wd690a4")
    check("a wrapped summon note is removed whole, continuation and all",
          "already in those files" not in B.read(path), B.read(path))

    # ---- a HANDOFF says `COMMANDED:`, and dies with its result the same way ----
    # [his, 2026-07-29] `SUMMONED:` is a NEW agent and `COMMANDED:` is one
    # already running that was given more work, so he can tell the two apart off
    # the board. The parser has to read BOTH words: a `COMMANDED:` note it did
    # not match would sit under the result forever announcing work the line
    # below it has already reported the end of.
    CMD_A = ("INFORMATION: **the reset tooltip** - COMMANDED: Marbas "
             "(`wd690a4`) for the tooltip")
    board(CMD_A, SUM_B)
    check("a handoff note announces a summon just as a dispatch note does",
          B.summon_of(CMD_A) == {"name": "Marbas", "id": "wd690a4"},
          B.summon_of(CMD_A))
    bm.note("COMPLETION: **the reset tooltip** - it slides left now.",
            path=path, agent_id="wd690a4")
    check("...so a worker's result retires its `commanded` note too",
          not [t for t in texts() if "COMMANDED: Marbas" in t], texts())
    check("...and still leaves the other worker's note alone",
          any("SUMMONED: Zepar" in t for t in texts()), texts())
    import boardwork as bw
    check("the orchestrator is told which word is which, and never to swap them",
          "COMMANDED Marbas" in bw.ORCHESTRATOR_PROMPT
          and "`SUMMONED` is for a `dispatch` ONLY" in bw.ORCHESTRATOR_PROMPT,
          "COMMANDED Marbas" in bw.ORCHESTRATOR_PROMPT)
    check("...and is never told to write that nothing has landed yet",
          "nothing landed yet" not in bw.ORCHESTRATOR_PROMPT,
          "nothing landed yet" in bw.ORCHESTRATOR_PROMPT)
    # The lowercase verbs are the shape this replaced, and the store still holds
    # notes written that way; they must keep being read or they never retire.
    check("the old lowercase wording is still recognised",
          B.summon_of("INFORMATION: **x** - commanded Marbas (`wd690a4`), yes.")
          == {"name": "Marbas", "id": "wd690a4"},
          B.summon_of("INFORMATION: **x** - commanded Marbas (`wd690a4`), yes."))

    # ---- THE SHAPE HE ASKED FOR, 2026-07-30 ----
    # *"the message posted to the board when a minister is summoned should read
    # `SUMMONED [agent] [for/to] [task]` ... it should NOT say INFORMATION: at
    # the beginning"*. So `SUMMONED` is a tag of its own, with nothing in front
    # of it — and, [his, 2026-07-30, later the same day] *"SUMMONED messages
    # should go in their own sub section"*, it heads that sub-section too, with
    # `COMMANDED` filed beside it by `TAG_SECTION`.
    NEW_A = "SUMMONED Marbas (`wd690a4`) to add commit times"
    NEW_B = "COMMANDED Zepar (`w4f82de`) for the flashing titlebar"
    check("a bare `SUMMONED <Name> ...` line is a tagged bullet",
          B.is_tagged(NEW_A) and B.tag_of(NEW_A) == "SUMMONED", B.tag_of(NEW_A))
    check("...and `COMMANDED` is its sibling, in the same shape",
          B.is_tagged(NEW_B) and B.tag_of(NEW_B) == "COMMANDED", B.tag_of(NEW_B))
    check("...and neither needs INFORMATION: in front of it any more",
          B.summon_of(NEW_A) == {"name": "Marbas", "id": "wd690a4"}
          and B.summon_of(NEW_B) == {"name": "Zepar", "id": "w4f82de"},
          (B.summon_of(NEW_A), B.summon_of(NEW_B)))
    board(NEW_A, NEW_B)
    groups = {g["tag"]: [i["text"] for i in g["items"]]
              for g in B.parse(B.read(path))["todoGroups"]}
    check("...while both are DRAWN in the summon subsection, as he asked",
          sorted(groups.get("SUMMONED", []))
          == sorted(B.text(t) for t in (NEW_A, NEW_B)), groups)
    check("...under one heading that says what those lines ARE",
          B.label_of("SUMMONED").startswith("summoned - "),
          B.label_of("SUMMONED"))
    check("...and `COMMANDED` heads no second subsection of its own",
          "COMMANDED" not in groups, list(groups))
    bm.note("COMPLETION: **the landed section** - done.", path=path,
            agent_id="wd690a4")
    check("...and the new shape is retired by its worker's result too",
          not [t for t in texts() if t.startswith("SUMMONED")], texts())
    check("...leaving the other minister's line alone",
          any(t.startswith("COMMANDED Zepar") for t in texts()), texts())

    # An OLD line keeps rendering: the store is full of them and it is his file.
    board(SUM_A)
    old = B.parse(B.read(path))
    check("a summon note written the old way still reads as INFORMATION",
          [t["tag"] for t in old["todo"] if "SUMMONED: Marbas" in t["text"]]
          == ["INFORMATION"],
          [(t["tag"], t["text"][:40]) for t in old["todo"]])

    # PARTIAL and FAILED are results too — a rebuild left pending or a worker
    # that landed nothing is still an outcome he has read.
    for tag in ("PARTIAL", "FAILED"):
        board(SUM_A)
        bm.note("%s: **the landed section** - a rebuild is pending." % tag,
                path=path, agent_id="wd690a4")
        check("a %s retires the summon note as well" % tag,
              not [t for t in texts() if "SUMMONED: Marbas" in t], texts())

    # ---- what must NEVER be removed ----
    board(SUM_A)
    bm.note("QUESTION: **the landed section** - which order?", path=path,
            agent_id="wd690a4")
    check("a QUESTION is not a result, so the summon note stays",
          any("SUMMONED: Marbas" in t for t in texts()), texts())

    board(SUM_A)
    bm.note("INFORMATION: **a fact** - the times come from git.", path=path,
            agent_id="wd690a4")
    check("...nor is an INFORMATION note",
          any("SUMMONED: Marbas" in t for t in texts()), texts())

    board(SUM_A, "INFORMATION: **the cap** - it is 6 now.")
    bm.note("COMPLETION: **the landed section** - done.", path=path,
            agent_id="wd690a4")
    check("a plain INFORMATION note that announces no summon is untouched",
          any("the cap" in t for t in texts()), texts())

    board(SUM_B)
    bm.note("COMPLETION: **something else** - done.", path=path,
            agent_id="wd690a4")
    check("a result from a DIFFERENT worker removes nothing",
          any("SUMMONED: Zepar" in t for t in texts()), texts())

    board(SUM_A)
    bm.note("COMPLETION: **the landed section** - done.", path=path)
    check("a result from nobody in particular removes nothing",
          any("SUMMONED: Marbas" in t for t in texts()), texts())

    # ---- ambiguity is a refusal, never a guess ----
    board(SUM_A, SUM_A.replace("the landed section", "a second job"))
    bm.note("COMPLETION: **the landed section** - done.", path=path,
            agent_id="wd690a4")
    check("two summon notes naming one id: both stay, and nothing is guessed",
          len([t for t in texts() if "SUMMONED: Marbas" in t]) == 2, texts())

    # A note with NO id falls back to the NAME — that is the older shape, and
    # the fallback is deliberately only for a note that carries no id at all: a
    # name can be moved off a live agent (`boardagents.pick_name`), an id never.
    board("INFORMATION: **an older summon** - summoned Marbas, nothing yet.")
    bm.note("COMPLETION: **an older summon** - done.", path=path,
            agent_id=_id_named("Marbas"))
    check("an id-less summon note is matched by NAME",
          not [t for t in texts() if "summoned Marbas" in t], texts())

    board(SUM_A)
    bm.note("COMPLETION: **the landed section** - done.", path=path,
            agent_id=_id_named("Marbas"))
    check("...but a name match never overrides an id that says otherwise",
          any("SUMMONED: Marbas" in t for t in texts()), texts())

    # ---- the several-results case: each takes its own, one call at a time ----
    board(SUM_A, SUM_B)
    bm.note("COMPLETION: **the landed section** - done.", path=path,
            agent_id="wd690a4")
    bm.note("PARTIAL: **the commit times** - a rebuild is pending.", path=path,
            agent_id="w4f82de")
    left = texts()
    check("two workers reporting clears two summon notes and no more",
          not [t for t in left if "SUMMONED" in t] and len(left) == 3, left)

    # ---- and the OTHER writer of a result passes the id explicitly ----
    # board-watch writes the failure note for a worker whose process is gone, so
    # `BOARD_AGENT_ID` there names the watcher and not the worker that died. It
    # is checked as SOURCE, like the templates above: the copy that runs is
    # whatever the last rebuild put in the store.
    watch = os.path.join(os.path.dirname(APPS), "home", "srvs",
                         "board-watch-files", "board-watch.py")
    src = open(watch).read() if os.path.exists(watch) else ""
    check("board-watch's dead-worker note names the worker it is a result for",
          re.search(r"WORKER_FAIL\.format\(.*?agent_id=", src, re.S), bool(src))


def _id_named(name):
    """An agent id whose derived name is `name` — the harness's way of asking
    for the id that goes with a name, since the mapping is one-way."""
    import boardagents as ba
    for i in range(4096):
        aid = "w%04x" % i
        if ba.name_for(aid) == name:
            return aid
    raise AssertionError("no id derives the name %r" % name)


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
    """*"i should be able to remove items from the 'to do' section"*.

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
    import boardwork as bw

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
    # HIS OWN SESSIONS ARE NOT BOARD WORK — [his, 2026-07-31] *"agents started
    # by the user can be hidden from the triangle"*. The row above (no name, no
    # --where) is HIS terminal, so it is dropped from the window's cards while
    # the agent-facing CLI listing (`groups()`, which is `boardctl.py agents`)
    # keeps it: that is a collision check where a live session of his matters.
    bom = ba.agents(procs=fake)
    cli = [a["id"] for g in bw.groups(agents=bom) for a in g["rows"]
           if a["kind"] == "session"]
    tri = [a["id"] for a in bw.cards(agents=bom) if a["kind"] == "session"]
    check("his interactive session stays in the CLI listing, hidden from the triangle",
          [a["id"] for a in bom if a["kind"] == "session"] == cli and not tri,
          ([a["id"] for a in bom if a["kind"] == "session"], cli, tri))
    for aid in ("unit-worker", "tick-agent"):
        p = os.path.join(ba.agents_dir(), "%s.json" % aid)
        if os.path.exists(p):
            os.unlink(p)

    # ---- the watcher's own state, said honestly ----
    # Against a SCRATCH state dir: the kill switch is read off the filesystem
    # and `board-watch.py` resolves it under `~` and not under `$XDG_STATE_HOME`
    # (which is why `watch_kill_switch()` exists), so without this the answers
    # below would depend on whether the machine running the tests has the
    # watcher switched off.
    wstate = os.path.join(os.path.dirname(ba.agents_dir()), "watch-scratch")
    os.makedirs(wstate, exist_ok=True)
    os.environ["BOARD_WATCH_STATE"] = wstate
    #: Service block, then path block, the order `_ask_systemd` asks in.
    ARMED = "ActiveState=inactive\n\nActiveState=active\n"
    check("an unaskable watcher says so rather than looking healthy",
          "could not be asked" in ba.watcher_state("")["text"])
    check("...and does not claim armed OR unarmed off a systemctl we never ran",
          ba.watcher_state("")["armed"] is None)
    check("a failed watcher is reported as failed",
          "failed" in ba.watcher_state("ActiveState=failed\n")["text"]
          and ba.watcher_state("ActiveState=failed\n")["armed"] is False)
    check("an idle watcher reads as armed, not as broken",
          "armed" in ba.watcher_state(ARMED)["text"]
          and ba.watcher_state(ARMED)["armed"] is True)
    # The service is `inactive` BETWEEN ticks whether or not anything will ever
    # start one, so the service alone cannot answer this: asking it only is what
    # used to report a dead feature as armed.
    check("...but a stopped path unit is NOT armed, however idle the service",
          ba.watcher_state("ActiveState=inactive\n\nActiveState=inactive\n")
            ["armed"] is False)
    # NEVER DEPLOYED here is a different sentence from STOPPED, because only one
    # of them tells him what to run. `systemctl show` answers for a unit that
    # does not exist with an ordinary `ActiveState=inactive`, so LoadState is
    # the only tell.
    NOTHERE = ("ActiveState=inactive\nLoadState=not-found\n\n"
               "ActiveState=inactive\nLoadState=not-found\n")
    check("a watcher that was never deployed on this host says so, and names it",
          ba.watcher_state(NOTHERE)["armed"] is False
          and "not installed" in ba.watcher_state(NOTHERE)["text"]
          and os.uname().nodename in ba.watcher_state(NOTHERE)["text"])
    check("...and a LOADED but stopped one keeps the old wording",
          "path unit is" in ba.watcher_state(
              "ActiveState=inactive\nLoadState=loaded\n\n"
              "ActiveState=inactive\nLoadState=loaded\n")["text"])
    open(ba.watch_kill_switch(), "w").close()
    check("...and neither is one he has switched off at the kill switch",
          ba.watcher_state(ARMED)["armed"] is False
          and "switched off" in ba.watcher_state(ARMED)["text"])
    os.unlink(ba.watch_kill_switch())
    check("...which re-arms by deleting that file and nothing else",
          ba.watcher_state(ARMED)["armed"] is True)

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


def _tsc_usage(tmp, uuid_, model, usage):
    """One assistant entry carrying only a `usage` stamp, which is where the
    context tally is measured from. Same file the tool calls go in."""
    d = os.path.join(tmp, "transcripts", "-proj")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, uuid_ + ".jsonl")
    # The half-written line the live-append test leaves behind is real - the
    # platform finishes it. Start a new line rather than gluing onto it.
    lead = "\n" if os.path.exists(p) and open(p, "rb").read()[-1:] not in (b"\n", b"") \
        else ""
    with open(p, "a") as f:
        f.write(lead
                + json.dumps({"type": "assistant", "timestamp": "2026-07-29T00:00:00Z",
                              "message": {"model": model, "usage": usage,
                                          "content": []}}) + "\n")
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
    # ...and `none` is a GRACE too, for the same reason `starting` is. A worker
    # that wedges before its first API call is linked, has a transcript, and
    # writes nothing into it ever; `none` is what holds a card in its bare
    # *"<name> arises..."* form (`boardagents.arising`), so an unbounded `none`
    # would leave a stuck minister claiming forever that it is on its way —
    # and under the older `speaks` gate it was UNDRAWABLE outright, measured on
    # top 2026-07-31 at 45 minutes invisible on 100% of one core. Past the
    # grace it is `silent`, which says so.
    bph.observe("ph-silent", session=u)          # its own id: `ph-a` is reused
    p = bph.sidecar("ph-silent")                 # further down and must not move
    rec = json.load(open(p))
    rec["linkedAt"] = time.time() - bph.START_GRACE_S - 5
    with open(p, "w") as f:
        json.dump(rec, f)
    r = bph.observe("ph-silent", session=u)
    check("a linked agent that has NEVER acted goes silent past the grace",
          r["observed"] == "silent", (r["observed"], bph.actually(r)))
    check("...and says it never started, rather than 'nothing yet'",
          bph.actually(r) == "not started - nothing in its transcript at all"
          and bph.doing_line(r, "Halphas")
          == "not started - nothing in its transcript at all",
          (bph.actually(r), bph.doing_line(r, "Halphas")))
    check("...and its card is NOT withheld, which is the whole point",
          r["observed"] not in ("none", "starting"), r["observed"])

    r = bph.observe("ph-none")
    check("an agent with NO session says it cannot be observed, and never guesses",
          r["observed"] == "unlinked" and "cannot see what it is doing"
          in bph.actually(r), bph.actually(r))

    # ---- a spawn of ours whose transcript is seconds away is STARTING ----
    # [his, 2026-07-29] *"when solomon first takes a request, his section very
    # briefly shows 'cannot see what solomon is doing' and then changes to
    # 'Solomon is getting ready' - it shouldnt show that breif initial 'dont
    # know' text"*. The two used to collapse into `unlinked`, and the young case
    # picked the wrong sentence for as long as the CLI took to write its file.
    r = bph.observe("ph-young", session="99999999-8888-7777-6666-555555555555")
    check("a session id with no transcript YET is starting, not unobservable",
          r["observed"] == "starting" and bph.actually(r) == "nothing yet",
          (r["observed"], bph.actually(r)))
    check("...and its card line never says the board cannot see it",
          bph.doing_line(r, "Solomon") == "nothing yet",
          bph.doing_line(r, "Solomon"))
    check("...and it is not filed under a phase it has not reached",
          r["phase"] == "unreported", r["phase"])
    # ...and it is a GRACE, not a synonym: a spawn whose transcript never turns
    # up is a real failure and goes back to saying so.
    p = bph.sidecar("ph-young")
    rec = json.load(open(p))
    rec["linkedAt"] = time.time() - bph.START_GRACE_S - 5
    with open(p, "w") as f:
        json.dump(rec, f)
    r = bph.observe("ph-young")
    check("...but past the grace it is unobservable again, and says so",
          r["observed"] == "unlinked" and "cannot see what it is doing"
          in bph.actually(r), (r["observed"], bph.actually(r)))

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
    # TWO LINES, not one hyphenated one — [his, 2026-07-29] *"[agent]
    # [verb]s..."* and then the words it gave, verbatim, underneath. The ticking
    # dots are the TOP line's and no other line's — *"the only line of an agents
    # card that should have the animated elipsies is the top line. no others"*.
    check("a card's first sentence is the agent's own claim, led by its name",
          bph.says_line(r, "Marbas") == "Marbas is testing..."
          and bph.says_detail(r) == "the parser round-trips",
          (bph.says_line(r, "Marbas"), bph.says_detail(r)))
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
          bph.says_line(r) == "it is testing..."
          and bph.doing_line(r) == "editing Main.qml",
          (bph.says_line(r), bph.doing_line(r)))
    # ---- SIMPLE PRESENT, and an ellipsis that MOVES ----
    # [his, 2026-07-29] *"instead of the agent verb-part being 'is researching'
    # or 'is coding' etc it should just say 'researches...' or 'codes...' with
    # animated elipsies"*. One table (`PHASE_PREDICATE`) decides the verb form
    # for every card, his included, so it cannot drift between them — and the
    # three trailing cells are ASCII, never U+2026, which would drop the line
    # ~5px on the fallback font (docs/DESIGN.md §2.3).
    check("the verb-part is `is <word>`, which is his wording twice over",
          bph.says_line({"claimPhase": "researching"}, "Marbas")
          == "Marbas is researching..."
          and bph.says_line({"claimPhase": "coding"}, "Marbas")
          == "Marbas is coding...",
          (bph.says_line({"claimPhase": "researching"}, "Marbas"),
           bph.says_line({"claimPhase": "coding"}, "Marbas")))
    # The dots go on the TOP line and NOWHERE ELSE — [his, 2026-07-29, settling
    # a reversal] *"the only line of an agents card that should have the animated
    # elipsies is the top line. no others"*. He had asked for the opposite earlier
    # the same evening; this is the later word.
    check("...and the ticking dots sit on the verb line, and on no other",
          bph.says_line({"claimPhase": "researching"},
                        "Marbas").endswith("...")
          and bph.says_detail({"claimPhase": "researching",
                               "claimDoing": "the parser"}) == "the parser",
          (bph.says_line({"claimPhase": "researching"}, "Marbas"),
           bph.says_detail({"claimPhase": "researching",
                            "claimDoing": "the parser"})))
    check("...and the ellipsis is three ASCII periods, never one glyph (2.3)",
          all(ord(c) < 128 for w in bph.PHASE_WORDS
              for c in bph.says_line({"claimPhase": w}, "Marbas")
              + bph.says_detail({"claimPhase": w, "claimDoing": "x"})),
          [w for w in bph.PHASE_WORDS
           if any(ord(c) > 127 for c in bph.says_line({"claimPhase": w}, "M"))])
    # `blocked` is the one word in the list that is not a gerund, so its
    # predicate keeps the auxiliary — `blocks` says the opposite — and it gets NO
    # ticking dots: a stall is not motion, which is §10's rule and the same one
    # that scopes the observed line's own tick to `observed == "ok"`.
    # ...and the words do not open by repeating the verb the line above ends on —
    # [his, 2026-07-29] *"if the verb at the end of the top line is the same as
    # the verb at the start of the second line, then hide the verb"*. Every
    # separator an agent actually writes, case-insensitively, and only ever the
    # LEADING word.
    def _detail(phase, doing):
        return bph.says_detail({"claimPhase": phase, "claimDoing": doing})

    check("the claim's words never repeat the verb the line above ends on",
          (_detail("coding", "coding - writing highlight.py"),
           _detail("coding", "Coding: writing highlight.py"),
           _detail("coding", "coding \u2014 writing highlight.py"),
           _detail("coding", "coding writing highlight.py"))
          == ("writing highlight.py",) * 4,
          _detail("coding", "coding - writing highlight.py"))
    check("...but a DIFFERENT verb is left exactly as the agent wrote it",
          _detail("coding", "testing - the parser") == "testing - the parser",
          _detail("coding", "testing - the parser"))
    check("...and it is a word boundary, not a prefix match",
          _detail("coding", "codingstyle rules") == "codingstyle rules",
          _detail("coding", "codingstyle rules"))
    check("...and words that are ONLY the verb stay, rather than going blank",
          _detail("reading", "reading") == "reading",
          _detail("reading", "reading"))
    check("...but a STALL keeps `is blocked`, and does not animate",
          bph.says_line({"claimPhase": "blocked"}, "Marbas") == "Marbas is blocked"
          and bph.says_detail({"claimPhase": "blocked",
                               "claimDoing": "the merge"}) == "the merge",
          (bph.says_line({"claimPhase": "blocked"}, "Marbas"),
           bph.says_detail({"claimPhase": "blocked", "claimDoing": "the merge"})))
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

    # ---- HOW FULL IT IS: measured out of the transcript, or ABSENT ----
    # *"on the very right of the top row of the agent's information box it
    # should keep a running tally of how much context that agent has vs how much
    # it can handle"*. The claims: nothing is estimated, the cached context is
    # counted (it is the bulk of it), the window comes from the model id rather
    # than from an assumption, and anything unmeasured draws NOTHING - never a
    # zero, which would be a claim that the agent is empty.
    check("an agent whose transcript never stated a usage shows no tally",
          bph.context_line(bph.observe("ph-a")) == "",
          bph.context_line(bph.observe("ph-a")))
    check("...and half a measurement is no measurement",
          (bph.context_line({"ctxUsed": 5000}), bph.context_line({"ctxWindow": 200000}),
           bph.context_line({"ctxUsed": 0, "ctxWindow": 0}),
           bph.context_line({}), bph.context_line(None)) == ("", "", "", "", ""))
    _tsc_usage(tmp, u, "claude-opus-5", {"input_tokens": 1200,
                                         "cache_read_input_tokens": 58000,
                                         "cache_creation_input_tokens": 2600})
    r = bph.observe("ph-a")
    check("a tally counts the CACHED context too, or it is an order of magnitude out",
          bph.context_line(r) == "62k/200k",
          (r.get("ctxUsed"), bph.context_line(r)))
    check("...and it survives a poll that reads nothing new, rather than blinking off",
          bph.context_line(bph.observe("ph-a")) == "62k/200k",
          bph.context_line(bph.observe("ph-a")))
    _tsc_usage(tmp, u, "claude-opus-5[1m]", {"input_tokens": 300000})
    r = bph.observe("ph-a")
    check("...and the WINDOW is read from the model id when the id says",
          bph.context_line(r) == "300k/1m", bph.context_line(r))

    # ---- THE DENOMINATOR IS EVIDENCE, NOT THE STAMP ----
    # His: *"sometimes itll show the active context as being larger than the max
    # context so idk what that really means is some context getting lost or is it
    # just not reporting correctly"*. It was mis-reporting, and nothing was lost.
    # Measured 2026-07-29 over 188 transcripts in ~/.claude/projects: NOT ONE of
    # ~38k assistant entries stamped `[1m]`, while 29 sessions climbed past 200k
    # - one to 582k, monotonically, with no compaction, which a 200k model
    # cannot do. So `[1m]` is a hint that is nearly always missing, and the
    # window shown is the smallest one that HOLDS what was measured (§10).
    check("a session that stood in 450k was on a 1m model, whatever its id said",
          bph._fits(450_000) == bph.CONTEXT_WINDOW_1M
          and bph._fits(62_000) == bph.CONTEXT_WINDOW
          and bph._fits(200_000) == bph.CONTEXT_WINDOW,
          (bph._fits(450_000), bph._fits(62_000), bph._fits(200_000)))
    check("...and past every window a Claude model has, there is nothing honest to draw",
          bph._fits(2_000_000) == 0, bph._fits(2_000_000))
    u2 = "66666666-7777-8888-9999-aaaaaaaaaaaa"
    _tsc_usage(tmp, u2, "claude-opus-5", {"cache_read_input_tokens": 452000})
    r = bph.observe("ph-b", session=u2)
    check("an unstamped 1m session is never drawn as 452k/200k - the impossible state",
          bph.context_line(r) == "452k/1m", (r.get("ctxWindow"), bph.context_line(r)))
    _tsc_usage(tmp, u2, "claude-opus-5", {"cache_read_input_tokens": 90000})
    r = bph.observe("ph-b")
    check("...and compacting back to 90k does not shrink the window it proved",
          bph.context_line(r) == "90k/1m", (r.get("ctxPeak"), bph.context_line(r)))
    check("a record written before any of this still cannot draw the impossible",
          (bph.context_line({"ctxUsed": 452_000, "ctxWindow": 200_000}),
           bph.context_line({"ctxUsed": 9_000_000, "ctxWindow": 200_000}))
          == ("452k/1m", ""),
          (bph.context_line({"ctxUsed": 452_000, "ctxWindow": 200_000}),
           bph.context_line({"ctxUsed": 9_000_000, "ctxWindow": 200_000})))
    check("a small count is not dressed up as thousands",
          (bph._k(812), bph._k(1500), bph._k(1_200_000)) == ("812", "2k", "1.2m"),
          (bph._k(812), bph._k(1500), bph._k(1_200_000)))
    check("...and the tally carries no time, no age and no percentage",
          not re.search(r"%|ago|\bs\b", bph.context_line(r)), bph.context_line(r))

    # ---- ...and HOW LONG IT HAS BEEN WORKING, beside that tally ----
    # His, 2026-07-29, replacing the absolute spawn stamp he asked for that
    # morning: the card shows *"how long the agent has been working"* — the ONE
    # elapsed time this app draws, his own deliberate exception to the
    # no-pressure rule. `boardphase.worked_line` carries the whole argument.
    now = time.time()
    check("a card says how long its agent has been working, in words",
          bph.worked_line(now - 4 * 60) == "working for 4 minutes",
          bph.worked_line(now - 4 * 60))
    check("...reading naturally at every age, never as a seconds counter",
          (bph.worked_line(now - 5), bph.worked_line(now - 61),
           bph.worked_line(now - 3600), bph.worked_line(now - 3900))
          == ("working for under a minute", "working for 1 minute",
              "working for 1 hour", "working for 1 hour 5 minutes"),
          (bph.worked_line(now - 5), bph.worked_line(now - 3900)))
    check("...and a STOPPED agent counts nothing - born-to-now is not how long "
          "a dead process worked",
          bph.worked_line(now - 300, running=False) == "",
          bph.worked_line(now - 300, running=False))
    check("...and nothing is invented for a record that carries no stamp",
          (bph.worked_line(0), bph.worked_line(None), bph.worked_line("x"))
          == ("", "", ""),
          (bph.worked_line(0), bph.worked_line(None), bph.worked_line("x")))

    # ---- ANY ONE WORD, not the classic five ----
    # *"allow agents more freedom to indicate what they are doing, but it should
    # still only be a single word - and still actually related to what they say
    # they are doing"*. What is still enforced is only what protects the card:
    # one word, letters, short. The honesty check is the OBSERVED line under it,
    # which the agent cannot write — that is why a free word is safe.
    check("a claim may be any single word now, not one of five",
          (bph.clean_phase_word("Bisecting"), bph.clean_phase_word("  waiting "),
           bph.clean_phase_word("code-review"), bph.clean_phase_word("coding"))
          == ("bisecting", "waiting", "code-review", "coding"))
    check("...but it is ONE word, refused rather than truncated to its first",
          (bph.clean_phase_word("code review"), bph.clean_phase_word("!!"),
           bph.clean_phase_word("v2"), bph.clean_phase_word("x" * 40),
           bph.clean_phase_word(""), bph.clean_phase_word(None)) == ("",) * 6)
    bph.claim("ph-a", "bisecting", "which commit broke the harness")
    r = bph.observe("ph-a")
    check("...and a free word is drawn as the card's own first line",
          bph.says_line(r, "Marbas") == "Marbas is bisecting..."
          and bph.says_detail(r) == "which commit broke the harness",
          (bph.says_line(r, "Marbas"), bph.says_detail(r)))
    check("...while the card is still FILED by what it is OBSERVED doing",
          r["phase"] in bph.CLAIMABLE and r["phase"] != "bisecting", r["phase"])
    # THE MENU. [his, 2026-07-29] *"create a larger list of words that could
    # describe what an agent is doing ... and allow agents to select from this
    # new larger list"*. It is offered, not enforced — so the thing to assert is
    # that every word on it is one the code would actually accept, and that the
    # block the prompt shows is generated FROM it rather than typed out beside
    # it, which is the only way the two can disagree.
    import boardwork as bw
    bad = [w for w in bph.PHASE_WORDS if bph.clean_phase_word(w) != w]
    check("every word on the offered menu survives clean_phase_word", not bad,
          str(bad))
    check("...and none is listed twice",
          len(set(bph.PHASE_WORDS)) == len(bph.PHASE_WORDS))
    check("...and the classic five are still on it, first",
          bph.PHASE_WORDS[:5] == bph.CLAIMABLE, str(bph.PHASE_WORDS[:5]))
    def _says(w):
        # every word bar the one stall ticks, and the tick is the top line's
        return "Marbas is %s%s" % (w, "" if w in bph.TICKLESS else "...")
    check("...and each reads as English after \"is\"",
          all(bph.says_line({"claimPhase": w}, "Marbas") == _says(w)
              for w in bph.PHASE_WORDS),
          [w for w in bph.PHASE_WORDS
           if bph.says_line({"claimPhase": w}, "Marbas") != _says(w)])
    check("...and a word that is NOT on the menu reads the same way",
          bph.says_line({"claimPhase": "yakshaving"}, "Marbas")
          == "Marbas is yakshaving...",
          bph.says_line({"claimPhase": "yakshaving"}, "Marbas"))
    menu = bw.phase_word_menu()
    check("the prompt's menu block is generated from the list, not retyped",
          all(("`%s`" % w) in menu for w in bph.PHASE_WORDS))
    check("...and the worker prompt actually carries it",
          menu in bw.WORKER_PROMPT.format(
              repo="R", host="H", task="T", rules="X", name="N", aid="a",
              context="", phase_words=menu))
    # ...and a word NOT on it is still accepted, because it is a menu.
    bph.claim("ph-a", "yakshaving", "the third yak")
    check("a word that is not on the menu is still a legal claim",
          bph.observe("ph-a").get("claimPhase") == "yakshaving",
          bph.observe("ph-a").get("claimPhase"))
    bph.claim("ph-a", "bisecting", "which commit broke the harness")

    refused = False
    try:
        bph.claim("ph-a", "code review", "")
    except ValueError:
        refused = True
    check("a claim that cannot be drawn is REFUSED, never silently dropped",
          refused)
    check("...leaving the last good claim standing rather than blanking the line",
          bph.observe("ph-a").get("claimPhase") == "bisecting",
          bph.observe("ph-a").get("claimPhase"))
    import subprocess
    cli = os.path.join(BOARD, "tools", "boardctl.py")
    env = dict(os.environ, BOARD_AGENT_ID="ph-a")
    ok = subprocess.run([sys.executable, cli, "phase", "measuring",
                         "--doing", "the fan curve"],
                        capture_output=True, text=True, env=env)
    bad = subprocess.run([sys.executable, cli, "phase", "code review"],
                         capture_output=True, text=True, env=env)
    check("the CLI takes a free word instead of rejecting it out of a fixed list",
          ok.returncode == 0 and "measuring" in ok.stdout,
          (ok.returncode, ok.stdout.strip()[:90], ok.stderr.strip()[:90]))
    check("...and says why when it will not take one, on stderr, nonzero",
          bad.returncode != 0 and "ONE word" in bad.stderr,
          (bad.returncode, bad.stderr.strip()[:120]))


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
    check("...the full Goetia, in the traditional order 1 Bael...72 Andromalius, "
          "keeping the pre-72 pool's spellings where they overlap",
          len(ba.NAMES) == 72 and ba.NAMES[0] == "Bael"
          and ba.NAMES[71] == "Andromalius" and ba.NAMES[20] == "Marax"
          and ba.NAMES[63] == "Haures" and ba.NAMES[24] == "Glasya"
          and ba.NAMES[57] == "Amy", (len(ba.NAMES), ba.NAMES[:5]))
    check("...and no two collide, since `inbox send --to` matches on the name",
          len({n.lower() for n in ba.NAMES}) == len(ba.NAMES))
    check("...with room in the pool to walk past every live agent",
          len(ba.NAMES) >= 24, len(ba.NAMES))
    check("a task queued above the cap is given no name, having nobody on it",
          all(r["name"] == "" for x in bw.groups() if x["phase"] == "queued"
              for r in x["rows"]))

    # ---- SOLOMON: one fixed name, pinned to the top, and always there ----
    # *"make the main orchestrators name Solomon. he should always be kept on
    # the top of the agent list and should basically indicate like he's there
    # and ready to go at all times when hes not doing something."* Three claims,
    # and they are separable: the NAME (fixed, out of the pool), the PLACE
    # (first, whatever was born when), and the PRESENCE (a row even with no
    # orchestrator on the machine at all).
    check("Solomon is not in the worker pool, so no worker can be him",
          ba.ORCHESTRATOR_NAME not in ba.NAMES
          and ba.ORCHESTRATOR_NAME.lower() not in {n.lower() for n in ba.NAMES},
          ba.ORCHESTRATOR_NAME)
    check("...and the collision shuffle never reaches him, pool exhausted or not",
          ba.pick_name("wanything", taken=set(ba.NAMES)) != ba.ORCHESTRATOR_NAME
          and ba.name_for("worch") != ba.ORCHESTRATOR_NAME)
    check("...and he is ASCII, which the font can draw (2.3)",
          ba.ORCHESTRATOR_NAME.isascii() and ba.ORCHESTRATOR_NAME.isalpha())
    orec = ba.register("orch-1", "what he typed", os.getpid(),
                       kind="orchestrator", where="board-watch")
    check("an orchestrator is named Solomon, whatever its id would have hashed to",
          orec["name"] == ba.ORCHESTRATOR_NAME
          and ba.name_of("orch-1") == ba.ORCHESTRATOR_NAME, orec)
    orec2 = ba.register("orch-2", "and the next thing", os.getpid(),
                        kind="orchestrator", name="Marbas")
    check("...and a caller cannot name one anything else",
          orec2["name"] == ba.ORCHESTRATOR_NAME, orec2)
    # ---- and the FIRST thing his card says is that he is starting up ----
    # [his, 2026-07-29] *"when solomon first takes a request, his section very
    # briefly shows 'cannot see what solomon is doing' and then changes to
    # 'Solomon is getting ready' - it shouldnt show that breif initial 'dont
    # know' text"*. A spawn's transcript does not exist for a second or two, and
    # that used to reach `unlinked` — the same branch an unobservable interactive
    # session takes. Registered here exactly as a spawn is: a session id we
    # chose, and no file at it yet.
    #
    # The two states now say two DIFFERENT things, in his own words and in his
    # order: *"Solomon wields the ring..."* while the transcript is still coming,
    # then *"Solomon etches the circle..."* once it is there and nothing has
    # happened in it. That ordering is the point — the brief initial line LEADS,
    # which is what collapsing the pair onto one sentence took away.
    ba.register("orch-fresh", "what he just typed", os.getpid(),
                kind="orchestrator", where="board-watch",
                session="deadbeef-0000-1111-2222-333344445555")
    fresh = [a for a in ba.agents() if a["id"] == "orch-fresh"]
    check("a freshly spawned Solomon wields the ring, and never `cannot see`",
          len(fresh) == 1
          and fresh[0]["doingLine"] == "%s wields the ring..." % ba.ORCHESTRATOR_NAME,
          [a.get("doingLine") for a in fresh])
    check("...and that is the ONLY thing it says, in either sentence",
          fresh and "cannot see" not in (fresh[0]["doingLine"]
                                        + fresh[0]["saysLine"]),
          [(a.get("saysLine"), a.get("doingLine")) for a in fresh])
    import boardphase as bph
    check("...and the brief initial line LEADS the getting-ready one",
          (bph.orch_doing_line("starting"), bph.orch_doing_line("none"))
          == ("%s wields the ring..." % ba.ORCHESTRATOR_NAME,
              # the CIRCLE is Solomon's — [his, 2026-07-29] the magician stands
              # in it; `triangle` now names the agents area the ministers sit in
              "%s etches the circle..." % ba.ORCHESTRATOR_NAME),
          (bph.orch_doing_line("starting"), bph.orch_doing_line("none")))
    check("...while a worker keeps the honest bare placeholder",
          bph.doing_line({"observed": "starting"}, "Marbas") == "nothing yet",
          bph.doing_line({"observed": "starting"}, "Marbas"))
    ba.unregister("orch-fresh")   # the checks below count the live ones
    ocards = bw.cards()
    check("two overlapping orchestrators are both Solomon, and both on top",
          [c["kind"] for c in ocards[:2]] == ["orchestrator"] * 2
          and [c["name"] for c in ocards[:2]] == [ba.ORCHESTRATOR_NAME] * 2
          and not any(c.get("kind") == "orchestrator" for c in ocards[2:]),
          [(c["id"], c.get("kind"), c.get("name")) for c in ocards])
    check("...and the standing row gives way to them, so he is never doubled",
          not any(c.get("state") == "idle" for c in ocards),
          [c.get("state") for c in ocards])
    # The pin is what is under test here, so the births are hand-built: an
    # orchestrator started LAST would sort to the bottom on birth alone, which
    # is the case the pin exists for and the one a real spawn cannot produce
    # (board-watch registers the orchestrator against its own long-lived tick).
    younger = bw.cards(
        agents=[{"id": "w-old", "kind": "worker", "name": "Marbas",
                 "born": 1.0, "state": "running"},
                {"id": "orch-late", "kind": "orchestrator",
                 "name": ba.ORCHESTRATOR_NAME, "born": 9.0, "state": "running"}],
        pend=[])
    check("...even when the orchestrator is the youngest thing on the list",
          [c["id"] for c in younger] == ["orch-late", "w-old"],
          [c["id"] for c in younger])
    ba.unregister("orch-1")
    ba.unregister("orch-2")
    idle = bw.cards()[0]
    check("with NO orchestrator running, Solomon still holds the top row",
          idle.get("name") == ba.ORCHESTRATOR_NAME
          and idle.get("state") == "idle", idle)
    check("...leading with his NAME, the way every other card does",
          idle.get("saysLine") == "%s awaits" % ba.ORCHESTRATOR_NAME,
          idle.get("saysLine"))
    check("...and never as work in flight: nothing pretends to observe him",
          idle.get("doingLine") == "" and idle.get("running") is False
          and idle.get("observed") == "unlinked", idle)
    # [his, 2026-07-29] the resting card is TWO lines and this is both of them:
    # `Solomon awaits` above, his own sentence below, and nothing after it. The
    # window draws `describe()` and not the row's own `detail`, so both are
    # checked — a third line coming back through either one is the regression.
    check("...the second line being his sentence, verbatim and with the stop",
          idle.get("title") == "summons a minister to do your bidding.",
          idle.get("title"))
    check("...and NO third line, from either of the two things that feed one",
          ba.describe(idle) == "" and idle.get("detail") == "",
          (ba.describe(idle), idle.get("detail")))
    check("...offered no inbox, there being nobody there to read one",
          idle.get("id") == "", idle)
    # ...and the card of a LIVE Solomon leads with his name, which is the one
    # that did not. [his, 2026-07-29] the orchestrator's card should read
    # "Solomon is ..." like everybody else's. It never did, for one reason: with
    # no claim, `says_line` is "" and the top line becomes the OBSERVED one,
    # which names nobody by design. The fix is not to manufacture a claim for
    # him — it is to tell him to make one, the way every worker is told.
    # ...and he is told to DELEGATE rather than scope. [his, 2026-07-29] *"it
    # seems like solomon does a ton of work himself"*. His run is waited on and
    # holds the tick, so reading the repo to plan delays every later item.
    check("the orchestrator is told to delegate fast, not to scope the work",
          "DELEGATE FAST" in bw.ORCHESTRATOR_PROMPT
          and "goes into the TASK TEXT" in bw.ORCHESTRATOR_PROMPT)
    check("...while the checks that prevent a real mistake are still in it",
          all(s in bw.ORCHESTRATOR_PROMPT for s in (
              "Run `agents` before you dispatch",
              "touch the same files are ONE dispatch",
              "DISPATCH OR ASK",
              "At most two questions",
              "MUST carry `--if-unanswered`")))
    check("the orchestrator is told to claim a phase, or his card names nobody",
          "boardctl.py phase " in bw.ORCHESTRATOR_PROMPT
          and "SAY WHAT YOU ARE DOING" in bw.ORCHESTRATOR_PROMPT)
    import boardphase as _bph
    # ...and it is in HIS OWN VOICE for the two words he actually uses [his,
    # 2026-07-29]: `dispatching` is *"Solomon is summoning..."* — the dots are
    # the animated three cells `AgentRow.tick` cycles, so the sentence has to
    # END in them — and `waiting` is
    # *"Solomon awaits <agent>..."*, which NAMES whoever he is waiting on.
    # Everything else on his card goes through the one shared predicate table, so
    # the verb form cannot drift between his card and a worker's.
    check("...and once he has, his card's FIRST line is his name",
          _bph.orch_says_line({"claimPhase": "dispatching",
                               "claimDoing": "three pieces of what you typed"},
                              ba.ORCHESTRATOR_NAME)
          == "Solomon is summoning...",
          _bph.orch_says_line({"claimPhase": "dispatching",
                               "claimDoing": "three pieces of what you typed"},
                              ba.ORCHESTRATOR_NAME))
    check("...and waiting NAMES the one he is waiting on, with moving dots",
          (_bph.orch_says_line({"claimPhase": "waiting"}, "Solomon", "Marbas"),
           _bph.orch_says_line({"claimPhase": "waiting"}, "Solomon", "his workers"),
           _bph.orch_says_line({"claimPhase": "waiting"}, "Solomon", ""))
          == ("Solomon awaits Marbas...", "Solomon awaits his workers...",
              "Solomon awaits..."),
          _bph.orch_says_line({"claimPhase": "waiting"}, "Solomon", "Marbas"))
    check("...and never an empty name or the literal word `agent`",
          "agent" not in _bph.orch_says_line({"claimPhase": "waiting"},
                                             "Solomon", ""),
          _bph.orch_says_line({"claimPhase": "waiting"}, "Solomon", ""))
    check("...while any other word of his takes the shared table, like a worker",
          _bph.orch_says_line({"claimPhase": "reading"}, "Solomon")
          == _bph.says_line({"claimPhase": "reading"}, "Solomon")
          == "Solomon is reading...",
          _bph.orch_says_line({"claimPhase": "reading"}, "Solomon"))
    check("...and drawn exactly once, and in the same place on the next poll",
          [c.get("name") for c in bw.cards()].count(ba.ORCHESTRATOR_NAME) == 1
          and [c["id"] for c in bw.cards()] == [c["id"] for c in bw.cards()],
          [c.get("name") for c in bw.cards()])
    check("...and nothing under him moved to make room",
          [c["id"] for c in bw.cards()[1:]]
          == [c["id"] for c in ocards[2:]],
          ([c["id"] for c in bw.cards()], [c["id"] for c in ocards]))

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

    # ---- which model orchestrates: his choice, read at every spawn ----
    check("with nothing chosen, the default orchestrates",
          not os.path.exists(bw.orch_model_file())
          and bw.orch_model() == bw.DEFAULT_ORCH_MODEL, bw.orch_model())
    check("a name he half-remembers resolves, ambiguity does not",
          bw.resolve_model("opus") == "claude-opus-5"
          and bw.resolve_model("haiku") == "claude-haiku-4-5-20251001")
    for bad in ("5", "gpt", ""):
        try:
            bw.resolve_model(bad)
            check("...%r is refused rather than guessed" % bad, False)
        except ValueError:
            check("...%r is refused rather than guessed" % bad, True)
    check("choosing one writes it, and it is what the next spawn reads",
          bw.set_orch_model("sonnet") == "claude-sonnet-5"
          and bw.orch_model() == "claude-sonnet-5"
          and bw.role_flags("orchestrator")[:2] == ["--model", "claude-sonnet-5"],
          bw.role_flags("orchestrator"))
    # The whole of "changing it mid-run applies to the NEXT prompt" is that this
    # is a file read per spawn, with nothing cached and nothing signalled.
    bw.set_orch_model("opus")
    check("...and changing it again changes the next spawn, with no restart",
          bw.role_flags("orchestrator")[:2] == ["--model", "claude-opus-5"],
          bw.role_flags("orchestrator"))
    check("...while its EFFORT stays pinned - he chose a model, not a budget",
          bw.role_flags("orchestrator")[2:] == ["--effort", "high"],
          bw.role_flags("orchestrator"))
    with open(bw.orch_model_file(), "w") as fh:
        fh.write("something-that-was-retired\n")
    check("a stale or hand-edited choice falls back, never reaching --model",
          bw.orch_model() == bw.DEFAULT_ORCH_MODEL, bw.orch_model())
    os.unlink(bw.orch_model_file())
    # [his, 2026-07-29] "the other agents should all be opus 5 medium thinking"
    for role in ("worker", "decision"):
        check("a %s is opus 5, medium, whatever he picked for the orchestrator"
              % role,
              bw.role_flags(role) == ["--model", "claude-opus-5",
                                      "--effort", "medium"],
              bw.role_flags(role))

    # ---- what the MINISTERS run on, and the ceiling on it ----
    # [his, 2026-07-29] "do not allow ministers to be anything higher than opus 5
    # medium thinking." Two independent halves: a list that cannot offer more, and
    # a spawn that cannot pass more. The second is what a hand-edited file meets.
    check("with nothing chosen, a minister is the ceiling itself",
          not os.path.exists(bw.minister_file())
          and bw.minister_model() == bw.MINISTER_CEILING
          and bw.MINISTER_CEILING == ("claude-opus-5", "medium"),
          bw.minister_model())
    check("nothing above the ceiling is even offered",
          all(e in ("low", "medium") for _, e, _ in bw.MINISTER_MODELS)
          and not any(f == "claude-fable-5" for f, _, _ in bw.MINISTER_MODELS),
          [(f, e) for f, e, _ in bw.MINISTER_MODELS])
    check("choosing one writes it, and it is what the next spawn reads",
          bw.set_minister_model("sonnet 5 low") == ("claude-sonnet-5", "low")
          and bw.role_flags("worker") == ["--model", "claude-sonnet-5",
                                          "--effort", "low"],
          bw.role_flags("worker"))
    for bad in ("opus 5 high", "claude-opus-5 max", "fable 5", "opus", ""):
        try:
            bw.resolve_minister(bad)
            check("...%r is refused rather than raised or guessed" % bad, False)
        except ValueError:
            check("...%r is refused rather than raised or guessed" % bad, True)
    with open(bw.minister_file(), "w") as fh:
        fh.write("claude-opus-5 max\n")
    check("a hand-edited file ABOVE the ceiling spawns at the ceiling",
          bw.minister_model() == bw.MINISTER_CEILING
          and bw.role_flags("worker") == ["--model", "claude-opus-5",
                                          "--effort", "medium"],
          bw.role_flags("worker"))
    with open(bw.minister_file(), "w") as fh:
        fh.write("a-model-that-was-retired medium\n")
    check("...and a stale one falls back too, never reaching --model",
          bw.minister_model() == bw.MINISTER_CEILING, bw.minister_model())
    os.unlink(bw.minister_file())
    os.environ["BOARD_WORKER_EFFORT"] = "xhigh"
    check("...and the environment can lower a minister, never raise one",
          bw.role_flags("worker") == ["--model", "claude-opus-5",
                                      "--effort", "medium"],
          bw.role_flags("worker"))
    os.environ["BOARD_WORKER_MODEL"] = ""
    os.environ["BOARD_WORKER_EFFORT"] = ""
    check("...and an emptied override cannot inherit settings.json past it",
          bw.role_flags("worker") == ["--model", "claude-opus-5",
                                      "--effort", "medium"],
          bw.role_flags("worker"))
    del os.environ["BOARD_WORKER_MODEL"], os.environ["BOARD_WORKER_EFFORT"]

    # ---- how many SUMMONERS plan at once ----
    # The count is a ceiling on the fan-out, not a quota: `board-watch` splits
    # what he typed across up to that many runs, and `tools/board-watch-test.py`
    # asserts the runs themselves.
    check("with nothing chosen, one summoner plans - what it always did",
          bw.summoners() == 1 and bw.DEFAULT_SUMMONERS == 1, bw.summoners())
    check("choosing one writes the store the watcher reads",
          bw.set_summoners(3) == 3
          and open(bw.summoners_file()).read().strip() == "3"
          and bw.summoners() == 3)
    check("...and what he typed is split across them, contiguous and none empty",
          bw.split_for_summoners(list(range(5))) == [[0, 1], [2, 3], [4]],
          bw.split_for_summoners(list(range(5))))
    check("...while one sentence is one summoner, whatever the number says",
          bw.split_for_summoners(["only this"]) == [["only this"]])
    check("...and 1 is the floor, since 0 summoners plans nothing",
          bw.set_summoners(0) == 1 and bw.summoners() == 1, bw.summoners())

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
    # Back to the HARNESS's scratch dir, never unset: deleting it drops every
    # later test through to the live `~/.local/state/board-watch`, kill switch
    # and all (see the note beside the default at the top of this file).
    os.environ["BOARD_WATCH_STATE"] = WATCH_STATE
    del os.environ["BOARD_WORK_SPAWN"]


def test_summon_confirmed(tmp):
    """A SUMMON IS NOT A CARD until the agent is really up. [his, 2026-07-30]

    Two ends of one bug: a card drawn while Solomon is still summoning, and a
    card left behind by a summon that never produced an agent. So the checks
    are (a) nothing is drawn between the spawn call and the confirmation,
    (b) everything that COUNTS workers sees the row throughout, or a starting
    worker would be double-started and reaped as dead, (c) a spawn that fails
    outright registers nothing and still gets its task reported rather than
    orphaned in `taken/`.
    """
    import boardagents as ba
    import boardphase as bph
    import boardwork as bw

    os.environ["BOARD_WORK_SPAWN"] = "sleep 30"
    os.environ["BOARD_MAX_WORKERS"] = "2"
    scripts = os.path.join(tmp, "transcripts", "proj")
    os.makedirs(scripts, exist_ok=True)
    os.environ["BOARD_TRANSCRIPTS"] = os.path.dirname(scripts)
    # The constant is read at import, so the grace is put back by hand rather
    # than through the environment this file already elapsed globally.
    ba.CONFIRM_GRACE_S = 3600.0

    rec = bw.dispatch("confirmable work", where="apps/zzz/**")
    aid = rec["id"]
    check("a dispatch that started still reports `running` to its caller",
          rec["state"] == "running", rec)
    check("...and the registration is on disk, so nothing about it is lost",
          os.path.isfile(os.path.join(ba.agents_dir(), aid + ".json")))
    check("but NO CARD is drawn while the summon is unconfirmed",
          aid not in [c["id"] for c in bw.cards()],
          [c["id"] for c in bw.cards()])
    check("...nor in the terminal listing, which draws the same rows",
          aid not in [r["id"] for g in bw.groups() for r in g["rows"]])
    check("...while the CAP still counts it, or it would be double-started",
          aid in [w["id"] for w in bw.live_workers()])
    check("...and a note can still be addressed to it",
          any(a["id"] == aid for a in ba.agents()))

    # ITS OWN TRANSCRIPT IS THE PROOF: only a running agent writes one.
    with open(os.path.join(scripts, rec["session"] + ".jsonl"), "w") as f:
        f.write("{}\n")
    check("the card appears once the agent's own transcript exists",
          aid in [c["id"] for c in bw.cards()])
    os.unlink(os.path.join(scripts, rec["session"] + ".jsonl"))
    check("...and confirmation is STICKY, so it cannot un-draw itself",
          aid in [c["id"] for c in bw.cards()])

    # ---- a spawn that never started leaves NO card and NO orphan ----
    start_unit, start_detached = bw._start_unit, bw._start_detached
    bw._start_unit = lambda *a, **k: None
    bw._start_detached = lambda *a, **k: None
    try:
        dead = bw.dispatch("work nothing could start", where="apps/zzz/**")
    finally:
        bw._start_unit, bw._start_detached = start_unit, start_detached
    check("a spawn that could not start says so rather than claiming a worker",
          dead["state"] == "failed", dead)
    check("...and registers nothing, so no card is left behind for it",
          not os.path.isfile(os.path.join(ba.agents_dir(), dead["id"] + ".json"))
          and dead["id"] not in [c["id"] for c in bw.cards()])
    _, failed, _ = bw.reap()
    check("...and its task is REPORTED as failed, not orphaned in taken/",
          "work nothing could start" in [r["task"] for r in failed],
          [r["task"] for r in failed])

    # The stub worker outlives this function otherwise, and the window tests
    # below assert on an EMPTY agents section.
    os.kill(rec["pid"], 9)
    time.sleep(0.2)
    ba.sweep()
    bw.reap()
    del os.environ["BOARD_TRANSCRIPTS"]
    del os.environ["BOARD_WORK_SPAWN"]
    ba.CONFIRM_GRACE_S = -1.0


def test_finished_leaves(tmp):
    """A MINISTER THAT FINISHED LEAVES THE TRIANGLE AT ONCE. [his, 2026-07-30]

    *"are ministers sometimes staying in the triangle unfocused colored until
    the user clears their completion message?"* — they were: the card is only
    deleted from disk by `boardagents.sweep()`, on a board-watch tick, and the
    next thing to trigger a tick after a worker's final `note` was usually his
    reply clearing that bullet. So the DRAWING decides now
    (`boardwork._drawable`), off liveness it already polls.

    The other half is the one that must NOT leave: a worker that stopped
    without reporting keeps its card until the tick puts the FAILED bullet on
    his board, because until then it is the only visible trace of the loss.
    """
    import boardagents as ba
    import boardwork as bw

    os.environ["BOARD_WORK_SPAWN"] = "sleep 30"
    os.environ["BOARD_MAX_WORKERS"] = "3"
    bw.reap()          # clear earlier fixtures' dead tasks out of work/taken

    drawn = lambda: [c["id"] for c in bw.cards()]

    ok = bw.dispatch("finish and go", where="apps/zzz/**")
    bad = bw.dispatch("stop mid-sentence", where="apps/yyy/**")
    check("(setup) both ministers are drawn while they run",
          ok["id"] in drawn() and bad["id"] in drawn(), drawn())

    bw.mark_reported(ok["id"], "recorded its result")
    check("...and reporting alone does not remove a LIVE one",
          ok["id"] in drawn(), drawn())

    os.kill(ok["pid"], 9)
    os.kill(bad["pid"], 9)
    time.sleep(0.4)
    check("the finished minister is gone the moment it exits - no tick needed",
          ok["id"] not in drawn(), drawn())
    check("...while the one that stopped without reporting stays",
          bad["id"] in drawn(), drawn())
    listed = [r["id"] for g in bw.groups() for r in g["rows"]]
    check("...and the terminal listing agrees, applying the same filter",
          ok["id"] not in listed and bad["id"] in listed, listed)
    check("...but EVERYTHING THAT COUNTS still sees the finished record",
          any(a["id"] == ok["id"] for a in ba.agents()))

    done, failed, _ = bw.reap()
    check("(setup) the reap files them apart on the same fact",
          [r["task"] for r in done] == ["finish and go"]
          and [r["task"] for r in failed] == ["stop mid-sentence"],
          ([r["task"] for r in done], [r["task"] for r in failed]))
    check("the finished one STAYS gone once the reap has moved the stamp",
          ok["id"] not in drawn(), drawn())
    ba.sweep()
    check("...and the failed one leaves when the sweep drops it",
          bad["id"] not in drawn(), drawn())


def test_overlap(tmp):
    """`dispatch` WARNS on a --where that overlaps a live worker's — the
    mechanical half of the prompt's `run agents first` rule. Warn only: a
    near-miss must not block real work, so the dispatch itself is untouched."""
    import subprocess
    import boardagents as ba
    import boardwork as bw

    os.environ["BOARD_WORK_SPAWN"] = "sleep 30"
    os.environ["BOARD_MAX_WORKERS"] = "2"

    first = bw.dispatch("hold the board files", where="apps/board/**")
    check("(setup) a worker is live in apps/board/**",
          first["state"] == "running", first)

    hits = bw.overlaps("apps/board/qml/Main.qml")
    check("a --where inside a live worker's glob is flagged",
          [a["id"] for a in hits] == [first["id"]],
          [(a["id"], a.get("where")) for a in hits])
    check("...and the wider glob is flagged from the other side too",
          [a["id"] for a in bw.overlaps("apps/**")] == [first["id"]])
    check("a --where in different files is not",
          bw.overlaps("home/prog/quickshell-files/**") == [])
    check("...case-sensitively, since paths here are",
          bw.overlaps("APPS/board/**") == [])
    check("an empty or all-glob --where flags nobody rather than everybody",
          bw.overlaps("") == [] and bw.overlaps("*") == [])
    check("a multi-token --where overlaps on any of its tokens",
          [a["id"] for a in bw.overlaps("tools/x.sh apps/board/boardwork.py")]
          == [first["id"]])

    second = bw.dispatch("also in the board files", where="apps/board/tools/**")
    check("the overlap rides on the dispatch record, naming the live worker",
          [w["id"] for w in second.get("overlaps") or []] == [first["id"]],
          second.get("overlaps"))
    check("...and WARN ONLY: the dispatch still happened, exactly as asked",
          second["state"] == "running", second["state"])

    cli = os.path.join(BOARD, "tools", "boardctl.py")
    p = subprocess.run([sys.executable, cli, "dispatch", "a third task in the",
                        "same files", "--where", "apps/board/boardagents.py"],
                       capture_output=True, text=True)
    check("boardctl dispatch prints the warning, naming the worker",
          p.returncode == 0 and "warning:" in p.stdout
          and (first.get("name") or first["id"]) in p.stdout, p.stdout[-200:])
    check("...suggesting the handoff, not refusing the dispatch",
          "inbox send --to" in p.stdout
          and ("queued" in p.stdout or "started as" in p.stdout),
          p.stdout[-200:])
    q = subprocess.run([sys.executable, cli, "dispatch", "unrelated work",
                        "--where", "sys/net/**"],
                       capture_output=True, text=True)
    check("...and a disjoint --where draws no warning at all",
          q.returncode == 0 and "warning:" not in q.stdout, q.stdout[-200:])

    check("the orchestrator is told the tool itself warns on overlap...",
          "`dispatch` itself warns when the" in bw.ORCHESTRATOR_PROMPT
          and "never a refusal" in bw.ORCHESTRATOR_PROMPT)
    check("...while `run agents first` is still the instruction",
          "Run `agents` before you dispatch" in bw.ORCHESTRATOR_PROMPT)
    check("rule 1 sends the rebuild through the host wrapper, which takes the "
          "shared lock itself...",
          "use the host's own" in bw.RULES and "rebuild-air" in bw.RULES
          and "runs preflight itself" in bw.RULES)
    check("...and keeps the manual flock for a RAW switch, same lock path",
          "/tmp/claude-1000/-home-lam-nix/rebuild.lock" in bw.RULES
          and "RAW switch" in bw.RULES)

    for a in bw.live_workers():
        os.kill(a["pid"], 9)
    time.sleep(0.4)
    ba.sweep()          # drop the dead registrations, as the real tick would
    del os.environ["BOARD_WORK_SPAWN"]


def test_dead_worker_notes(tmp):
    """A dead worker's TAKEN inbox notes go back to the queue.

    `sweep()` already rescued a note nobody READ; a note a worker `inbox
    take`-d used to die with the worker — 2026-07-29, a handed-over item taken
    at 11:27 by a worker that then died on an API 500, and nothing flagged it.
    Now `reap()` sends a failed or transiently-requeued worker's taken notes
    back through `boardagents.requeue_taken`, and the conservation property
    holds across it: one file, one directory, at every instant."""
    import boardagents as ba
    import boardwork as bw

    os.environ["BOARD_WORK_SPAWN"] = "sleep 30"
    os.environ["BOARD_MAX_WORKERS"] = "3"
    bw.reap()          # clear earlier fixtures' dead tasks out of work/taken

    def places(text):
        out = []
        for sub in ("queue", "taken", "dropped", "editing"):
            for m in ba._list(ba.inbox_dir(sub)):
                if m["text"] == text:
                    out.append((sub, m.get("state")))
        root = ba.inbox_dir("to")
        for name in sorted(os.listdir(root)):
            d = os.path.join(root, name)
            if os.path.isdir(d):
                out += [("to/" + name, m.get("state"))
                        for m in ba._list(d) if m["text"] == text]
        return out

    # ---- a FAILED worker: its taken note goes back to the queue ----
    rec = bw.dispatch("die holding a note", where="apps/board/**")
    aid = rec["id"]
    msg = ba.send("the handed-over item, in full", to=aid)
    check("(setup) the handoff is delivered to the live worker",
          msg["state"] == "delivered", msg)
    took = ba.take(aid)
    check("(setup) the worker took it", len(took) == 1
          and places(msg["text"]) == [("taken", "taken")], places(msg["text"]))
    os.kill(rec["pid"], 9)
    time.sleep(0.4)
    done, failed, requeued = bw.reap()
    mine = [t for t in failed if t["task"] == "die holding a note"]
    check("the stampless worker is reaped as FAILED, tuple shape unchanged",
          len(mine) == 1, [t["task"] for t in failed])
    check("...its taken note is back in the queue, saying who dropped it",
          places(msg["text"]) == [("queue", "requeued-from-dead-worker")],
          places(msg["text"]))
    check("...riding on the reaped record for the tick to count",
          mine and [m["text"] for m in mine[0].get("notesBack") or []]
          == [msg["text"]], mine and mine[0].get("notesBack"))
    check("...exactly once - nothing lost, nothing doubled",
          len(places(msg["text"])) == 1, places(msg["text"]))

    # ---- a worker requeued on a TRANSIENT death: same rescue ----
    rec2 = bw.dispatch("die transiently holding a note", where="apps/x/**")
    msg2 = ba.send("the second handed-over item", to=rec2["id"])
    ba.take(rec2["id"])
    with open(bw._log_path(rec2["id"]), "w") as f:
        f.write("API Error: 500\n")
    os.kill(rec2["pid"], 9)
    time.sleep(0.4)
    done, failed, requeued = bw.reap()
    check("the transiently-dead worker's task is requeued, not failed",
          [t["task"] for t in requeued] == ["die transiently holding a note"],
          ([t["task"] for t in requeued], [t["task"] for t in failed]))
    check("...and its taken note went back to the queue with it",
          places(msg2["text"]) == [("queue", "requeued-from-dead-worker")],
          places(msg2["text"]))

    # ---- a DONE worker keeps its taken notes: it reported ----
    rec3 = bw.dispatch("finish after taking a note", where="apps/y/**")
    msg3 = ba.send("a note the worker handled", to=rec3["id"])
    ba.take(rec3["id"])
    bw.mark_reported(rec3["id"], what="did the thing")
    os.kill(rec3["pid"], 9)
    time.sleep(0.4)
    done, failed, requeued = bw.reap()
    check("a worker that REPORTED is reaped as done",
          [t["task"] for t in done] == ["finish after taking a note"],
          [t["task"] for t in done])
    check("...and its taken note stays taken: it is presumed handled",
          places(msg3["text"]) == [("taken", "taken")], places(msg3["text"]))

    ba.sweep()          # drop the dead registrations, as the real tick would
    del os.environ["BOARD_WORK_SPAWN"]
    os.environ["BOARD_MAX_WORKERS"] = "2"


# ----------------------------------------------------------------- 2. the store
def real_store():
    """This host's live board, or None. READ ONLY, and never `ensure_board()`:
    the harness must not bring a store into existence, and the pre-split
    `board.md` is still the right file until the migration lands."""
    import boardparse as B
    for p in (B.BOARD_PATH, B.LEGACY_BOARD_PATH):
        if os.path.isfile(p):
            return p
    return None


def test_real_store():
    import boardparse as B

    path = real_store()
    if path is None:
        check("the store exists", False, B.BOARD_PATH)
        return
    src = B.read(path)
    doc = B.parse(src)
    check("the real store round-trips unchanged", "".join(doc["lines"]) == src)
    # NEEDS YOU is deliberately NOT required to be non-empty: with the moves in
    # `boardmove.py` an answered decision leaves it, so an empty section is the
    # resting state (and the one he sees most often), not a parse regression.
    # TODO is the same and for the same reason — a chore leaves it when it is
    # done, and a board he has caught up with is not a parser bug. LANDED is
    # the one that must have content: it is DERIVED from `git log`
    # (`boardmove.landed_view()`), so an empty one means the derivation broke.
    check("...and the sections that have content parsed",
          bool(doc["landed"]),
          (len(doc["needs"]), len(doc["todo"]), len(doc["landed"])))
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
    from PySide6.QtCore import QUrl, QObject, Signal, Slot
    from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
    import PySide6.QtQuick  # noqa: F401  (registers the QQuickItem converter)
    from deskstyle import DeskStyle
    import main as brd

    class StubTitlebar(QObject):
        # The real `Titlebar.clicked` (main.py), so a test can press a cell the
        # way the plugin does. Without it the window's `Connections` has no
        # signal to attach to and every titlebar action is untested.
        clicked = Signal(str)
        clicks = []
        # Every message the window would put on the vtb socket, in order. The
        # ORDER is the point: the first REGISTER is what he sees for the first
        # frames, and it used to light the wrong cell (see `test_window`).
        sent = []

        @Slot("QVariantList")
        def setButtons(self, b):
            StubTitlebar.sent.append(
                ("buttons", tuple("-" if isinstance(x, str)
                                  else (str(x["label"]), int(x.get("state", 0)))
                                  for x in b)))

        @Slot(str)
        def setFooter(self, t):
            StubTitlebar.sent.append(("footer", str(t)))

        @Slot(bool)
        def setTitleText(self, on):
            StubTitlebar.sent.append(("titleText", bool(on)))

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    keep = (brd.Palette(brd.PANEL_THEME), DeskStyle(parent=engine), StubTitlebar(),
            brd.Board(path), brd.Settings(), brd.Agents(), brd.Usage())
    ctx.setContextProperty("WalPalette", keep[0])
    ctx.setContextProperty("DeskStyle", keep[1])
    ctx.setContextProperty("Titlebar", keep[2])
    ctx.setContextProperty("Board", keep[3])
    ctx.setContextProperty("Settings", keep[4])
    ctx.setContextProperty("Agents", keep[5])
    # Every context property main.py installs is installed here too, or the
    # window loads with a ReferenceError the harness cannot see and the section
    # is simply missing on his screen.
    ctx.setContextProperty("Usage", keep[6])
    # ...and every WIRE between them, for the same reason: the usage bars follow
    # the agent list's lifecycle transitions, and a harness that skipped this
    # would report an app that does not.
    keep[6].follow(keep[5])
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
    path = real_store()
    if path is None:
        return
    engine, win, keep = build(app, path)
    spin(500)
    # Not "there is a decision": there may legitimately be none (`boardmove.py`
    # takes answered ones out). What must hold is that his real document draws.
    check("the real store draws",
          len(prop(win, "landed")) > 0,
          (len(prop(win, "needs")), len(prop(win, "landed"))))
    shot(win, "00-real-store")
    # ...and with the two live sections folded away, which is how LANDED gets
    # onto one screen — the collapse is persisted state, so this is a real
    # state, not a harness trick.
    win.setProperty("collapsed", {"needs": True, "landed": True})
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
    check("the sections parsed into the view",
          len(prop(win, "needs")) == 2 and len(prop(win, "landed")) == 1,
          (len(prop(win, "needs")), len(prop(win, "landed"))))
    check("the to-do list is drawn with the things that need him",
          len(prop(win, "todo")) == 1, prop(win, "todo"))

    # ---- the line under the section rule does not depend on the contents ----
    # [his, 2026-07-30] it read one way with decisions on the board and another
    # way without, and the EMPTY wording is the one that stays. So a POPULATED
    # section draws that same sentence and not the store's own framing
    # paragraph; the empty side of the pair is checked further down.
    def _drawn(w):
        return [t.property("text").strip() for t in descendants(w.contentItem())
                if isinstance(t.property("text"), str)
                and t.property("text").strip() and t.isVisible()]

    full = _drawn(win)
    check("a populated NEEDS YOU draws the same one sentence as an empty one",
          "decisions brought to you from Solomon." in full, full[:12])
    check("...and not the store's framing paragraph, which varied with it",
          not any(s.startswith("Decisions only you can make") for s in full),
          [s for s in full if s.startswith("Decisions")])

    # ---- what the titlebar is told FIRST, before he has touched anything ----
    # The very first REGISTER used to light `if` — the LAST section — because
    # before the Column has laid out, every section is at y 0 and
    # `contentY (0) >= secFlight.y - 4` is true. It was corrected a frame later,
    # so what he saw was the lit cell flashing on the wrong cell at startup, and
    # every REGISTER makes the plugin re-warm its glyphs and repaint the bar.
    sent = type(keep[2]).sent
    regs = [m for m in sent if m[0] == "buttons"]
    lit = [[lab for lab in r[1] if lab != "-" and lab[1] == 1] for r in regs]
    check("the first thing the titlebar is told is the section he is ON",
          regs and lit[0] == [("ny", 1)], (lit[:2], prop(win, "section")))
    check("...and it is never told he is in a section further down the page",
          all(l == [("ny", 1)] for l in lit), lit)
    # The footer carries the STATUS and nothing else — [his, 2026-07-29]
    # *"remove the 'goetia' text at the bottom of the inner titlebar"*. The
    # program's name is already the title the plugin draws up the side.
    foots = [m[1] for m in sent if m[0] == "footer"]
    check("...and the footer never says the program's own name",
          not any("goetia" in f for f in foots), foots)
    # ...and it does NOT suppress the stacked title. [his, 2026-07-29] *"really
    # for now there should be no title text in the left side inner bar of
    # goetia"* was answered with `TITLETEXT 0`, which is the wrong lever: the
    # stacked title is drawn in the OUTER column and the inner bar he meant only
    # ever holds the buttons and the footer, so the flag erased the title from
    # the RIGHT OUTER bar instead. Dropped 2026-07-30.
    check("the window does NOT suppress the stacked title it never drew",
          ("titleText", False) not in sent, sent[:6])
    check("...while keeping the window title, which is the only name it has",
          win.title() == "goetia", win.title())

    # ---- each usage meter carries its OWN reset tooltip ----
    # [his, 2026-07-29] *"add a tooltip to each usage indicator that says when
    # that limit next resets"*. Both rows always exist (`readings()` returns the
    # pair on every host, known or not), so both chips must, and each must carry
    # ITS row's sentence rather than the other's — swapping them is the failure
    # this catches. The chip starts closed: it is a dwell, never a thing that is
    # already on screen (§8).
    meters = [it for it in descendants(win.contentItem())
              if "UsageMeter" in it.metaObject().className()]
    tips = [(m, [c for c in descendants(m)
                 if "ToolTipArea" in c.metaObject().className()]) for m in meters]
    check("both usage meters have a tooltip, and it is the whole row's",
          len(meters) == 2 and all(len(t) == 1
                                   and round(t[0].width()) == round(m.width())
                                   for m, t in tips),
          [(round(m.width()), len(t)) for m, t in tips])
    # ONE line, and it is the countdown: [his, 2026-07-30] *"the tooltip should
    # just say `resets in ____`"*. It carried `detail` above that line until
    # then; nothing else may creep back in, which is what the equality (rather
    # than a containment) is here to hold.
    check("...saying how long until THAT window resets, and nothing else",
          all(t[0].property("text") == (m.property("row") or {}).get("reset")
              and t[0].property("text").startswith("resets in")
              for m, t in tips),
          [(t[0].property("text") if t else None) for m, t in tips])
    chips = [it for it in descendants(win.contentItem()) if it.property("z") == 5000]
    # SIX now: two meters and the four dropdowns, which carry their `hint` here
    # rather than in the footer for the same reason.
    check("...and no chip is on screen until he dwells on one (8)",
          len(chips) == 6 and all(c.width() == 0 and not c.isVisible() for c in chips),
          [(c.width(), c.isVisible()) for c in chips])

    # ---- ...and it slides out to the LEFT, out of a fixed right edge ----
    # docs/DESIGN.md §8, and [his, 2026-07-29] *"it slides out to the right, it
    # was supposed to slide out to the left"* — the first cut grew rightward,
    # inherited from painter's copy, which diverges from §8 (§19.2). This
    # asserts the GEOMETRY over the reveal rather than the pixels: the right
    # edge never moves, it sits off the row's left side, and `x` walks left as
    # the clip widens. The retraction has to SNAP (§8) — one sample after the
    # pointer leaves, the chip is already shut.
    from PySide6.QtCore import QPoint                                  # noqa: E402
    from PySide6.QtTest import QTest                                   # noqa: E402
    meter, chip = meters[0], chips[0]
    at = meter.mapToItem(win.contentItem(),
                         QPoint(int(meter.width() / 2), int(meter.height() / 2)))
    QTest.mouseMove(win, QPoint(int(at.x()), int(at.y())))
    spin(60)
    check("...the pointer on a meter is what opens its chip, after a dwell (8)",
          tips[0][1][0].property("containsMouse") and not tips[0][1][0].property("open"),
          (tips[0][1][0].property("containsMouse"), tips[0][1][0].property("open")))
    frames = []
    for _ in range(26):
        spin(20)
        frames.append((round(chip.x(), 1), round(chip.width(), 1)))
    moving = [f for f in frames if 0 < f[1] < chip.property("fullW")]
    edges = {round(x + w, 1) for x, w in frames if w > 0}
    left = meter.mapToItem(win.contentItem(), QPoint(0, 0)).x()
    check("the reset chip opens at all when he dwells on the meter",
          chip.width() > 0 and len(moving) >= 3, (frames[-1], len(moving)))
    check("...and grows out of ONE fixed right edge, off the row's left side (8)",
          len(edges) == 1 and edges.pop() <= left, (sorted(edges), left))
    check("...so its left edge walks LEFTWARD as it opens, never rightward",
          all(b[0] <= a[0] for a, b in zip(moving, moving[1:]))
          and moving[-1][0] < moving[0][0], moving)
    QTest.mouseMove(win, QPoint(2, 2))
    spin(20)
    check("...and the retraction snaps back the way it came, in one frame (8)",
          chip.width() == 0 and not chip.isVisible(),
          (chip.x(), chip.width(), chip.isVisible()))

    # ---- ...and CLICKING one refreshes it, out loud ----
    # [his, 2026-07-30] a click on a usage meter must fetch that reading now.
    # The row is the target (a 7px bar is not one), and §10 is the other half:
    # the harness runs with `BOARD_USAGE_OFFLINE=1`, so this click can achieve
    # nothing at all — and the whole point is that it SAYS so in the footer
    # instead of looking like it worked. A silent one would be the inert control
    # with a pointing cursor over it.
    from PySide6.QtCore import Qt                                       # noqa: E402
    usage_obj = keep[6]
    said = []
    usage_obj.refreshed.connect(lambda why: said.append(why))
    sent[:] = []
    hit = meter.mapToItem(win.contentItem(),
                          QPoint(int(meter.width() / 2), int(meter.height() / 2)))
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier,
                     QPoint(int(hit.x()), int(hit.y())))
    for _ in range(20):
        spin(20)
        if said:
            break
    feet = [t for k, t in sent if k == "footer" and t]
    check("clicking a usage meter runs a fetch, there and then",
          said == ["off"], said)
    check("...and reports it in the footer, both while it runs and how it ended",
          any("refreshing" in t for t in feet)
          and any("usage" in t and "showing the last reading" in t for t in feet),
          feet)
    # The in-flight state has to reach the ROW, not only the footer — a fetch is
    # a round trip and the row he clicked is where he is looking. Driven rather
    # than raced: the offline fetch settles in microseconds, so the wire is what
    # is asserted, one notify to both meters.
    usage_obj._busy = True
    usage_obj.busyChanged.emit()
    spin(20)
    lit = [m.property("busy") for m in meters]
    usage_obj._busy = False
    usage_obj.busyChanged.emit()
    spin(20)
    check("...and every meter draws the in-flight state, from `Usage.busy`",
          lit == [True, True]
          and [m.property("busy") for m in meters] == [False, False],
          (lit, [m.property("busy") for m in meters]))

    # ---- the model chooser sits to the RIGHT of the box he types in ----
    # His words placed it: "a drop down to the right of the top prompt box".
    # Found by its label rather than an id, because that label is the one thing
    # about it he can see, and a control that draws the wrong model is the whole
    # failure mode worth catching.
    from PySide6.QtCore import QPointF                                  # noqa: E402
    import boardwork as bwm                                             # noqa: E402
    agents_obj = keep[5]
    # Two dropdowns in that column now — which model, and how many agents — so
    # they are told apart by the label, which is the only thing about either of
    # them he can see. A control drawing the wrong model, or the wrong cap, is
    # the whole failure mode worth catching.
    drops = [it for it in descendants(win.contentItem())
             if (it.property("text") or "").endswith("  v")]
    picks = [it for it in drops
             if it.property("text").startswith(agents_obj.modelLabel)]
    caps = [it for it in drops
            if it.property("text").startswith(agents_obj.capLabel)]
    # ...and the TOP of that column, which is the summoner count since his four
    # dropdowns landed. Anything measuring the column's span reads this one and
    # not the model chooser, which is now the second rung.
    sums = [it for it in drops
            if it.property("text").startswith(agents_obj.summonerLabel)]
    check("there is exactly one model chooser, and it says which model",
          len(picks) == 1, [p.property("text") for p in drops])
    if picks:
        # The TOP box specifically — every agent card and decision carries an
        # InputBox too, and they are wider, so a max() over all of them compares
        # the chooser against a box on the other side of the window.
        boxes = sorted((it.mapToItem(win.contentItem(), QPointF(0, 0)).y(), it)
                       for it in descendants(win.contentItem())
                       if it.property("hintText") is not None)
        pt = picks[0].mapToItem(win.contentItem(), QPointF(0, 0))
        top = boxes[0][1] if boxes else None
        bx = top.mapToItem(win.contentItem(), QPointF(0, 0)).x() + top.width() \
            if top else 0
        # BESIDE the box, not over or under it — and vertically it is inside the
        # box's own span rather than level with its first line: the chooser is
        # the SECOND rung of the column since his four dropdowns landed, and the
        # top-flush assertion belongs to the summoner count (below).
        check("...to the RIGHT of the box, not over it or under it",
              top is not None and pt.x() >= bx - 1
              and boxes[0][0] - 1 <= pt.y() <= boxes[0][0] + top.height(),
              (pt.x(), pt.y(), bx, boxes[0][0], top.height() if top else 0))
    # It offers every model and marks the live one — the tick comes from
    # boardwork, so the control cannot disagree with what will actually spawn.
    listed = agents_obj.models
    check("...and offers every model, with exactly one marked current",
          len(listed) == len(bwm.ORCH_MODELS)
          and sum(1 for m in listed if m["current"]) == 1,
          [(m["label"], m["current"]) for m in listed])
    check("...whose label is prose, never the raw wire name",
          "claude-" not in agents_obj.modelLabel, agents_obj.modelLabel)

    # ---- ...and BETWEEN it and the meters, how many may run at once ----
    # [his, 2026-07-29] *"between the model selector and the indicators, add
    # another drop down for the max number of agents available."* Same idiom
    # (one component, `PickBox.qml`), his order, and ONE store: the file
    # `boardctl.py cap` writes. A second copy of the number is the failure.
    check("there is a second dropdown, and it says how many agents",
          len(caps) == 1 and str(bwm.cap()) in caps[0].property("text"),
          [d.property("text") for d in drops])
    check("...offering a range, with exactly one marked current",
          [c["n"] for c in agents_obj.caps][:len(bwm.CAP_CHOICES)]
          == list(bwm.CAP_CHOICES)
          and sum(1 for c in agents_obj.caps if c["current"]) == 1,
          [(c["label"], c["current"]) for c in agents_obj.caps])
    if caps and picks:
        cp = caps[0].parentItem().mapToItem(win.contentItem(), QPointF(0, 0))
        mp = picks[0].parentItem().mapToItem(win.contentItem(), QPointF(0, 0))
        check("...UNDER the model chooser (the meters come after it, below)",
              cp.y() > mp.y(), (mp.y(), cp.y()))
        check("...and flush with the chooser, one edge for the whole column",
              abs(cp.x() - mp.x()) < 1
              and abs(caps[0].parentItem().width()
                      - picks[0].parentItem().width()) < 1,
              (cp.x(), mp.x(), caps[0].parentItem().width(),
               picks[0].parentItem().width()))
    # Picking one writes THAT store — the file, checked as bytes. The env
    # override goes away for the duration, or `cap()` reports `2` back at us
    # whatever was written and the check would pass on a control that wrote
    # nowhere.
    env_cap = os.environ.pop("BOARD_MAX_WORKERS", None)
    was = open(bwm.cap_file()).read() if os.path.exists(bwm.cap_file()) else ""
    try:
        check("picking a cap writes the one store boardctl writes",
              agents_obj.chooseCap(7)
              and open(bwm.cap_file()).read().strip() == "7"
              and agents_obj.capLabel == "7 ministers",
              (bwm.cap_file(), agents_obj.capLabel))
        agents_obj.chooseCap(9)
        check("...and a cap of his that is off the range is drawn, and ticked",
              any(c["n"] == 9 and c["current"] for c in agents_obj.caps)
              and len(agents_obj.caps) == len(bwm.CAP_CHOICES) + 1,
              [(c["n"], c["current"]) for c in agents_obj.caps])
        check("...and 1 is the floor, since 0 agents is not a cap",
              agents_obj.chooseCap(0) and bwm.cap() == 1, bwm.cap())
        check("...and one minister is singular, because he reads it",
              agents_obj.capLabel == "1 minister", agents_obj.capLabel)
    finally:
        with open(bwm.cap_file(), "w") as f:
            f.write(was or "%d\n" % bwm.DEFAULT_CAP)
        if env_cap is not None:
            os.environ["BOARD_MAX_WORKERS"] = env_cap
        agents_obj.capChanged.emit()

    # ---- FOUR dropdowns, and the ORDER IS HIS ----
    # [his, 2026-07-29] *"1. number of summoners 2. summoner model 3. number of
    # ministers 4. minister model"*. Found by their labels, top to bottom, because
    # the label is the only thing about any of them he can see and a column in the
    # wrong order is the whole failure worth catching here.
    order = sorted((round(it.parentItem()
                          .mapToItem(win.contentItem(), QPointF(0, 0)).y(), 1),
                    it.property("text").split("  v")[0].strip())
                   for it in drops)
    want = [agents_obj.summonerLabel, agents_obj.modelLabel,
            agents_obj.capLabel, agents_obj.ministerLabel]
    check("all four dropdowns are drawn, in his order, top to bottom",
          [lab for _, lab in order] == want, (order, want))
    check("...and every one of them is padded to one arrow column",
          len({len(it.property("text")) for it in drops}) == 1,
          [it.property("text") for it in drops])
    # The minister chooser: what it offers is the ceiling and below, and picking
    # one writes the store `role_flags` reads at the spawn.
    listed = agents_obj.ministers
    check("the minister chooser offers the capped list, one marked current",
          [m["label"] for m in listed]
          == [lab for _, _, lab in bwm.MINISTER_MODELS]
          and sum(1 for m in listed if m["current"]) == 1,
          [(m["label"], m["current"]) for m in listed])
    check("...and stops at opus 5 medium - nothing higher is drawn at all",
          not any(e not in ("low", "medium") for _, e, _ in bwm.MINISTER_MODELS)
          and agents_obj.ministerLabel == "opus 5 medium",
          agents_obj.ministerLabel)
    was_min = open(bwm.minister_file()).read() \
        if os.path.exists(bwm.minister_file()) else ""
    try:
        check("picking one writes the store the spawn reads",
              agents_obj.chooseMinister("claude-sonnet-5 low")
              and bwm.minister_model() == ("claude-sonnet-5", "low")
              and agents_obj.ministerLabel == "sonnet 5 low",
              agents_obj.ministerLabel)
        check("...and one above the ceiling is refused rather than written",
              not agents_obj.chooseMinister("claude-opus-5 max")
              and bwm.minister_model() == ("claude-sonnet-5", "low"),
              bwm.minister_model())
    finally:
        if was_min:
            with open(bwm.minister_file(), "w") as f:
                f.write(was_min)
        elif os.path.exists(bwm.minister_file()):
            os.unlink(bwm.minister_file())
        agents_obj.ministerChanged.emit()
    # ...and the summoner count, the one control that had no store before.
    env_sum = os.environ.pop("BOARD_MAX_SUMMONERS", None)
    was_sum = open(bwm.summoners_file()).read() \
        if os.path.exists(bwm.summoners_file()) else ""
    try:
        check("picking a summoner count writes the store the watcher reads",
              agents_obj.chooseSummoners(2)
              and open(bwm.summoners_file()).read().strip() == "2"
              and agents_obj.summonerLabel == "2 summoners",
              agents_obj.summonerLabel)
        agents_obj.chooseSummoners(1)
        check("...and one summoner is singular, because he reads it",
              agents_obj.summonerLabel == "1 summoner", agents_obj.summonerLabel)
    finally:
        if was_sum:
            with open(bwm.summoners_file(), "w") as f:
                f.write(was_sum)
        elif os.path.exists(bwm.summoners_file()):
            os.unlink(bwm.summoners_file())
        if env_sum is not None:
            os.environ["BOARD_MAX_SUMMONERS"] = env_sum
        agents_obj.summonersChanged.emit()

    # ---- ...and the two usage bars sit UNDER it ----
    # His words placed these too: "directly under the orchestrator
    # model-selection box". Found by their labels, which are the whole of what
    # he reads: a bar with no window name beside it is not a readout.
    import boardusage as bum                                            # noqa: E402
    labels = [w[2] for w in bum.WINDOWS]
    bars = [it for it in descendants(win.contentItem())
            if it.property("hovering") is not None]
    check("there are exactly two usage meters, one per window",
          len(bars) == len(labels), len(bars))
    if bars and picks:
        # Top to bottom now, not left to right: they are STACKED, so every
        # meter has the same x and only y orders them. 5h is the top line.
        texts = sorted((it.mapToItem(win.contentItem(), QPointF(0, 0)).y(),
                        (it.property("row") or {}).get("label", ""))
                       for it in bars)
        check("...labelled by the window each one measures, in order",
              [t[1] for t in texts] == labels, [t[1] for t in texts])
        pt = picks[0].mapToItem(win.contentItem(), QPointF(0, 0))
        by = min(it.mapToItem(win.contentItem(), QPointF(0, 0)).y() for it in bars)
        check("...UNDER the model chooser, not beside it", by > pt.y(),
              (pt.y(), by))
        # ...and under the CAP dropdown too, which is between the two of them:
        # his order for that column is model -> how many -> what they cost.
        check("...and under the cap dropdown, which sits between the two",
              caps and by > caps[0].mapToItem(win.contentItem(),
                                              QPointF(0, 0)).y(),
              (by, [c.mapToItem(win.contentItem(), QPointF(0, 0)).y()
                    for c in caps]))
        # ...and flush with it: his words were "exactly as wide as the model
        # selection box above it", which is both edges, so both are checked.
        # A width bound to the chooser cannot drift when a longer model name
        # widens it; a hardcoded one silently could.
        # Against the BOX, not against its label: the chooser's text is centred
        # inside it, so comparing edges with `picks[0]` measures the inset.
        box = picks[0].parentItem()
        bp = box.mapToItem(win.contentItem(), QPointF(0, 0))
        xs = set(round(it.mapToItem(win.contentItem(), QPointF(0, 0)).x())
                 for it in bars)
        ws = set(round(it.width()) for it in bars)
        check("...exactly as WIDE as the chooser, flush at both edges",
              len(xs) == 1 and len(ws) == 1
              and abs(xs.pop() - bp.x()) < 1
              and abs(ws.pop() - box.width()) < 1,
              (bp.x(), box.width(),
               [(round(it.mapToItem(win.contentItem(), QPointF(0, 0)).x()),
                 round(it.width())) for it in bars]))
        # Stacked means stacked: one directly on top of the other, with no
        # third element wedged between them and no side-by-side fallback.
        ys = sorted(t[0] for t in texts)
        check("...one directly above the other, not beside it",
              len(ys) == 2 and 0 < ys[1] - ys[0] <= bars[0].height() + 4,
              (ys, bars[0].height()))

        # ---- and the BOX is as tall as that whole column ----
        # [his, 2026-07-29] *"the prompt box should extend so that it is not a
        # single line but rather multiple lines so that it is the same height as
        # from the top of the model selector box to the bottom of the
        # indicators"*. Measured against the real items, because the point of
        # the change is that the height is DERIVED: a hardcoded one would pass
        # today and drift the moment a longer model label or a bigger font size
        # moved the column.
        box = (sums or picks)[0].parentItem()
        bp = box.mapToItem(win.contentItem(), QPointF(0, 0))
        # Bottom of the WHOLE usage column, not just the % meters: the box is
        # derived to fill it end to end, and since 2026-07-31 the column also
        # carries the hermes minister readout below the meters (plain Items with
        # no `hovering`, so `bars` alone would stop at the second meter).
        col = bars[0].parentItem()
        cb = col.mapToItem(win.contentItem(), QPointF(0, 0))
        colBottom = cb.y() + col.height()
        ap = top.mapToItem(win.contentItem(), QPointF(0, 0))
        check("the box he types in is as tall as chooser + meters, top flush",
              abs(ap.y() - bp.y()) < 1
              and abs(top.height() - (colBottom - bp.y())) < 1,
              (ap.y(), bp.y(), top.height(), colBottom - bp.y()))
        check("...and it is a RESTING height, not the content's own",
              top.property("minHeight") > top.property("contentHeight"),
              (top.property("minHeight"), top.property("contentHeight")))
        # It is a FLOOR: typing past it still extends the box downward, which is
        # the half of his sentence a `height:` binding would have broken.
        resting = top.height()
        top.setProperty("editing", True)
        spin(80)
        eds = [it for it in descendants(top)
               if it.property("cursorPosition") is not None]
        check("...whose editor opens at exactly that height, not one line",
              len(eds) == 1 and abs(top.height() - resting) < 1,
              (len(eds), top.height(), resting))
        if eds:
            # Enough to overrun a column of FOUR dropdowns plus the meters:
            # 80 of these cleared the old two-rung floor and not this one.
            eds[0].setProperty("text", "wrap me " * 240)
            spin(120)
            check("...and typing more lines than it fits GROWS it past that",
                  top.height() > resting + 20, (top.height(), resting))
            eds[0].setProperty("text", "")
            spin(120)
            check("...back to the resting height when the lines go away",
                  abs(top.height() - resting) < 1, (top.height(), resting))
        top.setProperty("editing", False)
        spin(80)
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
    before_needs = len(prop(win, "needs"))

    B.write(path, "".join(B.set_answer(B.parse(B.read(path))["lines"],
                                       B.parse(B.read(path))["needs"][1], "go on")))
    spin(400)
    rec = bm.start("2", where="apps/thing", path=path)
    spin(500)
    check("an item taken off NEEDS YOU leaves the screen, no relaunch",
          len(prop(win, "needs")) == before_needs - 1,
          (before_needs, len(prop(win, "needs"))))
    check("...and his answer went to the stash, where the hand-back reads it",
          "go on" in (rec.get("notes") or ""), rec.get("notes"))
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
    check("landing redraws LANDED without a relaunch",
          len(prop(win, "landed")) == before_landed + 1,
          len(prop(win, "landed")))
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
    check("...and LANDED is still there",
          len(prop(win, "landed")) > 0, len(prop(win, "landed")))

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

    # ---- the triangle header says how many it BINDS, in words ----
    # [his, 2026-07-31] *"the triangle binds three ministers"*. The band's
    # count (`Agents.boundMinisters`) must equal the RUNNING, non-orchestrator
    # cards actually drawn (`win.agentCards` is `Agents.workers`, the set the
    # triangle renders — sessions the user started are already filtered out by
    # `cards()`, so a live anonymous session here can never be one of them).
    # Drawn-live is running; drawn-dead is not.
    _n = prop(agents, "boundMinisters")
    _running = [a for a in prop(win, "agentCards")
                if a.get("state") == "running"]
    check("the header count is exactly the running ministers drawn",
          _n == len(_running) and _n >= 1, (_n, [a["id"] for a in _running]))
    _words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
    _want = ("the triangle binds " + _words.get(_n, str(_n))
             + (" minister" if _n == 1 else " ministers"))
    _band = [str(it.property("label") or "") for it in descendants(win.contentItem())
             if it.property("interactive") is not None
             and str(it.property("label") or "").startswith("the triangle")]
    check("...and the band says it in the same voice as the cards",
          _band and _band[-1] == _want, (_band, _want))

    # ---- a RISING card is one line ON SCREEN, not just in the model ----
    # *"the card should just show the rising text and nothing else"* [his,
    # 2026-07-31]. `boardagents` blanks the two sentence fields, but the title
    # row, the context tally and the worked-for stamp are QML's own and are
    # dropped by `AgentRow`'s `arising` — so this is checked against the drawn
    # items, which is the only place that half of the rule exists.
    tdir = os.path.join(tmp, "rising-transcripts")
    os.makedirs(tdir, exist_ok=True)
    old_tsc = os.environ.get("BOARD_TRANSCRIPTS")
    os.environ["BOARD_TRANSCRIPTS"] = tdir
    open(os.path.join(tdir, "ses-rising.jsonl"), "w").close()   # exists, empty
    ba.register("w-rising", "Make the scrollbar wider", os.getpid(),
                kind="worker", where="apps/x/**", session="ses-rising")
    agents.refresh()
    spin(250)
    rising = [a for a in prop(win, "agents") if a["id"] == "w-rising"]
    check("a freshly spawned worker is drawn, and it is RISING",
          len(rising) == 1 and rising[0].get("arising") is True, rising)
    card = [it for it in descendants(win.contentItem())
            if it.property("arising") is True]
    check("...and exactly one card on screen is in that state", len(card) == 1,
          len(card))
    if card:
        # The message box is EXCLUDED from "nothing else", deliberately. It is
        # the card's control surface rather than one of its lines — every
        # addressable card carries one — and the first seconds of a spawn are
        # exactly when he might want to correct it before it goes wrong, so
        # hiding it would take away a thing he did not ask to lose. Everything
        # that is a LINE of the card is what the rule covers.
        # One walk that PRUNES the box subtree, rather than two walks and a set
        # of `id()`s: PySide mints a fresh Python wrapper per traversal, so the
        # ids never match and the exclusion silently does nothing (it did).
        shown = []

        def _lines(it):
            if it.property("placeholder") is not None:
                return                       # the message box, and all of it
            t = it.property("text")
            if t is not None and it.isVisible() and str(t).strip():
                shown.append(str(t))
            for ch in it.childItems():
                _lines(ch)
        for ch in card[0].childItems():
            _lines(ch)
        # The three dots are ANIMATED, so the drawn cell is `.`, `..` or `...`
        # padded to three cells — assert the stem, never the current frame.
        check("...drawing the rising line and NOTHING else - his 'nothing else'",
              len(shown) == 1
              and shown[0].strip().startswith("%s arises" % rising[0]["name"]),
              shown)
        check("...so the title, the tally and the worked-for stamp are all gone",
              not any(rising[0]["title"] in s or "/" in s or "working for" in s
                      for s in shown), shown)
    ba.unregister("w-rising")
    if old_tsc is None:
        del os.environ["BOARD_TRANSCRIPTS"]
    else:
        os.environ["BOARD_TRANSCRIPTS"] = old_tsc
    agents.refresh()
    spin(150)
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
              or "rewrite this order" in str(b.property("placeholder"))
              for b in boxes if b not in unattached),
          [str(b.property("placeholder")) for b in boxes])
    typed = "the scrollbar arrows feel sluggish"
    said = keep[5].send("", "", "", typed)
    spin(200)
    check("what he types with nothing named goes to the inbox, and says only that",
          "inbox" in said and "summoner" in said, said)
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
          qlabels[-1] == "remove it from the pending orders"
          and qlabels[-2] == "", qlabels)
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
          card.get("saysLine") == card.get("name") + " is testing..."
          and card.get("saysDetail") == "the vtbclient parser"
          and card.get("doingLine") == "editing vtbclient.py",
          (card.get("saysLine"), card.get("saysDetail"),
           card.get("doingLine")))
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
    # ---- SOLOMON, IN A SECTION OF HIS OWN, above the workers ----
    # *"he should always be kept on the top of the agent list and should
    # basically indicate like he's there and ready to go at all times when hes
    # not doing something."* ...and then, twice: *"solmon should be in his own
    # \"summoner\" section above the agents section"*. So he is no longer a row
    # inside the workers' list at all: `boardwork.cards()` still orders him first
    # and still substitutes the standing row when nothing is running, and `main.py`
    # splits that one ordering into two lists. Nothing here registers an
    # orchestrator, so this is the standing row — it is the whole point that it
    # exists anyway.
    summoner = prop(win, "summonerCards")
    check("Solomon has a section of his own, and it holds only him",
          len(summoner) == 1
          and summoner[0].get("name") == ba.ORCHESTRATOR_NAME
          and summoner[0].get("state") == "idle",
          [(c.get("name"), c.get("state")) for c in summoner])
    check("...and the agents section below holds only the workers",
          all(c.get("name") != ba.ORCHESTRATOR_NAME for c in cards)
          and all(c.get("kind") != "orchestrator" for c in cards),
          [(c.get("name"), c.get("kind")) for c in cards])
    check("...leading with `Solomon awaits`, the way every card leads",
          summoner[0].get("saysLine") == "%s awaits" % ba.ORCHESTRATOR_NAME,
          summoner[0].get("saysLine"))
    check("...with no observation on him: nothing claims to have SEEN him",
          summoner[0].get("doingLine") == ""
          and summoner[0].get("running") is False, summoner[0])
    check("...and no box under it, there being nobody there to send to",
          summoner[0].get("id") == "" and summoner[0].get("waiting") == [],
          summoner[0])
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
    # A line that ends in `...` is drawn with those three cells ANIMATED
    # (`AgentRow.tick`), so a drawn line is matched by its stem rather than by an
    # exact string — the tail changes about once a second.
    def stem(s):
        return s[:-3] if s.endswith("...") else s

    saysStem = stem(card.get("saysLine") or "\0")
    saysY = min([y for y, s, _ in lines if s.startswith(saysStem)] or [1e9])
    check("the card's FIRST line is what the agent SAYS it is doing",
          bool(lines) and lines[0][1].startswith(saysStem),
          [(y, s) for y, s, _ in lines])
    # The observed line is drawn with the live tick on the end of it, so it is
    # found by its opening rather than by an exact match.
    doingY = min([y for y, s, _ in lines
                  if s.startswith(card.get("doingLine", "\0"))] or [1e9])
    check("...its SECOND is what it is OBSERVED doing, still under the claim",
          doingY > saysY,
          [(y, s) for y, s, _ in lines])
    check("...and the title row it used to open with is now the THIRD",
          ys.get("Wire FOCUS through vtbclient", -1) > doingY,
          [(y, s) for y, s, _ in lines])
    check("...with `where` still on the title's own line, right-aligned",
          ys.get("apps/pylib/**") == ys.get("Wire FOCUS through vtbclient"),
          [(y, s) for y, s, _ in lines])
    # ---- the tick on the end of the observed line ----
    # *"at the end of the second row of an agents information, it should have an
    # animated elipsies to show its currently happening"*. Three claims: it is
    # ASCII (§2.3), it does not reflow the line as it cycles (a fixed three
    # cells), and it appears ONLY where something is actually happening — a
    # stopped agent's past-tense line and the states that say nothing is
    # happening get none, which is §10's honesty rule about a moving thing.
    doingText = [s for y, s, _ in lines if y == doingY]
    # THE THIRD LINE ENDS ON ITS OWN WORDS — [his, 2026-07-29] *"the third line of
    # an agents card should not have the animated elipsies or any elipsies at the
    # end of it"*. It used to carry the tick; the tick is on the claim's words now
    # (the line above), and there is nothing appended here at all.
    check("the observed line ends on its words, with no dots of any kind",
          bool(doingText) and not doingText[0].rstrip().endswith(".")
          and "…" not in doingText[0]
          and doingText[0] == card.get("doingLine"),
          (doingText, card.get("doingLine")))
    # ...and THE TOP LINE, AND ONLY THE TOP LINE, TICKS — [his, 2026-07-29, and he
    # said it twice because the first pass put them one line down] *"the only line
    # of an agents card that should have the animated elipsies is the top line. no
    # others"*. So the verb line's last three cells cycle and the claim's words
    # under it end on the agent's own last word, with no dots at all rather than
    # three frozen ones. One mechanism for every line that ends in them, so his
    # card and a worker's cannot drift.
    saysItem = [t for y, s, t in lines if s.startswith(saysStem)]
    detailItem = [t for y, s, t in lines
                  if s.startswith(card.get("saysDetail") or "\0")]
    tails = set()
    for _ in range(20):
        if saysItem:
            tails.add(str(saysItem[0].property("text"))[-3:])
        spin(100)
    check("the verb line carries the ticking dots, and no other line does",
          len(tails) > 1 and {len(v) for v in tails} == {3}
          and all(set(v) <= {".", " "} for v in tails)
          and detailItem
          and not str(detailItem[0].property("text")).rstrip().endswith("."),
          (sorted(tails), detailItem and detailItem[0].property("text")))
    stoppedCards = [drawnCards.get(c.get("title")) for c in cards
                    if not c.get("running")]
    check("...and NOTHING that has stopped ticks - a gone agent is not happening",
          all(it is None or not any(str(it.property(k) or "").endswith("...")
                                    for k in ("saysLine", "saysDetail",
                                              "doingLine"))
              for it in stoppedCards),
          [(c.get("title"), c.get("running")) for c in cards])

    # The tone ladder, retuned for the new order (docs/DESIGN.md §10.6): the
    # LEAD tone goes to whichever line is drawn first, so a card never opens on
    # its quietest text. It is position, not trust, that picks it.
    tone = {s: t.property("color") for _, s, t in lines}
    saysTone = [t for s, t in tone.items() if s.startswith(saysStem)]
    check("...and the top line takes the lead tone, not the quietest one",
          saysTone and saysTone[0] == keep[-1].property("text")
          and tone.get("Wire FOCUS through vtbclient") == keep[-1].property("dim"),
          (saysTone, tone.get("Wire FOCUS through vtbclient")))
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

    # ---- the DRAWER: what the minister is actually saying ----
    # [his, 2026-07-30] *"a minister card should expand to show what that
    # minister is actually saying"* — clicking anywhere on the card slides a
    # drawer down out from under it with the last couple of lines that agent
    # logged, indented, with a rule down its left edge; clicking again closes it.
    #
    # Driven with a REAL left click on the card, because the card's own
    # right-click MouseArea used to be the only one on it and a left button
    # reached nothing at all — the same defect the double-click test below
    # records. The log is written into the harness's own `XDG_CACHE_HOME`.
    from PySide6.QtCore import QPointF, Qt                              # noqa: E402
    from PySide6.QtTest import QTest                                    # noqa: E402

    with open(bw._log_path("w-code"), "w") as f:
        f.write("first line, scrolled off\n"
                "\x1b[32mstill going\x1b[0m\n"
                "\n"
                "downloading 40%\rdownloading 100%\n"
                "  wrote vtbclient.py\n")
    tail = agents.output("w-code")
    check("a card can read the tail of its own agent's log",
          tail == ["still going", "downloading 100%", "  wrote vtbclient.py"],
          tail)
    check("...with the ANSI and the control junk gone, and no blank lines",
          not any("\x1b" in s or "\r" in s or not s.strip() for s in tail), tail)
    check("...and an agent that has logged NOTHING gets an empty answer, not junk",
          agents.output("w-read") == [] and agents.output("") == [],
          agents.output("w-read"))

    drawers = [it for it in descendants(cardItem or win.contentItem())
               if it.property("openH") is not None]
    check("a card carries exactly one output drawer", len(drawers) == 1,
          len(drawers))
    drawer = drawers[0] if drawers else None
    check("...and it is SHUT until he opens it, taking no height at all",
          drawer is not None and drawer.height() == 0, drawer and drawer.height())

    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier,
                     cardItem.mapToScene(QPointF(cardItem.width() / 2, 6))
                     .toPoint())
    spin(600)                                    # past the slide (§6.2's 260ms)
    check("clicking the card opens it, keyed by the AGENT and not the row",
          prop(win, "outputOpen").get("w-code") is True
          and drawer is not None and drawer.height() > 0,
          (prop(win, "outputOpen"), drawer and drawer.height()))
    drawn = [s for _, s, _ in _texts(drawer)] if drawer is not None else []
    check("...showing the last few lines the agent itself wrote",
          [s for s in drawn if "wrote vtbclient.py" in s] and len(drawn) <= 3,
          drawn)
    check("...indented past the card's own text, under a rule of its own",
          drawer is not None
          and [c for c in descendants(drawer)
               if c.property("color") is not None and c.property("width") == 1]
          and all(t.mapToItem(cardItem, 0, 0).x() > 10
                  for _, _, t in _texts(drawer)),
          [(t.mapToItem(cardItem, 0, 0).x()) for _, _, t in _texts(drawer)])

    # A REFRESH MUST NOT SHUT IT. The cards are rebuilt whenever the key list
    # changes, so this is the failure a drawer held in the delegate would have.
    agents.refresh()
    spin(300)
    drawers = [it for it in descendants(win.contentItem())
               if it.property("openH") is not None and it.height() > 0]
    check("...and it stays open across a refresh of the card list",
          prop(win, "outputOpen").get("w-code") is True and len(drawers) == 1,
          (prop(win, "outputOpen"), len(drawers)))

    # Re-found: the refresh may have rebuilt the delegate under us.
    cardItem = None
    for it in descendants(win.contentItem()):
        a = prop(it, "agent") if it.property("doingLine") is not None else None
        if isinstance(a, dict) and a.get("title") == "Wire FOCUS through vtbclient":
            cardItem = it
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier,
                     cardItem.mapToScene(QPointF(cardItem.width() / 2, 6))
                     .toPoint())
    spin(600)
    shut = [it for it in descendants(cardItem)
            if it.property("openH") is not None]
    check("clicking it again slides the drawer back up and hides it",
          not prop(win, "outputOpen").get("w-code")
          and shut and shut[0].height() == 0,
          (prop(win, "outputOpen"), shut and shut[0].height()))
    # THE BOX HE TYPES INTO KEEPS ITS OWN CLICKS. Click-anywhere is the gesture,
    # and the one thing on the card that must be exempt is the editor: putting
    # his caret in it would otherwise open a drawer over the words he is writing.
    box = [it for it in descendants(cardItem)
           if it.property("placeholder") is not None]
    if box:
        QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier,
                         box[0].mapToScene(QPointF(box[0].width() / 2,
                                                   box[0].height() / 2)).toPoint())
        spin(400)
        check("...and clicking INTO the card's box does not open one",
              not prop(win, "outputOpen").get("w-code"), prop(win, "outputOpen"))

    # ...and it says so in WORDS when there is nothing to show (§10): an empty
    # drawer would read as a broken one.
    empty = drawnCards.get("Find where focus is decided")
    if empty is not None:
        win.setProperty("outputOpen", {"w-read": True})
        spin(600)
        etexts = [s for _, s, _ in _texts(empty)]
        check("a drawer with nothing logged says so rather than opening empty",
              "nothing logged yet" in etexts, etexts)
        win.setProperty("outputOpen", {})
        spin(300)

    # ---- ...and ONE SWITCH opens every card's drawer at once ----
    # [his, 2026-07-30] a global toggle under `md`, PERSISTED (§14): he leaves
    # the logs showing and they are showing when he next opens the window. The
    # thing being asserted is that it is a DEFAULT and not a bulk edit — a card
    # that appears after the switch is thrown is open too — and that turning it
    # off puts every drawer away, including the ones he opened by hand.
    import main as brd_mod

    def _drawerHeights():
        return [it.height() for it in descendants(win.contentItem())
                if it.property("openH") is not None]

    def brd_settings_get(k):
        # A FRESH `Settings`, i.e. what the next launch reads off disk. Asking
        # the live one back would only prove the property was assigned.
        return brd_mod.Settings().get(k)

    cells = ["-" if isinstance(b, str) else str(b["label"])
             for b in prop(win, "tbButtons")]
    check("the titlebar carries a `lg` cell in its own section under `md`",
          cells[-3:] == ["md", "-", "lg"], cells)

    type(keep[2]).sent[:] = []
    keep[2].clicked.emit("logs")
    spin(600)
    heights = _drawerHeights()
    check("throwing it opens the drawer on EVERY card, not just the ones drawn",
          prop(win, "allLogs") is True and heights and all(h > 0 for h in heights),
          heights)
    regs = [m[1] for m in type(keep[2]).sent if m[0] == "buttons"]
    check("...and the cell lights, which is the only report a toggle owes (§12.1)",
          regs and ("lg", 1) in regs[-1], regs)
    check("...and it survives the app being closed and opened again (§14)",
          brd_settings_get("allLogs") is True, brd_settings_get("allLogs"))

    # A card he shuts by hand while the switch is on is an EXCEPTION to it, and
    # the others stay open — the map holds exceptions, not absolute states.
    win.setProperty("outputOpen", {"w-code": False})
    spin(600)
    check("...and shutting one card by hand leaves the rest open",
          [h for h in _drawerHeights() if h == 0]
          and [h for h in _drawerHeights() if h > 0], _drawerHeights())

    keep[2].clicked.emit("logs")
    spin(600)
    check("throwing it back shuts every drawer, exceptions included",
          prop(win, "allLogs") is False and all(h == 0 for h in _drawerHeights())
          and prop(win, "outputOpen") == {}, _drawerHeights())
    check("...and THAT is remembered too", brd_settings_get("allLogs") is False,
          brd_settings_get("allLogs"))

    # ---- ...and SOLOMON'S OWN ROW LEADS WITH HIS NAME ----
    # [his, 2026-07-29] the orchestrator's card should read *"Solomon is ..."*
    # like everybody else's, and he said so twice. The first answer put the name
    # in the name column on the title row, which is not what he asked for; the
    # standing row now carries `Solomon awaits` as its top line
    # (`boardwork._idle_orchestrator_row`), so `nameNeeded` is false on it and
    # the name column is not what is being measured here any more.
    #
    # The column's WIDTH rule still exists and still matters — the pool is
    # capped at six characters so the titles line up down the list, and
    # `Solomon` is seven — so it is asserted below for whichever card is
    # actually drawing one.
    solItem = None
    for it in descendants(win.contentItem()):
        if it.property("nameNeeded") is None:
            continue
        a = prop(it, "agent")
        if isinstance(a, dict) and a.get("name") == ba.ORCHESTRATOR_NAME:
            solItem = it
    solLines = _texts(solItem) if solItem is not None else []
    cols = [c for c in (descendants(solItem) if solItem is not None else [])
            if c.property("nameW") is not None]
    cellW = solItem.property("cellW") if solItem is not None else 0
    lead = "%s awaits" % ba.ORCHESTRATOR_NAME
    check("Solomon's row LEADS with his name, like every other card",
          bool(solLines) and solLines[0][1] == lead,
          [(y, s) for y, s, _ in solLines])
    check("...whole, not six characters of it - the pool's cap is not his",
          ba.ORCHESTRATOR_NAME in solLines[0][1] if solLines else False,
          [(y, s) for y, s, _ in solLines])
    check("...so the name column is not drawn twice on the same card",
          solItem is not None and solItem.property("nameNeeded") is False
          and len([s for _, s, _ in solLines
                   if s == ba.ORCHESTRATOR_NAME]) == 0,
          [(y, s) for y, s, _ in solLines])
    check("...and it still MEASURES for a card that does draw one",
          not cols or not cellW
          or all(c.property("nameW") >= (len(ba.ORCHESTRATOR_NAME) + 1) * cellW
                 for c in cols if c.property("nameW") > 0),
          [(c.property("nameW"), cellW) for c in cols])
    # HIS TEXT NEVER GOES QUIET, and it never wears the unfocused grey — [his,
    # 2026-07-29] *"his text should never become the unfocused colors and he
    # doesnt need a line to the left of his card"*. The standing row used to lead
    # at `fgDim` for not running; his card is not a record of finished work, so it
    # leads at full strength either way, and its tones are the `Theme` ones rather
    # than the window's faded pair.
    check("...and the standing row still leads at full strength, never dimmed",
          solItem is not None and solItem.property("running") is False
          and solItem.property("summoner") is True
          and {s: t.property("color") for _, s, t in solLines}
          .get(lead) == solItem.property("fgText"),
          [(s, t.property("color").name()) for _, s, t in solLines])
    check("...with the unfocused fade never reaching him, whatever the window",
          solItem is not None
          and solItem.property("fgText") == keep[-1].property("text")
          and solItem.property("fgDim") == keep[-1].property("textDim")
          and solItem.property("fgAccent") == keep[-1].property("accent"),
          [solItem.property("fgText").name() if solItem else None,
           keep[-1].property("text").name()])
    check("...and no accent rule to the left of his card",
          solItem is not None
          and not any(it.property("width") == 2 and it.isVisible()
                      for it in solItem.childItems()),
          [(it.property("width"), it.isVisible())
           for it in solItem.childItems()] if solItem else None)
    check("...and 'nothing is running' is about the WORKERS, not about him",
          prop(win, "nothingRunning") is False, prop(win, "nothingRunning"))

    # ---- HOW FULL IT IS, at the right end of the TOP row ----
    # *"on the very right of the top row of the agent's information box it
    # should keep a running tally of how much context that agent has vs how much
    # it can handle"*. On screen: it is on the card's OWN top line, its right
    # edge is the card's right edge, and a card with nothing measured draws none
    # rather than a zero.
    check("a card with nothing measured carries no tally at all",
          all(r.get("contextLine", "") == "" for r in cards),
          [(r.get("title"), r.get("contextLine")) for r in cards])
    _tsc_usage(tmp, u, "claude-opus-5", {"input_tokens": 2000,
                                         "cache_read_input_tokens": 60000})
    agents.refresh()
    spin(300)
    tallied = {r["title"]: r.get("contextLine", "")
               for r in prop(win, "agentCards")}
    check("...and one whose transcript states its usage carries it, measured",
          tallied.get("Wire FOCUS through vtbclient") == "62k/200k", tallied)
    codeItem = None
    for it in descendants(win.contentItem()):
        if it.property("contextLine") is None or it.property("nameNeeded") is None:
            continue
        a = prop(it, "agent")
        if isinstance(a, dict) and a.get("title") == "Wire FOCUS through vtbclient":
            codeItem = it
    drawn = _texts(codeItem) if codeItem is not None else []
    tallyDrawn = [(y, s, t) for y, s, t in drawn if s == "62k/200k"]
    check("...drawn on the card's TOP line, not on a line of its own",
          len(tallyDrawn) == 1 and tallyDrawn[0][0] == drawn[0][0],
          [(y, s) for y, s, _ in drawn])
    claimDrawn = [t for _, s, t in drawn if s.startswith(card.get("name", "\0"))]
    check("...at the RIGHT end of it, and not over the text it shares the row with",
          bool(tallyDrawn) and bool(claimDrawn)
          and tallyDrawn[0][2].x() >= claimDrawn[0].x() + claimDrawn[0].width()
          and abs((tallyDrawn[0][2].x() + tallyDrawn[0][2].width())
                  - codeItem.width()) < 16,
          [(s, t.x(), t.width()) for _, s, t in drawn[:2]] + [codeItem.width()])
    check("...in the quiet tone: it is standing metadata, not an alert",
          bool(tallyDrawn)
          and tallyDrawn[0][2].property("color") == keep[-1].property("dim"),
          tallyDrawn and tallyDrawn[0][2].property("color").name())
    # ...and the working duration beside it, on the same row and the same rung.
    # From the DRAWN card's own agent, not from a snapshot taken elsewhere in
    # this test — the line is per-record and only that item's is being checked.
    codeAgent = prop(codeItem, "agent") if codeItem is not None else {}
    bornStr = codeAgent.get("workedLine", "") if isinstance(codeAgent, dict) else ""
    bornDrawn = [(y, s, t) for y, s, t in drawn if bornStr and s == bornStr]
    check("a card says how long its agent has been working, next to the tally",
          bool(bornStr) and len(bornDrawn) == 1
          and bornDrawn[0][0] == drawn[0][0], (bornStr, [s for _, s, _ in drawn]))
    check("...immediately LEFT of the tally, not stacked or overlapping it",
          bool(bornDrawn) and bool(tallyDrawn)
          and bornDrawn[0][2].x() + bornDrawn[0][2].width()
          <= tallyDrawn[0][2].x(),
          [(s, t.x(), t.width()) for _, s, t in bornDrawn + tallyDrawn])
    check("...and in the same quiet tone, both being standing metadata",
          bool(bornDrawn)
          and bornDrawn[0][2].property("color") == keep[-1].property("dim"),
          bornDrawn and bornDrawn[0][2].property("color").name())

    # ...with the store's own sections folded away, so the shot is of THIS
    # section rather than of whatever happens to be above it.
    win.setProperty("collapsed", {"needs": True, "landed": True})
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
          len(prop(win2, "landed")) == 1)

    # ONE SENTENCE AND NO OTHER. [his, 2026-07-29] *"decisions brought to you
    # from Solomon."* is the whole of the empty section — the second placeholder
    # line went, and so did the store's own framing paragraph, which empty would
    # be a second introduction to nothing. Asserted on the DRAWN text, because
    # both of the lines this replaces were drawn from three different places.
    def _visible_texts():
        out = []
        for t in descendants(win2.contentItem()):
            s = t.property("text")
            if isinstance(s, str) and s.strip() and t.isVisible():
                out.append(s.strip())
        return out

    shown = _visible_texts()
    check("the empty NEEDS YOU is his one sentence, verbatim",
          "decisions brought to you from Solomon." in shown, shown[:12])
    check("...and neither placeholder line it replaced is drawn any more",
          not any(s.startswith("nothing needs you")
                  or s.startswith("nothing here expires") for s in shown),
          [s for s in shown if s.startswith("nothing")])
    check("...nor the store's framing paragraph, empty needing no second one",
          not any(s.startswith("Decisions only you can make") for s in shown),
          [s for s in shown if s.startswith("Decisions")])
    # The header lost its word, not its controls: [his] *"just have the line and
    # collapse toggle"*. `[-]` is still drawn and the band still toggles.
    check("...and the section header is the toggle and the rule alone",
          "needs you" not in shown and "[-]" in shown,
          [s for s in shown if s in ("needs you", "[-]", "[+]")])
    win2.setProperty("collapsed", {"needs": True})
    spin(200)
    check("...which he can still work, the whole band being the hit target",
          prop(win2, "collapsed").get("needs") is True
          and "[+]" in _visible_texts())
    win2.setProperty("collapsed", {})
    spin(200)
    shot(win2, "03-empty-needs-you")

    # NOTHING RUNNING is the resting state of the agents section, and the one he
    # will see most often — it has to read as finished, not as broken. The
    # harness stubs /proc away entirely (a machine with no agent and no session
    # on it), because the process that runs this test is itself under a Claude
    # session and would otherwise be in the list.
    real_procs = ba._procs
    ba._procs = lambda: {}
    # ...and the QUEUED tasks earlier tests left behind go with them: a task
    # waiting for a slot is a card in this section, so the section is not empty
    # while one exists and `nothingRunning` is honestly false.
    pend = bw.work_dir("pending")
    for f in os.listdir(pend):
        os.unlink(os.path.join(pend, f))
    try:
        keep2[5].refresh()
        spin(250)
        check("with nothing running the agents section is empty, not broken",
              prop(win2, "agents") == [], prop(win2, "agents"))
        # [his, 2026-07-29] *"binds ministers."* — what the triangle IS, and
        # with board-watch armed it is the ONLY text down there: no systemd
        # sentence, no second line. The window's `armed` comes from the real
        # `Agents`, so the armed case is forced here rather than waited for.
        keep2[5]._armed, keep2[5]._watcher = True, "board-watch is armed - x"
        keep2[5].changed.emit()
        spin(200)
        shown2 = _visible_texts()
        check("the empty triangle says what it is, in his words",
              "binds ministers." in shown2, shown2[:12])
        check("...and armed, that sentence is the only text the section draws",
              not any("board-watch" in s for s in shown2),
              [s for s in shown2 if "board-watch" in s])
        keep2[5]._armed = False
        keep2[5].changed.emit()
        spin(200)
        shown3 = _visible_texts()
        check("...while a watcher that will never fire is said so, once",
              "binds ministers." in shown3
              and shown3.count("board-watch is not armed") == 1,
              [s for s in shown3 if "board-watch" in s])
        # Unknown is neither: §10 does not let "could not ask systemctl" become
        # a claim about his machine in either direction.
        keep2[5]._armed, keep2[5]._watcher = None, "board-watch could not be asked"
        keep2[5].changed.emit()
        spin(200)
        shown4 = _visible_texts()
        check("...and an unaskable systemctl reports itself, claiming neither",
              "board-watch could not be asked" in shown4
              and "board-watch is not armed" not in shown4,
              [s for s in shown4 if "board-watch" in s])
        keep2[5]._armed, keep2[5]._watcher = True, "board-watch is armed - x"
        keep2[5].changed.emit()
        win2.setProperty("collapsed", {"needs": True, "landed": True})
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
    # *"i should be able to just double click on stuff in the to do
    # section to remove them"*. It did nothing for a day: the
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
    # ---- the bullet's two blocks are two items, with a gap, or one and none ----
    B.write(path, FIXTURE.replace(
        "- **Relaunch `reader`** - live source, no hot reload.",
        "- COMPLETION: **the thing** - it works now\n"
        "  Why it did not before, and what to watch.\n"
        "- INFORMATION: nothing under this one"))
    engine2, win2, keep2 = build(app, path)
    spin(400)
    drawn = [str(it.property("text")) for it in descendants(win2.contentItem())
             if it.property("text") is not None and it.isVisible()]
    check("the elaboration is drawn as its OWN block, under the summary",
          "COMPLETION: the thing - it works now" in drawn
          and "Why it did not before, and what to watch." in drawn,
          [t for t in drawn if "the thing" in t or "watch" in t])
    # ...and the one with nothing under it is SHORTER, because the gap and the
    # second block collapse rather than being reserved (§5.2).
    rows = {}
    for it in descendants(win2.contentItem()):
        if it.property("replying") is None:
            continue
        texts = [str(t.property("text")) for t in descendants(it)
                 if t.property("text") is not None]
        for t in texts:
            if t.startswith(("COMPLETION:", "INFORMATION:")):
                rows[t.split(":")[0]] = it.property("height")
    check("...and a bullet with none is SHORTER: no gap, no empty second block",
          len(rows) == 2 and rows["INFORMATION"] < rows["COMPLETION"], rows)
    shot(win2, "07-todo-summary")

    # ---- FOLDING ONE CHORE, from the mark to the left of it ----
    # *"i should be able to collapse to a single line and expand messages in
    # the to do section via the mark to the left of the messages."* Here rather
    # than beside the other chore tests because this is the fixture with an
    # elaboration to fold AWAY. Three claims: the mark says which way it goes,
    # folding takes the elaboration and leaves the summary, and the store does
    # not move a byte — it is a VIEW gesture and the round trip is contractual.
    from PySide6.QtCore import QPointF, Qt                             # noqa: E402
    from PySide6.QtTest import QTest                                   # noqa: E402
    foldRow, otherRow = None, None
    for it in descendants(win2.contentItem()):
        if it.property("folded") is None:
            continue
        a = prop(it, "modelData")
        if isinstance(a, dict) and a.get("detail"):
            foldRow = it
        elif isinstance(a, dict):
            otherRow = it
    marks = [it for it in descendants(foldRow) if foldRow is not None
             and str(it.property("text")) in ("-", "+")]
    detail = [it for it in descendants(foldRow) if foldRow is not None
              and str(it.property("text")) == "Why it did not before, "
                                              "and what to watch."]
    storeBefore = open(path).read()
    tallBefore = foldRow.height() if foldRow is not None else 0
    check("a chore's mark says which way it goes, in ASCII the font has (2.3)",
          len(marks) == 1 and str(marks[0].property("text")) == "-",
          [str(m.property("text")) for m in marks])
    check("...and its elaboration is drawn, this one being open",
          len(detail) == 1 and detail[0].isVisible(),
          [d.isVisible() for d in detail])
    if foldRow is not None:
        QTest.mouseClick(win2, Qt.LeftButton, Qt.NoModifier,
                         foldRow.mapToScene(QPointF(4, 8)).toPoint())
        spin(250)
    check("clicking the mark folds that chore to a single line",
          foldRow is not None and foldRow.property("folded") is True
          and foldRow.height() < tallBefore,
          (tallBefore, foldRow is not None and foldRow.height()))
    check("...the elaboration is what goes, the summary being what he keeps",
          bool(detail) and not detail[0].isVisible()
          and bool(marks) and marks[0].isVisible(),
          [d.isVisible() for d in detail])
    check("...and the mark now says it is folded, so the row is not a dead end",
          bool(marks) and str(marks[0].property("text")) == "+",
          [str(m.property("text")) for m in marks])
    check("...with nothing cut by a glyph this font cannot draw (2.3)",
          foldRow is not None
          and all("…" not in str(t.property("text") or "")
                  for t in descendants(foldRow)),
          [str(t.property("text")) for t in descendants(foldRow)
           if foldRow is not None and t.property("text")])
    check("...one chore at a time - this is not a section-wide switch",
          otherRow is not None and otherRow.property("folded") is False,
          otherRow is not None and otherRow.property("folded"))
    check("...and the chore is untouched on disk, folding being a VIEW only",
          open(path).read() == storeBefore
          and len(prop(win2, "todo")) == 2, prop(win2, "todo"))
    if foldRow is not None:
        QTest.mouseClick(win2, Qt.LeftButton, Qt.NoModifier,
                         foldRow.mapToScene(QPointF(4, 8)).toPoint())
        spin(250)
    check("...and clicking it again puts the whole chore back, unchanged",
          foldRow is not None and foldRow.property("folded") is False
          and abs(foldRow.height() - tallBefore) < 1
          and bool(detail) and detail[0].isVisible(),
          (tallBefore, foldRow is not None and foldRow.height()))

    cardW, titles = title_width(win.contentItem())
    check("...and the question text is the same width stamped or not",
          titles0 > 0 and titles0 == titles, (titles0, titles))
    check("...having given up the column whether it uses it or not",
          titles > 0 and titles < bare - 100, (titles, bare))
    shot(win, "06-placed")

    # ---- ...and WHO put it there, on the line ABOVE the time ----
    # *"every entry on the board should record WHO wrote it"*, drawn in the
    # gutter above the time. Two claims the store test cannot make: that it is
    # drawn at all, and — the one that matters — that an entry with NO
    # attribution reserves nothing for it, since every entry written before this
    # existed has none and one of the three writers does not emit it yet.
    slots0 = [it for it in descendants(win0.contentItem())
              if it.objectName() == "gutterBy"]
    check("an unattributed board reserves NOTHING for an author it does not have",
          slots0 and all(str(it.property("text")) == "" and not it.isVisible()
                         and it.height() == 0 for it in slots0),
          [(str(it.property("text")), it.isVisible(), it.height()) for it in slots0])
    check("...and the stamp is never prose: no comment syntax reaches the screen",
          not [it for it in descendants(win0.contentItem())
               if str(it.property("text")).startswith("<!--")],
          [str(it.property("text")) for it in descendants(win0.contentItem())
           if str(it.property("text")).startswith("<!--")])

    B.write(path, FIXTURE)
    os.environ["BOARD_AGENT_ID"] = "w2502ad"
    # ...and one of them was dispatched from something he typed, so it also
    # quotes that (`for:`), which is the line drawn between the two it already
    # had.
    HIS_ORDER = "make the titlebar stop flashing"
    os.environ["BOARD_ORDER"] = HIS_ORDER
    try:
        who = bm.whoami()[1]
        bm.note("INFORMATION: **an attributed chore** - it is done.\n"
                "    And this is the verbose line under it.", path=path)
        bm.ask("An attributed question?", if_unanswered="nothing happens", path=path)
    finally:
        del os.environ["BOARD_AGENT_ID"]
        del os.environ["BOARD_ORDER"]
    stamp = [d["placed"] for d in B.parse(B.read(path))["needs"] if d["placed"]][0]
    engineB, winB, keepB = build(app, path)
    spin(400)

    def boxes(s):
        """(top, right edge) of every visible drawing of `s`, topmost first."""
        from PySide6.QtCore import QPointF                              # noqa: E402
        out = []
        for it in descendants(winB.contentItem()):
            if str(it.property("text")) == s and it.isVisible():
                p = it.mapToScene(QPointF(0, 0))
                out.append((round(p.y(), 1), round(p.x() + it.property("width"), 1)))
        return sorted(out)

    authors, times = boxes(who), boxes(stamp)
    check("both shapes draw who put them there - the decision and the bullet",
          who and len(authors) == 2 and len(times) == 2, (who, authors, times))
    check("...ABOVE the time, in the same trailing-edge column (§9.1)",
          len(authors) == len(times)
          and all(a[0] < t[0] for a, t in zip(authors, times))
          and all(a[1] == t[1] for a, t in zip(authors, times)),
          (authors, times))
    # ...and the two stamped entries are the ONLY ones that draw an author on a
    # board that also holds three older ones. A slot that filled itself in would
    # be an invented attribution, which is worse than none (§10).
    filled = [it for it in descendants(winB.contentItem())
              if it.objectName() == "gutterBy" and it.isVisible()]
    check("...and the older items on the same board still draw none",
          len(filled) == 2 and all(str(it.property("text")) == who
                                   for it in filled),
          [str(it.property("text")) for it in filled])
    # A ONE-LINE bullet has one line of text against TWO of metadata, and the
    # row has to be as tall as the taller of the two or the name and the time
    # draw over the bullet below — which is what a stack of one-line SUMMONED
    # lines is. The decision card has always taken the max; the bullet did not.
    for it in filled:
        row = it.parentItem().parentItem()      # gutter Column -> the row's `bar`
        check("a stamped row is at least as tall as its own gutter",
              row.height() >= it.parentItem().height() > 0,
              (row.height(), it.parentItem().height()))

    # ---- ...and WHICH OF HIS ASKS it came out of, BETWEEN the two lines ----
    # *"...between the top line and the second verbose line"*, so the check is
    # the ordering and not merely the presence: summary above it, elaboration
    # below it.
    quoted = boxes("for: " + HIS_ORDER)
    summary = [b for b in boxes("INFORMATION: an attributed chore - it is done.")]
    verbose = boxes("And this is the verbose line under it.")
    check("an information card quotes the ask it came out of, truncated",
          len(quoted) == 1, (quoted, [str(it.property("text"))
                                      for it in descendants(winB.contentItem())
                                      if str(it.property("text")).startswith("for:")]))
    check("...between the top line and the verbose line under it",
          len(summary) == 1 and len(verbose) == 1
          and summary[0][0] < quoted[0][0] < verbose[0][0],
          (summary, quoted, verbose))
    # ...and the cards that were NOT dispatched from anything quote nothing:
    # every entry written before this existed is one of those.
    check("...and a card with no recorded ask draws no line for one",
          len([it for it in descendants(winB.contentItem())
               if str(it.property("text")).startswith("for: ")
               and it.isVisible()]) == 1)
    shot(winB, "06b-attributed")


def test_usage(tmp):
    """The two usage bars: HIS number, or none, and never a Fable one.

    Every check here is about honesty rather than arithmetic — the percentages
    are the CLI's own. What can go wrong is drawing one that is not his (the
    scoped Fable entry), drawing a zero where there is no reading, or drawing an
    hours-old figure as if it were now.
    """
    import boardusage as bu
    print("\n=== usage ===")

    def write(name, payload):
        p = os.path.join(tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        return p

    now = 1785379200.0
    real = write("real.json", {"cachedUsageUtilization": {
        "fetchedAtMs": int((now - 300) * 1000),
        "utilization": {
            "five_hour": {"utilization": 4, "resets_at": None},
            "seven_day": {"utilization": 73,
                          "resets_at": "2026-08-02T02:59:59+00:00"},
            "seven_day_opus": None,
            "limits": [
                {"kind": "session", "group": "session", "percent": 4,
                 "resets_at": None, "scope": None},
                {"kind": "weekly_all", "group": "weekly", "percent": 73,
                 "resets_at": "2026-08-02T02:59:59+00:00", "scope": None},
                {"kind": "weekly_scoped", "group": "weekly", "percent": 34,
                 "resets_at": "2026-08-02T02:59:59+00:00",
                 "scope": {"model": {"id": None, "display_name": "Fable"}}},
            ]}}})
    rows = bu.readings(real, now)
    check("both windows are read, in order, from claude code's own cache",
          [r["key"] for r in rows] == ["session", "weekly"]
          and [r["text"] for r in rows] == ["4%", "73%"], rows)
    # THE constraint he stated: no Fable figure anywhere. The payload carries
    # one (34%, `weekly_scoped`) and `weekly_all` already contains that usage,
    # so folding it in is nothing more than never reading the scoped entry.
    blob = json.dumps(rows).lower()
    check("...and the per-model breakout is not drawn, in any row",
          "fable" not in blob and "34%" not in blob, blob)
    check("...the weekly bar being the WHOLE account, which is why",
          rows[1]["percent"] == 73, rows[1])
    check("...saying when it resets, in a clock this font can draw (2.3)",
          "resets" in rows[1]["detail"]
          and all(ord(c) < 128 for c in rows[1]["detail"]), rows[1]["detail"])
    check("...and the short window is named for what it IS - 5 hours, not a day",
          rows[0]["label"] == "5h" and "5 hour" in rows[0]["detail"],
          rows[0]["detail"])

    # ---- the tooltip line: HOW LONG until this limit comes back ----
    # [his, 2026-07-30] *"the tooltip should just say `resets in ____`"* — one
    # line, a countdown, nothing else. This payload has one window with a
    # `resets_at` and one without, which is the whole point: neither may end up
    # with an empty chip (§10), and the one that cannot say a span must say THAT
    # rather than nothing.
    check("each window's tooltip is a countdown and nothing else",
          rows[1]["reset"] == "resets in 3d" and "\n" not in rows[1]["reset"],
          rows[1]["reset"])
    check("...and a window with no reset time in the payload still says `resets in`",
          rows[0]["reset"] == "resets in ? - this reading carries no reset time",
          rows[0]["reset"])
    check("...and a reset time already gone by is not counted down to 0m",
          bu.readings(real, now + 4 * 86400)[1]["reset"]
          == "resets in ? - this reading's reset time has gone by",
          bu.readings(real, now + 4 * 86400)[1]["reset"])
    check("...in ASCII, so the chip cannot clip on a missing glyph (2.3)",
          all(ord(c) < 128 for c in rows[0]["reset"] + rows[1]["reset"]),
          [rows[0]["reset"], rows[1]["reset"]])

    # A reading nobody has taken is UNKNOWN, never 0% — a bar at zero says "he
    # has used none of it", which is a claim (10).
    for name, payload in (("none", None),
                          ("empty", {}),
                          ("nokey", {"cachedUsageUtilization": {}}),
                          ("junk", {"cachedUsageUtilization":
                                    {"utilization": {"limits": "no"}}}),
                          ("nan", {"cachedUsageUtilization": {"utilization": {
                              "limits": [{"kind": "session", "percent": None,
                                          "scope": None}]}}})):
        p = os.path.join(tmp, "gone.json") if payload is None \
            else write(name + ".json", payload)
        rows = bu.readings(p, now)
        check("a missing/broken reading (%s) says unknown, and draws no bar" % name,
              all(r["known"] is False and r["text"] == "unknown" for r in rows),
              rows)
        check("...and its tooltip says why there is no reset time either (%s)" % name,
              all(r["reset"] == "resets in ? - no usage reading on this host yet"
                  for r in rows), [r["reset"] for r in rows])

    # The old payload shape, before `limits` existed: the two flat totals are
    # still unscoped, so they are still his.
    flat = write("flat.json", {"cachedUsageUtilization": {
        "fetchedAtMs": int((now - 60) * 1000),
        "utilization": {"five_hour": {"utilization": 11, "resets_at": None},
                        "seven_day": {"utilization": 50, "resets_at": None},
                        "seven_day_opus": {"utilization": 99}}}})
    rows = bu.readings(flat, now)
    check("a payload with no `limits` list falls back to the flat totals",
          [r["text"] for r in rows] == ["11%", "50%"], rows)
    check("...and never to a per-model key, whatever it says",
          "99" not in json.dumps(rows), rows)

    # A weekly whose ONLY entry is the scoped one must read unknown. Silently
    # promoting it would put Fable's number under the word "7d".
    only = write("only.json", {"cachedUsageUtilization": {
        "fetchedAtMs": int(now * 1000),
        "utilization": {"limits": [
            {"kind": "weekly_scoped", "group": "weekly", "percent": 34,
             "scope": {"model": {"display_name": "Fable"}}}]}}})
    rows = bu.readings(only, now)
    check("a scoped-only weekly is unknown, not promoted to the whole account",
          rows[1]["known"] is False and "34" not in json.dumps(rows), rows)

    # An old cache still shows its number — 73% an hour ago is not false — but
    # carries its age in the ROW, because colour alone can be missed (3.5).
    old = write("old.json", {"cachedUsageUtilization": {
        "fetchedAtMs": int((now - 9 * 3600) * 1000),
        "utilization": {"limits": [
            {"kind": "session", "percent": 20, "scope": None},
            {"kind": "weekly_all", "percent": 60, "scope": None}]}}})
    rows = bu.readings(old, now)
    check("a stale cache still reports, and says how old in the row itself",
          all(r["stale"] and r["note"] == "9h old" for r in rows),
          [r["note"] for r in rows])
    fresh = bu.readings(real, now)
    check("...while a fresh one carries no age at all",
          all(f["note"] == "" for f in fresh), [f["note"] for f in fresh])

    # It reads a file it does not own, so it may never write one.
    before = sorted(os.listdir(tmp))
    bu.readings(real, now)
    check("reading his config never writes to it", sorted(os.listdir(tmp)) == before)


def test_usage_fetch(tmp):
    """Where the number comes FROM, now that it no longer waits for a session.

    [his, 2026-07-29] *"why did it take me opening an instance of claude-code for
    the usage indicators to update? they should always be up to date"* —
    `~/.claude.json` advances only while a CLI session runs, so `boardusage`
    fetches for itself. The checks are about the two ways that can go wrong:
    reading the STALER of the two caches, and overwriting a good reading with a
    failure.
    """
    import boardusage as bu
    print("\n=== usage: the live fetch ===")
    now = 1785379200.0

    def envelope(fetched, session, weekly):
        return {"cachedUsageUtilization": {
            "fetchedAtMs": int(fetched * 1000),
            "utilization": {"limits": [
                {"kind": "session", "percent": session, "scope": None},
                {"kind": "weekly_all", "percent": weekly, "scope": None}]}}}

    def write(path, payload):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

    real = (bu.CLAUDE_JSON, bu.LIVE_PATH, bu.CREDS, bu.urllib.request.urlopen)
    bu.CLAUDE_JSON = os.path.join(tmp, "claude.json")
    bu.LIVE_PATH = os.path.join(tmp, "state", "usage.json")
    bu.CREDS = os.path.join(tmp, "creds.json")
    off = os.environ.pop(bu.OFFLINE_ENV, None)
    try:
        # ---- whichever cache is newer is the one drawn ----
        os.makedirs(os.path.dirname(bu.LIVE_PATH), exist_ok=True)
        write(bu.CLAUDE_JSON, envelope(now - 8 * 3600, 4, 73))
        rows = bu.readings(None, now)
        check("with only the CLI's cache, it is read exactly as before",
              [r["text"] for r in rows] == ["4%", "73%"]
              and rows[0]["note"] == "8h old", rows)
        write(bu.LIVE_PATH, envelope(now - 30, 9, 75))
        rows = bu.readings(None, now)
        check("...and our own fresher reading supersedes it, age and all",
              [r["text"] for r in rows] == ["9%", "75%"]
              and all(r["note"] == "" for r in rows), rows)
        write(bu.CLAUDE_JSON, envelope(now - 5, 11, 76))
        rows = bu.readings(None, now)
        check("...while a CLI that got there first is never thrown away",
              [r["text"] for r in rows] == ["11%", "76%"], rows)
        write(bu.LIVE_PATH, "not json at all")
        rows = bu.readings(None, now)
        check("...and one unreadable cache does not take the other down with it",
              [r["text"] for r in rows] == ["11%", "76%"], rows)

        # ---- a fetch is refused before it is attempted, when it must be ----
        sent = []
        check("no credentials file at all means no request, and it says so",
              bu.fetch(now=now) == "no-token" and not sent, sent)
        write(bu.CREDS, {"claudeAiOauth": {
            "accessToken": "sk-ant-oat01-x",
            "expiresAt": int((now - 60) * 1000)}})
        check("an expired token is not spent on a round trip that can only 401",
              bu.fetch(now=now) == "expired" and not sent, sent)
        write(bu.CREDS, {"claudeAiOauth": {
            "accessToken": "sk-ant-oat01-x",
            "expiresAt": int((now + 3600) * 1000)}})

        # ---- and with a usable one, the wire is the CLI's own shape ----
        class Reply:
            def __init__(self, body):
                self._body = json.dumps(body).encode()

            def read(self, *a):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        answer = [{"limits": [
            {"kind": "session", "percent": 21, "resets_at": None,
             "scope": None},
            {"kind": "weekly_all", "percent": 80, "resets_at": None,
             "scope": None},
            {"kind": "weekly_scoped", "percent": 34, "resets_at": None,
             "scope": {"model": {"display_name": "Fable"}}}]}]

        def fake(req, timeout=None):
            sent.append((req.full_url, req.get_header("Authorization"), timeout))
            if isinstance(answer[0], Exception):
                raise answer[0]
            return Reply(answer[0])

        bu.urllib.request.urlopen = fake
        check("a good fetch stores the reading and reports ok",
              bu.fetch(now=now) == "ok" and os.path.exists(bu.LIVE_PATH), sent)
        check("...having asked the account's own endpoint, with the CLI's token",
              len(sent) == 1 and sent[0][0] == bu.USAGE_URL
              and sent[0][1] == "Bearer sk-ant-oat01-x"
              and sent[0][2] == bu.FETCH_TIMEOUT, sent)
        rows = bu.readings(None, now)
        check("...and it is what the bars draw, with no age on it",
              [r["text"] for r in rows] == ["21%", "80%"]
              and all(r["note"] == "" for r in rows), rows)
        check("...still with no Fable figure, the wire carrying one",
              "34" not in json.dumps(rows), rows)

        # A failure must cost freshness and NOTHING else: the reading above has
        # to survive every one of these, or an endpoint having a bad afternoon
        # would blank a bar that was working.
        for why, reply in (("offline", bu.urllib.error.URLError("down")),
                           ("unauthorized",
                            bu.urllib.error.HTTPError(bu.USAGE_URL, 401, "no",
                                                      None, None)),
                           ("http-500",
                            bu.urllib.error.HTTPError(bu.USAGE_URL, 500, "no",
                                                      None, None)),
                           ("bad-payload", {"limits": []}),
                           ("bad-payload", ["not", "a", "dict"])):
            answer[0] = reply
            got = bu.fetch(now=now)
            rows = bu.readings(None, now)
            check("a failed fetch (%s) keeps the last reading, unblanked" % why,
                  got == why and [r["text"] for r in rows] == ["21%", "80%"],
                  (got, rows))

        # The harness switch, which every other test in this file runs under.
        os.environ[bu.OFFLINE_ENV] = "1"
        before = len(sent)
        check("BOARD_USAGE_OFFLINE reaches neither the network nor the CLI",
              bu.fetch(now=now) == "off" and bu.nudge() is False
              and len(sent) == before, sent)
    finally:
        os.environ.pop(bu.OFFLINE_ENV, None)
        if off is not None:
            os.environ[bu.OFFLINE_ENV] = off
        (bu.CLAUDE_JSON, bu.LIVE_PATH, bu.CREDS,
         bu.urllib.request.urlopen) = real


def test_usage_follows_agents(app):
    """The bars move when an agent's life does, not only on their own clock.

    [his, 2026-07-29] *"ensure the usage indicators update every time an agent is
    killed / finishes their job / etc."* Two halves, and the second is the one
    that can regress quietly: it must fire on a LIFECYCLE transition and NOT on
    the churn every 2.5s poll brings, or the 60s fallback has been replaced by a
    2.5s poll of `~/.claude.json`.
    """
    import boardagents as ba
    import boardusage as bu
    import boardwork as bw
    import main as brd
    print("\n=== usage follows the agents ===")

    def card(cid, state, worked="working for 2 minutes", ctx=""):
        return {"id": cid, "name": "", "kind": "decision", "title": "T",
                "where": "apps/x/**", "pid": 1, "session": "", "state": state,
                "born": 1785380450.0, "unread": 0, "phase": "unreported",
                "says": "", "actually": "", "saysLine": "", "doingLine": "",
                "observed": "unlinked", "contextLine": ctx,
                "workedLine": worked}

    live = [card("w-one", "running")]
    real_cards, real_agents, real_pending = bw.cards, ba.agents, ba.pending
    real_readings = bu.readings
    reads = []
    bw.cards = lambda: list(live)
    ba.agents = lambda: list(live)
    ba.pending = lambda: []
    try:
        agents = brd.Agents()
        usage = brd.Usage()
        usage.follow(agents)
        fired = []
        agents.lives.connect(lambda: fired.append(1))
        bu.readings = lambda *a, **k: reads.append(1) or real_readings(*a, **k)

        # The churn: the same agent, two minutes older, with a context tally it
        # did not have. The card redraws; nothing was born and nothing died.
        live[:] = [card("w-one", "running", "working for 4 minutes", "12% of 200k")]
        agents.refresh()
        check("a card merely redrawing does NOT re-read his usage",
              fired == [] and reads == [], (fired, reads))

        # ...and the four transitions he named, one at a time.
        for label, cards in (("a new agent starting",
                              [card("w-one", "running"), card("w-two", "running")]),
                             ("one of them finishing",
                              [card("w-one", "running"), card("w-two", "done")]),
                             ("one being killed",
                              [card("w-one", "failed"), card("w-two", "done")]),
                             ("one leaving the list entirely",
                              [card("w-two", "done")])):
            fired[:] = []
            reads[:] = []
            live[:] = cards
            agents.refresh()
            check("...%s re-reads it, at that moment" % label,
                  len(fired) == 1 and len(reads) == 1, (fired, reads))

        # The poll is the FALLBACK and stays the fallback: the fix must not have
        # turned into "read it more often".
        check("...and the periodic re-read is still the 60s one, untouched",
              usage._poll.interval() == 60000, usage._poll.interval())
    finally:
        bw.cards, ba.agents, ba.pending = real_cards, real_agents, real_pending
        bu.readings = real_readings


def test_undo(tmp):
    """CTRL+Z, the mechanism. [his, 2026-07-29] *"before solomon summons a
    minister, allow the user to crtl+z to stop solomon from doing that ... and
    then insert the prompt back into the prompt box"*.

    The three answers that are NOT a cancellation are the point of most of these
    checks: `boardundo.py` may never tell him it stopped a summon that had
    already gone out, and it may never take two other orders down with one.
    """
    import boardagents as ba
    import boardundo as bun

    m = ba.send("do the thing")
    bun.remember(m)
    mid = ba.msg_id(m)
    check("ctrl+z is offered while the order is still pending",
          (bun.undoable() or {}).get("id") == mid, bun.undoable())
    out = bun.cancel(mid)
    check("...and cancelling it hands his own words back",
          (out["state"], out["text"]) == ("queued", "do the thing"), out)
    check("...it is out of the pending orders",
          "do the thing" not in [x["text"] for x in ba.pending()],
          [x["text"] for x in ba.pending()])
    check("...and nothing was deleted - it rests in cancelled/",
          "do the thing" in [x["text"]
                             for x in ba._list(ba.inbox_dir("cancelled"))])
    check("...so the key stops being offered", bun.undoable() is None)
    check("...and pressing it again says gone rather than cancelling twice",
          bun.cancel(mid)["state"] == "gone")

    # ---- a summoner already holds it, and has not acted yet ----
    m = ba.send("second thing")
    mid = ba.msg_id(m)
    drained = ba.drain()
    bun.remember(m)
    bun.begin_run("orch-2", drained)
    out = bun.cancel(mid)
    check("a summoner that has not acted IS stopped",
          (out["state"], out["text"]) == ("stopped", "second thing"), out)
    check("...and boardctl refuses every write verb it tries after that",
          bun.claim("orch-2") is False)
    check("...and the order is out of taken/, so a dead run cannot revive it",
          ba.requeue_taken("orch-2") == []
          and "second thing" not in [t["text"] for t in ba.taken()],
          [t["text"] for t in ba.taken()])
    check("...and board-watch is told, so it writes no failure note",
          bun.end_run("orch-2") is True)

    # ---- a summoner that has ALREADY acted: nothing is cancelled ----
    m = ba.send("third thing")
    mid = ba.msg_id(m)
    drained = ba.drain()
    bun.remember(m)
    bun.begin_run("orch-3", drained)
    check("the first verb of an uncancelled run is allowed",
          bun.claim("orch-3") is True)
    out = bun.cancel(mid)
    check("...and after it, ctrl+z reports the summon gone",
          (out["state"], out["text"]) == ("summoned", ""), out)
    bun.end_run("orch-3")

    # ---- one order of several: refuse rather than half-cancel ----
    a, b = ba.send("alpha"), ba.send("beta")
    drained = ba.drain()
    bun.remember(a)
    bun.begin_run("orch-4", drained)
    out = bun.cancel(ba.msg_id(a))
    check("one order out of a summoner's several is NOT cancelled",
          (out["state"], out["others"], out["text"]) == ("shared", 1, ""), out)
    check("...and that run may still act on the others",
          bun.claim("orch-4") is True)
    bun.end_run("orch-4")

    # ---- everybody else is untouched by the gate ----
    was = os.environ.get("BOARD_AGENT_ID")
    os.environ["BOARD_AGENT_ID"] = "w1a2b3c"
    check("a minister is never gated by any of this", bun.claim() is True)
    if was is None:
        del os.environ["BOARD_AGENT_ID"]
    else:
        os.environ["BOARD_AGENT_ID"] = was

    # ---- and the gate is real: boardctl itself, in a subprocess ----
    import subprocess
    m = ba.send("fourth thing")
    drained = ba.drain()
    bun.begin_run("orch-5", drained)
    bun.remember(m)
    bun.cancel(ba.msg_id(m))
    path = os.path.join(tmp, "board.md")
    open(path, "w").write(FIXTURE)
    env = dict(os.environ, BOARD_AGENT_ID="orch-5")
    ctl = os.path.join(BOARD, "tools", "boardctl.py")
    for verb, want in (
            (["note", "INFORMATION: **x** - a note nobody asked for"], 4),
            (["dispatch", "do something", "--where", "apps/**"], 4),
            (["inbox", "send", "hello", "--to", "Marbas"], 4),
            (["agents"], 0),
            (["phase", "reading", "--doing", "the file"], 0)):
        p = subprocess.run([sys.executable, ctl, "--board", path, *verb],
                           env=env, capture_output=True, text=True)
        check("boardctl %s -> %s after a ctrl+z"
              % (verb[0], "REFUSED" if want else "allowed"),
              p.returncode == want and (want == 0 or "CANCELLED" in p.stderr),
              (p.returncode, p.stderr[-120:]))
    bun.end_run("orch-5")
    # Nothing reached the board: a cancelled order writes no bullet anywhere.
    check("...and none of the refused verbs wrote a line on the board",
          "a note nobody asked for" not in open(path).read())


def test_undo_window(app, tmp):
    """CTRL+Z, at the window: the key, the box he gets his words back in, and
    the word ORDERS on the section he asked to have renamed."""
    import boardagents as ba
    import boardundo as bun
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest                                   # noqa: E402

    path = os.path.join(tmp, "board.md")
    open(path, "w").write(FIXTURE)
    # EMPTY QUEUE FIRST. Earlier tests in this file send real notes into the
    # same state dir, and this one is about what the list says when it is empty
    # and when it holds exactly one thing.
    ba.drain()
    engine, win, keep = build(app, path)
    agents = keep[5]
    agents.refresh()
    spin(400)

    def shown(text):
        return [it for it in descendants(win.contentItem())
                if str(it.property("text") or "") == text
                and it.property("visible") and it.property("height")]

    check("with nothing pending there is no `pending orders` label",
          shown("pending orders") == [])
    msg = ba.send("make the thing blue")
    bun.remember(msg)
    agents.refresh()
    spin(250)
    # [his, 2026-07-29] *"instead of messages it says orders"*.
    check("the pending list is labelled `pending orders`",
          len(shown("pending orders")) == 1)
    # [his, 2026-07-30] *"pending orders for solomon should be shown at the
    # bottom of the summoner section NOT at the bottom of the triangle"*. An
    # order is waiting on the SUMMONER to pick it up, so it sits under his card
    # — measured by position, because that is what he reads.
    from PySide6.QtCore import QPointF as _QPointF                     # noqa: E402

    def _top(it):
        return it.mapToItem(win.contentItem(), _QPointF(0, 0)).y()

    tri = shown("the triangle")
    check("...at the foot of the SUMMONER section, above the triangle",
          len(tri) == 1
          and _top(shown("pending orders")[0]) < _top(tri[0]),
          (len(tri), _top(shown("pending orders")[0]),
           _top(tri[0]) if tri else None))
    rows = [str(it.property("text")) for it in descendants(win.contentItem())
            if "waiting for the next" in str(it.property("text") or "")]
    check("...and the row calls it an order, not a message",
          rows == ["  order waiting for the next summoner: make the thing blue"],
          rows)

    box = [it for it in descendants(win.contentItem())
           if "type anything" in str(it.property("placeholder") or "")]
    check("found the box at the top", len(box) == 1, len(box))
    check("the key is offered while there is an order to take back",
          agents.property("canUndo") is True)
    # QTest.keyClick, not a hand-built event: a QML `Shortcut` is resolved by the
    # application's shortcut map, which only sees a key delivered through the
    # window system (§11.2's own note about the same trap).
    QTest.keyClick(win, Qt.Key_Z, Qt.ControlModifier)
    spin(300)
    check("ctrl+z took the order out of the pending list", ba.pending() == [],
          [m["text"] for m in ba.pending()])  # the list was drained above
    check("...and put his words back in the box",
          str(prop(box[0], "draft")) == "make the thing blue",
          prop(box[0], "draft"))
    check("...open, so he can edit and send it again",
          prop(box[0], "editing") is True)
    check("...and the footer says what happened",
          "back in the box" in str(prop(win, "status")), prop(win, "status"))
    check("...and the key is not offered any more",
          agents.property("canUndo") is False)

    # WITH THE CARET IN A BOX IT IS TEXT UNDO, not ours (§10.2 the other way
    # round: a shortcut that fired mid-sentence would eat the undo he meant).
    msg = ba.send("second order")
    bun.remember(msg)
    agents.refresh()
    spin(250)
    ed = [it for it in descendants(box[0])
          if it.property("cursorPosition") is not None]
    check("the box's editor is the one item with a caret", len(ed) == 1, len(ed))
    ed[0].forceActiveFocus()
    spin(120)
    check("...and the window knows he is typing in it",
          prop(win, "inAnEditor") is True)
    QTest.keyClick(win, Qt.Key_Z, Qt.ControlModifier)
    spin(250)
    check("ctrl+z does NOT cancel an order while his caret is in a field",
          [m["text"] for m in ba.pending()] == ["second order"],
          [m["text"] for m in ba.pending()])
    # A DRAFT ALREADY IN THE BOX SURVIVES the restore — nothing this app does
    # throws away a sentence he typed.
    ed[0].setProperty("focus", False)
    win.contentItem().forceActiveFocus()
    win.setProperty("drafts", {"msg:queue": "half of another thought"})
    spin(120)
    QTest.keyClick(win, Qt.Key_Z, Qt.ControlModifier)
    spin(250)
    check("a cancelled order lands ABOVE a draft rather than over it",
          str(prop(box[0], "draft")) == "second order\nhalf of another thought",
          prop(box[0], "draft"))
    check("...and the footer says that is what happened",
          "above the draft" in str(prop(win, "status")), prop(win, "status"))

    # A REPLY TO A CHORE takes the same `send()` and is NOT an order: it also
    # cleared a bullet, and undoing one half of that pair into the wrong box is
    # not an undo (`Agents.notAnOrder`, called by `replyToTodo`).
    bun.remember(ba.send("a reply-shaped sentence"))
    agents.refresh()
    spin(150)
    check("a reply is claimed by nothing until it is un-claimed",
          agents.property("canUndo") is True)
    agents.notAnOrder()
    spin(120)
    check("...and ctrl+z stops claiming what was a reply, not an order",
          agents.property("canUndo") is False)
    shot(win, "07-pending-orders")


def test_card_output(tmp):
    """What the card's drawer tails, and in which order it prefers them.

    The `.log` is written once, at exit, so preferring it is what made the
    drawer read "nothing logged yet" for the whole of every run. The transcript
    is appended to as the agent works and is therefore the live source; the log
    is the fallback for after it, when there is no more transcript.
    """
    import main as brd
    import boardagents as ba
    import boardwork as bw
    import boardphase as bph
    print("\n=== the card drawer shows real live output ===")
    os.environ["BOARD_TRANSCRIPTS"] = os.path.join(tmp, "transcripts")
    agents = brd.Agents.__new__(brd.Agents)      # no Qt, no polling: one method

    ba.register("w-live", "T", 1, kind="worker", where="apps/x/**",
                session="ses-live")
    d = os.path.join(tmp, "transcripts", "-proj")
    os.makedirs(d, exist_ok=True)
    tsc = os.path.join(d, "ses-live.jsonl")

    def say(*parts):
        with open(tsc, "a") as f:
            f.write(json.dumps({"type": "assistant",
                                "message": {"role": "assistant",
                                            "content": list(parts)}}) + "\n")

    # An empty log, which is what a running worker's really looks like.
    open(bw._log_path("w-live"), "w").close()
    check("no transcript and an empty log is honestly nothing",
          agents.output("w-live") == [], agents.output("w-live"))

    # LITERAL, not a summary of it — [his, 2026-07-30] *"its literal actual
    # thinking / tool call / coding output"*. Every line of the real payload.
    say({"type": "thinking", "thinking": "the seed drift is\nthe suspect"})
    say({"type": "tool_use", "name": "Edit",
         "input": {"file_path": "/a/b/Main.qml", "new_string": "visible: true"}})
    check("a running agent's own thinking and tool ARGUMENTS are the drawer",
          agents.output("w-live") == ["Edit /a/b/Main.qml", "new_string:",
                                      "visible: true"],
          agents.output("w-live"))

    # ...and it keeps up: the next poll sees what was appended since.
    say({"type": "tool_use", "name": "Bash",
         "input": {"command": "git push", "description": "Push to main"}})
    check("...and a Bash call is the COMMAND, not a description of it",
          agents.output("w-live")[-1] == "$ git push", agents.output("w-live"))

    # A tool RESULT rides on a `user` entry and is the one thing in one that is
    # the agent's log rather than his words.
    with open(tsc, "a") as f:
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "content": "3 files changed\n1 insertion"}]}}) + "\n")
    check("...and the tool's own OUTPUT lands in the log under it",
          agents.output("w-live")[-2:] == ["3 files changed", "1 insertion"],
          agents.output("w-live"))

    # Only the last few, however long it ran.
    for i in range(8):
        say({"type": "text", "text": "line %d" % i})
    check("...trimmed to the couple of lines the drawer can carry",
          agents.output("w-live") == ["line 5", "line 6", "line 7"],
          agents.output("w-live"))

    # A tool RESULT is a whole file's contents in somebody else's voice, and a
    # user turn is his own prompt read back at him. Neither is the agent.
    with open(tsc, "a") as f:
        f.write(json.dumps({"type": "user", "message": {
            "role": "user", "content": [{"type": "text", "text": "HIS PROMPT"}]}}) + "\n")
    check("...and his own prompt read back is NOT the agent's output",
          "HIS PROMPT" not in agents.output("w-live"), agents.output("w-live"))

    # After the run: no transcript at all, and the log finally has the output.
    ba.register("w-done", "T", 1, kind="worker", where="apps/x/**",
                session="ses-gone")
    with open(bw._log_path("w-done"), "w") as f:
        f.write("\x1b[32mfinished\x1b[0m\nlast word\n")
    check("a finished worker with no transcript falls back to its log",
          agents.output("w-done") == ["finished", "last word"],
          agents.output("w-done"))
    # ---- a card with nothing to say yet RISES; it is never withheld ----
    # [his, 2026-07-31] *"instead of hiding the card ... '[agent] arises...'
    # with an animated elipsies ... nothing else until the agent card actually
    # starts producing stuff"*. This replaced `speaks`, whose withheld state was
    # exactly the one a wedged minister sat in, invisibly, for 45 minutes.
    ba.register("w-hush", "T", os.getpid(), kind="worker", where="apps/x/**",
                session="ses-never")          # linked, transcript never appears
    by_id = {a["id"]: a for a in ba.agents()}
    check("a running agent that has neither claimed nor been seen RISES",
          by_id["w-hush"]["arising"] is True, by_id.get("w-hush", {}).get("arising"))
    check("...and the rising line names it and ends in three ASCII dots",
          by_id["w-hush"]["saysLine"]
          == "%s arises..." % (by_id["w-hush"]["name"] or "it"),
          by_id.get("w-hush", {}).get("saysLine"))
    check("...and it is the WHOLE card - no observed line, no metadata",
          by_id["w-hush"]["doingLine"] == ""
          and by_id["w-hush"]["saysDetail"] == "",
          (by_id["w-hush"]["doingLine"], by_id["w-hush"]["saysDetail"]))
    check("...while one whose transcript already shows work is not rising",
          by_id["w-live"]["arising"] is False, by_id.get("w-live", {}).get("arising"))
    bph.claim("w-hush", "researching", "the vtbclient parser")
    by_id = {a["id"]: a for a in ba.agents()}
    check("...and its first phase ends the rising, nothing else changed",
          by_id["w-hush"]["arising"] is False and by_id["w-hush"]["saysLine"],
          by_id.get("w-hush", {}).get("saysLine"))
    ba.unregister("w-hush")

    # AND IT DOES NOT RISE FOREVER. Past `START_GRACE_S` with an empty
    # transcript the observation is `silent`, and the card stops claiming it is
    # on its way and says plainly that it never started — the whole point of the
    # change being that a wedged minister is VISIBLE, not that it looks tidy.
    # An EMPTY transcript that exists is the wedged shape: a file was opened and
    # not one entry was ever written to it. (A session id with no file at all is
    # the other failure, `unlinked`, and has its own sentence.)
    open(os.path.join(d, "ses-wedged.jsonl"), "w").close()
    ba.register("w-wedged", "T", os.getpid(), kind="worker", where="apps/x/**",
                session="ses-wedged")
    old_grace = bph.START_GRACE_S
    try:
        bph.START_GRACE_S = -1                # everything is instantly past it
        by_id = {a["id"]: a for a in ba.agents()}
        check("a minister wedged past the grace stops rising and says so",
              by_id["w-wedged"]["arising"] is False
              and "not started" in by_id["w-wedged"]["doingLine"],
              (by_id["w-wedged"]["arising"], by_id["w-wedged"]["doingLine"]))
    finally:
        bph.START_GRACE_S = old_grace
    ba.unregister("w-wedged")

    # ---- FINISHED is not ABANDONED ----
    # [his, 2026-07-30] a worker that had completed its task sat on the board
    # proclaiming `exited without finishing - nothing was committed on its
    # behalf`, greyed and with no accent gutter. `reap()` always knew better;
    # the card did not, until it was given the same fact.
    dead = os.fork()
    if dead == 0:
        os._exit(0)
    os.waitpid(dead, 0)
    ba.register("w-quit", "T", dead, kind="worker", where="apps/x/**")
    ba.register("w-fin", "T", dead, kind="worker", where="apps/x/**")
    bw.mark_reported("w-fin", "it said what it did")
    by_id = {a["id"]: a for a in ba.agents()}
    check("a stopped worker that reported is drawn as FINISHED",
          by_id["w-fin"]["finished"] is True
          and "finished" in ba.describe(by_id["w-fin"]),
          ba.describe(by_id.get("w-fin", {})))
    check("...and one that simply stopped is still abandoned, in words",
          by_id["w-quit"]["finished"] is False
          and "without finishing" in ba.describe(by_id["w-quit"]),
          ba.describe(by_id.get("w-quit", {})))
    check("...and neither claim is made about a worker still running",
          by_id["w-live"]["finished"] is False)
    ba.unregister("w-quit")
    ba.unregister("w-fin")

    # The registrations are in the ONE shared state dir every later test reads,
    # and two strangers in the agents list is enough to fail the window's own
    # "with nothing running" checks. Take them back out.
    ba.unregister("w-live")
    ba.unregister("w-done")
    del os.environ["BOARD_TRANSCRIPTS"]


def _hermes_db(path):
    """A synthetic `~/.hermes/state.db` with the columns this reads.

    The real schema is hermes's and much wider; what is asserted here is that
    the reader finds a run by its query, follows it live and never touches his
    own store — `BOARD_HERMES_DB` is what keeps the test off it.
    """
    import sqlite3
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL,
                               model TEXT, started_at REAL NOT NULL);
        CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT,
                               session_id TEXT NOT NULL, role TEXT NOT NULL,
                               content TEXT, tool_calls TEXT, tool_name TEXT,
                               reasoning_content TEXT, timestamp REAL NOT NULL);
    """)
    con.commit()
    return con


def _hsession(con, sid, query, at):
    con.execute("INSERT INTO sessions (id, source, model, started_at)"
                " VALUES (?, 'tool', 'deepseek/x', ?)", (sid, at))
    con.execute("INSERT INTO messages (session_id, role, content, timestamp)"
                " VALUES (?, 'user', ?, ?)", (sid, query, at))
    con.commit()


def _hcall(con, sid, name, args, at=0.0):
    con.execute("INSERT INTO messages (session_id, role, tool_calls, timestamp)"
                " VALUES (?, 'assistant', ?, ?)",
                (sid, json.dumps([{"type": "function",
                                   "function": {"name": name,
                                                "arguments": json.dumps(args)}}]),
                 at))
    con.commit()


def test_hermes(tmp):
    """A MINISTER ON THE OTHER RUNTIME IS WATCHED THE SAME WAY.

    Hermes has no `--session-id` and no transcript file, so until 2026-07-31 a
    hermes minister's card was claim-only and its log pointed at a
    `~/.claude/projects/*.jsonl` that was never written. The run is bound by a
    hash of the query hermes stores verbatim instead; everything downstream —
    the observed phase, the drawer, the confirmation of the summon — has to
    reach the same answers it reaches for a Claude worker, out of a database.
    """
    import boardhermes as bhx
    import boardphase as bph
    import boardagents as ba
    import boardwork as bw
    import main as brd
    print("\n=== a hermes minister is observed out of hermes's own store ===")
    db = os.path.join(tmp, "state.db")
    os.environ["BOARD_HERMES_DB"] = db
    con = _hermes_db(db)
    now = time.time()

    q = "You are running headless...\n--- your task ---\nDRAW THE PANEL\n"
    check("nothing is bound before the run exists",
          bhx.resolve(bhx.fingerprint(q), now) == "")

    # ARMED at the spawn, from the argv the backend built — the same call
    # `boardwork._spawn_worker` and board-watch's `spawn` both make.
    argv = bw.HermesBackend().args(prompt=q, session=None, role="worker",
                                   label="board: x")
    bw.HermesBackend().arm("h-one", argv)
    sent = argv[argv.index("-q") + 1]
    check("the query the backend actually sends is what the run is keyed on",
          bph.read_sidecar("h-one").get("probe") == bhx.fingerprint(sent))

    r = bph.observe("h-one")
    check("an armed spawn whose session has not opened yet is STARTING",
          r["observed"] == "starting" and bph.actually(r) == "nothing yet", r)

    # ...and hermes opens it. A DIFFERENT run started a moment earlier must not
    # be mistaken for it: the fingerprint is the key, not the clock.
    _hsession(con, "20260731_1_aaa", "somebody else's prompt", now - 1)
    _hsession(con, "20260731_2_bbb", sent, now + 1)
    r = bph.observe("h-one")
    check("the run is found by ITS OWN query, not by whatever started nearby",
          bph.read_sidecar("h-one").get("hsession") == "20260731_2_bbb",
          bph.read_sidecar("h-one").get("hsession"))
    check("...and a bound-but-idle minister says nothing yet, like any other",
          r["observed"] == "none", r["observed"])
    check("...and that binding is the proof its summon completed",
          ba._confirmed({"id": "h-one", "confirmed": False}, False) is True)

    # THE OBSERVED LINE, in the SAME vocabulary a Claude worker's is in.
    _hcall(con, "20260731_2_bbb", "read_file", {"path": "/a/b/Theme.qml"}, now)
    r = bph.observe("h-one")
    check("a hermes read_file reads as researching, and says the file",
          r["phase"] == "researching" and r["doing"] == "reading Theme.qml",
          (r["phase"], r["doing"]))
    _hcall(con, "20260731_2_bbb", "patch",
           {"path": "/a/b/Bar.qml", "old_string": "a", "new_string": "b"}, now)
    r = bph.observe("h-one")
    check("...a patch is EDITING, in our word for it",
          r["phase"] == "coding" and r["doing"] == "editing Bar.qml",
          (r["phase"], r["doing"]))
    _hcall(con, "20260731_2_bbb", "terminal",
           {"command": "git commit -m x -- a"}, now)
    r = bph.observe("h-one")
    check("...and a terminal call is classified by what it RAN",
          r["phase"] == "finishing", r["phase"])
    _hcall(con, "20260731_2_bbb", "process", {"action": "list"}, now)
    r = bph.observe("h-one")
    check("...a hermes tool we have no word for keeps its own name",
          r["doing"] == "using process", r["doing"])
    check("...and claims no phase, so the window still reads the real work",
          r["phase"] == "finishing", r["phase"])

    # ONLY WHAT IS NEW, poll to poll — the rowid is the byte offset's analogue.
    before = bph.read_sidecar("h-one").get("offset")
    r = bph.observe("h-one")
    check("a poll with nothing new advances nothing and changes nothing",
          bph.read_sidecar("h-one").get("offset") == before
          and r["doing"] == "using process")

    # THE DRAWER: literal output, out of the database, newest at the tail.
    agents = brd.Agents.__new__(brd.Agents)
    ba.register("h-one", "T", 1, kind="worker", where="", session="")
    con.execute("INSERT INTO messages (session_id, role, content, timestamp)"
                " VALUES (?, 'tool', ?, ?)",
                ("20260731_2_bbb",
                 json.dumps({"output": "3 files changed\n1 insertion",
                             "exit_code": 0}), now))
    con.commit()
    check("a tool RESULT is its own output, unwrapped from the json",
          agents.output("h-one")[-2:] == ["3 files changed", "1 insertion"],
          agents.output("h-one"))
    con.execute("INSERT INTO messages (session_id, role, content, timestamp)"
                " VALUES (?, 'user', 'HIS PROMPT', ?)", ("20260731_2_bbb", now))
    con.commit()
    check("...and his own prompt read back is NOT the minister's output",
          "HIS PROMPT" not in agents.output("h-one"), agents.output("h-one"))
    _hcall(con, "20260731_2_bbb", "terminal", {"command": "hyprctl layers"}, now)
    check("...and a terminal call is the command, the same as a Bash one",
          agents.output("h-one")[-1] == "$ hyprctl layers",
          agents.output("h-one"))

    # WHERE TO READ THE WHOLE RUN. The log header is written before the session
    # exists, so it names the store; once bound it names the run itself, and
    # NEITHER of them is ever a `~/.claude/projects` path (the 2026-07-31 bug).
    hint = bw.HermesBackend().history_hint("h-one", None)
    check("a bound run is pointed at by the command that prints it",
          hint == "hermes sessions export 20260731_2_bbb", hint)
    check("...and an unbound one names the store rather than a file that is not there",
          ".claude" not in bw.HermesBackend().history_hint("h-none", None),
          bw.HermesBackend().history_hint("h-none", None))

    # A RETRY runs the same prompt again under the same agent id. The dead
    # session must not go on being read as the live one.
    bw.HermesBackend().arm("h-one", argv)
    check("re-arming drops the session bound to the run that died",
          not bph.read_sidecar("h-one").get("hsession")
          and bph.read_sidecar("h-one").get("offset") == 0,
          bph.read_sidecar("h-one"))
    _hsession(con, "20260731_3_ccc", sent, time.time() + 1)
    bph.observe("h-one")
    check("...and the retry binds to the LATER session with the same query",
          bph.read_sidecar("h-one").get("hsession") == "20260731_3_ccc",
          bph.read_sidecar("h-one").get("hsession"))

    con.close()
    ba.unregister("h-one")
    del os.environ["BOARD_HERMES_DB"]


def main():
    from PySide6.QtGui import QGuiApplication
    global SHOTS
    if "--shots" in sys.argv:
        SHOTS = os.path.abspath(sys.argv[sys.argv.index("--shots") + 1])
        os.makedirs(SHOTS, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["XDG_STATE_HOME"] = os.path.join(tmp, "state")
        # ...and the WORKER LOGS with it (`boardwork._log_path`). Without this
        # every worker a dispatch test spawns left an empty log in his real
        # `~/.cache/board-work/`, which is the directory an agent reads to find
        # out what actually ran (2026-07-29: 682 of 714 files there were debris
        # from these two harnesses).
        os.environ["XDG_CACHE_HOME"] = os.path.join(tmp, "cache")
        os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp, "config")
        # ...and THE CALLER'S OWN AGENT ENVIRONMENT. An agent running this
        # harness has `BOARD_ORDER` (his sentence), `BOARD_AGENT_ID` and the
        # rest exported into it, and the writers read them: every bullet written
        # here then carried a `<!-- for: -->` stamp the fixtures do not expect,
        # and seven checks failed for whoever ran it from a worker while passing
        # from a plain shell. The env is an input; a test must supply it.
        for k in ("BOARD_ORDER", "BOARD_AGENT_ID", "BOARD_WORK_SESSION",
                  "BOARD_WORK_TASK", "BOARD_WATCH_KEY", "BOARD_FILE",
                  "BOARD_WORK_SPAWN", "BOARD_MAX_WORKERS", "BOARD_TRANSCRIPTS",
                  "BOARD_HERMES_DB"):
            os.environ.pop(k, None)
        os.makedirs(os.path.join(tmp, "rt"))
        os.makedirs(os.path.join(tmp, "mv"))
        os.makedirs(os.path.join(tmp, "win"))
        test_roundtrip(os.path.join(tmp, "rt"))
        test_moves(os.path.join(tmp, "mv"))
        os.makedirs(os.path.join(tmp, "ld"))
        test_landed(os.path.join(tmp, "ld"))
        os.makedirs(os.path.join(tmp, "ls"))
        test_landed_view(os.path.join(tmp, "ls"))
        os.makedirs(os.path.join(tmp, "lw"))
        test_landed_window(os.path.join(tmp, "lw"))
        os.makedirs(os.path.join(tmp, "lup"))
        test_landed_upgrade(os.path.join(tmp, "lup"))
        os.makedirs(os.path.join(tmp, "tg"))
        test_todo_tags(os.path.join(tmp, "tg"))
        os.makedirs(os.path.join(tmp, "sum"))
        test_summon_cleared(os.path.join(tmp, "sum"))
        os.makedirs(os.path.join(tmp, "pl"))
        test_placed(os.path.join(tmp, "pl"))
        os.makedirs(os.path.join(tmp, "by"))
        test_by(os.path.join(tmp, "by"))
        os.makedirs(os.path.join(tmp, "td"))
        test_todo_remove(os.path.join(tmp, "td"))
        test_agents(tmp)
        test_phase(tmp)
        os.makedirs(os.path.join(tmp, "un"))
        test_undo(os.path.join(tmp, "un"))
        os.makedirs(os.path.join(tmp, "work"))
        test_work(os.path.join(tmp, "work"))
        test_overlap(os.path.join(tmp, "work"))
        test_dead_worker_notes(os.path.join(tmp, "work"))
        test_finished_leaves(os.path.join(tmp, "work"))
        os.makedirs(os.path.join(tmp, "conf"))
        test_summon_confirmed(os.path.join(tmp, "conf"))
        os.makedirs(os.path.join(tmp, "use"))
        test_usage(os.path.join(tmp, "use"))
        os.makedirs(os.path.join(tmp, "usf"))
        test_usage_fetch(os.path.join(tmp, "usf"))
        os.makedirs(os.path.join(tmp, "out"))
        test_card_output(os.path.join(tmp, "out"))
        os.makedirs(os.path.join(tmp, "herm"))
        test_hermes(os.path.join(tmp, "herm"))
        app = QGuiApplication(sys.argv)
        test_usage_follows_agents(app)
        test_real_store()
        test_real_window(app)
        test_window(app, os.path.join(tmp, "win"))
        os.makedirs(os.path.join(tmp, "plw"))
        test_placed_window(app, os.path.join(tmp, "plw"))
        os.makedirs(os.path.join(tmp, "unw"))
        test_undo_window(app, os.path.join(tmp, "unw"))
    print()
    if FAILS:
        print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
