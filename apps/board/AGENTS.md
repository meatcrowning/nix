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
    <!-- placed: ... -->  WHEN it went on the board. Drawn; see below
    prose                 what the decision is about
    - [ ] option          ALTERNATIVES; wrapped continuations are indented
    > answer              his free text. Always beats the options
    *If unanswered:* ...  what happens if he never answers
## WAITING ON YOU TO DO   `- <TAG>: ` bullets. Actions, not decisions, each
                          followed by its own `<!-- placed: ... -->`
## IN FLIGHT              a | table |: what / where / notes
## LANDED                 `### <date>` groups of | commit | what | when |,
                          plus prose. `when` is the commit's own local time in
                          12-hour form and is OPTIONAL in both directions
```

Everything else — the `# Board` preamble, the `---` rules — is preserved and not
drawn. `boardparse.py`'s module docstring is the authoritative statement of both
the format and the round-trip contract; do not restate it elsewhere.

### Every WAITING bullet says WHAT IT IS in its first word

*"messages in the to do section should start with either QUESTION:
INFORMATION: COMPLETION: or something like those, maybe others too?, so that the
user can easily know what that message is about. any sort of elaboration or
background should go after the short description of the message"*. So a bullet
is **TAG, then a SHORT description, then anything else** — and that ordering
binds every writer, `boardmove.note` and both prompts included.

**And the shape of "anything else" is his too**: *"it should show the PARTIAL
INFORMATION whatever text, then a single line summarizing, a new line, and THEN
the elaboration if needed. it shouldnt really elaborate that much though"*. So:

- **ONE line of summary**, on the bullet's own line, after the tag. Not two.
- **The elaboration, if there has to be one, goes on INDENTED continuation lines
  under it — and it is a sentence or two, not a paragraph.** "it shouldnt really
  elaborate that much" is the instruction to the writers, not a layout note: a
  bullet that needs three paragraphs needs a doc under `docs/` and a link.
- **`parse()` splits them into `summary` and `detail`** beside the joined `text`
  every other consumer already reads (removal, the one-level undo, `reply`, the
  menus, `tag_of`, the glyph check), and `qml/Main.qml` draws them as two blocks
  with a 6px gap, the elaboration a rung dimmer. **It is a VIEW change**: the
  store on disk is untouched and its round trip is still byte-identical.
- **A bullet with nothing under it COLLAPSES** rather than reserving the gap
  (§5.2 — that absence is permanent, not transient), so it draws exactly as it
  always did and there is no blank line to look at.
- The one thing the split costs: a `**bold span**` that wraps ACROSS the first
  line puts its two markers in different halves and neither is stripped. `text`
  is unaffected, and the rule above says the summary is one short line anyway.
- **He can FOLD one, from the mark to its left** — [his, 2026-07-29] *"i should
  be able to collapse to a single line and expand messages in the to do section
  via the mark to the left of the messages."* The mark is the control and says
  which way it goes, `-` open / `+` folded, one character in the same ASCII
  vocabulary the section bands use (§2.3 — no triangles in this font). Folded,
  the elaboration goes and the summary is cut to one line **in characters, with
  an ASCII `...`** — `Main.qml`'s `clipTo`, never `Text.ElideRight`, which
  draws a U+2026 the font does not have and clips the row.
  Also a VIEW change: nothing is written.
  - **Keyed on the bullet's TEXT, and session-only**, both deliberately
    (`win.todoFolded`). The line number is what the rest of the app addresses a
    bullet by and is exactly the wrong key here — the file is rewritten under
    this window by agents and by the docs sync, so a remembered line would come
    back folded over a *different* chore. The text moves with the bullet;
    rewording one unfolds it, which is right. Nothing is persisted: the section
    collapse in `Settings` is three named permanent sections, not a map of his
    prose growing an entry per chore he ever folded.
  - The mark's hit band is wider than its ink and takes the LEFT button only
    (§5.1, §10) — a right-click anywhere still opens the row's menu, and the
    double-click-that-removes is swallowed in that band on purpose.

Five tags, `boardparse.TODO_TAGS`, and the set is short on purpose:

| | it means | who emits it |
| --- | --- | --- |
| `QUESTION:` | nothing moves until he says a word | an agent's own `note` |
| `INFORMATION:` | a fact; nothing is asked of him | the orchestrator's note, `stall` |
| `COMPLETION:` | done, and on his machine | a worker's or decision agent's `note` |
| `PARTIAL:` | some landed, some did not — a pending rebuild counts | the same |
| `FAILED:` | attempted, nothing landed | every failure path in `board-watch.py`, and `reconcile`'s dead-agent bullet |

