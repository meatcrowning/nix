"""Read-only access to Claude Code's own session store (Qt-free).

Claude keeps each session as ``~/.claude/projects/<slug>/<session-id>.jsonl``.
Coder lists and displays those files and resumes them with ``--resume``; it
never writes them and keeps no second copy of a transcript. Codex history goes
through its app-server (``thread/list``, ``thread/read``) instead.

``CODER_CLAUDE_PROJECTS`` points a harness at a scratch store.
"""

import json
import os
from pathlib import Path

from proto import new_item, short
from claude_proto import _text_of, tool_title

SKIP_PREFIXES = ("<local-command", "<command-name>", "<command-message>",
                 "<system-reminder>", "Caveat:", "<bash-", "[Request interrupted")


def projects_root():
    env = os.environ.get("CODER_CLAUDE_PROJECTS")
    if env:
        return Path(env)
    base = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(base) / "projects"


def _prompt_text(msg):
    content = (msg.get("message") or {}).get("content")
    text = _text_of(content) if not isinstance(content, str) else content
    return text.strip()


def scan(limit=300, head_lines=400):
    """Newest sessions first: id, cwd, title, updated (epoch seconds), path."""
    root = projects_root()
    files = []
    try:
        for d in root.iterdir():
            if not d.is_dir():
                continue
            for f in d.glob("*.jsonl"):
                try:
                    files.append((f.stat().st_mtime, f))
                except OSError:
                    pass
    except OSError:
        return []
    files.sort(reverse=True)
    out = []
    for mtime, f in files[:limit]:
        info = {"id": f.stem, "cwd": "", "title": "", "prompt": "", "updated": mtime,
                "path": str(f), "backend": "claude"}
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh):
                    if i > head_lines and info["prompt"] and info["cwd"]:
                        # titles are appended late; keep scanning only for them
                        if '"ai-title"' not in line and '"custom-title"' not in line:
                            continue
                    try:
                        o = json.loads(line)
                    except ValueError:
                        continue
                    t = o.get("type")
                    if not info["cwd"] and o.get("cwd"):
                        info["cwd"] = o["cwd"]
                    if t == "custom-title" and o.get("customTitle"):
                        info["title"] = o["customTitle"]
                        info["custom"] = True
                    elif t == "ai-title" and o.get("aiTitle") and not info.get("custom"):
                        info["title"] = o["aiTitle"]
                    elif t == "user" and not info["prompt"] and not o.get("isMeta") \
                            and not o.get("isSidechain"):
                        txt = _prompt_text(o)
                        if txt and not txt.startswith(SKIP_PREFIXES):
                            info["prompt"] = short(txt, 200)
        except OSError:
            continue
        if not info["prompt"] and not info["title"]:
            continue    # empty or command-only session
        out.append(info)
    return out


def load(path, max_items=4000):
    """A stored session as normalized items, oldest first."""
    items, tools = [], {}
    n = 0
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return []
    with fh:
        for line in fh:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("isSidechain"):
                continue
            t = o.get("type")
            if t not in ("user", "assistant"):
                continue
            m = o.get("message") or {}
            content = m.get("content")
            if t == "user":
                if o.get("isMeta"):
                    continue
                if isinstance(content, str):
                    if content.strip() and not content.startswith(SKIP_PREFIXES):
                        n += 1
                        items.append(new_item("h%d" % n, "user", text=content))
                    continue
                for c in content or []:
                    if not isinstance(c, dict):
                        continue
                    if c.get("type") == "tool_result":
                        idx = tools.get(c.get("tool_use_id", ""))
                        if idx is not None:
                            items[idx]["text"] = _text_of(c.get("content"))[-20000:]
                            items[idx]["status"] = "failed" if c.get("is_error") else "completed"
                    elif c.get("type") == "text":
                        txt = c.get("text", "")
                        if txt.strip() and not txt.startswith(SKIP_PREFIXES):
                            n += 1
                            items.append(new_item("h%d" % n, "user", text=txt))
                        elif txt.startswith("[Request interrupted"):
                            n += 1
                            items.append(new_item("h%d" % n, "notice", text="interrupted"))
            else:
                for c in content or []:
                    if not isinstance(c, dict):
                        continue
                    n += 1
                    ct = c.get("type")
                    if ct == "text" and c.get("text", "").strip():
                        items.append(new_item("h%d" % n, "assistant", text=c["text"], status="completed"))
                    elif ct == "thinking" and c.get("thinking"):
                        items.append(new_item("h%d" % n, "reasoning", text=c["thinking"], status="completed"))
                    elif ct == "tool_use":
                        inp = c.get("input") or {}
                        name = c.get("name", "tool")
                        kind = "plan" if name == "ExitPlanMode" else "tool"
                        tools[c.get("id", "")] = len(items)
                        items.append(new_item("h%d" % n, kind, title=tool_title(name, inp),
                                              text=inp.get("plan", "") if kind == "plan" else "",
                                              detail=json.dumps(inp, indent=1, ensure_ascii=False)[:4000],
                                              status="completed", meta={"name": name}))
            if len(items) > max_items:
                drop = len(items) - max_items
                items = items[drop:]
                tools = {k: v - drop for k, v in tools.items() if v >= drop}
    return items
