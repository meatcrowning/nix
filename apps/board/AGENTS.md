# `goetia` — what needs him, what is moving, what landed

**The program is called Goetia** (lowercase `goetia` in the window title, the
desktop entry and the binary, like every other app here). Only the presentation
carries the name: the store it reads and writes is still the board — since
2026-07-30 one file PER MACHINE, `docs/board.top.md` on `top` and
`docs/board.book.md` on `book`, never merged (`guide/store.md`) — and
every path and identifier is still `board*` — this directory, `boardctl.py`,
`board.nix`, `board-watch`, `~/.local/state/board/`, the `Board` context
property. Renamed 2026-07-29, his call; the prose here goes on calling the FILE
"the board", because that is what it is.

Vendored source of the decision board: `main.py`, `boardparse.py`, `boardmove.py`,
`boardagents.py`, `boardwork.py`, `boardphase.py`, `boardhermes.py`,
`boardusage.py`, `boardundo.py` and `qml/`. (`boardhermes.py` is the second
runtime's half of `boardphase`: a minister spawned on hermes has no transcript
file, so its card and its drawer are read out of hermes's own session store —
see `guide/cards.md`.)
Built and installed by `home/prog/board.nix`, which mirrors `reader.nix` exactly
(including the `air` system-python split) and runs the **live** source at
`/home/lam/nix/apps/board/main.py`, so `.py`/`.qml` edits need no rebuild. See
[`../AGENTS.md`](../AGENTS.md) for the rules shared by all eight apps, and
`~/nix/docs/DESIGN.md` before you draw anything.

```bash
goetia                      # ~/nix/docs/board.<hostname>.md, this host's own
goetia /path/to/other.md    # any file with the same shape
```

## The word he reads for an agent is MINISTER

[his, 2026-07-29] *"ANYTHING that could refer to an agent where the user can see
should use minister instead"*. So every string he can read — goetia's own labels,
placeholders and framing prose, the cap dropdown (`4 ministers`), everything
`boardctl.py` prints back at him, and every template that writes a line into
the board, `board-watch.py`'s included — says **minister** / **ministers**,
never *agent* or *worker*.

**Identifiers do not move.** `kind="worker"`, `board-worker-*.service`,
`boardctl.py agents`, the `agents` section id, `~/.cache/board-work/`, the socket
keys and every log line stay exactly as they are: renaming running state buys
nothing and breaks what is already on disk — the same rule that kept every path
`board*` when the app itself became `goetia`.

The section they sit in is drawn as **the triangle** (id still `agents`), under
Solomon's own **summoner** section: the magician stands in the circle and the
spirits are bound in the triangle.

**A length is not free.** These templates are wrapped when they are written, and
*minister* is three characters longer than *agent* — `board-watch.py`'s
`FAIL_TEMPLATE` had to give three characters back elsewhere in the sentence or
the write re-wrapped lines around it (`tools/board-watch-test.py` catches that).

## Where the rest of this guide is

This file is the map. **The detail lives in six files under `guide/`, and you
read the one your change lands in — not all of them.** It was one 2,598-line
file until 2026-07-30, which was past `Read`'s 2,000-line cap: an agent that
opened it paid ~44k tokens *and* silently got a truncated guide. Every heading
of every part is listed below, so `grep` still finds the section from here.

**Read the part, then grep it.** Nothing under `guide/` is small enough to
swallow whole for one change.

### [`guide/store.md`](guide/store.md) — the STORE — `docs/board.<host>.md` and how anything writes to it

513 lines. Its sections:

  - It is a GUI over ONE file, and that file is not this app's to redesign
    - The store's shape
  - NEEDS YOU              decisions, `### <n>. <title>` each
  - WAITING ON YOU TO DO   `- <TAG>: ` bullets. Actions, not decisions, each
  - LANDED                 `### <date>` groups of | commit | what | when |,
    - Every WAITING bullet says WHAT IT IS in its first word
    - ONE BOARD ITEM PER ASK
    - ...and the tag is what the bullets are grouped by on screen
    - Everything under NEEDS YOU says WHEN it was put there
    - ...and WHO put it there, on the line above the time
    - ...and WHICH OF HIS ASKS it came out of
  - The no-pressure requirement is a design constraint
  - Answering here now STARTS something
    - ...and the item MOVES when it does

### [`guide/orchestrator.md`](guide/orchestrator.md) — the ORCHESTRATOR half (`boardwork.py`) — spawning, the cap, the handoff

733 lines. Its sections:

