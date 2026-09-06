#!/usr/bin/env python3
"""Retain real Editor states for sampling, entirely offscreen and scratch."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", type=int, default=24)
    ap.add_argument("--lines", type=int, default=1200)
    args = ap.parse_args()
    repo = Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory(prefix="editor-resource-") as tmp:
        root = Path(tmp)
        docs = root / "docs"
        docs.mkdir()
        paths = []
        for n in range(args.files):
            path = docs / f"fixture_{n:03d}.py"
            path.write_text("".join(f"def value_{i}(): return {i + n}\n"
                                    for i in range(args.lines)))
            paths.append(str(path))
        env = os.environ.copy()
        env.update({
            "QT_QPA_PLATFORM": "offscreen",
            "EDITOR_RESOURCE_FIXTURE": "1",
            "EDITOR_RESOURCE_PATHS": os.pathsep.join(paths),
            "XDG_STATE_HOME": str(root / "state"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_CACHE_HOME": str(root / "cache"),
            "XDG_RUNTIME_DIR": str(root / "runtime"),
            "HOME": str(root / "home"),
        })
        env.pop("WAYLAND_DISPLAY", None)
        env.pop("DISPLAY", None)
        env.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
        # A Nix-launched terminal on book exports top's Qt plugin paths.  They
        # are ABI-incompatible with Fedora's /usr/bin/python3 and make Qt abort
        # before it can select offscreen.  The system interpreter must use its
        # own plugins; top's packaged interpreter keeps its qtenv paths.
        if Path(sys.executable).resolve() == Path("/usr/bin/python3").resolve():
            for key in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "QML_IMPORT_PATH"):
                env.pop(key, None)
            env["QT_QPA_PLATFORMTHEME"] = ""
            env["QT_STYLE_OVERRIDE"] = ""
        (root / "runtime").mkdir(mode=0o700)
        (root / "home").mkdir()
        subprocess.run(["bash", "-c",
                        f'. "{repo}/tools/lib/session-guard.sh"; sg_require_offscreen'],
                       check=True, env=env)
        child = subprocess.Popen(
            [sys.executable, str(repo / "apps/editor/main.py")], env=env)
        rc = child.wait()
        # Popen.wait() plus the absence of helper processes in this no-service
        # fixture is the teardown assertion: the measured tree is gone before
        # TemporaryDirectory removes its private sockets and roots.
        if child.poll() is None:
            raise RuntimeError("editor resource child survived teardown")
        return rc


if __name__ == "__main__":
    main()
