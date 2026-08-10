# `oracle` — a minimal ollama chat window

The smallest of the vendored apps, and deliberately so. Two things and nothing
more: a **model selector** filled from the local ollama daemon's `/api/tags`,
and a **prompt box** that sends one chat turn to `/api/chat` and shows the reply
as it streams. No history persistence, no settings, no system prompt — his
scope was *"right now i think thats all i need"*.

## Shape

- **`main.py`** — the whole app. `Ollama` (on `QNetworkAccessManager`) is the
  only non-boilerplate class: `refreshModels()` GETs the tag list, `send(model,
  prompt)` POSTs a single-turn `stream: true` `/api/chat` and emits each NDJSON
  delta (`replyStarted`/`replyChunk`/`replyDone`, or `replyError`). One turn at
  a time — a new `send` aborts any reply still streaming. `Palette` and
  `Titlebar` are the same wal-palette-watch and vtb-chrome bridge every app here
  carries (copied from `reader/main.py`).
- **`qml/Main.qml`** — one file: the selector row, a `KineticFlickable`
  conversation area, and a prompt `TextEdit` (Ctrl+Enter sends). The model
  dropdown is inline rather than a shared `CtxMenu`, keeping this window's
  imports to the theme, `PixelText` and the `qmlcommon` Kinetic views. The
  conversation is a **persistent in-session LOG** (`ListModel chatLog`, a
  `Repeater` per turn): every send appends a `you` row and an assistant row and
  streams into the latter; prior turns stay in place and scrolled back, never
  scrubbed (docs/DESIGN.md §14). It follows the newest turn to the bottom only
  while a stream is live — idle, the scroll stays where he put it. A model's
  reasoning is a **collapsible disclosure, folded by default** (§9.1
  subordinated), whose heading reports progress: `thinking…` (one brightness
  step up) while the reasoning streams, settling to `thinking` (textDim) the
  moment the answer's first delta arrives. No history persists across launches.
- **`qml/theme/Theme.qml`, `qml/PixelText.qml`** — verbatim copies of reader's
  (the theme-as-context-property idiom, see `apps/AGENTS.md`).

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

## Packaging & verifying

`home/prog/oracle.nix` builds the live-source wrapper (board.nix's template,
with the air split). No MimeType — it is a GUI over a daemon, not a file opener.
Verify offscreen, never on his screen:

```bash
QT_QPA_PLATFORM=offscreen oracle    # queries /api/tags, builds the model list
```

A rebuild is only needed for a dependency or `.nix` change; `.py`/`.qml` edits
are live on next launch.
