#!/usr/bin/env python3
"""Pure check that updater workload commands are captured, never executed."""

import importlib.util
import os
from pathlib import Path
import tempfile

with tempfile.TemporaryDirectory(prefix="updater-isolation-") as tmp:
    root = Path(tmp)
    fake = root / "fake-runner"
    os.environ["NIX_UPGRADABLE_REPO"] = str(root / "flake")
    os.environ["UPDATER_COMMAND_RUNNER"] = str(fake)
    os.environ["XDG_STATE_HOME"] = str(root / "state")
    app = Path(__file__).resolve().parent.parent / "main.py"
    spec = importlib.util.spec_from_file_location("updater_main", app)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.REPO == root / "flake"
    assert mod.isolated_step(["nix", "flake", "update", "nixpkgs"]) == [
        str(fake), "nix", "flake", "update", "nixpkgs"]
    assert mod.isolated_step(mod.rebuild_cmd())[0] == str(fake)
print("updater isolation: commands captured")
