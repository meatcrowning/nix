# goetia — decision board

The program is called goetia in its window title, desktop entry, and binary.
Its store and identifiers deliberately remain board*: apps/board/, boardctl.py,
board.nix, board-watch, ~/.local/state/board/, Board, kind="worker",
board-worker-*.service, boardctl.py agents, the agents section, ~/.cache/board-work/,
and socket/log keys. There is one store per host: docs/board.top.md on top and
docs/board.book.md on book; never merge them. The default invocation reads this
host's store; an explicit board-shaped path is also accepted.

The source is main.py, boardparse.py, boardmove.py, boardagents.py, boardwork.py,
boardphase.py, boardhermes.py, boardusage.py, boardundo.py, and qml/. The hermes
runtime reads its card/drawer from hermes's session store when no transcript file
exists; see guide/cards.md. home/prog/board.nix runs the live source at
/home/lam/nix/apps/board/main.py, including the air system-python split, so
.py/.qml edits need no rebuild. Read ../AGENTS.md and ~/nix/docs/DESIGN.md first.

## User-facing vocabulary

Anything rendered or written for the user says spirit/spirits, never agent or
worker: labels, placeholders, framing prose, the cap dropdown, boardctl output,
and all board-watch/templates. The triangle remains internally the agents section
beneath Solomon's summoner section; do not rename identifiers. Wrapped templates
have fixed geometry: spirit is three characters longer than agent, so preserve
line lengths and run tools/board-watch-test.py after changing FAIL_TEMPLATE.

## Guide routing

This file is only the map. Read the guide matching the change, then grep it;
do not load every guide at once.

- guide/store.md: per-host store shape; NEEDS YOU decisions; WAITING ON YOU TO DO
  tagged actions; LANDED rows; timestamps/authorship; one item per ask; no-pressure
  behavior; and answer/start moves.
- guide/orchestrator.md: boardwork.py, batching, model/tier and concurrency
  controls, handoff, spawn context, non-blocking dispatch, delegation, and
  clearing summon notes.
- guide/cost.md: burst coalescing, tier choice, and relay.
- guide/cards.md: the triangle, summon/card lifecycle, stable spirit names,
  Solomon, claimed versus observed phase, withheld top lines, and transcript cards.
- guide/controls.md: input, four dropdowns, usage, queued-item correction, and
  real Ctrl+Z cancellation.
- guide/drawing.md: no-clobber defenses, rendering, the prose-deleting clear,
  hyprvtb chrome, usage button/countdown, and font glyph limits.

## Verification

Run the offscreen harness; the user performs the appearance check. On top, do not
source the wrapper as a program: remove its final exec line, source the env, and
invoke its Nix Python.

~~~bash
W=$(readlink -f "$(command -v goetia)"); sed '$d' "$W" > /tmp/brdenv.sh
( . /tmp/brdenv.sh; "$(tail -1 "$W" | grep -o '/nix/store/[^\"]*/bin/python3')" \
    apps/board/tools/board-test.py --shots /tmp/board-shots )
~~~

On book, sourcing the air wrapper (a shebang plus exec) launches goetia on the
user's screen. Invoke the system interpreter directly:

~~~bash
/usr/bin/python3 apps/board/tools/board-test.py --shots /tmp/board-shots
~~~

board-test.py must be offscreen and redirect BOARD_TRANSCRIPTS to synthetic
transcripts, XDG_STATE_HOME to scratch, and all writes to a copy of the store.
Stub Titlebar, export BOARD_USAGE_OFFLINE=1, and never write ~/.claude (it syncs
to book) or ~/.local/state/board. test_usage_fetch is the exception: unset the
offline flag and use its stub urlopen.

The harness covers: test_todo_tags (valid tags, malformed/untagged writes refused,
legacy bullets, FAILED templates, one item per ask, splitting, hostile text and
prompts); test_summon_cleared (matching result/id/name clears only its SUMMONED or
COMMANDED note, including wrapped/stamped forms); test_landed (git time, timeless
unknown hashes, two-cell rows and one header widening); test_phase (tool classifier,
byte-offset tailing, partial lines, missing sessions, honest stalled wording and
claim/card divergence); and test_work (cap/oldest queue, exactly-once persistence,
dead-slot promotion, stable unique ASCII names, stopped sweep, ask gating and
board-watch seed).

Round-trip tests preserve bytes except intended one-line edits, radio markers, the
> marker, and atomic writes. test_todo_remove checks exact wrapped removal, undo,
middle/last/empty cases, stale-index refusal, double-click semantics and reply.
Move tests cover start/land/back/note/reconcile, unchanged IN FLIGHT text, refusal
of unanswered work, dead-owner reclaim and stale-edit retry. Conservation tests
keep every message exactly once in one directory. Store tests require a title,
if-unanswered line, answer destination, and font audit.

Window tests run qml/Main.qml with QT_QPA_PLATFORM=offscreen and cover stale and
external/renamed-store edits, all section redraws while preserving scroll/draft,
empty sections, running/failed/finished cards, one unattached input and exactly-once
queue writes, flat oldest-first cards with present/stopped two-sentence wording
and no time/age/count, plus PNG cases for real/fixture/answered/empty/unreadable
stores. Stub /proc where needed because the harness itself runs in a session.
Visual appearance is checked by the user, never by screenshotting the live desktop.

## Invariants

State belonging to another board must never enter this host's state directory.
boardparse.scratch_state_dir routes non-default boards under XDG_RUNTIME_DIR;
lock_path and boardmove.start use it, while explicit XDG_STATE_HOME still wins.
Existing state is not deleted and boardphase sidecars use the same locked path.
Keep test_scratch_state, which deliberately checks the real directory in isolation.

No clock path may scan the machine on the GUI thread. boardspend._summary memoizes
transcript summaries by size/mtime; Spend reads on a worker and applies results
through its private signal. !Spend.known may appear briefly on cold start; that
is honest state, not a zero to paper over.
