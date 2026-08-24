# `oracle` — a minimal ollama chat window

**User-facing name is "chatter"** (window title, `Name=` in the desktop
entry) — presentation only, same as goetia keeps its store named board. The
source directory, module/file names, `ORACLE_SANDBOX`, and the runtime data
paths (`~/.local/share/oracle/{sandbox,sessions}`) all keep the `oracle` name
on purpose, so existing sessions and the sandbox jail need no migration.

**Commit messages for this app say `chatter:`, not `oracle:`** (his call) —
the subject line and any human-facing prose about it use the presented name,
matching every other reference he reads. Only the directory and identifiers
(`apps/oracle`, `ORACLE_*`, module names) keep `oracle`; those are internal.

The smallest of the vendored apps, and deliberately so. Two things at its core:
a **model selector** filled from the local ollama daemon's `/api/tags`, and a
**prompt box** that sends one chat turn to `/api/chat` and shows the reply as it
streams. It also keeps its **conversation sessions**: every conversation is a
named, persisted transcript you can switch between (*Sessions* below), and a
selectable **base system prompt** — a handful of built-in presets plus your own
editable custom text (*The base prompt* below). It remembers the **model
selector** too — the model last used and an agent-suggested ranking (see *The
model selector* below).

## "server", not "ollama"

**Every string he reads says `server`** [his, 2026-08-23] — the status bar
(`server running` / `server · <model>` / `server down`), the start/stop reasons the
askpass dialog shows, the pull heading. Which daemon is behind it is an
implementation detail and the name of one is noise in a status bar. The
model-facing text keeps `ollama` where it is a technical fact (the endpoint in
`describe_self`, the tool descriptions), and so does every identifier.

The two halves say different kinds of thing, and neither repeats the other:
the **left** is what is HAPPENING (`generating…`, an error, a server action's
result) and the **right** is the standing fact (jobs, then the daemon). So the
left names its resting state — **`idle`**, whenever the daemon is up and no
turn is in flight — because a blank left half is also what a wedged window
looks like [his, 2026-08-23], and `stopReply()` clears `win.status` so the
line the interrupted turn was last saying about itself does not stand after it
is over. With the daemon down the left is empty: the right already says
`server down`, and `idle` beside it would be a claim about a server that is
not running.

## Two roofs

**Under Plasma, chatter is a REAL KDE window** — a `QMainWindow` with a real
menubar, toolbar and status bar, built by `pylib/kdeshell.py` (the third app to
get one, after painter and player; read `apps/AGENTS.md` → kdeshell BEFORE
touching any of it, and docs/DESIGN.md §7.6 for why). The Hyprland face is
exactly what it always was.

- **`qml/Root.qml` is the whole app, as an `Item`**; `qml/Main.qml` is the
  Hyprland session's `Window` wrapper around it. Nothing Window-only lives in
  Root — the title is published as `windowTitle`.
- **The four header rows collapse in that session.** model, session, base
  prompt and server become: two `QComboBox`es on the toolbar (model, session),
  the File menu's session rows, the Settings menu's base-prompt radio set, and
  the Tools menu's Unload/Start/Stop with the observed state in the status bar's
  right-hand slot. They stay in the tree at zero height, not branched away, so
  every id they carry (the three dropdowns, the prompt editor) still resolves
  and one file still serves both faces.
- **`actions` is the table, and it reaches no socket.** chatter registers no
  hyprvtb buttons — the compositor draws only its title — so this table exists
  for the KDE chrome alone (`bind_chrome(None)`, bound to `actionsChanged`).
  `Titlebar.setButtons` is never called; adding a row here cannot change the
  Hyprland window. `tbAction(id)` answers every id, including the `session:` and
  `prompt:` prefixes the two radio sets are built from.
- **Deleting a session is asked about first** — the one row that destroys
  something of his, with no undo in the store. A constructed `QMessageBox` with
  `DontUseNativeDialog`, shown modelessly: the static helpers segfault this
  stack (apps/AGENTS.md).
- **The two pickers sit at the RIGHT end of the toolbar** [his, 2026-08-22] —
  a `QToolBar` has no alignment of its own, so an expanding blank `QWidget` in
  front of them takes every pixel the action buttons leave.
- **Seven components have `+plasma` twins**, swapped by the file selector with
  the same API either way: `PromptBox` (the compose box as the STYLE'S OWN
  INPUT — a `ScrollView` holding a `TextArea` that keeps the background
  qqc2-desktop-style gives it, beside a real `Button`. It was a `Frame` around a
  background-less TextArea until 2026-08-22, and that is a group box's relief:
  the window colour behind a flat outline, where Oxygen draws an input as a
  recessed hole — a dark View-coloured fill in a rounded inset frame. [his] *"is
  the bottom prompt section in style for oxygen? i feel like it's not"* — it was
  not), `Chip` (the attachment chip as a flat `Button`),
  `Bubble` (a message as a real KStyle `Button` frame — `enabled: false` so it
  takes no hover, press or focus, with the message's own selectable text drawn
  above it), and, from the Oxygen audit of 2026-08-22 [his] *"the scroll bar is
  not properly themed, but im sure there are other things as well"*:
    - **`ViewFrame`** — the conversation's surround. Ours was a 1px rounded
      Rectangle sitting directly above the compose box's real `Frame`: two
      surrounds, two reliefs, one window. The twin is that same `Frame`, and the
      content's inset is the frame's own `pad`.
    - **`PromptEditor`** — the custom-prompt panel (Settings ▸ Edit Custom
      Prompt…), which in that session was an accent-bordered aero box with
      lowercase pixel `cancel` / `save` inches from the toolbar's real buttons.
      The twin is a `Frame` + `ScrollView`/`TextArea` + `DialogButtonBox`, so
      the words, the icons and the button ORDER are the platform's. It is a
      component now rather than markup in `Root.qml`: `load(text)` fills and
      shows it, `saved(text)` / `cancelled()` report the choice, and Root.qml
      still decides what saving MEANS (it writes `Ollama`).
    - **`CapChip`** — a capability indicator, as the KStyle's button frame with
      the label above it, the same non-interactive treatment `Bubble` uses.
      **Not `flat`**: a flat KStyle button draws no relief until it is hovered,
      and these never are, so flat left three bare words with nothing boxing
      them.
    - **`CtxMenu`** — the log's right-click menu (below), ours under Hyprland
      and the style's own popup under Plasma. Copied verbatim from player's
      pair; it is generic by design.
  `qmlcommon/+plasma/VScroll.qml` is the fifth fix and lives one level up,
  since every app shares it (apps/AGENTS.md → oxygenstyle).
- **`Meter.qml` and the picture frames in a reply keep OUR drawing on purpose.**
  A KStyle `ProgressBar` paints nothing inside the `QQuickWidget` (measured
  2026-08-22: blank in the app and blank in a standalone qqc2-desktop-style
  harness where a `Button` drew fine), and it is a ~20px control in a 16px text
  row besides. Both are readouts in the CONTENT, not chrome — the line the
  audit drew.
- **There is an `&Edit` menu**, added 2026-08-23. chatter was the only app of
  ours without one: Copy and Select All existed on the transcript's right-click
  menu and nowhere a menu could show them, so `Ctrl+C` had no home and no way
  to be discovered. Its three rows — **Copy** (Ctrl+C), **Copy Whole Message**,
  **Select All** (Ctrl+A) — run `runTextRow(i)`, which calls the SAME
  `textMenu()` rows the right-click menu does, so a reply is copied as markdown
  from either and the two cannot drift.
    - **They act on the message the selection is in.** A transcript is many
      independent read-only editors, so "Copy" has no single target the way it
      has in an editor; each body reports itself through `win.noteSelection()`
      on `onSelectedTextChanged`, and `win.selectedBody` is what the rows use.
    - **With no selection every row is DISABLED, not silently inert**
      (docs/DESIGN.md §10). `ORACLE_SELECT=1` makes a real selection in the
      longest reply — the only way a harness can see the rows live, since a
      selection otherwise only comes from a drag.
- **The transcript has a right-click menu** — Copy (dead while nothing is
  selected), Copy Message, Select All — because Ctrl+C on a mouse selection was
  the only way to get text out of it, and every other program on this desktop
  offers the menu. `win.textMenu(item, isMarkdown)` builds the rows; a reply is
  copied AS markdown (`Clip.copyMarkdown`, or `Clip.copyText` for the whole
  message), never as the flattened render. The labels follow the session: KDE's
  Copy / Select All there, lowercase here.
- **The harness renders it**, offscreen and never on his screen:

  ```
  QT_QPA_PLATFORMTHEME=kde DESK_SESSION=plasma ORACLE_CHROME=1 ORACLE_POKE=1 \
      ORACLE_FACES=1 ORACLE_SHOT=/tmp/chatter.png \
      oracle-qtenv python3 main.py --selftest     # then LOOK at the PNG
  ```

  `ORACLE_CHROME` prints the menus as text (a menu is not on screen until it is
  opened, so no render can show what is in one), `ORACLE_POKE` fires a few of
  them, `ORACLE_FACES` proves the file selector took, and `ORACLE_SELECT` makes
  a real text selection in the longest reply (what the `&Edit` rows are enabled
  by). `--selftest` points
  `ORACLE_CONFIG` and `ORACLE_SESSIONS` at a temp directory — poking Settings
  calls `setPromptChoice`, which persists, and a run without that override
  rewrote his own base prompt.

  Three things that make a render show STATE, not just the resting window:

  - **`ORACLE_POKE=edit-prompt,new-session`** names the rows instead of firing
    the default four, and works in BOTH sessions (under Hyprland the same ids
    go through the QML side's `tbAction`). It is the only way to photograph a
    panel with no other way in — the base-prompt editor opens from a menu row
    and nothing else.
  - **`ORACLE_MENU=1`** opens the log's right-click menu over the first reply
    and prints its labels. Needs `ORACLE_FAKE` for a reply to exist.
  - **A QQuickWidget's `grab()` returns its LAST RENDERED frame**, and
    `processEvents()` alone does not force a new one: a poke that opened a
    panel photographed byte-for-byte as the unpoked window until the harness
    started spinning the loop for ~0.8s afterwards. If a change you made does
    not appear in a shot, suspect this before suspecting the change.

## Shape

- **`main.py`** — the whole app. `Ollama` (on `QNetworkAccessManager`) is the
  only non-boilerplate class: `refreshModels()` GETs the tag list, `send(model,
  prompt, web)` POSTs a `stream: true` `/api/chat` and emits each NDJSON
  delta (`replyStarted`/`replyChunk`/`replyDone`, or `replyError`). One turn at
  a time — a new `send` aborts any reply still streaming. `Palette` and
  `Titlebar` are the same wal-palette-watch and vtb-chrome bridge every app here
  carries (copied from `reader/main.py`).
  - **The web_search tool loop.** `send` offers ollama a `web_search` function
    tool (`WEB_SEARCH_TOOL`) on **every** turn — no toggle, always on, same as
    the file tools (his call). If the model emits a `tool_calls` frame,
    `_on_finished` runs each call — `web_search` hits Tavily (`_tavily_search` →
    `TAVILY_URL`), the result is fed back as a `role: tool` message, and
    `_post_chat` re-posts so the model summarizes and cites. It loops until the
    model stops calling tools or `MAX_TOOL_ROUNDS` (4).
    `webSearchStarted`/`webSearchDone`/`webSearchError` surface the search to
    QML for its sources disclosure. The consequence is the same one the file
    tools already carry: **a model with no tool support rejects a request that
    carries `tools`**, so point oracle at a tool-capable model.
- **`qml/Root.qml`** (`qml/Main.qml` is the Hyprland `Window` around it) — the
  selector row — the model and session pickers **hug the window's right edge**
  with their labels beside them [his, 2026-08-22], sized to their own text and
  capped at 60% of the row — a `KineticFlickable`
  conversation area, and a prompt `TextEdit` (Enter sends, Shift+Enter newline).
  The model dropdown is inline rather than a shared `CtxMenu`, keeping this
  window's imports to the theme, `PixelText` and the `qmlcommon` Kinetic views.
  The conversation is a **persistent in-session LOG** (`ListModel chatLog`, a
  `Repeater` per turn): every send appends a `you` row and an assistant row and
  streams into the latter; prior turns stay in place and scrolled back, never
  scrubbed (docs/DESIGN.md §14). **The whole log is read-only selectable** so any
  message can be highlighted and copied: a model row's answer is drawn through
  **`qml/MarkdownText.qml`** (a read-only, `selectByMouse` `TextEdit.MarkdownText`,
  pixel idiom, themed links via `palette.link`) — the replies come back in
  Markdown, with fenced code blocks in the monospaced pixel face; user prompts
  and error lines stay verbatim on **`qml/SelectableText.qml`** (a read-only
  selectable `TextEdit`, pinned `PlainText`, the shared guard — the selectable
  twin of `PixelText`), so only trusted-shape strings are ever interpreted. Both
  selectable types pin the face as a whole `Theme.editorFont` QFont (an editable
  item ignores `antialiasing:false`, §2.2) and carry no `lineHeight` (Text-only).
  **Ctrl+C on a reply copies the MARKDOWN, not the flattened render** [his,
  2026-08-22]: Qt's own copy hands over the rendered document as plain text,
  which drops the blank line between paragraphs and every list marker, so a
  video prompt pasted into another program arrived as one run-on block. The key
  goes to `Clip.copyMarkdown` (main.py) instead — a whole-message selection
  copies the source verbatim, a partial one is re-serialised out of the document
  fragment and unescaped (Qt writes `\<Picture 1>` for `<Picture 1>`). `text` is
  NOT the source on a `MarkdownText` TextEdit — reading it back re-serialises the
  parsed document — so the call site sets `text` and `source` from one
  expression.
  It auto-follows the newest text to the bottom
  only while he is already at the bottom (see *The model selector* §streaming) —
  scroll up mid-stream and it stops yanking. A model's
  **Before the model has said anything** — no answer, no reasoning — the turn
  shows **`loading…`** with the same animated ellipsis, on its own line OUTSIDE
  the bubble [his, 2026-08-22]; it used to be a static `…` inside an otherwise
  empty bubble, which read as a message rather than as a wait.
  A turn's message sits in **`qml/Bubble.qml` — a BUTTON frame** [his,
  2026-08-22], not a tinted slab; it draws no hover or pressed state in either
  face, since the log is selectable text and nothing in it is clickable. A model's
  reasoning is a **collapsible disclosure, folded by default** (§9.1
  subordinated) that sits **OUTSIDE the bubble** [his, 2026-08-22] — as do the
  tool, web-search and file disclosures, all four between the speaker caption
  and the bubble, full width, so the bubble carries only the answer itself, whose heading reports progress: while the reasoning streams it
  reads **`thinking for 12s…`** (one brightness step up, the ellipsis animated),
  **`waiting…`** while a tool call is out, and settles to **`thought for 12s`**
  [his, 2026-08-22]. **The clock counts reasoning AND tool waits** — it accrues
  while `thinkingActive || awaiting` and pauses while the answer itself streams,
  so a turn that thought, searched and thought again reports the sum of the
  three rather than the wall clock of the whole turn (`win.accrueThink`, called
  after every flag change; `awaiting` is set by `toolCallStarted` and cleared by
  the next delta of any kind). Only the total `thinkMs` is saved, so a reloaded
  transcript still says how long each answer was worked on. To its LEFT, still
  and named, is the **token count** — `240 tokens`, `1.2k tokens` past a
  thousand (`win.fmtCount`); the animated ellipsis rides the STATE, never the
  count (dim, §9.1). A turn that only waited on tools still gets the heading,
  with no toggle on it — there is nothing to unfold. Harness:
  `tools/think-clock-test.py`, which drives the real `Root.qml` against a stub
  ollama and asserts the heading text the delegate actually renders — the count is the running frame
  count `Ollama` emits on `replyThinkTokens` (ollama streams one token per NDJSON
  frame), the ellipsis cycles 0–3 dots at one roll beat each (§6.2, static under
  reduceMotion). The token count PERSISTS in the heading once counted (the
  ellipsis is the only part that ends with the thinking), so a folded block
  still reports its size after the answer starts — the heading is all that shows
  when it is collapsed. **The model sees the whole current chat, not just the
  latest prompt**: every `send()` builds `history` from `chatLog` (skipping
  error rows and empty streams) and calls `Ollama.send(model, prompt,
  JSON.stringify(history))`; no cap on its length yet, so a very long chat
  resends its whole transcript every turn. Nothing persists **across
  launches** — only the current session's turns feed a send, and only while
  the window stays open (the selected model does persist — see *The model
  selector*; a whole conversation persists too, but only via *Sessions*
  below, and the model cannot see a past session unless it calls
  `read_session`).
  - **The sources disclosure** is the same subordinated, folded-by-default
    block for a turn's web searches: `searching the web…` (one step brighter,
    animated ellipsis) while a search is live, settling to `web · N sources`
    once results land. Its body is Tavily's own `answer` plus a themed-link list
    of the hits, drawn through `MarkdownText`. Several searches in one turn
    accumulate into it.
- **`qml/theme/Theme.qml`, `qml/PixelText.qml`** — verbatim copies of reader's
  (the theme-as-context-property idiom, see `apps/AGENTS.md`).

## The model selector

Two persisted inputs shape the dropdown, both optional and no-rebuild — drop the
file in and relaunch, same as `tavily.key`, and both live in `~/.config/oracle/`:

- **`last-model`** — one line, the model to pre-select. `Ollama.rememberModel`
  writes it on every pick and every send, so the model he last used is the
  default the next time he opens the window. On launch the selector defaults to
  `Ollama.lastModel` when the daemon still lists it, else the daemon's first
  model; a selection that is still valid is never overridden. He no longer
  reselects his model every launch.
