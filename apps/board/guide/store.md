# The store: `docs/board.<host>.md`, its five sections and the rules for writing them

*What the file looks like, what a bullet must say, one board item per ask, the stamps every entry carries, and what answering a decision sets off.*

Part of goetia's guide — the map and the shared
rules are in [`../AGENTS.md`](../AGENTS.md); read that first.

---

## It is a GUI over ONE file, and that file is not this app's to redesign

**The store is `~/nix/docs/board.<hostname>.md`** — `board.top.md` on `top`,
`board.book.md` on `book` — plain markdown, in the private `docs/` repo, written
by whichever agent is orchestrating and edited by hand by him. board **parses
it, draws it, and writes his answers back into the same lines**. It does not own
it, does not migrate it, and must never become the only way to edit it.

**ONE BOARD PER MACHINE, and they are never merged** [his, 2026-07-30]. Both
files are committed and both sync, so each machine keeps a full history and a
backup of the other's board — but **every reader and writer on a host touches
only its own**, and nothing anywhere reconciles the two. That is the whole point:
*"specifically for this reason now of an overnight test i dont want that
overwriting ... to overwrite anything i do on air"*. An overnight agent on `top`
and his own typing on `book` can no longer land on the same lines.

Resolve the path, never spell it:

- **`boardparse.board_path()`** — this host's store. Pure, no I/O:
  `$BOARD_FILE` if set, else `~/nix/docs/board.<os.uname().nodename>.md`. The
  token is the OS **hostname** (`top` / `book`) and deliberately not the flake
  attribute (`top` / `air`), which exists only inside nix eval — every runtime
  writer has the hostname and nothing else, so there is no mapping table on this
  path at all. `boardparse.BOARD_PATH` is that call made once at import, and is
  the default in every `boardmove` signature.
- **`boardparse.ensure_board(path=None)`** — the path to actually *use*, brought
  into existence: a host that has never had a board gets the empty skeleton
  rather than an error. Every entry point calls it (`main.py`'s `Board`,
  `boardctl`'s `--board` default, `board-watch`, `board-reminder`), so a missing
  board is never an error anywhere. A host's first board is EMPTY on purpose and
  never a copy of the other's: duplicating the open questions onto both boards
  would let both watchers work the same item.
- One temporary branch inside `ensure_board`: while the pre-split
  `docs/board.md` still exists and this host's file does not, it creates nothing
  and returns the old file. Seeding an empty `board.top.md` in front of the
  migration's `git mv` would have shown him an empty board with his real one a
  filename away. Dead code once the move has landed on both machines.

**...and this app kicks that sync at both ends of a session** (`main.sync_now`,
2026-07-29): `systemctl --user start --no-block nix-docs-sync.service` on
startup, which PULLS what the other machine wrote before he reads a word, and
again on `aboutToQuit`, which PUSHES what he just answered — *"i'd like the
board to also sync after the program has been closed by the user."* The timer is
untouched and is still the guarantee; these only remove the up-to-five-minute
wait either side of the window. It starts the unit that already exists rather
than running git here, does nothing for a board outside `docs/` (same reading as
`Board._derives`), and **fails silently on purpose** — it is an optimisation of
when the timer would have run anyway, so the honest report for a miss is the
timer's, not a dialog over a board he has just closed. `BOARD_NO_SYNC=1` turns
it off for a harness.

`board.*.md merge=boardrecent` stays registered — real 3-way merge first, most
recent side wins a genuine collision — but with one writer per file it is now a
backstop rather than the mechanism. Root `AGENTS.md` → the `docs/` bullet;
harness `tools/board-merge-test.sh`.

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
  This file is a git checkout a timer commits and pushes; half a board would
  sync to the other machine.

### The store's shape

```
## NEEDS YOU              decisions, `### <n>. <title>` each
    <!-- by: ... -->      WHO put it there. Drawn; see below. OPTIONAL
    <!-- placed: ... -->  WHEN it went on the board. Drawn; see below
    prose                 what the decision is about
    - [ ] option          ALTERNATIVES; wrapped continuations are indented
    > answer              his free text. Always beats the options
    *If unanswered:* ...  what happens if he never answers
## WAITING ON YOU TO DO   `- <TAG>: ` bullets. Actions, not decisions, each
                          followed by its own `<!-- by: -->` then
                          `<!-- placed: ... -->`, in that order
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

- **ONE line of summary, AT MOST about a dozen words**, on the bullet's own
  line, after the tag. Not two lines, and not a long one: "a SHORT description"
  alone did not hold — he came back with *"still too long"* (2026-07-29) — so
  the length is mechanical now. `boardparse.check_short_summary` refuses a
  first line past `SUMMARY_MAX_WORDS` (12), counting a code span as ONE word
  (interpolated data must not make a mechanical note refusable) and counting
  the `**headline**`'s words like any others (a twenty-word headline is the
  disease, not an exemption).
  **That exemption is only as good as the span**, and a DOUBLED one voids it:
  `oneline(code=True)` returns the backticks itself, so a template that also
  wraps the placeholder emits ``x``, whose empty pair at each end is what
  `_CODE` matches — the data between them reverts to countable prose. It cost
  the one note that must never be refusable: board-watch's dead-worker bullet
  measured 35 words and was rejected, so Halphas (`wa5844f`) died on its
  runtime limit leaving nothing at all on the board (2026-07-31). Interpolate
  the formatter's span; never add a second pair. `tools/board-test.py`
  renders every board-watch failure template from a hostile record and puts it
  through the real checks, which is the half that was missing — reading the
  tag off the source proved only that it was tagged.
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
    collapse in `Settings` is named headings — the sections, the tag groups, a
    day in `landed` — and not a map of his prose growing an entry per chore he
    ever folded.
  - The mark's hit band is wider than its ink and takes the LEFT button only
    (§5.1, §10) — a right-click anywhere still opens the row's menu, and the
    double-click-that-removes is swallowed in that band on purpose.

