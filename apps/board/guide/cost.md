# What a run COSTS (`boardwork.py` + `board-watch.py`): the batch, the tier, the relay

*The three levers on what one of his asks costs to work: waiting out a burst so
it is planned once, tiering each dispatched piece to a model that fits it, and
bounding how long one spirit runs. Spawning, the cap and the handoff are in
[`orchestrator.md`](orchestrator.md); read that first — this file assumes it.*

Part of goetia's guide — the map and the shared rules are in
[`../AGENTS.md`](../AGENTS.md).

**Why there is a file for this at all.** Measured on `top` for the week to
2026-08-01 (`docs/claude-usage-2026-08-01.md`): the spirits were $4,426 of the
spend against the summoners' $911, **84% of every dollar was context re-read
rather than output**, and per-turn cost climbed with session length (42k
cache-read/turn at 22 turns, 151k at 163). The summoner dropdown had tiered the
planner and nothing had touched the other three quarters. The spec these three
were built from is `docs/goetia-request-management.md`.

---

### A BURST IS ONE PLANNING PROBLEM: the coalescing window

[his, 2026-08-01] *"being able to send a multitude of requests in either a
single or multitude of prompts"*. How he split his thinking into box-fulls is
not how the work divides, so `drain_queue()` can wait out the rest of a burst
and hand the whole of it to ONE summoner, which can then group it by file set.

The coalescing hold lives in `drain_queue`, upstream of `work_the_queue`, so it
is the same hold whatever the summoner dial says: what it buys is that a burst
of two or more reaches ONE Solomon for the file-set
coordination this section is about.

