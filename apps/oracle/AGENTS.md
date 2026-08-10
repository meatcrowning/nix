# `oracle` — a minimal ollama chat window

The smallest of the vendored apps, and deliberately so. Two things and nothing
more: a **model selector** filled from the local ollama daemon's `/api/tags`,
and a **prompt box** that sends one chat turn to `/api/chat` and shows the reply
as it streams. No conversation-history persistence and no system prompt — his
scope was *"right now i think thats all i need"*. The one thing it does remember
is the **model selector**: the model last used and an agent-suggested ranking
(see *The model selector* below).

## Shape

- **`main.py`** — the whole app. `Ollama` (on `QNetworkAccessManager`) is the
  only non-boilerplate class: `refreshModels()` GETs the tag list, `send(model,
  prompt, web)` POSTs a `stream: true` `/api/chat` and emits each NDJSON
  delta (`replyStarted`/`replyChunk`/`replyDone`, or `replyError`). One turn at
  a time — a new `send` aborts any reply still streaming. `Palette` and
  `Titlebar` are the same wal-palette-watch and vtb-chrome bridge every app here
  carries (copied from `reader/main.py`).
  - **The web_search tool loop.** When the `web` toggle is on, `send` offers
    ollama a `web_search` function tool (`WEB_SEARCH_TOOL`). If the model emits
    a `tool_calls` frame, `_on_finished` runs each call — `web_search` hits
    Tavily (`_tavily_search` → `TAVILY_URL`), the result is fed back as a
    `role: tool` message, and `_post_chat` re-posts so the model summarizes and
    cites. It loops until the model stops calling tools or `MAX_TOOL_ROUNDS`
    (4). `webSearchStarted`/`webSearchDone`/`webSearchError` surface the search
    to QML for its sources disclosure. The tool is **opt-in** because a model
    with no tool support rejects a request that carries `tools` — off by default,
    normal chat is unchanged and never handed tools it would refuse.
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
  when it is collapsed. No conversation history persists across launches (the
  selected model does — see *The model selector*).
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
boot, so the tunnel script only reports its state, never starts it; the
`Backend.startServer()`/`stopServer()` buttons in `main.py` still shell out to
a *local* `sudo -A systemctl`, which correctly fails (not silently) on book,
where there is no such unit. `ORACLE_NO_TUNNEL=1` skips the tunnel for
UI-only work with no top.

## Web search (Tavily)

The `web` toggle beside the model selector lets the model reach the public web
mid-turn. It is backed by **[Tavily](https://tavily.com)** — sign up there for
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

## Packaging & verifying

`home/prog/oracle.nix` builds the live-source wrapper (board.nix's template,
with the air split). No MimeType — it is a GUI over a daemon, not a file opener.
Verify offscreen, never on his screen:

```bash
QT_QPA_PLATFORM=offscreen oracle    # queries /api/tags, builds the model list
```

A rebuild is only needed for a dependency or `.nix` change; `.py`/`.qml` edits
are live on next launch.
