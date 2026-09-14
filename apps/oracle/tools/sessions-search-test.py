#!/usr/bin/env python3
"""Hermetic contract for bounded, verbatim past-session retrieval."""
import importlib.util
import json
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("sessions_store", HERE / "sessions-store.py")
store = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(store)

fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


with tempfile.TemporaryDirectory(prefix="chatter-session-search-") as tmp:
    root = Path(tmp)
    rows = [
        {"id": "sess-old", "title": "wallpaper notes", "updated": 10,
         "turns": [{"isUser": True, "who": "you",
                    "body": "keep the wallpaper lettering removed"}]},
        {"id": "sess-new", "title": "music", "updated": 20,
         "turns": [{"isUser": False, "who": "Sable",
                    "body": "the music library lives on aud"}]},
        {"id": "sess-current", "title": "current", "updated": 30,
         "turns": [{"isUser": True, "who": "you",
                    "body": "wallpaper current conversation"}]},
    ]
    for obj in rows:
        (root / (obj["id"] + ".json")).write_text(json.dumps(obj), encoding="utf-8")
    found = store.op_search(str(root), {"query": "wallpaper lettering",
                                        "exclude_id": "sess-current", "limit": 5})
    matches = found["matches"]
    check("search returns the matching earlier session", len(matches) == 1,
          json.dumps(matches))
    check("the excerpt is verbatim and attributable",
          matches and matches[0]["id"] == "sess-old"
          and matches[0]["turn"] == 0
          and "wallpaper lettering" in matches[0]["excerpt"], json.dumps(matches))
    check("the current session is excluded",
          all(m["id"] != "sess-current" for m in matches))

print("FAILED: " + ", ".join(fails) if fails else "OK")
raise SystemExit(1 if fails else 0)
