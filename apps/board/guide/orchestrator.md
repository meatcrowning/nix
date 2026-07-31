# The orchestrator's half (`boardwork.py`): spawning, the cap, the handoff

*How an ask becomes ministers: the box, the concurrency cap, handing an item to a worker already in those files, what every spawn is told and what it starts with, the transient unit, and the summon note's life.*

Part of goetia's guide — the map and the shared
rules are in [`../AGENTS.md`](../AGENTS.md); read that first.

---

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
- **NOTHING IS WRITTEN IN ITS PLACE** [2026-07-30, his call]. There was an
  `## IN FLIGHT` section holding a `| what | where | notes |` row for every
  started decision, and it is gone: the triangle already draws what is running
  from the agents' own processes, LANDED is computed from git, and the row's
  third job — his answer read back to him — is on the stash, where the hand-back
  reads it. What the section actually did in practice was accumulate; the
  bullets below on stranding are what is left of it. Nothing about that changes
  the no-pressure rule: there is still **no start time, no age, no count**
  anywhere he can see. The stash records one because reclaiming a dead agent's
  item is machine business; it never reaches the file.
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
- **`land` needs no selector, and requiring one was a real bug.** It used to
  need an IN FLIGHT row, which only a decision agent had (`start()` made it); a
  WORKER dispatched out of the box never did, so every commit the fan-out
  produced was unrecordable — `land` refused, `note` was all a worker could
  reach, and LANDED sat at 2026-07-28 while a run of board commits went in over
  the next day. He noticed: *"are you sure the landed section functions? it's
  showing what look like older commits"*. `--what` carries the sentence now,
  always, and a selector only names the STASH to close out — a decision agent
  finishing its own item. One that matches nothing is not an error, which is
  the whole shape of that bug refusing to come back. The worker prompt says to
  call it once per commit.
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
- **An item cannot be stranded.** Three ways back onto the board: the agent
  lands it, the watcher hands it back when the agent exits badly, or
  `boardmove.reconcile()` — run at the top of every board-watch tick — sees the
  owning pid is gone and hands it back itself. Worst case, one timer interval.
  (There was a fourth, `boardctl stall <row>`, and it existed only because the
  IN FLIGHT rows nothing here owned had no other exit. It went with them.)
  A hand-started item (`boardctl start` with no `--pid`) is not
  reclaimed on liveness — nothing can tell whether that session is still
  thinking — **but it is reclaimed on AGE**, after `boardmove.UNOWNED_STRAND_S`
  (4h, `BOARD_UNOWNED_STRAND`). Without that bound "not ours to reclaim" meant
  *forever*: two pid-less stashes from 2026-07-28 were still drawing `unowned`
  agent cards a day later with nothing in this tree able to collect them, and he
  spotted it — *"some residual agents left that should've been swept up"*. The
  bound lives in `_abandoned()`, deliberately **not** folded into `_alive()`:
  that is THE liveness rule for the whole tree and there is one definition of
  "running" on purpose, so answering "dead" for a record that merely never named
  an owner would make every other caller lie. Its bullet says *nothing was
  working* it rather than that an agent died — there was never an agent, and
  inventing a death to explain a row is the confident lie this tree refuses
  everywhere else. Hours, not minutes, because what is being waited on is a
  person or a session at a terminal: it sits well clear of both board-watch's
  45-minute agent cap and `ESCALATE_AFTER_S`.