- **There is no tag nothing can write**, and `tools/board-test.py` asserts that.
  His three are the starting set he opened up (*"or something like those, maybe
  others too?"*); `PARTIAL:` and `FAILED:` exist because the writers that were
  already there could not be honest with only three — most of what a worker
  leaves is *some of it*, and a failure filed as information is exactly what
  this system must never do.
- **`QUESTION:` is not a decision.** A decision is a numbered item in NEEDS YOU
  with options and an `*If unanswered:*` line (`boardmove.ask`). This tag is the
  small "say the word and X" an agent leaves on its way out.
- **The check is in `boardparse.add_todo_bullet`** — the one function every
  writer of that section already goes through — so a new writer cannot be added
  that forgets, and an untagged bullet is **REFUSED**, not defaulted. A
  refusal is an error the writing agent reads and fixes in one retry; a default
  would put a wrong word in front of his message.
- **Every LINE is checked, not just the first.** The orchestrator writes one
  line per task in one `note` call, and `note` prefixes `- ` **per line**: doing
  it once for the whole string left the second line a bare paragraph glued onto
  the bullet above it, which is how *"**default handlers for every app we
  wrote** - handed to Sam"* came to be drawn inside somebody else's message
  (2026-07-29). An INDENTED line is a wrapped continuation and needs no tag —
  that is where his "elaboration or background" goes.
- **READING is untouched.** The store is his and is full of bullets written
  before this existed: they parse, they draw, they can still be removed and
  restored byte-for-byte. Only writing is constrained.
- **Nothing in `qml/` draws the tag specially** — it is plain text at the front
  of the line, in the row's own tone. A colour would have to come from the
  palette's one hue, and the only ramp that says *severity* is warn/crit, which
  on this desktop means a machine fault (§8.1, §9.3) and is forbidden here by
  the no-pressure rule. A badge would be the counted, sortable thing that rule
  refuses outright. The word does the work. What the tag *does* decide is which
  SUB-SECTION the bullet is drawn in — below.

### ...and the tag is what the bullets are grouped by on screen

*"the information, completion, partial etc of a message should be used to
organize them on the board. under the needs you section there should be sub
sections for each of these headers"*. So `to do, when you feel like it` is no
longer one flat list: each tag that has bullets gets a sub-heading with its own
bullets under it.

**It is a VIEW change and nothing else.** No sub-heading is ever written into
`board.md`, the on-disk format is untouched, and the round-trip contract holds
byte-for-byte. `boardparse.parse()` tags each bullet (`tag_of`) and buckets them
(`todo_groups`) at the end of the read — once per load, for the same reason the
glyph map is applied at ingest (§2.3) — and a bullet inside a group is **the
same dict**, with the same `line`/`endLine`, that the flat `todo` list holds. So
removal, the one-level undo, `reply` and every stale-line re-resolution work
exactly as they did; `Main.qml` still keeps `win.todo` beside `win.todoGroups`
and every one of those paths reads the flat one.

- **The order is `boardparse.TODO_ORDER`: QUESTION, FAILED, PARTIAL,
  COMPLETION, INFORMATION** — by what the bullet ASKS OF HIM, and fixed by tag.
  `QUESTION` first because nothing moves until he says a word, and it is the
  only group waiting on him. `FAILED` second because the one thing this system
  must never do is let a failure sink to the bottom of a list of good news
  (the same reason the tag exists at all). Then the one with a remainder
  (`PARTIAL`), then the two that are pure record (`COMPLETION`, `INFORMATION`).
  **This is not sort-by-urgency and must not become one**: the order is a
  constant, not a function of age, count or arrival, so a bullet never moves
  between two readings and no group is ranked against a clock.
- **A tag with no bullets gets no heading at all** — an empty sub-section would
  be a slot he has to fill, which is the shape this board refuses everywhere.
- **An untagged bullet — the store is full of ones written before the tag rule —
  is drawn FIRST, under no heading**, so nothing claims it as something it is
  not. Reading stays untouched by the tag rule, and by this.
- **The sub-heading is `SectionHead`, one rung quieter**: `interactive: false`
  (no `[-]`, no click — it groups, it does not collapse) and not `accented`, so
  it is the dim label plus the border hairline. No new chrome, and **it is a
  heading and NOT a count**: no tally, no badge, no severity colour, exactly as
  the flat list had none.
- The empty state is unchanged — `nothing needs you` still keys off the section
  being empty, and an empty section draws no headings because there are no
  groups.

### Everything under NEEDS YOU says WHEN it was put there

*"mesages in the needs you section should all have the time they were placed on
the board indicated on them."* Both shapes drawn under that heading carry it — a
decision and a WAITING bullet — and it is written by the WRITER at the moment
the item goes up, never guessed at read time.

- **The store carries `<!-- placed: 2026-07-29T15:42 -->`**, a local ISO minute
  on a line of its own. Same shape and same reasons as `answered-on` above:
  markdown renders nothing for it, `reader` skips it, `boardparse._PLACED` owns
  it, and it is never prose. `placed_now()` writes it, `format_placed()` turns
  it into what is drawn, and the two are deliberately different strings — the
  store keeps the sortable one, the screen gets the readable one.
- **Where it sits is per shape.** A decision: the line under its `### <n>.
  <title>` (`boardmove.ask`). A bullet: the line under the bullet's LAST line,
  so it falls inside `todo_span()` and removal, the one-level undo and every
  stale-line re-resolution take it with them. `boardmove.note()` writes one call
  per message and the orchestrator routinely puts several bullets in one, so
  **each bullet gets its own** — one stamp at the end would date the last of
  them and leave the rest looking older than the file.
- **It is OPTIONAL in both directions**, exactly like LANDED's `when`, and for
  the same reason: this file syncs between `top` and `book` and either may be
  running the older app. An item without one draws **no time at all** — not an
  empty box, not an invented one — and an older parser carries the line through
  untouched as it does anything else it has no case for. The store was full of
  items written before this existed; `boardmove.backfill_placed()` is the
  one-off that dated them from `docs/`'s own git history (blame on the item's
  first line) and skips anything already stamped, so a second run is a no-op.
- **It is DRAWN at the trailing edge in `Theme.dim`**, in a column 15 characters
  wide (`jul 29 11:04 pm`, the longest it gets) — §9.1's metadata cluster, the
  same treatment a LANDED row's `when` gets. The question text **reserves that
  column whether or not the item has a stamp** (§5.4), so an item written before
  this existed wraps exactly where a new one does and nothing shifts under him
  as the list fills.
- **It carries the DATE as well, and that is the difference from LANDED.** A
  landed row sits under a `### <date>` heading that already says which day; an
  item in NEEDS YOU can sit there a week with nothing around it to date it, and
  a bare `3:42 pm` on a five-day-old question reads as this afternoon.
- **It is an ABSOLUTE time and it must stay one.** No "3 days ago", no age, no
  badge — that is the no-pressure requirement below, and a relative string is
  exactly the clock it forbids. This is a fact about the past, like the hash
  beside a LANDED row. `tools/board-test.py` asserts that `format_placed` cannot
  see the clock at all.

## The no-pressure requirement is a design constraint

He asked for this because the terminal chat log made him feel he had to answer
in the moment: *"i feel pressured to act quickly when really i dont need to"*.
So, as binding as the parse:

- **No counts, no badges, no ages, no deadlines, no sort-by-urgency.** A tally
  of open questions is a debt; there is not one anywhere in this app. The
  `placed` time above is not an exception to this and must not be turned into
  one: an absolute time is a fact about the past, an elapsed one is a clock
  running against him.
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
- **...with ONE exception, and it is this app's job: the HOST STAMP.** board-watch
  runs on `top` AND on `book` now, and this file syncs both ways every five
  minutes, so "he answered this" is not on its own a reason to fire — two
  watchers would put two agents on one job. So every write here that leaves an
  item ANSWERED also writes `<!-- answered-on: <hostname> -->` under the `>`
  block, in the same targeted line edit (`Board._stamp` ->
  `boardparse.set_answer_host`), and clearing the answer removes it again. The
  machine he answered on is the machine that works it.
  - It is an HTML comment because **`board.md` is his and must still read
    cleanly**: markdown shows nothing for it, `boardparse` consumes it into
    `item["answerHost"]` so it is not even prose, and `reader` skips HTML
    comment blocks (`apps/reader/mdparse.py`, changed in the same pass — it used
    to draw one as an ordinary paragraph). **Nothing in this app draws it.**
  - Re-answering an item on the other machine restamps it, and the stamp is part
    of board-watch's fingerprint — so that IS the hand-off. There is no
    automatic takeover; `docs/agents/board-watch.md` says why.

### ...and the item MOVES when it does

An answered decision that stays in NEEDS YOU is the board asking him for
something he already gave, so as work starts the decision is **relocated into IN
FLIGHT**, and to LANDED when it lands. `boardmove.py` is the whole mechanism and
its docstring is the authoritative statement; the short version:

```bash
apps/board/tools/boardctl.py start 4 --where 'apps/player/**'   # NEEDS YOU -> IN FLIGHT
apps/board/tools/boardctl.py land 4 --commit a3c2aac --what 'player: dim the art'
apps/board/tools/boardctl.py land --commit a3c2aac --what 'board: no row needed'
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
- **LANDED IS READ FROM THE COMMIT LOG, every time it is drawn.**
  `boardmove.landed_view()` derives the section from `git log`: the file's rows
  supply the WORDING and git supplies what exists. Nothing sweeps, nothing
  appends, nothing has to have remembered — so the section cannot be stale
  unless git is. His verdict, 2026-07-29, after the third time he found it hours
  behind: *"it should just read from the commit log of the repo itself. it
  shouldnt need an agent to do that"*.
    - **He was right about the SHAPE of the bug, not just the bug.** Twice the
      fix was to have something WRITE the missing rows — `Board._catch_up`
      first, then `board-watch.py`'s tick — and both were correct code that
      could not reach him. `apps/` is live source with no hot reload, so the
      board window he had open went on running the code from before the first
      fix for as long as he left it open; the watcher is a home-manager unit, so
      on `top` the second fix needed a `sudo rebuild-top` before it existed
      there at all. **A derived view has no deployment**: whichever build of
      `boardmove.py` is running reads git at the moment of the read, so a stale
      watcher and a stale window are both harmless.
    - **BOTH repos.** `~/nix` (public) and `docs/` (private, its own repo inside
      the checkout) — a change lands in one or the other and he should not have
      to know which. The docs sync timer's own `sync(host): n doc(s)` commits
      are dropped, or forty a day of them would bury the section.
    - **BOTH refs, `HEAD` and `origin/main`, unioned.** `HEAD` is what is
      actually on this machine and needs no network at all; the old sweep read
      `origin/main` alone, so a commit made here was invisible until a push
      moved the remote-tracking ref and the other host's was invisible until
      somebody fetched — *"you say that but landed still didnt update even after
      i rebooted"*. `_fetch_origin()` still runs, detached and throttled, but it
      is a COURTESY now: it decides how soon the other machine's commits show
      up, never whether this machine's do.
    - **A cached row wins on wording, never on existence.** `land --what` is
      still the primary path and still required of a worker — the sentence an
      agent chose is usually better than the raw commit subject, and the file is
      the only place to keep it. A row naming no commit at all (`no change`, a
      decision settled) is carried through verbatim. **The file is never the
      reason a commit does or does not appear.**
    - **It is TODAY AND YESTERDAY, and nothing older** — `LANDED_DAYS` (1),
      counted in **local calendar days**, not as a rolling 48 hours: his words
      were *"today and yesterdays commit log"*, so at midnight the section
      loses the day before last. The cut is on what is DRAWN and reaches the
      file's own older date groups too; nothing is ever deleted, the file keeps
      every row it has. This repo takes ~80 commits a day, so without that
      bound the section would become the whole log.
    - **NEWEST FIRST inside a day, not only across days**, and that was the
      fourth staleness report and the one that was not staleness at all
      (2026-07-29). The view was derived correctly and complete to the minute —
      the rows were sorted OLDEST-first within a group, so the top row under
      today's date was the day's *first* commit, at 12:16 am, with 87 newer
      ones below the fold under a heading that says "Newest first." He read the
      section as hours behind and he was reading it correctly. **A derived view
      still has to be ordered the way it is read**: computing the right rows is
      only half of not being stale.
    - **It is a pure read.** No lock, no write, `landed_tips()` (a `rev-parse`,
      about a millisecond) gates the expensive `git log` so it can be called on
      every repaint. `Board._poll_git` re-derives on a 10 s timer only when a
      ref has actually moved — that is for the case where nothing else wakes the
      app, a commit made in another terminal.
    - **Only a board INSIDE the repo it is a record of** (`Board._derives`).
      `--board` and every harness point this app at a throwaway file, and
      handing that one ~/nix's real history would invent a hundred rows.
    - `tools/board-test.py` → `test_landed_view` asserts a commit nobody
      recorded appears from local HEAD with no fetch and no `origin/main`, that
      the `docs/` repo is read, that sync commits are dropped, that the cached
      sentence survives without duplicating its hash, and that **nothing is
      written**; `test_landed_window` asserts the bound.
      `tools/board-watch-test.py` → `test_landed_needs_no_tick` asserts the
      inverse of what it used to: a tick appends nothing, and the commit is in
      the section anyway.
- **`land` does not need an IN FLIGHT row, and requiring one was a real bug.**
  Only a decision agent has a row (`start()` made it); a WORKER dispatched out
  of the box never did, so every commit the fan-out produced was unrecordable —
  `land` refused, `note` was all a worker could reach, and LANDED sat at
  2026-07-28 while a run of board commits went in over the next day. He noticed:
  *"are you sure the landed section functions? it's showing what look like older
  commits"*. So a selector is optional: one that matches a row moves it, and none
  at all simply records the commit (`--what` is then required, there being no row
  to take it from). The worker prompt says to call it once per commit.
- **A LANDED row carries WHEN its commit happened** — `| commit | what | when |`,
  the commit's own committer date in local time, 12-hour (`3:42 pm`), read from
  git by `boardmove.commit_time()` and never from when the row was written. That
  is not the no-pressure rule being bent: it is a fact about the past, like the
  hash beside it, and not a clock running against him. It is **optional in both
  directions** because this file syncs between the machines and either may be
  running the older app: a two-cell row parses with an empty time, and a
  three-cell row read by an older parser just loses the cell. A row with no
  commit to read one from (`no change`) is written with two cells, not an empty
  third. A group that gains its first timed row gains the `When` header in the
  same edit — a markdown row with more cells than its header drops the extras in
  every renderer, and this file is read in `reader` and on GitHub too.
- **An item cannot be stranded.** Four ways back out of IN FLIGHT: the agent
  lands it, the watcher hands it back when the agent exits badly,
  `boardmove.reconcile()` — run at the top of every board-watch tick — sees the
  owning pid is gone and hands it back itself, or `boardctl stall <row>` moves a
  row nothing owns into WAITING ON YOU TO DO. The first three are worst-case one
  timer interval. A hand-started item (`boardctl start` with no `--pid`) is
  never reclaimed automatically; nothing can tell whether that session is still
  thinking.
- **The first three are keyed on the STASH, and the stash is machine-local.**
  `board.md` syncs both ways; `~/.local/state/board/inflight/` does not. So from
  either machine, a row the *other* one started is indistinguishable from a row
  nobody started — and neither is a row written before the stash existed, or one
  added by hand. `reconcile()` covers what this host started and nothing else,
  which is why IN FLIGHT could only ever grow: reading it on 2026-07-29 he said
  it *"doesnt update at all its still got old stuff in it"*, and four of its
  five rows were ones no mechanism here could remove. `boardmove.unowned()`
  reports them (`boardctl reconcile` prints the list after its own work) and
  `stall()` is their exit. **Neither is automatic and neither should become
  one** — a row this host does not own may be perfectly alive on the other.
  `stall` MOVES the row's three cells into WAITING ON YOU TO DO rather than
  dropping them, and refuses a row whose decision is stashed here, because
  `back` would put his actual question back instead of flattening it.
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
| the orchestrator | counts the distinct asks in the input; `dispatch`es a worker per independent one, hands one to a worker already in those files, or `ask`s him. It does not build anything | `boardwork.ORCHESTRATOR_PROMPT` |
| each worker | **its own systemd unit**, capped, works/tests/commits/pushes, **and may rebuild or reload** under `~/nix/AGENTS.md` -> "When it is okay to rebuild or hot-reload" | `boardwork._spawn_worker` |
| a card per worker | two sentences — what it claims, then what it is observed doing — in one flat list, oldest first | `boardwork.cards()` + `qml/AgentRow.qml` |
| a question | an ordinary decision in NEEDS YOU, answered at his leisure | `boardmove.ask()` |

Rules that fall out of it, all load-bearing:

- **ONE MESSAGE IS OFTEN SEVERAL JOBS, and it is counted before anything is
  dispatched.** *"the orchestrator should be able to know when to break tasks up
  to different agents when the user puts multiple perhaps unrelated requests /
  features / etc into a single inbox message"* — the shape
  `~/.claude/orchestrator-briefing.md` opens with (*"The prompt may contain
  several unrelated requests, or one — you decide"*). So the prompt says to read
  the input for how many DISTINCT asks it holds — two features, a bug plus a
  feature, a knob plus a task — and give each independent one **its own worker**,
  so they run concurrently: a worker handed a shopping list half-finishes both
  jobs and leaves one commit that is hard to undo. **Genuinely coupled pieces
  stay in ONE worker** (same file, same behaviour, one change) — splitting those
  is two agents making conflicting edits to the same file, which is worse.
  DISPATCH-OR-ASK then applies **per item**, so one message can yield two
  dispatches, or a dispatch plus one question, while the *at most two questions
  for one input* ceiling goes on binding the whole message rather than each item.
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
(It is set to **5** on `top`, by his own request through the box.)

**A settings-shaped sentence is not a task.** *"change the number of allowed
agents to 5"* went through the box and an orchestrator has no business handing
it to a worker — a model session, a commit and a wait, for a one-second write.
So `cap` is in the orchestrator's own verb list and its prompt says to apply a
knob it owns itself and say so in the note. That list is deliberately short:
today the cap is the only knob on it, and anything settings-shaped without a
tool here is dispatched like any other work, with the note saying it needed one.
Every worker is a full model session with a shell in a **shared** git checkout,
so an unbounded fan-out is a real cost and a real risk.

**Work above the cap is queued, never dropped**, in `work/pending/` by the same
`os.replace()` discipline as the inbox, and it is **drawn** on his board in the
`not started yet` group — work that exists and is not running is the last thing
a control surface may hide. `boardwork.promote()` runs at the top of every
board-watch tick, so the worst case for a queued task is one timer interval,
exactly like `reconcile()` and `sweep()`.

### A NEW WORKER IS NOT THE ONLY ANSWER: handing an item to one already in those files

*"it should also know when to give items to existing agents who are already
working out of the same place or doing the same or similar things"*. So the
orchestrator's list of verbs now opens with `boardctl.py agents` — what is
running, the task each was given, and the `--where` it was dispatched against —
and closes with `boardctl.py inbox send '<the item>' --to <Name>`.

**No new machinery, and deliberately so: a handoff IS the inbox.** It is the
same `boardagents.send()` the box at the top takes and the same three
directories, so the conservation property holds unchanged, and the worker reads
it through the `boardctl.py inbox take` its own prompt already tells it to run
between steps. What changed is who may write into it — it was his channel
alone — and the worker prompt now says so: a note is either him, which outranks
the prompt, or the orchestrator handing over a further item, which is part of
the job and gets said in the final note.

Everything else about it is the honest reading of what that channel can do:

- **Workers only.** In `boardctl.py agents` a worker is the row with a NAME in
  front of its id and a path or glob in its last column. The orchestrator's own
  row is named too (`register` mints one for every registration) and is told
  apart by its `where`, which is `board-watch`; a decision agent and his
  interactive session have **no** name at all — and a decision agent's prompt
  forbids it to pick up anything else, which is why it may not be a target.
- **`delivered` is not `taken`,** exactly as everywhere else here. A handoff
  waits for the worker to check between steps; nothing interrupts it and there
  is no reply.
- **A miss is not a loss.** `send` files the message to the QUEUE whenever the
  named agent is not live — a worker that finished first, a name that resolves
  to nothing — and `sweep()` escalates one that was delivered and never read.
  The queue is drained into a fresh orchestrator on a later tick, so the item
  comes back around and is dispatched from **its own words**. That is why the
  prompt says to write the item in full, as a `dispatch` would be written.
- **It takes no slot against the cap**, which is a consequence and is written
  down as one: handing work over to get under the cap is refused in the prompt,
  because `dispatch` already queues what is over it and `promote()` starts it.
- **It is still a START, not a result** — reported as one `INFORMATION:` line
  naming the worker, inside the same note budget as a dispatch.

The neighbouring rule is the same one read from the other end: two items in ONE
message that touch the same files are one `dispatch`, not a dispatch and a
handoff.

### What the orchestrator and its workers are told, beyond the board

`boardwork.RULES` is quoted verbatim into both prompts, and it is the board's
half of `~/.claude/orchestrator-briefing.md` — the standing constraints a
regular `~/nix` triage agent gets and this system was never given. Beyond the
board's own rules it now carries: **read `docs/HARDWARE.md` before measuring
anything about the metal**, **read `docs/DESIGN.md` in SLICES** (its Contents
table plus the two or three sections a change touches — the whole file is ~35k
tokens and an agent that runs out of context mid-task leaves the tree
half-edited), **a pathspec is not enough when another agent holds the same
file** (`git diff` every hunk, commit against HEAD as it is now), and **a real
bug next to your work is his standing approval to deal with** — fix it in its
own commit if you are doing the work, dispatch it if you are the one handing
work out, and never ask him about a well-scoped improvement. The screen rule
and the sandbox were already rule 2, and **`sudo -A` is never a test**: it puts
a real password dialog in front of him, so it belongs to work that genuinely
needs root and never to proving that something works.

The decision agent's prompt (`board-watch.py`) keeps its own hand-written
copy of rules 1-5 and does **not** see these; it is one item, already scoped by
him, and it is not a dispatch target.

### The one thing that could hold the whole system up, and does not

board-watch is a `oneshot` holding a flock, so **anything it waits for blocks
every other trigger**. Hence the split: the orchestrator run is *waited on* (it
is short — capped at 15 min — and a failure has to be reported onto the board in
his own words, and there is nobody else left to do that), while **a worker runs
in its OWN transient systemd unit** and is not waited on. Four 45-minute workers
therefore do not stop a decision he answers five minutes later from firing.

**It has to be a unit, and "detached" was never enough.** A `oneshot`'s default
`KillMode` is `control-group`: when its main process exits, systemd kills
everything left in that cgroup — and `start_new_session=True` detaches the
process *group*, a terminal-signal concept, and moves nothing out of the cgroup.
So for a day **every worker was killed seconds after it started**, while the
orchestrator honestly reported the work as dispatched and the board said nothing
was wrong. Worker `we9f99c` registered at 22:49:16, the orchestrator exited at
22:49:29, and that worker's transcript ends three tool calls in with
`[Request interrupted by user]`; nobody interrupted it. **The failure mode is
silent success**, which is why `tools/board-watch-test.py` now runs a whole tick
*inside a real transient oneshot unit* and asserts a worker dispatched from it is
still running afterwards and goes on to finish its job. Run outside a unit, the
broken version passes.

`systemd-run --user --unit=board-worker-<id> --service-type=exec` is the whole
mechanism. Three things come free with it and are now relied on: `RuntimeMaxSec`
finally enforces the 45 minutes `WORKER_TIMEOUT_S` always claimed (a detached
`Popen` has no timeout at all); the user manager reaps the worker, so the zombie
window cannot open for one; and it is a **genuine systemd unit**, which is the
shape he asked for the agents section in. `KillMode=process` on the parent was
measured and also works — it is set in `board-watch.nix` as the net under the
no-user-manager fallback, but it is a `.nix` change and needs a rebuild, which
is why it is not the primary fix.

**Liveness did not change.** The unit's `MainPID` is read once, at spawn, to
fill in the registration; `boardmove._alive` (pid + kernel start time + not a
zombie) goes on being the ONE rule, and nothing asks systemd whether an agent is
running. The zombie clause stays: it was a real bug for the old path (two stub
workers that ran for one second still counted as running two and a half seconds
later, holding slots against the cap and keeping cards on his board).

### A DISPATCH IS A START, NOT A RESULT

The same bug cost him the work twice: it also produced a board that read as
though the work was done. So a worker's *ending* is accounted for rather than
assumed.

- **The orchestrator may say what it HANDED OUT and nothing more.** Its prompt
  forbids "done", "fixed", "wired", "implemented", "working" — it did not do the
  work and cannot see whether it happened.
- **And it says it in one line per task.** The bullet an orchestrator leaves in
  WAITING ON YOU TO DO is `INFORMATION:` (a start is a fact, never a result),
  then the subject, the worker's **name** (its coded id in
  parentheses, because that is what its log is called), and that nothing has
  landed yet; one more line for anything it asked, tagged `QUESTION:`. The tag
  is *inside* this budget and not a second rule beside it — the line is still
  one line. The prompt states that as a
  budget — *one line each, 25 words at the most, no second paragraph* — because "concise"
  bought a 150-word paragraph that restated his own sentence back at him
  (2026-07-29: *"it really doesnt need to elaborate that much. im not even sure
  it needed to tell me any of that"*). Four things are named there as things to
  leave out: his own words or facts restated, the orchestrator's theory of the
  cause, why the work was split or grouped that way, and **negative status** —
  no "no question for you", no "nothing needed a rebuild". Silence says both.
- **`boardctl note|land|ask` stamp `boardwork.mark_reported()`** whenever
  `BOARD_AGENT_ID` names a worker. Those three are the only ways an agent is
  allowed to say anything, so they are the only evidence needed.
- **`boardwork.reap()` runs at the top of every tick**, beside `reconcile()`,
  `sweep()` and `promote()`. A worker whose process is gone with a stamp behind
  it is filed under `work/done/`; one without is filed under `work/failed/` and
  **gets a `FAILED:` bullet in WAITING ON YOU TO DO quoting its task**. That bullet is the
  only trace such a worker leaves — its registration is dropped by `sweep()` and
  its card leaves the list the moment it dies.
- A worker's prompt therefore says to run `note` **even when it finished
  nothing**, and says why.

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

### A worker has a name, and the name is what he reads

*"can you give the workers regular human names? you can still keep the coded
names if you'd like but i think itd be interesting to have them referred to by
regular names"*, then: *"i want the names of agents to be taken from the names
of demons in the lesser key of solomon"*. So every worker is `Marbas`, not
`w1a2b3c`, on the card, in `boardctl` output, and in the bullet the
orchestrator leaves on the board. The pool is the Lemegeton's — the Ars
Goetia's 72, plus the short names the Theurgia-Goetia and the Ars Paulina
supply.

- **The coded id is still the only key, and nothing was renamed.** The systemd
  unit (`board-worker-<id>`), `~/.cache/board-work/<id>.log`, the observation
  sidecar, the inbox directory and the `agents/<id>.json` record are all keyed on
  it — renaming any of them would orphan a worker that is running right now. The
  name is **presentation**; `boardagents.NAMES` is the pool and the only place
  names are written down.
- **It is chosen once, where the id is minted** (`boardwork._spawn_worker`), and
  **persisted in the record** (`boardagents.register`). Never re-derived on a
  read: a card that renamed itself between two polls would be worse than a hex
  string. A record written before this landed gets a name derived from its id
  (`name_for`, sha1 over the pool) — stable, and the same in every process.
- **No two LIVE agents share one.** `pick_name` walks the pool past anything a
  running agent already answers to, so a note he addresses to Marbas is never
  ambiguous. Above `len(NAMES)` live agents a name repeats; the cap is 4.
- **A card draws the name and never the id**, and it draws it as the SUBJECT of
  the CLAIM — `Marbas is coding - ...`. The observed line under it carries no
  subject at all (below), so the 7-cell name column beside the title is the
  fallback for a card whose agent has said nothing, so a name is
  still **six ASCII characters at most** (§2.1's cell, §2.3's cmap): the column
  is 7 cells for a pool name, and the title starts after it without eliding, so
  a seventh character would sit against the title with no gap. That is what
  rules out `Focalor`, `Gremory` and the other long spellings, and
  `board-test.py` asserts it. The column itself **measures** (`AgentRow`'s
  `nameW`) rather than assuming 7, for the one name that is not from the pool —
  below.
- **Nothing that has nobody on it is given a name**: a task queued above the cap,
  a decision he answered, an interactive session. Same rule as the inbox box —
  a name is a claim that somebody is on it. The one exception is Solomon, and
  it is an exception on purpose (below): he is a ROLE that is always there, not
  a claim that anything is in flight, and his row says `ready` in so many
  words.

### ...and the orchestrator's name is SOLOMON, always, and it is pinned

[his, 2026-07-29] *"make the main orchestrators name Solomon. he should always
be kept on the top of the agent list and should basically indicate like he's
there and ready to go at all times when hes not doing something."* Three
separable rules, and `board-test.py` asserts each of them separately.

- **The name is fixed and out of the pool.** `boardagents.ORCHESTRATOR_NAME`;
  `register()` applies it off `kind="orchestrator"`, so every path that starts
  one gets it without asking. Solomon is not in `NAMES`, so no worker can be
  him and `pick_name` never shuffles onto him. The pool is the Lemegeton's
  demons and Solomon is the king who binds them — the one that hands out the
  work is the one name never drawn from the bag.
- **He is seven characters, and he is not truncated.** That is what widened
  `AgentRow`'s `nameW` from a hardcoded `7 * cellW` to a measured
  `max(7, len+1) * cellW`. The pool stays at six so the titles line up down the
  rest of the list.
- **He is first, whatever was born when.** `boardwork.cards()` pins every
  orchestrator row above every worker; birth-order still governs everything
  below. Two overlapping orchestrators (successive things typed close together)
  are BOTH Solomon and both pinned — one role, briefly doing two things, and a
  message addressed to him reaches a live one.
- **The row exists with nothing running.** `boardwork._idle_orchestrator_row()`
  — `state: "idle"`, no claim, no observed line, and **no id, so no inbox**:
  a note left for an orchestrator that does not exist would have nobody to read
  it, and the box at the top of the window already queues one for the next.
  `describe()` gives it the only sentence that is true — *"ready - what you
  type at the top of this window goes to him"*.
- **So the list is never empty**, and the section's "nothing is running"
  sentence is gated on `Main.qml`'s `nothingRunning` (any card that is not the
  standing row) rather than on the list's length.
- `boardctl.py inbox send --to` takes either the name or the id.

### A card says what the agent CLAIMS and what it is OBSERVED doing — both

His call, in one sentence: *"i want both. i want what its saying its doing and
what its actually doing"*. `boardphase.py` is the whole mechanism and its
docstring is the authority. It is drawn as **two plain sentences led by the
agent's name**, which is how he asked to read it: *"[agent name] is [what the
agent says its doing] and then the line below should be the [agent name] is
actually [what it is actualy doing]"*. The bare labels `says` and `doing` in a
column beside the two texts are what that replaced.

**The two sentences are the card's FIRST and SECOND lines, and the title row is
the THIRD** — his call, and the reason is that the title row does not move:
*"the very first line of an agent in the agent section should be the [name] is
[what the agent says theyre doing]. the second line should be [name] is actually
doing XYZ. the third line should be what the current first line is"*. What the
agent was handed, and the `where` it works in, are fixed for the life of the
card; the two live lines are what he re-reads. The detail line, any note
waiting in the agent's inbox, and the box he types into stay below all three.

The short version, and every line of it is a rule:

- **`says` is the agent's own words** (`boardctl.py phase coding --doing '...'`).
  It carries the OBJECT — *"the vtbclient parser"* — which watching tool calls
  can never give you.
- **The claimed word is ANY single word, not a fixed five** — [his, 2026-07-29]
  *"allow agents more freedom to indicate what they are doing, but it should
  still only be a single word - and still actually related to what they say they
  are doing. enhancing the existing coding/testing etc"*. So `bisecting`,
  `measuring`, `waiting` are all legal claims beside the classic
  planning/researching/coding/testing/finishing. `boardphase.clean_phase_word`
  is the whole rule and it enforces only what protects the card: one word,
  letters (a hyphen inside is one word), lowercase, at most
  `CLAIM_WORD_MAX`. Anything else is **REFUSED**, loudly, by `claim()` and by
  the CLI — a phrase is never truncated to its first word, because an agent
  that meant *"code review"* and got `code` would be misreported. **The honesty
  check is not a vocabulary**: it is the observed line under the claim, which
  the agent cannot write, and that is exactly why a free word is safe to allow.
  `bph.CLAIMABLE` is now only what the CLASSIFIER can produce from a
  transcript — the observed phase, and what `boardwork.groups()` buckets by.
- **...and there is a MENU of them, `bph.PHASE_WORDS`, which is not a
  whitelist** — [his, 2026-07-29] *"create a larger list of words that could
  describe what an agent is doing, i.e. more than just coding or planning - and
  allow agents to select from this new larger list"*. ~33 words that follow
  "is" as English, the classic five first; `clean_phase_word` still accepts
  anything that passes its four rules, so an off-list word is legal and refused
  by nothing. What the list buys is that an agent bisecting a regression reaches
  for `bisecting` instead of rounding itself off to `coding`. It reaches agents
  through `boardwork.phase_word_menu()`, which GENERATES the block rule 8 shows
  — a menu retyped beside the constant is a menu that drifts from what the code
  takes, and `tools/board-test.py` asserts both that every word survives
  `clean_phase_word` and that the block comes from the list.
- **Solomon DELEGATES, he does not scope** — [his, 2026-07-29] *"it seems like
  solomon does a ton of work himself"*. His run is waited on and holds the tick
  (`ORCH_TIMEOUT_S`), so a minute spent reading `AGENTS.md` to plan is a minute
  the next thing he types waits. `ORCHESTRATOR_PROMPT` tells him to read only
  enough to name a plausible `--where`, to put what he does not know into the
  task text as words, and never to open the guides to plan — the worker's own
  rules already send it there. What stayed slow on purpose is the `agents`
  check: handing an item to somebody already in those files is the one mistake
  that costs a merge.
- **Solomon claims a phase like everybody else, and that is what puts his name
  on his own top line.** A card with no claim leads with the OBSERVED line,
  which names nobody by design, so the orchestrator's card named him nowhere on
  the line he reads first — [his, 2026-07-29] it should say *"Solomon is …"*
  like the rest. The fix is in `ORCHESTRATOR_PROMPT`, not in the card: a claim
  is never manufactured for an agent (above), so he is TOLD to make one. The
  IDLE row is a different thing and is unchanged — it is not a process, it has
  no claim and no observation, and its name comes from the 7-cell column.
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
- **The second line is the OBSERVED one, never the claim, and it is the
  description ALONE** — [his, 2026-07-29] *"actually just take out the [agent]
  is actually and just display the text after it"*. An agent saying
  `testing` while every recent call is an `Edit` reads *"Marbas is testing - the
  parser"* on one line and *"editing vtbclient.py"* on the
  next — and **that divergence is a feature, not an error**. Nothing
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
  observed action reads *"last seen editing Main.qml"* — with no subject on the
  line there is nowhere else for the tense to live, and the present tense is
  false about a process that is gone — and a stopped
  agent nothing was ever seen doing gets no second line at all rather than
  an invented past. `boardphase.says_line`/`doing_line` decide all of that in
  one place, because the joining is a judgement about the real strings: a claim
  with no phase word (`boardctl.py phase` takes the phase as optional) is
  QUOTED — *"Marbas says: the vtbclient parser"* — rather than forced after
  "is", where it would not be a sentence.
- **The LEAD TONE goes to whichever of the three lines is drawn first**, so a
  card never opens on its quietest text (`AgentRow.leadTone`, docs/DESIGN.md
  §10.6). Ordinarily that is the claim, at `Theme.text`; the observation keeps
  the ordinary secondary tone under it; the title row drops to `Theme.dim`. A
  card with no claim leads with the observation instead, and one with neither
  leads with the title row. **Position picks the tone, not rank** — while the
  title row was on top the claim sat a rung *quieter* than the observation, for
  being somebody's account of themselves, and keeping that under the new order
  would make the first line of every card the dimmest thing on it.
- **The 7-cell name column exists for the card NO sentence names** — a stopped
  agent nothing was ever seen doing, or a queued task — so nothing on the list
  is anonymous and the name is never drawn twice. It lives on the title row, so
  on such a card that row is also the top line and takes the lead tone. The
  condition is one property (`AgentRow.titleFirst`) and both the column and the
  ladder read it; `tools/board-test.py` asserts the drawn order, the tones and
  both branches of the fallback offscreen.
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
  is just running. The order is BIRTH, oldest first (`boardwork.cards()`),
  which is stable — a row must not move under his cursor between two polls —
  and is not urgency: a new agent appends at the bottom and nothing above it
  moves for the rest of its life. The stamps that decide it never reach the
  screen (`boardagents.born`), which is what keeps an ordering from becoming an
  age.
- **A finished agent leaves the list at once** — board-watch drops the stash on
  success and on failure alike — and **a failed one is told apart in WORDS**
  (`exited without finishing`), with §9.1's accent gutter present only on a
  running row. Colour says nothing here; §8.1's ramp means a machine fault.
- **There are NO phase headings over the cards.** He asked for them and then
  asked for them back out: *"maybe for now take out the 'coding' 'Testing'
  'finishing touches' text and just keep agents ordered by birth/age so they
  dont move around so much"* — a card jumped from one section to another every
  time its agent picked up a different tool. **That was about the HEADINGS, and
  it is not the later request that opened the claimed word up** (above, same
  day): what came out was the sectioning, what stayed is the phase itself.
  The phase is untouched
  (`boardphase.py` still derives it, the agent still cannot set it, and the
  observed sentence is built from it) and `boardwork.groups()` still buckets
  for `boardctl.py agents`, where a terminal listing has no cursor to keep
  still. The two states that were headings rather than phases — **queued** (no
  process yet) and **stopped** — say so in words on the card's own `detail`
  line, so nothing depends on a heading being there.
- **The interactive session is not faked.** It is not a systemd unit, so it is
  listed as what can actually be observed — a process — and described as
  `running - board sees the process, not what it is doing`. Nothing invents a
  title for it.
- **Empty is the resting state**: `nothing is running`, in `Theme.dim`, with the
  box still there. Same reading as `nothing needs you`.

### The box, and the promise it can honestly make

**You cannot type into a running agent.** `claude -p` is headless with stdin
closed, and the interactive session's stdin is his terminal's. So a message is a
FILE, and a message is in exactly one directory at every instant —
`inbox/to/<agent>/`, `inbox/queue/`, `inbox/taken/`, plus `inbox/dropped/` and
`inbox/editing/` below — only ever moved between
them by `os.replace()`. That is why "nothing he types can be lost" is a property
of the filesystem here and not of anybody's diligence, and it is what
`tools/board-test.py` asserts after every path.

| he types it... | what happens | what the footer says |
| --- | --- | --- |
| to a RUNNING agent | into that agent's inbox; the row keeps showing it as `waiting in its inbox` until the agent takes it | `left in Marbas's inbox - Marbas reads that between steps` (`its`/`it` for an agent with no name) |
| to one that has FINISHED | straight to the queue | `it is not running - queued for the next agent instead` |
| with NOTHING running | straight to the queue | `queued - the next agent board-watch spawns gets it` |