- ...and the orchestrator's half (`boardwork.py`)
  - The box at the top: this window STARTS things now
    - The three cost levers are their own part (-> `cost.md`)
    - The concurrency cap, and what is above it
    - A NEW WORKER IS NOT THE ONLY ANSWER: handing an item to one already in those files
    - What the orchestrator and its workers are told, beyond the board
    - What each spawn STARTS WITH, before it reads a line
    - The one thing that could hold the whole system up, and does not
    - The deepseek subminister: a Claude minister OR the orchestrator delegates a chunk
    - A DISPATCH IS A START, NOT A RESULT
    - ...and the summon note GOES when the result arrives

### [`guide/cost.md`](guide/cost.md) — what a RUN COSTS — the batch, the tier, the relay

106 lines. Its sections:

  - A BURST IS ONE PLANNING PROBLEM: the coalescing window
  - WHICH TIER a minister runs on, per piece of work
  - The RELAY: a minister hands the rest on rather than running long

### [`guide/cards.md`](guide/cards.md) — the TRIANGLE — what a minister's card says

559 lines. Its sections:

  - The `agents` section: the only part of this window that is NOT the store
    - A SUMMON IS NOT A CARD until the agent is really up
    - A worker has a name, and the name is what he reads
    - ...and the orchestrator's name is SOLOMON, always, and it is pinned
    - A card says what the agent CLAIMS and what it is OBSERVED doing — both
    - A card is WITHHELD until its top line is a real sentence
    - ...and clicking the card opens what it is ACTUALLY SAYING

### [`guide/controls.md`](guide/controls.md) — the CONTROLS — the box, the four dropdowns, the usage meter, ctrl+z

452 lines. Its sections:

    - The box, and the promise it can honestly make
    - FOUR dropdowns beside the box, and the order is his
    - 1. How many summoners plan at once
    - 2. The dropdown beside the box: which model, and how hard, summons
    - 3. ...and under THAT, how many agents may run at once
    - 4. ...and under that, what the MINISTERS run on — CAPPED
    - ...and under that, how much of his usage is gone
    - Second thoughts about something still queued
    - Ctrl+Z takes the last order back — and it is a real cancellation

### [`guide/drawing.md`](guide/drawing.md) — what it DRAWS, and why it looks like that

352 lines. Its sections:

  - Never clobber him — four defences
  - What it draws, and why it looks like that
    - Clearing a chore: the one thing in this app that DELETES his prose
    - Chrome: the hyprvtb titlebar (§12, §7.4)
    - A usage meter is a BUTTON, and its tooltip is a countdown
  - Recorded limit: the store quotes glyphs the font lacks

## Verify

```bash
# on `top`, where the wrapper carries the Qt env:
# the binary is `goetia`; there has never been one called `board` (the NAME is
# the only thing that was renamed - every path and identifier is still board*)
W=$(readlink -f "$(command -v goetia)"); sed '$d' "$W" > /tmp/brdenv.sh
( . /tmp/brdenv.sh; "$(tail -1 "$W" | grep -o '/nix/store/[^"]*/bin/python3')" \
    apps/board/tools/board-test.py --shots /tmp/board-shots )

# on `book`, where it does NOT — run the harness under the system python
# directly. **Do not source the wrapper there**: its `air` split is two lines,
# a shebang and an `exec`, so `sed '$d'` leaves the exec and sourcing it
# LAUNCHES BOARD on his screen. It has happened.
/usr/bin/python3 apps/board/tools/board-test.py --shots /tmp/board-shots
```

`tools/board-test.py`, offscreen, eleven layers. Five of them are
new and are the ones to read first if the fan-out misbehaves:

- **the tags** (`test_todo_tags`) — a writer that emits an untagged bullet
  **FAILS**, and writes nothing: no tag, a lowercase one, a word that is not in
  the set, no space after the colon, a tag with no description behind it, and a
  multi-line note whose second line forgot one. Every tag in the set has a
  writer that can emit it; `stall` and `reconcile` carry theirs; every
  `board-watch.py` failure template says `FAILED:` (checked as SOURCE — that
  file is deployed by home-manager, so the copy that runs on a machine is the
  last one a rebuild put there); and an old untagged bullet still parses, draws,
  removes and restores.

  **And one board item per ask**: each of the five bundled shapes is refused and
  writes nothing, a headline that merely names one ("the third item") is not,
  several tagged lines land as several bullets with a stamp each, `boardctl`
  splits its argv at each tag, a bullet quoting a hostile line of his survives
  every check with his words intact inside the code span, and both prompts still
  carry the rule in the words the refusal uses.

- **the summon note dies with its result** (`test_summon_cleared`) — a worker's
  `ENACTED:`/`PARTIAL:`/`FAILED:` takes its own `SUMMONED <Name> (`<id>`)`
  note with it — and a `COMMANDED <Name>` handoff note the same way, the
  lowercase verbs and the `INFORMATION: ... SUMMONED:` shape they replaced
  included — whole,
  stamp and wrapped lines included, and takes **nothing**
  else: not another worker's summon note, not a `QUESTION:`, not a plain
  `INFORMATION:` fact, not a result from a different id or from nobody. Two
  notes naming one id leave both, an id-less note falls back to the name, and
  board-watch's dead-worker note is checked (as source) to pass the id.

