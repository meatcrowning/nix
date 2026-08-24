#!/usr/bin/env python3
"""Background jobs for chatter — the part that outlives the turn.

`tools/sandbox-exec.py` caps a run at 30 seconds, which is right for a program
the model wrote to answer a question and useless for the work he actually wants
an agent doing: fingerprinting 19,000 tracks, fetching an album, a replaygain
pass, a tag sweep. Those are minutes to hours [his, 2026-08-23: *"the goal here
is to allow oracle agents to help me build maintain clean etc my music
library"*].

So a job is a DIRECTORY, not a process handle:

    <root>/<id>/spec.json     what was asked for (command, lang, cwd, label)
    <root>/<id>/status.json   state, pid, started, ended, exit code
    <root>/<id>/log           stdout and stderr, interleaved, as it happens

That shape is what makes a job survive chatter itself — a relaunch reads the
directory back and picks the running ones up again — and what lets `book` drive
jobs on `top` over the same ssh every other executor here uses, with no daemon
and no port.

Pure stdlib: it runs under top's system python3 with nothing installed, exactly
like `sandbox-exec.py`.

    job-run.py start <root> --command CMD [--lang bash|python] [--cwd DIR]
                            [--label TEXT] [--max-seconds N]
    job-run.py list  <root> [--tail N] [--id ID]
    job-run.py stop  <root> --id ID
    job-run.py clear <root> [--id ID]      # forget a FINISHED job
    job-run.py run   <root> --id ID        # the runner itself (internal)
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time

#: A job that has not finished in this long is killed. Twelve hours is longer
#: than any library pass measured here and short enough that a wedged process
#: does not sit on the machine for a week.
MAX_SECONDS_DEFAULT = 12 * 3600
MAX_SECONDS_CEILING = 24 * 3600

#: The log is truncated past this, with a line saying so. `/` on top runs above
#: 80% full (the root AGENTS.md says to check before any bulk write), so a
#: runaway `find /` must not be able to fill it.
LOG_MAX_BYTES = 20 * 1024 * 1024

#: What `list` returns per job unless asked for more.
TAIL_DEFAULT = 8
TAIL_MAX = 400

STATES_DONE = ("done", "failed", "stopped", "timeout")


def _id_from(label):
    """A readable, sortable, collision-free id: the time, then the label."""
    slug = re.sub(r"[^a-z0-9]+", "-", (label or "job").lower()).strip("-")
    return "%d-%s" % (int(time.time() * 1000), slug[:32] or "job")


def _read(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def _tail(path, n):
    """The last `n` lines, without reading a 20 MB log into memory."""
    n = max(0, min(int(n or 0), TAIL_MAX))
    if not n:
        return [], 0
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            block = min(size, 8192 * max(1, n // 40 + 1))
            f.seek(max(0, size - block))
            data = f.read()
        lines = data.decode("utf-8", "replace").split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        return lines[-n:], size
    except OSError:
        return [], 0


# ---- start: make the directory, then hand it to a detached runner ----------

def cmd_start(args):
    root = os.path.abspath(os.path.expanduser(args.root))
    os.makedirs(root, exist_ok=True)
    job_id = _id_from(args.label)
    d = os.path.join(root, job_id)
    os.makedirs(d, exist_ok=True)
    cwd = os.path.abspath(os.path.expanduser(args.cwd or root))
    if not os.path.isdir(cwd):
        print(json.dumps({"error": "no such directory: " + cwd}))
        return 1
    spec = {"id": job_id, "label": (args.label or "").strip() or "job",
            "command": args.command, "lang": args.lang, "cwd": cwd,
            "max_seconds": max(1, min(int(args.max_seconds or
                                          MAX_SECONDS_DEFAULT),
                                      MAX_SECONDS_CEILING))}
    _write(os.path.join(d, "spec.json"), spec)
    _write(os.path.join(d, "status.json"),
           {"state": "starting", "started": time.time()})
    open(os.path.join(d, "log"), "a").close()

    # DETACHED, so the job outlives whatever started it — this process, the ssh
    # that ran it from book, and chatter itself. Its own session and its own
    # process group, which is also what makes `stop` able to take the whole
    # tree down rather than just the shell.
    argv = [sys.executable, os.path.abspath(__file__), "run", root,
            "--id", job_id]
    subprocess.Popen(argv, start_new_session=True,
                     stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True)
    print(json.dumps({"id": job_id, "label": spec["label"],
                      "state": "starting", "cwd": cwd,
                      "log": os.path.join(d, "log")}))
    return 0


# ---- run: the runner, inside the job's own session -------------------------

def cmd_run(args):
    root = os.path.abspath(os.path.expanduser(args.root))
    d = os.path.join(root, args.id)
    spec = _read(os.path.join(d, "spec.json"))
    if not spec:
        return 1
    log_path = os.path.join(d, "log")
    status_path = os.path.join(d, "status.json")
    started = time.time()
    if spec.get("lang") == "python":
        argv = [sys.executable, "-u", "-c", spec.get("command", "")]
    else:
        argv = ["/bin/sh", "-c", spec.get("command", "")]
    try:
        log = open(log_path, "a", buffering=1, encoding="utf-8",
                   errors="replace")
    except OSError:
        return 1
    try:
        proc = subprocess.Popen(argv, cwd=spec.get("cwd") or root,
                                stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
    except OSError as e:
        log.write("could not start: %s\n" % e)
        log.close()
        _write(status_path, {"state": "failed", "exit": 127,
                             "started": started, "ended": time.time(),
                             "error": str(e)})
        return 1
    _write(status_path, {"state": "running", "pid": proc.pid,
                         "started": started})

    deadline = started + int(spec.get("max_seconds") or MAX_SECONDS_DEFAULT)
    state, code = "done", None
    while True:
        try:
            code = proc.wait(timeout=2)
            break
        except subprocess.TimeoutExpired:
            pass
        # The kill switch `stop` writes, and the two limits that protect the
        # machine rather than the job.
        if os.path.exists(os.path.join(d, "stop")):
            _kill(proc)
            state, code = "stopped", proc.wait()
            break
        if time.time() > deadline:
            log.write("\n[job-run] killed: over its %ds limit\n"
                      % spec.get("max_seconds", MAX_SECONDS_DEFAULT))
            _kill(proc)
            state, code = "timeout", proc.wait()
            break
        try:
            if os.path.getsize(log_path) > LOG_MAX_BYTES:
                log.write("\n[job-run] killed: log past %d MB\n"
                          % (LOG_MAX_BYTES // (1024 * 1024)))
                _kill(proc)
                state, code = "failed", proc.wait()
                break
        except OSError:
            pass
    if state == "done" and code:
        state = "failed"
    log.close()
    _write(status_path, {"state": state, "exit": code, "pid": proc.pid,
                         "started": started, "ended": time.time()})
    return 0


def _kill(proc):
    """TERM the whole process group, then KILL what is left of it."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except OSError:
            return
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            continue