**On the card that `waiting in its inbox` line is cut to ONE line**, marked with
ASCII `...` — he types paragraphs into those boxes, and wrapped in full they
buried the three lines the card is for (§5.2). Nothing is lost by the cut: the
agent is handed the untouched text by `boardctl.py inbox take`. The marker is
ASCII and not Qt's `elide` because `elide` draws U+2026 and a hardcoded UI
string on this desktop is ASCII (docs/DESIGN.md §2.3); the width is a character
count, which is exact in a monospace font (§2.7).

`delivered` never means "it read it" — only `taken` does, and that is a file
move an agent performs. Anything nobody takes is escalated to the queue by
`sweep()` (its agent went, or it has sat unread past `ESCALATE_AFTER_S`, which
is machine business and never drawn), and the queue is drained by a board-watch
run of its own (`work_the_queue`, spawning an ORCHESTRATOR - see below). If that run fails, the bullet
it leaves in WAITING ON YOU TO DO **quotes what he wrote**. There is no path
where a sentence he typed reaches nobody and says nothing.

### Second thoughts about something still queued

*"allow the user to remove queued `waiting for next agent` items or edit them in
place"*. Right-click a `waiting for the next agent` row: **edit what it says**
opens the same `InputBox` every other typed sentence here uses, seeded with the
current wording; **remove it from the queue** is last behind a separator (§7.2)
and moves the message to `inbox/dropped/` — removed from the queue is not the
same as never written, and this app deletes no prose. `QueuedNote.qml`,
`boardagents.remove_queued`/`edit_queued`, `Agents.removeQueued`/`editQueued`.

