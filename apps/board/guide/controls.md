# The box, the four dropdowns, the usage meter and taking an order back

*Everything he can operate at the top of the window, in the order he asked for them, plus second thoughts and ctrl+z.*

Part of goetia's guide — the map and the shared
rules are in [`../AGENTS.md`](../AGENTS.md); read that first.

---

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

**The box is as TALL as the column beside it, and that is one-directional.**
[his, 2026-07-29] *"the prompt box should extend so that it is not a single line
but rather multiple lines so that it is the same height as from the top of the
model selector box to the bottom of the indicators. the indicators should be
anchored to the model selector box not the prompt box as they are now"*. So the
column's TOP control sits at y 0 — `summonerPick` since his four dropdowns
landed — each control anchors to the one above it, the meters anchor to the
**last** of them, and `askBox.minHeight` is that column's whole span — four
dropdowns, both meters and a 4px rung between each — read off their real
geometry, never a number, so a
longer model
label or a bigger font size moves box and column together (§2.7). The
dependency runs column -> box and only that way: anchoring the meters to the box
while the box measures itself off the meters is a **binding loop**, and it is
the one thing to re-check if this arrangement is ever rearranged (`InputBox`
derives its own `contentHeight` from the two states' `implicitHeight` for the
same reason — never from `height`). `minHeight` is a FLOOR, not a cap: typing
past it still extends the box downward, which is the rest of his sentence.
The slack it fills was dead space (docs/DESIGN.md §5.2) — a one-line box left
the area beside the meters empty — and the whole tall region is the hover fill
and the click target (§5.3), in both the resting and the open state.
Regression layer: four checks in `test_window`, measured against the real items.

### FOUR dropdowns beside the box, and the order is his

[his, 2026-07-29] *"1. number of summoners 2. summoner model 3. number of
ministers 4. minister model"*. Top to bottom, in that order, in one column to the
right of the box he types in, with the usage meters under the last of them.

- **Each COUNT names the role of the MODEL under it**, which is what lets the
  labels stay as short as they are: `fable 5` on its own does not say which of
  the two models it is, and `1 summoner` directly above it does. The hover line
  on each control says the rest (§8).
- **One component for all four (`qml/PickBox.qml`)**, one `colW`, one
  `pickCells` arrow column, and one store each. A fifth copy of the chrome is
  how four controls that must look identical stop being (docs/DESIGN.md §19.1).
- **Every one of them APPLIES**, and the harnesses assert the applying rather
  than the drawing: `apps/board/tools/board-test.py` for the stores, the ceiling
  and the order on screen, `tools/board-watch-test.py::test_summoner_fanout` for
  how many summoners really start. A dropdown that only rendered would be the
  §10 failure this app is most exposed to.
- **All four choices are machine-local** — files under `~/.local/state/board/`,
  which does not sync — so `top` and `book` can be set differently and neither
  surprises the other.

### 1. How many summoners plan at once

[his, 2026-07-29] *"number of summoners"*.

- **`boardwork.summoners()` / `set_summoners()`**, the file
  `~/.local/state/board/summoners`, also written by `boardctl.py summoners <n>`
  and overridable by `BOARD_MAX_SUMMONERS` for a harness.
- **What it MEANS is a ceiling on the fan-out, not a quota.** A tick with
  something in the queue splits what he typed across up to that many
  orchestrator runs (`boardwork.split_for_summoners` — contiguous, longest
  first, none empty) and starts them together in threads
  (`board-watch.work_the_queue` → `_summon`). One queued sentence is ONE
  summoner however high the number is, because there is nothing for a second to
  read.
- **Contiguous, not round-robin**: two sentences he typed one after the other
  about the same thing stay in one prompt, where a human would read them
  together.
- **The tick is held for the slowest run, not the sum** — the runs are waited on
  (that is what puts a failure back on his board in his own words), so the
  flock's worst case does not grow with the count. Each failed run leaves its
  own `QUEUE_FAIL` bullet, written serially after the join because `board.md` is
  one file.
- **The range offered is `SUMMONER_CHOICES` (1-4)**, small on purpose: every
  summoner is a claude session held open for up to `BOARD_ORCH_TIMEOUT` while
  the tick's flock is held. `boardctl.py summoners` still takes any `n >= 1`, and
  a value of his off the list is drawn and ticked rather than hidden.

### 2. The dropdown beside the box: which model, and how hard, summons

