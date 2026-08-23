#!/usr/bin/env python3
"""oracle's Python code runner — the muscle behind its run_python tool.

oracle offers the local ollama model a `run_python` tool (see apps/oracle/main.py
`EXEC_TOOL`) so it can actually RUN code instead of only reasoning about it — the
gap gemma4:e4b named honestly ("no code-execution env"). Executing model-written
code is a security decision he took deliberately (the board question of
2026-08-11); this script is where that runs, and it is the jail:

  * a SCRATCH root as argv[1] — `~/.local/share/oracle/sandbox` — is the
    process's default WORKING DIRECTORY, so relative paths the code writes land
    somewhere tidy. A request may name its own `cwd` instead;
  * WALL TIME, CPU, ADDRESS SPACE, FILE SIZE and OUTPUT are all capped, so a
    runaway loop, a fork bomb of allocations, a 10 GB write or a flood of prints
    cannot wedge the host or blow the model's context window.

**This is NOT a jail, since 2026-08-22** ("i dont really want them to be
[sandboxed]"). The code runs as the user with the network up, so it can read,
write and delete whatever the user can and reach whatever the user can reach —
the same reach the file tools now have, which is the point. Pass `--no-net` as
argv[2] to put the old network cut back (an unprivileged net+user namespace via
`unshare -rn`, reported in `network_isolated`); main.py sends it when
`ORACLE_EXEC_NET=0`. What remains hard either way is the RESOURCE caps, which
protect this desktop from a runaway program rather than from its author, and
main.py's EXEC_TOOL / CAPABILITY_NOTE describe exactly this (docs/DESIGN.md
§10 — never overstate a jail, in either direction).

WHERE it runs: oracle's compute is ollama on `top`, so this runs there too —
locally on `top`, over the SAME ssh master tools/ollama-tunnel.sh holds open on
`book` (`ssh top python3 <this> <root>`), identical to the file/session/memory
executors. Pure stdlib on purpose, so top's system python3 runs it over ssh with
nothing installed.

PROTOCOL: one JSON request object on stdin, one JSON result object on stdout.
    {"code": "print(2**10)", "timeout": 5, "stdin": "", "cwd": "/home/lam"}
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
    no_net = "--no-net" in sys.argv[2:]
    try:
        os.makedirs(root, exist_ok=True)      # a fresh top has no scratch dir
    except OSError as e:
        fail("cannot create scratch root: " + str(e))

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

    # Where the program runs. The scratch root by default; a caller-named `cwd`
    # (absolute, or relative to that root) otherwise — the code may write
    # anywhere the user can, so it may also RUN anywhere the user can.
    cwd = root
    want = req.get("cwd", "")
    if isinstance(want, str) and want.strip():
        cand = os.path.expanduser(want.strip())
        cand = cand if os.path.isabs(cand) else os.path.join(root, cand)
        if os.path.isdir(cand):
            cwd = os.path.realpath(cand)
        else:
            fail("no such working directory: " + want)

    # The program goes to a temp file in the scratch root, run with -I
    # (isolated: ignore env/user-site, so a run is reproducible).
    fd, path = tempfile.mkstemp(prefix="run-", suffix=".py", dir=root)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(code_bytes)
        net = _net_isolation_argv() if no_net else []
        argv = net + [sys.executable, "-I", path]
        try:
            proc = subprocess.Popen(
                argv, cwd=cwd, stdin=subprocess.PIPE,
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
               "network_isolated": bool(net), "cwd": cwd,
               "timeout": timeout}
        if no_net and not net:
            res["note_network"] = ("asked to isolate the network but this host "
                                   "has no unprivileged user namespaces — the "
                                   "run had network access")
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
