#!/usr/bin/env python3
"""nix-intent-add-hook.py — PostToolUse(Write) hook: `git add -N` a NEW file
under ~/nix the moment it is created, mechanically.

Flake eval reads the working tree but does NOT see an untracked file, so a new
`.nix`/`.qml` that nobody intent-added is silently missing from the build —
the rebuild "succeeds" and the panel throws `ReferenceError` at runtime. That
rule lived in prompts and in preflight's warning; this closes it at the point
of creation, for every session and every agent, remembering nothing.

Wired in ~/.claude/settings.json (matcher "Write", async), which syncs to both
machines — repo-absolute path, host-neutral text. `git -C <dir> rev-parse
--show-toplevel` finds the OWNING repo, so a file under docs/ (its own private
repo inside this checkout) is intent-added there, not in ~/nix. `add -N`
itself refuses gitignored paths, which is the correct no-op.

Always exits 0 and prints nothing: a hook that can break the Write tool is
worse than the bug it prevents. Intent-to-add stages NO content, so another
agent's pathspec-less commit cannot swallow the file — the same argument as
preflight's.
"""
import json
import os
import subprocess
import sys

REPO = "/home/lam/nix"


def main():
    try:
        d = json.load(sys.stdin)
    except Exception:
        return
    path = ((d.get("tool_input") or {}).get("file_path")) or ""
    if not path.startswith(REPO + os.sep) or not os.path.isfile(path):
        return
    try:
        top = subprocess.run(
            ["git", "-C", os.path.dirname(path), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5).stdout.strip()
        if not top.startswith(REPO):
            return
        tracked = subprocess.run(
            ["git", "-C", top, "ls-files", "--error-unmatch", "--", path],
            capture_output=True, timeout=5).returncode == 0
        if not tracked:
            subprocess.run(["git", "-C", top, "add", "-N", "--", path],
                           capture_output=True, timeout=5)
    except Exception:
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
