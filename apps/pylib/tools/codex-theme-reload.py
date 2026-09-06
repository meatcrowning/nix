#!/usr/bin/env python3
"""Queue a safe Codex TUI restart after the current turn completes.

The supervisor owns the process launched by the desktop entry.  A theme change
writes one generation to its runtime queue.  Once Codex records task_complete,
the supervisor stops that idle TUI and invokes ``codex resume <session-id>`` in
the same terminal.  The session id is read from Codex's own JSONL metadata, so
the restart never falls back to whichever conversation happened to be newest.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Iterable


RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
QUEUE = RUNTIME / "codex-theme-reload" / "generation"
SESSIONS = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"


def queue() -> int:
    """Publish one coalescing refresh generation without touching a TUI."""
    QUEUE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = QUEUE.with_name(f".{QUEUE.name}.{os.getpid()}")
    tmp.write_text(f"{time.time_ns()}\n", encoding="ascii")
    os.replace(tmp, QUEUE)
    return 0


def generation() -> str:
    try:
        return QUEUE.read_text(encoding="ascii").strip()
    except OSError:
        return ""


def jsonl_paths() -> Iterable[Path]:
    if not SESSIONS.is_dir():
        return ()
    return SESSIONS.rglob("*.jsonl")


def session_id(path: Path, cwd: Path) -> str | None:
    """Return this supervisor's newly opened session, never another window's."""
    try:
        with path.open(encoding="utf-8") as source:
            first = json.loads(source.readline())
    except (OSError, ValueError):
        return None
    payload = first.get("payload", {})
    if first.get("type") != "session_meta" or payload.get("cwd") != str(cwd):
        return None
    ident = payload.get("id")
    return ident if isinstance(ident, str) else None


def find_session(cwd: Path, not_before_ns: int) -> tuple[str, Path] | None:
    candidates: list[tuple[int, str, Path]] = []
    for path in jsonl_paths():
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            continue
        if stamp < not_before_ns:
            continue
        ident = session_id(path, cwd)
        if ident:
            candidates.append((stamp, ident, path))
    if not candidates:
        return None
    _stamp, ident, path = max(candidates)
    return ident, path


def turn_complete(path: Path) -> bool:
    """Whether the log's latest turn boundary is a completed turn.

    The tail contains the latest boundary even for long conversations.  A
    malformed/incomplete line means unknown, which deliberately declines a
    restart rather than risking an active turn.
    """
    try:
        with path.open("rb") as source:
            source.seek(0, os.SEEK_END)
            source.seek(max(0, source.tell() - 1_048_576))
            if source.tell():
                source.readline()
            lines = source.readlines()
    except OSError:
        return False
    latest = ""
    for raw in lines:
        try:
            event = json.loads(raw)
        except (UnicodeDecodeError, ValueError):
            continue
        payload = event.get("payload", {})
        if event.get("type") == "event_msg" and payload.get("type") in {"task_started", "task_complete"}:
            latest = payload["type"]
    return latest == "task_complete"


def stop_idle(child: subprocess.Popen[object]) -> bool:
    """Request a normal TUI exit; never kill an active or unresponsive one."""
    child.send_signal(signal.SIGTERM)
    try:
        child.wait(timeout=8)
    except subprocess.TimeoutExpired:
        return False
    return True


def supervise(command: list[str]) -> int:
    cwd = Path.cwd().resolve()
    seen = generation()                 # a change before launch belongs to no TUI
    resume: str | None = None

    while True:
        started = time.time_ns()
        args = command if resume is None else [command[0], "resume", resume]
        child = subprocess.Popen(args)
        tracked: tuple[str, Path] | None = None
        requested = False

        while child.poll() is None:
            if tracked is None:
                tracked = find_session(cwd, started)
            current = generation()
            if current and current != seen:
                requested = True
            if requested and tracked and turn_complete(tracked[1]):
                # Recheck after a short grace period: a just-submitted user
                # prompt always writes task_started, which cancels this reload.
                time.sleep(1)
                if generation() != seen and turn_complete(tracked[1]) and stop_idle(child):
                    seen = generation()
                    resume = tracked[0]
                    break
            time.sleep(0.35)
        else:
            return child.returncode or 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("queue", help="queue one refresh for supervised Codex windows")
    watch = sub.add_parser("supervise", help="run Codex and safely resume it after a queued refresh")
    watch.add_argument("command", nargs=argparse.REMAINDER,
                       help="command to launch (default: codex)")
    args = parser.parse_args()
    if args.action == "queue":
        return queue()
    command = args.command or ["codex"]
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("supervise needs a command")
    return supervise(command)


if __name__ == "__main__":
    raise SystemExit(main())
