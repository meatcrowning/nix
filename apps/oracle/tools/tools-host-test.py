#!/usr/bin/env python3
"""Which machine a tool acts on.

    <an app python> apps/oracle/tools/tools-host-test.py

Every executor here used to hard-branch to `top` from book — right for the
model's compute, wrong for his files: chatter on book could not read a file on
book, could not run a command against it, and asked top what was playing while
he sat in front of book playing something else [his, 2026-08-24].

So the file tools, the two runners, background jobs and the music library
default to THE MACHINE THIS WINDOW IS ON, the file tools' `host` argument still
reaches the other one, and `ORACLE_TOOLS_HOST` forces the whole lot either way.
What must NOT follow it — ollama, generation, the shared session and memory
stores — is checked here too, since that is the half a refactor breaks silently.

It runs a child per configuration and reads the argv the app would actually
build, so nothing is asserted against a remembered rule.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix="oracle-toolshost-"))
APP = HERE.parent

PROBE = r'''
import json, os, sys
sys.path.insert(0, %r); sys.path.insert(0, %r)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
# NOT --selftest: that mode points the session and memory stores at a
# throwaway root, and a store pointed somewhere else runs LOCALLY by design
# (main.STORE_LOCAL) — which is exactly the fact this file is checking.
# `$ORACLE_CONFIG` keeps his own config out of it instead.
sys.argv = [sys.argv[0]]
import main as o
print(json.dumps({
    "local": o.LOCAL_HOST,
    "tools_host": o.TOOLS_HOST,
    "remote": o.TOOLS_REMOTE,
    "fs_default": o.Ollama._fs_argv(),
    "fs_top": o.Ollama._fs_argv("top"),
    "fs_book": o.Ollama._fs_argv("book"),
    "exec": o.Ollama._exec_argv(),
    "music": o.Ollama._music_argv(),
    "jobs": o.Jobs._argv("list"),
    "memory": o.Ollama._memories_argv(),
    "sessions": o.Ollama._sessions_argv(),
    "host_arg_default": o.HOST_ARG["description"],
    "write_takes_host": [t["function"]["name"] for t in o.FILE_TOOLS
                         if "host" in t["function"]["parameters"]["properties"]],
}))
''' % (str(APP), str(APP.parent / "pylib"))

fails = []


def check(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"   [{detail}]" if detail else ""))
    if not ok:
        fails.append(name)


def probe(**env):
    e = dict(os.environ)
    e.pop("ORACLE_TOOLS_HOST", None)
    for k in ("ORACLE_MEMORY", "ORACLE_SESSIONS"):
        e.pop(k, None)
    e["ORACLE_CONFIG"] = str(TMP)
    e.update({k: str(v) for k, v in env.items()})
    out = subprocess.run([sys.executable, "-c", PROBE], env=e, text=True,
                         capture_output=True, timeout=120)
    try:
        return json.loads(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        print(out.stdout[-2000:], out.stderr[-2000:])
        raise


def is_ssh(argv):
    return any(a.endswith("ssh") for a in argv[:1]) or "ssh" in os.path.basename(argv[0])


def local(argv):
    return not is_ssh(argv)


print("where chatter's tools act")

here = probe()
other = "book" if here["local"] == "top" else "top"

check("the default is the machine this window is on",
      here["tools_host"] == here["local"] and not here["remote"],
      here["local"] + " -> " + here["tools_host"])

# ---- his files, his shell, his jobs, his music: HERE ---------------------
for what in ("fs_default", "exec", "music", "jobs"):
    check("%s runs on this machine" % what, local(here[what]),
          " ".join(here[what][:3]))

# ---- ...and the other machine is still one argument away ----------------
check("the file tools reach this machine by name too",
      local(here["fs_" + here["local"]]), " ".join(here["fs_" + here["local"]][:3]))
check("...and the OTHER one over ssh",
      is_ssh(here["fs_" + other]), " ".join(here["fs_" + other][:4]))
check("the host argument says which is the default, by name",
      here["local"] in here["host_arg_default"], here["host_arg_default"])
check("every file tool takes it, writes included",
      set(here["write_takes_host"]) >= {"read_file", "list_dir", "write_file",
                                        "edit_file", "move_path", "delete_path",
                                        "make_dir", "find_files", "search_text",
                                        "show_tree"},
      str(here["write_takes_host"]))

# ---- what must NOT follow it --------------------------------------------
if here["local"] == "book":
    check("the shared memory store still lives on top", is_ssh(here["memory"]),
          " ".join(here["memory"][:3]))
    check("...and the session history with it", is_ssh(here["sessions"]),
          " ".join(here["sessions"][:3]))
else:
    check("on top every store is local anyway",
          local(here["memory"]) and local(here["sessions"]))

# ---- the escape hatch, both ways ----------------------------------------
forced = probe(ORACLE_TOOLS_HOST=other)
check("ORACLE_TOOLS_HOST sends the whole lot to the other machine",
      forced["tools_host"] == other and forced["remote"]
      and is_ssh(forced["fs_default"]) and is_ssh(forced["exec"])
      and is_ssh(forced["music"]) and is_ssh(forced["jobs"]),
      other + ": " + " ".join(forced["fs_default"][:3]))
back = probe(ORACLE_TOOLS_HOST=here["local"])
check("...and naming this one is the same as saying nothing",
      back["tools_host"] == here["local"] and local(back["fs_default"]))
check("a junk value falls back to this machine rather than to a junk host",
      probe(ORACLE_TOOLS_HOST="nowhere")["tools_host"] == here["local"])

print("FAILED: " + ", ".join(fails) if fails else "all ok")
sys.exit(1 if fails else 0)
