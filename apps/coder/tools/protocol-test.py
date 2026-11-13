#!/usr/bin/env python3
"""Qt-free protocol test: replay each fixture through the real parsers.

No process, network, display or CLI store is touched. Run:

    python3 apps/coder/tools/protocol-test.py
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))

import claude_proto  # noqa: E402
import codex_proto  # noqa: E402
import fake  # noqa: E402

FIX = APP / "fixtures"
failures = []


def check(cond, what):
    if not cond:
        failures.append(what)
        print("FAIL", what)


class Collector:
    def __init__(self):
        self.items = {}
        self.order = []
        self.events = []
        self.backend = None

    def __call__(self, ev, p):
        self.events.append((ev, p))
        if ev == "item":
            if p["id"] not in self.items:
                self.order.append(p["id"])
            self.items[p["id"]] = dict(p)
        elif ev == "item_patch":
            it = self.items.get(p["id"])
            if it is not None:
                for k, v in p.items():
                    if k == "meta_patch":
                        it.setdefault("meta", {}).update(v)
                    elif k != "id":
                        it[k] = v
        elif ev == "delta":
            it = self.items.get(p["id"])
            if it is not None:
                it[p["field"]] = it.get(p["field"], "") + p["text"]

    def kinds(self):
        return [self.items[i]["kind"] for i in self.order]

    def of(self, kind):
        return [self.items[i] for i in self.order if self.items[i]["kind"] == kind]

    def ev(self, name):
        return [p for e, p in self.events if e == name]


def run_claude(name, prompts, answer="allow", interrupt_after_items=None):
    col = Collector()
    lines = []
    rep = None

    def write(line):
        lines.append(line)
        rep.write(line)

    be = claude_proto.Claude(col, write)
    rep = fake.Replayer(fake.load(FIX / name), "claude", be.on_line)
    be.start()
    rep.start()
    for i, p in enumerate(prompts):
        be.send(p)
        for _ in range(4):
            waiting = [it for it in col.of("approval") if it["status"] == "waiting"]
            for it in waiting:
                rid = it["meta"]["request_id"]
                deny = "rm " in json.dumps(it["meta"].get("input", {}))
                be.answer(rid, "deny" if deny else answer)
        if interrupt_after_items is not None and i == len(prompts) - 1:
            pass
    return col, be, rep, lines


def test_claude_two_turns():
    col, be, rep, _ = run_claude("claude-two-turns.jsonl",
                                 ["Run the shell command: ls -la, then tell me how many files.",
                                  "Now run: rm a.txt"])
    check(be.native_id, "claude: session id from init")
    check(col.kinds()[0] == "user", "claude: first item is the prompt")
    tools = col.of("tool")
    check(any(t["title"].startswith("Bash ls") for t in tools), "claude: ls tool row titled from input")
    check(any("a.txt" in t["text"] for t in tools), "claude: tool output attached to its row")
    denied = [t for t in tools if t["status"] == "denied"]
    check(denied, "claude: auto-denied rm is marked denied")
    msgs = col.of("assistant")
    check(len(msgs) >= 2 and all(m["status"] == "completed" for m in msgs), "claude: replies completed")
    check(any("a.txt" in m["text"] for m in msgs), "claude: streamed text assembled")
    turns = col.ev("turn")
    check(len(turns) == 2 and all(t["status"] == "completed" for t in turns), "claude: two completed turns")
    caps = col.ev("caps")
    check(caps and caps[0]["models"], "claude: model list from initialize")
    usage = [u for u in col.ev("usage") if u.get("window")]
    check(usage and usage[-1]["window"] == 1000000, "claude: context window from modelUsage")
    check(col.ev("limits"), "claude: 5h window from rate_limit_event")
    check(be.state == "idle", "claude: idle after result")
    check(not rep.unexpected, "claude: replayer matched every host line %r" % rep.unexpected[:2])


def test_claude_approval():
    col, be, rep, lines = run_claude("claude-approval.jsonl",
                                     ["Create b.txt with hi, then run rm a.txt"])
    aps = col.of("approval")
    check(len(aps) == 2, "claude: two permission requests (got %d)" % len(aps))
    check(aps and aps[0]["status"] == "allowed", "claude: Write allowed")
    check(len(aps) > 1 and aps[1]["status"] == "denied", "claude: rm denied")
    sent = [json.loads(l) for l in lines]
    allows = [m for m in sent if m.get("type") == "control_response"
              and m["response"]["response"].get("behavior") == "allow"]
    check(allows and allows[0]["response"]["response"].get("updatedInput", {}).get("content") == "hi\n",
          "claude: allow carries the original input")
    tools = col.of("tool")
    check(any(t["status"] == "denied" for t in tools), "claude: tool denied in coder shows as denied")
    check(col.ev("turn")[-1]["status"] == "completed", "claude: turn completes after denial")


def test_claude_interrupt():
    col = Collector()
    rep = None
    be = claude_proto.Claude(col, lambda l: rep.write(l))
    rep = fake.Replayer(fake.load(FIX / "claude-interrupt.jsonl"), "claude", be.on_line)
    be.start()
    be.set_mode("default")
    be.set_model("haiku")
    seen = [0]
    inner = be.on_line

    def on_line(line):
        # Press stop at the first streamed text, as the user would.
        inner(line)
        if '"text_delta"' in line and not seen[0]:
            seen[0] = 1
            be.interrupt()
    rep.emit = on_line
    be.send("Write the numbers from 1 to 400 as English words, one per line.")
    turns = col.ev("turn")
    check(turns and turns[-1]["status"] == "interrupted", "claude: interrupt ends the turn as interrupted %r" % turns)
    check(col.of("notice"), "claude: interrupted notice")


def run_codex(name, prompts, deny="rm "):
    col = Collector()
    glob = []
    rep = None
    server = codex_proto.CodexServer(lambda l: rep.write(l), on_global=lambda m, p: glob.append((m, p)))
    rep = fake.Replayer(fake.load(FIX / name), "codex", server.on_line)
    be = codex_proto.Codex(col, server, cwd="/work/repo", model="gpt-test", mode="ask")
    server.start()
    rep.start()
    be.start()
    for p in prompts:
        be.send(p)
        for _ in range(4):
            for it in [i for i in col.of("approval") if i["status"] == "waiting"]:
                be.answer(it["meta"]["request_id"], "deny" if deny in it["title"] else "allow")
    return col, be, rep, glob


def test_codex_synthetic():
    col, be, rep, glob = run_codex("codex-synthetic.jsonl",
                                   ["Create a file c.txt containing the word hi, then run the shell command ls.",
                                    "Run the shell command: rm a.txt"])
    check(be.native_id == "th-0001", "codex: thread id")
    check(col.ev("caps") and col.ev("caps")[0]["models"], "codex: models published to the session")
    fc = col.of("file_change")
    check(fc and fc[0]["status"] == "completed" and "c.txt" in fc[0]["title"], "codex: file change row")
    cmds = col.of("command")
    check(len(cmds) == 2, "codex: two command rows")
    check(cmds and cmds[0]["text"].strip().endswith("c.txt") and cmds[0]["detail"] == "exit 0",
          "codex: command output and exit code")
    check(len(cmds) > 1 and cmds[1]["status"] == "declined", "codex: rm declined")
    aps = col.of("approval")
    check([a["status"] for a in aps] == ["allowed", "allowed", "denied"], "codex: approvals %r" %
          [a["status"] for a in aps])
    msgs = col.of("assistant")
    check(msgs and msgs[0]["text"].startswith("Created `c.txt`"), "codex: streamed reply")
    check(col.of("plan") and "[x] run ls" in col.of("plan")[0]["text"], "codex: plan steps")
    check(col.ev("diff"), "codex: turn diff")
    check(col.ev("usage") and col.ev("usage")[0]["window"] == 258400, "codex: context window")
    check(any(m == "account/rateLimits/updated" for m, _ in glob), "codex: rate limits are global")
    check(len(col.ev("turn")) == 2, "codex: two turns")
    check(be.state == "idle", "codex: idle at the end")
    check(not rep.unexpected, "codex: replayer matched every host line %r" % rep.unexpected[:2])


def test_codex_limit():
    col, be, rep, glob = run_codex("codex-usage-limit.jsonl",
                                   ["Create a file c.txt containing the word hi, then run the shell command ls."])
    errs = col.of("error")
    check(errs and "usage limit" in errs[0]["text"], "codex: usage-limit error shown")
    check(col.ev("turn") and col.ev("turn")[0]["status"] == "failed", "codex: failed turn")


def test_history():
    import history
    import os
    import tempfile
    d = tempfile.mkdtemp(prefix="coder-hist-")
    proj = Path(d) / "-work-repo"
    proj.mkdir()
    rows = [
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "<local-command-caveat>x"}},
        {"type": "user", "cwd": "/work/repo", "message": {"role": "user", "content": "fix the bug"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "Looking."},
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "a.txt"}]}},
        {"type": "ai-title", "aiTitle": "Bug fix"},
    ]
    (proj / "s1.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    os.environ["CODER_CLAUDE_PROJECTS"] = d
    found = history.scan()
    check(len(found) == 1 and found[0]["title"] == "Bug fix" and found[0]["cwd"] == "/work/repo"
          and found[0]["prompt"] == "fix the bug", "history: scan %r" % found)
    items = history.load(found[0]["path"]) if found else []
    check([i["kind"] for i in items] == ["user", "assistant", "tool"], "history: load kinds %r" %
          [i["kind"] for i in items])
    check(items and items[-1]["text"] == "a.txt", "history: tool result attached")


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    if failures:
        print("%d failure(s)" % len(failures))
        return 1
    print("protocol-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
