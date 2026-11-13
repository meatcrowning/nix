#!/usr/bin/env python3
"""Record a real Claude/Codex exchange as a scrubbed Coder fixture.

OPT-IN AND BY HAND ONLY. This runs the real CLI, spends real usage, and makes
a session in the CLI's own store. Run it in a scratch git repository with a
trivial prompt. Harnesses never call it; they replay what it wrote
(apps/coder/AGENTS.md).

  record-fixture.py claude OUT --cwd DIR --prompt TEXT [--prompt TEXT...]
        [--model haiku] [--deny SUBSTR] [--interrupt-after N]
  record-fixture.py codex OUT --cwd DIR --prompt TEXT [...] [--model M]
        [--mode ask] [--deny SUBSTR] [--interrupt-after N]
  record-fixture.py scrub RAW OUT [--cwd DIR]

Permission requests are allowed unless their input contains a --deny
substring. ``--interrupt-after N`` interrupts the last turn after N streamed
text deltas. The output is scrubbed for this public repository: home paths,
the scratch cwd, account identity, skill and command lists, hook output,
thinking signatures and installation ids.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

GENERIC_COMMANDS = [{"name": "compact", "description": "Clear history but keep a summary", "argumentHint": ""},
                    {"name": "code-review", "description": "Review the current diff", "argumentHint": ""},
                    {"name": "init", "description": "Initialize a CLAUDE.md file", "argumentHint": ""}]
DROP_KEYS = {"signature", "installationId", "memory_paths", "messaging_socket_path",
             "codexHome", "userAgent", "uuid", "leafUuid"}


def scrub(obj, cwd, home):
    def s(v):
        if isinstance(v, str):
            if cwd:
                v = v.replace(cwd, "/work/repo")
            v = v.replace(home, "/home/user")
            v = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "user@example.invalid", v)
            return v
        if isinstance(v, list):
            return [s(x) for x in v]
        if isinstance(v, dict):
            out = {}
            for k, x in v.items():
                if k in DROP_KEYS:
                    out[k] = "scrubbed" if isinstance(x, str) else None
                elif k == "account":
                    out[k] = {"email": "user@example.invalid", "subscriptionType": "test"}
                elif k in ("commands",) and isinstance(x, list):
                    out[k] = GENERIC_COMMANDS
                elif k in ("slash_commands", "skills", "plugins", "agents", "mcp_servers",
                           "terminal_slash_commands") and isinstance(x, list):
                    out[k] = [y for y in x if y in ("compact", "code-review", "init")] \
                        if k == "slash_commands" else []
                elif k == "tools" and isinstance(x, list) and all(isinstance(y, str) for y in x):
                    out[k] = [y for y in x if y in ("Bash", "Read", "Edit", "Write", "Glob", "Grep")]
                elif k in ("output", "stdout", "stderr") and v.get("subtype") == "hook_response":
                    out[k] = "hook output scrubbed"
                elif k == "data" and isinstance(x, list) and x and isinstance(x[0], dict) \
                        and "preview" in x[0]:
                    # thread/list: keep only threads recorded in the scratch cwd
                    out[k] = [s(t) for t in x if cwd and str(t.get("cwd", "")) == cwd]
                elif k in ("serverName",):
                    out[k] = "host"
                else:
                    out[k] = s(x)
            return out
        return v
    return s(obj)


def _drop(r):
    """Partial tool-input JSON splits paths across deltas, past scrubbing."""
    ev = (r.get("msg") or {}).get("event") if isinstance(r.get("msg"), dict) else None
    return isinstance(ev, dict) and (ev.get("delta") or {}).get("type") in (
        "input_json_delta", "signature_delta")


def write_fixture(records, out, cwd):
    home = str(Path.home())
    records = [r for r in records if not _drop(r)]
    meta = {"dir": "meta", "msg": {"recorded": time.strftime("%Y-%m-%d"),
                                   "versions": versions()}}
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(meta) + "\n")
        for r in records:
            if r.get("dir") == "meta":
                continue
            r = dict(r, msg=scrub(r.get("msg"), cwd, home))
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def versions():
    out = {}
    for name in ("claude", "codex"):
        try:
            out[name] = subprocess.run([name, "--version"], capture_output=True, text=True,
                                       timeout=20).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            out[name] = ""
    return out


def run_claude(a):
    import claude_proto
    argv = claude_proto.argv(model=a.model or "haiku", mode=a.mode or "default")
    p = subprocess.Popen(argv, cwd=a.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, bufsize=1)
    recs = []

    def log(d, o):
        recs.append({"t": round(time.time(), 3), "dir": d, "msg": o})

    def send(o):
        log("out", o)
        p.stdin.write(json.dumps(o) + "\n")
        p.stdin.flush()

    prompts = list(a.prompt)
    send({"type": "control_request", "request_id": "rec_init", "request": {"subtype": "initialize", "hooks": None}})

    def user(t):
        send({"type": "user", "session_id": "", "message": {"role": "user", "content": t},
              "parent_tool_use_id": None})
    user(prompts.pop(0))
    deltas, interrupted = 0, False
    for line in p.stdout:
        try:
            o = json.loads(line)
        except ValueError:
            continue
        log("in", o)
        if o.get("type") == "control_request" and (o.get("request") or {}).get("subtype") == "can_use_tool":
            inp = json.dumps(o["request"].get("input", {}))
            if any(d in inp for d in a.deny):
                resp = {"behavior": "deny", "message": "denied by the user"}
            else:
                resp = {"behavior": "allow", "updatedInput": o["request"].get("input", {})}
            send({"type": "control_response", "response": {"subtype": "success",
                                                           "request_id": o["request_id"], "response": resp}})
        ev = o.get("event") or {}
        if (a.interrupt_after and not prompts and not interrupted
                and ev.get("type") == "content_block_delta"
                and (ev.get("delta") or {}).get("type") == "text_delta"):
            deltas += 1
            if deltas >= a.interrupt_after:
                interrupted = True
                send({"type": "control_request", "request_id": "rec_int", "request": {"subtype": "interrupt"}})
        if o.get("type") == "result":
            if prompts:
                user(prompts.pop(0))
            else:
                p.stdin.close()
    p.wait()
    log("exit", {"code": p.returncode})
    return recs


def run_codex(a):
    p = subprocess.Popen(["codex", "app-server"], cwd=a.cwd, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    recs = []
    ids = iter(range(1, 10**6))
    import codex_proto
    mode = codex_proto._mode(a.mode or "ask")

    def log(d, o):
        recs.append({"t": round(time.time(), 3), "dir": d, "msg": o})

    def send(o):
        log("out", o)
        p.stdin.write(json.dumps(o) + "\n")
        p.stdin.flush()

    def req(method, params):
        i = next(ids)
        send({"jsonrpc": "2.0", "id": i, "method": method, "params": params})
        return i

    prompts = list(a.prompt)
    init = req("initialize", {"clientInfo": {"name": "coder", "title": "Coder", "version": "record"},
                              "capabilities": {"experimentalApi": False}})
    thread, turn, deltas, interrupted = None, None, 0, False
    start_id = None
    for line in p.stdout:
        try:
            o = json.loads(line)
        except ValueError:
            continue
        log("in", o)
        if o.get("id") == init and "result" in o:
            send({"jsonrpc": "2.0", "method": "initialized"})
            start_id = req("thread/start", {"cwd": a.cwd, "approvalPolicy": mode[1], "sandbox": mode[2],
                                            "model": a.model or None})
        elif o.get("id") == start_id and "result" in o:
            thread = o["result"]["thread"]["id"]
            req("turn/start", {"threadId": thread, "input": [{"type": "text", "text": prompts.pop(0),
                                                              "text_elements": []}], "effort": "low"})
        elif "method" in o and "id" in o:
            params = json.dumps(o.get("params", {}))
            if "requestApproval" in o["method"]:
                dec = "decline" if any(d in params for d in a.deny) else "accept"
                send({"jsonrpc": "2.0", "id": o["id"], "result": {"decision": dec}})
            else:
                send({"jsonrpc": "2.0", "id": o["id"], "error": {"code": -32601, "message": "unsupported"}})
        elif o.get("method") == "turn/started":
            turn = o["params"]["turn"]["id"]
        elif o.get("method") == "item/agentMessage/delta" and a.interrupt_after and not prompts:
            deltas += 1
            if deltas >= a.interrupt_after and not interrupted:
                interrupted = True
                req("turn/interrupt", {"threadId": thread, "turnId": turn})
        elif o.get("method") == "turn/completed":
            if prompts:
                req("turn/start", {"threadId": thread, "input": [{"type": "text", "text": prompts.pop(0),
                                                                  "text_elements": []}], "effort": "low"})
            else:
                break
    p.stdin.close()
    p.terminate()
    try:
        p.wait(5)
    except subprocess.TimeoutExpired:
        p.kill()
    log("exit", {"code": 0})
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["claude", "codex", "scrub"])
    ap.add_argument("out")
    ap.add_argument("out2", nargs="?")
    ap.add_argument("--cwd", default="")
    ap.add_argument("--prompt", action="append", default=[])
    ap.add_argument("--model", default="")
    ap.add_argument("--mode", default="")
    ap.add_argument("--deny", action="append", default=[])
    ap.add_argument("--interrupt-after", type=int, default=0)
    a = ap.parse_args()
    if a.kind == "scrub":
        recs = [json.loads(l) for l in open(a.out, encoding="utf-8") if l.strip()]
        write_fixture(recs, a.out2, a.cwd)
        return 0
    if not a.cwd or not a.prompt:
        ap.error("--cwd and --prompt are required")
    a.cwd = os.path.realpath(a.cwd)
    recs = run_claude(a) if a.kind == "claude" else run_codex(a)
    write_fixture(recs, a.out, a.cwd)
    print("wrote %s (%d records)" % (a.out, len(recs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
