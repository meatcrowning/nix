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


def main() -> int:
    config = os.environ["PLAYER_VISUALIZER_CAVA_CONFIG"]
    target = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
                          "player-visualizer.json")
    cava = subprocess.Popen([os.environ["CAVA"], "-p", config],
                            stdout=subprocess.PIPE, text=True, bufsize=1)
    assert cava.stdout is not None
    try:
        for line in cava.stdout:
            levels = [min(100, max(0, int(v or 0)))
                      for v in line.strip().split(";") if v != ""]
            if not levels:
                continue
            fd, tmp = tempfile.mkstemp(prefix="player-visualizer.",
                                       dir=os.path.dirname(target))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"levels": levels}, f, separators=(",", ":"))
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, target)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
    finally:
        cava.terminate()
        cava.wait(timeout=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