[his, 2026-07-29] *"add a drop down to the right of the top prompt box that
allows the user to select which model they wish the orchestrator to be. if this
changes in the middle of the orchestrator working, simply change it to the
defined model on the next prompt it recieves."* — and, later, the reasoning
effort of the summoner too, so this control now picks a `(model, effort)` PAIR,
exactly as the minister chooser (§4) does. One pick, one label (`opus 5 xhigh`).

- **The list and the choice live in `boardwork`** — `ORCH_MODELS`,
  `orch_model()`, `set_orch_model()`, `orch_label()` — because `boardctl.py
  model`, both spawners and the control all read the same functions. A copy of
  the list in the QML would be a second answer to "what may he pick".
- **`(flag, effort, label)`, a curated spread, NOT a ceiling.** Unlike
  `MINISTER_MODELS` this list has no clamp behind it: the summoner's judgement is
  the whole of its job and he asked to be able to buy as much of it as he likes,
  so the higher efforts (`xhigh`, `max`) are offered on the reasoning models and
  `role_flags("orchestrator")` never clamps the pair. It is curated rather than
  the full model×effort cross product for the same reason the minister list is —
  a dropdown is a short list of sensible pairs.
- **Full model names, never the `opus`/`sonnet` aliases.** An alias means *the
  latest of that family* and would silently re-point his choice the day a new
  one ships, which is the exact thing a chooser exists to stop. What he TYPES at
  `boardctl.py model` is forgiving in the way this tool's selectors are
  (`resolve_model`: exact `<flag> <effort>`, exact label, or one unambiguous
  substring — ambiguity is an error, never a guess); what is STORED is always
  the full pair.
- **His rule for a mid-run change is the mechanism, not a rule layered on one.**
  `role_flags("orchestrator")` reads the file on every spawn and caches nothing,
  so a session already running keeps what it started with — nothing can
  re-point it from outside — and the next prompt off the queue reads the file
  again. There is no signal to plumb and nothing to reconcile.
- **A stale or hand-edited value falls back to `DEFAULT_ORCH`** (`fable 5` at
  `high`, what a summoner ran before the effort was selectable) rather than
  reaching `--model`/`--effort`, where the failure would be a spawn dying on a
  CLI usage error and a `FAILED:` bullet he has to decode.
- **It is a `CtxMenu`, not a combo box** (§7.2 — menus here are ours), with a
  resting label and a `*` beside the live one. The label is prose (`opus 5
  xhigh`), never the wire pair; the tick is computed from `boardwork`, so the
  control cannot disagree with what will actually spawn.
- **The choice is machine-local**, same as `cap` and for the same reason: it is
  a file under `~/.local/state/board/`, which does not sync. `top` and `book`
  can summon on different models and efforts, and neither surprises the other.

**Workers and decision agents default to `deepseek v4 flash`** — [his,
2026-08-02] the minister default is deepseek, so an unnamed dispatch runs cheap
and off the weekly Claude window, and Solomon tiers UP from there per piece of
work. The `opus 5 medium` the fourth dropdown tops out at stays the CEILING (the
hard cap, *"do not allow ministers to be anything higher than opus 5 medium"*
[his, 2026-07-29]) — the two are no longer the same value: `MINISTER_DEFAULT`
(the last row) is what an unset dial gives, `MINISTER_CEILING` (the first) is
what a stale or out-of-range one clamps to.

### 3. ...and under THAT, how many agents may run at once

[his, 2026-07-29] *"between the model selector and the indicators, add another
drop down for the max number of agents available."*

- **It writes the cap FILE, and that is the only cap there is.**
  `boardwork.cap()` / `set_cap()` — `~/.local/state/board/cap`, the same store
  `boardctl.py cap <n>` writes and every spawner reads. `Agents.chooseCap()` is
  four lines over those two functions for the reason `chooseModel` is: a second
  copy of the number is a control that can disagree with what actually runs.
- **Nothing is restarted and nothing is killed.** `promote()` re-reads the file
  at the top of every board-watch tick, so a bigger cap starts queued work on
  the next one and a smaller cap simply stops starting more. The **`hint` on
  the box** says that, permanently and before he picks; it used to be a footer
  line after the pick, which is the flash he reported — see "the footer only
  says what nothing else on screen can", below.
