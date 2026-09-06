#!/usr/bin/env python3
"""Read-only Linux process-tree resource sampler.

Memory values come from /proc/PID/smaps_rollup and are reported in KiB.  The
tool never signals, attaches to, or otherwise changes a sampled process.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
from collections import defaultdict, deque
from typing import Any


PROC = pathlib.Path("/proc")
CGROUP = pathlib.Path("/sys/fs/cgroup")


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def proc_stat(pid: int) -> dict[str, int | str]:
    raw = (PROC / str(pid) / "stat").read_text()
    # comm can contain spaces and parentheses; the final ')' precedes state.
    end = raw.rfind(")")
    if end < 0:
        raise ValueError("malformed stat")
    comm = raw[raw.find("(") + 1 : end]
    fields = raw[end + 2 :].split()
    return {
        "comm": comm,
        "ppid": int(fields[1]),
        "minor_faults": int(fields[7]),
        "major_faults": int(fields[9]),
        "user_ticks": int(fields[11]),
        "system_ticks": int(fields[12]),
        "threads": int(fields[17]),
        "start_ticks": int(fields[19]),
    }


def process_table() -> dict[int, dict[str, int | str]]:
    table = {}
    for entry in PROC.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            table[pid] = proc_stat(pid)
        except (FileNotFoundError, PermissionError, ProcessLookupError, ValueError):
            pass
    return table


def descendants(roots: set[int], table: dict[int, dict[str, int | str]]) -> set[int]:
    children: dict[int, list[int]] = defaultdict(list)
    for pid, stat in table.items():
        children[int(stat["ppid"])].append(pid)
    found = set(roots)
    queue = deque(roots)
    while queue:
        for child in children.get(queue.popleft(), ()):
            if child not in found:
                found.add(child)
                queue.append(child)
    return found


def cgroup_pids(value: str) -> set[int]:
    requested = pathlib.Path(value)
    # /proc/PID/cgroup reports paths beginning with '/', but those paths are
    # relative to the cgroup mount.  Also accept a full /sys/fs/cgroup path.
    root = requested if str(requested).startswith(str(CGROUP) + "/") else CGROUP / value.lstrip("/")
    try:
        root = root.resolve(strict=True)
        cgroup_root = CGROUP.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError(f"cgroup does not exist: {value}") from exc
    if root != cgroup_root and cgroup_root not in root.parents:
        raise ValueError("cgroup must be beneath /sys/fs/cgroup")
    if not root.is_dir():
        raise ValueError(f"cgroup is not a directory: {value}")

    result: set[int] = set()
    files = list(root.rglob("cgroup.procs"))
    # cgroup v1 controllers expose tasks rather than cgroup.procs in places.
    if not files:
        files = list(root.rglob("tasks"))
    for filename in files:
        try:
            result.update(int(line) for line in filename.read_text().splitlines())
        except (FileNotFoundError, PermissionError, ValueError):
            continue
    return result


def key_values(filename: pathlib.Path) -> dict[str, int]:
    values = {}
    for line in filename.read_text().splitlines():
        key, separator, rest = line.partition(":")
        if not separator:
            continue
        token = rest.strip().split()
        if token and token[0].isdigit():
            values[key] = int(token[0])
    return values


def sample_process(pid: int, stat: dict[str, int | str]) -> dict[str, Any]:
    base = PROC / str(pid)
    memory = key_values(base / "smaps_rollup")
    status = key_values(base / "status")
    try:
        io = key_values(base / "io")
    except PermissionError:
        io = {}
    try:
        cmdline = (base / "cmdline").read_bytes().rstrip(b"\0").replace(b"\0", b" ").decode(
            errors="replace"
        )
    except PermissionError:
        cmdline = ""
    try:
        fd_count = sum(1 for _ in (base / "fd").iterdir())
    except PermissionError:
        fd_count = None
    return {
        "pid": pid,
        "ppid": stat["ppid"],
        "comm": stat["comm"],
        "cmdline": cmdline,
        "memory_kib": {
            key: memory.get(key, 0)
            for key in ("Rss", "Pss", "Pss_Anon", "Pss_File", "Pss_Shmem", "Private_Clean", "Private_Dirty", "Swap", "SwapPss")
        },
        "cpu": {key: stat[key] for key in ("user_ticks", "system_ticks", "start_ticks")},
        "minor_faults": stat["minor_faults"],
        "major_faults": stat["major_faults"],
        "threads": stat["threads"],
        "voluntary_context_switches": status.get("voluntary_ctxt_switches"),
        "nonvoluntary_context_switches": status.get("nonvoluntary_ctxt_switches"),
        "read_bytes": io.get("read_bytes"),
        "write_bytes": io.get("write_bytes"),
        "fd_count": fd_count,
    }


def one_sample(args: argparse.Namespace) -> dict[str, Any]:
    table = process_table()
    selected: set[int] = set(args.pid)
    if args.cgroup:
        selected.update(cgroup_pids(args.cgroup))
    if args.descendants:
        selected = descendants(selected, table)

    processes, skipped = [], []
    for pid in sorted(selected):
        try:
            processes.append(sample_process(pid, table[pid]))
        except (KeyError, FileNotFoundError, PermissionError, ProcessLookupError, ValueError) as exc:
            skipped.append({"pid": pid, "reason": type(exc).__name__})

    memory_keys = next((p["memory_kib"].keys() for p in processes), ())
    totals = {key: sum(p["memory_kib"][key] for p in processes) for key in memory_keys}
    return {
        "timestamp_unix_ns": time.time_ns(),
        "clock_ticks_per_second": os.sysconf("SC_CLK_TCK"),
        "page_size_bytes": os.sysconf("SC_PAGE_SIZE"),
        "requested_pids": args.pid,
        "cgroup": args.cgroup,
        "include_descendants": args.descendants,
        "process_count": len(processes),
        "totals_memory_kib": totals,
        "processes": processes,
        "skipped": skipped,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--pid", action="append", type=positive_int, default=[], help="root PID (repeatable)")
    result.add_argument("--cgroup", help="cgroup path below /sys/fs/cgroup, recursively sampled")
    result.add_argument("--no-descendants", dest="descendants", action="store_false", help="sample only explicit/cgroup PIDs")
    result.add_argument("--count", type=positive_int, default=1, help="number of snapshots")
    result.add_argument("--interval", type=float, default=1.0, help="seconds between snapshots")
    result.add_argument("--json-lines", action="store_true", help="emit one JSON object per line")
    return result


def main() -> int:
    args = parser().parse_args()
    if not args.pid and not args.cgroup:
        parser().error("at least one --pid or --cgroup is required")
    if args.interval < 0:
        parser().error("--interval cannot be negative")
    try:
        samples = []
        for index in range(args.count):
            sample = one_sample(args)
            if args.json_lines:
                print(json.dumps(sample, separators=(",", ":")), flush=True)
            else:
                samples.append(sample)
            if index + 1 < args.count:
                time.sleep(args.interval)
        if not args.json_lines:
            print(json.dumps({"schema_version": 1, "samples": samples}, indent=2))
    except (OSError, ValueError) as exc:
        print(f"resource-sampler: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
