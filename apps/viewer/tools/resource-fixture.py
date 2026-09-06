#!/usr/bin/env python3
"""Retain real Viewer pane states for sampling, offscreen on scratch images."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    repo = Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory(prefix="viewer-resource-") as tmp:
        root = Path(tmp)
        images = []
        for n in range(18):
            path = root / f"image-{n:02d}.ppm"
            pixels = bytes((n * 13 % 256, n * 29 % 256, n * 47 % 256)) * (512 * 384)
            path.write_bytes(b"P6\n512 384\n255\n" + pixels)
            images.append(str(path))
        env = _scratch_env(root, "VIEWER_RESOURCE_FIXTURE")
        _guard(repo, env)
        # One path still makes Viewer scan the scratch directory into its flip
        # list; stress can therefore add nine real panes without front-loading
        # their decoded surfaces into the normal state.
        os.execve(sys.executable, [sys.executable, str(repo / "apps/viewer/main.py"),
                                   "--new-window", images[0]], env)


def _scratch_env(root, flag):
    env = os.environ.copy()
    env.update({"QT_QPA_PLATFORM": "offscreen", flag: "1", "HOME": str(root / "home"),
                "XDG_CONFIG_HOME": str(root / "config"), "XDG_STATE_HOME": str(root / "state"),
                "XDG_CACHE_HOME": str(root / "cache"), "XDG_RUNTIME_DIR": str(root / "runtime")})
    for key in ("WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE",
                "QT_PLUGIN_PATH", "QT_QPA_PLATFORMTHEME", "QT_STYLE_OVERRIDE"):
        env.pop(key, None)
    (root / "home").mkdir(); (root / "runtime").mkdir(mode=0o700)
    return env


def _guard(repo, env):
    subprocess.run(["bash", "-c", f'. "{repo}/tools/lib/session-guard.sh"; sg_require_offscreen'],
                   check=True, env=env)


if __name__ == "__main__": main()