Seven tags, `boardparse.TODO_TAGS`, and the set is short on purpose:

| | it means | who emits it |
| --- | --- | --- |
| `QUESTION:` | nothing moves until he says a word | an agent's own `note` |
| `INFORMATION:` | a fact; nothing is asked of him | the orchestrator's note, `stall` |
| `COMPLETION:` | done, and on his machine | a worker's or decision agent's `note` |
| `PARTIAL:` | some landed, some did not — a pending rebuild counts | the same |
| `FAILED:` | attempted, nothing landed | every failure path in `board-watch.py`, and `reconcile`'s dead-agent bullet |
| `SUMMONED` | a minister was started for a piece of work | the orchestrator's note |
| `COMMANDED` | ...and the same, for one that was already running | the same |

**The last two carry NO COLON and NOTHING in front of them**, and they are the
only two written that way (`boardparse.BARE_TAGS`). [his, 2026-07-30] *"the
message posted to the board when a minister is summoned should read `SUMMONED
[agent] [for/to] [task]` instead of what it is now ... it should NOT say
INFORMATION: at the beginning"*. So the line is
`SUMMONED Marbas (`wd690a4`) to add commit times` — the `for`/`to` is whichever
is grammatical.

**They are DRAWN in a sub-section of their own**, headed
`summoned - who is on what right now` — [his, later on 2026-07-30] *"SUMMONED
messages should go in their own sub section"*, which reverses the half of the
rule above that filed them under `information`. `COMMANDED` is filed beside
`SUMMONED` by `boardparse.TAG_SECTION`/`section_of()` (the one place a tag and
the sub-section it files under are allowed to differ), and the heading text is
`TAG_LABEL`/`label_of()` because `summoned` alone would read as one more tag in
a column of tags. It is LAST in `TODO_ORDER`: not a report at all but the state
of the triangle, and every line in it is retired by its own minister's result.
Reading is unchanged: the store
is full of the old `INFORMATION: **subject** - SUMMONED: Marbas (...)` shape and
every one of them still parses, still groups under `information` (its tag is
`INFORMATION`, and the store keeps the tag he reads) and still gets
retired by its worker's result (`tag_of` tries the colon first, `summon_of`
accepts either). A `SUMMONED:` further along a line is deliberately NOT read as
a second ask by `check_one_ask` — that IS the old shape.

