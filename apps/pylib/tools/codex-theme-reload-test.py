#!/usr/bin/env python3
"""Hermetic smoke test for codex-theme-reload.py; touches no real Codex state."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


HERE = Path(__file__).resolve().parent
SUPERVISOR = HERE / "codex-theme-reload.py"
SESSION = "11111111-1111-1111-1111-111111111111"


def append(path: Path, kind: str) -> None:
    with path.open("a", encoding="utf-8") as out:
        out.write(json.dumps({"type": "event_msg", "payload": {"type": kind}}) + "\n")
        out.flush()


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sessions = root / "codex" / "sessions" / "today"
        sessions.mkdir(parents=True)
        log = sessions / "rollout.jsonl"
        log.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": SESSION, "cwd": str(root),
            "timestamp": (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat().replace("+00:00", "Z"),
        }}) + "\n")
        fake = root / "fake-codex.py"
        fake.write_text("""#!/usr/bin/env python3
import os, pathlib, signal, sys, time
if sys.argv[1:3] == ['resume', '11111111-1111-1111-1111-111111111111']:
    pathlib.Path(os.environ['FAKE_RESULT']).write_text('resumed')
    raise SystemExit(0)
signal.signal(signal.SIGTERM, lambda *_: raise_exit())
def raise_exit(): raise SystemExit(0)
while True: time.sleep(.1)
""")
        fake.chmod(0o755)
        resumed = root / "resumed"
        env = os.environ | {"CODEX_HOME": str(root / "codex"), "XDG_RUNTIME_DIR": str(root / "run"),
                            "FAKE_RESULT": str(resumed)}
        proc = subprocess.Popen([sys.executable, str(SUPERVISOR), "supervise", "--", str(fake)], cwd=root, env=env)
        try:
            time.sleep(.4)
            subprocess.run([sys.executable, str(SUPERVISOR), "queue"], env=env, check=True)
            append(log, "task_complete")
            proc.wait(timeout=12)
            assert proc.returncode == 0, proc.returncode
            assert resumed.read_text() == "resumed"
        finally:
            proc.kill()
            proc.wait()
    print("PASS codex theme supervisor resumes the exact completed session")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
