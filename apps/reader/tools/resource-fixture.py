#!/usr/bin/env python3
"""Retain real Reader document states for sampling, offscreen on scratch Markdown."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    repo = Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory(prefix="reader-resource-") as tmp:
        root = Path(tmp); docs = root / "docs"; docs.mkdir()
        normal = docs / "normal.md"; stress = docs / "stress.md"
        normal.write_text("# fixture\n\nsmall retained document\n")
        stress.write_text("".join(f"## section {n}\n\nparagraph {n} " + "word " * 80 + "\n\n"
                                  for n in range(1800)))
        env = _scratch_env(root)
        env.update({"READER_RESOURCE_FIXTURE": "1", "READER_RESOURCE_NORMAL_PATH": str(normal),
                    "READER_RESOURCE_STRESS_PATH": str(stress)})
        _guard(repo, env)
        os.execve(sys.executable, [sys.executable, str(repo / "apps/reader/main.py"), str(normal)], env)


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
