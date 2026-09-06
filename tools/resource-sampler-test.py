#!/usr/bin/env python3
"""Focused, seat-free tests for resource-sampler.py."""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

TOOL = pathlib.Path(__file__).with_name("resource-sampler.py")


def run(*args: str) -> dict:
    return json.loads(subprocess.check_output([sys.executable, str(TOOL), *args], text=True))


def smaps(pid: int) -> dict[str, int]:
    result = {}
    for line in pathlib.Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
        key, separator, value = line.partition(":")
        if separator and value.strip().split()[0].isdigit():
            result[key] = int(value.strip().split()[0])
    return result


def main() -> int:
    # A private child gives tree discovery a stable, harmless target.  It opens
    # no display and inherits no desktop-facing work beyond this test process.
    # Use the tiny native sleep binary so starting another Python interpreter
    # cannot change this target's proportional share of Python's mapped pages.
    child = subprocess.Popen([shutil.which("sleep") or "/bin/sleep", "30"])
    try:
        time.sleep(0.05)
        document = run("--pid", str(os.getpid()))
        sample = document["samples"][0]
        by_pid = {process["pid"]: process for process in sample["processes"]}
        assert os.getpid() in by_pid, "root PID missing"
        assert child.pid in by_pid, "child PID missing"

        # Single-process mode must reproduce the kernel rollup exactly enough
        # to catch accidental RSS/PSS parsing or unit conversion.  Concurrent
        # allocations can move values slightly between the two read instants.
        kernel = smaps(child.pid)
        alone = run("--pid", str(child.pid), "--no-descendants")["samples"][0]
        measured = alone["processes"][0]["memory_kib"]
        for key in ("Rss", "Pss", "Private_Clean", "Private_Dirty", "Swap"):
            assert abs(measured[key] - kernel[key]) <= 256, (key, measured[key], kernel[key])
            assert alone["totals_memory_kib"][key] == measured[key]

        lines = subprocess.check_output(
            [sys.executable, str(TOOL), "--pid", str(child.pid), "--count", "2", "--interval", "0", "--json-lines"],
            text=True,
        ).splitlines()
        assert len(lines) == 2 and all(json.loads(line)["process_count"] == 1 for line in lines)

        unified = next(
            (line.split(":", 2)[2] for line in pathlib.Path("/proc/self/cgroup").read_text().splitlines() if line.startswith("0::")),
            None,
        )
        if unified is not None:
            group = run("--cgroup", unified, "--no-descendants")["samples"][0]
            assert os.getpid() in {process["pid"] for process in group["processes"]}, "cgroup member missing"
        print("ok: process tree, cgroup, smaps_rollup parity, totals, and JSON Lines")
        return 0
    finally:
        child.terminate()
        child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
