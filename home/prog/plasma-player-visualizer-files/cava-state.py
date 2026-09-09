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


def easyeffects_sink_exists(pw_dump: str) -> bool:
    try:
        objects = json.loads(pw_dump)
    except json.JSONDecodeError:
        return False
    return any(obj.get("info", {}).get("props", {}).get("node.name")
               == "easyeffects_sink" for obj in objects)


def pre_effects_config(source: str, runtime_dir: str) -> str:
    with open(source, encoding="utf-8") as f:
        config = f.read()
    config = config.replace("source = auto",
                            "source = easyeffects_sink.monitor", 1)
    target = os.path.join(runtime_dir, "player-visualizer-cava.conf")
    fd, tmp = tempfile.mkstemp(prefix="player-visualizer-cava.",
                               dir=runtime_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(config)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return target


def write_levels(target: str, levels: list[int]) -> None:
    fd, tmp = tempfile.mkstemp(prefix="player-visualizer.",
                               dir=os.path.dirname(target))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"levels": levels}, f, separators=(",", ":"))
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
        return (state.get("view") == "now"
                and time.time() - float(state.get("updated", 0)) < 3)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def main() -> int:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    target = os.path.join(runtime_dir,
                          "player-visualizer.json")
    player_target = os.path.join(runtime_dir,
                                 "player-visualizer-player.json")
    while True:
        dump = subprocess.run([os.environ["PW_DUMP"]], capture_output=True,
                              text=True, check=False)
        if dump.returncode == 0 and easyeffects_sink_exists(dump.stdout):
            break
        time.sleep(0.25)
    config = pre_effects_config(
        os.environ["PLAYER_VISUALIZER_CAVA_CONFIG"], runtime_dir)
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
            write_levels(target, [] if player_owns_visualizer(runtime_dir)
                         else levels)
    finally:
        cava.terminate()
        cava.wait(timeout=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