- **All three are keyed on the STASH, and the stash is machine-local — which is
  why the section had to go.** `board.md` syncs both ways;
  `~/.local/state/board/inflight/` does not. So from either machine, a row the
  *other* one started was indistinguishable from a row nobody started — and so
  was a row written before the stash existed, or one added by hand. `reconcile()`
  covers what this host started and nothing else, so IN FLIGHT could only ever
  grow: reading it on 2026-07-29 he said it *"doesnt update at all its still got
  old stuff in it"*, and four of its five rows were ones no mechanism here could
  remove. Nothing accumulates now, because nothing is written — and a stash the
  other machine owns is simply not this host's business, which it always was.
  **Do not reintroduce a synced record of what is running.** The two hosts
  cannot reconcile one, and that is the whole finding.
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
- **...AND ONE ASK IS OFTEN SEVERAL JOBS TOO** [his, 2026-07-29]. The rule above
  counted his sentences; this one says not to stop there. Solomon now reads each
  item for the AREAS it lands in — panel QML, plugin C++, an app's Python, the
  window config, a doc — and gives **each area that does not share files with
  another its own worker**, one sentence or not, "same feature" or not.

  It is a COST rule, and the cost does not look like one: a session's input grows
  with the SQUARE of its turns, because everything already said is re-read on
  every turn after it and a worker's own output is ~85% thinking. Measured on
  book 2026-07-29 — a 200-turn worker cost ~50M input tokens; four 50-turn
  workers doing the same total work cost about a quarter of that, and finish in a
  quarter of the wall-clock. **Fanning out costs nothing at startup**: the floor
  is paid once per turn, so 4 x 50 turns and 1 x 200 turns pay the identical
  startup bill. That symmetry is what makes "one worker, it will get there" the
  wrong instinct even when it is true, and it is why the prompt spells the
  arithmetic out instead of just saying to split more.

  **The axis is DISJOINT FILES and the sentence above outranks this one.** Two
  agents in one file is still the thing this system is built not to do, so the
  split goes where the file sets do not intersect and `--where` carries a
  non-overlapping glob per worker. Sequential pieces are still two workers — B's
  task text says to pull Marbas's commit first, and B queues behind the cap
  meanwhile. Three guards against over-shredding: a one-file change is one
  worker and always was; the cap queues rather than fails, so a spare dispatch
  costs latency and not correctness; and the prompt says in as many words not to
  manufacture areas to split on.
- **The box writes down the path that already existed.** `boardagents.send()`
  with no agent named — the same one a note to a running agent takes, with the
  same conservation property (a message is in exactly one of `to/`, `queue/`,
  `taken/` at every instant, moved only by `os.replace()`). There is no second
  write and there must never be one; the harness asserts conservation after the
  GUI path as well as the CLI one.
- **The footer says where it WENT, never what will come of it.** `in the inbox -
  ctrl+z takes it back until a summoner acts`. Nothing fires immediately: the
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

**A handoff is reported as `COMMANDED: <Name>`, a dispatch as `SUMMONED: <Name>`**
— his rule, 2026-07-29, and the distinction is the point: he can tell off the
board whether a new agent was started or an existing one was given more work.
The tag is uppercase, immediately before the name, and what follows the `(id)`
is `to` or `for` plus a few words on what the worker went out for —
`SUMMONED: Marbas (`wd690a4`) to add commit times`. **Never a "nothing landed
yet" tail**: he does not want it written, silence says it. The dozen-word
summary cap (`boardparse.SUMMARY_MAX_WORDS`) still binds and that tail spends
most of what the headline leaves.
Both words are read by `boardparse._SUMMONED` — in either case, the lowercase
verbs `summoned`/`commanded` this replaced still match, because the store holds
notes written that way — so a handoff note is retired by its worker's result
exactly like a summon note; a wording change that skipped the parser would leave
every handoff note sitting under the result forever, announcing work he has
already been told the end of.

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
- **It is still a START, not a result** — reported as one `COMMANDED` line
  naming the worker, inside the same note budget as a dispatch.

The neighbouring rule is the same one read from the other end: two items in ONE
message that touch the same files are one `dispatch`, not a dispatch and a
handoff.

