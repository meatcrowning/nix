#!/usr/bin/env python3
"""Observe an already-running Quickshell process without attaching to it.

This tool never starts, signals, or invokes IPC on Quickshell.  It samples
/proc, including descendants, and reports memory, CPU and the short-lived child
processes it managed to observe.  Child counts are a lower bound: a process
whose whole lifetime falls between samples is necessarily invisible.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time


PROC = Path("/proc")
HZ = os.sysconf("SC_CLK_TCK")


def stat(pid: int) -> dict[str, int | str]:
    raw = (PROC / str(pid) / "stat").read_text()
    end = raw.rfind(")")
    fields = raw[end + 2 :].split()
    return {
        "comm": raw[raw.find("(") + 1 : end],
        "ppid": int(fields[1]),
        "ticks": int(fields[11]) + int(fields[12]),
        "start": int(fields[19]),
    }


def table() -> dict[int, dict[str, int | str]]:
    out = {}
    for entry in PROC.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            out[int(entry.name)] = stat(int(entry.name))
        except (FileNotFoundError, PermissionError, ProcessLookupError, ValueError):
            pass
    return out


def roots(t: dict[int, dict[str, int | str]]) -> list[int]:
    return sorted(pid for pid, row in t.items() if row["comm"] in {"qs", "quickshell"})


def descendants(root: int, t: dict[int, dict[str, int | str]]) -> set[int]:
    found = {root}
    changed = True
    while changed:
        changed = False
        for pid, row in t.items():
            if int(row["ppid"]) in found and pid not in found:
                found.add(pid)
                changed = True
    return found


def key_values(path: Path) -> dict[str, int]:
    out = {}
    for line in path.read_text().splitlines():
        key, sep, value = line.partition(":")
        words = value.strip().split()
        if sep and words and words[0].isdigit():
            out[key] = int(words[0])
    return out


def memory(pid: int) -> tuple[int, int]:
    values = key_values(PROC / str(pid) / "smaps_rollup")
    return values.get("Pss", 0), values.get("Rss", 0)


def cmdline(pid: int) -> str:
    return (PROC / str(pid) / "cmdline").read_bytes().rstrip(b"\0").replace(b"\0", b" ").decode(errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=0.05)
    args = parser.parse_args()
    if args.seconds <= 0 or args.interval <= 0:
        parser.error("--seconds and --interval must be positive")

    initial = table()
    found = roots(initial)
    if len(found) != 1:
        parser.error(f"expected exactly one running qs/quickshell process; found {found}")
    root = found[0]
    root_start = int(initial[root]["start"])
    begun = time.monotonic()
    first_ticks = int(initial[root]["ticks"])
    last_ticks = first_ticks
    memory_samples = []
    children: dict[tuple[int, int], str] = {}
    scans = 0

    while time.monotonic() - begun < args.seconds:
        t = table()
        if root not in t or int(t[root]["start"]) != root_start:
            parser.error("Quickshell exited or restarted during the observation")
        last_ticks = int(t[root]["ticks"])
        for pid in descendants(root, t) - {root}:
            identity = (pid, int(t[pid]["start"]))
            if identity not in children:
                try:
                    children[identity] = cmdline(pid)
                except (FileNotFoundError, PermissionError, ProcessLookupError):
                    children[identity] = str(t[pid]["comm"])
        # smaps_rollup is substantially dearer than stat; sample it at 1 Hz.
        if scans % max(1, round(1.0 / args.interval)) == 0:
            try:
                pss, rss = memory(root)
                memory_samples.append({"elapsed_s": round(time.monotonic() - begun, 3), "pss_kib": pss, "rss_kib": rss})
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                pass
        scans += 1
        time.sleep(args.interval)

    elapsed = time.monotonic() - begun
    print(json.dumps({
        "pid": root,
        "elapsed_s": round(elapsed, 3),
        "scan_interval_s": args.interval,
        "qs_cpu_percent_one_core": round((last_ticks - first_ticks) / HZ / elapsed * 100, 3),
        "memory_samples": memory_samples,
        "observed_child_count_lower_bound": len(children),
        "observed_children": [
            {"pid": pid, "start_ticks": start, "cmdline": command}
            for (pid, start), command in sorted(children.items(), key=lambda item: item[0][1])
        ],
        "limitations": "children shorter-lived than the scan interval can be missed; exited-child CPU is not attributed",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
