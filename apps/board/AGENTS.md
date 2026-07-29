# `board` — what needs him, what is moving, what landed

Vendored source of the decision board: `main.py`, `boardparse.py`, `boardmove.py`,
`boardagents.py`, `boardwork.py`, `boardphase.py` and `qml/`.
Built and installed by `home/prog/board.nix`, which mirrors `reader.nix` exactly
(including the `air` system-python split) and runs the **live** source at
`/home/lam/nix/apps/board/main.py`, so `.py`/`.qml` edits need no rebuild. See
[`../AGENTS.md`](../AGENTS.md) for the rules shared by all eight apps, and
`~/nix/docs/DESIGN.md` before you draw anything.

```bash
board                       # ~/nix/docs/board.md
board /path/to/other.md     # any file with the same shape
```

## It is a GUI over ONE file, and that file is not this app's to redesign

**The store is `~/nix/docs/board.md`** — plain markdown, in the private `docs/`
repo, synced between `top` and `book` every five minutes, written by whichever
agent is orchestrating and edited by hand by him. board **parses it, draws it,
and writes his answers back into the same lines**. It does not own it, does not
migrate it, and must never become the only way to edit it.

Consequences that are rules, not preferences:

- **A write is a targeted LINE EDIT, never a re-serialisation.** `boardparse`
  keeps the raw line list from the read and replaces exactly the lines an edit
  names. A round-trip that reformats his prose, re-wraps a table or reorders a
  section is a bug — `tools/board-test.py` asserts *parse -> write with no
  change -> byte-identical*, and *tick one box -> exactly one line differs*.
- **An unrecognised line is carried through untouched and simply not drawn.** A
  future agent will add something this parser has no case for; that must cost a
  blank spot on screen, never a rewritten file.