- **And the tool itself notices a missed handoff: `dispatch` WARNS on `--where`
  overlap with a live worker.** `boardwork.overlaps()` cuts each whitespace
  token of both globs at its first glob character and flags any pair of cleaned
  prefixes where one startswith the other; `dispatch()` attaches the matching
  live workers to the record (`rec["overlaps"]`) and `boardctl dispatch` prints
  a warning line naming the worker and suggesting `inbox send --to <Name>`.
  **WARN ONLY, never a refusal, and dispatch behaviour is unchanged** — a
  prefix match is a heuristic and a near-miss must not block real work. The
  prose rule (run `agents` first, hand over what is genuinely the same work)
  still binds; the orchestrator's prompt says the warning is that check firing
  after the fact. `tools/board-test.py` → `test_overlap` covers both halves.

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

The decision agent's prompt (`board-watch.py`) quotes the **same `RULES`
block verbatim** (since 2026-07-29 — it kept a hand-written copy of rules 1-5
before that, which drifted exactly the way the `RULES` comment warns a
paraphrase does, and never gained rules 6-7 at all); only the board-specific
closing rules (record with the tool, the inbox) stay its own. It is still not
a dispatch target. Beyond what the section above lists, `RULES` also carries
the standing constraints the old orchestrator briefing had and this system
lost for a while: **every rebuild is serialized behind the shared flock**
(`/tmp/claude-1000/-home-lam-nix/rebuild.lock` — up to five agents may rebuild
here and two switches must not race), **the per-area ritual for getting an
edit live** (seed-once files edited in BOTH copies with `seed-drift.sh` before
and after, the `Theme.qml` bump, `hyprctl reload`, the hyprvtb version bump,
never bare `qs`, never scripting hyprvtb Lua actions), **the IPC/log
verification toolbox**, and **saying what the other host must run**.

### What each spawn STARTS WITH, before it reads a line

`boardwork.context_flags(role)` is the other half of `role_flags` — not which
model, but how big the prompt already is when the model gets it. Both spawners
call it for the same reason both call `role_flags`: a flag set in one and not
the other is invisible until the numbers stop matching.

**Why it is a knob at all.** Measured on book, 2026-07-29: a real worker spawn
started at **51,425 tokens**, and that floor is re-read on *every turn* of the
session. Over one day — 215 sessions, 11,987 assistant turns — the floor alone
accounted for **~600M of 1,510M input tokens, 40%**. A token cut here is paid
back once per turn, and the long ministers run 150-350 turns each.

| | worker floor |
|---|---|
| before | 51,425 |
| `--tools` restricted to `boardwork.TOOLS` | -10.5k |
| `--disable-slash-commands` | -2.2k |
| superpowers off (`MINISTER_SETTINGS`) | -2.0k, and it arrived TWICE |
| **now** | **36,417 (-29%)** |

`--tools` is the big one, and it is a *different axis from `ALLOW`*: `ALLOW` is
a permission filter and the schema loads either way, while `--tools` decides
which built-in tools exist at all. It drops the deferred-tool block, `Workflow`
(~6k of description by itself), `Artifact`, `ScheduleWakeup`, `ToolSearch`,
`AskUserQuestion`, `ReportFindings`, `Skill`, and the Task/todo reminders that
fire every few turns. `Task` stays — a minister that cannot fan out reads
serially in its own context, which is the expensive shape — and so does the web
pair, which costs ~1k and has no recorded use: a minister sent at an upstream
API it cannot look up flounders for far more than that.

**`--exclude-dynamic-system-prompt-sections` is in no row of that table and is
the reason it is worth having anyway.** It moves cwd, env, memory paths and git
status out of the system prompt, so the prefix is identical across spawns and
each one is a pure cache READ. Measured back-to-back: `read 36,417 + write 0` on
the second spawn, against `read 14,736 + write 17,292` without it — on a prefix
any other agent's differing git status would have broken regardless. Writes cost
1.25x and reads 0.1x, against ~200 spawns a day.

