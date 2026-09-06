#!/usr/bin/env python3
"""Focused safety/state smoke test for resource-fixture.py."""
from pathlib import Path
import subprocess
import sys


RUNNER = Path(__file__).with_name("resource-fixture.py")

for state in ("blank", "fake", "clear"):
    run = subprocess.run(
        [sys.executable, str(RUNNER), "--state", state, "--seconds", "0.05"],
        text=True, capture_output=True, timeout=15,
    )
    output = run.stdout + run.stderr
    rows = 8 if state == "fake" else 0
    wanted = f"resource fixture: ready state={state} rows={rows} pid="
    if run.returncode or wanted not in output or "0 QML warning(s)" not in output:
        raise SystemExit(f"FAIL {state}: rc={run.returncode}\n{output}")
    print(f"PASS {state}")
