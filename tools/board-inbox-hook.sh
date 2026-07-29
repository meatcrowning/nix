#!/bin/sh
# board-inbox-hook.sh — PostToolUse hook: deliver board inbox notes to the
# agent MID-FLIGHT, mechanically, instead of trusting the model to remember
# `boardctl.py inbox take` between steps (workers forgot, and notes died
# unread or died with the worker — one of his handed-over asks was lost
# exactly that way on 2026-07-29).
#
# Wired in ~/.claude/settings.json (PostToolUse, all tools), which syncs to
# BOTH machines — so this file is addressed by its repo path and stays
# host-neutral. It runs after EVERY tool call of EVERY session, so the idle
# path must cost nearly nothing:
#   * not a board agent (no BOARD_AGENT_ID)      -> exit, no fork
#   * board agent, empty inbox (pure-shell glob) -> exit, no python
# Only when a note is actually waiting does python start: `inbox take` moves
# the notes to taken/ (same conservation as always — taking here is no more
# lossy than the prompt-driven take it replaces, and reap() now requeues a
# dead worker's taken notes), and the JSON on stdout hands the text to the
# model as additional context.
#
# Never exits nonzero and never blocks: a broken inbox must not break tools.
[ -n "${BOARD_AGENT_ID:-}" ] || exit 0

# Mirror boardagents.clean_id: lowercase, [^a-z0-9._-] -> "-", strip "-".
aid=$(printf '%s' "$BOARD_AGENT_ID" | tr 'A-Z' 'a-z' \
      | sed 's/[^a-z0-9._-]\{1,\}/-/g; s/^-*//; s/-*$//')
[ -n "$aid" ] || exit 0

d="${XDG_STATE_HOME:-$HOME/.local/state}/board/inbox/to/$aid"
set -- "$d"/*.json
[ -e "$1" ] || exit 0

out=$(python3 /home/lam/nix/apps/board/tools/boardctl.py inbox take --quiet 2>/dev/null) || exit 0
[ -n "$out" ] || exit 0

# json.dumps does the escaping; a note containing quotes or newlines must not
# be able to break the hook protocol.
printf '%s' "$out" | python3 -c '
import json, sys
notes = sys.stdin.read().strip()
if notes:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext":
            "from his board inbox (this outranks your prompt):\n" + notes}}))
'
exit 0