**SOLOMON IS EXEMPT FROM EVERYTHING BUT THAT ONE FLAG.** [his, 2026-07-29]
*"def disable superpowers for ministers but solomon should still have it
enabled"*. The split follows the shape of the two runs rather than the quality
of the advice: the superpowers injection is ~2k and arrives twice, plus ~2.2k of
skill listing, so it costs a 6-12 turn orchestrator ~50k a run and a 150-350
turn minister ~1.2M. And its first instruction — invoke a skill before
answering, brainstorm before building — is advice for somebody with a human to
check with; a minister has none, has its whole task in one prompt, and has
`RULES`. Passing `--tools` to Solomon would also have taken its skills away by
the back door, since `Skill` is not in the list, leaving an injected text at war
with its own tool list. Solomon measures 53,281 -> 52,984: nearly nothing, and
nothing risked.

`--settings` **merges over** `~/.claude/settings.json` rather than replacing it,
which is what makes the plugin switch safe: the SessionStart host-id hook and
the PostToolUse inbox hook both still fire, and an inbox note reaching a worker
mid-flight is load-bearing for rule 11.

**The floor is not the whole bill.** It is ~35% of it (measured across 25
long minister sessions on `top`, 2026-07-30: 3,872 turns, an average floor of
39.1k against an average final context of 154.6k, 438.6M input tokens re-read
in total). The rest is that context grows over a long minister and every turn
re-reads all of it, and what fills it is **the agents' own output — 81% of the
growth, nearly all of it thinking**; tool results are the other 19%. Shortening
sessions is the other lever and it is not this one.

**The floor is not the whole STARTUP either — a nested `CLAUDE.md` used to
double it, silently.** [measured on `top`, 2026-07-30] A minister's floor is
36.5k, of which 16.5k is the CLI itself (system prompt + the nine `--tools`
schemas) and ~20k is repo context — the root `AGENTS.md` (11.7k), `~/CLAUDE.md`
(1.2k) and `MEMORY.md` (3.7k). But **the nested `CLAUDE.md` symlinks were
injected in full the moment an agent opened any file beneath them**, and then
re-read every turn for the rest of the session. Reading a 3.6 KB
`home/prog/quickshell-files/Theme.qml` cost **45.8k tokens**; the identical
read of a file outside those trees cost 27.7k, the difference being
`home/prog/AGENTS.md` and `quickshell-files/AGENTS.md` swallowed whole for a
900-token file. The three nested symlinks are gone (same measurement after:
**27.9k**, -17.9k *per turn*); the guides themselves are untouched and rule 5
still sends every minister to the nearest one, in slices. **Never re-add a
nested `CLAUDE.md`** — see `~/nix/AGENTS.md` -> "How to work here".

**And a guide can be a token bomb on its own.** This one was a single
2,598-line file until 2026-07-30 — past `Read`'s 2,000-line cap, so a minister
sent at goetia paid ~44k *and* got a truncated guide. It is an index plus
`guide/*.md` now. When a nested guide here goes past ~700 lines, split it
rather than letting the next agent swallow it.

**One row of the table above has expired.** `--disable-slash-commands` measured
-2.2k on book in 2026-07-29 and measures **~0** on `top` on 2026-07-30 (36,535
with it, 36,312 without — noise). The CLI stopped listing skills in a headless
run. The flag is harmless and stays; the saving is no longer real, and the
number is kept only so nobody re-derives it as a win.

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
  WAITING ON YOU TO DO is `SUMMONED` (a start is a fact, never a result — and
  since 2026-07-30 that word IS the tag, with no `INFORMATION:` and no subject
  in front of it), then the worker's **name**, its coded id in
  parentheses because that is what its log is called, then `for`/`to` and a few
  words; one more line for anything it asked, tagged `QUESTION:`. The tag
  is *inside* this budget and not a second rule beside it — the line is still
  one line. The prompt states that as a
  budget — *one line each, about a dozen words after the tag at the most, no
  second paragraph*, the same number `check_short_summary` enforces — because "concise"
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
- **A transient platform death is REQUEUED once, not failed** (2026-07-29). A
  worker that recorded nothing and whose log ENDS on an API 5xx/overload line
  (`boardwork.TRANSIENT_RE`) died at the platform's hand, usually before its
  first tool call — during the outage that motivated this, two workers' whole
  logs were one line each (`API Error: 500` / `529 Overloaded`) and the board
  asked him to re-type sentences the system still held verbatim. `reap()` puts
  such a task back in `pending/` with a `retried` mark and `promote()` starts
  it again the same tick; the second death is final whatever its cause, so it
  cannot loop. A worker that reported *anything* is `done` as before, never
  re-run — re-running half-landed work would commit it twice. board-watch's
  `spawn` gives the two runs it waits on (decision, orchestrator) the same
  one-retry on the same pattern.
