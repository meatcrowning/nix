#!/usr/bin/env python3
"""Hermetic scale benchmark for chatter's session-picker listing.

Builds disposable transcript stores, calls the real ``op_list`` directly, and
prints medians.  It never reads the user's session store or starts Qt.
"""
import importlib.util
import json
import statistics
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "oracle_sessions_store", HERE / "sessions-store.py")
STORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STORE)


def populate(root, count, turns, body_chars):
    body = "x" * body_chars
    for i in range(count):
        rows = [{"role": "user", "body": body},
                {"role": "assistant", "body": body}] * (turns // 2)
        obj = {"id": f"sess-{i}", "title": f"session {i}",
               "created": i, "updated": i, "turns": rows}
        (root / f"sess-{i}.json").write_text(json.dumps(obj), encoding="utf-8")


def median_ms(root, repeats=7):
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        STORE.op_list(str(root))
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples)


def main():
    cases = ((50, 20, 300), (250, 40, 500), (1000, 40, 500))
    with tempfile.TemporaryDirectory(prefix="chatter-session-bench-") as tmp:
        base = Path(tmp)
        for count, turns, body_chars in cases:
            root = base / str(count)
            root.mkdir()
            populate(root, count, turns, body_chars)
            total_mb = sum(p.stat().st_size for p in root.iterdir()) / 1_000_000
            print(f"{count:4d} sessions  {total_mb:7.1f} MB  "
                  f"{median_ms(root):8.2f} ms")


if __name__ == "__main__":
    main()