- **There is no tag nothing can write**, and `tools/board-test.py` asserts that.
  His three are the starting set he opened up (*"or something like those, maybe
  others too?"*); `PARTIAL:` and `FAILED:` exist because the writers that were
  already there could not be honest with only three — most of what a worker
  leaves is *some of it*, and a failure filed as information is exactly what
  this system must never do.
- **`QUESTION:` is not a decision.** A decision is a numbered item in NEEDS YOU
  with options and an `*If unanswered:*` line (`boardmove.ask`). This tag is the
  small "say the word and X" an agent leaves on its way out.
- **The checks are in `boardparse.add_todo_bullet`** — the one function every
  writer of that section already goes through — so a new writer cannot be added
  that forgets, and an untagged bullet or an over-long first line is
  **REFUSED**, not defaulted or truncated. A refusal is an error the writing
  agent reads and fixes in one retry; a default would put a wrong word in
  front of his message, and a truncation would cut a summary he never wrote.
  The mechanical writers obey the same cap: `stall`'s and `reconcile`'s
  bullets and board-watch's four failure templates all keep their first line
  inside the budget and put the story on indented continuation lines, with
  interpolations of unknown length (`{how}`, his titles) off the first line.
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

### ONE BOARD ITEM PER ASK

[his, 2026-07-29] **Messages are SEPARATED**: an agent reporting on several
things writes several bullets, never one message covering them all. It is not
style, it is how the board CLEARS — replying to a bullet removes that bullet
(`reply`), so an ask folded into another one is cleared by a reply that was
never about it and survives nowhere he can see. Worker Purson was handed four
asks and left one bullet whose headline named the first; his reply to it took
2-4 with it, unseen.

The write path already made separation cheap — `note` prefixes `- ` per line, so
several unindented lines are several bullets, each with its own `placed` stamp,
each removable, replyable and foldable on its own. What was missing was anything
that stopped a writer bundling instead. `boardparse.check_one_ask` is that, at
the same choke point as the tag check, and it refuses the SHAPES a second ask
arrives in — a machine cannot read intent, but each of these is one wearing a
disguise:

| refused | because |
| --- | --- |
| a second `TAG:` further along a bullet's line | two messages written as one |
| a `TAG:` on an INDENTED line | an ask hidden where the tag check does not look |
| more than one `**headline**` on a line | the shape is `TAG: **the one ask** - what you did` |
| a `-` list under a bullet | the elaboration is a sentence or two about THIS ask |
| prose counting other work in ("plus two more items") | that work gets its own headline he can reply to |

- **`boardctl note 'A: x' 'B: y'` is two items, not one.** The argv is split at
  each tagged argument (`_note_text`) instead of joined with a space, which used
  to land one bullet claiming to be both.
- **What it deliberately does not do is guess at prose.** Two asks written as
  two plain sentences pass. The prompts carry the rest — `boardwork.RULES` /
  `WORKER_PROMPT` rule 9 and board-watch's rule 6 state it in the same words the
  refusal does, and `board-test.py` asserts both still say it.
- **His own words are DATA, not prose these checks read.** The mechanical
  failure templates interpolate what he typed into the box, and a note saying a
  worker DIED must never be refused for how he phrased the thing it died on. So
  they pass it through `boardparse.oneline(..., code=True)`, which collapses it
  to one line and hands it over as a code span; the checks skip a span, so his
  `**` and his tag words reach the board unedited. The plain form (no span)
  strips both and is for text that has to sit inside a `**headline**` — a glob
  like `apps/**/qml` is why that is a flag and not a blanket strip.
- The newline collapse also closes a latent one: a multi-line `{task}` used to
  make the template's second line an untagged bullet, and the whole
  worker-died note was refused. Nothing then said the worker had died.
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
- **The sub-heading is `SectionHead`, one rung quieter**: not `accented`, so it
  is the dim label plus the border hairline. No new chrome, and **it is a
  heading and NOT a count**: no tally, no badge, no severity colour, exactly as
  the flat list had none.
- **EVERY heading on this page collapses, and they all do it the same way** —
  [his, 2026-07-30] *"all sections / subsections should be collapseable like the
  top decisions one"*. One component (`SectionHead`), one gesture (the whole
  band), one persisted map (`Settings`' `collapsed`), one container idiom
  (`Item { visible: !collapsed; implicitHeight: visible ? col.implicitHeight : 0 }`).
  So the sub-headings lost the `interactive: false` they shipped with, and
  `to do, when you feel like it` and each DAY in `landed` became bands instead
  of bare dim lines. The keys are namespaced by what they name and never by
  position — `todo:<TAG>`, `landed:<date>` — because a group's index changes
  with what is on the board and would hand one group's fold to another. The
  untagged group has no band, so it has no fold: there would be no way back.
- The empty state still keys off the section being empty, and an empty section
  draws no headings because there are no groups. What it SAYS is now one line —
  see the empty state below.

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

### ...and WHO put it there, on the line above the time

*"every entry on the board should record WHO wrote it - which program or agent
put it there"*, drawn in the message gutter above the time. `<!-- by: Marbas -->`
— the twin of `placed:` in shape, ownership (`boardparse._BY`), invisibility to
markdown and `reader`, and drawing (same trailing-edge cluster, same `dim` rung,
same reserved column). Three things are specific to it:

- **It is the agent's NAME when an agent wrote it**, because that is the word he
  reads for an agent everywhere else on this board. `boardmove.whoami()` resolves
  it **from the environment** (`BOARD_AGENT_ID`, which every worker's `boardctl`
  run already carries) — so **no writer needed a second channel**, and the whole
  write side is `boardmove.note()` + `boardmove.ask()`. The `by=` argument is
  only the FALLBACK for a caller with no agent identity at all (`boardctl`
  passes `"boardctl"`, `board-watch` passes `"board-watch"`); an agent behind
  the same call outranks it.
- **`agent_id` is NOT authorship and must never be read as it.** It names the
  agent a result is FROM, which is what retires that agent's summon note
  (`drop_summon`). Reading it as the author stamped every `board-watch` failure
  note with the DEAD minister's name — a bullet whose own text says that
  minister recorded nothing, attributed to it (fixed 2026-07-30; the stamp comes
  from `whoami()` with no argument, and `board-watch` names itself through
  `by=`).
- **Nobody resolving means NO stamp.** `by_now()` returns `""` for an empty or
  unspellable author rather than writing `unknown`, so "nothing recorded it" and
  "written before this existed" are one state in the file and one on screen. The
  gutter slot **collapses to zero height** when it is empty — an unattributed
  entry draws exactly as it always did, and never an empty row.
- **`by:` goes ABOVE `placed:` and that order is load-bearing.** For a WAITING
  bullet, `placed:` is the line that CLOSES the bullet's span, so a `by:` written
  under it would fall outside `todo_span()` and be left behind by a removal as an
  orphan comment.

**What is not attributed yet, and it is fine that it is not.** `board-watch`'s
results go through `note_on_board()` -> `boardmove.note(..., by="board-watch")`
and are attributed to the watcher, but its own housekeeping bullets — `give_back`'s `why` and
`reconcile`'s idle-row INFORMATION — are written by whichever tick noticed, and
nothing in that process names itself. They ask `whoami()` and land unstamped
when it answers nothing; **no `by=` fallback is passed there on purpose**, since
naming a program that may not be the caller is an invented attribution. Anything
in `home/srvs/board-watch-files/` that writes the store by some other path is
unstamped too, and that file is outside this tree. The parser is built for
exactly this — an unstamped entry is normal, not a defect.

LANDED is deliberately out of scope: its rows are table cells with no gutter to
draw in, and a commit already records its own author in git.

### ...and WHICH OF HIS ASKS it came out of

[his, 2026-07-30] *"information messages should display a truncated version of
the original user prompt that spawned the message between the top line and the
second verbose line"*. A third stamp, `<!-- for: ... -->`, the same shape and
the same optionality as the two above it, and it sits FIRST of the three (above
`by:`, above `placed:`, inside the bullet's span).

**The text is HIS, and it is never an agent's paraphrase of his.** The chain is
by construction, so nothing has to remember to pass it:

1. He types into the box; `board-watch` registers the summoner under those
   words (`boardagents.register`, `kind="orchestrator"`).
2. `boardwork.order_of()` reads that card — **and only a summoner's card**: a
   worker is registered under the TASK it was handed, which is an agent's words
   about his and must not be quoted back at him as his ask.
3. `boardwork.dispatch()` puts it on the task record; `_spawn_worker` exports it
   as **`BOARD_ORDER`**, which every `boardctl` the worker runs inherits.
4. `boardparse.for_now()` reads that variable and writes the line. `boardctl`
   seeds the variable for a summoner writing its own `SUMMONED` lines
   (`_seed_order`).

Capped at `ORDER_CHARS` (200) and collapsed to one line at the WRITE, with any
`-->` in it broken up — a stamp that closed the comment early would spill the
rest of his sentence into the store as prose. Drawn as one `dim` line between
the summary and the elaboration, cut in CHARACTERS with an ASCII `...`
(`win.clipTo`; `Text.ElideRight`'s U+2026 is not in the font, §2.3). Nothing
recorded, nothing drawn — a bullet nobody dispatched, one typed by hand, and
every bullet written before this existed all draw exactly as they did.

## The no-pressure requirement is a design constraint

He asked for this because the terminal chat log made him feel he had to answer
in the moment: *"i feel pressured to act quickly when really i dont need to"*.
So, as binding as the parse:

- **No counts, no badges, no ages, no deadlines, no sort-by-urgency.** A tally
  of open questions is a debt; there is not one anywhere in this app. The
  `placed` time above is not an exception to this and must not be turned into
  one: an absolute time is a fact about the past, an elapsed one is a clock
  running against him. **The ONE exception is the working duration on a live
  agent card** (`working for 4 minutes`, `boardphase.worked_line`) — his own
  explicit ask, 2026-07-29, replacing the absolute spawn stamp he had asked
  for that morning. It is granted by the person this rule protects, and the
  reading that keeps it coherent: a running agent's clock counts against the
  AGENT, not against him. Scoped to exactly that line; nothing else may count,
  and nothing may cite it as precedent.
- **Nothing is drawn in the `warn`/`crit` ramp.** Those colours mean a machine
  fault on this desktop (§8.1, §9.3); a question is not one.
- **Every decision draws its own `if unanswered` line, always** — never behind a
  fold, never abbreviated. That sentence is what makes walking away safe, and it
  comes from the file rather than from this app's judgement.
- **Nothing leaves NEEDS YOU because board says so.** The store's own rule: an
  agent may add items and record what landed, but only he resolves a decision. board ticks boxes and writes his sentence; it never
  deletes an item. An item leaves NEEDS YOU only once **he** has answered it and
  work has actually started — see *Answering here now STARTS something*, below.
  That is not this app doing it: `boardmove.py` is, on behalf of whoever is doing
  the work, and the GUI still has no move in it at all.
- The empty state is ONE sentence, `decisions brought to you from Solomon.`, in
  `Theme.dim` with the section rule above it unchanged, so a board with nothing
  on it reads as finished rather than as broken. It is the state he will see
  most often. [his, 2026-07-29] every other line that used to be down there is
  gone: the second placeholder (`nothing here expires - come back whenever`) and
  — while the section is empty — the store's own framing paragraph, which would
  be a second introduction to nothing.
- **The header has no label.** [his, 2026-07-29] *"just have the line and
  collapse toggle"*: `SectionHead { label: "" }`, so the band is the accent rule
  and the `[-]` and nothing else. The whole band has always been the MouseArea,
  so the toggle keeps its hit target; `SectionHead` drops the second 8px gutter
  an empty label would leave behind it (docs/DESIGN.md §5.4).

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
something he already gave, so as work starts the decision is **taken off the
list** — lifted out verbatim into a stash outside the store, with nothing
written in its place — and the commit reaches LANDED when it lands. (There was
an `## IN FLIGHT` section carrying a row for it until 2026-07-30; see
`boardparse.py`'s note for why it went and what took its three jobs.)
`boardmove.py` is the whole mechanism and its docstring is the authoritative
statement; the short version:

```bash
apps/board/tools/boardctl.py start 4 --where 'apps/player/**'   # off NEEDS YOU
apps/board/tools/boardctl.py land --commit a3c2aac --what 'player: dim the art'
apps/board/tools/boardctl.py land 4 --commit a3c2aac --what 'player: dim the art'
apps/board/tools/boardctl.py back 4 --why 'blocked on the FOCUS signal'
apps/board/tools/boardctl.py note '**Relaunch `player`** - live source.'
