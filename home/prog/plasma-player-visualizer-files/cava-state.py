#!/usr/bin/env python3
"""Publish Cava's raw spectrum for the Plasma player visualizer.

The state file lives in XDG_RUNTIME_DIR, not on disk: the decoration and the
panel repaint from the same frame without turning a 60 Hz meter into writes to
the SSD.  Cava remains the sole analyser; consumers only read this tiny JSON
snapshot.
"""
import json
import os
import subprocess
import sys
import tempfile
import time


def write_levels(target: str, levels: list[int]) -> None:
    fd, tmp = tempfile.mkstemp(prefix="player-visualizer.",
                               dir=os.path.dirname(target))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"levels": levels, "updated": time.time()}, f,
                      separators=(",", ":"))
            f.flush()
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def player_owns_visualizer(runtime_dir: str) -> bool:
    try:
        with open(os.path.join(runtime_dir, "player-view.json"),
                  encoding="utf-8") as f:
            state = json.load(f)
        return (state.get("view") in ("now", "visualizer")
                and time.time() - float(state.get("updated", 0)) < 3)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def main() -> int:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    target = os.path.join(runtime_dir,
                          "player-visualizer.json")
    player_target = os.path.join(runtime_dir,
                                 "player-visualizer-player.json")
    panel_target = os.path.join(runtime_dir, "player-visualizer-panel.json")
    config = os.environ["PLAYER_VISUALIZER_CAVA_CONFIG"]
    cava = subprocess.Popen([os.environ["CAVA"], "-p", config],
                            stdout=subprocess.PIPE, text=True, bufsize=1)
    assert cava.stdout is not None
    try:
        for line in cava.stdout:
            levels = [min(100, max(0, int(v or 0)))
                      for v in line.strip().split(";") if v != ""]
            if not levels:
                continue
            write_levels(player_target, levels)
            write_levels(panel_target, levels)
            write_levels(target, [] if player_owns_visualizer(runtime_dir)
                         else levels)
    finally:
        write_levels(panel_target, [])
        cava.terminate()
        cava.wait(timeout=2)
    # EOF is unexpected for this continuous producer; let systemd restart it.
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