- **The range offered is `boardwork.CAP_CHOICES` (1-8), not a ceiling.**
  `boardctl.py cap` still takes any `n >= 1` — a typed selector here is always
  more forgiving than a drawn one — and a cap of his that is off the list is
  **appended and ticked** rather than hidden, or the control would draw a tick
  beside a number that is not live. `BOARD_MAX_WORKERS` still wins over the
  file, which is why the harness pops it before checking that picking one
  writes anything.
- **One component for every dropdown: `qml/PickBox.qml`.** Label, `v`, hover
  chrome, and `CtxMenu` under it — his *"another drop down"* is the same
  control, and a second hand-rolled copy of the chrome is how two things that
  must look identical stop being (docs/DESIGN.md §19.1). Its menu property is
  called `popup`, not `menu`, so a call site can write `popup: menu` without the
  id resolving to the property.
- **The column has ONE left and ONE right edge**: `colW` is the widest of the
  four dropdowns' `implicitWidth`, and the meters take it too — his "exactly as
  wide as the model selection box" generalised, since labels of different lengths
  would otherwise give that column five edges.

### 4. ...and under that, what the MINISTERS run on — CAPPED

[his, 2026-07-29] *"do not allow ministers to be anything higher than opus 5
medium thinking."* That is a hard ceiling and it is enforced in **two independent
places**, because a control is not a guard against a file:

- **The list cannot offer more.** `boardwork.MINISTER_MODELS` is an ALLOWLIST of
  `(flag, effort, label)`, ceiling first, and it is the only list — the dropdown,
  `boardctl.py minister` and `resolve_minister` all read it. An allowlist rather
  than an ordering, because *"higher"* needs no definition if nothing above the
  ceiling is reachable. Effort never exceeds `medium` for any family: his
  sentence caps the thinking budget as well as the model, and a bigger budget on
  a smaller model is still a tier he did not offer. `fable 5` is deliberately
  absent — it is what a SUMMONER defaults to, and this list may not exceed opus 5.
- **The spawn cannot pass more.** `role_flags()` reads `minister_model()` for
  both `MINISTER_ROLES` (`worker`, `decision`) and then clamps the pair to
  `MINISTER_CEILING` if it is not in the list — **after** the `BOARD_WORKER_*` /
  `BOARD_DECISION_*` environment overrides, so those can lower a minister and
  never raise one, and an emptied override cannot inherit whatever
  `~/.claude/settings.json` says. A stale, hand-edited or retired value is the
  ceiling, not a spawn dying on a CLI usage error and a `FAILED:` bullet he has
  to decode.
- **`minister_model()` returns a `(flag, effort)` PAIR** — one choice, so the
  label carries both (`opus 5 medium`). A chooser that showed only half of what
  it sets would be the §10 failure with a shorter string.
- **The store** is `~/.local/state/board/minister-model`, one line,
  `<flag> <effort>`; `boardctl.py minister [name]` is the typed half and is
  forgiving the way `resolve_model` is (exact, or one unambiguous substring —
  ambiguity is an error). A model this board offers a summoner but not a minister
  is refused **with the reason** rather than silently becoming the ceiling.
- Read at spawn, cached nowhere: a minister already running keeps what it started
  with, and the next one dispatched reads the file again.

### ...and under that, how much of his usage is gone

[his, 2026-07-29] *"add usage indicators directly under the orchestrator
model-selection box: how much of his daily usage and how much of his weekly
usage has been consumed"*, with one constraint stated in the same breath: **he
does not want Fable broken out.** `boardusage.py` + `qml/UsageMeter.qml`; the
module docstring is authoritative and this is the summary.

- **The percentages are the ACCOUNT's, never derived here.** Everything on this
  desktop that looks like a second source is not one — the session transcripts
  carry token counts with **no denominator**, `~/.claude/stats-cache.json`
  carries neither and goes days without updating, and there is no `claude usage`
  subcommand. **Nothing here derives a percentage from tokens against a ceiling
  nobody published** (§10.5, and the same refusal `boardphase` makes about an
  assumed context window).
