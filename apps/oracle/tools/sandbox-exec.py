#!/usr/bin/env python3
"""oracle's code runner — the muscle behind its run_python and run_bash tools.

oracle offers the local ollama model a `run_python` tool and a `run_bash` tool
(see apps/oracle/main.py `EXEC_TOOL` / `BASH_TOOL`) so it can actually RUN code
instead of only reasoning about it — the gap gemma4:e4b named honestly ("no
code-execution env"). Executing model-written code is a security decision he
took deliberately (the board question of 2026-08-11); the SHELL half is his call
of 2026-08-22 ("give them the same abilities and tools you do when manipulating
files") — a model that can write and delete any file but cannot run `grep`, `cp`
or `git` was doing the job with one hand. One request field, `lang`, picks the
interpreter; everything else — the caps, the cwd rules, the protocol — is shared
so the two runners cannot drift apart. This script is where that runs:

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
    {"code": "print(2**10)", "lang": "python", "timeout": 5, "stdin": "",
     "cwd": "/home/lam"}
    -> {"ok": true, "stdout": "1024\n", "stderr": "", "exit_code": 0,
        "lang": "python", "timed_out": false, "network_isolated": true, ...}
`lang` is "python" (the default, so an old caller is unchanged) or "bash".
An error in the HARNESS (bad request, unwritable sandbox) is `{"error": "..."}`
with exit 0 — reported to the model, never a crash. Code that itself raises is a
SUCCESSFUL run with a non-zero `exit_code` and the traceback in `stderr`.
"""
import json
import os
import resource
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time

# --- caps: a run must never wedge the host or blow the model's context window ---
TIMEOUT_DEFAULT = 10          # wall-clock seconds if the caller names none
TIMEOUT_MAX = 30              # hard ceiling on the wall clock, whatever is asked
OUT_MAX_BYTES = 40_000        # per stream (stdout / stderr); the rest is dropped
CODE_MAX_BYTES = 256_000      # refuse an absurdly large program outright
#: How much LIVE output one run may echo while it works. The full stdout is
#: still returned (clipped by OUT_MAX_BYTES); this only bounds the tail he
#: watches, so a program printing a gigabyte cannot flood the pipe either.
STREAM_MAX_BYTES = 20000
STDIN_MAX_BYTES = 256_000     # ...and an absurdly large stdin feed
CPU_SECONDS = 20              # RLIMIT_CPU — a hair above the wall cap, a backstop
#: RLIMIT_AS — ADDRESS SPACE, not resident memory, and that distinction is what
#: made 1 GiB the wrong number [his, 2026-08-23: chatter tried to `ollama pull`
#: a model for him and got `runtime/cgo: pthread_create failed` before the
#: download began]. A Go runtime RESERVES far more virtual address space than it
#: ever touches — arenas, plus 8 MB of stack per OS thread — so every Go binary
#: on this machine (ollama, gh, deno…) died instantly under a 1 GiB cap while a
#: python loop happily allocating real memory sailed under it. Measured with
#: `ulimit -v` the same afternoon: `ollama list` aborts at 1 GiB and works at
#: 2 GiB. 4 GiB is that with headroom, and RSS — the number that can actually
#: hurt the machine — is still bounded by the wall clock, the CPU cap and
#: oomd's own watch on the user slice.
MEM_BYTES = 4 * 1024 * 1024 * 1024  # RLIMIT_AS — 4 GiB of address space per run
FSIZE_BYTES = 16 * 1024 * 1024  # RLIMIT_FSIZE — biggest file the code may write

#: The interpreters a request may ask for. Python was the only one until
#: 2026-08-22; bash is the second because the file work the model does is shell
#: work — `grep -rn`, `cp -a`, `git diff`, a for-loop over a directory. Both get
#: the SAME caps and the same cwd rules: the language is the only difference.
LANGS = ("python", "bash")


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


