#!/usr/bin/env python3
"""Stateful command stand-in used only by updater's offscreen fixture."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def main():
    state_path = Path(os.environ["UPDATER_FAKE_RUNNER_STATE"])
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {"runs": 0, "commands": []}
    command = sys.argv[1:]
    state["runs"] += 1
    state["commands"].append(command)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state), encoding="utf-8")

    print(f"synthetic run {state['runs']}: {' '.join(command)}")
    if "--input" in command:
        name = command[command.index("--input") + 1]
        print("== drv-closure diff")
        for n in range(96):
            print(f"{name}-dependency-{n:03d}: 1.{n} -> 2.{n}, +1 KiB")
    elif any(part.endswith("nix-upgradable.sh") for part in command):
        for n in range(6000):
            print(f"synthetic package {n:04d}: 1.{n} -> 2.{n}")
        print("read-only preview complete")
    elif command[:3] == ["nix", "flake", "update"]:
        print("synthetic lock update complete")
    elif command and command[0] in {"rebuild-air", "sudo"}:
        print("synthetic rebuild complete")
    else:
        print("synthetic command complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
