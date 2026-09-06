#!/usr/bin/env python3
"""Hermetic benchmark for chatter's repeated prompt/tool payload assembly."""
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))


def median_ms(fn, repeats=21):
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples)


def main():
    with tempfile.TemporaryDirectory(prefix="chatter-turn-bench-") as tmp:
        root = Path(tmp)
        for name in ("tools", "skills", "agents", "sessions", "memory"):
            (root / name).mkdir()
        os.environ.update({
            "ORACLE_CUSTOM_TOOLS": str(root / "tools"),
            "ORACLE_SKILLS": str(root / "skills"),
            "ORACLE_AGENTS": str(root / "agents"),
            "ORACLE_SESSIONS": str(root / "sessions"),
            "ORACLE_MEMORY": str(root / "memory"),
        })
        import main as oracle
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance() or QGuiApplication([])
        chatter = oracle.Ollama()
        history = []
        body = "x" * 1200
        for _ in range(200):
            history += [{"role": "user", "content": body},
                        {"role": "assistant", "content": body}]

        def build_prompt():
            chatter._system_prompt("focused research")

        def build_tools():
            chatter._offered_tools()

        def build_payload():
            past, _ = chatter._fit_history(history, 32768)
            payload = {"model": "stub", "messages": past,
                       "tools": chatter._offered_tools()}
            json.dumps(payload).encode("utf-8")

        print(f"system prompt       {median_ms(build_prompt):8.3f} ms")
        print(f"offered tools       {median_ms(build_tools):8.3f} ms")
        print(f"long-turn payload   {median_ms(build_payload):8.3f} ms")
        del app


if __name__ == "__main__":
    main()
