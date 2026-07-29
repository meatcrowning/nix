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
## LANDED                 `### <date>` groups of | commit | what | when |,
                          plus prose. `when` is the commit's own local time in
                          12-hour form and is OPTIONAL in both directions
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
| the orchestrator | splits the input up; `dispatch`es workers or `ask`s him. It does not build anything | `boardwork.ORCHESTRATOR_PROMPT` |
| each worker | **its own systemd unit**, capped, works/tests/commits/pushes, **never rebuilds** | `boardwork._spawn_worker` |
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
  WAITING ON YOU TO DO is the subject, the worker's **name** (its coded id in
  parentheses, because that is what its log is called), and that nothing has
  landed yet; one more line for anything it asked. The prompt states that as a
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
  **gets a bullet in WAITING ON YOU TO DO quoting its task**. That bullet is the
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

### A worker has a first name, and the name is what he reads

*"can you give the workers regular human names? you can still keep the coded
names if you'd like but i think itd be interesting to have them referred to by
regular names"*. So every worker is `Rosa`, not `w1a2b3c`, on the card, in
`boardctl` output, and in the bullet the orchestrator leaves on the board.

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
  running agent already answers to, so a note he addresses to Rosa is never
  ambiguous. Above 24 live agents a name repeats; the cap is 4.
- **A card draws the name and never the id.** It sits in the same 7-cell label
  column as `says` and `doing`, so the three lines line up as one block —
  which is why the pool is short ASCII names (§2.1's cell, §2.3's cmap).
- **Nothing that has nobody on it is given a name**: a task queued above the cap,
  a decision he answered, an interactive session. Same rule as the inbox box —
  a name is a claim that somebody is on it.
- `boardctl.py inbox send --to` takes either the name or the id.

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
| to a RUNNING agent | into that agent's inbox; the row keeps showing it as `waiting in its inbox` until the agent takes it | `left in Rosa's inbox - Rosa reads that between steps` (`its`/`it` for an agent with no name) |
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
  travels with his sentence (`about the `to do` bullet "...": ...`), because
  "yes, do that one" means nothing to the orchestrator that reads it half an
  hour later. §7.2's ordering still holds — the thing he does most is first,
  read-only next, the undo, then the one destructive entry behind its separator.
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

`tools/board-test.py`, offscreen, nine layers (237 checks). Three of them are
new and are the ones to read first if the fan-out misbehaves:

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
  queue oldest-first; **every worker has a first name** that is unique among the
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
`reply` is the top entry on that row's menu, opening the row's own box and
sending down the queue with the chore quoted), **the moves**
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