- **LANDED** (`test_landed`) — a commit records with no selector at all (the
  bug that made the section look frozen), the time comes from git rather than
  from now, a hash that resolves nowhere is simply timeless, a two-cell row still
  parses, and the header widens exactly once when an old group gains its first
  timed row.

- **what an agent says vs what it does** (`test_phase`) — the classifier per
  tool, that reading is not a phase of its own, tailing by byte offset, half a
  line at the end of a live transcript, an agent with no session saying so
  rather than guessing, a stalled one saying `nothing recently` **with no
  elapsed time in it**, and the divergence itself: a claim is recorded, drawn,
  and does **not** move the card.
- **the fan-out** (`test_work`) — dispatch runs up to the cap and queues the
  rest; every dispatched task is on disk exactly once in exactly one directory;
  queued work is drawn rather than hidden and is not offered an inbox it has no
  process for; a killed worker stops holding a slot and `promote()` starts the
  queue oldest-first; **every worker has a name** that is unique among the
  living, persisted in its record rather than re-derived per poll, ASCII, and
  absent on a task nobody is on yet; a dead agent is filed under `stopped`
  **whatever it last claimed** and the sweep then drops its record; `ask`
  refuses without `--if-unanswered` and writes nothing, then lands as an ordinary numbered
  decision with all four parts and no robot flag; and the board-watch seed.

The other six: **the round trip** (pure Python
— byte-identity, one-line edits, the radio, the `> ` marker preserved on a
clear, the atomic write), **removing a chore** (`test_todo_remove`: a wrapped
bullet loses both its lines and no other line changes at all, the undo restores
the file byte-for-byte from the first, a middle and the LAST position, the
section empties completely and an agent can still add to it afterwards, and a
stale line index is refused rather than obeyed; a DOUBLE click on the real
delegate removes one and a single left click does not, driven with `QTest`; and
`reply` is the top entry on that row's menu, opening the row's own box, sending
down the queue with his sentence leading and the chore quoted after it, and
clearing the answered bullet off the list — restorably, against a stale line
index, and removing nothing when the chore has already gone), **the moves**
(start/land/back/note/reconcile: every
decision's start -> back is byte-identical, a start writes nothing in the
decision's place and an old `## IN FLIGHT` section is left byte-identical
through a whole start/land cycle, an unanswered decision is refused, a
dead owner is reclaimed, and an edit computed from stale bytes is retried rather
than landed), **the agents** (a live agent, a dead one and a hand-moved one are
told apart by `boardmove`'s own liveness rule; and every path the box takes is a
CONSERVATION check — after each one his message is on disk exactly once, in
exactly one of the three directories, whether it was read, escalated or
drained), **the real store** (it parses, every decision has a
title, an `if unanswered` line and somewhere to write an answer, and the font
audit above), and **the window** — the real `qml/Main.qml` under
`QT_QPA_PLATFORM=offscreen`, including the stale-write refusal, an external edit
appearing without a relaunch, **all three sections redrawing when an item moves
between them — with his scroll position and his half-typed draft kept**, a store
replaced by rename (a sync, a `git checkout`) still reloading, a section
emptying out completely, **a running agent and a failed one drawn differently
and a finished one leaving the list**, **the one box at the top being the only
un-attached one on the page and what he types into it landing in the queue
exactly once**, **the cards as one flat list with no phase sections in it,
oldest first and the same order on the next poll, each reading as two sentences
led by the agent's name, a stopped one never in the present tense, and no time,
age, birth or count anywhere on them**, and
`grabWindow()` PNGs with `--shots`:
the real store, the fixture populated, a decision answered, an EMPTY `NEEDS
YOU`, an EMPTY agents section (with `/proc` stubbed away, since the process
running the harness is itself under a Claude session), the agents section
populated, a 420x600 window, and an unreadable store. It redirects
`BOARD_TRANSCRIPTS` at a synthetic transcript tree — a harness here must **never**
write into `~/.claude`, which syncs to book — and `XDG_STATE_HOME` into a
scratch dir (a harness here **must**, or it rewrites his own app's state), works
on a COPY of the store for every write, and stubs the Titlebar, because the real
one registers buttons against the harness's pid in the live compositor. It also
exports **`BOARD_USAGE_OFFLINE=1`**, which makes `boardusage.fetch()` and
`nudge()` no-ops: `Usage` fetches the account's live figures on a worker thread
from its constructor, so without that switch every test that builds one would
reach the network and write his real
`~/.local/state/board/usage.json`. `test_usage_fetch` unsets it and drives the
fetch against a stub `urlopen` instead.

The *appearance* is his check, as always.
