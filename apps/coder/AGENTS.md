# coder — Claude Code and Codex front end

Read [the shared app guide](../AGENTS.md) first. The private
[plan](../../docs/agents/coder-plan.md) owns scope, phases and the feature
survey; this guide owns the current contracts.

## Owners and harnesses

| Area | Owner | Harness |
| --- | --- | --- |
| Event vocabulary | `proto.py` | `tools/protocol-test.py` |
| Claude stream-json control protocol | `claude_proto.py` | `tools/protocol-test.py` |
| Codex app-server JSON-RPC | `codex_proto.py` | `tools/protocol-test.py` |
| Claude session store (read-only) | `history.py` | `tools/protocol-test.py` |
| Fixture replay | `fake.py`, `fixtures/` | both harnesses |
| Processes, models, app state | `session.py` | `tools/ui-test.sh` |
| Window, chrome, selftest | `main.py`, `qml/` | `tools/ui-test.sh` |

`protocol-test.py` is Qt-free. `ui-test.sh` renders both faces offscreen under
a private `dbus-run-session`, with scratch state and fixture CLIs. On book the
KDE platform theme segfaults building a menubar offscreen against the live
bus, and Fedora's Qt aborts on the Nix plugin paths a Konsole shell exports.
The harness and the book launcher both clear those paths.

## Backends

The app runs the real CLIs and never writes their config, hooks, skills or
session stores. Claude runs as one `claude -p` per live session, with
`--permission-prompt-tool stdio`. Without that flag, prompts are auto-denied
and never reach the host. Codex runs as one private `codex app-server` per
window. Never connect to, start, stop or update the CLI's managed background
daemon.

Protocol names come from the installed CLIs: recorded fixtures for Claude,
and `codex app-server generate-json-schema` for Codex. Unknown messages are
ignored. Unknown host or server requests get an error reply, so a CLI never
waits on Coder. Approval answers update state before the reply is written,
because the reply can finish the turn at once (the replayer finishes it
synchronously).

Model text is untrusted. Markdown goes through `session.md_safe()`, which
defuses raw HTML and remote images outside code. Everything else renders as
plain text.

## Fixtures

`tools/record-fixture.py` runs a real CLI. It spends usage and creates a
session in the CLI's store, so run it by hand only, in a scratch git repo.
It scrubs paths, identity, skill and command lists, hook output, signatures
and partial tool-input deltas, because this repository is public. Read a new
fixture before committing it. `codex-synthetic.jsonl` was written from the
0.166.0 schema; replace it with a real recording when one is possible.

## Verification

Never launch the app on the real screen or relaunch the user's copy. Never run
a model turn from a harness. `CODER_FIXTURES`, `CODER_STATE`,
`CODER_CLAUDE_PROJECTS` and `CODER_NO_NOTIFY` isolate a run. `--selftest`
refuses any platform but offscreen. Python/QML edits apply on the next launch.
Packaging changes need the host rebuild.