# ---- list / stop / clear ---------------------------------------------------

def _snapshot(d, tail_n):
    spec = _read(os.path.join(d, "spec.json")) or {}
    status = _read(os.path.join(d, "status.json")) or {}
    state = status.get("state") or "unknown"
    # A runner killed outright (a reboot, an OOM) leaves "running" behind and
    # nothing ever corrects it. The PID is the check — never the file alone.
    if state in ("running", "starting") and status.get("pid") \
            and not _alive(status["pid"]):
        state = "failed"
    lines, size = _tail(os.path.join(d, "log"), tail_n)
    started = status.get("started") or 0
    ended = status.get("ended") or 0
    return {"id": spec.get("id") or os.path.basename(d),
            "label": spec.get("label") or "job",
            "command": spec.get("command") or "",
            "lang": spec.get("lang") or "bash",
            "cwd": spec.get("cwd") or "",
            "state": state,
            "exit": status.get("exit"),
            "started": started,
            "ended": ended,
            "seconds": round((ended or time.time()) - started, 1)
                       if started else 0,
            "log_bytes": size,
            "tail": lines}


def cmd_list(args):
    root = os.path.abspath(os.path.expanduser(args.root))
    tail_n = TAIL_DEFAULT if args.tail is None else args.tail
    jobs = []
    if os.path.isdir(root):
        names = [args.id] if args.id else sorted(os.listdir(root))
        for name in names:
            d = os.path.join(root, name)
            if os.path.isfile(os.path.join(d, "spec.json")):
                jobs.append(_snapshot(d, tail_n))
    jobs.sort(key=lambda j: j.get("started") or 0)
    print(json.dumps({"jobs": jobs}))
    return 0


def cmd_stop(args):
    root = os.path.abspath(os.path.expanduser(args.root))
    d = os.path.join(root, args.id or "")
    if not os.path.isdir(d):
        print(json.dumps({"error": "no such job: " + str(args.id)}))
        return 1
    open(os.path.join(d, "stop"), "a").close()      # the runner picks this up
    status = _read(os.path.join(d, "status.json")) or {}
    if status.get("state") in STATES_DONE:
        print(json.dumps({"id": args.id, "state": status.get("state"),
                          "note": "already finished"}))
        return 0
    print(json.dumps({"id": args.id, "state": "stopping"}))
    return 0


def cmd_clear(args):
    """Forget FINISHED jobs. A running one is never removed — the row he can
    see is the only handle on a process that outlives this window."""
    root = os.path.abspath(os.path.expanduser(args.root))
    removed = []
    if os.path.isdir(root):
        names = [args.id] if args.id else sorted(os.listdir(root))
        for name in names:
            d = os.path.join(root, name)
            if not os.path.isfile(os.path.join(d, "spec.json")):
                continue
            snap = _snapshot(d, 0)
            if snap["state"] not in STATES_DONE:
                continue
            for f in ("spec.json", "status.json", "log", "stop"):
                try:
                    os.remove(os.path.join(d, f))
                except OSError:
                    pass
            try:
                os.rmdir(d)
                removed.append(name)
            except OSError:
                pass
    print(json.dumps({"cleared": removed}))
    return 0


def main():
    p = argparse.ArgumentParser(add_help=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("start", "run", "list", "stop", "clear"):
        s = sub.add_parser(name)
        s.add_argument("root")
        s.add_argument("--id")
        s.add_argument("--command", default="")
        s.add_argument("--lang", default="bash", choices=("bash", "python"))
        s.add_argument("--cwd", default="")
        s.add_argument("--label", default="")
        s.add_argument("--max-seconds", type=int, default=MAX_SECONDS_DEFAULT)
        s.add_argument("--tail", type=int, default=None)
    args = p.parse_args()
    return {"start": cmd_start, "run": cmd_run, "list": cmd_list,
            "stop": cmd_stop, "clear": cmd_clear}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
