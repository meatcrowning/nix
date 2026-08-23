#!/usr/bin/env python3
"""control_player and file_metadata, without touching his music or his screen.

The player half runs against a STUB `playerctl` this test writes ($ORACLE_PLAYERCTL)
— it never reaches the session bus, so the player he is listening to right now
is not paused, skipped or re-shuffled by a test run (root AGENTS.md: "never
drive the running player"). The metadata half runs the REAL executor against
files this test makes in a temp directory.

    oracle-qtenv python3 tools/player-meta-test.py
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ.pop("DISPLAY", None)

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))

_TMP = Path(tempfile.mkdtemp(prefix="oracle-player-"))

from PySide6.QtCore import QTimer                            # noqa: E402
from PySide6.QtGui import QGuiApplication                    # noqa: E402

sys.argv = [sys.argv[0], "--selftest"]
import main as oracle                                        # noqa: E402

app = QGuiApplication([])
fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + extra if extra else ""))
    if not cond:
        fails.append(name)


# ---- the stub player: records its argv, answers a status line --------------
LOG = _TMP / "calls.log"
STUB = _TMP / "playerctl-stub.sh"
STUB.write_text(
    "#!/bin/sh\n"
    'printf "%s\\n" "$*" >> ' + str(LOG) + "\n"
    'case "$*" in\n'
    '  *nosuch*) echo "No players found" >&2; exit 1 ;;\n'
    '  *metadata*) printf "Playing\\tStone Age\\tMachinedrum\\tPsyconia\\t'
    '236924000\\t61000000\\t0.8\\ttrue\\tPlaylist\\n" ;;\n'
    "esac\n", encoding="utf-8")
STUB.chmod(STUB.stat().st_mode | stat.S_IEXEC)
oracle.PLAYERCTL = str(STUB)

o = oracle.Ollama()
seen = []
o.playerToolDone.connect(lambda j: seen.append(json.loads(j)))


def player(args, ms=6000):
    seen.clear()
    LOG.write_text("", encoding="utf-8")
    o._run_player_tool(args, None, None, None)
    if not seen:
        loop = QTimer()
        loop.setSingleShot(True)
        loop.timeout.connect(app.quit)
        loop.start(ms)
        o.playerToolDone.connect(app.quit)
        app.exec()
        o.playerToolDone.disconnect(app.quit)
    calls = [l for l in LOG.read_text(encoding="utf-8").splitlines() if l]
    return (seen[0] if seen else None), calls


# 1. status: one call, parsed into the shape the model reads
res, calls = player({"action": "status"})
check("status reads the player in one call",
      res is not None and res.get("ok") is True
      and res.get("title") == "Stone Age" and res.get("artist") == "Machinedrum"
      and res.get("playing") == "Playing" and res.get("volume") == 80
      and res.get("duration_seconds") == 236.9
      and res.get("position_seconds") == 61.0
      and res.get("shuffle") is True and res.get("loop") == "Playlist",
      json.dumps(res)[:200])
check("...and it is a metadata read, nothing else", len(calls) == 1, str(calls))

# 2. every verb ends in a status read, so the model reports what it produced
for action, want in (("pause", "pause"), ("play_pause", "play-pause"),
                     ("next", "next"), ("previous", "previous")):
    res, calls = player({"action": action})
    check("%s runs %r then reads back" % (action, want),
          len(calls) == 2 and calls[0].split()[-1] == want
          and res is not None and res.get("did") == action, str(calls))

# 3. seek: absolute and relative are DIFFERENT commands
res, calls = player({"action": "seek", "seconds": 90})
check("an absolute seek is `position 90`",
      calls and calls[0].endswith("position 90"), str(calls))
res, calls = player({"action": "seek", "seconds": 10, "relative": True})
check("a forward relative seek is `position 10+`",
      calls and calls[0].endswith("position 10+"), str(calls))
res, calls = player({"action": "seek", "seconds": -15, "relative": True})
check("a backward relative seek is `position 15-`",
      calls and calls[0].endswith("position 15-"), str(calls))

# 4. volume is 0-100 to the model and 0-1 on the wire, and it is clamped
res, calls = player({"action": "volume", "level": 40})
check("volume 40 goes out as 0.40", calls and calls[0].endswith("volume 0.40"),
      str(calls))
res, calls = player({"action": "volume", "level": 500})
check("...and an absurd level is clamped, not passed on",
      calls and calls[0].endswith("volume 1.00"), str(calls))

# 5. shuffle and loop
res, calls = player({"action": "shuffle", "on": False})
check("shuffle off", calls and calls[0].endswith("shuffle off"), str(calls))
res, calls = player({"action": "loop", "mode": "track"})
check("loop track", calls and calls[0].endswith("loop track"), str(calls))

# 6. an action the player cannot really do is refused, not silently dropped
res, _ = player({"action": "stop"})
check("an unoffered action is refused with a reason",
      res is not None and "unknown action" in (res.get("error") or ""),
      json.dumps(res)[:120])

# 7. no player: the honest answer, not an empty status
oracle.MPRIS_NAME = "nosuch"
res, _ = player({"action": "status"})
check("no player running is said plainly",
      res is not None and "no music player is running" in (res.get("error") or ""),
      json.dumps(res)[:160])
oracle.MPRIS_NAME = "player"

# ---- file_metadata, through the REAL executor ------------------------------
FS = str(APP / "tools" / "sandbox-fs.py")
txt = _TMP / "notes.md"
txt.write_text("one two three\nfour five\n", encoding="utf-8")


def meta(path, **extra):
    req = dict({"op": "meta", "path": str(path).lstrip("/")}, **extra)
    out = subprocess.run([sys.executable, FS, str(_TMP / "sbx"), "/"],
                         input=json.dumps(req).encode(), capture_output=True)
    return json.loads(out.stdout.decode() or "{}")


r = meta(txt)
check("a text file reports its size, type and counts",
      r.get("ok") and r.get("media_type") == "text/plain"
      and r.get("bytes") == 24 and r.get("lines") == 2 and r.get("words") == 5,
      json.dumps(r)[:200])
check("...and a timestamp a model can quote",
      len(str(r.get("modified") or "")) >= 16, str(r.get("modified")))

r = meta(txt, hash=True)
check("the sha256 is opt-in and correct",
      r.get("sha256") == __import__("hashlib").sha256(
          txt.read_bytes()).hexdigest(), str(r.get("sha256"))[:20])
check("...and absent when not asked", "sha256" not in meta(txt))

r = meta(_TMP)
check("a directory says so and counts its entries",
      r.get("kind") == "directory" and r.get("entries", 0) >= 1,
      json.dumps(r)[:160])

# A REAL media file, made here with ffmpeg when it is on this host — the media
# half is the whole reason the tool exists, so it is checked rather than assumed.
clip = _TMP / "tone.flac"
made = subprocess.run(
    ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
     "-metadata", "artist=A Test", "-metadata", "title=A Tone", "-y", str(clip)],
    capture_output=True)
if made.returncode == 0 and clip.exists():
    r = meta(clip)
    check("an audio file reports its container, duration and tags",
          r.get("media_type") == "audio/flac"
          and 1.9 <= (r.get("duration_seconds") or 0) <= 2.1
          and (r.get("tags") or {}).get("artist") == "A Test"
          and any(st.get("type") == "audio" for st in (r.get("streams") or [])),
          json.dumps(r)[:260])
else:
    print("skip  audio metadata (no ffmpeg on this host)")

r = meta("nope/not/here.txt")
check("a missing file is an error, not a crash", "error" in r, json.dumps(r)[:120])

print("\n%d checks failed" % len(fails))
sys.exit(1 if fails else 0)
