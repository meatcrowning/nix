# The triangle: what a minister's card says

*The `agents` section — the only part of the window that is not the store. A summon becoming a card, names, claimed vs observed work, the rising card, and the output drawer.*

Part of goetia's guide — the map and the shared
rules are in [`../AGENTS.md`](../AGENTS.md); read that first.

---

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

### A SUMMON IS NOT A CARD until the agent is really up

[his, 2026-07-30] *a card should appear only once the summon has actually
completed* — a minister's card was showing while Solomon was still summoning it.
`_spawn_worker` registers the instant the spawn call returns, and that return is
an `execve`, not a running agent: `systemd-run --service-type=exec` came back in
**19 ms** (measured, book, 2026-07-30). A `claude` that then died on an API 500
— which is exactly what the 2026-07-29 outage did — left a card behind for an
agent that never started. Same bug, both ends.

- **The record is written UNCONFIRMED** (`boardagents.register(confirmed=False)`,
  set only by `boardwork._spawn_worker`). Every other caller knows its own
  process is up and leaves the default, and a record written before this
  existed reads as confirmed — so nothing that was on his board disappears.
- **The proof is the agent's OWN TRANSCRIPT.** `boardagents._confirmed()`
  publishes the row once `boardphase.transcript()` finds the session file we
  named ourselves; only a running agent writes one. Confirmation is **sticky** —
  a transcript that rotates away must not un-draw a live card.
- **`CONFIRM_GRACE_S` is a bound, not a gate.** Past it (20s) a still-LIVE
  record is drawn whatever the transcript says: hiding work that genuinely
  exists is the worse failure, and the observed line already says `unlinked`
  honestly. Well under `boardphase.START_GRACE_S`.
- **Only the DRAWING skips it** — `boardwork._drawable()`, used by `cards()` and
  `groups()`. `boardagents.agents()` returns every record, so the concurrency
  cap, `reap()`, `sweep()` and `--to` resolution all see a worker that is
  starting up. Filtering in `agents()` instead would double-start it and reap
  it as dead in the same tick.
- **A spawn that never started registers nothing** and stamps its own id onto
  the task file anyway. Without that stamp `reap()` skips a `taken/` record with
  no `agent` and the task sat there forever, unworked and unreported; with it,
  the next tick files it under `failed/` and his board gets the `FAILED:`
  bullet quoting his task. A death between the two steps is the same path.
- Harness: `test_summon_confirmed` in `tools/board-test.py`. The rest of that
  file sets `BOARD_CONFIRM_GRACE=-1`, since a stubbed worker writes no
  transcript to be confirmed by.

### A worker has a name, and the name is what he reads