- **Writes are atomic** — temp file in the target's own directory, fsync,
  `os.replace()`. Same rules as `apps/player/atomicsave.py` (that function is
  mutagen's, for audio containers, so the rules are reused rather than the code).
  This file is a git checkout a timer commits and pushes; half a `board.md`
  would sync to the other machine.

### The store's shape

```
## NEEDS YOU              decisions, `### <n>. <title>` each
    prose                 what the decision is about
    - [ ] option          ALTERNATIVES; wrapped continuations are indented
    > answer              his free text. Always beats the options
    *If unanswered:* ...  what happens if he never answers
## WAITING ON YOU TO DO   `- ` bullets. Actions, not decisions
## IN FLIGHT              a | table |: what / where / notes
## LANDED                 `### <date>` groups of | commit | what |, plus prose
```

Everything else — the `# Board` preamble, the `---` rules — is preserved and not
drawn. `boardparse.py`'s module docstring is the authoritative statement of both
the format and the round-trip contract; do not restate it elsewhere.

## The no-pressure requirement is a design constraint

He asked for this because the terminal chat log made him feel he had to answer
in the moment: *"i feel pressured to act quickly when really i dont need to"*.
So, as binding as the parse:

- **No counts, no badges, no ages, no deadlines, no sort-by-urgency.** A tally
  of open questions is a debt; there is not one anywhere in this app.
- **Nothing is drawn in the `warn`/`crit` ramp.** Those colours mean a machine
  fault on this desktop (§8.1, §9.3); a question is not one.
- **Every decision draws its own `if unanswered` line, always** — never behind a
  fold, never abbreviated. That sentence is what makes walking away safe, and it
  comes from the file rather than from this app's judgement.
- **Nothing leaves NEEDS YOU because board says so.** The store's own rule: an
  agent may add items and move things between IN FLIGHT and LANDED, but only he
  resolves a decision. board ticks boxes and writes his sentence; it never
  deletes an item. An item leaves NEEDS YOU only once **he** has answered it and
  work has actually started — see *Answering here now STARTS something*, below.
  That is not this app doing it: `boardmove.py` is, on behalf of whoever is doing
  the work, and the GUI still has no move in it at all.
- The empty state says `nothing needs you` / `nothing here expires - come back
  whenever`, in `Theme.dim` with the section rule above it unchanged, so a board
  with nothing on it reads as finished rather than as broken. It is the state he
  will see most often.

## Answering here now STARTS something

`home/srvs/board-watch.nix` watches this file and, when a decision becomes
newly answered, spawns one headless agent on that one decision. Two consequences
for anything in this app that writes:

- **A write must remain a targeted line edit**, above — the watcher fingerprints
  only the ticked option indices and the `>` text, so a re-serialisation that
  moved lines would still not fire it, but a rewritten option list would look
  like him changing his mind. The round-trip contract is now load-bearing twice.
- **The watcher never fires on its own writes or the agent's**, so this app does
  not have to coordinate with it, mark anything, or know it exists. Do not add a
  "worked by an agent" flag to the store to help it; the filter is deliberately
  content-based and authorship-blind (a `git pull` from book has no author it
  could ask about anyway).

### ...and the item MOVES when it does

An answered decision that stays in NEEDS YOU is the board asking him for
something he already gave, so as work starts the decision is **relocated into IN
FLIGHT**, and to LANDED when it lands. `boardmove.py` is the whole mechanism and
its docstring is the authoritative statement; the short version:

```bash
apps/board/tools/boardctl.py start 4 --where 'apps/player/**'   # NEEDS YOU -> IN FLIGHT
apps/board/tools/boardctl.py land 4 --commit a3c2aac --what 'player: dim the art'
apps/board/tools/boardctl.py back 4 --why 'blocked on the FOCUS signal'
apps/board/tools/boardctl.py note '**Relaunch `player`** - live source.'

# ...and the orchestrator's half (`boardwork.py`)
apps/board/tools/boardctl.py dispatch 'wire FOCUS through vtbclient' --where 'apps/pylib/**'
apps/board/tools/boardctl.py ask 'How far should the fade reach?' \
    --option 'apps only' --option 'apps and panel' \
    --if-unanswered 'the apps get it and nothing else does'
apps/board/tools/boardctl.py cap 6          # workers allowed at once
apps/board/tools/boardctl.py phase coding --doing 'the vtbclient parser'
apps/board/tools/boardctl.py agents         # who is running, by phase
```

Rules that fall out of it, all of them load-bearing:

- **Every writer goes through `boardparse.edit()`** — advisory lock, digest
  re-check, atomic replace. `boardctl`, `board-watch` and the app can all write
  while he has the window open. **Nothing hand-edits this file**, agents
  included; the watcher's prompt says so in as many words.
- **A move is a RELOCATION, not a summary.** The decision's raw lines are cut and
  stashed under `~/.local/state/board/inflight/`, so `back` restores them
  byte-for-byte, in their original position, and a failed agent leaves no trace
  in the store at all. `tools/board-test.py` asserts that for every item.
- **The moved row carries his answer and nothing else.** The ticked option, his
  sentence, or both — it is the one thing in the item he wrote, and LANDED will
  not carry it. **No start time, no age, no count**: the no-pressure requirement
  above applies to IN FLIGHT exactly as it does to NEEDS YOU, and a start time is
  an elapsed time the moment he reads it. The stash records one because
  reclaiming a dead agent's item is machine business; it never reaches the file.
- **An item cannot be stranded.** Three ways back out of IN FLIGHT: the agent
  lands it, the watcher hands it back when the agent exits badly, or
  `boardmove.reconcile()` — run at the top of every board-watch tick — sees the
  owning pid is gone and hands it back itself. Worst case is one timer interval.
  A hand-started item (`boardctl start` with no `--pid`) is never reclaimed
  automatically; nothing can tell whether that session is still thinking.
- **A failed decision does NOT re-fire.** Its answer is already recorded in the
  watcher's state, so it comes back to NEEDS YOU and sits there with the bullet
  saying what happened. Re-answering it is what starts it again — deliberately,
  because the alternative is a crash loop spawning an agent every five minutes.
- **Moving an item by hand SUPPRESSES the auto-spawn for it**, because only
  NEEDS YOU is fingerprinted. Correct — work is underway — but whoever moves it
  owns doing the work.
- **An empty NEEDS YOU is now the resting state**, not a parse failure. Nothing
  in this app or its harness may treat "no decisions" as a regression.

## The box at the top: this window STARTS things now

He asked for a control surface, in one sentence:

> *"i was imagining more of a single box that i could type things into, press
> enter, and have them sent to an inbox. then an agent figures out what agents
> to assign to what (like how you used to orchestrate) and as agents spawned,
> theyd show up as a little visual box that indicated what they were doing, and
> each agent would be placed in sections based on what they were doing;
> planning, researching, coding, testing, finishing touches, etc. and there'd be
> another section where questions for me to answer would be easily reachable in
> a list and i could answer them at my leasure."*

So the page opens with ONE box, above every section, because it is the only
thing on the page that starts something — everything below it is a report. The
whole pipeline, and what each piece is allowed to claim:

| | what happens | where it lives |
| --- | --- | --- |
| he types and presses enter | a FILE in `inbox/queue/`, by the write path that already existed | `boardagents.send()` |
| board-watch's next run | drains the queue and spawns ONE **orchestrator**, and WAITS for it | `board-watch.py:work_the_queue` |
| the orchestrator | splits the input up; `dispatch`es workers or `ask`s him. It does not build anything | `boardwork.ORCHESTRATOR_PROMPT` |
| each worker | detached, capped, works/tests/commits/pushes, **never rebuilds** | `boardwork._spawn_worker` |
| a card per worker | grouped by phase, saying what it claims AND what it is observed doing | `boardwork.groups()` + `qml/AgentRow.qml` |
| a question | an ordinary decision in NEEDS YOU, answered at his leisure | `boardmove.ask()` |

Rules that fall out of it, all load-bearing:

- **The box writes down the path that already existed.** `boardagents.send()`
  with no agent named — the same one a note to a running agent takes, with the
  same conservation property (a message is in exactly one of `to/`, `queue/`,
  `taken/` at every instant, moved only by `os.replace()`). There is no second
  write and there must never be one; the harness asserts conservation after the
  GUI path as well as the CLI one.
- **The footer says where it WENT, never what will come of it.** `in the inbox -
  an orchestrator works out who does what`. Nothing fires immediately: the
  at-the-machine gate still applies, and promising more would be exactly §10's
  dishonest feedback.
- **A question an agent asks is not a second mechanism.** `boardctl.py ask`
  writes the same `### n. title` block, with options, a `>` line and an
  `*If unanswered:*` sentence, at the end of NEEDS YOU. It draws, answers and
  fires identically, and it carries **no "asked by a robot" flag** — the
  generalisation was the requirement, not a parallel list.
- **`ask` REFUSES without `--if-unanswered`,** and writes nothing. That sentence
  is what makes a question safe to walk away from; a question that arrived
  without one would be the first thing on this board that quietly demands an
  answer.
- **A new question is seeded into board-watch's fingerprints as it is written**
  (`boardwork.seed_watch_state`). board-watch deliberately does not fire on a
  key it has never seen, so without this an answer he gave inside the
  five-minute window between the question and the next tick would be recorded
  and never worked. This is the one thing outside board-watch that writes its
  state file.

### The concurrency cap, and what is above it

**Four workers at once by default,** and it is a FILE
(`~/.local/state/board/cap`, `boardctl.py cap 6`), not a nix option — same
reasoning as board-watch's kill switch: he can change it at 2am with no rebuild.
Every worker is a full model session with a shell in a **shared** git checkout,
so an unbounded fan-out is a real cost and a real risk.

**Work above the cap is queued, never dropped**, in `work/pending/` by the same
`os.replace()` discipline as the inbox, and it is **drawn** on his board in the
`not started yet` group — work that exists and is not running is the last thing
a control surface may hide. `boardwork.promote()` runs at the top of every
board-watch tick, so the worst case for a queued task is one timer interval,
exactly like `reconcile()` and `sweep()`.

### The one thing that could hold the whole system up, and does not

board-watch is a `oneshot` holding a flock, so **anything it waits for blocks
every other trigger**. Hence the split: the orchestrator run is *waited on* (it
is short — capped at 15 min — and a failure has to be reported onto the board in
his own words, and there is nobody else left to do that), while **workers are
spawned detached** and reparented to init. Four 45-minute workers therefore do
not stop a decision he answers five minutes later from firing on time.

Consequence, and it was a real bug: a detached child is a **zombie** until its
spawner exits, and `/proc/<pid>` still exists for one. `boardmove._alive` now
treats state `Z` as dead — measured, two stub workers that ran for one second
were still counted as running two and a half seconds later, holding slots
against the cap and keeping cards on his board.

## The `agents` section: the only part of this window that is NOT the store

He asked for *"a display on the board of currently active systemd claude agents
running and a brief title / description and a text box for me to send commands /
new ideas / fixes to an agent"*. That section is `boardagents.py` plus
`qml/AgentRow.qml`, and it reads the MACHINE, not `board.md`:

- **the stashes** `boardmove.start()` already writes (title, where, owning pid
  and that pid's kernel start time),
- **`/proc`**, for `claude` processes nothing here spawned,
- **one `systemctl --user show board-watch.service`**, run through `QProcess` so
  a fork never lands on the GUI thread's clock.

Rules, all of them load-bearing:

- **There is ONE liveness rule and it is `boardmove._alive`** — pid, kernel
  start time, and not a zombie. A recycled pid cannot make a dead agent look
  alive and neither can an unreaped one. Do not add a second definition of
  "running" anywhere in this tree.

### A card says what the agent CLAIMS and what it is OBSERVED doing — both

His call, in one sentence: *"i want both. i want what its saying its doing and
what its actually doing"*. `boardphase.py` is the whole mechanism and its
docstring is the authority. The short version, and every line of it is a rule:

- **`says` is the agent's own words** (`boardctl.py phase coding --doing '...'`).
  It carries the OBJECT — *"the vtbclient parser"* — which watching tool calls
  can never give you.
- **`doing` is derived from the agent's live transcript**,
  `~/.claude/projects/*/<session-uuid>.jsonl`, which Claude Code appends to as
  the agent works. It carries the VERB — *"editing vtbclient.py"* — and cannot
  be faked, forgotten or left stale.
- **The linkage is CHOSEN, not guessed.** Every spawn passes
  `claude --session-id <uuid>`, so the transcript is found by globbing that uuid
  and the project-slug rule is never reimplemented here. That flag is
  load-bearing: lose it and every card silently degrades to *"cannot see what it
  is doing"* with no error anywhere. `tools/board-watch-test.py` asserts the
  spawn passes it.
- **The card is filed under the OBSERVED phase, never the claim.** An agent
  saying `testing` while every recent call is an `Edit` appears under *coding*,
  saying *testing* — and **that divergence is a feature, not an error**. Nothing
  hides it, reconciles it, warns about it or colours it: the warn/crit ramp on
  this desktop means a machine fault (§8.1, §9.3), not an agent being optimistic
  about itself.
- **Each side may be missing, and says so on its own terms.** No claim is
  silence — a claim is never manufactured out of the observation, which would
  make the two agree by construction and throw away the only thing having two of
  them buys. No transcript, or nothing in it yet, is stated plainly rather than
  falling back to the claim and passing it off as observation.
- **A stalled agent is visible, without a clock.** No tool call for a while sets
  the observed side to `nothing recently` — words, no number. The threshold is
  machine business exactly like `ESCALATE_AFTER_S`; the no-pressure rule is not
  suspended because the subject is a robot.
- **Present tense only while the process is there.** A stopped agent's last
  observed action is labelled `last`, not `doing`.
- **Transcripts reach megabytes** (a long session's is ~1.8 MB), so nothing ever
  reads one whole: each agent's record keeps a byte offset and a poll reads only
  the delta, advancing past complete lines only — a transcript is appended to
  while it is being read.
- **The classifier is meant to be tuned**, and it lives in exactly one place:
  `TOOL_PHASE` and `BASH_PHASE` at the top of `boardphase.py`. Reading is the
  background noise of every phase, so `researching` is what an agent is doing
  when reading is *all* it is doing; a plain `Bash` command claims no phase at
  all.

**Why the transcript and not `--output-format stream-json`.** stream-json is
real and would work, but a worker is detached on purpose — there is no parent
left alive to read its stdout, so the stream would have to be redirected to a
file and tailed, which is this same problem in a format we would then own. The
transcript is already on disk, already structured, already written by the
platform, and it works for agents this system did not spawn. One spawn flag buys
all of it.
- **It writes nothing to the store.** Everything it persists is under
  `~/.local/state/board/` (`inbox/`, `agents/`). `board.md`'s writers are still
  exactly three, all through `boardparse.edit()`.
- **The no-pressure rule applies here too**: no ages, no elapsed times, no
  counts, no urgency ordering, nothing from the warn/crit ramp. A running agent
  is just running. The order is running -> unowned -> exited, which is stable
  (a row must not move under his cursor between two polls), not urgent.
- **A finished agent leaves the list at once** — board-watch drops the stash on
  success and on failure alike — and **a failed one is told apart in WORDS**
  (`exited without finishing`), with §9.1's accent gutter present only on a
  running row. Colour says nothing here; §8.1's ramp means a machine fault.
- **Nothing in the phase groups is a count or an ordering by urgency**, and an
  EMPTY phase is not drawn at all — an idle board is one dim sentence, not a
  column of eight empty headings (§5.2).
- **The interactive session is not faked.** It is not a systemd unit, so it is
  listed as what can actually be observed — a process — and described as
  `running - board sees the process, not what it is doing`. Nothing invents a
  title for it.
- **Empty is the resting state**: `nothing is running`, in `Theme.dim`, with the
  box still there. Same reading as `nothing needs you`.

### The box, and the promise it can honestly make

**You cannot type into a running agent.** `claude -p` is headless with stdin
closed, and the interactive session's stdin is his terminal's. So a message is a
FILE, and a message is in exactly one of three directories at every instant —
`inbox/to/<agent>/`, `inbox/queue/`, `inbox/taken/` — only ever moved between
them by `os.replace()`. That is why "nothing he types can be lost" is a property
of the filesystem here and not of anybody's diligence, and it is what
`tools/board-test.py` asserts after every path.

| he types it... | what happens | what the footer says |
| --- | --- | --- |
| to a RUNNING agent | into that agent's inbox; the row keeps showing it as `waiting in its inbox` until the agent takes it | `left in its inbox - it reads that between steps` |
| to one that has FINISHED | straight to the queue | `it is not running - queued for the next agent instead` |
| with NOTHING running | straight to the queue | `queued - the next agent board-watch spawns gets it` |

`delivered` never means "it read it" — only `taken` does, and that is a file
move an agent performs. Anything nobody takes is escalated to the queue by
`sweep()` (its agent went, or it has sat unread past `ESCALATE_AFTER_S`, which
is machine business and never drawn), and the queue is drained by a board-watch
run of its own (`work_the_queue`, spawning an ORCHESTRATOR - see below). If that run fails, the bullet
it leaves in WAITING ON YOU TO DO **quotes what he wrote**. There is no path
where a sentence he typed reaches nobody and says nothing.

**Agents reach their side with `boardctl.py inbox take`** — `BOARD_AGENT_ID`
names the inbox, board-watch's prompt tells every agent it spawns to check it
between steps, and an interactive session finds its own id by walking its
process ancestry. **Only agents spawned after this landed have that line in
their prompt**; an older one will never look, which is exactly what the
escalation exists for.

## Never clobber him — three defences

The store is edited by agents and by a sync timer **while this window is open**.

1. **Watched and re-read in place.** `QFileSystemWatcher` on the file *and* its
   directory (an atomic save replaces the inode), coalesced by a 120 ms settle
   timer. The QML puts the scroll position back afterwards, so a reload is
   invisible (§6.1).
2. **A write refuses on a race.** `Board._commit` re-reads the file and compares
   its sha256 against the parse the edit was computed from. Different means
   somebody else moved the lines: it reloads, says
   `board.md changed on disk - reloaded, nothing written`, and writes nothing.
   Clicking again works. **This is asserted in the harness**; a stale line index
   landing his answer inside someone else's paragraph is the one failure this
   app must never have.
3. **Unsaved free text is never discarded.** A draft answer is persisted to
   `~/.local/state/board/state.json` on a 700 ms settle timer, survives a
   reload, a relaunch and a crash, and is drawn with
   `(a draft, not written to board.md yet)` under it. Escape leaves the editor
   and *keeps* the draft. Only committing (Enter) or clearing it removes it.

## What it draws, and why it looks like that

One page, four sections, in his stated order of interest — **what needs you,
what is moving, who is running it, what happened** — inside **one**
`KineticFlickable`. §9.2
forbids nested scroll regions, so every section sizes to its whole content and a
wheel notch means the same thing wherever the cursor is. `VScroll` is the bar and
the gutter is reserved from its own `barW`, never a literal.

- **Sections are told apart by a RULE and by spacing, never by size or weight**
  (§2.2 — the font ships Regular only, and every size here is one desktop-wide
  setting). `needs you` takes an accent rule; `in flight`, `agents` and `landed`
  take the border hairline. The band is also the collapse control and says so: `[-]` /
  `[+]`, ASCII, because the font has no triangles (§2.3).
- **An ANSWERED decision carries the 2px accent gutter** §9.1 gives a current
  row. Nothing marks an unanswered one: an open question is this file's resting
  state, not an exception to flag.
- **Once an option is chosen the alternatives recede a rung** to `textDim`
  (§3.3's ladder). They have to: body text on this desktop *is* the accent
  (§3.1), so "chosen" cannot be said by making one label brighter — there is
  nothing brighter to go to.
- **Options are a RADIO.** They are alternatives; ticking one clears the others,
  and ticking the chosen one clears it, so a mind can be changed here rather
  than only in an editor (§10.2).
- **The WAITING TO DO bullets get no checkbox**, because the store gives them
  none to write to — §10's rule that a control which cannot work is not drawn.
- **LANDED is drawn entirely in the secondary tone**, commits in `dim`. It is
  the answer to "what did that session actually do to my machine", not something
  that wants attention.
- **The `where` column drops widest-first** as the window narrows (§9.1), at
  `width: 0`. Its width comes from a CHARACTER COUNT, not from `implicitWidth`:
  `width: Math.min(implicitWidth, …)` on an elided `Text` is self-referential and
  measured out at zero — the column silently vanished until it was changed.
- **Motion** is `qmlcommon/Motion.qml`'s and there is no duration literal in the
  tree. **Focus** is filer's idiom (§3.1.1): the root `Window` derives
  `fgAccent`/`fgText`/`fgDim` and hands them down; no leaf reads `Window.active`.

### Chrome: the hyprvtb titlebar (§12, §7.4)

`ny` / `if` / `ag` / `ld` jump to a section **and** report position — the lit one is the
section the top of the viewport is in, like reader's outline marking. `md` opens
the store in `reader`, and says so if `reader` cannot be launched.

**There are deliberately no `<`/`>` cells and no `NavButtons`.** board has one
page and no journey to retrace; §11.1 says a program with no genuine history gets
nothing rather than an invented one. Add a row to DESIGN.md §11.1's table if that
ever changes.

## Recorded limit: the store quotes glyphs the font lacks

`board.md`'s open font decision literally lists the characters More Perfect DOS
VGA is missing — `À Á Â Ã È Ê Ë Ì Í Î Ï Ð Ò Ó Ô Õ Ø Ù Ú Û Ý Þ` — and the shared
map (`pylib/glyphs.py` + the panel's `Glyphs.qml` twin) has no entry for the
Latin-1 accented capitals, so **that one line clips** (§2.3). Extending the table
is a desktop-wide change across both roofs and belongs to that decision, not to
this app. `tools/board-test.py` carries the set as a named baseline and prints a
`NOTE`, so a genuine new regression is still a FAIL rather than being lost in it.

Everything else is glyph-mapped at INGEST, once per load, in `boardparse.text()`
— and emphasis stripping plus mapping happen on the **joined** paragraph, never
per line: a `**bold span**` that wraps in the source is two lines, and stripping
each separately leaves both markers on screen (it did).

## Verify

```bash
W=$(readlink -f "$(which board)"); sed '$d' "$W" > /tmp/brdenv.sh
( . /tmp/brdenv.sh; "$(tail -1 "$W" | grep -o '/nix/store/[^"]*/bin/python3')" \
    apps/board/tools/board-test.py --shots /tmp/board-shots )
```

`tools/board-test.py`, offscreen, seven layers (156 checks). Two of them are
new and are the ones to read first if the fan-out misbehaves:

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
  queue oldest-first; a dead agent is filed under `stopped` **whatever it last
  claimed** and the sweep then drops its record; `ask` refuses without
  `--if-unanswered` and writes nothing, then lands as an ordinary numbered
  decision with all four parts and no robot flag; and the board-watch seed.

The other five: **the round trip** (pure Python
— byte-identity, one-line edits, the radio, the `> ` marker preserved on a
clear, the atomic write), **the moves** (start/land/back/note/reconcile: every
decision's start -> back is byte-identical, the row lands in IN FLIGHT's own
table and not the `Queued` one below it, an unanswered decision is refused, a
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
exactly once**, **cards grouped by what each agent is OBSERVED doing, carrying
both statements, with no time, age or count anywhere on them**, and
`grabWindow()` PNGs with `--shots`:
the real store, the fixture populated, a decision answered, an EMPTY `NEEDS
YOU`, an EMPTY agents section (with `/proc` stubbed away, since the process
running the harness is itself under a Claude session), the agents section
populated, a 420x600 window, and an unreadable store. It redirects
`BOARD_TRANSCRIPTS` at a synthetic transcript tree — a harness here must **never**
write into `~/.claude`, which syncs to book — and `XDG_STATE_HOME` into a
scratch dir (a harness here **must**, or it rewrites his own app's state), works
on a COPY of the store for every write, and stubs the Titlebar, because the real
one registers buttons against the harness's pid in the live compositor.

The *appearance* is his check, as always.
