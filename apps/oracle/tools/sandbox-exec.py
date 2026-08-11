#!/usr/bin/env python3
"""oracle's jailed Python code runner — the muscle behind its run_python tool.

oracle offers the local ollama model a `run_python` tool (see apps/oracle/main.py
`EXEC_TOOL`) so it can actually RUN code instead of only reasoning about it — the
gap gemma4:e4b named honestly ("no code-execution env"). Executing model-written
code is a security decision he took deliberately (the board question of
2026-08-11); this script is where that runs, and it is the jail:

  * a WRITE root as argv[1] — the same `~/.local/share/oracle/sandbox` the file
    tools use — is the process's WORKING DIRECTORY, so relative paths the code
    writes stay inside the sandbox;
  * NETWORK is cut with an unprivileged network+user namespace (`unshare -rn`)
    when the host allows it, so the code cannot reach the internet or a
    loopback backend;
  * WALL TIME, CPU, ADDRESS SPACE, FILE SIZE and OUTPUT are all capped, so a
    runaway loop, a fork bomb of allocations, a 10 GB write or a flood of prints
    cannot wedge the host or blow the model's context window.

It is NOT a container. The code runs as the user, so it can still READ the
user's files (exactly what the read-only file tools already grant) and, with an
absolute path, write outside the working directory. The confinement that IS hard
here — no network, bounded resources, sandbox as cwd — is real; the honesty note
in main.py's EXEC_TOOL and CAPABILITY_NOTE says so plainly rather than implying a
container that is not there (docs/DESIGN.md §10).

WHERE it runs: oracle's compute is ollama on `top`, so this runs there too —
locally on `top`, over the SAME ssh master tools/ollama-tunnel.sh holds open on
`book` (`ssh top python3 <this> <root>`), identical to the file/session/memory
executors. Pure stdlib on purpose, so top's system python3 runs it over ssh with
nothing installed.

PROTOCOL: one JSON request object on stdin, one JSON result object on stdout.
    {"code": "print(2**10)", "timeout": 5, "stdin": ""}
    -> {"ok": true, "stdout": "1024\n", "stderr": "", "exit_code": 0,
        "timed_out": false, "network_isolated": true, ...}
An error in the HARNESS (bad request, unwritable sandbox) is `{"error": "..."}`
with exit 0 — reported to the model, never a crash. Code that itself raises is a
SUCCESSFUL run with a non-zero `exit_code` and the traceback in `stderr`.
"""
import json
import os
import resource
import shutil
import signal
import subprocess
import sys
import tempfile

# --- caps: a run must never wedge the host or blow the model's context window ---
TIMEOUT_DEFAULT = 10          # wall-clock seconds if the caller names none
TIMEOUT_MAX = 30              # hard ceiling on the wall clock, whatever is asked
OUT_MAX_BYTES = 40_000        # per stream (stdout / stderr); the rest is dropped
CODE_MAX_BYTES = 256_000      # refuse an absurdly large program outright
STDIN_MAX_BYTES = 256_000     # ...and an absurdly large stdin feed
CPU_SECONDS = 20              # RLIMIT_CPU — a hair above the wall cap, a backstop
MEM_BYTES = 1024 * 1024 * 1024  # RLIMIT_AS — 1 GiB address space per run
FSIZE_BYTES = 16 * 1024 * 1024  # RLIMIT_FSIZE — biggest file the code may write


def fail(reason):
    print(json.dumps({"error": reason}))
    sys.exit(0)


def _child_setup():
    """preexec_fn for the child: put it in its OWN process group (so a timeout
    can kill any grandchildren the code spawns, not just python), then cap CPU,
    address space, file size and cores. The rlimits are inherited across both
    the namespace unshare and the exec into python, so they bind the code."""
    os.setsid()
    for res, soft in ((resource.RLIMIT_CPU, CPU_SECONDS),
                      (resource.RLIMIT_AS, MEM_BYTES),
                      (resource.RLIMIT_FSIZE, FSIZE_BYTES),
                      (resource.RLIMIT_CORE, 0)):
        try:
            resource.setrlimit(res, (soft, soft))
        except (ValueError, OSError):
            pass          # a limit the kernel won't grant is skipped, never fatal


