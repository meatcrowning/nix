# chatter — local model chat

Read [the shared app guide](../AGENTS.md) for session detection, native controls,
packaging, and isolation. The displayed name is Chatter; internal paths,
`ORACLE_*` variables, module names, and persisted stores retain `oracle`.
Do not rename stores as part of a presentation change.

Detailed older implementation notes are in the private
[historical reference](../../docs/agents/oracle-legacy-reference.md), with a
section index. They preserve rationale and dated observations; they are not
current operating instructions. Read the relevant source before using a
historical constant, model name, performance figure, or service command.

## Owners and routing

| Area | Owner | Focused harnesses under `tools/` |
| --- | --- | --- |
| Chat transport, tool dispatch, context | `main.py` | `ctx-fit-test.py`, `lazy-tools-test.py`, `tool-repeat-test.py` |
| Shared window content | `qml/Root.qml` | `prose-layout-test.py`, `think-clock-test.py` |
| Plasma shell/actions | `main.py`, shared `pylib/kdeshell.py` | `plasma-chrome-test.py` |
| Sessions and prompt history | `tools/sessions-store.py`, `tools/prompt-history.py` | `sessions-search-test.py`, `prompt-history-test.py`, `timestamp-test.py` |
| Durable memory | `tools/memory-store.py` | `memory-save-test.py`, `memory-carry-test.py` |
| Tool host routing | `main.py` | `tools-host-test.py`, `request-routing-test.py` |
| File and code execution | `tools/sandbox-fs.py`, `tools/sandbox-exec.py` | `sandbox-exec-test.py`, `exec-peek-test.py` |
| Subagents/background jobs | `main.py`, `tools/job-run.py` | `subagent-test.py`, `jobs-test.py` |
| Continuation | `main.py`, `qml/Root.qml` | `continue-test.py`, `continue-any-test.py`, `cutoff-detect-test.py` |
| Images/video/attachments | `main.py`, QML media rows | `typed-image-test.py`, `typed-video-test.py`, `attachment-art-test.py` |
| Extensible tools/skills/agents | `main.py` | `self-extend-test.py`, `toolbox-test.py` |

Read harness setup before execution: a descriptive filename does not establish
that a test is isolated. Additional focused tests live alongside these; use
those matching the changed seam rather than running every integration test.

## Session shells and text

Verify the active desktop through the root guide. `Root.qml` is an Item shared
by the Hyprland `Main.qml` Window and Plasma's native shell. Keep Window-only
operations in the wrapper; Root publishes `windowTitle`. The actions table
serves Plasma, while `tbButtons` projects it into Hyprland's titlebar; both
call `tbAction(id)`. Hidden selector rows keep zero height so IDs resolve.

Plasma uses right-aligned model/session toolbar pickers, File session actions,
Settings base prompts, and Tools server controls. Confirm session deletion
through the shared modeless `DontUseNativeDialog` pattern, never static
`QMessageBox` helpers.

Keep file-selector variant APIs unchanged. `+oxygen/PromptBox` must select the
native `+plasma` TextArea implementation because Oxygen takes precedence.
Bubble and CapChip use non-interactive native button frames. ViewFrame exposes
native padding. PromptEditor exposes `load(text)`, `saved(text)`, `cancelled()`;
Root owns persistence. Meter and reply pictures retain their content drawing.
Shared CtxMenu/VScroll contracts apply.

The Edit menu and transcript context menu share `textMenu()/runTextRow()`.
`noteSelection` and `selectedBody` identify the editor; disable Edit rows
without a selection. Copy reply selections as Markdown through `Clip`, not
flattened rendered text. Keep source Markdown separate from a TextEdit's
re-serialized `text`; user prompts and errors remain plain text.

The transcript is selectable and append-only during a turn. Auto-follow only
while already at the bottom. Reasoning/tool details are folded by default;
generation progress remains visible. Preserve the think clock across reasoning
and tool waits, and persist elapsed totals rather than running timers.

UI strings call the daemon “server”; technical tool descriptions may say
Ollama. Status left shows activity/results or idle when the server is up;
right shows jobs and server state. `stopReply` clears stale activity text.
With the server down, leave the left resting status empty.

## Unity 12.10 frontend

`unity_engine.py` selects the GTK face only with the Unity desktop token,
`UNITY_QUANTAL_SESSION_DIR`, and the installed Quantal runtime. Explicit
`--face` choices and `--selftest` retain their original routing. Book keeps
its existing faces; Quantal is top-only.

`unity_frontend.py` runs under Quantal's Python 2.7 / GTK 3.6, using the session
Ambiance theme, server decorations and original appmenu exporter. The modern
engine hosts `Root.qml` invisibly on offscreen Qt so turn handling, continuation,
choices, attachments and session saves retain one owner. `unitySnapshot` and
`unitySend` are the JSON/action seam; no second conversation store or tool loop.
The engine owns the backend lease and drains session saves before exit.
The private per-window socket transport is shared with Painter in
`pylib/unityipc.py` and `pylib/unitygtk.py`.

Run `tools/unity-test.sh UNITY_PACKAGE` under this app. It uses private
PID/mount/network namespaces, Xvfb, D-Bus and scratch stores; its inner Python
scripts must never run directly on the host. It verifies the desktop gate,
GTK controls/global-menu export, streaming, attachment submission, cancellation
and session persistence. No live model or desktop interaction is needed.

