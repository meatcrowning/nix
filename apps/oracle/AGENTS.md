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
- **`qml/Main.qml`** — one file: the selector row, a `KineticFlickable` reply
  area, and a prompt `TextEdit` (Ctrl+Enter sends). The model dropdown is inline
  rather than a shared `CtxMenu`, keeping this window's imports to the theme,
  `PixelText` and the `qmlcommon` Kinetic views.
- **`qml/theme/Theme.qml`, `qml/PixelText.qml`** — verbatim copies of reader's
  (the theme-as-context-property idiom, see `apps/AGENTS.md`).

## Talking to ollama

`OLLAMA` defaults to `http://127.0.0.1:11434` (override with `$OLLAMA_HOST`).
Loopback-pinned like every other local backend on this desktop — oracle opens no
listener. The daemon is the `ollama` service; if it is down, the model list is
empty and the reply area draws the error rather than nothing (docs/DESIGN.md
§10).

## Packaging & verifying

`home/prog/oracle.nix` builds the live-source wrapper (board.nix's template,
with the air split). No MimeType — it is a GUI over a daemon, not a file opener.
Verify offscreen, never on his screen:

```bash
QT_QPA_PLATFORM=offscreen oracle    # queries /api/tags, builds the model list
```

A rebuild is only needed for a dependency or `.nix` change; `.py`/`.qml` edits
are live on next launch.
