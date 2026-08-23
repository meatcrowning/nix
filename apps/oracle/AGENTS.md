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
model change and every send; 0/hidden when unknown). `tokensPerSec` is a running
estimate while a reply streams (one content frame ≈ one token, clocked from the
first frame) that settles to ollama's exact `eval_count / eval_duration` on the
final `done` frame. **`contextUsed`** is how full the context is — ollama's own
`prompt_eval_count + eval_count` from the last turn — drawn as `used/ceiling`, a
percentage, and a proportional **fill bar** (docs/DESIGN.md §9 meter; accent,
`warn` past 75%, `crit` past 90%; width animated §6). The row collapses to
nothing until at least one stat exists.

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

## Skills (Claude Code's own, as a real tool)

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
covers every skill, and a skill added under `~/.claude/skills` is offered with
no code change at all.

- **Where they live** — `SKILLS_ROOT` (`~/.claude/skills`, override
  `$ORACLE_SKILLS`): a directory per skill holding `SKILL.md` (YAML
  frontmatter `name`/`description`, then the instructions) plus reference
  guides in `references/`. **Nothing is vendored here** — `~/.claude` syncs to
  both hosts (`home/srvs/claude-state.nix`), so chatter and Claude Code read
  ONE source of truth and none of it lands in this public repo. Today:
  `video-prompt`, `flux-klein-edit` (the painter edit-mode instruction),
  `krea-prompt` (the positive/negative image pair) and `anima-prompt` (the
  same pair in Danbooru tags, for painter's anime mode).
- **`use_skill(name)`** returns that skill's `description`, its `instructions`
  (the SKILL.md with frontmatter stripped) and the names of its `guides`;
  **`use_skill(name, guide=…)`** returns one guide **in full**, in ONE call —
  the point of it being a tool rather than the old preset's instruction to page
  through the file with `read_file`. Capped at `SKILL_MAX_CHARS` (40000; the
  largest guide today is ~24k) and a cut is reported in the result.
- **Read in-process, no host branch.** Unlike the sandbox/session/memory
  stores it is a plain local file read, so it runs wherever the window is —
  both machines have the same `~/.claude`.
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

- **Definitions are files**, `AGENTS_ROOT/<name>.md` (`~/.claude/agents`,
  override `$ORACLE_AGENTS`): optional `---` frontmatter (`description:`,
  `tools:`, `model:`) and a body that IS that agent's system prompt. Same root
  reasoning as the skills: `~/.claude` syncs to both hosts
  (`home/srvs/claude-state.nix`), Claude Code reads the same directory, and
  none of it lands in this public repo.
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
  a tool result. It still surfaces — its own tools appear in the transcript as
  `<agent>: <tool>` and the spawn itself as a file-disclosure line (`agent
  explorer finished, 4 rounds`), so nothing it did is silent (docs/DESIGN.md
  §9.1, §10).
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
  the main context**. Plus the definition rules (fallbacks, group resolution,
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

So the one button beside the prompt box has three states, in this precedence
(docs/DESIGN.md §10.2 — one control, one place, and it says what it will do):

| state | when |
|---|---|
| `stop` | a reply is streaming (`busy`) |
| `send` | there is something typed or attached (`canSend`) — a prompt he wrote outranks carrying the last answer on |
| `continue` | neither, and `canContinue` |

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

Harness: `tools/round-split-test.py` — it drives one real prompt through the
real window offscreen against a stub ollama that asks for two tool rounds, and
asserts the log comes out as three reply rows with the prose and the tool on the
round that made them. It rides on `ORACLE_SEND` (send this prompt, then print
the chat log as JSON via `Root.rowsJson()`), which is the only way to see what
the ROWS became.

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
its next step — "I'd like to proceed with…", "Shall I?", "I'll now grep for…" —
and he was pressing `continue` over and over to get one task done [his,
2026-08-23]. So the app presses it:

- `Ollama.looksUnfinished(text)` reads the last 400 characters of a finished
  answer against `UNFINISHED_PATTERNS` — announcements of the model's own next
  action, and permission-asks for work he already asked for. An answer that just
  ENDS matches nothing, and a real question to him ("which of the two?") is not
  an announcement.
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

**Pictures sit at the TOP of the bubble** [his, 2026-08-22] — before the words,
the way a message with a photo in it reads everywhere else — and **their
captions are always drawn, not only on hover**: a caption you have to go looking
for with the pointer is not a caption. On a tile the caption stays INSIDE the
artwork (§5.1) and its wash goes one step more opaque as the pointer arrives; a
solo picture keeps its caption under it.

**Two or more pictures are a GALLERY, and one opens over the window** [his,
2026-08-23]: they used to stack full-width, one on top of the other, so seeing
the third meant scrolling past the first two. `qml/ImageGallery.qml` draws one
picture exactly as before and two or more as a tiled grid — balanced rows,
justified to the full width, gapless from the shared edge, square crops, the
caption inside the artwork on hover (docs/DESIGN.md §5.1). A tile opens
`qml/Lightbox.qml`, a scene-level overlay in `Root.qml` (z:300, above the drop
overlay): the picture fitted but never upscaled past native, Escape or a click
on the ground to close, arrows or a click on the picture to step, and focus
handed back to the reply area on close. Both are drawn once and serve both
faces, since `Root.qml` is the shared Item. Failures keep their crit line
whatever the count. Render them with `tools/gallery-shot.py [N]` — offscreen,
its own generated pictures, no daemon and no turn — which also checks the
overlay's keyboard.

**A model that TYPES the image gets it attached anyway** [his, 2026-08-22:
*"see how it failed to attached some images"*]. gemma4 reliably answers "show
me pictures of X" by writing `![alt](url)` into the reply instead of calling
`fetch_image`, however plainly the tool says otherwise — and `MarkdownText`
DEMOTES image markdown to a link on purpose (Qt would fetch it on render, at its
own pixel size), so the picture simply never appeared. `_attach_typed_images`
closes that at the other end: when a reply finishes with no more tool rounds,
its `![](http…)` URLs go through the same `_fetch_image` (capped at
`MD_IMAGE_MAX`, 4 per reply, deduped against everything already fetched this
turn), and `replyDone` waits for them. `_fetch_image`'s `idx` is `None` for
those — there is no tool call to answer, only the picture.

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