- **`suggested.json`** — a JSON array of model name strings that AGENTS write to
  recommend a model (e.g. after benchmarking tool-calling support). Those that
  the daemon actually has are ranked **above** the rest of the dropdown, in the
  file's order; everything else follows alphabetically. `Ollama._order` does the
  ranking and publishes `suggestedCount` (the size of the leading group) so the
  dropdown rules a 1px `Theme.border` line off the suggested models from the
  rest (docs/DESIGN.md §7.2). Malformed or absent → no ranking, plain alpha
  order. Re-read on every `/api/tags` poll, so a mid-session write lands with no
  relaunch.

**Streaming no longer hijacks his scroll.** The reply view auto-follows the
newest text to the bottom only while he is already AT the bottom
(`replyFlick.followBottom`); the moment he scrolls up mid-stream it stops forcing
the position, and it re-arms when he scrolls back down to the bottom
(docs/DESIGN.md §6.1 — never yank his position).

**Model stats** (the `statsRow` readout, under the server note): the selected
model's **context ceiling** and the reply's **generation rate**, both true
numbers not guesses (docs/DESIGN.md §10). `contextMax` is read from ollama's
`/api/show` — the model's own `<arch>.context_length` in `model_info`, keyed off
`general.architecture`, never the filename (`refreshModelInfo`, run on every
model change and every send; 0/hidden when unknown) — but that ceiling is no
longer what the readout shows: see *The window is the real one* below. `tokensPerSec` is a running
estimate while a reply streams (one content frame ≈ one token, clocked from the
first frame) that settles to ollama's exact `eval_count / eval_duration` on the
final `done` frame. **`contextUsed`** is how full the context is — ollama's own
`prompt_eval_count + eval_count` from the last turn — drawn as `used/ceiling`, a
percentage, and a proportional **fill bar** (docs/DESIGN.md §9 meter; accent,
`warn` past 75%, `crit` past 90%; width animated §6). The row also carries **how many tool calls this conversation has made** and
**how many durable memories the model is carrying** [his, 2026-08-23] — both
standing facts about the chat on screen rather than about the turn in flight,
each drawn only once it is non-zero (§5.2). `toolCallCount` sums the rows'
`toolCount` and depends on `chatRev`, because a ListModel row settles without
notifying; `Ollama.memoryCount` is the length of the same cache the system
prompt injects, so the number and what the model actually knows are one thing.

**Under Plasma those two are the status bar's alone** — not drawn in the row
at all [his, 2026-08-23]. The row is the CONTEXT readout; a face that has a
status bar for standing facts does not also print them beside the context bar
(§7.6 — one source, two roofs, and only ever one of them at a time). The
Hyprland face has no status bar, so there they stay in the row. It collapses
to nothing until at least one stat exists.

### The window is the real one

