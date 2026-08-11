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
- **`qml/Main.qml`** — one file: the selector row, a `KineticFlickable`
  conversation area, and a prompt `TextEdit` (Ctrl+Enter sends). The model
  dropdown is inline rather than a shared `CtxMenu`, keeping this window's
  imports to the theme, `PixelText` and the `qmlcommon` Kinetic views. The
  conversation is a **persistent in-session LOG** (`ListModel chatLog`, a
  `Repeater` per turn): every send appends a `you` row and an assistant row and
  streams into the latter; prior turns stay in place and scrolled back, never
  scrubbed (docs/DESIGN.md §14). A model row's answer is drawn through
  **`qml/MarkdownText.qml`** (`Text.MarkdownText`, pixel idiom, themed links) —
  the replies come back in Markdown; user prompts and error lines stay verbatim
  on `PixelText` (pinned `PlainText`, the shared guard), so only trusted-shape
  strings are ever interpreted. It auto-follows the newest text to the bottom
  only while he is already at the bottom (see *The model selector* §streaming) —
  scroll up mid-stream and it stops yanking. A model's
  reasoning is a **collapsible disclosure, folded by default** (§9.1
  subordinated), whose heading reports progress: while the reasoning streams it
  reads `thinking` (one brightness step up) with a **live token count** and an
  **animated ellipsis** beside it (dim, §9.1) — the count is the running frame
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

## File tools (jailed, on top)

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

**The jail.** Every op runs through `tools/sandbox-fs.py`, which takes one ROOT
directory and refuses to touch anything outside it, **symlinks included**
(`os.path.realpath` + a containment check). Paths the model gives are always
sandbox-relative. That script is the entire security model: the model gets a
sandbox, not the filesystem. The root is `SANDBOX_ROOT` — one constant,
`~/.local/share/oracle/sandbox`, overridable with `$ORACLE_SANDBOX`. To **widen
it later** ("maybe we let it run free"), point that env at `~` or `/`; no code
change.

**It lives on `top`.** oracle's compute is ollama on top, so the sandbox is
there too. On `top` `main.py` runs `sandbox-fs.py` locally; on `book` it runs it
**over the same ssh master** `tools/ollama-tunnel.sh` holds open
(`OLLAMA_SSH*`) — `ssh top python3 tools/sandbox-fs.py <root>` — so the tools
operate on top's filesystem whichever machine the window is on
(`Ollama._fs_argv`, host-branched exactly like `Backend._systemctl`). The
executor is **pure stdlib** so top's system `python3` runs it over ssh, and it
`mkdir -p`s the root on first use, so a fresh top needs nothing set up by hand.
`sandbox-fs.py` speaks one JSON request on stdin → one JSON result on stdout;
`main.py` dispatches each call as an async `QProcess` in the existing tool loop,
concurrent with any web search, and surfaces it as a third per-turn disclosure
(`fileToolStarted`/`fileToolDone` → the "files · N" block in `Main.qml`, §9.1).

**Context is respected** (his rule 5): reads are paginated (default ~300 lines,
a 40 KB byte ceiling, over-long lines clipped, `next_offset` to page on),
listings are capped at 200 entries with `truncated`, binary files are refused
rather than dumped, and every tool result is a compact JSON object.

## Packaging & verifying

`home/prog/oracle.nix` builds the live-source wrapper (board.nix's template,
with the air split). No MimeType — it is a GUI over a daemon, not a file opener.
Verify offscreen, never on his screen:

```bash
QT_QPA_PLATFORM=offscreen oracle    # queries /api/tags, builds the model list
```

A rebuild is only needed for a dependency or `.nix` change; `.py`/`.qml` edits
are live on next launch.
