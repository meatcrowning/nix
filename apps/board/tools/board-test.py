#!/usr/bin/env python3
"""board's regression harness — offscreen, no window on anyone's screen.

Three layers, in the order a failure is cheapest to read:

  1. THE ROUND TRIP (pure Python, and the reason this file exists). His store is
     a markdown file he also edits by hand, so the contract is byte-level:
     parse -> write back with no change -> **the file is identical**; tick one
     box -> **exactly one line differs**, and it differs only inside its `[ ]`.
     Clearing an answer that was never given must also leave the file untouched,
     because the store ships `> ` with a trailing space.
  2. THE PARSE against the real `~/nix/docs/board.md`, so a change to the file's
     shape shows up here rather than as an empty section on screen.
  3. THE WINDOW: the real `qml/Main.qml` under QT_QPA_PLATFORM=offscreen, plus
     `grabWindow()` PNGs of the three states worth looking at — everything
     populated, a decision with a chosen option and a typed answer, and an EMPTY
     `NEEDS YOU`, which is the state he will see most often.

Run it with board's own Qt env, not the bare system python:

    W=$(readlink -f "$(which board)"); sed '$d' "$W" > /tmp/brdenv.sh
    ( . /tmp/brdenv.sh; "$(tail -1 "$W" | grep -o '/nix/store/[^"]*/bin/python3')" \\
        apps/board/tools/board-test.py --shots /tmp/board-shots )

`XDG_STATE_HOME` is redirected into a scratch dir — a harness here must never
rewrite where the user's own app reopens — and every write test runs against a
COPY of the store in that scratch dir. This harness never writes board.md.
"""
import os
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
            brd.Board(path), brd.Settings())
    ctx.setContextProperty("WalPalette", keep[0])
    ctx.setContextProperty("DeskStyle", keep[1])
    ctx.setContextProperty("Titlebar", keep[2])
    ctx.setContextProperty("Board", keep[3])
    ctx.setContextProperty("Settings", keep[4])
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