**`contextMax` is the window ACTUALLY IN FORCE, not the model's trained
ceiling** [his, 2026-08-23: *"can you make the context indicator represent the
REAL amount of context i have based on my system specs for the given model?"*].
It read 262144 for qwen3.6:35b-a3b while every turn it ever sent ran in 32768 —
a true number about the model, and a lie about him. The trained ceiling is
`contextTrained`, kept for `describe_self` and the harness but **not drawn**: it
was there for one afternoon as a dim `of 256K` beside the readout and he had it
out again the same day — the second half of `used/window` is already the
ceiling that matters, and a third number reads as a repeat.

- **Loaded beats computed.** Once ollama has the model resident, `/api/ps`
  reports the `context_length` it was loaded in; that is the number, measured.
  `Backend`'s existing 3s poll hands the raw body to `Ollama.notePs` — one poll,
  two readers, rather than a second timer.
- **`CtxFit` sizes what has not loaded yet**, from free VRAM (`nvidia-smi`) plus
  `MemAvailable` over `CTX_RAM_FLOOR`, minus the weights when they are not
  already resident, halved (`CTX_FIT_SAFETY`), over the model's KV cost per
  token — capped by `CHAT_NUM_CTX_CAP` and by what the model was trained for.
- **The KV cost is MEASURED, never estimated.** `/api/show` cannot give it: a
  hybrid-attention model reports `head_count_kv: null` and does not say which of
  its layers hold KV (qwen3.6 keeps 10 of 40, so the metadata estimate is 4x
  out — in the direction that would have cut his window to ~9k). ollama prints
  the truth at load — `llama_kv_cache: size = 640.00 MiB ( 32768 cells, …)`,
  20 KiB a token — so `CtxFit.calibrate` reads that line out of
  `journalctl -u ollama.service`, once per model, and only when its cell count
  matches the window `/api/ps` reports. Cached in `CTX_FIT_STORE`.
- **A model never measured gets `CHAT_NUM_CTX`** — exactly what every model got
  before this existed. Nothing here can make a window smaller than it was.
- **The ladder, and the sticky window, both exist because `num_ctx` forces a
  RELOAD.** Only `CTX_LADDER` values are ever asked for, so free-memory jitter
  cannot bounce the window; and a model already loaded is asked for the window
  it is already in, so a newly measured fit applies at its next load rather than
  dropping 24 GB of weights mid-conversation.
- **`book` has no local `ollama.service`** (the daemon is on `top`, over the
  tunnel), so nothing calibrates there and the fallback is the whole behaviour.

Harness: `tools/ctx-fit-test.py`, with a stub ollama, a fake `journalctl` and a
fake `nvidia-smi` — it never reads the real journal or loads a model.

## The base prompt

A selectable **base system prompt** leads every turn's system message: a handful
of built-in **presets** (`default` — no persona, the historical behaviour —
plus `concise`, `coder`, `tutor`, `writer`, `casual`) and **your own custom
text**, picked from the *prompt* row (a boxed selector, docs/DESIGN.md §7.2, like
the model/session pickers) with an **edit** button that opens the custom-text
editor. The dropdown carries a **preview pane** (docs/DESIGN.md §9.1) that shows
the full text of the hovered preset — and the active custom text — so a base can
be read before it is chosen, not picked blind from a label.

- **`PROMPT_PRESETS`** (`main.py`) defines the presets (`id`/`label`/`text`);
  `custom` is offered in the QML dropdown alongside them. `_base_prompt()`
  resolves the active base (the custom text when `custom` is chosen, else the
  preset's text, else empty).
- **It only swaps the LEADING block.** `_system_prompt` prepends the resolved
  base ahead of the time line, the injected memory block, and the recall/save
  guidance — **all of which run regardless of which base is active**. A preset
  changes the model's persona; it never turns off memory recall.
- **Persisted** like `last-model`, no rebuild: `~/.config/oracle/system-prompt.json`,
  `{"choice": <preset id or "custom">, "custom": <your text>}`. The custom text
  is kept even while a preset is active. `setPromptChoice`/`setCustomPrompt`
  (slots) write it; `promptPresets`/`promptChoice`/`customPrompt` (properties)
  feed the UI. Malformed/absent → the `default` preset.

## What is on the wire — the core tools, and the index

**A turn carries 16 tool schemas, not 39** [his, 2026-08-23, after an agent in
chatter told him the schemas were context bloat: *"go for it"*]. Measured the
same day: the full set is **39,948 characters, ~13k tokens**, sent on every
round — against the 32k window that was most of the room, and it is why a
music-library turn had nothing left to answer with.

| | tokens |
|---|---|
| every schema, as it was | ~13,100 |
| `CORE_TOOL_NAMES`, on the wire now | ~4,630 |
| `tools_note()`, the one-line index | ~815 |
| **saved, every round** | **~7,650** |

- **`CORE_TOOL_NAMES` is what a turn reaches for unprompted**: the file six,
  the two runners, `web_search`/`fetch_url`, the clock, memory's two, and the
  three doors to everything else — `use_skill`, `spawn_agent`, `get_tools`.
- **`tools_note()` names every other tool in one line each** — name plus first
  sentence, capped at 90 characters. Same shape and the same reason as
  `skills_note()`: a model does not reach for a door it was never told about.
  This is the whole reason the saving is safe.
- **`get_tools(names)` attaches by name or by group** (`AGENT_TOOL_GROUPS` plus
  `EXTRA_TOOL_GROUPS` — the sets a subagent never gets) **and returns the full
  schemas in the same result**, so the model can call correctly on the very
  next round rather than guessing argument names. Attachments last the turn;
  every turn starts lean again.
- **A tool called straight off the index still RUNS.** `_dispatch_tool`
  resolves by name, not by what the payload happened to offer — it always did,
  which is what makes this cheap — and `_run_tool_calls` then attaches it for
  the rest of the turn, so no round is spent asking for a tool it has already
  used correctly. That self-attach lives in `_run_tool_calls`, NOT in
  `_dispatch_tool`, because subagents share the dispatcher and their tool sets
  are their own.
- **`describe_self` reports both**: `tools_available` is everything reachable
  (the registry), `tools_attached_now` is what this message carries. Neither is
  a remembered list; both are read off the same objects the payload is built
  from (docs/DESIGN.md §10).
- **Subagents are untouched** — their sets were already curated per definition,
  which is the same idea one level down.

Harness: `tools/lazy-tools-test.py`.

## Skills (chatter's own, as a real tool)

`use_skill` (`skill_tool()`, offered every turn, dispatched `_run_skill_tool`)
loads a **skill** — a set of expert instructions for one job — mid-turn, and
the model follows it, output contract and all. It is the same mechanism Claude
Code has, ported here in the same shape: the **catalog** (each skill's name and
`description`) is named in every system prompt (`skills_note()`), and the
**instructions** cost context only when the model actually calls the tool.

Until 2026-08-22 the one skill chatter had was `vidprompt`, a **base-prompt
preset** — which meant picking a persona for one message, getting a video prompt
for everything you said afterwards, and picking the persona back off. **That
preset is gone**; a persisted `{"choice": "vidprompt"}` falls back to `default`
by itself (`_load_prompt_config` already rejects an unknown id). One tool now
covers every skill, and a skill added under the skills root is offered with
no code change at all.

- **Where they live** — `SKILLS_ROOT` (`~/.local/share/oracle/skills` since
  2026-08-23, override `$ORACLE_SKILLS`): a directory per skill holding
  `SKILL.md` (YAML frontmatter `name`/`description`, then the instructions)
  plus reference guides in `references/`. **chatter's canonical base is its
  OWN runtime dir**, not `~/.claude/skills` — that dir belongs to Claude Code,
  and the two sets drifted apart (chatter reads its own, Claude Code its own).
  The old default (`~/.claude/skills`) and its claude-state sync are gone.
  **Since 2026-08-23 the runtime dir syncs BOTH WAYS between `top` and `book`
  on its own** (`home/srvs/oracle-skills.nix`, 5-minute timer, private remote
  `meatcrowning/oracle-skills`): a skill or agent written on either machine
  reaches the other with nothing to run by hand. The repo root is the whole
  runtime dir, so its `.gitignore` is an ALLOWLIST — only `skills/` and
  `agents/` are tracked, and `sessions/`, `memory/`, `jobs/`, `sandbox/` and
  `images/` can never be pushed. `*.md` merges by the recency driver the boards
  use (real 3-way first, newest side whole on a genuine collision), because an
  unresolved conflict would wedge the sync for everything else. Log
  `~/.cache/oracle-skills-sync.log`; force a run with
  `systemctl --user start oracle-skills-sync.service`. Today:
  `video-prompt`, `flux-klein-edit` (the painter edit-mode instruction),
  `krea-prompt` (the positive/negative image pair), `anima-prompt` (the same
  pair in Danbooru tags, for painter's anime mode), the machine-runbook set
  translated into chatter's vocabulary (`music-library`,
  `soulseek-acquisition`, `music-library-curation`, `goetia-board-agents`,
  `comfyui`, `media-library-organization`, and the four hardware-triage skills
  `nixos-hard-freeze-triage`, `nvidia-gpu-fault-triage`,
  `memory-corruption-diagnosis`, `linux-data-integrity-triage`), and the
  useful generic Hermes defaults ported in (`humanizer`, `systematic-debugging`,
  `youtube-content`). `~/.local/share/oracle/seed-skills-to-book.sh` is the
  superseded one-way push; the timer does this now. The
  machine-built `youtube-content` venv is excluded from both — book's first use
  of that skill rebuilds it from the skill's own setup block.
- **`use_skill(name)`** returns that skill's `description`, its `instructions`
  (the SKILL.md with frontmatter stripped) and the names of its `guides`;
  **`use_skill(name, guide=…)`** returns one guide **in full**, in ONE call —
  the point of it being a tool rather than the old preset's instruction to page
  through the file with `read_file`. Capped at `SKILL_MAX_CHARS` (40000; the
  largest guide today is ~24k) and a cut is reported in the result.
- **Read in-process, no host branch.** Unlike the sandbox/session/memory
  stores it is a plain local file read, so it runs wherever the window is —
  the runtime dir exists on each machine chatter runs on.
- **The `name` is an enum built from what is installed**, and the tool is not
  offered at all when the skills directory is missing (docs/DESIGN.md §10 —
  never an affordance that is not there). A `guide` is resolved by **basename**
  against the skill's own files, so a crafted path cannot escape the skill
  directory — the jail shape `sessions-store.py` uses for a session id.

## Subagents (spawn_agent)

`spawn_agent` (`spawn_agent_tool()`, offered every turn, dispatched
`_spawn_agent`) hands one self-contained job to a **subagent** — its own
message list, its own tool rounds, its own share of the window — and returns
**only its final answer** to the turn that spawned it.

**It is a second CONTEXT, not a second model** [his, 2026-08-23: *"would it be
worth giving agents the ability to spawn qwen3-coder (or similar)
subagents?"*]. A turn has one 32k window (`CHAT_NUM_CTX`) and
`MAX_TOOL_ROUNDS` rounds to spend in it, and the expensive tool results are the
ones worth least afterwards: a `search_text` over `~/nix` or a `read_file` on a
260 KB source costs thousands of tokens to establish one fact that fits in a
line. A subagent reads all of that in ITS context and hands back the line.

**So the default model is the parent's, deliberately.** Spawning
`qwen3-coder:30b` from a `qwen3.6:35b-a3b` turn means ollama unloading 22.3 GiB
and loading 17.3 — `top` runs `OLLAMA_MAX_LOADED_MODELS=1` (`sys/ai/ollama.nix`)
and those two do not fit in 30 GiB together — so a per-call model switch pays
two full reloads for one delegation. A definition may still name a `model:` when
that swap is worth it; nothing else does it.

- **Definitions are files**, `AGENTS_ROOT/<name>.md` (`~/.local/share/oracle/agents`,
  override `$ORACLE_AGENTS`): optional `---` frontmatter (`description:`,
  `tools:`, `model:`) and a body that IS that agent's system prompt. Like the
  skills root, this is chatter's **own** dir — not `~/.claude/agents`, which
  belongs to Claude Code. The two sets are deliberately separate, and this one
  rides the same `oracle-skills-sync` timer the skills root does — both ways
  between `top` and `book`, not via claude-state. None of it lands in this
  public repo.
- **Four built-ins are always there** (`BUILTIN_AGENTS`: `general`, `explorer`,
  `coder`, `researcher`), so an empty directory is not an empty menu — and a
  file of the same name **replaces** one outright, which is how either of you
  edits a built-in without touching `main.py`.
- **The model can write one, and is told so.** `agents_note()` lists the agents
  every turn (a model does not spawn what it was never told about — the same
  reason `skills_note()` exists) and names the directory, the frontmatter and
  the tool groups. It already has the file tools, so authoring a new specialist
  or fixing one that keeps getting something wrong is a `write_file`, not a
  code change [his, 2026-08-23: *"make it easier for oracle agents to modify
  themselves and future / other agents"*]. The note also tells it to SAY when
  it rewrites one he relies on.
- **`tools:` takes GROUPS** (`read`, `write`, `exec`, `web`, `sessions`,
  `skills`, `time`), individual tool names, or `all`. A name chatter does not
  have is **ignored** rather than fatal — a Claude Code definition naming
  `Read, Grep` is still a usable chatter agent — and a list that resolves to
  nothing falls back to the default set, because an agent that can do nothing
  is never what was meant (docs/DESIGN.md §10).
- **What a subagent never gets**: `spawn_agent` itself (it is absent from
  `_tool_registry()`, so subagents are one level deep by construction, not by
  a check that could be forgotten); the **image tools**, which render into the
  transcript of the turn that spawned it; and the **memory tools**, which write
  what the MAIN agent recalls.
- **A tool round is an object now** — `_new_round()` returns `{n, sink, done}`
  and every tool method writes into `remaining["sink"][idx]` instead of a
  single `self._tool_results`. That is what lets a subagent's round and the
  turn's own run at the same time without overwriting each other, and it is why
  `_spawn_agent` reaches every tool through `_dispatch_tool` — the same branch
  the main agent uses, rather than a second copy of it that would drift.
- **Non-streaming** (`stream: false`): there is no bubble to fill, the answer is
  a tool result.
- **Delegation is its OWN disclosure** (`agentStarted`/`agentProgress`/
  `agentDone` → the `agents` block in `Root.qml`), not the file block it used to
  borrow. That block said `files · N` about work that touched no file of his,
  counted a subagent's fourteen reads as the main agent's own tool calls, and
  reduced minutes of work to `agent explorer finished, 4 rounds`. Now the
  heading is the live agent, its round and the tool it just called while it
  works, and the body keeps one block per agent: who (with the **model**, when
  the definition names one that is not the parent's — that swap costs ollama a
  full unload and load, and was otherwise only audible), the full task, the
  rounds and tools it spent, and **what it answered**, that being the one thing
  that says whether delegating was worth it (docs/DESIGN.md §9.1, §10). A
  failure, an empty answer or a cut one names itself in the heading.
- **Bounded**: `AGENT_MAX_ROUNDS` (12), `AGENT_CTX_FRACTION` (0.7) and the same
  **wrap-up round** the main loop learned to do — a subagent out of rounds is
  re-posted with no tools rather than allowed to return a frame that is all
  tool calls and no prose. `AGENT_RESULT_CHARS` (12000) caps the answer and
  says when it was cut: an agent that returns 40k of pasted file is the problem
  it was spawned to solve.
- **One list for the payload and `describe_self`** — `Ollama._all_tools()`.
  Those were written out twice and had already started to drift.
- **Harness**: `tools/subagent-test.py` — drives a real spawn through the real
  window (offscreen) against a stub ollama and reads all four request bodies:
  the subagent gets its own system prompt and its own restricted tool list, it
  carries none of the main conversation, and **the bulk it read never enters
  the main context** It reads the rendered transcript too: the agent
  block names the agent, the task, the cost and the answer, and the subagent's
  `read_file` never lands in the turn's own tool list. Plus the definition rules (fallbacks, group resolution,
  a file replacing a built-in).

## Sessions

Every conversation is a **session**: a named transcript that persists and can be
switched to later. The session row (under the model row) is a picker showing the
current session, opening a list of every saved session, and a **+ new** that
starts a fresh one. The whole log always belongs to a session — nothing to opt
into — and it **titles itself from the first prompt** (truncated), so there is no
naming modal.

- **`Sessions`** (`main.py`) is the seam. It drives `tools/sessions-store.py` as
  a `QProcess` — the same async idiom the file tools use, so a save never blocks
  the UI — and exposes `sessions` (a list of `{id,title,updated,turns}`, newest
  first) plus `refresh` / `open` / `save` / `remove`. The **id is generated in
  QML** (`ensureSessionId`, a stable `sess-<ms>-<rand>`), so the store never
  mints one and there is no round-trip before the first save.
- **`tools/sessions-store.py`** is the store: one JSON transcript file per
  session under a root, pure stdlib, one JSON request on stdin → one JSON result
  on stdout (`list`/`load`/`save`/`delete`). Writes are atomic (`os.replace`).
  The id is validated as a bare filename so a crafted one cannot escape the root.
- **When it saves.** `saveCurrent()` persists the whole log on every finished
  turn (`replyDone`/`replyError`) and on a stop — never mid-stream. Only the
  display fields are stored; the transient stream flags are reset on load.
- **Where it lives** — `SESSIONS_ROOT` (`~/.local/share/oracle/sessions`,
  override `$ORACLE_SESSIONS`). ONE canonical store, not per-machine (his call,
  "for now"), kept where oracle's compute is — on `top`, reached from `book`
  over the tunnel's ssh master exactly like the file-tool sandbox.
- **The model can read past sessions too**, not just this one — a small
  **read-only** tool pair (`SESSION_TOOLS` in `main.py`, offered on every turn
  alongside the file/web/time tools): `list_sessions` (id, title, updated,
  turn count) and `read_session` (full transcript by id, see
  `SESSION_TOOL_NAMES`, dispatched in `_run_tool_calls` via
  `_run_session_tool`). It shells out to `tools/sessions-store.py` exactly
  like `Sessions` does — `list`/`load` ops only — over the same host branch
  (`Ollama._sessions_argv`, local on `top`, ssh from `book`, since `Ollama`
  and `Sessions` are separate QObjects with no cross-ref). No `save`/`delete`
  is ever exposed to the model, and `sessions-store.py`'s own id validation
  (a bare filename) is the only jail this needs — sessions already live
  outside `ORACLE_SANDBOX`, so this was the narrower option over widening the
  sandbox to cover them.

### When a turn happened

Every row carries **`ts`** — unix seconds, stamped when it is appended, saved
with the turn and read back on load (an old transcript with no `ts` reads 0 and
behaves as it always did). It exists because the model could not see time at
all: the system prompt is built at send time and says "the current time right
now", while the transcript under it was undated, so a session reopened three
days later read as if all of it had just been said and "earlier"/"yesterday"
were unanswerable.

- **In the history, only HIS turns are stamped, and only when stale.**
  `stampedBody` prefixes `[sent YYYY-MM-DD HH:MM local]` to a user turn older
  than `stampAfter` (1h). The model never sees its own output stamped, so there
  is no format for it to imitate, and his last stamp against the system
  prompt's "now" places the whole gap. A conversation held in one sitting goes
  to the model exactly as before.
- **On screen it is a date, once.** `opensNewDay(i)` is true only for the first
  row of a day that is not the previous row's, and that row draws
  `dayLabel(ts)` above its caption (docs/DESIGN.md §9.1). A same-day session
  draws nothing.
- Harness `tools/timestamp-test.py`, off the `ORACLE_TIMES` probe in the
  selftest's `ORACLE_FAKE` block (whose demo turns now span two days, so
  `ORACLE_SHOT` shows the divider).

## Memory (chatter's own durable facts)

Distinct from *Sessions*: a session is a past **transcript** the model can read;
a memory is a **fact chatter chose to keep**, created/edited/deleted by the model
itself and carried across every conversation — the board / Claude-memory pattern
(one fact per entry with a shared index). It is what stops "you told me your name
last week" from being distrusted: the model no longer has to go re-read an old
session to recall a durable fact, it saved one.

- **`tools/memory-store.py`** is the store: ONE `memories.json` under a root, a
  list of `{id,text,created,updated}`, pure stdlib, one JSON request on stdin →
  one JSON result on stdout. Ops: `list` (newest-updated first), `save`
  (`{text}` mints a `mem-<ms>-<rand>` id; `{text,id}` updates that entry), and
  `delete` (`{id}`). Writes are atomic (`os.replace`). Caps: ~4000 chars/entry,
  ~500 entries (a create past the cap drops the oldest-updated). Unlike the
  session store, the id is **minted here** so a create is one round-trip. Errors
  are `{"error": …}` with exit 0 — reported, never a crash (docs/DESIGN.md §10).
- **The three tools** (`MEMORY_TOOLS` in `main.py`, offered every turn beside
  the file/web/time/session tools): `save_memory(text, id?)`,
  `list_memories()`, `delete_memory(id)` (`MEMORY_TOOL_NAMES`, dispatched in
  `_run_tool_calls` via `_run_memory_tool`). It shells out to
  `tools/memory-store.py` over the same host branch as the session tools
  (`Ollama._memories_argv`, local on `top`, ssh from `book`) — the store lives
  on `top` with oracle's compute, so both machines share one set.
- **Recall is automatic, not a tool call.** `Ollama._memories` caches the list
  (`refreshMemories()` at launch, re-run after any `save_memory`/`delete_memory`
  lands), and `_system_prompt` prepends it as a "durable memories you saved
  (real facts, trust them)" block each turn — capped at `MEMORY_CTX_MAX` (60)
  entries / `MEMORY_CTX_CHARS` (8000) chars so a big store never crowds out the
  chat. So the model sees its memories every turn without calling
  `list_memories`; the tools are for writing and housekeeping.
- **Where it lives** — `MEMORY_ROOT` (`~/.local/share/oracle/memory`, override
  `$ORACLE_MEMORY`), an absolute `/home/lam/...` path like `SESSIONS_ROOT`.
  No UI surface: chatter manages these itself, they are not a picker.

## Self-introspection (describe_self)

`SELF_TOOL` (`describe_self`, offered every turn, dispatched `_describe_self`)
lets the model look up **everything it can access about itself** rather than
guess from training: the exact served model id and provider/backend, the app and
machine (hostname, OS, arch, cores, memory), the **context ceiling and current
fill**, the last **tokens/sec**, the active **persona / base prompt** (label plus
the leading text), the **saved memories** (count + capped list), the **tools
available this turn** (`_offered_tool_names`, the same list `_post_chat` sends —
so it is true, not remembered), the sampling options, and the conversation's
size. Synchronous and host-neutral; every fact is in-process or read live off the
host, and the machine facts are re-derived (never the private hardware notes),
keeping this public source clean.

**Honest capabilities every turn (`CAPABILITY_NOTE`).** A model does not call
`describe_self` on its own, so a static, honest summary of what the app actually
lets it do — the tool families it HAS, and the **limits** on them (no root, no
general internet beyond web search / image fetch / `fetch_url`, and the exact
bounds of the two code runners) — is appended to every system prompt (docs/DESIGN.md §10, honesty
in both directions, and never overstating a jail). It exists because gemma4:e4b
told him it "has no code-execution env": true at the time, but reached for blind
rather than from its real inventory. That gap is now closed — see *Code runners*
below — and `describe_self` still gives the exact live tool list on demand.

## Code runners (run_python and run_bash, on top)

`run_python` (`EXEC_TOOL`) and `run_bash` (`BASH_TOOL`) — both offered every
turn, both dispatched `_run_exec_tool` → `_exec_argv` — let the model actually
**execute code** instead of only reasoning about it — the board decision of 2026-08-11 (he ticked *add a jailed
code-runner*; running untrusted model output is a security call he took
deliberately). It runs through **`tools/sandbox-exec.py`** and returns
`{stdout, stderr, exit_code, timed_out, cwd, network_isolated, …}` fed back
into the same async tool loop as the file tools (`fileToolStarted`/
`fileToolDone` → the "files · N" disclosure; heading `running python` /
`running bash`, outcome `python exited 0` / `bash exited 2`).

**`run_bash` is the shell, added 2026-08-22** — his call: *"add bash tooling to
agents in chatter, not just python stuff. give them the same abilities and tools
you do when manipulating files"*. The file tools already reached the whole
filesystem, but the work an agent actually does to files is shell work — `grep
-rn`, `cp -a`, `git diff`, `find … -exec`, a loop over a directory — and having
to express each of those as a Python program was the last thing keeping this an
assistant rather than an agent. It is the **same runner**, not a second one:
`tools/sandbox-exec.py` takes a `lang` field (`"python"` default, so an old
caller is unchanged) and that is the only difference between the two — caps,
`cwd` rules, protocol, host branch and disclosure are shared, so they cannot
drift apart. `run_bash` takes `command` where `run_python` takes `code` (a model
that swaps them gets what it meant, not an empty-program error); bash runs the
script with the environment inherited, python still with `-I`. There is no
`sudo` and the tool description says so.

**It stopped being a jail on 2026-08-22** — his call, the same one that widened
the write root (*"i dont really want them to be [sandboxed]"*). What that
changed and what it did not:

- **The network is up.** The `unshare -rn` net+user namespace is no longer
  applied; `ORACLE_EXEC_NET=0` sends `--no-net` and puts it back (probed as
  before, so a host with no unprivileged user namespaces degrades honestly to
  `network_isolated: false` plus a `note_network` line rather than pretending).
  A runner that could rewrite his filesystem but not open a socket was theatre.
- **The working directory is a default, not a fence.** `SANDBOX_ROOT` is still
  argv[1] and still the default cwd — a scratch dir, which is all it usefully
  ever was — and a call may name its own `cwd` (absolute, or relative to that
  root; a missing directory is an error, never a silent fallback).
- **The resource caps are unchanged and stay**: wall clock (default 10 s, max
  30), CPU, address space, file size, per-stream output, and a timeout that
  kills the whole process group. Those protect this desktop from a runaway
  program, not from its author.
- **`EXEC_TOOL`'s and `BASH_TOOL`'s descriptions, and `CAPABILITY_NOTE`, say
  all of this plainly**
  (docs/DESIGN.md §10 — never overstate a jail *or* a freedom), and they tell
  the model what the freedom obliges: read before overwriting, prefer an edit
  to a replacement, never delete what it did not create.

**Where it runs** — on `top`, like every other executor: local on `top`, over
the tunnel's ssh master from `book` (`ssh top python3 sandbox-exec.py
<scratch>`). Pure stdlib so top's system python3 runs it with nothing
installed. **Because it runs on top, top's checkout needs `sandbox-exec.py`**
— a `book` edit is inert until top pulls (same caveat the `put` op carries).

## The Oxygen pass — what the Plasma face actually draws

Audited 2026-08-23 [his: *"quadruple check that the entire program is fully
oxygen no breeze or anything else"*], by rendering the window offscreen in that
session and reading the item tree (`ORACLE_TREE=1` with
`QT_QPA_PLATFORMTHEME=kde DESK_SESSION=plasma`) rather than by grepping —
the rule the panel's own audits landed on.

- **The style and the icons are Oxygen's**: the run prints
  `style=oxygen … icons=oxygen`, and every widget-shaped thing in the tree is
  the style's own — `Button`, `Frame`, `ScrollView`, `TextArea`,
  `KQuickStyleItem`, plus the menubar/toolbar/status bar on the widget side.
- **The scrollbar is the style's too**, through `qmlcommon/+plasma/VScroll.qml`
  — the selector is on for every kdeshell app, so the hand-drawn pixel bar is
  not what loads here.
- **The type called `PixelText` does NOT draw a pixel font in that session.**
  `DeskStyle` already resolves the family and size from `kdeglobals` under
  Plasma (measured: `Oxygen-Sans` at 12px, a 16px line box, `smooth=true`, and
  the same font in `editorFont`), so every label, every message and the compose
  box are already in the session's own face. The name is a misnomer there, and
  a reader auditing by type name will draw the wrong conclusion — this
  paragraph is the correction.
- **What is still ours, on purpose**: the `Meter` (a data readout, not a
  widget — the style's `ProgressBar` paints nothing inside a `QQuickWidget`,
  measured), and the surfaces that frame CONTENT — `VideoCard`, `ImageGallery`,
  `Lightbox`. Those are picture furniture, not chrome.
- **Fixed in this pass**: `qml/+plasma/VideoTransport.qml`. The video strip
  drew its own scrub track and a fullscreen mark made of four 1px corner
  brackets; in that session it is now a `Slider`, two `Label`s and a `Button`
  carrying the session's own `view-fullscreen` / `view-restore` icon — the rule
  player's transport bar was rebuilt under (§7.6).

## Media, not just the player — `control_media`

**Any MPRIS player, and the SYSTEM volume** [his, 2026-08-23: *"it seems
control_player should be made into a broader control_media … right now it
thinks the volume level is always 100 since player doesnt expose any volume …
i want it to be able to control all types of media playback"*].

- **`MPRIS_NAME` is a fallback LIST now** (`player,%any`), not one bus name, so
  the tool reaches a browser tab or mpv when his own player is not running. A
  call may name one (`player: "vivaldi"`), and `action: "list"` names what is
  on the bus.
- **`volume` and `mute` go to the PipeWire mixer** (`wpctl`, `AUDIO_SINK`),
  because his player exposes no MPRIS volume — it answers 1.0 for ever, which
  is why the model kept reporting 100. Every status now carries
  `system_volume` and `muted` from the mixer, plus `player_volume` reported as
  what it is: that one app's own number, meaningless for his. `scope: "player"`
  asks the app instead.
- **`control_player` still answers** — every earlier session and agent
  definition calls it that.
- **A harness never moves his volume**: `_mixer_set` refuses under `--selftest`
  unless `$ORACLE_WPCTL` points at a stub, the same shape as
  `Backend._systemctl`. Harness `tools/player-meta-test.py`.

## Gemma 4, and per-family sampler defaults

Chatter sent **no sampling options at all** until 2026-08-23 — fine for a model
whose published Modelfile carries good ones, wrong for a raw GGUF imported from
HuggingFace. `SAMPLER_DEFAULTS` is a small table matched against the model name
(longest key first); an unmatched model is still left alone, because silence is
the right default when the author already tuned it. Gemma's are Google's own:
temperature 1.0, top_k 64, top_p 0.95, min_p 0.0.

**The two Gemma 4 12B entries live in ollama, not in a llama.cpp service**:
`gemma4-qat:12b` (unsloth `UD-Q4_K_XL`, the QAT build, 6.9 GB) and
`gemma4-q5:12b` (`Q5_K_M`, PTQ, 8.6 GB) — same size class, one QAT and one not,
which is the comparison he wanted. Both were imported with the shared
`mmproj-F16` projector, so `/api/show` reports **vision, audio, tools,
thinking** and 262144 trained context. `ollama pull hf.co/…` is rate-limited by
IP without an HF token (429 on the manifest API, measured); plain file
downloads are not, so `~/models/gguf-import/import-gemma4.sh` curls the GGUF
and the projector and does an `ollama create` off a two-`FROM` Modelfile.

**The blob store had to be repaired first**: `~/.ollama/models/blobs` held 28
blobs still owned by `lam` from before ollama became a system unit, and the
daemon cannot `chtimes` a file it does not own — every import died on
`operation not permitted`. They are `ollama:ollama` now.

## Background jobs (run_job, and the tray)

**The work he actually wants an agent doing on his music library does not fit
in a tool call** [his, 2026-08-23: *"the goal here is to allow oracle agents to
help me build maintain clean etc my music library"*]. `sandbox-exec.py` caps a
run at **30 seconds** (`TIMEOUT_MAX`), which is right for a program written to
answer a question and useless for fingerprinting 19,000 tracks, fetching an
album or a replaygain pass. So a long command becomes a **job**.

**A job is a DIRECTORY, not a process handle** (`tools/job-run.py`):
`<ORACLE_JOBS>/<id>/` holding `spec.json` (what was asked for), `status.json`
(state, pid, exit, times) and `log` (stdout and stderr, interleaved, live).
That shape is what makes a job outlive the turn, the window and a relaunch —
chatter re-reads the directory and picks the running ones back up — and what
lets `book` drive jobs on `top` over the same ssh every other executor here
uses, with no daemon and no port. The runner is detached in its own session,
so `stop` can take the whole process group down rather than a shell.

- **Verbs**: `job-run.py start|list|stop|clear|run <root>`. `list` is the only
  one the window calls on a timer (2s while anything runs, 6s otherwise), and
  it returns each job's tail as well as its state, so one poll draws everything.
- **A job whose runner died is not "running" for ever** — `list` checks the pid,
  never the file alone (a reboot or an OOM leaves a stale status behind).
- **Two limits protect the machine, not the job**: `MAX_SECONDS_DEFAULT` (12h)
  and a 20 MB log cap, both killing the process group with a line in the log
  saying which one it was. `/` on top runs above 80% full; a runaway `find /`
  must not be able to fill it.
- **The model gets four tools**: `run_job` (on every turn — a model does not
  background what it was never told it could), and `job_status` / `job_log` /
  `job_stop` in the index, which attach themselves the moment one is called.
  All four go through the same `Jobs` object the tray draws from, so what the
  model is told and what he sees are one read of one directory (§10).
- **`Jobs.notify`** raises a desktop notification when a job ends while chatter
  is not the active window — a job runs for an hour, and the row going still is
  only visible to someone watching it. `--` before the positionals: notify-send
  parses a summary starting with `-` as an option.

**The tray** (`qml/JobsTray.qml` + `qml/JobRow.qml`, both with `+plasma`
twins) sits ABOVE the conversation, under the stat line [his, 2026-08-23:
*"should go at the top of the chat window rather than the bottom"*] — the
machine's own state belongs with the window's other standing facts, and a strip
that grows downward from there does not push what he is reading. It is small on
purpose: two rows before it scrolls, and **no heading** (the rows say what is
running better than a count of them does). It collapses to nothing when there
are no jobs (§5.2). A row is: a state dot that pulses only
while the job runs, the label, the state in words with the exit code on a
failure, a **reserved** clock slot so nothing shifts when a job ends (§5.4),
and two verbs — `log`/`hide` plus `stop` while running, `clear` once finished
(the verb that does not apply is not drawn, §10.2). The log is folded away
until asked for (§9.1) and opens at the bottom, where a running job is writing.
Under Plasma the same row is the KStyle's `Frame`, real `Button`s and the
style's `ScrollView`+`TextArea` well (§7.6), and the running count leads the
status bar's right-hand fact.

**A harness never touches his daemon**: `Backend._systemctl` refuses under
`--selftest`. The offscreen selftest pokes every chrome id it can find, and
Tools ▸ Stop Server is one of them — measured 2026-08-23, a test run stopped
the ollama he was using. The refusal lives in the app so a new harness cannot
reintroduce it.

**The library work this exists for** has two more pieces, both files rather
than code, both under chatter's own runtime dirs (machine-local, so seed book's
copy): the **`music-library` skill** — where the library is, what
`apps/player/tools/` already does (reorg, curate, the fingerprint audit,
soulseek, replaygain, dbsync) and the rules that keep a pass from destroying
his ratings or his audio — and the **`librarian` subagent**, which reads that
skill first and runs the long passes as jobs in its own context. Neither is
code: he or the model can edit them with the file tools, and the next spawn
uses the new version.

Harness: `tools/jobs-test.py` — the runner, the four tools, and the tray in
both faces, against a throwaway jobs root and a stub daemon.

## Talking to ollama

`OLLAMA` defaults to `http://127.0.0.1:11434` (override with `$OLLAMA_HOST`).
Loopback-pinned like every other local backend on this desktop — oracle opens no
listener. The daemon is the `ollama` service; if it is down, the model list is
empty and the reply area draws the error rather than nothing (docs/DESIGN.md
§10).

**On book, ollama is top's.** `sys/ai/ollama.nix` pins it to `127.0.0.1` on
top same as painter's ComfyUI, so `home/prog/oracle.nix`'s `air` branch execs
`apps/oracle/tools/ollama-tunnel.sh -- python3 main.py` as oracle's launcher —
modelled directly on painter's `comfy-tunnel.sh` (probe `top`/`top.local`,
forward the port over ssh, reuse an already-open forward). No sshfs mounts:
oracle has no model files or output gallery of its own to peer. `ollama` is a
SYSTEM unit (unlike `--user` `comfy-painter`) and already `enable = true` at
boot, so the tunnel script only reports its state, never starts it. The
`Backend.startServer()`/`stopServer()` buttons in `main.py` are host-branched:
on top they run a *local* `sudo -A systemctl {start,stop} ollama.service`; on
book, which has no local unit, they run the same command over ssh to top —
`ssh top sudo -n systemctl …`, reusing the tunnel's ssh master (the tunnel
exports `OLLAMA_SSH_HOST`/`OLLAMA_SSH`/`OLLAMA_SSH_CTL` for it). That needs
passwordless sudo for exactly those two commands on top, granted by the
`security.sudo.extraRules` block in `sys/ai/ollama.nix` (top-only, deployed on
top's next rebuild) — top askpass cannot prompt over a tty-less ssh. Both start
and stop work from book once top has rebuilt. `ORACLE_NO_TUNNEL=1` skips the
tunnel for UI-only work with no top.

## Web search (Tavily)

The model can reach the public web mid-turn on **every** turn (always on, no
toggle — his call, same as the file tools). It is backed by
**[Tavily](https://tavily.com)** — sign up there for
the **free tier** (a monthly quota, no card) and you get an API key like
`tvly-…`. **oracle never hardcodes it**; `tavily_key()` reads, in order:

1. **`$TAVILY_API_KEY`** — the environment variable (the same shape `OLLAMA`
   reads its endpoint from). Export it in your shell, or set it in home-manager
   so oracle's wrapper inherits it.
2. **`~/.config/oracle/tavily.key`** — a one-line file, the key and nothing
   else. The no-rebuild path: drop the key in and relaunch.

With neither present the tool reports itself unavailable to the model (which
then answers without it) and the sources block shows `search failed: no Tavily
API key configured` — it never silently does nothing (docs/DESIGN.md §10) and
oracle opens no listener and reaches Tavily only when a search is actually run.
The request is `POST https://api.tavily.com/search` with `api_key` in the body,
`include_answer: true`, `max_results: 5`; the reply's `answer` and each hit's
`title`/`url`/`content` are fed back to the model and shown in the disclosure.

## Reading a page (fetch_url)

`web_search` returns Tavily's snippets — a paragraph at most — so a model
handed a link could not actually **read** it. `FETCH_URL_TOOL` (`fetch_url`,
offered every turn, dispatched `_fetch_url`/`_on_fetch_url`) closes that: one
http(s) URL in, the page's **text** out, paged.

- **In-process, no executor.** The same shared `QNetworkAccessManager`
  `fetch_image` uses (Qt6 follows redirects), so it runs wherever the window is
  and needs no host branch. It is surfaced through the **web-search
  disclosure** (`webSearchStarted`/`webSearchDone`/`webSearchError`), so a
  fetched page appears in the same folded sources block as a search.
- **HTML → readable text** by `_PageText`, a stdlib `HTMLParser` that drops
  `script`/`style`/`svg`/`iframe` *and* the page furniture (`nav`, `aside`,
  `form`, `select`, `button`, `menu` — Wikipedia's chrome alone is the first
  ~2k characters otherwise), turns block elements into line breaks, collapses
  whitespace and keeps the `<title>`. JSON and plain text pass through
  untouched.
- **Paged, capped, honest.** `FETCH_URL_CHARS` (20000) of text per call with
  `chars_total`/`next_offset` to continue, `FETCH_URL_MAX_BYTES` (4 MB) on the
  body. An image URL is refused by name (*use fetch_image*), other binary types
  by content-type, a non-http(s) URL before the network — each reaching both
  the model and the disclosure (docs/DESIGN.md §10).
- **It sends a browser User-Agent**, because a default Qt UA gets a bot wall on
  a fair number of sites and a tool that cannot read them is not the tool this
  is meant to be. It cannot post a form or log in.

## Web APIs (call_api)

`fetch_url` already GETs a JSON endpoint — a booru's `posts.json` came back as
raw text and worked. It was just bad at it: 20k characters of budget spent on
eight posts of metadata nobody asked for, no way to send a credential, and the
model guessing each site's endpoint shape. `CALL_API_TOOL` (`call_api`, offered
every turn) is the same GET with the three missing pieces, and nothing more.

- **Read-only by construction** (his call): `method` is a two-value enum, GET
  and HEAD. A tool-calling model holding his keys cannot favourite, upload or
  delete on a remote account, and that is a property of the schema, not of a
  check somewhere.
- **Field projection before the cap.** The response is parsed, the result list
  located (`select`, a dotted path; the registry knows the wrapped ones), and
  each row cut down to `fields` — dotted, so `file.url` reaches into e621's
  nested shape. `["*"]` keeps whole rows. Twenty usable rows instead of eight
  whole posts: measured, a 5-post danbooru search projects to 4.7k characters.
- **The cap DROPS WHOLE ROWS, never cuts a document in half.** `API_CHARS`
  (16000) against the serialized rows, popping from the end until it fits, with
  `count_total`/`next_offset` to page. A half-serialized row is unreadable to
  the model; a short list is not.
- **`API_SITES` is the registry** — danbooru, safebooru, e621, gelbooru,
  rule34, yandere, konachan: base, endpoint, default params, default fields,
  where the list lives, and a note. It is a convenience, **not the surface**:
  `url` reaches any http(s) JSON API, with `auth` naming a keyring entry. The
  tool description is BUILT from the table (`_api_sites_blurb`), so it cannot
  drift from what the code sends.
- **A named client User-Agent, not fetch_url's browser one** — the opposite
  rule holds here and it is measured (2026-08-22): danbooru's JSON API answers
  that Chrome string with **403** and `chatter/1.0 (oracle desktop client)`
  with 200. An API wants a named client; a page wants a browser.
- **The keyring, so a key never enters a transcript.**
  `~/.config/oracle/api-keys.json` (override `$ORACLE_API_KEYS`), read on every
  call so adding a key needs no restart: entry name →
  `{"params": {...}, "headers": {...}, "basic": [user, key]}`. Every credential
  parameter is stripped from the URL that reaches the model, the session file
  and the disclosure line (`_api_safe_url`, `API_SECRET_PARAMS`) — a session
  transcript is a file that syncs.
- **A site known to refuse anonymous requests is refused BEFORE the network**,
  naming the exact JSON to put in the keyring (docs/DESIGN.md §10 — never a
  silent failure, and never a guessed key). Measured 2026-08-22: gelbooru 401s,
  e621 403s, rule34 answers 200 with a *"missing authentication"* body;
  danbooru, safebooru, yandere and konachan answer anonymously.
- **It runs wherever the window is** — the shared `QNetworkAccessManager`,
  exactly like `fetch_url`/`fetch_image`, so no executor and no host branch —
  and it is surfaced through the **web-search disclosure**
  (`webSearchStarted`/`webSearchDone`/`webSearchError`), so an API call folds
  into the same sources block as a search. No QML change was needed for it.
- **It pairs with `fetch_image`**: a booru row's `file_url` is a direct image
  URL, so "find me X and show it" is `call_api` then `fetch_image`, and the
  tool descriptions say so.
- **Harness `tools/api-tool-test.py`** — offline and deterministic (it builds
  requests against a fake NAM and projects canned responses, and points the
  keyring at a throwaway file), with `--live` for read-only GETs against the
  four boorus that answer anonymously. Re-run it after touching the registry,
  the projection or the keyring.

## A reply that stopped short — `continue`

**Any finished answer offers `continue`, and it lives on the SEND BUTTON**
[his, 2026-08-23] — not under the bubble, which is where it started as the way
on from an answer cut off mid-sentence [his, 2026-08-22]. Three things end a
reply: the model hits its generation ceiling (ollama's final frame says
`done_reason: "length"`, which `Ollama` surfaces as `replyTruncated`), he
presses stop — either marks the row `cutOff` — or it simply finishes. All three
are continuable.

**A fourth way, which nothing announces: the TURN ran out of window.** ollama
shifts the context rather than failing, so a turn that spent its 32k on tool
rounds gets a normal `done_reason: "stop"` on an answer that breaks off
mid-sentence — observed 2026-08-23, a music-library turn whose table stops
mid-row with no `continue` on it, because nothing in the app knew. So
`_truncation_reason` reports `"context"` when the turn was **squeezed**
(a round filled `CTX_FULL_FRACTION` of `CHAT_NUM_CTX`, or the tool loop was
forced into its wrap-up round) **and** `_ends_abruptly` says the text stops
mid-sentence. **Both halves are required**: measured across his saved sessions,
one finished reply in nine ends on a bare word (a bullet list, a heading, a
trailing link), so shape alone would put a `continue` on answers that are
complete. Harness `tools/cutoff-detect-test.py`.

So the one button beside the prompt box has three states, in this precedence
(docs/DESIGN.md §10.2 — one control, one place, and it says what it will do):

| state | when |
|---|---|
| `stop` | a reply is streaming (`busy`) |
| `send` | there is something typed or attached (`canSend`) — a prompt he wrote outranks carrying the last answer on |
| `continue` | neither, and `canContinue` |

**The box hugs ONE line, and the slack is split.** Its height is the send
button's, floored — the button is taller than a line of text — and the input is
CENTRED on that rather than anchored to the top, because slack anchored to the
top all falls out of the bottom: 34px around a 30px input put six pixels under
the text and none above it [his, 2026-08-23: *"extra empty space under the text
line and the bottom edge"*]. Both faces do it the same way (`root.pad` in
`qml/PromptBox.qml`, `sendBtn.implicitHeight` in `qml/+plasma/PromptBox.qml`),
and both are measurable offscreen — `ORACLE_TREE=1` prints every item's y and h,
which is how the asymmetry was found rather than guessed at.

`PromptBox` takes `canContinue` and emits `continued()`; both faces implement it
(`qml/PromptBox.qml` and `qml/+plasma/PromptBox.qml`, where the states are
`Stop`/`Send`/`Continue` on a real KStyle Button). The menubar/toolbar `send`
action carries the same three verbs, since it is the same verb with a name on
it. `win.canContinue` is true when a model is picked, nothing is streaming, and
the LAST row is a finished non-error assistant turn — only the last, since
continuing one further up would write into the middle of the conversation.

**`chatRev` is why that binding is live.** A `ListModel` notifies on `count`,
never on a per-row `setProperty`, and `Ollama.busy` flips to false BEFORE the
QML handler clears the row's `streaming` flag — so a binding on `busy` alone
re-evaluates one step too early and the button never offers `continue`. Every
place that settles a row (`onReplyDone`, `onReplyError`, `stopReply`,
`continueReply`) bumps `chatRev`, which the binding reads first.

`Ollama.continueReply(model, history, partial, mode)` re-posts the chat with
every earlier turn, then the partial as an `assistant` message, then one
instruction as a user turn — a user turn rather than a bare assistant prefix
because no model is reliable about not starting over when asked that way. `mode`
picks the instruction, and QML picks `mode` off `cutOff`:

- `resume` → `CONTINUE_PROMPT`: carry on from the very next character.
- `extend` → `EXTEND_PROMPT`: the sentence ENDED, so ask for what comes next
  rather than a mid-word resume. QML appends a blank line to the row first, so
  the extension is its own paragraph.
- an empty `partial`, either mode → `ANSWER_PROMPT`, with no assistant message
  at all: the turn spent itself on tools and never wrote, so there is nothing to
  carry on from.

QML points `win.activeIndex` at the existing row first, so the continuation
streams onto the END of it: a continued answer stays ONE answer, not two bubbles
that have to be read together. Harnesses: `tools/continue-test.py` (the cut-off
half) and `tools/continue-any-test.py` (extend, the empty turn, and the wrap-up
round below) — both offscreen against a stub ollama on 127.0.0.1, so his daemon
is never touched and no model is ever loaded — plus
`tools/continue-button-test.py`, which drives the real window offscreen in BOTH
faces (`--selftest` with `ORACLE_FAKE`, whose demo log ends on a finished turn)
and reads the button's label back: `continue` with nothing typed, `send` the
moment there is.

### How long a turn may work — rounds, context, and the wrap-up

**The tool loop is a work budget, and he should never have to press `continue`
to get one task finished** [his, 2026-08-23]. It used to stop after
`MAX_TOOL_ROUNDS = 4`, which a real job (find a directory, read three files,
edit one, check the edit) exhausts halfway through, so a task took several
presses. Two changes:

- **`MAX_TOOL_ROUNDS` is 24** and is now only a runaway guard — the backstop for
  a model looping on the same call forever. He can always press stop.
- **What really ends a long turn is `_ctx_room()`**: four-chars-to-the-token
  over the whole message list, against `TOOL_CTX_FRACTION` (0.75) of
  `CHAT_NUM_CTX`. Past that the next tool result would be truncated by the
  server anyway (no context-shift on this model), so the turn is better spent
  answering. Measured, not guessed.
- **`PERSISTENCE_NOTE` is on every system prompt**: finish the job in THIS turn,
  look → act → check, do not stop to announce a plan or ask permission for
  something he already asked for. Without it a model treats one tool round as
  one turn and hands back a description of what it would do next.

### Working memory — what the last turn did comes with it

**A turn starts with the tool rounds of the turn before it, not blind.** Until
2026-08-22 it did not, and that single fact is what made long jobs impossible:
`send()` rebuilt the message list from the chat log every turn, and
`_parse_history` keeps `user`/`assistant` TEXT and nothing else — so every tool
call and every tool RESULT died with the turn that made it. Reading the session
where he asked an agent to change something in `~/nix` is the whole argument: it
re-read the same files turn after turn, re-derived the same conclusion five
separate times, and never reached the edit. It was not short of tools. It had no
memory of using them.

- **`_prior`** holds the last finished turn's whole message list (tool rounds
  included), snapshotted by **`_remember_turn()`** at the two points a turn ends.
