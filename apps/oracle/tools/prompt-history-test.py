#!/usr/bin/env python3
"""Hermetic contract test for Chatter's read-only prompt-history tool."""
import json
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "prompt-history.py"


def call(claude, sessions, request):
    result = subprocess.run(["python3", str(SCRIPT), str(claude), str(sessions)],
                            input=json.dumps(request), text=True,
                            capture_output=True, check=True)
    return json.loads(result.stdout)


def main():
    with tempfile.TemporaryDirectory(prefix="chatter-prompt-history-") as tmp:
        root = Path(tmp)
        claude, sessions = root / "claude", root / "sessions"
        (claude / "project").mkdir(parents=True)
        sessions.mkdir()
        rows = [
            {"type": "user", "userType": "external", "timestamp": "2026-09-01T12:00:00Z",
             "message": {"content": "find my Nix prompt history"}},
            {"type": "user", "userType": "external", "timestamp": "2026-09-02T12:00:00Z",
             "message": {"content": "find my Nix prompt history"}},  # synced duplicate
            {"type": "user", "userType": "external", "timestamp": "2026-09-03T12:00:00Z",
             "message": {"content": "tool output"}, "isSidechain": True},
            {"type": "user", "userType": "external", "timestamp": "2026-09-03T12:00:00Z",
             "message": {"content": "/compact"}},
            {"type": "assistant", "timestamp": "2026-09-03T12:00:00Z",
             "message": {"content": "not his prompt"}},
        ]
        (claude / "project" / "one.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows), encoding="utf-8")
        session = {"id": "sess-1", "title": "history work", "turns": [
            {"isUser": True, "ts": 1788436800, "body": "analyze prompt habits\n[attached: notes.md]"},
            {"isUser": False, "ts": 1788436801, "body": "not his prompt"},
        ]}
        (sessions / "sess-1.json").write_text(json.dumps(session), encoding="utf-8")

        stats = call(claude, sessions, {"op": "stats"})
        assert stats["prompts"] == 2, stats
        assert stats["sources"] == {"chatter": 1, "claude": 1}, stats
        assert stats["characters"]["total"] == len("find my Nix prompt history") + len("analyze prompt habits"), stats
        assert any(t["term"] == "prompt" for t in stats["common_terms"]), stats

        found = call(claude, sessions, {"op": "search", "query": "prompt", "source": "all"})
        assert found["matched"] == 2 and found["returned"] == 2, found
        assert {m["source"] for m in found["matches"]} == {"claude", "chatter"}, found
        chatter = next(m for m in found["matches"] if m["source"] == "chatter")
        assert chatter["session"] == "sess-1" and "[attached:" not in chatter["excerpt"], chatter

        bounded = call(claude, sessions, {"op": "stats", "since": "2026-09-02"})
        assert bounded["prompts"] == 1 and bounded["sources"] == {"chatter": 1}, bounded
        assert "error" in call(claude, sessions, {"op": "search"})

    print("prompt-history: ok")


if __name__ == "__main__":
    main()