def _pump(proc, stdin_bytes, timeout):
    """Run the child, echoing its output line-by-line as it comes.

    Returns (stdout, stderr, timed_out) exactly as `communicate` would, so the
    result object is built from the same bytes either way — the stream is an
    ADDITION to the protocol, never a replacement for its answer. Output is
    still capped by `_clip` at the end; what is echoed live is capped here too,
    so a program printing a gigabyte cannot flood the caller's pipe either.
    """
    if stdin_bytes:
        try:
            proc.stdin.write(stdin_bytes)
        except OSError:
            pass
    try:
        proc.stdin.close()
    except OSError:
        pass
    chunks = {proc.stdout: [], proc.stderr: []}
    kind = {proc.stdout: "o", proc.stderr: "e"}
    live = [0]
    deadline = time.monotonic() + timeout
    open_pipes = [proc.stdout, proc.stderr]
    timed_out = False
    while open_pipes:
        left = deadline - time.monotonic()
        if left <= 0:
            timed_out = True
            break
        ready, _, _ = select.select(open_pipes, [], [], min(left, 0.5))
        for pipe in ready:
            data = os.read(pipe.fileno(), 65536)
            if not data:
                open_pipes.remove(pipe)
                continue
            chunks[pipe].append(data)
            if live[0] < STREAM_MAX_BYTES:
                text = data.decode("utf-8", "replace")
                live[0] += len(data)
                if live[0] >= STREAM_MAX_BYTES:
                    text += "\n… (live output capped; the full result follows)"
                print(json.dumps({"t": kind[pipe], "d": text}), flush=True)
        if not ready and proc.poll() is not None and not open_pipes:
            break
    if timed_out:
        try:                           # kill the whole group, not just python
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
        for pipe in list(open_pipes):
            try:
                chunks[pipe].append(pipe.read() or b"")
            except OSError:
                pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    return (b"".join(chunks[proc.stdout]), b"".join(chunks[proc.stderr]),
            timed_out)


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

    lang = str(req.get("lang") or "python").strip().lower()
    if lang not in LANGS:
        fail("unknown lang %r (want one of %s)" % (lang, ", ".join(LANGS)))

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

    # The program goes to a temp file in the scratch root. Python runs with -I
    # (isolated: ignore env/user-site, so a run is reproducible); bash runs the
    # script plainly, inheriting the environment — a shell with no PATH or no
    # HOME is not the shell the model is being told it has.
    suffix = ".sh" if lang == "bash" else ".py"
    fd, path = tempfile.mkstemp(prefix="run-", suffix=suffix, dir=root)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(code_bytes)
        net = _net_isolation_argv() if no_net else []
        if lang == "bash":
            argv = net + [shutil.which("bash") or "/bin/bash", path]
        else:
            argv = net + [sys.executable, "-I", path]
        try:
            proc = subprocess.Popen(
                argv, cwd=cwd, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                preexec_fn=_child_setup)
        except OSError as e:
            fail("cannot run %s: %s" % (lang, e))
        # STREAMING (`stream: true`) — the caller watches the program work
        # instead of staring at a still window for thirty seconds. Each chunk
        # goes out as its own NDJSON line, `{"t":"o"|"e","d":"…"}`, and the
        # final result object is the LAST line exactly as before, so a caller
        # that does not ask for it — or an OLDER copy of this script reached
        # over ssh, which ignores the unknown key — is unaffected.
        if req.get("stream"):
            out_raw, err_raw, timed_out = _pump(proc, stdin_bytes, timeout)
        else:
            timed_out = False
            try:
                out_raw, err_raw = proc.communicate(input=stdin_bytes,
                                                    timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:                   # kill the whole group, not just python
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    proc.kill()
                out_raw, err_raw = proc.communicate()
        out, out_cut = _clip(out_raw or b"")
        err, err_cut = _clip(err_raw or b"")
        res = {"ok": True, "lang": lang, "timed_out": timed_out,
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
