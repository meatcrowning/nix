#!/usr/bin/env python3
"""proc-list.py [count]

One line per running process, busiest first:

    pid|name|cpu%|mem%|rss_kb|state|nice|mine

`state` is /proc/pid/stat's single-letter state ('T' is stopped, i.e. suspended),
`nice` its nice value, and `mine` 1 when the process is owned by the user running
this script. All three exist for the row's context menu, which must not offer an
action that would silently do nothing: signalling or renicing somebody else's
process fails with EPERM and `execDetached` has no exit code to notice it with.
Fields are APPENDED, never reordered — Procs.qml indexes them positionally and
tolerates the older five-field shape carried across a panel reload.

CPU% is INSTANTANEOUS — the share of one core's time used between two samples
taken `INTERVAL` apart — not `ps`'s %cpu, which is the average over the whole
lifetime of the process and so reports a long-lived idle daemon as busy forever
and a process that just started spinning as idle. A task manager whose numbers
only converge after an hour is not a task manager, so this pays 0.4s per refresh
to read /proc twice and diff it.

Values are per-core, like top: a process using two cores fully reads 200%.
"""

import os
import sys
import time

INTERVAL = 0.4
CLK_TCK = os.sysconf("SC_CLK_TCK")
PAGE_KB = os.sysconf("SC_PAGE_SIZE") // 1024


def pretty_name(pid, comm):
    """A name worth showing.

    /proc/pid/stat's comm is capped at 15 characters by the kernel, and on NixOS
    almost everything runs through a wrapper, so it reads ".quickshell-wra" /
    ".claude-wrapped" — truncated AND wrong. argv[0] is neither, so prefer it and
    undo the two things the wrapper adds.
    """
    name = comm
    try:
        with open("/proc/" + pid + "/cmdline", "rb") as f:
            argv0 = f.read().split(b"\0")[0].decode("utf-8", "replace")
        if argv0:
            base = os.path.basename(argv0)
            # Chromium/QtWebEngine helpers rewrite their whole command line into
            # argv[0] as one blob (it is how they relabel themselves), so a
            # "name" full of spaces or hundreds of characters long means argv[0]
            # is not a program name at all — fall back to comm.
            if base and " " not in base and len(base) <= 24:
                name = base
    except OSError:
        pass
    if name.startswith("."):
        name = name[1:]
    if name.endswith("-wrapped"):
        name = name[:-len("-wrapped")]
    return name.replace("|", "/")   # '|' is the field separator


def sample():
    """{pid: (ticks, comm, rss_pages, state, nice)} for every process we can read."""
    out = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open("/proc/" + pid + "/stat", "rb") as f:
                raw = f.read()
        except OSError:
            # the process exited between listdir and open; that is normal
            continue
        # comm is field 2 and may contain spaces and parentheses, so split
        # around the LAST ')' rather than tokenising the whole line.
        try:
            lp = raw.index(b"(")
            rp = raw.rindex(b")")
        except ValueError:
            continue
        comm = raw[lp + 1:rp].decode("utf-8", "replace")
        rest = raw[rp + 2:].split()
        if len(rest) < 22:
            continue
        try:
            # after the state field, rest[0] is field 3, so field N is rest[N-3]
            utime, stime = int(rest[11]), int(rest[12])
            rss = int(rest[21])
            nice = int(rest[16])
        except ValueError:
            continue
        state = rest[0].decode("ascii", "replace")[:1] or "?"
        out[pid] = (utime + stime, comm, rss, state, nice)
    return out


def total_mem_kb():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return 0


def main():
    count = 40
    if len(sys.argv) > 1:
        try:
            count = max(1, int(sys.argv[1]))
        except ValueError:
            pass

    a = sample()
    t0 = time.monotonic()
    time.sleep(INTERVAL)
    b = sample()
    elapsed = max(1e-3, time.monotonic() - t0)

    mem_kb = total_mem_kb()
    uid = os.getuid()
    rows = []
    for pid, (ticks, comm, rss, state, nice) in b.items():
        prev = a.get(pid)
        # A process that appeared during the window has no baseline; report 0
        # rather than charging it for every tick since it was born.
        cpu = 0.0 if prev is None else (ticks - prev[0]) / CLK_TCK / elapsed * 100.0
        rss_kb = rss * PAGE_KB
        mem = (rss_kb / mem_kb * 100.0) if mem_kb else 0.0
        # Kernel threads have no resident memory of their own and mostly just
        # add noise to the list.
        if rss_kb == 0:
            continue
        rows.append((cpu, pid, comm, mem, rss_kb, state, nice))

    rows.sort(key=lambda r: (-r[0], -r[3]))
    # Resolve names and ownership only for the rows we are actually going to
    # print — that is one extra open() and one stat() each for 40 processes
    # instead of ~400.
    for cpu, pid, comm, mem, rss_kb, state, nice in rows[:count]:
        try:
            mine = 1 if os.stat("/proc/" + pid).st_uid == uid else 0
        except OSError:
            continue    # it exited; a row we cannot own is not worth a menu
        print("%s|%s|%.1f|%.1f|%d|%s|%d|%d"
              % (pid, pretty_name(pid, comm), cpu, mem, rss_kb, state, nice, mine))


if __name__ == "__main__":
    main()