- **IT FETCHES FOR ITSELF, because the CLI's cache does not tick.** [his,
  2026-07-29] *"why did it take me opening an instance of claude-code for the
  usage indicators to update? they should always be up to date"* — and the
  answer was not the poll. `~/.claude.json` -> `cachedUsageUtilization` advances
  **only while a claude-code session runs**: measured on `top` 2026-07-29, with
  no session live its `fetchedAtMs` does not move at all, and even a whole
  `claude -p "/usage"` run leaves it untouched (it printed 16% while the cache
  still said 14%). So the bars were as old as his last session, however honestly
  they said so. `boardusage.fetch()` now does the same
  `GET /api/oauth/usage` the CLI does, with the access token the CLI already
  holds, and writes the answer to `LIVE_PATH`
  (`~/.local/state/board/usage.json`) — **a file this app owns**. The response
  body is shape-identical to `cachedUsageUtilization.utilization`, `limits[]`
  and all, so nothing downstream learned a second format. `_cache()` reads both
  files and takes the newer `fetchedAtMs`, so the CLI's writes are never thrown
  away and a host where the fetch cannot work behaves exactly as before.
- **`~/.claude.json` and the credentials stay READ-ONLY from here.** `fetch()`
  uses the access token and **never refreshes or rewrites it**: the refresh token
  rotates, and racing the CLI for `~/.claude/.credentials.json` could log him out
  of every session on the machine. An expired token therefore fails the fetch;
  `nudge()` asks the CLI to sort its own credentials out (`claude auth status`,
  measured 0.22s on `top` — no session, no transcript, no model call) and the
  fetch is retried once, at most every `Usage.NUDGE_SEC`. If that does not work
  either the last reading is still drawn with its honest age.
- **A failed fetch costs freshness and nothing else.** `fetch()` returns a reason
  word (`off`, `no-token`, `expired`, `unauthorized`, `http-<code>`, `offline`,
  `bad-payload`, `unwritable`) and never raises, never blanks a working bar, and
  refuses to STORE a payload from which no window parses — overwriting a real
  reading with a shape we cannot read would turn a bar into `unknown` for as long
  as the endpoint stayed odd. `Usage` logs the reason to stderr only when it
  *changes*, or a machine with no network writes a line a minute.
- **The short window is FIVE HOURS and is labelled `5h`, not "daily".** The
  account has no daily bucket. What stops him mid-afternoon is the rolling
  session limit, so that is what is drawn, under its own name — a five-hour
  number under the word "daily" is §10.5's failure with a friendlier label.
- **No Fable row, and no arithmetic was needed to get there.** The payload's
  `limits` list carries a `weekly_scoped` entry whose `scope.model.display_name`
  is `Fable` beside the unscoped `weekly_all`; the module reads **only entries
  with no `scope`**, and `weekly_all` already contains that usage. A future
  per-model kind is excluded by construction rather than by a name list that
  would go stale. The same rule kills `utilization.seven_day_opus` and friends.
- **Unknown is a state, not a zero** — missing file, missing key, a percentage
  that is not a number all draw the empty track and the word `unknown`. A bar at
  zero would be the claim "you have used none of it".
- **A stale cache still reports, and says its age in the ROW**, not only on
  hover: the difference between "he has used 73%" and "he had, nine hours ago"
  is exactly the sort of thing colour alone loses (§3.5). It is the row's
  SECOND LINE, under the percentage it qualifies, because the row is only as
  wide as the chooser and `73%` plus `(9h old)` is wider than that on its own.
- **Both meters are exactly as wide as the model chooser, stacked, `5h` on
  top** [his, 2026-07-29]. The width is *bound* to `modelPick`, never a number,
  so a longer model label widens box and bars together; the stack takes its
  order from `boardusage.WINDOWS` and its internal spacing from nothing (each
  meter is its own line box, §4.1/§5.1). It leads in 4px under the chooser and
  leaves 4px under itself — *"just a little more space between the top of the
  indicators and the bottom of the model selector"*, one rung of §4.1's scale
  and the gap that block already used, so the card has one gap rather than
  three. The 5h/7d rows still butt together. Inside a meter the window name goes hard left
  and the reading hard right (§5.4) and the **bar is what flexes** into what is
  left (§5.2) — under `minBarW` it is not drawn at all, which happens only for
  `unknown`, a word about as wide as the chooser and the whole reading in that
  state anyway.
- **Two clocks, because reading is cheap and fetching is not.** The 60s tick
  re-reads both caches (two `stat`s and a small JSON parse); a FETCH happens at
  most every `Usage.FETCH_SEC` (300s), on a daemon thread so the window never
  waits on the network, with exactly one ever in flight and the result carried
  back over a queued `_fetched` signal. That is what makes the bars right with no
  claude-code running, right after a relaunch, and right after the machine has
  been idle for hours.