- **`_carry(hist)`** hands it back when this turn continues the same
  conversation, and `None` otherwise — matched on `_prior_users`, the RAW
  prompts, against the user turns QML sent. Prompts, deliberately, not assistant
  text: the chat log splits one answer into a row per round (above) while the
  message list holds one, so matching on assistant text would fail on exactly
  the turns worth carrying. A switched session, a reopened one, an edited log or
  a fresh app all fail the match and fall back to the old text-only history,
  which is why nothing here can leak one chat into another.
- **`TOOL_CARRY_CHARS` (12k) is charged NEWEST FIRST**, and what does not fit is
  STUBBED, not dropped (`_trim_carry`): the assistant message that *called* the
  tool always survives, so the model can see it already ran `read_file` on that
  path even when the output is gone. ~3k tokens against a 32k window.
- **`continueReply` carries it too**, and needs it most — `continue` is pressed
  exactly when a turn ran out of room mid-job. Two things it does that `send`
  does not: the instruction it writes and the partial answer QML hands it are
  marked `_synthetic` and kept OUT of the memory (they were never his words, and
  the partial comes back as part of the finished answer via `_partial_prefix`),
  and if the memory already ends with that same partial, the memory's copy is
  dropped so the model does not read its own last words twice.
- **It is in RAM, per running app.** Restart chatter, or switch away and back,
  and the conversation is still whole (the store has every turn) but the tool
  memory of it is gone. That is the honest limit of this version.

