# What a run COSTS (`boardwork.py` + `board-watch.py`): the batch, the tier, the relay

*The three levers on what one of his asks costs to work: waiting out a burst so
it is planned once, tiering each dispatched piece to a model that fits it, and
bounding how long one minister runs. Spawning, the cap and the handoff are in
[`orchestrator.md`](orchestrator.md); read that first — this file assumes it.*

Part of goetia's guide — the map and the shared rules are in
[`../AGENTS.md`](../AGENTS.md).

**Why there is a file for this at all.** Measured on `top` for the week to
2026-08-01 (`docs/claude-usage-2026-08-01.md`): the ministers were $4,426 of the
spend against the summoners' $911, **84% of every dollar was context re-read
rather than output**, and per-turn cost climbed with session length (42k
cache-read/turn at 22 turns, 151k at 163). The operator roster had tiered the
planners and nothing had touched the other three quarters. The spec these three
were built from is `docs/goetia-request-management.md`.

---

### A BURST IS ONE PLANNING PROBLEM: the coalescing window

[his, 2026-08-01] *"being able to send a multitude of requests in either a
single or multitude of prompts"*. How he split his thinking into box-fulls is
not how the work divides, so `drain_queue()` **waits for the queue to go quiet
for `COALESCE_QUIET_S` (75 s) before planning any of it**, bounded by
`COALESCE_MAX_HOLD_S` (300 s) measured against the OLDEST queued item so a
steady typist is still planned promptly and a hold can never become a stall.
Both are `BOARD_COALESCE_QUIET` / `BOARD_COALESCE_MAX`.

- **It SLEEPS inside the run, holding the flock — it does not return.**
  `board-inbox.path` is `PathExistsGlob` and level-triggered, so returning with
  the queue still full is a respawn every few hundred milliseconds for the
  length of the window. Holding the flock means every trigger arriving
  meanwhile is already a no-op, and it is the same shape as waiting on a
  summoner (up to 15 min) for a fraction of the time.
- **A sentence typed DURING the hold joins the same batch** and pushes the
  window out — the queue is re-read after every sleep. That is the whole point:
  the batch then reaches ONE summoner (`route_groups` groups it by operator),
  which can group it by file set instead of two summoners dispatching two
  ministers into the same files.
- **Nothing is dropped and nothing is promised.** The queue is left exactly as
  it was until it is drained, and the box's footer already says only *"in the
  inbox - ctrl+z takes it back until a summoner acts"* — so nothing drawn
  becomes a lie, and Ctrl+Z gets a WIDER window, not a narrower one.
- An item with no `sent` stamp is planned NOW rather than held: it is one this
  cannot reason about, and the safe answer for a message of his is to work it.
- Harness: `tools/board-watch-test.py` → `test_coalescing`. Every other test
  there sets `BOARD_COALESCE_QUIET=0` by default, or each would take 75 seconds
  longer.

### WHICH TIER a minister runs on, per piece of work

**`dispatch --model` names the tier, and it is stored on the task record.** The
operator roster tiered the PLANNERS (~9% of the spend); every minister — the
43% — read one global dial, so a doc edit and a compositor C++ change spawned on
the same model. `boardwork.minister_tier()` resolves what the planner asked for
(`resolve_minister`'s forgiveness), `dispatch()` stores `(model, effort)` on the
record, and `_spawn_worker` picks the BACKEND from that record's model —
so a deepseek-tiered minister reaches hermes rather than Claude carrying a
deepseek flag.

- **His dial (`minister-model`) becomes the CEILING rather than the setting**,
  which is the word this guide already used for it. A dispatch naming no tier
  gets exactly what it got before.
- **Resolved at DISPATCH, not at spawn.** A task that queues above the cap runs
  on the tier it was planned with, not on whatever the dial says whenever
  `promote()` finds it a slot.
- **An unreadable tier is his dial, never a cheap guess**, and `boardctl` SAYS
  so rather than falling back silently. The `role_flags` clamp still runs last
  and independently, so no route here can spawn a minister above the ceiling.
- **The prompt's rubric is deepseek-flash for inventories/surveys/doc edits,
  haiku/sonnet for a change whose shape is decided, the ceiling for the
  plugin's C++, QML, anything visual and anything ambiguous — and WHEN IN
  DOUBT, TIER UP.** A minister on too small a model does not fail where he can
  see it: it half-lands the work and reports `ENACTED`.
- Harness: `tools/board-test.py` → `test_tier`.

### The RELAY: a minister hands the rest on rather than running long

**`RELAY_TURNS` (60) is a turn budget, and reaching it is a HANDOVER, not a
kill.** A session's cost is quadratic in its turns — everything already said is
re-read on every turn after it — and the measured average minister was 118 turns
with cache-read per turn climbing 42k → 151k across that range.
`WORKER_TIMEOUT_S` bounded the wall-clock and nothing bounded the turns.

- **`boardctl.py turns`** reads the count from the minister's own transcript
  (the file `boardphase` already tails) and says whether to hop. An unreadable
  count — a hermes minister, a transcript not written yet — is the honest
  unknown and NEVER advises a hop.
- **`boardctl.py relay '<brief>'`** writes the successor into `work/pending/`
  carrying the brief, the same tier, the same `--where` and `relay: n+1`, and
  `promote()` starts it next tick like anything else over the cap.
- **Why not `--max-turns`:** a hard CLI cut leaves the tree half-edited and is
  indistinguishable from a crash to `reap()` — filed `failed`, with a `FAILED:`
  bullet for work that was going fine. Here the ending is voluntary: the
  successor exists before the exit and **the hop stamps `mark_reported()`**, so
  the finished minister reaps as `done`. The `relay` call IS its report.
- **`RELAY_MAX` (4) is the depth cap**; the last hop is refused and told to
  report the remainder as `PARTIAL:`. A relay is not a `retried` — the two marks
  stay distinct because the causes do (a budget reached vs a platform death).
- **A minister that cannot hop is not told the mechanism exists.**
  `relay_block()` renders rule 14 only when there is a hop left, because every
  line in that prompt is re-read on every turn of the session it is telling to
  be short.
- Harness: `tools/board-test.py` → `test_relay`.
