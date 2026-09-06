#!/usr/bin/env python3
"""A subagent does the bulky work, and only its ANSWER comes back.

`spawn_agent` exists so one turn's 32k window is not spent on output nobody
needs afterwards — a grep over a big tree, three files read to establish one
fact. This drives a real turn through the real window (offscreen) against a
STUB ollama on 127.0.0.1 and reads every request body, in order:

    1  the main agent calls spawn_agent(explorer, …)
    2  the SUBAGENT's first request — its own system prompt, its own
       restricted tool list, none of the main conversation
    3  the subagent's second request, carrying the file it read
    4  the main agent's next round — which must hold the subagent's summary
       and NOT one byte of what the subagent actually read

His daemon is never touched, no model is loaded, nothing reaches his screen.
"""
import http.server
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
BODIES = []
fails = []

TREE = Path(tempfile.mkdtemp(prefix="oracle-subagent-"))
BULK = "the-bulk-only-the-subagent-should-see"
(TREE / "note.txt").write_text((BULK + "\n") * 20)
SUMMARY = "SUBAGENT-SUMMARY-OK"


class Stub(http.server.BaseHTTPRequestHandler):
    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/tags"):
            self._json({"models": [{"name": "stub:latest"}]})
        elif self.path.startswith("/api/ps"):
            self._json({"models": []})
        else:
            self.send_error(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        if not self.path.startswith("/api/chat"):
            self._json({})
            return
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}
        BODIES.append(body)
        # A subagent's request is the non-streaming one, and it answers with a
        # single JSON object rather than NDJSON.
        if not body.get("stream"):
            if any(m.get("role") == "tool" for m in body.get("messages", [])):
                self._json({"message": {"content": SUMMARY}, "done": True})
            else:
                self._json({"message": {"content": "reading it.", "tool_calls": [
                    {"function": {"name": "read_file",
                                  "arguments": {"path": str(TREE / "note.txt")}}}]},
                    "done": True})
            return
        # The main agent: spawn once, then answer.
        if len([b for b in BODIES if b.get("stream")]) == 1:
            frames = [{"message": {"content": "delegating.", "tool_calls": [
                {"function": {"name": "spawn_agent",
                              "arguments": {"agent": "explorer",
                                            "task": "read note.txt and report",
                                            "context": "it is in " + str(TREE)}}}]},
                "done": False},
                {"done": True, "done_reason": "stop"}]
        else:
            frames = [{"message": {"content": "the agent says it is fine."}},
                      {"done": True, "done_reason": "stop"}]
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for f in frames:
            self.wfile.write(json.dumps(f).encode() + b"\n")
            self.wfile.flush()

    def log_message(self, *a):
        pass


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


srv = http.server.HTTPServer(("127.0.0.1", 0), Stub)
threading.Thread(target=srv.serve_forever, daemon=True).start()

env = dict(os.environ)
env["OLLAMA_HOST"] = "http://127.0.0.1:%d" % srv.server_address[1]
env["ORACLE_SEND"] = "find out what is in that file"
env["ORACLE_AGENTS"] = str(TREE / "no-such-agents-dir")   # built-ins only
env["QT_QPA_PLATFORM"] = "offscreen"
env["XDG_CURRENT_DESKTOP"] = "Hyprland"
for k in ("QT_QPA_PLATFORMTHEME", "DESK_SESSION", "WAYLAND_DISPLAY", "DISPLAY"):
    env.pop(k, None)
out = subprocess.run([sys.executable, str(APP / "main.py"), "--selftest"],
                     env=env, capture_output=True, text=True, timeout=300)
srv.shutdown()
txt = out.stdout + out.stderr
if not re.search(r"^rows: ", txt, re.M):
    print(txt[-2000:])
    print("FAILED: the harness never finished a turn")
    sys.exit(1)

check("the window still loads clean", "0 QML warning(s)" in txt)
check("four requests: spawn, two subagent rounds, then the answer",
      len(BODIES) == 4, str(len(BODIES)))
if len(BODIES) < 4:
    print("FAILED: " + ", ".join(fails or ["too few requests"]))
    sys.exit(1)

spawn_round, sub_first, sub_second, main_next = BODIES


def msgs(b):
    return b.get("messages", [])


def tool_names(b):
    return [t.get("function", {}).get("name") for t in b.get("tools", [])]


# --- the subagent is its OWN conversation ---------------------------------
check("the subagent's request does not stream", not sub_first.get("stream"))
check("it opens with its own system prompt",
      any(m.get("role") == "system" and "SUBAGENT" in str(m.get("content"))
          for m in msgs(sub_first)))
check("it carries the task and the context it was handed",
      any("read note.txt" in str(m.get("content")) and str(TREE) in str(m.get("content"))
          for m in msgs(sub_first) if m.get("role") == "user"))
check("it does NOT carry the main conversation",
      not any("find out what is in that file" in str(m.get("content"))
              for m in msgs(sub_first)))

# --- and its own, restricted tool list ------------------------------------
names = tool_names(sub_first)
check("explorer gets the read tools", "read_file" in names and "search_text" in names)
check("and NOT the write ones", "write_file" not in names, str(sorted(names)))
check("and cannot spawn another agent", "spawn_agent" not in names)
check("the MAIN agent can", "spawn_agent" in tool_names(spawn_round))