**Both can lose a race with `board-watch`, and both say so.** The queue is
drained on the watcher's clock, so a message can leave between the menu opening
and the click landing. So neither writes the queue path in place: each **claims**
the file with `os.replace` first — the removal straight into `dropped/`, the
edit into `inbox/editing/` for the length of three syscalls and then back under
its own name. Either the claim wins, or it raises and the operation reports the
message **gone** (`None` → *"that one has already gone to an agent"*), which is
§10.2's refuse-visibly. An in-place rewrite of the queue path would have done
the one unforgivable thing instead: recreate a message a drain had just taken,
so the run already working it would find it queued again and do it twice.
`sweep()` returns anything stranded in `editing/` (a process that died
mid-edit, older than `EDIT_RESCUE_AFTER_S`) to the queue.

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

One page, four sections — **what needs you, who is running it, what happened,
what is moving** — inside **one** `KineticFlickable`. IN FLIGHT sits at the
BOTTOM, below LANDED, at his request (*"for now"*, 2026-07-29); it used to sit
second. **That is a DISPLAY order and nothing else** — `board.md`'s own section
order and `boardparse.SECTIONS` are untouched, and a reorder here has to carry
three things with it or the titlebar lies: the `section` position readout (which
asks bottom-up and takes the first match), the `tbButtons` cell order, and
`jump()`. §9.2
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
  **They can be REMOVED, though** — see below.