- **The clocks are the fallback; the trigger is an agent's LIFE changing.**
  [his, 2026-07-29] *"ensure the usage indicators update every time an agent is
  killed / finishes their job / etc."* `Agents.lives` fires when the set of
  `(id, state)` pairs changes — born, finished, killed, failed, reclaimed,
  gone — and `Usage.follow()` hangs `kick()` on it, which now genuinely re-reads
  the number instead of re-reading a file nobody wrote. It is deliberately
  **not** `Agents.changed`, which also fires for per-poll churn (a worked-for
  line ticking over, a context tally, a new unread note): hanging it off that
  would make this a 2.5s fetch. `Usage.KICK_SEC` (20s) is the floor either way.
- **...and a CLICK on a meter is the third trigger** [his, 2026-07-30], with the
  gap set to zero and the outcome reported in the footer. See "A usage meter is a
  BUTTON" below.
- Machine-local by construction: neither `~/.claude.json` nor `LIVE_PATH` is
  inside the `~/.claude` tree that syncs between `top` and `book`, so each host
  draws what it last read for itself. Same account, different freshness.
- Regression layer: `test_usage` in `tools/board-test.py` (the scoped entry is
  never drawn, a scoped-only weekly reads `unknown` rather than being promoted,
  every broken shape reads `unknown`, an old cache carries its age), plus the
  window checks that there are two meters, that they sit **under** the chooser
  in `WINDOWS` order top-to-bottom, and that both edges are flush with the
  chooser's — a hardcoded width would pass the first three and silently drift on
  the fourth — plus `test_usage_fetch`, which covers where the number comes FROM
  (the fresher of the two caches wins, an unreadable one does not take the other
  down, a token that has expired is not spent on a round trip, the wire is the
  account's own endpoint with the CLI's token, and every failure mode keeps the
  last reading unblanked) — plus `test_usage_follows_agents`, which asserts the
  lifecycle
  re-read fires on all four transitions and **not** on a card merely redrawing. **Every context property `main.py` installs must also be installed in
  the harness's `build()`** — a missing one is a `ReferenceError` the harness
  cannot see and a section simply absent on his screen.

### Second thoughts about something still queued

**The list is PENDING ORDERS, and that is the word on it** — [his, 2026-07-29]
*"instead of messages it says orders"*. So the group is labelled `pending orders`
(drawn only when it holds something), a row reads `order waiting for the next
summoner`, and every sentence about one — the menu entry, the footer after a
removal or an edit — says *order* and *summoner*. Identifiers did not move: the
directory is still `inbox/queue/`, the slots are still `boardagents.pending()`
and `Agents.queued`, exactly as `kind="worker"` survived the rename to
*minister*. And what a pending order waits for is a **summoner**, never a
minister: Solomon is who drains the queue and decides who does it.

**It is drawn at the foot of the SUMMONER section** — [his, 2026-07-30]
*"pending orders for solomon should be shown at the bottom of the summoner
section NOT at the bottom of the triangle"*, where it used to sit. It is waiting
on the summoner to pick it up, so it belongs under his card; the triangle
answers a different question (who is bound right now). `board-test.py` asserts
the position, not just the label.

*"allow the user to remove queued `waiting for next agent` items or edit them in
place"*. Right-click a pending order: **edit what it says**
opens the same `InputBox` every other typed sentence here uses, seeded with the
current wording; **remove it from the pending orders** is last behind a separator (§7.2)
and moves the message to `inbox/dropped/` — removed from the queue is not the
same as never written, and this app deletes no prose. `QueuedNote.qml`,
`boardagents.remove_queued`/`edit_queued`, `Agents.removeQueued`/`editQueued`.

**Both can lose a race with `board-watch`, and both say so.** The queue is
drained on the watcher's clock, so a message can leave between the menu opening
and the click landing. So neither writes the queue path in place: each **claims**
the file with `os.replace` first — the removal straight into `dropped/`, the
edit into `inbox/editing/` for the length of three syscalls and then back under
its own name. Either the claim wins, or it raises and the operation reports the
message **gone** (`None` → *"that one has already gone to a summoner"*), which is
§10.2's refuse-visibly. An in-place rewrite of the queue path would have done
the one unforgivable thing instead: recreate a message a drain had just taken,
so the run already working it would find it queued again and do it twice.
`sweep()` returns anything stranded in `editing/` (a process that died
mid-edit, older than `EDIT_RESCUE_AFTER_S`) to the queue.

### Ctrl+Z takes the last order back — and it is a real cancellation

