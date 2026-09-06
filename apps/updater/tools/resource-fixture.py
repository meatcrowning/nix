#!/usr/bin/env python3
"""Retain real updater states over a synthetic flake, offscreen only."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def lock_document(names):
    nodes = {"root": {"inputs": {name: name for name in names}}}
    for n, name in enumerate(names):
        nodes[name] = {"locked": {
            "lastModified": 1700000000 + n,
            "narHash": "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            "rev": f"{n:040x}", "type": "github",
            "owner": "synthetic", "repo": name,
        }}
    return {"nodes": nodes, "root": "root", "version": 7}


def main():
    repo = Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory(prefix="updater-resource-") as tmp:
        root = Path(tmp)
        flake = root / "flake"
        flake.mkdir()
        (flake / "tools").mkdir()
        # Runner never executes these placeholders; their paths merely exercise
        # the same argv construction as the live app.
        (flake / "tools" / "nix-upgradable.sh").write_text("fixture\n")
        normal_lock = root / "normal.lock"
        stress_lock = root / "stress.lock"
        normal_lock.write_text(json.dumps(lock_document([
            "hyprland", "nixpkgs", "nixpkgs-quickshell", "systems"])))
        stress_lock.write_text(json.dumps(lock_document(
            ["hyprland", "hyprland-air", "nixpkgs-quickshell"]
            + [f"input-{n:03d}" for n in range(420)])))
        (flake / "flake.lock").write_bytes(normal_lock.read_bytes())
        for name in ("state", "config", "cache", "runtime", "home"):
            (root / name).mkdir(mode=0o700 if name == "runtime" else 0o755)

        env = os.environ.copy()
        env.update({
            "QT_QPA_PLATFORM": "offscreen",
            "UPDATER_RESOURCE_FIXTURE": "1",
            "NIX_UPGRADABLE_REPO": str(flake),
            "UPDATER_COMMAND_RUNNER": str(
                repo / "apps/updater/tools/fake-command-runner.py"),
            "UPDATER_FAKE_RUNNER_STATE": str(root / "runner-state.json"),
            "UPDATER_RESOURCE_NORMAL_LOCK": str(normal_lock),
            "UPDATER_RESOURCE_STRESS_LOCK": str(stress_lock),
            "XDG_STATE_HOME": str(root / "state"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_CACHE_HOME": str(root / "cache"),
            "XDG_RUNTIME_DIR": str(root / "runtime"),
            "HOME": str(root / "home"),
            "DESK_SESSION": "hypr",
        })
        for key in ("WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE"):
            env.pop(key, None)
        if Path(sys.executable).resolve() == Path("/usr/bin/python3").resolve():
            for key in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "QML_IMPORT_PATH"):
                env.pop(key, None)
            env["QT_QPA_PLATFORMTHEME"] = ""
            env["QT_STYLE_OVERRIDE"] = ""
        subprocess.run([
            "bash", "-c",
            f'. "{repo}/tools/lib/session-guard.sh"; sg_require_offscreen',
        ], check=True, env=env)
        return subprocess.call(
            [sys.executable, str(repo / "apps/updater/main.py")], env=env)


if __name__ == "__main__":
    raise SystemExit(main())