- **LANDED is drawn entirely in the secondary tone**, commits in `dim`. It is
  the answer to "what did that session actually do to my machine", not something
  that wants attention. The **time sits at the trailing edge** in `dim` (§9.1 —
  metadata clusters with its kin at the end of the row), so the reading order
  stays hash, what, when and the time never competes with the sentence. Its
  width is a character count like the commit's, and it is `0` for a row that has
  no time, so the older rows give the space back to the `what`.
- **The `where` column drops widest-first** as the window narrows (§9.1), at
  `width: 0`. Its width comes from a CHARACTER COUNT, not from `implicitWidth`:
  `width: Math.min(implicitWidth, …)` on an elided `Text` is self-referential and
  measured out at zero — the column silently vanished until it was changed.
- **Motion** is `qmlcommon/Motion.qml`'s and there is no duration literal in the
  tree. **Focus** is filer's idiom (§3.1.1): the root `Window` derives
  `fgAccent`/`fgText`/`fgDim` and hands them down; no leaf reads `Window.active`.

### Clearing a chore: the one thing in this app that DELETES his prose

*"i should be able to clear the 'to do, when you feel like it' stuff if i wish.
currently i cannot remove it via board program"*. Agents add bullets to WAITING
ON YOU TO DO (`boardmove.note`, the watcher's failure paths) and until now
nothing ever took one away, so the section only ever grew.

`Board.removeTodo(line)` / `Board.undoRemove()`, reached two ways — a **double
click** on the row and the row's right-click menu. Every point of it is a rule:

- **A DOUBLE CLICK removes it**, because that is how he asked: *"i should be
  able to just double click on stuff in the to do when you feel like it section
  to remove them"*. It did nothing for a day and the reason is worth keeping:
  the row's `MouseArea` was `acceptedButtons: Qt.RightButton`, so the left
  button never reached it at all and the double click landed on nothing. **A
  single left click stays inert** — the store gives these bullets no checkbox,
  so there is nothing for one click to do, and a row that acted on one pass of
  the pointer would make the removal an accident waiting to happen.
- Its regression lives in `tools/board-test.py` and must use **`QTest`**, not a
  hand-built `QMouseEvent` sequence: Qt Quick derives a double click from its
  own press bookkeeping, so a `MouseButtonDblClick` posted straight at the
  window is silently dropped and the test passes against the broken code.
  Measured — the hand-built sequence reached `onClicked` and never
  `onDoubleClicked`.

- **ONE verb, `remove`. There is no "done".** A chore he has finished and a
  chore he no longer wants both end the same way — the line goes — and the
  record of *why* it existed is already in LANDED, where an agent writes what it
  did. A second "done" state would make this list a checklist with a completion
  to account for, which is exactly the debt the no-pressure requirement refuses.
- **A confirm was NOT added, an UNDO was.** The deliberateness §10.3 asks for is
  in the second click (or in the right-click plus the entry — the reading
  `ProcMenu`'s `force quit` settled), and unlike a signal to a process a deleted
  line can be put back
  byte-for-byte. `put back "..."` appears in **every** menu, because he may have
  removed the only row there was to right-click, and is **absent rather than
  greyed** when there is nothing behind it (§10). One level, this session only:
  older removals are in `docs/`'s git history, which a timer commits every five
  minutes, and the risk this guards is the misclick he notices immediately.
- **`remove this from the list` is LAST, behind a separator** (§7.2), so the
  pointer never lands on it.
- **`reply` is FIRST**, and it is his: *"the top item on the right click menu
  for to do items should be `reply` that lets me reply directly to it instead of
  typing in the top box like i am doing now"*. It opens an `InputBox` **on that
  row**, and it is **not a second write path** — `boardagents.send()` with
  nothing named, exactly what the box at the top does, so the conservation
  property still holds. The one thing it adds is the QUOTE: the chore's own text
  travels with his sentence, because "yes, do that one" means nothing to the
  orchestrator that reads it half an hour later. §7.2's ordering still holds —
  the thing he does most is first, read-only next, the undo, then the one
  destructive entry behind its separator.
- **His sentence is FIRST in the body, the quote comes after it**
  (`<his reply>  (about the `to do` bullet "...")`), and that order is the whole
  point: *"the resulting agent created should indicate the reply from the user
  rather than the original message"*. Everything downstream reads the HEAD of
  that one string — the `waiting for the next agent` line this window draws,
  `board-watch`'s card title for the orchestrator it spawns
  (`msgs[0]["text"][:70]`), every `boardctl` listing — so a body that opened with
  the quote made all of them announce the chore and bury the answer. Reordering
  the string was the whole fix; none of those readers changed.
- **A reply REMOVES the chore** — *"when the user replies to something in the to
  do section it should then remove the entry from the to do section"* — and only
  once `Agents.send()` has returned non-empty, so a reply he made and a chore
  still sitting there cannot both be true. It goes through `Board.removeTodo`,
  the same one path the menu entry and the double click take, so it inherits the
  one-level undo: a reply aimed at the wrong row costs a right-click, not his
  prose. The bullet is **re-resolved against the doc as it is now**
  (`todoLineOf`, by text, preferring its own line) rather than trusting the index
  the row was drawn from — three programs write this file and it syncs every five
  minutes, and a stale line would take somebody else's bullet. A chore that has
  gone in the meantime removes nothing and the reply still goes.
- **A bullet is removed as a UNIT.** `boardparse.remove_todo` deletes
  `line`..`endLine` — a chore routinely wraps onto indented continuation lines,
  and `remove_row` above it is for a *table* row, which is one line by
  definition. `endLine` is recorded by the parser for every paragraph.
- **Nothing is tidied.** The blank lines around it are left exactly as they
  were, even when the section empties out completely: squashing them would be a
  write touching lines it was not asked about, and this file syncs to book.
- It goes through the app's one write path (`Board._commit`: re-read, digest
  compare, refuse on a race), and `boardctl`/`board-watch` still reach the same
  edits through `boardparse.edit()`. There is no second writer.

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
# on `top`, where the wrapper carries the Qt env:
W=$(readlink -f "$(which board)"); sed '$d' "$W" > /tmp/brdenv.sh
( . /tmp/brdenv.sh; "$(tail -1 "$W" | grep -o '/nix/store/[^"]*/bin/python3')" \
    apps/board/tools/board-test.py --shots /tmp/board-shots )

# on `book`, where it does NOT — run the harness under the system python
# directly. **Do not source the wrapper there**: its `air` split is two lines,
# a shebang and an `exec`, so `sed '$d'` leaves the exec and sourcing it
# LAUNCHES BOARD on his screen. It has happened.
/usr/bin/python3 apps/board/tools/board-test.py --shots /tmp/board-shots
```

`tools/board-test.py`, offscreen, ten layers (267 checks). Four of them are
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

- **LANDED** (`test_landed`) — a commit records with NO IN FLIGHT row (the bug
  that made the section look frozen), the time comes from git rather than from
  now, a hash that resolves nowhere is simply timeless, a two-cell row still
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
one registers buttons against the harness's pid in the live compositor.

The *appearance* is his check, as always.
