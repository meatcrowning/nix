#!/usr/bin/env python3
"""chatter writing its own tools, skills and subagents — and using them.

The model can extend itself permanently [his, 2026-08-23]: `make_tool` writes a
program it can then call like a built-in, `make_skill` writes instructions a
future turn loads with use_skill, `make_agent` writes a specialist spawn_agent
can hand a job to. All three stores are read fresh every turn, so what it
writes is live on the NEXT tool call — that is the thing worth asserting, along
with the refusals that stop it installing something that cannot run.

Everything runs against TEMPORARY stores (ORACLE_TOOLS/SKILLS/AGENTS), so his
own tools, skills and agent definitions are never touched. No daemon, no model,
no window.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="oracle-selfext-"))
os.environ["ORACLE_TOOLS"] = str(TMP / "tools")
os.environ["ORACLE_SKILLS"] = str(TMP / "skills")
os.environ["ORACLE_AGENTS"] = str(TMP / "agents")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
for k in ("WAYLAND_DISPLAY", "DISPLAY"):
    os.environ.pop(k, None)

sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))
sys.argv = [sys.argv[0], "--selftest"]
import main as oracle                                                # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


# The three writers are static methods taking the parsed arguments, which is
# exactly what `_run_author_tool` hands them — no Qt, no event loop, no signals.
mk_tool = oracle.Ollama._author_tool
mk_skill = oracle.Ollama._author_skill
mk_agent = oracle.Ollama._author_agent

# ---- 1. a tool it writes is a tool it can call ---------------------------
CODE = ("import json, sys\n"
        "a = json.load(sys.stdin)\n"
        "print(json.dumps({'doubled': a.get('n', 0) * 2}))\n")
res = mk_tool("doubler", {
    "description": "Double a number.",
    "parameters": {"type": "object",
                   "properties": {"n": {"type": "number"}},
                   "required": ["n"]},
    "language": "python", "code": CODE}, False)
check("the tool is written", res.get("ok") is True, json.dumps(res)[:200])
check("...and it is LIVE, with nothing restarted", res.get("live") is True)
check("...and it appears in the catalog the payload is built from",
      "doubler" in oracle.custom_tools(),
      str(sorted(oracle.custom_tools())))
names = [t["function"]["name"] for t in oracle.custom_tool_defs()]
check("...as a function definition the model is offered", "doubler" in names,
      str(names))
if res.get("ok"):
    prog = res["program"]
    check("the program is executable", os.access(prog, os.X_OK))
    out = subprocess.run([prog], input=json.dumps({"n": 21}), text=True,
                         capture_output=True, timeout=30)
    check("and running it the way chatter does gives the answer",
          out.returncode == 0 and json.loads(out.stdout or "{}") == {"doubled": 42},
          repr(out.stdout.strip() or out.stderr.strip())[:120])

# ---- 2. what it refuses ---------------------------------------------------
bad = mk_tool("read_file", {"description": "x", "language": "python",
                            "code": "print(1)"}, False)
check("a tool cannot shadow one of the app's own", "error" in bad,
      json.dumps(bad)[:120])
bad = mk_tool("brokenpy", {"description": "x", "language": "python",
                           "code": "def (:\n"}, False)
check("a program that will not parse is never installed", "error" in bad,
      json.dumps(bad)[:120])
check("...and nothing of it is left behind",
      "brokenpy" not in oracle.custom_tools())
bad = mk_tool("nodesc", {"language": "python", "code": "print(1)"}, False)
check("a tool with no description is refused", "error" in bad)

# ---- 3. a skill it writes is a skill it can load --------------------------
res = mk_skill("tsv-report", {
    "description": "How to write the weekly TSV report he asks for.",
    "instructions": "One row per day, tab separated, no header.\n"}, False)
check("the skill is written", res.get("ok") is True, json.dumps(res)[:200])
cat = {s["name"]: s["description"] for s in oracle.skill_catalog()}
check("...and use_skill can see it", "tsv-report" in cat, str(sorted(cat)))
check("...with the description a future turn reads",
      cat.get("tsv-report", "").startswith("How to write"), repr(cat.get("tsv-report")))
tool = oracle.skill_tool()
check("...and it is in the tool's own enum",
      bool(tool) and "tsv-report" in tool["function"]["parameters"]
      ["properties"]["name"]["enum"])

# ---- 4. an agent it writes is an agent it can spawn -----------------------
res = mk_agent("tsv-writer", {
    "description": "Writes the weekly TSV report.",
    "prompt": "You write TSV. Nothing else.",
    "tools": "read, author"}, False)
check("the agent definition is written", res.get("ok") is True,
      json.dumps(res)[:200])
check("...and its tools: line resolved to real tools",
      isinstance(res.get("tools"), list) and "read_file" in res["tools"]
      and "make_tool" in res["tools"], json.dumps(res.get("tools"))[:160])
cat = {a["name"]: a for a in oracle.agent_catalog()}
check("...and spawn_agent can see it", "tsv-writer" in cat, str(sorted(cat)))
check("...beside the app's own agents", "general" in cat and "coder" in cat)

# ---- 5. deleting is the same door ----------------------------------------
check("a tool can be deleted", mk_tool("doubler", {}, True).get("ok") is True)
check("...and it is gone from the catalog",
      "doubler" not in oracle.custom_tools())
check("a skill can be deleted", mk_skill("tsv-report", {}, True).get("ok") is True)
check("an agent can be deleted", mk_agent("tsv-writer", {}, True).get("ok") is True)
check("...and the built-ins are still there",
      {"general", "coder"} <= {a["name"] for a in oracle.agent_catalog()})
check("deleting one that was never there is an honest error",
      "error" in mk_tool("neverwas", {}, True))

# ---- 6. the model is TOLD about all three --------------------------------
note = oracle.authoring_note()
check("the system prompt names every door",
      all(w in note for w in ("make_tool", "make_skill", "make_agent")))
check("...and says where they live", os.environ["ORACLE_TOOLS"] in note)
offered = {t["function"]["name"] for t in oracle.Ollama._builtin_tools()}
check("...and they are offered as tools", {"make_tool", "make_skill",
                                           "make_agent"} <= offered)
check("...to subagents too",
      {"make_tool", "make_skill", "make_agent"} <= set(oracle._tool_registry()))

for p in sorted(TMP.rglob("*"), reverse=True):
    try:
        p.unlink() if p.is_file() else p.rmdir()
    except OSError:
        pass
try:
    TMP.rmdir()
except OSError:
    pass

print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