- **A LONE SENTENCE WAITS FOR NOTHING** — `COALESCE_QUIET_S` is **0**. This
  shipped as a flat 75 s and he felt it within the hour (*"why does it take
  seemingly minutes for prompts to get picked up and acted upon"*), then at
  10 s and he felt that too (*"it still took like a few seconds even though no
  summoners were busy"*). Both readings are right: measured from the journal,
  `board-inbox.path` starts the tick **~100 ms** after the queue file appears,
  so ANY hold here is the entire delay he can see before a summoner starts —
  and for one sentence it buys nothing, there being no second item to batch it
  with.
- **`COALESCE_BURST_S` (40 s) applies only once TWO OR MORE are queued**, which
  is the only state that PROVES a burst instead of guessing at one. Nothing
  ever waits on a guess.
- **Bounded from both ends**, which is what stops a hold becoming a stall: it
  ends when the newest item has been quiet for the window, AND unconditionally
  once the OLDEST has waited one window. So a batch is planned at most `window`
  seconds after its first sentence however fast he keeps typing, and a queue
  that has been SITTING — behind a running summoner, say — is planned at once,
  being already coalesced by definition.
- **The other half of the batching is free and needs no window at all**:
  board-watch holds the flock while it waits on a summoner, so everything typed
  during a run is drained together by the next tick whatever these are set to.
- Env: `BOARD_COALESCE_QUIET` / `BOARD_COALESCE_BURST`.
- **For scale, what the hold is measured AGAINST**: over ~190 runs in
  `~/.cache/board-watch.log` the summoner itself is a median ~50 s, p90 ~2 min,
  tail 3-6 min, and nothing is dispatched until it finishes. That, and not this
  window, is where the wait between his sentence and a spirit card lives.
- **It SLEEPS inside the run, holding the flock — it does not return.**
  `board-inbox.path` is `PathExistsGlob` and level-triggered, so returning with
  the queue still full is a respawn every few hundred milliseconds for the
  length of the window. Holding the flock means every trigger arriving
  meanwhile is already a no-op, and it is the same shape as waiting on a
  summoner (up to 15 min) for a fraction of the time.
- **A sentence typed DURING the hold joins the same batch** and pushes the
  window out — the queue is re-read after every sleep. That is the whole point:
  the batch then reaches ONE summoner, which can group it by file set instead
  of two summoners dispatching two
  spirits into the same files.
- **Nothing is dropped and nothing is promised.** The queue is left exactly as
  it was until it is drained, and the box's footer already says only *"in the
  inbox - ctrl+z takes it back until a summoner acts"* — so nothing drawn
  becomes a lie, and Ctrl+Z gets a WIDER window, not a narrower one.
- An item with no `sent` stamp is planned NOW rather than held: it is one this
  cannot reason about, and the safe answer for a message of his is to work it.
- Harness: `tools/board-watch-test.py` → `test_coalescing`. Every other test
  there sets `BOARD_COALESCE_QUIET=0` by default, or each would take 75 seconds
  longer.

### WHICH TIER a spirit runs on, per piece of work

**`dispatch --model` names the tier, and it is stored on the task record.** The
summoner dropdown tiers the PLANNER (~9% of the spend); every spirit — the
43% — read one global dial, so a doc edit and a compositor C++ change spawned on
the same model. `boardwork.spirit_tier()` resolves what the planner asked for
(`resolve_spirit`'s forgiveness), `dispatch()` stores `(model, effort)` on the
record, and `_spawn_worker` picks the BACKEND from that record's model —
so a deepseek-tiered spirit reaches hermes rather than Claude carrying a
deepseek flag.

- **His dial (`spirit-model`) is the DEFAULT a dispatch tiers UP from**, not a
  ceiling. [his, 2026-08-02] it defaults to `deepseek v4`, so a dispatch naming
  no tier runs cheap and off the weekly Claude window; Solomon names a higher
  `--model` only for work that needs one. (The hard `role_flags` clamp — opus 5
  medium — is a separate, higher SAFETY cap, untouched.)
- **Resolved at DISPATCH, not at spawn.** A task that queues above the cap runs
  on the tier it was planned with, not on whatever the dial says whenever
  `promote()` finds it a slot.
- **An unreadable tier is his dial, never a cheap guess**, and `boardctl` SAYS
  so rather than falling back silently. The `role_flags` clamp still runs last
  and independently, so no route here can spawn a spirit above the ceiling.
- **The prompt's rubric makes deepseek-flash the DEFAULT** (inventories,
  surveys, doc edits, mechanical renames, anything within what deepseek can
  usually handle) **and Solomon tiers UP from it, by difficulty, only for work
  that needs it**: haiku 4.5 then sonnet 5 for a change whose shape is decided,
  up to a ceiling of `opus 4.8 medium` for the plugin's C++, QML, anything
  visual, `docs/DESIGN.md` reads and multi-file design work — work that
  demonstrably needs it, not uncertainty. **WHEN IN DOUBT, TIER DOWN**: unsure
  whether a piece needs more than deepseek, prefer the default unless the piece
  is plainly more than mechanical, and before reaching for opus consider
  splitting the piece into simpler models working together on disjoint files —
  each cheap, running in parallel. Higher than opus 4.8 medium he is ASKED
  first. A spirit on too small a model does not fail where he can see it: it
  half-lands the work and reports `ENACTED` — so tier UP when the work
  genuinely exceeds the cheap model, never because the difficulty is
  uncertain.
- Harness: `tools/board-test.py` → `test_tier`.

### The RELAY: a spirit hands the rest on rather than running long

**`RELAY_TURNS` (60) is a turn budget, and reaching it is a HANDOVER, not a
kill.** A session's cost is quadratic in its turns — everything already said is
re-read on every turn after it — and the measured average spirit was 118 turns
with cache-read per turn climbing 42k → 151k across that range.
`WORKER_TIMEOUT_S` bounded the wall-clock and nothing bounded the turns.

- **`boardctl.py turns`** reads the count from the spirit's own transcript
  (the file `boardphase` already tails) and says whether to hop. An unreadable
  count — a hermes spirit, a transcript not written yet — is the honest
  unknown and NEVER advises a hop.
- **`boardctl.py relay '<brief>'`** writes the successor into `work/pending/`
  carrying the brief, the same tier, the same `--where` and `relay: n+1`, and
  `promote()` starts it next tick like anything else over the cap.
- **Why not `--max-turns`:** a hard CLI cut leaves the tree half-edited and is
  indistinguishable from a crash to `reap()` — filed `failed`, with a `FAILED:`
  bullet for work that was going fine. Here the ending is voluntary: the
  successor exists before the exit and **the hop stamps `mark_reported()`**, so
  the finished spirit reaps as `done`. The `relay` call IS its report.
- **`RELAY_MAX` (4) is the depth cap**; the last hop is refused and told to
  report the remainder as `PARTIAL:`. A relay is not a `retried` — the two marks
  stay distinct because the causes do (a budget reached vs a platform death).
- **A spirit that cannot hop is not told the mechanism exists.**
  `relay_block()` renders rule 14 only when there is a hop left, because every
  line in that prompt is re-read on every turn of the session it is telling to
  be short.
- Harness: `tools/board-test.py` → `test_relay`.