Harness: `tools/memory-carry-test.py` — two prompts through the real window
against a stub daemon, asserting on the REQUEST BODIES that turn 2 still carries
turn 1's tool call, its result and the file's actual text.

### The tree tells the agent its own rules

**The first file tool to touch a tree that has an `AGENTS.md` gets that path
handed back with the result** (`_house_note`, `HOUSE_FILES`), so he does not
have to point the agent at the conventions of the place it is standing in [his,
2026-08-22: *"i just want it to be easy for me to change things about chatter
and the rest of the system without needing to point it to every little thing"*].
It walks up from the path to `$HOME` and stops there — `/` and `/nix/store` have
no house rules — takes the NEAREST guide, and names it once per conversation.

**Named, never inlined.** `~/nix/AGENTS.md` alone is 62 KB, a fifth of the
32k-token window, and there are three more in the trees chatter touches most.
The pointer costs a line; reading it is the model's own call, with its own
`read_file`, only when it is actually working there.

### One bubble PER ROUND

A turn that took six tool rounds used to be ONE row: six rounds of prose, every
tool name and the final answer stacked together, with nothing to say where a
round began [his, 2026-08-23]. Now each round is its own row.

`Ollama.roundStarted(n)` fires in `_tool_done`, after a round's results are back
and before the next POST. QML settles the row that round wrote into — its prose,
and the tools, sources, files and images IT called, stay on it — and
`appendReplyRow(n)` opens a fresh one. `step` is the round a row belongs to: 1
for the row his prompt opens, 2 and up for each round after it, persisted with
the turn — and NOT drawn anywhere. The caption used to read `model · round 2`
from 2 on; he had it taken out [his, 2026-08-22]: the split is the point, and a
new bubble already says a new round began. `step` stays in the store and in
`rowsJson` (the harness asserts on it), it just has no label.

Everything keyed on "the last row" still means the ANSWER row, since that is the
last one: `continue`, the auto-press, `canContinue`.

**One deliberate exception: a media-only round does NOT open a fresh bubble.**
When the row a round leaves behind holds a picture (or a video) and no words,
`onRoundStarted` keeps the same row streaming and lets the next round's text
land on it — so the image and the answer it accompanies read as one message
instead of a detached picture floating above a separate text bubble [his,
2026-08-23]. Once a row HAS words, the rounds split again exactly as above. The
merge decision is made off the row's `images`/`videos` roles, never a child
item's `visible` (the latch in the bubble's `visible`).

**And a SHORT line on a round that called a tool counts as no words at all.** He watched
a turn draw "Here's your Lain image:" with the picture under it and then a
second bubble saying "Here you go — here's Lain:" with nothing in it
[2026-08-24]. The row that called the tool wrote before it had seen the result —
which `PERSISTENCE_NOTE` already forbids and models do anyway — and the round
after it says the same thing again. And it is not only the picture rows: one
request put NINE bubbles between it and the result — "Seed locked: …", "Found
shirow_masamune. Let me find one more." — each its own slab, none of them the
answer. So ANY row whose body is at most `preambleMax` (140) characters AND that
called a tool has its body cleared; if it also carries media it merges like a
wordless one, and otherwise it is drawn as its tool block, which is where that
work belongs. Longer prose is left alone and still splits — that is content, and losing it would be worse
than repeating it. Only the DISPLAY is trimmed; the model's own context still
holds what it wrote.

Harness: `tools/round-split-test.py` — it drives one real prompt through the
real window offscreen against a stub ollama that asks for two tool rounds, and
asserts the log comes out as three reply rows with the prose and the tool on the
round that made them; a second scenario (MODE=media, a `show_image` round then
an answer) asserts the picture and the following text land on ONE row, and a
third (MODE=preamble) replays exactly what he saw and asserts the announcement
is dropped. It rides
on `ORACLE_SEND` (send this prompt, then print the chat log as JSON via
`Root.rowsJson()`), which is the only way to see what the ROWS became.

### A bubble hugs its text, with no floor

A message's bubble is as wide as its longest laid-out line and no wider (capped
at `bubbleMax`). Two things used to stop that being true for a SHORT one, and
both are gone [his, 2026-08-23]:

- a **72px floor**, which drew a padded slab around a one-character `k`;
- the **speaker caption in the measurement** — `whoText.contentWidth` was in
  `turnCol.natural`, so every short reply was held open to the width of the
  model's name, and the caption is not even inside the bubble.

`natural` is now `max(plainBody, mdBody)`. A row carrying media still takes the
full cap (`turn.wide`). Harness: `tools/exec-peek-test.py` — a one-character
prompt beside a long-named model's two-letter answer, measured on the rendered
`Bubble`.

### The time under each bubble

Every message carries the time it landed, under its bubble and on its own side
— dim, faded, the weight of the speaker caption above it (§9.1) [his,
2026-08-23]. `win.timeLabel(ts)` is 12h — `2:07 pm`, lowercase [his,
2026-08-23]; the DATE stays a once-a-day separator across the
column (`opensNewDay`), so a session held in one sitting draws one date and a
time per message. A row from before the store kept `ts` shows no time rather
than a made-up one. Harness: `tools/exec-peek-test.py`.

### One meta block per turn, at the top of it

One row per round fixed the "where did round 3 begin" problem and made a new
one: between two things the model SAID sat three or four lines of bookkeeping —
that round's reasoning heading, its tools, its sources, its files [his,
2026-08-23]. So the bubbles of a turn now run **one after another with nothing
between them but their timestamps**, and every disclosure of every round is
aggregated into ONE block above the first bubble, where the counts, the clock
and the live state already were. (It replaces the old per-run fold, which
existed to get the silent rounds out of the way.)

- **The head of a turn is the first model row after his prompt** —
  `win.turnHead(i)`, read off the log, nothing stored. That row draws the block
  for the whole run; no other row draws any meta at all, or repeats the
  speaker's name.
- **`win.turnAgg(head)` is the block's whole input**: reasoning text and
  tokens, tool names and count, agents, sources, files and the exec tail,
  summed and concatenated over the run, plus the live flags. One object, so a
  disclosure reads `turn.agg.files` instead of a row role.
- **What re-evaluates it.** A ListModel notifies no binding when `setProperty`
  writes a role, and rebuilding the aggregate per token would redo the whole
  turn for every visible row on every delta. So the block carries a 300ms
  `Timer` that bumps `win.metaRev` while `Ollama.busy`, and `chatRev` (bumped
  wherever a row settles) carries the final state.
- **A round that said NOTHING is drawn nowhere** — its bookkeeping is in the
  block, so the row has nothing left of its own. `win.roundIsSilent(r)` is the
  test, read off the row's own roles (never a child item's `visible` — the
  latch that hid a picture for good). `visible: false`, not height 0: an Item
  of height 0 still takes the column's 12px spacing.
- **Output is never hidden**: a round that produced prose, a picture or a video
  keeps its bubble, under the same one block.
- Harness: `tools/round-split-test.py`, on `Root.turnJson()` (what the block
  made of each row, never drawn).

### A picture the write-up names is drawn where it names it

A turn that gathers pictures over several rounds and then writes them up used to
end with a list naming eleven of them and a bubble holding NONE [his,
2026-08-22]. Two rules met badly: a picture is attached to the ROUND bubble that
fetched it, and `_attach_typed_images` skips a `![](url)` whose URL this turn
already fetched (`_images_shown`) — so the write-up's own markdown was demoted
to plain links and nothing was drawn under it, while the pictures sat further up
the transcript.

Now a named picture that is already on disk is DRAWN AGAIN on the bubble that
names it: `_image_entries` keeps the entry each URL produced this turn, and
`_emit_image` is the one door every picture goes through so that ledger and
`_row_urls` (what is already on the bubble being written) both stay true. It is
a redraw, not a second download, and `_row_urls` stops one bubble showing the
same picture twice. Harness: `tools/typed-image-test.py`, case 5.

### Code blocks stay inside the bubble

Qt's markdown reader marks every fenced block `NonBreakableLines`, so a long
line does not wrap: it lays out past the item's width and paints across whatever
is beside it — code spilling out of the bubble [his, 2026-08-22]. That flag is
on the QTextDocument's block formats, which QML cannot reach, so `MdFormat`
(`Md.styleCode`, main.py) walks the document `MarkdownText.qml` is already
drawing, clears the flag, gives each block a margin, and returns the CHARACTER
RANGES of each run of code lines. The item draws the embedded panel behind those
ranges itself (`positionToRectangle`, `z: -1`).

- **The tint cannot be done in the document.** Qt Quick's text nodes paint a
  CHARACTER format's background and ignore a BLOCK format's (measured: a block
  background drew nothing at all), and a char background stops at the end of
  each line — a ragged strip, not an embedded block.
- **A block is recognised by Qt's flag, then by our own mark**
  (`MdFormat.CODE_MARK`), because clearing the flag is the point and nothing
  else on a block format remembers. NOT by the monospace family: a paragraph
  that merely BEGINS with an inline `code` span reports monospace as its block
  char format, and drew a whole prose line as a code panel.
- **The text is never rewritten** — no re-wrapping of the source, no inserted
  newlines — so `Clip.copyMarkdown` still hands over exactly what the model
  wrote.
- Debounced (60 ms) because a streaming reply rebuilds the document on every
  delta and each rebuild brings the flag back. Harness:
  `tools/code-block-test.py`.

### Lines break where the model broke them, paragraphs stand apart

Two things about a reply's shape, both his [2026-08-23], both measured on the
laid-out document rather than on the source:

- **A single newline is a LINE BREAK.** CommonMark joins it into the paragraph
  above, so a reply written as short lines came back as one run-on block. Qt's
  reader has no "soft breaks are hard breaks" switch, and markdown's own hard
  break (two trailing spaces) opens a whole new BLOCK — which would give a soft
  break the same standoff as a real paragraph and make the two
  indistinguishable. So `Root.hardBreaks` swaps that newline for **U+2028**, the
  separator Qt's layout breaks on INSIDE a block: same block, next line, no gap.
  It is applied to `text` only — `source` stays the model's markdown verbatim,
  so `Clip.copyMarkdown` still hands over what it wrote. One character for one,
  so document positions still map to the source. Lines that open a block of
  their own (a list marker, a heading, a quote, a fence, a table row) are left
  alone, and nothing inside a fence is touched.
- **A blank line opens a paragraph, and the paragraph says so.** Qt gives every
  block a 6px top AND bottom margin, which collapse to a 6px gap — no stronger
  than a wrapped line. `MdFormat` sets the gap on the TOP margin only (adjacent
  margins collapse to the larger, so one side is enough): `PARA_TOP` 12,
  `HEAD_TOP` 16, `LIST_TOP` 2 (bullets are one list, not a stack of
  paragraphs), and 0 on the first block or every bubble opens with a blank
  strip. Code is skipped — `styleCode` sees one block PER LINE inside a fence,
  so a margin there would space the code out line by line.

It runs in the same debounced document pass as the code blocks, and only writes
a block format when the value differs, or the write would retrigger the pass.
Harness: `tools/prose-layout-test.py`.

### Sending scrolls him to the bottom

Reading back up the log clears the view's `followBottom`, and his own new prompt
then lands off-screen below him [his, 2026-08-23]. `send()` calls
`replyFlick.toBottom()` — cancel any flick, re-arm `followBottom`, jump to the
end — which is the one place jumping the view is not yanking it, since he just
wrote the thing at the end of it. Everywhere else the rule stands: the log
follows the newest text only while he is already at the bottom
(docs/DESIGN.md §6.1). Harness: `tools/prose-layout-test.py`.

### One state at a time in an unfinished bubble

A model row that has said nothing yet draws a `loading…` line of its own; the
reasoning clock beside it draws `waiting…` while a tool is out. An empty bubble
on its FIRST tool round satisfied both and stacked them [his, 2026-08-22]. The
clock block is now hidden while that loading line is up, so `loading` owns a
bubble with nothing in it and the clock takes over the moment there is something
to show. `tools/think-clock-test.py` samples the two together — a union of
everything seen over time cannot tell coexistence from a handover.

### It presses `continue` for him

Even with `PERSISTENCE_NOTE` on every prompt, gemma4 ends a turn by ANNOUNCING
its next step — "I'd like to proceed with…", "I'll now grep for…" — and he was
pressing `continue` over and over to get one task done [his, 2026-08-23]. So the
app presses it:

- `Ollama.looksUnfinished(text)` reads the last 400 characters of a finished
  answer against `UNFINISHED_PATTERNS` — announcements of the model's own next
  action. An answer that just ENDS matches nothing.
- **A tail that ends in `?` is never carried on**, whatever else it says. It is
  his turn, and the press answers with `proceed` — so an unanswered question
  gets answered for him. That is exactly what happened on 2026-08-23: a `hello`
  drew "would you like me to play one of these tracks?", the app said yes twice,
  and the turn ended with a track queued he never asked for. `shall i`,
  `would you like me to` and `should i proceed` were patterns in that list and
  are gone; a permission-ask now costs him one press, which is cheaper than an
  action he did not ask for.
- QML's `autoContinue()` runs off `onReplyDone`: at most
  `AUTO_CONTINUE_MAX` (3) presses per prompt, `continueReply("proceed")` each
  time, streaming into the same row. `PROCEED_PROMPT` tells the model to act
  rather than ask again.
- **It says so**: the status line reads `carrying on by itself (n/3)`, and when
  the budget runs out with the answer still announcing, `it stopped short again
  — press continue` (docs/DESIGN.md §10 — nothing on his behalf in silence).
- **Stop is stop**: `stopReply` spends the whole budget, so a turn he
  interrupted is never carried on for him. His next prompt re-arms it.

### The wrap-up round — why replies came back EMPTY