[his, 2026-07-29] *"before solomon summons a minister, allow the user to crtl+z to
stop solomon from doing that (he should not send any messages he should just stop
doing that specific inbox item) and then insert the prompt back into the prompt
box for the user to edit. if the last prompt had to be placed in the pending
[orders] section, then ctrl+z should remove it from the pending list and insert it
back into the prompt box"*.

**TWO CASES, ONE PATH.** `boardundo.cancel()` — its docstring is authoritative —
and it does not ask which case it is in. The order is either still in
`inbox/queue/` (nothing has happened) or a summoner run has been given it
(Solomon exists and is deciding). Either way what he gets is his own words back
in the box, open, caret at the end, because the point of the key is that he edits
it and sends it again (`InputBox.restore`, `Main.qml`'s `undoSend`).

**HOW A RUNNING SOLOMON IS ACTUALLY STOPPED**, given that he is a model run
nothing here can reason with: **every act he is allowed goes through
`boardctl.py`**, so that is where the teeth are. `board-watch._summon` calls
`boardundo.begin_run()` with the drained orders immediately before it spawns;
every write verb in `boardctl` calls `boardundo.claim()` first, which STAMPS the
run as having acted and returns False — refusing the verb — if he cancelled it.
`cancel()` marks and then reads `acted` back. Both take the same `flock` on the
same file in the opposite order, which is why the answer is never a guess: either
the mark landed first (nothing went out, and nothing now can) or the stamp did
(something is already out there). **There is no interleaving that both summons a
minister and tells him it did not.**

- **The ungated verbs are `list`, `agents`, `phase` and `inbox take`.**
  Everything else is gated, and gating is the DEFAULT — a verb added later is
  refused after a ctrl+z without anybody remembering to add it to a list.
- **A summon that has ALREADY gone out is reported, not half-undone** (§10.2).
  `summoned` → *"too late - a minister has already been summoned for it"*, and
  nothing is touched: no worker is killed, no note is retracted.
- **One order out of a summoner's several is refused too** (`shared`). The gate
  is per run, so cancelling would abandon the other orders — and *"that specific
  inbox item"* is the opposite of that. It says how many others are in there.
- **A cancelled run writes NOTHING.** `board-watch` reads `end_run()`'s verdict
  and skips the `QUEUE_FAIL` path, because a run he took back did not fail: his
  sentence is in the prompt box, which is where he asked for it. No dispatch, no
  handoff, no note, and the other orders in the queue are untouched.
- **The key is only bound while it can do something.** `Agents.canUndo` is polled
  off `boardundo.undoable()`, and the `Shortcut` is additionally off whenever his
  caret is in a text field (`win.inAnEditor`) — there, Ctrl+Z is ordinary text
  undo, which is the undo he meant. An offered undo that no-ops is the §10 defect
  this app is not allowed to draw.
- **A draft already in the box survives it.** The cancelled order is inserted
  ABOVE what he had typed and the footer says so, rather than overwriting a
  sentence of his — `InputBox.qml`'s standing rule, and the case is real (type,
  send, type again, click away).
- **A reply to a chore is not an order.** It takes the same `send()`, but it also
  cleared a bullet, so ctrl+z does not claim it (`Agents.notAnOrder`) and `put it
  back` in the row menu stays that act's own undo.
- **Nothing is deleted.** `inbox/cancelled/` is another resting place beside
  `queue/`, `taken/`, `dropped/` and `editing/`; the conservation property holds
  across it, and moving the order OUT of `taken/` is also what stops
  `requeue_taken()` handing a cancelled order to the next run.
- **The last order he sent is a FILE** (`~/.local/state/board/last-order.json`),
  not memory, so the key still works after the window has been closed and opened.

Harnesses: `tools/board-test.py` → `test_undo` (the mechanism, the three answers
that are NOT a cancellation, and `boardctl` refusing in a real subprocess) and
`test_undo_window` (a real `Ctrl+Z` through `QTest.keyClick`, the box refilled,
the label). `tools/board-watch-test.py` → `test_cancelled_summoner` covers the
only half a real tick can show: a cancelled summoner exits nonzero and still
leaves nothing on the board.

**Agents reach their side with `boardctl.py inbox take`** — `BOARD_AGENT_ID`
names the inbox, board-watch's prompt tells every agent it spawns to check it
between steps, and an interactive session finds its own id by walking its
process ancestry. **Only agents spawned after this landed have that line in
their prompt**; an older one will never look, which is exactly what the
escalation exists for.