def _net_isolation_argv():
    """`[unshare, -r, -n]` if an unprivileged net+user namespace can be created
    here, else `[]`. Probed once with `unshare -rn true` so a host without user
    namespaces degrades to a run WITHOUT network isolation (reported honestly),
    rather than every run failing to start."""
    unshare = shutil.which("unshare")
    if not unshare:
        return []
    try:
        p = subprocess.run([unshare, "-r", "-n", "true"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=5)
        return [unshare, "-r", "-n"] if p.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        return []


def _clip(raw):
    """Decode a captured stream, capped at OUT_MAX_BYTES; report if it was cut."""
    cut = len(raw) > OUT_MAX_BYTES
    text = raw[:OUT_MAX_BYTES].decode("utf-8", "replace")
    if cut:
        text += "\n…[output truncated at %d bytes]" % OUT_MAX_BYTES
    return text, cut


def main():
    if len(sys.argv) < 2:
        fail("no sandbox root given")
    root = os.path.realpath(os.path.expanduser(sys.argv[1]))
    try:
        os.makedirs(root, exist_ok=True)      # a fresh top has no sandbox yet
    except OSError as e:
        fail("cannot create sandbox root: " + str(e))

    try:
        req = json.loads(sys.stdin.read() or "{}")
        if not isinstance(req, dict):
            raise ValueError
    except ValueError:
        fail("bad request")

    code = req.get("code", "")
    if not isinstance(code, str) or not code.strip():
        fail("code must be a non-empty string")
    code_bytes = code.encode("utf-8")
    if len(code_bytes) > CODE_MAX_BYTES:
        fail("refusing to run %d bytes of code (cap %d)" % (len(code_bytes),
                                                            CODE_MAX_BYTES))
    stdin_text = req.get("stdin", "") or ""
    if not isinstance(stdin_text, str):
        fail("stdin must be a string")
    stdin_bytes = stdin_text.encode("utf-8")
    if len(stdin_bytes) > STDIN_MAX_BYTES:
        fail("stdin too large (cap %d bytes)" % STDIN_MAX_BYTES)
    try:
        timeout = float(req.get("timeout", TIMEOUT_DEFAULT) or TIMEOUT_DEFAULT)
    except (TypeError, ValueError):
        timeout = TIMEOUT_DEFAULT
    timeout = max(1.0, min(timeout, TIMEOUT_MAX))

    # The program goes to a temp file INSIDE the sandbox (so it too lives in the
    # jail), run with -I (isolated: ignore env/user-site, reproducible).
    fd, path = tempfile.mkstemp(prefix="run-", suffix=".py", dir=root)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(code_bytes)
        net = _net_isolation_argv()
        argv = net + [sys.executable, "-I", path]
        try:
            proc = subprocess.Popen(
                argv, cwd=root, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                preexec_fn=_child_setup)
        except OSError as e:
            fail("cannot run code: " + str(e))
        timed_out = False
        try:
            out_raw, err_raw = proc.communicate(input=stdin_bytes, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:                       # kill the whole group, not just python
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            out_raw, err_raw = proc.communicate()
        out, out_cut = _clip(out_raw or b"")
        err, err_cut = _clip(err_raw or b"")
        res = {"ok": True, "timed_out": timed_out,
               "exit_code": None if timed_out else proc.returncode,
               "stdout": out, "stderr": err,
               "stdout_truncated": out_cut, "stderr_truncated": err_cut,
               "network_isolated": bool(net), "timeout": timeout}
        if timed_out:
            res["note"] = "killed after %g s (wall-clock cap)" % timeout
        print(json.dumps(res))
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