## Transport, tools, and context

`Ollama` uses asynchronous Qt network/process work. Stream NDJSON incrementally,
retain tool-call/result pairs when fitting or compacting context, and keep the
saved transcript whole. Use the source constants for current budgets; the old
reference includes obsolete round counts and context measurements.

`CORE_TOOL_NAMES` owns initial tool schemas. `tools_note()` advertises the
remaining registry; `get_tools` attaches full schemas for the current turn.
Generation schemas attach early when request routing identifies generation.
A valid directly called indexed tool still runs and self-attaches in
`_run_tool_calls`, not the shared dispatcher; subagent tool sets are separate.

Tool failures use `_tool_done`'s bounded recovery envelope: preserve the original
error, stable kind, retryability, and suggested next actions. Hints do not
execute retries or grant authority. `describe_self` derives available/attached
tools and host facts from runtime state rather than a remembered inventory.
Keep grounding and capability claims consistent with actual results.
API credentials from the keyring must pass through `_api_safe_url` and
`API_SECRET_PARAMS` redaction before URLs reach the model, persisted sessions,
or UI disclosure. Those transcripts sync privately; never include secrets.

At a tool/context limit, complete pending calls and make the one-shot wrap-up
request without tools. Reset that state for a new send or continuation.
Continuation appends to the correct assistant row and carries complete tool
edges; truncation requires evidence, not merely a heading/list-shaped ending.
Automatic continuation is bounded and must never treat a question or request
for permission as approval. Stop exhausts its current continuation budget.

`_prior` tool memory is RAM-only. Match raw user prompts when carrying turns,
exclude synthetic continuation instructions, and fall back to saved text when a
session changes or restarts. Persist media paths/dimensions even in wordless
media rows. House-rule discovery returns the nearest `AGENTS.md` path once per
conversation; do not scan `/` or `/nix/store` for it.

## Host routing and persistence

The Chatter window's host and the inference server's host are distinct.
`TOOLS_HOST` defaults to `LOCAL_HOST`; `ORACLE_TOOLS_HOST` can select top/book.
File tools accept an explicit host for reads and mutations. Code runners,
background jobs, and player operations follow their actual target host.
Custom tool manifests may explicitly route to top/book. Never infer file or
player location from an Ollama tunnel.

Compute/generation and shared session/memory stores have separate routing.
Overrides such as `ORACLE_MEMORY` and `ORACLE_SESSIONS` mark local disposable
stores through `STORE_LOCAL`; preserve that seam in tests. Generation uses
Painter's actual workflow/settings path; keep input staging, argv routing, and
result display in agreement. Show an existing local file regardless of which
host generated it.

Sessions are transcripts; memories are durable user facts. A memory save
requires `source_quote` to occur verbatim in the current user prompt. Do not
turn inferred preferences, tool summaries, or mutable machine/library scans
into personal facts. Legacy memories remain marked unverified. Bound automatic
recall and keep atomic store writes.

The file helpers' “sandbox” names do not imply restricted defaults: read/write
roots default to `/`, and `SANDBOX_ROOT` is scratch space. Environment overrides
can restrict the roots. Tool descriptions must reflect the actual roots;
resolve real paths, apply containment checks, never follow directory symlinks
while walking, and cap/paginate results. Attachment staging obeys the write
root. These app capabilities do not authorize an agent to touch the user's
files or desktop during verification.

Self-created tools/skills/agents live in the user's private Oracle stores;
follow the root guide's source/sync ownership rules. A rendered result must
represent actual tool evidence, including failures and unavailable media.

## Verification

Use `oracle-qtenv` to obtain the packaged Qt environment; never launch the live
app as a smoke test. Use scratch HOME/XDG/config/session/memory roots and a
stub or closed endpoint. Explicitly select offscreen Qt, remove inherited
display/compositor sockets, and apply the root/shared guard rules. Stub network,
SSH, warden, filesystem writes, clipboard, media, notifications, and desktop
control before any path that can call them.

`main.py --selftest` supports `ORACLE_CHROME`, `ORACLE_FACES`, `ORACLE_POKE`,
`ORACLE_SELECT`, `ORACLE_MENU`, `ORACLE_FAKE`, and `ORACLE_SHOT` for isolated
inspection. Settings actions persist: `ORACLE_CONFIG` and `ORACLE_SESSIONS`
must be scratch stores. Read the selftest entry point before use; offscreen Qt
alone does not isolate services or persistent state.

`tools/resource-fixture.py --state blank|fake|clear --seconds N` forces offscreen,
isolates writable stores, and uses a closed local server port. Clear exercises
session-load cleanup after fake content. Keep this seam free of live services.

`home/prog/oracle.nix` packages the live-source wrapper for both hosts. Python
and QML edits apply on a later user launch; dependency/packaging changes require
the matching host rebuild. Do not relaunch the user's Chatter for verification.

`tools/qwen38-ollama-shim.py` is an exception to live app source:
`sys/ai/ollama.nix` embeds it with `builtins.readFile`, so shim changes require
a top system rebuild. Keep it under the existing Ollama service lifecycle,
tunnel, and warden contract; use `tools/qwen38-ollama-shim-test.py` with stub
backends for verification, never the user's active inference service.
