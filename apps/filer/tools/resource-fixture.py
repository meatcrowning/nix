#!/usr/bin/env python3
"""Retain real Filer listing states for sampling, entirely offscreen and scratch."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    repo = Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory(prefix="filer-resource-") as tmp:
        root = Path(tmp); normal = root / "normal"; stress = root / "stress"
        normal.mkdir(); stress.mkdir()
        for n in range(2500):
            (stress / f"file-{n:04d}.txt").write_text((f"fixture {n}\n" * 8))
        env = _scratch_env(root)
        env.update({"FILER_RESOURCE_FIXTURE": "1", "FILER_RESOURCE_NORMAL_DIR": str(normal),
                    "FILER_RESOURCE_STRESS_DIR": str(stress)})
        _guard(repo, env)
        os.execve(sys.executable, [sys.executable, str(repo / "apps/filer/main.py"), str(normal)], env)


def _scratch_env(root):
    env = os.environ.copy()
    env.update({"QT_QPA_PLATFORM": "offscreen", "HOME": str(root / "home"),
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