- **A dead worker's TAKEN inbox notes go back to the queue** (2026-07-29).
  `sweep()` rescues a note nobody READ; a note a worker `inbox take`-d used to
  die with the worker — worker Vual took a handed-over item at 11:27, died on
  an API 500, and nothing flagged the loss. `reap()` now calls
  `boardagents.requeue_taken()` for every worker it files as FAILED and every
  one whose task it requeues on a transient death: the messages sitting in
  `taken/` whose `movedBy` is that worker move back to `queue/` (state
  `requeued-from-dead-worker`, same `os.replace`, exactly-one-directory
  invariant intact), so the next tick drains them into a fresh orchestrator.
  The rescued notes ride on the reaped record as `notesBack` — the tuple
  `reap()` returns keeps its three-value shape, so a board-watch deployed
  before this change does not crash unpacking it — and board-watch's tick logs
  how many went back. A worker reaped as DONE keeps its taken notes: it
  reported, so it is presumed to have handled what it took. **The residual
  gap, stated honestly: a worker that reports something, THEN takes a note,
  then dies is reaped as done, and that note is presumed handled when it may
  not have been.** Nothing covers that ordering; watch for it before trusting
  a `done` worker with an unacted-on handoff.

### ...and the summon note GOES when the result arrives

*"once an agent give the board a completed, partial, etc message - its related
summon information message should be removed since the user would already know
that part."* [his, 2026-07-29]

A start and a result are two bullets about one piece of work, and the start is
only true until the result lands. So posting a `COMPLETION:`/`PARTIAL:`/`FAILED:`
(`boardparse.RESULT_TAGS`) retires the `SUMMONED <Name> (`<id>`)` note that
announced it — **or the `COMMANDED <Name>` one**, which is
the same announcement for a worker that was already running, and either of them
in the pre-2026-07-30 `INFORMATION: ... SUMMONED: <Name>` shape — in the **same**
read-modify-write as the
insert — one edit under the lock, so the board is never briefly holding both and
a `boardrecent` merge never sees a half-state.

- **It lives in `boardmove.note`, not in `boardctl`.** There are two writers of
  a result — `boardctl note` for a worker that finished, board-watch's
  `WORKER_FAIL` for one that died mid-sentence — and a rule implemented in one
  caller is a rule that is true in one caller. `note(agent_id=...)` names the
  agent the result is FROM; it defaults to `BOARD_AGENT_ID` (the same key
  `mark_reported` reads), and board-watch passes it explicitly because there the
  process writing the failure is the watcher, not the worker that failed.
- **The ID matches first, the NAME only second**, and a name match is accepted
  only for a summon note carrying no id at all: a name can be moved off a live
  agent (`boardagents.pick_name`), an id never is.
- **Ambiguity is a refusal to act.** Two summon notes naming one id, or none,
  and every one of them stays. A wrong deletion loses something he cannot get
  back; an undeleted summon note is a line he has already read. Nothing else is
  reachable — a `QUESTION:`, a decision, an ordinary `INFORMATION:` fact and the
  result itself are all outside the candidate set by construction
  (`boardparse.summon_of`).
- The bullet goes **whole**, its wrapped continuation lines and its
  `<!-- placed: -->` stamp with it (`remove_todo`), and the removal happens
  BEFORE the insert so the result bullet cannot match itself.
- Harness: `test_summon_cleared` in `tools/board-test.py`.
