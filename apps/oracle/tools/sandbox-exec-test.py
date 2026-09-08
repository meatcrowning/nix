#!/usr/bin/env python3
"""Focused contract check for chatter's shared Python/Bash runner limits."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
RUNNER = HERE / "sandbox-exec.py"
EXPECTED_FSIZE = 16 * 1024 * 1024 * 1024


def run(root, code, lang="python"):
    proc = subprocess.run(
        [sys.executable, str(RUNNER), str(root)],
        input=json.dumps({"code": code, "lang": lang, "timeout": 5}),
        text=True, capture_output=True, timeout=10, check=True)
    return json.loads(proc.stdout.strip().splitlines()[-1])


with tempfile.TemporaryDirectory(prefix="chatter-exec-test-") as scratch:
    root = Path(scratch)
    py = run(root, """
import json, resource
with open('over-old-cap.bin', 'wb') as f:
    f.truncate(17 * 1024 * 1024)
print(json.dumps({'fsize': resource.getrlimit(resource.RLIMIT_FSIZE)[0],
                  'size': __import__('os').path.getsize('over-old-cap.bin')}))
""")
    assert py["ok"] and py["exit_code"] == 0, py
    measured = json.loads(py["stdout"])
    assert measured == {"fsize": EXPECTED_FSIZE, "size": 17 * 1024 * 1024}, measured

    sh = run(root, "ulimit -f", "bash")
    assert sh["ok"] and sh["exit_code"] == 0, sh
    assert int(sh["stdout"].strip()) * 1024 == EXPECTED_FSIZE, sh

print("sandbox exec: python and bash inherit a 16 GiB per-file limit")
