#!/usr/bin/env python3
"""The first request gets obvious tool families; no Qt or backend."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from routing import request_tools


def has(prompt, *names):
    got = request_tools(prompt)
    assert set(names) <= got, (prompt, sorted(got))


def lean(prompt):
    got = request_tools(prompt)
    assert not got, (prompt, sorted(got))


has("generate an image of a rainy street", "make_image")
has("animate this picture into a short clip", "make_video")
has("show me a photo of an arctic fox", "search_images", "fetch_image")
has("what albums are in my music library?", "music_library")
has("pause the music player", "control_media")
has("what did I tell you in our previous conversation?",
    "list_sessions", "read_session")
has("pull a new ollama model", "manage_models")
has("run this fingerprint pass in the background",
    "run_job", "job_status", "job_log", "job_stop")
has("rename this file", "move_path", "delete_path", "make_dir")
lean("explain why the sky looks blue")
lean("help me think through this layout")
print("OK")