*"can you give the workers regular human names? you can still keep the coded
names if you'd like but i think itd be interesting to have them referred to by
regular names"*, then: *"i want the names of agents to be taken from the names
of demons in the lesser key of solomon"*. So every worker is `Marbas`, not
`w1a2b3c`, on the card, in `boardctl` output, and in the bullet the
orchestrator leaves on the board. The pool is the Ars Goetia's 72 — complete,
in the traditional order (1 Bael ... 72 Andromalius), and keeping the short
spellings the pool already used where they overlap (`Marax`, `Haures`,
`Glasya`) so a worker running under one still matches its own name. [his,
2026-07-29 — it ran 56 before, padded with Theurgia-Goetia / Ars Paulina
names, until he asked for the full seventy-two.]

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
  subject at all (below), so the name column beside the title is the fallback
  for a card whose agent has said nothing. A name is **ASCII letters only**
  (§2.3's cmap — `Bune`, never a diacritical spelling), and the column
  **measures** (`AgentRow`'s `nameW`, `max(7, len+1) * cellW`): the full-72
  pool runs up to `Andromalius`'s eleven characters, and a long name costs the
  title cells on its own card and nothing anywhere else. `board-test.py`
  asserts the pool's shape.
- **Nothing that has nobody on it is given a name**: a task queued above the cap,
  an interactive session. Same rule as the inbox box —
  a name is a claim that somebody is on it. The one exception is Solomon, and
  it is an exception on purpose (below): he is a ROLE that is always there, not
  a claim that anything is in flight, and his row says `ready` in so many
  words.
- **A decision agent has a name too — because somebody IS on it.** [his,
  2026-08-01] two cards (an answered decision each) sat in the triangle with no
  name on them while the minister board-watch had spawned worked on, and he
  came back to have it fixed. A decision HE answered has a real stashed process
  on the job, so the "claim that somebody is on it" rule is satisfied — the
  name is derived off the stable stash key in `boardagents._stash_agents`
  (the same `name_for` fallback a record written before names existed uses), so
  the app, `boardctl` and the agent agree with nothing persisted and the name
  never changes between two polls. It is the QUIET ones with nobody on them
  that stay nameless: a queued task and an interactive session.

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
- **He is seven characters, and he is not truncated.** That is what first
  widened `AgentRow`'s `nameW` from a hardcoded `7 * cellW` to a measured
  `max(7, len+1) * cellW` — a measurement the pool itself now leans on, its
  names running past six since it grew to the full 72.
- **He is first, whatever was born when.** `boardwork.cards()` pins every
  orchestrator row above every worker; birth-order still governs everything
  below. Two overlapping orchestrators (successive things typed close together)
  are BOTH Solomon and both pinned — one role, briefly doing two things, and a
  message addressed to him reaches a live one.
- **The row exists with nothing running.** `boardwork._idle_orchestrator_row()`
  — `state: "idle"`, no claim, no observed line, and **no id, so no inbox**:
  a note left for an orchestrator that does not exist would have nobody to read
  it, and the box at the top of the window already queues one for the next.
  `describe()` returns `""` for it: [his, 2026-07-29] the resting card is TWO
  lines — `Solomon awaits`, then `summons a minister to do your bidding.` — and
  the third, which said what you type at the top of the window goes to him, is
  gone. The row's own `detail` is `""` for the same reason, so the two things
  that can feed that line cannot disagree.
- **So the list is never empty**, and the triangle's empty sentence is gated on
  `Main.qml`'s `nothingRunning` (any card that is not the standing row) rather
  than on the list's length.
- `boardctl.py inbox send --to` takes either the name or the id.
- **His card names his MODEL too, same as a minister's** — [his, 2026-08-02]
  *"Solomon (deepseek v4 flash)"*, the same `"[name] ([model])"` a worker's
  row carries (`boardagents.agents()`, `tier_label`). It is not hardcoded:
  `board-watch._summon` resolves the pair he chose for the NEXT orchestrator
  run (`boardwork.orch_model()`, overridable by `BOARD_ORCH_MODEL`/
  `BOARD_ORCH_EFFORT` like every other role) once, at the spawn, and stamps it
  on the registration exactly like `_spawn_worker` does for a minister — so a
  future run on a different model shows that model with no code change. A
  record with no stamped model (a hand call, an old record) falls back to
  `boardwork.orch_label()`, the currently-chosen pair, rather than showing
  nothing — there is no `taken/`-style dispatch record for an orchestrator to
  join against the way a pre-tiering worker's card does. The idle standing row
  carries none: it is not a run, so there is nothing yet to name.

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
**So the third line is the ORIGINAL PROMPT the card was created from** — the
task it was handed (a worker's `rec["task"]`) or the decision it answers (its
title) — and it holds that fixed for the life of the card, never the user's
most recent answer: a note he sends later goes to the inbox below, not to this
line.

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
  **And before anything is observed at all, the LIVE card gets his own startup
  PAIR, in his order** — [his, 2026-07-29] *"Solomon wields the ring..."* while
  observed is `starting` (his transcript is a second away), then *"Solomon etches
  the circle..."* on `none` (it is there and nothing has happened in it).
  **The CIRCLE is his and the TRIANGLE is theirs** — [his, 2026-07-29] the
  magician stands in the circle and the spirit is bound in the triangle, so that
  line named the wrong shape. `triangle` is not retired: it now names the AREA
  THE MINISTERS RESIDE IN, the agents section under Solomon's summoner section,
  whose `SectionHead` draws the label `triangle` (the section **id** stays
  `agents` — it keys the collapse state, `jump()` and the `ag` titlebar cell).
  The "no triangles in this font" lines elsewhere in this guide are about the
  ASCII fold marker and mean something else entirely.
  `boardphase.orch_doing_line` owns both wordings and the ordering; scoped in
  `boardagents.agents()` to `kind == orchestrator`, running, so worker cards keep
  the honest bare placeholder. Same §10.6 argument as the idle row — a
  placeholder for the absence of observation, promoted from nothing, never a
  claim derived from one.
  **The brief initial line LEADS, and that is the whole point.** `481b524`
  collapsed the two states onto one sentence (`Solomon is getting ready`, which
  is what these two replace), so the initial line stopped leading and only
  reappeared past `START_GRACE_S` — i.e. AFTER the getting-ready one. Restored at
  his ask; his original complaint is untouched, because what he objected to was a
  *"dont know"* text flashing first and `starting` never reaches the unlinked
  sentence now.
- **SOLOMON IS HIS OWN SECTION, headed `summoner`, above `agents`** — [his,
  2026-07-29, asked twice] *"solmon should be in his own \"summoner\" section
  above the agents section"*. He was a row pinned to the top of the agents list.
  `boardwork.cards()` is unchanged and still owns the WHOLE ordering (the pin,
  birth order under it, the standing row when nothing runs); `main.py` splits that
  one list into `Agents.summoner` and `Agents.workers`, so the two sections cannot
  disagree about who is where. It is a titled `SectionHead` band like every other
  section, not a headerless card floated above the list — that band is what makes
  a section one on this page, and he said "section".
  Two recorded exceptions come with it (`docs/DESIGN.md` §20): **his text never
  takes the unfocused fade** — the summoner Repeater hands `AgentRow` the `Theme`
  tones instead of the window's `fgX` pair, which covers every label on the card
  at once (§3.1.1 says a leaf takes the tone it is given), and `leadTone` exempts
  him from the stopped-dim rung — and **his card has no 2px accent gutter**.
  `main.py`'s `section` readout and `jump()` treat summoner as part of the `ag`
  region: it is one region of the page and §12.1 keeps the titlebar vocabulary
  short, so there is no fifth cell.
- **SOLOMON'S OWN VOICE, for the two words he actually uses** —
  [his, 2026-07-29] `dispatching` reads *"Solomon is summoning..."* — with the
  animated ellipsis, because the state is live while the card says it; it read
  *"Solomon summons"* with no dots until he asked for both the wording and the
  animation — and `waiting` reads *"Solomon awaits <agent>..."*, which NAMES
  whoever he is waiting on. The name is resolved in `boardagents.agents()`,
  the only place that can see the other cards: one running named worker is that
  worker, several are `his workers`, none names nobody at all — never an empty
  cell and never the literal word "agent". `boardphase.orch_says_line` is the
  override and it is deliberately thin: every other word of his falls through to
  the shared table below, so *his* card cannot drift from a worker's.
- **THE VERB LINE IS `<name> is <word>`, AND THE DOTS ARE ON IT AND NOWHERE
  ELSE.** `boardphase.predicate()` is the ONE place a phase word becomes words on
  a card, every card included, so the verb form cannot drift between his card and
  a worker's. **Both halves of this are his, twice.** The verb was the simple
  present (*"it should just say 'researches...' or 'codes...'"*) for about an hour
  on 2026-07-29 and he walked it back the same evening: *"sorry, change the top
  line of an agents card back to 'is reading' or 'is coding' etc"*. Do not
  "restore" the simple present. The ticking `...` moved around the card that same
  evening and has SETTLED on the TOP line: it left the top line
  (*"take the animated elipsies out of the top line"*), then left the third
  (*"the third line ... should not have the animated elipsies or any elipsies at
  the end of it"*), and then he said it twice more — **"the only line of an agents
  card that should have the animated elipsies is the top line. no others"**. That
  is the rule now, and it is the LAST word: exactly one line ticks, the card's
  first, and every other line is drawn through `AgentRow.untick()` so a sentence
  an agent ended in dots of its own loses them entirely rather than sitting frozen
  at three. `says_line` is where the suffix is added; `says_detail` adds none.
  On Solomon's card the first line is his own (`orch_says_line`), so that is the
  one that ticks — and when a card has no claim at all, the observed line is
  first and inherits it.
  **And the words below never repeat the verb above them** — [his, 2026-07-29]
  *"if the verb at the end of the top line is the same as the verb at the start of
  the second line, then hide the verb"*. `_drop_repeated_verb` strips a leading
  phase word, case-insensitively, across every separator an agent actually writes
  (`-`, `:`, en and em dash, or none at all), at a word boundary only — a
  different verb is left exactly as written, and words that are ONLY the verb stay
  rather than leaving the line blank. `boardphase` is the one composition site;
  the panel has none.
  `TICKLESS` is which phase words leave even that line bare: `blocked` today,
  because a stall is not motion (§10, the same rule that used to scope the
  observed line's tick to `observed == "ok"`).
  **And the claim is TWO lines, not one hyphenated one** — [his, 2026-07-29] the
  card reads *"Marbas researches..."* and then *"the vtbclient parser"* under it.
  `says_line` is the verb line alone and `says_detail` is the words the agent
  gave, verbatim and never reformatted; both cross into QML as their own fields
  (`main.py`'s card dict — a new field that is not added there is silently
  `undefined` in QML and draws as nothing). It also puts the dots back at the end
  of a line, which the hyphenated form had cost.
  The `...` is three ASCII periods in the Python — never U+2026, which drops the
  line ~5px on the fallback font (docs/DESIGN.md §2.3) — and `AgentRow.qml`'s
  `tick()` cycles those three cells for ANY line that ends in them, on the
  existing `liveDots` timer (one step per desktop slide, §6.2). Animation is
  presentation and stays in QML: in the Python the string a test asserts on would
  change four times a second.
- **`starting` exists because "not yet" and "cannot see" were the same branch.**
  [his, 2026-07-29] *"when solomon first takes a request, his section very
  briefly shows 'cannot see what solomon is doing' and then changes to 'Solomon
  is getting ready' - it shouldnt show that breif initial 'dont know' text"*.
  Measured cause: `observe()` returned `unlinked` for BOTH "no session id was
  ever recorded" (an interactive session this system did not spawn — the real
  unknown) and "a session id we chose, whose transcript the CLI has not written
  yet", which is every spawn for its first second or two. They are now two
  states; `actually()` and `doing_line()` read `starting` exactly as they read
  `none` (`nothing yet`), so the difference never reaches the screen. It is a
  **grace, not a synonym**: `boardphase.START_GRACE_S` (120s, stamped as
  `linkedAt` the first time the id is seen), past which a spawn whose transcript
  never appeared is `unlinked` again and says so — that one is a real failure
  and hiding it forever would be the §10 lie. Checks: four in `test_phase`
  (young, its card line, its phase, and the grace expiring) and four in
  `test_work` (a freshly registered Solomon wields the ring, neither of his
  sentences says `cannot see`, the pair is in his order, and a WORKER in the same
  state still reads the bare `nothing yet`).
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
- **...and where it cannot be chosen it is BOUND, still never guessed.** A
  minister on the hermes runtime has no transcript file and no `--session-id`:
  its history is rows in `~/.hermes/state.db`. The spawn therefore records a
  SHA-1 of the query it sent (`boardphase.arm`), and hermes stores that query
  verbatim as its session's first user message, so `boardhermes.resolve` finds
  the one run that is ours — not the one nearest in time. From there everything
  on this page is the same: the same phases, the same wording, the same states
  and the same grace, out of a database instead of a file, with hermes's tool
  names translated into ours (`boardhermes.TRANSLATE`) rather than classified
  again. What does NOT carry over is the context tally: hermes writes no
  per-message token count, so a hermes card has no `62k/200k` line at all.
  Covered by `test_hermes`.
- **The second line is the OBSERVED one, never the claim, and UNDER A CLAIM it
  is the description ALONE** — [his, 2026-07-29] *"actually just take out the
  [agent] is actually and just display the text after it"*. An agent saying
  `testing` while every recent call is an `Edit` reads *"Marbas is testing - the
  parser"* on one line and *"editing vtbclient.py"* on the
  next — and **that divergence is a feature, not an error**. Nothing
  hides it, reconciles it, warns about it or colours it: the warn/crit ramp on
  this desktop means a machine fault (§8.1, §9.3), not an agent being optimistic
  about itself.
- **...but when the observed line LEADS the card, it keeps the name ON the top
  line** — [his, 2026-08-01] the card used to lose its name off the top line the
  moment activity was reported: a claimless card leads with the observation, and
  that line named nobody. So a claimless active card now reads *"Marbas is
  editing vtbclient.py..."* — name, and the top line's tick — instead of the
  bare description. `boardphase.doing_line`'s `lead` flag (true iff `says_line`
  is empty) is the whole mechanism; `boardagents.agents()` passes it off exactly
  that emptiness. The name is drawn ONCE — the 7-cell column below is now gated
  on `titleFirst`, so it appears only when neither sentence names the agent.
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
  condition is `AgentRow.titleFirst` (both sentences empty), which `nameNeeded`
  now reads directly: once the leading observed line carries the name (above),
  the claim line, the observed line and the title row cannot all be blank while
  a name still needs a home. `tools/board-test.py` asserts the drawn order, the
  tones and both branches of the fallback offscreen.
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
- **The no-pressure rule applies here too**, with the one exception recorded
  above: the card's `4 minutes` line is the only thing that counts, and
  it counts against the agent. Otherwise no ages, no
  counts, no urgency ordering, nothing from the warn/crit ramp. A running agent
  is just running. The order is BIRTH, oldest first (`boardwork.cards()`),
  which is stable — a row must not move under his cursor between two polls —
  and is not urgency: a new agent appends at the bottom and nothing above it
  moves for the rest of its life. The raw `born` epoch still never reaches
  QML (`boardagents.born`) — the duration is formatted in Python, so the
  ordering key cannot quietly become a second counter.
- **A finished agent leaves the list at once, and the DRAWING is what makes
  that true** (`boardwork._drawable` skips a row that is `exited` AND
  `finished`) — [his, 2026-07-30] *"are ministers sometimes staying in the
  triangle unfocused colored until the user clears their completion
  message?"*. They were, and "sometimes" was a race: the card is only deleted
  from disk by `boardagents.sweep()`, on a board-watch tick, and the tick a
  worker's own final `note` triggers usually runs while that worker is still
  alive. Nothing then wrote the board again until HE replied to the bullet — so
  clearing the message looked like the thing that removed the card, and the
  5-minute timer was the only other way out. Liveness is polled here every
  second, so the drawing already knew; the sweep behind it is bookkeeping he
  does not have to watch. **A worker that stopped WITHOUT reporting keeps its
  card** until the tick files it and puts the FAILED bullet on his board — that
  dimmed row is the only visible trace of the loss until then. Harness:
  `test_finished_leaves`.
- **A stopped worker is told apart from a finished one in WORDS**, wherever one
  is still shown — the card in the moment before it goes, and everything that
  reads `boardagents.agents()` rather than the drawing. **A stopped worker that
  REPORTED reads as finished, not abandoned**: [his, 2026-07-30] a completed worker's card
  *"still sits and proclaims 'exited without finishing - nothing was
  committed..' ... and no vertical line on the left EVEN THOUGH its task has been
  completed"*. `boardagents` carries `finished` off `boardwork.reported` — the
  same fact `reap()` sorts `done/` from `failed/` by, read from the live stamp
  before the reap and from `done/` after it — so `describe()` says `finished - it
  recorded its result on the board` and §9.1's accent gutter is present on a
  running row **and** on a finished one. A worker that genuinely stopped
  mid-sentence keeps both the old words and no gutter. The reap runs on a
  board-watch tick, so the stale claim had up to five minutes to be read — and
  that same five minutes is what the bullet above took out of the drawing.
  Colour says nothing here; §8.1's ramp means a machine fault.
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
- **...but it is not drawn any more — [his, 2026-07-31] *"agents started by the
  user can be hidden from the triangle"*.** Those anonymous rows (no name, no
  `--where`, an id like `s831183`) are HIS terminals, not summoned ministers,
  so `boardwork.cards()` drops every `kind == "session"` row and the triangle
  no longer shows them. The filter lives in `cards()`, the one surface that
  draws the window — **not** in `_drawable()`, so `boardctl.py agents` (which
  reads `groups()`) still lists them, because that is an agent-facing
  collision check where a live session of his still matters. Board-dispatched
  workers (named rows) and Solomon are never a `session` and are unaffected.
- **THE SECTION DESCRIBES ITSELF WITH CARDS — it has no description of its
  own.** [his, 2026-07-30] bound ministers → the cards and nothing else; none
  bound → the one empty line below and nothing else. Two things went for that:
  the paragraph that framed the cards (*"each minister says what it is doing,
  and the line under it is what it is actually doing…"*) and the watcher's
  systemd sentence that sat under them. `Agents.watcher`/`Agents.armed` are
  still read and still polled — the only place either is DRAWN now is the
  not-armed line below, which §10 does not let us drop. Do not reintroduce a
  subtitle here; the other sections keep theirs.
- **Empty is the resting state**: `binds ministers.`, in `Theme.dim`, with the
  box still there — [his, 2026-07-29] what the triangle IS, rather than a report
  that it currently holds nobody.
- **The band says how many it BINDS, in words — [his, 2026-07-31] *"the
  triangle binds three ministers"*.** Once any minister is running the
  `SectionHead` label reads `the triangle binds <n> minister(s)` (one/two/
  three/four, matching the cap); with none it falls back to the plain `the
  triangle`, because the dim `binds ministers.` line below already says the
  empty state and `binds no ministers` would contradict it. The number is
  `Agents.boundMinisters` (`main.py`), counting the RUNNING, non-orchestrator
  cards in the exact set the triangle draws — so it inherits the session
  filter (`cards()` drops `kind == "session"`), and an anonymous session the
  user started is never counted. A queued task (no process yet) and an exited
  card are unbound and do not count.
- **...and a SECOND line only when nothing will ever start.** Armed, that
  sentence is the only text the section draws. Not armed, it reads
  `board-watch is not armed`. The verdict is `Agents.armed`, three-valued —
  `boardagents.watcher_state()` asks BOTH `board-watch.service` (a tick running,
  a failed last run) and `board-watch.path` (will anything start one), checks
  the kill switch `~/.local/state/board-watch/off` itself, and answers `None`
  when systemctl could not be asked, which §10 does not let the window turn into
  a claim in either direction. Polled with the units every ten seconds and never
  on a repaint. Asking the service ALONE is what this replaces: its resting
  state is `inactive` whether or not the path unit exists, so the old sentence
  claimed armed for a watcher that could never fire.

### A card with nothing to say yet RISES; it is never withheld

[his, 2026-07-31] *"instead of hiding the card until it shows the name on the top
line etc, can we just put a card in there that reads '[agent] awakens...' with an
animated elipsies ... the card should just show the rising text and nothing else
until the agent card actually starts producing stuff like before"*. The word is
**AWAKENS, not arises** — [his, 2026-08-01] *"have it just say like '[agent]
awakens...' with an animated elipsies"* — the name-led top line he asked for on
31 July settling on the waking verb.

- **`boardagents`' `arising` decides, off the observation STATE**, never off the
  words: a card rises exactly while it is *running*, has claimed no phase, has no
  orchestrator startup line of its own, and its observation is `none` or
  `starting`. Matching the string would break the moment either sentence is
  reworded.
- **The rising line is the WHOLE card.** `boardagents` blanks `doingLine` and
  `saysDetail` and writes `boardphase.arises_line()` into `saysLine`; `AgentRow`
  drops the title row, the context tally and the worked-for stamp off the same
  flag. His *"nothing else"*, and it is also honest — the observed line under it
  could only read `nothing yet`, which is the placeholder the rising line
  replaces, so drawing both says one absence twice.
- **The dots animate for free.** The line ends in three ASCII periods and lands
  on the card's TOP line, which is the only line `AgentRow` ticks (never U+2026 —
  the font has no such glyph, docs/DESIGN.md §2.3).
- **There is no `visible` binding on `AgentRow`, and putting one back is a
  regression.** This replaced `speaks`, a gate that withheld a card until its top
  line was a real sentence [his, 2026-07-30] — right for the two seconds a
  healthy spawn takes, and the reason a minister wedged before its first API call
  was *undrawable*: registered, linked, and having genuinely never done anything
  was exactly the withheld state. One burned a core behind an empty triangle for
  45 minutes [top, 2026-07-31]. There is now no state in which a running agent
  has no card.
- **It does not rise forever.** Past `boardphase.START_GRACE_S` (120s) with an
  empty transcript the observation becomes `silent`, the rising stops, and the
  card says `not started - nothing in its transcript at all`. A spawn whose
  transcript never appears at all goes `unlinked` on the same bound and says it
  cannot see the work. Both are the point of the change: the failure is VISIBLE.
- **A stopped card never rises**, whatever it said: its top line is the title
  row, which is real.

### ...and clicking the card opens what it is ACTUALLY SAYING

[his, 2026-07-30] *"a minister card should expand to show what that minister is
actually saying"* — a drawer slides down out from under the card with the last
couple of lines that agent logged, and clicking the card again slides it back up.
The card's three lines are this app's account of the agent; the drawer is the
agent's own voice, uncut except for width.

- **The whole card is the hit target, and the BOX is the one exemption.** A left
  click anywhere on it toggles; `AgentRow`'s toggle `MouseArea` is declared
  BEFORE the column, so everything the card draws sits above it and only the
  parts that accept no click of their own fall through. The editor keeps its
  clicks — a caret placed in it must not open a drawer over what he is writing —
  and the card lights on hover, which is what says it can be clicked at all
  (§10). The right-click menu is untouched: that `MouseArea` takes
  `RightButton` only, which is why a left button reached nothing here before.

### Right-clicking a card can FORCE-STOP that minister

[his] the card's right-click menu (`Main.qml`'s `agentRowMenu`) ends with a
**force-stop** entry for a RUNNING worker or decision minister — the destructive
act §10.3 makes a menu entry rather than a click, at the FOOT of the menu behind
its own separator (the same shape `todoMenu` uses for its one removal), so the
two deliberate acts are the right-click and the entry, and the pointer never
lands on it by accident.