# --- it actually ran a tool -----------------------------------------------
check("its second round carries what it read",
      any(BULK in str(m.get("content")) for m in msgs(sub_second)
          if m.get("role") == "tool"))

# --- the point: only the ANSWER comes back --------------------------------
back = [m for m in msgs(main_next) if m.get("role") == "tool"]
check("the main agent gets a spawn_agent tool result", bool(back), str(len(back)))
if back:
    payload = json.loads(back[-1].get("content") or "{}")
    check("holding the subagent's answer", payload.get("result") == SUMMARY,
          str(payload)[:200])
    check("and the agent it ran", payload.get("agent") == "explorer")
# --- and the DELEGATION is visible, not folded into the file block ---------
rows = json.loads(re.search(r"^rows: (.*)$", txt, re.M).group(1))
blocks = [r.get("agents", "") for r in rows if r.get("agents")]
check("the transcript shows a block for the agent that ran", len(blocks) == 1,
      str(len(blocks)))
if blocks:
    b = blocks[0]
    check("naming the agent", b.split("\n")[0] == "explorer", b.split("\n")[0])
    check("the task it was given", "task: read note.txt and report" in b)
    check("what it cost", "1 round · 1 tool call · read_file" in b)
    check("and what it answered", SUMMARY in b)
check("the main agent's own tool count does not swallow the subagent's",
      all("read_file" not in (r.get("tools") or "") for r in rows))

check("the bulk the subagent read never enters the main context",
      not any(BULK in str(m.get("content")) for m in msgs(main_next)))

# --- the definitions ------------------------------------------------------
sys.path.insert(0, str(APP))
try:
    import main as oracle_main
except ImportError as exc:
    print("skip  the definition checks (%s)" % exc)
else:
    cat = oracle_main.agent_catalog()
    check("the built-ins are always there", len(cat) >= 4)
    check("an unknown agent name falls back, never fails",
          oracle_main.agent_spec("no-such-agent")["name"] == cat[0]["name"])
    check("a tools: group resolves to its tools",
          "run_bash" in oracle_main._agent_tool_names("exec"))
    check("an unknown tool name is ignored, not fatal",
          oracle_main._agent_tool_names("read, Grep, NotebookEdit")
          == oracle_main.AGENT_TOOL_GROUPS["read"])
    check("a definition naming nothing chatter has gets the default set",
          oracle_main._agent_tool_names("Grep, Bash")
          == list(oracle_main.AGENT_TOOLS_DEFAULT))
    check("no subagent can ever be handed spawn_agent",
          "spawn_agent" not in oracle_main._tool_registry())
    check("the payload and describe_self read one list",
          "spawn_agent" in oracle_main.Ollama._offered_tool_names())
    skills = [{"name": "music-library"}, {"name": "soulseek-acquisition"}]
    check("skill names tolerate underscore-for-hyphen drift",
          oracle_main.resolve_skill_name("soulseek_acquisition", skills)
          == "soulseek-acquisition")
    remote = oracle_main.Ollama._custom_tool_argv(
        {"prog": "/tmp/tool.py", "host":
         "book" if oracle_main.LOCAL_HOST == "top" else "top"})
    check("a custom tool can declare the other host",
          remote[0] == os.environ.get("OLLAMA_SSH", "/usr/bin/ssh")
          and remote[-2] != oracle_main.LOCAL_HOST
          and remote[-1] == "/tmp/tool.py", str(remote))
    # A definition file replaces a built-in outright.
    d = Path(tempfile.mkdtemp(prefix="oracle-agentdefs-"))
    (d / "explorer.md").write_text(
        "---\ndescription: my own explorer\ntools: exec\n---\nbe terse.\n")
    (d / "brand-new.md").write_text("---\ndescription: fresh\n---\nhello.\n")
    oracle_main.AGENTS_ROOT = str(d)
    cat2 = oracle_main.agent_catalog()
    names2 = [a["name"] for a in cat2]
    check("a file of the same name replaces the built-in",
          next(a for a in cat2 if a["name"] == "explorer")["prompt"] == "be terse.")
    check("its frontmatter wins too",
          oracle_main.agent_spec("explorer", cat2)["tool_names"]
          == oracle_main.AGENT_TOOL_GROUPS["exec"])
    check("a new file becomes a new agent", "brand-new" in names2, str(names2))
    check("and it is offered by name",
          "brand-new" in (oracle_main.spawn_agent_tool(cat2)["function"]
                          ["parameters"]["properties"]["agent"]["enum"]))
    check("the system prompt names the directory to write into",
          str(d) in oracle_main.agents_note(cat2))
    librarian = cat2 + [{"name": "librarian", "description": "music"}]
    check("librarian routes Soulseek acquisition out of the main context",
          "immediately spawn `librarian`" in oracle_main.agents_note(librarian))
    routed = librarian + [
        {"name": "media-organizer", "description": "media"},
        {"name": "triage", "description": "diagnostics"},
    ]
    routing_note = oracle_main.agents_note(routed)
    check("librarian also routes YouTube and broad library work",
          "from a YouTube link" in routing_note
          and "broad music-library clean-up" in routing_note)
    check("media organization routes to its specialist with a review boundary",
          "immediately spawn `media-organizer`" in routing_note
          and "destructive move/delete/overwrite decision" in routing_note)
    check("diagnosis and codebase investigation route to compact specialists",
          "immediately spawn `triage`" in routing_note
          and "immediately spawn `explorer`" in routing_note)

print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