**Either limit above ends the loop, and ending it used to end the turn.** Until
2026-08-23 the loop just stopped and "took the answer as-is" — but a model
still calling tools when it stops has written NO prose in that frame, so what he got was an
**empty message**: observed twice in a row on 2026-08-22, gemma4 spending four
`run_bash` rounds hunting for a directory and then saying nothing at all, with
no `cutOff` either (ollama's `done_reason` was `stop`, not `length`) so not even
a `continue` to press.

So the limit now takes one more round instead of dropping the turn: the last
round's tool calls still run, and the follow-up POST carries **no `tools` key at
all** plus `TOOL_CAP_PROMPT` as a user turn — leaving the model nothing to do
but answer with what it found. `_no_tools` is the one-shot flag (`_post_chat`
drops the tool list, `_tool_done` appends the prompt); it is cleared by `send`
and `continueReply`, so the next turn gets the full loop back. Harness:
`tools/continue-any-test.py`, which drives the whole loop to both limits.

## Web images (fetch_image)

The model can DOWNLOAD an image from the web and have it shown inline in the
chat — the one place a reply becomes a picture, not text. `IMAGE_TOOL`
(`fetch_image`, offered every turn beside the web/file/time tools) takes a
direct image URL and an optional `alt` caption; `Ollama._fetch_image` GETs it on
the shared `QNetworkAccessManager` (Qt6 follows redirects), and `_on_image`
validates the result.

**One data contract, `imageFetchResult` (a single JSON entry).** Success is
`{ok:true, url, path, alt, w, h}` — `path` is the local file, `w`/`h` the real
decoded pixel size; failure is `{ok:false, url, error}`. QML's `onImageFetchResult`
parses it and appends to the turn row's `images` array (a JSON-string field); the
Main.qml delegate renders each ok entry as a framed inline `Image` (1px border,
`Theme.rounding`, `sourceSize.width` capped to the column so it never upscales)
with the caption under it, and each failure as a crit line. `imageFetchStarted`/
`imagesActive` drive the in-flight line. The model also gets a text tool result
(`{ok, note}` or `{error}`) so it knows the outcome.

**NEVER ask a child whether the bubble should be visible.** The bubble shows
when the row has words OR media, and that condition is read off the model roles
(`turn.hasMedia`) — never off `imageCol.visible`, which is what it used to do.
QML's `visible` is EFFECTIVE visibility (false if any ancestor is hidden), so a
hidden bubble asking its own child produced a latch: a picture landing on a
round with no text — `view_image` says nothing, it just looks — found the bubble
hidden, read its child as hidden, and stayed hidden for good [his, 2026-08-23:
a graph the model had just plotted, and no graph]. Reloading the session drew it
perfectly, which is what made it look like a fluke: a row BORN with its picture
never hits the latch, only one the picture ARRIVES on. Harness:
`tools/media-row-test.py`, which drives the live order (empty row, then the
signal) for both a picture and a video.

**A picture the model writes into its prose is drawn AT that spot — in with the
text, not hoisted to the top of the bubble** [his, 2026-08-23: *"all images
must be at top of message ... allow them to be put in line i.e. in with the
text, AND support transparancy"*]. A reply used to carry every picture in a
strip above the words; now `Ollama.replyRuns` splits the markdown at each
`![alt](url)` and the bubble lays it out as a FLOW of runs — text runs render
as `MarkdownText`, an image run renders `qml/InlineImage.qml` at that spot.
An inline picture is capped to the column, never upscaled past native, its
frame's fill is TRANSPARENT so a PNG's alpha shows the bubble behind it rather
than a solid slab, and one click opens the Lightbox. A failed fetch names
itself with a crit line where the picture was meant to be (docs/DESIGN.md §10 —
surfaced, never vanished). A markdown image that was NOT fetched this turn is
still demoted to a plain link in its run — MarkdownText would fetch the URL on
render at its own pixel size — but a fetched one is drawn, alpha intact.

**Two or more pictures not tied to a word are a GALLERY, and one opens over the
window** [his, 2026-08-23]: they used to stack full-width, one on top of the
other, so seeing the third meant scrolling past the first two. The gallery is
now the NET for a fetched picture the reply never referenced inline (a
`view_image` has no url to tie to a word, so it always lands here). `qml/ImageGallery.qml`
draws one picture exactly as before and two or more as a tiled grid — balanced
rows, justified to the full width, gapless from the shared edge, square crops,
the caption inside the artwork on hover (docs/DESIGN.md §5.1). A tile opens
`qml/Lightbox.qml`, a scene-level overlay in `Root.qml` (z:300, above the drop
overlay): the picture fitted but never upscaled past native, Escape or a click
on the ground to close, arrows or a click on the picture to step, and focus
handed back to the reply area on close. Both are drawn once and serve both
faces, since `Root.qml` is the shared Item. Failures keep their crit line
whatever the count. Render them with `tools/gallery-shot.py [N]` — offscreen,
its own generated pictures, no daemon and no turn — which also checks the
overlay's keyboard.

**A model that TYPES the image gets it attached anyway, and drawn inline** [his,
2026-08-22: *"see how it failed to attached some images"*]. gemma4 reliably
answers "show me pictures of X" by writing `![alt](url)` into the reply instead
of calling `fetch_image`, however plainly the tool says otherwise — and
`MarkdownText` DEMOTES image markdown to a link on purpose (Qt would fetch it
on render, at its own pixel size), so the picture simply never appeared.
`_attach_typed_images` closes that at the other end: when a reply finishes with
no more tool rounds, its `![](http…)` URLs go through the same `_fetch_image`
(capped at `MD_IMAGE_MAX`, 4 per reply, deduped against everything already
fetched this turn), and `replyDone` waits for them. Because the split
(`Ollama.replyRuns`) keys each inline image to the row's fetched files by URL,
a typed image that lands mid-turn renders INLINE where the model wrote it.
`_fetch_image`'s `idx` is `None` for those — there is no tool call to answer,
only the picture.

**A mistyped booru md5 is refused before the request.** The same session's other
failure was the model RETYPING a URL from memory: `12a90ec8d770cc4898c17bece1ee561`
(31 chars) and `45bf9a3erm88cd10126904ca995c7` (not hex) both went out and both
404'd. Boorus address a file by its md5, so the shape is checkable —
`_booru_url_fault` fails those instantly with a message that says what to do
instead (copy `file_url` verbatim, or search again), which a bare 404 cannot; a
404 from anywhere else gets the same nudge appended to the tool result. Harness:
`tools/typed-image-test.py` (offscreen, its own 127.0.0.1 image server, no
network and no daemon).

**Looking at a LOCAL picture — `view_image`** [his, 2026-08-22: *"give agents
the ability to see the contents of my local files in the same way it sees images
uploaded to the chat"*]. `read_file` reaches every file on the machine and hands
back TEXT, so an image was a wall: the model could find `holiday.jpg` and not
see a pixel of it. `VIEW_IMAGE_TOOL` reads the bytes through the **same jailed
executor and the same wide READ root** as the read-only file tools
(`sandbox-fs.py` op `image` — magic-sniffed, png/jpeg/gif/webp, 8 MB cap, `host`
selects the machine exactly as `read_file` does), and then:

- the base64 goes into `_pending_vision`, which `_tool_done` attaches to a
  **user message carrying `images`** before the next post — the same field a
  dropped attachment uses, because ollama carries image bytes on a message and
  never in a tool result;
- **the bytes never enter the tool result** (a base64 blob in the transcript is
  unreadable and enormous) — the model gets `{ok, path, media, bytes, note}`;
- the picture is **drawn inline in the chat as well**, so he sees exactly what
  the model was shown (docs/DESIGN.md §10 — nothing looked at in secret);
- a model with **no vision** is refused with a reason, and no bytes are read.

Harness: `tools/continue-test.py` covers it against the real executor.

**Finding a real URL first — `search_images`.** `fetch_image` only GETs a URL
the model already holds, and a model asked for "a picture of X" tends to GUESS
a plausible image URL that 404s (the fetch then fails honestly, but no picture
shows). `SEARCH_IMAGE_TOOL` (`search_images`, offered every turn) closes that:
it queries Tavily with `include_images` and returns real direct image URLs
(with descriptions) through the web-search disclosure signals, and both tool
descriptions tell the model to search first and never invent a URL. So a "show
me X" resolves to a URL that actually loads. No Tavily key → the same honest
"unavailable" the web search reports (docs/DESIGN.md §10).

**It does NOT run on top** (unlike the sandbox/session/memory stores): a QML
`Image` loads a LOCAL file, and the fetch is an in-process web GET, so it runs
wherever the window is and saves under `IMAGES_ROOT`
(`~/.local/share/oracle/images`, override `$ORACLE_IMAGES`), content-addressed by
URL so a re-fetch reuses the file. `IMAGE_MAX_BYTES` (20 MB) caps one download.

**Failure is surfaced, never swallowed** (docs/DESIGN.md §10): a non-http(s) URL
is refused before the network, a body that does not decode as an image (a web
page, a 404 HTML) reports the content-type, an over-large body is rejected, and a
saved file that will not load draws its own crit line. All three reach both the
user (a visible line) and the model (a tool error). The saved `path` persists in
the session transcript, so a reloaded conversation still shows its images.

## Video (show_video)

**A video the reply NAMES is drawn even when the tool was never called.**
Observed 2026-08-23 in his own session: the model wrote
`{{show_video|https://…}}` into its prose as literal text and the window drew
nothing — *"it seems something happaned to where the video was not shown inline
like how it should"*. `_attach_typed_videos` is the same fix
`_attach_typed_images` already was at the other end: every brace-marker shape a
model invents (`{{show_video|…}}`, `{{video(…)}}`, `{{play_video=…}}`) plus a
plain YouTube/Vimeo URL it merely mentioned, capped at `MD_VIDEO_MAX`. A marker
is replaced in the prose by the bare URL through `replyBodyFixed` (the card
carries the video; if the card fails he can still see what it was), while a
mentioned URL is left exactly as written. The tool path registers its own URLs
in `_videos_shown`, so nothing is drawn twice, and the turn does not end until
the cards resolve — the saved session has them in it. Harness
`tools/typed-video-test.py`. It matters more since the tool index landed:
`show_video` is not on the wire every turn any more, so typing it is the MORE
likely failure.

**A reply can play a video where it says it** [his, 2026-08-23: *"are inline
youtube video displays possible in oracle? like the youtube video displays in
the bubble? or any video pulled from the internet?"*]. `VIDEO_TOOL`
(`show_video`, offered every turn) takes a URL and an optional caption, and
unlike `fetch_image` it accepts a **web PAGE**: a YouTube or Vimeo watch link
resolves, and so does a direct `.mp4`/`.webm`/`.mkv`.

**Nothing is downloaded.** What the tool produces is a STREAM url the QML
`MediaPlayer` pulls off the network itself, so a 200 MB video costs no disk and
no wait; the only local file is the poster frame, saved through the same
`_save_image` the pictures use. The contract is `videoResult`, one JSON entry —
`{ok:true, url, src, title, alt, w, h, duration, poster, live}` or
`{ok:false, url, error}` — which QML appends to the row's `videos` array
(a JSON-string field beside `images`) and `VideoDeck.qml` draws as one card per
video. `videoStarted`/`videosActive` carry the in-flight line, which matters
more here than for an image: resolving a watch page is the slow part.

**Two routes, cheap one first.** A URL that names a media file is HEADed; if the
server confirms it is video, that URL IS the stream and no subprocess runs.
Everything else — a watch page, a shortener, and a media-looking URL the server
would not confirm — goes to **yt-dlp**, async on the file tools' `QProcess`
idiom, killed at `VIDEO_RESOLVE_MS` (45s) so a hung resolver fails the tool
instead of stranding the turn.

**A LADDER, and every rung is PROVED before a card is drawn.** `-f b` asks for
the best SINGLE file (a video+audio pair would have to be downloaded and merged
before anything could play). What that returns is not reliably playable, and the
failure is not chatter's to fix by choosing formats: on 2026-08-23 three YouTube
watch pages resolved to a progressive mp4 that answered **403 to every player on
this machine** — yt-dlp's own downloader, ffmpeg and mpv all refused, so no
source chatter could have handed QML would have played. What changes the answer
is which CLIENT the extraction pretends to be. The same three videos, the same
minute:

| `player_client` | result |
|---|---|
| default / mweb / android_vr / web_embedded | itag 18, **HTTP 403** |
| web / web_safari / ios | "requested format is not available" |
| tv | "the page needs to be reloaded" |
| **tv_simply** | itag 18, **HTTP 206**, plays |

So rung 1 is the default extraction PREFERRING HLS (`b[protocol^=m3u8]/b`) — a
manifest is the best single stream YouTube offers, up to 1080p, and needs no
headers — and rung 2 is `tv_simply`, which is only 360p but answered for every
video that had failed. `_video_probe` proves each rung's stream with a RANGED
GET (not a HEAD: googlevideo gave 403 to a plain GET and 206 to a ranged one on
the same URL) before the card exists, so a dead stream costs a retry instead of
a card that fails when he presses play — and when no rung serves, the reply says
so with the status code instead of drawing one.

**It never autoplays, and the decoder is built on the click.** The card sits on
its poster under a drawn play marker (the staircase of §2.3, not a `▶` two of
the three pixel fonts lack) until he presses it — he listens to music while he
works, and a chat window that starts making noise because a model said something
has taken his speakers. The `MediaPlayer` lives behind a `Loader` that only the
click activates: viewer measured the process's FIRST QtMultimedia object at
~460ms, and a transcript holding six videos he never played must not pay for
six. The transport strip (elapsed clock in a fixed slot, scrub track, duration)
sits INSIDE the artwork on hover, seeks with the pointer and no easing (§6.4),
and is absent for a live stream, which has nothing to scrub.

**Fullscreen BORROWS the player** [his, 2026-08-23]. The strip's right-hand mark
— four corner brackets, drawn, turning inward when it is already full — throws
the video onto `VideoStage.qml`, the lightbox's counterpart for a moving
picture: a scene-level overlay in `Root.qml` (z:290, under the image lightbox),
Escape or a click on the ground to leave, space or a click on the picture to
pause. It builds NO second player. A `MediaPlayer`'s `videoOutput` is only where
its frames land, so the stage points that at its own surface and hands it back
on the way out — the stream neither restarts nor re-buffers nor loses its
position, which a second player and a reparented card would each cost. The strip
itself is one file (`VideoTransport.qml`) worn by both, because the scrub is
exactly the control that must not differ between them (§0.1).

**The strip gained its OWN play/pause and stop, and the mini-player exists**
[his, 2026-08-23]. The transport used to be driven only by clicking the picture;
now `VideoTransport` also carries play/pause and stop (pause + seek 0), so a
video can be driven from anywhere the strip shows. And when a video is playing
whose bubble is NOT in view, a compact `MiniPlayer.qml` bar floats at the top of
the message view carrying that strip — so scrub/play-pause/stop are always
reachable [his: *\"when a video is playing and its chat bubble is not in view, can
it show a little playing preview thing at the top of the message box?\"*]. It
BORROWS the card's player the same way the stage does (one videoOutput at a
time; fullscreen from the bar hands the picture back to the card first, then
throws it to the stage). Root tracks started cards via `VideoCard.host`
(`videoCardActive` on the Loader's `onLoaded`, `videoCardGone` on
`Component.onDestruction`), and a 200ms timer (`miniTimer`, running only while
any card is registered) opens the bar for the first registered card out of view
and closes it when that card is back. Dismissing the bar remembers that card
(`miniDismissed`) until it returns to view, so a dismissed bar is not reopened
200ms later.

**The strip's visibility fixes a hover-steal glitch.** The card shows the strip
on `hover.containsMouse || !video.playing`. `containsMouse` on the whole-frame
tracker goes FALSE the instant the pointer lands on the strip's own controls —
they're on top and take the mouse — so a playing strip vanished under the
pointer it just appeared under, then came back when the mouse was handed back:
the pop-in-and-out glitch. The card now ORs `VideoTransport.pointerHere` (the
OR of every control's `containsMouse`) into that condition, so the strip stays
while the pointer is on any part of it.

**Failure is drawn** (docs/DESIGN.md §10): a non-http URL is refused before any
request, a resolve that fails reports yt-dlp's own last line, a resolve that
produced no single stream says so, a missing yt-dlp names itself and the limit
it leaves ("only a DIRECT video file URL"), and a stream the decoder rejects
puts `can't play this stream` on the card rather than leaving a black box.
Each reaches both audiences — a crit line in the chat, an error the model can
act on.

**The success result says the video is SHOWN, not "tell him about it"** — the
first wording asked the model to announce it, and it did: a turn on 2026-08-23
ended with the card and its sentence in the round-2 bubble and then a whole
extra bubble saying the video "is now in the chat above, ready to press play"
[his: *"why … it produced a video and then sent another message i dont
understand"*]. Two rules met badly — one bubble per round, and a note that
commissions a paragraph about something he can already see — so the note now
reads like `fetch_image`'s: he can see it, do not announce or describe it unless
he asks.

**Packaging**: `home/prog/oracle.nix` adds `qt6.qtmultimedia` (the QML
MediaPlayer/VideoOutput and its FFmpeg backend), puts `yt-dlp` on the wrapper's
PATH, and sets `QT_FFMPEG_DECODING_HW_DEVICE_TYPES=cuda` on `top` for the same
reason viewer does — Qt's ffmpeg backend probes VAAPI first, and VAAPI on
`top`'s render node is NVIDIA's shim, which cannot export a surface at all.
book keeps Qt's default. Harness: `tools/video-test.py` (offscreen; a stub
resolver and a 127.0.0.1 server, so it reaches neither his screen nor the
network), `--shot` for a PNG of the card.

## Showing, making and capturing a picture

Three tools that put pixels in the chat, and they are three because they differ
in **who sees what** — the distinction `view_image` alone could not make.

**`show_image` — DISPLAY, not LOOK** [his, 2026-08-23]. Until this existed, the
only way to put a local picture in the chat was `view_image`, which is a VISION
tool: it needs a vision-capable model, reads the whole file, and spends up to
8 MB of context on base64 — all to display a graph the model had just plotted
itself. `show_image` shows it and hands the model *nothing*, so a coding model
with no vision can still draw something and show it. The fast path is the honest
one: a QML `Image` loads a local file, so the entry points straight at it — no
copy, no re-encode. `_display_image` is the shared half; a file on the OTHER
machine comes back through the same jailed executor and is saved locally,
because QML cannot load a path that is not here.

**`make_image` / `make_video` — painter's backend, not a second one.**
`apps/painter/tools/smoke.py` is painter's OWN registry/graph/client path with
the GUI taken off, so chatter runs THAT, on `top`, where the weights and the GPU
are; it builds no graph and knows nothing about models, which is what keeps the
two from drifting. One shell does four things because they are one act: put any
input pictures where the backend can see them, start `comfy-painter` if it is
down (a user unit, `start` on a running one is a no-op), wait for
`/system_stats` to answer, then generate. `_painter_argv` is the whole command
for both tools and `_make_media` the whole body — the family, the clock and how
the result is DRAWN are the only differences, and two copies of the warden dance
is what splitting them would cost.

- **Everything painter can do, chatter can ask for.** Text-to-image on any
  installed family (`model` is a substring — 'anima', 'krea', 'chroma',
  'z_image', …), an EDIT when `input_images` are given (which selects the edit
  model on its own), and a clip from `make_video` with a first frame, a last
  frame, both, or neither. `aspect` + `megapixels` are converted by the
  registry's own `calc_dims`, so his shorthand and painter's sliders land on the
  same width and height.
- **An input picture has to BE on the machine the backend is on.** On top the
  path is passed straight through; from book the files travel as a tar on the
  command's stdin (`_painter_input_payload`, capped at `PAINTER_INPUT_MAX`) and
  are unpacked into `/tmp/oracle-painter-in`, because the ssh master is the only
  thing the two machines share. A path that is not there is refused BEFORE the
  backend is woken.
- **A still is drawn through `_display_image`; a clip is a VideoCard pointed at
  the local file** (`_display_clip`), on a poster frame lifted with one ffmpeg
  frame — a card with no poster is a black box wearing a play marker. A clip
  made from book is NOT shown, because QtMultimedia cannot stream a path that is
  not there; the tool says where it is instead (docs/DESIGN.md §10).
- **What he set in painter is what he gets.** Every argument the model leaves
  out falls back to painter's own remembered settings for that model
  (`painter/userprefs.py` — size, steps, sampler, his negative prompt, a clip's
  length, the seed policy), which is why both tool descriptions say to pass ONLY
  what he asked for. His rule, 2026-08-24: painter's defaults are the reference,
  and something else only when he says so.
- **A clip's clock is not a picture's.** `MAKE_VIDEO_MS` is an hour against
  `MAKE_IMAGE_MS`'s fifteen minutes: MiniMax H3 samples every frame, so six
  seconds is tens of minutes on this GPU.
- **Both are CORE tools** (`CORE_TOOL_NAMES`), unlike the rest of the image
  group. "make me a picture" is a thing he asks in plain words, and an
  unattached tool is one the model has to go looking for — on 2026-08-24 it went
  looking, read the `comfyui` skill, curled the backend, and told him the daemon
  did not exist and painter was not installed, with both sitting right there.

**The memory dance, and why chatter gives its OWN weights back first.** The
warden never interrupts work in flight, and chatter's `send` lease is still live
while a tool runs — so with a 22 GiB model resident it would (correctly) refuse
every generation chatter itself asked for. But chatter is not a third party
here: between rounds it is generating nothing, and its weights are exactly the
room the render needs. So `_make_media` does what he asked for in so many words
[2026-08-24] — *unload to make room, reload to carry on*:

1. `done("ollama")` — drop its own lease, so the warden sees an idle ollama and
   frees it (`keep_alive=0`; the daemon stays up).
2. `reserve("comfy", lease=WARDEN_LEASE_S)` — a SHORT lease, not the job's
   ceiling.
3. `renew("comfy")` every `WARDEN_BEAT_MS` while the process runs. Waking the
   backend and loading 20 GB can outlast a reservation on its own, and comfy's
   queue only becomes the busy signal once the graph is submitted — the far end
   of exactly that window. A re-`reserve` would be the wrong heartbeat: it
   re-runs admission, unloading the other side and toasting it once per beat.
   Short + renewed means a chatter that dies mid-render costs painter two
   minutes, not an hour.
4. `done("comfy")` then `reserve("ollama")` at the end, in that order — so the
   model reloading for the rest of the reply cannot land on top of a render, and
   comfy's weights go back before it does.

A refusal still puts the ollama lease back before it answers, since it never got
as far as freeing anything. Harness: the recording-warden section of
`tools/toolbox-test.py`, and `~/nix/tools/ai-warden-test.py` for the decision
table behind it.

**A render is minutes; the chat shows where it is.** Until 2026-08-24 the whole
of one was a single motionless "making a picture…", which reads as stalled. The
generator reports its position (`--progress`) and chatter reads stdout AS IT
RUNS — `readyReadStandardOutput`, accumulating the whole of it, because
`finished` still needs the `saved …` lines and `readAllStandardOutput` hands
back only what has not been read. `genProgress(label, frac)` / `genFinished()`
land on the turn as `genLabel`/`genFrac`/`genRunning`, and QML draws a `Meter`
under the tool disclosure's heading — open or shut, since the point is that the
wait is visible. Transient like `execTail`: what it MADE is the picture, so
nothing about the bar is persisted.

**A PORTRAIT picture is capped by its HEIGHT, not only by the column.** Sized by
the column alone a 2:3 render is nearly three times the height of a 16:9 one in
the same chat and pushes the reply off the screen [his, 2026-08-24]. The ceiling
is 320 in all three places media is drawn — `ImageGallery.maxH`,
`InlineImage.maxH` and `VideoCard.maxH` — so a still and a clip of the same
shape take the same room. Nothing is cropped: the picture is drawn smaller, and
one click still opens it full size in the Lightbox.

**ONE PICTURE, DRAWN ONCE.** `_images_shown` keys on the URL, so it never
covered a local file — and a turn that generated one picture then `show_image`d
the same path twice put it in the chat three times and told him two had been
generated [2026-08-24]. `_paths_shown` is the per-turn set of local files
already drawn (reset in `send`, like the URL ledgers); a second request for one
already on screen is answered `ok` with `already_shown`, no second card, and a
note saying there is one of it and not two. The file is the identity here, not
the URL, because a generated picture has no URL at all.

**The tool result carries the FACTS back, not just "it exists"** (`_gen_facts`).
Seed, model, size, steps, sampler/scheduler, cfg and the final prompt go to the
model as fields, because otherwise it cannot answer "lock that seed and change
one thing" at all: on 2026-08-24 it spent five tool rounds — `file_metadata`,
`find_files`, three `run_bash` — digging its own seed back out of the PNG it had
just written. The note with them says the picture is MADE (do not call again),
and not to say where it is: the same turn told him it "should be showing inline
above" while the picture sat below, which is the model narrating a layout it
cannot see.

**A generated picture says what made it.** The caption is the prompt the GRAPH
ran — the generator reports it in `::result`, so it is the transformed spelling
with the NegPip negative folded in, not the argument the tool was handed [his,
2026-08-24: "i dont see the negpip negative text anywhere in the caption"]. A
second,
dimmer line under it (`entry.meta`, drawn where a fetched picture's host goes)
carries the model, the size, the steps, the sampler/scheduler, the cfg and the
seed — the rest of the answer to "what is this", and the seed is what makes the
same picture again [his, 2026-08-24]. `_gen_meta` builds it from the generator's
`::result`, i.e. off the graph that actually ran, so everything that came from
his painter settings and never appeared as a tool argument is in it too.

**The lightbox walks the WHOLE conversation, and takes the log with it.** It
used to open on the pictures of ONE reply, which made the arrows useless for the
thing he wanted them for [his, 2026-08-24]. `conversationImages()` collects
every drawn picture in order with the row it sits on; `openPicture(entry)` finds
the clicked one inside that run; and `Lightbox.currentRow` — the row parallel to
the current entry — scrolls the reply as he steps, so closing it leaves him
where the picture is rather than where he opened it.

**A picture or a clip can LEAVE the window.** Right-click anything in the log —
inline picture, gallery tile, lightbox, video card — and `Clip.copyImage` /
`copyFile` put it on the clipboard through `pylib/clipfile.py`, never
QClipboard: a Wayland selection dies with the process that offered it, and
`setMimeData` hands Qt's global-static clipboard a Python-built QMimeData it
frees after the interpreter is gone (a SIGSEGV on exit from any run that
copied). The components own no menu — each has a `contextRequested(path, x, y)`
signal and Root, which holds the one `ctxMenu`, puts the rows on it. The outcome
is TOASTED (§10): chatter had no transient surface at all, so painter's toast
came over verbatim — a copy that silently did nothing looks exactly like one
that worked, right up until the paste.

**`booru_tags` — the vocabulary, searched, not remembered.** Anima was captioned
with Danbooru's tags, and a tag the site does not have does nothing at all — it
is not a weaker version of the tag you meant. A model writing from memory
invents plausible ones at a steady rate, so the 91k-tag list ships with the apps
(`pylib/boorutags.py`) and the tool searches it, resolves aliases
(`sole female` → `1girl`), names each tag's category (an artist is written
`@name`) and CHECKS a drafted prompt for the invented ones. Pasting a whole
vocabulary into the context would be 2 MB and still not say which tag is the
used one.

**His shorthand is parsed HERE, not by the model** (`genshort.py`). `anima. 2:3
x1 1girl, solo, …` and `video. first frame: [pasted image]. 6s i2v. …` are jobs
with numbers in them, and a local model asked to infer them gets the aspect
backwards and "improves" his danbooru tag list. So `send` parses the message
into the exact tool arguments, appends them to the turn as an instruction
(`hint_for`), and attaches the generator to that turn so no `get_tools` round is
spent on it. The parse is deliberately conservative — a message that does not
open with a model or a mode word produces nothing at all — and the prompt is
whatever is left after the settings, verbatim. Attached pictures fill the
frames of a clip and the subject of an edit, which is what attaching one to a
generation means. Harness: `tools/shorthand-test.py`.

**An attachment's PATH is part of the note the model gets**, whether the model
has vision or not: an attached picture is also the thing `make_image` edits and
the frame `make_video` animates from, and neither needs vision. Without the path
the model has a picture it cannot name to a tool.

**The warden goes first, and its refusal is the honest answer** (`apps/pylib/
warden.py`). ollama and ComfyUI share 31 GiB, and a collision does not fail an
allocation — it livelocks the desktop. Note what that means in practice: while a
23 GiB model is loaded and mid-reply, the warden REFUSES, and it is right to.
The tool result says so in the terms he can act on — a smaller model leaves room
— rather than pretending the picture is coming.

**`screenshot` — his screen, and he sees what was seen.** `grim` under Hyprland,
Spectacle under Plasma, chosen by what is installed rather than by a guess about
the session; `$ORACLE_SHOT_CMD` replaces it (the harness points it at a stub, so
no test photographs his desk). The frame is drawn in the chat AND attached to
the model's next turn, because a model looking at his screen while he cannot see
what it looked at is exactly the secret docs/DESIGN.md §10 forbids; over
`ATTACH_IMAGE_MAX` it is downscaled rather than refused. `show_only` captures
without handing it over.

**This does NOT cross root AGENTS.md's line.** That rule forbids an AGENT'S TEST
from screenshotting his session. This is the opposite direction — he asked the
app for it, at his own keystroke, in his own window — and no harness may call it
for real.

## Tools he writes himself (a directory of manifests)

Asked whether it could make its own tools, chatter answered "no — those are
defined by the framework I run in" [his session, 2026-08-23]. This is the door.
`$ORACLE_TOOLS` (default `~/.local/share/oracle/tools`) holds one JSON manifest
per tool:

```json
{"description": "What it does, written for the model.",
 "parameters": {"type": "object", "properties": {"city": {"type": "string"}},
                "required": ["city"]},
 "run": "weather.sh", "timeout": 30}
```

`run` is optional (default: the executable of the same stem beside it). The
program gets the call's arguments as **JSON on stdin** and whatever it prints on
stdout is the result — parsed as JSON when it parses, text otherwise; a non-zero
exit is an error carrying its stderr, so the model can tell him which of his
scripts broke and how. That is the shape of every executor here, so a tool is a
shell script that reads stdin and prints.

Read FRESH every turn, so adding one is saving a file, not restarting chatter.
A manifest that will not parse, names no runnable program, or collides with a
BUILT-IN name is skipped rather than offered (§10 — never an affordance that is
not there); `Ollama._builtin_tools()` is what the collision is decided against,
so the two lists cannot drift. Subagents get them too, through the same
registry, and every custom description carries `BUILT_BY_HIM` so the model knows
whose failure it is looking at.

## Chatter extends ITSELF (make_tool / make_skill / make_agent)

The section above is a directory HE writes into. This is the model writing into
it [his, 2026-08-23: *"ensure agents have the ability to create tools for
themselves and other / future agents… oracle should have a ton of self
modification ability"*]. Three tools, offered every turn and to subagents too:

| Tool | Writes | Read back by |
|---|---|---|
| `make_tool` | `$ORACLE_TOOLS/<name>.json` + `<name>.py`/`.sh`, chmod 755 | `custom_tools()`, every turn |
| `make_skill` | `$ORACLE_SKILLS/<name>/SKILL.md` (frontmatter + body) | `skill_catalog()` / `use_skill` |
| `make_agent` | `$ORACLE_AGENTS/<name>.md` (frontmatter + prompt) | `agent_catalog()` / `spawn_agent` |

- **It could already do this with `write_file`** — and that is exactly why the
  tools exist. A skill or an agent is one markdown file and hard to get wrong; a
  TOOL is a manifest plus an executable plus a JSON schema, and a model that
  gets one of the three subtly wrong installs something that silently never
  loads. So the shape is written here, VALIDATED, and reported back as live or
  not at all (docs/DESIGN.md §10): the name is checked against the app's own
  tool names, the program is syntax-checked (`compile()` for python, `bash -n`
  for bash) before it is installed, a missing description is refused because it
  is all a future model will know, and the result says whether the catalog
  actually picked it up.
- **Live on the NEXT tool call.** All three stores are read fresh every turn, so
  nothing restarts and nothing rebuilds — the same property that makes his own
  manifests work.
- **`delete` is the same door**, and deleting an agent definition puts the
  app's own built-in of that name back.
- **Subagents get them** (`AGENT_TOOL_GROUPS["author"]`, in the default set),
  which is the "and other / future agents" half: an agent can leave a tool
  behind for the next one.
- **The model is TOLD** — `authoring_note()` in every system prompt, beside
  `skills_note()` and `agents_note()`. A model does not reach for a door it was
  never told about; chatter's own answer before this existed was "no, those are
  defined by the framework I run in".
- Harness: `tools/self-extend-test.py`, against temporary stores — it writes a
  tool, runs it the way chatter does, checks the refusals, and deletes all
  three. His own tools, skills and agents are never touched.

## Watching a program run (run_bash / run_python)

`tools/sandbox-exec.py` takes `stream: true` and then emits its child's output
as NDJSON lines — `{"t":"o"|"e","d":"…"}` — with the result object still LAST,
exactly as before, so a caller that does not ask (or an older copy of the script
reached over ssh, which ignores the key) is unaffected. chatter parses those
lines out of the pipe and emits `execOutput`; the row keeps a bounded tail
(`execTailMax`, 4000 chars) under the files disclosure. The tail is transient
and is not persisted: what the program MEANT is in the reply.

**The heading previews the last line; the block stays shut** [his, 2026-08-23].
It used to spring open on its own while a program ran — live output nobody can
see is not live output — but a build or a download prints hundreds of lines and
the block became the flood it was there to contain. So `execPeek` puts the LAST
line of the tail **on its own line under** `working with files…`, elided so it
stays one line however long the program's is. Not beside the heading [his,
2026-08-23]: a path or a progress bar sharing that line leaves neither half
room to read, so `fileToggle` is two rows tall while it shows.

It is drawn **only while the program runs** (`execRunning`), and goes the
moment it stops [his, 2026-08-23] — a finished console has nothing live to
preview, and its last line left sitting under the heading reads as still
going. It also goes when he opens the block, where the whole tail is drawn
anyway. His own click still wins in both directions.

- **`win.lastLine()` splits on `\r` as well as `\n`.** A download or a build
  redraws ONE line with carriage returns, so splitting on newlines alone hands
  back the whole progress bar's history as a single enormous line — and the
  line being redrawn is exactly the one worth previewing.
- Harness: `tools/exec-peek-test.py`, which drives `execOutput` with a
  carriage-return progress bar, then asserts on the rendered items that the
  preview sits BELOW the heading and is gone once `execFinished` lands. It
  holds a Python reference to every `setContextProperty` object: dropped, they
  are garbage-collected, `DeskStyle` reads as undefined and `Theme.lineHeight`
  falls to 0 — which is not an error but a layout, every row collapsing to
  nothing under an assertion that then measures the collapse.

## Branching: edit and resend, ask again

Right-click a prompt of his → **edit & resend**; right-click an answer → **ask
again** [his, 2026-08-23]. Both go through `branchAt(i)`, and the rule there is
that going back is **not** undo: what came after is a real conversation. So the
transcript as it stands is SAVED under the id it already has, and the shortened
one becomes a NEW session — the old branch keeps its title and its rows in the
picker, and the window carries on from the fork. Nothing is deleted anywhere.
`edit & resend` puts the text back in the box and sends nothing; `ask again`
re-sends the prompt above the answer unchanged. Both stand down while a reply is
streaming. Harness: `tools/toolbox-test.py`.

## The models themselves (manage_models)

**Asked to install a model, chatter reached for `run_bash` and lost** [his,
2026-08-23]. `ollama pull qwen3.6:27b` died with `runtime/cgo: pthread_create
failed` before a byte was downloaded, the model read that as thread exhaustion,
delegated it to a subagent, failed the same way, and finished by advising him to
edit `/etc/security/limits.conf` — *"which won't work on macOS"*. Two separate
faults, both worth naming:

1. **The runner's `RLIMIT_AS` was 1 GiB, and address space is not memory.** A Go
   runtime RESERVES far more virtual space than it touches (arenas, 8 MB of
   stack per OS thread), so EVERY Go binary on this machine died under that cap
   while a python loop allocating real memory sailed under it. Measured with
   `ulimit -v`: `ollama list` aborts at 1 GiB and works at 2 GiB. It is 4 GiB
   now (`tools/sandbox-exec.py`), and what actually bounds a runaway is still
   the wall clock, the CPU cap and oomd.
2. **A pull was never a shell job.** `ollama` on the command line is a client
   for the daemon chatter is ALREADY a client of. `manage_models` calls that API
   directly: `list` (installed models, biggest first), `show` (the real context
   length and capabilities, off `/api/show`), `pull` (streamed, so progress goes
   to the same live tail a running program writes to — a 20 GB download looks
   like work rather than a hang), and `remove`. No shell, no rlimits, and
   ollama's own error text instead of a shell's exit code.

**A pull checks the DISK first** (`MODEL_DISK_FLOOR`, 5 GB): the weights land on
`/`, which runs fairly full, and finding that out 18 GB in is not a check. It
carries no transfer timeout — `MODEL_PULL_MS` (90 min) is the only leash — and
it is the same endpoint from either machine, since book's `$OLLAMA` is the
tunnel to top.

**`remove` needs `confirm: true`.** Deleting 20 GB of weights is not undoable
and is not the kind of thing a model should be able to do while tidying up; the
first call comes back telling it to ask him. Harness: `tools/toolbox-test.py`,
against a stand-in ollama that serves `/api/tags`, `/api/show`, a streamed
`/api/pull` and `/api/delete` — so a test run never pulls onto his disk or
deletes a model he uses.

## The music player (control_player)

**A reply can see and drive what is playing** [his, 2026-08-23: *"give agents
the ability to manipulate playback of player"*]. `PLAYER_TOOL` takes an
`action` — status, play, pause, play_pause, next, previous, seek, volume,
shuffle, loop — and **every one of them ends in a status read**, so the model
reports the state it produced rather than the one it intended. No new seam in
`apps/player` was needed: it already publishes MPRIS
(`org.mpris.MediaPlayer2.player`, the interface the panel's media widget
drives).

**Only what the player really does is offered** (docs/DESIGN.md §10). MPRIS
`Stop` and `OpenUri` are no-ops in its adapter, so neither is in the enum; an
action that is not there comes back as a refusal with a reason, never a silent
success.

**Through `playerctl`, not QtDBus.** The obvious route is a `QDBusInterface` on
the session bus, and it is a dead end: PySide cannot demarshal MPRIS's `a{sv}`
`Metadata` — `QDBusArgument.asVariant()` returns null, so `PlaybackStatus` and
`Position` read fine while the title, artist, album and length all come back
empty (measured against the real player, 2026-08-23). playerctl is a real MPRIS
client, one `--format` line carries everything the model is told, and the whole
status costs ONE process instead of nine property reads. It is on the wrapper's
PATH (`home/prog/oracle.nix`); absent, the tool says so.

**It is the bus of the machine the WINDOW runs on**, and that is an honest
limit rather than a hidden one: his library lives on `top`, so a book window
finds nothing and the result says exactly that — "no music player is running on
this machine" — for the model to relay instead of pretending.

**Browsing the library is a different seam, and it had to be built** [his,
2026-08-23: *"are agents able to easily browse and play music from my
library?"*]. They were not: MPRIS carries the CURRENT track and nothing else, so
`control_player` could skip and pause but could not answer "what have I got" or
"put that album on" — and `OpenUri`, the one MPRIS verb that would play a file,
is a no-op in player's adapter. `music_library` is the other half:
`apps/player/tools/library-ipc.py` runs where the music is (top, over the same
ssh master as the file executor) and does two things — a READ-ONLY sqlite query
against player's own `library.db` (search / albums / album_tracks / stats, with
ratings, favourites and play counts), and the queue verbs on player's socket.
Every row carries its `path`, which is the whole point: search, then hand those
paths to `control_player` `play_these` (replace the queue and start) or
`queue_these` (append).

**The queue verbs go over player's socket, not MPRIS** — `OPEN` was already
there for a second launch's `%F`, and `QUEUE` is its new counterpart
(`Player.queuePaths`, apps/player/AGENTS.md). Read-only on the database, always:
the library is player's to write, and a second writer is how a library loses
ratings.

**A seek TO and a seek BY are different commands**: `position 90` versus
playerctl's own `position 10+` / `15-`. Volume is 0-100 to the model, 0-1 on
the wire, and clamped rather than passed through.

Harness: `tools/player-meta-test.py`, which drives a **stub playerctl** it
writes itself (`$ORACLE_PLAYERCTL`, `$ORACLE_MPRIS`) and asserts on the argv —
so a test run never pauses, skips or re-shuffles the music he is listening to
(root AGENTS.md: never drive the running player).

## Last.fm — what he PLAYS, not what he owns (`lastfm`)

`music_library` answers "what does he have"; `LASTFM_TOOL` answers "what does
he listen to", which is a different question and the one a recommendation
actually needs. player scrobbles every play into the same account, so `recent`
is a live read of what it has been writing.

- **One account, one credential file** — `~/.config/lastfm/account.json`,
  owned by `pylib/lastfm.py` (read `apps/AGENTS.md` → `pylib/lastfm.py`
  first). Linked once with `apps/player/tools/lastfm-connect.py` or from
  player's settings; re-read on **every call**, so linking an account while
  chatter is open needs no relaunch.
- **The credentials and the signature stay in pylib, the transport does
  not.** `lastfm.request_params()` hands back the signed, urlencoded body and
  chatter puts it on its own `QNetworkAccessManager` — the same reason every
  other network tool here is async: `pylib`'s blocking urllib call on the GUI
  thread would freeze the window mid-reply.
- **Read, plus the two loves, and nothing else.** `love`/`unlove` are offered
  because they are his own gesture, reversible in one call, and the same one
  the player's heart makes. **There is deliberately no scrobble action**: a
  model inventing plays would corrupt the very history the read actions exist
  to consult, and only he can delete a scrobble.
- **The projection is generic, by field NAME, not a shape per method**
  (`_lastfm_project`). Every Last.fm response is one wrapper key around rows
  carrying five sizes of the same image, a streamable flag nobody wants and,
  on the info methods, a whole biography — so the wrapper is unwrapped,
  `LASTFM_DROP` names what goes, long strings are cut at `LASTFM_STR_CHARS`
  and the whole thing is capped at `LASTFM_CHARS` (his rule 5). Twenty
  hand-written projections would not survive Last.fm adding a field; this
  does.
- **`user` defaults to him** and the three info methods carry his `username`,
  so `track_info` reports his own play count and loved flag rather than the
  world's.
- **Not set up is a reason, not an empty result** (docs/DESIGN.md §10): with
  no API key the tool answers with the command that fixes it, and a write with
  no linked account is refused before it is sent.
- Subagents can be given it — it is in `_tool_registry()` and in the new
  `music` tool group alongside `music_library`.
- Harness: `apps/player/tools/lastfm-test.py`, whose last section asserts this
  projection and that the tool is offered. Run it as
  `oracle-qtenv python3 apps/player/tools/lastfm-test.py`.

## What a file IS (file_metadata)

**The answer `read_file` cannot give.** A 4-minute flac is bytes to `read_file`,
and a model asked how long a track is, who it is by, or what a video is encoded
with had to guess from the filename. `file_metadata` is a read-only file tool
like the others — same executor, same wide read root, same `host` argument — and
returns size, mtime, mode, the **real** type (sniffed from the first bytes,
never the extension), the line and word count of a text file, and for media the
container, duration, bitrate, per-stream codecs and dimensions, and the embedded
TAGS.

`sha256` is opt-in (`hash: true`) because it reads every byte. The counts are
over the WHOLE file, streamed — a capped count is a wrong count, and "3062
lines" of a 5904-line file is worse than no number.

The media half is `ffprobe` when it is on the target host; everything else is
stdlib, because `sandbox-fs.py` still has to run over ssh on a machine with
nothing installed. Its output is projected down (`META_MAX_STREAMS`,
`META_MAX_TAGS`) — a raw `-show_streams` on a video is hundreds of lines of side
data, and the context budget is the point.

## Dropped-file attachments

Drag files from the file manager onto the window and they attach to the **next**
message as context (docs/DESIGN.md §13 — dropping into a window works like a file
manager). A window-filling `DropArea` (`fileDrop`, keyed `text/uri-list`)
highlights while a drag hovers, drops append to the `attachments` `ListModel`
(one removable chip each in the `attachBar` above the compose box), and the tray
clears when the message is sent. A message may be text, files, or both.

- **Read LOCALLY, not on top.** These are the user's own dropped files, not
  sandbox paths, so `Ollama._read_attachments` reads each where the window runs
  and inlines its **text** into that one user message (`send`'s 4th arg,
  `attachments_json` = `[{name, path}]`). Bounded per his context rule:
  `ATTACH_FILE_MAX` (128 KB) per file, `ATTACH_TOTAL_MAX` (512 KB) per turn, with
  a truncation note; a **binary or unreadable** file is NAMED with the reason,
  never dumped (docs/DESIGN.md §10). The budget heuristic runs on the prompt
  BEFORE inlining, so a big file cannot fan the web search wide.
- **An IMAGE goes to the model as vision, not text.** `send` classifies each
  dropped file by its MAGIC BYTES (`_sniff_image`, never the extension —
  png/jpeg/gif/webp); image items are routed away from the text block and, for a
  **vision-capable** model (the `capabilities` list read off `/api/show`, gated
  on it being for THIS model), base64-encoded onto ollama's `images` message
  field (`_read_image_attachments`), bounded by `ATTACH_IMAGE_MAX` (8 MB/image;
  an over-cap or unreadable one is named, not dropped). For a model with **no
  vision support** no image bytes are sent and the message carries an honest note
  that images were attached but this model cannot see them (docs/DESIGN.md §10 —
  never silently dropped; pick a vision model). Either way a `[attached
  image(s): …]` line is added to the visible/saved turn.
- **URLs are resolved in Python** (`Ollama.localFileInfo` → `QUrl.toLocalFile`),
  never decoded in QML (§13 — `decodeURI` mangles `#`/`?` in a uri-list).
- **Staged into the sandbox for the file tools.** Beyond inlining a text file's
  (bounded) body, `send` also COPIES every non-image attachment into the file-tool
  sandbox under `attachments/` (`_stage_attachments` → the `put` op on
  `sandbox-fs.py`, run through the same `_fs_argv` executor — local on top, over
  the ssh master on book), and the user message names where each landed. So the
  model can `read_file attachments/<name>` for the FULL file (the inline text is
  capped at 128 KB) and `edit_file`/`write_file` to manipulate it — the "read and
  MANIPULATE the dropped file" path, reusing the existing jail rather than a new
  tool surface. Staging is synchronous (the files are small and must be in place
  before the first tool round), capped at `ATTACH_STAGE_MAX` (2 MB, the sandbox's
  own write ceiling), and best-effort: a file too big or an executor/ssh failure
  is NAMED in the note, never silent (docs/DESIGN.md §10). `put` is NOT a model
  tool (no schema in `FILE_TOOLS`, no name in `FILE_OP`) — only oracle's own
  staging code calls it. **Because the tools run on top, top's checkout needs the
  `put` op** (any `sandbox-fs.py` change is live on top only once top pulls).
- **Per-message, not persisted as context.** The visible/saved turn shows the
  prompt plus a dim `[attached: …]` filename note; the file bodies go only to the
  model on the turn they were dropped, so history stays clean and a later turn
  does not silently re-see them. (The staged copies under `attachments/` do
  persist in the sandbox — the model may have edited them on purpose.)

## File tools (unjailed since 2026-08-22)

oracle offers the model a set of **file tools on every turn** — `list_dir`,
`read_file`, `write_file`, `edit_file`, `move_path`, `delete_path`, `make_dir`,
plus the **search tools** `find_files` (glob), `search_text` (regex grep) and
`show_tree` (`FILE_TOOLS` in `main.py`). Reading, searching *and* manipulation,
always available: **no toggle**, his call.

**Adding another tool.** The seam is four small edits and no plumbing: add an
`op_<name>` to `tools/sandbox-fs.py`'s `OPS` dict (it gets the jail root and the
request, returns a dict), add the tool schema to `FILE_TOOLS` in `main.py`, map
its tool name to the op in `FILE_OP`, and give it a heading/outcome line in
`_fs_heading`/`_fs_outcome`. `FILE_TOOL_NAMES` and the dispatch (`_run_fs_tool`,
tool-result feedback with `tool_name`) pick it up automatically. Any op that
WALKS the tree (`glob`/`grep`/`tree`) must descend with
`os.walk(followlinks=False)` and pass every candidate through `contained()`
before reading or reporting it — the same realpath guard `resolve()` uses, so a
symlinked file cannot leak a path outside the jail. Cap every result (a match
list, a scan, a tree) so it can never blow the model's context window. The consequence is deliberate and worth knowing — because
every request now carries `tools`, a model with **no tool support rejects it**
(the same reason the `web` toggle was opt-in). oracle is a tool-calling window
now; point it at a tool-capable model.

**Both roots are now `/`.** Every op runs through `tools/sandbox-fs.py`,
which refuses to touch anything outside its root, **symlinks included**
(`os.path.realpath` + a containment check — `_under()`, which has to normalize
a root of `/` specially, since `"/" + os.sep` is `"//"`, a prefix nothing
starts with; that bug shipped and was caught the same day the root widened to
`/`). Until 2026-08-22 the read ops reached the whole
filesystem while the mutating ops stayed in the sandbox — so a chatter agent
could read any file on the machine and then not fix it. **That half-jail is
gone** (*"i dont really want them to be [sandboxed]"*): `WRITE_ROOT` is `/`
too, and a local model can now overwrite, move and delete anything the user
can, with no confirmation step. That is a real security decision and it is
his; `ORACLE_WRITE_ROOT` is how it is taken back (point it at `SANDBOX_ROOT`
for the pre-2026-08-22 behaviour, or at his home for something in between).
`SANDBOX_ROOT` survives as the model's **scratch directory** — where dropped
attachments are staged and where `run_python` starts — not as a fence.

- `list_dir`, `read_file`, `find_files`, `search_text`, `show_tree` (the
  `READ_OPS` set in `sandbox-fs.py`) resolve against `READ_ROOT` — **`/`** by
  default (overridable with `$ORACLE_READ_ROOT`; point it at his home to
  restore the 2026-08-11 scope, or at `SANDBOX_ROOT` to restore jailed reads).
  Their paths are **root-relative** (`'.'` is `/`).
- `write_file`, `edit_file`, `move_path`, `delete_path`, `make_dir` (and the
  internal `put`) resolve against `WRITE_ROOT` — **`/`**, overridable with
  `$ORACLE_WRITE_ROOT`. Their paths are root-relative like the read ops', so
  an absolute path is what the model should pass. **The tool descriptions are
  built from the live root** (`WRITE_FREE`/`WRITE_PATH`/`WRITE_WHERE` in
  `main.py`), so re-jailing with the env var re-words the tools instead of
  leaving them promising a reach they no longer have — the same rule
  `skill_tool()` follows.
- **Attachment staging follows the write root.** Dropped files still land in
  `SANDBOX_ROOT/attachments`, but the `put` op resolves against `WRITE_ROOT`,
  so `_stage_path()` expresses that target relative to it and hands the model
  the absolute path to read (`_stage_note`).

`sandbox-fs.py` takes the write root as `argv[1]` and the read root as an
optional `argv[2]`; with no `argv[2]` the read ops fall back to the write root,
so an older executor over ssh (the OTHER host not yet pulled) keeps the old
jailed-both behaviour rather than breaking. (The `argv[2]`-less fallback also means an un-pulled host silently keeps
whatever roots ITS copy was told, which is why a change here is only real once
both checkouts have it.)
(`sandbox-fs.py` also carries a `put` op that writes base64 bytes —
binary-safe, sandbox-jailed — used only by oracle's own attachment staging,
never offered to the model.)

**Reads reach BOTH machines, not just the one the window runs on** (his ask,
2026-08-11 — widened alongside the root). Every read-only tool schema carries
an optional `host` ("top"/"book", default "top" for backward compat with the
pre-widening behaviour) that the model sets to pick which machine's filesystem
it wants; `Ollama._fs_argv(target_host)` resolves it: if `target_host` is the
same machine the window already runs on, `sandbox-fs.py` runs **locally**;
otherwise it opens a **fresh ssh call to that host over the tailnet** (both
directions work — MagicDNS `top`/`book`; the book→top hop reuses
`tools/ollama-tunnel.sh`'s already-open control master via `OLLAMA_SSH*`, no
new listener). **Mutating tools take no `host`** — there is only one sandbox
and it always lives on `top`, so `write_file`/`edit_file`/`move_path`/
`delete_path`/`make_dir` always resolve `_fs_argv(None)`, i.e. local on `top`,
over the tunnel's master from `book` — exactly the pre-2026-08-11 behaviour,
unwidened.

Concretely: on `top`, `main.py` runs `sandbox-fs.py` locally for a `top` read
or any write, and `ssh book python3 tools/sandbox-fs.py <sandbox> /` for a
`book` read. On `book`, it's the mirror: local for a `book` read, `ssh top
python3 tools/sandbox-fs.py <sandbox> /` (over the tunnel's master) for a `top`
read or any write. The executor is **pure stdlib** so either host's system
`python3` runs it over ssh with nothing installed, and it `mkdir -p`s the
sandbox root on first use wherever it runs, so a fresh host needs nothing set
up by hand. `sandbox-fs.py` speaks one JSON request on stdin → one JSON result
on stdout; `main.py` dispatches each call as an async `QProcess` in the
existing tool loop, concurrent with any web search, and surfaces it as a third
per-turn disclosure (`fileToolStarted`/`fileToolDone` → the "files · N" block
in `Main.qml`, §9.1) with a `(book)` suffix in the heading when reading the
non-default host.

**Context is respected** (his rule 5): reads are paginated (default ~300 lines,
a 40 KB byte ceiling, over-long lines clipped, `next_offset` to page on),
listings are capped at 200 entries with `truncated`, binary files are refused
rather than dumped, and every tool result is a compact JSON object.

## Does the Plasma face still wear KDE's conventions?

`tools/plasma-chrome-test.py` — the standing check that this face is a KDE
program and not a Qt one wearing a KDE palette. It builds the real window
offscreen and reads what the shell actually made: the KStyle resolved to
something that is not Fusion, the palette came from his colour scheme and not
Qt's default light one, the icon theme is the desktop's, `&File` leads and
`&Edit` is second, Settings opens with the three view toggles and the app's
rows come after, `Show Menubar` is on the WINDOW (the trapdoor check), and the
`&Edit` rows go live with a selection and are disabled without one. Re-run it
after touching `apps/pylib/kdeshell.py`, since that file is shared with painter
and player — `player/tools/plasma-chrome-test.py` is the same check from their
side and covers the toolbar/transport half.

What the 2026-08-23 sweep MEASURED as already correct, so nobody re-derives it:
the live session resolves `widgetStyle=oxygen` (out of `kdedefaults/kdeglobals`
— the user file has no such key, which is normal for a Global Theme), the QML
font is `Oxygen-Sans` at 12px with `smooth` inverted for Plasma
(`deskstyle._kde_type`), every toolbar icon name resolves in the oxygen icon
theme at 16/22/32, and there is not one hardcoded colour literal in this app's
QML. `PixelText` under Plasma is therefore the SYSTEM font, not the pixel one —
it is the app's one `Text` type, not a pixel-only type.

Two deviations are known and deliberate rather than missed:

- **Help is Qt's shape, not KDE's** — `About chatter` and `About Qt`, where a
  KDE program has Handbook / What's This / Report Bug / About / **About KDE**.
  The KDE half of that lives in KXmlGui, which has no PySide6 bindings; a
  hand-written "About KDE" would be a fake of a dialog everyone recognises, so
  it is left off rather than imitated (docs/DESIGN.md §10).
- **`Meter.qml` and a reply's picture frames keep OUR drawing** — measured
  2026-08-22, a KStyle `ProgressBar` paints nothing inside a `QQuickWidget`,
  and both are readouts in the CONTENT rather than chrome. See *Two roofs*.

## Packaging & verifying

`home/prog/oracle.nix` builds the live-source wrapper (board.nix's template,
with the air split). No MimeType — it is a GUI over a daemon, not a file opener.
Verify offscreen, never on his screen:

```bash
QT_QPA_PLATFORM=offscreen oracle    # queries /api/tags, builds the model list
```

A rebuild is only needed for a dependency or `.nix` change; `.py`/`.qml` edits
are live on next launch.