- **The kill is HONEST, per §10** — `boardwork.force_stop` SIGKILLs the
  minister's own transient unit (`systemctl --user kill --signal=KILL
  board-worker-<id>` / `board-decision-<id>`, the whole cgroup), then RE-READS
  the one liveness rule (`boardmove._alive` via `boardagents.agents()`) and
  reports what is actually true — never success off the command's own exit. A
  minister with no unit (the detached fallback) is SIGKILLed by pid group
  instead; the verdict is still the re-read, so nothing here can silently no-op.
  `main.py`'s `Agents.forceStop` returns that verified line for the footer and
  re-polls so the card redraws stopped at once.
- **The entry is offered ONLY where a real unit can be stopped** — a running
  `worker` or `decision`. **Solomon is excluded**: the orchestrator is a brief
  planning burst that holds the board-watch tick and then delegates, its resting
  card has no process to stop, and killing it mid-plan would abandon a dispatch
  he asked for. **A subminister is excluded too**: it has no unit of its own and
  lives in its parent minister's cgroup, so force-stopping that parent takes it
  down with it. `force_stop` refuses both regardless, as defence in depth.
  Harness: `test_force_stop`.
- **The state is the WINDOW's, keyed by the agent's id** (`Main.qml`'s
  `outputOpen` map, session-only). A card is destroyed and rebuilt whenever the
  key list changes — one agent finishing is enough — so a drawer remembered in
  the delegate, or by list index, would shut itself on the next 2.5s poll or
  reopen under somebody else's card. Several open at once is the point.
- **The LIVE source is the agent's TRANSCRIPT; the `.log` is the fallback.**
  [his, 2026-07-30] *"the drop down log in agent cards should be the last couple
  lines of their REAL LIVE OUTPUT... agent card logs should really never read as
  'nothing logged yet' which they do now pretty much all the time"*. The
  `.log` (`boardwork._log_path`, `~/.cache/board-work/<id>.log`) is real output
  and is **empty for the entire run** — `claude -p` with no tty writes its
  result once, at exit. Measured on top 2026-07-30: both live workers' logs were
  0 bytes, and every non-empty one of ~200 finished workers was written at exit.
  So the drawer said `nothing logged yet` for exactly as long as there was
  anything to watch. `Agents._transcript_lines()` now reads
  `boardphase.transcript(rec["session"])` instead — the same file
  `boardphase` already tails for the observed line, appended to as the agent
  works.
- **...and the `.log` is now a POINTER, so a killed worker is never `log
  empty`.** Same fact, worse consequence: a worker that is SIGKILLed, OOMed or
  reaped at `RuntimeMaxSec` never reaches the exit that would have written its
  output, so its log stayed 0 bytes forever — and the one case where it matters
  most is the one case it said nothing. [his, 2026-07-30, of a bullet reporting
  a worker killed mid-verification with an empty log] *"i doubt you have no idea
  what happened to foras as this message implies"*. So `boardwork` writes the
  file itself at both ends: a **header** before the spawn (who, the task, the
  session, and the transcript path — the spawn chooses the uuid, so the path is
  known before the agent exists; on a runtime whose session id we cannot choose
  the header names the STORE and the id is appended the moment the run is
  bound, because a header that names a file which will never exist is worse
  than one that names none) and a **post-mortem** when `reap()` closes a
  worker that reported nothing (`log_postmortem`, plus `rec["transcript"]` on
  the failed record for whatever writes the bullet). `_session_of()` recovers
  the uuid from that header when the registration is already swept, which is
  why the header carries it. Board-written lines are `- [board HH:MM:SS] ` so
  nothing mistakes them for the agent's voice, and `_died_transiently` reads
  only the tail, which they cannot match.
- **And it is the LITERAL output, not a summary of it.** [his, 2026-07-30]
  *"you are saying we cannot actually see its real live log i.e. not what its
  saying its doing but its literal actual thinking / tool call / coding
  output?"* — so every line of every assistant `text` and `thinking` block, each
  tool call's own ARGUMENTS (`Agents._tool_use_lines`: `$ <command>` for Bash,
  otherwise the tool and its lead path/pattern, then the `old_string` /
  `new_string` / `content` body), and each tool result's own text
  (`Agents._result_lines`), flattened in file order. The drawer draws the last
  few, which makes it `tail` on a running log. `boardphase.describe_call`'s
  one-line-per-event summary is still right for the card's OBSERVED line, which
  is a summary by design, and wrong here. The only entries skipped are his own
  turns — a user message is his prompt read back at him; a `tool_result` riding
  on one is kept, being the tool's output.
- **Both readers are in PYTHON** (QML cannot open a file), and both are trimmed
  there rather than in the drawer. Transcript: the last 256k, whole lines only —
  it is being appended to while this runs. Log: the last 64k, ANSI/C0 junk and
  blank lines dropped, and only what a `\r`-rewritten progress line settled on.
  Either way `px()` maps the glyphs, because §2.3 says to map at INGEST; three
  lines, and only the width-dependent elide is the drawer's (§2.7 — the font is
  monospace).
- **Nothing logged says so in words** — `nothing logged yet`, not an empty box
  and not an error colour (§10; a worker that has not written yet is not a
  machine fault). No transcript, a missing log, an unreadable one and one
  holding only control junk are the same honest answer. It should now be RARE:
  an agent registered with no `session` at all (an interactive one nothing here
  spawned) is the case that still reads that way before it exits.
- **It follows the poll while it is open** and reads no file at all while it is
  shut. The look is §6.2's clipped growth from the card's bottom edge and §9.1's
  indented block with a `Theme.border` spine — never `accent`, which two pixels
  to its left already means *current*.
